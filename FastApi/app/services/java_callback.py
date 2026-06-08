import logging
import time
from typing import Any

import httpx

from app.core.config import Settings
from app.schemas.documents import DocumentIngestJob, DocumentIngestResponse

logger = logging.getLogger(__name__)


class JavaDocumentStatusCallback:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def notify_running(self, job: DocumentIngestJob) -> None:
        self._post(
            {
                "tenantId": job.tenant_id,
                "docId": job.doc_id,
                "status": "running",
                "chunkCount": 0,
                "errorMessage": None,
            }
        )

    def notify_success(self, job: DocumentIngestJob, response: DocumentIngestResponse) -> None:
        self._post(
            {
                "tenantId": response.tenant_id,
                "docId": response.doc_id,
                "status": "success",
                "chunkCount": response.chunk_count,
                "errorMessage": None,
            }
        )

    def notify_failure(self, job: DocumentIngestJob, error_message: str) -> None:
        self._post(
            {
                "tenantId": job.tenant_id,
                "docId": job.doc_id,
                "status": "failed",
                "chunkCount": 0,
                "errorMessage": error_message[:1024],
            }
        )

    def _post(self, payload: dict[str, Any]) -> None:
        url = callback_url(self.settings)
        if not url:
            logger.info("Java callback URL is not configured; skipping document status callback.")
            return

        headers: dict[str, str] = {}
        if self.settings.java_callback_token:
            headers[self.settings.java_callback_token_header] = self.settings.java_callback_token

        last_error: Exception | None = None
        attempts = max(self.settings.java_callback_max_attempts, 1)
        for attempt in range(1, attempts + 1):
            try:
                with httpx.Client(timeout=self.settings.java_callback_timeout_seconds) as client:
                    response = client.post(url, json=payload, headers=headers)
                    response.raise_for_status()
                logger.info(
                    "Java callback delivered doc=%s status=%s attempt=%s",
                    payload.get("docId"),
                    payload.get("status"),
                    attempt,
                )
                return
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_error = exc
                logger.warning(
                    "Java callback failed doc=%s status=%s attempt=%s/%s: %s",
                    payload.get("docId"),
                    payload.get("status"),
                    attempt,
                    attempts,
                    exc,
                )
                if attempt < attempts:
                    time.sleep(min(2 ** (attempt - 1), 5))
        if last_error:
            logger.error("Java callback permanently failed doc=%s: %s", payload.get("docId"), last_error)


def callback_url(settings: Settings) -> str | None:
    if settings.java_callback_url:
        return settings.java_callback_url
    if settings.java_callback_base_url:
        return settings.java_callback_base_url.rstrip("/") + "/" + settings.java_callback_path.lstrip("/")
    return None
