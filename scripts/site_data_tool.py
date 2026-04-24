#!/usr/bin/env python3
"""
This script has grown to ~1500 LOC.

TODO (probably never):
  * Break into multiple files
  * Make it readable
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import logging
import logging.handlers
import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from nicegui import ui
from nicegui.events import KeyEventArguments
from site_data_tool_diff import (
    NavHelper,
    _char_level_diff,
    _go,
    diff_lines_html,
    struct_diff_html,
)
from site_data_tool_io import load_html_parts, save_html_parts

from novel_downloader.infra.cookies import parse_cookies
from novel_downloader.plugins import registry
from novel_downloader.schemas import FetcherConfig, ParserConfig

# ---------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------
DATA_DIR = Path(__file__).parent / "data"
CONFIG_PATH = DATA_DIR / "site_test_data.json"
SITE_DATA_PATH = DATA_DIR / "site_test_data.db"
HTML_ROOT = DATA_DIR / "html"
LOG_DIR = Path.cwd() / "logs"

LOGIN_REQUIRED: set[str] = set()
TEST_DATA: dict[str, list[dict[str, Any]]] = {}
REQ_INTERVALS: dict[str, float] = {}
DEFAULT_REQ_INTERVAL: float = 0.5
BACKEND_MAP: dict[str, str] = {}
DEFAULT_BACKEND: str = "aiohttp"
_PARSER_CONFIG = ParserConfig()

DATE_STR = datetime.now().strftime("%Y-%m-%d")

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS books (
    sitekey TEXT NOT NULL,
    bookid TEXT NOT NULL,
    date TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (sitekey, bookid, date)
);
CREATE TABLE IF NOT EXISTS chapters (
    sitekey TEXT NOT NULL,
    bookid TEXT NOT NULL,
    cid TEXT NOT NULL,
    date TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (sitekey, bookid, cid, date)
);
"""


# ---------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------
def setup_logging() -> logging.Logger:
    logger = logging.getLogger("site_tool")
    if logger.handlers:
        return logger

    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / "site_data_tool.log"

    handler = logging.handlers.TimedRotatingFileHandler(
        filename=log_path,
        when="midnight",
        interval=1,
        backupCount=14,
        encoding="utf-8",
    )

    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )

    handler.setFormatter(fmt)

    console = logging.StreamHandler()
    console.setFormatter(fmt)

    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.addHandler(console)
    return logger


logger = setup_logging()


# ---------------------------------------------------------------------
# Config & IO
# ---------------------------------------------------------------------
def load_config(cfg_path: Path) -> None:
    global LOGIN_REQUIRED, TEST_DATA, REQ_INTERVALS, DEFAULT_REQ_INTERVAL, NAV_HELPER
    global BACKEND_MAP, DEFAULT_BACKEND
    with open(cfg_path, encoding="utf-8") as f:
        data = json.load(f)

    TEST_DATA = data["TEST_DATA"]
    LOGIN_REQUIRED = set(data["LOGIN_REQUIRED"])

    req_cfg = data.get("REQ_INTERVALS", {})
    DEFAULT_REQ_INTERVAL = req_cfg.pop("default", 0.5)
    REQ_INTERVALS = req_cfg

    backend_cfg = data.get("BACKEND_MAP", {})
    DEFAULT_BACKEND = backend_cfg.pop("default", "aiohttp")
    BACKEND_MAP = backend_cfg

    NAV_HELPER = NavHelper(TEST_DATA)


