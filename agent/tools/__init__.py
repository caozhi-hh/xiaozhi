"""工具注册表 — 所有 Agent 可用的工具"""
from agent.tools.web_search import web_search
from agent.tools.weather import get_weather
from agent.tools.translate import translate
from agent.tools.image_gen import generate_image
from agent.tools.code_runner import run_code

ALL_TOOLS = [web_search, get_weather, translate, generate_image, run_code]
