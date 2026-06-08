import asyncio
import hashlib
import json
import logging
import signal
from typing import Any

import aio_pika
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.runtime_gc import collect_runtime_memory, start_periodic_gc, stop_periodic_gc
from app.schemas.documents import DocumentIngestJob
from app.services.factory import get_ingestion_service, get_java_callback, get_mysql_repository
from app.langchain_modules.retrieval.vector_store import KnowledgeBaseScope

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")


class RabbitDocumentConsumer:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.connection: Any | None = None
        self.channel: Any | None = None
        self.queue: Any | None = None
        self.consumer_tag: str | None = None
        self.concurrency = max(int(self.settings.rag_ingest_concurrency), 1)
        self.prefetch_count = max(int(self.settings.rabbitmq_prefetch_count or 0), self.concurrency)
        self.semaphore = asyncio.Semaphore(self.concurrency)
        self.tasks: set[asyncio.Task[None]] = set()
        self._stop_event = asyncio.Event()
        self._stopping = False

    async def start(self) -> None:
        self.connection = await aio_pika.connect_robust(self.settings.rabbitmq_url)
        self.channel = await self.connection.channel()
        await self._declare_topology()
        await self.channel.set_qos(prefetch_count=self.prefetch_count)
        self.consumer_tag = await self.queue.consume(self._on_message, no_ack=False)
        logger.info(
            "RabbitMQ async consumer started queue=%s concurrency=%s prefetch=%s",
            self.settings.rabbitmq_queue,
            self.concurrency,
            self.prefetch_count,
        )
        try:
            await self._stop_event.wait()
        finally:
            await self.stop()

    def request_stop(self) -> None:
        self._stopping = True
        self._stop_event.set()

    async def stop(self) -> None:
        self._stopping = True
        if self.queue is not None and self.consumer_tag:
            try:
                await self.queue.cancel(self.consumer_tag)
            except Exception as exc:
                logger.warning("RabbitMQ consumer cancel failed: %s", exc)
            self.consumer_tag = None
        if self.tasks:
            logger.info("Waiting for %s active ingestion task(s) to finish", len(self.tasks))
            await asyncio.gather(*list(self.tasks), return_exceptions=True)
        if self.connection is not None and not self.connection.is_closed:
            await self.connection.close()

    async def _declare_topology(self) -> None:
        if self.channel is None:
            raise RuntimeError("RabbitMQ channel is not initialized.")
        document_exchange = await self.channel.declare_exchange(
            self.settings.rabbitmq_document_exchange,
            type=aio_pika.ExchangeType.DIRECT,
            durable=True,
        )
        dead_letter_exchange = await self.channel.declare_exchange(
            self.settings.rabbitmq_document_dlx,
            type=aio_pika.ExchangeType.DIRECT,
            durable=True,
        )
        dead_letter_queue = await self.channel.declare_queue(
            self.settings.rabbitmq_document_dlq,
            durable=True,
        )
        await dead_letter_queue.bind(
            dead_letter_exchange,
            routing_key=self.settings.rabbitmq_document_dlq_routing_key,
        )
        self.queue = await self.channel.declare_queue(
            self.settings.rabbitmq_queue,
            durable=True,
            arguments={
                "x-dead-letter-exchange": self.settings.rabbitmq_document_dlx,
                "x-dead-letter-routing-key": self.settings.rabbitmq_document_dlq_routing_key,
            },
        )
        await self.queue.bind(
            document_exchange,
            routing_key=self.settings.rabbitmq_document_routing_key,
        )
        logger.info(
            "RabbitMQ topology declared exchange=%s queue=%s dlx=%s dlq=%s",
            self.settings.rabbitmq_document_exchange,
            self.settings.rabbitmq_queue,
            self.settings.rabbitmq_document_dlx,
            self.settings.rabbitmq_document_dlq,
        )

    async def _on_message(self, message: Any) -> None:
        if self._stopping:
            await self._nack(message, requeue=True)
            return
        await self.semaphore.acquire()
        if self._stopping:
            self.semaphore.release()
            await self._nack(message, requeue=True)
            return
        task = asyncio.create_task(self._handle_message(message))
        self.tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task[None]) -> None:
        self.tasks.discard(task)
        self.semaphore.release()
        if task.cancelled():
            return
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            logger.error("Unhandled ingestion task error: %s", exc, exc_info=(type(exc), exc, exc.__traceback__))

    async def _handle_message(self, message: Any) -> None:
        payload: dict[str, Any] | None = None
        job: DocumentIngestJob | None = None
        job_key: str | None = None
        repository = get_mysql_repository()
        callback = get_java_callback()

        try:
            payload = json.loads(message.body.decode("utf-8"))
            job = DocumentIngestJob.model_validate(payload)
            job_key = ingestion_job_key(job, payload)
            scope = KnowledgeBaseScope(tenant_id=job.tenant_id, kb_id=job.kb_id)
            if job.doc_id and await repository.is_document_deleted(scope, job.doc_id):
                logger.info(
                    "Skipping deleted ingestion job tenant=%s kb=%s doc=%s job=%s",
                    job.tenant_id,
                    job.kb_id,
                    job.doc_id,
                    job_key,
                )
                await self._ack(message)
                return
            decision = await repository.begin_job(
                job_key=job_key,
                tenant_id=job.tenant_id,
                kb_id=job.kb_id,
                doc_id=job.doc_id or job_key,
                payload=redact_payload(payload),
                stale_after_seconds=self.settings.rabbitmq_processing_timeout_seconds,
            )
            if decision == "succeeded":
                logger.info("Skipping duplicate completed ingestion job=%s", job_key)
                await self._ack(message)
                return
            if decision == "failed":
                logger.info("Skipping duplicate failed ingestion job=%s", job_key)
                await self._ack(message)
                return
            if decision == "processing":
                if getattr(message, "redelivered", False):
                    logger.warning(
                        "Recovering redelivered in-flight ingestion job=%s after consumer restart",
                        job_key,
                    )
                else:
                    logger.warning("Duplicate in-flight ingestion job=%s acknowledged without reprocessing", job_key)
                    await self._ack(message)
                    return

            await self._notify_running(callback, job)
            response = await get_ingestion_service().ingest(job)
            await repository.complete_job(job_key, response.chunk_count)
            if response.status == "deleted":
                logger.info(
                    "Acknowledged deleted ingestion job without Java success callback tenant=%s kb=%s doc=%s job=%s",
                    response.tenant_id,
                    response.kb_id,
                    response.doc_id,
                    job_key,
                )
                await self._ack(message)
                return
            await self._notify_success(callback, job, response)
            logger.info(
                "Indexed tenant=%s kb=%s doc=%s chunks=%s job=%s",
                response.tenant_id,
                response.kb_id,
                response.doc_id,
                response.chunk_count,
                job_key,
            )
            await self._ack(message)
        except (json.JSONDecodeError, ValidationError, FileNotFoundError, ValueError) as exc:
            logger.exception("Rejecting invalid ingestion message: %s", exc)
            if job and job_key:
                try:
                    await repository.fail_job(job_key, str(exc))
                except Exception as record_exc:
                    logger.exception("Failed to record invalid ingestion job=%s: %s", job_key, record_exc)
                await self._notify_failure(callback, job, str(exc))
            await self._nack(message, requeue=False)
        except Exception as exc:
            logger.exception("Ingestion failed: %s", exc)
            if job and job_key:
                try:
                    attempts = await repository.mark_job_retryable_error(job_key, str(exc))
                except Exception as record_exc:
                    logger.exception("Failed to record retryable ingestion error job=%s: %s", job_key, record_exc)
                    await self._nack(message, requeue=True)
                    return
                if attempts >= self.settings.rabbitmq_max_retries:
                    try:
                        await repository.fail_job(job_key, str(exc))
                    except Exception as record_exc:
                        logger.exception("Failed to mark ingestion job failed job=%s: %s", job_key, record_exc)
                    await self._notify_failure(callback, job, str(exc))
                    await self._nack(message, requeue=False)
                    return
                await asyncio.sleep(min(2 ** max(attempts - 1, 0), 30))
                await self._nack(message, requeue=True)
                return
            await self._nack(message, requeue=False)
        finally:
            if self.settings.runtime_gc_enabled:
                await asyncio.to_thread(collect_runtime_memory, self.settings)

    async def _notify_running(self, callback: Any, job: DocumentIngestJob) -> None:
        try:
            await asyncio.to_thread(callback.notify_running, job)
        except Exception as exc:
            logger.exception("Java running callback failed doc=%s: %s", job.doc_id, exc)

    async def _notify_success(self, callback: Any, job: DocumentIngestJob, response: Any) -> None:
        try:
            await asyncio.to_thread(callback.notify_success, job, response)
        except Exception as exc:
            logger.exception("Java success callback failed after indexing doc=%s: %s", response.doc_id, exc)

    async def _notify_failure(self, callback: Any, job: DocumentIngestJob, error_message: str) -> None:
        try:
            await asyncio.to_thread(callback.notify_failure, job, error_message)
        except Exception as exc:
            logger.exception("Java failure callback failed doc=%s: %s", job.doc_id, exc)

    async def _ack(self, message: Any) -> None:
        try:
            await message.ack()
        except Exception as exc:
            logger.exception("RabbitMQ ack failed: %s", exc)

    async def _nack(self, message: Any, requeue: bool) -> None:
        try:
            await message.nack(requeue=requeue)
        except Exception as exc:
            logger.exception("RabbitMQ nack failed requeue=%s: %s", requeue, exc)


