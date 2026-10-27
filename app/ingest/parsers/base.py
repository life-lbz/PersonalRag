"""统一中间表示（IR）与解析器协议，依据《RAG系统方案设计文档.md》§3.1.2。"""
from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

BlockType = Literal["heading", "text", "table", "image", "formula", "code", "list"]


class Block(BaseModel):
    block_type: BlockType = "text"
    content: str                     # 表格为 HTML/Markdown，图片为 MinIO uri
    level: int = 0                   # heading 层级
    page: int | None = None
    bbox: list[float] | None = None  # 版面坐标(引用溯源用)
    metadata: dict = Field(default_factory=dict)


class ParsedDocument(BaseModel):
    doc_id: str
    doc_type: str                    # pdf/docx/excel/law/html...
    metadata: dict = Field(default_factory=dict)
    blocks: list[Block] = Field(default_factory=list)
    structure_tree: dict = Field(default_factory=dict)  # 章节层级树


class BaseParser(Protocol):
    supported_types: list[str]

    def parse(self, data: bytes, doc_id: str, filename: str = "") -> ParsedDocument: ...


def detect_doc_type(filename: str) -> str:
    """按扩展名初判 doc_type（law 由预扫描升级判定，见 parsers/__init__.py）。"""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"
    mapping = {
        "pdf": "pdf", "docx": "docx", "doc": "docx", "md": "md", "markdown": "md",
        "txt": "txt", "xlsx": "xlsx", "xls": "xlsx", "csv": "csv", "pptx": "pptx",
        "html": "html", "htm": "html", "eml": "eml", "json": "txt", "xml": "txt",
    }
    return mapping.get(ext, "txt")
