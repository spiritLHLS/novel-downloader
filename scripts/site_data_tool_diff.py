#!/usr/bin/env python3
"""
Diff and navigation helpers for scripts/site_data_tool.py.
"""

from __future__ import annotations

import html as py_html
import json
from collections.abc import Iterable
from itertools import zip_longest
from typing import Any

from nicegui import ui

_MISSING = object()


def _go(target: str):
    def _handler(*_: Any) -> None:
        ui.navigate.to(target)

    return _handler


def _split_lines(text: str) -> list[str]:
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    return t.split("\n")


def _is_scalar(x: Any) -> bool:
    return isinstance(x, str | int | float | bool) or x is None


def _dump_scalar(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False)


def _iter_sorted_keys(d: dict[str, Any]) -> Iterable[str]:
    return sorted(d.keys(), key=lambda k: str(k))


def _indent_css(level: int) -> str:
    return f"margin-left:{level * 16}px;" if level > 0 else ""


def _box_html(kind: str, body_html: str, indent_level: int = 0) -> str:
    """kind in {'eq','del','ins','struct'}"""
    styles = {
        "eq": ("#9ca3af", "rgba(229,231,235,.45)"),
        "del": ("#ef4444", "rgba(254,226,226,.60)"),
        "ins": ("#10b981", "rgba(220,252,231,.60)"),
        "struct": ("#d1d5db", "transparent"),
    }
    border, bg = styles.get(kind, styles["eq"])
    return (
        '<div style="box-sizing:border-box;'
        f"border-left:4px solid {border};background:{bg};"
        "padding:.20rem .5rem;margin:.18rem 0;border-radius:6px;"
        "display:flex;gap:.5rem;align-items:flex-start;"
        f'{_indent_css(indent_level)}">'
        f'<div style="flex:1 1 auto">{body_html}</div>'
        "</div>"
    )


def _code(k: str) -> str:
    return f"<code>{py_html.escape(k)}</code>"


def _kv_line(prefix_html: str, v: Any) -> str:
    try:
        value = _dump_scalar(v) if _is_scalar(v) else json.dumps(v, ensure_ascii=False)
    except Exception:
        value = repr(v)
    return f"{prefix_html} {py_html.escape(value)}"


def _struct_diff_html(
    a: Any, b: Any, *, limit: int, level: int, diff_only: bool
) -> list[str]:
    out: list[str] = []

    if _is_scalar(a) and _is_scalar(b):
        if a == b:
            if not diff_only:
                out.append(_box_html("eq", _kv_line("", a), level))
        else:
            out.append(_box_html("del", _kv_line("", a), level))
            out.append(_box_html("ins", _kv_line("", b), level))
        return out

    if isinstance(a, dict) and isinstance(b, dict):
        if not diff_only:
            out.append(_box_html("struct", "<strong>dict</strong> {", level))
        a_keys = set(a.keys())
        b_keys = set(b.keys())
        for k in _iter_sorted_keys({**dict.fromkeys(a_keys | b_keys)}):
            in_a, in_b = k in a_keys, k in b_keys
            key_html = _code(str(k)) + ":"
            if in_a and not in_b:
                v = a[k]
                if _is_scalar(v):
                    out.append(_box_html("del", _kv_line(key_html, v), level + 1))
                else:
                    out.append(_box_html("del", f"{key_html}", level + 1))
                    out.extend(
                        _struct_render_full(v, limit=limit, level=level + 2, kind="del")
                    )
                continue
            if in_b and not in_a:
                v = b[k]
                if _is_scalar(v):
                    out.append(_box_html("ins", _kv_line(key_html, v), level + 1))
                else:
                    out.append(_box_html("ins", f"{key_html}", level + 1))
                    out.extend(
                        _struct_render_full(v, limit=limit, level=level + 2, kind="ins")
                    )
                continue

            va, vb = a[k], b[k]
            if _is_scalar(va) and _is_scalar(vb):
                if va == vb:
                    if not diff_only:
                        out.append(_box_html("eq", _kv_line(key_html, va), level + 1))
                else:
                    out.append(_box_html("del", _kv_line(key_html, va), level + 1))
                    out.append(_box_html("ins", _kv_line(key_html, vb), level + 1))
            else:
                child = _struct_diff_html(
                    va, vb, limit=limit, level=level + 2, diff_only=diff_only
                )
                if child:
                    out.append(_box_html("struct", f"{key_html}", level + 1))
                    out.extend(child)
        if not diff_only:
            out.append(_box_html("struct", "}", level))
        return out

    if isinstance(a, list) and isinstance(b, list):
        len_a, len_b = len(a), len(b)
        if not diff_only:
            out.append(
                _box_html(
                    "struct", f"<strong>list</strong> [A={len_a}, B={len_b}]", level
                )
            )
        show_a = len_a if limit <= 0 else min(len_a, limit)
        show_b = len_b if limit <= 0 else min(len_b, limit)
        show = max(show_a, show_b)
        for i in range(show):
            va = a[i] if i < len_a else _MISSING
            vb = b[i] if i < len_b else _MISSING
            idx_html = f"{_code(f'[{i}]')}:"
            if va is _MISSING:
                if _is_scalar(vb):
                    out.append(_box_html("ins", _kv_line(idx_html, vb), level + 1))
                else:
                    out.append(_box_html("ins", f"{idx_html}", level + 1))
                    out.extend(
                        _struct_render_full(
                            vb, limit=limit, level=level + 2, kind="ins"
                        )
                    )
                continue
            if vb is _MISSING:
                if _is_scalar(va):
                    out.append(_box_html("del", _kv_line(idx_html, va), level + 1))
                else:
                    out.append(_box_html("del", f"{idx_html}", level + 1))
                    out.extend(
                        _struct_render_full(
                            va, limit=limit, level=level + 2, kind="del"
                        )
                    )
                continue
            if _is_scalar(va) and _is_scalar(vb):
                if va == vb:
                    if not diff_only:
                        out.append(_box_html("eq", _kv_line(idx_html, va), level + 1))
                else:
                    out.append(_box_html("del", _kv_line(idx_html, va), level + 1))
                    out.append(_box_html("ins", _kv_line(idx_html, vb), level + 1))
            else:
                child = _struct_diff_html(
                    va, vb, limit=limit, level=level + 2, diff_only=diff_only
                )
                if child:
                    out.append(_box_html("struct", f"{idx_html}", level + 1))
                    out.extend(child)

        tail_a = len_a - show if show < len_a else 0
        tail_b = len_b - show if show < len_b else 0
        if (tail_a or tail_b) and not diff_only:
            out.append(
                _box_html("struct", f"... trimmed (A:{tail_a}, B:{tail_b})", level + 1)
            )
        return out

    out.append(_box_html("del", _one_line_html(a), level))
    out.append(_box_html("ins", _one_line_html(b), level))
    return out


