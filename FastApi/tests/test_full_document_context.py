import unittest

from app.langchain_modules.chains.rag_chain import (
    full_document_candidates,
    join_parent_chunks,
    should_use_full_document_context,
)
from app.langchain_modules.retrieval.vector_store import VectorSearchResult
from app.schemas.rag import Citation, RetrievalHit


class DummySettings:
    full_document_context_enabled = True


class FullDocumentContextTests(unittest.TestCase):
    def test_contract_template_queries_use_full_document_context(self):
        settings = DummySettings()

        self.assertTrue(should_use_full_document_context("帮我拟一份采购合同", settings))
        self.assertTrue(should_use_full_document_context("帮我找合同样本", settings))
        self.assertTrue(should_use_full_document_context("sample employment contract", settings))

    def test_targeted_contract_question_keeps_chunk_context(self):
        self.assertFalse(should_use_full_document_context("查一下合同里的付款条款", DummySettings()))

    def test_full_document_candidates_dedupe_by_kb_and_doc(self):
        hits = [
            hit("kb-1", "doc-a", "chunk-a-1", 0.2),
            hit("kb-1", "doc-a", "chunk-a-2", 0.8),
            hit("kb-1", "doc-b", "chunk-b-1", 0.7),
            hit("kb-1", "doc-c", "chunk-c-1", 0.1),
        ]

        candidates = full_document_candidates(hits, max_docs=2, min_score=0.15)

        self.assertEqual([item["doc_id"] for item in candidates], ["doc-a", "doc-b"])
        self.assertEqual(candidates[0]["hit"].chunk_id, "chunk-a-2")
        self.assertEqual(candidates[0]["source_hit_count"], 2)

    def test_join_parent_chunks_preserves_order_and_budget(self):
        chunks = [
            parent_chunk("p2", 2, "第二部分"),
            parent_chunk("p1", 1, "第一部分"),
            parent_chunk("p3", 3, "第三部分"),
        ]

        text, truncated = join_parent_chunks(chunks, max_chars=8)

        self.assertEqual(text, "第一部分\n\n第二")
        self.assertTrue(truncated)


def hit(kb_id: str, doc_id: str, chunk_id: str, score: float) -> RetrievalHit:
    return RetrievalHit(
        chunkId=chunk_id,
        text=f"text for {chunk_id}",
        score=score,
        citation=Citation(docId=doc_id, chunkId=chunk_id, fileName=f"{doc_id}.txt"),
        metadata={"kb_id": kb_id, "doc_id": doc_id, "chunk_id": chunk_id},
    )


def parent_chunk(chunk_id: str, chunk_index: int, text: str) -> VectorSearchResult:
    return VectorSearchResult(
        chunk_id=chunk_id,
        text=text,
        metadata={"chunk_id": chunk_id, "chunk_index": chunk_index},
        score=0.0,
    )


if __name__ == "__main__":
    unittest.main()
