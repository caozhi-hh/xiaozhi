"""
向量知识库 — ChromaDB + 本地 bge-small Embedding

功能：
  - 文档上传 → 自动分块 → 向量化 → 存储
  - 手动文本输入 → 分块 → 向量化 → 存储
  - 语义搜索 → 返回最相关的知识片段
  - 管理接口 → 列出/删除知识条目
"""
import os
import uuid
import logging
from datetime import datetime, timezone

logger = logging.getLogger("xiaozhi.knowledge")

# ---------- 配置 ----------

CHROMA_DIR = os.environ.get("CHROMA_DIR", "/data/chroma_db")
COLLECTION_NAME = "knowledge"
EMBEDDING_MODEL_NAME = "BAAI/bge-small-zh-v1.5"  # 本地 bge(512维,免费离线);改这个常量会触发知识库自动迁移
CHUNK_SIZE = 500
CHUNK_OVERLAP = 100

# 本地开发兜底路径
if not os.path.isabs(CHROMA_DIR):
    # services/ → 退到 backend-v2/ 根，与迁移前路径一致
    CHROMA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), CHROMA_DIR)

# ---------- 单例缓存 ----------

_embedding = None
_chroma_client = None
_collection = None


def _get_embedding():
    """获取 Embedding 客户端（单例，本地 bge 模型，免费离线，不依赖任何 API key）"""
    global _embedding
    if _embedding is not None:
        return _embedding

    from langchain_huggingface import HuggingFaceEmbeddings

    _embedding = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL_NAME,
        encode_kwargs={"normalize_embeddings": True},
    )
    logger.info("Embedding 客户端初始化完成 (本地模型=%s)", EMBEDDING_MODEL_NAME)
    return _embedding


def _get_chroma():
    """获取 ChromaDB 持久化客户端（单例）"""
    global _chroma_client
    if _chroma_client is not None:
        return _chroma_client

    import chromadb

    os.makedirs(CHROMA_DIR, exist_ok=True)
    _chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
    logger.info("ChromaDB 客户端初始化完成 (path=%s)", CHROMA_DIR)
    return _chroma_client


def _migrate_collection(client, old_collection):
    """embedding 模型不兼容时，读原文用当前模型(bge)重新 embed 重建，保留数据"""
    old_model = (old_collection.metadata or {}).get("embedding_model", "旧版(未知)")
    logger.warning("知识库 embedding 不兼容(%s → %s)，启动自动迁移...", old_model, EMBEDDING_MODEL_NAME)
    all_data = old_collection.get(include=["documents", "metadatas"])
    docs = all_data.get("documents") or []
    ids = all_data.get("ids") or []
    metas = all_data.get("metadatas") or []
    if not docs:
        client.delete_collection(COLLECTION_NAME)
        logger.info("旧库为空，已删除待重建")
        return
    n = len(docs)
    logger.info("读取旧库 %d 条原文，用 bge 重新 embed...", n)
    embedding = _get_embedding()
    new_embeddings = _embed_batch(embedding, docs)
    client.delete_collection(COLLECTION_NAME)
    logger.info("旧库已删除，写入新库(%d 条, bge 512维)...", n)
    new_col = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"description": "小智的知识库", "embedding_model": EMBEDDING_MODEL_NAME},
    )
    new_col.add(ids=ids, documents=docs, embeddings=new_embeddings, metadatas=metas)
    logger.info("迁移完成 ✓ %d 条已用 bge 重新 embed", n)


def _get_collection():
    """获取 knowledge 集合（启动时检测 embedding 兼容性，不兼容自动迁移）"""
    global _collection
    if _collection is not None:
        return _collection

    client = _get_chroma()
    # 检测现有 collection 的 embedding 模型是否匹配当前(不匹配则自动迁移)
    try:
        existing = client.get_collection(name=COLLECTION_NAME)
        if existing.count() > 0:
            col_model = (existing.metadata or {}).get("embedding_model", "")
            if col_model != EMBEDDING_MODEL_NAME:
                _migrate_collection(client, existing)
    except Exception as e:
        logger.debug("无现有 collection(首次创建): %s", e)

    _collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"description": "小智的知识库", "embedding_model": EMBEDDING_MODEL_NAME},
    )
    logger.info("ChromaDB 集合 '%s' 就绪，已有 %d 条记录", COLLECTION_NAME, _collection.count())
    return _collection


def _chunk_text(text: str) -> list[str]:
    """将文本按中文友好规则切片"""
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
        length_function=len,
    )
    chunks = splitter.split_text(text)
    return chunks


