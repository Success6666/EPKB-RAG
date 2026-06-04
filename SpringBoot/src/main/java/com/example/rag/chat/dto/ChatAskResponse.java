package com.example.rag.chat.dto;

import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import java.util.List;

public record ChatAskResponse(
    @JsonSerialize(using = ToStringSerializer.class)
    Long sessionId,
    String answer,
    List<Citation> citations,
    Trace trace
) {
    public record Citation(String id, String title, Integer page, Double score, String text) {
    }

    public record Trace(Integer retrievalMs, Integer rerankMs, Integer generationMs, Integer topK) {
    }
}
