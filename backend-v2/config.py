"""
集中配置 — 从环境变量加载，.env 文件作为本地开发兜底
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

# 本地开发：从 .env 加载到环境变量（不覆盖已有的）
if ENV_FILE.exists():
    from dotenv import load_dotenv
    load_dotenv(ENV_FILE, override=False)

SILICONFLOW_API_KEY = os.environ.get("SILICONFLOW_API_KEY", "")
