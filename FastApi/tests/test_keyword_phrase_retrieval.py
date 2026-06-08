import unittest

from app.langchain_modules.chains.rag_chain import parent_candidate_top_k
from app.langchain_modules.retrieval.rerank import lexical_overlap_score
from app.langchain_modules.retrieval.scoring import phrase_search_terms, tokenize
from app.schemas.rag import Citation, RetrievalHit
from app.services.mysql_repository import like_search_terms


class KeywordPhraseRetrievalTests(unittest.TestCase):
    def test_phrase_terms_strip_conversational_prefix(self):
        terms = phrase_search_terms("讲一下关于基层教学组织的主要职责")

        self.assertIn("基层教学组织的主要职责", terms)

    def test_phrase_terms_preserve_exact_chinese_heading(self):
        terms = phrase_search_terms("请问第三章 基层教学组织的主要职责是什么？")

        self.assertIn("第三章 基层教学组织的主要职责", terms)
        self.assertIn("第三章基层教学组织的主要职责", terms)
        self.assertIn("基层教学组织的主要职责", terms)

    def test_like_terms_prioritize_long_phrases_before_short_ngrams(self):
        query = "第三章 基层教学组织的主要职责是什么"
        terms = [*phrase_search_terms(query), *tokenize(query)]

        like_terms = like_search_terms(terms, limit=4)

        self.assertIn("基层教学组织的主要职责", like_terms)
        self.assertNotIn("基层", like_terms)

    def test_lexical_rerank_rewards_stripped_heading_phrase(self):
        query = "第三章 基层教学组织的主要职责是什么"
        exact_hit = hit(
            "exact",
            "第三章 基层教学组织的主要职责\n基层教学组织负责落实人才培养方案、开展课程建设。",
        )
        partial_hit = hit(
            "partial",
            "基层教学组织建设要加强教学研究，完善教学运行管理。",
        )

        self.assertGreater(
            lexical_overlap_score(query, exact_hit),
            lexical_overlap_score(query, partial_hit),
        )

    def test_parent_candidate_window_keeps_enough_parents_for_rerank(self):
        settings = DummySettings()

        self.assertEqual(parent_candidate_top_k(5, settings), 20)


class DummySettings:
    rerank_enabled = True
    child_chunks_per_parent = 3
    rerank_top_n = 40
    retrieval_candidate_multiplier = 4


def hit(chunk_id: str, text: str) -> RetrievalHit:
    return RetrievalHit(
        chunkId=chunk_id,
        text=text,
        score=0.5,
        citation=Citation(docId="doc-1", chunkId=chunk_id, fileName="rules.pdf"),
        metadata={"chunk_id": chunk_id, "doc_id": "doc-1"},
    )


if __name__ == "__main__":
    unittest.main()
