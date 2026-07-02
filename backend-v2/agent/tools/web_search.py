"""网络搜索工具 — 智谱 web-search-pro（国内可用，替代 DuckDuckGo）

DuckDuckGo(ddgs) 走 brave.com 国内持续超时，已弃用。
改用智谱独立搜索 API：POST https://open.bigmodel.cn/api/paas/v4/tools
- 复用 .env 里 MODEL_* 配置的智谱 key（无需额外环境变量）
- 0.03 元/次
- 失败降级返回 str，绝不抛异常（避免 Agent 崩 + str+list 拼接错）
"""
import logging
import uuid
import httpx
from langchain_core.tools import tool

logger = logging.getLogger("web_search")

API_URL = "https://open.bigmodel.cn/api/paas/v4/tools"
TIMEOUT = 15  # 智谱 API 通常 2-5s，15s 余量


def _get_api_key() -> str:
    """从 core.llm 注册表取智谱 key（复用 .env 里 MODEL_ 配置，无需单独变量）"""
    try:
        from core.llm import MODELS
        for m in MODELS.values():
            if "bigmodel" in m.get("base_url", "") and m.get("api_key"):
                return m["api_key"]
    except Exception:
        pass
    return ""


def _parse_search_result(data: dict) -> str:
    """从智谱返回里提取 search_result，拼成 LLM 友好的 str"""
    try:
        tool_calls = data["choices"][0]["message"]["tool_calls"]
        for tc in tool_calls:
            if tc.get("type") == "search_result":
                items = tc.get("search_result", [])
                lines = []
                for i, it in enumerate(items[:8], 1):
                    title = it.get("title", "")
                    content = it.get("content", "")
                    link = it.get("link", "")
                    lines.append(f"[{i}] {title}\n{content}\n来源: {link}")
                return "\n\n".join(lines) if lines else ""
    except Exception as e:
        logger.warning("解析智谱搜索结果失败: %s", e)
    return ""


@tool
def web_search(query: str) -> str:
    """搜索互联网获取最新信息。当用户问时事、新闻、或其他需要最新数据的问题时使用。"""
    api_key = _get_api_key()
    if not api_key:
        return "搜索功能暂不可用（未配置智谱 API key）。请直接用你的已有知识回答用户。"

    try:
        resp = httpx.post(
            API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "request_id": str(uuid.uuid4()),
                "tool": "web-search-pro",
                "stream": False,
                "messages": [{"role": "user", "content": query}],
            },
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        results = _parse_search_result(resp.json())
        if results:
            return results
        return f"搜索未返回结果（{query}）。请用你的已有知识回答。"
    except Exception as e:
        logger.warning("web_search 智谱搜索失败(query=%s): %s", query, e)
        return (
            f"网络搜索暂时不可用（{type(e).__name__}: {str(e)[:120]}）。"
            f"请直接用你的已有知识回答用户关于「{query}」的问题，并说明这是离线回答、可能不是最新信息。"
        )
