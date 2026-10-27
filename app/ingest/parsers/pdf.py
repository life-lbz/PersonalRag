"""PDF 解析：原生文字层直提（pdfplumber），扫描件 OCR 一期不启用（留 TODO）。

输出 Block 序列：heading（按字号聚类判定）/ text / table(HTML)。
"""
from __future__ import annotations

import io
import logging
import re

import pdfplumber

from .base import Block, ParsedDocument

logger = logging.getLogger(__name__)

_HEADING_PATTERNS = [
    re.compile(r"^第[一二三四五六七八九十百\d]+[章节篇]"),
    re.compile(r"^\d+(\.\d+)*\s+\S"),
    re.compile(r"^[一二三四五六七八九十]+、"),
]


class PdfParser:
    supported_types = ["pdf"]

    def parse(self, data: bytes, doc_id: str, filename: str = "") -> ParsedDocument:
        blocks: list[Block] = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            # 收集全文档字号分布，中位字号以上的独立短行判为标题
            font_sizes: list[float] = []
            lines_by_page: list[list[dict]] = []
            for page in pdf.pages:
                lines = _extract_lines(page)
                lines_by_page.append(lines)
                font_sizes.extend(ln["size"] for ln in lines)
            base_size = sorted(font_sizes)[len(font_sizes) // 2] if font_sizes else 0

            for pno, page in enumerate(pdf.pages, start=1):
                # 表格先提取，记录其 bbox 用于排除行文本
                tables = page.find_tables()
                table_bboxes = [t.bbox for t in tables]
                for t in tables:
                    html = _table_to_html(t.extract())
                    if html.strip():
                        blocks.append(Block(block_type="table", content=html, page=pno))
                for ln in lines_by_page[pno - 1]:
                    if _in_any_bbox(ln, table_bboxes):
                        continue
                    text = ln["text"].strip()
                    if not text:
                        continue
                    is_heading = (ln["size"] > base_size * 1.15 and len(text) < 60) or any(
                        p.match(text) for p in _HEADING_PATTERNS
                    )
                    blocks.append(
                        Block(
                            block_type="heading" if is_heading else "text",
                            content=text,
                            level=1 if is_heading else 0,
                            page=pno,
                        )
                    )
        return ParsedDocument(doc_id=doc_id, doc_type="pdf", blocks=blocks, metadata={"filename": filename})


def _extract_lines(page) -> list[dict]:
    """按 y 坐标聚簇字符成行。"""
    chars = [c for c in page.chars if c.get("text", "").strip()]
    if not chars:
        return []
    chars.sort(key=lambda c: (round(c["top"], 1), c["x0"]))
    lines: list[dict] = []
    cur: list[dict] = []
    cur_top: float | None = None
    for c in chars:
        if cur_top is None or abs(c["top"] - cur_top) <= 3:
            cur.append(c)
            cur_top = c["top"] if cur_top is None else (cur_top + c["top"]) / 2
        else:
            lines.append(_make_line(cur))
            cur = [c]
            cur_top = c["top"]
    if cur:
        lines.append(_make_line(cur))
    return lines


def _make_line(chars: list[dict]) -> dict:
    chars.sort(key=lambda c: c["x0"])
    text = "".join(c["text"] for c in chars)
    sizes = [c["size"] for c in chars]
    return {
        "text": text,
        "size": max(sizes),
        "bbox": [min(c["x0"] for c in chars), min(c["top"] for c in chars),
                 max(c["x1"] for c in chars), max(c["bottom"] for c in chars)],
    }


def _in_any_bbox(ln: dict, bboxes: list[tuple]) -> bool:
    x0, top, x1, bottom = ln["bbox"]
    cx, cy = (x0 + x1) / 2, (top + bottom) / 2
    for b in bboxes:
        if b[0] <= cx <= b[2] and b[1] <= cy <= b[3]:
            return True
    return False


def _table_to_html(rows: list[list[str | None]]) -> str:
    if not rows:
        return ""
    import html as html_mod

    parts = ["<table>"]
    for i, row in enumerate(rows):
        tag = "th" if i == 0 else "td"
        cells = "".join(f"<{tag}>{html_mod.escape(str(c or ''))}</{tag}>" for c in row)
        parts.append(f"<tr>{cells}</tr>")
    parts.append("</table>")
    return "".join(parts)
