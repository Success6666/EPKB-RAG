import unittest

from app.langchain_modules.chains.rag_chain import cross_kb_candidate_top_k, parent_candidate_top_k
from app.langchain_modules.retrieval.rerank import lexical_overlap_score
from app.langchain_modules.retrieval.scoring import phrase_search_terms, tokenize
from app.schemas.rag import Citation, RetrievalHit
from app.services.mysql_repository import (
    batched,
    keyword_metadata_like_expression,
    like_search_terms,
    like_term_weight,
    metadata_like_term_weight,
    should_run_like_fallback,
)


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

    def test_cross_kb_candidate_window_keeps_rerank_floor(self):
        settings = DummySettings()

        self.assertEqual(cross_kb_candidate_top_k(5, settings), 40)

    def test_like_fallback_skips_when_fulltext_has_enough_hits(self):
        settings = DummySettings()

        self.assertFalse(should_run_like_fallback([{"chunk_id": "a"}, {"chunk_id": "b"}], 2, settings))
        self.assertTrue(should_run_like_fallback([{"chunk_id": "a"}], 2, settings))

    def test_like_fallback_uses_configured_fulltext_threshold(self):
        settings = DummySettings()
        settings.mysql_keyword_like_fallback_min_fulltext_hits = 3

        self.assertFalse(should_run_like_fallback([{}, {}, {}], 10, settings))
        self.assertTrue(should_run_like_fallback([{}, {}], 10, settings))

    def test_batched_yields_batches_without_prebuilding_all_slices(self):
        items = [{"id": value} for value in range(5)]

        self.assertEqual([[row["id"] for row in batch] for batch in batched(items, 2)], [[0, 1], [2, 3], [4]])

    def test_metadata_like_expression_covers_lightweight_metadata_fields(self):
        expression = keyword_metadata_like_expression()

        self.assertIn("file_name", expression)
        self.assertIn("section_title", expression)
        self.assertIn("section_path", expression)
        self.assertIn("keywords", expression)

    def test_metadata_like_weight_is_small_title_boost(self):
        self.assertEqual(metadata_like_term_weight("refund"), like_term_weight("refund") + 2)


class DummySettings:
    rerank_enabled = True
    child_chunks_per_parent = 3
    rerank_top_n = 40
    retrieval_candidate_multiplier = 4
    mysql_keyword_like_fallback_enabled = True
    mysql_keyword_like_fallback_min_fulltext_hits = 0
    mysql_keyword_metadata_like_enabled = True
    mysql_keyword_metadata_like_max_terms = 8


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
