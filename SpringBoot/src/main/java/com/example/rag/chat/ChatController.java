package com.example.rag.chat;

import com.example.rag.chat.dto.ChatAskRequest;
import com.example.rag.chat.dto.ChatAskResponse;
import com.example.rag.chat.dto.ChatHistoryResponse;
import com.example.rag.chat.dto.ChatMessageListResponse;
import cn.dev33.satoken.annotation.SaCheckPermission;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@RestController
@RequestMapping("/api/chat")
public class ChatController {

    private final ChatService chatService;

    public ChatController(ChatService chatService) {
        this.chatService = chatService;
    }

    @PostMapping("/ask")
    @SaCheckPermission("chat:ask")
    public ChatAskResponse ask(@Valid @RequestBody ChatAskRequest request) {
        return chatService.ask(request);
    }

    @PostMapping(value = "/ask/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    @SaCheckPermission("chat:ask")
    public SseEmitter askStream(@Valid @RequestBody ChatAskRequest request) {
        return chatService.askStream(request);
    }

    @GetMapping("/history")
    @SaCheckPermission("chat:ask")
    public ChatHistoryResponse history(
        @RequestParam(value = "page", defaultValue = "1") @Min(1) int page,
        @RequestParam(value = "size", defaultValue = "20") @Min(1) @Max(100) int size
    ) {
        return chatService.listHistory(page, size);
    }

    @GetMapping("/messages")
    @SaCheckPermission("chat:ask")
    public ChatMessageListResponse messages(
        @RequestParam(value = "sessionId", required = false) Long sessionId,
        @RequestParam(value = "page", defaultValue = "1") @Min(1) int page,
        @RequestParam(value = "size", defaultValue = "20") @Min(1) @Max(200) int size
    ) {
        return chatService.listMessages(sessionId, page, size);
    }

    @DeleteMapping("/sessions/{sessionId}")
    @SaCheckPermission("chat:ask")
    public void deleteSession(@PathVariable Long sessionId) {
        chatService.deleteSession(sessionId);
    }
}
