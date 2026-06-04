import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.schemas.rag import ChatAskRequest, ChatAskResponse, ChatCitation, ChatTrace, RetrievalQuery, RetrievalResponse
from app.services.factory import get_retrieval_service

router = APIRouter(prefix="/rag", tags=["rag"])
logger = logging.getLogger(__name__)


@router.post("/query", response_model=RetrievalResponse)
async def query_rag(request: RetrievalQuery) -> RetrievalResponse:
    return await get_retrieval_service().retrieve(request)


@router.post("/chat/ask", response_model=ChatAskResponse)
async def ask_chat(request: ChatAskRequest) -> ChatAskResponse:
    started = time.perf_counter()
    kb_ids = request.knowledge_base_ids or [request.knowledge_base if request.knowledge_base != "all" else "default"]
    response = await get_retrieval_service().retrieve_many(
        RetrievalQuery(
            tenantId=request.tenant_id,
            kbId=request.knowledge_base,
            query=request.question,
            topK=request.top_k,
            includeAnswer=True,
            mode="hybrid",
            history=request.history,
            context=request.context,
            contextWindowTokens=request.context_window_tokens,
            tokenBudget=request.token_budget,
            contextCompressed=request.context_compressed,
            contextSummary=request.context_summary,
            deepThinking=request.deep_thinking,
            scoreThreshold=request.score_threshold,
            embeddingProvider=request.embedding_provider,
            embeddingModel=request.embedding_model,
            embeddingBaseUrl=request.embedding_base_url,
            embeddingApiKey=request.embedding_api_key,
            embeddingTruncate=request.embedding_truncate,
            rerankModel=request.rerank_model,
            rerankBaseUrl=request.rerank_base_url,
            rerankApiKey=request.rerank_api_key,
        ),
        kb_ids=kb_ids,
        provider=request.provider,
        model=request.model,
        base_url=request.base_url,
        api_key=request.api_key,
        rerank_model=request.rerank_model,
        rerank_base_url=request.rerank_base_url,
        rerank_api_key=request.rerank_api_key,
        temperature=request.temperature,
        top_p=request.top_p,
    )
    retrieval_ms = int((time.perf_counter() - started) * 1000)
    citations = [
        ChatCitation(
            id=hit.chunk_id,
            title=hit.citation.file_name or hit.citation.doc_id or "unknown",
            page=hit.citation.page,
            score=round(hit.score, 4),
            text=hit.text,
        )
        for hit in response.hits
        if hit.score >= request.score_threshold
    ]
    answer = response.answer or "知识库中没有检索到足够可靠的内容，请补充文档或降低引用阈值后重试。"
    if response.warnings:
        answer = "\n".join([f"检索提示：{warning}" for warning in response.warnings] + ["", answer])
    return ChatAskResponse(
        sessionId=request.session_id,
        answer=answer,
        citations=citations,
        trace=ChatTrace(
            retrievalMs=retrieval_ms,
            rerankMs=response.rerank_ms,
            generationMs=retrieval_ms,
            topK=request.top_k,
        ),
    )


