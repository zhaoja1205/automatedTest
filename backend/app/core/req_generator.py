"""
SWE.1 软件需求分析 — 生成器。

规则模板兜底生成需求项骨架；导出程序化 docx（python-docx）+ xlsx（openpyxl）。
docx/xlsx 均从零程序化生成，不复制 Pangu 模板，项目代号原样填入。
"""
import os
from datetime import datetime
from typing import Optional

from app.core import id_chain


# ---- 规则生成（兜底）----

def generate_requirements(
    raw_text: str,
    project_code: str,
    existing: Optional[list[dict]] = None,
) -> list[dict]:
    """从客户原始需求文本按规则生成需求项骨架。

    简单按行切分：以数字编号开头的行视为一条需求项。
    用 id_chain 自动分配 OR ID + SWE.1 ReqID（项目代号原样使用）。
    AI 失败时调用此函数兜底。
    """
    if not raw_text or not raw_text.strip():
        return []

    existing = existing or []
    r_seq = id_chain.next_req_seq(existing)

    # 按行切分，过滤空行和纯标题行
    lines = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        # 跳过明显的章节标题（"一、" "1. " 开头但过短）
        if len(line) < 8 and (line.startswith("一") or line.startswith("第")):
            continue
        lines.append(line)

    requirements = list(existing)
    idx = 0
    for line in lines:
        idx += 1
        or_id = id_chain.derive_or(project_code, idx)
        req_id = id_chain.derive_req(or_id, 1)
        requirements.append({
            "or_id": or_id,
            "req_id": req_id,
            "software_mark": "原始",
            "content": line[:200],
            "category": "",
            "milestone": "",
            "owner": "",
            "input_source": "客户原始需求",
            "priority": 2,
        })
        r_seq = id_chain.next_req_seq(requirements)

    return requirements


# ---- docx 导出（程序化生成）----

def export_swe1_docx(project: dict, out_path: str) -> str:
    """程序化生成 SWE.1 软件需求说明书 docx。"""
    from docx import Document
    from docx.shared import Pt, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    aspice = project.get("aspice", {})
    swe1 = aspice.get("swe1", {})
    project_code = aspice.get("project_code", "")
    meta = project.get("meta", {})
    requirements = swe1.get("requirements", [])
    topology = swe1.get("topology", [])
    kpi = swe1.get("kpi", [])

    doc = Document()

    # 封面
    title = doc.add_heading("", level=0)
    run = title.add_run(f"{project_code or project.get('name','')}项目软件需求说明书")
    run.font.size = Pt(22)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run(f"版本号：{meta.get('doc_version', 'V1.0')}").font.size = Pt(14)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run(f"{meta.get('company', '中科创达软件股份有限公司')}").font.size = Pt(12)

    doc.add_page_break()

    # 历史记录
    doc.add_heading("历史记录", level=1)
    t = doc.add_table(rows=2, cols=4)
    t.style = "Table Grid"
    t.rows[0].cells[0].text = "日期"
    t.rows[0].cells[1].text = "版本号"
    t.rows[0].cells[2].text = "作者"
    t.rows[0].cells[3].text = "修改内容"
    t.rows[1].cells[0].text = datetime.now().strftime("%Y/%m/%d")
    t.rows[1].cells[1].text = meta.get("doc_version", "V1.0")
    t.rows[1].cells[2].text = meta.get("modifier", "")
    t.rows[1].cells[3].text = "初版"

    # 1 项目范围
    doc.add_heading("1 项目范围", level=1)
    doc.add_heading("1.1 项目概况", level=2)
    doc.add_paragraph(
        f"基于{project_code or '客户'}提供的硬件平台进行Camera驱动软件的开发"
        "以及实现各种合理范围的软件功能需求。"
    )

    doc.add_heading("1.2 项目假设和关键依赖", level=2)
    doc.add_paragraph("关键依赖：")
    doc.add_paragraph("基于Nvidia平台自带ISP；Deserializer和Serializer均采用NVIDIA Orin支持的参考设计。")

    doc.add_heading("1.3 sensor位置描述", level=2)
    if topology:
        for item in topology:
            doc.add_paragraph(
                f"{item.get('group', '')}：{item.get('sensor_model', '')} "
                f"（{item.get('fov', '')}）"
            )
    else:
        doc.add_paragraph("<待补充:sensor位置描述>")

    # 2 功能需求
    doc.add_heading("2 功能需求", level=1)
    for i, req in enumerate(requirements, start=1):
        doc.add_heading(f"2.{i} {req.get('content', '')[:50]}", level=2)
        p = doc.add_paragraph()
        p.add_run(f"需求编号：{req.get('req_id', '')}").bold = True
        doc.add_heading(f"2.{i}.1 功能描述", level=3)
        doc.add_paragraph(req.get("content", ""))
        doc.add_heading(f"2.{i}.2 操作描述", level=3)
        doc.add_paragraph(req.get("operation", "<待补充:操作描述>"))

    # 3 非功能需求
    doc.add_heading("3 非功能需求", level=1)
    doc.add_heading("3.1 性能测试", level=3)
    if kpi:
        for item in kpi:
            doc.add_paragraph(f"KPI{item.get('seq', '')}：{item.get('desc', '')}")
    else:
        doc.add_paragraph("<待补充:KPI指标>")

    # 4 其他需求
    doc.add_heading("4 其他需求", level=1)
    doc.add_heading("4.1 质量需求", level=2)
    doc.add_paragraph("遵循软件质量规格书内同意之内容进行软件开发过程的管控。")
    doc.add_heading("4.2 软件设计约束和限制", level=2)
    doc.add_paragraph("需使用NV框架进行开发，编程语言：c/c++")

    doc.save(out_path)
    return out_path


