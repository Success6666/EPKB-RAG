import unittest

from tools.evaluate_retrieval import Hit, GoldItem, parse_k_values, score_item, summarize


class RetrievalEvaluationTests(unittest.TestCase):
    def test_score_item_matches_chunk_parent_or_doc(self):
        item = GoldItem(
            id="q1",
            query="制度职责",
            tenant_id="1",
            kb_id="10",
            relevant_doc_ids={"doc-a"},
            relevant_chunk_ids={"chunk-a"},
            relevant_parent_ids={"parent-a"},
        )
        result = {
            "hits": [
                {
                    "chunkId": "chunk-b",
                    "score": 0.4,
                    "citation": {"docId": "doc-b", "chunkId": "chunk-b"},
                    "metadata": {"parent_id": "parent-b"},
                },
                {
                    "chunkId": "chunk-a",
                    "score": 0.9,
                    "citation": {"docId": "doc-a", "chunkId": "chunk-a"},
                    "metadata": {"parent_id": "parent-a"},
                },
            ]
        }

        metrics = score_item(item, result, [1, 2, 5])

        self.assertEqual(metrics.matched_rank, 2)
        self.assertEqual(metrics.recall[1], 0)
        self.assertEqual(metrics.recall[2], 1)
        self.assertAlmostEqual(metrics.reciprocal_rank, 0.5)

    def test_unanswerable_query_rewards_empty_hits_and_flags_false_positive(self):
        item = GoldItem(id="q2", query="unknown", tenant_id="1", kb_id="10", answerable=False)

        empty_metrics = score_item(item, {"hits": []}, [1, 3])
        noisy_metrics = score_item(
            item,
            {"hits": [{"chunkId": "noise", "score": 0.2, "citation": {"docId": "doc-noise", "chunkId": "noise"}}]},
            [1, 3],
        )

        self.assertEqual(empty_metrics.precision[1], 1)
        self.assertEqual(empty_metrics.recall[3], 1)
        self.assertTrue(noisy_metrics.false_positive_at_k[1])
        self.assertEqual(noisy_metrics.precision[1], 0)

    def test_summarize_reports_recall_and_false_positive_rate(self):
        answerable = GoldItem(id="q1", query="q", tenant_id="1", kb_id="10", relevant_doc_ids={"doc-a"})
        unanswerable = GoldItem(id="q2", query="q", tenant_id="1", kb_id="10", answerable=False)
        metrics = [
            score_item(answerable, {"hits": [{"chunkId": "c", "citation": {"docId": "doc-a", "chunkId": "c"}}]}, [1]),
            score_item(unanswerable, {"hits": [{"chunkId": "n", "citation": {"docId": "doc-n", "chunkId": "n"}}]}, [1]),
        ]

        summary = summarize(metrics, [1])

        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["recall@1"], 1)
        self.assertEqual(summary["false_positive_rate@1"], 1)

    def test_parse_k_values_sorts_and_deduplicates(self):
        self.assertEqual(parse_k_values("10,1,5,5"), [1, 5, 10])

    def test_hit_dataclass_accepts_missing_fields(self):
        hit = Hit(doc_id=None, chunk_id=None, parent_id=None)

        self.assertIsNone(hit.doc_id)


if __name__ == "__main__":
    unittest.main()
