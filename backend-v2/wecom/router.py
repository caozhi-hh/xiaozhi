"""
企业微信回调路由

GET  /wecom/callback  → URL 验证（首次配置时）
POST /wecom/callback  → 接收用户消息

关键：企微要求 5 秒内返回响应，AI 处理放入后台任务。
"""
import asyncio
import logging
from functools import lru_cache

from fastapi import APIRouter, Query, Request, Response

from config import WECOM_CORP_ID, WECOM_ENCODING_AES_KEY, WECOM_TOKEN
from wecom.crypto import WeComCrypto, parse_encrypted_xml, parse_message_xml

logger = logging.getLogger("wecom.router")

router = APIRouter(prefix="/wecom", tags=["企业微信"])


@lru_cache
def _get_crypto() -> WeComCrypto:
    """延迟初始化加解密（环境变量可能后加载）"""
    return WeComCrypto(
        token=WECOM_TOKEN,
        encoding_aes_key=WECOM_ENCODING_AES_KEY,
        corp_id=WECOM_CORP_ID,
    )


def _wecom_configured() -> bool:
    return bool(WECOM_TOKEN and WECOM_ENCODING_AES_KEY and WECOM_CORP_ID)

# 已处理的 MsgId 集合（防止重复处理）
_processed_msgs: set[str] = set()
_MAX_PROCESSED = 200


@router.get("/callback")
def verify_url(
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
):
    """URL 验证 -- 企业微信后台配置回调时调用"""
    logger.info("====== 收到企微 URL 验证请求 ======")
    logger.info("msg_signature=%s, timestamp=%s, nonce=%s, echostr=%s",
                msg_signature, timestamp, nonce, echostr[:30] + "..." if len(echostr) > 30 else echostr)

    if not _wecom_configured():
        logger.error("企微未配置! TOKEN=%s, AES_KEY=%s, CORP_ID=%s",
                      bool(WECOM_TOKEN), bool(WECOM_ENCODING_AES_KEY), bool(WECOM_CORP_ID))
        return Response(content="wecom not configured", status_code=503)

    crypto = _get_crypto()
    if not crypto.verify_signature(msg_signature, timestamp, nonce, echostr):
        logger.warning("URL 验证签名失败")
        return Response(content="signature mismatch", status_code=403)

    try:
        plain = crypto.decrypt(echostr)
        logger.info("URL 验证成功! 解密结果: %s", plain)
        # 企微要求返回纯文本，不能有引号、BOM、换行
        return Response(content=plain, media_type="text/plain")
    except Exception as e:
        logger.error("URL 验证解密失败: %s", e, exc_info=True)
        return Response(content=f"decrypt error: {e}", status_code=500)


@router.post("/callback")
async def receive_message(
    request: Request,
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
):
    """接收企业微信消息"""
    logger.info("====== 收到企微 POST 消息 ======")
    body = await request.body()
    xml_body = body.decode("utf-8")
    logger.info("POST body: %s", xml_body[:200])

    if not _wecom_configured():
        logger.warning("企微未配置，忽略消息")
        return Response(content="success")

    try:
        crypto = _get_crypto()

        # 1. 提取加密内容
        encrypt = parse_encrypted_xml(xml_body)

        # 2. 验证签名
        if not crypto.verify_signature(msg_signature, timestamp, nonce, encrypt):
            logger.warning("消息签名验证失败")
            return Response(content="success")

        # 3. 解密消息（POST消息含CorpID，需要校验）
        plain_xml = crypto.decrypt(encrypt, verify_corp_id=True)
        msg = parse_message_xml(plain_xml)
        logger.info("收到企微消息: FromUser=%s, Content=%s", msg.get("FromUserName", ""), msg.get("Content", "")[:50])

        # 4. 去重
        msg_id = msg.get("MsgId", "")
        if msg_id and msg_id in _processed_msgs:
            return Response(content="success")
        if msg_id:
            _processed_msgs.add(msg_id)
            if len(_processed_msgs) > _MAX_PROCESSED:
                to_remove = list(_processed_msgs)[: _MAX_PROCESSED // 2]
                for mid in to_remove:
                    _processed_msgs.discard(mid)

        # 5. 只处理文本消息
        if msg.get("MsgType") != "text":
            asyncio.create_task(_send_unsupported(msg.get("FromUserName", "")))
            return Response(content="success")

        user_id = msg.get("FromUserName", "")
        content = msg.get("Content", "")

        if not content.strip():
            return Response(content="success")

        # 6. 立即返回 success，后台处理 AI 回复
        asyncio.create_task(_handle_and_reply(user_id, content))
        return Response(content="success")

    except Exception as e:
        logger.error("处理企微POST失败: %s", e, exc_info=True)
        return Response(content="success")


async def _handle_and_reply(user_id: str, content: str):
    """后台任务：处理消息并发送回复"""
    try:
        reply = await process_message(user_id, content)
        await send_text(user_id, reply)
        logger.info("企微回复已发送: user=%s, len=%d", user_id, len(reply))
    except Exception as e:
        logger.error("企微回复失败: %s", e, exc_info=True)
        try:
            await send_text(user_id, "抱歉，处理消息时出错了，请稍后再试。")
        except Exception:
            pass


async def _send_unsupported(user_id: str):
    """发送不支持的消息类型提示"""
    try:
        await send_text(user_id, "目前只支持文字消息哦，请直接发文字和我聊天。")
    except Exception:
        pass
