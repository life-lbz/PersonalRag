"""解析器注册制路由：格式探测（扩展名 + law 预扫描），输出统一 IR。

新增格式：实现 BaseParser 协议并注册进 PARSER_REGISTRY，零改框架。
"""
from __future__ import annotations

import logging
import re

from .base import Block, BaseParser, ParsedDocument, detect_doc_type
from .docx import DocxParser
from .excel import CsvParser, ExcelParser
from .markdown import MarkdownParser, TextParser
from .misc import EmailParser, HtmlParser, PptxParser
from .pdf import PdfParser

logger = logging.getLogger(__name__)

PARSER_REGISTRY: dict[str, BaseParser] = {
    "pdf": PdfParser(),
    "docx": DocxParser(),
    "md": MarkdownParser(),
    "txt": TextParser(),
    "xlsx": ExcelParser(),
    "csv": CsvParser(),
    "pptx": PptxParser(),
    "html": HtmlParser(),
    "eml": EmailParser(),
}

# 法规锚点密度判定：pdf/docx 预扫 "第X章/第X条" 达标则标记 doc_type=law
_LAW_ANCHOR = re.compile(r"第[一二三四五六七八九十百千\d]+条")
_LAW_CHAPTER = re.compile(r"第[一二三四五六七八九十百千\d]+[章节编]")
_LAW_DENSITY_THRESHOLD = 5  # 至少 5 个条锚点


def _looks_like_law(doc: ParsedDocument) -> bool:
    text = "\n".join(b.content for b in doc.blocks if b.block_type in ("text", "heading"))
    articles = len(_LAW_ANCHOR.findall(text))
    chapters = len(_LAW_CHAPTER.findall(text))
    return articles >= _LAW_DENSITY_THRESHOLD and chapters >= 1


def parse_document(data: bytes, doc_id: str, filename: str, doc_type_hint: str | None = None) -> ParsedDocument:
    """格式探测 + 解析插件路由。"""
    doc_type = doc_type_hint or detect_doc_type(filename)
    if doc_type not in PARSER_REGISTRY:
        logger.warning("未知类型 %s, 降级为 txt 解析", doc_type)
        doc_type = "txt"
    parser = PARSER_REGISTRY[doc_type]
    doc = parser.parse(data, doc_id, filename)

    # law 类型判定：格式探测阶段预扫锚点密度，达标则进入法规插件重解析
    from .law import LawParser  # 延迟导入避免循环

    if doc_type in ("pdf", "docx", "txt") and _looks_like_law(doc):
        logger.info("文档 %s 命中法规锚点, 走 LawParser", doc_id)
        doc = LawParser().parse(data, doc_id, filename)
    return doc


__all__ = [
    "PARSER_REGISTRY",
    "parse_document",
    "detect_doc_type",
    "Block",
    "ParsedDocument",
    "BaseParser",
]