def _struct_render_full(obj: Any, *, limit: int, level: int, kind: str) -> list[str]:
    """Render subtree in a compact single-sided way (for pure add/remove)."""
    out: list[str] = []
    if _is_scalar(obj):
        out.append(_box_html(kind, _kv_line("", obj), level))
        return out
    if isinstance(obj, dict):
        out.append(_box_html(kind, "<strong>dict</strong> {", level))
        for k in _iter_sorted_keys(obj):
            v = obj[k]
            key_html = _code(str(k)) + ":"
            if _is_scalar(v):
                out.append(_box_html(kind, _kv_line(key_html, v), level + 1))
            else:
                out.append(_box_html(kind, f"{key_html}", level + 1))
                out.extend(
                    _struct_render_full(v, limit=limit, level=level + 2, kind=kind)
                )
        out.append(_box_html(kind, "}", level))
        return out
    if isinstance(obj, list):
        n = len(obj)
        out.append(_box_html(kind, f"<strong>list</strong> [len={n}]", level))
        show = n if limit <= 0 else min(n, limit)
        for i in range(show):
            v = obj[i]
            idx_html = f"{_code(f'[{i}]')}:"
            if _is_scalar(v):
                out.append(_box_html(kind, _kv_line(idx_html, v), level + 1))
            else:
                out.append(_box_html(kind, f"{idx_html}", level + 1))
                out.extend(
                    _struct_render_full(v, limit=limit, level=level + 2, kind=kind)
                )
        if show < n:
            out.append(_box_html(kind, f"... ({n - show} more)", level + 1))
        return out
    out.append(_box_html(kind, _one_line_html(obj), level))
    return out


def _one_line_html(obj: Any) -> str:
    try:
        if _is_scalar(obj):
            return py_html.escape(_dump_scalar(obj))
        return py_html.escape(json.dumps(obj, ensure_ascii=False))
    except Exception:
        return py_html.escape(repr(obj))


def struct_diff_html(a: Any, b: Any, *, limit: int = 50, diff_only: bool = True) -> str:
    """Public: build the HTML for structured diffs."""
    blocks = _struct_diff_html(a, b, limit=limit, level=0, diff_only=diff_only)
    return "".join(blocks)


def _char_level_diff(old: str, new: str) -> tuple[str, str]:
    """Return (old_html, new_html) with <del>/<ins> highlighting at char level."""
    import difflib

    s = difflib.SequenceMatcher(a=old, b=new)
    old_out: list[str] = []
    new_out: list[str] = []
    for tag, i1, i2, j1, j2 in s.get_opcodes():
        a = py_html.escape(old[i1:i2])
        b = py_html.escape(new[j1:j2])
        if tag == "equal":
            old_out.append(a)
            new_out.append(b)
        elif tag == "delete":
            old_out.append(
                '<del style="background:#ffeef0;color:#a00;'
                f'text-decoration:line-through">{a}</del>'
            )
        elif tag == "insert":
            new_out.append(
                '<ins style="background:#e6ffed;color:#065f46;'
                f'text-decoration:none">{b}</ins>'
            )
        elif tag == "replace":
            old_out.append(
                '<del style="background:#ffeef0;color:#a00;'
                f'text-decoration:line-through">{a}</del>'
            )
            new_out.append(
                '<ins style="background:#e6ffed;color:#065f46;'
                f'text-decoration:none">{b}</ins>'
            )
    return "".join(old_out), "".join(new_out)


