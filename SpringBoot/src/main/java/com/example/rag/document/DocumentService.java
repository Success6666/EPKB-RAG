package com.example.rag.document;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.example.rag.common.exception.BizException;
import com.example.rag.config.RagProperties;
import com.example.rag.document.dto.TaskListResponse;
import com.example.rag.document.dto.DocumentStatusCallbackRequest;
import com.example.rag.document.dto.UploadTaskResponse;
import com.example.rag.document.mapper.DocumentFileMapper;
import com.example.rag.document.mapper.KnowledgeBaseMapper;
import com.example.rag.model.ModelConfig;
import com.example.rag.model.mapper.ModelConfigMapper;
import com.example.rag.mq.DocumentIndexMessage;
import com.example.rag.mq.DocumentIndexProducer;
import com.example.rag.ratelimit.RedisRateLimiter;
import com.example.rag.security.SecurityConstants;
import com.example.rag.tenant.TenantContext;
import com.example.rag.user.UserAccount;
import com.example.rag.user.mapper.UserAccountMapper;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.client.RestClientException;

@Service
public class DocumentService {

    private static final Logger log = LoggerFactory.getLogger(DocumentService.class);
    private static final DateTimeFormatter DISPLAY_TIME = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private final KnowledgeBaseMapper knowledgeBaseMapper;
    private final DocumentFileMapper documentFileMapper;
    private final DocumentIndexProducer documentIndexProducer;
    private final DocumentRagClient documentRagClient;
    private final RagProperties ragProperties;
    private final RedisRateLimiter redisRateLimiter;
    private final ModelConfigMapper modelConfigMapper;
    private final UserAccountMapper userAccountMapper;

    public DocumentService(
        KnowledgeBaseMapper knowledgeBaseMapper,
        DocumentFileMapper documentFileMapper,
        DocumentIndexProducer documentIndexProducer,
        DocumentRagClient documentRagClient,
        RagProperties ragProperties,
        RedisRateLimiter redisRateLimiter,
        ModelConfigMapper modelConfigMapper,
        UserAccountMapper userAccountMapper
    ) {
        this.knowledgeBaseMapper = knowledgeBaseMapper;
        this.documentFileMapper = documentFileMapper;
        this.documentIndexProducer = documentIndexProducer;
        this.documentRagClient = documentRagClient;
        this.ragProperties = ragProperties;
        this.redisRateLimiter = redisRateLimiter;
        this.modelConfigMapper = modelConfigMapper;
        this.userAccountMapper = userAccountMapper;
    }

