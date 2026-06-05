"""图片生成工具 — 使用 SiliconFlow Kolors API，自动下载到本地持久化"""
import os
import logging
import hashlib
import httpx
from datetime import datetime
from config import SILICONFLOW_API_KEY
from langchain_core.tools import tool

logger = logging.getLogger("image_gen")

API_URL = "https://api.siliconflow.cn/v1/images/generations"
MODEL = "Kwai-Kolors/Kolors"

FILES_DIR = os.environ.get("FILES_DIR", "/data/files")
if not os.path.isabs(FILES_DIR):
    FILES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), FILES_DIR)

BACKEND_URL = os.environ.get(
    "NEXT_PUBLIC_API_URL",
    os.environ.get("BACKEND_URL", "https://powercz-xiaozhi.hf.space"),
)


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
        if not images:
            return f"图片生成失败：{data.get('message', str(data))}"

        img_url = images[0].get("url", "")
        if not img_url:
            return f"图片生成失败：未返回图片链接"

        # 下载图片到本地，防止临时链接过期
        local_path = _download_image(img_url, prompt)
        if local_path:
            local_url = f"{BACKEND_URL}/files/{local_path}"
            return f"图片已生成！\n![{prompt}]({local_url})"
        # 下载失败则回退到临时链接
        return f"图片已生成（临时链接，可能过期）！\n![{prompt}]({img_url})"

    except Exception as e:
        logger.error(f"图片生成异常: {e}")
        return f"图片生成失败: {e}"


def _download_image(url: str, prompt: str) -> str | None:
    """下载图片到本地 FILES_DIR，返回文件名"""
    try:
        os.makedirs(FILES_DIR, exist_ok=True)
        img_resp = httpx.get(url, timeout=30, follow_redirects=True)
        if img_resp.status_code != 200:
            logger.warning(f"下载图片失败: HTTP {img_resp.status_code}")
            return None

        # 用 prompt hash + 时间戳生成唯一文件名
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()[:8]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"img_{timestamp}_{prompt_hash}.png"
        filepath = os.path.join(FILES_DIR, filename)

        with open(filepath, "wb") as f:
            f.write(img_resp.content)

        logger.info(f"图片已下载到本地: {filename} ({len(img_resp.content)} bytes)")
        return filename

    except Exception as e:
        logger.warning(f"图片下载到本地失败: {e}")
        return None
