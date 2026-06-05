"""热梗抓取器 — 定时从互联网获取最新网络热梗，注入到小智人设中"""
import logging
import time
import threading
import httpx

logger = logging.getLogger("meme_fetcher")

# 缓存：{ "memes": "梗1、梗2、梗3...", "updated_at": timestamp }
_cache: dict = {"memes": "", "updated_at": 0}
_ttl = 6 * 3600  # 6 小时刷新一次

DEFAULT_MEMES = (
    "我嘞个豆、太抽象了、家人们谁懂啊、已老实求放过、"
    "一声兄弟大过天、不是吧阿Sir、我去了、这合理吗、"
    "小丑竟是我自己、有一说一、绝绝子、格局打开、"
    "你个老六、栓Q、芭比Q了、CPU烧了、"
    "尊嘟假嘟、命运的齿轮开始转动、遥遥领先"
)


def get_memes() -> str:
    """获取当前缓存的热梗文本"""
    if _cache["memes"] and (time.time() - _cache["updated_at"] < _ttl):
        return _cache["memes"]
    # 缓存过期或为空，同步刷新一次
    refresh_memes()
    return _cache["memes"] or DEFAULT_MEMES


def refresh_memes():
    """从多个来源抓取最新热梗，用 LLM 整理成一句"""
    try:
        raw = _fetch_from_sources()
        if not raw:
            return
        memes_text = _summarize_with_llm(raw)
        if memes_text:
            _cache["memes"] = memes_text
            _cache["updated_at"] = time.time()
            logger.info(f"热梗更新成功: {memes_text[:60]}...")
    except Exception as e:
        logger.warning(f"热梗刷新失败，使用缓存: {e}")


def _fetch_from_sources() -> str:
    """从多个来源抓取热梗文本"""
    results = []
    headers = {"User-Agent": "Mozilla/5.0"}

    # 来源 1：通过搜索引擎抓
    try:
        resp = httpx.get(
            "https://html.duckduckgo.com/html/",
            params={"q": "2025年6月 抖音热梗 网络流行语 最新"},
            headers=headers,
            timeout=15,
        )
        if resp.status_code == 200:
            text = resp.text[:5000]
            # 粗提取：找中文短语
            results.append(text)
    except Exception as e:
        logger.debug(f"DuckDuckGo 抓取失败: {e}")

    # 来源 2：百度百科热词（如果有）
    try:
        resp = httpx.get(
            "https://baike.baidu.com/cms/home/beikewords/newwordlist.json",
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            words = []
            for month_data in data.values():
                if isinstance(month_data, dict):
                    for item in month_data.get("wordlist", []):
                        w = item.get("title", "")
                        if w and len(w) <= 15:
                            words.append(w)
            if words:
                results.append("、".join(words[:30]))
    except Exception as e:
        logger.debug(f"百度百科抓取失败: {e}")

    return "\n".join(results)


def _summarize_with_llm(raw: str) -> str:
    """用 LLM 把杂乱文本整理成热梗列表"""
    try:
        from llm import get_llm
        llm = get_llm("qwen-turbo")
        resp = llm.invoke(
            f"从以下文本中提取最新的中国网络热梗/流行语（抖音、微博、B站等平台）。\n"
            f"只返回用顿号分隔的梗列表，不要解释，不要编号，不要其他文字，最多20个。\n\n"
            f"原始文本：\n{raw[:3000]}"
        )
        return resp.content.strip()
    except Exception as e:
        logger.warning(f"LLM 整理热梗失败: {e}")
        return ""


def start_background_refresh():
    """启动后台定时刷新线程"""
    def _loop():
        while True:
            try:
                refresh_memes()
            except Exception as e:
                logger.warning(f"热梗定时刷新异常: {e}")
            time.sleep(_ttl)

    t = threading.Thread(target=_loop, daemon=True, name="meme-refresher")
    t.start()
    logger.info("热梗定时刷新已启动（每6小时）")
