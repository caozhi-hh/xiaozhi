"""知识库搜索工具 — 从向量知识库中检索相关信息"""
import logging
from langchain_core.tools import tool

logger = logging.getLogger("knowledge_search")


@tool
def search_knowledge(query: str) -> str:
    """搜索用户的知识库。当用户问到之前上传的文档内容、个人知识库中的信息、或需要参考已有资料时使用。
    输入为搜索关键词或自然语言问题。

    Args:
        query: 搜索查询，可以是关键词或自然语言问题
    """
    try:
        from services.knowledge import search_knowledge as _search
        results = _search(query, top_k=5)
        if not results:
            return "知识库中没有找到相关内容。请直接回答用户问题。"
        lines = []
        for i, r in enumerate(results, 1):
            source = r.get("filename") or r.get("source_id", "未知来源")
            lines.append(f"[{i}] (来源: {source}) {r['content']}")
        return "知识库检索结果：\n" + "\n".join(lines)
    except Exception as e:
        logger.error("知识库搜索失败: %s", e)
        return "知识库搜索暂不可用。请直接回答用户问题。"