@router.post("/chat/ask/stream")
async def ask_chat_stream(request: ChatAskRequest) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        try:
            started = time.perf_counter()
            kb_ids = request.knowledge_base_ids or [request.knowledge_base if request.knowledge_base != "all" else "default"]
            retrieval_service = get_retrieval_service()
            yield sse_event(
                "status",
                {"type": "status", "sessionId": request.session_id, "message": "模型思考中，正在检索知识库..."},
            )
            if request.deep_thinking:
                yield sse_event(
                    "reasoning",
                    {"type": "reasoning", "sessionId": request.session_id, "reasoning": "正在检索知识库，并准备筛选相关证据。\n"},
                )
            response = await retrieval_service.retrieve_many(
                RetrievalQuery(
                    tenantId=request.tenant_id,
                    kbId=request.knowledge_base,
                    query=request.question,
                    topK=request.top_k,
                    includeAnswer=False,
                    mode="hybrid",
                    history=request.history,
                    context=request.context,
                    contextWindowTokens=request.context_window_tokens,
                    tokenBudget=request.token_budget,
                    contextCompressed=request.context_compressed,
                    contextSummary=request.context_summary,
                    deepThinking=request.deep_thinking,
                    scoreThreshold=request.score_threshold,
                    embeddingProvider=request.embedding_provider,
                    embeddingModel=request.embedding_model,
                    embeddingBaseUrl=request.embedding_base_url,
                    embeddingApiKey=request.embedding_api_key,
                    embeddingTruncate=request.embedding_truncate,
                    rerankModel=request.rerank_model,
                    rerankBaseUrl=request.rerank_base_url,
                    rerankApiKey=request.rerank_api_key,
                ),
                kb_ids=kb_ids,
                provider=request.provider,
                model=request.model,
                base_url=request.base_url,
                api_key=request.api_key,
                rerank_model=request.rerank_model,
                rerank_base_url=request.rerank_base_url,
                rerank_api_key=request.rerank_api_key,
                temperature=request.temperature,
                top_p=request.top_p,
            )
            retrieval_ms = int((time.perf_counter() - started) * 1000)
            citations = chat_citations(response.hits, request.score_threshold)
            answer_parts: list[str] = []
            generation_started = time.perf_counter()
            for warning in response.warnings:
                yield sse_event(
                    "status",
                    {"type": "status", "sessionId": request.session_id, "message": warning},
                )
            yield sse_event(
                "status",
                {"type": "status", "sessionId": request.session_id, "message": "已完成检索，正在整理证据..."},
            )

            if request.deep_thinking:
                async for reasoning in retrieval_reasoning_chunks(response.hits, request.score_threshold, retrieval_ms):
                    yield sse_event(
                        "reasoning",
                        {"type": "reasoning", "sessionId": request.session_id, "reasoning": reasoning},
                    )

            trusted_hits = [hit for hit in response.hits if hit.score >= request.score_threshold]
            yield sse_event(
                "status",
                {"type": "status", "sessionId": request.session_id, "message": "正在调用模型生成回答..."},
            )

            try:
                async for chunk in retrieval_service.generator.stream_generate(
                    request.question,
                    trusted_hits,
                    request.history,
                    request.context,
                    context_summary=request.context_summary,
                    context_compressed=request.context_compressed,
                    token_budget=request.token_budget,
                    context_window_tokens=request.context_window_tokens,
                    provider=request.provider,
                    model=request.model,
                    base_url=request.base_url,
                    api_key=request.api_key,
                    temperature=request.temperature,
                    top_p=request.top_p,
                    deep_thinking=request.deep_thinking,
                ):
                    text = chunk.get("text", "")
                    if not text:
                        continue
                    if chunk.get("type") == "reasoning" and request.deep_thinking:
                        yield sse_event(
                            "reasoning",
                            {"type": "reasoning", "sessionId": request.session_id, "reasoning": text},
                        )
                    else:
                        answer_parts.append(text)
                        yield sse_event("delta", {"type": "delta", "sessionId": request.session_id, "delta": text})
            except Exception as exc:
                logger.exception(
                    "Streaming generation failed provider=%s model=%s base_url=%s session_id=%s",
                    request.provider,
                    request.model,
                    request.base_url,
                    request.session_id,
                )
                answer = generation_fallback_answer(response.hits, exc)
                yield sse_event(
                    "status",
                    {"type": "status", "sessionId": request.session_id, "message": "模型生成暂不可用，正在返回证据摘要..."},
                )
                for delta in text_chunks(answer):
                    answer_parts.append(delta)
                    yield sse_event("delta", {"type": "delta", "sessionId": request.session_id, "delta": delta})
                    await asyncio.sleep(0)
            answer = "".join(answer_parts).strip()
            if not answer:
                answer = "知识库中没有检索到足够可靠的内容，请补充文档或降低引用阈值后重试。"
                for delta in text_chunks(answer):
                    yield sse_event("delta", {"type": "delta", "sessionId": request.session_id, "delta": delta})
                    await asyncio.sleep(0)

            trace = ChatTrace(
                retrievalMs=retrieval_ms,
                rerankMs=response.rerank_ms,
                generationMs=int((time.perf_counter() - generation_started) * 1000),
                topK=request.top_k,
            )
            yield sse_event(
                "done",
                {
                    "type": "done",
                    "sessionId": request.session_id,
                    "answer": answer,
                    "citations": [item.model_dump(by_alias=True) for item in citations],
                    "trace": trace.model_dump(by_alias=True),
                },
            )
        except Exception as exc:
            yield sse_event("error", {"type": "error", "sessionId": request.session_id, "message": str(exc)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def chat_citations(hits, score_threshold: float) -> list[ChatCitation]:
    return [
        ChatCitation(
            id=hit.chunk_id,
            title=hit.citation.file_name or hit.citation.doc_id or "unknown",
            page=hit.citation.page,
            score=round(hit.score, 4),
            text=hit.text,
        )
        for hit in hits
        if hit.score >= score_threshold
    ]


def sse_event(event_type: str, payload: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def text_chunks(value: str, size: int = 8):
    for index in range(0, len(value), size):
        yield value[index:index + size]


def generation_fallback_answer(hits, exc: Exception) -> str:
    lines = [
        "已完成知识库检索，但外部模型生成暂时不可用，因此先返回检索证据摘要。",
        f"生成失败原因：{exc}",
    ]
    for index, hit in enumerate(hits[:3], start=1):
        title = hit.citation.file_name or hit.citation.doc_id or "未知来源"
        preview = " ".join(str(hit.text or "").split())[:160]
        lines.append(f"{index}. {title}（相关度 {hit.score:.3f}）：{preview}")
    return "\n".join(lines)


async def retrieval_reasoning_chunks(hits, score_threshold: float, retrieval_ms: int):
    if not hits:
        lines = [
            f"已完成知识库检索，用时约 {retrieval_ms} ms。",
            "没有检索到可用于回答的候选片段，将返回知识库依据不足的提示。",
        ]
    else:
        usable_hits = [hit for hit in hits if hit.score >= score_threshold]
        top_hits = usable_hits[:3] or hits[:3]
        lines = [
            f"已完成知识库检索，用时约 {retrieval_ms} ms，找到 {len(hits)} 个候选片段。",
            f"按相似度阈值筛选后，优先检查 {len(top_hits)} 个高相关片段。",
        ]
        for index, hit in enumerate(top_hits, start=1):
            title = hit.citation.file_name or hit.citation.doc_id or "未知来源"
            preview = " ".join(str(hit.text or "").split())[:72]
            lines.append(f"{index}. {title}，相关度 {hit.score:.3f}：{preview}")
        lines.append("接下来将基于这些证据生成最终回答，并在答案中保留引用。")
    for line in lines:
        yield line + "\n"
        await asyncio.sleep(0)
