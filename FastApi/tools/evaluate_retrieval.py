"""Offline retrieval evaluation for RAG search results.

The tool can either score a prepared JSONL result file, or call a running
FastAPI RAG endpoint for each gold-set item and score the returned hits.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError


DEFAULT_K_VALUES = (1, 3, 5, 10, 20, 40)


@dataclass
class GoldItem:
    id: str
    query: str
    tenant_id: str
    kb_id: str
    relevant_doc_ids: set[str] = field(default_factory=set)
    relevant_chunk_ids: set[str] = field(default_factory=set)
    relevant_parent_ids: set[str] = field(default_factory=set)
    answerable: bool = True
    metadata_filter: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class Hit:
    doc_id: str | None
    chunk_id: str | None
    parent_id: str | None
    score: float | None = None
    title: str | None = None


@dataclass
class ItemMetrics:
    id: str
    query: str
    answerable: bool
    hit_count: int
    matched_rank: int | None
    reciprocal_rank: float
    ndcg: float
    precision: dict[int, float]
    recall: dict[int, float]
    false_positive_at_k: dict[int, bool]
    tags: list[str]
    error: str = ""
    expected: dict[str, list[str]] = field(default_factory=dict)
    top_hits: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class MetricGate:
    metric: str
    threshold: float


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate RAG retrieval results against a JSONL gold set.")
    parser.add_argument("--gold", required=True, help="Path to gold-set JSONL.")
    parser.add_argument("--results", help="Path to prepared retrieval result JSONL.")
    parser.add_argument("--endpoint", help="FastAPI RAG endpoint, for example http://localhost:8000/api/v1/rag/query.")
    parser.add_argument("--output", help="Optional path to write summary JSON.")
    parser.add_argument("--failures", help="Optional path to write per-query failure CSV.")
    parser.add_argument("--failure-jsonl", help="Optional path to write detailed per-query failure JSONL.")
    parser.add_argument("--fail-under", action="append", default=[], help="Metric gate like recall@5=0.85. Can be repeated.")
    parser.add_argument("--top-k", type=int, default=40, help="topK used when calling --endpoint.")
    parser.add_argument("--mode", default="hybrid", choices=("hybrid", "vector", "keyword"))
    parser.add_argument("--score-threshold", type=float, default=None)
    parser.add_argument("--internal-token", default=os.getenv("INTERNAL_API_TOKEN") or os.getenv("JAVA_CALLBACK_TOKEN"))
    parser.add_argument("--internal-token-header", default="X-Internal-Token")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--k", default="1,3,5,10,20,40", help="Comma-separated K values.")
    args = parser.parse_args(argv)

    k_values = parse_k_values(args.k)
    gold_items = load_gold(Path(args.gold))
    if not gold_items:
        raise SystemExit("Gold set is empty.")

    if args.results and args.endpoint:
        raise SystemExit("Use either --results or --endpoint, not both.")
    if args.results:
        results = load_results(Path(args.results))
    elif args.endpoint:
        results = fetch_results(
            gold_items,
            args.endpoint,
            args.top_k,
            args.mode,
            args.score_threshold,
            args.timeout,
            internal_headers(args.internal_token, args.internal_token_header),
        )
    else:
        raise SystemExit("Either --results or --endpoint is required.")

    metrics = [score_item(item, results.get(item.id, {"hits": [], "error": "missing result"}), k_values) for item in gold_items]
    summary = summarize(metrics, k_values)
    gates = parse_metric_gates(args.fail_under)
    gate_failures = evaluate_metric_gates(summary, gates)
    if gate_failures:
        summary["gateFailures"] = gate_failures
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.output:
        Path(args.output).write_text(json.dumps({"summary": summary, "items": [metric_to_dict(m) for m in metrics]}, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.failures:
        write_failures_csv(Path(args.failures), metrics, k_values)
    if args.failure_jsonl:
        write_failures_jsonl(Path(args.failure_jsonl), metrics, k_values)
    return 2 if gate_failures else 0


def parse_k_values(value: str) -> list[int]:
    parsed = sorted({int(item.strip()) for item in value.split(",") if item.strip()})
    if not parsed or any(item <= 0 for item in parsed):
        raise ValueError("--k must contain positive integers")
    return parsed


def parse_metric_gates(values: list[str]) -> list[MetricGate]:
    gates: list[MetricGate] = []
    for value in values:
        if "=" not in value:
            raise ValueError("--fail-under must use metric=value, for example recall@5=0.85")
        metric, threshold = value.split("=", 1)
        metric = metric.strip()
        if not metric:
            raise ValueError("--fail-under metric name cannot be empty")
        gates.append(MetricGate(metric=metric, threshold=float(threshold.strip())))
    return gates


def load_gold(path: Path) -> list[GoldItem]:
    items: list[GoldItem] = []
    for line_no, row in read_jsonl(path):
        item_id = str(row.get("id") or "").strip()
        query = str(row.get("query") or "").strip()
        tenant_id = str(row.get("tenantId") or row.get("tenant_id") or "").strip()
        kb_id = str(row.get("kbId") or row.get("kb_id") or "").strip()
        if not item_id or not query or not tenant_id or not kb_id:
            raise ValueError(f"{path}:{line_no} requires id, query, tenantId, and kbId")
        relevant = row.get("relevant") or {}
        items.append(
            GoldItem(
                id=item_id,
                query=query,
                tenant_id=tenant_id,
                kb_id=kb_id,
                relevant_doc_ids=set(map(str, relevant.get("docIds") or relevant.get("doc_ids") or [])),
                relevant_chunk_ids=set(map(str, relevant.get("chunkIds") or relevant.get("chunk_ids") or [])),
                relevant_parent_ids=set(map(str, relevant.get("parentIds") or relevant.get("parent_ids") or [])),
                answerable=bool(row.get("answerable", True)),
                metadata_filter=dict(row.get("metadataFilter") or row.get("metadata_filter") or {}),
                tags=[str(tag) for tag in row.get("tags") or []],
                notes=str(row.get("notes") or ""),
            )
        )
    return items


def load_results(path: Path) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for line_no, row in read_jsonl(path):
        item_id = str(row.get("id") or row.get("queryId") or row.get("query_id") or "").strip()
        if not item_id:
            raise ValueError(f"{path}:{line_no} requires id/queryId")
        results[item_id] = row
    return results


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            yield line_no, json.loads(stripped)


def fetch_results(
    gold_items: list[GoldItem],
    endpoint: str,
    top_k: int,
    mode: str,
    score_threshold: float | None,
    timeout: float,
    headers: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for item in gold_items:
        payload: dict[str, Any] = {
            "tenantId": item.tenant_id,
            "kbId": item.kb_id,
            "query": item.query,
            "topK": top_k,
            "mode": mode,
            "includeAnswer": False,
            "metadataFilter": item.metadata_filter,
        }
        if score_threshold is not None:
            payload["scoreThreshold"] = score_threshold
        try:
            response = post_json(endpoint, payload, timeout, headers)
            results[item.id] = {"id": item.id, "hits": response.get("hits") or [], "raw": response}
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            results[item.id] = {"id": item.id, "hits": [], "error": str(exc)}
    return results


def post_json(endpoint: str, payload: dict[str, Any], timeout: float, headers: dict[str, str] | None = None) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    req = urlrequest.Request(endpoint, data=data, headers=request_headers, method="POST")
    with urlrequest.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def internal_headers(token: str | None, header_name: str) -> dict[str, str]:
    return {header_name: token} if token else {}


def score_item(item: GoldItem, result: dict[str, Any], k_values: list[int]) -> ItemMetrics:
    raw_hits = list(result.get("hits") or [])
    hits = [parse_hit(hit) for hit in raw_hits]
    error = str(result.get("error") or "")
    matched_rank = first_relevant_rank(item, hits)
    reciprocal_rank = 0.0 if matched_rank is None else 1.0 / matched_rank
    precision = {k: precision_at_k(item, hits, k) for k in k_values}
    recall = {k: recall_at_k(item, hits, k) for k in k_values}
    false_positive_at_k = {k: (not item.answerable and any_retrieved(hits, k)) for k in k_values}
    return ItemMetrics(
        id=item.id,
        query=item.query,
        answerable=item.answerable,
        hit_count=len(hits),
        matched_rank=matched_rank,
        reciprocal_rank=reciprocal_rank,
        ndcg=ndcg_at_k(item, hits, max(k_values)),
        precision=precision,
        recall=recall,
        false_positive_at_k=false_positive_at_k,
        tags=item.tags,
        error=error,
        expected=expected_targets(item),
        top_hits=[hit_to_dict(hit, raw_hit) for hit, raw_hit in zip(hits[:10], raw_hits[:10])],
    )


def parse_hit(row: dict[str, Any]) -> Hit:
    citation = row.get("citation") or {}
    metadata = row.get("metadata") or {}
    return Hit(
        doc_id=string_or_none(citation.get("docId") or citation.get("doc_id") or metadata.get("doc_id")),
        chunk_id=string_or_none(row.get("chunkId") or row.get("chunk_id") or citation.get("chunkId") or citation.get("chunk_id") or metadata.get("chunk_id")),
        parent_id=string_or_none(metadata.get("parent_id") or metadata.get("parentId")),
        score=float(row["score"]) if row.get("score") is not None else None,
        title=string_or_none(citation.get("fileName") or citation.get("file_name")),
    )


def hit_to_dict(hit: Hit, raw_hit: dict[str, Any]) -> dict[str, Any]:
    metadata = raw_hit.get("metadata") or {}
    return {
        "docId": hit.doc_id,
        "chunkId": hit.chunk_id,
        "parentId": hit.parent_id,
        "score": hit.score,
        "title": hit.title,
        "vectorScore": value_by_alias(raw_hit, "vectorScore", "vector_score"),
        "keywordScore": value_by_alias(raw_hit, "keywordScore", "keyword_score"),
        "retrievalStrategy": metadata.get("retrieval_strategy"),
        "chunkType": metadata.get("chunk_type"),
        "fullDocumentContext": bool(metadata.get("full_document_context")),
        "preview": " ".join(str(raw_hit.get("text") or "").split())[:240],
    }


def expected_targets(item: GoldItem) -> dict[str, list[str]]:
    return {
        "docIds": sorted(item.relevant_doc_ids),
        "chunkIds": sorted(item.relevant_chunk_ids),
        "parentIds": sorted(item.relevant_parent_ids),
    }


def value_by_alias(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row:
            return row[key]
    return None


def string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def first_relevant_rank(item: GoldItem, hits: list[Hit]) -> int | None:
    for index, hit in enumerate(hits, start=1):
        if is_relevant(item, hit):
            return index
    return None


def is_relevant(item: GoldItem, hit: Hit) -> bool:
    if not item.answerable:
        return False
    if item.relevant_chunk_ids and hit.chunk_id in item.relevant_chunk_ids:
        return True
    if item.relevant_parent_ids and hit.parent_id in item.relevant_parent_ids:
        return True
    if item.relevant_doc_ids and hit.doc_id in item.relevant_doc_ids:
        return True
    return False


def relevant_target_count(item: GoldItem) -> int:
    if not item.answerable:
        return 0
    candidates = [len(item.relevant_chunk_ids), len(item.relevant_parent_ids), len(item.relevant_doc_ids)]
    return max((value for value in candidates if value > 0), default=1)


def precision_at_k(item: GoldItem, hits: list[Hit], k: int) -> float:
    if k <= 0:
        return 0.0
    if not item.answerable:
        return 0.0 if any_retrieved(hits, k) else 1.0
    return sum(1 for hit in hits[:k] if is_relevant(item, hit)) / k


def recall_at_k(item: GoldItem, hits: list[Hit], k: int) -> float:
    if not item.answerable:
        return 0.0 if any_retrieved(hits, k) else 1.0
    total = relevant_target_count(item)
    if total <= 0:
        return 0.0
    matched = relevant_id_set(item, hits[:k])
    return min(len(matched) / total, 1.0)


def relevant_id_set(item: GoldItem, hits: list[Hit]) -> set[str]:
    matched: set[str] = set()
    for hit in hits:
        if item.relevant_chunk_ids and hit.chunk_id in item.relevant_chunk_ids:
            matched.add(f"chunk:{hit.chunk_id}")
        if item.relevant_parent_ids and hit.parent_id in item.relevant_parent_ids:
            matched.add(f"parent:{hit.parent_id}")
        if item.relevant_doc_ids and hit.doc_id in item.relevant_doc_ids:
            matched.add(f"doc:{hit.doc_id}")
    return matched


def any_retrieved(hits: list[Hit], k: int) -> bool:
    return bool(hits[:k])


def ndcg_at_k(item: GoldItem, hits: list[Hit], k: int) -> float:
    if not item.answerable:
        return 0.0 if any_retrieved(hits, k) else 1.0
    gains = [1.0 if is_relevant(item, hit) else 0.0 for hit in hits[:k]]
    dcg = sum(gain / log2(index + 2) for index, gain in enumerate(gains))
    ideal_relevant = min(relevant_target_count(item), k)
    if ideal_relevant <= 0:
        return 0.0
    idcg = sum(1.0 / log2(index + 2) for index in range(ideal_relevant))
    return dcg / idcg if idcg else 0.0


def log2(value: int) -> float:
    return value.bit_length() - 1 if value > 0 and value & (value - 1) == 0 else __import__("math").log2(value)


def summarize(metrics: list[ItemMetrics], k_values: list[int]) -> dict[str, Any]:
    total = len(metrics)
    answerable = [item for item in metrics if item.answerable]
    unanswerable = [item for item in metrics if not item.answerable]
    summary: dict[str, Any] = {
        "total": total,
        "answerable": len(answerable),
        "unanswerable": len(unanswerable),
        "mrr": mean(item.reciprocal_rank for item in answerable),
        "ndcg": mean(item.ndcg for item in answerable),
        "errors": sum(1 for item in metrics if item.error),
    }
    for k in k_values:
        summary[f"precision@{k}"] = mean(item.precision[k] for item in answerable)
        summary[f"recall@{k}"] = mean(item.recall[k] for item in answerable)
        summary[f"hit_rate@{k}"] = mean(1.0 if item.matched_rank is not None and item.matched_rank <= k else 0.0 for item in answerable)
        if unanswerable:
            summary[f"false_positive_rate@{k}"] = mean(1.0 if item.false_positive_at_k[k] else 0.0 for item in unanswerable)
    tag_summary = summarize_by_tag(metrics, k_values)
    if tag_summary:
        summary["byTag"] = tag_summary
    return summary


def summarize_by_tag(metrics: list[ItemMetrics], k_values: list[int]) -> dict[str, Any]:
    grouped: dict[str, list[ItemMetrics]] = {}
    for metric in metrics:
        for tag in metric.tags:
            grouped.setdefault(tag, []).append(metric)
    result: dict[str, Any] = {}
    for tag, tag_metrics in sorted(grouped.items()):
        answerable = [item for item in tag_metrics if item.answerable]
        unanswerable = [item for item in tag_metrics if not item.answerable]
        item_summary: dict[str, Any] = {
            "total": len(tag_metrics),
            "answerable": len(answerable),
            "unanswerable": len(unanswerable),
            "mrr": mean(item.reciprocal_rank for item in answerable),
            "ndcg": mean(item.ndcg for item in answerable),
            "errors": sum(1 for item in tag_metrics if item.error),
        }
        for k in k_values:
            item_summary[f"recall@{k}"] = mean(item.recall[k] for item in answerable)
            item_summary[f"hit_rate@{k}"] = mean(
                1.0 if item.matched_rank is not None and item.matched_rank <= k else 0.0 for item in answerable
            )
            if unanswerable:
                item_summary[f"false_positive_rate@{k}"] = mean(
                    1.0 if item.false_positive_at_k[k] else 0.0 for item in unanswerable
                )
        result[tag] = item_summary
    return result


def evaluate_metric_gates(summary: dict[str, Any], gates: list[MetricGate]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for gate in gates:
        actual = summary.get(gate.metric)
        if actual is None:
            failures.append({"metric": gate.metric, "threshold": gate.threshold, "actual": None, "reason": "missing"})
            continue
        if float(actual) < gate.threshold:
            failures.append({"metric": gate.metric, "threshold": gate.threshold, "actual": actual, "reason": "below_threshold"})
    return failures


def mean(values) -> float:
    values = list(values)
    if not values:
        return 0.0
    return round(sum(values) / len(values), 6)


def metric_to_dict(metric: ItemMetrics) -> dict[str, Any]:
    return {
        "id": metric.id,
        "query": metric.query,
        "answerable": metric.answerable,
        "hitCount": metric.hit_count,
        "matchedRank": metric.matched_rank,
        "reciprocalRank": metric.reciprocal_rank,
        "ndcg": metric.ndcg,
        "precision": metric.precision,
        "recall": metric.recall,
        "falsePositiveAtK": metric.false_positive_at_k,
        "tags": metric.tags,
        "error": metric.error,
        "expected": metric.expected,
        "topHits": metric.top_hits,
    }


def write_failures_csv(path: Path, metrics: list[ItemMetrics], k_values: list[int]) -> None:
    max_k = max(k_values)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["id", "query", "answerable", "hitCount", "matchedRank", f"recall@{max_k}", "tags", "error"],
        )
        writer.writeheader()
        for metric in metrics:
            failed_answerable = metric.answerable and metric.recall[max_k] < 1.0
            failed_unanswerable = not metric.answerable and metric.false_positive_at_k[max_k]
            if failed_answerable or failed_unanswerable or metric.error:
                writer.writerow(
                    {
                        "id": metric.id,
                        "query": metric.query,
                        "answerable": metric.answerable,
                        "hitCount": metric.hit_count,
                        "matchedRank": metric.matched_rank or "",
                        f"recall@{max_k}": metric.recall[max_k],
                        "tags": ",".join(metric.tags),
                        "error": metric.error,
                    }
                )


def write_failures_jsonl(path: Path, metrics: list[ItemMetrics], k_values: list[int]) -> None:
    max_k = max(k_values)
    with path.open("w", encoding="utf-8") as handle:
        for metric in metrics:
            failed_answerable = metric.answerable and metric.recall[max_k] < 1.0
            failed_unanswerable = not metric.answerable and metric.false_positive_at_k[max_k]
            if failed_answerable or failed_unanswerable or metric.error:
                handle.write(json.dumps(metric_to_dict(metric), ensure_ascii=False) + "\n")


if __name__ == "__main__":
    sys.exit(main())
