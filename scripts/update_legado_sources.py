#!/usr/bin/env python3
"""
scripts/update_legado_sources.py
---------------------------------

下载并更新打包进项目的 Legado 书源 JSON 文件。

用法::

    python scripts/update_legado_sources.py

会将结果写入 src/novel_downloader/resources/legado_sources/
若某个来源获取失败，该文件保持原样（不覆盖），脚本继续处理其余来源。

书源来源
--------
- XIU2/Yuedu      : https://github.com/XIU2/Yuedu
- shuyuan.yiove.com: API
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# 路径配置
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = REPO_ROOT / "src" / "novel_downloader" / "resources" / "legado_sources"

# ---------------------------------------------------------------------------
# 书源来源定义
# ---------------------------------------------------------------------------

TIMEOUT = 30  # seconds per request

# 每个来源的配置：
#   url     : 下载 URL（若为列表则依次尝试）
#   output  : 写入到 OUTPUT_DIR 下的文件名
#   min_size: 认为有效的最小书源数量，低于此值视为下载失败
#   parser  : 可选，解析原始 JSON → list[dict] 的函数名（默认直接当数组用）
SOURCES: list[dict[str, Any]] = [
    {
        "name": "XIU2/Yuedu",
        "urls": [
            "https://raw.githubusercontent.com/XIU2/Yuedu/master/shuyuan",
            "https://ghfast.top/https://raw.githubusercontent.com/XIU2/Yuedu/master/shuyuan",
        ],
        "output": "xiuyuedu.json",
        "min_size": 10,
    },
    {
        "name": "tickmao/Novel (Legado 完整书源)",
        "urls": [
            "https://raw.githubusercontent.com/tickmao/Novel/master/sources/legado/full.json",
            "https://ghfast.top/https://raw.githubusercontent.com/tickmao/Novel/master/sources/legado/full.json",
        ],
        "output": "tickmao.json",
        "min_size": 50,
    },
]

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 解析器
# ---------------------------------------------------------------------------


def default_parser(raw: Any) -> list[dict[str, Any]]:
    """原始 JSON 直接是书源数组。"""
    if isinstance(raw, list):
        return raw
    raise ValueError(f"期望 JSON 数组，实际类型: {type(raw).__name__}")


def yiove_parser(raw: Any) -> list[dict[str, Any]]:
    """
    shuyuan.yiove.com 的 API 返回格式通常为::

        {"data": [...], "total": N, ...}

    或直接是数组，兼容两种情况。
    """
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("data", "result", "list", "shuyuans", "sources"):
            if isinstance(raw.get(key), list):
                return raw[key]
    keys = list(raw.keys()) if isinstance(raw, dict) else type(raw)
    raise ValueError(f"无法从响应中提取书源数组: {keys}")


PARSERS: dict[str, Any] = {
    "yiove_parser": yiove_parser,
}

# ---------------------------------------------------------------------------
# 验证
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {"bookSourceUrl"}


def is_valid_source(obj: Any) -> bool:
    """粗略验证一个书源对象是否合法。"""
    if not isinstance(obj, dict):
        return False
    return bool(obj.get("bookSourceUrl"))


def validate_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """过滤掉不合法的书源条目。"""
    valid = [s for s in sources if is_valid_source(s)]
    dropped = len(sources) - len(valid)
    if dropped:
        logger.warning("  过滤掉 %d 个无效条目（缺少 bookSourceUrl）", dropped)
    return valid


# ---------------------------------------------------------------------------
# 网络下载
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; novel-downloader-updater/1.0; "
        "+https://github.com/saudadez21/novel-downloader)"
    ),
    "Accept": "application/json, text/plain, */*",
}


def fetch_url(url: str) -> bytes:
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


# ---------------------------------------------------------------------------
# 主逻辑
# ---------------------------------------------------------------------------


def process_source(cfg: dict[str, Any]) -> bool:
    """
    处理单个书源配置。

    :return: True 表示成功更新，False 表示跳过（已与现有相同或下载失败）。
    """
    name: str = cfg["name"]
    urls: list[str] = cfg["urls"]
    output_name: str = cfg["output"]
    min_size: int = cfg.get("min_size", 1)
    parser_name: str = cfg.get("parser", "default_parser")
    parser = PARSERS.get(parser_name, default_parser)

    output_path = OUTPUT_DIR / output_name

    logger.info("处理书源: %s", name)

    raw_data: bytes | None = None
    for url in urls:
        try:
            logger.info("  下载: %s", url)
            raw_data = fetch_url(url)
            break
        except (URLError, OSError, TimeoutError) as e:
            logger.warning("  下载失败 (%s): %s", url, e)
            time.sleep(1)

    if raw_data is None:
        logger.error("  所有 URL 均下载失败，跳过 %s", output_name)
        return False

    # 解析 JSON
    try:
        raw_json = json.loads(raw_data.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as e:
        logger.error("  JSON 解析失败: %s", e)
        return False

    # 提取书源列表
    try:
        sources: list[dict[str, Any]] = parser(raw_json)
    except ValueError as e:
        logger.error("  书源提取失败: %s", e)
        return False

    # 验证
    sources = validate_sources(sources)

    if len(sources) < min_size:
        logger.error(
            "  书源数量不足（期望至少 %d，实际 %d），跳过写入",
            min_size,
            len(sources),
        )
        return False

    # 与现有文件比较，无变化则跳过
    if output_path.exists():
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            if existing == sources:
                logger.info("  内容无变化，跳过写入（共 %d 个书源）", len(sources))
                return False
        except Exception:
            pass  # 文件损坏则覆盖

    # 写入
    output_path.write_text(
        json.dumps(sources, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("  已写入 %d 个书源 → %s", len(sources), output_path)
    return True


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    updated = 0
    failed = 0

    for cfg in SOURCES:
        try:
            if process_source(cfg):
                updated += 1
        except Exception as e:
            logger.exception("处理 %r 时发生意外错误: %s", cfg.get("name"), e)
            failed += 1

    logger.info(
        "完成：更新 %d 个书源文件，失败 %d 个，跳过 %d 个。",
        updated,
        failed,
        len(SOURCES) - updated - failed,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
