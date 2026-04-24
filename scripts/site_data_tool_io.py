#!/usr/bin/env python3
"""
HTML part IO helpers for scripts/site_data_tool.py.
"""

from __future__ import annotations

import re
from pathlib import Path


def save_html_parts(raw_pages: list[str], html_dir: Path, filename_prefix: str) -> None:
    """Save HTML parts like {prefix}_1.html, {prefix}_2.html, ..."""
    html_dir.mkdir(parents=True, exist_ok=True)
    for idx, html in enumerate(raw_pages, start=1):
        (html_dir / f"{filename_prefix}_{idx}.html").write_text(html, encoding="utf-8")


def load_html_parts(html_dir: Path, filename_prefix: str) -> list[str]:
    """Load HTML parts like {prefix}_1.html, {prefix}_2.html, ...
    Raises:
        FileNotFoundError: if html_dir does not exist.
    Returns:
        list[str]: ordered HTML parts; empty if there are no matching files.
    """
    if not html_dir.exists():
        raise FileNotFoundError(f"HTML directory does not exist: {html_dir}")

    pattern = f"{filename_prefix}_*.html"
    candidates = list(html_dir.glob(pattern))
    regex = re.compile(rf"^{re.escape(filename_prefix)}_(\d+)\.html$")
    indexed: list[tuple[int, Path]] = []
    for path in candidates:
        m = regex.match(path.name)
        if m:
            indexed.append((int(m.group(1)), path))

    if not indexed:
        return []

    indexed.sort()
    return [p.read_text(encoding="utf-8") for _, p in indexed]
