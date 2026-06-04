package com.example.rag.tenant.dto;

import java.util.List;

public record TenantListResponse(List<TenantItem> items) {
    public record TenantItem(String id, String name, String code, String role, String quota) {
    }
}
