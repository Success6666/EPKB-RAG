package com.example.rag.document;

import com.example.rag.document.dto.TaskListResponse;
import com.example.rag.config.RagProperties;
import com.example.rag.common.exception.BizException;
import com.example.rag.document.dto.DocumentStatusCallbackRequest;
import com.example.rag.document.dto.KnowledgeBaseListResponse;
import com.example.rag.document.dto.UploadTaskResponse;
import cn.dev33.satoken.annotation.SaCheckPermission;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.util.StringUtils;

@RestController
@RequestMapping("/api/documents")
public class DocumentController {

    private final DocumentService documentService;
    private final RagProperties ragProperties;

    public DocumentController(DocumentService documentService, RagProperties ragProperties) {
        this.documentService = documentService;
        this.ragProperties = ragProperties;
    }

    @PostMapping("/upload")
    @SaCheckPermission("document:upload")
    public UploadTaskResponse upload(
        @RequestParam("file") MultipartFile file,
        @RequestParam(value = "knowledgeBase", defaultValue = "default") @NotBlank String knowledgeBase,
        @RequestParam(value = "tags", required = false) String tags
    ) {
        return documentService.upload(file, knowledgeBase, tags);
    }

    @GetMapping("/tasks")
    @SaCheckPermission("document:read")
    public TaskListResponse tasks(@RequestParam(value = "tenantId", required = false) Long tenantId) {
        return documentService.listTasks(tenantId);
    }

    @GetMapping("/knowledge-bases")
    @SaCheckPermission("document:read")
    public KnowledgeBaseListResponse knowledgeBases() {
        return documentService.listKnowledgeBases();
    }

    @DeleteMapping("/{documentId}")
    @SaCheckPermission("document:upload")
    public void delete(@PathVariable Long documentId) {
        documentService.deleteDocument(documentId);
    }

    @PostMapping("/internal/status")
    public void updateStatus(
        @RequestHeader(value = "X-Internal-Token", required = false) String token,
        @Valid @RequestBody DocumentStatusCallbackRequest request
    ) {
        String callbackToken = ragProperties.getInternal().getCallbackToken();
        if (!StringUtils.hasText(callbackToken) || !callbackToken.equals(token)) {
            throw new BizException(403, "Invalid internal callback token.");
        }
        documentService.updateStatusFromWorker(request);
    }
}
