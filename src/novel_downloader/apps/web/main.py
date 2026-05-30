#!/usr/bin/env python3
"""
novel_downloader.apps.web.main
------------------------------

Novel Downloader web UI (NiceGUI).

This entry point starts the local server and registers the app's pages.
"""

import argparse
import asyncio
import time
from pathlib import Path

from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse
from nicegui import app, ui

import novel_downloader.apps.web.pages  # noqa: F401
from novel_downloader.apps.web.services import manager
from novel_downloader.infra.config import get_config_value
from novel_downloader.infra.logger import setup_logging

_APP_STARTED_AT = time.time()


@app.get("/api/v1/health", tags=["system"], summary="Service health")
async def api_health() -> JSONResponse:
    payload = manager.health_snapshot()
    payload["uptime_seconds"] = max(0, int(time.time() - _APP_STARTED_AT))
    return JSONResponse(payload)


@app.get("/api/v1/tasks", tags=["tasks"], summary="Task queue snapshot")
async def api_tasks() -> JSONResponse:
    return JSONResponse(manager.api_snapshot())


@app.get("/openapi.json", include_in_schema=False)
async def openapi_json() -> JSONResponse:
    schema = get_openapi(
        title="Novel Downloader Web API",
        version="1.0.0",
        description="Health and task observability API for the web runtime.",
        routes=app.routes,
    )
    return JSONResponse(schema)


@app.get("/swagger", include_in_schema=False)
async def swagger_ui() -> HTMLResponse:
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="Novel Downloader Swagger",
    )


def mount_exports() -> None:
    output_dir = get_config_value(["general", "output_dir"], "./downloads")
    out = Path(output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    # serves /downloads/<filename> from the export dir
    app.add_static_files("/downloads", local_directory=out)


async def shutdown() -> None:
    print("Shutting down workers...")
    await manager.close()


def web_main() -> None:
    p = argparse.ArgumentParser(
        description="Novel Downloader web UI.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--listen",
        choices=["local", "public"],
        default="local",
        help=(
            "Bind address mode: 'local' binds to 127.0.0.1; 'public' binds to 0.0.0.0."
        ),
    )
    p.add_argument(
        "--port",
        type=int,
        default=8080,
        help="TCP port to serve the app on.",
    )
    p.add_argument(
        "--reload",
        action="store_true",
        help="Enable autoreload on code changes (development).",
    )
    args = p.parse_args()

    host = "127.0.0.1" if args.listen == "local" else "0.0.0.0"

    log_level = get_config_value(["general", "debug", "log_level"], "INFO")
    log_dir = get_config_value(["general", "debug", "log_dir"], "./logs")
    setup_logging(log_dir=log_dir, console_level=log_level)

    app.on_startup(mount_exports)
    app.on_shutdown(shutdown)
    try:
        ui.run(host=host, port=args.port, reload=args.reload)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("Server has stopped")


if __name__ in {"__main__", "__mp_main__"}:
    web_main()
