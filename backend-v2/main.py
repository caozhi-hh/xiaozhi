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
import asyncio
import httpx

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from database import get_db, engine, Base
from models import Conversation, Message, Memory, Document, ScheduledTask
from llm import get_llm, get_available_models
from agent import create_agent
from agent.prompt import SYSTEM_PROMPT
from file_handler import is_image, is_pdf, is_docx, is_xlsx, extract_text, image_to_base64
from config import SILICONFLOW_API_KEY
from memory import extract_memories
from rag import ingest_document, search_knowledge, delete_document_vectors

# 创建所有数据库表（如果不存在）
Base.metadata.create_all(bind=engine)

app = FastAPI(title="小智 AI", version="0.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Render 使用 PORT 环境变量
PORT = int(os.environ.get("PORT", 8001))

# 自用单用户，固定 user_id=1
USER_ID = 1


# ---------- 请求格式 ----------

class NewConversationRequest(BaseModel):
    title: str | None = "新对话"


class UpdateConversationRequest(BaseModel):
    title: str | None = None
    pinned: bool | None = None


# ---------- 基础接口 ----------

@app.get("/")
def root():
    return {"status": "ok", "message": "小智 AI 后端运行中"}


@app.get("/models")
def models_list():
    return get_available_models()


# ---------- 对话管理接口 ----------

@app.get("/conversations")
def list_conversations(db: Session = Depends(get_db)):
    """获取当前用户的所有对话列表"""
    convs = db.query(Conversation).filter(Conversation.user_id == USER_ID).order_by(Conversation.created_at.desc()).all()
    return [
        {"id": c.id, "title": c.title, "created_at": c.created_at.isoformat(), "pinned": c.pinned or False}
        for c in convs
    ]


@app.post("/conversations")
def create_conversation(req: NewConversationRequest, db: Session = Depends(get_db)):
    """新建对话"""
    conv = Conversation(title=req.title or "新对话", user_id=USER_ID)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return {"id": conv.id, "title": conv.title}


@app.delete("/conversations/{conv_id}")
def delete_conversation(conv_id: int, db: Session = Depends(get_db)):
    """删除对话及其所有消息"""
    conv = db.query(Conversation).filter(Conversation.id == conv_id, Conversation.user_id == USER_ID).first()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    db.delete(conv)
    db.commit()
    return {"ok": True}


@app.patch("/conversations/{conv_id}")
def update_conversation(conv_id: int, req: UpdateConversationRequest, db: Session = Depends(get_db)):
    """更新对话标题或置顶状态"""
    conv = db.query(Conversation).filter(Conversation.id == conv_id, Conversation.user_id == USER_ID).first()
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
def get_messages(conv_id: int, db: Session = Depends(get_db)):
    """获取某个对话的所有消息"""
    conv = db.query(Conversation).filter(Conversation.id == conv_id, Conversation.user_id == USER_ID).first()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    msgs = db.query(Message).filter(Message.conversation_id == conv_id).order_by(Message.created_at).all()
    return [{"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at.isoformat()} for m in msgs]


class BranchRequest(BaseModel):
    from_message_index: int


@app.post("/conversations/{conv_id}/branch")
def branch_conversation(conv_id: int, req: BranchRequest, db: Session = Depends(get_db)):
    """从某条消息分叉出新对话"""
    conv = db.query(Conversation).filter(Conversation.id == conv_id, Conversation.user_id == USER_ID).first()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    msgs = db.query(Message).filter(Message.conversation_id == conv_id).order_by(Message.created_at).all()
    if req.from_message_index < 0 or req.from_message_index >= len(msgs):
        raise HTTPException(status_code=400, detail="消息索引无效")

    # 创建新对话
    new_conv = Conversation(title=conv.title + " (分支)", user_id=USER_ID)
    db.add(new_conv)
    db.commit()
    db.refresh(new_conv)

    # 复制 from_message_index 之前的消息
    for m in msgs[:req.from_message_index]:
        db.add(Message(role=m.role, content=m.content, conversation_id=new_conv.id))
    db.commit()

    return {"id": new_conv.id, "title": new_conv.title}


# ---------- 聊天接口 ----------

_IMAGE_GEN_KEYWORDS = [
    "画", "生成图片", "生成图", "创建图片", "制作图片",
    "generate image", "draw", "create image",
]


def _is_image_gen(text: str) -> bool:
    msg = text.lower().strip()
    return any(kw in msg for kw in _IMAGE_GEN_KEYWORDS)


def _sse(event: dict) -> str:
    """把 dict 编码成 SSE data 行"""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _build_messages(history, user_id=None, db=None, query=None):
    """从数据库历史记录构建 LangChain 消息列表，注入用户记忆和知识库"""
    system_content = SYSTEM_PROMPT

    if user_id and db:
        # 注入记忆
        mems = db.query(Memory).filter(Memory.user_id == user_id).order_by(Memory.updated_at.desc()).limit(20).all()
        if mems:
            mem_text = "\n\n【关于用户的记忆】\n" + "\n".join(f"- [{m.category}] {m.content}" for m in mems)
            system_content += mem_text

        # 注入知识库检索
        if query:
            docs = db.query(Document).filter(Document.user_id == user_id).count()
            if docs > 0:
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


@app.post("/chat/{conv_id}")
async def chat(
    conv_id: int,
    message: str = Form(...),
    model: str = Form("qwen-max"),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    """在指定对话中聊天，支持文件上传，SSE 流式返回"""
    conv = db.query(Conversation).filter(
        Conversation.id == conv_id, Conversation.user_id == USER_ID
    ).first()
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
    messages = _build_messages(history, user_id=USER_ID, db=db, query=message)

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

    # 路径 2：图片生成 → SiliconFlow Kolors（同步，~5秒）
    if SILICONFLOW_API_KEY and _is_image_gen(message):
        async def stream_image_gen():
            ai_content = ""
            try:
                yield _sse({"type": "image_generating"})

                resp = httpx.post(
                    "https://api.siliconflow.cn/v1/images/generations",
                    headers={
                        "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "Kwai-Kolors/Kolors",
                        "prompt": message[:500],
                        "image_size": "1024x1024",
                        "num_inference_steps": 25,
                    },
                    timeout=60,
                )
                data = resp.json()

                images = data.get("images", [])
                if images and images[0].get("url"):
                    img_url = images[0]["url"]
                    yield _sse({"type": "image_done", "url": img_url})
                    ai_content = f"![generated image]({img_url})"
                else:
                    err = f"图片生成失败：{data.get('message', data.get('error', {}).get('message', 'unknown error'))}"
                    yield _sse({"type": "token", "content": err})
                    ai_content = err
            except Exception as e:
                err = f"图片生成失败：{e}"
                yield _sse({"type": "token", "content": err})
                ai_content = err

            db.add(Message(role="assistant", content=ai_content, conversation_id=conv_id))
            db.commit()
            yield _sse({"type": "done"})

        return StreamingResponse(stream_image_gen(), media_type="text/event-stream")

    # 路径 3：DeepAgent（带工具调用）
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

                    if hasattr(chunk, "type") and chunk.type == "AIMessageChunk" and chunk.content:
                        ai_content += chunk.content
                        yield _sse({"type": "token", "content": chunk.content})

                    elif hasattr(chunk, "tool_calls") and chunk.tool_calls:
                        for tc in chunk.tool_calls:
                            yield _sse({"type": "tool_start", "tool": tc["name"], "args": tc["args"]})

                    elif hasattr(chunk, "type") and chunk.type == "ToolMessage":
                        preview = str(chunk.content)[:100] if chunk.content else ""
                        yield _sse({"type": "tool_end", "tool": chunk.name, "result_preview": preview})
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

    # 路径 4：简单聊天（模型不支持工具调用时的兜底）
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


# ---------- 知识库接口 ----------

@app.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """上传文档到知识库"""
    filename = file.filename or "unknown.txt"
    file_bytes = await file.read()

    # 提取文字
    text = extract_text(file_bytes, filename)
    if not text:
        raise HTTPException(status_code=400, detail="仅支持 PDF、Word、Excel、TXT、MD 格式")

    if not text.strip():
        raise HTTPException(status_code=400, detail="文档内容为空")

    # 存元数据
    file_type = filename.rsplit(".", 1)[-1].lower()
    doc = Document(user_id=USER_ID, filename=filename, file_type=file_type)
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # 向量化
    chunk_count = ingest_document(USER_ID, doc.id, filename, text)
    doc.chunk_count = chunk_count
    db.commit()

    return {"id": doc.id, "filename": filename, "chunks": chunk_count}


@app.get("/documents")
def list_documents(db: Session = Depends(get_db)):
    """获取用户的知识库文档列表"""
    docs = db.query(Document).filter(Document.user_id == USER_ID).order_by(Document.created_at.desc()).all()
    return [{"id": d.id, "filename": d.filename, "file_type": d.file_type, "chunks": d.chunk_count, "created_at": d.created_at.isoformat()} for d in docs]


@app.delete("/documents/{doc_id}")
def delete_document(doc_id: int, db: Session = Depends(get_db)):
    """删除知识库文档"""
    doc = db.query(Document).filter(Document.id == doc_id, Document.user_id == USER_ID).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    delete_document_vectors(USER_ID, doc.id)
    db.delete(doc)
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
    except Exception:
        final_path = audio_path
        logger.info(f"STT: ffmpeg failed, sending raw {suffix}")

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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)

