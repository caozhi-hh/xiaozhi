"""翻译工具"""


def translate(text: str, target_language: str = "中文") -> str:
    """翻译文本到指定语言。当用户要求翻译时使用。"""
    return f"[翻译请求] 请将以下内容翻译为{target_language}：\n{text}"
