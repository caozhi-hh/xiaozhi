"""
LLM 配置 — 模型注册表 + 动态创建客户端

模型注册表：
  从 .env 文件读取所有 MODEL_ 开头的配置
  格式：MODEL_名称=https://base_url|api_key|model_name

  get_llm("glm-4-flash") → 返回对应的 ChatOpenAI 客户端
  get_available_models() → 返回可选模型列表

所有国产模型都用 OpenAI 兼容接口：
  换 base_url + api_key + model 就能切换，代码不用改
"""
import os
# 绕过系统代理直连 API（代理会导致 Python 3.14 SSL 握手失败）
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'

from pathlib import Path
from langchain_openai import ChatOpenAI
from langchain_community.embeddings import DashScopeEmbeddings
from dotenv import load_dotenv, dotenv_values

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

load_dotenv(ENV_FILE, override=True)

def _load_models() -> dict:
    models = {}
    env_values = dotenv_values(ENV_FILE)
    for key, value in env_values.items():
        if not key.startswith("MODEL_"):
            continue
        parts = value.split("|")
        if len(parts) != 3:
            continue
        base_url, api_key, model_name = parts
        # KEY 名转显示名：MODEL_GLM_4_FLASH → glm-4-flash
        display = key[6:].lower().replace("_", "-")
        models[display] = {
            "base_url": f"https://{base_url}" if not base_url.startswith("http") else base_url,
            "api_key": api_key,
            "model": model_name,
            "display_name": display,
        }
    return models

MODELS = _load_models()

# 缓存已创建的 LLM 客户端，避免重复创建
_llm_cache: dict = {}


def _make_http_client():
    """创建不走代理的 httpx 客户端"""
    import httpx
    return httpx.Client(proxy=None, timeout=httpx.Timeout(120.0))


def get_llm(model_key: str = "glm-4-flash") -> ChatOpenAI:
    """根据模型标识获取 LLM 客户端（带缓存）"""
    if model_key in _llm_cache:
        return _llm_cache[model_key]

    config = MODELS.get(model_key)
    if not config:
        fallback = next(iter(MODELS.values()), None)
        if not fallback:
            raise RuntimeError("没有可用的模型，请检查 .env 配置")
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
    """获取 DashScope Embedding 客户端（text-embedding-v3）"""
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
    """返回前端可选的模型列表"""
    return [
        {"key": k, "name": v["display_name"]}
        for k, v in MODELS.items()
    ]
