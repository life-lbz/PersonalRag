"""Excel/CSV 解析：每个 sheet 一组块；表行块由 splitter 进一步切分（table 模板）。"""
from __future__ import annotations

import csv
import io
import logging

from openpyxl import load_workbook

from .base import Block, ParsedDocument

logger = logging.getLogger(__name__)


class ExcelParser:
    supported_types = ["xlsx"]

    def parse(self, data: bytes, doc_id: str, filename: str = "") -> ParsedDocument:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        blocks: list[Block] = []
        for ws in wb.worksheets:
            blocks.append(Block(block_type="heading", content=ws.title, level=1))
            rows = [[("" if c is None else str(c)) for c in row] for row in ws.iter_rows(values_only=True)]
            rows = [r for r in rows if any(cell.strip() for cell in r)]
            if rows:
                html = _rows_to_html(rows)
                blocks.append(Block(block_type="table", content=html, metadata={"sheet": ws.title}))
        wb.close()
        return ParsedDocument(doc_id=doc_id, doc_type="xlsx", blocks=blocks, metadata={"filename": filename})


class CsvParser:
    supported_types = ["csv"]

    def parse(self, data: bytes, doc_id: str, filename: str = "") -> ParsedDocument:
        text = data.decode("utf-8-sig", errors="replace")
        rows = list(csv.reader(io.StringIO(text)))
        rows = [r for r in rows if any(cell.strip() for cell in r)]
        blocks = [Block(block_type="table", content=_rows_to_html(rows))] if rows else []
        return ParsedDocument(doc_id=doc_id, doc_type="csv", blocks=blocks, metadata={"filename": filename})


def _rows_to_html(rows: list[list[str]], max_rows: int = 500) -> str:
    import html as html_mod

    parts = ["<table>"]
    for i, row in enumerate(rows[:max_rows]):
        tag = "th" if i == 0 else "td"
        cells = "".join(f"<{tag}>{html_mod.escape(c.strip())}</{tag}>" for c in row)
        parts.append(f"<tr>{cells}</tr>")
    parts.append("</table>")
    return "".join(parts)
