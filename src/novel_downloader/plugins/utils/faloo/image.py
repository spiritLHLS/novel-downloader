#!/usr/bin/env python3
"""
novel_downloader.plugins.utils.faloo.image
------------------------------------------
"""

from __future__ import annotations

from typing import Final

import numpy as np
from numpy.typing import NDArray

from novel_downloader.libs import image_utils

_BOX_H: Final = 18
_BOX_W: Final = 18
_REQ_CHUNK_SIZE: Final = 32

_BOX_REQUIRED_MASK: Final = np.array(
    [
        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0],
        [1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    ],
    dtype=bool,
)

_REQ_COORDS: Final = np.argwhere(_BOX_REQUIRED_MASK)
_REQ_CHUNKS: Final = [
    (
        _REQ_COORDS[i : i + _REQ_CHUNK_SIZE, 0],
        _REQ_COORDS[i : i + _REQ_CHUNK_SIZE, 1],
    )
    for i in range(0, len(_REQ_COORDS), _REQ_CHUNK_SIZE)
]


def detect_interference_boxes(
    img: NDArray[np.uint8],
    *,
    white_threshold: int = 250,
    min_inner_white_ratio: float = 0.35,
) -> list[tuple[int, int]]:
    """
    Detect Faloo's 18x18 anti-OCR frame boxes.

    Returns top-left coordinates as ``(row, col)`` pairs. Detection is based on
    the fixed three-sided frame shape used by Faloo VIP chapter images.
    """
    h, w, _ = img.shape
    if h < _BOX_H or w < _BOX_W:
        return []

    is_white: NDArray[np.bool_] = np.asarray(
        (img >= white_threshold).all(axis=-1),
        dtype=np.bool_,
    )
    out_h = h - _BOX_H + 1
    out_w = w - _BOX_W + 1
    matches = np.ones((out_h, out_w), dtype=bool)

    for di_list, dj_list in _REQ_CHUNKS:
        bad = np.zeros((out_h, out_w), dtype=bool)
        for di, dj in zip(di_list, dj_list, strict=False):
            bad |= is_white[di : di + out_h, dj : dj + out_w]
        matches &= ~bad
        if not matches.any():
            return []

    coords = np.argwhere(matches)
    if min_inner_white_ratio <= 0:
        return [(int(r), int(c)) for r, c in coords]

    result: list[tuple[int, int]] = []
    for r, c in coords:
        crop_white = is_white[r : r + _BOX_H, c : c + _BOX_W]
        inner_white_ratio = crop_white[~_BOX_REQUIRED_MASK].mean()
        if inner_white_ratio >= min_inner_white_ratio:
            result.append((int(r), int(c)))
    return result


def clean_interference_boxes(
    img: NDArray[np.uint8],
    *,
    background: tuple[int, int, int] = (255, 255, 255),
    white_threshold: int = 250,
) -> NDArray[np.uint8]:
    """
    Remove Faloo anti-OCR frame pixels while preserving non-frame content.
    """
    cleaned = img.copy()
    for r, c in detect_interference_boxes(img, white_threshold=white_threshold):
        block = cleaned[r : r + _BOX_H, c : c + _BOX_W, :]
        block[_BOX_REQUIRED_MASK] = background
    return cleaned


def prepare_ocr_lines(
    img: NDArray[np.uint8],
    *,
    remove_watermark: bool = False,
) -> list[NDArray[np.uint8]]:
    """Clean and split Faloo VIP chapter images into OCR-ready text lines."""
    prepared = clean_interference_boxes(img)
    if remove_watermark:
        prepared = image_utils.filter_gray_watermark(prepared, threshold=225)

    lines = image_utils.split_by_white_lines(
        prepared,
        padding=4,
        white_threshold=250,
        max_nonwhite=max(1, prepared.shape[1] // 800),
        min_height=6,
    )
    return lines
