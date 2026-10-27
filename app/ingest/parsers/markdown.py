"""Markdown / 纯文本解析。"""
from __future__ import annotations

import re

from .base import Block, ParsedDocument

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


class MarkdownParser:
    supported_types = ["md"]

    def parse(self, data: bytes, doc_id: str, filename: str = "") -> ParsedDocument:
        text = data.decode("utf-8", errors="replace")
        blocks: list[Block] = []
        for raw in text.split("\n\n"):
            content = raw.strip()
            if not content:
                continue
            m = _HEADING_RE.match(content)
            if m:
                blocks.append(Block(block_type="heading", content=m.group(2).strip(),
                                    level=len(m.group(1))))
            elif content.startswith("|") or content.startswith("<table"):
                blocks.append(Block(block_type="table", content=content))
            elif content.startswith("```"):
                blocks.append(Block(block_type="code", content=content.strip("` \n")))
            else:
                blocks.append(Block(block_type="text", content=content))
        return ParsedDocument(doc_id=doc_id, doc_type="md", blocks=blocks, metadata={"filename": filename})


class TextParser:
    supported_types = ["txt"]

    def parse(self, data: bytes, doc_id: str, filename: str = "") -> ParsedDocument:
        text = data.decode("utf-8", errors="replace")
        blocks = [Block(block_type="text", content=p.strip())
                  for p in re.split(r"\n\s*\n", text) if p.strip()]
        return ParsedDocument(doc_id=doc_id, doc_type="txt", blocks=blocks, metadata={"filename": filename})
