#!/usr/bin/env python3
"""
novel_downloader.plugins.sites.legado.fetcher
----------------------------------------------

LegadoFetcher：通用 Legado 书源抓取器。

工作原理
--------
1. 通过 ``book_source_manager`` 根据 URL 找到对应 BookSource
2. 使用书源配置的 HTTP 请求头和 URL 规则发起请求
3. ``fetch_book_info`` 中内置了 ``tocUrl`` 的迷你规则求值，若目录页与
   详情页不同则自动追加请求
4. 返回的 raw_pages 第一项是特殊标记行（含书源 URL 信息），供 LegadoParser
   识别当前使用的书源

raw_pages 格式
--------------
``["__legado_meta__:<book_url>:<source_url>", html_page, ...]``

- ``html_page``：信息页（或目录页）的 HTML 字符串
- 若有独立目录页，则追加一个 html 字符串（raw_pages[2]）
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urljoin

from lxml import html as lxml_html

from novel_downloader.plugins.base.fetcher import BaseFetcher
from novel_downloader.plugins.registry import registrar
from novel_downloader.schemas import FetcherConfig

from .manager import book_source_manager
from .rule_engine import eval_rule

logger = logging.getLogger(__name__)

_META_PREFIX = "__legado_meta__:"


@registrar.register_fetcher()
class LegadoFetcher(BaseFetcher):
    """
    通用 Legado 书源抓取器。

    ``book_id``   = 书源管理器注册后的 URL 哈希 ID（由 book_url_resolver 生成）
    ``chapter_id``= 章节 URL 对应的哈希 ID（由 LegadoParser.parse_book_info 注册）
    """

    site_name: str = "legado"

    def __init__(
        self,
        config: FetcherConfig,
        cookies: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(config, cookies, **kwargs)

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    async def fetch_book_info(
        self,
        book_id: str,
        **kwargs: Any,
    ) -> list[str]:
        """
        获取书籍信息页（以及可能的独立目录页）。

        :param book_id: 书源管理器中注册的书籍 URL Hash ID。
        :return: raw_pages 列表：``[meta_marker, info_html, <toc_html>?]``
        """
        book_url = book_source_manager.get_url(book_id)
        if not book_url:
            logger.error("未找到 book_id=%r 对应的 URL，请确认书源已加载", book_id)
            return []

        source = book_source_manager.get_source_for_url(book_url)
        if not source:
            logger.error("无匹配书源（URL=%s），请先加载书源文件", book_url)
            return []

        headers = {**self.headers, **source.header}
        meta = f"{_META_PREFIX}{book_url}|{source.book_source_url}"

        # ---- 获取信息页 ----
        try:
            info_html = await self.fetch(book_url, headers=headers, **kwargs)
        except Exception as e:
            logger.error("获取书籍信息页失败（url=%s）：%s", book_url, e)
            return []

        pages: list[str] = [meta, info_html]

        # ---- 尝试获取独立目录页 ----
        toc_rule = source.rule_book_info.toc_url
        if toc_rule:
            toc_url = self._extract_toc_url(info_html, toc_rule, book_url)
            if toc_url and _normalize_url(toc_url) != _normalize_url(book_url):
                logger.debug("检测到独立目录页：%s", toc_url)
                try:
                    toc_html = await self.fetch(toc_url, headers=headers, **kwargs)
                    pages.append(toc_html)
                except Exception as e:
                    logger.warning("获取目录页失败（url=%s）：%s", toc_url, e)

        return pages

    async def fetch_chapter_content(
        self,
        book_id: str,
        chapter_id: str,
        **kwargs: Any,
    ) -> list[str]:
        """
        获取章节内容页。

        :param book_id:    书籍 URL Hash ID（用于查找书源）。
        :param chapter_id: 章节 URL Hash ID。
        :return: raw_pages：``[meta_marker, chapter_html]``
        """
        book_url = book_source_manager.get_url(book_id)
        chapter_url = book_source_manager.get_url(chapter_id)

        if not chapter_url:
            logger.error("未找到 chapter_id=%r 对应的 URL", chapter_id)
            return []

        source = book_source_manager.get_source_for_url(chapter_url)
        if source is None and book_url:
            # 可能章节在本书源域名下
            source = book_source_manager.get_source_for_url(book_url)

        if source is None:
            logger.error("无匹配书源（chapter_url=%s）", chapter_url)
            return []

        headers = {**self.headers, **source.header}
        meta = f"{_META_PREFIX}{chapter_url}|{source.book_source_url}"

        try:
            chapter_html = await self.fetch(chapter_url, headers=headers, **kwargs)
        except Exception as e:
            logger.error("获取章节内容失败（url=%s）：%s", chapter_url, e)
            return []

        return [meta, chapter_html]

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _extract_toc_url(
        self,
        html_text: str,
        toc_rule: str,
        page_url: str,
    ) -> str | None:
        """
        在已获取的 HTML 页面上执行 tocUrl 规则，提取目录页 URL。
        """
        try:
            tree = lxml_html.fromstring(html_text)
            results = eval_rule(toc_rule, tree, page_url)
            if results:
                url = results[0].strip()
                if url and not url.startswith(("http://", "https://")):
                    url = urljoin(page_url, url)
                return url or None
        except Exception as e:
            logger.debug("提取 tocUrl 失败（rule=%r）：%s", toc_rule, e)
        return None


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _normalize_url(url: str) -> str:
    """去掉末尾斜杠，方便比较。"""
    return url.rstrip("/").lower()
