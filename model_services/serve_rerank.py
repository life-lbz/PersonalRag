"""serve_rerank.py —— bge-reranker-base（方案E选定, CPU）。

启动: python model_services/serve_rerank.py   (:8002)
注意: 必须用模型收 body（pydantic），标量参数会被 FastAPI 解析为查询参数导致 422。
"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import app._platform_fix  # noqa: E402  Windows 下短路 WMI 平台查询, 避免首次加载模型时卡死

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

_DEFAULT_MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "bge-reranker-base"
MODEL_DIR = os.environ.get("BGE_RERANKER_DIR", str(_DEFAULT_MODEL_DIR))
USE_FP16 = os.environ.get("BGE_USE_FP16", "0") == "1"
PORT = int(os.environ.get("RERANK_PORT", "8002"))

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """启动即加载模型：health 就绪即代表模型可用，避免首个业务请求冷加载超时。"""
    get_model()
    yield


app = FastAPI(title="bge-reranker-base service", lifespan=_lifespan)
_model = None


def get_model():
    global _model
    if _model is None:
        from FlagEmbedding import FlagReranker

        _model = FlagReranker(MODEL_DIR, use_fp16=USE_FP16)
    return _model


class RerankReq(BaseModel):
    query: str
    documents: list[str]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/v1/rerank")
def rerank(req: RerankReq):
    model = get_model()
    scores = model.compute_score([[req.query, d] for d in req.documents],
                                 normalize=True, batch_size=16)
    if not isinstance(scores, list):
        scores = [scores]
    return {"scores": [float(s) for s in scores]}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
