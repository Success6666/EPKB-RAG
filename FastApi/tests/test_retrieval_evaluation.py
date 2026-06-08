import unittest
from unittest.mock import patch

from tools.evaluate_retrieval import (
    Hit,
    GoldItem,
    evaluate_metric_gates,
    parse_k_values,
    parse_metric_gates,
    post_json,
    score_item,
    summarize,
)


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
        self.assertNotIn("byTag", summary)

    def test_summarize_groups_metrics_by_tag(self):
        answerable = GoldItem(
            id="q1",
            query="q",
            tenant_id="1",
            kb_id="10",
            relevant_doc_ids={"doc-a"},
            tags=["policy", "exact"],
        )
        metrics = [
            score_item(answerable, {"hits": [{"chunkId": "c", "citation": {"docId": "doc-a", "chunkId": "c"}}]}, [1])
        ]

        summary = summarize(metrics, [1])

        self.assertEqual(summary["byTag"]["policy"]["total"], 1)
        self.assertEqual(summary["byTag"]["exact"]["recall@1"], 1)

    def test_metric_gates_report_failures(self):
        gates = parse_metric_gates(["recall@5=0.8", "mrr=0.5"])

        failures = evaluate_metric_gates({"recall@5": 0.75, "mrr": 0.5}, gates)

        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["metric"], "recall@5")

    def test_parse_k_values_sorts_and_deduplicates(self):
        self.assertEqual(parse_k_values("10,1,5,5"), [1, 5, 10])

    def test_score_item_keeps_failure_diagnostics(self):
        item = GoldItem(id="q3", query="q", tenant_id="1", kb_id="10", relevant_doc_ids={"doc-a"})

        metrics = score_item(
            item,
            {
                "hits": [
                    {
                        "chunkId": "noise",
                        "text": "irrelevant text",
                        "score": 0.3,
                        "citation": {"docId": "doc-noise", "chunkId": "noise", "fileName": "noise.txt"},
                        "metadata": {"parent_id": "parent-noise", "retrieval_strategy": "hybrid"},
                    }
                ]
            },
            [1],
        )

        self.assertEqual(metrics.expected["docIds"], ["doc-a"])
        self.assertEqual(metrics.top_hits[0]["docId"], "doc-noise")
        self.assertEqual(metrics.top_hits[0]["retrievalStrategy"], "hybrid")

    def test_failure_diagnostics_keep_zero_scores(self):
        item = GoldItem(id="q4", query="q", tenant_id="1", kb_id="10", relevant_doc_ids={"doc-a"})

        metrics = score_item(
            item,
            {
                "hits": [
                    {
                        "chunkId": "noise",
                        "score": 0.0,
                        "vectorScore": 0.0,
                        "keyword_score": 0.0,
                        "citation": {"docId": "doc-noise", "chunkId": "noise"},
                    }
                ]
            },
            [1],
        )

        self.assertEqual(metrics.top_hits[0]["score"], 0.0)
        self.assertEqual(metrics.top_hits[0]["vectorScore"], 0.0)
        self.assertEqual(metrics.top_hits[0]["keywordScore"], 0.0)

    def test_post_json_sends_internal_token_header(self):
        class Response:
            def __enter__(self):
                self.status = 200
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"{}"

        captured = {}

        def fake_urlopen(request, timeout):
            captured["token"] = request.get_header("X-internal-token")
            captured["timeout"] = timeout
            return Response()

        with patch("tools.evaluate_retrieval.urlrequest.urlopen", fake_urlopen):
            post_json("http://example.test/api", {"query": "hello"}, 3.0, {"X-Internal-Token": "secret"})

        self.assertEqual(captured["token"], "secret")
        self.assertEqual(captured["timeout"], 3.0)

    def test_hit_dataclass_accepts_missing_fields(self):
        hit = Hit(doc_id=None, chunk_id=None, parent_id=None)

        self.assertIsNone(hit.doc_id)


if __name__ == "__main__":
    unittest.main()
