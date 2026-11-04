"""配置加载：config.yaml ← 环境变量(RAG_前缀) ← .env；yaml 内 ${VAR} 占位符用环境变量替换。

依据《RAG系统基本配置文档.md》§1 配置管理约定。
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    # ${VAR} 占位符替换为环境变量（缺失则替换为空串并告警）
    def _sub(m: re.Match) -> str:
        var = m.group(1)
        val = os.environ.get(var, "")
        if val == "":
            import logging
            logging.getLogger("config").warning("环境变量 %s 未设置, 替换为空串", var)
        return val
    raw = re.sub(r"\$\{(\w+)\}", _sub, raw)
    return yaml.safe_load(raw) or {}


# .env（敏感信息）
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env.local", override=True)

_yaml: dict = _load_yaml(PROJECT_ROOT / "config.yaml")

RAG_ENV = os.environ.get("RAG_ENV", "dev")


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 2
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])


class AuthConfig(BaseModel):
    """API 鉴权（L5）：生产环境启用后，除 /health 外全部接口需 Bearer token 或 X-API-Key。"""

    enabled: bool = False
    tokens: list[str] = Field(default_factory=list)


class PostgresConfig(BaseModel):
    dsn: str = ""
    sync_dsn: str = ""
    pool_size: int = 20


class MilvusConfig(BaseModel):
    uri: str = "http://localhost:19530"
    text_collection: str = "kb_chunks"
    image_collection: str = "kb_images"


class RedisConfig(BaseModel):
    url: str = ""


class Neo4jConfig(BaseModel):
    uri: str = "bolt://localhost:7687"
    auth: list[str] = Field(default_factory=lambda: ["neo4j", ""])
    enabled: bool = False


class MinioConfig(BaseModel):
    endpoint: str = "localhost:9000"
    access_key: str = ""
    secret_key: str = ""
    bucket: str = "rag-docs"


class EmbeddingConfig(BaseModel):
    base_url: str = "http://localhost:8001"
    model: str = "bge-m3"
    dim: int = 1024
    batch_size: int = 16
    timeout: int = 120


class RerankConfig(BaseModel):
    base_url: str = "http://localhost:8002"
    model: str = "bge-reranker-base"
    batch_size: int = 64
    timeout: int = 120


class LLMConfig(BaseModel):
    base_url: str = "http://localhost:11434/v1"  # 经 SSH 隧道到 AutoDL vLLM
    model: str = "Qwen3-30B-A3B-Instruct-2507"
    temperature: float = 0.1
    max_output_tokens: int = 1024
    context_window: int = 8192
    timeout: int = 180


class ModelsConfig(BaseModel):
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    rerank: RerankConfig = Field(default_factory=RerankConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)


class IngestCacheConfig(BaseModel):
    enabled: bool = True
    key_prefix: str = "ingest_cache:"
    step_version: str = "v1"


class SplitterGeneralConfig(BaseModel):
    child_tokens: int = 256
    parent_tokens: int = 1024
    overlap_ratio: float = 0.1
    table_context_window: int = 256


class SplitterConfig(BaseModel):
    default: str = "general"
    map: dict[str, str] = Field(default_factory=dict)
    general: SplitterGeneralConfig = Field(default_factory=SplitterGeneralConfig)


class AutoQuestionConfig(BaseModel):
    enabled: bool = True
    questions_per_chunk: int = 3
    queue: str = "low_priority"
    concurrency: int = 4  # M1: 并发生成问题的最大在途请求数


class AutoKeywordConfig(BaseModel):
    enabled: bool = False
    topn: int = 5


class EnhanceConfig(BaseModel):
    auto_question: AutoQuestionConfig = Field(default_factory=AutoQuestionConfig)
    auto_keyword: AutoKeywordConfig = Field(default_factory=AutoKeywordConfig)
    augmented_context: dict[str, Any] = Field(default_factory=lambda: {"enabled": False})


class VersionConfig(BaseModel):
    default_policy: str = "replace"
    purge_window_days: int = 7
    policy_by_doc_type: dict[str, str] = Field(default_factory=lambda: {"law": "coexist"})


class IngestConfig(BaseModel):
    upload_max_mb: int = 100
    task_retry_max: int = 3
    cache: IngestCacheConfig = Field(default_factory=IngestCacheConfig)
    splitter: SplitterConfig = Field(default_factory=SplitterConfig)
    enhance: EnhanceConfig = Field(default_factory=EnhanceConfig)
    version: VersionConfig = Field(default_factory=VersionConfig)


class FusionConfig(BaseModel):
    mode: str = "weighted"  # weighted | rrf
    vector_weight: float = 0.3


class RetrieveRerankConfig(BaseModel):
    score_threshold: float = 0.2
    top_n: int = 5
    candidate_pool_max: int = 400


class RetrieveCacheConfig(BaseModel):
    query_embedding_ttl: int = 3600
    query_result_ttl: int = 600


class RetrieveConfig(BaseModel):
    per_channel_top_k: int = 100
    vector_score_threshold: float | None = None
    fusion: FusionConfig = Field(default_factory=FusionConfig)
    kb_boost: dict[str, float] = Field(default_factory=dict)
    rerank: RetrieveRerankConfig = Field(default_factory=RetrieveRerankConfig)
    version_filter: str = "searchable_only"
    cache: RetrieveCacheConfig = Field(default_factory=RetrieveCacheConfig)


class AssembleConfig(BaseModel):
    context_window: int = 8192
    max_output: int = 1024
    prompt_overhead: int = 800
    merge_sibling_chunks: bool = True
    truncation: str = "keep_head_tail"


class RouterConfig(BaseModel):
    mode: str = "auto"
    confidence_threshold: float = 0.6
    max_retry: int = 2
    planner_max_steps: int = 4


class LawConfig(BaseModel):
    default_status_filter: str = "现行有效"
    graph_enabled: bool = False


class CeleryQueueConfig(BaseModel):
    concurrency: int = 4


class CeleryConfig(BaseModel):
    broker_url: str = ""
    result_backend: str = ""
    queues: dict[str, CeleryQueueConfig] = Field(
        default_factory=lambda: {
            "high_priority": CeleryQueueConfig(concurrency=4),
            "low_priority": CeleryQueueConfig(concurrency=2),
        }
    )


class LoggingConfig(BaseModel):
    level: str = "INFO"
    query_log_enabled: bool = True
    file_enabled: bool = True          # 日志落文件（logs/ 目录，按天轮转）
    dir: str = "logs"
    file_max_days: int = 14            # 轮转保留天数


class AppConfig(BaseModel):
    env: str = RAG_ENV
    server: ServerConfig = Field(default_factory=ServerConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    postgres: PostgresConfig = Field(default_factory=PostgresConfig)
    milvus: MilvusConfig = Field(default_factory=MilvusConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    neo4j: Neo4jConfig = Field(default_factory=Neo4jConfig)
    minio: MinioConfig = Field(default_factory=MinioConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    ingest: IngestConfig = Field(default_factory=IngestConfig)
    retrieve: RetrieveConfig = Field(default_factory=RetrieveConfig)
    assemble: AssembleConfig = Field(default_factory=AssembleConfig)
    router: RouterConfig = Field(default_factory=RouterConfig)
    law: LawConfig = Field(default_factory=LawConfig)
    celery: CeleryConfig = Field(default_factory=CeleryConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def build_config() -> AppConfig:
    """yaml 配置 ← RAG_ 前缀环境变量覆盖（双下划线表示嵌套层级，如 RAG_RETRIEVE__RERANK__SCORE_THRESHOLD）。"""
    data = dict(_yaml)
    prefix = "RAG_"
    for key, val in os.environ.items():
        if not key.startswith(prefix):
            continue
        parts = key[len(prefix):].lower().split("__")
        node: dict = data
        for p in parts[:-1]:
            node = node.setdefault(p, {})
            if not isinstance(node, dict):
                break
        else:
            node[parts[-1]] = yaml.safe_load(val)  # 类型按 yaml 解析
    return AppConfig(**data)


settings = build_config()

# prod 下强制校验必填项与密钥非默认值（§1 配置管理约定）
# 本地开发默认密钥集合：prod 环境一旦命中直接拒绝启动
_KNOWN_DEFAULT_SECRETS = {
    "rag_local_pwd", "redis_local_pwd", "minioadmin", "neo4j_local_pwd",
    "postgres", "password", "changeme", "xxx", "",
}
if settings.env == "prod":
    _secrets = {
        "PG_PASSWORD": os.environ.get("PG_PASSWORD"),
        "REDIS_PASSWORD": os.environ.get("REDIS_PASSWORD"),
        "MINIO_ACCESS_KEY": os.environ.get("MINIO_ACCESS_KEY"),
        "MINIO_SECRET_KEY": os.environ.get("MINIO_SECRET_KEY"),
        "NEO4J_PASSWORD": os.environ.get("NEO4J_PASSWORD"),
    }
    # 前 4 项为必填；Neo4j 密码仅在启用时要求非默认值
    _required_keys = ("PG_PASSWORD", "REDIS_PASSWORD", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY")
    missing = [k for k in _required_keys if not _secrets[k]]
    weak = [k for k, v in _secrets.items() if v and v.lower() in _KNOWN_DEFAULT_SECRETS]
    if missing:
        raise RuntimeError(f"prod 环境缺少必填密钥: {missing}")
    if weak:
        raise RuntimeError(f"prod 环境仍在使用默认/弱密钥，请替换后再启动: {weak}")
