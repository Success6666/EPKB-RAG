package com.example.rag.chat;

import cn.dev33.satoken.stp.StpUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.core.toolkit.IdWorker;
import com.example.rag.chat.ChatContextService.ContextPackage;
import com.example.rag.chat.dto.ChatAskRequest;
import com.example.rag.chat.dto.ChatAskResponse;
import com.example.rag.chat.dto.ChatHistoryResponse;
import com.example.rag.chat.dto.ChatMessageListResponse;
import com.example.rag.chat.dto.ChatStreamEvent;
import com.example.rag.common.exception.BizException;
import com.example.rag.config.RagProperties;
import com.example.rag.document.KnowledgeBase;
import com.example.rag.document.mapper.KnowledgeBaseMapper;
import com.example.rag.model.ModelConfig;
import com.example.rag.model.mapper.ModelConfigMapper;
import com.example.rag.ratelimit.RedisRateLimiter;
import com.example.rag.security.SecurityConstants;
import com.example.rag.tenant.TenantContext;
import com.example.rag.user.UserAccount;
import com.example.rag.user.mapper.UserAccountMapper;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigDecimal;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executor;
import java.util.concurrent.atomic.AtomicBoolean;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;
import org.springframework.web.client.RestClientException;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import com.example.rag.chat.mapper.ChatMessageMapper;
import com.example.rag.chat.mapper.ChatSessionMapper;

@Service
public class ChatService {

    private static final Logger log = LoggerFactory.getLogger(ChatService.class);

    private final RagApiClient ragApiClient;
    private final ChatSessionMapper chatSessionMapper;
    private final ChatMessageMapper chatMessageMapper;
    private final ChatContextService chatContextService;
    private final RedisRateLimiter redisRateLimiter;
    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;
    private final RagProperties ragProperties;
    private final ModelConfigMapper modelConfigMapper;
    private final UserAccountMapper userAccountMapper;
    private final KnowledgeBaseMapper knowledgeBaseMapper;
    private final Executor chatStreamExecutor;

    public ChatService(
        RagApiClient ragApiClient,
        ChatSessionMapper chatSessionMapper,
        ChatMessageMapper chatMessageMapper,
        ChatContextService chatContextService,
        RedisRateLimiter redisRateLimiter,
        StringRedisTemplate redisTemplate,
        ObjectMapper objectMapper,
        RagProperties ragProperties,
        ModelConfigMapper modelConfigMapper,
        UserAccountMapper userAccountMapper,
        KnowledgeBaseMapper knowledgeBaseMapper,
        @Qualifier("chatStreamExecutor") Executor chatStreamExecutor
    ) {
        this.ragApiClient = ragApiClient;
        this.chatSessionMapper = chatSessionMapper;
        this.chatMessageMapper = chatMessageMapper;
        this.chatContextService = chatContextService;
        this.redisRateLimiter = redisRateLimiter;
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
        this.ragProperties = ragProperties;
        this.modelConfigMapper = modelConfigMapper;
        this.userAccountMapper = userAccountMapper;
        this.knowledgeBaseMapper = knowledgeBaseMapper;
        this.chatStreamExecutor = chatStreamExecutor;
    }

    public ChatHistoryResponse listHistory(int page, int size) {
        Long tenantId = TenantContext.tenantId();
        Long userId = StpUtil.getLoginIdAsLong();
        int safePage = Math.max(page, 1);
        int safeSize = Math.min(Math.max(size, 1), 100);
        long total = chatSessionMapper.selectCount(new LambdaQueryWrapper<ChatSession>()
            .eq(ChatSession::getTenantId, tenantId)
            .eq(ChatSession::getUserId, userId)
            .eq(ChatSession::getDeleted, 0));
        List<ChatSession> records = chatSessionMapper.selectList(new LambdaQueryWrapper<ChatSession>()
            .eq(ChatSession::getTenantId, tenantId)
            .eq(ChatSession::getUserId, userId)
            .eq(ChatSession::getDeleted, 0)
            .orderByDesc(ChatSession::getUpdatedAt)
            .last("limit " + safeSize + " offset " + ((safePage - 1) * safeSize)));
        return new ChatHistoryResponse(
            records.stream()
                .map(session -> new ChatHistoryResponse.Item(
                    session.getId(),
                    session.getTitle(),
                    session.getCreatedAt(),
                    session.getUpdatedAt()
                ))
                .toList(),
            total,
            safePage,
            safeSize
        );
    }

