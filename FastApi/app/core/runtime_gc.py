import asyncio
import ctypes
import gc
import logging
from contextlib import suppress

from app.core.config import Settings

logger = logging.getLogger(__name__)


def collect_runtime_memory(settings: Settings) -> int:
    collected = gc.collect()
    if settings.runtime_malloc_trim_enabled:
        _malloc_trim()
    return collected


def start_periodic_gc(settings: Settings) -> asyncio.Task[None] | None:
    if not settings.runtime_gc_enabled:
        return None
    interval = max(int(settings.runtime_gc_interval_seconds), 30)
    return asyncio.create_task(_periodic_gc(settings, interval), name="runtime-gc")


async def stop_periodic_gc(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def _periodic_gc(settings: Settings, interval: int) -> None:
    while True:
        await asyncio.sleep(interval)
        collected = await asyncio.to_thread(collect_runtime_memory, settings)
        if settings.runtime_gc_log_enabled:
            logger.info("Runtime GC collected=%s malloc_trim=%s", collected, settings.runtime_malloc_trim_enabled)


def _malloc_trim() -> None:
    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
    except Exception:
        logger.debug("malloc_trim is unavailable on this platform", exc_info=True)
