"""
小智 AI - 后端入口（DeepAgents 版·自用单用户）

路由结构：
  GET  /                    健康检查
  GET  /models              获取可用模型列表
  GET  /conversations       获取所有对话
  POST /conversations       新建对话
  DELETE /conversations/{id} 删除对话
  POST /chat/{conv_id}      聊天（SSE 流式）
  GET  /memories            获取记忆
  DELETE /memories/{id}     删除记忆
  POST /documents/upload    上传知识库文档
  GET  /documents           获取文档列表
  DELETE /documents/{id}    删除文档
"""
import os
# 绕过系统代理直连 API（代理会导致 Python 3.14 SSL 握手失败）
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'

import json
import logging
import asyncio
import httpx

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage

from database import get_db, engine, Base
from models import Conversation, Message, Memory, ScheduledTask
from llm import get_llm, get_available_models
from agent import create_agent
from agent.prompt import SYSTEM_PROMPT
from device import get_device_context, DeviceContext
from fastapi import Request
from agent.meme_fetcher import refresh_memes, start_background_refresh
from file_handler import is_image, is_pdf, is_docx, is_xlsx, extract_text, image_to_base64
from config import SILICONFLOW_API_KEY
from memory import extract_memories

# 创建所有数据库表（如果不存在）
Base.metadata.create_all(bind=engine)

# 自动迁移：给 conversations 表添加 device_id 列
def _migrate_device_id():
    import sqlite3
    from database import DB_PATH
    if not DB_PATH.startswith("sqlite"):
        return
    db_path = DB_PATH.replace("sqlite:///", "")
    if not os.path.exists(db_path):
        return
    try:
        conn = sqlite3.connect(db_path)
        cols = [row[1] for row in conn.execute("PRAGMA table_info(conversations)").fetchall()]
        if "device_id" not in cols:
            conn.execute("ALTER TABLE conversations ADD COLUMN device_id VARCHAR DEFAULT 'web-default'")
            conn.commit()
        conn.close()
    except Exception:
        pass

_migrate_device_id()

app = FastAPI(title="小智 AI", version="0.5.0")
logger = logging.getLogger("xiaozhi.main")