# ---------------------------------------------------------------------
# Mode Handlers
# ---------------------------------------------------------------------
async def run_fetch(args: argparse.Namespace) -> None:
    """Async fetch mode"""
    load_config(args.config)
    registrar = registry.registrar

    selected_sites = args.site or list(TEST_DATA.keys())

    for site_key in selected_sites:
        if site_key not in TEST_DATA:
            logger.warning("Unknown site key: %s (skipped)", site_key)
            continue

        need_login = site_key in LOGIN_REQUIRED
        req_interval = REQ_INTERVALS.get(site_key, DEFAULT_REQ_INTERVAL)
        backend = BACKEND_MAP.get(site_key, DEFAULT_BACKEND)

        fetcher_cfg = FetcherConfig(
            request_interval=req_interval,
            backend=backend,
            impersonate="chrome136",
        )

        logger.info(
            "Initialized fetcher for site=%s | backend=%s | login_required=%s | interval=%.2fs",  # noqa: E501
            site_key,
            backend,
            need_login,
            req_interval,
        )

        async with registrar.get_fetcher(site_key, fetcher_cfg) as f:
            logged_in = await f.load_state() if need_login else True

            if need_login and not logged_in:
                logger.info("%s: login required.", site_key)

                login_kwargs: dict[str, Any] = {}
                for field in f.login_fields:
                    prompt_text = f"{field.label or field.name}"
                    if field.placeholder:
                        prompt_text += f" ({field.placeholder})"
                    if field.default:
                        prompt_text += f" [default: {field.default}]"
                    prompt_text += ": "

                    if field.type == "password":
                        value = getpass.getpass(prompt_text)
                    else:
                        value = input(prompt_text)

                    value = value.strip() or field.default

                    if field.type == "cookie":
                        try:
                            value = parse_cookies(value)
                        except Exception as e:
                            logger.warning(
                                "%s: failed to parse cookies (%s)", site_key, e
                            )
                            value = {}

                    login_kwargs[field.name] = value

                try:
                    ok = await f.login(**login_kwargs)
                except Exception as e:
                    logger.error("%s: login raised exception: %s", site_key, e)
                    ok = False

                if not ok:
                    logger.warning("%s: login failed, skipping site.", site_key)
                    continue
                else:
                    logger.info("%s: login successful.", site_key)

            for entry in TEST_DATA[site_key]:
                book_id = entry["book_id"]
                book_dir = HTML_ROOT / site_key / DATE_STR
                info_prefix = f"{book_id}_info"
                info_path = book_dir / f"{info_prefix}_1.html"

                if info_path.exists() and not args.overwrite:
                    logger.info("Skipping existing book info: %s:%s", site_key, book_id)
                else:
                    try:
                        logger.info("Fetching book info: %s:%s", site_key, book_id)
                        info_htmls = await f.fetch_book_info(book_id)
                        save_html_parts(info_htmls, book_dir, info_prefix)
                    except Exception as e:
                        logger.exception(
                            "Failed to fetch book info %s:%s - %s", site_key, book_id, e
                        )

                for chap_id in entry["chap_ids"]:
                    chap_prefix = f"{book_id}_{chap_id}"
                    chap_path = book_dir / f"{chap_prefix}_1.html"

                    if chap_path.exists() and not args.overwrite:
                        logger.info(
                            "Skipping existing chapter: %s:%s:%s",
                            site_key,
                            book_id,
                            chap_id,
                        )
                        continue

                    try:
                        logger.info(
                            "Fetching chapter: %s:%s:%s", site_key, book_id, chap_id
                        )
                        chap_htmls = await f.fetch_chapter_content(book_id, chap_id)
                        save_html_parts(chap_htmls, book_dir, chap_prefix)
                    except Exception as e:
                        logger.exception(
                            "Failed to fetch chapter %s:%s:%s - %s",
                            site_key,
                            book_id,
                            chap_id,
                            e,
                        )

            if need_login:
                await f.save_state()

    logger.info("Fetch complete.")


