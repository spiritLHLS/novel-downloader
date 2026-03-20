#!/usr/bin/env python3
"""
novel_downloader.plugins.sites.legado
--------------------------------------

Legado (阅读) 书源适配器。

支持加载标准 Legado JSON 格式书源文件，使用其内置规则动态抓取任意
书源配置中描述的小说网站的内容。

使用方法
--------
在下载前，先通过 ``book_source_manager`` 加载书源文件::

    from novel_downloader.plugins.sites.legado import book_source_manager
    book_source_manager.load_source_file("my_sources.json")

之后直接将书籍 URL 传给下载命令，系统会自动识别对应书源。
"""

from .manager import book_source_manager
from .schema import BookSource

__all__ = ["book_source_manager", "BookSource"]
