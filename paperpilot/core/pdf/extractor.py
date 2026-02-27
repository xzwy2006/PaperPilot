"""
extractor.py — PDF 文本预处理工具函数，为 AI 提取做准备。
"""

import re
from collections import Counter


# ---------------------------------------------------------------------------
# 章节关键词（顺序即优先级）
# ---------------------------------------------------------------------------
_SECTION_KEYS = [
    "abstract",
    "introduction",
    "methods",
    "results",
    "discussion",
    "conclusion",
]

# 匹配独立章节标题行，例如：
#   "Abstract", "2. Methods", "RESULTS", "3 Discussion"
_SECTION_RE = re.compile(
    r"^\s*(?:\d+[\.\s]+)?(" + "|".join(_SECTION_KEYS) + r"s?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def clean_text(raw: str) -> str:
    """
    去除页眉页脚噪声。

    规则：行长度 < 40 字符 **且** 该行（去首尾空格后）在文档中重复出现
    >= 3 次，则视为噪声行并删除。

    Parameters
    ----------
    raw : str
        原始提取文本。

    Returns
    -------
    str
        清理后的文本。
    """
    lines = raw.splitlines()

    # 统计短行出现频次
    short_line_counts: Counter[str] = Counter()
    for line in lines:
        stripped = line.strip()
        if stripped and len(stripped) < 40:
            short_line_counts[stripped] += 1

    # 过滤噪声行
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and len(stripped) < 40 and short_line_counts[stripped] >= 3:
            continue  # 跳过噪声行
        cleaned.append(line)

    return "\n".join(cleaned)


def split_sections(text: str) -> dict[str, str]:
    """
    按章节标题切分文本。

    识别以下章节（不区分大小写）：
    Abstract / Introduction / Methods / Results / Discussion / Conclusion

    Parameters
    ----------
    text : str
        待切分的文本。

    Returns
    -------
    dict[str, str]
        键为小写章节名（如 ``"abstract"``、``"methods"``），
        值为对应文本内容。未识别内容归入 ``"other"``。
    """
    sections: dict[str, str] = {key: "" for key in _SECTION_KEYS}
    sections["other"] = ""

    # 找出所有章节标题的位置
    matches = list(_SECTION_RE.finditer(text))

    if not matches:
        sections["other"] = text
        return sections

    # "other" 部分：第一个标题之前的内容
    pre_text = text[: matches[0].start()].strip()
    if pre_text:
        sections["other"] = pre_text

    for i, match in enumerate(matches):
        key = match.group(1).lower().rstrip("s")  # 去掉复数 s，统一键名
        # 规范化：methodsection → methods，conclusionss → conclusion
        # 确保 key 在已知列表中，否则归入 other
        if key not in _SECTION_KEYS:
            key = "other"

        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()

        if sections[key]:
            # 同一章节出现多次时拼接（罕见，保险处理）
            sections[key] += "\n" + content
        else:
            sections[key] = content

    return sections


def truncate_for_ai(text: str, max_tokens: int = 6000) -> str:
    """
    按 token 估算截断文本，优先保留 abstract + methods 部分。

    Token 估算：4 个字符 ≈ 1 token。

    Parameters
    ----------
    text : str
        待截断的文本。
    max_tokens : int
        最大 token 数，默认 6000。

    Returns
    -------
    str
        截断后的文本，不超过 ``max_tokens * 4`` 个字符。
    """
    max_chars = max_tokens * 4

    if len(text) <= max_chars:
        return text

    # 尝试按章节优先策略
    sections = split_sections(text)
    priority_keys = ["abstract", "methods", "introduction", "results",
                     "discussion", "conclusion", "other"]

    result_parts: list[str] = []
    remaining = max_chars

    for key in priority_keys:
        content = sections.get(key, "").strip()
        if not content:
            continue
        if len(content) <= remaining:
            result_parts.append(content)
            remaining -= len(content)
        else:
            # 截取剩余预算
            result_parts.append(content[:remaining])
            remaining = 0
            break

        if remaining <= 0:
            break

    return "\n\n".join(result_parts)
