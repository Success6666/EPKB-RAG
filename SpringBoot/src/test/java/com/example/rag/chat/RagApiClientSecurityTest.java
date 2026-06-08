package com.example.rag.chat;

import static org.junit.jupiter.api.Assertions.assertEquals;

import com.example.rag.chat.dto.ChatAskRequest;
import com.example.rag.config.RagProperties;
import com.example.rag.langchain.LangChain4jChatService;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;

class RagApiClientSecurityTest {

    @Test
    void chatRequestSendsInternalTokenToFastApi() throws Exception {
        AtomicReference<String> tokenHeader = new AtomicReference<>();
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/api/v1/rag/chat/ask", exchange -> {
            tokenHeader.set(exchange.getRequestHeaders().getFirst("X-Internal-Token"));
            byte[] body = """
                {"sessionId":null,"answer":"ok","citations":[],"trace":{"retrievalMs":0,"rerankMs":0,"generationMs":0,"topK":5,"hitCount":0,"returnedCitationCount":0,"knowledgeBaseIds":[],"warnings":[]}}
                """.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();
        try {
            RagProperties properties = new RagProperties();
            properties.getRagApi().setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
            properties.getInternal().setCallbackToken("secret-token");
            RagApiClient client = new RagApiClient(
                properties,
                org.mockito.Mockito.mock(LangChain4jChatService.class),
                new ObjectMapper()
            );

            client.ask(new ChatAskRequest(
                1L,
                null,
                "hello",
                "all",
                List.of("1"),
                5,
                0.2,
                null,
                0.15,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                false,
                null,
                null,
                false,
                null,
                List.<ChatAskRequest.HistoryMessage>of(),
                null
            ));

            assertEquals("secret-token", tokenHeader.get());
        } finally {
            server.stop(0);
        }
    }
}
