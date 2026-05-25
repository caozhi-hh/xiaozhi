"""网络搜索工具 — DuckDuckGo"""
from langchain_community.tools import DuckDuckGoSearchRun

_search = DuckDuckGoSearchRun()


def web_search(query: str) -> str:
    """搜索互联网获取最新信息。当用户问时事、新闻、或其他需要最新数据的问题时使用。"""
    return _search.invoke(query)
