"""End-to-end smoke test for a running FastAPI RAG service.

The script ingests a small text document, queries it, and validates that the
returned hits include the expected document id. It is intentionally tiny so it
can be used before a deploy without preparing external files.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any
from urllib import request as urlrequest


DEFAULT_DOCUMENT = (
    "Enterprise knowledge-base smoke document. Alpha-Recall-2026 is an internal code "
    "used to verify the end-to-end retrieval path. A healthy query should retrieve this document."
)
DEFAULT_QUERY = "What is Alpha-Recall-2026?"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a small FastAPI RAG ingest/query smoke test.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="FastAPI base URL.")
    parser.add_argument("--tenant-id", default="smoke-tenant", help="Tenant id used by the smoke test.")
    parser.add_argument("--kb-id", default="smoke-kb", help="Knowledge base id used by the smoke test.")
    parser.add_argument("--doc-id", default=f"smoke-doc-{int(time.time())}", help="Document id to ingest.")
    parser.add_argument("--content", default=DEFAULT_DOCUMENT, help="Text content to ingest.")
    parser.add_argument("--query", default=DEFAULT_QUERY, help="Query to run after ingest.")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--mode", default="hybrid", choices=("hybrid", "vector", "keyword"))
    parser.add_argument("--score-threshold", type=float, default=None)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--skip-health", action="store_true")
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    if not args.skip_health:
        get_json(f"{base_url}/api/v1/health", args.timeout)

    ingest_payload = {
        "tenantId": args.tenant_id,
        "kbId": args.kb_id,
        "docId": args.doc_id,
        "fileName": f"{args.doc_id}.txt",
        "sourceUri": f"smoke://{args.doc_id}",
        "content": args.content,
        "metadata": {"category": "smoke", "source": "smoke_rag_e2e"},
    }
    ingest_response = post_json(f"{base_url}/api/v1/documents/ingest", ingest_payload, args.timeout)
    if ingest_response.get("status") not in {"indexed", "deleted"}:
        raise SystemExit(f"Unexpected ingest status: {json.dumps(ingest_response, ensure_ascii=False)}")
    if ingest_response.get("status") == "deleted":
        raise SystemExit("Smoke document was already marked deleted; use another --doc-id.")

    query_payload: dict[str, Any] = {
        "tenantId": args.tenant_id,
        "kbId": args.kb_id,
        "query": args.query,
        "topK": args.top_k,
        "mode": args.mode,
        "includeAnswer": False,
    }
    if args.score_threshold is not None:
        query_payload["scoreThreshold"] = args.score_threshold
    query_response = post_json(f"{base_url}/api/v1/rag/query", query_payload, args.timeout)
    hits = query_response.get("hits") or []
    matching_hits = [hit for hit in hits if hit_doc_id(hit) == args.doc_id]
    if not matching_hits:
        print(json.dumps({"ingest": ingest_response, "query": query_response}, ensure_ascii=False, indent=2))
        raise SystemExit(f"Smoke query did not retrieve docId={args.doc_id}.")

    summary = {
        "status": "ok",
        "tenantId": args.tenant_id,
        "kbId": args.kb_id,
        "docId": args.doc_id,
        "chunkCount": ingest_response.get("chunkCount"),
        "hitCount": len(hits),
        "matchedRank": hits.index(matching_hits[0]) + 1,
        "topHit": compact_hit(hits[0]),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def get_json(url: str, timeout: float) -> dict[str, Any]:
    with urlrequest.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urlrequest.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urlrequest.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def hit_doc_id(hit: dict[str, Any]) -> str | None:
    citation = hit.get("citation") or {}
    metadata = hit.get("metadata") or {}
    value = citation.get("docId") or citation.get("doc_id") or metadata.get("doc_id")
    return str(value) if value is not None else None


def compact_hit(hit: dict[str, Any]) -> dict[str, Any]:
    citation = hit.get("citation") or {}
    metadata = hit.get("metadata") or {}
    return {
        "docId": hit_doc_id(hit),
        "chunkId": hit.get("chunkId") or hit.get("chunk_id") or citation.get("chunkId"),
        "score": hit.get("score"),
        "vectorScore": hit.get("vectorScore"),
        "keywordScore": hit.get("keywordScore"),
        "fileName": citation.get("fileName"),
        "chunkType": metadata.get("chunk_type"),
        "preview": " ".join(str(hit.get("text") or "").split())[:180],
    }


if __name__ == "__main__":
    sys.exit(main())
