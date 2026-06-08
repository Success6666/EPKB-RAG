package com.example.rag.langchain;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.example.rag.chat.dto.ChatAskRequest;
import com.example.rag.chat.dto.ChatAskResponse;
import com.example.rag.config.RagProperties;
import com.example.rag.model.ModelConfig;
import com.example.rag.model.mapper.ModelConfigMapper;
import com.example.rag.security.SecurityConstants;
import com.example.rag.user.UserAccount;
import com.example.rag.user.mapper.UserAccountMapper;
import dev.langchain4j.data.message.SystemMessage;
import dev.langchain4j.data.message.UserMessage;
import dev.langchain4j.model.chat.ChatModel;
import dev.langchain4j.model.chat.request.ChatRequest;
import dev.langchain4j.model.chat.response.ChatResponse;
import dev.langchain4j.model.ollama.OllamaChatModel;
import dev.langchain4j.model.openai.OpenAiChatModel;
import java.math.BigDecimal;
import java.time.Duration;
import java.util.List;
import java.util.Locale;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

@Service
public class LangChain4jChatService {

    private static final Logger log = LoggerFactory.getLogger(LangChain4jChatService.class);
    private static final String FALLBACK_SYSTEM_PROMPT = """
        你是企业私有知识库 RAG 中台的降级模型 Agent。当前 FastAPI 检索链路不可用，
        你没有可引用的知识库片段。请直接回答用户问题；如果问题依赖企业私有资料，
        明确说明当前无法访问知识库引用，不要编造引用、文件名或页码。
        """;

    private final RagProperties ragProperties;
    private final ModelConfigMapper modelConfigMapper;
    private final UserAccountMapper userAccountMapper;

    public LangChain4jChatService(
        RagProperties ragProperties,
        ModelConfigMapper modelConfigMapper,
        UserAccountMapper userAccountMapper
    ) {
        this.ragProperties = ragProperties;
        this.modelConfigMapper = modelConfigMapper;
        this.userAccountMapper = userAccountMapper;
    }

    public Optional<ChatAskResponse> ask(ChatAskRequest request) {
        if (!ragProperties.getLangchain4j().isEnabled()) {
            return Optional.empty();
        }
        long startedAt = System.nanoTime();
        try {
            ModelRoute route = resolveRoute(request);
            ChatModel chatModel = createChatModel(route);
            ChatResponse response = chatModel.chat(ChatRequest.builder()
                .messages(List.of(
                    SystemMessage.from(FALLBACK_SYSTEM_PROMPT),
                    UserMessage.from(fallbackUserPrompt(request))
                ))
                .temperature(route.temperature())
                .topP(route.topP())
                .maxOutputTokens(route.maxTokens())
                .build());
            int generationMs = elapsedMs(startedAt);
            String answer = response.aiMessage() == null ? "" : response.aiMessage().text();
            if (!StringUtils.hasText(answer)) {
                return Optional.empty();
            }
            return Optional.of(new ChatAskResponse(
                request.sessionId(),
                "（LangChain4j 模型降级回答，未使用知识库检索）\n\n" + answer,
                List.of(),
                new ChatAskResponse.Trace(
                    0,
                    0,
                    generationMs,
                    request.topK() == null ? 0 : request.topK(),
                    null,
                    0,
                    0,
                    List.of(),
                    List.of()
                )
            ));
        } catch (Exception ex) {
            log.warn("LangChain4j fallback chat failed: {}", ex.getMessage());
            return Optional.empty();
        }
    }

