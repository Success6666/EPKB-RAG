package com.example.rag.model.dto;

import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.math.BigDecimal;

public record UpsertModelRequest(
    @NotBlank @Size(max = 64) String provider,
    @Size(max = 128) String originalModelName,
    @NotBlank @Size(max = 128) String modelName,
    @Size(max = 512) String baseUrl,
    @Size(max = 1024) String apiKey,
    @Size(max = 64) String embeddingProvider,
    @NotBlank @Size(max = 128) String embeddingModel,
    @Size(max = 512) String embeddingBaseUrl,
    @Size(max = 1024) String embeddingApiKey,
    @Size(max = 16) String embeddingInputType,
    @Size(max = 16) String embeddingTruncate,
    @Size(max = 128) String rerankModel,
    @DecimalMin("0.0") @DecimalMax("2.0") BigDecimal temperature,
    @DecimalMin("0.0") @DecimalMax("1.0") BigDecimal topP,
    @Min(1) @Max(200000) Integer maxTokens,
    @Min(1024) @Max(1048576) Integer contextWindowTokens,
    Boolean enabled
) {
}
