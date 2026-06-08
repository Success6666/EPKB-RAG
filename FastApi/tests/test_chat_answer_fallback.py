import unittest

from app.api.routes.rag import NO_RELIABLE_EVIDENCE_ANSWER, chat_citations, no_answer_fallback_answer
from app.schemas.rag import Citation, RetrievalHit


class ChatAnswerFallbackTests(unittest.TestCase):
    def test_no_hits_keeps_no_reliable_evidence_message(self):
        answer = no_answer_fallback_answer([], 0.15)

        self.assertEqual(answer, NO_RELIABLE_EVIDENCE_ANSWER)

    def test_trusted_hits_return_evidence_summary_when_model_outputs_nothing(self):
        answer = no_answer_fallback_answer(
            [
                hit("chunk-1", "新乡学院主要职责包括组织实施高等本、专科学历人才培养。", 0.86),
                hit("chunk-2", "这个片段低于阈值，不应进入兜底摘要。", 0.12),
            ],
            0.15,
        )

        self.assertIn("已检索到可用于回答的知识库证据", answer)
        self.assertIn("新乡学院主要职责包括", answer)
        self.assertNotIn("低于阈值", answer)

    def test_chat_citations_keep_scores_and_safe_metadata(self):
        citations = chat_citations(
            [
                RetrievalHit(
                    chunkId="chunk-1",
                    text="evidence",
                    score=0.87654,
                    vectorScore=0.7,
                    keywordScore=0.2,
                    citation=Citation(docId="doc-1", chunkId="chunk-1", fileName="doc.txt", sourceUri="s3://doc.txt"),
                    metadata={
                        "chunk_id": "chunk-1",
                        "doc_id": "doc-1",
                        "kb_id": "kb-1",
                        "retrieval_strategy": "hybrid",
                        "api_key": "must-not-leak",
                    },
                )
            ],
            0.15,
        )

        citation = citations[0].model_dump(by_alias=True)
        self.assertEqual(citation["docId"], "doc-1")
        self.assertEqual(citation["chunkId"], "chunk-1")
        self.assertEqual(citation["kbId"], "kb-1")
        self.assertEqual(citation["sourceUri"], "s3://doc.txt")
        self.assertEqual(citation["score"], 0.8765)
        self.assertEqual(citation["vectorScore"], 0.7)
        self.assertEqual(citation["keywordScore"], 0.2)
        self.assertEqual(citation["metadata"]["retrieval_strategy"], "hybrid")
        self.assertNotIn("api_key", citation["metadata"])


def hit(chunk_id: str, text: str, score: float) -> RetrievalHit:
    return RetrievalHit(
        chunkId=chunk_id,
        text=text,
        score=score,
        citation=Citation(docId="doc-1", chunkId=chunk_id, fileName="新乡学院2024年部门预算公开.pdf"),
        metadata={"chunk_id": chunk_id, "doc_id": "doc-1"},
    )


if __name__ == "__main__":
    unittest.main()