def ingestion_job_key(job: DocumentIngestJob, payload: dict[str, Any]) -> str:
    explicit = payload.get("jobId") or payload.get("job_id") or payload.get("messageId") or payload.get("message_id")
    if explicit:
        return "job:" + stable_digest(str(explicit))
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    doc_id = job.doc_id or job.source_uri or job.file_path or digest
    return "doc:" + stable_digest(f"{job.tenant_id}:{job.kb_id}:{doc_id}")


def stable_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(payload)
    for key in ("apiKey", "api_key", "embeddingApiKey", "embedding_api_key", "rerankApiKey", "rerank_api_key"):
        if redacted.get(key):
            redacted[key] = "[configured]"
    return redacted


def main() -> None:
    consumer = RabbitDocumentConsumer()

    async def run() -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, consumer.request_stop)
            except NotImplementedError:
                signal.signal(sig, lambda signum, frame: loop.call_soon_threadsafe(consumer.request_stop))
        gc_task = start_periodic_gc(consumer.settings)
        try:
            await consumer.start()
        finally:
            await stop_periodic_gc(gc_task)
            collect_runtime_memory(consumer.settings)

    def handle_signal(signum: int, frame: Any) -> None:
        del signum, frame
        consumer.request_stop()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    asyncio.run(run())


if __name__ == "__main__":
    main()
