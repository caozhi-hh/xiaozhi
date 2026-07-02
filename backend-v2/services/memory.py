"""
记忆系统 — 自动从对话中提取关键信息

流程：
  对话完成 → LLM 分析 → 提取可记忆信息 → 去重 → 存入 memories 表
"""
import json
import asyncio
from sqlalchemy.orm import Session
from core.models import Memory
from core.database import SessionLocal
from core.llm import get_llm

EXTRACT_PROMPT = """你是一个信息提取助手。分析下面的用户和 AI 对话，提取值得长期记住的关键信息。

规则：
- 只提取关于用户个人的事实性信息（名字、职业、年龄、地区、技术栈、项目背景等）
- 提取用户的明确偏好（喜欢/不喜欢的风格、格式、语言等）
- 忽略一次性的闲聊内容、普通问答
- 每条记忆要简洁（一句话）
- 如果没有值得记住的信息，返回空数组

分类说明：
- profile: 个人信息（名字、职业、学校、地区等）
- preference: 偏好（回答风格、语言、格式等）
- knowledge: 背景知识（项目、技术栈、工作内容等）
- context: 当前正在做的事（任务、计划等）

输出格式（纯 JSON，不要 markdown）：
[{{"category": "profile", "content": "用户名叫小明"}}, ...]

用户说：{user_text}

AI 回复：{ai_text}"""


def _extract_sync(user_text: str, ai_text: str, user_id: int):
    """同步版本，在线程中运行，使用独立 db session"""
    if len(user_text) < 5:
        return

    prompt = EXTRACT_PROMPT.format(user_text=user_text[:500], ai_text=ai_text[:500])
    db = SessionLocal()

    try:
        llm = get_llm("glm-4-flash")
        response = llm.invoke(prompt)
        raw = response.content.strip()

        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        items = json.loads(raw)
        if not isinstance(items, list):
            return

        for item in items:
            category = item.get("category", "context")
            content = item.get("content", "").strip()
            if not content or category not in ("profile", "preference", "knowledge", "context"):
                continue

            existing = db.query(Memory).filter(
                Memory.user_id == user_id,
                Memory.content.ilike(f"%{content[:20]}%")
            ).first()

            if existing:
                existing.content = content
                existing.category = category
            else:
                db.add(Memory(user_id=user_id, category=category, content=content))

        db.commit()
    except Exception:
        pass
    finally:
        db.close()


async def extract_memories(user_text: str, ai_text: str, user_id: int):
    """异步版本 — 在后台线程中运行提取，使用独立 db session"""
    await asyncio.to_thread(_extract_sync, user_text, ai_text, user_id)
