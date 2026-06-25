"""
LLM 配置 — 模型注册表 + 动态创建客户端

模型注册表：
  从 .env 文件读取所有 MODEL_ 开头的配置
  格式：MODEL_名称=base_url|api_key|model_name

  get_llm("glm-5.2") → 返回对应的 ChatModel 客户端
  get_available_models() → 返回可选模型列表

协议自动识别（按 base_url）：
  - /api/anthropic  → ChatAnthropic（智谱 glm-5.x 等，Anthropic 协议端点）
  - 其他            → ChatOpenAI（OpenAI 兼容端点，如 paas/v4、SiliconFlow）

注册表 key 直接用 model_name（如 glm-5.2 / glm-4-flash / glm-4v），更直观。
"""
import os
# 绕过系统代理直连 API（代理会导致 Python 3.14 SSL 握手失败）
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'

from pathlib import Path
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from dotenv import load_dotenv, dotenv_values

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

load_dotenv(ENV_FILE, override=True)

def _load_models() -> dict:
    models = {}
    # 1) 先读 .env 文件（本地开发）
    file_values = dotenv_values(ENV_FILE)
    # 2) 环境变量覆盖（HF Secrets 等部署环境）
    env_values = {**file_values, **os.environ}
    for key, value in env_values.items():
        if not key.startswith("MODEL_"):
            continue
        parts = value.split("|")
        if len(parts) != 3:
            continue
        base_url, api_key, model_name = parts
        # 注册表 key 用 model_name（如 glm-5.2），直观且与调用处一致
        display = model_name
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


def get_llm(model_key: str = "glm-5.2") -> BaseChatModel:
    """根据模型标识获取 LLM 客户端（带缓存）。

    自动按 base_url 选协议：
    - /api/anthropic → ChatAnthropic（智谱 glm-5.x 额度在此端点）
    - 其他 → ChatOpenAI（OpenAI 兼容，paas/v4 / SiliconFlow 等）
    """
    if model_key in _llm_cache:
        return _llm_cache[model_key]

    config = MODELS.get(model_key)
    if not config:
        fallback = next(iter(MODELS.values()), None)
        if not fallback:
            raise RuntimeError("没有可用的模型，请检查 .env 配置")
        config = fallback

    base_url = config["base_url"]
    if "/api/anthropic" in base_url:
        # 智谱 Anthropic 协议端点（glm-5.x）
        llm = ChatAnthropic(
            api_key=config["api_key"],
            base_url=base_url,
            model=config["model"],
            max_tokens=4096,
            temperature=0,
            streaming=True,
        )
    else:
        # OpenAI 兼容端点（paas/v4 / SiliconFlow 等）
        llm = ChatOpenAI(
            api_key=config["api_key"],
            base_url=base_url,
            model=config["model"],
            streaming=True,
            http_client=_make_http_client(),
        )
    _llm_cache[model_key] = llm
    return llm


def get_available_models() -> list[dict]:
    """返回前端可选的模型列表"""
    return [
        {"key": k, "name": v["display_name"]}
        for k, v in MODELS.items()
    ]
