import asyncio
import unittest

from app.core.config import Settings
from app.langchain_modules.chains.rag_chain import HybridRetrievalService
from app.schemas.rag import Citation, RetrievalHit, RetrievalQuery, RetrievalResponse


class MultiKbRetrievalTests(unittest.TestCase):
    def test_retrieve_many_rewrites_once_and_defers_rerank_to_cross_kb_pass(self):
        service = OrchestratedRetrievalService()
        request = RetrievalQuery(
            tenantId="tenant-a",
            kbId="kb-a",
            query="what about it",
            topK=2,
            includeAnswer=False,
            history=[{"role": "user", "content": "tell me about the refund policy"}],
        )

        response = asyncio.run(service.retrieve_many(request, ["kb-a", "kb-b", "kb-a"]))

        self.assertEqual(service.rewrite_count, 1)
        self.assertEqual(service.retrieved_kb_ids, ["kb-a", "kb-b"])
        self.assertTrue(all(kwargs["retrieval_query_override"] == "rewritten query" for kwargs in service.retrieve_kwargs))
        self.assertTrue(all(kwargs["rerank_hits"] is False for kwargs in service.retrieve_kwargs))
        self.assertEqual(service.cross_kb_rerank_count, 1)
        self.assertEqual(response.rerank_ms, 7)
        self.assertEqual([hit.metadata["kb_id"] for hit in response.hits], ["kb-a", "kb-b"])


class OrchestratedRetrievalService(HybridRetrievalService):
    def __init__(self) -> None:
        settings = Settings(
            child_chunks_per_parent=1,
            full_document_context_enabled=False,
            llm_context_refinement_enabled=False,
            query_rewrite_min_chars=1,
            retrieval_multi_kb_max_concurrency=1,
        )
        super().__init__(settings, vector_store=None, generator=None, mysql_repository=None, reranker=None)  # type: ignore[arg-type]
        self.rewrite_count = 0
        self.cross_kb_rerank_count = 0
        self.retrieved_kb_ids: list[str] = []
        self.retrieve_kwargs: list[dict] = []

    async def _maybe_rewrite_query(self, *args, **kwargs) -> str:
        self.rewrite_count += 1
        return "rewritten query"

    async def retrieve(self, request: RetrievalQuery, **kwargs) -> RetrievalResponse:
        self.retrieved_kb_ids.append(request.kb_id)
        self.retrieve_kwargs.append(kwargs)
        return RetrievalResponse(
            tenantId=request.tenant_id,
            kbId=request.kb_id,
            query=request.query,
            answer=None,
            hits=[hit_for_kb(request.kb_id)],
            warnings=[],
            rerankMs=0,
        )

    async def _rerank_hits(self, query: str, hits: list[RetrievalHit], top_k: int, **kwargs) -> tuple[list[RetrievalHit], int]:
        self.cross_kb_rerank_count += 1
        return hits[:top_k], 7


def hit_for_kb(kb_id: str) -> RetrievalHit:
    chunk_id = f"{kb_id}-chunk"
    return RetrievalHit(
        chunkId=chunk_id,
        text=f"text for {kb_id}",
        score=0.8,
        citation=Citation(docId=f"{kb_id}-doc", chunkId=chunk_id, fileName=f"{kb_id}.txt"),
        metadata={"kb_id": kb_id, "doc_id": f"{kb_id}-doc", "chunk_id": chunk_id},
    )


if __name__ == "__main__":
    unittest.main()