ALLOWED_ORIGINS = [
    "https://xiaozhi-ex8.pages.dev",
    "http://localhost:3000",
]
# 支持通过环境变量追加额外域名
extra = os.environ.get("CORS_ORIGINS", "")
if extra:
    ALLOWED_ORIGINS.extend(o.strip() for o in extra.split(",") if o.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Render 使用 PORT 环境变量
PORT = int(os.environ.get("PORT", 8001))

# 自用单用户，固定 user_id=1
USER_ID = 1

# 企业微信渠道（未配置时自动跳过，不影响 Web 前端）
from wecom import router as wecom_router
if wecom_router:
    app.include_router(wecom_router)


# ---------- 请求格式 ----------

class NewConversationRequest(BaseModel):
    title: str | None = None


class UpdateConversationRequest(BaseModel):
    title: str | None = None
    pinned: bool | None = None


# ---------- 基础接口 ----------

@app.get("/")
def root():
    return {"status": "ok", "message": "小智 AI 后端运行中", "version": app.version}


@app.get("/models")
def models_list():
    return get_available_models()


DEFAULT_SUGGESTIONS = [
    {"icon": "💡", "text": "帮我分析一下今天适合学什么"},
    {"icon": "🔍", "text": "搜索一下最近的 AI 新闻"},
    {"icon": "🎯", "text": "聊聊你的能力吧"},
]


@app.get("/suggestions")
def get_suggestions(db: Session = Depends(get_db)):
    mems = db.query(Memory).filter(Memory.user_id == USER_ID).order_by(Memory.updated_at.desc()).limit(10).all()
    recent_convs = db.query(Conversation).filter(Conversation.user_id == USER_ID).order_by(Conversation.created_at.desc()).limit(10).all()

    if len(mems) < 2 and len(recent_convs) < 3:
        return DEFAULT_SUGGESTIONS

    mem_summary = "\n".join(f"- [{m.category}] {m.content}" for m in mems[:5])
    conv_titles = ", ".join(c.title for c in recent_convs[:5])

    prompt = f"""根据以下用户信息，生成 3 个个性化的推荐提示，让用户在 AI 对话中使用。
每条包含 icon (emoji) 和 text (中文，15字以内)。
只返回 JSON 数组，不要其他文字。

用户记忆：
{mem_summary}

最近对话标题：{conv_titles}

输出格式：[{{"icon": "emoji", "text": "提示文本"}}]"""

    try:
        llm = get_llm("qwen-turbo")
        response = llm.invoke(prompt)
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        suggestions = json.loads(raw)
        if isinstance(suggestions, list) and len(suggestions) >= 2:
            return suggestions[:3]
    except Exception:
        pass

    return DEFAULT_SUGGESTIONS


@app.get("/search")
def search_messages(q: str = "", db: Session = Depends(get_db)):
    if not q or len(q) < 2:
        return []
    msgs = db.query(Message).filter(
        Message.content.ilike(f"%{q}%"),
        Message.conversation_id.in_(
            db.query(Conversation.id).filter(Conversation.user_id == USER_ID)
        ),
    ).order_by(Message.created_at.desc()).limit(20).all()

    conv_ids = set(m.conversation_id for m in msgs)
    conv_map = {}
    for cid in conv_ids:
        conv = db.query(Conversation).filter(Conversation.id == cid).first()
        if conv:
            conv_map[cid] = conv.title

    return [
        {
            "conversation_id": m.conversation_id,
            "conversation_title": conv_map.get(m.conversation_id, "未知"),
            "role": m.role,
            "content": m.content[:200],
            "created_at": m.created_at.isoformat(),
        }
        for m in msgs
    ]


# ---------- 对话管理接口 ----------

@app.get("/conversations")
def list_conversations(request: Request, db: Session = Depends(get_db)):
    """获取当前设备的所有对话列表"""
    ctx = get_device_context(db, request)
    convs = db.query(Conversation).filter(Conversation.user_id == USER_ID, Conversation.device_id == ctx.device_id).order_by(Conversation.created_at.desc()).all()
    return [
        {"id": c.id, "title": c.title, "created_at": c.created_at.isoformat(), "pinned": c.pinned or False}
        for c in convs
    ]


@app.post("/conversations")
def create_conversation(req: NewConversationRequest, request: Request, db: Session = Depends(get_db)):
    """新建对话"""
    ctx = get_device_context(db, request)
    conv = Conversation(title=req.title or "新对话", user_id=USER_ID, device_id=ctx.device_id)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return {"id": conv.id, "title": conv.title}


@app.delete("/conversations/{conv_id}")
def delete_conversation(conv_id: int, request: Request, db: Session = Depends(get_db)):
    """删除对话及其所有消息"""
    ctx = get_device_context(db, request)
    conv = db.query(Conversation).filter(Conversation.id == conv_id, Conversation.user_id == USER_ID, Conversation.device_id == ctx.device_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    db.delete(conv)
    db.commit()
    return {"ok": True}


@app.patch("/conversations/{conv_id}")
def update_conversation(conv_id: int, req: UpdateConversationRequest, request: Request, db: Session = Depends(get_db)):
    """更新对话标题或置顶状态"""
    ctx = get_device_context(db, request)
    conv = db.query(Conversation).filter(Conversation.id == conv_id, Conversation.user_id == USER_ID, Conversation.device_id == ctx.device_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    if req.title is not None:
        conv.title = req.title
    if req.pinned is not None:
        conv.pinned = req.pinned
    db.commit()
    db.refresh(conv)
    return {"id": conv.id, "title": conv.title, "pinned": conv.pinned or False}


@app.get("/conversations/{conv_id}/messages")
def get_messages(conv_id: int, request: Request, db: Session = Depends(get_db)):
    """获取某个对话的所有消息"""
    ctx = get_device_context(db, request)
    conv = db.query(Conversation).filter(Conversation.id == conv_id, Conversation.user_id == USER_ID, Conversation.device_id == ctx.device_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    msgs = db.query(Message).filter(Message.conversation_id == conv_id).order_by(Message.created_at).all()
    return [{"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at.isoformat()} for m in msgs]


class BranchRequest(BaseModel):
    from_message_index: int


@app.post("/conversations/{conv_id}/branch")
def branch_conversation(conv_id: int, req: BranchRequest, request: Request, db: Session = Depends(get_db)):
    """从某条消息分叉出新对话"""
    ctx = get_device_context(db, request)
    conv = db.query(Conversation).filter(Conversation.id == conv_id, Conversation.user_id == USER_ID, Conversation.device_id == ctx.device_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    msgs = db.query(Message).filter(Message.conversation_id == conv_id).order_by(Message.created_at).all()
    if req.from_message_index < 0 or req.from_message_index >= len(msgs):
        raise HTTPException(status_code=400, detail="消息索引无效")

    new_conv = Conversation(title=conv.title + " (分支)", user_id=USER_ID, device_id=ctx.device_id)
    db.add(new_conv)
    db.commit()
    db.refresh(new_conv)

    for m in msgs[:req.from_message_index]:
        db.add(Message(role=m.role, content=m.content, conversation_id=new_conv.id))
    db.commit()

    return {"id": new_conv.id, "title": new_conv.title}




@app.get("/devices")
def list_devices(db: Session = Depends(get_db)):
    """列出所有已知设备"""
    ctx = get_device_context(db, request)
    """从某条消息分叉出新对话"""
    conv = db.query(Conversation).filter(Conversation.id == conv_id, Conversation.user_id == USER_ID, Conversation.device_id == ctx.device_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    msgs = db.query(Message).filter(Message.conversation_id == conv_id).order_by(Message.created_at).all()
    if req.from_message_index < 0 or req.from_message_index >= len(msgs):
        raise HTTPException(status_code=400, detail="消息索引无效")

    # 创建新对话
    new_conv = Conversation(title=conv.title + " (分支)", user_id=USER_ID, device_id=ctx.device_id)
    db.add(new_conv)
    db.commit()
    db.refresh(new_conv)

    # 复制 from_message_index 之前的消息
    for m in msgs[:req.from_message_index]:
        db.add(Message(role=m.role, content=m.content, conversation_id=new_conv.id))
    db.commit()

    return {"id": new_conv.id, "title": new_conv.title}




# ---------- 文件下载 ----------

@app.get("/files/{filename}")
def download_file(filename: str):
    """提供生成的文件下载"""
    from fastapi.responses import FileResponse
    import os as _os
    files_dir = _os.environ.get("FILES_DIR", "/data/files")
    if not _os.path.isabs(files_dir):
        files_dir = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), files_dir)
    _os.makedirs(files_dir, exist_ok=True)
    filepath = _os.path.join(files_dir, filename)
    if not _os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(filepath, filename=filename)


# 确保文件目录存在
import os as _os
_files_dir = _os.environ.get("FILES_DIR", "/data/files")
if not _os.path.isabs(_files_dir):
    _files_dir = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), _files_dir)
_os.makedirs(_files_dir, exist_ok=True)

# ---------- 聊天接口 ----------

def _sse(event: dict) -> str:
    """把 dict 编码成 SSE data 行"""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _build_messages(history, user_id=None, db=None, query=None, device_ctx=None):
    """从数据库历史记录构建 LangChain 消息列表，注入用户记忆"""
    system_content = SYSTEM_PROMPT

    # 注入设备信息
    if device_ctx:
        device_summary = device_ctx.summary_for_prompt
        if device_summary:
            system_content += f"\n\n[当前设备信息]\n{device_summary}\n注意：自然地利用这个信息，如果用户问你在什么设备上，你可以直接告诉他。"

    if user_id and db:
        # 注入记忆
        mems = db.query(Memory).filter(Memory.user_id == user_id).order_by(Memory.updated_at.desc()).limit(20).all()
        if mems:
            mem_text = "\n\n【关于用户的记忆】\n" + "\n".join(f"- [{m.category}] {m.content}" for m in mems)
            system_content += mem_text

    messages = [SystemMessage(content=system_content)]
    for m in history:
        if m.role == "user":
            messages.append(HumanMessage(content=m.content))
        else:
            messages.append(AIMessage(content=m.content))
    return messages


@app.post("/chat/{conv_id}")
async def chat(
    request: Request,
    conv_id: int,
    message: str = Form(...),
    model: str = Form("qwen-max"),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    """在指定对话中聊天，支持文件上传，SSE 流式返回"""
    ctx = get_device_context(db, request)
    conv = db.query(Conversation).filter(Conversation.id == conv_id, Conversation.user_id == USER_ID, Conversation.device_id == ctx.device_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    # 处理文件
    file_context = ""
    user_display = message
    use_vision = False
    image_data_url = ""

    if file and file.filename:
        file_bytes = await file.read()
        filename = file.filename

        if is_image(filename):
            image_data_url = image_to_base64(file_bytes, filename)
            use_vision = True
            user_display = f"{message}（附图片: {filename}）"

        elif is_pdf(filename) or is_docx(filename) or is_xlsx(filename):
            text = extract_text(file_bytes, filename)
            if text:
                file_context = f"\n\n[用户上传了文件 {filename}，内容如下：]\n{text}"
                user_display = f"{message}（附文件: {filename}）"

    # 存用户消息
    db.add(Message(role="user", content=user_display, conversation_id=conv_id))
    db.commit()

    # 构建消息列表
    history = db.query(Message).filter(
        Message.conversation_id == conv_id
    ).order_by(Message.created_at).all()
    messages = _build_messages(history, user_id=USER_ID, db=db, query=message, device_ctx=ctx)

    # 如果有文件上下文，追加到最后一条 HumanMessage
    if file_context and messages and isinstance(messages[-1], HumanMessage):
        messages[-1] = HumanMessage(content=messages[-1].content + file_context)

    # 路径 1：图片理解 → 视觉模型（不走 Agent）
    if use_vision and image_data_url:
        async def stream_vision():
            ai_content = ""
            try:
                vl_model = get_llm("qwen-vl-max")
                vl_messages = [SystemMessage(content=SYSTEM_PROMPT)]
                vl_messages.append(HumanMessage(content=[
                    {"type": "text", "text": message},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ]))
                async for chunk in vl_model.astream(vl_messages):
                    if chunk.content:
                        ai_content += chunk.content
                        yield _sse({"type": "token", "content": chunk.content})
            except Exception as e:
                err_msg = f"视觉模型调用失败: {e}"
                yield _sse({"type": "token", "content": err_msg})
                ai_content = err_msg
            db.add(Message(role="assistant", content=ai_content, conversation_id=conv_id))
            db.commit()
            await extract_memories(message, ai_content, USER_ID)
            yield _sse({"type": "done"})

        return StreamingResponse(stream_vision(), media_type="text/event-stream")

    # 路径 2：DeepAgent（带工具调用）（带工具调用）
    agent = create_agent(model)

    if agent:
        async def stream_agent():
            ai_content = ""
            try:
                async for event in agent.astream(
                    {"messages": messages},
                    stream_mode="messages",
                ):
                    chunk, metadata = event
                    chunk_type = getattr(chunk, "type", "")

                    # Tool 结束（ToolMessage type 可能是 "tool" 或 "ToolMessage"）
                    if chunk_type in ("tool", "ToolMessage") or isinstance(chunk, ToolMessage):
                        preview = str(chunk.content)[:100] if chunk.content else ""
                        tool_name = getattr(chunk, "name", "unknown")
                        yield _sse({"type": "tool_end", "tool": tool_name, "result_preview": preview})

                    # AI 文本输出（非工具调用 chunk）
                    elif chunk_type in ("AIMessageChunk",) or hasattr(chunk, "tool_calls"):
                        if hasattr(chunk, "tool_calls") and chunk.tool_calls:
                            for tc in chunk.tool_calls:
                                yield _sse({"type": "tool_start", "tool": tc["name"], "args": tc["args"]})
                        if chunk.content:
                            ai_content += chunk.content
                            yield _sse({"type": "token", "content": chunk.content})
            except Exception as e:
                err_msg = f"Agent 调用出错: {e}"
                if not ai_content:
                    ai_content = err_msg
                    yield _sse({"type": "token", "content": err_msg})

            db.add(Message(role="assistant", content=ai_content, conversation_id=conv_id))
            db.commit()
            await extract_memories(message, ai_content, USER_ID)
            yield _sse({"type": "done"})

        return StreamingResponse(stream_agent(), media_type="text/event-stream")

    # 路径 3：简单聊天（模型不支持工具调用时的兜底）
    else:
        async def stream_simple():
            ai_content = ""
            try:
                llm = get_llm(model)
                async for chunk in llm.astream(messages):
                    if chunk.content:
                        ai_content += chunk.content
                        yield _sse({"type": "token", "content": chunk.content})
            except Exception as e:
                err_msg = f"模型调用出错: {e}"
                if not ai_content:
                    ai_content = err_msg
                    yield _sse({"type": "token", "content": err_msg})
            db.add(Message(role="assistant", content=ai_content, conversation_id=conv_id))
            db.commit()
            await extract_memories(message, ai_content, USER_ID)
            yield _sse({"type": "done"})

        return StreamingResponse(stream_simple(), media_type="text/event-stream")


# ---------- 记忆管理接口 ----------

@app.get("/profile")
def get_profile(db: Session = Depends(get_db)):
    """获取用户画像（从记忆中聚合）"""
    mems = db.query(Memory).filter(Memory.user_id == USER_ID).order_by(Memory.updated_at.desc()).all()
    profile = {"profile": [], "preference": [], "knowledge": [], "context": []}
    for m in mems:
        cat = m.category if m.category in profile else "context"
        profile[cat].append(m.content)
    return profile


@app.get("/memories")
def list_memories(db: Session = Depends(get_db)):
    """获取当前用户的所有记忆"""
    mems = db.query(Memory).filter(Memory.user_id == USER_ID).order_by(Memory.updated_at.desc()).all()
    return [{"id": m.id, "category": m.category, "content": m.content, "created_at": m.created_at.isoformat()} for m in mems]


@app.delete("/memories/{mem_id}")
def delete_memory(mem_id: int, db: Session = Depends(get_db)):
    """删除某条记忆"""
    mem = db.query(Memory).filter(Memory.id == mem_id, Memory.user_id == USER_ID).first()
    if not mem:
        raise HTTPException(status_code=404, detail="记忆不存在")
    db.delete(mem)
    db.commit()
    return {"ok": True}


# ---------- 定时任务接口 ----------

class NewTaskRequest(BaseModel):
    name: str
    prompt: str
    cron: str  # e.g. "0 8 * * *" = 每天8点


@app.get("/scheduled-tasks")
def list_tasks(db: Session = Depends(get_db)):
    """获取所有定时任务"""
    tasks = db.query(ScheduledTask).filter(ScheduledTask.user_id == USER_ID).order_by(ScheduledTask.created_at.desc()).all()
    return [{"id": t.id, "name": t.name, "prompt": t.prompt, "cron": t.cron, "enabled": t.enabled} for t in tasks]


@app.post("/scheduled-tasks")
def create_task(req: NewTaskRequest, db: Session = Depends(get_db)):
    """创建定时任务"""
    task = ScheduledTask(user_id=USER_ID, name=req.name, prompt=req.prompt, cron=req.cron)
    db.add(task)
    db.commit()
    db.refresh(task)
    return {"id": task.id, "name": task.name, "prompt": task.prompt, "cron": task.cron, "enabled": task.enabled}


@app.patch("/scheduled-tasks/{task_id}")
def toggle_task(task_id: int, db: Session = Depends(get_db)):
    """切换定时任务开关"""
    task = db.query(ScheduledTask).filter(ScheduledTask.id == task_id, ScheduledTask.user_id == USER_ID).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    task.enabled = not task.enabled
    db.commit()
    return {"id": task.id, "enabled": task.enabled}


@app.delete("/scheduled-tasks/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db)):
    """删除定时任务"""
    task = db.query(ScheduledTask).filter(ScheduledTask.id == task_id, ScheduledTask.user_id == USER_ID).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    db.delete(task)
    db.commit()
    return {"ok": True}


@app.post("/stt")
async def speech_to_text(audio: UploadFile = File(...)):
    """语音转文字 — 使用 SiliconFlow SenseVoice（多语言）"""
    import logging, tempfile, subprocess
    logger = logging.getLogger("stt")

    logger.info(f"STT called. SILICONFLOW_API_KEY set: {bool(SILICONFLOW_API_KEY)}")
    if not SILICONFLOW_API_KEY:
        raise HTTPException(status_code=500, detail="未配置 SILICONFLOW_API_KEY")

    audio_bytes = await audio.read()
    if len(audio_bytes) < 500:
        return {"text": "", "error": "音频太短"}

    orig_name = audio.filename or "audio.webm"
    suffix = orig_name.rsplit(".", 1)[-1] if "." in orig_name else "webm"

    audio_path = None
    wav_path = None
    final_path = None
    final_name = orig_name
    final_mime = audio.content_type or "audio/webm"

    try:
        with tempfile.NamedTemporaryFile(suffix=f".{suffix}", delete=False) as tmp:
            tmp.write(audio_bytes)
            audio_path = tmp.name

        wav_path = audio_path.rsplit(".", 1)[0] + ".wav"
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", audio_path, "-ar", "16000", "-ac", "1", wav_path],
            capture_output=True, timeout=10,
        )
        if proc.returncode == 0 and os.path.exists(wav_path):
            final_path = wav_path
            final_name = "audio.wav"
            final_mime = "audio/wav"
            logger.info(f"STT: converted {suffix} -> wav ({os.path.getsize(wav_path)} bytes)")
        else:
            final_path = audio_path
            logger.info(f"STT: ffmpeg unavailable, sending raw {suffix}")
    except Exception as e:
        final_path = audio_path
        logger.warning(f"STT: ffmpeg failed: {e}")

    if not final_path or not os.path.exists(final_path):
        raise HTTPException(status_code=500, detail="音频临时文件写入失败")

    try:
        async with httpx.AsyncClient(proxy=None, timeout=httpx.Timeout(30.0)) as client:
            with open(final_path, "rb") as f:
                r = await client.post(
                    "https://api.siliconflow.cn/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {SILICONFLOW_API_KEY}"},
                    files={"file": (final_name, f, final_mime)},
                    data={"model": "FunAudioLLM/SenseVoiceSmall"},
                )
            result = r.json()
            logger.info(f"STT SiliconFlow response: status={r.status_code} body={str(result)[:300]}")

            text = result.get("text", "")
            if not text:
                logger.warning("STT returned empty text")
            return {"text": text}
    except Exception as e:
        logger.error(f"STT error: {e}")
        raise HTTPException(status_code=500, detail=f"语音识别失败: {e}")
    finally:
        for p in [audio_path, wav_path]:
            if p and os.path.exists(p):
                try: os.unlink(p)
                except: pass


@app.on_event("startup")
def _on_startup():
    """启动时：刷新热梗缓存 + 启动后台定时刷新"""
    refresh_memes()
    start_background_refresh()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)

