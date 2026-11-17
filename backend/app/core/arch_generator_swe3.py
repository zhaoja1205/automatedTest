"""
SWE.3 软件详细设计 — 生成器。

docx 骨架对齐《PreDev_详细设计V1.0_updated》14 章结构：
  封面 → 历史记录 → 评审记录
  1 概述（目的/范围/参考文档/字符集/get-set 规则）
  2 术语定义
  3 软件功能概述（功能概述 + 模块构成追溯表 SWE.1→SWE.2→类→SWE.3）
  4~N 各模块详细设计（9 模块：类图 PNG / 类列表 / 每类成员常量 + 成员变量 + 函数列表 + 每函数详情 + 流程图 PNG / 单元时序图 PNG）
  N+1 性能分析设计
  N+2 函数设计评估（影响范围 + 边界值分析）
  N+3 共通定义（常量/变量/枚举/结构体/配置文件）
  N+4 系统集成

关键改动（对齐参考文档）：
  - 每个函数独立 H4 heading，内含声明/介绍段 + 参数表 + 返回表 + 流程图 PNG
  - PlantUML 源码（类图/时序图/流程图）通过 plantuml.com 代理渲染为 PNG 嵌入文档
    PNG 失败时降级为 "<PlantUML 源码>" 段，不打断导出
  - 章节号动态计算：11/12/13/14 跟随实际模块数（关闭 Camera Security 时不留空档）

xlsx 导出：多 sheet（模块构成追溯/类列表/函数列表/枚举/结构体/边界值分析）
"""
import os
import re
import zlib
from datetime import datetime
from io import BytesIO
from typing import Optional

import httpx

from app.core import arch_sections_swe3 as sections3
from app.core import arch_sections


# ---- PlantUML 渲染（zlib deflate + plantuml-base64，走官方 plantuml.com） ----

# PlantUML 的 base64 字符表，位序 0..63；和前端 utils/cppFlowchart.ts 保持一致
_PU_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"


def _plantuml_base64(data: bytes) -> str:
    """PlantUML 专用 base64：和标准 base64 位序相同，但用自家字符表。"""
    out = []
    n = len(data)
    for i in range(0, n, 3):
        b1 = data[i]
        b2 = data[i + 1] if i + 1 < n else 0
        b3 = data[i + 2] if i + 2 < n else 0
        out.append(_PU_ALPHABET[(b1 >> 2) & 0x3F])
        out.append(_PU_ALPHABET[((b1 << 4) | (b2 >> 4)) & 0x3F])
        out.append(_PU_ALPHABET[((b2 << 2) | (b3 >> 6)) & 0x3F])
        out.append(_PU_ALPHABET[b3 & 0x3F])
    return "".join(out)


def _plantuml_to_png(uml: str, timeout: float = 25.0, retries: int = 2) -> Optional[bytes]:
    """把 PlantUML 源码渲染为 PNG 字节；失败返回 None（调用方会降级为文本段）。

    走官方 plantuml.com；网络抖动做 2 次重试，UML 语法错 plantuml.com 会返回
    带错误图示的 PNG（我们仍视为成功，图片里会直接显示错误行号便于定位）。
    任何异常都捕获，避免整篇导出被单张图挂掉。
    """
    if not uml or not uml.strip():
        return None
    try:
        raw = uml.encode("utf-8")
        # PlantUML 期望 raw deflate（无 zlib header）—— wbits=-15
        compressor = zlib.compressobj(level=9, wbits=-15)
        compressed = compressor.compress(raw) + compressor.flush()
        encoded = _plantuml_base64(compressed)
        url = f"https://www.plantuml.com/plantuml/png/{encoded}"
    except Exception:
        return None

    attempt = 0
    last_err: Optional[Exception] = None
    while attempt <= retries:
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                resp = client.get(url)
            if resp.status_code == 200 and resp.content:
                return resp.content
            # plantuml.com 对坏源码偶尔会返回 400，重试没意义；但 5xx/网络抖动值得重试
            if 500 <= resp.status_code < 600:
                attempt += 1
                continue
            return None
        except Exception as e:
            last_err = e
            attempt += 1
    return None


# ---- docx 辅助 ----

# 表头背景色：参考文档深蓝灰，和微软 Word "浅色网格" 风格一致。
# BBDEFB = 浅蓝（Material Blue 100），接近用户截图里函数详情表的表头色
HEADER_FILL_HEX = "BBDEFB"
# 字段标签列（如 "函数声明" / "函数介绍" / "Parameter1"）用的更浅背景
LABEL_FILL_HEX = "E3F2FD"


def _shade_cell(cell, hex_color: str) -> None:
    """给 docx 表格单元格设置底纹色（RGB hex，不含 #）。

    python-docx 没有原生 API；需要往 `<w:tcPr>` 塞 `<w:shd w:fill="..."/>`。
    颜色失败不致命（table 本身还能渲染），try/except 兜底。
    """
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    try:
        tc_pr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), hex_color)
        tc_pr.append(shd)
    except Exception:
        pass


def _add_table(doc, headers: list[str], rows: list[list[str]], widths: Optional[list[float]] = None):
    """统一样式封装：建带表头的 Table Grid（表头带蓝色底纹）。"""
    from docx.shared import Pt, Cm

    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    hdr_cells = t.rows[0].cells
    for i, h in enumerate(headers):
        hdr_cells[i].text = h
        _shade_cell(hdr_cells[i], HEADER_FILL_HEX)
        for p in hdr_cells[i].paragraphs:
            for run in p.runs:
                run.bold = True
                run.font.size = Pt(10)

    for row in rows:
        cells = t.add_row().cells
        for i, val in enumerate(row[: len(headers)]):
            cells[i].text = "" if val is None else str(val)

    if widths:
        for i, w in enumerate(widths[: len(headers)]):
            try:
                for row in t.rows:
                    row.cells[i].width = Cm(w)
            except Exception:
                pass
    return t


def _add_paragraphs(doc, paragraphs: list[str]):
    """批量添加段落，忽略空字符串。"""
    for p in paragraphs or []:
        if p and p.strip():
            doc.add_paragraph(p)


def _add_plantuml_image(doc, uml: str, caption: str, width_inches: float = 5.5):
    """渲染 PlantUML 为 PNG 并嵌入 docx；失败则落源码块。"""
    from docx.shared import Inches

    if not uml or not uml.strip():
        doc.add_paragraph(f"<待 AI 生成 {caption}>")
        return

    png = _plantuml_to_png(uml)
    if png:
        try:
            doc.add_picture(BytesIO(png), width=Inches(width_inches))
            # 居中
            try:
                last = doc.paragraphs[-1]
                last.alignment = 1
            except Exception:
                pass
            return
        except Exception as e:
            # python-docx 极少数情况下嵌入失败（PNG 字节异常），降级为源码块
            doc.add_paragraph(f"（{caption} 的 PNG 嵌入失败：{e}；下方给出 PlantUML 源码）")

    # 降级：PlantUML 源码块（可能是网络不通到 plantuml.com）
    doc.add_paragraph(
        f"（{caption} 自动渲染失败，可能原因：导出时服务器无法访问 www.plantuml.com；"
        f"请检查网络后重新导出，或将下面源码贴到 http://www.plantuml.com/plantuml 手动生成图片）"
    )
    code_p = doc.add_paragraph()
    code_p.add_run(uml).font.name = "Consolas"


def _render_cover(doc, project_code: str, meta: dict):
    """封面页。"""
    from docx.shared import Pt

    title_p = doc.add_paragraph()
    title_p.alignment = 1
    title_run = title_p.add_run(f"{project_code or '本项目'}\n软件详细设计")
    title_run.font.size = Pt(28)
    title_run.bold = True

    for _ in range(2):
        doc.add_paragraph()
    v_p = doc.add_paragraph()
    v_p.alignment = 1
    v_p.add_run(f"版本号：{meta.get('doc_version', 'V1.0')}").font.size = Pt(14)
    c_p = doc.add_paragraph()
    c_p.alignment = 1
    c_p.add_run(meta.get("company", "中科创达软件股份有限公司")).font.size = Pt(12)

    doc.add_page_break()


def _render_history_review(doc, project: dict):
    """历史记录 + 评审记录。"""
    history = project.get("history") or [{
        "date": datetime.now().strftime("%Y/%m/%d"),
        "version": project.get("meta", {}).get("doc_version", "V1.0"),
        "author": project.get("meta", {}).get("modifier", ""),
        "change": "初版",
    }]
    reviews = project.get("reviews") or []

    doc.add_heading("历史记录", level=1)
    _add_table(doc, ["日期", "版本号", "作者", "修改内容"],
               [[h.get("date", ""), h.get("version", ""), h.get("author", ""), h.get("change", "")]
                for h in history])

    doc.add_heading("评审记录", level=1)
    if reviews:
        _add_table(doc, ["版本号", "评审日期", "评审人", "审批人", "评审意见"],
                   [[r.get("version", ""), r.get("date", ""), r.get("reviewer", ""),
                     r.get("approver", ""), r.get("comment", "")]
                    for r in reviews])
    else:
        _add_table(doc, ["版本号", "评审日期", "评审人", "审批人", "评审意见"],
                   [["", "", "", "", ""]])

    doc.add_paragraph(
        "注：请在 Word 中右键『更新目录』刷新页码。"
    )
    doc.add_page_break()


# ---- 1 概述 ----

def _render_overview(doc, swe3: dict, project_code: str):
    doc.add_heading("1 概述", level=1)
    overview = swe3.get("overview") or {}

    doc.add_heading("1.1 目的", level=2)
    purpose = (overview.get("purpose") or "").strip() or \
        sections3.DEFAULT_SWE3_PURPOSE.format(code=project_code or "本项目")
    doc.add_paragraph(purpose)

    doc.add_heading("1.2 范围", level=2)
    doc.add_paragraph("本文档描述的软件系统的范围如下表：")
    scope_rows = overview.get("scope_rows") or sections3.DEFAULT_SWE3_SCOPE_ROWS
    _add_table(doc, ["NO.", "范围", "作用及功能"],
               [[r.get("no", ""), r.get("scope", ""), r.get("function", "")] for r in scope_rows])

    doc.add_heading("1.3 参考文档", level=2)
    ref_docs = overview.get("ref_docs") or []
    if ref_docs:
        _add_table(doc, ["NO.", "参考文献名称", "文件版本", "说明"],
                   [[r.get("no", ""), r.get("name", ""), r.get("version", ""), r.get("note", "")]
                    for r in ref_docs])
    else:
        _add_table(doc, ["NO.", "参考文献名称", "文件版本", "说明"],
                   [["1", "NVIDIA Drive-OS NvSIPL Programming Guide", "-", "NV 官方文档"],
                    ["2", f"{project_code or 'Project'}_软件架构&概要设计书", "V1.0", "SWE.2 产物"]])

    doc.add_heading("1.4 字符集", level=2)
    _add_table(doc, ["字符集", "说明"],
               [["UTF-8", overview.get("charset") or sections3.DEFAULT_SWE3_CHARSET]])

    doc.add_heading("1.5 成员变量的 set 和 get 函数统一处理规则", level=2)
    doc.add_paragraph(overview.get("getset_rule") or sections3.DEFAULT_SWE3_GETSET_RULE)


# ---- 2 术语定义 ----

def _render_terms(doc, swe3: dict):
    doc.add_heading("2 术语定义", level=1)
    terms = swe3.get("terms") or sections3.DEFAULT_SWE3_TERMS
    _add_table(doc, ["缩写和术语", "定义"],
               [[t.get("term", ""), t.get("definition", "")] for t in terms])


# ---- 3 软件功能概述 ----

def _render_composition(doc, swe3: dict, swe2: dict):
    doc.add_heading("3 软件功能概述", level=1)

    doc.add_heading("3.1 功能概述", level=2)
    comp = swe3.get("composition") or {}
    overview_text = (comp.get("function_overview") or "").strip() or (
        "本系统基于 NVIDIA Drive-OS NvSIPL 框架实现相机驱动软件，"
        "包含 Serializer / Deserializer / EEPROM / Camera Module / Camera Security "
        "/ nvsipl_camera / nvsipl_multicast / PMIC / Campwr 共 9 个模块。"
        "各模块按设计 ID 命名规则（D{组件编号}-{组件名}-{类/函数}-{序号}）唯一标识类与函数。"
    )
    doc.add_paragraph(overview_text)

    doc.add_heading("3.2 模块构成", level=2)
    rows = comp.get("composition_rows") or sections3.build_composition_from_swe2(swe2)
    if rows:
        _add_table(doc,
                   ["SWE.1", "需求描述", "SWE.2", "对应组件", "功能模块图中的类", "SWE.3"],
                   [[r.get("swe1_id", ""), r.get("req_desc", ""), r.get("swe2_id", ""),
                     r.get("component", ""), r.get("classes", ""), r.get("swe3_ids", "")]
                    for r in rows])
    else:
        doc.add_paragraph("<待 SWE.2 填充映射表后自动派生，或由用户手动维护>")


# ---- 4~N 各模块详细设计 ----

