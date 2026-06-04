package com.example.rag.tenant.dto;

import java.time.LocalDateTime;
import java.util.List;

public record CompanyListResponse(List<CompanyItem> items) {
    public record CompanyItem(
        String id,
        String name,
        String code,
        Integer status,
        LocalDateTime createdAt
    ) {
    }
}
