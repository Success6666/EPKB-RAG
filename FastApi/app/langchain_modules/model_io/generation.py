import asyncio
import json
from collections import OrderedDict
from hashlib import sha256
from typing import Any, AsyncIterator

import httpx

from app.core.config import Settings
from app.langchain_modules.callbacks.streaming import ThinkingTagParser, safe_emit_length
from app.langchain_modules.memory.conversation_memory import (
    format_context_budget,
    format_context_summary,
    format_history,
    format_runtime_context,
)
from app.langchain_modules.prompts.rag_prompts import (
    GENERATION_PROMPT_TEMPLATE,
    build_generation_prompt,
    format_hits,
    format_thinking_mode,
)
from app.schemas.rag import RetrievalHit


class OllamaGenerationClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = settings.ollama_generation_model
        self.timeout = settings.ollama_timeout_seconds
        self._chains: OrderedDict[
            tuple[str | None, str | None, str | None, bool, float | None, float | None], Any
        ] = OrderedDict()

    def chain(
        self,
        provider: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
    ):
        route = self._resolve_route(provider, model, base_url, api_key)
        key = (route["provider"], route["model"], route["base_url"], key_fingerprint(route["api_key"]), temperature, top_p)
        cached = self._chains.get(key)
        if cached is not None:
            self._chains.move_to_end(key)
            return cached

        max_items = max(1, self.settings.generation_chain_cache_max_items)
        while len(self._chains) >= max_items:
            self._chains.popitem(last=False)

        self._chains[key] = self._create_chain(route, temperature, top_p)
        return self._chains[key]

    def _create_chain(self, route: dict[str, str | None], temperature: float | None, top_p: float | None):
        from langchain.chains import LLMChain
        from langchain.prompts import PromptTemplate

        prompt = PromptTemplate.from_template(GENERATION_PROMPT_TEMPLATE)
        llm = self._create_llm(route, temperature, top_p)
        return LLMChain(llm=llm, prompt=prompt)

    def generate(
        self,
        query: str,
        hits: list[RetrievalHit],
        history: list[dict[str, str]] | None = None,
        runtime_context: str | list[str] | dict[str, Any] | None = None,
        context_summary: str | None = None,
        context_compressed: bool = False,
        token_budget: int | None = None,
        context_window_tokens: int | None = None,
        deep_thinking: bool = False,
        provider: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> str:
        return str(
            self.chain(provider=provider, model=model, base_url=base_url, api_key=api_key, temperature=temperature, top_p=top_p).run(
                question=query,
                context=format_hits(hits),
                history=format_history(history),
                runtime_context=format_runtime_context(runtime_context),
                context_summary=format_context_summary(context_summary),
                context_budget=format_context_budget(context_compressed, token_budget, context_window_tokens),
                thinking_mode=format_thinking_mode(deep_thinking),
            )
        ).strip()

    async def stream_generate(
        self,
        query: str,
        hits: list[RetrievalHit],
        history: list[dict[str, str]] | None = None,
        runtime_context: str | list[str] | dict[str, Any] | None = None,
        context_summary: str | None = None,
        context_compressed: bool = False,
        token_budget: int | None = None,
        context_window_tokens: int | None = None,
        deep_thinking: bool = False,
        provider: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> AsyncIterator[dict[str, str]]:
        route = self._resolve_route(provider, model, base_url, api_key)
        prompt = build_generation_prompt(
            query,
            hits,
            history,
            runtime_context,
            context_summary,
            context_compressed,
            token_budget,
            context_window_tokens,
            deep_thinking,
        )
        recovery_prompt = final_answer_recovery_prompt(
            build_generation_prompt(
                query,
                hits,
                history,
                runtime_context,
                context_summary,
                context_compressed,
                token_budget,
                context_window_tokens,
                False,
            )
        )
        if route["provider"] == "ollama":
            async for chunk in self._stream_ollama(route, prompt, recovery_prompt, temperature, top_p, deep_thinking):
                yield chunk
            return

        async for chunk in self._stream_openai_compatible(route, prompt, recovery_prompt, temperature, top_p, deep_thinking):
            yield chunk

    async def rewrite_query(
        self,
        query: str,
        history: list[dict[str, str]] | None = None,
        provider: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        temperature: float | None = 0.0,
        top_p: float | None = None,
    ) -> str:
        route = self._resolve_route(provider, model, base_url, api_key)
        prompt = (
            "Rewrite the user's latest question into a standalone knowledge-base search query.\n"
            "Keep the original language. Preserve key entities, dates, product names and constraints.\n"
            "Do not answer the question. Do not add facts not present in the user message or conversation history.\n"
            "Return only the rewritten query.\n\n"
            f"Conversation history:\n{format_history(history)}\n\n"
            f"Latest question:\n{query}\n\n"
            "Standalone search query:"
        )
        if route["provider"] == "ollama":
            text = await self._complete_ollama(route, prompt, temperature, top_p)
        else:
            text = await self._complete_openai_compatible(route, prompt, temperature, top_p)
        rewritten = " ".join(text.strip().strip('"').strip("'").split())
        return rewritten[:500]

    async def refine_context(
        self,
        query: str,
        hits: list[RetrievalHit],
        provider: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        temperature: float | None = 0.0,
        top_p: float | None = None,
    ) -> list[str]:
        if not hits:
            return []
        route = self._resolve_route(provider, model, base_url, api_key)
        prompt = (
            "Extract only the evidence that is useful for answering the user question.\n"
            "Use the retrieved child chunks as precise evidence and the parent context only to resolve missing local context.\n"
            "Do not answer the question. Do not add facts. Keep original language.\n"
            "Return a compact numbered evidence list, one item per useful chunk. If a chunk is irrelevant, omit it.\n\n"
            f"Question:\n{query}\n\n"
            f"Retrieved child chunks with parent context:\n{format_hits(hits)}\n\n"
            "Compact evidence:"
        )
        if route["provider"] == "ollama":
            text = await self._complete_ollama(route, prompt, temperature, top_p)
        else:
            text = await self._complete_openai_compatible(route, prompt, temperature, top_p)
        lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
        return lines[: len(hits)]

    async def _stream_ollama(
        self,
        route: dict[str, str | None],
        prompt: str,
        recovery_prompt: str,
        temperature: float | None,
        top_p: float | None,
        deep_thinking: bool,
    ) -> AsyncIterator[dict[str, str]]:
        payload: dict[str, Any] = {
            "model": route["model"],
            "prompt": prompt,
            "stream": True,
        }
        options = generation_options(temperature, top_p)
        if options:
            payload["options"] = options

        timeout = httpx.Timeout(self.timeout, connect=5.0)
        parser = ThinkingTagParser(emit_reasoning=deep_thinking)
        emitted_answer = False
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", f"{route['base_url']}/api/generate", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    token = chunk.get("response") or ""
                    if token:
                        for item in parser.feed(token):
                            emitted_answer = emitted_answer or is_answer_chunk(item)
                            yield item
                for item in parser.flush():
                    emitted_answer = emitted_answer or is_answer_chunk(item)
                    yield item
        if not emitted_answer:
            async for item in self._recover_answer_stream(route, recovery_prompt, temperature, top_p):
                yield item

    async def _complete_ollama(
        self,
        route: dict[str, str | None],
        prompt: str,
        temperature: float | None,
        top_p: float | None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": route["model"],
            "prompt": prompt,
            "stream": False,
        }
        options = generation_options(temperature, top_p)
        if options:
            payload["options"] = options
        timeout = httpx.Timeout(min(self.timeout, 30), connect=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{route['base_url']}/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()
        return str(data.get("response") or "")

    async def _stream_openai_compatible(
        self,
        route: dict[str, str | None],
        prompt: str,
        recovery_prompt: str,
        temperature: float | None,
        top_p: float | None,
        deep_thinking: bool,
    ) -> AsyncIterator[dict[str, str]]:
        payload: dict[str, Any] = {
            "model": route["model"],
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if top_p is not None:
            payload["top_p"] = top_p

        headers = {"Authorization": f"Bearer {route['api_key'] or 'not-needed'}"}
        timeout = httpx.Timeout(self.timeout, connect=5.0)
        url = f"{route['base_url']}/chat/completions"
        for attempt in range(3):
            try:
                parser = ThinkingTagParser(emit_reasoning=deep_thinking)
                emitted_answer = False
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream("POST", url, json=payload, headers=headers) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            data = line.removeprefix("data:").strip()
                            if not data or data == "[DONE]":
                                break
                            chunk = json.loads(data)
                            choice = (chunk.get("choices") or [{}])[0]
                            delta = choice.get("delta") or {}
                            reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
                            if deep_thinking and reasoning:
                                yield {"type": "reasoning", "text": reasoning}
                            token = delta.get("content") or choice.get("text") or ""
                            if token:
                                for item in parser.feed(token):
                                    emitted_answer = emitted_answer or is_answer_chunk(item)
                                    yield item
                        for item in parser.flush():
                            emitted_answer = emitted_answer or is_answer_chunk(item)
                            yield item
                if not emitted_answer:
                    async for item in self._recover_answer_stream(route, recovery_prompt, temperature, top_p):
                        yield item
                return
            except (httpx.ConnectError, httpx.ConnectTimeout):
                if attempt == 2:
                    raise
                await asyncio.sleep(0.25 * (attempt + 1))

    async def _recover_answer_stream(
        self,
        route: dict[str, str | None],
        prompt: str,
        temperature: float | None,
        top_p: float | None,
    ) -> AsyncIterator[dict[str, str]]:
        if not prompt:
            return
        if route["provider"] == "ollama":
            text = await self._complete_ollama(route, prompt, temperature, top_p)
        else:
            text = await self._complete_openai_compatible(route, prompt, temperature, top_p)
        answer = final_answer_text(text)
        if not answer:
            return
        for chunk in text_deltas(answer):
            yield {"type": "delta", "text": chunk}

    async def _complete_openai_compatible(
        self,
        route: dict[str, str | None],
        prompt: str,
        temperature: float | None,
        top_p: float | None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": route["model"],
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if top_p is not None:
            payload["top_p"] = top_p
        headers = {"Authorization": f"Bearer {route['api_key'] or 'not-needed'}"}
        timeout = httpx.Timeout(min(self.timeout, 30), connect=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{route['base_url']}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        return str(message.get("content") or choice.get("text") or "")

    def _create_llm(self, route: dict[str, str | None], temperature: float | None, top_p: float | None):
        if route["provider"] == "ollama":
            from langchain_community.llms import Ollama

            llm_kwargs: dict[str, Any] = {"base_url": route["base_url"], "model": route["model"]}
            model_kwargs: dict[str, Any] = {}
            if temperature is not None:
                model_kwargs["temperature"] = temperature
            if top_p is not None:
                model_kwargs["top_p"] = top_p
            if model_kwargs:
                llm_kwargs["model_kwargs"] = model_kwargs
            return Ollama(**llm_kwargs)

        from langchain_community.chat_models import ChatOpenAI

        llm_kwargs = {
            "openai_api_base": route["base_url"],
            "openai_api_key": route["api_key"] or "not-needed",
            "model_name": route["model"],
            "request_timeout": self.timeout,
        }
        if temperature is not None:
            llm_kwargs["temperature"] = temperature
        if top_p is not None:
            llm_kwargs["model_kwargs"] = {"top_p": top_p}
        return ChatOpenAI(**llm_kwargs)

    def _resolve_route(
        self,
        provider: str | None,
        model: str | None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> dict[str, str | None]:
        requested_provider, requested_model = split_model(provider, model)
        normalized = normalize_provider(requested_provider or self.settings.generation_provider)
        requested_base_url = base_url.rstrip("/") if base_url else None
        requested_api_key = api_key.strip() if api_key else None
        if normalized == "ollama":
            return {
                "provider": "ollama",
                "base_url": requested_base_url or self.base_url,
                "model": requested_model or self._default_model("ollama"),
                "api_key": None,
            }
        if normalized == "deepseek":
            return {
                "provider": "deepseek",
                "base_url": requested_base_url or self.settings.deepseek_base_url.rstrip("/"),
                "model": requested_model or self._default_model("deepseek"),
                "api_key": requested_api_key or self.settings.deepseek_api_key or self.settings.openai_compatible_api_key,
            }
        if normalized in {"dashscope", "tongyi", "qwen-cloud", "aliyun"}:
            return {
                "provider": "dashscope",
                "base_url": requested_base_url or self.settings.dashscope_base_url.rstrip("/"),
                "model": requested_model or self._default_model("dashscope"),
                "api_key": requested_api_key or self.settings.dashscope_api_key or self.settings.openai_compatible_api_key,
            }
        return {
            "provider": "openai-compatible",
            "base_url": requested_base_url or (self.settings.openai_compatible_base_url or self.settings.openai_base_url).rstrip("/"),
            "model": requested_model or self._default_model("openai-compatible"),
            "api_key": requested_api_key or self.settings.openai_compatible_api_key or self.settings.openai_api_key,
        }

    def _default_model(self, provider: str) -> str:
        configured_provider = normalize_provider(self.settings.generation_provider)
        if self.settings.default_chat_model and configured_provider == provider:
            return self.settings.default_chat_model
        if provider == "ollama":
            return self.settings.ollama_generation_model
        if provider == "deepseek":
            return "deepseek-v4-pro"
        if provider == "dashscope":
            return "qwen-plus"
        return self.settings.openai_model


def generation_options(temperature: float | None, top_p: float | None) -> dict[str, float]:
    options: dict[str, float] = {}
    if temperature is not None:
        options["temperature"] = temperature
    if top_p is not None:
        options["top_p"] = top_p
    return options


def is_answer_chunk(item: dict[str, str]) -> bool:
    return item.get("type") == "delta" and bool(str(item.get("text") or "").strip())


def final_answer_recovery_prompt(prompt: str) -> str:
    return (
        f"{prompt}\n\n"
        "Important: Return only the final answer in normal answer text. "
        "Do not include <think> tags, hidden reasoning, analysis notes, or a reasoning-only response. "
        "If the retrieved context is insufficient, say that directly as the final answer."
    )


def final_answer_text(text: str) -> str:
    value = strip_thinking_blocks(str(text or ""))
    return value.strip()


def strip_thinking_blocks(text: str) -> str:
    value = str(text or "")
    while True:
        lowered = value.lower()
        start = lowered.find(ThinkingTagParser.OPEN)
        if start < 0:
            return value
        end = lowered.find(ThinkingTagParser.CLOSE, start + len(ThinkingTagParser.OPEN))
        if end < 0:
            value = value[:start]
            continue
        value = value[:start] + value[end + len(ThinkingTagParser.CLOSE):]


def text_deltas(value: str, size: int = 16):
    text = str(value or "")
    for index in range(0, len(text), size):
        yield text[index:index + size]


def split_model(provider: str | None, model: str | None) -> tuple[str | None, str | None]:
    if provider:
        return provider, model
    if not model:
        return None, None
    for separator in ("/", "::"):
        if separator in model:
            prefix, name = model.split(separator, 1)
            if normalize_provider(prefix) != "openai-compatible" or prefix.lower() in {
                "openai",
                "deepseek",
                "dashscope",
                "tongyi",
                "ollama",
            }:
                return prefix, name
    return None, model


def normalize_provider(provider: str | None) -> str:
    value = (provider or "ollama").strip().lower().replace("_", "-")
    if value in {"local", "ollama"}:
        return "ollama"
    if value in {"deepseek"}:
        return "deepseek"
    if value in {"dashscope", "tongyi", "qwen-cloud", "aliyun", "alibaba"}:
        return "dashscope"
    return "openai-compatible"


def key_fingerprint(api_key: str | None) -> str:
    if not api_key:
        return ""
    return sha256(api_key.encode("utf-8")).hexdigest()[:16]


__all__ = [
    "GENERATION_PROMPT_TEMPLATE",
    "OllamaGenerationClient",
    "ThinkingTagParser",
    "build_generation_prompt",
    "format_context_budget",
    "format_context_summary",
    "format_history",
    "format_hits",
    "format_runtime_context",
    "format_thinking_mode",
    "generation_options",
    "key_fingerprint",
    "normalize_provider",
    "safe_emit_length",
    "split_model",
]
