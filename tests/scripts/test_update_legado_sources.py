from __future__ import annotations

from importlib import util
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).parents[2] / "scripts" / "update_legado_sources.py"
)


def load_update_module():
    spec = util.spec_from_file_location("update_legado_sources", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_process_source_keeps_existing_file_when_remote_payload_invalid(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = load_update_module()
    output_dir = tmp_path / "legado_sources"
    output_dir.mkdir()

    output_path = output_dir / "sample.json"
    existing = [{"bookSourceUrl": "https://old.example/book"}]
    output_path.write_text(
        module.json.dumps(existing, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(module, "fetch_url", lambda url: b"[]")
    monkeypatch.setattr(module.time, "sleep", lambda _: None)

    status = module.process_source(
        {
            "name": "sample",
            "urls": ["https://example.invalid/sample.json"],
            "output": "sample.json",
            "min_size": 1,
        }
    )

    assert status is module.ProcessStatus.FAILED
    assert module.json.loads(output_path.read_text(encoding="utf-8")) == existing


def test_main_returns_nonzero_when_any_source_failed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = load_update_module()
    monkeypatch.setattr(module, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(
        module,
        "SOURCES",
        [
            {"name": "ok", "urls": ["https://example.invalid/ok"], "output": "ok.json"},
            {
                "name": "bad",
                "urls": ["https://example.invalid/bad"],
                "output": "bad.json",
            },
        ],
    )

    def fake_process_source(cfg):
        if cfg["name"] == "bad":
            return module.ProcessStatus.FAILED
        return module.ProcessStatus.SKIPPED

    monkeypatch.setattr(module, "process_source", fake_process_source)

    assert module.main() == 1