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

WECOM_CORP_ID = os.environ.get("WECOM_CORP_ID", "")
WECOM_AGENT_ID = os.environ.get("WECOM_AGENT_ID", "")
WECOM_SECRET = os.environ.get("WECOM_SECRET", "")
WECOM_TOKEN = os.environ.get("WECOM_TOKEN", "")
WECOM_ENCODING_AES_KEY = os.environ.get("WECOM_ENCODING_AES_KEY", "")

WECOM_WEBHOOK_URL = os.environ.get("WECOM_WEBHOOK_URL", "")
