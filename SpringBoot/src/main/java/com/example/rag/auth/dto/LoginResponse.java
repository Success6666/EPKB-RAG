package com.example.rag.auth.dto;

import java.util.List;

public record LoginResponse(
    String token,
    UserView user,
    List<TenantView> tenants
) {
    public record UserView(String id, String name, String email, String role) {
    }

    public record TenantView(String id, String name, String code, String role, String quota) {
    }
}
