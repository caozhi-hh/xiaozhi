"""
企业微信渠道 -- 优雅降级

只在 WECOM_* 环境变量完整配置时才加载路由，
否则 router=None，不影响 Web 前端和其他功能。
"""
from config import WECOM_CORP_ID, WECOM_SECRET, WECOM_TOKEN

if WECOM_CORP_ID and WECOM_SECRET and WECOM_TOKEN:
    from wecom.router import router
else:
    router = None
