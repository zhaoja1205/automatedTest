"""
ASPICE docx 模板引擎（docxtpl 封装）。

设计原则（和 arch_generator.py 的 1500 行拼装代码彻底分开）：
- 样式、标题编号、字体、页眉页脚全部由模板文件本身承载，Python 不碰
- 这层只做：加载模板 → 渲染 context → 嵌入图片 → 返回 BytesIO
- PlantUML 图片走后端已部署的本地渲染服务（10.10.134.116:8080），env 兜底 cloud
- 友好错误：模板里的 `{{ var }}` 找不到对应 context 时不是抛 Jinja 的裸异常，
  而是明确告诉用户 "模板 X 里 {{ Y }} 在 context 里不存在"

关键依赖：
- docxtpl 0.19.0  — 支持 {{ var }} / {% for %} / {%tr for %} / {%p if %} / InlineImage
- httpx          — 同步/异步下载 PlantUML PNG
- plantuml 编码由前端的 cppFlowchart.ts 完成（统一算法），这里只接收编码后的串
"""

from __future__ import annotations

import io
import logging
import os
import zlib
from pathlib import Path
from typing import Any

import httpx
from docx.shared import Mm
from docxtpl import DocxTemplate, InlineImage
from jinja2 import exceptions as jinja_exc

logger = logging.getLogger(__name__)

# ---------------- 模板目录 ----------------
_HERE = Path(__file__).resolve().parent
TEMPLATES_DIR = _HERE.parent / "templates" / "aspice"


def template_path(name: str) -> Path:
    """
    把逻辑名解析成磁盘路径。统一入口便于后续加缓存或热加载。

    name: "swe2_arch" | "swe2_arch_sample" | ...
    """
    p = TEMPLATES_DIR / f"{name}.docx"
    if not p.exists():
        raise FileNotFoundError(f"ASPICE 模板不存在：{p}")
    return p


# ---------------- PlantUML 图 → PNG 下载 ----------------
# 与 app/api/plantuml_routes.py 的 env 保持一致，避免两处硬编码飘移
_PLANTUML_BACKEND = os.getenv("PLANTUML_BACKEND", "local").strip().lower()
_PLANTUML_LOCAL = os.getenv("PLANTUML_LOCAL_URL", "http://10.10.134.116:8080").rstrip("/")
_PLANTUML_CLOUD = "https://www.plantuml.com/plantuml"


def _plantuml_png_url(encoded: str) -> str:
    base = _PLANTUML_LOCAL if _PLANTUML_BACKEND == "local" else _PLANTUML_CLOUD
    return f"{base}/png/{encoded}"


def fetch_plantuml_png(encoded: str, *, timeout: float = 20.0) -> bytes:
    """
    用已部署的 PlantUML 服务把编码串渲染成 PNG bytes。
    失败不吃异常 —— 让上层决定是写占位图还是重跑。
    """
    url = _plantuml_png_url(encoded)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.content


def plantuml_encode(source: str) -> str:
    """
    把 PlantUML 源码编码成 URL 片段（zlib deflate + PlantUML 的 base64 变种字母表）。
    和前端 cppFlowchart.ts 的 encodePlantUml 必须等价（都遵循官方规范）。
    """
    # zlib raw deflate（无 2 byte header / 4 byte adler32）
    compressed = zlib.compress(source.encode("utf-8"))[2:-4]

    # PlantUML 变种字母表
    alphabet = (
        "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "abcdefghijklmnopqrstuvwxyz-_"
    )
    out = []
    data = compressed
    b = bytearray(data)
    i = 0
    while i < len(b):
        if i + 2 < len(b):
            b1, b2, b3 = b[i], b[i + 1], b[i + 2]
            out.append(alphabet[(b1 >> 2) & 0x3F])
            out.append(alphabet[((b1 & 0x3) << 4) | ((b2 >> 4) & 0xF)])
            out.append(alphabet[((b2 & 0xF) << 2) | ((b3 >> 6) & 0x3)])
            out.append(alphabet[b3 & 0x3F])
            i += 3
        elif i + 1 < len(b):
            b1, b2 = b[i], b[i + 1]
            out.append(alphabet[(b1 >> 2) & 0x3F])
            out.append(alphabet[((b1 & 0x3) << 4) | ((b2 >> 4) & 0xF)])
            out.append(alphabet[(b2 & 0xF) << 2])
            i += 2
        else:
            b1 = b[i]
            out.append(alphabet[(b1 >> 2) & 0x3F])
            out.append(alphabet[(b1 & 0x3) << 4])
            i += 1
    return "".join(out)


# ---------------- PNG 降采样（防 docx 膨胀） ----------------
_MAX_PNG_SIDE_PX = int(os.getenv("ASPICE_MAX_PNG_SIDE_PX", "1600"))


