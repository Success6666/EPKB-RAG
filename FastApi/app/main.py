from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import documents, health, rag
from app.core.config import get_settings
from app.core.runtime_gc import collect_runtime_memory, start_periodic_gc, stop_periodic_gc


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        del app
        gc_task = start_periodic_gc(settings)
        try:
            yield
        finally:
            await stop_periodic_gc(gc_task)
            collect_runtime_memory(settings)

    docs_url = None if settings.is_prod else "/docs"
    redoc_url = None if settings.is_prod else "/redoc"
    openapi_url = None if settings.is_prod else "/openapi.json"

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Multi-tenant private knowledge-base RAG middleware.",
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )

    app.include_router(health.router, prefix=settings.api_prefix)
    app.include_router(documents.router, prefix=settings.api_prefix)
    app.include_router(rag.router, prefix=settings.api_prefix)

    return app


app = create_app()
