#!/usr/bin/env python3
"""
novel_downloader.apps.web.services
----------------------------------

Convenience re-exports for web UI services
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "setup_dialog",
    "manager",
]


def __getattr__(name: str) -> Any:
    if name == "setup_dialog":
        from .client_dialog import setup_dialog

        return setup_dialog
    if name == "manager":
        from .task_manager import manager

        return manager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