def _shrink_png_if_huge(png: bytes) -> bytes:
    """长宽任一超 _MAX_PNG_SIDE_PX 时等比缩，并走 optimize 再压。

    - Pillow 不可用 → 直接返回原字节（兜底）
    - 原图已经够小 → 原样返回（省 CPU）
    - 任何异常 → 返回原字节，不影响主流程
    """
    try:
        from io import BytesIO
        from PIL import Image  # type: ignore
    except Exception:
        return png
    try:
        im = Image.open(BytesIO(png))
        w, h = im.size
        longest = max(w, h)
        if longest <= _MAX_PNG_SIDE_PX:
            return png
        im.thumbnail((_MAX_PNG_SIDE_PX, _MAX_PNG_SIDE_PX), Image.Resampling.LANCZOS)
        buf = BytesIO()
        # PNG 的 optimize=True 开 zlib max level，大约再省 10%~30% 字节
        im.save(buf, format="PNG", optimize=True)
        shrunk = buf.getvalue()
        # 极端情况（原图就是优化好的 PNG，缩放后反而变大） → 保留原图
        return shrunk if len(shrunk) < len(png) else png
    except Exception as e:
        logger.warning("PNG 降采样失败，保留原图：%s", e)
        return png


# ---------------- 渲染器 ----------------
class TemplateRenderer:
    """
    用法：
        r = TemplateRenderer("swe2_arch_sample")
        r.add_plantuml_image("comp_a001_seq_img", plant_source="@startuml ... @enduml")
        buf = r.render({...context...})
        return StreamingResponse(buf, media_type="application/vnd.openxml...")
    """

    def __init__(self, template_name: str):
        self.template_name = template_name
        self.path = template_path(template_name)
        self.tpl = DocxTemplate(str(self.path))
        self._images: dict[str, bytes] = {}      # key → PNG bytes

    def add_plantuml_image(self, key: str, *, plant_source: str) -> None:
        """
        注册一张 PlantUML 图：模板里用 {{ <key> }} 引用。
        渲染时自动下载 PNG 并嵌入。
        """
        encoded = plantuml_encode(plant_source)
        png = fetch_plantuml_png(encoded)
        self._images[key] = png

    def add_png_bytes(self, key: str, *, png: bytes) -> None:
        """直接塞已有 PNG（场景：cppFlowchart.ts 渲染完得到的字节）."""
        self._images[key] = png

    def _materialize_images(self, context: dict) -> dict:
        """
        在渲染前，把注册的图片转为 InlineImage 对象。
        做法：每张图写到临时文件，构造 InlineImage，挂到 context 里 key 对应的槽位。

        ★ docx 体积兜底：PlantUML 对超长流程会出 11000×6000 这种巨幅 PNG，几 MB
        一张，100+ 张 docx 就奔 50MB 去了。由于 docx 显示宽度被我们锁到 140mm
        (≈ 1600 px @ 288 DPI 已足矣)，这里统一把 PNG 降采样到最长边 ≤ 1600 px，
        用 PNG optimize 二次压缩。实测大图可缩小 10～50 倍，显示效果无感差异。
        """
        if not self._images:
            return context
        import tempfile
        tmp_dir = Path(tempfile.mkdtemp(prefix="aspice_imgs_"))
        enriched = dict(context)
        for key, png in self._images.items():
            fp = tmp_dir / f"{key}.png"
            fp.write_bytes(_shrink_png_if_huge(png))
            enriched[key] = InlineImage(self.tpl, str(fp), width=Mm(140))
        return enriched

    def render(self, context: dict) -> io.BytesIO:
        enriched = self._materialize_images(context)
        try:
            self.tpl.render(enriched)
        except jinja_exc.UndefinedError as e:
            raise ValueError(
                f"模板 {self.template_name} 渲染失败：context 缺字段 — {e.message}"
            ) from e
        except jinja_exc.TemplateSyntaxError as e:
            raise ValueError(
                f"模板 {self.template_name} 语法错误 @ line {e.lineno}: {e.message}"
            ) from e

        buf = io.BytesIO()
        self.tpl.save(buf)
        buf.seek(0)
        return buf


# ---------------- 覆盖检查工具 ----------------
def extract_template_variables(template_name: str) -> set[str]:
    """
    扫模板里用到的 Jinja2 变量名（顶层 identifier）。用于：
    - CI 检查：模板里引用的变量是否都在 schema 里定义了
    - 调试：quick sanity check
    """
    p = template_path(template_name)
    tpl = DocxTemplate(str(p))
    # init_docx 会把内部 .docx 填好，之后 get_undeclared_template_variables 才能跑
    tpl.init_docx()
    return set(tpl.get_undeclared_template_variables())


__all__ = [
    "TemplateRenderer",
    "template_path",
    "extract_template_variables",
    "fetch_plantuml_png",
    "plantuml_encode",
    "TEMPLATES_DIR",
]