def _render_function_detail(doc, func: dict, heading_level: int = 4,
                             heading_override: Optional[str] = None):
    """单个函数：H{heading_level} heading + [设计 ID] + 单张合并大表（函数声明/介绍/参数/返回值/流程图）+ 下方"功能说明"段。

    heading_level：
      - 4（默认）：类子节下的函数详情（对齐参考文档 Chapter 5 Class CNvMMax96724 → 函数GetErrorInfo）
      - 独立函数（模块级 H3 "函数列表" 下）也用 4

    heading_override：外部已经算好带章节号的完整标题（如 "4.2.1.3 函数SetConfig"）就直接用，
    否则按 `函数{name}` 兜底。

    表结构对齐《PreDev_详细设计V1.0_updated》7.3.2.x 样式：
      行 1: 函数声明 | <签名>（横跨 2 列）
      行 2: 函数介绍 | <介绍>（横跨 2 列）
      行 3: Parameter N  | Type       | 说明  ← 表头
      行 4: <参数名>     | <类型>     | <描述>
      ... 每个参数两行
      行 X: 返回值        | Type       | 说明  ← 表头
      行 X+1: <ret>      | <类型>     | <描述>
      行 Y: 函数流程图（横跨 3 列·居中）
      行 Y+1: <PNG>（横跨 3 列）
    表后：功能说明（独立段落，含异常处理/返回值说明等正文）
    """
    from docx.shared import Cm, Inches, Pt

    name = func.get("name", "")
    head_text = heading_override or f"函数{name}"
    doc.add_heading(head_text, level=heading_level)

    # 设计 ID 行（如 [D004-IMX623-function-001]）
    design_id = func.get("design_id", "")
    if design_id:
        p = doc.add_paragraph()
        p.add_run(f"[{design_id}]").bold = True

    declaration = (func.get("declaration") or "").strip() or f"<待 AI 补充 {name} 函数声明>"
    intro = (func.get("intro") or "").strip() or f"<待 AI 补充 {name} 功能介绍>"
    params = func.get("parameters") or []
    returns = func.get("returns") or [{
        "name": "NVSIPL_STATUS_OK",
        "type": "SIPLStatus",
        "desc": "定义 NvSIPL 中函数返回的状态代码。",
    }]
    flow = (func.get("flowchart_plantuml") or "").strip()
    description = (func.get("description") or "").strip()

    # R4 收尾：即使 AI 没生成 / 失败 / 异常 / 豁免，也**保留流程图占位行**（2 行：标题 + 占位文案），
    # 让读文档的人一眼看到"这里原本应该有流程图，当前是 X 状态"。
    # 实际占位文案由 _resolve_flowchart_placeholder 负责按四态生成。
    placeholder_text = ""
    if not flow:
        placeholder_text = _resolve_flowchart_placeholder(func)

    # 预计算行数：声明1 + 介绍1 + 每参数 2 + 返回值 2 + 流程图 2（恒有，无论有图/占位）
    row_count = 2 + len(params) * 2 + 2 + 2

    t = doc.add_table(rows=row_count, cols=3)
    t.style = "Table Grid"
    # 列宽：标签列 4cm / 类型列 4cm / 说明列 8.5cm
    col_widths = [Cm(4.0), Cm(4.0), Cm(8.5)]
    for row in t.rows:
        for i, w in enumerate(col_widths):
            try:
                row.cells[i].width = w
            except Exception:
                pass

    def _set_cell(cell, text: str, bold: bool = False, shade: Optional[str] = None):
        cell.text = ""
        p = cell.paragraphs[0]
        run = p.add_run("" if text is None else str(text))
        run.bold = bold
        run.font.size = Pt(10)
        if shade:
            _shade_cell(cell, shade)

    def _merge_right(row_idx: int, start_col: int):
        """把某行从 start_col 起向右合并到最后一列，返回合并后的首格。"""
        a = t.cell(row_idx, start_col)
        b = t.cell(row_idx, len(col_widths) - 1)
        return a.merge(b)

    r = 0
    # 行 1: 函数声明 + 签名（跨 2/3 列合并）
    _set_cell(t.cell(r, 0), "函数声明", bold=True, shade=LABEL_FILL_HEX)
    _set_cell(_merge_right(r, 1), declaration)
    r += 1
    # 行 2: 函数介绍
    _set_cell(t.cell(r, 0), "函数介绍", bold=True, shade=LABEL_FILL_HEX)
    _set_cell(_merge_right(r, 1), intro)
    r += 1

    # 参数：每个占两行（表头 + 数据）
    for idx, pp in enumerate(params, 1):
        _set_cell(t.cell(r, 0), f"Parameter{idx}", bold=True, shade=HEADER_FILL_HEX)
        _set_cell(t.cell(r, 1), "Type", bold=True, shade=HEADER_FILL_HEX)
        _set_cell(t.cell(r, 2), "说明", bold=True, shade=HEADER_FILL_HEX)
        r += 1
        _set_cell(t.cell(r, 0), pp.get("name", ""))
        _set_cell(t.cell(r, 1), pp.get("type", ""))
        _set_cell(t.cell(r, 2), pp.get("desc", ""))
        r += 1

    # 返回值：表头 + 一行数据（NVSIPL 风格通常一行；多行会取第一行，其余作为补充放到说明里）
    _set_cell(t.cell(r, 0), "返回值", bold=True, shade=HEADER_FILL_HEX)
    _set_cell(t.cell(r, 1), "Type", bold=True, shade=HEADER_FILL_HEX)
    _set_cell(t.cell(r, 2), "说明", bold=True, shade=HEADER_FILL_HEX)
    r += 1
    first_ret = returns[0] if returns else {}
    _set_cell(t.cell(r, 0), first_ret.get("name", ""))
    _set_cell(t.cell(r, 1), first_ret.get("type", ""))
    extra_rets = returns[1:]
    ret_desc = first_ret.get("desc", "")
    if extra_rets:
        extras = "；".join(f"{x.get('name','')}: {x.get('desc','')}" for x in extra_rets)
        ret_desc = (ret_desc + "\n其它返回：" + extras).strip()
    _set_cell(t.cell(r, 2), ret_desc)
    r += 1

    # 流程图：标题行（跨 3 列·居中） + 图片/占位行（跨 3 列）
    # R4：有 flow 走 PNG 嵌入；无 flow 走 placeholder_text（四态占位文案）
    title_cell = t.cell(r, 0).merge(t.cell(r, 1)).merge(t.cell(r, 2))
    _set_cell(title_cell, "函数流程图", bold=True, shade=LABEL_FILL_HEX)
    try:
        title_cell.paragraphs[0].alignment = 1
    except Exception:
        pass
    r += 1
    img_cell = t.cell(r, 0).merge(t.cell(r, 1)).merge(t.cell(r, 2))
    img_cell.text = ""
    img_para = img_cell.paragraphs[0]
    try:
        img_para.alignment = 1
    except Exception:
        pass

    if flow:
        png = _plantuml_to_png(flow)
        if png:
            try:
                run = img_para.add_run()
                # 嵌入图片宽度收窄到 4.0"（原 4.5"），避免长流程图撑爆页面高度
                run.add_picture(BytesIO(png), width=Inches(4.0))
            except Exception as e:
                img_para.add_run(f"（PNG 嵌入失败：{e}，源码如下）\n").italic = True
                img_para.add_run(flow).font.name = "Consolas"
        else:
            # 降级：源码块 + 诊断说明（通常是导出时服务器无法访问 plantuml.com）
            img_para.add_run(
                "（流程图自动渲染失败：无法访问 www.plantuml.com；"
                "请检查后端服务器网络再重新导出，或将下方源码手工贴到 plantuml 服务生成 PNG 后替换）\n"
            ).italic = True
            img_para.add_run(flow).font.name = "Consolas"
    else:
        # R4 占位文案：四态 - 豁免 / 异常 / SDK·不画 / 失败 / 待生成
        run = img_para.add_run(placeholder_text or "<待生成 流程图>")
        run.italic = True
        run.font.size = Pt(10)
    r += 1

    # 表后：功能说明段（截图里以"功能说明：..."开头的正文）
    # 优先用显式 description；否则回退到 intro（避免空白），都没有时省略
    narrative = description or (func.get("intro") or "").strip()
    if narrative:
        p = doc.add_paragraph()
        p.add_run("功能说明：").bold = True
        p.add_run(narrative)



def _add_class_list_table(doc, classes: list[dict]):
    """渲染类列表表 — 对齐参考文档 Chapter 4/5 的交织布局。

    每个类占两行：
      row A:  序号 | 设计 ID | 类名 | 说明
      row B:  "路径" | <paths 合并单元格，横跨 cols 1-3，多路径用换行分隔>

    用 python-docx 的 `cell.merge` 做水平合并，视觉效果与参考文档一致。
    """
    from docx.shared import Pt

    headers = ["序号", "设计 ID", "类名", "说明"]
    t = doc.add_table(rows=1 + 2 * len(classes), cols=4)
    t.style = "Table Grid"

    # 表头
    for i, h in enumerate(headers):
        cell = t.rows[0].cells[i]
        cell.text = h
        for p in cell.paragraphs:
            for run in p.runs:
                run.bold = True
                run.font.size = Pt(10)
        _shade_cell(cell, HEADER_FILL_HEX)

    for idx, cls in enumerate(classes, 1):
        info_row = t.rows[1 + 2 * (idx - 1)]
        path_row = t.rows[1 + 2 * (idx - 1) + 1]
        info_row.cells[0].text = str(idx)
        info_row.cells[1].text = cls.get("design_id", "") or ""
        info_row.cells[2].text = f"Class {cls.get('class_name', '')}" if cls.get("class_name") else ""
        info_row.cells[3].text = (cls.get("description", "") or "")[:200]

        # 路径行：col0 固定 "路径"；col1-3 合并，多路径用换行
        path_row.cells[0].text = "路径"
        _shade_cell(path_row.cells[0], LABEL_FILL_HEX)
        merged = path_row.cells[1].merge(path_row.cells[2]).merge(path_row.cells[3])
        paths = cls.get("paths") or ([cls.get("path")] if cls.get("path") else [])
        paths = [p for p in paths if p]
        merged.text = ""
        if paths:
            p0 = merged.paragraphs[0]
            p0.add_run(paths[0]).font.size = Pt(10)
            for extra in paths[1:]:
                p = merged.add_paragraph()
                p.add_run(extra).font.size = Pt(10)
        # "路径" 单元格加粗
        for p in path_row.cells[0].paragraphs:
            for run in p.runs:
                run.bold = True
                run.font.size = Pt(10)

    return t


def _render_class_section(doc, cls: dict, prefix: str = ""):
    """单个类子节 — 对齐参考文档 Chapter 5 Class CNvMMax96724 结构：

        H3 Class {name}
        H4 类的成员常量列表    → table 或 "NA"
        H4 类的成员变量列表    → table 或 "NA"
        H4 函数列表            → 3 列总表 [设计 ID | 函数名 | 说明]（如果有焦点函数）
        H4 函数 {name}          → 调 _render_function_detail (每个焦点函数一节)
        H4 原始 NV 函数列表    → 3 列表（如果该类有非焦点 NV 函数）

    `prefix` 为该类的章节号（如 "4.2.1"）；非空时为所有子标题带上编号前缀。
    """
    class_name = cls.get("class_name", "")
    head = f"{prefix} Class {class_name}" if prefix else f"Class {class_name}"
    doc.add_heading(head, level=3)
    desc = (cls.get("description") or "").strip()
    if desc:
        doc.add_paragraph(desc)

    def _sub(n: int, label: str) -> str:
        return f"{prefix}.{n} {label}" if prefix else label

    sub_idx = 0

    # 成员常量
    consts = cls.get("constants") or []
    sub_idx += 1
    doc.add_heading(_sub(sub_idx, "类的成员常量列表"), level=4)
    if consts:
        _add_table(doc, ["序号", "成员常量", "类型", "值", "说明"],
                   [[c.get("seq", ""), c.get("name", ""), c.get("type", ""),
                     c.get("value", ""), c.get("desc", "")] for c in consts])
    else:
        doc.add_paragraph("NA")

    # 成员变量
    vars_ = cls.get("variables") or []
    sub_idx += 1
    doc.add_heading(_sub(sub_idx, "类的成员变量列表"), level=4)
    if vars_:
        _add_table(doc, ["序号", "成员变量", "类型", "说明"],
                   [[v.get("seq", ""), v.get("name", ""), v.get("type", ""), v.get("desc", "")]
                    for v in vars_])
    else:
        doc.add_paragraph("NA")

    # 类内焦点函数 — 对齐参考文档：先总表 + 每函数 H4 详情
    focus_fns = cls.get("functions") or []
    if focus_fns:
        # 补齐 design_id
        module_hint = class_name or "Class"
        for i, f in enumerate(focus_fns, 1):
            if not f.get("design_id"):
                f["design_id"] = f"D001-{module_hint}-function-{i:03d}"
        sub_idx += 1
        doc.add_heading(_sub(sub_idx, "函数列表"), level=4)
        _add_table(doc, ["设计 ID", "函数名", "说明"],
                   [[f.get("design_id", ""), f.get("name", ""),
                     (f.get("intro", "") or "")[:120]]
                    for f in focus_fns])
        for fn_idx, fn in enumerate(focus_fns, 1):
            sub_idx += 1
            fn_name = fn.get("name", "")
            head_text = _sub(sub_idx, f"函数 {fn_name}")
            _render_function_detail(doc, fn, heading_level=4, heading_override=head_text)

    # 类内 NV 原始函数（非焦点、SDK）— 子表只给 ID/名/说明
    nv_fns = cls.get("nv_functions") or []
    if nv_fns:
        sub_idx += 1
        doc.add_heading(_sub(sub_idx, "原始 NV 函数列表"), level=4)
        MAX_ROWS = 60
        shown = nv_fns[:MAX_ROWS]
        for i, f in enumerate(shown, 1):
            if not f.get("design_id"):
                f["design_id"] = f"NV-{class_name}-function-{i:03d}"
        _add_table(doc, ["设计 ID", "函数名", "说明"],
                   [[f.get("design_id", ""), f.get("name", ""),
                     (f.get("intro", "") or f.get("doc_comment", "") or "")[:120]]
                    for f in shown])
        if len(nv_fns) > MAX_ROWS:
            doc.add_paragraph(
                f"（仅列出前 {MAX_ROWS} 条，共 {len(nv_fns)} 条；完整清单见导出的 xlsx）"
            )


