"""
企业微信渠道

路由始终注册（保证回调 URL 可达），
缺少配置时 API 调用会失败但不影响启动。
"""
from wecom.router import router