def run_parse(args: argparse.Namespace) -> None:
    """Sync parse mode"""
    load_config(args.config)
    date_str = args.date or DATE_STR

    db_path = args.db
    conn = sqlite3.connect(db_path)
    conn.executescript(_CREATE_TABLE_SQL)
    cur = conn.cursor()

    registrar = registry.registrar
    selected_sites = args.site or list(TEST_DATA.keys())

    for site_key in selected_sites:
        if site_key not in TEST_DATA:
            logger.warning("Unknown site key: %s (skipped)", site_key)
            continue

        parser = registrar.get_parser(site_key, _PARSER_CONFIG)
        html_base = HTML_ROOT / site_key / date_str

        for entry in TEST_DATA[site_key]:
            book_id = entry["book_id"]

            try:
                raw_pages = load_html_parts(html_base, f"{book_id}_info")
                if raw_pages:
                    book_info = parser.parse_book_info(raw_pages)
                    cur.execute(
                        "INSERT OR REPLACE INTO books VALUES (?, ?, ?, ?)",
                        (
                            site_key,
                            book_id,
                            date_str,
                            json.dumps(book_info, ensure_ascii=False),
                        ),
                    )
            except Exception as e:
                logger.exception(
                    "Failed to parse book info %s:%s - %s", site_key, book_id, e
                )

            for chap_id in entry["chap_ids"]:
                try:
                    raw_pages = load_html_parts(html_base, f"{book_id}_{chap_id}")
                    if not raw_pages:
                        continue
                    chapter = parser.parse_chapter_content(raw_pages, chap_id)
                    cur.execute(
                        "INSERT OR REPLACE INTO chapters VALUES (?, ?, ?, ?, ?)",
                        (
                            site_key,
                            book_id,
                            chap_id,
                            date_str,
                            json.dumps(chapter, ensure_ascii=False),
                        ),
                    )
                except Exception as e:
                    logger.exception(
                        "Failed to parse chapter %s:%s:%s - %s",
                        site_key,
                        book_id,
                        chap_id,
                        e,
                    )

    conn.commit()
    conn.close()
    logger.info("Parse complete for date %s", date_str)


# ---------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------
def _list_book_versions(site: str, book_id: str) -> list[str]:
    """Return list of available dates for a given book."""
    with sqlite3.connect(SITE_DATA_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT date FROM books WHERE sitekey = ? AND bookid = ? ORDER BY date",  # noqa: E501
            (site, book_id),
        )
        return [row[0] for row in cur.fetchall()]


def _list_chapter_versions(site: str, book_id: str, chap_id: str) -> list[str]:
    with sqlite3.connect(SITE_DATA_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT date FROM chapters WHERE sitekey=? AND bookid=? AND cid=? ORDER BY date",  # noqa: E501
            (site, book_id, chap_id),
        )
        return [r[0] for r in cur.fetchall()]


def _load_book_snapshot(site: str, book_id: str, date: str) -> dict:
    with sqlite3.connect(SITE_DATA_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT data FROM books WHERE sitekey = ? AND bookid = ? AND date = ?",
            (site, book_id, date),
        )
        row = cur.fetchone()
        return json.loads(row[0]) if row else {}


def _load_chapter_snapshot(site: str, book_id: str, chap_id: str, date: str) -> dict:
    with sqlite3.connect(SITE_DATA_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT data FROM chapters WHERE sitekey = ? AND bookid = ? AND cid = ? AND date = ?",  # noqa: E501
            (site, book_id, chap_id, date),
        )
        row = cur.fetchone()
        return json.loads(row[0]) if row else {}


NAV_HELPER: NavHelper = NavHelper(TEST_DATA)


