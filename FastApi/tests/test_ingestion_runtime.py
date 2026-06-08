import importlib
import importlib.util
import unittest
from unittest.mock import patch

from app.core.config import Settings
from app.langchain_modules.model_io.embeddings import NvidiaEmbeddingProvider
from app.langchain_modules.retrieval.vector_store import batched as vector_batches, milvus_search_params
from app.schemas.documents import DocumentIngestJob
from app.services import factory
from app.services.java_callback import JavaDocumentStatusCallback
from app.services.mysql_repository import batched as mysql_batches, mysql_connection_kwargs


def has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


class IngestionBatchingTests(unittest.TestCase):
    @unittest.skipIf(
        not has_module("langchain_community.vectorstores.milvus"),
        "langchain_community Milvus vector store is not installed",
    )
    def test_milvus_vectorstore_dependency_exports_milvus(self):
        module = importlib.import_module("langchain_community.vectorstores.milvus")

        self.assertTrue(hasattr(module, "Milvus"))

    def test_batch_helpers_split_long_inputs(self):
        items = [{"id": str(index)} for index in range(5)]

        self.assertEqual(
            vector_batches(items, 2),
            [items[:2], items[2:4], items[4:]],
        )
        self.assertEqual(
            list(mysql_batches(items, 3)),
            [items[:3], items[3:]],
        )

    def test_mysql_connection_omits_unsupported_read_and_write_timeouts(self):
        settings = Settings(
            mysql_dsn="mysql+aiomysql://user:pass@db.example.test:3307/rag",
            mysql_read_timeout_seconds=41,
            mysql_write_timeout_seconds=43,
        )

        kwargs = mysql_connection_kwargs(settings)

        self.assertEqual(kwargs["connect_timeout"], settings.mysql_connect_timeout_seconds)
        self.assertNotIn("read_timeout", kwargs)
        self.assertNotIn("write_timeout", kwargs)

    def test_milvus_hnsw_search_ef_grows_with_top_k(self):
        settings = Settings(
            milvus_index_type="HNSW",
            milvus_metric_type="L2",
            milvus_search_ef=128,
        )

        params = milvus_search_params(settings, top_k=360)

        self.assertEqual(params["metric_type"], "L2")
        self.assertEqual(params["params"]["ef"], 376)

    def test_dynamic_vector_store_cache_evicts_least_recent_config(self):
        settings = Settings(dynamic_vector_store_cache_max_items=2)
        created = []

        def fake_create_vector_store(scoped_settings, embedding_provider):
            store = {"model": scoped_settings.nvidia_embedding_model}
            created.append(store)
            return store

        factory._dynamic_vector_stores.clear()
        with (
            patch.object(factory, "get_settings", return_value=settings),
            patch.object(factory, "create_embedding_provider", side_effect=lambda scoped_settings: object()),
            patch.object(factory, "create_vector_store", side_effect=fake_create_vector_store),
        ):
            first = factory.resolve_vector_store_from_embedding_config("nvidia", "model-a", None, None, None)
            factory.resolve_vector_store_from_embedding_config("nvidia", "model-b", None, None, None)

            self.assertIs(first, factory.resolve_vector_store_from_embedding_config("nvidia", "model-a", None, None, None))

            factory.resolve_vector_store_from_embedding_config("nvidia", "model-c", None, None, None)

        cached_models = [key[1] for key in factory._dynamic_vector_stores.keys()]
        self.assertEqual(cached_models, ["model-a", "model-c"])
        self.assertEqual([item["model"] for item in created], ["model-a", "model-b", "model-c"])
        factory._dynamic_vector_stores.clear()


class NvidiaEmbeddingBatchingTests(unittest.TestCase):
    def test_parallel_batches_preserve_original_order(self):
        provider = NvidiaEmbeddingProvider(
            base_url="https://example.test/v1",
            api_key="test-key",
            model="test-model",
            truncate="NONE",
            encoding_format="float",
            timeout_seconds=1,
            batch_size=2,
            max_concurrency=2,
            max_retries=1,
            retry_backoff_seconds=0,
            retry_max_backoff_seconds=0,
        )
        vectors_by_text = {
            "t0": [1.0, 0.0],
            "t1": [0.0, 1.0],
            "t2": [-1.0, 0.0],
            "t3": [0.0, -1.0],
            "t4": [1.0, 1.0],
        }
        calls = []

        def fake_embed_batch(texts, input_type):
            calls.append((tuple(texts), input_type))
            return [vectors_by_text[text] for text in texts]

        provider._embed_batch = fake_embed_batch

        vectors = provider.embed_documents(["t0", "t1", "t2", "t3", "t4"])

        self.assertEqual(len(calls), 3)
        self.assertEqual(vectors[0], [1.0, 0.0])
        self.assertEqual(vectors[1], [0.0, 1.0])
        self.assertEqual(vectors[2], [-1.0, 0.0])
        self.assertEqual(vectors[3], [0.0, -1.0])
        self.assertAlmostEqual(vectors[4][0], 0.707106, places=5)
        self.assertAlmostEqual(vectors[4][1], 0.707106, places=5)


class JavaCallbackStatusTests(unittest.TestCase):
    def test_notify_running_posts_running_payload(self):
        class CapturingCallback(JavaDocumentStatusCallback):
            def __init__(self):
                super().__init__(Settings())
                self.payload = None

            def _post(self, payload):
                self.payload = payload

        callback = CapturingCallback()
        job = DocumentIngestJob(tenantId="tenant-1", kbId="kb-1", docId="doc-1")

        callback.notify_running(job)

        self.assertEqual(
            callback.payload,
            {
                "tenantId": "tenant-1",
                "docId": "doc-1",
                "status": "running",
                "chunkCount": 0,
                "errorMessage": None,
            },
        )


if __name__ == "__main__":
    unittest.main()