    @Transactional
    public UploadTaskResponse upload(MultipartFile file, String knowledgeBaseName, String tags) {
        Long tenantId = TenantContext.tenantId();
        redisRateLimiter.check("rate:upload:" + tenantId, ragProperties.getRateLimit().getUploadPerMinute(), Duration.ofMinutes(1));
        if (file.isEmpty()) {
            throw new BizException(400, "Uploaded file is empty.");
        }
        String originalFilename = StringUtils.cleanPath(file.getOriginalFilename() == null ? "document.txt" : file.getOriginalFilename());
        assertSupportedFile(originalFilename);

        KnowledgeBase knowledgeBase = findOrCreateKnowledgeBase(tenantId, TenantContext.groupId(), knowledgeBaseName);
        Path target = saveFile(file, tenantId, knowledgeBase.getId(), originalFilename);

        LocalDateTime now = LocalDateTime.now();
        DocumentFile document = new DocumentFile();
        document.setTenantId(tenantId);
        document.setGroupId(TenantContext.groupId());
        document.setKnowledgeBaseId(knowledgeBase.getId());
        document.setFileName(originalFilename);
        document.setContentType(file.getContentType());
        document.setFileSize(file.getSize());
        document.setStoragePath(target.toString());
        document.setStatus("queued");
        document.setChunkCount(0);
        document.setCreatedAt(now);
        document.setUpdatedAt(now);
        document.setDeleted(0);
        documentFileMapper.insert(document);

        ModelConfig modelConfig = resolveModelConfig(tenantId);
        String embeddingProvider = firstText(modelConfig == null ? null : modelConfig.getEmbeddingProvider(), "NVIDIA");
        String embeddingModel = firstText(modelConfig == null ? null : modelConfig.getEmbeddingModel(), defaultEmbeddingModel(embeddingProvider));
        String embeddingBaseUrl = normalizeEmbeddingBaseUrl(
            embeddingProvider,
            trimToNull(modelConfig == null ? null : modelConfig.getEmbeddingBaseUrl())
        );
        String embeddingApiKey = trimToNull(modelConfig == null ? null : modelConfig.getEmbeddingApiKey());
        String embeddingTruncate = firstText(modelConfig == null ? null : modelConfig.getEmbeddingTruncate(), "NONE");
        log.info(
            "Resolved document indexing embedding route tenantId={} provider={} model={} baseUrl={} apiKeyConfigured={}",
            tenantId,
            embeddingProvider,
            embeddingModel,
            embeddingBaseUrl,
            StringUtils.hasText(embeddingApiKey)
        );

        documentIndexProducer.send(new DocumentIndexMessage(
            String.valueOf(tenantId),
            String.valueOf(knowledgeBase.getId()),
            String.valueOf(document.getId()),
            target.toString(),
            originalFilename,
            target.toUri().toString(),
            embeddingProvider,
            embeddingModel,
            embeddingBaseUrl,
            embeddingApiKey,
            embeddingTruncate,
            Map.of("tags", tags == null ? "" : tags, "knowledge_base", knowledgeBase.getName())
        ));

        return toTaskResponse(document, knowledgeBase);
    }

    public TaskListResponse listTasks(Long tenantId) {
        Long effectiveTenantId = tenantId == null ? TenantContext.tenantId() : tenantId;
        if (!TenantContext.tenantId().equals(effectiveTenantId)) {
            throw new BizException(403, "Cannot read another tenant's tasks.");
        }
        List<DocumentFile> documents = documentFileMapper.selectList(new LambdaQueryWrapper<DocumentFile>()
            .eq(DocumentFile::getTenantId, effectiveTenantId)
            .eq(DocumentFile::getDeleted, 0)
            .orderByDesc(DocumentFile::getCreatedAt)
            .last("limit 100"));
        List<UploadTaskResponse> items = documents.stream()
            .map(doc -> toTaskResponse(doc, knowledgeBaseMapper.selectById(doc.getKnowledgeBaseId())))
            .toList();
        return new TaskListResponse(items);
    }

    @Transactional
    public void deleteDocument(Long documentId) {
        Long tenantId = TenantContext.tenantId();
        DocumentFile document = documentFileMapper.selectOne(new LambdaQueryWrapper<DocumentFile>()
            .eq(DocumentFile::getId, documentId)
            .eq(DocumentFile::getTenantId, tenantId)
            .eq(DocumentFile::getDeleted, 0)
            .last("limit 1"));
        if (document == null) {
            throw new BizException(404, "Document not found.");
        }

        documentFileMapper.update(null, new LambdaUpdateWrapper<DocumentFile>()
            .eq(DocumentFile::getId, document.getId())
            .eq(DocumentFile::getTenantId, tenantId)
            .eq(DocumentFile::getDeleted, 0)
            .set(DocumentFile::getStatus, "deleted")
            .set(DocumentFile::getUpdatedAt, LocalDateTime.now())
            .set(DocumentFile::getDeleted, 1));
        deleteStoredFile(document.getStoragePath());
        CompletableFuture.runAsync(() -> deleteRagIndexBestEffort(
            document.getTenantId(),
            document.getKnowledgeBaseId(),
            document.getId()
        ));
    }

