package com.example.rag.chat.dto;

import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import java.util.List;
import java.util.Map;

public record ChatAskResponse(
    @JsonSerialize(using = ToStringSerializer.class)
    Long sessionId,
    String answer,
    List<Citation> citations,
    Trace trace
) {
    public record Citation(
        String id,
        String title,
        String docId,
        String chunkId,
        String kbId,
        String sourceUri,
        Integer page,
        Double score,
        Double vectorScore,
        Double keywordScore,
        String text,
        Map<String, Object> metadata
    ) {
    }

    public record Trace(
        Integer retrievalMs,
        Integer rerankMs,
        Integer generationMs,
        Integer topK,
        Double scoreThreshold,
        Integer hitCount,
        Integer returnedCitationCount,
        List<String> knowledgeBaseIds,
        List<String> warnings
    ) {
    }
}
