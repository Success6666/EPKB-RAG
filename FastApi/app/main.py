from fastapi import FastAPI

from app.api.routes import documents, health, rag
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Multi-tenant private knowledge-base RAG middleware.",
    )

    app.include_router(health.router, prefix=settings.api_prefix)
    app.include_router(documents.router, prefix=settings.api_prefix)
    app.include_router(rag.router, prefix=settings.api_prefix)
    app.include_router(rag.router)

    return app


app = create_app()
