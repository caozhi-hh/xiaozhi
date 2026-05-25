"""
RAG 知识库 — 文档切分、向量化、检索

- ingest_document: 上传文档 → 切分 → embedding → 存 ChromaDB
- search_knowledge: 查询问题 → 向量搜索 → 返回相关片段
- 每个用户独立 collection（user_{id}）
"""

from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter

from llm import get_embeddings
from pathlib import Path

_CHROMA_DIR = Path(__file__).resolve().parent / "chroma_db"

_text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=100,
    separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""],
)


def _get_collection_name(user_id: int) -> str:
    return f"user_{user_id}"


def _get_vectorstore(user_id: int) -> Chroma:
    """获取用户的向量存储"""
    return Chroma(
        collection_name=_get_collection_name(user_id),
        embedding_function=get_embeddings(),
        persist_directory=str(_CHROMA_DIR),
    )


def ingest_document(user_id: int, doc_id: int, filename: str, text: str) -> int:
    """切分文档并存入向量数据库，返回 chunk 数量"""
    chunks = _text_splitter.split_text(text)
    if not chunks:
        return 0

    metadatas = [{"doc_id": doc_id, "filename": filename, "chunk_index": i} for i in range(len(chunks))]
    ids = [f"doc{doc_id}_chunk{i}" for i in range(len(chunks))]

    vs = _get_vectorstore(user_id)
    vs.add_texts(texts=chunks, metadatas=metadatas, ids=ids)

    return len(chunks)


def search_knowledge(user_id: int, query: str, top_k: int = 5) -> list[dict]:
    """搜索用户知识库，返回相关片段"""
    try:
        vs = _get_vectorstore(user_id)
        results = vs.similarity_search_with_score(query, k=top_k)
        return [
            {"content": doc.page_content, "filename": doc.metadata.get("filename", ""), "score": round(score, 4)}
            for doc, score in results
            if score < 1.0  # 过滤掉完全不相关的结果
        ]
    except Exception:
        return []


def delete_document_vectors(user_id: int, doc_id: int):
    """删除文档的所有向量"""
    try:
        vs = _get_vectorstore(user_id)
        chroma_collection = vs._collection
        chroma_collection.delete(where={"doc_id": doc_id})
    except Exception:
        pass
