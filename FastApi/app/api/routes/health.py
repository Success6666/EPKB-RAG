from urllib.error import URLError
from urllib.request import urlopen

from fastapi import APIRouter

from app.core.config import get_settings
from app.langchain_modules.model_io.embeddings import normalize_embedding_provider
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    components: dict[str, str] = {}
    details: dict[str, str] = {}
    embedding_provider = normalize_embedding_provider(settings.embedding_provider)
    if embedding_provider == "ollama":
        try:
            with urlopen(f"{settings.ollama_base_url.rstrip('/')}/api/tags", timeout=2) as response:
                components["embedding"] = "ok" if response.status == 200 else "degraded"
        except (OSError, URLError) as exc:
            components["embedding"] = "degraded"
            details["embedding"] = f"Ollama embedding service unavailable at {settings.ollama_base_url}: {exc}"
    else:
        components["embedding"] = "ok"
    status = "ok" if all(value != "degraded" for value in components.values()) else "degraded"
    return HealthResponse(
        status=status,
        app=settings.app_name,
        version=settings.app_version,
        vector_store=settings.vector_store,
        embedding_provider=embedding_provider,
        components=components,
        details=details,
    )