    @Transactional
    public void updateStatusFromWorker(DocumentStatusCallbackRequest request) {
        DocumentFile document = documentFileMapper.selectOne(new LambdaQueryWrapper<DocumentFile>()
            .eq(DocumentFile::getId, request.docId())
            .eq(DocumentFile::getTenantId, request.tenantId())
            .eq(DocumentFile::getDeleted, 0)
            .last("limit 1"));
        if (document == null) {
            throw new BizException(404, "Document task not found.");
        }
        document.setStatus(normalizeStatus(request.status()));
        if (request.chunkCount() != null) {
            document.setChunkCount(request.chunkCount());
        }
        document.setErrorMessage(StringUtils.hasText(request.errorMessage()) ? request.errorMessage() : null);
        document.setUpdatedAt(LocalDateTime.now());
        documentFileMapper.updateById(document);
    }

    private KnowledgeBase findOrCreateKnowledgeBase(Long tenantId, Long groupId, String name) {
        String kbName = StringUtils.hasText(name) ? name : "default";
        KnowledgeBase existing = knowledgeBaseMapper.selectOne(new LambdaQueryWrapper<KnowledgeBase>()
            .eq(KnowledgeBase::getTenantId, tenantId)
            .eq(KnowledgeBase::getName, kbName)
            .last("limit 1"));
        if (existing != null) {
            return existing;
        }
        LocalDateTime now = LocalDateTime.now();
        KnowledgeBase kb = new KnowledgeBase();
        kb.setTenantId(tenantId);
        kb.setGroupId(groupId);
        kb.setName(kbName);
        kb.setDescription("");
        kb.setVisibility(0);
        kb.setCreatedAt(now);
        kb.setUpdatedAt(now);
        kb.setDeleted(0);
        knowledgeBaseMapper.insert(kb);
        return kb;
    }

    private ModelConfig resolveModelConfig(Long tenantId) {
        ModelConfig tenantConfig = selectEnabledModelConfig(tenantId);
        if (tenantConfig != null) {
            return tenantConfig;
        }
        Long platformTenantId = resolvePlatformAdminTenantId();
        ModelConfig platformConfig = selectEnabledModelConfig(platformTenantId);
        if (platformConfig != null) {
            log.info(
                "Using platform admin embedding config for document indexing tenantId={} sourceTenantId={} provider={} model={} embeddingApiKeyConfigured={}",
                tenantId,
                platformConfig.getTenantId(),
                platformConfig.getEmbeddingProvider(),
                platformConfig.getEmbeddingModel(),
                StringUtils.hasText(platformConfig.getEmbeddingApiKey())
            );
        }
        return platformConfig;
    }

    private ModelConfig selectEnabledModelConfig(Long tenantId) {
        if (tenantId == null) {
            return null;
        }
        return modelConfigMapper.selectOne(new LambdaQueryWrapper<ModelConfig>()
            .eq(ModelConfig::getTenantId, tenantId)
            .eq(ModelConfig::getEnabled, 1)
            .eq(ModelConfig::getDeleted, 0)
            .last("limit 1"));
    }

    private Long resolvePlatformAdminTenantId() {
        UserAccount platformAdmin = userAccountMapper.selectOne(new LambdaQueryWrapper<UserAccount>()
            .eq(UserAccount::getRole, SecurityConstants.GLOBAL_PLATFORM_ADMIN)
            .eq(UserAccount::getStatus, 1)
            .eq(UserAccount::getDeleted, 0)
            .orderByAsc(UserAccount::getId)
            .last("limit 1"));
        return platformAdmin == null ? null : platformAdmin.getTenantId();
    }

    private Path saveFile(MultipartFile file, Long tenantId, Long kbId, String originalFilename) {
        try {
            Path dir = Path.of(ragProperties.getStorage().getDocumentRoot(), String.valueOf(tenantId), String.valueOf(kbId));
            Files.createDirectories(dir);
            Path target = dir.resolve(UUID.randomUUID() + "_" + originalFilename).normalize();
            if (!target.startsWith(dir)) {
                throw new BizException(400, "Invalid file name.");
            }
            file.transferTo(target);
            return target;
        } catch (IOException ex) {
            throw new BizException(500, "Failed to store uploaded file: " + ex.getMessage());
        }
    }

