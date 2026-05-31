"""
LLM 配置 — 模型注册表 + 动态创建客户端

模型注册表：
  优先读环境变量，回退 .env 文件
  格式：MODEL_名称=https://base_url|api_key|model_name
"""
import os
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'

from pathlib import Path
from langchain_openai import ChatOpenAI
from langchain_community.embeddings import DashScopeEmbeddings
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

# load_dotenv 不覆盖已有环境变量（HF Secrets 优先）
load_dotenv(ENV_FILE, override=False)


def _load_models() -> dict:
    models = {}
    for key, value in os.environ.items():
        if not key.startswith("MODEL_"):
            continue
        parts = value.split("|")
        if len(parts) != 3:
            continue
        base_url, api_key, model_name = parts
        display = key[6:].lower().replace("_", "-")
        models[display] = {
            "base_url": f"https://{base_url}" if not base_url.startswith("http") else base_url,
            "api_key": api_key,
            "model": model_name,
            "display_name": display,
        }
    return models

MODELS = _load_models()

_llm_cache: dict = {}


def _make_http_client():
    import httpx
    return httpx.Client(proxy=None, timeout=httpx.Timeout(120.0))


def get_llm(model_key: str = "glm-4-flash") -> ChatOpenAI:
    if model_key in _llm_cache:
        return _llm_cache[model_key]

    config = MODELS.get(model_key)
    if not config:
        fallback = next(iter(MODELS.values()), None)
        if not fallback:
            raise RuntimeError("没有可用的模型，请检查环境变量或 .env 配置")
        config = fallback

    llm = ChatOpenAI(
        api_key=config["api_key"],
        base_url=config["base_url"],
        model=config["model"],
        streaming=True,
        http_client=_make_http_client(),
    )
    _llm_cache[model_key] = llm
    return llm


_embeddings_cache = None

def get_embeddings() -> DashScopeEmbeddings:
    global _embeddings_cache
    if _embeddings_cache:
        return _embeddings_cache

    qwen_config = MODELS.get("qwen-max") or MODELS.get("qwen-turbo")
    if not qwen_config:
        raise RuntimeError("未找到 DashScope 模型配置，无法初始化 Embedding")

    _embeddings_cache = DashScopeEmbeddings(
        model="text-embedding-v3",
        dashscope_api_key=qwen_config["api_key"],
    )
    return _embeddings_cache


def get_available_models() -> list[dict]:
    return [
        {"key": k, "name": v["display_name"]}
        for k, v in MODELS.items()
    ]
