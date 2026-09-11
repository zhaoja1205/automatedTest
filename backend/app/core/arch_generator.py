"""
SWE.2 软件架构设计 — 生成器。

基于 SWE.1 需求项自动建映射表（每需求→组件，swe2_id 自动派生）。
导出程序化 docx + xlsx，不复制 Pangu 模板。
"""
import os
from datetime import datetime
from typing import Optional

from app.core import id_chain


# ---- 映射生成（规则）----

# 组件编号 A001~A008
_COMPONENTS = {
    "A001": "Serializer",
    "A002": "Deserializer",
    "A003": "EEPROM",
    "A004": "Camera Module",
    "A005": "nvsipl_camera",
    "A006": "nvsipl_multicast",
    "A007": "PMIC",
    "A008": "Camera Security",
}


def _guess_components(content: str) -> list[str]:
    """根据需求描述文本猜测涉及的组件 ID（规则模板）。

    规则（从 SWE.2 映射表归纳）：
      raw/yuv/起流/出图/配置SerDes/Sensor → A001 + A002 + A004
      帧率/分辨率/nito/ISP                  → A005（+A006）
      帧同步/SOF/同步曝光/时间戳             → A005
      EEPROM/内参/序列号/标定                → A003
      multicast/集成                        → A006
      PMIC/电源                             → A007
      Security/认证/认证/密钥                 → A008
      故障/诊断/故障上报                      → A001 + A002（SerDes故障）
    """
    text = content.lower() if content else ""
    comps = []

    if any(k in text for k in ["raw", "yuv", "起流", "出图", "serdes", "sensor", "配置"]):
        comps += ["A001", "A002", "A004"]
    if any(k in text for k in ["nito", "帧率", "分辨率", "isp"]):
        comps += ["A005"]
    if any(k in text for k in ["帧同步", "sof", "同步曝光", "时间戳", "触发"]):
        comps += ["A005"]
    if any(k in text for k in ["eeprom", "内参", "序列号", "标定", "lens"]):
        comps += ["A003"]
    if any(k in text for k in ["multicast", "集成", "同时点亮"]):
        comps += ["A006"]
    if any(k in text for k in ["pmic", "电源", "供电"]):
        comps += ["A007"]
    if any(k in text for k in ["security", "认证", "密钥", "证书", "篡改"]):
        comps += ["A008"]
    if any(k in text for k in ["故障", "诊断", "fault", "error", "检测"]):
        comps += ["A001", "A002"]
    if any(k in text for k in ["直方图", "histogram", "嵌入行", "metadata"]):
        comps += ["A004", "A005"]
    if any(k in text for k in ["rotate", "旋转", "fipl"]):
        comps += ["A004"]

    # 去重保序
    seen = set()
    unique = []
    for c in comps:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    # 兜底：没匹配到任何组件时默认落到 Camera Module
    if not unique:
        unique = ["A004"]
    return unique


def generate_mappings(
    requirements: list[dict],
    existing: Optional[list[dict]] = None,
) -> list[dict]:
    """基于 SWE.1 需求项自动生成 SWE.1→SWE.2 映射表。

    每条需求按规则拆到多个组件，每行一个组件，swe2_id 自动派生。
    """
    existing = existing or []
    mappings = list(existing)

    for req in requirements:
        req_id = req.get("req_id", "")
        content = req.get("content", "")
        comp_ids = _guess_components(content)
        for comp_id in comp_ids:
            a_seq = id_chain.next_arch_seq(mappings, req_id)
            swe2_id = id_chain.derive_arch(req_id, a_seq)
            mappings.append({
                "swe1_id": req_id,
                "swe2_id": swe2_id,
                "component_id": comp_id,
                "component": _COMPONENTS.get(comp_id, ""),
                "description": content[:80],
                "release_version": "V1.0",
            })
    return mappings


# ---- docx 导出（程序化）----

