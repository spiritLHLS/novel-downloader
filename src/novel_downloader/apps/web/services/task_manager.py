#!/usr/bin/env python3
"""
novel_downloader.apps.web.services.task_manager
-----------------------------------------------

"""

import asyncio
import os
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any

from novel_downloader.infra.config import ConfigAdapter, load_config
from novel_downloader.libs.time_utils import async_jitter_sleep
from novel_downloader.plugins import ClientProtocol, registrar
from novel_downloader.schemas import BookConfig

from ..models import DownloadTask, Status
from ..ui_adapters import WebDownloadUI, WebExportUI, WebLoginUI, WebProcessUI

MAX_COMPLETED_TASKS = 100
_STAGE_RETRY_TIMES = 2
_STAGE_BACKOFF_BASE = 1.0


def _read_env_limit(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
        return max(1, value)
    except ValueError:
        return default


def _is_retryable_stage_error(error: Exception) -> bool:
    return isinstance(error, (TimeoutError, ConnectionError, OSError))


class TaskManager:
    """
    A multi-site task manager:
      * Each site has its own queue and a single worker.
      * Tasks from the same site run sequentially.
      * Tasks from different sites can run in parallel.
      * Workers automatically exit when their site's queue becomes empty.
    """

    def __init__(self) -> None:
        self.pending: dict[str, list[DownloadTask]] = defaultdict(list)
        self.running: dict[str, DownloadTask] = {}
        self.completed: deque[DownloadTask] = deque(maxlen=MAX_COMPLETED_TASKS)

        self._worker_tasks: dict[str, asyncio.Task[None]] = {}

        self._clients: dict[str, ClientProtocol] = {}
        self._closed = False
        self._process_sem = asyncio.Semaphore(
            _read_env_limit("NOVEL_WEB_PROCESS_LIMIT", 2)
        )
        self._export_sem = asyncio.Semaphore(
            _read_env_limit("NOVEL_WEB_EXPORT_LIMIT", 2)
        )

        self._lock = asyncio.Lock()
        self._adapter = ConfigAdapter(load_config())

    # ---------- public API ----------
    async def add_task(self, *, title: str, site: str, book_id: str) -> DownloadTask:
        """
        Add a new task and ensure a worker for its site is running.
        """
        title = title.strip()
        site = site.strip()
        book_id = book_id.strip()
        if not title:
            raise ValueError("title must not be empty")
        if not site:
            raise ValueError("site must not be empty")
        if not book_id:
            raise ValueError("book_id must not be empty")
        if self._closed:
            raise RuntimeError("task manager is closed")

        task = DownloadTask(title=title, site=site, book_id=book_id)
        async with self._lock:
            self.pending[site].append(task)
            # start a new worker if needed
            if site not in self._worker_tasks or self._worker_tasks[site].done():
                self._worker_tasks[site] = asyncio.create_task(self._site_worker(site))
        return task

    async def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a task by id (either pending or currently running).
        """
        async with self._lock:
            # cancel pending
            for queue in self.pending.values():
                for i, pending_task in enumerate(queue):
                    if pending_task.task_id == task_id:
                        pending_task.status = Status.CANCELLED
                        self.completed.append(pending_task)
                        queue.pop(i)
                        return True

            # cancel running
            for running_task in self.running.values():
                if running_task.task_id == task_id:
                    if running_task.status not in {Status.QUEUED, Status.RUNNING}:
                        return False
                    if running_task.asyncio_task:
                        running_task.asyncio_task.cancel()
                    running_task.status = Status.CANCELLED
                    return True
        return False

    def snapshot(self) -> dict[str, list[DownloadTask]]:
        """
        Return a shallow copy of the current queue state (running, pending, completed).
        """
        return {
            "running": list(self.running.values()),
            "pending": [task_item for q in self.pending.values() for task_item in q],
            "completed": list(self.completed),
        }

    def health_snapshot(self) -> dict[str, Any]:
        workers_alive = sum(1 for t in self._worker_tasks.values() if not t.done())
        return {
            "status": "ok",
            "closed": self._closed,
            "workers_alive": workers_alive,
            "pending": sum(len(q) for q in self.pending.values()),
            "running": len(self.running),
            "completed": len(self.completed),
            "clients": len(self._clients),
        }

    def api_snapshot(self) -> dict[str, list[dict[str, Any]]]:
        state = self.snapshot()

        def to_payload(task: DownloadTask) -> dict[str, Any]:
            return {
                "task_id": task.task_id,
                "title": task.title,
                "site": task.site,
                "book_id": task.book_id,
                "status": str(task.status),
                "chapters_total": task.chapters_total,
                "chapters_done": task.chapters_done,
                "error": task.error,
                "exported_paths": {
                    fmt: path.name for fmt, path in task.exported_paths.items()
                },
            }

        return {
            "running": [to_payload(task) for task in state["running"]],
            "pending": [to_payload(task) for task in state["pending"]],
            "completed": [to_payload(task) for task in state["completed"]],
        }

    async def close(self) -> None:
        """Cancel or gracefully finish all workers before shutdown."""
        self._closed = True
        all_tasks = [*self._worker_tasks.values()]

        for worker_task in all_tasks:
            worker_task.cancel()

        results = await asyncio.gather(*all_tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception) and not isinstance(
                result, asyncio.CancelledError
            ):
                print(f"Worker error during shutdown: {result!r}")

        self._worker_tasks.clear()

        client_results = await asyncio.gather(
            *(client.close() for client in self._clients.values()),
            return_exceptions=True,
        )
        for result in client_results:
            if isinstance(result, Exception) and not isinstance(
                result, asyncio.CancelledError
            ):
                print(f"Client error during shutdown: {result!r}")

        self._clients.clear()

    # ---------- internals ----------
    def _get_client(self, site: str) -> ClientProtocol:
        """Get or create a client instance for a site."""
        if site not in self._clients:
            self._clients[site] = registrar.get_client(
                site, self._adapter.get_client_config(site)
            )

        return self._clients[site]

    async def _site_worker(self, site: str) -> None:
        """
        Sequentially run tasks for a specific site until its queue is empty.
        """
        while True:
            async with self._lock:
                if not self.pending[site]:
                    self.running.pop(site, None)
                    self._worker_tasks.pop(site, None)
                    return
                current_task = self.pending[site].pop(0)
                self.running[site] = current_task

            try:
                await self._run_task(current_task)
            except asyncio.CancelledError:
                current_task.status = Status.CANCELLED
                current_task.error = "Cancelled by user"
            except Exception as e:
                current_task.status = Status.FAILED
                current_task.error = str(e)
            finally:
                async with self._lock:
                    self.completed.append(current_task)
                    self.running.pop(site, None)

    async def _run_task(self, task: DownloadTask) -> None:
        """Run a single task end-to-end: download, optional process, then export."""
        task.status = Status.RUNNING
        adapter = self._adapter
        client = self._get_client(task.site)

        login_ui = WebLoginUI(task)
        download_ui = WebDownloadUI(task)

        async def download_books() -> None:
            async with client:
                if adapter.get_login_required(task.site):
                    success = await client.login(
                        ui=login_ui, login_cfg=adapter.get_login_config(task.site)
                    )
                    if not success:
                        return
                await client.download_book(
                    BookConfig(book_id=task.book_id), ui=download_ui
                )

        task.asyncio_task = asyncio.create_task(download_books())
        await task.asyncio_task
        task.asyncio_task = None

        if task.status in {Status.CANCELLED, Status.FAILED}:
            return

        processors = adapter.get_processor_configs(task.site)
        if processors:
            task.status = Status.PROCESSING
            ok = await self._run_stage_with_retry(
                task=task,
                stage="processing",
                sem=self._process_sem,
                runner=client.process_book,
                book=BookConfig(book_id=task.book_id),
                processors=processors,
                ui=WebProcessUI(task),
            )
            if not ok:
                return

        if task.status in {Status.CANCELLED, Status.FAILED}:
            return

        task.status = Status.EXPORTING
        ok = await self._run_stage_with_retry(
            task=task,
            stage="export",
            sem=self._export_sem,
            runner=client.export_book,
            book=BookConfig(book_id=task.book_id),
            cfg=adapter.get_exporter_config(task.site),
            ui=WebExportUI(task),
        )
        if not ok:
            return

        if task.status not in {Status.CANCELLED, Status.FAILED}:
            task.status = Status.COMPLETED

    async def _run_stage_with_retry(
        self,
        *,
        task: DownloadTask,
        stage: str,
        sem: asyncio.Semaphore,
        runner: Callable[..., Any],
        **kwargs: Any,
    ) -> bool:
        backoff = _STAGE_BACKOFF_BASE
        last_error: Exception | None = None

        for attempt in range(_STAGE_RETRY_TIMES + 1):
            if task.status == Status.CANCELLED:
                return False
            try:
                async with sem:
                    await asyncio.to_thread(runner, **kwargs)
                return True
            except Exception as e:
                last_error = e
                if attempt >= _STAGE_RETRY_TIMES or not _is_retryable_stage_error(e):
                    break
                await async_jitter_sleep(
                    base=backoff,
                    mul_spread=1.2,
                    max_sleep=backoff + 2,
                )
                backoff *= 2

        task.status = Status.FAILED
        task.error = f"{stage} failed: {last_error}"
        return False


manager = TaskManager()
