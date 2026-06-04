from typing import Any

from pydantic import Field

from app.schemas.base import ApiModel


class DocumentIngestJob(ApiModel):
    tenant_id: str = Field(..., alias="tenantId")
    kb_id: str = Field(..., alias="kbId")
    doc_id: str | None = Field(default=None, alias="docId")
    file_path: str | None = Field(default=None, alias="filePath")
    file_name: str | None = Field(default=None, alias="fileName")
    source_uri: str | None = Field(default=None, alias="sourceUri")
    embedding_provider: str | None = Field(default=None, alias="embeddingProvider")
    embedding_model: str | None = Field(default=None, alias="embeddingModel")
    embedding_base_url: str | None = Field(default=None, alias="embeddingBaseUrl")
    embedding_api_key: str | None = Field(default=None, alias="embeddingApiKey")
    embedding_truncate: str | None = Field(default=None, alias="embeddingTruncate")
    content: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentIngestResponse(ApiModel):
    tenant_id: str = Field(..., alias="tenantId")
    kb_id: str = Field(..., alias="kbId")
    doc_id: str = Field(..., alias="docId")
    chunk_count: int = Field(..., alias="chunkCount")
    status: str