    public ChatMessageListResponse listMessages(Long sessionId, int page, int size) {
        Long tenantId = TenantContext.tenantId();
        Long userId = StpUtil.getLoginIdAsLong();
        if (sessionId != null) {
            requireSession(tenantId, userId, sessionId);
        }
        int safePage = Math.max(page, 1);
        int safeSize = Math.min(Math.max(size, 1), 200);
        long total = chatMessageMapper.countByTenantUserAndSession(tenantId, userId, sessionId);
        List<ChatMessage> records = chatMessageMapper.pageByTenantUserAndSession(
            tenantId,
            userId,
            sessionId,
            safeSize,
            (safePage - 1) * safeSize
        );
        return new ChatMessageListResponse(
            records.stream()
                .map(message -> new ChatMessageListResponse.Item(
                    message.getId(),
                    message.getSessionId(),
                    message.getRole(),
                    message.getContent(),
                    message.getCitationsJson(),
                    message.getCreatedAt()
                ))
                .toList(),
            total,
            safePage,
            safeSize
        );
    }

    @Transactional
    public void deleteSession(Long sessionId) {
        Long tenantId = TenantContext.tenantId();
        Long userId = StpUtil.getLoginIdAsLong();
        requireSession(tenantId, userId, sessionId);
        LocalDateTime now = LocalDateTime.now();
        chatSessionMapper.update(null, new LambdaUpdateWrapper<ChatSession>()
            .eq(ChatSession::getTenantId, tenantId)
            .eq(ChatSession::getUserId, userId)
            .eq(ChatSession::getId, sessionId)
            .eq(ChatSession::getDeleted, 0)
            .set(ChatSession::getDeleted, 1)
            .set(ChatSession::getUpdatedAt, now));
        chatMessageMapper.update(null, new LambdaUpdateWrapper<ChatMessage>()
            .eq(ChatMessage::getTenantId, tenantId)
            .eq(ChatMessage::getUserId, userId)
            .eq(ChatMessage::getSessionId, sessionId)
            .eq(ChatMessage::getDeleted, 0)
            .set(ChatMessage::getDeleted, 1));
        Set<String> summaryKeys = redisTemplate.keys("chat:summary:" + tenantId + ":" + sessionId + ":*");
        if (summaryKeys != null && !summaryKeys.isEmpty()) {
            redisTemplate.delete(summaryKeys);
        }
    }

    @Transactional
    public ChatAskResponse ask(ChatAskRequest request) {
        PreparedAsk prepared = prepareAsk(request);
        ChatAskResponse cachedResponse = readCachedResponse(prepared);
        if (cachedResponse != null) {
            persistAssistantResponse(prepared, cachedResponse);
            return withSession(prepared.sessionId(), cachedResponse);
        }

        ChatAskResponse response = withSession(prepared.sessionId(), ragApiClient.ask(prepared.downstream()));
        persistAssistantResponse(prepared, response);
        cacheResponse(prepared, response);
        return response;
    }

