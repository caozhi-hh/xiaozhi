"""
Agent 工厂 — 创建 LangGraph ReAct Agent

流程：
  create_agent("qwen-max")
  → 尝试创建带 tools 的 Agent
  → 成功：返回 Agent（可调工具）
  → 失败：返回 None（走普通聊天）
"""
from langgraph.prebuilt import create_react_agent

from tools import TOOLS
from llm import get_llm

AGENT_PROMPT = (
    "你是一个叫'小智'的 AI 助手。\n"
    "你拥有以下工具能力：\n"
    "- web_search: 搜索互联网获取最新信息\n"
    "- get_weather: 查询城市天气\n"
    "- translate: 翻译文本\n"
    "- generate_image: 根据文字描述生成图片\n\n"
    "【重要规则】当用户说'画''生成图片''画一个''给我画'等任何涉及图片生成的请求时，"
    "你**必须**调用 generate_image 工具，绝对不要只用文字描述图片。"
    "将用户的中文需求翻译成详细的英文 prompt 传给工具。\n"
    "只在真正需要时才使用其他工具（搜索、天气、翻译）。普通聊天直接回答即可。\n"
    "用中文回答，友好幽默，偶尔调皮。"
)

_agent_cache: dict = {}


def create_agent(model_key: str):
    """为指定模型创建 ReAct Agent，不支持 tool_call 时返回 None。"""
    if model_key in _agent_cache:
        return _agent_cache[model_key]

    llm = get_llm(model_key)

    try:
        agent = create_react_agent(
            model=llm,
            tools=TOOLS,
            prompt=AGENT_PROMPT,
        )
        _agent_cache[model_key] = agent
        return agent
    except Exception:
        return None
