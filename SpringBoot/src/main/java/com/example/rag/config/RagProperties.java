package com.example.rag.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "rag")
public class RagProperties {

    private Storage storage = new Storage();
    private Rabbitmq rabbitmq = new Rabbitmq();
    private Model model = new Model();
    private Retrieval retrieval = new Retrieval();
    private Chat chat = new Chat();
    private Tenant tenant = new Tenant();
    private RateLimit rateLimit = new RateLimit();
    private RagApi ragApi = new RagApi();
    private LangChain4j langchain4j = new LangChain4j();
    private Internal internal = new Internal();

    public Storage getStorage() {
        return storage;
    }

    public void setStorage(Storage storage) {
        this.storage = storage;
    }

    public Rabbitmq getRabbitmq() {
        return rabbitmq;
    }

    public void setRabbitmq(Rabbitmq rabbitmq) {
        this.rabbitmq = rabbitmq;
    }

    public Model getModel() {
        return model;
    }

    public void setModel(Model model) {
        this.model = model;
    }

    public Retrieval getRetrieval() {
        return retrieval;
    }

    public void setRetrieval(Retrieval retrieval) {
        this.retrieval = retrieval;
    }

    public Chat getChat() {
        return chat;
    }

    public void setChat(Chat chat) {
        this.chat = chat;
    }

    public Tenant getTenant() {
        return tenant;
    }

    public void setTenant(Tenant tenant) {
        this.tenant = tenant;
    }

    public RateLimit getRateLimit() {
        return rateLimit;
    }

    public void setRateLimit(RateLimit rateLimit) {
        this.rateLimit = rateLimit;
    }

    public RagApi getRagApi() {
        return ragApi;
    }

    public void setRagApi(RagApi ragApi) {
        this.ragApi = ragApi;
    }

    public LangChain4j getLangchain4j() {
        return langchain4j;
    }

    public void setLangchain4j(LangChain4j langchain4j) {
        this.langchain4j = langchain4j;
    }

    public Internal getInternal() {
        return internal;
    }

    public void setInternal(Internal internal) {
        this.internal = internal;
    }

    public static class Storage {
        private String documentRoot = "E:/AI/SpringBoot/storage/documents";

        public String getDocumentRoot() {
            return documentRoot;
        }

        public void setDocumentRoot(String documentRoot) {
            this.documentRoot = documentRoot;
        }
    }

    public static class Rabbitmq {
        private String documentExchange = "rag.document.exchange";
        private String documentRoutingKey = "rag.document.index";
        private String documentIndexQueue = "rag.document.ingest";
        private String documentDeadLetterExchange = "rag.document.dlx";
        private String documentDeadLetterRoutingKey = "rag.document.dead";
        private String documentDeadLetterQueue = "rag.document.ingest.dlq";

        public String getDocumentExchange() {
            return documentExchange;
        }

        public void setDocumentExchange(String documentExchange) {
            this.documentExchange = documentExchange;
        }

        public String getDocumentRoutingKey() {
            return documentRoutingKey;
        }

        public void setDocumentRoutingKey(String documentRoutingKey) {
            this.documentRoutingKey = documentRoutingKey;
        }

        public String getDocumentIndexQueue() {
            return documentIndexQueue;
        }

        public void setDocumentIndexQueue(String documentIndexQueue) {
            this.documentIndexQueue = documentIndexQueue;
        }

        public String getDocumentDeadLetterExchange() {
            return documentDeadLetterExchange;
        }

        public void setDocumentDeadLetterExchange(String documentDeadLetterExchange) {
            this.documentDeadLetterExchange = documentDeadLetterExchange;
        }

        public String getDocumentDeadLetterRoutingKey() {
            return documentDeadLetterRoutingKey;
        }

        public void setDocumentDeadLetterRoutingKey(String documentDeadLetterRoutingKey) {
            this.documentDeadLetterRoutingKey = documentDeadLetterRoutingKey;
        }

        public String getDocumentDeadLetterQueue() {
            return documentDeadLetterQueue;
        }

        public void setDocumentDeadLetterQueue(String documentDeadLetterQueue) {
            this.documentDeadLetterQueue = documentDeadLetterQueue;
        }
    }

