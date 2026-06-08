from typing import Any, Literal

from pydantic import Field, field_validator

from app.schemas.base import ApiModel


class RetrievalQuery(ApiModel):
    tenant_id: str = Field(..., alias="tenantId")
    kb_id: str = Field(..., alias="kbId")
    query: str
    top_k: int = Field(default=5, ge=1, le=50, alias="topK")
    mode: Literal["hybrid", "vector", "keyword"] = "hybrid"
    include_answer: bool = Field(default=False, alias="includeAnswer")
    metadata_filter: dict[str, Any] = Field(default_factory=dict, alias="metadataFilter")
    history: list[dict[str, str]] = Field(default_factory=list)
    context: str | list[str] | dict[str, Any] | None = None
    context_window_tokens: int | None = Field(default=None, alias="contextWindowTokens")
    token_budget: int | None = Field(default=None, alias="tokenBudget")
    context_compressed: bool = Field(default=False, alias="contextCompressed")
    context_summary: str | None = Field(default=None, alias="contextSummary")
    deep_thinking: bool = Field(default=False, alias="deepThinking")
    score_threshold: float | None = Field(default=None, ge=0, le=1, alias="scoreThreshold")
    embedding_provider: str | None = Field(default=None, alias="embeddingProvider")
    embedding_model: str | None = Field(default=None, alias="embeddingModel")
    embedding_base_url: str | None = Field(default=None, alias="embeddingBaseUrl")
    embedding_api_key: str | None = Field(default=None, alias="embeddingApiKey")
    embedding_truncate: str | None = Field(default=None, alias="embeddingTruncate")
    rerank_model: str | None = Field(default=None, alias="rerankModel")
    rerank_base_url: str | None = Field(default=None, alias="rerankBaseUrl")
    rerank_api_key: str | None = Field(default=None, alias="rerankApiKey")

    @field_validator("tenant_id", "kb_id", mode="before")
    @classmethod
    def stringify_scope_ids(cls, value: Any) -> Any:
        return str(value) if value is not None else value


class Citation(ApiModel):
    doc_id: str | None = Field(default=None, alias="docId")
    chunk_id: str = Field(..., alias="chunkId")
    file_name: str | None = Field(default=None, alias="fileName")
    source_uri: str | None = Field(default=None, alias="sourceUri")
    page: int | None = None


class RetrievalHit(ApiModel):
    chunk_id: str = Field(..., alias="chunkId")
    text: str
    score: float
    vector_score: float | None = Field(default=None, alias="vectorScore")
    keyword_score: float | None = Field(default=None, alias="keywordScore")
    citation: Citation
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalResponse(ApiModel):
    tenant_id: str = Field(..., alias="tenantId")
    kb_id: str = Field(..., alias="kbId")
    query: str
    answer: str | None = None
    hits: list[RetrievalHit]
    warnings: list[str] = Field(default_factory=list)
    rerank_ms: int = Field(default=0, alias="rerankMs")


class ChatAskRequest(ApiModel):
    tenant_id: str = Field(..., alias="tenantId")
    session_id: str | int | None = Field(default=None, alias="sessionId")
    question: str
    knowledge_base: str = Field(default="all", alias="knowledgeBase")
    knowledge_base_ids: list[str] = Field(default_factory=list, alias="knowledgeBaseIds")
    top_k: int = Field(default=5, ge=1, le=50, alias="topK")
    temperature: float = Field(default=0.2, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1, alias="topP")
    score_threshold: float = Field(default=0.15, ge=0, le=1, alias="scoreThreshold")
    provider: str | None = None
    model: str | None = None
    base_url: str | None = Field(default=None, alias="baseUrl")
    api_key: str | None = Field(default=None, alias="apiKey")
    embedding_provider: str | None = Field(default=None, alias="embeddingProvider")
    embedding_model: str | None = Field(default=None, alias="embeddingModel")
    embedding_base_url: str | None = Field(default=None, alias="embeddingBaseUrl")
    embedding_api_key: str | None = Field(default=None, alias="embeddingApiKey")
    embedding_truncate: str | None = Field(default=None, alias="embeddingTruncate")
    rerank_model: str | None = Field(default=None, alias="rerankModel")
    rerank_base_url: str | None = Field(default=None, alias="rerankBaseUrl")
    rerank_api_key: str | None = Field(default=None, alias="rerankApiKey")
    context_window_tokens: int | None = Field(default=None, alias="contextWindowTokens")
    token_budget: int | None = Field(default=None, alias="tokenBudget")
    context_compressed: bool = Field(default=False, alias="contextCompressed")
    context_summary: str | None = Field(default=None, alias="contextSummary")
    deep_thinking: bool = Field(default=False, alias="deepThinking")
    history: list[dict[str, str]] = Field(default_factory=list)
    context: str | list[str] | dict[str, Any] | None = None

    @field_validator("tenant_id", mode="before")
    @classmethod
    def stringify_tenant_id(cls, value: Any) -> Any:
        return str(value) if value is not None else value


class ChatCitation(ApiModel):
    id: str
    title: str
    doc_id: str | None = Field(default=None, alias="docId")
    chunk_id: str | None = Field(default=None, alias="chunkId")
    kb_id: str | None = Field(default=None, alias="kbId")
    source_uri: str | None = Field(default=None, alias="sourceUri")
    page: int | None = None
    score: float
    vector_score: float | None = Field(default=None, alias="vectorScore")
    keyword_score: float | None = Field(default=None, alias="keywordScore")
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatTrace(ApiModel):
    retrieval_ms: int = Field(default=0, alias="retrievalMs")
    rerank_ms: int = Field(default=0, alias="rerankMs")
    generation_ms: int = Field(default=0, alias="generationMs")
    top_k: int = Field(..., alias="topK")
    score_threshold: float | None = Field(default=None, alias="scoreThreshold")
    hit_count: int = Field(default=0, alias="hitCount")
    returned_citation_count: int = Field(default=0, alias="returnedCitationCount")
    knowledge_base_ids: list[str] = Field(default_factory=list, alias="knowledgeBaseIds")
    warnings: list[str] = Field(default_factory=list)


class ChatAskResponse(ApiModel):
    session_id: str | int | None = Field(default=None, alias="sessionId")
    answer: str
    citations: list[ChatCitation]
    trace: ChatTrace
