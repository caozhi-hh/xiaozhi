"""网页阅读工具 — 抓取网页内容并用 readability 算法提取正文"""
import re
import logging
import httpx
from langchain_core.tools import tool

logger = logging.getLogger("web_reader")


def _extract_with_readability(html: str) -> str | None:
    """尝试用 readability-lxml 提取正文（智能去噪）"""
    try:
        from readability import Document
        doc = Document(html)
        title = doc.title()
        summary = doc.summary()
        # summary 返回的是 HTML，简单清理
        clean = re.sub(r"<[^>]+>", "", summary)
        clean = clean.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ")
        clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
        if clean:
            return f"标题: {title}\n\n{clean}"
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"readability 提取失败: {e}")
    return None


def _html_to_text(html: str) -> str:
    """备用方案：正则清理 HTML"""
    _SCRIPT_RE = re.compile(r"<script[^>]*>[\s\S]*?</script>", re.IGNORECASE)
    _STYLE_RE = re.compile(r"<style[^>]*>[\s\S]*?</style>", re.IGNORECASE)
    _TAG_RE = re.compile(r"<[^>]+>")

    text = _SCRIPT_RE.sub("", html)
    text = _STYLE_RE.sub("", text)
    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = text.replace("</p>", "\n").replace("</div>", "\n").replace("</li>", "\n")
    text = _TAG_RE.sub("", text)
    for old, new in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&nbsp;", " ")]:
        text = text.replace(old, new)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


@tool
def fetch_webpage(url: str) -> str:
    """抓取网页内容并提取正文。当用户分享链接想要了解内容，或需要读取某个网页的具体内容时使用。

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

        # 解码
        content_type = resp.headers.get("content-type", "")
        if "charset" not in content_type.lower():
            try:
                text = resp.content.decode("utf-8")
            except UnicodeDecodeError:
                text = resp.content.decode(resp.encoding or "utf-8", errors="replace")
        else:
            text = resp.text

        # 非 HTML 直接返回
        if "<html" not in text.lower() and "<!doctype" not in text.lower():
            result = text
        else:
            # 优先用 readability 提取正文
            result = _extract_with_readability(text)
            if not result or len(result) < 50:
                # readability 失败或内容太少，降级到正则
                result = _html_to_text(text)

        # 截断过长内容
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
