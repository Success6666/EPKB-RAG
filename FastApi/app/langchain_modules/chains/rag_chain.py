import asyncio
import logging
import re
import time
from typing import Callable, Protocol

from app.core.config import Settings
from app.schemas.rag import Citation, RetrievalHit, RetrievalQuery, RetrievalResponse
from app.langchain_modules.model_io.generation import OllamaGenerationClient
from app.langchain_modules.retrieval.rerank import Reranker, create_reranker
from app.langchain_modules.retrieval.scoring import keyword_score, normalize_scores, tokenize
from app.langchain_modules.retrieval.vector_store import KnowledgeBaseScope, VectorSearchResult, VectorStore

logger = logging.getLogger(__name__)


class KeywordSearchRepository(Protocol):
    async def keyword_search(
        self,
        scope: KnowledgeBaseScope,
        query: str,
        metadata_filter: dict,
        top_k: int,
    ) -> list[VectorSearchResult]:
        ...

    async def child_chunks_for_parents(
        self,
        scope: KnowledgeBaseScope,
        parent_ids: list[str],
        metadata_filter: dict | None = None,
        limit_per_parent: int = 8,
    ) -> dict[str, list[VectorSearchResult]]:
        ...

    async def parent_chunks_by_ids(
        self,
        scope: KnowledgeBaseScope,
        parent_ids: list[str],
        metadata_filter: dict | None = None,
    ) -> dict[str, VectorSearchResult]:
        ...