def _embed_batch(embedding, documents: list[str], batch_size: int = 6) -> list[list[float]]:
    """分批生成 Embedding（控制内存，本地 bge 无条数限制）"""
    all_embeddings = []
    for i in range(0, len(documents), batch_size):
        batch = documents[i : i + batch_size]
        batch_embeddings = embedding.embed_documents(batch)
        all_embeddings.extend(batch_embeddings)
        logger.debug("Embedding 批次 %d/%d 完成", i // batch_size + 1, -(-len(documents) // batch_size))
    return all_embeddings


# ---------- 核心操作 ----------


def add_document(source_id: str, filename: str, text: str) -> dict:
    """
    文档入库：切片 → 生成 Embedding → 存入 ChromaDB

    Args:
        source_id: 来源唯一标识
        filename: 原始文件名
        text: 提取出的全文

    Returns:
        {"source_id": str, "filename": str, "chunks": int}
    """
    if not text or not text.strip():
        return {"source_id": source_id, "filename": filename, "chunks": 0}

    chunks = _chunk_text(text)
    if not chunks:
        return {"source_id": source_id, "filename": filename, "chunks": 0}

    collection = _get_collection()
    embedding = _get_embedding()
    now = datetime.now(timezone.utc).isoformat()

    ids = []
    documents = []
    metadatas = []
    for i, chunk in enumerate(chunks):
        ids.append(f"{source_id}#{i}")
        documents.append(chunk)
        metadatas.append({
            "source_id": source_id,
            "filename": filename,
            "source_type": "document",
            "chunk_index": i,
            "created_at": now,
        })

    # 生成 Embedding 并入库
    embeddings = _embed_batch(embedding, documents)
    collection.add(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)

    logger.info("文档入库完成: %s, %d 个分块", filename, len(chunks))
    return {"source_id": source_id, "filename": filename, "chunks": len(chunks)}


def add_text(source_id: str, title: str, text: str) -> dict:
    """
    手动文本入库：切片 → 生成 Embedding → 存入 ChromaDB

    Args:
        source_id: 来源唯一标识
        title: 文本标题
        text: 文本内容

    Returns:
        {"source_id": str, "title": str, "chunks": int}
    """
    if not text or not text.strip():
        return {"source_id": source_id, "title": title, "chunks": 0}

    chunks = _chunk_text(text)
    if not chunks:
        return {"source_id": source_id, "title": title, "chunks": 0}

    collection = _get_collection()
    embedding = _get_embedding()
    now = datetime.now(timezone.utc).isoformat()

    ids = []
    documents = []
    metadatas = []
    for i, chunk in enumerate(chunks):
        ids.append(f"{source_id}#{i}")
        documents.append(chunk)
        metadatas.append({
            "source_id": source_id,
            "filename": title,
            "source_type": "text",
            "chunk_index": i,
            "created_at": now,
        })

    embeddings = _embed_batch(embedding, documents)
    collection.add(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)

    logger.info("文本入库完成: %s, %d 个分块", title, len(chunks))
    return {"source_id": source_id, "title": title, "chunks": len(chunks)}


def search_knowledge(query: str, top_k: int = 5) -> list[dict]:
    """
    语义搜索知识库

    Args:
        query: 查询文本
        top_k: 返回前 K 条结果

    Returns:
        [{"content": str, "filename": str, "source_id": str, "distance": float}]
    """
    try:
        collection = _get_collection()
        if collection.count() == 0:
            return []

        embedding = _get_embedding()
        query_embedding = embedding.embed_query(query)

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        if not results["documents"] or not results["documents"][0]:
            return []

        items = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            items.append({
                "content": doc,
                "filename": meta.get("filename", ""),
                "source_id": meta.get("source_id", ""),
                "distance": dist,
            })
        return items
    except Exception as e:
        logger.error("知识库搜索失败: %s", e)
        return []


def list_sources() -> list[dict]:
    """列出知识库中所有来源（按 source_id 聚合）"""
    try:
        collection = _get_collection()
        if collection.count() == 0:
            return []

        all_meta = collection.get(include=["metadatas"])
        source_map: dict[str, dict] = {}

        for meta in all_meta["metadatas"]:
            sid = meta.get("source_id", "")
            if not sid:
                continue
            if sid not in source_map:
                source_map[sid] = {
                    "source_id": sid,
                    "filename": meta.get("filename", ""),
                    "source_type": meta.get("source_type", ""),
                    "chunk_count": 0,
                    "created_at": meta.get("created_at", ""),
                }
            source_map[sid]["chunk_count"] += 1

        return list(source_map.values())
    except Exception as e:
        logger.error("列出知识来源失败: %s", e)
        return []


def delete_source(source_id: str) -> bool:
    """删除某个来源的所有分块"""
    try:
        collection = _get_collection()
        results = collection.get(
            where={"source_id": source_id},
            include=["metadatas"],
        )
        if not results["ids"]:
            return False

        collection.delete(ids=results["ids"])
        logger.info("已删除来源: %s (%d 个分块)", source_id, len(results["ids"]))
        return True
    except Exception as e:
        logger.error("删除知识来源失败: %s", e)
        return False


def get_stats() -> dict:
    """获取知识库统计信息"""
    try:
        collection = _get_collection()
        sources = list_sources()
        return {
            "total_chunks": collection.count(),
            "total_sources": len(sources),
        }
    except Exception as e:
        logger.error("获取知识库统计失败: %s", e)
        return {"total_chunks": 0, "total_sources": 0}
