package com.example.rag.model.dto;

import java.math.BigDecimal;
import java.util.List;

public record ModelListResponse(List<ModelItem> items) {
    public record ModelItem(
        String id,
        String provider,
        boolean enabled,
        String baseUrl,
        boolean apiKeyConfigured,
        BigDecimal temperature,
        BigDecimal topP,
        Integer maxTokens,
        Integer contextWindowTokens,
        String embeddingProvider,
        String embeddingModel,
        String embeddingBaseUrl,
        boolean embeddingApiKeyConfigured,
        String embeddingInputType,
        String embeddingTruncate,
        String rerankModel
    ) {
    }
}