# ---- xlsx 导出（程序化生成）----

def export_swe1_xlsx(project: dict, out_path: str) -> str:
    """程序化生成 SWE.1 需求详细表 xlsx。"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

    aspice = project.get("aspice", {})
    swe1 = aspice.get("swe1", {})
    requirements = swe1.get("requirements", [])

    wb = Workbook()
    ws = wb.active
    ws.title = "Requirement"

    header_font = Font(bold=True, size=11)
    header_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    thin = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    wrap = Alignment(wrap_text=True, vertical="top")

    headers = [
        "Input", "Chapter", "NO.", "ReqID", "软件需求标识",
        "Content", "Category", "Project Release Time",
        "RA DeadLine", "OR", "Owner", "Memo",
    ]
    for ci, h in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=ci, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = border
        cell.alignment = wrap

    for ri, req in enumerate(requirements, start=2):
        row_data = [
            req.get("input_source", ""),
            "",
            f"{ri-1}.a",
            req.get("req_id", ""),
            req.get("software_mark", "原始"),
            req.get("content", ""),
            req.get("category", ""),
            req.get("milestone", ""),
            "",
            req.get("or_id", ""),
            req.get("owner", ""),
            "",
        ]
        for ci, val in enumerate(row_data, start=1):
            cell = ws.cell(row=ri, column=ci, value=val)
            cell.border = border
            cell.alignment = wrap

    # 列宽
    widths = [28, 10, 8, 22, 12, 50, 22, 18, 18, 14, 10, 20]
    for ci, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + ci)].width = w

    # 需求总览表 sheet
    ws2 = wb.create_sheet("ProjectName")
    ov_headers = ["需求编号", "原始需求文档", "软件需求标识", "需求分析完成时间",
                  "架构设计完成时间", "功能发布版本", "OR & Owner", "Note"]
    for ci, h in enumerate(ov_headers, start=1):
        cell = ws2.cell(row=1, column=ci, value=h)
        cell.font = header_font
        cell.fill = header_fill
    for ri, req in enumerate(requirements, start=2):
        ws2.cell(row=ri, column=1, value=req.get("req_id", ""))
        ws2.cell(row=ri, column=2, value=req.get("input_source", ""))
        ws2.cell(row=ri, column=3, value=req.get("software_mark", "原始"))
        ws2.cell(row=ri, column=4, value="")
        ws2.cell(row=ri, column=5, value="")
        ws2.cell(row=ri, column=6, value="")
        ws2.cell(row=ri, column=7, value=req.get("owner", ""))
        ws2.cell(row=ri, column=8, value="")

    wb.save(out_path)
    return out_path