    private void deleteStoredFile(String storagePath) {
        if (!StringUtils.hasText(storagePath)) {
            return;
        }
        try {
            Path root = Path.of(ragProperties.getStorage().getDocumentRoot()).toAbsolutePath().normalize();
            Path target = Path.of(storagePath).toAbsolutePath().normalize();
            if (!target.startsWith(root)) {
                log.warn("Skipped deleting document file outside storage root: {}", storagePath);
                return;
            }
            Files.deleteIfExists(target);
        } catch (IOException ex) {
            log.warn("Failed to delete stored file {}: {}", storagePath, ex.getMessage());
        }
    }

    private void deleteRagIndexBestEffort(Long tenantId, Long knowledgeBaseId, Long documentId) {
        try {
            documentRagClient.deleteDocument(tenantId, knowledgeBaseId, documentId);
        } catch (RestClientException ex) {
            log.warn(
                "FastAPI document index cleanup failed tenantId={} knowledgeBaseId={} documentId={}: {}",
                tenantId,
                knowledgeBaseId,
                documentId,
                ex.getMessage()
            );
        }
    }

    private void assertSupportedFile(String filename) {
        String lower = filename.toLowerCase();
        if (!(lower.endsWith(".pdf")
            || lower.endsWith(".doc")
            || lower.endsWith(".docx")
            || lower.endsWith(".txt")
            || lower.endsWith(".md")
            || lower.endsWith(".csv")
            || lower.endsWith(".xls")
            || lower.endsWith(".xlsx"))) {
            throw new BizException(400, "Only PDF, Word, TXT, Markdown, CSV, and Excel files are supported.");
        }
    }

    private String normalizeStatus(String status) {
        String normalized = status == null ? "" : status.trim().toLowerCase();
        Set<String> allowed = Set.of("queued", "running", "success", "failed");
        if (!allowed.contains(normalized)) {
            throw new BizException(400, "Unsupported document status: " + status);
        }
        return normalized;
    }

    private String trimToNull(String value) {
        return StringUtils.hasText(value) ? value.trim() : null;
    }

    private String firstText(String value, String fallback) {
        return StringUtils.hasText(value) ? value.trim() : fallback;
    }

    private String defaultEmbeddingModel(String embeddingProvider) {
        String normalized = embeddingProvider == null ? "" : embeddingProvider.trim().toLowerCase();
        if ("ollama".equals(normalized) || "local".equals(normalized)) {
            return "bge-m3";
        }
        return "nvidia/nv-embedqa-e5-v5";
    }

    private String normalizeEmbeddingBaseUrl(String embeddingProvider, String embeddingBaseUrl) {
        String normalized = embeddingProvider == null ? "" : embeddingProvider.trim().toLowerCase();
        if ("sentence-transformers".equals(normalized) || "sentence_transformers".equals(normalized) || "st".equals(normalized)) {
            return null;
        }
        return embeddingBaseUrl;
    }

    private UploadTaskResponse toTaskResponse(DocumentFile document, KnowledgeBase knowledgeBase) {
        int progress = switch (document.getStatus()) {
            case "success" -> 100;
            case "failed" -> 100;
            case "running" -> 50;
            default -> 0;
        };
        return new UploadTaskResponse(
            "job-" + document.getId(),
            String.valueOf(document.getId()),
            document.getFileName(),
            knowledgeBase == null ? String.valueOf(document.getKnowledgeBaseId()) : knowledgeBase.getName(),
            document.getStatus(),
            progress,
            document.getChunkCount() == null ? 0 : document.getChunkCount(),
            document.getUpdatedAt() == null ? "" : DISPLAY_TIME.format(document.getUpdatedAt()),
            document.getErrorMessage()
        );
    }
}
