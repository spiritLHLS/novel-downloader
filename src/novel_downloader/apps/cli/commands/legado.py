#!/usr/bin/env python3
"""
novel_downloader.apps.cli.commands.legado
-----------------------------------------

Legado 书源管理子命令。

提供加载书源文件、列出已加载书源、验证书源文件等操作。

用法示例
--------
::

    # 列出书源文件内包含的书源
    novel-dl legado list my_sources.json

    # 验证书源文件格式
    novel-dl legado validate my_sources.json

    # 用书源下载小说（等价于 download --legado-source）
    novel-dl legado download my_sources.json https://example.com/book/123
"""

from __future__ import annotations

import json
from argparse import ArgumentParser, Namespace
from pathlib import Path

from novel_downloader.apps.cli import ui
from novel_downloader.infra.i18n import t

from .base import Command


class LegadoCmd(Command):
    name = "legado"
    help = t("Manage and use Legado (阅读) book sources.")

    @classmethod
    def add_arguments(cls, parser: ArgumentParser) -> None:
        sub = parser.add_subparsers(dest="legado_action")

        # ---- list ----
        list_p = sub.add_parser("list", help=t("List book sources from a JSON file."))
        list_p.add_argument("source_file", help=t("Legado JSON book source file."))
        list_p.add_argument(
            "--enabled-only",
            action="store_true",
            default=False,
            help=t("Only show enabled sources."),
        )

        # ---- validate ----
        val_p = sub.add_parser(
            "validate", help=t("Validate a Legado book source JSON file.")
        )
        val_p.add_argument("source_file", help=t("Legado JSON book source file."))

        # ---- download ----
        dl_p = sub.add_parser(
            "download",
            help=t("Download a novel using a Legado book source."),
        )
        dl_p.add_argument("source_file", help=t("Legado JSON book source file."))
        dl_p.add_argument("book_url", help=t("URL of the book to download."))
        dl_p.add_argument(
            "--config", type=str, help=t("Path to the configuration file.")
        )
        dl_p.add_argument(
            "--start", type=str, help=t("Start chapter ID (for the book).")
        )
        dl_p.add_argument("--end", type=str, help=t("End chapter ID (for the book)."))
        dl_p.add_argument(
            "--no-export",
            action="store_true",
            help=t("Skip export step (download data only)."),
        )
        dl_p.add_argument("--format", nargs="+", help=t("Output format(s)."))

    @classmethod
    def run(cls, args: Namespace) -> None:
        action: str | None = getattr(args, "legado_action", None)

        if action == "list":
            cls._run_list(args)
        elif action == "validate":
            cls._run_validate(args)
        elif action == "download":
            cls._run_download(args)
        else:
            ui.info(
                t(
                    "Usage: novel-dl legado <list|validate|download> ...\n"
                    "Run 'novel-dl legado --help' for details."
                )
            )

    # ------------------------------------------------------------------
    # 子动作实现
    # ------------------------------------------------------------------

    @classmethod
    def _run_list(cls, args: Namespace) -> None:
        """列出书源文件中的所有书源。"""
        from novel_downloader.plugins.sites.legado.schema import BookSource

        path = Path(args.source_file)
        if not path.is_file():
            ui.error(t("File not found: {path}").format(path=path))
            return

        try:
            sources = BookSource.from_file(path)
        except Exception as e:
            ui.error(t("Failed to parse book source file: {err}").format(err=e))
            return

        enabled_only: bool = getattr(args, "enabled_only", False)
        displayed = [s for s in sources if not enabled_only or s.enabled]

        if not displayed:
            ui.warn(t("No book sources found in {path}.").format(path=path))
            return

        ui.info(
            t("Found {n} book source(s) in {path}:").format(
                n=len(displayed), path=path.name
            )
        )
        for i, s in enumerate(displayed, 1):
            status = "✓" if s.enabled else "✗"
            print(
                f"  {i:3}. [{status}] {s.book_source_name or '(无名称)':30s}  "
                f"{s.book_source_url}"
            )

    @classmethod
    def _run_validate(cls, args: Namespace) -> None:
        """验证书源 JSON 文件格式。"""
        from novel_downloader.plugins.sites.legado.schema import BookSource

        path = Path(args.source_file)
        if not path.is_file():
            ui.error(t("File not found: {path}").format(path=path))
            return

        raw = path.read_text(encoding="utf-8")

        # 1. JSON 语法检查
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            ui.error(t("Invalid JSON: {err}").format(err=e))
            return

        ui.info(t("JSON syntax: OK"))

        # 2. 书源格式检查
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            ui.error(
                t("Expected a JSON array or object, got: {type}").format(
                    type=type(data).__name__
                )
            )
            return

        ok, fail = 0, 0
        for i, item in enumerate(data, 1):
            try:
                s = BookSource.from_dict(item)
                if not s.book_source_url:
                    ui.warn(t("  Entry {i}: missing 'bookSourceUrl'").format(i=i))
                    fail += 1
                else:
                    ok += 1
            except Exception as e:
                ui.warn(t("  Entry {i}: parse error – {err}").format(i=i, err=e))
                fail += 1

        if fail:
            ui.warn(
                t("Validation: {ok} OK, {fail} with issues (total {total}).").format(
                    ok=ok, fail=fail, total=ok + fail
                )
            )
        else:
            ui.info(
                t("Validation: all {n} source(s) OK.").format(n=ok)
            )

    @classmethod
    def _run_download(cls, args: Namespace) -> None:
        """使用书源下载指定 URL 的小说（代理 download 命令）。"""
        from novel_downloader.plugins.sites.legado.manager import book_source_manager

        source_file = args.source_file
        book_url = args.book_url

        # 加载书源
        count = book_source_manager.load_source_file(source_file)
        if count == 0:
            ui.error(
                t("No valid book sources loaded from: {path}").format(path=source_file)
            )
            return

        ui.info(
            t("Loaded {n} Legado book source(s) from {path}.").format(
                n=count, path=source_file
            )
        )

        # 检查 URL 是否有匹配书源
        if not book_source_manager.has_source_for_url(book_url):
            ui.error(
                t(
                    "No matching book source found for URL: {url}\n"
                    "Available sources in {file}:\n{sources}"
                ).format(
                    url=book_url,
                    file=source_file,
                    sources="\n".join(
                        f"  • {s['name']} ({s['url']})"
                        for s in book_source_manager.list_sources()
                    ),
                )
            )
            return

        # 注册 URL
        book_id = book_source_manager.register_url(book_url)
        source = book_source_manager.get_source_for_url(book_url)
        ui.info(
            t("Using book source: {name} ({url})").format(
                name=source.display_name if source else "?",
                url=book_url,
            )
        )

        # 构造 Namespace，复用 DownloadCmd.run() 的后半段逻辑
        from novel_downloader.apps.utils import load_or_init_config
        from novel_downloader.infra.config import ConfigAdapter
        from novel_downloader.plugins import registrar
        from novel_downloader.schemas import BookConfig

        from ..ui_adapters import CLIDownloadUI, CLIExportUI, CLIProcessUI

        config_path: Path | None = (
            Path(args.config) if getattr(args, "config", None) else None
        )
        formats: list[str] | None = getattr(args, "format", None)

        books = [
            BookConfig(
                book_id=book_id,
                start_id=getattr(args, "start", None),
                end_id=getattr(args, "end", None),
            )
        ]

        config_data = load_or_init_config(config_path)
        if config_data is None:
            return

        adapter = ConfigAdapter(config=config_data)
        formats = formats or adapter.get_export_fmt("legado")

        ui.setup_logging(
            log_dir=adapter.get_log_dir(),
            console_level=adapter.get_log_level(),
        )

        import asyncio

        download_ui = CLIDownloadUI()
        client = registrar.get_client("legado", adapter.get_client_config("legado"))

        async def download_books() -> None:
            try:
                async with client:
                    for book in books:
                        await client.download_book(book, ui=download_ui)
            except Exception as e:
                ui.error(t("Download error: {err}").format(err=e))

        asyncio.run(download_books())

        if not download_ui.completed_books:
            return

        if not getattr(args, "no_export", False):
            process_ui = CLIProcessUI()
            export_ui = CLIExportUI()

            for book in download_ui.completed_books:
                client.process_book(
                    book,
                    processors=adapter.get_processor_configs("legado"),
                    ui=process_ui,
                )
                client.export_book(
                    book,
                    formats=formats,
                    ui=export_ui,
                )
