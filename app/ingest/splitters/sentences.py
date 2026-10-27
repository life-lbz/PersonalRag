"""中文标点感知断句：按句号/问号/叹号/省略号/引号后断句，超长句多级降级（架构文档 §2.2）。"""
from __future__ import annotations

import re

_SENT_SPLIT = re.compile(r"""(?<=[。！？!?…；;])\s*|(?<=[。！？!?…]["”』」)])\s*""")
_LONG_SENT_HARD = re.compile(r"(?<=[，,、])\s*")


def split_sentences(text: str, max_len: int = 512) -> list[str]:
    """断句；单句超 max_len 时按逗号降级，再按硬截断。"""
    parts = [p for p in _SENT_SPLIT.split(text) if p.strip()]
    out: list[str] = []
    for p in parts:
        if len(p) <= max_len:
            out.append(p)
            continue
        sub = [s for s in _LONG_SENT_HARD.split(p) if s.strip()]
        buf = ""
        for s in sub:
            if len(buf) + len(s) <= max_len:
                buf += s
            else:
                if buf:
                    out.append(buf)
                while len(s) > max_len:  # 无标点超长句硬截断
                    out.append(s[:max_len])
                    s = s[max_len:]
                buf = s
        if buf:
            out.append(buf)
    return out