def _parse_bases(base_str: str) -> list[str]:
    """把 code_scanner 存的 base 字符串（可能是 'public A, protected B'）→ 纯类名列表。"""
    if not base_str:
        return []
    out: list[str] = []
    for part in base_str.split(","):
        tok = part.strip()
        for pre in ("public ", "protected ", "private ", "virtual "):
            if tok.lower().startswith(pre):
                tok = tok[len(pre):].strip()
        # 去掉命名空间（如 nvsipl::CNvMDevice → CNvMDevice）
        if "::" in tok:
            tok = tok.split("::")[-1]
        if tok:
            out.append(tok)
    return out


# 父类追溯：扫描时命中单文件后的产出会缓存到这里（key = engineering_root）
_PARENT_SEARCH_CACHE: dict[str, dict[str, list[dict]]] = {}


def _index_parent_candidates(eng_root: str) -> dict[str, list[dict]]:
    """遍历 engineering_src 一次，用快速正则（_CLASS_RE）定位每个 class 的声明文件。

    返回 {ClassName: [{"path": rel, "abs": abs}]}。缓存按 eng_root 复用。
    代价：一次全树扫描，但只做轻量 regex（没有函数解析），比完整 _scan_source 便宜一个量级。
    """
    cached = _PARENT_SEARCH_CACHE.get(eng_root)
    if cached is not None:
        return cached

    try:
        from app.core import code_scanner
    except Exception:
        return {}

    exts = {".h", ".hpp", ".hh"}  # 父类定义一般在头文件
    index: dict[str, list[dict]] = {}
    for cur, _dirs, files in os.walk(eng_root):
        for name in files:
            if os.path.splitext(name)[1].lower() not in exts:
                continue
            abs_path = os.path.join(cur, name)
            rel = os.path.relpath(abs_path, eng_root).replace("\\", "/")
            try:
                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read(300_000)   # 父类头文件一般小于 300KB
            except OSError:
                continue
            # 快速定位本文件声明了哪些 class
            try:
                for m in code_scanner._CLASS_RE.finditer(text):
                    cname = m.group("name")
                    if not cname:
                        continue
                    index.setdefault(cname, []).append({"path": rel, "abs": abs_path})
            except Exception:
                continue

    _PARENT_SEARCH_CACHE[eng_root] = index
    return index


def _scan_single_parent_class(eng_root: str, class_name: str,
                               index: dict[str, list[dict]]) -> Optional[dict]:
    """在 engineering_src 中找到 class_name 的定义文件，用 code_scanner 解析并返回该类条目。

    返回 derive_from_push_d_scan 期待的类 dict 结构，功能全部作为 nv_functions（非焦点）；
    聚合多文件（.hpp 声明 + .cpp 实现同在时合并路径）。找不到返回 None。
    """
    try:
        from app.core import code_scanner
    except Exception:
        return None

    hits = index.get(class_name) or []
    if not hits:
        return None

    merged: Optional[dict] = None
    for h in hits:
        rel = h["path"]
        abs_path = h["abs"]
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        if len(text) > 1_500_000:
            continue
        try:
            info = code_scanner._scan_source(rel, text)
        except Exception:
            continue
        for cls in info.get("classes") or []:
            if cls.get("name") != class_name:
                continue
            if merged is None:
                merged = {
                    "class_name": class_name,
                    "design_id": "",
                    "description": cls.get("doc_comment", "") or "",
                    "paths": [rel],
                    "base": cls.get("base", ""),
                    "constants": [],
                    "variables": [],
                    "functions": [],         # 父类无焦点函数
                    "nv_functions": [],      # 全部作为"原始 NV 函数列表"展开
                    "_fn_keys": set(),
                    "_parent_depth": 0,      # 占位，调用方会覆盖
                }
            else:
                if rel not in merged["paths"]:
                    merged["paths"].append(rel)
                if not merged.get("base") and cls.get("base"):
                    merged["base"] = cls.get("base", "")

            for c in cls.get("constants") or []:
                merged["constants"].append({
                    "seq": len(merged["constants"]) + 1,
                    "name": c.get("name", ""),
                    "type": c.get("type", ""),
                    "value": c.get("value", ""),
                    "desc": c.get("desc", ""),
                })
            for v in cls.get("variables") or []:
                merged["variables"].append({
                    "seq": len(merged["variables"]) + 1,
                    "name": v.get("name", ""),
                    "type": v.get("type", ""),
                    "desc": v.get("desc") or v.get("init") or "",
                })
            for fn in cls.get("functions") or []:
                fn_key = fn.get("key") or ""
                if fn_key in merged["_fn_keys"]:
                    continue
                merged["_fn_keys"].add(fn_key)
                merged["nv_functions"].append(_normalize_scanned_fn(fn, rel))
    if merged is not None:
        merged.pop("_fn_keys", None)
        merged["path"] = (merged["paths"] or [""])[0]
    return merged


def _trace_parent_classes(project_id: str, child_classes: list[dict],
                           max_depth: int = 3) -> list[dict]:
    """从 engineering_src 里追溯 child_classes 的基类，默认追 3 层。

    返回按 "最远基类 → 直接父类 → 子类" 顺序排列的完整类列表（含原始 child_classes）。
    追溯范围由 _index_parent_candidates 一次性建索引，避免反复 walk。
    """
    if not child_classes or max_depth <= 0:
        return list(child_classes or [])

    try:
        from app.core import engineering_store
    except Exception:
        return list(child_classes)

    eng_root = engineering_store.engineering_root(project_id)
    if not eng_root or not os.path.isdir(eng_root):
        return list(child_classes)

    index = _index_parent_candidates(eng_root)
    if not index:
        return list(child_classes)

    # existing_names：已存在的类（child 层）
    existing_names: set[str] = {
        (c.get("class_name") or c.get("name") or "") for c in child_classes
    }
    existing_names.discard("")

    # BFS，一层一层追
    ancestors_in_order: list[dict] = []     # 新发现的父类（后进后排，再反转为"远→近"）
    queue: list[tuple[str, int]] = []       # (需追溯的类名, 当前已追的层数)
    for c in child_classes:
        for b in _parse_bases(c.get("base") or ""):
            if b and b not in existing_names:
                queue.append((b, 1))

    visited: set[str] = set()
    while queue:
        name, depth = queue.pop(0)
        if name in visited or depth > max_depth:
            continue
        visited.add(name)
        parent = _scan_single_parent_class(eng_root, name, index)
        if parent is None:
            continue
        parent["_parent_depth"] = depth
        ancestors_in_order.append(parent)
        existing_names.add(name)
        # 继续追它的父类
        for b in _parse_bases(parent.get("base") or ""):
            if b and b not in existing_names and b not in visited:
                queue.append((b, depth + 1))

    # 让"最远的祖先"排最前，然后依次往下，最后才是原 child_classes
    ancestors_in_order.sort(key=lambda c: -(c.get("_parent_depth") or 0))
    return ancestors_in_order + list(child_classes)


def _derive_from_push_d_scan(module: dict, push_d: Optional[dict]) -> dict:
    """从推送 D 的 scan_cache + 关注函数 派生 classes / nv_original_functions / 独立函数。

    对齐参考文档《PreDev_详细设计V1.0_updated》Chapter 5 (Deserializer) 结构：
      - 每个类在"类列表"表里有多条路径（.hpp 声明 + .cpp 实现 → 合并单元格渲染为"路径"行）
      - 类内函数再分成两段：
          cls.focus_functions = 用户勾选的关注函数（跟随类走 → 渲染 H4 函数详情）
          cls.nv_functions    = 该类下非焦点的 NV 原始函数（渲染 "原始 NV 函数列表" 子表）
      - 类外的焦点函数（__free__ 作用域）走返回值 `functions`
      - 类外的 NV 函数走返回值 `nv_original_functions`（模块级兜底清单）

    返回 {"classes": [...], "functions": [...], "nv_original_functions": [...]}；
    若 push_d 不可用则返回 {}。
    """
    if not push_d:
        return {}
    try:
        from app.core import engineering_store
    except Exception:
        return {}

    cid = module.get("component_id") or ""
    project_id = push_d.get("_project_id")
    if not project_id or not cid:
        return {}
    scan = engineering_store.read_scan_cache(project_id, cid)
    if not scan or not scan.get("files"):
        return {}

    focused_keys: set[str] = set()
    for ff in push_d.get("focus_functions") or []:
        if ff.get("component_id") == cid:
            focused_keys = set(ff.get("focused_keys") or [])
            break

    # 聚合跨文件同名类（NvSIPL 实现经常在 .h 声明、在 .cpp 定义，扫描后两边都会有记录）
    classes_by_name: dict[str, dict] = {}
    free_focus_funcs: list[dict] = []
    module_nv_funcs: list[dict] = []  # 类外的 NV 函数

    for file_info in scan.get("files") or []:
        is_sdk_file = bool(file_info.get("is_sdk"))
        path_rel = file_info.get("path", "")
        for cls in file_info.get("classes") or []:
            cname = cls.get("name") or ""
            if not cname or cname == "__free__":
                # 独立函数（没有类作用域的）— 不进任何类
                # 焦点优先：用户勾选的 key 一律进 focus，哪怕来自 SDK 文件
                for fn in cls.get("functions") or []:
                    if fn.get("key") in focused_keys:
                        fn_norm = _normalize_scanned_fn(fn, path_rel)
                        free_focus_funcs.append(fn_norm)
                    else:
                        # NV / 非焦点函数：lite 模式，跳过 body→PlantUML 解析（OOM 保护）
                        fn_norm = _normalize_scanned_fn(fn, path_rel, lite=True)
                        module_nv_funcs.append(fn_norm)
                continue
            entry = classes_by_name.setdefault(cname, {
                "class_name": cname,
                "design_id": "",
                "description": "",
                "paths": [],           # 多路径（.hpp + .cpp）— 对齐参考文档"路径"合并行
                "base": cls.get("base", ""),
                "constants": [],
                "variables": [],
                "functions": [],        # 焦点函数（渲染详情表）
                "nv_functions": [],     # 本类下的 NV / 非焦点函数（只进 "原始 NV 函数列表" 子表）
                "_fn_keys": set(),      # 去重（key 一致则同一函数在不同文件只收一次）
            })
            # 聚合路径（跨文件同名类）
            if path_rel and path_rel not in entry["paths"]:
                entry["paths"].append(path_rel)
            # 继承签名以第一次见到的为准
            if not entry.get("base") and cls.get("base"):
                entry["base"] = cls.get("base", "")
            # 合并 constants / variables
            for c in cls.get("constants") or []:
                entry["constants"].append({
                    "seq": len(entry["constants"]) + 1,
                    "name": c.get("name", ""),
                    "type": c.get("type", ""),
                    "value": c.get("value", ""),
                    "desc": c.get("desc", ""),
                })
            for v in cls.get("variables") or []:
                entry["variables"].append({
                    "seq": len(entry["variables"]) + 1,
                    "name": v.get("name", ""),
                    "type": v.get("type", ""),
                    "desc": v.get("desc") or v.get("init") or "",
                })
            # 函数分流：
            #   焦点（无论来自 SDK 还是项目文件）→ 该类的 functions 渲染详情
            #   非焦点 → 该类的 nv_functions 只进"原始 NV 函数列表"子表
            # 注意：扫描时整个 nvsipl SDK 树会被标 is_sdk=True，但用户勾选的焦点函数
            # 本质就是"要在详细设计里展开的函数"，不该因为 is_sdk 掩盖。
            for fn in cls.get("functions") or []:
                fn_key = fn.get("key") or ""
                if fn_key in entry["_fn_keys"]:
                    continue
                entry["_fn_keys"].add(fn_key)
                if fn_key in focused_keys:
                    fn_norm = _normalize_scanned_fn(fn, path_rel)
                    entry["functions"].append(fn_norm)
                else:
                    # NV / 非焦点函数：lite 模式，跳过昂贵的 body→PlantUML 解析
                    fn_norm = _normalize_scanned_fn(fn, path_rel, lite=True)
                    entry["nv_functions"].append(fn_norm)

    # 收尾：删除内部辅助字段 + 按 (name, parameters-signature) 去重同名双录
    #       （同一函数的 .hpp 声明 + .cpp 实现会产生两条 key 不同的记录，
    #        这里按 body_lines 更大的保留 — 即实现胜过声明。）
    def _dedupe_fns(fns: list[dict]) -> list[dict]:
        picked: dict[str, dict] = {}
        for f in fns:
            # 用 name + 归一化参数类型 作为去重键
            # 为什么要归一化：同一函数的 .hpp 声明 vs .cpp 实现，参数类型文本可能差
            # 一个空格（"const *const" vs "const * const"），直接拼签名会错失去重。
            # 这里压掉所有空白再比较类型；参数名不参与去重（.hpp 常省略）。
            params = f.get("parameters") or []
            type_sig = ",".join(
                re.sub(r"\s+", "", (p.get("type", "") if isinstance(p, dict) else str(p)))
                for p in params
            )
            k = f"{f.get('name','')}({type_sig})"
            prev = picked.get(k)
            if prev is None:
                picked[k] = f
                continue
            # 已有一份：按 body_lines 大的保留；相同则 intro/ai_intro 更全的
            if (f.get("body_lines") or 0) > (prev.get("body_lines") or 0):
                picked[k] = f
            elif (f.get("body_lines") or 0) == (prev.get("body_lines") or 0):
                if (f.get("ai_intro") or f.get("intro")) and not (prev.get("ai_intro") or prev.get("intro")):
                    picked[k] = f
        return list(picked.values())

    classes_out: list[dict] = []
    for i, entry in enumerate(classes_by_name.values(), 1):
        entry.pop("_fn_keys", None)
        entry["functions"] = _dedupe_fns(entry["functions"])
        entry["nv_functions"] = _dedupe_fns(entry["nv_functions"])
        # path 字段保留一份字符串（兼容老代码读 entry["path"]）
        entry["path"] = (entry["paths"] or [""])[0]
        classes_out.append(entry)

    free_focus_funcs = _dedupe_fns(free_focus_funcs)
    module_nv_funcs = _dedupe_fns(module_nv_funcs)

    # 父类追溯：从 module 的 parent_trace_depth 读深度（默认 3 层，可被单模块关掉设 0）
    # 对齐用户反馈："max96717的uml图应该生成如图所示但目前生成函数很少，建议父类可以调整层级，默认追踪三级父类"
    depth = module.get("parent_trace_depth")
    if depth is None:
        depth = 3
    try:
        depth = int(depth)
    except (TypeError, ValueError):
        depth = 3
    if depth > 0:
        classes_out = _trace_parent_classes(project_id, classes_out, max_depth=depth)
        # 父类的 nv_functions 再过一遍 dedupe（父类扫到的 .hpp/.cpp 双录同样会出现）
        for entry in classes_out:
            entry["nv_functions"] = _dedupe_fns(entry.get("nv_functions") or [])

    # 补齐 design_id（按最终顺序，确保父类+子类不冲突 D001-...-class-001）
    for i, entry in enumerate(classes_out, 1):
        entry["design_id"] = f"D{i:03d}-{module.get('name','')}-class-{i:03d}"

    return {
        "classes": classes_out,
        "functions": free_focus_funcs,
        "nv_original_functions": module_nv_funcs,
    }


