package com.example.rag.chat;

import com.example.rag.chat.dto.ChatAskRequest;
import com.example.rag.chat.dto.ChatAskResponse;
import com.example.rag.chat.dto.ChatStreamEvent;
import com.example.rag.config.RagProperties;
import com.example.rag.langchain.LangChain4jChatService;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Iterator;
import java.util.List;
import java.util.function.Consumer;
import java.util.stream.Stream;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClientException;

@Component
public class RagApiClient {

    private final HttpClient httpClient;
    private final RagProperties ragProperties;
    private final LangChain4jChatService langChain4jChatService;
    private final ObjectMapper objectMapper;

    public RagApiClient(
        RagProperties ragProperties,
        LangChain4jChatService langChain4jChatService,
        ObjectMapper objectMapper
    ) {
        this.httpClient = HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)
            .connectTimeout(Duration.ofSeconds(3))
            .build();
        this.ragProperties = ragProperties;
        this.langChain4jChatService = langChain4jChatService;
        this.objectMapper = objectMapper;
    }

    public ChatAskResponse askStream(
        ChatAskRequest request,
        Consumer<String> deltaConsumer,
        Consumer<String> reasoningConsumer,
        Consumer<String> statusConsumer,
        StreamCancellation cancellation
    ) {
        String payload = toJson(request);
        HttpRequest httpRequest = HttpRequest.newBuilder()
            .uri(URI.create(ragProperties.getRagApi().getBaseUrl() + "/api/v1/rag/chat/ask/stream"))
            .version(HttpClient.Version.HTTP_1_1)
            .timeout(Duration.ofSeconds(180))
            .header("Content-Type", "application/json")
            .header("Accept", "text/event-stream")
            .POST(HttpRequest.BodyPublishers.ofString(payload, StandardCharsets.UTF_8))
            .build();
        try {
            HttpResponse<InputStream> response = httpClient.send(httpRequest, HttpResponse.BodyHandlers.ofInputStream());
            int status = response.statusCode();
            if (status < 200 || status >= 300) {
                String body = new String(response.body().readAllBytes(), StandardCharsets.UTF_8);
                throw new RestClientException("FastAPI stream returned " + status + ": " + body);
            }
            InputStream responseBody = response.body();
            if (cancellation != null) {
                cancellation.attach(responseBody);
            }
            try (
                BufferedReader reader = new BufferedReader(new InputStreamReader(responseBody, StandardCharsets.UTF_8));
                Stream<String> lines = reader.lines()
            ) {
                return readStreamResponse(lines, request, deltaConsumer, reasoningConsumer, statusConsumer, cancellation);
            }
        } catch (RestClientException ex) {
            throw ex;
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new RestClientException("Interrupted while calling FastAPI streaming chat API.", ex);
        } catch (Exception ex) {
            throw new RestClientException("Failed to call FastAPI streaming chat API.", ex);
        }
    }

    @CircuitBreaker(name = "chatModel", fallbackMethod = "fallback")
    public ChatAskResponse ask(ChatAskRequest request) {
        String payload = toJson(request);
        HttpRequest httpRequest = HttpRequest.newBuilder()
            .uri(URI.create(ragProperties.getRagApi().getBaseUrl() + "/api/v1/rag/chat/ask"))
            .version(HttpClient.Version.HTTP_1_1)
            .timeout(Duration.ofSeconds(120))
            .header("Content-Type", "application/json")
            .header("Accept", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(payload, StandardCharsets.UTF_8))
            .build();
        try {
            HttpResponse<String> response = httpClient.send(httpRequest, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            int status = response.statusCode();
            if (status >= 200 && status < 300) {
                return objectMapper.readValue(response.body(), ChatAskResponse.class);
            }
            throw new RestClientException("FastAPI returned " + status + ": " + response.body());
        } catch (RestClientException ex) {
            throw ex;
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new RestClientException("Interrupted while calling FastAPI chat API.", ex);
        } catch (Exception ex) {
            throw new RestClientException("Failed to call FastAPI chat API.", ex);
        }
    }

    @SuppressWarnings("unused")
    public ChatAskResponse fallback(ChatAskRequest request, RestClientException ex) {
        return degraded(request);
    }

    @SuppressWarnings("unused")
    public ChatAskResponse fallback(ChatAskRequest request, Exception ex) {
        return degraded(request);
    }

    private ChatAskResponse degraded(ChatAskRequest request) {
        return langChain4jChatService.ask(request).orElseGet(this::staticDegraded);
    }

    private ChatAskResponse staticDegraded() {
        return new ChatAskResponse(
            null,
            "Knowledge retrieval is temporarily unavailable. LangChain4j fallback also failed; please check FastAPI, vector storage, and model service.",
            List.of(),
            new ChatAskResponse.Trace(0, 0, 0, 0)
        );
    }

    private ChatAskResponse readStreamResponse(
        Stream<String> lines,
        ChatAskRequest request,
        Consumer<String> deltaConsumer,
        Consumer<String> reasoningConsumer,
        Consumer<String> statusConsumer,
        StreamCancellation cancellation
    ) {
        StringBuilder frameData = new StringBuilder();
        StringBuilder answer = new StringBuilder();
        ChatAskResponse completed = null;
        Iterator<String> iterator = lines.iterator();
        while (iterator.hasNext()) {
            if (cancellation != null && cancellation.isCancelled()) {
                throw new RestClientException("Streaming chat cancelled by client.");
            }
            String line = iterator.next();
            if (line.isBlank()) {
                completed = handleStreamFrame(frameData, request, deltaConsumer, reasoningConsumer, statusConsumer, answer);
                frameData.setLength(0);
                if (completed != null) {
                    return completed;
                }
                continue;
            }
            if (line.startsWith("data:")) {
                frameData.append(line.substring(5).stripLeading()).append('\n');
            }
        }
        completed = handleStreamFrame(frameData, request, deltaConsumer, reasoningConsumer, statusConsumer, answer);
        if (completed != null) {
            return completed;
        }
        if (!answer.isEmpty()) {
            return new ChatAskResponse(request.sessionId(), answer.toString(), List.of(), new ChatAskResponse.Trace(0, 0, 0, request.topK()));
        }
        throw new RestClientException("FastAPI stream ended without a done event.");
    }

    private ChatAskResponse handleStreamFrame(
        StringBuilder frameData,
        ChatAskRequest request,
        Consumer<String> deltaConsumer,
        Consumer<String> reasoningConsumer,
        Consumer<String> statusConsumer,
        StringBuilder answer
    ) {
        if (frameData.length() == 0) {
            return null;
        }
        ChatStreamEvent event = parseStreamEvent(frameData.toString());
        if ("delta".equals(event.type())) {
            String delta = event.delta() == null ? "" : event.delta();
            if (!delta.isEmpty()) {
                answer.append(delta);
                deltaConsumer.accept(delta);
            }
            return null;
        }
        if ("reasoning".equals(event.type())) {
            String reasoning = event.reasoning() == null ? "" : event.reasoning();
            if (!reasoning.isEmpty()) {
                reasoningConsumer.accept(reasoning);
            }
            return null;
        }
        if ("status".equals(event.type())) {
            String message = event.message() == null ? "" : event.message();
            if (!message.isEmpty()) {
                statusConsumer.accept(message);
            }
            return null;
        }
        if ("done".equals(event.type())) {
            return new ChatAskResponse(
                request.sessionId(),
                answer.toString(),
                event.citations() == null ? List.of() : event.citations(),
                event.trace() == null ? new ChatAskResponse.Trace(0, 0, 0, request.topK()) : event.trace()
            );
        }
        if ("error".equals(event.type())) {
            throw new RestClientException(event.message() == null ? "FastAPI streaming chat failed." : event.message());
        }
        return null;
    }

    private ChatStreamEvent parseStreamEvent(String data) {
        try {
            return objectMapper.readValue(data.trim(), ChatStreamEvent.class);
        } catch (JsonProcessingException ex) {
            throw new RestClientException("Failed to parse FastAPI streaming event.", ex);
        }
    }

    private String toJson(ChatAskRequest request) {
        try {
            return objectMapper.writeValueAsString(request);
        } catch (JsonProcessingException ex) {
            throw new IllegalArgumentException("Failed to serialize FastAPI chat request.", ex);
        }
    }

    public static class StreamCancellation {
        private volatile boolean cancelled;
        private volatile InputStream responseBody;

        public boolean isCancelled() {
            return cancelled;
        }

        public void cancel() {
            cancelled = true;
            InputStream currentBody = responseBody;
            if (currentBody != null) {
                try {
                    currentBody.close();
                } catch (IOException ignored) {
                    // Closing is best-effort; the caller only needs the stream to unblock.
                }
            }
        }

        private void attach(InputStream nextResponseBody) {
            responseBody = nextResponseBody;
            if (cancelled && nextResponseBody != null) {
                try {
                    nextResponseBody.close();
                } catch (IOException ignored) {
                    // Closing is best-effort; the caller only needs the stream to unblock.
                }
            }
        }
    }
}
