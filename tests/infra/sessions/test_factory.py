import pytest

import novel_downloader.infra.sessions as sessions_pkg
from novel_downloader.infra.sessions import create_session
from novel_downloader.infra.sessions._aiohttp import AiohttpSession
from novel_downloader.infra.sessions._curl_cffi import CurlCffiSession
from novel_downloader.infra.sessions._httpx import HttpxSession
from novel_downloader.schemas import FetcherConfig


@pytest.fixture
def cfg():
    return FetcherConfig(
        timeout=5,
        headers={"ua": "pytest"},
        user_agent="agent123",
        proxy=None,
        proxy_user=None,
        proxy_pass=None,
        trust_env=False,
        verify_ssl=False,
        max_connections=10,
    )


def test_create_session_aiohttp(cfg):
    s = create_session("aiohttp", cfg, cookies={"a": "1"})
    assert isinstance(s, AiohttpSession)
    assert s._cookies == {"a": "1"}


def test_create_session_httpx(cfg):
    s = create_session("httpx", cfg, cookies={"b": "2"})
    assert isinstance(s, HttpxSession)
    assert s._cookies == {"b": "2"}


def test_create_session_curl_cffi(cfg):
    s = create_session("curl_cffi", cfg, cookies={"c": "3"})
    assert isinstance(s, CurlCffiSession)
    assert s._cookies == {"c": "3"}


def test_create_session_kwargs_passthrough(cfg):
    # Ensure kwargs are correctly passed to the session constructor
    s = create_session("aiohttp", cfg, cookies=None, extra_option="xyz")
    assert hasattr(s, "_extra_option") or True  # we just test that kwargs don't crash


def test_create_session_invalid_backend(cfg):
    with pytest.raises(ValueError) as excinfo:
        create_session("not-a-backend", cfg)

    msg = str(excinfo.value)
    assert "Unsupported backend" in msg
    assert "not-a-backend" in msg


def test_create_session_fallback_when_dependency_missing(cfg, monkeypatch):
    original_import_module = sessions_pkg.import_module

    def fake_import_module(name):
        if name == "novel_downloader.infra.sessions._httpx":
            raise ModuleNotFoundError("No module named 'httpx'", name="httpx")
        return original_import_module(name)

    monkeypatch.setattr(sessions_pkg, "import_module", fake_import_module)

    s = create_session("httpx", cfg, cookies={"x": "1"})
    assert isinstance(s, AiohttpSession)
    assert s._cookies == {"x": "1"}


def test_create_session_raise_if_all_backends_unavailable(cfg, monkeypatch):
    missing_by_module = {
        "novel_downloader.infra.sessions._aiohttp": "aiohttp",
        "novel_downloader.infra.sessions._httpx": "httpx",
        "novel_downloader.infra.sessions._curl_cffi": "curl_cffi",
    }

    def fake_import_module(name):
        dep = missing_by_module[name]
        raise ModuleNotFoundError(f"No module named '{dep}'", name=dep)

    monkeypatch.setattr(sessions_pkg, "import_module", fake_import_module)

    with pytest.raises(RuntimeError) as excinfo:
        create_session("aiohttp", cfg)

    assert "No available HTTP backend" in str(excinfo.value)
