#!/usr/bin/env python3
"""
novel_downloader.plugins.sites.legado.parser
---------------------------------------------

LegadoParser：通用 Legado 书源解析器。

与 LegadoFetcher 配合，从 raw_pages 的特殊 meta 行中读取书源上下文，
再利用书源规则解析书籍信息、目录和章节正文。

raw_pages 约定（与 LegadoFetcher 一致）
----------------------------------------
``["__legado_meta__:<current_url>|<source_base_url>", html_page, ...]``

- ``parse_book_info``   → raw_pages[1] = 详情页，raw_pages[2]（可选）= 目录页
- ``parse_chapter_content``  → raw_pages[1] = 章节页
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin

from lxml import html as lxml_html

from novel_downloader.plugins.base.parser import BaseParser
from novel_downloader.plugins.registry import registrar
from novel_downloader.schemas import (
    BookInfoDict,
    ChapterDict,
    ChapterInfoDict,
    VolumeInfoDict,
)

from .manager import book_source_manager
from .rule_engine import eval_rule, eval_rule_str, select_elements
from .schema import BookSource

logger = logging.getLogger(__name__)

_META_PREFIX = "__legado_meta__:"


@registrar.register_parser()
class LegadoParser(BaseParser):
    """
    通用 Legado 书源解析器。

    根据 BookSource 中的文本规则对 HTML 页面进行结构化提取。
    """

    site_name: str = "legado"

    # ------------------------------------------------------------------
    # 解析书籍信息 + 目录
    # ------------------------------------------------------------------

    def parse_book_info(
        self,
        raw_pages: list[str],
        **kwargs: Any,
    ) -> BookInfoDict | None:
        """
        解析书籍详情页（以及可选的目录页），返回 BookInfoDict。

        :param raw_pages: 来自 LegadoFetcher.fetch_book_info() 的页面列表。
        :return: 填充完整的书籍信息字典，或 None（解析失败）。
        """
        if not raw_pages:
            return None

        # ---- 读取 meta / 找书源 ----
        current_url, source = self._resolve_context(raw_pages)
        if source is None:
            logger.error("无法解析书源上下文，跳过")
            return None

        info_html = raw_pages[1] if len(raw_pages) > 1 else ""
        toc_html = raw_pages[2] if len(raw_pages) > 2 else info_html

        if not info_html:
            return None

        info_tree = lxml_html.fromstring(info_html)
        toc_tree = lxml_html.fromstring(toc_html)
        base_url = current_url or source.book_source_url

        # ---- 书籍元信息 ----
        r = source.rule_book_info

        book_name = eval_rule_str(r.name, info_tree, base_url)
        author = eval_rule_str(r.author, info_tree, base_url)
        cover_url = eval_rule_str(r.cover_url, info_tree, base_url)
        update_time = eval_rule_str(r.update_time, info_tree, base_url)
        kind = eval_rule_str(r.kind, info_tree, base_url)
        word_count = eval_rule_str(r.word_count, info_tree, base_url)
        intro_parts = eval_rule(r.intro, info_tree, base_url)
        summary = "\n".join(intro_parts)

        tags = [t.strip() for t in kind.split() if t.strip()]

        # ---- 章节目录 ----
        chapters = self._parse_toc(toc_tree, source, base_url)

        if not chapters and toc_html != info_html:
            # 如果没有从目录页解析到章节，尝试从信息页解析
            chapters = self._parse_toc(info_tree, source, base_url)

        if not chapters:
            logger.warning(
                "书源 %r 未解析到任何章节（url=%s）",
                source.display_name,
                base_url,
            )
            # 仍返回书籍信息，只是没有章节
            chapters = []

        volumes: list[VolumeInfoDict] = [{"volume_name": "正文", "chapters": chapters}]

        return {
            "book_name": book_name,
            "author": author,
            "cover_url": cover_url,
            "update_time": update_time,
            "summary": summary,
            "tags": tags,
            "word_count": word_count,
            "volumes": volumes,
            "extra": {
                "source": source.display_name,
                "source_url": source.book_source_url,
            },
        }

    def _parse_toc(
        self,
        tree: Any,
        source: BookSource,
        base_url: str,
    ) -> list[ChapterInfoDict]:
        """从 lxml 树中按目录规则提取章节列表。"""
        rt = source.rule_toc
        if not rt.chapter_list:
            return []

        items = select_elements(rt.chapter_list, tree)
        if not items:
            logger.debug("目录规则未匹配任何元素（rule=%r）", rt.chapter_list)
            return []

        chapters: list[ChapterInfoDict] = []
        for item in items:
            name = eval_rule_str(rt.chapter_name, item, base_url).strip()
            url_raw = eval_rule_str(rt.chapter_url, item, base_url).strip()

            if not url_raw:
                continue

            # 将相对 URL 转为绝对 URL
            if not url_raw.startswith(("http://", "https://")):
                url_raw = urljoin(base_url, url_raw)

            # 注册章节 URL 并获取稳定 ID
            chapter_id = book_source_manager.register_url(url_raw)

            if not name:
                name = f"第{len(chapters) + 1}章"

            chapters.append(
                {
                    "title": name,
                    "url": url_raw,
                    "chapterId": chapter_id,
                }
            )

        return chapters

    # ------------------------------------------------------------------
    # 解析章节正文
    # ------------------------------------------------------------------

    def parse_chapter_content(
        self,
        raw_pages: list[str],
        chapter_id: str,
        **kwargs: Any,
    ) -> ChapterDict | None:
        """
        从章节页 HTML 提取正文内容。

        :param raw_pages: 来自 LegadoFetcher.fetch_chapter_content() 的页面列表。
        :param chapter_id: 章节的哈希 ID。
        :return: ChapterDict 或 None（失败时）。
        """
        if not raw_pages:
            return None

        # ---- 读取 meta / 找书源 ----
        current_url, source = self._resolve_context(raw_pages)
        if source is None:
            return None

        chapter_html = raw_pages[1] if len(raw_pages) > 1 else ""
        if not chapter_html:
            return None

        tree = lxml_html.fromstring(chapter_html)
        base_url = current_url or source.book_source_url
        rc = source.rule_content

        # ---- 提取正文 ----
        content_parts = eval_rule(rc.content, tree, base_url)

        if not content_parts:
            # 降级：取 body 全文
            body_list = tree.xpath("//body")
            if body_list:
                text = body_list[0].text_content().strip()
                content_parts = [text] if text else []

        # ---- 应用正文替换规则 ----
        raw_content = "\n".join(content_parts)
        if rc.replace_regex:
            raw_content = self._apply_content_replace(raw_content, rc.replace_regex)

        # ---- 按行清洗 ----
        lines = [line.strip() for line in raw_content.splitlines()]
        lines = self._filter_ads(line for line in lines if line)

        # 去除常见噪声行（如连续空行）
        cleaned: list[str] = []
        for line in lines:
            if cleaned and not cleaned[-1] and not line:
                continue  # 折叠连续空行
            cleaned.append(line)

        content = "\n".join(cleaned).strip()

        return {
            "id": chapter_id,
            "title": "",  # 由 download mixin 用目录标题填充
            "content": content,
            "extra": {},
        }

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def _resolve_context(
        self,
        raw_pages: list[str],
    ) -> tuple[str, BookSource | None]:
        """
        从 raw_pages[0] 的元数据行解析当前 URL 和 BookSource。

        :return: (current_url, BookSource) 或 ("", None) 若失败。
        """
        if not raw_pages:
            return "", None

        meta = raw_pages[0]
        if not meta.startswith(_META_PREFIX):
            # 兼容：直接尝试用全部书源猜
            logger.debug("raw_pages[0] 不含 meta 标记，尝试降级")
            return "", None

        meta_body = meta[len(_META_PREFIX):]
        parts = meta_body.split("|", 1)
        current_url = parts[0].strip() if parts else ""
        source_base = parts[1].strip() if len(parts) > 1 else ""

        source = None
        # 优先按书源 base_url 查找
        if source_base:
            source = book_source_manager.get_source_for_url(source_base)
        # 降级按当前页 URL 查找
        if source is None and current_url:
            source = book_source_manager.get_source_for_url(current_url)

        if source is None:
            logger.error(
                "找不到书源（url=%s，source_base=%s）。"
                "请确认已通过 book_source_manager.load_source_file() 加载对应书源。",
                current_url,
                source_base,
            )

        return current_url, source

    @staticmethod
    def _apply_content_replace(content: str, replace_regex: str) -> str:
        """
        应用正文替换规则。

        格式：``pattern##replacement``（多条规则用 ``\n`` 分隔）。
        """
        for line in replace_regex.splitlines():
            line = line.strip()
            if not line:
                continue
            if "##" in line:
                pattern, _, replacement = line.partition("##")
            else:
                pattern, replacement = line, ""
            try:
                content = re.sub(pattern, replacement, content, flags=re.DOTALL)
            except re.error:
                logger.debug("正文替换规则无效: %r", line)
        return content
