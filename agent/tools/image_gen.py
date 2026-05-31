"""图片生成工具 — SiliconFlow Kolors"""
import httpx
from config import SILICONFLOW_API_KEY


def generate_image(prompt: str) -> str:
    """根据文字描述生成图片。只要用户提到'画''画一个''生成图片'等任何图片相关请求，就必须调用此工具。参数 prompt 是英文详细描述。"""
    if not SILICONFLOW_API_KEY:
        return "图片生成失败：未找到 SiliconFlow API Key"

    try:
        resp = httpx.post(
            "https://api.siliconflow.cn/v1/images/generations",
            headers={
                "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "Kwai-Kolors/Kolors",
                "prompt": prompt[:500],
                "image_size": "1024x1024",
                "num_inference_steps": 25,
            },
            timeout=60,
        )
        data = resp.json()
        images = data.get("images", [])
        if images and images[0].get("url"):
            img_url = images[0]["url"]
            return f"图片生成成功！\n![生成的图片]({img_url})\n图片链接: {img_url}"
        return f"图片生成失败：{data.get('message', str(data))}"
    except Exception as e:
        return f"图片生成失败：{e}"
