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
from pathlib import Path
from langchain_openai import ChatOpenAI
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


def get_llm(model_key: str = "glm-4-flash") -> ChatOpenAI:
    """根据模型标识获取 LLM 客户端（带缓存）"""
    if model_key in _llm_cache:
        return _llm_cache[model_key]

    config = MODELS.get(model_key)
    if not config:
        # 找不到就用第一个可用的模型
        fallback = next(iter(MODELS.values()), None)
        if not fallback:
            raise RuntimeError("没有可用的模型，请检查 .env 配置")
        config = fallback

    llm = ChatOpenAI(
        api_key=config["api_key"],
        base_url=config["base_url"],
        model=config["model"],
        streaming=True,
    )
    _llm_cache[model_key] = llm
    return llm


def get_available_models() -> list[dict]:
    """返回前端可选的模型列表"""
    return [
        {"key": k, "name": v["display_name"]}
        for k, v in MODELS.items()
    ]


SYSTEM_PROMPT = """你是一个叫"小智"的 AI 助手。

你的性格特点：
- 友好、幽默、偶尔调皮
- 回答问题清晰有逻辑
- 擅长用大白话解释复杂概念
- 会在适当的时候用 emoji 增加趣味

你的能力：
- 回答各种问题
- 帮助分析和解决问题
- 陪用户聊天
- 提供建议和思路

注意：
- 用中文回答
- 不要编造不确定的信息
- 如果不知道就说不知道
"""
