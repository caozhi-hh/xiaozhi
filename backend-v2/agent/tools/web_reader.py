"""网页阅读工具 — 抓取网页内容并转为纯文本"""
import re
import logging
import httpx
from langchain_core.tools import tool

logger = logging.getLogger("web_reader")

# 简易 HTML → 纯文本（不引入 BeautifulSoup 等重依赖）
_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<script[^>]*>[\s\S]*?</script>", re.IGNORECASE)
_STYLE_RE = re.compile(r"<style[^>]*>[\s\S]*?</style>", re.IGNORECASE)
_WS_RE = re.compile(r"\n{3,}")


def _html_to_text(html: str) -> str:
    """粗暴但高效地将 HTML 转为可读文本"""
    text = _SCRIPT_RE.sub("", html)
    text = _STYLE_RE.sub("", text)
    # 保留换行
    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = text.replace("</p>", "\n").replace("</div>", "\n").replace("</li>", "\n")
    text = text.replace("<hr>", "\n---\n")
    text = _TAG_RE.sub("", text)
    # 解码常见 HTML 实体
    for old, new in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&nbsp;", " ")]:
        text = text.replace(old, new)
    text = _WS_RE.sub("\n\n", text).strip()
    return text


@tool
def fetch_webpage(url: str) -> str:
    """抓取网页内容并转为纯文本。当用户分享了一个链接想要了解内容，或者需要读取某个网页的具体内容时使用。

    Args:
        url: 要抓取的网页 URL
    """
    if not url.startswith(("http://", "https://")):
        return "无效的 URL，请以 http:// 或 https:// 开头"

    try:
        resp = httpx.get(
            url,
            follow_redirects=True,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
        resp.raise_for_status()

        # 尝试检测编码
        content_type = resp.headers.get("content-type", "")
        if "charset" not in content_type.lower():
            # 尝试 UTF-8，失败则用 apparent_encoding
            try:
                text = resp.content.decode("utf-8")
            except UnicodeDecodeError:
                text = resp.content.decode(resp.encoding or "utf-8", errors="replace")
        else:
            text = resp.text

        # 检查是否是 HTML
        if "<html" in text.lower() or "<!doctype" in text.lower():
            result = _html_to_text(text)
        else:
            result = text

        # 截断过长的内容
        if len(result) > 8000:
            result = result[:8000] + "\n\n... (内容过长，已截断)"

        if not result.strip():
            return "网页内容为空"

        return result

    except httpx.TimeoutException:
        return "网页加载超时，请稍后重试"
    except httpx.HTTPStatusError as e:
        return f"网页返回错误: {e.response.status_code}"
    except Exception as e:
        return f"抓取网页失败: {e}"
