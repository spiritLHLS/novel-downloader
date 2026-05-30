from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass
class DummyClientConfig:
    pass


class DummyAdapter:
    def __init__(self, cfg: dict):
        self._cfg = cfg

    def get_client_config(self, site: str) -> DummyClientConfig:
        return DummyClientConfig()

    def get_login_required(self, site: str) -> bool:
        return True

    def get_login_config(self, site: str) -> dict[str, str]:
        return {}

    def get_processor_configs(self, site: str) -> list[dict[str, str]]:
        return []

    def get_exporter_config(self, site: str) -> dict[str, str]:
        return {}


class PipelineAdapter(DummyAdapter):
    def get_login_required(self, site: str) -> bool:
        return False

    def get_processor_configs(self, site: str) -> list[dict[str, str]]:
        return [{"name": "noop", "overwrite": False, "options": {}}]


class LoginFailClient:
    def __init__(self) -> None:
        self.download_called = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def close(self) -> None:
        return None

    async def login(self, *, ui, login_cfg):
        ui.on_login_failed()
        return False

    async def download_book(self, book, ui) -> None:  # pragma: no cover
        self.download_called = True


class SuccessPipelineClient:
    def __init__(self) -> None:
        self.download_called = False
        self.process_called = False
        self.export_called = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def close(self) -> None:
        return None

    async def login(self, *, ui, login_cfg):  # pragma: no cover
        return True

    async def download_book(self, book, ui) -> None:
        self.download_called = True
        await ui.on_start(book)
        await ui.on_progress(1, 1)
        await ui.on_complete(book)

    def process_book(self, book, processors, ui) -> None:
        self.process_called = True
        ui.on_stage_start(book, "noop")
        ui.on_stage_progress(book, "noop", 1, 1)
        ui.on_stage_complete(book, "noop")

    def export_book(self, book, cfg, ui) -> None:
        self.export_called = True
        ui.on_start(book, "txt")


class RetryPipelineClient(SuccessPipelineClient):
    def __init__(self) -> None:
        super().__init__()
        self.process_attempts = 0
        self.export_attempts = 0

    def process_book(self, book, processors, ui) -> None:
        self.process_attempts += 1
        if self.process_attempts == 1:
            raise TimeoutError("transient process error")
        super().process_book(book, processors, ui)

    def export_book(self, book, cfg, ui) -> None:
        self.export_attempts += 1
        if self.export_attempts == 1:
            raise TimeoutError("transient export error")
        super().export_book(book, cfg, ui)


class NonRetryProcessClient(SuccessPipelineClient):
    def __init__(self) -> None:
        super().__init__()
        self.process_attempts = 0

    def process_book(self, book, processors, ui) -> None:
        self.process_attempts += 1
        raise RuntimeError("non-retryable processing error")


@pytest.mark.asyncio
async def test_run_task_stops_after_login_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import novel_downloader.infra.config as config_module

    monkeypatch.setattr(config_module, "load_config", lambda *args, **kwargs: {})
    monkeypatch.setattr(config_module, "ConfigAdapter", DummyAdapter)

    sys.modules.pop("novel_downloader.apps.web.services.task_manager", None)
    task_manager_module = importlib.import_module(
        "novel_downloader.apps.web.services.task_manager"
    )

    TaskManager = task_manager_module.TaskManager
    web_models = importlib.import_module("novel_downloader.apps.web.models")
    DownloadTask = web_models.DownloadTask
    Status = web_models.Status

    manager = TaskManager()
    client = LoginFailClient()

    monkeypatch.setattr(
        task_manager_module.registrar,
        "get_client",
        lambda site, cfg: client,
    )

    task = DownloadTask(title="T", site="dummy", book_id="1")
    await manager._run_task(task)

    assert task.status == Status.FAILED
    assert task.error == "登录失败"
    assert client.download_called is False


@pytest.mark.asyncio
async def test_add_task_rejects_empty_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import novel_downloader.infra.config as config_module

    monkeypatch.setattr(config_module, "load_config", lambda *args, **kwargs: {})
    monkeypatch.setattr(config_module, "ConfigAdapter", DummyAdapter)

    sys.modules.pop("novel_downloader.apps.web.services.task_manager", None)
    task_manager_module = importlib.import_module(
        "novel_downloader.apps.web.services.task_manager"
    )
    manager = task_manager_module.TaskManager()

    with pytest.raises(ValueError, match="title"):
        await manager.add_task(title=" ", site="site", book_id="1")
    with pytest.raises(ValueError, match="site"):
        await manager.add_task(title="title", site=" ", book_id="1")
    with pytest.raises(ValueError, match="book_id"):
        await manager.add_task(title="title", site="site", book_id=" ")


@pytest.mark.asyncio
async def test_add_task_rejects_when_manager_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import novel_downloader.infra.config as config_module

    monkeypatch.setattr(config_module, "load_config", lambda *args, **kwargs: {})
    monkeypatch.setattr(config_module, "ConfigAdapter", DummyAdapter)

    sys.modules.pop("novel_downloader.apps.web.services.task_manager", None)
    task_manager_module = importlib.import_module(
        "novel_downloader.apps.web.services.task_manager"
    )
    manager = task_manager_module.TaskManager()
    await manager.close()

    with pytest.raises(RuntimeError, match="closed"):
        await manager.add_task(title="title", site="site", book_id="1")


