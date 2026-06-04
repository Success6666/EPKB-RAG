package com.example.rag.document.dto;

public record UploadTaskResponse(
    String id,
    String documentId,
    String fileName,
    String knowledgeBase,
    String status,
    int progress,
    int chunks,
    String updatedAt,
    String errorMessage
) {
}
