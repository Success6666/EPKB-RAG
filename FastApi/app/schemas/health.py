from pydantic import Field

from app.schemas.base import ApiModel


class HealthResponse(ApiModel):
    status: str
    app: str
    version: str
    vector_store: str
    embedding_provider: str
    components: dict[str, str] = Field(default_factory=dict)
    details: dict[str, str] = Field(default_factory=dict)
