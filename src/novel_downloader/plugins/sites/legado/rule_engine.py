#!/usr/bin/env python3
"""
novel_downloader.plugins.sites.legado.rule_engine
--------------------------------------------------

Legado 书源规则引擎。

支持以下规则格式：
- XPath：``//div[@id='content']``、``./span/text()``、``//a/@href``
- CSS 选择器：``div.content``、``#content > p``（需安装 cssselect）
- 属性提取后缀：``div.content@href``、``//a@text``
- 正则替换：``##pattern##replacement``（可叠加）
- 多规则 OR 降级：``rule1||rule2``（取第一个非空结果）
- JS 规则：``<js>...</js>`` 或 ``@js:...``（暂不支持，返回空）

规则执行原则
------------
*  ``eval_rule(rule, element, base_url)``
   → 返回 ``list[str]``，适用于叶子字段（name/author/content 等）
*  ``select_elements(rule, element)``
   → 返回 ``list[HtmlElement]``，适用于列表字段（bookList/chapterList 等）
"""

from __future__ import annotations

import contextlib
import logging
import re
from typing import Any
from urllib.parse import urljoin

from lxml import html as lxml_html

logger = logging.getLogger(__name__)

# 匹配 Legado 正则变换段 ##pattern##replacement
_REGEX_TRANSFORM_RE = re.compile(r"##(.*?)##(.*?)(?=##|$)", re.DOTALL)

# 简单的 JS 规则检测
_JS_RULE_RE = re.compile(r"^(<js>|@js:)", re.IGNORECASE)

# 常见属性名（用来区分 CSS@attr 和链式规则中的 @）
_KNOWN_ATTRS = frozenset(
    [
        "text",
        "ownText",
        "html",
        "href",
        "src",
        "data-src",
        "alt",
        "title",
        "content",
        "value",
        "class",
        "id",
        "name",
        "type",
        "action",
        "textNodes",
        "innerText",
    ]
)


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------


def eval_rule(
    rule: str,
    element: Any,
    base_url: str = "",
) -> list[str]:
    """
    对 ``element`` 执行 Legado 规则字符串，返回字符串列表。

    :param rule: Legado 规则字符串。
    :param element: lxml HTML 元素（HtmlElement）或根文档。
    :param base_url: 用于将相对 URL 转为绝对 URL。
    :return: 最终提取出的字符串列表（已去除首尾空白、过滤空字符串）。
    """
    if not rule:
        return []

    rule = rule.strip()

    # 多规则 OR 降级：rule1||rule2
    if "||" in rule:
        for sub in rule.split("||"):
            result = eval_rule(sub.strip(), element, base_url)
            if result:
                return result
        return []

    # 提取正则变换段
    rule_clean, transforms = _extract_regex_transforms(rule)

    # JS 规则：暂不支持
    if _JS_RULE_RE.match(rule_clean):
        logger.debug("不支持 JS 规则，跳过: %s", rule_clean[:80])
        return []

    # 执行选择器
    texts = _eval_selector(rule_clean, element, base_url)

    # 应用正则变换
    if transforms:
        processed = []
        for t in texts:
            for pattern, replacement in transforms:
                    with contextlib.suppress(re.error):
                        t = re.sub(pattern, replacement, t, flags=re.DOTALL)
            t = t.strip()
            if t:
                processed.append(t)
        return processed

    return [t for t in texts if t]


def eval_rule_str(
    rule: str,
    element: Any,
    base_url: str = "",
    sep: str = "\n",
) -> str:
    """
    执行规则并将结果合并为单个字符串（多段以 ``sep`` 分隔）。
    """
    return sep.join(eval_rule(rule, element, base_url))