    public Optional<String> compressHistory(ChatAskRequest request, List<ChatAskRequest.HistoryMessage> history, int tokenBudget) {
        if (!ragProperties.getLangchain4j().isEnabled() || history == null || history.isEmpty() || tokenBudget <= 0) {
            return Optional.empty();
        }
        try {
            int outputTokens = Math.max(512, Math.min(tokenBudget, 4096));
            ModelRoute route = resolveRoute(request).withMaxTokens(outputTokens);
            ChatModel chatModel = createChatModel(route);
            ChatResponse response = chatModel.chat(ChatRequest.builder()
                .messages(List.of(
                    SystemMessage.from("你是企业 RAG 多轮对话的上下文压缩器。只保留对后续回答有用的用户目标、事实、约束、偏好、已完成事项和待办，不要编造。"),
                    UserMessage.from(compressionPrompt(history))
                ))
                .temperature(0.0)
                .topP(0.8)
                .maxOutputTokens(outputTokens)
                .build());
            String summary = response.aiMessage() == null ? "" : response.aiMessage().text();
            return StringUtils.hasText(summary) ? Optional.of(summary.trim()) : Optional.empty();
        } catch (Exception ex) {
            log.warn("LangChain4j history compression failed: {}", ex.getMessage());
            return Optional.empty();
        }
    }

    private ModelRoute resolveRoute(ChatAskRequest request) {
        RagProperties.LangChain4j properties = ragProperties.getLangchain4j();
        RequestedModel requestedModel = parseRequestedModel(request.model());
        ModelConfig requestedConfig = findModelConfig(request.tenantId(), requestedModel.modelName()).orElse(null);
        ModelConfig activeConfig = findActiveConfig(request.tenantId()).orElse(null);

        String provider = firstText(
            request.provider(),
            requestedModel.provider(),
            requestedConfig == null ? null : requestedConfig.getProvider(),
            activeConfig == null ? null : activeConfig.getProvider(),
            properties.getProvider(),
            ragProperties.getModel().getProvider()
        );
        String modelName = firstText(
            requestedModel.modelName(),
            requestedConfig == null ? null : requestedConfig.getModelName(),
            activeConfig == null ? null : activeConfig.getModelName(),
            defaultModelName(provider)
        );
        String baseUrl = firstText(
            request.baseUrl(),
            requestedConfig == null ? null : requestedConfig.getBaseUrl(),
            activeConfig == null ? null : activeConfig.getBaseUrl(),
            baseUrl(provider)
        );
        String apiKey = firstText(
            request.apiKey(),
            requestedConfig == null ? null : requestedConfig.getApiKey(),
            activeConfig == null ? null : activeConfig.getApiKey(),
            apiKey(provider)
        );
        Double temperature = firstDouble(
            request.temperature(),
            requestedConfig == null ? null : toDouble(requestedConfig.getTemperature()),
            activeConfig == null ? null : toDouble(activeConfig.getTemperature())
        );
        Double topP = firstDouble(
            request.topP(),
            requestedConfig == null ? null : toDouble(requestedConfig.getTopP()),
            activeConfig == null ? null : toDouble(activeConfig.getTopP())
        );
        Integer maxTokens = requestedConfig == null ? null : requestedConfig.getMaxTokens();
        if (maxTokens == null && activeConfig != null) {
            maxTokens = activeConfig.getMaxTokens();
        }

        return new ModelRoute(
            provider,
            modelName,
            baseUrl,
            apiKey,
            temperature,
            topP,
            maxTokens
        );
    }

    private Optional<ModelConfig> findActiveConfig(Long tenantId) {
        Optional<ModelConfig> tenantConfig = selectActiveConfig(tenantId);
        if (tenantConfig.isPresent()) {
            return tenantConfig;
        }
        return platformAdminTenantId()
            .filter(platformTenantId -> !platformTenantId.equals(tenantId))
            .flatMap(this::selectActiveConfig);
    }

    private Optional<ModelConfig> findModelConfig(Long tenantId, String modelName) {
        Optional<ModelConfig> tenantConfig = selectModelConfig(tenantId, modelName);
        if (tenantConfig.isPresent()) {
            return tenantConfig;
        }
        return platformAdminTenantId()
            .filter(platformTenantId -> !platformTenantId.equals(tenantId))
            .flatMap(platformTenantId -> selectModelConfig(platformTenantId, modelName));
    }