# ---------------------------------------------------------------------
# Shared controls (right panel)
# ---------------------------------------------------------------------
def build_diff_controls(
    *,
    versions: list[str],
    state: dict,
    on_change: Callable[[], None],
    site: str | None = None,
    book_id: str | None = None,
    chap_id: str | None = None,
) -> None:
    """Floating control panel with diff settings and quick navigation."""
    state.setdefault("date_a", versions[-2] if len(versions) > 1 else versions[-1])
    state.setdefault("date_b", versions[-1])
    state.setdefault("diff_only", True)

    panel_hidden = {"hidden": False}

    def toggle_panel(show: bool) -> None:
        panel_hidden["hidden"] = not show
        expand_btn.visible = panel_hidden["hidden"]
        card.visible = not panel_hidden["hidden"]

    # --- Helper accessors from TEST_DATA ---
    def site_books(site: str) -> list[str]:
        entries = TEST_DATA.get(site, [])
        return [str(e.get("book_id", "")) for e in entries if "book_id" in e]

    def site_book_chaps(site: str, book_id: str) -> list[str]:
        for e in TEST_DATA.get(site, []):
            if str(e.get("book_id", "")) == str(book_id):
                return [str(cid) for cid in e.get("chap_ids", [])]
        return []

    # --- Floating Panel ---
    with ui.page_sticky(position="top-right", x_offset=16, y_offset=16):
        # collapsed floating gear icon
        expand_btn = (
            ui.button(icon="tune", on_click=lambda: toggle_panel(True))
            .props("round fab color=primary")
            .tooltip("Show controls")
        )

        # main card
        card = ui.card().classes("q-pa-sm").style("width: 380px;")
        with card, ui.column().classes("q-gutter-sm"):
            ui.label("Diff Controls").classes("text-subtitle2")

            # --- Diff version selectors ---
            with ui.row().classes("q-gutter-sm"):
                diff_a = (
                    ui.select(
                        options=list(reversed(versions)),
                        value=state["date_a"],
                        label="Old version",
                        with_input=False,
                    )
                    .props("dense outlined")
                    .style("flex:1;")
                )
                diff_a.bind_value(state, "date_a")
                diff_a.on_value_change(lambda *_: on_change())

                diff_b = (
                    ui.select(
                        options=list(reversed(versions)),
                        value=state["date_b"],
                        label="New version",
                        with_input=False,
                    )
                    .props("dense outlined")
                    .style("flex:1;")
                )
                diff_b.bind_value(state, "date_b")
                diff_b.on_value_change(lambda *_: on_change())

            diff_only = ui.checkbox("Show differences only", value=state["diff_only"])
            diff_only.bind_value(state, "diff_only")
            diff_only.on_value_change(lambda *_: on_change())

            ui.separator()

            # --- Navigation section ---
            ui.label("Navigation").classes("text-subtitle2")

            # Dropdown selectors
            sites = list(TEST_DATA.keys())
            current_site = site or (sites[0] if sites else "")

            site_sel = ui.select(
                options=sites,
                value=current_site,
                label="Site key",
                with_input=False,
            ).props("dense outlined")

            books = site_books(current_site) if current_site else []
            current_book = book_id or (books[0] if books else "")

            book_sel = ui.select(
                options=books,
                value=current_book,
                label="Book ID",
                with_input=False,
            ).props("dense outlined")

            chaps = site_book_chaps(current_site, current_book) if current_book else []
            current_chap = (
                chap_id if chap_id in chaps else (chaps[0] if chaps else None)
            )

            chap_sel = ui.select(
                options=chaps,
                value=current_chap,
                label="Chapter ID",
                with_input=False,
            ).props("dense outlined")
            chap_sel.disable() if not current_chap else chap_sel.enable()

            # --- Update dropdown logic ---
            def on_site_change(e):
                new_site = e.value or ""
                new_books = site_books(new_site)
                book_sel.options = new_books
                book_sel.value = new_books[0] if new_books else ""

                new_chaps = (
                    site_book_chaps(new_site, book_sel.value) if book_sel.value else []
                )
                chap_sel.options = new_chaps
                chap_sel.value = new_chaps[0] if new_chaps else None
                chap_sel.disable() if not new_chaps else chap_sel.enable()

            def on_book_change(e):
                s = site_sel.value or ""
                b = e.value or ""
                new_chaps = site_book_chaps(s, b)
                chap_sel.options = new_chaps
                chap_sel.value = new_chaps[0] if new_chaps else None
                chap_sel.disable() if not new_chaps else chap_sel.enable()

            site_sel.on_value_change(on_site_change)
            book_sel.on_value_change(on_book_change)

            # --- Manual navigation buttons ---
            def goto_book():
                s, b = site_sel.value, book_sel.value
                if s and b:
                    _go(f"/book_info/{s}/{b}")()

            def goto_chap():
                s, b, c = site_sel.value, book_sel.value, chap_sel.value
                if s and b and c:
                    _go(f"/chapter/{s}/{b}/{c}")()

            with ui.row().classes("q-gutter-sm"):
                ui.button("Book Info", color="primary", on_click=goto_book).props(
                    "flat dense"
                )
                ui.button("Chapter", color="primary", on_click=goto_chap).props(
                    "flat dense"
                )
                ui.button("Index", color="secondary", on_click=_go("/")).props(
                    "flat dense"
                )

            # --- Prev / Next navigation buttons ---
            with ui.row().classes("q-gutter-sm"):
                prev_btn = ui.button("Prev", color="primary")
                next_btn = ui.button("Next", color="primary")

            def update_nav_buttons(is_first: bool, is_last: bool):
                """Enable/disable prev/next buttons based on current index."""
                if is_first:
                    prev_btn.disable()
                else:
                    prev_btn.enable()
                if is_last:
                    next_btn.disable()
                else:
                    next_btn.enable()

            def on_prev():
                """Go to previous book/chapter based on current selection."""
                s = site or ""
                b = book_id or ""
                c = chap_id
                (ns, nb, nc), is_first, is_last = NAV_HELPER.move_prev(s, b, c)
                if not ns:
                    return
                site_sel.value, book_sel.value, chap_sel.value = ns, nb, nc or ""
                update_nav_buttons(is_first, is_last)
                if nc:
                    _go(f"/chapter/{ns}/{nb}/{nc}")()
                else:
                    _go(f"/book_info/{ns}/{nb}")()

            def on_next():
                """Go to next book/chapter based on current selection."""
                s = site or ""
                b = book_id or ""
                c = chap_id
                (ns, nb, nc), is_first, is_last = NAV_HELPER.move_next(s, b, c)
                if not ns:
                    return
                site_sel.value, book_sel.value, chap_sel.value = ns, nb, nc or ""
                update_nav_buttons(is_first, is_last)
                if nc:
                    _go(f"/chapter/{ns}/{nb}/{nc}")()
                else:
                    _go(f"/book_info/{ns}/{nb}")()

            has_prev, has_next = NAV_HELPER.has_prev_next(
                current_site, current_book, current_chap or None
            )
            update_nav_buttons(not has_prev, not has_next)

            prev_btn.on_click(on_prev)
            next_btn.on_click(on_next)

            ui.separator()

            # --- Collapse button ---
            ui.button(
                "Hide Controls",
                icon="close",
                color="negative",
                on_click=lambda: toggle_panel(False),
            ).props("outline dense")

        def handle_key(e: KeyEventArguments) -> None:
            """Handle arrow key navigation."""
            if not e.action.keyup:
                return
            if e.key == "ArrowLeft":
                on_prev()
            elif e.key == "ArrowRight":
                on_next()

        ui.keyboard(on_key=handle_key)
        expand_btn.visible = False
        card.visible = True


