"""
v4.37: Batch Scheduler — async priority task queue for AI workloads.

Enables submitting multiple LLM/agent tasks asynchronously:
  - Priority queue with configurable concurrency
  - Per-task status tracking (pending → running → done/error)
  - Cancellation support
  - Result retrieval by task_id

API:
  POST /pipeline/batch/submit  — Submit batch of tasks
  GET  /pipeline/batch/status/{task_id} — Query individual task
  GET  /pipeline/batch/queue   — Current queue state
  DELETE /pipeline/batch/cancel/{task_id} — Cancel pending task
"""
import asyncio, time, uuid, logging
from typing import Any, Callable, Dict, List, Optional, Awaitable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger("gw.batch-scheduler")


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class BatchTask:
    """A single task in the batch queue."""
    task_id: str
    priority: int = 0  # Lower = higher priority
    status: TaskStatus = TaskStatus.PENDING
    description: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Any = None
    error: Optional[str] = None
    _coro: Optional[Awaitable] = field(default=None, repr=False)


class BatchScheduler:
    """Async priority task queue with concurrency control.

    Usage:
        scheduler = BatchScheduler(max_concurrent=3)
        task_id = await scheduler.submit("Analyze 1000 FITS", priority=1, coro=process_batch())
        result = await scheduler.get_result(task_id)
    """

    def __init__(self, max_concurrent: int = 3):
        self._max_concurrent = max_concurrent
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._tasks: Dict[str, BatchTask] = {}
        self._running: Dict[str, asyncio.Task] = {}
        self._running_count = 0
        self._lock = asyncio.Lock()
        self._worker_task: Optional[asyncio.Task] = None
        self._stats = {
            "total_submitted": 0,
            "total_completed": 0,
            "total_errored": 0,
            "total_cancelled": 0,
        }

    # ── Public API ──────────────────────────────────────────────────────────

    async def submit(self, description: str, coro: Awaitable,
                     priority: int = 0, task_id: str = None) -> str:
        """Submit a task to the queue.

        Args:
            description: Human-readable task description
            coro: Awaitable to execute
            priority: Lower number = higher priority (0 = default)
            task_id: Optional custom ID (auto-generated if not provided)

        Returns:
            task_id for status/result queries
        """
        task_id = task_id or f"batch_{uuid.uuid4().hex[:12]}"

        task = BatchTask(
            task_id=task_id,
            priority=priority,
            description=description,
            _coro=coro,
        )

        async with self._lock:
            self._tasks[task_id] = task
            self._stats["total_submitted"] += 1

        # Push to priority queue: (priority, insertion_order, task)
        # Using timestamp as tiebreaker for FIFO within same priority
        await self._queue.put((priority, time.monotonic(), task_id))

        # Ensure worker is running
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker_loop())

        logger.info(f"Batch task submitted: {task_id} — {description}")
        return task_id

    async def get_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get the current status of a task.

        Args:
            task_id: Task identifier

        Returns:
            Task status dict or None if not found.
        """
        task = self._tasks.get(task_id)
        if not task:
            return None

        return {
            "task_id": task.task_id,
            "status": task.status.value,
            "priority": task.priority,
            "description": task.description,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
            "error": task.error,
        }

    async def get_result(self, task_id: str, timeout: float = None) -> Any:
        """Wait for and return a task's result.

        Args:
            task_id: Task identifier
            timeout: Max seconds to wait (None = wait forever)

        Returns:
            Task result value

        Raises:
            ValueError: If task not found
            TimeoutError: If timeout exceeded
            Exception: If the task raised an exception
        """
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        deadline = time.monotonic() + timeout if timeout else None

        while task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            if deadline and time.monotonic() > deadline:
                raise TimeoutError(f"Task {task_id} did not complete within {timeout}s")
            await asyncio.sleep(0.5)

        if task.status == TaskStatus.ERROR:
            raise RuntimeError(f"Task {task_id} failed: {task.error}")
        if task.status == TaskStatus.CANCELLED:
            raise RuntimeError(f"Task {task_id} was cancelled")

        return task.result

    async def cancel(self, task_id: str) -> bool:
        """Cancel a pending task.

        Args:
            task_id: Task identifier

        Returns:
            True if cancelled, False if already running/completed.
        """
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False

            if task.status == TaskStatus.PENDING:
                task.status = TaskStatus.CANCELLED
                task.completed_at = datetime.utcnow().isoformat()
                self._stats["total_cancelled"] += 1
                logger.info(f"Task cancelled: {task_id}")
                return True

            if task.status == TaskStatus.RUNNING:
                # Try to cancel the asyncio task
                running = self._running.get(task_id)
                if running and not running.done():
                    running.cancel()
                    task.status = TaskStatus.CANCELLED
                    self._stats["total_cancelled"] += 1
                    return True

            return False

    async def get_queue_state(self) -> Dict[str, Any]:
        """Get current queue statistics and task list.

        Returns:
            Dict with queue stats, running tasks, and pending count.
        """
        async with self._lock:
            pending = sum(
                1 for t in self._tasks.values()
                if t.status == TaskStatus.PENDING
            )
            running = sum(
                1 for t in self._tasks.values()
                if t.status == TaskStatus.RUNNING
            )
            recent = []
            for t in sorted(
                self._tasks.values(),
                key=lambda x: x.created_at, reverse=True
            )[:20]:
                recent.append({
                    "task_id": t.task_id,
                    "status": t.status.value,
                    "description": t.description,
                    "created_at": t.created_at,
                })

        return {
            "pending": pending,
            "running": running,
            "max_concurrent": self._max_concurrent,
            "stats": dict(self._stats),
            "recent_tasks": recent,
        }

    # ── Internal Worker ─────────────────────────────────────────────────────

    async def _worker_loop(self) -> None:
        """Main worker loop — processes tasks from the priority queue."""
        logger.info(f"Batch scheduler worker started (max_concurrent={self._max_concurrent})")

        while True:
            # Check if queue is empty
            if self._queue.empty() and self._running_count == 0:
                # No work — exit worker (restarted on next submit)
                logger.debug("Batch worker idle — exiting")
                return

            try:
                # Wait for a task (with timeout to check for shutdown)
                priority, ts, task_id = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue

            # Wait for concurrency slot
            while self._running_count >= self._max_concurrent:
                await asyncio.sleep(0.5)

            task = self._tasks.get(task_id)
            if not task or task.status == TaskStatus.CANCELLED:
                self._queue.task_done()
                continue

            # Start execution
            async with self._lock:
                task.status = TaskStatus.RUNNING
                task.started_at = datetime.utcnow().isoformat()
                self._running_count += 1

            logger.debug(f"Batch task running: {task_id} (running={self._running_count})")

            # Run in background
            asyncio_task = asyncio.create_task(self._execute_one(task))
            self._running[task_id] = asyncio_task

    async def _execute_one(self, task: BatchTask) -> None:
        """Execute a single task and record the result."""
        try:
            if task._coro is not None:
                result = await task._coro
            else:
                result = None

            async with self._lock:
                task.status = TaskStatus.DONE
                task.result = result
                task.completed_at = datetime.utcnow().isoformat()
                self._stats["total_completed"] += 1
                self._running_count = max(0, self._running_count - 1)

            logger.info(f"Batch task done: {task.task_id}")

        except asyncio.CancelledError:
            async with self._lock:
                task.status = TaskStatus.CANCELLED
                task.completed_at = datetime.utcnow().isoformat()
                self._stats["total_cancelled"] += 1
                self._running_count = max(0, self._running_count - 1)

        except Exception as e:
            async with self._lock:
                task.status = TaskStatus.ERROR
                task.error = f"{type(e).__name__}: {str(e)}"
                task.completed_at = datetime.utcnow().isoformat()
                self._stats["total_errored"] += 1
                self._running_count = max(0, self._running_count - 1)

            logger.error(f"Batch task error: {task.task_id} — {task.error}")

        finally:
            # Clean up running tracker
            self._running.pop(task.task_id, None)
            self._queue.task_done()


# ── Module-level singleton ─────────────────────────────────────────────────
_scheduler: Optional[BatchScheduler] = None


def get_scheduler(max_concurrent: int = None) -> BatchScheduler:
    """Get or create the global BatchScheduler singleton."""
    global _scheduler
    if _scheduler is None:
        _scheduler = BatchScheduler(
            max_concurrent=max_concurrent or int(os.getenv("BATCH_MAX_CONCURRENT", "3"))
        )
    return _scheduler