    private Optional<ModelConfig> selectActiveConfig(Long tenantId) {
        if (tenantId == null) {
            return Optional.empty();
        }
        try {
            return Optional.ofNullable(modelConfigMapper.selectOne(new LambdaQueryWrapper<ModelConfig>()
                .eq(ModelConfig::getTenantId, tenantId)
                .eq(ModelConfig::getEnabled, 1)
                .eq(ModelConfig::getDeleted, 0)
                .last("LIMIT 1")));
        } catch (Exception ex) {
            log.warn("Failed to load active model config for tenant {}: {}", tenantId, ex.getMessage());
            return Optional.empty();
        }
    }

    private Optional<ModelConfig> selectModelConfig(Long tenantId, String modelName) {
        if (tenantId == null || !StringUtils.hasText(modelName)) {
            return Optional.empty();
        }
        try {
            return Optional.ofNullable(modelConfigMapper.selectOne(new LambdaQueryWrapper<ModelConfig>()
                .eq(ModelConfig::getTenantId, tenantId)
                .eq(ModelConfig::getModelName, modelName)
                .eq(ModelConfig::getDeleted, 0)
                .last("LIMIT 1")));
        } catch (Exception ex) {
            log.warn("Failed to load model config {} for tenant {}: {}", modelName, tenantId, ex.getMessage());
            return Optional.empty();
        }
    }

    private Optional<Long> platformAdminTenantId() {
        try {
            UserAccount platformAdmin = userAccountMapper.selectOne(new LambdaQueryWrapper<UserAccount>()
                .eq(UserAccount::getRole, SecurityConstants.GLOBAL_PLATFORM_ADMIN)
                .eq(UserAccount::getStatus, 1)
                .eq(UserAccount::getDeleted, 0)
                .orderByAsc(UserAccount::getId)
                .last("LIMIT 1"));
            return platformAdmin == null ? Optional.empty() : Optional.ofNullable(platformAdmin.getTenantId());
        } catch (Exception ex) {
            log.warn("Failed to load platform admin tenant id: {}", ex.getMessage());
            return Optional.empty();
        }
    }

    private ChatModel createChatModel(ModelRoute route) {
        if (isOllama(route.provider())) {
            OllamaChatModel.OllamaChatModelBuilder builder = OllamaChatModel.builder();
            builder.baseUrl(route.baseUrl());
            builder.modelName(route.modelName());
            builder.timeout(timeout());
            builder.maxRetries(maxRetries());
            if (route.temperature() != null) {
                builder.temperature(route.temperature());
            }
            if (route.topP() != null) {
                builder.topP(route.topP());
            }
            if (route.maxTokens() != null) {
                builder.numPredict(route.maxTokens());
            }
            return builder.build();
        }

        OpenAiChatModel.OpenAiChatModelBuilder builder = OpenAiChatModel.builder();
        builder.baseUrl(route.baseUrl());
        builder.apiKey(route.apiKey());
        builder.modelName(route.modelName());
        builder.timeout(timeout());
        builder.maxRetries(maxRetries());
        if (route.temperature() != null) {
            builder.temperature(route.temperature());
        }
        if (route.topP() != null) {
            builder.topP(route.topP());
        }
        if (route.maxTokens() != null) {
            builder.maxTokens(route.maxTokens());
        }
        return builder.build();
    }

    private RequestedModel parseRequestedModel(String rawModel) {
        if (!StringUtils.hasText(rawModel)) {
            return new RequestedModel(null, null);
        }
        String value = rawModel.trim();
        for (String separator : List.of("/", ":")) {
            int index = value.indexOf(separator);
            if (index > 0 && index < value.length() - 1) {
                String prefix = value.substring(0, index);
                if (isKnownProvider(prefix)) {
                    return new RequestedModel(prefix, value.substring(index + 1));
                }
            }
        }
        return new RequestedModel(null, value);
    }

    private boolean isKnownProvider(String provider) {
        String normalized = normalize(provider);
        return normalized.equals("ollama")
            || normalized.equals("openai")
            || normalized.equals("deepseek")
            || normalized.equals("openai-compatible")
            || normalized.equals("compatible");
    }

