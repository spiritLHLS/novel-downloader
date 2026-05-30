from __future__ import annotations

from novel_downloader.infra import http_defaults


def test_build_stealth_headers_uses_randomized_user_agent(
    monkeypatch,
):
    monkeypatch.setattr(http_defaults, "choose_user_agent", lambda: "UA-RANDOM")

    headers = http_defaults.build_stealth_headers(randomize_user_agent=True)

    assert headers["User-Agent"] == "UA-RANDOM"
    assert "Accept" in headers


def test_build_stealth_headers_uses_default_when_disabled():
    headers = http_defaults.build_stealth_headers(randomize_user_agent=False)

    assert headers["User-Agent"] == http_defaults.DEFAULT_USER_AGENT
