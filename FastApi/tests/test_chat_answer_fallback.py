import unittest

from app.api.routes.rag import NO_RELIABLE_EVIDENCE_ANSWER, no_answer_fallback_answer
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
