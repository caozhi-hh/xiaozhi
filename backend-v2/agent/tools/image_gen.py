"""图片生成工具 — 使用 SiliconFlow Kolors API"""
import logging
import httpx
from config import SILICONFLOW_API_KEY
from langchain_core.tools import tool

logger = logging.getLogger("image_gen")

API_URL = "https://api.siliconflow.cn/v1/images/generations"
MODEL = "Kwai-Kolors/Kolors"


@tool
def generate_image(prompt: str, size: str = "1024x1024") -> str:
    """根据文字描述生成图片。当用户要求画图、生成图片、AI绘图时使用。

    Args:
        prompt: 图片描述（中文或英文均可，描述越详细效果越好）
        size: 图片尺寸，可选 1024x1024、768x1024、1024x768，默认 1024x1024
    """
    if not SILICONFLOW_API_KEY:
        return "图片生成功能未配置（缺少 SILICONFLOW_API_KEY）"

    try:
        resp = httpx.post(
            API_URL,
            headers={
                "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "prompt": prompt[:500],
                "image_size": size,
                "num_inference_steps": 25,
            },
            timeout=60,
        )
        data = resp.json()
        images = data.get("images", [])
        if images and images[0].get("url"):
            img_url = images[0]["url"]
            return f"图片已生成！\n![{prompt}]({img_url})"
        return f"图片生成失败：{data.get('message', str(data))}"
    except Exception as e:
        logger.error(f"图片生成异常: {e}")
        return f"图片生成失败: {e}"
