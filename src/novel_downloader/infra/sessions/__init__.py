#!/usr/bin/env python3
"""
novel_downloader.infra.sessions
-------------------------------
"""

__all__ = ["create_session"]

import logging
from importlib import import_module
from typing import Any, cast

from novel_downloader.schemas import FetcherConfig

from .base import BaseSession

logger = logging.getLogger(__name__)

_BACKEND_IMPORTS: dict[str, tuple[str, str]] = {
    "aiohttp": ("novel_downloader.infra.sessions._aiohttp", "AiohttpSession"),
    "httpx": ("novel_downloader.infra.sessions._httpx", "HttpxSession"),
    "curl_cffi": (
        "novel_downloader.infra.sessions._curl_cffi",
        "CurlCffiSession",
    ),
}

_OPTIONAL_DEPS_BY_BACKEND: dict[str, set[str]] = {
    "aiohttp": {"aiohttp"},
    "httpx": {"httpx", "httpcore", "h11", "h2"},
    "curl_cffi": {"curl_cffi"},
}


class _BackendUnavailableError(RuntimeError):
    pass


def _load_backend_class(backend: str) -> type[BaseSession]:
    module_name, class_name = _BACKEND_IMPORTS[backend]

    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        missing_name = (exc.name or "").split(".")[0]
        optional_deps = _OPTIONAL_DEPS_BY_BACKEND.get(backend, set())

        if missing_name in optional_deps:
            raise _BackendUnavailableError(
                f"backend={backend!r} unavailable because dependency "
                f"{missing_name!r} is not installed"
            ) from exc
        raise

    klass = cast(type[BaseSession], getattr(module, class_name))
    return klass


def create_session(
    backend: str,
    cfg: FetcherConfig,
    cookies: dict[str, str] | None = None,
    **kwargs: Any,
) -> BaseSession:
    """
    Factory method to create a session backend instance.

    Available backends:
      * aiohttp
      * httpx
      * curl_cffi
    """
    backend = backend.strip().lower()
    if backend not in _BACKEND_IMPORTS:
        raise ValueError(f"Unsupported backend: {backend!r}")

    fallback_chain = [backend, *(b for b in _BACKEND_IMPORTS if b != backend)]
    unavailable_errors: list[str] = []

    for candidate in fallback_chain:
        try:
            session_class = _load_backend_class(candidate)
        except _BackendUnavailableError as exc:
            unavailable_errors.append(str(exc))
            continue

        if candidate != backend:
            logger.warning(
                "Requested backend %s is unavailable, fallback to %s. details=%s",
                backend,
                candidate,
                "; ".join(unavailable_errors),
            )
        return session_class(cfg, cookies, **kwargs)

    raise RuntimeError(
        "No available HTTP backend. Ensure at least one of "
        "aiohttp/httpx/curl_cffi is installed. "
        f"Requested backend={backend!r}. details={'; '.join(unavailable_errors)}"
    )