def select_elements(rule: str, element: Any) -> list[Any]:
    """
    执行列表选择规则（如 bookList / chapterList），返回元素列表。

    .. note::
        此函数只做元素筛选，不提取文本。返回值是 lxml HtmlElement 对象列表，
        供后续逐元素调用 :func:`eval_rule` 使用。

    :param rule: 列表选择规则（XPath 或 CSS）。
    :param element: 上下文元素。
    :return: HtmlElement 列表。
    """
    if not rule:
        return []

    rule = rule.strip()

    # 去掉正则变换段（列表规则不做变换）
    rule_clean, _ = _extract_regex_transforms(rule)
    rule_clean = rule_clean.strip()

    if not rule_clean:
        return []

    # JS 规则：跳过
    if _JS_RULE_RE.match(rule_clean):
        return []

    # 去掉可能的 @attr 尾部（列表规则不需要属性）
    selector, _ = _split_attr_suffix(rule_clean)
    selector = selector.strip() or rule_clean

    # XPath
    if _is_xpath(selector):
        try:
            results = element.xpath(selector)
            return [r for r in results if hasattr(r, "tag")]
        except Exception as e:
            logger.debug("XPath 列表规则失败 %r: %s", selector, e)
            return []

    # CSS
    return _css_select_elements(selector, element)


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _extract_regex_transforms(rule: str) -> tuple[str, list[tuple[str, str]]]:
    """
    从规则末尾提取 ##pattern##replacement 变换段。

    示例::

        "//div/text()##\\s+## ##广告##"
        → ("//div/text()", [("\\s+", " "), ("广告", "")])
    """
    # 找到第一个 ## 分隔符的位置
    idx = rule.find("##")
    if idx == -1:
        return rule, []

    main_rule = rule[:idx]
    transform_str = rule[idx + 2 :]  # 跳过开头的 ##

    transforms: list[tuple[str, str]] = []
    # 用 ## 分割剩余部分，两两组成 (pattern, replacement)
    parts = transform_str.split("##")
    for i in range(0, len(parts) - 1, 2):
        pattern = parts[i]
        replacement = parts[i + 1] if i + 1 < len(parts) else ""
        transforms.append((pattern, replacement))

    return main_rule, transforms


def _is_xpath(rule: str) -> bool:
    """判断规则是否为 XPath（以 / 或 ./ 开头）。"""
    return rule.startswith(("//", "./", "/"))


def _split_attr_suffix(rule: str) -> tuple[str, str | None]:
    """
    将 ``selector@attr`` 拆分为 ``(selector, attr)``。

    仅当 ``@`` 在所有方括号闭合后出现、且后面是合法属性名时才拆分。
    XPath 内部的 ``[@class='x']``、``/@href`` 不会被错误拆分。

    示例::

        "div.content@href"   → ("div.content", "href")
        "//a/@href"          → ("//a/@href", None)         ← XPath 内部
        "//a@text"           → ("//a", "text")
    """
    depth = 0
    last_at = -1
    for i, ch in enumerate(rule):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        elif ch == "@" and depth == 0:
            last_at = i

    if last_at <= 0:
        return rule, None

    attr = rule[last_at + 1 :].strip()
    selector = rule[:last_at].strip()

    # 如果是 XPath 内部的 /@attr（即前面还有路径），不拆
    if selector.endswith("/"):
        return rule, None

    # 验证 attr 是合法属性标识符（字母数字 - _）或已知关键字
    if re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", attr):
        return selector, attr

    return rule, None


def _eval_selector(rule: str, element: Any, base_url: str) -> list[str]:
    """分发至 XPath 或 CSS 求值器。"""
    rule = rule.strip()
    if not rule:
        return []

    # 显式前缀
    lower = rule.lower()
    if lower.startswith("@xpath:"):
        return _eval_xpath(rule[7:].strip(), element, base_url)
    if lower.startswith("@css:"):
        return _eval_css(rule[5:].strip(), element, base_url)
    if lower.startswith("@json:") or lower.startswith("$."):
        logger.debug("JSONPath 规则暂不支持: %s", rule[:60])
        return []

    # 独立属性（如 @text、@href，作用于当前元素列表中的每个）
    if rule.startswith("@") and not rule.startswith("@xpath:"):
        attr = rule[1:]
        return _extract_attr_from_element(element, attr, base_url)

    # 自动检测
    if _is_xpath(rule):
        return _eval_xpath(rule, element, base_url)

    return _eval_css(rule, element, base_url)


