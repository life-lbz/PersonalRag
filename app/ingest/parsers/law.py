"""法规领域插件：LawParser 正则锚点识别编/章/节/条/款/项，重建条文树。

依据《RAG系统方案设计文档.md》§3.3：
- 编/章/节 → heading 块；条 → text 块（一条一块，不切），款/项随条
- 条内引用、跨法引用正则抽取 → 写入块 metadata（供 Neo4j 图谱，三期）
- 元数据扩展：law_name / effective_date / article_no 等
"""
from __future__ import annotations

import re

from .base import Block, ParsedDocument
from .text_fallback import parse_as_text

# 章节层级锚点
_LEVEL_RE = re.compile(r"^第([一二三四五六七八九十百千\d]+)(编|章|节)")
# 条锚点：第X条
_ARTICLE_RE = re.compile(r"^第([一二三四五六七八九十百千\d]+)条\s*")
# 法律名称：从标题行《XXX》提取
_LAW_NAME_RE = re.compile(r"《([^》]{2,60})》")
# 常见法律标题行（文件首行通常为法名）
_TITLE_RE = re.compile(r"^([\u4e00-\u9fa5（）()]{4,40}(?:法|条例|规定|办法|规则|细则|决定|意见))\s*$")
# 条内引用：本法第X条 / 《法名》第X条
_CITE_INNER_RE = re.compile(r"本法第([一二三四五六七八九十百千\d]+)条")
_CITE_CROSS_RE = re.compile(r"《([^》]{2,60})》第([一二三四五六七八九十百千\d]+)条")
# 施行日期
_EFFECTIVE_RE = re.compile(r"自(\d{4})年(\d{1,2})月(\d{1,2})日起施行")
# 法律层级
_LAW_LEVEL_KEYWORDS = ["宪法", "法律", "行政法规", "地方性法规", "部门规章", "司法解释"]


class LawParser:
    supported_types = ["law"]

    def parse(self, data: bytes, doc_id: str, filename: str = "") -> ParsedDocument:
        text = data.decode("utf-8", errors="replace")
        raw_blocks = parse_as_text(text)

        # 法名推断优先级：文件名中《X》→ 首行中《X》→ 首行标题式 → 文件名主干
        law_name = ""
        first_line = raw_blocks[0].content.strip() if raw_blocks else ""
        m = _LAW_NAME_RE.search(filename) or _LAW_NAME_RE.search(first_line)
        if m:
            law_name = m.group(1)
        if not law_name:
            m2 = _TITLE_RE.match(first_line) or _TITLE_RE.match(filename)
            if m2:
                law_name = m2.group(1)
        if not law_name and filename:
            from pathlib import Path as _Path

            stem = _Path(filename).stem.strip()
            if re.fullmatch(r"[\u4e00-\u9fa5（）()A-Za-z0-9]{2,40}", stem):
                law_name = stem

        blocks: list[Block] = []
        effective_date = ""
        for b in raw_blocks:
            content = b.content.strip()
            if not content:
                continue
            lm = _LEVEL_RE.match(content)
            am = _ARTICLE_RE.match(content)
            if lm and len(content) < 60:
                level = {"编": 1, "章": 2, "节": 3}.get(lm.group(2), 2)
                blocks.append(Block(block_type="heading", content=content, level=level))
            elif am:
                em = _EFFECTIVE_RE.search(content)
                if em:
                    effective_date = f"{em.group(1)}-{int(em.group(2)):02d}-{int(em.group(3)):02d}"
                cites = self._extract_cites(content, law_name)
                blocks.append(
                    Block(
                        block_type="text",
                        content=content,
                        level=4,  # 条
                        metadata={
                            "article_no": f"第{am.group(1)}条",
                            "law_name": law_name,
                            "cites": cites,
                        },
                    )
                )
            else:
                # 款/项等正文延续：并入最近条块（条不切原则）
                if blocks and blocks[-1].block_type == "text" and blocks[-1].metadata.get("article_no"):
                    blocks[-1].content += "\n" + content
                    em = _EFFECTIVE_RE.search(content)
                    if em:
                        effective_date = f"{em.group(1)}-{int(em.group(2)):02d}-{int(em.group(3)):02d}"
                else:
                    blocks.append(Block(block_type="text", content=content))

        structure_tree = self._build_tree(blocks)
        metadata = {
            "filename": filename,
            "law_name": law_name,
            "effective_date": effective_date,
        }
        return ParsedDocument(doc_id=doc_id, doc_type="law", blocks=blocks,
                              structure_tree=structure_tree, metadata=metadata)

    @staticmethod
    def _extract_cites(content: str, law_name: str) -> list[dict]:
        cites: list[dict] = []
        for m in _CITE_INNER_RE.finditer(content):
            cites.append({"target_law": law_name, "target_article": f"第{m.group(1)}条", "scope": "inner"})
        for m in _CITE_CROSS_RE.finditer(content):
            if m.group(1) != law_name:
                cites.append({"target_law": m.group(1), "target_article": f"第{m.group(2)}条", "scope": "cross"})
        return cites

    @staticmethod
    def _build_tree(blocks: list[Block]) -> dict:
        tree: dict = {}
        stack: list[tuple[int, dict]] = []
        for b in blocks:
            if b.block_type != "heading":
                continue
            node = {"title": b.content, "level": b.level, "children": []}
            while stack and stack[-1][0] >= b.level:
                stack.pop()
            if stack:
                stack[-1][1]["children"].append(node)
            else:
                tree.setdefault("roots", []).append(node)
            stack.append((b.level, node))
        return tree
