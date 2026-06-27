#!/usr/bin/env python3
"""
novel_downloader.plugins.utils.faloo
------------------------------------
"""

__all__ = [
    "clean_interference_boxes",
    "detect_interference_boxes",
    "prepare_ocr_lines",
]

from .image import (
    clean_interference_boxes,
    detect_interference_boxes,
    prepare_ocr_lines,
)
