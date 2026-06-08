import json
import unittest
from unittest.mock import patch

from app.core.config import Settings
from app.langchain_modules.model_io.generation import (
    OllamaGenerationClient,
    final_answer_text,
    format_thinking_mode,
)
from app.schemas.rag import Citation, RetrievalHit


class StreamGenerationRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_reasoning_only_stream_recovers_final_answer_delta(self):
        client = RecoveringClient(Settings(generation_provider="deepseek", deepseek_api_key="test-key"))

        with patch("app.langchain_modules.model_io.generation.httpx.AsyncClient", FakeAsyncClient):
            chunks = [
                item
                async for item in client.stream_generate(
                    "新乡学院主要职责",
                    [hit("新乡学院主要职责包括组织实施高等本、专科学历人才培养。")],
                    deep_thinking=True,
                    provider="deepseek",
                    model="deepseek-reasoner",
                    api_key="test-key",
                )
            ]

        reasoning = "".join(item["text"] for item in chunks if item["type"] == "reasoning")
        answer = "".join(item["text"] for item in chunks if item["type"] == "delta")

        self.assertIn("检查证据", reasoning)
        self.assertIn("新乡学院主要职责包括组织实施高等本、专科学历人才培养", answer)
        self.assertEqual(client.complete_calls, 1)

    def test_deep_thinking_prompt_keeps_final_answer_in_normal_content(self):
        text = format_thinking_mode(True)

        self.assertIn("normal answer content", text)
        self.assertIn("Do not put <think> blocks", text)

    def test_recovered_answer_strips_thinking_blocks(self):
        self.assertEqual(final_answer_text("<think>检查证据</think>\n最终答案"), "最终答案")


    def test_generation_chain_cache_evicts_least_recent_route(self):
        client = CacheClient(
            Settings(generation_provider="ollama", ollama_generation_model="default", generation_chain_cache_max_items=2)
        )

        client.chain(model="model-a")
        client.chain(model="model-b")
        client.chain(model="model-a")
        client.chain(model="model-c")

        cached_models = [key[1] for key in client._chains.keys()]
        self.assertEqual(cached_models, ["model-a", "model-c"])


class CacheClient(OllamaGenerationClient):
    def _create_chain(self, route, temperature, top_p):
        return FakeChain(route["model"])


class FakeChain:
    def __init__(self, model):
        self.model = model

    def run(self, *args, **kwargs):
        return ""


class RecoveringClient(OllamaGenerationClient):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.complete_calls = 0

    async def _complete_openai_compatible(self, route, prompt, temperature, top_p) -> str:
        self.complete_calls += 1
        return "<think>不应返回给用户</think>\n新乡学院主要职责包括组织实施高等本、专科学历人才培养。"


class FakeAsyncClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, *args, **kwargs):
        return FakeStreamResponse()


class FakeStreamResponse:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self):
        payload = {"choices": [{"delta": {"reasoning_content": "检查证据后可以回答。"}}]}
        yield f"data: {json.dumps(payload, ensure_ascii=False)}"
        yield "data: [DONE]"


def hit(text: str) -> RetrievalHit:
    return RetrievalHit(
        chunkId="chunk-1",
        text=text,
        score=0.9,
        citation=Citation(docId="doc-1", chunkId="chunk-1", fileName="新乡学院2024年部门预算公开.pdf"),
        metadata={"chunk_id": "chunk-1", "doc_id": "doc-1"},
    )


if __name__ == "__main__":
    unittest.main()
