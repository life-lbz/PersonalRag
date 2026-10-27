"""PPTX / HTML / EML 解析。"""
from __future__ import annotations

import io
import logging
import re

from bs4 import BeautifulSoup

from .base import Block, ParsedDocument

logger = logging.getLogger(__name__)


class PptxParser:
    """每页一块（presentation 模板配套）。"""

    supported_types = ["pptx"]

    def parse(self, data: bytes, doc_id: str, filename: str = "") -> ParsedDocument:
        from pptx import Presentation

        prs = Presentation(io.BytesIO(data))
        blocks: list[Block] = []
        for i, slide in enumerate(prs.slides, start=1):
            texts: list[str] = []
            for shape in slide.shapes:
                if shape.has_text_frame:
                    t = shape.text_frame.text.strip()
                    if t:
                        texts.append(t)
                elif getattr(shape, "has_table", False) and shape.has_table:
                    import html as html_mod

                    rows = [[c.text.strip() for c in row.cells] for row in shape.table.rows]
                    trs = "".join(
                        "<tr>" + "".join(f"<td>{html_mod.escape(c)}</td>" for c in r) + "</tr>" for r in rows
                    )
                    texts.append(f"<table>{trs}</table>")
            if texts:
                blocks.append(Block(block_type="text", content="\n".join(texts),
                                    page=i, metadata={"slide": i}))
        return ParsedDocument(doc_id=doc_id, doc_type="pptx", blocks=blocks, metadata={"filename": filename})


class HtmlParser:
    supported_types = ["html"]

    def parse(self, data: bytes, doc_id: str, filename: str = "") -> ParsedDocument:
        soup = BeautifulSoup(data.decode("utf-8", errors="replace"), "lxml")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        blocks: list[Block] = []
        for el in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "table", "pre"]):
            text = el.get_text("\n", strip=True)
            if not text:
                continue
            if el.name.startswith("h"):
                blocks.append(Block(block_type="heading", content=text,
                                    level=int(el.name[1]), metadata={"tag": el.name}))
            elif el.name == "table":
                blocks.append(Block(block_type="table", content=str(el)))
            elif el.name == "pre":
                blocks.append(Block(block_type="code", content=text))
            else:
                blocks.append(Block(block_type="text", content=text))
        return ParsedDocument(doc_id=doc_id, doc_type="html", blocks=blocks, metadata={"filename": filename})


class EmailParser:
    """eml: 头部字段 + 正文 + 附件清单。"""

    supported_types = ["eml"]

    def parse(self, data: bytes, doc_id: str, filename: str = "") -> ParsedDocument:
        import email
        from email import policy

        msg = email.message_from_bytes(data, policy=policy.default)
        blocks: list[Block] = []

        header_lines = []
        for field in ("From", "To", "Cc", "Subject", "Date"):
            val = msg.get(field)
            if val:
                header_lines.append(f"{field}: {val}")
        if header_lines:
            blocks.append(Block(block_type="heading", content=msg.get("Subject", "(无主题)"), level=1))
            blocks.append(Block(block_type="text", content="\n".join(header_lines)))

        attachments: list[str] = []
        body_text = ""
        for part in msg.walk():
            cd = str(part.get("Content-Disposition") or "")
            if "attachment" in cd:
                attachments.append(part.get_filename() or "unnamed")
            elif part.get_content_type() == "text/plain" and not body_text:
                try:
                    body_text = part.get_content()
                except Exception:
                    body_text = ""
        if body_text:
            for para in re.split(r"\n\s*\n", body_text):
                if para.strip():
                    blocks.append(Block(block_type="text", content=para.strip()))
        if attachments:
            blocks.append(Block(block_type="text", content="附件: " + ", ".join(attachments)))
        return ParsedDocument(doc_id=doc_id, doc_type="eml", blocks=blocks, metadata={"filename": filename})