    public SseEmitter askStream(ChatAskRequest request) {
        SseEmitter emitter = new SseEmitter(Duration.ofMinutes(5).toMillis());
        AtomicBoolean cancelled = new AtomicBoolean(false);
        RagApiClient.StreamCancellation downstreamCancellation = new RagApiClient.StreamCancellation();
        Runnable cancelStream = () -> {
            cancelled.set(true);
            downstreamCancellation.cancel();
        };
        emitter.onCompletion(cancelStream);
        emitter.onTimeout(cancelStream);
        emitter.onError(ex -> cancelStream.run());
        PreparedAsk prepared;
        try {
            prepared = prepareAsk(request);
        } catch (Exception ex) {
            sendStreamEvent(emitter, ChatStreamEvent.error(request.sessionId(), streamErrorStatus(ex), streamErrorMessage(ex)), cancelled);
            emitter.complete();
            return emitter;
        }
        if (!sendStreamEvent(emitter, ChatStreamEvent.session(prepared.sessionId()), cancelled)) {
            return emitter;
        }
        if (!sendStreamEvent(emitter, ChatStreamEvent.status(prepared.sessionId(), "模型思考中，正在准备检索知识库..."), cancelled)) {
            return emitter;
        }

        CompletableFuture.runAsync(() -> {
            try {
                if (cancelled.get()) {
                    return;
                }
                ChatAskResponse response = null;
                if (response == null) {
                    AtomicBoolean streamedAnyAnswer = new AtomicBoolean(false);
                    try {
                        response = withSession(prepared.sessionId(), ragApiClient.askStream(
                            prepared.downstream(),
                            delta -> {
                                streamedAnyAnswer.set(true);
                                sendOrCancel(emitter, ChatStreamEvent.delta(prepared.sessionId(), delta), cancelled);
                            },
                            reasoning -> {
                                sendOrCancel(emitter, ChatStreamEvent.reasoning(prepared.sessionId(), reasoning), cancelled);
                            },
                            status -> {
                                sendOrCancel(emitter, ChatStreamEvent.status(prepared.sessionId(), status), cancelled);
                            },
                            downstreamCancellation
                        ));
                    } catch (RuntimeException ex) {
                        if (streamedAnyAnswer.get()) {
                            throw ex;
                        }
                        throw ex;
                    }
                } else {
                    response = withSession(prepared.sessionId(), response);
                    streamAnswer(emitter, prepared.sessionId(), response.answer(), cancelled);
                }
                if (cancelled.get()) {
                    return;
                }
                persistAssistantResponse(prepared, response);
                cacheResponse(prepared, response);
                sendStreamEvent(emitter, ChatStreamEvent.done(prepared.sessionId(), response), cancelled);
                emitter.complete();
            } catch (StreamClosedException ex) {
                cancelStream.run();
                emitter.complete();
            } catch (Exception ex) {
                if (cancelled.get()) {
                    return;
                }
                sendStreamEvent(emitter, ChatStreamEvent.error(prepared.sessionId(), streamErrorStatus(ex), streamErrorMessage(ex)), cancelled);
                emitter.complete();
            }
        }, chatStreamExecutor);
        return emitter;
    }

