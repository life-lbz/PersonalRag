"""token 计数：tiktoken 近似（qwen 词表相近），不可用时按字数估算。"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    import tiktoken

    _enc = tiktoken.get_encoding("cl100k_base")

    def count_tokens(text: str) -> int:
        return len(_enc.encode(text))

except Exception:  # pragma: no cover - tiktoken 不可用时兜底
    logger.warning("tiktoken 不可用, 使用字数估算")

    def count_tokens(text: str) -> int:
        cn = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        other = len(text) - cn
        return cn + (other + 3) // 4
