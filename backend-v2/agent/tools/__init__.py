"""工具注册表 — 所有 Agent 可用的工具"""
import logging

logger = logging.getLogger("agent.tools")

ALL_TOOLS = []

for _tool_mod, _tool_name in [
    ("agent.tools.web_search", "web_search"),
    ("agent.tools.weather", "get_weather"),
    ("agent.tools.translate", "translate"),
    ("agent.tools.file_gen", "generate_file"),
    ("agent.tools.code_runner", "run_code"),
]:
    try:
        import importlib
        mod = importlib.import_module(_tool_mod)
        ALL_TOOLS.append(getattr(mod, _tool_name))
    except Exception as e:
        logger.warning(f"工具 {_tool_name} 加载失败: {e}")
