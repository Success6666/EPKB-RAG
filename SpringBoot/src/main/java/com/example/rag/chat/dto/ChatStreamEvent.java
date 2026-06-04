package com.example.rag.chat.dto;

import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import java.util.List;

public record ChatStreamEvent(
    String type,
    @JsonSerialize(using = ToStringSerializer.class)
    Long sessionId,
    String delta,
    String reasoning,
    String answer,
    List<ChatAskResponse.Citation> citations,
    ChatAskResponse.Trace trace,
    Integer status,
    String message
) {
    public static ChatStreamEvent session(Long sessionId) {
        return new ChatStreamEvent("session", sessionId, null, null, null, List.of(), null, null, null);
    }

    public static ChatStreamEvent delta(Long sessionId, String delta) {
        return new ChatStreamEvent("delta", sessionId, delta, null, null, List.of(), null, null, null);
    }

    public static ChatStreamEvent reasoning(Long sessionId, String reasoning) {
        return new ChatStreamEvent("reasoning", sessionId, null, reasoning, null, List.of(), null, null, null);
    }

    public static ChatStreamEvent status(Long sessionId, String message) {
        return new ChatStreamEvent("status", sessionId, null, null, null, List.of(), null, null, message);
    }

    public static ChatStreamEvent done(Long sessionId, ChatAskResponse response) {
        return new ChatStreamEvent(
            "done",
            sessionId,
            null,
            null,
            response.answer(),
            response.citations() == null ? List.of() : response.citations(),
            response.trace(),
            null,
            null
        );
    }

    public static ChatStreamEvent error(Long sessionId, String message) {
        return error(sessionId, 500, message);
    }

    public static ChatStreamEvent error(Long sessionId, int status, String message) {
        return new ChatStreamEvent("error", sessionId, null, null, null, List.of(), null, status, message);
    }
}