# ---------------------------------------------------------------------
# Root page: menu
# ---------------------------------------------------------------------
@ui.page("/")
def index_page() -> None:
    with ui.column().classes("w-full max-w-screen-lg min-w-[320px] mx-auto gap-4"):
        ui.label("Novel Data Visualizer").classes("text-h5")

        sites = list(TEST_DATA.keys())
        default_site = sites[0] if sites else ""

        def site_books(site: str) -> list[str]:
            entries = TEST_DATA.get(site, [])
            return [str(e.get("book_id", "")) for e in entries if "book_id" in e]

        def site_book_chaps(site: str, book_id: str) -> list[str]:
            for e in TEST_DATA.get(site, []):
                if str(e.get("book_id", "")) == str(book_id):
                    return [str(cid) for cid in e.get("chap_ids", [])]
            return []

        with ui.row().classes("items-end"):
            site_sel = ui.select(
                options=sites,
                value=default_site,
                label="Site key",
                with_input=False,
            ).props("outlined dense")

            books_initial = site_books(default_site) if default_site else []
            default_book = books_initial[0] if books_initial else ""
            book_sel = ui.select(
                options=books_initial,
                value=default_book,
                label="Book ID",
                with_input=False,
            ).props("outlined dense")

            chaps_initial = (
                site_book_chaps(default_site, default_book) if default_book else []
            )
            default_chap = chaps_initial[0] if chaps_initial else ""
            chap_sel = ui.select(
                options=chaps_initial,
                value=default_chap,
                label="Chapter ID",
                with_input=False,
            ).props("outlined dense")

        def on_site_change(e):
            site = e.value or ""
            new_books = site_books(site)
            book_sel.options = new_books
            book_sel.value = new_books[0] if new_books else ""
            chaps = site_book_chaps(site, book_sel.value) if book_sel.value else []
            chap_sel.options = chaps
            chap_sel.value = chaps[0] if chaps else ""

        def on_book_change(e):
            site = site_sel.value or ""
            book = e.value or ""
            chaps = site_book_chaps(site, book)
            chap_sel.options = chaps
            chap_sel.value = chaps[0] if chaps else ""

        site_sel.on_value_change(on_site_change)
        book_sel.on_value_change(on_book_change)

        def _goto_book():
            s, b = site_sel.value, book_sel.value
            if s and b:
                _go(f"/book_info/{s}/{b}")()

        def _goto_chap():
            s, b, c = site_sel.value, book_sel.value, chap_sel.value
            if s and b and c:
                _go(f"/chapter/{s}/{b}/{c}")()

        with ui.row().classes("q-gutter-sm"):
            ui.button("Open Book Info Diff", on_click=_goto_book)
            ui.button("Open Chapter Diff", on_click=_goto_chap)