class HybridRetrievalService:
    def __init__(
        self,
        settings: Settings,
        vector_store: VectorStore,
        generator: OllamaGenerationClient,
        mysql_repository: KeywordSearchRepository,
        embedding_store_resolver: Callable[[RetrievalQuery], VectorStore] | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self.settings = settings
        self.vector_store = vector_store
        self.generator = generator
        self.mysql_repository = mysql_repository
        self.embedding_store_resolver = embedding_store_resolver
        self.reranker = reranker or create_reranker(settings)

    async def retrieve(
        self,
        request: RetrievalQuery,
        provider: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        rerank_model: str | None = None,
        rerank_base_url: str | None = None,
        rerank_api_key: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> RetrievalResponse:
        scope = KnowledgeBaseScope(tenant_id=request.tenant_id, kb_id=request.kb_id)
        child_filter = {**request.metadata_filter, "chunk_type": "child"}
        vector_store = self._vector_store_for_request(request)
        retrieval_query = await self._maybe_rewrite_query(
            request.query,
            request.history,
            provider,
            model,
            base_url,
            api_key,
        )
        expansion_max_queries = self.settings.hybrid_query_expansion_max_queries if self.settings.hybrid_query_expansion_enabled else 1
        search_queries = expanded_search_queries(request.query, retrieval_query, expansion_max_queries)
        candidate_top_k = retrieval_candidate_top_k(request.top_k, self.settings)
        effective_rerank_model = rerank_model if rerank_model is not None else request.rerank_model
        effective_rerank_base_url = rerank_base_url if rerank_base_url is not None else request.rerank_base_url
        effective_rerank_api_key = rerank_api_key if rerank_api_key is not None else request.rerank_api_key
        vector_results: list[VectorSearchResult] = []
        keyword_results: list[VectorSearchResult] = []
        warnings: list[str] = []
        rerank_ms = 0

        if request.mode in {"hybrid", "vector"}:
            try:
                vector_results = fuse_search_results(
                    await self._vector_search_many(vector_store, scope, search_queries, child_filter, candidate_top_k),
                    candidate_top_k,
                )
            except Exception as exc:
                if request.mode == "hybrid":
                    logger.warning("Vector search failed in hybrid mode, continuing with keyword search: %s", exc)
                    warnings.append(f"Vector retrieval is unavailable; keyword-only fallback was used. Reason: {exc}")
                elif not self.settings.vector_store.lower().endswith("_with_keyword_fallback"):
                    raise
                else:
                    logger.warning("Vector search failed, falling back to keyword search: %s", exc)
                    warnings.append(f"Vector retrieval is unavailable; keyword-only fallback was used. Reason: {exc}")
                    keyword_results = fuse_search_results(
                        await self._keyword_search_many(scope, search_queries, child_filter, candidate_top_k),
                        candidate_top_k,
                    )

        if request.mode in {"hybrid", "keyword"}:
            keyword_results = fuse_search_results(
                await self._keyword_search_many(scope, search_queries, child_filter, candidate_top_k),
                candidate_top_k,
            )

        child_hits = self._merge_results(
            vector_results,
            keyword_results,
            candidate_top_k,
            request.mode,
        )
        hits = await self._expand_child_hits_to_parent_context(
            scope,
            retrieval_query,
            child_hits,
            request.metadata_filter,
            parent_candidate_top_k(request.top_k, self.settings),
        )
        hits, rerank_ms = await self._rerank_hits(
            request.query,
            hits,
            max(request.top_k * self.settings.child_chunks_per_parent, request.top_k),
            rerank_model=effective_rerank_model,
            rerank_base_url=effective_rerank_base_url,
            rerank_api_key=effective_rerank_api_key,
        )
        threshold = request.score_threshold if request.score_threshold is not None else self.settings.hallucination_min_score
        trusted_hits = [hit for hit in hits if hit.score >= threshold]
        answer_hits = (
            await self._refine_context_for_llm(request.query, trusted_hits, provider, model, base_url, api_key, temperature, top_p)
            if request.include_answer
            else trusted_hits
        )
        answer = None
        if request.include_answer:
            answer = await self._generate_answer(
                request.query,
                answer_hits,
                request.history,
                request.context,
                context_summary=request.context_summary,
                context_compressed=request.context_compressed,
                token_budget=request.token_budget,
                context_window_tokens=request.context_window_tokens,
                deep_thinking=request.deep_thinking,
                provider=provider,
                model=model,
                base_url=base_url,
                api_key=api_key,
                temperature=temperature,
                top_p=top_p,
            )
        return RetrievalResponse(
            tenantId=request.tenant_id,
            kbId=request.kb_id,
            query=request.query,
            answer=answer,
            hits=answer_hits if request.include_answer else trusted_hits,
            warnings=warnings,
            rerankMs=rerank_ms,
        )

    def _vector_store_for_request(self, request: RetrievalQuery) -> VectorStore:
        if self.embedding_store_resolver is None:
            return self.vector_store
        return self.embedding_store_resolver(request)

    async def retrieve_many(
        self,
        request: RetrievalQuery,
        kb_ids: list[str],
        provider: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        rerank_model: str | None = None,
        rerank_base_url: str | None = None,
        rerank_api_key: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> RetrievalResponse:
        scoped_ids = [kb_id for kb_id in dict.fromkeys(kb_ids) if kb_id]
        if not scoped_ids:
            return RetrievalResponse(tenantId=request.tenant_id, kbId=request.kb_id, query=request.query, answer=None, hits=[])

        effective_rerank_model = rerank_model if rerank_model is not None else request.rerank_model
        effective_rerank_base_url = rerank_base_url if rerank_base_url is not None else request.rerank_base_url
        effective_rerank_api_key = rerank_api_key if rerank_api_key is not None else request.rerank_api_key
        hits: list[RetrievalHit] = []
        warnings: list[str] = []
        rerank_ms = 0
        for kb_id in scoped_ids:
            scoped_request = request.model_copy(update={"kb_id": kb_id, "include_answer": False})
            response = await self.retrieve(
                scoped_request,
                provider=provider,
                model=model,
                base_url=base_url,
                api_key=api_key,
                rerank_model=effective_rerank_model,
                rerank_base_url=effective_rerank_base_url,
                rerank_api_key=effective_rerank_api_key,
                temperature=temperature,
                top_p=top_p,
            )
            hits.extend(response.hits)
            warnings.extend(response.warnings)
            rerank_ms += response.rerank_ms

        merged_hits = dedupe_hits(hits, max(request.top_k * self.settings.child_chunks_per_parent, request.top_k))
        merged_hits, cross_kb_rerank_ms = await self._rerank_hits(
            request.query,
            merged_hits,
            max(request.top_k * self.settings.child_chunks_per_parent, request.top_k),
            rerank_model=effective_rerank_model,
            rerank_base_url=effective_rerank_base_url,
            rerank_api_key=effective_rerank_api_key,
        )
        rerank_ms += cross_kb_rerank_ms
        threshold = request.score_threshold if request.score_threshold is not None else self.settings.hallucination_min_score
        trusted_hits = [hit for hit in merged_hits if hit.score >= threshold]
        answer_hits = (
            await self._refine_context_for_llm(request.query, trusted_hits, provider, model, base_url, api_key, temperature, top_p)
            if request.include_answer
            else trusted_hits
        )
        answer = None
        if request.include_answer:
            answer = await self._generate_answer(
                request.query,
                answer_hits,
                request.history,
                request.context,
                context_summary=request.context_summary,
                context_compressed=request.context_compressed,
                token_budget=request.token_budget,
                context_window_tokens=request.context_window_tokens,
                deep_thinking=request.deep_thinking,
                provider=provider,
                model=model,
                base_url=base_url,
                api_key=api_key,
                temperature=temperature,
                top_p=top_p,
            )
        return RetrievalResponse(
            tenantId=request.tenant_id,
            kbId=request.kb_id,
            query=request.query,
            answer=answer,
            hits=answer_hits if request.include_answer else trusted_hits,
            warnings=dedupe_warnings(warnings),
            rerankMs=rerank_ms,
        )

    async def _generate_answer(
        self,
        query: str,
        hits: list[RetrievalHit],
        history: list[dict[str, str]] | None,
        context,
        context_summary: str | None,
        context_compressed: bool,
        token_budget: int | None,
        context_window_tokens: int | None,
        deep_thinking: bool,
        provider: str | None,
        model: str | None,
        base_url: str | None,
        api_key: str | None,
        temperature: float | None,
        top_p: float | None,
    ) -> str:
        try:
            return await asyncio.to_thread(
                self.generator.generate,
                query,
                hits,
                history,
                context,
                context_summary=context_summary,
                context_compressed=context_compressed,
                token_budget=token_budget,
                context_window_tokens=context_window_tokens,
                deep_thinking=deep_thinking,
                provider=provider,
                model=model,
                base_url=base_url,
                api_key=api_key,
                temperature=temperature,
                top_p=top_p,
            )
        except Exception as exc:
            logger.warning("Generation failed, returning evidence fallback: %s", exc)
            return evidence_fallback_answer(hits, exc)

    async def _keyword_search(
        self,
        scope: KnowledgeBaseScope,
        query: str,
        metadata_filter: dict,
        top_k: int,
    ) -> list[VectorSearchResult]:
        return await self.mysql_repository.keyword_search(scope, query, metadata_filter, top_k)

    async def _vector_search_many(
        self,
        vector_store: VectorStore,
        scope: KnowledgeBaseScope,
        queries: list[str],
        metadata_filter: dict,
        top_k: int,
    ) -> list[VectorSearchResult]:
        results: list[VectorSearchResult] = []
        for query_index, query in enumerate(queries):
            query_results = await asyncio.to_thread(vector_store.similarity_search, scope, query, top_k, metadata_filter)
            results.extend(tag_query_results(query_results, query_index, query))
        return results

    async def _keyword_search_many(
        self,
        scope: KnowledgeBaseScope,
        queries: list[str],
        metadata_filter: dict,
        top_k: int,
    ) -> list[VectorSearchResult]:
        results: list[VectorSearchResult] = []
        for query_index, query in enumerate(queries):
            query_results = await self._keyword_search(scope, query, metadata_filter, top_k)
            results.extend(tag_query_results(query_results, query_index, query))
        return results

    async def _rerank_hits(
        self,
        query: str,
        hits: list[RetrievalHit],
        top_k: int,
        rerank_model: str | None = None,
        rerank_base_url: str | None = None,
        rerank_api_key: str | None = None,
    ) -> tuple[list[RetrievalHit], int]:
        if not hits or not self.settings.rerank_enabled:
            return hits[:top_k], 0
        started = time.perf_counter()
        try:
            reranked = await asyncio.to_thread(
                self.reranker.rerank,
                query,
                hits,
                top_k,
                model=rerank_model,
                base_url=rerank_base_url,
                api_key=rerank_api_key,
            )
        except Exception as exc:
            logger.warning("Rerank failed, using retrieval order: %s", exc)
            return hits[:top_k], int((time.perf_counter() - started) * 1000)
        return reranked, int((time.perf_counter() - started) * 1000)

    async def _maybe_rewrite_query(
        self,
        query: str,
        history: list[dict[str, str]] | None,
        provider: str | None,
        model: str | None,
        base_url: str | None,
        api_key: str | None,
    ) -> str:
        if not should_rewrite_query(query, history, self.settings.query_rewrite_min_chars):
            return query
        try:
            rewritten = await self.generator.rewrite_query(
                query,
                history[-self.settings.query_rewrite_max_history_messages :] if history else [],
                provider=provider,
                model=model,
                base_url=base_url,
                api_key=api_key,
            )
        except Exception as exc:
            logger.warning("Query rewrite failed, using original query: %s", exc)
            return query
        if not valid_rewritten_query(query, rewritten):
            return query
        logger.info("Query rewritten original=%r rewritten=%r", query, rewritten)
        return rewritten

    async def _expand_child_hits_to_parent_context(
        self,
        scope: KnowledgeBaseScope,
        query: str,
        child_hits: list[RetrievalHit],
        metadata_filter: dict,
        top_k: int,
    ) -> list[RetrievalHit]:
        if not child_hits:
            return []
        parent_ids = [str(hit.metadata.get("parent_id") or "") for hit in child_hits if hit.metadata.get("parent_id")]
        parent_hits = await self.mysql_repository.parent_chunks_by_ids(scope, parent_ids, parent_context_filter(metadata_filter))
        child_groups = await self.mysql_repository.child_chunks_for_parents(
            scope,
            parent_ids,
            metadata_filter,
            limit_per_parent=max(self.settings.child_chunks_per_parent * 4, self.settings.child_chunks_per_parent),
        )
        best_child_by_parent: dict[str, RetrievalHit] = {}
        for child_hit in child_hits:
            parent_id = str(child_hit.metadata.get("parent_id") or "")
            if not parent_id:
                continue
            current = best_child_by_parent.get(parent_id)
            if current is None or child_hit.score > current.score:
                best_child_by_parent[parent_id] = child_hit
        query_terms = tokenize(query)
        selected: list[RetrievalHit] = []
        ranked_parent_ids = sorted(
            best_child_by_parent,
            key=lambda parent_id: best_child_by_parent[parent_id].score,
            reverse=True,
        )[:top_k]
        for parent_id in ranked_parent_ids:
            seed_child = best_child_by_parent[parent_id]
            parent_hit = parent_hits.get(parent_id)
            children = child_groups.get(parent_id) or []
            if not children:
                logger.info(
                    "Skipping stale vector hit without MySQL child rows tenant=%s kb=%s parent_id=%s matched_child_id=%s",
                    scope.tenant_id,
                    scope.kb_id,
                    parent_id,
                    seed_child.chunk_id,
                )
                continue
            ranked_children = sorted(
                children,
                key=lambda child: (
                    1 if child.chunk_id == seed_child.chunk_id else 0,
                    keyword_score(query_terms, child.text),
                    -int(child.metadata.get("child_index") or 0),
                ),
                reverse=True,
            )[: self.settings.child_chunks_per_parent]
            for child in sorted(ranked_children, key=lambda item: int(item.metadata.get("child_index") or 0)):
                child_keyword_score = keyword_score(query_terms, child.text)
                child_vector_score = seed_child.vector_score if child.chunk_id == seed_child.chunk_id else None
                child_combined_score = seed_child.score + min(child_keyword_score, 1.0) * 0.05
                selected.append(
                    RetrievalHit(
                        chunkId=child.chunk_id,
                        text=child.text,
                        score=child_combined_score,
                        vectorScore=child_vector_score,
                        keywordScore=seed_child.keyword_score,
                        citation=Citation(
                            docId=child.metadata.get("doc_id"),
                            chunkId=child.chunk_id,
                            fileName=child.metadata.get("file_name"),
                            sourceUri=child.metadata.get("source_uri"),
                            page=child.metadata.get("page"),
                        ),
                        metadata={
                            **child.metadata,
                            "retrieval_strategy": "child_vector_parent_context",
                            "parent_score": seed_child.score,
                            "parent_chunk_id": parent_id,
                            "parent_text": parent_hit.text if parent_hit else "",
                            "matched_child_id": seed_child.chunk_id,
                        },
                    )
                )
        return sorted(dedupe_hits(selected, max(top_k * self.settings.child_chunks_per_parent, top_k)), key=lambda hit: hit.score, reverse=True)

    async def _refine_context_for_llm(
        self,
        query: str,
        hits: list[RetrievalHit],
        provider: str | None,
        model: str | None,
        base_url: str | None,
        api_key: str | None,
        temperature: float | None,
        top_p: float | None,
    ) -> list[RetrievalHit]:
        if not hits or not self.settings.llm_context_refinement_enabled:
            return hits
        scoped_hits = hits[: self.settings.llm_context_refinement_max_hits]
        try:
            refined_texts = await self.generator.refine_context(
                query,
                scoped_hits,
                provider=provider,
                model=model,
                base_url=base_url,
                api_key=api_key,
                temperature=0.0 if temperature is None else min(temperature, 0.1),
                top_p=top_p,
            )
        except Exception as exc:
            logger.warning("LLM context refinement failed, using local compaction: %s", exc)
            return [compact_hit(hit) for hit in hits]

        if not refined_texts:
            return [compact_hit(hit) for hit in hits]

        refined_hits: list[RetrievalHit] = []
        for hit, refined_text in zip(scoped_hits, refined_texts):
            text = " ".join(str(refined_text or "").split())
            if len(text) < 8:
                text = compact_text(hit.text, 900)
            refined_hits.append(
                RetrievalHit(
                    chunkId=hit.chunk_id,
                    text=text[:1200],
                    score=hit.score,
                    vectorScore=hit.vector_score,
                    keywordScore=hit.keyword_score,
                    citation=hit.citation,
                    metadata={**hit.metadata, "context_refined": True},
                )
            )
        if len(hits) > len(refined_hits):
            refined_hits.extend(compact_hit(hit) for hit in hits[len(refined_hits):])
        return refined_hits

    def _merge_results(
        self,
        vector_results: list[VectorSearchResult],
        keyword_results: list[VectorSearchResult],
        top_k: int,
        mode: str,
    ) -> list[RetrievalHit]:
        vector_norm = normalize_scores(vector_results)
        keyword_norm = normalize_scores(keyword_results)
        merged: dict[str, dict] = {}

        for result in vector_results:
            merged[result.chunk_id] = {
                "result": result,
                "vector_score": vector_norm.get(result.chunk_id, result.score),
                "keyword_score": None,
            }

        for result in keyword_results:
            entry = merged.setdefault(
                result.chunk_id,
                {"result": result, "vector_score": None, "keyword_score": None},
            )
            entry["keyword_score"] = keyword_norm.get(result.chunk_id, result.score)

        hits: list[RetrievalHit] = []
        for chunk_id, entry in merged.items():
            result: VectorSearchResult = entry["result"]
            vector_score = entry["vector_score"]
            keyword = entry["keyword_score"]
            if mode == "vector":
                combined = vector_score or 0.0
            elif mode == "keyword":
                combined = keyword or 0.0
            else:
                combined = self.settings.vector_weight * (vector_score or 0.0) + self.settings.keyword_weight * (keyword or 0.0)
                combined += reciprocal_rank_bonus(entry)
                combined += metadata_boost(result.metadata, self.settings.metadata_boost_weight) if self.settings.metadata_boost_enabled else 0.0
            metadata = result.metadata
            hits.append(
                RetrievalHit(
                    chunkId=chunk_id,
                    text=result.text,
                    score=combined,
                    vectorScore=vector_score,
                    keywordScore=keyword,
                    citation=Citation(
                        docId=metadata.get("doc_id"),
                        chunkId=chunk_id,
                        fileName=metadata.get("file_name"),
                        sourceUri=metadata.get("source_uri"),
                        page=metadata.get("page"),
                    ),
                    metadata=metadata,
                )
            )

        return sorted(hits, key=lambda item: item.score, reverse=True)[:top_k]


def dedupe_hits(hits: list[RetrievalHit], top_k: int) -> list[RetrievalHit]:
    best_by_chunk: dict[str, RetrievalHit] = {}
    for hit in hits:
        current = best_by_chunk.get(hit.chunk_id)
        if current is None or hit.score > current.score:
            best_by_chunk[hit.chunk_id] = hit
    return sorted(best_by_chunk.values(), key=lambda item: item.score, reverse=True)[:top_k]


def dedupe_warnings(warnings: list[str]) -> list[str]:
    return list(dict.fromkeys(warning for warning in warnings if warning))


def child_search_top_k(top_k: int, child_chunks_per_parent: int) -> int:
    return max(top_k * max(child_chunks_per_parent, 1) * 2, top_k)


def retrieval_candidate_top_k(top_k: int, settings: Settings) -> int:
    child_top_k = child_search_top_k(top_k, settings.child_chunks_per_parent)
    multiplied = child_top_k * max(settings.retrieval_candidate_multiplier, 1)
    rerank_floor = settings.rerank_top_n if settings.rerank_enabled else 0
    return max(child_top_k, multiplied, rerank_floor)


def parent_candidate_top_k(top_k: int, settings: Settings) -> int:
    if not settings.rerank_enabled:
        return top_k
    per_parent = max(settings.child_chunks_per_parent, 1)
    return max(top_k, min(settings.rerank_top_n, top_k * max(settings.retrieval_candidate_multiplier, 1)) // per_parent)


def expanded_search_queries(original_query: str, retrieval_query: str, max_queries: int) -> list[str]:
    if max_queries <= 1:
        return list(dict.fromkeys(query for query in [retrieval_query, original_query] if query))[:1]
    queries = [retrieval_query, original_query]
    for token in query_keywords(f"{original_query} {retrieval_query}"):
        queries.append(token)
    return list(dict.fromkeys(query for query in queries if query))[: max(max_queries, 1)]


def query_keywords(text: str) -> list[str]:
    terms = [term for term in tokenize(text) if len(term) >= 2]
    preferred = [term for term in terms if len(term) >= 4 or re.fullmatch(r"[\u4e00-\u9fff]{2,}", term)]
    return preferred[:4]


def tag_query_results(results: list[VectorSearchResult], query_index: int, query: str) -> list[VectorSearchResult]:
    tagged: list[VectorSearchResult] = []
    for rank, result in enumerate(results, start=1):
        metadata = {
            **result.metadata,
            "query_variant": query,
            "query_variant_index": query_index,
            "query_variant_rank": rank,
        }
        tagged.append(VectorSearchResult(chunk_id=result.chunk_id, text=result.text, metadata=metadata, score=result.score))
    return tagged


def fuse_search_results(results: list[VectorSearchResult], top_k: int) -> list[VectorSearchResult]:
    best: dict[str, VectorSearchResult] = {}
    fused_scores: dict[str, float] = {}
    variants: dict[str, set[str]] = {}
    for result in results:
        rank = int(result.metadata.get("query_variant_rank") or 999)
        variant = str(result.metadata.get("query_variant") or "")
        fused_scores[result.chunk_id] = fused_scores.get(result.chunk_id, 0.0) + result.score + (1.0 / (60.0 + rank))
        variants.setdefault(result.chunk_id, set()).add(variant)
        current = best.get(result.chunk_id)
        if current is None or result.score > current.score:
            best[result.chunk_id] = result
    fused: list[VectorSearchResult] = []
    for chunk_id, result in best.items():
        metadata = {**result.metadata, "query_variant_count": len([item for item in variants.get(chunk_id, set()) if item])}
        fused.append(VectorSearchResult(chunk_id=chunk_id, text=result.text, metadata=metadata, score=fused_scores[chunk_id]))
    return sorted(fused, key=lambda item: item.score, reverse=True)[:top_k]


def reciprocal_rank_bonus(entry: dict) -> float:
    result: VectorSearchResult = entry["result"]
    variant_count = int(result.metadata.get("query_variant_count") or 0)
    cross_channel_bonus = 0.04 if entry.get("vector_score") is not None and entry.get("keyword_score") is not None else 0.0
    return min(variant_count, 3) * 0.015 + cross_channel_bonus


def metadata_boost(metadata: dict, weight: float) -> float:
    useful_fields = ("file_name", "section_title", "section_path", "keywords", "sheet", "row", "page")
    present = sum(1 for key in useful_fields if metadata.get(key) not in (None, ""))
    return min(max(weight, 0.0), 0.5) * min(present / 4.0, 1.0)


def parent_context_filter(metadata_filter: dict) -> dict:
    return {key: value for key, value in (metadata_filter or {}).items() if key != "chunk_type"}


def compact_hit(hit: RetrievalHit) -> RetrievalHit:
    parent_text = str(hit.metadata.get("parent_text") or "")
    compacted = compact_text(hit.text, 900)
    if parent_text and parent_text != hit.text:
        compacted = f"{compacted}\nParent context: {compact_text(parent_text, 700)}"
    return RetrievalHit(
        chunkId=hit.chunk_id,
        text=compacted,
        score=hit.score,
        vectorScore=hit.vector_score,
        keywordScore=hit.keyword_score,
        citation=hit.citation,
        metadata={**hit.metadata, "context_refined": False, "context_refinement_fallback": "local"},
    )


def compact_text(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def evidence_fallback_answer(hits: list[RetrievalHit], exc: Exception) -> str:
    lines = [
        "Knowledge retrieval completed, but generation is temporarily unavailable. Returning the retrieved evidence summary first.",
        f"Generation failure reason: {exc}",
    ]
    for index, hit in enumerate(hits[:5], start=1):
        title = hit.citation.file_name or hit.citation.doc_id or "unknown source"
        preview = compact_text(hit.text, 220)
        lines.append(f"[{index}] {title}, score {hit.score:.3f}: {preview}")
    return "\n".join(lines)


GREETINGS = {
    "hi",
    "hello",
    "hey",
    "你好",
    "您好",
    "在吗",
    "谢谢",
    "感谢",
    "ok",
    "好的",
    "嗯",
}
PRONOUN_PATTERN = re.compile(r"(这个|那个|它|他|她|它们|他们|她们|这些|那些|上述|前面|刚才|之前|请问|怎么做|怎么弄|如何处理)")


def should_rewrite_query(query: str, history: list[dict[str, str]] | None, min_chars: int) -> bool:
    normalized = "".join(str(query or "").split()).lower()
    if not normalized or normalized in GREETINGS:
        return False
    if not history:
        return False
    if PRONOUN_PATTERN.search(query):
        return len(normalized) >= 4
    if len(normalized) < min_chars:
        return False
    return len(normalized) <= 24 and any(mark in query for mark in {"?", "？", "吗", "呢"})


def valid_rewritten_query(original: str, rewritten: str) -> bool:
    value = " ".join(str(rewritten or "").split())
    if len(value) < 4:
        return False
    if len(value) > 500:
        return False
    if value.strip().lower() in GREETINGS:
        return False
    if value == original:
        return False
    return True