def _synthesize_class_diagram(classes: list[dict]) -> str:
    """从扫描派生出的类数据合成一张 PlantUML 类图作为无 AI 时的后备。

    - 列出类名 + 基类继承关系（base 字段可能是 "public A, protected B" 的字符串）
    - 把每个类的**成员常量 / 成员变量 / 所有函数**（焦点 + NV）都列进 UML
      → 对齐参考文档 Chapter 5 的"完整类图"要求，不再截断前 6 个
    - 外部基类用 `<<external>>` 标注，避免 PlantUML 画成空类
    """
    if not classes:
        return ""

    def _bases_of(base_str: str) -> list[str]:
        # 复用模块级 _parse_bases（统一基类字符串归一规则，支持 namespace::Name → Name）
        return _parse_bases(base_str)

    def _plant_safe(s: str) -> str:
        """PlantUML 成员名清洗：去空白换行、裁掉特殊符号；超长截断。"""
        s = re.sub(r"\s+", " ", (s or "")).strip()
        s = s.replace("{", "").replace("}", "").replace("|", "/")
        if len(s) > 80:
            s = s[:80] + "…"
        return s

    MAX_FUNCS_PER_CLASS = 20          # 类成员过多时的硬上限，避免图宽度爆炸
    MAX_CONSTS_PER_CLASS = 15
    MAX_VARS_PER_CLASS = 15

    lines = [
        "@startuml",
        "skinparam classAttributeIconSize 0",
        "skinparam defaultFontName \"PingFang SC, Microsoft YaHei, Segoe UI\"",
        "skinparam defaultFontSize 11",
        "hide empty members",
    ]
    base_names: set[str] = set()
    cls_names: set[str] = set()

    for cls in classes:
        name = cls.get("class_name") or cls.get("name") or ""
        if not name:
            continue
        cls_names.add(name)

        consts = (cls.get("constants") or [])[:MAX_CONSTS_PER_CLASS]
        vars_ = (cls.get("variables") or [])[:MAX_VARS_PER_CLASS]
        all_fns: list[dict] = list(cls.get("functions") or []) + list(cls.get("nv_functions") or [])
        # 去重后保留顺序
        seen: set[str] = set()
        uniq_fns: list[dict] = []
        for fn in all_fns:
            fname = fn.get("name") or ""
            if not fname or fname in seen:
                continue
            seen.add(fname)
            uniq_fns.append(fn)
        funcs = uniq_fns[:MAX_FUNCS_PER_CLASS]

        has_body = bool(consts or vars_ or funcs)
        if has_body:
            lines.append(f"class {name} {{")
            # 成员常量：前缀 '+ {static}' 以示区别
            for c in consts:
                cname = _plant_safe(c.get("name", ""))
                ctype = _plant_safe(c.get("type", ""))
                if cname:
                    piece = f"  + {{static}} {cname}" + (f" : {ctype}" if ctype else "")
                    lines.append(piece)
            # 成员变量：'-' 私有
            for v in vars_:
                vname = _plant_safe(v.get("name", ""))
                vtype = _plant_safe(v.get("type", ""))
                if vname:
                    piece = f"  - {vname}" + (f" : {vtype}" if vtype else "")
                    lines.append(piece)
            # 函数：'+' 公有（扫描无法可靠分辨 public/private，统一用 +，avoid misleading UML）
            for fn in funcs:
                fname = _plant_safe(fn.get("name", ""))
                if fname:
                    lines.append(f"  + {fname}()")
            total_fns = len(uniq_fns)
            if total_fns > MAX_FUNCS_PER_CLASS:
                lines.append(f"  + ...（{total_fns - MAX_FUNCS_PER_CLASS} more）")
            lines.append("}")
        else:
            lines.append(f"class {name}")

        for b in _bases_of(cls.get("base") or ""):
            base_names.add(b)
            lines.append(f"{b} <|-- {name}")

    # 外部基类（扫描里没见过的）单独标出，避免 PlantUML 把它当实体画成空类
    for b in sorted(base_names - cls_names):
        lines.append(f"class {b} <<external>>")

    lines.append("@enduml")
    return "\n".join(lines)


def _safe_build_plantuml(body: str, decl: str, *, budget_sec: float = 3.0,
                         fn_name: str = "") -> str:
    """包一层超时守卫调 build_plantuml_from_body。

    动机：scanner 偶尔把多个函数体粘到一个 body_text 里（body 结尾缺 `}`
    或嵌套结构解析错），`cpp_flow_to_plantuml.parse_body` 对这种畸形输入
    可能死循环。给它 budget_sec 秒预算，超时就返回空串 → 上层回退到
    AI / 手工 flowchart。

    实现：用 daemon 线程 + join(timeout)。超时后放弃该 daemon（它会继续
    空转一会，但进程退出时自动死）。注意：daemon thread 不可被 kill，所以
    极坏情况下累计大量僵尸线程 → 因此 budget 要短（≤3s）+ 上游应已把一批
    畸形 body 过滤掉。`signal.SIGALRM` 方案不可用：FastAPI 把路由跑在
    `asyncio.to_thread` 的 worker thread 里，SIGALRM 只能主线程注册。
    """
    import threading, logging
    from app.core.cpp_flow_to_plantuml import build_plantuml_from_body
    log = logging.getLogger(__name__)

    result: dict = {"val": "", "err": None}

    def _worker():
        try:
            result["val"] = build_plantuml_from_body(body, decl).strip()
        except Exception as e:
            result["err"] = e

    t = threading.Thread(target=_worker, name=f"plantuml-{fn_name or '?'}",
                         daemon=True)
    t.start()
    t.join(timeout=budget_sec)
    if t.is_alive():
        log.warning(
            f"build_plantuml_from_body 超时 >{budget_sec}s 放弃解析 "
            f"fn={fn_name!r} body_len={len(body)}；回退到 AI/手工 flowchart"
        )
        return ""
    if result["err"] is not None:
        log.warning(
            f"build_plantuml_from_body 异常 {result['err']!r} 放弃解析 fn={fn_name!r}"
        )
        return ""
    return result["val"]


def _normalize_scanned_fn(fn: dict, file_path: str = "", *, lite: bool = False) -> dict:
    """把 code_scanner.Swe3ScannedFunction + AI augmented 字段 → _render_function_detail 期望的字段名。

    - intro ← ai_intro（AI 补的）或 fn.intro（手工填）或 doc_comment
    - flowchart_plantuml ← 真实源码解析（优先）→ ai_flowchart → fn.flowchart_plantuml
    - description ← fn.description（给表后"功能说明"段用，没有就留空）

    介绍统一过一遍 compress_intro：老项目 scan_cache 里存的长文（prompt 改版前生成的）
    也需要在导出时被压短，否则表格撑得很难看。

    流程图来源的优先级重排：
      - 新：优先走 `cpp_flow_to_plantuml` 用真实 body_text 解析（和前端"代码分析"
        页同一套逻辑，离线确定性，分支结构 100% 对；长流程自动切泳道横向排布）
      - 回退：AI 生成的 ai_flowchart
      - 再回退：手工 flowchart_plantuml

    lite 模式（R4.2，仅给 NV / 非焦点函数用）：
      - 跳过 compress_intro（不进 OpenAI 调用）
      - 跳过 build_plantuml_from_body（不解析 body AST → 节省内存和 CPU）
      - 用 fn.ai_flowchart / fn.flowchart_plantuml 作兜底；都没有就空
      - A005 426 fn / A006 2355 fn 时这一步是 OOM 根因，lite 模式下批量 < 1s
    """
    if not lite:
        from app.core.swe3_ai import compress_intro
        from app.core.cpp_flow_to_plantuml import build_plantuml_from_body

    intro = (fn.get("intro") or fn.get("ai_intro") or "").strip()
    if not intro:
        # 只有 doc 注释时，作为回退（截短，避免整段 Doxygen 注释直接贴）
        doc_comment = (fn.get("doc_comment") or "").strip()
        if doc_comment:
            intro = doc_comment[:400]
    if not lite:
        intro = compress_intro(intro)
    else:
        # lite：手动截断，不走 AI 压缩
        if len(intro) > 200:
            intro = intro[:200] + "…"

    # 流程图：真实源码 >> AI >> 手工
    flow = ""
    if not lite:
        body = (fn.get("body_text") or "").strip()
        if body:
            # 对异常函数体（scanner 把多个函数粘成一块，常见于缺 `}` 时）
            # `build_plantuml_from_body` 曾出现死循环。加 3 秒硬超时兜底：
            # 超时就放弃本函数的源码解析，回退到 AI/手工 flow。
            flow = _safe_build_plantuml(
                body, fn.get("declaration", ""), budget_sec=3.0,
                fn_name=fn.get("name", ""),
            )
    if not flow:
        flow = (fn.get("flowchart_plantuml") or fn.get("ai_flowchart") or "").strip()

    return {
        "key": fn.get("key", ""),
        "name": fn.get("name", ""),
        "design_id": fn.get("design_id", ""),
        "declaration": (fn.get("declaration") or "").strip(),
        "parameters": fn.get("parameters") or [],
        "returns": fn.get("returns") or [],
        "intro": intro,
        "description": (fn.get("description") or "").strip(),
        "flowchart_plantuml": flow,
        "_file": file_path,
        "is_sdk": fn.get("is_sdk", False),
        # 推送 G R4：把四态元数据带到渲染层，供 _resolve_flowchart_placeholder 决定占位文案
        "ai_status": fn.get("ai_status", ""),
        "ai_last_error": fn.get("ai_last_error", ""),
        "ai_exception_note": fn.get("ai_exception_note", ""),
        "ai_retry_count": fn.get("ai_retry_count", 0),
        "exempt_from_ai": bool(fn.get("exempt_from_ai", False)),
        "diff_status": fn.get("diff_status", ""),
    }


