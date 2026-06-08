"""Offline retrieval evaluation for RAG search results.

The tool can either score a prepared JSONL result file, or call a running
FastAPI RAG endpoint for each gold-set item and score the returned hits.
"""

from __future__ import annotations

import argparse
import csv
import json
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate RAG retrieval results against a JSONL gold set.")
    parser.add_argument("--gold", required=True, help="Path to gold-set JSONL.")
    parser.add_argument("--results", help="Path to prepared retrieval result JSONL.")
    parser.add_argument("--endpoint", help="FastAPI RAG endpoint, for example http://localhost:8000/api/v1/rag/query.")
    parser.add_argument("--output", help="Optional path to write summary JSON.")
    parser.add_argument("--failures", help="Optional path to write per-query failure CSV.")
    parser.add_argument("--top-k", type=int, default=40, help="topK used when calling --endpoint.")
    parser.add_argument("--mode", default="hybrid", choices=("hybrid", "vector", "keyword"))
    parser.add_argument("--score-threshold", type=float, default=None)
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
        results = fetch_results(gold_items, args.endpoint, args.top_k, args.mode, args.score_threshold, args.timeout)
    else:
        raise SystemExit("Either --results or --endpoint is required.")

    metrics = [score_item(item, results.get(item.id, {"hits": [], "error": "missing result"}), k_values) for item in gold_items]
    summary = summarize(metrics, k_values)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.output:
        Path(args.output).write_text(json.dumps({"summary": summary, "items": [metric_to_dict(m) for m in metrics]}, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.failures:
        write_failures_csv(Path(args.failures), metrics, k_values)
    return 0


def parse_k_values(value: str) -> list[int]:
    parsed = sorted({int(item.strip()) for item in value.split(",") if item.strip()})
    if not parsed or any(item <= 0 for item in parsed):
        raise ValueError("--k must contain positive integers")
    return parsed


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
            response = post_json(endpoint, payload, timeout)
            results[item.id] = {"id": item.id, "hits": response.get("hits") or [], "raw": response}
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            results[item.id] = {"id": item.id, "hits": [], "error": str(exc)}
    return results


def post_json(endpoint: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urlrequest.Request(endpoint, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urlrequest.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def score_item(item: GoldItem, result: dict[str, Any], k_values: list[int]) -> ItemMetrics:
    hits = [parse_hit(hit) for hit in result.get("hits") or []]
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
    return summary


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


if __name__ == "__main__":
    sys.exit(main())
