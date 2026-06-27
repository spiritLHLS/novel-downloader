from __future__ import annotations

import base64
import io
from pathlib import Path

import numpy as np
from PIL import Image

from novel_downloader.plugins.sites.faloo.parser import FalooParser
from novel_downloader.plugins.utils.faloo import (
    clean_interference_boxes,
    detect_interference_boxes,
    prepare_ocr_lines,
)
from novel_downloader.schemas import ParserConfig


ASSET_DIR = Path(__file__).parents[2] / "docs" / "assets" / "images" / "faloo"


def _image_to_base64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_detect_and_clean_faloo_interference_boxes() -> None:
    img = np.array(Image.open(ASSET_DIR / "sample_8.png").convert("RGB"))

    coords = detect_interference_boxes(img)
    cleaned = clean_interference_boxes(img)

    assert coords == [(0, 0), (0, 16)]
    assert np.count_nonzero((cleaned == 255).all(axis=2)) > np.count_nonzero(
        (img == 255).all(axis=2)
    )
    assert np.count_nonzero(~(cleaned == 255).all(axis=2)) > 0


def test_prepare_ocr_lines_keeps_faloo_sample_as_single_line() -> None:
    img = np.array(Image.open(ASSET_DIR / "sample_8.png").convert("RGB"))

    lines = prepare_ocr_lines(img)

    assert len(lines) == 1
    assert lines[0].shape[1] == img.shape[1]


class StubFalooParser(FalooParser):
    def __init__(self, outputs: list[tuple[str, float]]) -> None:
        super().__init__(ParserConfig(enable_ocr=True))
        self.outputs = outputs
        self.seen_batch_size = 0

    def _extract_text_from_image(
        self,
        images: list[np.ndarray],
        batch_size: int = 1,
    ) -> list[tuple[str, float]]:
        self.seen_batch_size = batch_size
        return self.outputs[: len(images)]


def test_parse_image_chapter_groups_lines_into_paragraphs() -> None:
    img = Image.new("RGB", (80, 42), (255, 255, 255))
    arr = np.array(img)
    arr[5:15, 0:8] = 0
    arr[25:35, 40:48] = 0
    img_b64 = _image_to_base64(Image.fromarray(arr))

    parser = StubFalooParser([("第一行", 0.99), ("第二行", 0.99)])

    assert parser.parse_image_chapter(img_b64) == ["第一行", "第二行"]


def test_parse_image_chapter_rejects_low_quality_ocr() -> None:
    img = Image.new("RGB", (40, 20), (255, 255, 255))
    arr = np.array(img)
    arr[5:15, 2:12] = 0
    img_b64 = _image_to_base64(Image.fromarray(arr))

    parser = StubFalooParser([("疑似错误", 0.2)])

    assert parser.parse_image_chapter(img_b64) == []


def test_parse_chapter_content_keeps_image_fallback_when_ocr_empty() -> None:
    parser = FalooParser(ParserConfig(enable_ocr=True))
    img_b64 = _image_to_base64(Image.new("RGB", (20, 20), (255, 255, 255)))
    raw_html = '<div class="c_l_title"><h1>VIP</h1></div><script>image_do3()</script>'

    chapter = parser.parse_chapter_content([raw_html, img_b64], "1")

    assert chapter is not None
    assert chapter["content"] == ""
    assert chapter["extra"]["resources"] == [
        {
            "type": "image",
            "paragraph_index": 0,
            "base64": img_b64,
            "mime": "image/gif",
        }
    ]