def diff_lines_html(old_text: str, new_text: str, *, show_equals: bool = True) -> str:
    """Build a block-level diff with per-line boxes and char-level highlights.
    When show_equals=False, identical lines are omitted (diff-only mode)."""
    import difflib

    def _line_box(inner_html: str, kind: str) -> str:
        styles = {
            "eq": ("#9ca3af", "rgba(229,231,235,.45)"),
            "del": ("#ef4444", "rgba(254,226,226,.60)"),
            "ins": ("#10b981", "rgba(220,252,231,.60)"),
            "rep_old": ("#ef4444", "rgba(254,226,226,.50)"),
            "rep_new": ("#10b981", "rgba(220,252,231,.50)"),
        }
        border, bg = styles.get(kind, styles["eq"])
        return (
            '<div style="width:100%;box-sizing:border-box;'
            "display:flex;align-items:flex-start;gap:.5rem;"
            "margin:.18rem 0;padding:.20rem .5rem;"
            f'border-left:4px solid {border};background:{bg};border-radius:6px;">'
            f'<div style="flex:1 1 auto">{inner_html}</div>'
            "</div>"
        )

    old_lines = _split_lines(old_text)
    new_lines = _split_lines(new_text)
    sm = difflib.SequenceMatcher(a=old_lines, b=new_lines)

    parts: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            if show_equals:
                for k in range(i2 - i1):
                    line = py_html.escape(old_lines[i1 + k])
                    parts.append(_line_box(f"<span>{line}</span>", "eq"))
        elif tag == "delete":
            for k in range(i2 - i1):
                old_line = py_html.escape(old_lines[i1 + k])
                parts.append(_line_box(f"<span>{old_line}</span>", "del"))
        elif tag == "insert":
            for k in range(j2 - j1):
                new_line = py_html.escape(new_lines[j1 + k])
                parts.append(_line_box(f"<span>{new_line}</span>", "ins"))
        elif tag == "replace":
            for a, b in zip_longest(old_lines[i1:i2], new_lines[j1:j2], fillvalue=""):
                o, n = _char_level_diff(a, b)
                parts.append(_line_box(o, "rep_old"))
                parts.append(_line_box(n, "rep_new"))
    return "".join(parts)


class NavHelper:
    """Stateless navigation helper — computes prev/next purely from context."""

    def __init__(self, test_data: dict[str, list[dict[str, Any]]]):
        self.sequence: list[tuple[str, str | None, str | None]] = []
        self._build_sequence(test_data)

    def _build_sequence(self, test_data: dict[str, list[dict[str, Any]]]) -> None:
        seq = []
        for site in sorted(test_data.keys()):
            entries = sorted(
                test_data.get(site, []),
                key=lambda e: str(e.get("book_id", "")),
            )
            for entry in entries:
                book_id = str(entry.get("book_id", ""))
                chaps = [str(cid) for cid in entry.get("chap_ids", [])]
                seq.append((site, book_id, None))
                for chap in chaps:
                    seq.append((site, book_id, chap))
        self.sequence = seq

    def _find_index(self, site: str, book_id: str, chap_id: str | None) -> int:
        for i, (s, b, c) in enumerate(self.sequence):
            if s == site and b == book_id and c == chap_id:
                return i
        for i, (s, b, _) in enumerate(self.sequence):
            if s == site and b == book_id:
                return i
        return -1

    def move_next(self, site: str, book_id: str, chap_id: str | None):
        if not self.sequence:
            return ("", None, None), True, True
        idx = self._find_index(site, book_id, chap_id)
        if idx == -1 or idx >= len(self.sequence) - 1:
            return self.sequence[-1], False, True
        return self.sequence[idx + 1], False, (idx + 1 == len(self.sequence) - 1)

    def move_prev(self, site: str, book_id: str, chap_id: str | None):
        if not self.sequence:
            return ("", None, None), True, True
        idx = self._find_index(site, book_id, chap_id)
        if idx <= 0:
            return self.sequence[0], True, False
        return self.sequence[idx - 1], (idx - 1 == 0), False

    def has_prev_next(self, site: str, book_id: str, chap_id: str | None):
        idx = self._find_index(site, book_id, chap_id)
        if idx == -1:
            return False, False
        return idx > 0, idx < len(self.sequence) - 1
