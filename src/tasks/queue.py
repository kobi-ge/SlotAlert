import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, Optional

from src.database.connection import get_redis_client

logger = logging.getLogger("slotalert.queue")

QUEUE_KEY = "slotalert:task_queue"


class RedisTaskQueue:
    """Lightweight, native Redis-backed asynchronous task queue runner."""

    def __init__(self, queue_key: str = QUEUE_KEY) -> None:
        self.queue_key = queue_key
        self._handlers: Dict[str, Callable[..., Coroutine[Any, Any, Any]]] = {}
        self._worker_task: Optional[asyncio.Task] = None
        self._running = False

    def register_task(self, name: str, func: Callable[..., Coroutine[Any, Any, Any]]) -> None:
        """Register an async function as a task handler."""
        self._handlers[name] = func
        logger.info(f"Registered task handler: '{name}'")

    async def enqueue(self, task_name: str, **kwargs: Any) -> str:
        """Enqueue a task payload to Redis."""
        if task_name not in self._handlers:
            logger.warning(f"Enqueuing task '{task_name}' which has no locally registered handler.")

        task_id = str(uuid.uuid4())
        payload = {
            "task_id": task_id,
            "task_name": task_name,
            "kwargs": kwargs,
            "enqueued_at": datetime.now(timezone.utc).isoformat(),
        }

        redis = get_redis_client()
        await redis.rpush(self.queue_key, json.dumps(payload))
        logger.info(f"Enqueued task '{task_name}' (ID: {task_id})")
        return task_id

    async def process_one_job(self, timeout: float = 1.0) -> bool:
        """Pop and execute a single job from the queue. Returns True if job was processed."""
        try:
            redis = get_redis_client()
            # BLPOP returns tuple: (queue_name, item)
            item = await redis.blpop(self.queue_key, timeout=timeout)
            if not item:
                return False

            _, raw_payload = item
            data = json.loads(raw_payload)
            task_id = data["task_id"]
            task_name = data["task_name"]
            kwargs = data.get("kwargs", {})

            handler = self._handlers.get(task_name)
            if not handler:
                logger.error(f"No handler registered for task '{task_name}' (ID: {task_id})")
                return True

            logger.info(f"Executing task '{task_name}' (ID: {task_id})")
            await handler(**kwargs)
            logger.info(f"Finished task '{task_name}' (ID: {task_id})")
            return True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(f"Error processing job from queue: {exc}")
            return False

    async def _worker_loop(self) -> None:
        """Continuous worker execution loop."""
        logger.info("Background queue worker loop started.")
        while self._running:
            try:
                await self.process_one_job(timeout=0.5)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Worker loop error: {exc}")
                await asyncio.sleep(0.5)
        logger.info("Background queue worker loop stopped.")

    def start_worker(self) -> asyncio.Task:
        """Start background worker task."""
        if not self._running:
            self._running = True
            self._worker_task = asyncio.create_task(self._worker_loop())
        return self._worker_task

    async def stop_worker(self) -> None:
        """Gracefully stop background worker task."""
        self._running = False
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None


# Global queue singleton
task_queue = RedisTaskQueue()