def _render_module_section(doc, module: dict, chapter_no: int, push_d: Optional[dict] = None):
    """渲染第 4~N 章单个模块的完整详细设计。

    章节序号对齐参考文档 Chapter 5 布局：
      {N}   {模块标题}                      ← H1
      {N}.1 类图                            ← H2
      {N}.2 类列表                          ← H2
      {N}.2.{i} Class {name}                ← H3
        {N}.2.{i}.1 类的成员常量列表         ← H4
        {N}.2.{i}.2 类的成员变量列表         ← H4
        {N}.2.{i}.3 函数列表                 ← H4
        {N}.2.{i}.4 函数 {X}                 ← H4（逐函数）
        {N}.2.{i}.K 原始 NV 函数列表         ← H4
      {N}.3 {模块名} 详细设计（独立焦点）    ← H2（可选）
        {N}.3.1 函数列表                    ← H3
        {N}.3.2 函数 {X}                    ← H3（逐函数）
        {N}.3.N 原始 NV 函数列表             ← H3
      {N}.{last} 单元时序图                 ← H2
    """
    chapter = str(chapter_no)
    title = module.get("title") or f"模块{module.get('name', '')}详细设计"
    doc.add_heading(f"{chapter} {title}", level=1)

    # Camera Security 专用：功能安全目标 + 流程设计（放最前，参考文档结构）
    sec_idx = 0        # H2 子节号游标
    if module.get("component_id") == "A008":
        sec_idx += 1
        goals = module.get("security_goals") or {}
        doc.add_heading(f"{chapter}.{sec_idx} Camera Security 功能安全目标", level=2)
        doc.add_heading(f"{chapter}.{sec_idx}.1 身份验证与授权要求（Authentication and Authorization）", level=3)
        doc.add_paragraph(goals.get("authentication") or "<待填充>")
        doc.add_heading(f"{chapter}.{sec_idx}.2 数据保护要求（Data Protection）", level=3)
        doc.add_paragraph(goals.get("data_protection") or "<待填充>")
        doc.add_heading(f"{chapter}.{sec_idx}.3 密钥管理要求（Key Management）", level=3)
        doc.add_paragraph(goals.get("key_management") or "<待填充>")

        flow = module.get("flow_design") or {}
        sec_idx += 1
        doc.add_heading(f"{chapter}.{sec_idx} Camera Security 软件流程设计", level=2)
        sub = 0
        if flow.get("detailed_plan"):
            sub += 1
            doc.add_heading(f"{chapter}.{sec_idx}.{sub} 详细开发方案", level=3)
            doc.add_paragraph(flow["detailed_plan"])
        if flow.get("implementation"):
            sub += 1
            doc.add_heading(f"{chapter}.{sec_idx}.{sub} 实现流程", level=3)
            doc.add_paragraph(flow["implementation"])
        sub += 1
        doc.add_heading(f"{chapter}.{sec_idx}.{sub} camera security 动态流程图", level=3)
        _add_plantuml_image(doc, flow.get("flowchart_plantuml") or "",
                             "Camera Security 动态流程图", width_inches=5.5)

    # 优先从推送 D 扫描结果派生类/函数（当手工 SWE.3 数据为空时）
    classes = module.get("classes") or []
    functions = module.get("functions") or []
    nv_funcs = module.get("nv_original_functions") or []
    if not classes and not functions:
        derived = _derive_from_push_d_scan(module, push_d)
        if derived:
            classes = derived.get("classes") or []
            functions = derived.get("functions") or []
            # 用户没显式填 nv_original_functions 时也用扫描派生的
            if not nv_funcs:
                nv_funcs = derived.get("nv_original_functions") or []

    # 类图：优先用 module 上的 AI/手工 PlantUML，否则从派生类自动合成（不再是文字占位）
    sec_idx += 1
    doc.add_heading(f"{chapter}.{sec_idx} 类图", level=2)
    class_diagram = (module.get("class_diagram_plantuml") or "").strip()
    if not class_diagram and classes:
        class_diagram = _synthesize_class_diagram(classes)
    _add_plantuml_image(doc, class_diagram,
                         f"{module.get('name', '')} 类图", width_inches=5.5)

    # 类列表 —— 对齐参考文档 Chapter 5：
    #   H2 类列表 → 带"路径"合并行的 4 列总表
    #   每类 H3 Class {name} → H4 常量/变量/函数列表/逐函数详情/原始 NV 函数列表
    module_name = module.get("name", "")
    sec_idx += 1
    classes_sec = sec_idx
    doc.add_heading(f"{chapter}.{classes_sec} 类列表", level=2)
    if classes:
        _add_class_list_table(doc, classes)
        for ci, cls in enumerate(classes, 1):
            _render_class_section(doc, cls, prefix=f"{chapter}.{classes_sec}.{ci}")
    else:
        doc.add_paragraph("<待推送 D 的 AI 从头文件提取类列表>")

    # 独立焦点函数（__free__ 作用域）— 放在 H2 "{模块名} 详细设计" 下
    # 对齐参考文档 Chapter 5 下的 H2 "MAX96724详细设计" → H3 "函数列表" + 每函数 H4
    free_funcs = list(functions or [])
    # 模块级 "原始 NV 函数" —— 类外的 NV 函数（通常不多，但有些模块的 NV API 是函数式而不是类的方法）
    module_level_nv = list(nv_funcs or [])

    if free_funcs or module_level_nv:
        sec_idx += 1
        detail_sec = sec_idx
        doc.add_heading(f"{chapter}.{detail_sec} {module_name} 详细设计", level=2)
        detail_sub = 0

        if free_funcs:
            # 补齐 design_id
            for i, f in enumerate(free_funcs, 1):
                if not f.get("design_id"):
                    f["design_id"] = f"D001-{module_name}-function-{i:03d}"
            detail_sub += 1
            doc.add_heading(f"{chapter}.{detail_sec}.{detail_sub} 函数列表", level=3)
            _add_table(doc, ["设计 ID", "函数名", "说明"],
                       [[f.get("design_id", ""), f.get("name", ""),
                         (f.get("intro", "") or "")[:120]]
                        for f in free_funcs])
            for fn in free_funcs:
                detail_sub += 1
                fn_name = fn.get("name", "")
                head_text = f"{chapter}.{detail_sec}.{detail_sub} 函数 {fn_name}"
                _render_function_detail(doc, fn, heading_level=3,
                                         heading_override=head_text)

        if module_level_nv:
            detail_sub += 1
            doc.add_heading(
                f"{chapter}.{detail_sec}.{detail_sub} 原始 NV 函数列表（{len(module_level_nv)}）",
                level=3,
            )
            MAX_NV_ROWS = 60
            shown = module_level_nv[:MAX_NV_ROWS]
            for i, f in enumerate(shown, 1):
                if not f.get("design_id"):
                    f["design_id"] = f"NV-{module_name}-function-{i:03d}"
            _add_table(doc, ["设计 ID", "函数名", "说明"],
                       [[f.get("design_id", ""), f.get("name", ""),
                         (f.get("intro", "") or f.get("doc_comment", "") or "")[:120]]
                        for f in shown])
            if len(module_level_nv) > MAX_NV_ROWS:
                doc.add_paragraph(
                    f"（仅列出前 {MAX_NV_ROWS} 条，共 {len(module_level_nv)} 条；"
                    f"完整清单见导出的 xlsx 的「原始 NV 函数」sheet）"
                )

    # 单元时序图
    sec_idx += 1
    doc.add_heading(f"{chapter}.{sec_idx} {module_name} 单元时序图", level=2)
    _add_plantuml_image(doc, module.get("sequence_plantuml") or "",
                         f"{module_name} 单元时序图", width_inches=5.5)

    # 推送 D 扫描结果已融入上面的类列表 + 函数列表，不再单独起 4.6 节


def _render_push_d_scan(doc, module: dict, push_d: dict):
    """推送 D 扫描结果附录 — 原始 NV 函数清单 + 其余项目函数清单。

    关注函数的详细信息已通过 modules[*].classes/functions 流入正文，这里不再重复。
    """
    from app.core import engineering_store

    cid = module.get("component_id") or ""
    project_id = push_d.get("_project_id")
    if not project_id:
        return
    scan = engineering_store.read_scan_cache(project_id, cid)
    if not scan or not scan.get("files"):
        return

    # 找该模块的 focus
    focused_keys: set[str] = set()
    for ff in push_d.get("focus_functions") or []:
        if ff.get("component_id") == cid:
            focused_keys = set(ff.get("focused_keys") or [])
            break

    # 遍历 scan：剔除关注函数，剩下分 SDK/非 SDK
    sdk_other: list[tuple[str, str, dict]] = []
    custom_other: list[tuple[str, str, dict]] = []
    for file_info in scan.get("files") or []:
        for cls in file_info.get("classes") or []:
            for fn in cls.get("functions") or []:
                if fn.get("key") in focused_keys:
                    continue
                tup = (file_info.get("path", ""), cls.get("name", "__free__"), fn)
                if fn.get("is_sdk"):
                    sdk_other.append(tup)
                else:
                    custom_other.append(tup)

    if sdk_other:
        doc.add_heading(f"原始 NV 扫描函数清单（{len(sdk_other)}）", level=2)
        _add_table(doc, ["文件", "类/作用域", "函数名", "简介"],
                   [[fp, cn, fn.get("name", ""),
                     (fn.get("doc_comment") or "")[:60]] for fp, cn, fn in sdk_other])

    if custom_other:
        doc.add_heading(f"其余项目函数清单（{len(custom_other)}）", level=2)
        _add_table(doc, ["文件", "类/作用域", "函数名"],
                   [[fp, cn, fn.get("name", "")] for fp, cn, fn in custom_other])


# ---- 性能分析设计 ----

def _render_performance(doc, swe3: dict, chapter_no: int):
    doc.add_heading(f"{chapter_no} 性能分析设计", level=1)
    perf = swe3.get("performance") or {}
    _add_paragraphs(doc, perf.get("paragraphs") or sections3.DEFAULT_PERF_PARAGRAPHS)


# ---- 函数设计评估 ----

def _render_function_evaluation(doc, swe3: dict, chapter_no: int):
    doc.add_heading(f"{chapter_no} 函数设计评估", level=1)
    fe = swe3.get("function_evaluation") or {}
    _add_paragraphs(doc, fe.get("paragraphs") or sections3.DEFAULT_FUNC_EVAL_PARAGRAPHS)

    doc.add_heading(f"{chapter_no}.1 函数修改涉及的影响范围", level=2)
    _add_paragraphs(doc, fe.get("impact_paragraphs") or sections3.DEFAULT_FUNC_IMPACT_PARAGRAPHS)

    doc.add_heading(f"{chapter_no}.2 边界值分析", level=2)
    bv = fe.get("boundary_analysis") or []
    if bv:
        _add_table(doc, ["设计 ID", "函数名", "边界值分析说明"],
                   [[b.get("design_id", ""), b.get("func_name", ""), b.get("analysis", "")]
                    for b in bv])
    else:
        doc.add_paragraph("<待 AI 根据各函数入参生成边界值分析>")


# ---- 共通定义 ----

def _render_common_defs(doc, swe3: dict, chapter_no: int):
    doc.add_heading(f"{chapter_no} 共通定义", level=1)
    cd = swe3.get("common_defs") or {}

    doc.add_heading(f"{chapter_no}.1 常量", level=2)
    doc.add_paragraph("这里的常量是指项目的常量类，类属常量已经在类中进行了说明，不再多做说明。")
    consts = cd.get("constants") or sections3.DEFAULT_COMMON_CONSTANTS
    _add_table(doc, ["序号", "常量名", "值", "说明"],
               [[c.get("seq", ""), c.get("name", ""), c.get("value", ""), c.get("desc", "")]
                for c in consts])

    doc.add_heading(f"{chapter_no}.2 变量", level=2)
    doc.add_paragraph("本程序系统中使用的全局数据变量。")
    vars_ = cd.get("variables") or sections3.DEFAULT_COMMON_VARIABLES
    _add_table(doc, ["序号", "常量名", "类型", "值", "说明"],
               [[v.get("seq", ""), v.get("name", ""), v.get("type", ""),
                 v.get("value", ""), v.get("desc", "")] for v in vars_])

    doc.add_heading(f"{chapter_no}.3 枚举", level=2)
    enums = cd.get("enums") or sections3.DEFAULT_COMMON_ENUMS
    for idx, enum in enumerate(enums):
        doc.add_heading(f"{chapter_no}.3.{idx + 1} Enum {enum.get('name', '')}", level=3)
        _add_table(doc, ["序号", "枚举值", "说明"],
                   [[v.get("seq", ""), v.get("value", ""), v.get("desc", "")]
                    for v in enum.get("values", [])])

    doc.add_heading(f"{chapter_no}.4 结构体", level=2)
    structs = cd.get("structures") or sections3.DEFAULT_COMMON_STRUCTS
    for idx, s in enumerate(structs):
        doc.add_heading(f"{chapter_no}.4.{idx + 1} Structure {s.get('name', '')}", level=3)
        rows = [["结构体声明", s.get("declaration", "") or "<待填充>", ""],
                ["结构体介绍", s.get("intro", "") or "<待填充>", ""]]
        for f in s.get("fields", []):
            rows.append([f.get("name", ""), f.get("type", ""), f.get("desc", "")])
        _add_table(doc, ["字段", "类型", "说明"], rows)

    doc.add_heading(f"{chapter_no}.5 配置文件", level=2)
    cfg = cd.get("config_files") or sections3.DEFAULT_COMMON_CONFIG_FILES
    _add_table(doc, ["序号", "位置", "功能"],
               [[c.get("seq", ""), c.get("location", ""), c.get("function", "")] for c in cfg])


# ---- 系统集成 ----

