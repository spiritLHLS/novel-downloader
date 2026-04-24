from __future__ import annotations

import json

from novel_downloader.plugins.sites.shaoniandream.parser import ShaoniandreamParser
from novel_downloader.schemas import ParserConfig


def test_parse_chapter_content_handles_missing_encrypt_keys() -> None:
    parser = ShaoniandreamParser(ParserConfig())
    raw_pages = [
        json.dumps(
            {
                "status": 1,
                "data": {
                    "title": "chapter",
                    "imgPrefix": "",
                    "encryt_keys": [],
                    "show_content": [{"content": "ZmFrZQ=="}],
                    "chapterpic": [],
                },
            }
        )
    ]

    assert parser.parse_chapter_content(raw_pages, "1") is None