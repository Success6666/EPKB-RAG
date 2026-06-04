package com.example.rag.tenant.dto;

import java.time.LocalDateTime;
import java.util.List;

public record EmployeeListResponse(List<EmployeeItem> items) {
    public record EmployeeItem(
        String userId,
        String username,
        String displayName,
        String role,
        LocalDateTime joinedAt
    ) {
    }
}