    public static class Model {
        private String provider = "ollama";
        private String cloudProvider = "openai";
        private String localProvider = "ollama";
        private String ollamaBaseUrl = "http://localhost:11434";
        private String ollamaModel = "qwen2.5:7b";
        private String openAiBaseUrl = "https://api.openai.com/v1";
        private String openAiApiKey = "";
        private String openAiModel = "gpt-4o-mini";
        private String deepseekBaseUrl = "https://api.deepseek.com";
        private String deepseekApiKey = "";
        private String deepseekModel = "deepseek-v4-pro";
        private double temperature = 0.2;
        private double topP = 0.8;
        private int maxTokens = 2048;

        public String getProvider() {
            return provider;
        }

        public void setProvider(String provider) {
            this.provider = provider;
        }

        public String getCloudProvider() {
            return cloudProvider;
        }

        public void setCloudProvider(String cloudProvider) {
            this.cloudProvider = cloudProvider;
        }

        public String getLocalProvider() {
            return localProvider;
        }

        public void setLocalProvider(String localProvider) {
            this.localProvider = localProvider;
        }

        public String getOllamaBaseUrl() {
            return ollamaBaseUrl;
        }

        public void setOllamaBaseUrl(String ollamaBaseUrl) {
            this.ollamaBaseUrl = ollamaBaseUrl;
        }

        public String getOllamaModel() {
            return ollamaModel;
        }

        public void setOllamaModel(String ollamaModel) {
            this.ollamaModel = ollamaModel;
        }

        public String getOpenAiBaseUrl() {
            return openAiBaseUrl;
        }

        public void setOpenAiBaseUrl(String openAiBaseUrl) {
            this.openAiBaseUrl = openAiBaseUrl;
        }

        public String getOpenAiApiKey() {
            return openAiApiKey;
        }

        public void setOpenAiApiKey(String openAiApiKey) {
            this.openAiApiKey = openAiApiKey;
        }

        public String getOpenAiModel() {
            return openAiModel;
        }

        public void setOpenAiModel(String openAiModel) {
            this.openAiModel = openAiModel;
        }

        public String getDeepseekBaseUrl() {
            return deepseekBaseUrl;
        }

        public void setDeepseekBaseUrl(String deepseekBaseUrl) {
            this.deepseekBaseUrl = deepseekBaseUrl;
        }

        public String getDeepseekApiKey() {
            return deepseekApiKey;
        }

        public void setDeepseekApiKey(String deepseekApiKey) {
            this.deepseekApiKey = deepseekApiKey;
        }

        public String getDeepseekModel() {
            return deepseekModel;
        }

        public void setDeepseekModel(String deepseekModel) {
            this.deepseekModel = deepseekModel;
        }

        public double getTemperature() {
            return temperature;
        }

        public void setTemperature(double temperature) {
            this.temperature = temperature;
        }

        public double getTopP() {
            return topP;
        }

        public void setTopP(double topP) {
            this.topP = topP;
        }

        public int getMaxTokens() {
            return maxTokens;
        }

        public void setMaxTokens(int maxTokens) {
            this.maxTokens = maxTokens;
        }
    }

    public static class Retrieval {
        private int defaultTopK = 5;
        private String defaultMode = "hybrid";

        public int getDefaultTopK() {
            return defaultTopK;
        }

        public void setDefaultTopK(int defaultTopK) {
            this.defaultTopK = defaultTopK;
        }

        public String getDefaultMode() {
            return defaultMode;
        }

        public void setDefaultMode(String defaultMode) {
            this.defaultMode = defaultMode;
        }
    }

    public static class Chat {
        private int contextWindowTokens = 262144;
        private int compressionTriggerTokens = 200000;
        private int retrievalReserveTokens = 16000;
        private int summaryReserveTokens = 12000;

        public int getContextWindowTokens() {
            return contextWindowTokens;
        }

        public void setContextWindowTokens(int contextWindowTokens) {
            this.contextWindowTokens = contextWindowTokens;
        }

        public int getCompressionTriggerTokens() {
            return compressionTriggerTokens;
        }

        public void setCompressionTriggerTokens(int compressionTriggerTokens) {
            this.compressionTriggerTokens = compressionTriggerTokens;
        }

        public int getRetrievalReserveTokens() {
            return retrievalReserveTokens;
        }

        public void setRetrievalReserveTokens(int retrievalReserveTokens) {
            this.retrievalReserveTokens = retrievalReserveTokens;
        }

        public int getSummaryReserveTokens() {
            return summaryReserveTokens;
        }

        public void setSummaryReserveTokens(int summaryReserveTokens) {
            this.summaryReserveTokens = summaryReserveTokens;
        }
    }