# ---------------------------------------------------------------------
# Book Info page
# ---------------------------------------------------------------------
@ui.page("/book_info/{site}/{book_id}")
def book_info_page(site: str, book_id: str) -> None:
    with ui.column().classes("w-full max-w-screen-lg min-w-[320px] mx-auto gap-4"):
        ui.label(f"Book Info: {site}/{book_id}").classes("text-h6")

        versions = _list_book_versions(site, book_id)
        if not versions:
            ui.label("No versions found.")
            return

        latest = versions[-1]
        second_latest = versions[-2] if len(versions) > 1 else versions[-1]

        state: dict[str, Any] = {
            "date_a": second_latest,
            "date_b": latest,
            "diff_only": True,
            "limit": 50,
        }

        meta_diff_container = ui.column().classes("q-gutter-sm")
        vols_diff_container = ui.column().classes("q-gutter-sm")

        def _normalize_book_meta(d: dict) -> dict:
            if not isinstance(d, dict):
                return {}
            return {k: v for k, v in d.items() if k not in ("volumes", "last_checked")}

        def _render_meta_diff(data_a: dict, data_b: dict) -> None:
            meta_diff_container.clear()
            a_meta = _normalize_book_meta(data_a)
            b_meta = _normalize_book_meta(data_b)
            html_block = struct_diff_html(
                a_meta,
                b_meta,
                limit=int(state["limit"]),
                diff_only=bool(state["diff_only"]),
            )
            with meta_diff_container:
                ui.label(f"Metadata: {state['date_a']} vs {state['date_b']}").classes(
                    "text-caption text-grey"
                )
                ui.separator()
                ui.html(html_block, sanitize=False)

        def _render_volumes_diff(data_a: dict, data_b: dict) -> None:
            vols_diff_container.clear()
            va = data_a.get("volumes") or []
            vb = data_b.get("volumes") or []
            html_block = struct_diff_html(
                va, vb, limit=int(state["limit"]), diff_only=bool(state["diff_only"])
            )
            with vols_diff_container:
                ui.label(
                    f"Volumes/Chapters: {state['date_a']} vs {state['date_b']}"
                ).classes("text-caption text-grey")
                ui.separator()
                ui.html(html_block, sanitize=False)

        def _render_all() -> None:
            data_a = _load_book_snapshot(site, book_id, state["date_a"])
            data_b = _load_book_snapshot(site, book_id, state["date_b"])
            _render_meta_diff(data_a, data_b)
            _render_volumes_diff(data_a, data_b)

        build_diff_controls(
            versions=versions,
            state=state,
            on_change=_render_all,
            site=site,
            book_id=book_id,
        )

        _render_all()