def _eval_xpath(xpath: str, element: Any, base_url: str) -> list[str]:
    """执行 XPath 规则，返回字符串列表。"""
    # 检测是否有 Legado @attr 后缀（非 XPath 标准）
    selector, legado_attr = _split_attr_suffix(xpath)
    if legado_attr:
        # 用 XPath 选出元素，再按 legado_attr 提取
        try:
            elements: list[Any] = list(element.xpath(selector))
        except Exception as e:
            logger.debug("XPath 执行失败 %r: %s", selector, e)
            return []
        attr_texts: list[str] = []
        for el in elements:
            val = _extract_attr_from_element(el, legado_attr, base_url)
            attr_texts.extend(val)
        return attr_texts

    # 纯 XPath（可能直接返回字符串）
    try:
        results = element.xpath(xpath)
    except Exception as e:
        logger.debug("XPath 执行失败 %r: %s", xpath, e)
        return []

    texts: list[str] = []
    for r in results:
        if isinstance(r, str):
            text = r.strip()
        elif hasattr(r, "text_content"):
            text = r.text_content().strip()
        else:
            text = str(r).strip()

        if not text:
            continue

        if base_url:
            text = _maybe_resolve_url(text, base_url)
        texts.append(text)

    return texts


def _eval_css(rule: str, element: Any, base_url: str) -> list[str]:
    """执行 CSS 规则（含可选 @attr 后缀），返回字符串列表。"""
    selector, attr = _split_attr_suffix(rule)

    if not selector:
        # 仅有 @attr，作用于当前元素
        return _extract_attr_from_element(element, attr or "text", base_url)

    elements = _css_select_elements(selector, element)
    if not elements:
        return []

    texts = []
    for el in elements:
        val_list = _extract_attr_from_element(el, attr or "text", base_url)
        texts.extend(val_list)
    return texts


def _css_select_elements(selector: str, element: Any) -> list[Any]:
    """用 CSS 选择器在 element 内选取子元素。"""
    try:
        from lxml.cssselect import CSSSelector

        sel = CSSSelector(selector)
        return list(sel(element))
    except ImportError:
        # cssselect 未安装，降级为 lxml 内置 find_class / tag 等
        logger.debug("cssselect 未安装，无法使用 CSS 规则: %s", selector)
        return []
    except Exception as e:
        logger.debug("CSS 选择失败 %r: %s", selector, e)
        # 尝试作为简单标签名
        try:
            return list(element.xpath(f".//{selector}"))
        except Exception:
            return []


def _extract_attr_from_element(element: Any, attr: str, base_url: str) -> list[str]:
    """
    从单个 lxml 元素提取属性或文本。

    :param attr: 属性名，特殊值包括 text/ownText/html/textNodes 等。
    """
    if element is None:
        return []

    # 如果 element 本身是字符串（XPath text() 结果）
    if isinstance(element, str):
        return [element.strip()] if element.strip() else []

    val: str = ""

    if attr in ("text", "innerText", "allText", ""):
        val = element.text_content().strip()
    elif attr == "ownText":
        # 只取直接子文本节点，不含后代
        parts = []
        if element.text:
            parts.append(element.text.strip())
        for child in element:
            if child.tail:
                parts.append(child.tail.strip())
        val = " ".join(p for p in parts if p)
    elif attr == "textNodes":
        # 仅文本节点（不含子元素文本）
        parts = []
        if element.text:
            parts.append(element.text.strip())
        for child in element:
            if child.tail:
                parts.append(child.tail.strip())
        return [p for p in parts if p]
    elif attr == "html":
        try:
            val = lxml_html.tostring(element, encoding="unicode")
        except Exception:
            val = ""
    else:
        # 普通 HTML 属性
        val = (element.get(attr) or "").strip()

    if not val:
        return []

    if base_url:
        val = _maybe_resolve_url(val, base_url)

    return [val]


def _maybe_resolve_url(text: str, base_url: str) -> str:
    """若 text 看起来是相对 URL，则解析为绝对 URL。"""
    if text.startswith(("http://", "https://", "//", "data:", "javascript:")):
        return text
    if text.startswith(("/", "./", "../")) or (base_url and not text.startswith("#")):
        try:
            return urljoin(base_url, text)
        except Exception:
            pass
    return text
