package com.example.rag.tenant.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

public record UpdateEmployeeRoleRequest(
    @NotBlank @Size(max = 32) String role
) {
}
