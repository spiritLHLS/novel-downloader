from __future__ import annotations

import pytest

from novel_downloader.infra.book_url_resolver import resolve_book_url
from novel_downloader.plugins.sites.legado.manager import (
    BookSourceManager,
    book_source_manager,
)
from novel_downloader.plugins.sites.legado.schema import BookSource


@pytest.fixture
def isolated_global_legado_manager():
    snapshot = {
        "_sources": book_source_manager._sources.copy(),
        "_by_domain": book_source_manager._by_domain.copy(),
        "_pattern_sources": book_source_manager._pattern_sources.copy(),
        "_id_to_url": book_source_manager._id_to_url.copy(),
        "_url_to_id": book_source_manager._url_to_id.copy(),
        "_builtin_loaded": book_source_manager._builtin_loaded,
    }

    book_source_manager._sources = []
    book_source_manager._by_domain = {}
    book_source_manager._pattern_sources = []
    book_source_manager._id_to_url = {}
    book_source_manager._url_to_id = {}
    book_source_manager._builtin_loaded = True

    yield book_source_manager

    book_source_manager._sources = snapshot["_sources"]
    book_source_manager._by_domain = snapshot["_by_domain"]
    book_source_manager._pattern_sources = snapshot["_pattern_sources"]
    book_source_manager._id_to_url = snapshot["_id_to_url"]
    book_source_manager._url_to_id = snapshot["_url_to_id"]
    book_source_manager._builtin_loaded = snapshot["_builtin_loaded"]


def test_book_source_manager_matches_book_url_pattern() -> None:
    manager = BookSourceManager()
    source = BookSource(
        book_source_url="https://www.qidian.com",
        book_source_name="起点中文",
        book_url_pattern=r"https://m\.qidian\.com/book/.+",
    )

    assert manager.add_source(source) is True
    assert (
        manager.get_source_for_url("https://www.qidian.com/book/1043925220/")
        == source
    )
    assert manager.get_source_for_url("https://qidian.com/book/1043925220/") == source
    assert manager.get_source_for_url("https://m.qidian.com/book/1043925220/") == source


def test_resolve_book_url_uses_legado_book_url_pattern(
    isolated_global_legado_manager: BookSourceManager,
) -> None:
    url = "https://m.qidian.com/book/1043925220/"
    source = BookSource(
        book_source_url="https://www.qidian.com",
        book_source_name="起点中文",
        book_url_pattern=r"https://m\.qidian\.com/book/.+",
    )

    assert isolated_global_legado_manager.add_source(source) is True

    result = resolve_book_url(url)

    assert result is not None
    assert result["site_key"] == "legado"
    assert result["chapter_id"] is None
    assert result["book_id"] is not None
    assert isolated_global_legado_manager.get_url(result["book_id"]) == url