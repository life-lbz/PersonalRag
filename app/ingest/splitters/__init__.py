"""切分模板注册表：doc_type → 模板映射（config: ingest.splitter.map，§3.1.3）。"""
from __future__ import annotations

import logging

from app.ingest.parsers.base import ParsedDocument

from .base import Chunk
from .general import split_general, split_page, split_qa, split_structure, split_table, split_email
from .law_splitter import split_law
from ..config_ingest import get_default_splitter, get_splitter_map

logger = logging.getLogger(__name__)

SPLITTER_REGISTRY = {
    "general": split_general,
    "qa": split_qa,
    "table": split_table,
    "paper": lambda doc, doc_id: split_structure(doc, doc_id, mode="hierarchy"),
    "book": lambda doc, doc_id: split_structure(doc, doc_id, mode="group"),
    "law": split_law,
    "email": split_email,
    "presentation": split_page,
}


def split_document(doc: ParsedDocument, doc_id: str, doc_type: str) -> tuple[list[Chunk], list[Chunk]]:
    """按 doc_type 路由切分模板，返回 (children, parents)。"""
    template = get_splitter_map().get(doc_type) or get_default_splitter()
    fn = SPLITTER_REGISTRY.get(template)
    if fn is None:
        logger.warning("切分模板 %s 未注册, 降级 general", template)
        fn = split_general
    children, parents = fn(doc, doc_id)
    logger.info("文档 %s 切分: 模板=%s 子块=%d 父块=%d", doc_id, template, len(children), len(parents))
    return children, parents
