"""
企业微信渠道适配器

核心职责：
1. 查找/创建企微用户的对话
2. 复用小智的 Agent + 记忆 + RAG 处理消息
3. 非流式调用 Agent，收集完整回复
"""
import logging

from database import SessionLocal
from models import Conversation, Message
from memory import extract_memories
from agent import create_agent

logger = logging.getLogger("wecom.adapter")

# 小智系统固定 USER_ID
USER_ID = 1

# 模型名称（默认用 qwen-max）
DEFAULT_MODEL = "qwen-max"


def _get_or_create_conversation(db, wecom_user_id: str, content: str) -> int:
    """根据企微用户 ID 查找活跃对话，没有则创建"""
    tag = f"[WeCom:{wecom_user_id}]"
    conv = (
        db.query(Conversation)
        .filter(Conversation.user_id == USER_ID, Conversation.title.startswith(tag))
        .order_by(Conversation.created_at.desc())
        .first()
    )
    if conv:
        return conv.id

    # 创建新对话
    preview = content[:8] + "..." if len(content) > 8 else content
    conv = Conversation(title=f"{tag} {preview}", user_id=USER_ID)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    logger.info("创建企微对话: conv_id=%d, user=%s", conv.id, wecom_user_id)
    return conv.id


def _build_messages_simple(history, user_id=USER_ID, db=None, query=None):
    """构建消息列表（注入记忆+RAG），复用 main.py 的逻辑"""
    from agent.prompt import SYSTEM_PROMPT
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

    system_content = SYSTEM_PROMPT

    if db:
        mems = (
            db.query(Memory)
            .filter(Memory.user_id == user_id)
            .order_by(Memory.updated_at.desc())
            .limit(20)
            .all()
        )
        if mems:
            mem_text = "\n\n【关于用户的记忆】\n" + "\n".join(
                f"- [{m.category}] {m.content}" for m in mems
            )
            system_content += mem_text

        if query:
            from rag import search_knowledge

            doc_count = db.query(Document).filter(Document.user_id == user_id).count()
            if doc_count > 0:
                results = search_knowledge(user_id, query)
                if results:
                    rag_text = "\n\n【知识库参考】\n" + "\n".join(
                        f"- [来源: {r['filename']}] {r['content']}" for r in results
                    )
                    system_content += rag_text

    messages = [SystemMessage(content=system_content)]
    for m in history:
        if m.role == "user":
            messages.append(HumanMessage(content=m.content))
        else:
            messages.append(AIMessage(content=m.content))
    return messages


async def process_message(wecom_user_id: str, content: str) -> str:
    """
    处理来自企业微信的消息，返回 AI 回复文本。

    流程：
    1. 创建独立 DB 会话（后台任务，不能用请求级的 get_db）
    2. 查找/创建对话
    3. 保存用户消息
    4. 构建消息列表（注入记忆+RAG）
    5. 调用 Agent（非流式 ainvoke）
    6. 保存 AI 回复 + 提取记忆
    """
    db = SessionLocal()
    try:
        # 1. 查找/创建对话
        conv_id = _get_or_create_conversation(db, wecom_user_id, content)

        # 2. 保存用户消息
        db.add(Message(role="user", content=content, conversation_id=conv_id))
        db.commit()

        # 3. 构建消息列表
        history = (
            db.query(Message)
            .filter(Message.conversation_id == conv_id)
            .order_by(Message.created_at)
            .all()
        )
        messages = _build_messages_simple(history, user_id=USER_ID, db=db, query=content)

        # 4. 调用 Agent（非流式）
        agent = create_agent(DEFAULT_MODEL)
        if agent:
            result = await agent.ainvoke({"messages": messages})
            ai_content = result["messages"][-1].content
        else:
            # Agent 创建失败，用简单 LLM 对话
            from llm import get_llm

            llm = get_llm(DEFAULT_MODEL)
            response = await llm.ainvoke(messages)
            ai_content = response.content

        # 5. 保存 AI 回复
        db.add(Message(role="assistant", content=ai_content, conversation_id=conv_id))
        db.commit()

        # 6. 后台提取记忆（不阻塞回复）
        try:
            await extract_memories(content, ai_content, USER_ID)
        except Exception as e:
            logger.warning("记忆提取失败: %s", e)

        return ai_content

    except Exception as e:
        logger.error("处理企微消息失败: %s", e, exc_info=True)
        return f"抱歉，处理消息时出错了: {str(e)[:100]}"
    finally:
        db.close()
