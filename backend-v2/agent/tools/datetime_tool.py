"""时间工具 — 让 Agent 感知当前日期和时间"""
from datetime import datetime
from langchain_core.tools import tool


@tool
def get_current_datetime(format: str = "") -> str:
    """获取当前日期、时间和星期。当你需要知道今天几号、现在几点、星期几、或者需要计算时间差时使用此工具。

    Args:
        format: 可选的时间格式，留空则返回完整的中文日期时间
    """
    now = datetime.now()
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    if format:
        return now.strftime(format)
    return f"{now.strftime('%Y年%m月%d日')} {weekdays[now.weekday()]} {now.strftime('%H:%M:%S')}"