def _render_sys_integration(doc, swe3: dict, chapter_no: int):
    doc.add_heading(f"{chapter_no} 系统集成", level=1)
    si = swe3.get("integration") or {}
    _add_paragraphs(doc, si.get("paragraphs") or sections3.DEFAULT_SYS_INTEGRATION_PARAGRAPHS)


# ---- 主入口 ----

def export_swe3_docx(project: dict, out_path: str) -> str:
    """程序化生成 SWE.3 软件详细设计 docx（14 章完整骨架）。

    章节号动态计算：11/12/13/14 跟随实际渲染的模块数量，避免关闭 Camera Security 时
    出现跳号或和模块号冲突。
    """
    from docx import Document

    aspice = project.get("aspice", {}) or {}
    swe2 = aspice.get("swe2", {}) or {}
    swe3 = aspice.get("swe3") or sections3.default_swe3()
    project_code = aspice.get("project_code", "") or project.get("name", "")
    meta = project.get("meta", {}) or {}

    doc = Document()
    _render_cover(doc, project_code, meta)
    _render_history_review(doc, project)
    _render_overview(doc, swe3, project_code)
    _render_terms(doc, swe3)
    _render_composition(doc, swe3, swe2)

    # 推送 D：Camera Security 开关控制 A008 是否渲染
    push_d = swe3.get("push_d") or {}
    has_security = push_d.get("has_camera_security", True)
    push_d_for_render = dict(push_d) if push_d else {}
    push_d_for_render["_project_id"] = project.get("project_id")

    # 4~N 各模块（按出现顺序渲染，章节号连续；关闭 Camera Security 时跳过 A008）
    modules = swe3.get("modules") or []
    chapter_no = 4
    for module in modules:
        if not has_security and module.get("component_id") == "A008":
            continue
        _render_module_section(doc, module, chapter_no=chapter_no,
                                push_d=push_d_for_render if push_d else None)
        chapter_no += 1

    # 后续章节号 = 模块块后紧接着的编号
    _render_performance(doc, swe3, chapter_no); chapter_no += 1
    _render_function_evaluation(doc, swe3, chapter_no); chapter_no += 1
    _render_common_defs(doc, swe3, chapter_no); chapter_no += 1
    _render_sys_integration(doc, swe3, chapter_no)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    doc.save(out_path)
    return out_path


