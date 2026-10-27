"""DOCX 解析：段落标题（style Heading）/ 正文 / 表格，按文档顺序输出。"""
from __future__ import annotations

import io
import re

from docx import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph

from .base import Block, ParsedDocument


def _iter_block_items(doc):
    """按文档顺序产出 Paragraph / Table。"""
    from docx.oxml.ns import qn

    body = doc.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc)


class DocxParser:
    supported_types = ["docx"]

    def parse(self, data: bytes, doc_id: str, filename: str = "") -> ParsedDocument:
        doc = DocxDocument(io.BytesIO(data))
        blocks: list[Block] = []
        for item in _iter_block_items(doc):
            if isinstance(item, Paragraph):
                text = item.text.strip()
                if not text:
                    continue
                level = 0
                style = (item.style.name or "").lower() if item.style is not None else ""
                m = re.match(r"heading (\d)", style)
                if m:
                    level = int(m.group(1))
                    blocks.append(Block(block_type="heading", content=text, level=level))
                elif re.match(r"^第[一二三四五六七八九十百\d]+[章节篇]", text) and len(text) < 50:
                    blocks.append(Block(block_type="heading", content=text, level=1))
                else:
                    blocks.append(Block(block_type="text", content=text))
            elif isinstance(item, Table):
                html = _table_to_html(item)
                if html.strip():
                    blocks.append(Block(block_type="table", content=html))
        return ParsedDocument(doc_id=doc_id, doc_type="docx", blocks=blocks, metadata={"filename": filename})


def _table_to_html(table: Table) -> str:
    import html as html_mod

    parts = ["<table>"]
    for i, row in enumerate(table.rows):
        tag = "th" if i == 0 else "td"
        cells = "".join(f"<{tag}>{html_mod.escape(c.text.strip())}</{tag}>" for c in row.cells)
        parts.append(f"<tr>{cells}</tr>")
    parts.append("</table>")
    return "".join(parts)
