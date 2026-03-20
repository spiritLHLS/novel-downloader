#!/usr/bin/env python3
"""
novel_downloader.plugins.sites.legado.schema
--------------------------------------------

Legado（阅读 App）书源 JSON 格式的数据结构定义。

参考：https://github.com/gedoor/legado/blob/master/app/src/main/java/io/legado/app/data/entities/BookSource.kt
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SearchRule:
    """书源搜索规则（ruleSearch）"""

    book_list: str = ""    # 书列表选择规则
    name: str = ""         # 书名
    author: str = ""       # 作者
    book_url: str = ""     # 详情页 URL
    cover_url: str = ""    # 封面图 URL
    intro: str = ""        # 简介
    kind: str = ""         # 分类/标签
    last_chapter: str = "" # 最新章节名


@dataclass
class BookInfoRule:
    """书籍详情规则（ruleBookInfo）"""

    name: str = ""          # 书名
    author: str = ""        # 作者
    cover_url: str = ""     # 封面图 URL
    intro: str = ""         # 简介
    toc_url: str = ""       # 目录页 URL（为空时表示当前页即目录）
    update_time: str = ""   # 更新时间
    kind: str = ""          # 分类/标签
    word_count: str = ""    # 字数
    last_chapter: str = ""  # 最新章节名


@dataclass
class TocRule:
    """目录规则（ruleToc）"""

    pre_rule: str = ""      # 预处理 JS（暂不支持）
    chapter_list: str = ""  # 章节列表选择规则
    chapter_name: str = ""  # 章节名称
    chapter_url: str = ""   # 章节 URL
    is_vip: str = ""        # 是否 VIP（付费章节）
    update_time: str = ""   # 章节更新时间


@dataclass
class ContentRule:
    """正文规则（ruleContent）"""

    content: str = ""          # 正文内容选择规则
    next_content_url: str = "" # 下一页 URL（分页）
    replace_regex: str = ""    # 正文替换正则（格式：pattern##replacement）
    image_style: str = ""      # 图片样式（full/square 等）


@dataclass
class BookSource:
    """
    Legado 书源完整定义。

    对应 Legado App 导出的 JSON 格式，支持单个书源对象或书源数组。
    """

    book_source_url: str = ""         # 书源根 URL（域名基准）
    book_source_name: str = ""        # 书源名称
    book_source_type: int = 0         # 类型：0=文字, 1=音频, 2=图片
    enabled: bool = True              # 是否启用
    book_source_comment: str = ""     # 书源备注
    header: dict[str, str] = field(default_factory=dict)  # 自定义 HTTP 请求头
    search_url: str = ""              # 搜索 URL 模板（支持 {{key}} {{page}}）
    rule_search: SearchRule = field(default_factory=SearchRule)
    rule_book_info: BookInfoRule = field(default_factory=BookInfoRule)
    rule_toc: TocRule = field(default_factory=TocRule)
    rule_content: ContentRule = field(default_factory=ContentRule)
    # 用于标识书源的来源文件路径（加载后自动设置）
    _source_file: str = field(default="", repr=False, compare=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BookSource":
        """从字典（Legado JSON 对象）构建 BookSource。"""

        def _header(raw: Any) -> dict[str, str]:
            if isinstance(raw, dict):
                return {str(k): str(v) for k, v in raw.items()}
            if isinstance(raw, str) and raw.strip():
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        return {str(k): str(v) for k, v in parsed.items()}
                except json.JSONDecodeError:
                    pass
            return {}

        def _search_rule(raw: Any) -> SearchRule:
            if not isinstance(raw, dict):
                return SearchRule()
            return SearchRule(
                book_list=raw.get("bookList", ""),
                name=raw.get("name", ""),
                author=raw.get("author", ""),
                book_url=raw.get("bookUrl", ""),
                cover_url=raw.get("coverUrl", ""),
                intro=raw.get("intro", ""),
                kind=raw.get("kind", ""),
                last_chapter=raw.get("lastChapter", ""),
            )

        def _book_info_rule(raw: Any) -> BookInfoRule:
            if not isinstance(raw, dict):
                return BookInfoRule()
            return BookInfoRule(
                name=raw.get("name", ""),
                author=raw.get("author", ""),
                cover_url=raw.get("coverUrl", ""),
                intro=raw.get("intro", ""),
                toc_url=raw.get("tocUrl", ""),
                update_time=raw.get("updateTime", ""),
                kind=raw.get("kind", ""),
                word_count=raw.get("wordCount", ""),
                last_chapter=raw.get("lastChapter", ""),
            )

        def _toc_rule(raw: Any) -> TocRule:
            if not isinstance(raw, dict):
                return TocRule()
            return TocRule(
                pre_rule=raw.get("preRule", ""),
                chapter_list=raw.get("chapterList", ""),
                chapter_name=raw.get("chapterName", ""),
                chapter_url=raw.get("chapterUrl", ""),
                is_vip=raw.get("isVip", ""),
                update_time=raw.get("updateTime", ""),
            )

        def _content_rule(raw: Any) -> ContentRule:
            if not isinstance(raw, dict):
                return ContentRule()
            return ContentRule(
                content=raw.get("content", ""),
                next_content_url=raw.get("nextContentUrl", ""),
                replace_regex=raw.get("replaceRegex", ""),
                image_style=raw.get("imageStyle", ""),
            )

        return cls(
            book_source_url=data.get("bookSourceUrl", "").rstrip("/"),
            book_source_name=data.get("bookSourceName", ""),
            book_source_type=int(data.get("bookSourceType", 0)),
            enabled=bool(data.get("enabled", True)),
            book_source_comment=data.get("bookSourceComment", ""),
            header=_header(data.get("header", "")),
            search_url=data.get("searchUrl", ""),
            rule_search=_search_rule(data.get("ruleSearch")),
            rule_book_info=_book_info_rule(data.get("ruleBookInfo")),
            rule_toc=_toc_rule(data.get("ruleToc")),
            rule_content=_content_rule(data.get("ruleContent")),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "list[BookSource]":
        """从 JSON 字符串解析，支持单个对象或数组。"""
        data = json.loads(json_str)
        if isinstance(data, dict):
            data = [data]
        sources = []
        for item in data:
            try:
                sources.append(cls.from_dict(item))
            except Exception as e:
                logger.debug("跳过无效书源条目: %s", e)
        return sources

    @classmethod
    def from_file(cls, path: str | Path) -> "list[BookSource]":
        """从 JSON 文件加载书源列表。"""
        path = Path(path)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        sources = cls.from_json(text)
        for s in sources:
            s._source_file = str(path)
        return sources

    @property
    def display_name(self) -> str:
        """书源展示名，优先使用名称，否则用 URL。"""
        return self.book_source_name or self.book_source_url

    def __repr__(self) -> str:
        return f"BookSource(name={self.book_source_name!r}, url={self.book_source_url!r})"
