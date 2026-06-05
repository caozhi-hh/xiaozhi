"""工具注册表 — 所有 Agent 可用的工具"""
import logging

logger = logging.getLogger("agent.tools")

ALL_TOOLS = []

for _tool_mod, _tool_name in [
    ("agent.tools.web_search", "web_search"),
    ("agent.tools.weather", "get_weather"),
    ("agent.tools.file_gen", "generate_file"),
    ("agent.tools.code_runner", "run_code"),
    ("agent.tools.image_gen", "generate_image"),
    ("agent.tools.datetime_tool", "get_current_datetime"),
    ("agent.tools.web_reader", "fetch_webpage"),
]:
    try:
        import importlib
        mod = importlib.import_module(_tool_mod)
        tool_obj = getattr(mod, _tool_name)
        ALL_TOOLS.append(tool_obj)
        logger.info(f"工具注册成功: {_tool_name} (type={type(tool_obj).__name__})")
    except Exception as e:
        logger.error(f"工具 {_tool_name} 加载失败: {e}")

logger.info(f"共注册 {len(ALL_TOOLS)} 个工具: {[t.name if hasattr(t, 'name') else str(t) for t in ALL_TOOLS]}")