# ---------------------------------------------------------------------
# Chapter page
# ---------------------------------------------------------------------
@ui.page("/chapter/{site}/{book_id}/{chap_id}")
def chapter_page(site: str, book_id: str, chap_id: str) -> None:
    with ui.column().classes("w-full max-w-screen-lg min-w-[320px] mx-auto gap-4"):
        ui.label(f"Chapter: {site}/{book_id}/{chap_id}").classes("text-h6")

        versions = _list_chapter_versions(site, book_id, chap_id)
        if not versions:
            ui.label("No versions found.")
            return

        latest = versions[-1]
        second_latest = versions[-2] if len(versions) > 1 else versions[-1]
        state: dict[str, Any] = {
            "date_a": second_latest,
            "date_b": latest,
            "diff_only": True,
        }

        # Containers
        title_diff_container = ui.column().classes("q-gutter-sm")
        content_diff_container = ui.column().classes("q-gutter-sm")
        extra_diff_container = ui.column().classes("q-gutter-sm")

        def _render_title_diff(a: dict, b: dict) -> None:
            title_diff_container.clear()
            old_t = (a.get("title") or "").strip()
            new_t = (b.get("title") or "").strip()
            with title_diff_container:
                ui.label(f"Title: {state['date_a']} vs {state['date_b']}").classes(
                    "text-caption text-grey"
                )
                ui.separator()
                if state["diff_only"] and old_t == new_t:
                    ui.label("No title change.").classes("text-negative text-caption")
                else:
                    old_html, new_html = _char_level_diff(old_t, new_t)
                    ui.html(
                        "<div><strong>Old:</strong></div>" + old_html, sanitize=False
                    )
                    ui.html(
                        "<div style='margin-top:.5rem;'><strong>New:</strong></div>"
                        + new_html,
                        sanitize=False,
                    )

        def _render_content_diff(a: dict, b: dict) -> None:
            content_diff_container.clear()
            old_text = a.get("content", "") or ""
            new_text = b.get("content", "") or ""
            html_block = diff_lines_html(
                old_text, new_text, show_equals=not bool(state["diff_only"])
            )
            with content_diff_container:
                ui.label(f"Content: {state['date_a']} vs {state['date_b']}").classes(
                    "text-caption text-grey"
                )
                ui.separator()
                ui.html(html_block, sanitize=False)

        def _render_extra_diff(a: dict, b: dict) -> None:
            extra_diff_container.clear()
            html_block = struct_diff_html(
                a.get("extra", {}) or {},
                b.get("extra", {}) or {},
                limit=50,
                diff_only=bool(state["diff_only"]),
            )
            with extra_diff_container:
                ui.label(f"Extra: {state['date_a']} vs {state['date_b']}").classes(
                    "text-caption text-grey"
                )
                ui.separator()
                ui.html(html_block, sanitize=False)

        def _render_all() -> None:
            a = _load_chapter_snapshot(site, book_id, chap_id, state["date_a"]) or {}
            b = _load_chapter_snapshot(site, book_id, chap_id, state["date_b"]) or {}
            _render_title_diff(a, b)
            _render_content_diff(a, b)
            _render_extra_diff(a, b)

        build_diff_controls(
            versions=versions,
            state=state,
            on_change=_render_all,
            site=site,
            book_id=book_id,
            chap_id=chap_id,
        )

        _render_all()


# ---------------------------------------------------------------------
# Visualize Runner
# ---------------------------------------------------------------------
def run_visualize(args: argparse.Namespace) -> None:
    """Start NiceGUI server"""
    load_config(args.config)
    ui.run(
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


# ---------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------
def main() -> None:
    global CONFIG_PATH, SITE_DATA_PATH, HTML_ROOT, DATE_STR

    parser = argparse.ArgumentParser(description="Novel Downloader Testing Tool")

    parser.add_argument("--fetch", action="store_true", help="Run async fetching mode")
    parser.add_argument("--parse", action="store_true", help="Run HTML parsing mode")
    parser.add_argument(
        "--visualize", action="store_true", help="Run visualization mode"
    )

    parser.add_argument(
        "--site",
        type=str,
        nargs="+",
        help="Specify one or more site keys to process (default: all sites in config)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing HTML files or DB entries",
    )
    parser.add_argument(
        "--config", type=Path, default=CONFIG_PATH, help="Path to JSON config file"
    )
    parser.add_argument(
        "--db", type=Path, default=SITE_DATA_PATH, help="Path to SQLite DB file"
    )
    parser.add_argument(
        "--html-root", type=Path, default=HTML_ROOT, help="HTML root directory"
    )

    parser.add_argument("--date", type=str, help="Specify parse date (YYYY-MM-DD)")

    parser.add_argument(
        "--host", type=str, default="127.0.0.1", help="Host for NiceGUI app"
    )
    parser.add_argument(
        "--port", type=int, default=8080, help="TCP port to serve the app on"
    )
    parser.add_argument(
        "--reload", action="store_true", help="Enable autoreload on code changes"
    )

    args = parser.parse_args()

    CONFIG_PATH, SITE_DATA_PATH, HTML_ROOT = args.config, args.db, args.html_root
    if args.date:
        DATE_STR = args.date

    if args.fetch:
        asyncio.run(run_fetch(args))
    elif args.parse:
        run_parse(args)
    elif args.visualize:
        run_visualize(args)
    else:
        parser.print_help()


if __name__ in {"__main__", "__mp_main__"}:
    main()
