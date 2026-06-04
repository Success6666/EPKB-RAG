package com.example.rag.document;

import com.example.rag.config.RagProperties;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Map;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.client.RestClientException;

@Component
public class DocumentRagClient {

    private final HttpClient httpClient;
    private final RagProperties ragProperties;
    private final ObjectMapper objectMapper;

    public DocumentRagClient(RagProperties ragProperties, ObjectMapper objectMapper) {
        this.httpClient = HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)
            .connectTimeout(Duration.ofSeconds(3))
            .build();
        this.ragProperties = ragProperties;
        this.objectMapper = objectMapper;
    }

    public void deleteDocument(Long tenantId, Long knowledgeBaseId, Long documentId) {
        String callbackToken = ragProperties.getInternal().getCallbackToken();
        if (!StringUtils.hasText(callbackToken)) {
            throw new RestClientException("JAVA_CALLBACK_TOKEN must be configured before calling FastAPI internal document APIs.");
        }
        String payload = toJson(Map.of(
            "tenantId", String.valueOf(tenantId),
            "kbId", String.valueOf(knowledgeBaseId),
            "docId", String.valueOf(documentId)
        ));
        HttpRequest request = HttpRequest.newBuilder()
            .uri(URI.create(ragProperties.getRagApi().getBaseUrl() + "/api/v1/documents/internal"))
            .version(HttpClient.Version.HTTP_1_1)
            .timeout(Duration.ofSeconds(60))
            .header("Content-Type", "application/json")
            .header("X-Internal-Token", callbackToken)
            .method("DELETE", HttpRequest.BodyPublishers.ofString(payload, StandardCharsets.UTF_8))
            .build();
        try {
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            int status = response.statusCode();
            if (status < 200 || status >= 300) {
                throw new RestClientException("FastAPI delete returned " + status + ": " + response.body());
            }
        } catch (RestClientException ex) {
            throw ex;
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new RestClientException("Interrupted while deleting FastAPI document chunks.", ex);
        } catch (Exception ex) {
            throw new RestClientException("Failed to delete FastAPI document chunks.", ex);
        }
    }

    private String toJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException ex) {
            throw new IllegalArgumentException("Failed to serialize FastAPI document request.", ex);
        }
    }
}
