#!/usr/bin/env python3
"""
novel_downloader.apps.web
-------------------------

Web interface layer built with nicegui.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "web_main",
]


def __getattr__(name: str) -> Any:
    if name == "web_main":
        from .main import web_main

        return web_main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
