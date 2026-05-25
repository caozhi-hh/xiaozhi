"""
工具注册 — Agent 可调用的工具

新增工具：
  1. 写一个 @tool 函数
  2. 加到 TOOLS 列表
  3. 完成，Agent 自动识别
"""
import json
import time
import urllib.request
import urllib.parse

import httpx
from langchain_core.tools import tool
from langchain_community.tools import DuckDuckGoSearchRun
from dotenv import dotenv_values
from pathlib import Path


_search = DuckDuckGoSearchRun()

# 从 .env 读取 API Keys
_env = dotenv_values(Path(__file__).resolve().parent / ".env")
DASHSCOPE_API_KEY = None
SILICONFLOW_API_KEY = None
for _v in _env.values():
    if "dashscope" in _v.lower():
        DASHSCOPE_API_KEY = _v.split("|")[1]
        break
SILICONFLOW_API_KEY = _env.get("SILICONFLOW_API_KEY")


@tool
def web_search(query: str) -> str:
    """搜索互联网获取最新信息。当用户问时事、新闻、或其他需要最新数据的问题时使用。"""
    return _search.invoke(query)


@tool
def get_weather(city: str) -> str:
    """查询指定城市的当前天气。当用户问天气、温度、是否下雨等问题时使用。"""
    try:
        url = f"https://wttr.in/{urllib.parse.quote(city)}?format=j1"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
        resp = urllib.request.urlopen(req, timeout=8)
        data = json.loads(resp.read())
        c = data["current_condition"][0]
        return (
            f"城市: {city}\n"
            f"温度: {c['temp_C']}°C (体感 {c['FeelsLikeC']}°C)\n"
            f"天气: {c['weatherDesc'][0]['value']}\n"
            f"湿度: {c['humidity']}%\n"
            f"风速: {c['windspeedKmph']} km/h"
        )
    except Exception as e:
        return f"查询天气失败: {e}"


@tool
def translate(text: str, target_language: str = "中文") -> str:
    """翻译文本到指定语言。当用户要求翻译时使用。"""
    return f"[翻译请求] 请将以下内容翻译为{target_language}：\n{text}"


@tool
def generate_image(prompt: str) -> str:
    """根据文字描述生成图片。只要用户提到'画''画一个''生成图片''帮我画''给我画'等任何图片相关请求，就必须调用此工具。参数 prompt 是英文详细描述。"""
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


# 工具注册表 — Agent 会读取这个列表来决定可用的工具
TOOLS = [web_search, get_weather, translate, generate_image]