    private PreparedAsk prepareAsk(ChatAskRequest request) {
        Long tenantId = TenantContext.tenantId();
        Long userId = StpUtil.getLoginIdAsLong();
        redisRateLimiter.check("rate:chat:" + tenantId + ":" + userId, ragProperties.getRateLimit().getChatPerMinute(), Duration.ofMinutes(1));
        Long sessionId = request.sessionId() == null
            ? createSession(tenantId, userId, request.question())
            : requireSession(tenantId, userId, request.sessionId()).getId();
        ModelConfig selectedModel = resolveModelConfig(tenantId, request.model());
        String provider = firstNonBlank(request.provider(), selectedModel == null ? null : selectedModel.getProvider(), defaultProvider());
        String modelName = firstNonBlank(request.model(), selectedModel == null ? null : selectedModel.getModelName(), defaultModelName(provider));
        String baseUrl = firstNonBlank(request.baseUrl(), selectedModel == null ? null : selectedModel.getBaseUrl(), defaultBaseUrl(provider));
        String apiKey = firstNonBlank(request.apiKey(), selectedModel == null ? null : selectedModel.getApiKey(), defaultApiKey(provider));
        String embeddingProvider = firstNonBlank(
            request.embeddingProvider(),
            selectedModel == null ? null : selectedModel.getEmbeddingProvider(),
            defaultEmbeddingProvider(provider)
        );
        String embeddingModel = firstNonBlank(
            request.embeddingModel(),
            selectedModel == null ? null : selectedModel.getEmbeddingModel(),
            defaultEmbeddingModel(embeddingProvider)
        );
        String embeddingBaseUrl = normalizeEmbeddingBaseUrl(
            embeddingProvider,
            firstNonBlank(request.embeddingBaseUrl(), selectedModel == null ? null : selectedModel.getEmbeddingBaseUrl())
        );
        String embeddingApiKey = firstNonBlank(request.embeddingApiKey(), selectedModel == null ? null : selectedModel.getEmbeddingApiKey());
        String embeddingTruncate = firstNonBlank(
            request.embeddingTruncate(),
            selectedModel == null ? null : selectedModel.getEmbeddingTruncate(),
            "NONE"
        );
        String rerankModel = normalizeOptionalRerankModel(firstNonBlank(
            request.rerankModel(),
            selectedModel == null ? null : selectedModel.getRerankModel()
        ));
        boolean rerankConfigured = rerankModel != null && !"none".equalsIgnoreCase(rerankModel);
        String rerankBaseUrl = rerankConfigured
            ? firstNonBlank(
                request.rerankBaseUrl(),
                isDeepSeek(provider) ? selectedModel == null ? null : selectedModel.getBaseUrl() : null,
                isDeepSeek(provider) ? defaultBaseUrl(provider) : null
            )
            : null;
        String rerankApiKey = rerankConfigured
            ? firstNonBlank(
                request.rerankApiKey(),
                isDeepSeek(provider) ? selectedModel == null ? null : selectedModel.getApiKey() : null,
                isDeepSeek(provider) ? defaultApiKey(provider) : null
            )
            : null;
        int contextWindowTokens = contextWindowTokens(request, selectedModel);
        int tokenBudget = chatContextService.historyTokenBudget(contextWindowTokens);
        ContextPackage contextPackage = chatContextService.buildContextPackage(
            request,
            tenantId,
            userId,
            sessionId,
            request.question(),
            tokenBudget,
            contextWindowTokens
        );
        List<ChatAskRequest.HistoryMessage> history = contextPackage.history();
        Double temperature = firstNonNull(request.temperature(), toDouble(selectedModel == null ? null : selectedModel.getTemperature()));
        Double topP = firstNonNull(request.topP(), toDouble(selectedModel == null ? null : selectedModel.getTopP()));
        String knowledgeBase = request.knowledgeBase() == null ? "all" : request.knowledgeBase();
        List<String> knowledgeBaseIds = resolveKnowledgeBaseIds(tenantId, knowledgeBase, request.knowledgeBaseIds());
        Integer topK = request.topK() == null ? ragProperties.getRetrieval().getDefaultTopK() : request.topK();
        Double scoreThreshold = request.scoreThreshold() == null ? 0.15 : request.scoreThreshold();
        Map<String, Object> runtimeContext = chatContextService.runtimeContext(tenantId, userId, sessionId, contextPackage);
        Boolean deepThinking = Boolean.TRUE.equals(request.deepThinking());

        saveMessage(tenantId, userId, sessionId, "user", request.question(), null);
        log.info(
            "Resolved chat model route tenantId={} sessionId={} provider={} model={} baseUrl={} apiKeyConfigured={}",
            tenantId,
            sessionId,
            provider,
            modelName,
            baseUrl,
            StringUtils.hasText(apiKey)
        );

        String cacheKey = cacheKey(
            tenantId,
            userId,
            sessionId,
            knowledgeBase,
            knowledgeBaseIds,
            topK,
            scoreThreshold,
            provider,
            modelName,
            embeddingProvider,
            embeddingModel,
            embeddingBaseUrl,
            embeddingTruncate,
            rerankModel,
            rerankBaseUrl,
            temperature,
            topP,
            deepThinking,
            request.question(),
            history,
            runtimeContext
        );

        ChatAskRequest downstream = new ChatAskRequest(
            tenantId,
            sessionId,
            request.question(),
            knowledgeBase,
            knowledgeBaseIds,
            topK,
            temperature,
            topP,
            scoreThreshold,
            provider,
            modelName,
            baseUrl,
            apiKey,
            embeddingProvider,
            embeddingModel,
            embeddingBaseUrl,
            embeddingApiKey,
            embeddingTruncate,
            rerankModel,
            rerankBaseUrl,
            rerankApiKey,
            deepThinking,
            contextWindowTokens,
            tokenBudget,
            contextPackage.compressed(),
            contextPackage.summary(),
            history,
            runtimeContext
        );
        return new PreparedAsk(tenantId, userId, sessionId, request.question(), knowledgeBase, cacheKey, deepThinking, downstream);
    }

