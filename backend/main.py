"""
小智 AI - 后端入口

路由结构：
  GET  /                    健康检查
  GET  /models              获取可用模型列表
  POST /auth/register       注册
  POST /auth/login          登录
  GET  /auth/me             获取当前用户信息
  GET  /conversations       获取当前用户的所有对话
  POST /conversations       新建对话
  DELETE /conversations/{id} 删除对话
  POST /chat/{conv_id}      在指定对话中聊天（SSE 流式）
"""
import json
import asyncio
import httpx

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from database import get_db, engine, Base
from models import User, Conversation, Message
from auth import (
    hash_password, verify_password, create_token, get_current_user,
)
from llm import get_llm, get_available_models, SYSTEM_PROMPT
from agent import create_agent
from file_handler import is_image, is_pdf, extract_pdf_text, image_to_base64
from tools import SILICONFLOW_API_KEY

# 创建所有数据库表（如果不存在）
Base.metadata.create_all(bind=engine)

app = FastAPI(title="小智 AI", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- 请求格式 ----------

class RegisterRequest(BaseModel):
    username: str
    password: str

class NewConversationRequest(BaseModel):
    title: str | None = "新对话"

class ChatRequest(BaseModel):
    message: str
    model: str = "glm-4-flash"  # 用户选择的模型，默认 GLM


# ---------- 基础接口 ----------

@app.get("/")
def root():
    """健康检查"""
    return {"status": "ok", "message": "小智 AI 后端运行中"}


@app.get("/models")
def models_list():
    """返回可用的 AI 模型列表"""
    return get_available_models()


# ---------- 认证接口 ----------

@app.post("/auth/register")
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """注册新用户"""
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    user = User(username=req.username, hashed_password=hash_password(req.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"token": create_token(user.id, user.username), "username": user.username}


@app.post("/auth/login")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """登录（支持 Swagger docs 的 Authorize 按钮）"""
    user = db.query(User).filter(User.username == form.username).first()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return {"access_token": create_token(user.id, user.username), "token_type": "bearer"}


@app.get("/auth/me")
def me(current_user: User = Depends(get_current_user)):
    """获取当前登录用户信息"""
    return {"id": current_user.id, "username": current_user.username}


# ---------- 对话管理接口 ----------

@app.get("/conversations")
def list_conversations(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """获取当前用户的所有对话列表"""
    convs = db.query(Conversation).filter(Conversation.user_id == current_user.id).order_by(Conversation.created_at.desc()).all()
    return [
        {"id": c.id, "title": c.title, "created_at": c.created_at.isoformat()}
        for c in convs
    ]


@app.post("/conversations")
def create_conversation(req: NewConversationRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """新建对话"""
    conv = Conversation(title=req.title or "新对话", user_id=current_user.id)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return {"id": conv.id, "title": conv.title}


@app.delete("/conversations/{conv_id}")
def delete_conversation(conv_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """删除对话及其所有消息"""
    conv = db.query(Conversation).filter(Conversation.id == conv_id, Conversation.user_id == current_user.id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    db.delete(conv)
    db.commit()
    return {"ok": True}


@app.get("/conversations/{conv_id}/messages")
def get_messages(conv_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """获取某个对话的所有消息"""
    conv = db.query(Conversation).filter(Conversation.id == conv_id, Conversation.user_id == current_user.id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    msgs = db.query(Message).filter(Message.conversation_id == conv_id).order_by(Message.created_at).all()
    return [{"id": m.id, "role": m.role, "content": m.content} for m in msgs]


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


def _build_messages(history):
    """从数据库历史记录构建 LangChain 消息列表"""
    messages = [SystemMessage(content=SYSTEM_PROMPT)]
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
    model: str = Form("glm-4-flash"),
    file: UploadFile | None = File(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """在指定对话中聊天，支持文件上传，SSE 流式返回"""
    conv = db.query(Conversation).filter(
        Conversation.id == conv_id, Conversation.user_id == current_user.id
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
        print(f"[DEBUG] 收到文件: {filename}, 大小: {len(file_bytes)} bytes, 是图片: {is_image(filename)}")

        if is_pdf(filename):
            text = extract_pdf_text(file_bytes)
            if text:
                file_context = f"\n\n[用户上传了文件 {filename}，内容如下：]\n{text}"
                user_display = f"{message}（附文件: {filename}）"

        elif is_image(filename):
            image_data_url = image_to_base64(file_bytes, filename)
            use_vision = True
            user_display = f"{message}（附图片: {filename}）"
            print(f"[DEBUG] 图片处理完成, use_vision={use_vision}, base64长度: {len(image_data_url)}")
    else:
        print(f"[DEBUG] 未收到文件: file={file}, filename={file.filename if file else 'N/A'}")

    # 存用户消息
    db.add(Message(role="user", content=user_display, conversation_id=conv_id))
    db.commit()

    # 构建消息列表
    history = db.query(Message).filter(
        Message.conversation_id == conv_id
    ).order_by(Message.created_at).all()
    messages = _build_messages(history)

    # 如果有文件上下文，追加到最后一条 HumanMessage
    if file_context and messages and isinstance(messages[-1], HumanMessage):
        messages[-1] = HumanMessage(content=messages[-1].content + file_context)

    # 图片 → 用视觉模型直接回答（不走 Agent）
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
            yield _sse({"type": "done"})

        return StreamingResponse(stream_vision(), media_type="text/event-stream")

    # 图片生成 -> SiliconFlow FLUX.1-schnell（同步，~2-3秒）
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

    # 走 Agent 或普通聊天
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
                print(f"[ERROR] {err_msg}")
                if not ai_content:
                    ai_content = err_msg
                    yield _sse({"type": "token", "content": err_msg})

            db.add(Message(role="assistant", content=ai_content, conversation_id=conv_id))
            db.commit()
            yield _sse({"type": "done"})

        return StreamingResponse(stream_agent(), media_type="text/event-stream")

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
                print(f"[ERROR] {err_msg}")
                if not ai_content:
                    ai_content = err_msg
                    yield _sse({"type": "token", "content": err_msg})
            db.add(Message(role="assistant", content=ai_content, conversation_id=conv_id))
            db.commit()
            yield _sse({"type": "done"})

        return StreamingResponse(stream_simple(), media_type="text/event-stream")