    public static class Tenant {
        private String headerName = "X-Tenant-Id";
        private String groupHeaderName = "X-Group-Id";

        public String getHeaderName() {
            return headerName;
        }

        public void setHeaderName(String headerName) {
            this.headerName = headerName;
        }

        public String getGroupHeaderName() {
            return groupHeaderName;
        }

        public void setGroupHeaderName(String groupHeaderName) {
            this.groupHeaderName = groupHeaderName;
        }
    }

    public static class RateLimit {
        private int chatPerMinute = 30;
        private int uploadPerMinute = 20;

        public int getChatPerMinute() {
            return chatPerMinute;
        }

        public void setChatPerMinute(int chatPerMinute) {
            this.chatPerMinute = chatPerMinute;
        }

        public int getUploadPerMinute() {
            return uploadPerMinute;
        }

        public void setUploadPerMinute(int uploadPerMinute) {
            this.uploadPerMinute = uploadPerMinute;
        }
    }

    public static class RagApi {
        private String baseUrl = "http://localhost:8000";

        public String getBaseUrl() {
            return baseUrl;
        }

        public void setBaseUrl(String baseUrl) {
            this.baseUrl = baseUrl;
        }
    }

    public static class LangChain4j {
        private boolean enabled = true;
        private String provider = "ollama";
        private String baseUrl = "";
        private String apiKey = "";
        private String openaiBaseUrl = "https://api.openai.com/v1";
        private String openaiModel = "gpt-4o-mini";
        private String deepseekBaseUrl = "https://api.deepseek.com";
        private String deepseekApiKey = "";
        private String deepseekModel = "deepseek-v4-pro";
        private String ollamaBaseUrl = "http://localhost:11434";
        private String ollamaModel = "qwen2.5:7b";
        private java.time.Duration timeout = java.time.Duration.ofSeconds(120);
        private int maxRetries = 1;

        public boolean isEnabled() {
            return enabled;
        }

        public void setEnabled(boolean enabled) {
            this.enabled = enabled;
        }

        public String getProvider() {
            return provider;
        }

        public void setProvider(String provider) {
            this.provider = provider;
        }

        public String getBaseUrl() {
            return baseUrl;
        }

        public void setBaseUrl(String baseUrl) {
            this.baseUrl = baseUrl;
        }

        public String getApiKey() {
            return apiKey;
        }

        public void setApiKey(String apiKey) {
            this.apiKey = apiKey;
        }

        public String getOpenaiBaseUrl() {
            return openaiBaseUrl;
        }

        public void setOpenaiBaseUrl(String openaiBaseUrl) {
            this.openaiBaseUrl = openaiBaseUrl;
        }

        public String getOpenaiModel() {
            return openaiModel;
        }

        public void setOpenaiModel(String openaiModel) {
            this.openaiModel = openaiModel;
        }

        public String getDeepseekBaseUrl() {
            return deepseekBaseUrl;
        }

        public void setDeepseekBaseUrl(String deepseekBaseUrl) {
            this.deepseekBaseUrl = deepseekBaseUrl;
        }

        public String getDeepseekApiKey() {
            return deepseekApiKey;
        }

        public void setDeepseekApiKey(String deepseekApiKey) {
            this.deepseekApiKey = deepseekApiKey;
        }

        public String getDeepseekModel() {
            return deepseekModel;
        }

        public void setDeepseekModel(String deepseekModel) {
            this.deepseekModel = deepseekModel;
        }

        public String getOllamaBaseUrl() {
            return ollamaBaseUrl;
        }

        public void setOllamaBaseUrl(String ollamaBaseUrl) {
            this.ollamaBaseUrl = ollamaBaseUrl;
        }

        public String getOllamaModel() {
            return ollamaModel;
        }

        public void setOllamaModel(String ollamaModel) {
            this.ollamaModel = ollamaModel;
        }

        public java.time.Duration getTimeout() {
            return timeout;
        }

        public void setTimeout(java.time.Duration timeout) {
            this.timeout = timeout;
        }

        public int getMaxRetries() {
            return maxRetries;
        }

        public void setMaxRetries(int maxRetries) {
            this.maxRetries = maxRetries;
        }
    }

    public static class Internal {
        private String callbackToken = "";

        public String getCallbackToken() {
            return callbackToken;
        }

        public void setCallbackToken(String callbackToken) {
            this.callbackToken = callbackToken;
        }
    }
}
