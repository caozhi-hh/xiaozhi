"""
Agent 工厂 — 用 DeepAgents create_deep_agent 创建 Agent

支持多智能体：通过 subagents 参数启用 SubAgentMiddleware，
主 Agent 可派子 Agent 执行子任务（搜索、翻译、分析等）。
"""
from deepagents import create_deep_agent

from agent.tools import ALL_TOOLS
from agent.prompt import AGENT_PROMPT
from llm import get_llm

_agent_cache: dict = {}

# 子智能体定义 — 各有专长
_SUBAGENTS = [
    {
        "name": "researcher",
        "description": "搜索和研究智能体，擅长从互联网搜集信息并总结",
        "system_prompt": "你是一个研究助手。根据用户的请求搜索信息，用中文给出简洁准确的总结。",
    },
    {
        "name": "analyst",
        "description": "分析智能体，擅长数据分析、逻辑推理和深入思考",
        "system_prompt": "你是一个分析助手。对问题进行深入分析，给出有逻辑、有深度的回答。",
    },
    {
        "name": "writer",
        "description": "写作智能体，擅长文案创作、内容润色和格式化输出",
        "system_prompt": "你是一个写作助手。根据用户的需求撰写或优化文本内容，语言流畅、结构清晰。",
    },
]


def create_agent(model_key: str, enable_subagents: bool = True):
    """为指定模型创建 DeepAgent。

    Args:
        model_key: 模型标识，对应 .env 中的配置
        enable_subagents: 是否启用多智能体（企业微信场景建议开启）
    """
    if model_key in _agent_cache:
        return _agent_cache[model_key]

    llm = get_llm(model_key)

    try:
        kwargs = {
            "model": llm,
            "tools": ALL_TOOLS,
            "system_prompt": AGENT_PROMPT,
        }

        if enable_subagents:
            # DeepAgents 会自动注入 SubAgentMiddleware
            kwargs["subagents"] = _SUBAGENTS

        agent = create_deep_agent(**kwargs)
        _agent_cache[model_key] = agent
        return agent
    except Exception:
        return None
