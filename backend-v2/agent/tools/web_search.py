"""网络搜索工具 — DuckDuckGo（lazy import，缺包时跳过）"""
import logging
from langchain_core.tools import tool

logger = logging.getLogger("web_search")
_search = None

try:
    from langchain_community.tools import DuckDuckGoSearchRun
    _search = DuckDuckGoSearchRun()
except ImportError:
    logger.warning("duckduckgo-search 未安装，web_search 工具不可用")


@tool
def web_search(query: str) -> str:
    """搜索互联网获取最新信息。当用户问时事、新闻、或其他需要最新数据的问题时使用。"""
    if _search is None:
        return "搜索功能暂不可用（duckduckgo-search 未安装）。请直接回答用户问题。"
    return _search.invoke(query)
