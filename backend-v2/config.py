"""
集中配置 — 从 .env 加载 API Keys 和常量
"""
from pathlib import Path
from dotenv import dotenv_values

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

_env = dotenv_values(ENV_FILE)

# SiliconFlow 图片生成 API Key
SILICONFLOW_API_KEY = _env.get("SILICONFLOW_API_KEY")

# 企业微信 - 自建应用
WECOM_CORP_ID = _env.get("WECOM_CORP_ID", "")
WECOM_AGENT_ID = _env.get("WECOM_AGENT_ID", "")
WECOM_SECRET = _env.get("WECOM_SECRET", "")
WECOM_TOKEN = _env.get("WECOM_TOKEN", "")
WECOM_ENCODING_AES_KEY = _env.get("WECOM_ENCODING_AES_KEY", "")

# 企业微信 - 群机器人 Webhook
WECOM_WEBHOOK_URL = _env.get("WECOM_WEBHOOK_URL", "")
