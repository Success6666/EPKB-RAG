package com.example.rag.auth.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

public record RegisterRequest(
    @NotBlank @Size(max = 32) String mode,
    @NotBlank @Size(max = 128) String username,
    @NotBlank @Size(min = 6, max = 128) String password,
    @NotBlank @Size(max = 128) String displayName,
    @Size(max = 128) String companyName,
    @Size(max = 64) String companyCode
) {
}