def export_swe3_xlsx(project: dict, out_path: str) -> str:
    """SWE.3 多 sheet 导出：
      - 模块构成追溯（第 3 章）
      - 类列表（跨模块合并）
      - 函数列表（跨模块合并，带设计 ID）
      - 枚举（第 13 章）
      - 结构体字段（第 13 章）
      - 边界值分析（第 12 章）
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    aspice = project.get("aspice", {}) or {}
    swe2 = aspice.get("swe2", {}) or {}
    swe3 = aspice.get("swe3") or sections3.default_swe3()
    modules = swe3.get("modules") or []

    wb = Workbook()
    header_font = Font(bold=True)
    header_fill = PatternFill(start_color="DEEBF6", end_color="DEEBF6", fill_type="solid")

    def _write_sheet(ws, headers, rows):
        for i, h in enumerate(headers, 1):
            c = ws.cell(row=1, column=i, value=h)
            c.font = header_font
            c.fill = header_fill
        for r_idx, row in enumerate(rows, 2):
            for c_idx, val in enumerate(row, 1):
                ws.cell(row=r_idx, column=c_idx, value=val if val is not None else "")

    # Sheet 1：模块构成追溯
    ws1 = wb.active
    ws1.title = "模块构成追溯"
    comp = swe3.get("composition") or {}
    rows = comp.get("composition_rows") or sections3.build_composition_from_swe2(swe2)
    _write_sheet(ws1, ["SWE.1", "需求描述", "SWE.2", "对应组件", "功能模块图中的类", "SWE.3"],
                 [[r.get("swe1_id", ""), r.get("req_desc", ""), r.get("swe2_id", ""),
                   r.get("component", ""), r.get("classes", ""), r.get("swe3_ids", "")] for r in rows])

    # Sheet 2：类列表（跨模块）
    ws2 = wb.create_sheet("类列表")
    cls_rows = []
    for m in modules:
        for c in m.get("classes") or []:
            cls_rows.append([m.get("name", ""), c.get("design_id", ""), c.get("class_name", ""),
                             c.get("path", ""), c.get("description", "")])
    _write_sheet(ws2, ["模块", "设计 ID", "类名", "路径", "说明"], cls_rows)

    # Sheet 3：函数列表（跨模块：类内函数 + 独立函数）
    ws3 = wb.create_sheet("函数列表")
    func_rows = []
    for m in modules:
        mname = m.get("name", "")
        for c in m.get("classes") or []:
            cname = c.get("class_name", "")
            for f in c.get("functions") or []:
                func_rows.append([mname, cname, f.get("design_id", ""),
                                   f.get("name", ""), f.get("intro", ""), f.get("declaration", "")])
        for f in m.get("functions") or []:
            func_rows.append([mname, "", f.get("design_id", ""),
                               f.get("name", ""), f.get("intro", ""), f.get("declaration", "")])
    _write_sheet(ws3, ["模块", "类名", "设计 ID", "函数名", "函数介绍", "函数声明"], func_rows)

    # Sheet 4：枚举
    ws4 = wb.create_sheet("枚举")
    enum_rows = []
    for e in (swe3.get("common_defs") or {}).get("enums") or sections3.DEFAULT_COMMON_ENUMS:
        for v in e.get("values", []):
            enum_rows.append([e.get("name", ""), v.get("seq", ""), v.get("value", ""), v.get("desc", "")])
    _write_sheet(ws4, ["枚举名", "序号", "枚举值", "说明"], enum_rows)

    # Sheet 5：结构体字段
    ws5 = wb.create_sheet("结构体")
    struct_rows = []
    for s in (swe3.get("common_defs") or {}).get("structures") or sections3.DEFAULT_COMMON_STRUCTS:
        for f in s.get("fields", []):
            struct_rows.append([s.get("name", ""), f.get("seq", ""), f.get("name", ""),
                                 f.get("type", ""), f.get("desc", "")])
    _write_sheet(ws5, ["结构体名", "序号", "字段名", "类型", "说明"], struct_rows)

    # Sheet 6：边界值分析
    ws6 = wb.create_sheet("边界值分析")
    bv_rows = [[b.get("design_id", ""), b.get("func_name", ""), b.get("analysis", "")]
               for b in (swe3.get("function_evaluation") or {}).get("boundary_analysis") or []]
    _write_sheet(ws6, ["设计 ID", "函数名", "边界值分析"], bv_rows)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    wb.save(out_path)
    return out_path


def export_swe3(project: dict, out_dir: str) -> dict:
    """同时导出 docx + xlsx，返回文件名字典。"""
    project_code = (project.get("aspice", {}) or {}).get("project_code", "") or \
                   project.get("name", "project")
    safe = "".join(c for c in project_code if c.isalnum() or c in "._-") or "project"
    docx_name = f"{safe}_详细设计.docx"
    xlsx_name = f"{safe}_详细设计清单.xlsx"
    export_swe3_docx(project, os.path.join(out_dir, docx_name))
    export_swe3_xlsx(project, os.path.join(out_dir, xlsx_name))
    return {"docx": docx_name, "xlsx": xlsx_name}


# ============================================================================
# v2：模板引擎版本（docxtpl + swe3_detail.docx）
# ============================================================================
# F1 推送引入。老 _render_function_detail 等 1500 行拼装代码走旧 export_swe3_docx。
# v2 走 swe3_detail.docx 模板，样式/编号/页眉由模板承载。
# F1 范围：A001 Serializer + A003 EEPROM 两模块样板打通；F2 批量复刻剩余 7 模块。


def _norm_fn_to_schema(nfn: dict) -> dict:
    """R4.1：把 `_normalize_scanned_fn` 的产物映射成 Swe3Context.Function 需要的键。

    字段差异：
      intro        → brief
      description  → function_desc
      returns      → return_values
      parameters[i].desc → parameters[i].details
      returns[i].desc    → return_values[i].details
    其它字段（ai_status/exempt_from_ai/is_sdk/diff_status 等）也携带，供下游
    _resolve_flowchart_placeholder 决定占位文案；pydantic 未定义的会被丢弃，
    但模板层拿不到这些细节也不影响渲染。
    """
    name = nfn.get("name") or ""
    params = []
    for p in nfn.get("parameters") or []:
        if isinstance(p, dict):
            params.append({
                "name": p.get("name", ""),
                "type": p.get("type", ""),
                "details": p.get("details") or p.get("desc", ""),
            })
    rets = []
    for r in nfn.get("returns") or nfn.get("return_values") or []:
        if isinstance(r, dict):
            rets.append({
                "name": r.get("name", ""),
                "type": r.get("type", ""),
                "details": r.get("details") or r.get("desc", ""),
            })
    if not rets:
        rets = [{"name": "NVSIPL_STATUS_OK", "type": "SIPLStatus", "details": "函数执行成功"}]

    return {
        "name": name,
        "design_id": nfn.get("design_id", ""),
        "declaration": (nfn.get("declaration") or "").strip() or f"<待补充 {name} 声明>",
        "brief": (nfn.get("intro") or nfn.get("brief") or "").strip(),
        "parameters": params,
        "return_values": rets,
        "function_desc": (nfn.get("description") or nfn.get("function_desc") or "").strip(),
        "flowchart_plantuml": (nfn.get("flowchart_plantuml") or "").strip(),
    }


def _adapt_derived_module(derived: dict) -> dict:
    """R4.1：把 `_derive_from_push_d_scan` 的派生结构 → Swe3Context.Module 的键。

    派生结构：
      classes:    [{class_name, paths, constants, variables, functions:[nfn...], nv_functions:[nfn...]}, ...]
      functions:  类外焦点函数 [nfn...]
      nv_original_functions: 类外非焦点函数 [nfn...]
    目标结构：
      classes:        [ClassItem: {seq, design_id, class_name, description}]
      class_details:  [ClassDetail: {class_name, design_id, constants, variables}]
      functions:      [Function]  — 类内 + 类外的焦点全部拍平（渲染 H3/H4 函数详情）
      nv_functions:   [Function]  — 类内 + 类外的非焦点拍平
    """
    cls_src = derived.get("classes") or []
    free_focus = derived.get("functions") or []
    free_nv = derived.get("nv_original_functions") or []

    classes_items = []       # ClassItem 列表（类列表简表）
    class_details = []       # ClassDetail 列表（含成员常量/变量表）
    all_focus_fns = []       # 拍平后的焦点函数
    all_nv_fns = []          # 拍平后的 NV 原始函数

    for i, c in enumerate(cls_src, 1):
        cname = c.get("class_name", "")
        # 类列表简表的"说明"行：把路径塞成简述（无 description 时）
        paths = c.get("paths") or []
        desc = c.get("description") or (("、".join(paths)) if paths else "")
        classes_items.append({
            "seq": i,
            "design_id": c.get("design_id", ""),
            "class_name": cname,
            "description": desc,
        })
        # ClassDetail（常量/变量继承派生结构的格式）
        class_details.append({
            "class_name": cname,
            "design_id": c.get("design_id", ""),
            "constants": [{
                "seq": cc.get("seq", 0),
                "name": cc.get("name", ""),
                "type": cc.get("type", ""),
                "value": cc.get("value", ""),
                "description": cc.get("desc", "") or cc.get("description", ""),
            } for cc in (c.get("constants") or [])],
            "variables": [{
                "seq": vv.get("seq", 0),
                "name": vv.get("name", ""),
                "type": vv.get("type", ""),
                "description": vv.get("desc", "") or vv.get("description", ""),
            } for vv in (c.get("variables") or [])],
        })
        # 展开类内函数到顶层
        for fn in c.get("functions") or []:
            all_focus_fns.append(_norm_fn_to_schema(fn))
        for fn in c.get("nv_functions") or []:
            all_nv_fns.append(_norm_fn_to_schema(fn))

    # 类外（__free__）函数也塞进对应桶
    for fn in free_focus:
        all_focus_fns.append(_norm_fn_to_schema(fn))
    for fn in free_nv:
        all_nv_fns.append(_norm_fn_to_schema(fn))

    # function_list 简表（设计 ID | 函数名 | 说明）—— 从焦点函数派生
    function_list = [{
        "design_id": f.get("design_id", ""),
        "name": f.get("name", ""),
        "description": f.get("brief", ""),
    } for f in all_focus_fns]

    return {
        "classes": classes_items,
        "class_details": class_details,
        "functions": all_focus_fns,
        "nv_functions": all_nv_fns,
        "function_list": function_list,
    }


def _build_swe3_context(project: dict) -> dict:
    """project dict → Swe3Context → model_dump。字段映射统一在这做。"""
    from app.schemas.aspice.swe3_schema import Swe3Context  # 延迟导入
    from app.core import arch_sections_swe3 as sections3

    aspice = project.get("aspice", {}) or {}
    swe3 = aspice.get("swe3") or sections3.default_swe3()
    project_code = aspice.get("project_code", "") or project.get("name", "") or ""
    meta = project.get("meta", {}) or {}

    # history / reviews 字段名映射（和 SWE.2 一致）
    history_src = project.get("history") or [{
        "date": datetime.now().strftime("%Y/%m/%d"),
        "version": meta.get("doc_version", "V1.0"),
        "author": meta.get("modifier", ""),
        "change": "初版",
    }]
    history_rows = [{
        "date": h.get("date", ""),
        "version": h.get("version", ""),
        "author": h.get("author", ""),
        "content": h.get("content") or h.get("change", ""),
    } for h in history_src]

    reviews_src = project.get("reviews") or []
    review_rows = [{
        "version": r.get("version", ""),
        "review_date": r.get("review_date") or r.get("date", ""),
        "reviewer": r.get("reviewer", ""),
        "approver": r.get("approver", ""),
        "opinion": r.get("opinion") or r.get("comment", ""),
    } for r in reviews_src]

    project_block = {
        "name": f"{project_code}项目 软件详细设计书" if project_code else "软件详细设计书",
        "version": meta.get("doc_version", "V1.0"),
        "company": meta.get("company", "中科创达软件股份有限公司"),
        "history": history_rows,
        "reviews": review_rows,
    }

    # Overview（SWE.3 独有：scope_items/charsets/set_get_rule）
    overview_src = swe3.get("overview") or {}
    overview_block = {
        "purpose": overview_src.get("purpose", ""),
        "scope_text": overview_src.get("scope_text", ""),
        "scope_items": overview_src.get("scope_items") or [],
        "ref_docs": overview_src.get("ref_docs") or [],
        "charsets": overview_src.get("charsets") or [],
        "set_get_rule": overview_src.get("set_get_rule", ""),
    }

    # 2 术语
    terms_src = swe3.get("terms") or sections3.DEFAULT_SWE3_TERMS
    terms_rows = [{"term": t.get("term", ""), "definition": t.get("definition", "")} for t in terms_src]

    # 3 软件功能概述
    fo_src = swe3.get("function_overview") or swe3.get("composition") or {}
    fo_block = {
        "description": fo_src.get("description", "") or fo_src.get("intro", ""),
        "module_description": fo_src.get("module_description", "") or fo_src.get("note", ""),
        "module_image_key": fo_src.get("module_image_key"),
        "module_image_note": fo_src.get("module_image_note", ""),
    }

    # 需求映射（SWE.3 多一列 design_id）
    mappings_src = swe3.get("mappings") or []
    mapping_rows = [{
        "swe1_id": m.get("swe1_id", ""),
        "swe2_id": m.get("swe2_id", ""),
        "design_id": m.get("design_id", ""),
        "id_meaning": m.get("id_meaning", "") or m.get("component_name", ""),
        "remark": m.get("remark", ""),
        "version": m.get("version", ""),
    } for m in mappings_src]

    # 模块：和 modules_by_id 挂钩。缺失模块补空骨架，否则模板 A001~A009 索引会 UndefinedError
    _MODULE_NAMES = {
        "A001": "Serializer", "A002": "Deserializer", "A003": "EEPROM",
        "A004": "Camera Module", "A005": "nvsipl_camera", "A006": "nvsipl_multicast",
        "A007": "PMIC", "A008": "Camera Security", "A009": "Campwr",
    }
    modules_src = swe3.get("modules") or []
    # BUGFIX（R4.1）：原来按 `id` 聚合，但 swe3.modules[i] 实际键是 `component_id`，
    # 导致 user_by_id 全空键 → 所有模块走占位骨架 → 模板下标越界。
    user_by_id = {
        (m.get("id") or m.get("component_id") or ""): m
        for m in modules_src
        if (m.get("id") or m.get("component_id"))
    }
    merged = []
    for mid, mname in _MODULE_NAMES.items():
        if mid in user_by_id:
            merged.append(user_by_id[mid])
        else:
            merged.append({"id": mid, "component_id": mid, "name": mname})
    # 用户自定义但不在骨架的（A010+）保留
    for m in modules_src:
        mid = m.get("id") or m.get("component_id") or ""
        if mid and mid not in _MODULE_NAMES:
            merged.append(m)

    # R4.1：push_d 透传给 _derive_from_push_d_scan，让模块能从 scan_cache 自动派生
    # classes / functions / nv_original_functions — 用户已经在"模块代码路径配置"里
    # 扫过代码 + 在"关注函数选择"里勾过函数，这里一步贯通到 docx 模板。
    push_d = swe3.get("push_d") or {}
    push_d_for_derive = dict(push_d) if push_d else {}
    push_d_for_derive["_project_id"] = project.get("project_id")
    has_security = push_d.get("has_camera_security", True)

    module_rows = []
    for m in merged:
        # 把 id/component_id 对齐（_derive_from_push_d_scan 读 component_id）
        if not m.get("component_id") and m.get("id"):
            m["component_id"] = m["id"]
        if not m.get("id") and m.get("component_id"):
            m["id"] = m["component_id"]

        classes = m.get("classes") or []
        functions = m.get("functions") or []
        nv_funcs = m.get("nv_original_functions") or m.get("nv_functions") or []
        class_details = m.get("class_details") or []
        function_list = m.get("function_list") or m.get("functions_list") or []
        # 自动派生：只有当用户手工还没填 classes / functions 时才派生，避免覆盖人工微调。
        # 且仅当该模块**有**关注函数时派生：否则会把扫描到的所有函数（SDK 库可达几千个）
        # 全部展开到 nv_functions，一是 docx 爆表，二是 _normalize_scanned_fn 对每个函数
        # body_text 跑 PlantUML 解析，很容易把内存打爆。
        cid = m.get("component_id") or m.get("id") or ""
        has_focus = False
        if push_d:
            for ff in push_d.get("focus_functions") or []:
                if ff.get("component_id") == cid and (ff.get("focused_keys") or []):
                    has_focus = True
                    break
        if not classes and not functions and push_d and has_focus:
            try:
                derived = _derive_from_push_d_scan(m, push_d_for_derive)
                if derived:
                    adapted = _adapt_derived_module(derived)
                    classes = adapted["classes"] or classes
                    class_details = adapted["class_details"] or class_details
                    functions = adapted["functions"] or functions
                    # NV 函数兜底限制到前 50 个（避免 A006 这类 2k+ 函数把 docx 撑爆）
                    nv_candidates = adapted["nv_functions"] or nv_funcs
                    nv_funcs = nv_candidates[:50] if len(nv_candidates) > 50 else nv_candidates
                    function_list = adapted["function_list"] or function_list
            except Exception as _e:
                import logging
                logging.getLogger(__name__).warning(
                    f"_derive_from_push_d_scan failed for {cid}: {_e}"
                )

        # Camera Security 关闭 → 把 A008 的内容清空（保留骨架避免模板下标崩）
        if not has_security and m.get("component_id") == "A008":
            classes = []
            class_details = []
            functions = []
            nv_funcs = []
            function_list = []

        row = {
            "id": m.get("id", "") or m.get("component_id", ""),
            "component_id": m.get("component_id", "") or m.get("id", ""),
            "name": m.get("name", ""),
            "class_diagram_plantuml": m.get("class_diagram_plantuml", "") or m.get("class_diagram", ""),
            "class_diagram_image_key": m.get("class_diagram_image_key"),
            "classes": classes,
            "class_details": class_details,
            "functions_intro": m.get("functions_intro", ""),
            "function_list": function_list,
            "functions": functions,
            "nv_functions": nv_funcs,
            "nv_function_note": m.get("nv_function_note", ""),
            "sequence_diagrams": m.get("sequence_diagrams") or [],
        }
        module_rows.append(row)

    # 集成（可选）
    integration_src = swe3.get("integration") or {}
    integration_block = {
        "order": integration_src.get("order", ""),
        "principles": integration_src.get("principles") or [],
    }

    raw = {
        "project": project_block,
        "overview": overview_block,
        "terms": terms_rows,
        "function_overview": fo_block,
        "mappings": mapping_rows,
        "modules": module_rows,
        "integration": integration_block,
    }
    ctx = Swe3Context(**raw)
    return ctx.model_dump()


def export_swe3_docx_v2(project: dict, out_path: str) -> str:
    """SWE.3 模板引擎版导出（F1 推送）。

    走 app/templates/aspice/swe3_detail.docx 模板。
    F1 范围：A001/A003 两模块样板完整；其他模块用原文占位（F2 批量复刻）。
    """
    from app.core.template_engine import TemplateRenderer

    context = _build_swe3_context(project)
    renderer = TemplateRenderer("swe3_detail")

    # F1：注册 A001/A003 的 class_diagram 和 flowchart 图（若有 PlantUML 源）
    for m in context.get("modules", []):
        mid = m.get("id", "")
        if mid not in ("A001", "A003"):
            continue
        # 类图（可选）
        if m.get("class_diagram_plantuml"):
            key = f"module_{mid}_classdiagram"
            try:
                renderer.add_plantuml_image(key, plant_source=m["class_diagram_plantuml"])
                m["class_diagram_image_key"] = key
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    f"PlantUML 类图渲染失败 {mid}: {e}"
                )
        # 函数流程图
        for i, fn in enumerate(m.get("functions", [])):
            if fn.get("flowchart_plantuml"):
                key = f"module_{mid}_fn{i}_flowchart"
                try:
                    renderer.add_plantuml_image(key, plant_source=fn["flowchart_plantuml"])
                    fn["flowchart_image_key"] = key
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(
                        f"PlantUML 流程图渲染失败 {mid}.fn{i}: {e}"
                    )

    buf = renderer.render(context)

    # F2：对额外模块（非 A001/A003）深拷贝 A003 整段并填充。
    # 仅对真正有内容（classes/class_details/function_list/functions 任一非空）的模块追加，
    # 避免把 _MODULE_NAMES 补的空骨架也渲染出一堆空壳段。
    extra_modules = [
        m for m in context.get("modules", [])
        if m.get("id") not in ("A001", "A003")
        and (
            m.get("classes") or m.get("class_details")
            or m.get("function_list") or m.get("functions")
        )
    ]
    if extra_modules:
        buf = _append_extra_modules(buf, extra_modules, renderer=renderer)

    with open(out_path, "wb") as f:
        f.write(buf.getvalue())
    return out_path


# ============ F2：额外模块深拷贝追加 ============

def _append_extra_modules(buf: BytesIO, extra_modules: list[dict], renderer=None) -> BytesIO:
    """把 extra_modules 每个模块按 A003 样板深拷贝一份追加到模块设计章节末。

    buf: 已经由 docxtpl 渲染好的 docx 流
    extra_modules: 需要追加的模块字典列表（不含 A001/A003）

    策略：
      1. 用 python-docx 打开文档
      2. 定位 A003 段（"模块EEPROM详细设计" H1 到下一个 H1 之前）
      3. 对每个 extra，深拷贝 A003 段 body 元素
      4. 替换标题 / 类列表 / 函数列表 / 函数声明表 内容
      5. 插到当前文档末尾（后面的"性能分析"等章节会在最后）
    """
    from copy import deepcopy
    from docx import Document
    from docx.oxml.ns import qn

    d = Document(buf)
    body = d.element.body

    # 找 A003 段范围
    elements = list(body.iterchildren())

    def _para_text(el) -> str:
        return ''.join(t.text or '' for t in el.iter(qn('w:t')))

    a003_start_idx = None
    a003_end_idx = None  # 不含
    tail_boundary_keywords = (
        '性能分析', '函数设计评估', '函数评估', '共通定义', '系统集成',
    )
    for i, el in enumerate(elements):
        tag = el.tag.split('}')[-1]
        if tag != 'p':
            continue
        text = _para_text(el).strip()
        if a003_start_idx is None:
            if '模块EEPROM详细设计' in text or ('EEPROM' in text and '详细设计' in text):
                a003_start_idx = i
                continue
        else:
            # A003 段结束：
            #   (a) 遇到性能/集成等 tail 关键字
            #   (b) 遇到任意下一个 "模块XXX详细设计" H1
            if any(kw in text for kw in tail_boundary_keywords):
                a003_end_idx = i
                break
            # 下一个"模块…详细设计" H1（排除 EEPROM 自身）
            if text.startswith('模块') and '详细设计' in text and 'EEPROM' not in text:
                a003_end_idx = i
                break

    if a003_start_idx is None:
        # 找不到 A003 段，退化为"文档末尾 append"
        import logging
        logging.getLogger(__name__).warning("F2: A003 段未找到，额外模块跳过追加")
        out = BytesIO()
        d.save(out)
        out.seek(0)
        return out

    if a003_end_idx is None:
        a003_end_idx = len(elements)  # A003 之后再无 H1，追加到末尾

    # 取出 A003 段的元素（不含 end）— 这些是我们的样板
    template_els = elements[a003_start_idx:a003_end_idx]

    # 插入点：A003 段最后一个元素之后
    insert_anchor = elements[a003_end_idx - 1] if a003_end_idx > 0 else None

    for mod in extra_modules:
        new_els = [deepcopy(el) for el in template_els]

        # 1) 替换 H1 标题文字
        for el in new_els:
            if el.tag.split('}')[-1] == 'p':
                text = _para_text(el)
                if '模块EEPROM详细设计' in text or ('EEPROM' in text and '详细设计' in text):
                    new_title = f"模块{mod.get('name', '')}详细设计"
                    _replace_para_text(el, new_title)
                    break

        # 2) 先把 new_els 挨个插到 insert_anchor 之后（这样后面 _fill 才能 getparent）
        for el in new_els:
            insert_anchor.addnext(el)
            insert_anchor = el

        # 3) 遍历新段里的所有表，填充（此时 new_els 已在文档树里）
        tbls_in_new = [el for el in new_els if el.tag.split('}')[-1] == 'tbl']
        _fill_module_tables(tbls_in_new, mod)

    out = BytesIO()
    d.save(out)
    out.seek(0)
    return out


def _replace_para_text(p_el, new_text: str) -> None:
    """替换一个 <w:p> 元素里所有 run 的文本为 new_text（保留第一个 run 的格式）。"""
    from docx.oxml.ns import qn
    runs = p_el.findall(qn('w:r'))
    if not runs:
        return
    # 第一个 run 保留，改文本
    first = runs[0]
    # 清掉原有 <w:t>
    for t in first.findall(qn('w:t')):
        first.remove(t)
    # 新建一个
    from docx.oxml import OxmlElement
    t_el = OxmlElement('w:t')
    t_el.text = new_text
    t_el.set(qn('xml:space'), 'preserve')
    first.append(t_el)
    # 其他 run 删掉
    for r in runs[1:]:
        p_el.remove(r)


def _set_cell_text(cell_el, text: str) -> None:
    """清掉 <w:tc> 所有 <w:p> 文本，只在第一个段里塞 text（保留一个段元素）。"""
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    paras = cell_el.findall(qn('w:p'))
    if not paras:
        new_p = OxmlElement('w:p')
        cell_el.append(new_p)
        paras = [new_p]
    # 保留第一个段，其他段删掉
    first_p = paras[0]
    for p in paras[1:]:
        cell_el.remove(p)
    _replace_para_text(first_p, text)
    # 如果第一个段没 run，_replace_para_text 什么也不做，这里兜底
    if not first_p.findall(qn('w:r')):
        r = OxmlElement('w:r')
        t = OxmlElement('w:t')
        t.text = text
        t.set(qn('xml:space'), 'preserve')
        r.append(t)
        first_p.append(r)


def _fill_module_tables(tbl_els: list, mod: dict) -> None:
    """按 header 把一个模块的表分类后，批量填内容。

    tbl_els: 该模块段里所有 <w:tbl> 元素（已深拷贝自 A003 样板）
    mod: 单个模块字典（含 classes/function_list/functions 等）

    样板预期（和 A003 相同）：
      - 类列表表（4 列: 序号 | 设计ID | 类名 | 说明）
      - 函数列表表（3 列: 设计ID | 函数名 | 说明）
      - 函数声明表（10 行 5 列，固定结构）× N
    若新模块某种表数量不足，多余的样板表就地清空内容（保留表框，内容置 "—"）
    """
    from docx.oxml.ns import qn

    # 统计样板中的 3 种表位置
    class_tbl_idx = None
    fn_list_tbl_idx = None
    fn_decl_tbl_idxs = []

    for i, tbl_el in enumerate(tbl_els):
        rows = tbl_el.findall(qn('w:tr'))
        if not rows:
            continue
        # 第一行文本
        first_row_texts = []
        for tc in rows[0].findall(qn('w:tc')):
            first_row_texts.append(''.join(t.text or '' for t in tc.iter(qn('w:t'))))
        h0 = first_row_texts[0].strip() if first_row_texts else ''
        h1 = first_row_texts[1].strip() if len(first_row_texts) > 1 else ''

        if '序号' in h0 and '设计' in h1 and class_tbl_idx is None:
            class_tbl_idx = i
        elif '设计' in h0 and '函数名' in h1 and fn_list_tbl_idx is None:
            fn_list_tbl_idx = i
        elif '函数声明' in h0:
            fn_decl_tbl_idxs.append(i)

    classes = mod.get('classes') or []
    fn_list = mod.get('function_list') or []
    functions = mod.get('functions') or []

    # ---- 填类列表 ----
    if class_tbl_idx is not None:
        tbl_el = tbl_els[class_tbl_idx]
        rows = tbl_el.findall(qn('w:tr'))
        # 保留 header 行，重填数据行
        _rewrite_table_rows(tbl_el, rows[1:], [
            [str(c.get('seq', '')), c.get('design_id', ''), c.get('class_name', ''), c.get('description', '')]
            for c in classes
        ], placeholder_cols=4)

    # ---- 填函数列表 ----
    if fn_list_tbl_idx is not None:
        tbl_el = tbl_els[fn_list_tbl_idx]
        rows = tbl_el.findall(qn('w:tr'))
        _rewrite_table_rows(tbl_el, rows[1:], [
            [f.get('design_id', ''), f.get('name', ''), f.get('description', '')]
            for f in fn_list
        ], placeholder_cols=3)

    # ---- 填函数声明表 ----
    # 关键：样板里函数声明表数量固定（A003 样板是 6 张），
    # 新模块函数多于样板就复制最后一张表的"外壳"去扩，少于就把多余的清空占位
    from copy import deepcopy
    if fn_decl_tbl_idxs and len(functions) > len(fn_decl_tbl_idxs):
        last_decl_el = tbl_els[fn_decl_tbl_idxs[-1]]
        parent = last_decl_el.getparent()
        anchor_idx = list(parent).index(last_decl_el)
        for _ in range(len(functions) - len(fn_decl_tbl_idxs)):
            new_tbl = deepcopy(last_decl_el)
            anchor_idx += 1
            parent.insert(anchor_idx, new_tbl)
            # 同时把这张新表加到 tbl_els 末尾，让后面的填充能遍历到
            tbl_els.append(new_tbl)
            fn_decl_tbl_idxs.append(len(tbl_els) - 1)

    for i, decl_tbl_idx in enumerate(fn_decl_tbl_idxs):
        tbl_el = tbl_els[decl_tbl_idx]
        if i < len(functions):
            _fill_function_decl_table(tbl_el, functions[i])
        else:
            _clear_function_decl_table(tbl_el)


def _rewrite_table_rows(tbl_el, existing_data_rows: list, new_data: list[list[str]], placeholder_cols: int) -> None:
    """删掉 existing_data_rows，按 new_data 重建；若 new_data 为空，塞一行占位 '—'。"""
    from docx.oxml.ns import qn
    from copy import deepcopy

    if not existing_data_rows:
        return

    # 以第一个 existing 行作样板
    row_template = deepcopy(existing_data_rows[0])

    # 删掉所有 existing_data_rows
    for r in existing_data_rows:
        tbl_el.remove(r)

    rows_to_add = new_data if new_data else [['—'] * placeholder_cols]
    for row_data in rows_to_add:
        new_row = deepcopy(row_template)
        cells = new_row.findall(qn('w:tc'))
        for j, cell in enumerate(cells):
            text = row_data[j] if j < len(row_data) else ''
            _set_cell_text(cell, str(text) if text is not None else '')
        tbl_el.append(new_row)


def _fill_function_decl_table(tbl_el, fn: dict) -> None:
    """按 A003 函数声明表样板（10 行 5 列）填入 fn 的各字段。

    row0 col1: declaration
    row1 col1: brief
    row3-5 col0/1/2: parameters[0..2].name / type / details
    row-2 col0/1/2: return_values[0]
    row-1 col0 (merged): flowchart —— 推送 G 四态：
        - ok              → PlantUML 源码块文本（docxtpl 渲染流程另有图片嵌入，这里先文本占位）
        - exempt_from_ai  → "（流程图由人工补充）"
        - exception       → "⚠️ AI 生成失败，请人工补充"
        - unchanged_sdk   → "（SDK 原装函数，不画流程图）"
        - 兜底            → "<待生成 流程图>"
    """
    from docx.oxml.ns import qn
    rows = tbl_el.findall(qn('w:tr'))
    if not rows:
        return

    def _cells(r):
        return r.findall(qn('w:tc'))

    # row0 col1: declaration
    if len(rows) >= 1:
        cells = _cells(rows[0])
        if len(cells) > 1:
            _set_cell_text(cells[1], fn.get('declaration', ''))
    # row1 col1: brief
    if len(rows) >= 2:
        cells = _cells(rows[1])
        if len(cells) > 1:
            _set_cell_text(cells[1], fn.get('brief', ''))

    # params in row3-5
    params = fn.get('parameters') or []
    for i, prow in enumerate([3, 4, 5]):
        if prow < len(rows):
            cells = _cells(rows[prow])
            if i < len(params) and len(cells) >= 3:
                p = params[i]
                _set_cell_text(cells[0], p.get('name', ''))
                _set_cell_text(cells[1], p.get('type', ''))
                _set_cell_text(cells[2], p.get('details', ''))
            elif len(cells) >= 3:
                # 清空多余参数行
                _set_cell_text(cells[0], '')
                _set_cell_text(cells[1], '')
                _set_cell_text(cells[2], '')

    # 返回值：倒数第 2 行
    rets = fn.get('return_values') or []
    if len(rows) >= 2:
        ret_row = rows[-2]
        cells = _cells(ret_row)
        if rets and len(cells) >= 3:
            r = rets[0]
            _set_cell_text(cells[0], r.get('name', ''))
            _set_cell_text(cells[1], r.get('type', ''))
            _set_cell_text(cells[2], r.get('details', ''))

    # 推送 G：最后一行流程图四态
    if len(rows) >= 1:
        last_row = rows[-1]
        cells = _cells(last_row)
        if cells:
            flow_text = _resolve_flowchart_placeholder(fn)
            # 流程图单元格占满整行（合并单元格），只写到第 1 格即可
            _set_cell_text(cells[0], flow_text)


def _resolve_flowchart_placeholder(fn: dict) -> str:
    """推送 G：按函数四态返回流程图单元格应显示的文字占位。

    PNG 嵌入由上层 docxtpl 渲染路径另做（见 _render_function_detail），这里仅负责
    文本占位。优先级（最高到最低）：
      1. 用户豁免 (exempt_from_ai=True)
      2. AI 异常 (ai_status=exception)
      3. SDK 未改动 (is_sdk=True 且 diff_status in {unchanged_sdk, unchanged})
      4. AI 失败 (ai_status=failed)
      5. AI 成功 (有 ai_flowchart / flowchart_plantuml) → 显示 "（见下方流程图）"（真实 PNG 由上层嵌入）
      6. 未改动函数 (diff_status in {unchanged, unchanged_sdk}) → "（未改动函数，无需重画流程图）"
      7. 待生成 (改动函数但 AI 还没跑过) → "<待生成 流程图：请在「函数状态清单」点击生成>"
      8. 默认占位
    """
    if fn.get("exempt_from_ai"):
        return "（流程图由人工补充）"
    ai_status = (fn.get("ai_status") or "").lower()
    if ai_status == "exception":
        note = fn.get("ai_exception_note") or fn.get("ai_last_error") or ""
        return f"⚠️ AI 生成失败已标记异常，请人工补充{('：' + note[:80]) if note else ''}"
    if fn.get("is_sdk") and fn.get("diff_status") in ("unchanged_sdk", "unchanged"):
        return "（SDK 原装函数，不画流程图）"
    if ai_status == "failed":
        err = fn.get("ai_last_error") or ""
        retry = fn.get("ai_retry_count") or 0
        return f"⚠️ AI 尚未成功生成（已重试 {retry} 次：{err[:60]}…），可在「函数状态清单」点重试或标异常"
    if (fn.get("ai_flowchart") or fn.get("flowchart_plantuml") or "").strip():
        return "（见下方流程图）"
    # R4：区分"未改动不用画" vs "改动但 AI 未跑"，让人工 reviewer 一眼看出要补的地方
    if fn.get("diff_status") in ("unchanged", "unchanged_sdk"):
        return "（本函数自 baseline 以来未改动，复用历史流程图或省略）"
    return "<待生成 流程图：请在「函数状态清单」点击「生成」或「一键生成」>"


def _clear_function_decl_table(tbl_el) -> None:
    """函数声明表样板多出来的（新模块函数不够多），清空内容保留框。"""
    from docx.oxml.ns import qn
    rows = tbl_el.findall(qn('w:tr'))
    if len(rows) < 2:
        return
    # row0 col1, row1 col1
    for ri in [0, 1]:
        cells = rows[ri].findall(qn('w:tc'))
        if len(cells) > 1:
            _set_cell_text(cells[1], '—')
    # params rows
    for ri in [3, 4, 5]:
        if ri < len(rows):
            cells = rows[ri].findall(qn('w:tc'))
            for c in cells:
                _set_cell_text(c, '')
    # 返回值行
    if len(rows) >= 2:
        for c in rows[-2].findall(qn('w:tc')):
            _set_cell_text(c, '')


def export_swe3_v2(project: dict, out_dir: str) -> dict:
    """SWE.3 导出（v2 模板引擎版）：同时产 docx + xlsx。"""
    project_code = (project.get("aspice", {}) or {}).get("project_code", "") or \
                   project.get("name", "project")
    safe = "".join(c for c in project_code if c.isalnum() or c in "._-") or "project"
    docx_name = f"{safe}_详细设计.docx"
    xlsx_name = f"{safe}_详细设计清单.xlsx"
    export_swe3_docx_v2(project, os.path.join(out_dir, docx_name))
    export_swe3_xlsx(project, os.path.join(out_dir, xlsx_name))
    return {"docx": docx_name, "xlsx": xlsx_name}