def export_swe2_docx(project: dict, out_path: str) -> str:
    """程序化生成 SWE.2 软件架构&概要设计书 docx。"""
    from docx import Document
    from docx.shared import Pt

    aspice = project.get("aspice", {})
    swe2 = aspice.get("swe2", {})
    project_code = aspice.get("project_code", "")
    meta = project.get("meta", {})
    mappings = swe2.get("mappings", [])
    components = swe2.get("components", [])

    doc = Document()

    # 封面
    title = doc.add_heading("", level=0)
    run = title.add_run(f"{project_code or project.get('name','')}项目软件架构&概要设计书")
    run.font.size = Pt(22)
    p = doc.add_paragraph()
    p.alignment = 1
    p.add_run(f"版本号：{meta.get('doc_version', 'V1.0')}").font.size = Pt(14)
    p = doc.add_paragraph()
    p.alignment = 1
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

    # 1 概述
    doc.add_heading("1 概述（架构&概要）", level=1)
    doc.add_heading("1.1 目的", level=2)
    doc.add_paragraph("本文档对camera驱动软件系统进行概要的功能说明。")
    doc.add_heading("1.2 假设及依赖", level=2)
    doc.add_paragraph("基于Nvidia平台自带ISP；Deserializer和Serializer均采用NVIDIA Orin支持的参考设计。")

    # 2 需求列表（映射表）
    doc.add_heading("2 需求列表（架构&概要）", level=1)
    if mappings:
        t = doc.add_table(rows=1, cols=5)
        t.style = "Table Grid"
        hdr = t.rows[0].cells
        hdr[0].text = "SWE.1"
        hdr[1].text = "SWE.2"
        hdr[2].text = "ID含义"
        hdr[3].text = "备注"
        hdr[4].text = "发布版本"
        for m in mappings:
            row = t.add_row().cells
            row[0].text = m.get("swe1_id", "")
            row[1].text = m.get("swe2_id", "")
            row[2].text = m.get("component", "")
            row[3].text = m.get("description", "")[:60]
            row[4].text = m.get("release_version", "")

    # 3 软件设计
    doc.add_heading("3 软件设计（架构&概要）", level=1)
    doc.add_heading("3.1 静态信息", level=2)
    doc.add_paragraph("此软件系统使用了Nvidia Drive-OS NvSIPL架构。")

    # 4 模块设计（8 组件）
    doc.add_heading("4 模块设计（概要设计）", level=1)
    for comp in components:
        cid = comp.get("id", "")
        cname = comp.get("name", "")
        doc.add_heading(f"4.{cid[1:]} 组件名称{cname}", level=2)
        p = doc.add_paragraph()
        p.add_run(f"编号：{cid}").bold = True
        doc.add_heading("功能描述", level=3)
        doc.add_paragraph(f"完成对{cname}配置信息和控制。")
        doc.add_heading("接口信息", level=3)
        doc.add_paragraph("<待补充:接口信息>")

    # 5 资源消耗
    doc.add_heading("5 资源消耗", level=1)
    doc.add_paragraph("KPI指标按需求文档定义执行。")

    # 6 系统集成
    doc.add_heading("6 系统集成（概要设计）", level=1)
    doc.add_heading("6.1 各模块的集成顺序", level=2)
    doc.add_paragraph("集成顺序：Deserializer → Serializer → Sensor。"
                      "MAX20087、EEPROM、PMIC注册到框架中。")

    doc.save(out_path)
    return out_path


# ---- xlsx 导出（程序化）----

def export_swe2_xlsx(project: dict, out_path: str) -> str:
    """程序化生成 SWE.2 映射表 xlsx。"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

    aspice = project.get("aspice", {})
    swe2 = aspice.get("swe2", {})
    mappings = swe2.get("mappings", [])
    components = swe2.get("components", [])

    wb = Workbook()

    # 映射表 sheet
    ws = wb.active
    ws.title = "需求映射"

    header_font = Font(bold=True)
    header_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    thin = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    wrap = Alignment(wrap_text=True, vertical="top")

    headers = ["SWE.1", "SWE.2", "ID含义", "备注", "发布版本"]
    for ci, h in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=ci, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = border
        cell.alignment = wrap

    for ri, m in enumerate(mappings, start=2):
        row_data = [
            m.get("swe1_id", ""),
            m.get("swe2_id", ""),
            m.get("component", ""),
            m.get("description", ""),
            m.get("release_version", ""),
        ]
        for ci, val in enumerate(row_data, start=1):
            cell = ws.cell(row=ri, column=ci, value=val)
            cell.border = border
            cell.alignment = wrap

    for ci, w in enumerate([22, 28, 18, 40, 14], start=1):
        ws.column_dimensions[chr(64 + ci)].width = w

    # 组件属性表 sheet
    ws2 = wb.create_sheet("组件属性")
    comp_hdr = ["组件", "属性", "数值"]
    for ci, h in enumerate(comp_hdr, start=1):
        cell = ws2.cell(row=1, column=ci, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = border

    ri = 2
    for comp in components:
        for attr in ["Name", "I2C Address", "Model"]:
            val = comp.get("model" if attr == "Name" else
                           "i2c_addr" if attr == "I2C Address" else "model", "")
            ws2.cell(row=ri, column=1, value=comp.get("name", "")).border = border
            ws2.cell(row=ri, column=2, value=attr).border = border
            ws2.cell(row=ri, column=3, value=val).border = border
            ri += 1

    wb.save(out_path)
    return out_path
