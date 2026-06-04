package com.example.rag.mq;

import java.util.Map;

public record DocumentIndexMessage(
    String tenantId,
    String kbId,
    String docId,
    String filePath,
    String fileName,
    String sourceUri,
    String embeddingProvider,
    String embeddingModel,
    String embeddingBaseUrl,
    String embeddingApiKey,
    String embeddingTruncate,
    Map<String, Object> metadata
) {
}
