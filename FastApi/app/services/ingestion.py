import asyncio
import logging
from uuid import uuid4

from app.langchain_modules.retrieval.document_processor import DocumentProcessor
from app.langchain_modules.retrieval.vector_store import KnowledgeBaseScope, VectorStore
from app.schemas.documents import DocumentIngestJob, DocumentIngestResponse
from app.services.mysql_repository import MySqlRepository

logger = logging.getLogger(__name__)


class DocumentIngestionService:
    def __init__(
        self,
        processor: DocumentProcessor,
        vector_store: VectorStore,
        mysql_repository: MySqlRepository,
        vector_store_resolver=None,
    ) -> None:
        self.processor = processor
        self.vector_store = vector_store
        self.mysql_repository = mysql_repository
        self.vector_store_resolver = vector_store_resolver

    async def ingest(self, job: DocumentIngestJob) -> DocumentIngestResponse:
        doc_id = job.doc_id or uuid4().hex
        normalized = job.model_copy(update={"doc_id": doc_id})
        scope = KnowledgeBaseScope(tenant_id=job.tenant_id, kb_id=job.kb_id)
        if await self.mysql_repository.is_document_deleted(scope, doc_id):
            logger.info(
                "Skipping ingest for deleted document tenant_id=%s kb_id=%s doc_id=%s",
                job.tenant_id,
                job.kb_id,
                doc_id,
            )
            return DocumentIngestResponse(
                tenantId=job.tenant_id,
                kbId=job.kb_id,
                docId=doc_id,
                chunkCount=0,
                status="deleted",
            )
        chunks = await asyncio.to_thread(self.processor.process, normalized)
        child_chunks = [chunk for chunk in chunks if (chunk.get("metadata") or {}).get("chunk_type") == "child"]
        vector_chunks = child_chunks or chunks
        if await self.mysql_repository.is_document_deleted(scope, doc_id):
            logger.info(
                "Skipping index write for document deleted during processing tenant_id=%s kb_id=%s doc_id=%s",
                job.tenant_id,
                job.kb_id,
                doc_id,
            )
            return DocumentIngestResponse(
                tenantId=job.tenant_id,
                kbId=job.kb_id,
                docId=doc_id,
                chunkCount=0,
                status="deleted",
            )
        await self.mysql_repository.replace_chunks(scope, doc_id, chunks)
        vector_store = self.vector_store_resolver(normalized) if self.vector_store_resolver else self.vector_store
        try:
            await asyncio.to_thread(vector_store.upsert_chunks, scope, vector_chunks)
        except Exception:
            await self.mysql_repository.delete_chunks(scope, doc_id)
            raise
        return DocumentIngestResponse(
            tenantId=job.tenant_id,
            kbId=job.kb_id,
            docId=doc_id,
            chunkCount=len(chunks),
            status="indexed",
        )

    async def delete_document(self, job: DocumentIngestJob) -> DocumentIngestResponse:
        if not job.doc_id:
            raise ValueError("docId is required.")
        scope = KnowledgeBaseScope(tenant_id=job.tenant_id, kb_id=job.kb_id)
        await self.mysql_repository.mark_document_deleted(scope, job.doc_id)
        deleted_chunks = await self.mysql_repository.delete_chunks(scope, job.doc_id)
        if deleted_chunks > 0:
            try:
                await asyncio.to_thread(self.vector_store.delete_document, scope, job.doc_id)
            except Exception as exc:
                logger.warning(
                    "Vector index delete failed after MySQL chunks were deleted tenant_id=%s kb_id=%s doc_id=%s: %s",
                    job.tenant_id,
                    job.kb_id,
                    job.doc_id,
                    exc,
                )
        return DocumentIngestResponse(
            tenantId=job.tenant_id,
            kbId=job.kb_id,
            docId=job.doc_id,
            chunkCount=0,
            status="deleted",
        )
