package com.example.rag.document.dto;

import java.util.List;

public record KnowledgeBaseListResponse(List<Item> items) {
    public record Item(String id, String name, String description) {
    }
}
