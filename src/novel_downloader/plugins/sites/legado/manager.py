#!/usr/bin/env python3
"""
novel_downloader.plugins.sites.legado.manager
----------------------------------------------

书源管理器（BookSourceManager）。

* 加载 JSON 书源文件（单书源对象或书源数组）
* 按域名快速查找匹配的书源
* 管理 URL ↔ 稳定 ID 的双向映射（用于文件系统安全的书籍标识符）

全局单例
--------
::

    from novel_downloader.plugins.sites.legado.manager import book_source_manager
    book_source_manager.load_source_file("my_sources.json")
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from urllib.parse import urlparse

from .schema import BookSource

logger = logging.getLogger(__name__)


class BookSourceManager:
    """
    书源管理器。

    职责
    ----
    1. 加载 Legado JSON 格式书源文件
    2. 提供"给定 URL → 对应 BookSource"的查询接口
    3. 维护 URL ↔ 文件系统安全 ID 的双向映射表
    """

    def __init__(self) -> None:
        self._sources: list[BookSource] = []
        # 域名（netloc 小写）→ BookSource
        self._by_domain: dict[str, BookSource] = {}
        # 稳定 ID → 原始 URL
        self._id_to_url: dict[str, str] = {}
        # 原始 URL → 稳定 ID
        self._url_to_id: dict[str, str] = {}
        # 内置书源是否已加载
        self._builtin_loaded: bool = False

    # ------------------------------------------------------------------
    # 书源加载
    # ------------------------------------------------------------------

    def _ensure_builtin_loaded(self) -> None:
        """首次查询时自动加载打包的内置书源（懒加载，只执行一次）。"""
        if self._builtin_loaded:
            return
        self._builtin_loaded = True  # 先置 True，防止递归
        self.load_builtin_sources()

    def load_builtin_sources(self) -> int:
        """
        加载打包进项目的内置书源（位于 resources/legado_sources/）。

        :return: 成功加载的书源数量。
        """
        from importlib.resources import as_file

        from novel_downloader.infra.paths import LEGADO_SOURCES_DIR

        total = 0
        try:
            for item in LEGADO_SOURCES_DIR.iterdir():
                if not item.name.endswith(".json") or item.name.startswith("."):
                    continue
                try:
                    with as_file(item) as fp:
                        total += self.load_source_file(fp)
                except Exception as e:
                    logger.warning("加载内置书源文件 %s 失败: %s", item.name, e)
        except Exception as e:
            logger.debug("内置书源目录不可用: %s", e)
        if total:
            logger.info("已加载 %d 个内置书源", total)
        return total

    def load_source_file(self, path: str | Path) -> int:
        """
        从 JSON 文件加载书源。支持单对象和数组格式。

        :param path: JSON 文件路径。
        :return: 成功加载的书源数量。
        """
        path = Path(path)
        if not path.is_file():
            logger.warning("书源文件不存在: %s", path)
            return 0

        try:
            sources = BookSource.from_file(path)
        except Exception as e:
            logger.error("加载书源文件失败 %s: %s", path, e)
            return 0

        count = 0
        for source in sources:
            if not source.book_source_url:
                continue
            if not source.enabled:
                logger.debug("书源已禁用，跳过: %s", source.display_name)
                continue
            try:
                domain = urlparse(source.book_source_url).netloc.lower()
                if not domain:
                    continue
                if domain not in self._by_domain:
                    self._sources.append(source)
                    self._by_domain[domain] = source
                    count += 1
                    logger.debug("已加载书源: %s (%s)", source.display_name, domain)
                else:
                    logger.debug(
                        "书源域名已存在，跳过重复: %s (%s)",
                        source.display_name,
                        domain,
                    )
            except Exception as e:
                logger.debug("注册书源失败 %r: %s", source.display_name, e)

        logger.info(
            "从 %s 加载了 %d 个书源（共 %d 个书源已启用）",
            path.name,
            count,
            len(self._sources),
        )
        return count

    def load_source_dir(self, dirpath: str | Path) -> int:
        """
        递归扫描目录，加载所有 .json 文件中的书源。

        :param dirpath: 含书源 JSON 文件的目录。
        :return: 总共加载的书源数量。
        """
        dirpath = Path(dirpath)
        total = 0
        for json_file in sorted(dirpath.rglob("*.json")):
            total += self.load_source_file(json_file)
        return total

    def add_source(self, source: BookSource) -> bool:
        """
        手动添加单个书源对象。

        :return: True 表示成功添加，False 表示已存在或无效。
        """
        if not source.book_source_url or not source.enabled:
            return False
        domain = urlparse(source.book_source_url).netloc.lower()
        if not domain or domain in self._by_domain:
            return False
        self._sources.append(source)
        self._by_domain[domain] = source
        return True

    # ------------------------------------------------------------------
    # 书源查询
    # ------------------------------------------------------------------

    def get_source_for_url(self, url: str) -> BookSource | None:
        """
        根据 URL 查找对应书源（匹配域名）。

        首次调用时自动加载内置书源。

        :param url: 书籍或章节的完整 URL。
        :return: 匹配的 BookSource，或 None。
        """
        self._ensure_builtin_loaded()
        if not url:
            return None
        try:
            domain = urlparse(url).netloc.lower()
            return self._by_domain.get(domain)
        except Exception:
            return None

    def has_source_for_url(self, url: str) -> bool:
        """判断给定 URL 是否有对应的已加载书源。"""
        return self.get_source_for_url(url) is not None

    @property
    def sources(self) -> list[BookSource]:
        """返回所有已加载书源的列表（只读副本）。"""
        return list(self._sources)

    @property
    def source_count(self) -> int:
        """已加载的书源数量。"""
        return len(self._sources)

    # ------------------------------------------------------------------
    # URL ↔ 稳定 ID 映射
    # ------------------------------------------------------------------

    def register_url(self, url: str) -> str:
        """
        注册 URL 并返回其文件系统安全的稳定 ID。

        ID 由 URL 的 SHA-256 哈希前 16 位生成，保证唯一性和可
        重复生成性（只要 URL 不变，同一 ID 始终对应同一 URL）。

        :param url: 需要注册的完整 URL。
        :return: 16 位十六进制字符串 ID。
        """
        if url in self._url_to_id:
            return self._url_to_id[url]
        id_ = hashlib.sha256(url.encode()).hexdigest()[:16]
        self._url_to_id[url] = id_
        self._id_to_url[id_] = url
        return id_

    def get_url(self, id_: str) -> str | None:
        """
        根据 ID 查找对应 URL。

        :return: 原始 URL，或 None（ID 未注册）。
        """
        return self._id_to_url.get(id_)

    def require_url(self, id_: str) -> str:
        """
        根据 ID 获取 URL，不存在时抛出 ``KeyError``。
        """
        url = self._id_to_url.get(id_)
        if url is None:
            raise KeyError(
                f"书源 URL 未注册（ID={id_!r}）。"
                "请确保先调用 register_url() 或通过 resolve_book_url() 获取 book_id。"
            )
        return url

    # ------------------------------------------------------------------
    # 导出 / 调试
    # ------------------------------------------------------------------

    def list_sources(self) -> list[dict[str, str]]:
        """返回所有书源的摘要信息列表（name, url, file）。"""
        return [
            {
                "name": s.book_source_name,
                "url": s.book_source_url,
                "file": s._source_file,
            }
            for s in self._sources
        ]

    def __repr__(self) -> str:
        return f"BookSourceManager(sources={len(self._sources)})"


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

book_source_manager = BookSourceManager()
