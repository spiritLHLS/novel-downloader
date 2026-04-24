from __future__ import annotations

from novel_downloader.infra.paths import LEGADO_SOURCES_DIR
from novel_downloader.plugins.sites.legado.manager import BookSourceManager


def test_bundled_legado_sources_exist_and_load() -> None:
    bundled_files = {
        item.name
        for item in LEGADO_SOURCES_DIR.iterdir()
        if item.name.endswith(".json") and not item.name.startswith(".")
    }

    assert {"tickmao.json", "xiuyuedu.json"} <= bundled_files

    manager = BookSourceManager()
    loaded = manager.load_builtin_sources()

    assert loaded > 0
    assert manager.source_count == loaded