@pytest.mark.asyncio
async def test_cancel_task_rejects_non_interruptible_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import novel_downloader.infra.config as config_module

    monkeypatch.setattr(config_module, "load_config", lambda *args, **kwargs: {})
    monkeypatch.setattr(config_module, "ConfigAdapter", DummyAdapter)

    sys.modules.pop("novel_downloader.apps.web.services.task_manager", None)
    task_manager_module = importlib.import_module(
        "novel_downloader.apps.web.services.task_manager"
    )
    web_models = importlib.import_module("novel_downloader.apps.web.models")
    DownloadTask = web_models.DownloadTask
    Status = web_models.Status

    manager = task_manager_module.TaskManager()
    task = DownloadTask(title="T", site="dummy", book_id="1", status=Status.PROCESSING)
    manager.running[task.site] = task

    ok = await manager.cancel_task(task.task_id)

    assert ok is False
    assert task.status == Status.PROCESSING


@pytest.mark.asyncio
async def test_run_task_marks_completed_after_process_and_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import novel_downloader.infra.config as config_module

    monkeypatch.setattr(config_module, "load_config", lambda *args, **kwargs: {})
    monkeypatch.setattr(config_module, "ConfigAdapter", PipelineAdapter)

    sys.modules.pop("novel_downloader.apps.web.services.task_manager", None)
    task_manager_module = importlib.import_module(
        "novel_downloader.apps.web.services.task_manager"
    )

    TaskManager = task_manager_module.TaskManager
    web_models = importlib.import_module("novel_downloader.apps.web.models")
    DownloadTask = web_models.DownloadTask
    Status = web_models.Status

    manager = TaskManager()
    client = SuccessPipelineClient()
    monkeypatch.setattr(task_manager_module.registrar, "get_client", lambda *_: client)

    task = DownloadTask(title="T", site="dummy", book_id="1")
    await manager._run_task(task)

    assert client.download_called is True
    assert client.process_called is True
    assert client.export_called is True
    assert task.status == Status.COMPLETED


@pytest.mark.asyncio
async def test_run_task_retries_transient_stage_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import novel_downloader.infra.config as config_module

    monkeypatch.setattr(config_module, "load_config", lambda *args, **kwargs: {})
    monkeypatch.setattr(config_module, "ConfigAdapter", PipelineAdapter)

    sys.modules.pop("novel_downloader.apps.web.services.task_manager", None)
    task_manager_module = importlib.import_module(
        "novel_downloader.apps.web.services.task_manager"
    )

    TaskManager = task_manager_module.TaskManager
    web_models = importlib.import_module("novel_downloader.apps.web.models")
    DownloadTask = web_models.DownloadTask
    Status = web_models.Status

    manager = TaskManager()
    client = RetryPipelineClient()
    monkeypatch.setattr(task_manager_module.registrar, "get_client", lambda *_: client)

    task = DownloadTask(title="T", site="dummy", book_id="1")
    await manager._run_task(task)

    assert client.process_attempts == 2
    assert client.export_attempts == 2
    assert task.status == Status.COMPLETED


@pytest.mark.asyncio
async def test_health_snapshot_and_api_snapshot_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import novel_downloader.infra.config as config_module

    monkeypatch.setattr(config_module, "load_config", lambda *args, **kwargs: {})
    monkeypatch.setattr(config_module, "ConfigAdapter", DummyAdapter)

    sys.modules.pop("novel_downloader.apps.web.services.task_manager", None)
    task_manager_module = importlib.import_module(
        "novel_downloader.apps.web.services.task_manager"
    )

    manager = task_manager_module.TaskManager()
    web_models = importlib.import_module("novel_downloader.apps.web.models")
    DownloadTask = web_models.DownloadTask
    done = DownloadTask(title="T", site="dummy", book_id="1")
    done.exported_paths["txt"] = Path("/tmp/full/path/book.txt")
    manager.completed.append(done)

    health = manager.health_snapshot()
    snap = manager.api_snapshot()

    assert health["status"] == "ok"
    assert "workers_alive" in health
    assert set(snap) == {"running", "pending", "completed"}
    assert snap["completed"][0]["exported_paths"]["txt"] == "book.txt"


@pytest.mark.asyncio
async def test_run_task_does_not_retry_non_retryable_stage_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import novel_downloader.infra.config as config_module

    monkeypatch.setattr(config_module, "load_config", lambda *args, **kwargs: {})
    monkeypatch.setattr(config_module, "ConfigAdapter", PipelineAdapter)

    sys.modules.pop("novel_downloader.apps.web.services.task_manager", None)
    task_manager_module = importlib.import_module(
        "novel_downloader.apps.web.services.task_manager"
    )

    TaskManager = task_manager_module.TaskManager
    web_models = importlib.import_module("novel_downloader.apps.web.models")
    DownloadTask = web_models.DownloadTask
    Status = web_models.Status

    manager = TaskManager()
    client = NonRetryProcessClient()
    monkeypatch.setattr(task_manager_module.registrar, "get_client", lambda *_: client)

    task = DownloadTask(title="T", site="dummy", book_id="1")
    await manager._run_task(task)

    assert client.process_attempts == 1
    assert task.status == Status.FAILED
