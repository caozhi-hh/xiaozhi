"""
文件处理 — PDF 文字提取 + 图片 base64 编码

支持的文件类型：
  PDF → 提取文字内容
  图片（PNG/JPG/JPEG/GIF/WEBP）→ base64 编码，走视觉模型
"""
import base64
from io import BytesIO

import fitz  # PyMuPDF

IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


def is_image(filename: str) -> bool:
    return _ext(filename) in IMAGE_EXTENSIONS


def is_pdf(filename: str) -> bool:
    return _ext(filename) == "pdf"


def _ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def extract_pdf_text(file_bytes: bytes) -> str:
    """从 PDF 中提取全部文字"""
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text.strip()


def image_to_base64(file_bytes: bytes, filename: str) -> str:
    """将图片转为 base64 data URL（自动压缩大图）"""
    from PIL import Image

    img = Image.open(BytesIO(file_bytes))

    # 如果图片超过 1024px，等比缩小
    max_size = 1024
    if max(img.size) > max_size:
        ratio = max_size / max(img.size)
        new_size = (int(img.width * ratio), int(img.height * ratio))
        img = img.resize(new_size)

    # 转为 JPEG 压缩
    buf = BytesIO()
    img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/jpeg;base64,{b64}"
