from __future__ import annotations

import pytest

from novel_downloader.plugins import search as search_module


def _make_result(site: str, priority: int) -> dict[str, str | int]:
    return {
        "site": site,
        "book_id": f"{site}-book",
        "book_url": f"https://{site}.example/book/1",
        "cover_url": f"https://{site}.example/cover.jpg",
        "title": f"{site} title",
        "author": f"{site} author",
        "latest_chapter": "chapter-1",
        "update_date": "2025-01-01",
        "word_count": "1000",
        "priority": priority,
    }


def _make_searcher(site: str, priority: int, calls: list[tuple[str, str, int]]):
    class DummySearcher:
        nsfw = False

        def __init__(self, session) -> None:
            self.session = session

        async def search(self, keyword: str, limit: int = 5):
            calls.append((site, keyword, limit))
            return [_make_result(site, priority)]

    return DummySearcher


@pytest.mark.asyncio
async def test_search_dispatches_keyword_to_all_registered_searchers(monkeypatch):
    calls: list[tuple[str, str, int]] = []
    searchers = [
        _make_searcher("alpha", 20, calls),
        _make_searcher("beta", 10, calls),
        _make_searcher("gamma", 30, calls),
    ]

    monkeypatch.setattr(
        search_module.registrar,
        "get_searcher_classes",
        lambda sites, load_all_if_none=True: searchers,
    )

    results = await search_module.search("斗罗大陆", per_site_limit=3)

    assert calls == [
        ("alpha", "斗罗大陆", 3),
        ("beta", "斗罗大陆", 3),
        ("gamma", "斗罗大陆", 3),
    ]
    assert [result["site"] for result in results] == ["beta", "alpha", "gamma"]