    private String baseUrl(String provider) {
        RagProperties.LangChain4j properties = ragProperties.getLangchain4j();
        if (isOllama(provider)) {
            return firstText(properties.getBaseUrl(), properties.getOllamaBaseUrl());
        }
        if (isDeepSeek(provider)) {
            return firstText(properties.getBaseUrl(), properties.getDeepseekBaseUrl());
        }
        return firstText(properties.getBaseUrl(), properties.getOpenaiBaseUrl());
    }

    private String defaultModelName(String provider) {
        RagProperties.LangChain4j properties = ragProperties.getLangchain4j();
        if (isOllama(provider)) {
            return properties.getOllamaModel();
        }
        if (isDeepSeek(provider)) {
            return properties.getDeepseekModel();
        }
        return properties.getOpenaiModel();
    }

    private String apiKey(String provider) {
        RagProperties.LangChain4j properties = ragProperties.getLangchain4j();
        String apiKey = isDeepSeek(provider) ? firstText(properties.getApiKey(), properties.getDeepseekApiKey()) : properties.getApiKey();
        return StringUtils.hasText(apiKey) ? apiKey : "not-needed";
    }

    private boolean isOllama(String provider) {
        String normalized = normalize(provider);
        return normalized.equals("ollama") || normalized.equals("local");
    }

    private boolean isDeepSeek(String provider) {
        return normalize(provider).equals("deepseek");
    }

    private String normalize(String value) {
        return value == null ? "" : value.trim().toLowerCase(Locale.ROOT);
    }

    private Duration timeout() {
        Duration timeout = ragProperties.getLangchain4j().getTimeout();
        return timeout == null ? Duration.ofSeconds(120) : timeout;
    }

    private Integer maxRetries() {
        return Math.max(0, ragProperties.getLangchain4j().getMaxRetries());
    }

    private int elapsedMs(long startedAt) {
        return Math.toIntExact(Math.min(Duration.ofNanos(System.nanoTime() - startedAt).toMillis(), Integer.MAX_VALUE));
    }

    private Double toDouble(BigDecimal value) {
        return value == null ? null : value.doubleValue();
    }

    private String firstText(String... values) {
        for (String value : values) {
            if (StringUtils.hasText(value)) {
                return value.trim();
            }
        }
        return "";
    }

    private Double firstDouble(Double... values) {
        for (Double value : values) {
            if (value != null) {
                return value;
            }
        }
        return null;
    }

    private String fallbackUserPrompt(ChatAskRequest request) {
        StringBuilder prompt = new StringBuilder();
        prompt.append("用户问题：\n").append(request.question()).append("\n\n");
        if (request.history() != null && !request.history().isEmpty()) {
            prompt.append("最近会话历史：\n");
            request.history().forEach(message ->
                prompt.append(message.role()).append(": ").append(message.content()).append("\n")
            );
            prompt.append("\n");
        }
        if (StringUtils.hasText(request.contextSummary())) {
            prompt.append("压缩后的早期上下文摘要：\n").append(request.contextSummary()).append("\n\n");
        }
        if (request.context() != null) {
            prompt.append("运行上下文：\n").append(request.context()).append("\n\n");
        }
        prompt.append("如果问题依赖私有知识库原文，请说明当前检索链路不可用，不能伪造引用。");
        return prompt.toString();
    }

    private String compressionPrompt(List<ChatAskRequest.HistoryMessage> history) {
        StringBuilder prompt = new StringBuilder();
        prompt.append("请将以下早期对话压缩成可继续参与后续问答的上下文摘要，使用中文，控制在要点列表内：\n\n");
        for (ChatAskRequest.HistoryMessage message : history) {
            prompt.append(message.role()).append(": ").append(message.content()).append("\n");
        }
        return prompt.toString();
    }

    private record RequestedModel(String provider, String modelName) {
    }

    private record ModelRoute(
        String provider,
        String modelName,
        String baseUrl,
        String apiKey,
        Double temperature,
        Double topP,
        Integer maxTokens
    ) {
        private ModelRoute withMaxTokens(Integer nextMaxTokens) {
            return new ModelRoute(provider, modelName, baseUrl, apiKey, temperature, topP, nextMaxTokens);
        }
    }
}