    private ChatAskResponse readCachedResponse(PreparedAsk prepared) {
        if (prepared.deepThinking()) {
            return null;
        }
        String cached = redisTemplate.opsForValue().get(prepared.cacheKey());
        if (cached == null) {
            return null;
        }
        try {
            return objectMapper.readValue(cached, ChatAskResponse.class);
        } catch (JsonProcessingException ignored) {
            redisTemplate.delete(prepared.cacheKey());
            return null;
        }
    }

    private void persistAssistantResponse(PreparedAsk prepared, ChatAskResponse response) {
        ChatAskResponse responseWithSession = withSession(prepared.sessionId(), response);
        saveMessage(
            prepared.tenantId(),
            prepared.userId(),
            prepared.sessionId(),
            "assistant",
            responseWithSession.answer(),
            toJson(responseWithSession.citations())
        );
        touchSession(prepared.tenantId(), prepared.userId(), prepared.sessionId());
    }

    private void cacheResponse(PreparedAsk prepared, ChatAskResponse response) {
        if (prepared.deepThinking()) {
            return;
        }
        try {
            redisTemplate.opsForValue().set(prepared.cacheKey(), objectMapper.writeValueAsString(response), Duration.ofMinutes(10));
        } catch (JsonProcessingException ignored) {
            // Cache miss is acceptable; MySQL still has the durable chat record.
        }
    }

    private void streamAnswer(SseEmitter emitter, Long sessionId, String answer, AtomicBoolean cancelled) {
        String value = answer == null ? "" : answer;
        int index = 0;
        while (index < value.length() && !cancelled.get()) {
            int end = Math.min(value.length(), index + nextChunkSize(value, index));
            sendOrCancel(emitter, ChatStreamEvent.delta(sessionId, value.substring(index, end)), cancelled);
            index = end;
            sleepQuietly(18);
        }
    }

    private int nextChunkSize(String value, int index) {
        if (Character.UnicodeScript.of(value.charAt(index)) == Character.UnicodeScript.HAN) {
            return 3;
        }
        return 16;
    }

    private void sendOrCancel(SseEmitter emitter, ChatStreamEvent event, AtomicBoolean cancelled) {
        if (!sendStreamEvent(emitter, event, cancelled)) {
            throw new StreamClosedException();
        }
    }

    private boolean sendStreamEvent(SseEmitter emitter, ChatStreamEvent event, AtomicBoolean cancelled) {
        if (cancelled.get()) {
            return false;
        }
        try {
            emitter.send(SseEmitter.event()
                .name(event.type())
                .data(objectMapper.writeValueAsString(event), MediaType.APPLICATION_JSON));
            return true;
        } catch (Exception ignored) {
            cancelled.set(true);
            return false;
        }
    }

