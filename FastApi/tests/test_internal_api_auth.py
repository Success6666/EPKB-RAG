import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


class InternalApiAuthTests(unittest.TestCase):
    def setUp(self):
        get_settings.cache_clear()

    def tearDown(self):
        get_settings.cache_clear()

    def test_rag_query_requires_internal_token(self):
        client = TestClient(create_app())

        response = client.post(
            "/api/v1/rag/query",
            json={"tenantId": "tenant-1", "kbId": "kb-1", "query": "hello"},
        )

        self.assertEqual(response.status_code, 503)

    def test_rag_query_rejects_invalid_internal_token(self):
        with patch.dict("os.environ", {"INTERNAL_API_TOKEN": "secret"}, clear=False):
            get_settings.cache_clear()
            client = TestClient(create_app())

            response = client.post(
                "/api/v1/rag/query",
                headers={"X-Internal-Token": "wrong"},
                json={"tenantId": "tenant-1", "kbId": "kb-1", "query": "hello"},
            )

        self.assertEqual(response.status_code, 403)

    def test_unprefixed_rag_route_is_not_registered(self):
        client = TestClient(create_app())

        response = client.post(
            "/rag/query",
            headers={"X-Internal-Token": "any"},
            json={"tenantId": "tenant-1", "kbId": "kb-1", "query": "hello"},
        )

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
