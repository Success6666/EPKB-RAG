package com.example.rag.chat.dto;

import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import java.time.LocalDateTime;
import java.util.List;

public record ChatMessageListResponse(
    List<Item> items,
    long total,
    int page,
    int size
) {
    public record Item(
        @JsonSerialize(using = ToStringSerializer.class)
        Long id,
        @JsonSerialize(using = ToStringSerializer.class)
        Long sessionId,
        String role,
        String content,
        String citationsJson,
        LocalDateTime createdAt
    ) {
    }
}
