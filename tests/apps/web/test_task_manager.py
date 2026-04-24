from __future__ import annotations

import importlib
import sys

import pytest


class DummyClient:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_close_closes_cached_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    import novel_downloader.infra.config as config_module

    monkeypatch.setattr(config_module, "load_config", lambda *args, **kwargs: {})
    monkeypatch.setattr(config_module, "ConfigAdapter", lambda cfg: cfg)

    sys.modules.pop("novel_downloader.apps.web.services.task_manager", None)
    task_manager_module = importlib.import_module(
        "novel_downloader.apps.web.services.task_manager"
    )
    TaskManager = task_manager_module.TaskManager

    manager = TaskManager()
    client_a = DummyClient()
    client_b = DummyClient()
    manager._clients = {"site-a": client_a, "site-b": client_b}

    await manager.close()

    assert client_a.closed is True
    assert client_b.closed is True
    assert manager._clients == {}