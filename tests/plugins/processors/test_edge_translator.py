from __future__ import annotations

from datetime import datetime

from novel_downloader.plugins.processors.translator.edge import (
    EdgeTranslaterProcessor,
)


def test_parse_jwt_without_exp_does_not_raise() -> None:
    processor = EdgeTranslaterProcessor({})
    token = "a.eyJzdWIiOiAidGVzdCJ9.c"

    parsed = processor._parse_jwt(token)

    assert parsed["token"] == token
    assert isinstance(parsed["expire"], datetime)


def test_translate_returns_original_text_when_token_fetch_fails() -> None:
    processor = EdgeTranslaterProcessor({"sleep": 0})
    processor._get_token = lambda: (_ for _ in ()).throw(RuntimeError("boom"))

    assert processor._translate("hello") == "hello"