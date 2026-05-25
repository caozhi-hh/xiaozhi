"""
代码执行工具 — 安全沙箱运行 Python 代码
"""
import subprocess
import sys
import tempfile
import os

from langchain_core.tools import tool

BLOCKED_IMPORTS = {
    "os", "sys", "subprocess", "shutil", "pathlib",
    "socket", "http", "urllib", "requests",
    "ctypes", "signal", "multiprocessing",
    "importlib", "code", "codeop", "compileall",
    "pickle", "shelve", "marshal",
}

CODE_HEADER = """
import sys
class _Blocker:
    def find_module(self, fullname, path=None):
        for blocked in {blocked_list}:
            if fullname == blocked or fullname.startswith(blocked + '.'):
                raise ImportError(f'Module {{fullname}} is not allowed in sandbox')
    def load_module(self, fullname):
        raise ImportError(f'Module {{fullname}} is not allowed in sandbox')
sys.meta_path.insert(0, _Blocker())
del _Blocker, sys
""".format(blocked_list=repr(list(BLOCKED_IMPORTS)))


@tool
def run_code(code: str) -> str:
    """执行 Python 代码并返回输出结果。可用的库包括 math、json、re、datetime、collections、itertools、functools、random、string、statistics、textwrap、decimal、fractions、hashlib、base64。不支持文件读写、网络请求和系统调用。"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(CODE_HEADER + "\n" + code)
        tmp_path = f.name

    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=10,
            env={k: v for k, v in os.environ.items() if k not in ("PATH",)},
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += f"\n[stderr] {result.stderr}"
        if not output.strip():
            output = "(无输出)"
        return output[:3000]
    except subprocess.TimeoutExpired:
        return "执行超时（10秒限制）"
    except Exception as e:
        return f"执行错误: {e}"
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
