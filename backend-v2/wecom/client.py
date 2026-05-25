"""
企业微信 API 客户端

封装 access_token 获取和消息发送。
- access_token 内存缓存，7200 秒有效期
- 超长消息自动拆分（企微单条限制 2048 字节）
"""
import logging
import time

import httpx

from config import WECOM_AGENT_ID, WECOM_CORP_ID, WECOM_SECRET

logger = logging.getLogger("wecom.client")

# access_token 缓存
_token_cache: dict = {"token": "", "expires_at": 0.0}


async def get_access_token() -> str:
    """获取企业微信 access_token，带内存缓存"""
    if _token_cache["token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["token"]

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
            params={"corpid": WECOM_CORP_ID, "corpsecret": WECOM_SECRET},
        )
        data = resp.json()

    if data.get("errcode", 0) != 0:
        logger.error("获取 access_token 失败: %s", data)
        raise RuntimeError(f"获取 access_token 失败: {data.get('errmsg', 'unknown')}")

    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + data.get("expires_in", 7200) - 200
    logger.info("access_token 刷新成功")
    return _token_cache["token"]


def split_message(text: str, max_bytes: int = 2048) -> list[str]:
    """按字节长度拆分消息，优先在换行符处断开"""
    chunks = []
    while text:
        cut = len(text)
        while len(text[:cut].encode("utf-8")) > max_bytes and cut > 0:
            cut -= 1
        if cut < len(text):
            nl = text.rfind("\n", 0, cut)
            if nl > cut // 2:
                cut = nl
        chunks.append(text[:cut])
        text = text[cut:]
    return chunks


async def send_text(user_id: str, content: str) -> dict:
    """发送文本消息"""
    token = await get_access_token()
    parts = split_message(content)
    results = []
    async with httpx.AsyncClient(timeout=10) as client:
        for i, part in enumerate(parts):
            resp = await client.post(
                f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}",
                json={
                    "touser": user_id,
                    "msgtype": "text",
                    "agentid": int(WECOM_AGENT_ID),
                    "text": {"content": part},
                },
            )
            result = resp.json()
            results.append(result)
            if result.get("errcode", 0) != 0:
                logger.error("发送消息失败 (part %d): %s", i + 1, result)
    return results[-1] if results else {"errcode": -1, "errmsg": "nothing sent"}


async def send_markdown(user_id: str, content: str) -> dict:
    """发送 Markdown 消息（注意：企微 markdown 消息不支持嵌套和复杂格式）"""
    token = await get_access_token()
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}",
            json={
                "touser": user_id,
                "msgtype": "markdown",
                "agentid": int(WECOM_AGENT_ID),
                "markdown": {"content": content[:2048]},
            },
        )
        result = resp.json()
        if result.get("errcode", 0) != 0:
            logger.error("发送 Markdown 消息失败: %s", result)
        return result