    private void sleepQuietly(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
        }
    }

    private String streamErrorMessage(Exception ex) {
        return ex.getMessage() == null ? "Streaming chat failed." : ex.getMessage();
    }

    private int streamErrorStatus(Exception ex) {
        if (ex instanceof BizException bizException) {
            return bizException.getCode();
        }
        if (ex instanceof RestClientException) {
            return 502;
        }
        return 500;
    }

    private Long createSession(Long tenantId, Long userId, String question) {
        ChatSession session = new ChatSession();
        session.setId(IdWorker.getId());
        session.setTenantId(tenantId);
        session.setUserId(userId);
        session.setTitle(question.length() > 40 ? question.substring(0, 40) : question);
        session.setCreatedAt(LocalDateTime.now());
        session.setUpdatedAt(LocalDateTime.now());
        session.setDeleted(0);
        chatSessionMapper.insert(session);
        return session.getId();
    }

    private void saveMessage(Long tenantId, Long userId, Long sessionId, String role, String content, String citationsJson) {
        ChatMessage message = new ChatMessage();
        message.setTenantId(tenantId);
        message.setSessionId(sessionId);
        message.setUserId(userId);
        message.setRole(role);
        message.setContent(content);
        message.setCitationsJson(citationsJson);
        message.setPromptTokens(0);
        message.setCompletionTokens(0);
        message.setCreatedAt(LocalDateTime.now());
        message.setDeleted(0);
        chatMessageMapper.insert(message);
    }

    private void touchSession(Long tenantId, Long userId, Long sessionId) {
        chatSessionMapper.update(null, new LambdaUpdateWrapper<ChatSession>()
            .eq(ChatSession::getTenantId, tenantId)
            .eq(ChatSession::getUserId, userId)
            .eq(ChatSession::getId, sessionId)
            .eq(ChatSession::getDeleted, 0)
            .set(ChatSession::getUpdatedAt, LocalDateTime.now()));
    }

    private ChatSession requireSession(Long tenantId, Long userId, Long sessionId) {
        ChatSession session = chatSessionMapper.selectOne(new LambdaQueryWrapper<ChatSession>()
            .eq(ChatSession::getTenantId, tenantId)
            .eq(ChatSession::getUserId, userId)
            .eq(ChatSession::getId, sessionId)
            .eq(ChatSession::getDeleted, 0)
            .last("limit 1"));
        if (session == null) {
            throw new BizException(404, "Chat session not found.");
        }
        return session;
    }

    private String toJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException ex) {
            return "[]";
        }
    }

    private String cacheKey(
        Long tenantId,
        Long userId,
        Long sessionId,
        String knowledgeBase,
        List<String> knowledgeBaseIds,
        Integer topK,
        Double scoreThreshold,
        String provider,
        String model,
        String embeddingProvider,
        String embeddingModel,
        String embeddingBaseUrl,
        String embeddingTruncate,
        String rerankModel,
        String rerankBaseUrl,
        Double temperature,
        Double topP,
        Boolean deepThinking,
        String question,
        List<ChatAskRequest.HistoryMessage> history,
        Map<String, Object> runtimeContext
    ) {
        return "faq:" + tenantId + ":"
            + Integer.toHexString(String.join("|",
                String.valueOf(userId),
                String.valueOf(sessionId),
                knowledgeBase,
                String.join(",", knowledgeBaseIds),
                String.valueOf(topK),
                String.valueOf(scoreThreshold),
                String.valueOf(provider),
                String.valueOf(model),
                String.valueOf(embeddingProvider),
                String.valueOf(embeddingModel),
                String.valueOf(embeddingBaseUrl),
                String.valueOf(embeddingTruncate),
                String.valueOf(rerankModel),
                String.valueOf(rerankBaseUrl),
                String.valueOf(temperature),
                String.valueOf(topP),
                String.valueOf(deepThinking),
                question,
                toJson(history),
                toJson(runtimeContext)
            ).hashCode());
    }

    private ModelConfig resolveModelConfig(Long tenantId, String modelName) {
        ModelConfig tenantConfig = selectModelConfig(tenantId, modelName);
        if (tenantConfig != null) {
            return tenantConfig;
        }
        ModelConfig platformConfig = resolvePlatformAdminModelConfig(modelName);
        if (platformConfig != null && !Objects.equals(platformConfig.getTenantId(), tenantId)) {
            log.info(
                "Using platform admin model config for tenantId={} sourceTenantId={} provider={} model={} apiKeyConfigured={}",
                tenantId,
                platformConfig.getTenantId(),
                platformConfig.getProvider(),
                platformConfig.getModelName(),
                StringUtils.hasText(platformConfig.getApiKey())
            );
        }
        return platformConfig;
    }

    private ModelConfig selectModelConfig(Long tenantId, String modelName) {
        if (tenantId == null) {
            return null;
        }
        LambdaQueryWrapper<ModelConfig> wrapper = new LambdaQueryWrapper<ModelConfig>()
            .eq(ModelConfig::getTenantId, tenantId)
            .eq(ModelConfig::getDeleted, 0);
        if (modelName == null || modelName.isBlank()) {
            wrapper.eq(ModelConfig::getEnabled, 1);
        } else {
            wrapper.eq(ModelConfig::getModelName, modelName);
        }
        return modelConfigMapper.selectOne(wrapper.last("limit 1"));
    }

    private ModelConfig resolvePlatformAdminModelConfig(String modelName) {
        Long platformTenantId = resolvePlatformAdminTenantId();
        if (platformTenantId == null) {
            return null;
        }
        return selectModelConfig(platformTenantId, modelName);
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

    private List<String> resolveKnowledgeBaseIds(Long tenantId, String knowledgeBase, List<String> requestedIds) {
        List<String> explicitIds = normalizeKnowledgeBaseIds(requestedIds);
        if (!explicitIds.isEmpty()) {
            return validateKnowledgeBaseIds(tenantId, explicitIds);
        }
        String value = knowledgeBase == null || knowledgeBase.isBlank() ? "all" : knowledgeBase.trim();
        if ("all".equalsIgnoreCase(value)) {
            return knowledgeBaseMapper.selectList(new LambdaQueryWrapper<KnowledgeBase>()
                    .eq(KnowledgeBase::getTenantId, tenantId)
                    .eq(KnowledgeBase::getDeleted, 0)
                    .orderByAsc(KnowledgeBase::getId))
                .stream()
                .map(kb -> String.valueOf(kb.getId()))
                .toList();
        }

        KnowledgeBase knowledgeBaseRecord = null;
        if (value.matches("\\d+")) {
            knowledgeBaseRecord = knowledgeBaseMapper.selectOne(new LambdaQueryWrapper<KnowledgeBase>()
                .eq(KnowledgeBase::getTenantId, tenantId)
                .eq(KnowledgeBase::getId, Long.valueOf(value))
                .eq(KnowledgeBase::getDeleted, 0)
                .last("limit 1"));
        }
        if (knowledgeBaseRecord == null) {
            knowledgeBaseRecord = knowledgeBaseMapper.selectOne(new LambdaQueryWrapper<KnowledgeBase>()
                .eq(KnowledgeBase::getTenantId, tenantId)
                .eq(KnowledgeBase::getName, value)
                .eq(KnowledgeBase::getDeleted, 0)
                .last("limit 1"));
        }
        if (knowledgeBaseRecord == null) {
            throw new BizException(404, "Knowledge base not found: " + value);
        }
        return List.of(String.valueOf(knowledgeBaseRecord.getId()));
    }

    private List<String> normalizeKnowledgeBaseIds(List<String> requestedIds) {
        if (requestedIds == null || requestedIds.isEmpty()) {
            return List.of();
        }
        return requestedIds.stream()
            .filter(Objects::nonNull)
            .map(String::trim)
            .filter(id -> !id.isBlank())
            .distinct()
            .toList();
    }

    private List<String> validateKnowledgeBaseIds(Long tenantId, List<String> requestedIds) {
        List<Long> ids = new ArrayList<>(requestedIds.size());
        for (String requestedId : requestedIds) {
            if (!requestedId.matches("\\d+")) {
                throw new BizException(400, "Invalid knowledge base id: " + requestedId);
            }
            ids.add(Long.valueOf(requestedId));
        }
        List<KnowledgeBase> records = knowledgeBaseMapper.selectList(new LambdaQueryWrapper<KnowledgeBase>()
            .eq(KnowledgeBase::getTenantId, tenantId)
            .eq(KnowledgeBase::getDeleted, 0)
            .in(KnowledgeBase::getId, ids));
        Set<String> validIds = new HashSet<>(records.stream()
            .map(kb -> String.valueOf(kb.getId()))
            .toList());
        if (validIds.size() != requestedIds.size() || !validIds.containsAll(requestedIds)) {
            throw new BizException(404, "One or more knowledge bases were not found in current tenant");
        }
        return requestedIds;
    }

    private Double toDouble(BigDecimal value) {
        return value == null ? null : value.doubleValue();
    }

    private Double firstNonNull(Double first, Double second) {
        return first == null ? second : first;
    }

    private String firstNonBlank(String... values) {
        if (values == null) {
            return null;
        }
        for (String value : values) {
            if (value != null && !value.isBlank()) {
                return value.trim();
            }
        }
        return null;
    }

    private String defaultProvider() {
        return firstNonBlank(ragProperties.getModel().getProvider(), "ollama");
    }

    private String defaultModelName(String provider) {
        if (isOllama(provider)) {
            return ragProperties.getModel().getOllamaModel();
        }
        if (isDeepSeek(provider)) {
            return ragProperties.getModel().getDeepseekModel();
        }
        return ragProperties.getModel().getOpenAiModel();
    }

    private String defaultBaseUrl(String provider) {
        if (isOllama(provider)) {
            return ragProperties.getModel().getOllamaBaseUrl();
        }
        if (isDeepSeek(provider)) {
            return ragProperties.getModel().getDeepseekBaseUrl();
        }
        return ragProperties.getModel().getOpenAiBaseUrl();
    }

    private String defaultApiKey(String provider) {
        if (isOllama(provider)) {
            return null;
        }
        if (isDeepSeek(provider)) {
            return ragProperties.getModel().getDeepseekApiKey();
        }
        return ragProperties.getModel().getOpenAiApiKey();
    }

    private String defaultEmbeddingProvider(String provider) {
        String normalized = provider == null ? "" : provider.trim().toLowerCase();
        if ("nvidia".equals(normalized)) {
            return "NVIDIA";
        }
        return "SentenceTransformers";
    }

    private String defaultEmbeddingModel(String embeddingProvider) {
        String normalized = embeddingProvider == null ? "" : embeddingProvider.trim().toLowerCase();
        if ("nvidia".equals(normalized)) {
            return "nvidia/nv-embedqa-e5-v5";
        }
        if ("ollama".equals(normalized) || "local".equals(normalized)) {
            return "bge-m3";
        }
        return "BAAI/bge-small-zh-v1.5";
    }

    private String normalizeEmbeddingBaseUrl(String embeddingProvider, String embeddingBaseUrl) {
        String normalized = embeddingProvider == null ? "" : embeddingProvider.trim().toLowerCase();
        if ("sentence-transformers".equals(normalized) || "sentence_transformers".equals(normalized) || "st".equals(normalized)) {
            return null;
        }
        return embeddingBaseUrl;
    }

    private String normalizeOptionalRerankModel(String rerankModel) {
        if (!StringUtils.hasText(rerankModel)) {
            return null;
        }
        String value = rerankModel.trim();
        if ("none".equalsIgnoreCase(value) || "off".equalsIgnoreCase(value) || "disabled".equalsIgnoreCase(value)) {
            return "none";
        }
        return value;
    }

    private boolean isOllama(String provider) {
        String normalized = provider == null ? "" : provider.trim().toLowerCase();
        return "ollama".equals(normalized) || "local".equals(normalized);
    }

    private boolean isDeepSeek(String provider) {
        return "deepseek".equals(provider == null ? "" : provider.trim().toLowerCase());
    }

    private int contextWindowTokens(ChatAskRequest request, ModelConfig activeModel) {
        if (request.contextWindowTokens() != null && request.contextWindowTokens() > 0) {
            return request.contextWindowTokens();
        }
        if (activeModel != null && activeModel.getContextWindowTokens() != null && activeModel.getContextWindowTokens() > 0) {
            return activeModel.getContextWindowTokens();
        }
        return ragProperties.getChat().getContextWindowTokens();
    }

    private record PreparedAsk(
        Long tenantId,
        Long userId,
        Long sessionId,
        String question,
        String knowledgeBase,
        String cacheKey,
        Boolean deepThinking,
        ChatAskRequest downstream
    ) {
    }

    private ChatAskResponse withSession(Long sessionId, ChatAskResponse response) {
        return new ChatAskResponse(sessionId, response.answer(), response.citations(), response.trace());
    }

    private static class StreamClosedException extends RuntimeException {
    }
}
