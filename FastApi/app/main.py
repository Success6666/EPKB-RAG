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

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Multi-tenant private knowledge-base RAG middleware.",
        lifespan=lifespan,
    )

    app.include_router(health.router, prefix=settings.api_prefix)
    app.include_router(documents.router, prefix=settings.api_prefix)
    app.include_router(rag.router, prefix=settings.api_prefix)
    app.include_router(rag.router)

    return app


app = create_app()
