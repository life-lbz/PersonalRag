"""add uq_document_versions_doc_id_version & normalize law_articles.version

Revision ID: b7c4e1a90f22
Revises: f5d9216f0c3c
Create Date: 2026-10-28

本次迁移修复两处数据层缺口：
1. document_versions 只有 comment='UNIQUE(doc_id, version)'，数据库层面并未真正建约束，
   并发上传同一文档时可能产生重复版本号 —— 补真实 UniqueConstraint。
2. law_articles.version 历史上写死为 'v1'，与 document_versions.version 脱钩 ——
   统一为纯数字字符串（'v1' → '1'），便于按当前版本过滤法条。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'b7c4e1a90f22'
down_revision = 'f5d9216f0c3c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    dup = bind.execute(sa.text(
        "SELECT doc_id, version, count(*) AS n FROM document_versions "
        "GROUP BY doc_id, version HAVING count(*) > 1"
    )).all()
    if dup:
        raise RuntimeError(f"存在重复版本号, 请先人工清理后再迁移: {dup}")

    # 'v1' / 'v12' -> '1' / '12'
    bind.execute(sa.text(
        "UPDATE law_articles SET version = substring(version from 2) "
        "WHERE version ~ '^v[0-9]+$'"
    ))

    op.create_unique_constraint(
        "uq_document_versions_doc_id_version",
        "document_versions",
        ["doc_id", "version"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_document_versions_doc_id_version", "document_versions", type_="unique"
    )
    op.get_bind().execute(sa.text(
        "UPDATE law_articles SET version = 'v' || version WHERE version ~ '^[0-9]+$'"
    ))
