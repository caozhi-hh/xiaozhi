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

WECOM_CORP_ID = os.environ.get("WECOM_CORP_ID", "ww134b86debdd9d61b")
WECOM_AGENT_ID = os.environ.get("WECOM_AGENT_ID", "1000002")
WECOM_SECRET = os.environ.get("WECOM_SECRET", "FeKUBOVltZTO9DsaVFPMx7pUL4I-b7XflFVbTo228u0")
WECOM_TOKEN = os.environ.get("WECOM_TOKEN", "xiaozhi2026")
WECOM_ENCODING_AES_KEY = os.environ.get("WECOM_ENCODING_AES_KEY", "zd46dyvm7a7NAJhjwd5j5S4pK5Mdnak2cFeFzaby9y3")

WECOM_WEBHOOK_URL = os.environ.get("WECOM_WEBHOOK_URL", "")
