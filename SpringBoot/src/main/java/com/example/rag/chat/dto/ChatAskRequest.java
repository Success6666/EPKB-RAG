package com.example.rag.chat.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import java.util.List;

public record ChatAskRequest(
    @NotNull Long tenantId,
    Long sessionId,
    @NotBlank String question,
    String knowledgeBase,
    List<String> knowledgeBaseIds,
    Integer topK,
    Double temperature,
    Double topP,
    Double scoreThreshold,
    String provider,
    String model,
    String baseUrl,
    String apiKey,
    String embeddingProvider,
    String embeddingModel,
    String embeddingBaseUrl,
    String embeddingApiKey,
    String embeddingTruncate,
    String rerankModel,
    String rerankBaseUrl,
    String rerankApiKey,
    Boolean deepThinking,
    Integer contextWindowTokens,
    Integer tokenBudget,
    Boolean contextCompressed,
    String contextSummary,
    List<HistoryMessage> history,
    Object context
) {
    public record HistoryMessage(String role, String content) {
    }
}
