"""设备会话管理 — 识别设备、解析 UA、注入设备信息到系统提示"""
import hashlib
import logging
from datetime import datetime, timezone

logger = logging.getLogger("device")


def extract_client_ip(request) -> str:
    """提取真实客户端 IP（支持反向代理）"""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _parse_ua(ua_string: str) -> dict:
    """解析 User-Agent 为结构化设备信息"""
    try:
        from user_agents import parse
        ua = parse(ua_string or "")
        device_type = "desktop"
        if ua.is_mobile:
            device_type = "mobile"
        elif ua.is_tablet:
            device_type = "tablet"
        device_model = ""
        if ua.is_mobile or ua.is_tablet:
            device_model = ua.device_model or ua.device_brand or ""
        return {
            "device_model": device_model,
            "device_type": device_type,
            "browser": f"{ua.browser.family} {ua.browser.version_string}".strip(),
            "os_name": f"{ua.os.family} {ua.os.version_string}".strip(),
        }
    except Exception:
        ua_lower = (ua_string or "").lower()
        if "iphone" in ua_lower:
            return {"device_model": "iPhone", "device_type": "mobile", "browser": "", "os_name": "iOS"}
        if "android" in ua_lower:
            return {"device_model": "Android", "device_type": "mobile", "browser": "", "os_name": "Android"}
        if "ipad" in ua_lower:
            return {"device_model": "iPad", "device_type": "tablet", "browser": "", "os_name": "iPadOS"}
        return {"device_model": "", "device_type": "desktop", "browser": "", "os_name": ""}


def get_device_id_from_request(request) -> str:
    """从 X-Device-ID 头提取 device_id，无则用 UA+IP 生成"""
    raw = request.headers.get("x-device-id", "")
    if raw:
        return raw[:64]
    ua = request.headers.get("user-agent", "")
    ip = extract_client_ip(request)
    return hashlib.sha256(f"{ua}|{ip}".encode()).hexdigest()[:32]


def _upsert_device(db, device_id: str, request):
    """创建或更新设备记录（所有导入延迟到调用时）"""
    try:
        from models import Device
    except Exception:
        return None

    ua_string = request.headers.get("user-agent", "")
    ip = extract_client_ip(request)
    parsed = _parse_ua(ua_string)

    device = db.query(Device).filter(Device.device_id == device_id).first()
    if device:
        device.user_agent = ua_string[:500]
        device.ip_address = ip
        device.device_model = parsed["device_model"]
        device.device_type = parsed["device_type"]
        device.browser = parsed["browser"]
        device.os_name = parsed["os_name"]
        device.last_seen = datetime.now(timezone.utc)
    else:
        device = Device(
            device_id=device_id,
            user_agent=ua_string[:500],
            ip_address=ip,
            device_model=parsed["device_model"],
            device_type=parsed["device_type"],
            browser=parsed["browser"],
            os_name=parsed["os_name"],
        )
        db.add(device)
    db.commit()
    db.refresh(device)
    return device


class DeviceContext:
    """当前请求的设备上下文"""
    def __init__(self, device_id: str, device):
        self.device_id = device_id
        self.device = device

    @property
    def summary_for_prompt(self) -> str:
        if not self.device:
            return ""
        parts = []
        d = self.device
        if d.device_model:
            parts.append(d.device_model)
        if d.os_name:
            parts.append(d.os_name)
        if d.browser:
            parts.append(d.browser)
        if d.device_type:
            type_cn = {"mobile": "手机", "tablet": "平板", "desktop": "电脑"}.get(d.device_type, d.device_type)
            parts.append(type_cn)
        if d.ip_address and d.ip_address != "unknown":
            masked = ".".join(d.ip_address.split(".")[:-1] + ["xxx"]) if "." in d.ip_address else d.ip_address
            parts.append(f"IP: {masked}")
        if not parts:
            return ""
        return f"用户正在从 {' '.join(parts)} 上访问你"


def get_device_context(db, request):
    """从请求中提取设备上下文（非 Depends 模式，直接在端点内调用）"""
    device_id = get_device_id_from_request(request)
    try:
        device = _upsert_device(db, device_id, request)
    except Exception as e:
        logger.warning(f"设备记录更新失败: {e}")
        device = None
    return DeviceContext(device_id, device)
