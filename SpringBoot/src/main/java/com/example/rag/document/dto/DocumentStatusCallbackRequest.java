package com.example.rag.document.dto;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

public record DocumentStatusCallbackRequest(
    @NotNull Long tenantId,
    @NotNull Long docId,
    @NotBlank String status,
    @Min(0) Integer chunkCount,
    String errorMessage
) {
}
