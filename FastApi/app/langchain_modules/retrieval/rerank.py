import logging
import json
import re
import time
from typing import Protocol

import httpx

from app.core.config import Settings
from app.langchain_modules.retrieval.scoring import keyword_score, tokenize
from app.schemas.rag import RetrievalHit

logger = logging.getLogger(__name__)


class Reranker(Protocol):
    def rerank(
        self,
        query: str,
        hits: list[RetrievalHit],
        top_k: int,
        *,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> list[RetrievalHit]:
        ...


def create_reranker(settings: Settings) -> Reranker:
    provider = normalize_rerank_provider(settings.rerank_provider)
    if provider == "deepseek":
        return DeepSeekReranker(settings)
    if provider in {"cross_encoder", "sentence_transformers"}:
        return CrossEncoderReranker(settings)
    raise ValueError(f"Unsupported rerank provider: {settings.rerank_provider}")


class DeepSeekReranker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = (settings.rerank_base_url or settings.deepseek_base_url).rstrip("/")
        self.model = settings.rerank_model
        self.api_key = settings.rerank_api_key or settings.deepseek_api_key
        self.timeout = settings.rerank_timeout_seconds
        self._missing_api_key_logged = False
        self._remote_failure_logged = False

    def rerank(
        self,
        query: str,
        hits: list[RetrievalHit],
        top_k: int,
        *,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> list[RetrievalHit]:
        if not self.settings.rerank_enabled or not query or not hits:
            return hits[:top_k]
        if is_disabled_rerank_model(model):
            return hits[:top_k]
        candidates = hits[: max(top_k, self.settings.rerank_top_n)]
        effective_api_key = clean_value(api_key) or self.api_key
        if not effective_api_key:
            if not self._missing_api_key_logged:
                logger.info("DeepSeek rerank API key is not configured; using local lexical rerank fallback.")
                self._missing_api_key_logged = True
            return lexical_rerank(query, candidates, top_k, self.settings.rerank_weight, "lexical_fallback")

        effective_model = clean_value(model) or self.model
        effective_base_url = (clean_value(base_url) or self.base_url).rstrip("/")
        try:
            scores = self._score(query, candidates, effective_model, effective_base_url, effective_api_key)
        except Exception as exc:
            if not self._remote_failure_logged:
                logger.warning("DeepSeek rerank failed; using local lexical rerank fallback: %s", exc)
                self._remote_failure_logged = True
            else:
                logger.debug("DeepSeek rerank failed; using local lexical rerank fallback: %s", exc)
            return lexical_rerank(query, candidates, top_k, self.settings.rerank_weight, "lexical_fallback")
        return combine_rerank_scores(candidates, scores, top_k, self.settings.rerank_weight, "deepseek")

    def _score(self, query: str, hits: list[RetrievalHit], model: str, base_url: str, api_key: str) -> list[float]:
        prompt = build_deepseek_rerank_prompt(query, hits)
        response = post_with_connect_retries(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a strict relevance scoring service. Return only valid JSON. "
                            "Do not explain your reasoning."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
                "max_tokens": max(256, min(4096, len(hits) * 24)),
            },
            timeout=httpx.Timeout(self.timeout, connect=5.0),
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = truncate(response.text, 500)
            raise RuntimeError(f"DeepSeek rerank request failed status={response.status_code}: {body}") from exc

        payload = response.json()
        choice = (payload.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = str(message.get("content") or choice.get("text") or "")
        scores = parse_score_array(content)
        if len(scores) != len(hits):
            raise ValueError(f"DeepSeek rerank returned {len(scores)} scores for {len(hits)} candidates: {truncate(content, 300)}")
        return normalize_numbers([min(max(float(score), 0.0), 1.0) for score in scores])


class CrossEncoderReranker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model = None
        self._unavailable = False

    def rerank(
        self,
        query: str,
        hits: list[RetrievalHit],
        top_k: int,
        *,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> list[RetrievalHit]:
        if not self.settings.rerank_enabled or not query or not hits:
            return hits[:top_k]
        if is_disabled_rerank_model(model):
            return hits[:top_k]
        candidates = hits[: max(top_k, self.settings.rerank_top_n)]
        model = self._load_model()
        pairs = [[query, rerank_text(hit)] for hit in candidates]
        raw_scores = model.predict(pairs, batch_size=max(1, self.settings.rerank_batch_size))
        rerank_scores = normalize_numbers([float(score) for score in raw_scores])
        return combine_rerank_scores(candidates, rerank_scores, top_k, self.settings.rerank_weight, "cross_encoder")

    def _load_model(self):
        if self._model is not None:
            return self._model
        if self._unavailable:
            raise RuntimeError("rerank model is unavailable")
        try:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.settings.rerank_model)
            return self._model
        except Exception:
            self._unavailable = True
            raise


def rerank_text(hit: RetrievalHit) -> str:
    metadata = hit.metadata or {}
    parts = [
        str(metadata.get("file_name") or ""),
        str(metadata.get("section_title") or ""),
        str(metadata.get("section_path") or ""),
        str(metadata.get("keywords") or ""),
        str(hit.text or ""),
    ]
    return "\n".join(part for part in parts if part).strip()[:1800]


def build_deepseek_rerank_prompt(query: str, hits: list[RetrievalHit]) -> str:
    passages = []
    for index, hit in enumerate(hits):
        passages.append(
            {
                "index": index,
                "text": rerank_text(hit)[:1600],
            }
        )
    return (
        "Score each passage for relevance to the query on a 0.0 to 1.0 scale.\n"
        "Return only a JSON array of numbers in the same order as the passages.\n"
        "The array length must exactly equal the number of passages.\n\n"
        f"Query:\n{query}\n\n"
        f"Passages:\n{json.dumps(passages, ensure_ascii=False)}"
    )


def parse_score_array(content: str) -> list[float]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", text)
        if not match:
            raise ValueError(f"DeepSeek rerank did not return a JSON array: {truncate(content, 300)}")
        value = json.loads(match.group(0))
    if not isinstance(value, list):
        raise ValueError(f"DeepSeek rerank returned non-array JSON: {truncate(content, 300)}")
    return [float(item) for item in value]


def post_with_connect_retries(url: str, **kwargs) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            return httpx.post(url, **kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            last_error = exc
            if attempt == 2:
                break
            time.sleep(0.25 * (attempt + 1))
    raise last_error or RuntimeError("HTTP request failed before it was sent.")


def normalize_rerank_provider(provider: str | None) -> str:
    value = (provider or "deepseek").strip().lower().replace("-", "_")
    if value in {"deepseek", "deepseek_chat"}:
        return "deepseek"
    if value in {"cross_encoder", "sentence_transformers", "sentencetransformers", "local"}:
        return "cross_encoder"
    return value


def clean_value(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def is_disabled_rerank_model(model: str | None) -> bool:
    value = clean_value(model)
    return value is not None and value.lower() in {"none", "off", "disabled"}


def combine_rerank_scores(
    hits: list[RetrievalHit],
    rerank_scores: list[float],
    top_k: int,
    rerank_weight: float,
    method: str,
) -> list[RetrievalHit]:
    retrieval_scores = normalize_numbers([hit.score for hit in hits])
    weight = min(max(rerank_weight, 0.0), 1.0)
    reranked: list[RetrievalHit] = []
    for hit, retrieval_score, rerank_score in zip(hits, retrieval_scores, rerank_scores):
        combined = (1.0 - weight) * retrieval_score + weight * rerank_score
        reranked.append(
            RetrievalHit(
                chunkId=hit.chunk_id,
                text=hit.text,
                score=combined,
                vectorScore=hit.vector_score,
                keywordScore=hit.keyword_score,
                citation=hit.citation,
                metadata={
                    **hit.metadata,
                    "pre_rerank_score": hit.score,
                    "rerank_score": rerank_score,
                    "rerank_method": method,
                },
            )
        )
    return sorted(reranked, key=lambda item: item.score, reverse=True)[:top_k]


def lexical_rerank(
    query: str,
    hits: list[RetrievalHit],
    top_k: int,
    rerank_weight: float,
    method: str = "lexical",
) -> list[RetrievalHit]:
    rerank_scores = [lexical_overlap_score(query, hit) for hit in hits]
    if not has_any_positive(rerank_scores):
        return hits[:top_k]
    return combine_rerank_scores(hits, normalize_numbers(rerank_scores), top_k, rerank_weight, method)


def lexical_overlap_score(query: str, hit: RetrievalHit) -> float:
    query_terms = set(lexical_query_terms(query))
    if not query_terms:
        return 0.0
    text = rerank_text(hit).lower()
    matched = sum(1 for term in query_terms if term and term in text)
    coverage = matched / max(len(query_terms), 1)
    weighted_frequency = min(keyword_score(list(query_terms), text) / 3.0, 1.0)
    exact_bonus = 0.15 if query.strip() and query.strip().lower() in text else 0.0
    return min(1.0, 0.65 * coverage + 0.35 * weighted_frequency + exact_bonus)


def lexical_query_terms(query: str) -> list[str]:
    expanded = re.sub(r"[/\\|,;:，；、()\[\]{}<>]", " ", query)
    return list(dict.fromkeys([*tokenize(query), *tokenize(expanded)]))


def has_any_positive(values: list[float]) -> bool:
    return any(value > 0 for value in values)


def normalize_numbers(values: list[float]) -> list[float]:
    if not values:
        return []
    minimum = min(values)
    maximum = max(values)
    if maximum == minimum:
        return [1.0 for _ in values]
    return [(value - minimum) / (maximum - minimum) for value in values]


def truncate(value: str, max_length: int) -> str:
    return value if len(value) <= max_length else value[:max_length] + "..."
