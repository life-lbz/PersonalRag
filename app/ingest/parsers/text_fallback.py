"""纯文本兜底解析（txt / law 预解析共用）：按空行分段。"""
from __future__ import annotations

import re

from .base import Block, ParsedDocument


def parse_as_text(text: str) -> list[Block]:
    blocks = []
    for para in re.split(r"\n\s*\n", text):
        c = para.strip()
        if c:
            blocks.append(Block(block_type="text", content=c))
    return blocks


def parse_text_doc(data: bytes, doc_id: str, filename: str = "") -> ParsedDocument:
    text = data.decode("utf-8", errors="replace")
    return ParsedDocument(doc_id=doc_id, doc_type="txt", blocks=parse_as_text(text),
                          metadata={"filename": filename})
