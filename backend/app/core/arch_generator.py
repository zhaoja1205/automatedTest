"""
SWE.2 软件架构设计 — 生成器。

基于 SWE.1 需求项自动建映射表（每需求→组件，swe2_id 自动派生）。
导出程序化 docx + xlsx，不复制 Pangu 模板。

docx 骨架对齐《PreDev_软件架构&概要设计书V1.0》：
  封面 → 历史记录 → 评审记录 → 目录
  1 概述（1.1~1.5 完整落地：目的/范围/术语/参考/假设）
  2 需求列表（SWE.1→SWE.2 映射表）
  3 软件设计（简版：简介/静态/接口占位）
  4 模块设计（★ 按 8 组件统一模板展开：功能描述/外部接口/内部接口/类描述/场景）
  5 资源消耗（简版 + 空 KPI）
  6 备选软件架构（固定一段）
  7 系统集成（7.1 顺序 + 7.2 6 条原则）
"""
import os
from datetime import datetime
from typing import Optional

from app.core import id_chain, arch_sections


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
    "A009": "Campwr",
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


# ---- docx 导出辅助 ----

def _add_table(doc, headers: list[str], rows: list[list[str]], widths: Optional[list[int]] = None):
    """统一样式封装：建带表头的 Table Grid，返回 table 对象。"""
    from docx.shared import Pt, Cm

    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    hdr_cells = t.rows[0].cells
    for i, h in enumerate(headers):
        hdr_cells[i].text = h
        # 加粗表头
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


def _collect_linked_reqs_for_component(mappings: list[dict], component_id: str) -> list[str]:
    """从映射表中按组件 ID 收集溯源 SWE.2 ID 列表。"""
    out = []
    for m in mappings or []:
        if m.get("component_id") == component_id:
            s = m.get("swe2_id", "")
            if s:
                out.append(s)
    # 去重保序
    seen = set()
    unique = []
    for s in out:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique


def _render_component_section(doc, comp: dict, chapter_no: int, linked_reqs: list[str]):
    """渲染第 4 章单个组件的完整子节。

    chapter_no: 4.X 中的 X（从 1 开始）
    """
    name = comp.get("name", "")
    cid = comp.get("id", "")
    base = f"4.{chapter_no}"

    doc.add_heading(f"{base} 组件名称 {name}", level=2)
    p = doc.add_paragraph()
    p.add_run(f"编号：{cid}").bold = True

    # 4.X.1 功能描述
    doc.add_heading(f"{base}.1 功能描述", level=3)
    desc = (comp.get("function_desc") or "").strip() or arch_sections.COMPONENT_FUNCTION_DESC.get(cid, "")
    if desc:
        doc.add_paragraph(desc)
    comp_linked = (comp.get("linked_req_ids") or []) + linked_reqs
    traceable = arch_sections.build_linked_req_rows(comp_linked, component_name=name)
    if traceable:
        doc.add_paragraph(traceable)

    # 4.X.2 接口信息
    doc.add_heading(f"{base}.2 接口信息", level=3)

    # 4.X.2.1 外部接口
    doc.add_heading(f"{base}.2.1 外部接口", level=4)
    ext_ifs = comp.get("external_interfaces") or []
    if ext_ifs:
        rows = [[
            it.get("source", ""),
            it.get("method", ""),
            it.get("type", "外部接口"),
            it.get("params", ""),
            it.get("description", ""),
        ] for it in ext_ifs]
        _add_table(doc, ["接口溯源", "方法名", "接口类型", "参数", "说明"], rows)
    else:
        doc.add_paragraph(f"<待推送 B 的 AI 从 {name} 相关头文件中提取外部接口>")

    # 4.X.2.2 内部接口
    doc.add_heading(f"{base}.2.2 内部接口", level=4)
    int_ifs = comp.get("internal_interfaces") or []
    if int_ifs:
        rows = [[
            it.get("source", ""),
            it.get("method", ""),
            it.get("type", "内部接口"),
            it.get("params", ""),
            it.get("description", ""),
        ] for it in int_ifs]
        _add_table(doc, ["接口溯源", "方法名", "接口类型", "参数", "说明"], rows)
    else:
        doc.add_paragraph(f"<待推送 B 的 AI 从 {name} 相关头文件中提取内部接口>")

    # A004 Camera Module 特有：Class Description
    sub_no = 3
    if cid == "A004":
        doc.add_heading(f"{base}.{sub_no} Class Description", level=3)
        classes = comp.get("classes") or []
        if classes:
            rows = [[str(c.get("seq", i + 1)), c.get("class_name", ""), c.get("description", "")]
                    for i, c in enumerate(classes)]
            _add_table(doc, ["序号", "类名", "说明"], rows)
        else:
            doc.add_paragraph(f"<待推送 B 的 AI 从 {name} 头文件中识别类与说明>")
        sub_no += 1

    # A008 Camera Security 特有：安全目标 + 模块构成
    if cid == "A008":
        doc.add_heading(f"{base}.{sub_no} 功能目标（安全性目标）", level=3)
        doc.add_paragraph(comp.get("security_goals") or arch_sections.DEFAULT_SECURITY_GOALS)
        sub_no += 1
        doc.add_heading(f"{base}.{sub_no} 功能模块构成", level=3)
        doc.add_paragraph(comp.get("security_modules") or arch_sections.DEFAULT_SECURITY_MODULES)
        sub_no += 1

    # 场景（状态/时序）
    scenarios = comp.get("scenarios") or []
    if scenarios:
        for scn in scenarios:
            kind = scn.get("kind") or "时序"
            title = scn.get("title") or f"{name} 场景"
            doc.add_heading(f"{base}.{sub_no} {kind}图", level=3)
            doc.add_paragraph(f"场景说明：{title}")
            if scn.get("description"):
                doc.add_paragraph(scn["description"])
            if scn.get("plantuml"):
                doc.add_paragraph("<图：PlantUML 源码（推送 B 嵌入 PNG）>")
                code_p = doc.add_paragraph()
                code_p.add_run("```plantuml\n" + scn["plantuml"].strip() + "\n```").italic = True
            sub_no += 1
    else:
        doc.add_heading(f"{base}.{sub_no} 时序图", level=3)
        doc.add_paragraph(f"<待推送 B 的 AI 从 {name} 的使用场景生成时序图>")


# ---- docx 导出主入口 ----

def export_swe2_docx(project: dict, out_path: str) -> str:
    """程序化生成 SWE.2 软件架构&概要设计书 docx（1/4/7 章完整骨架）。"""
    from docx import Document
    from docx.shared import Pt

    aspice = project.get("aspice", {}) or {}
    swe2 = aspice.get("swe2", {}) or {}
    project_code = aspice.get("project_code", "") or project.get("name", "")
    meta = project.get("meta", {}) or {}
    mappings = swe2.get("mappings", []) or []
    components = swe2.get("components", []) or []
    overview = swe2.get("overview") or arch_sections.default_overview()
    integration = swe2.get("integration") or arch_sections.default_integration()
    history = project.get("history") or [{
        "date": datetime.now().strftime("%Y/%m/%d"),
        "version": meta.get("doc_version", "V1.0"),
        "author": meta.get("modifier", ""),
        "change": "初版",
    }]
    reviews = project.get("reviews") or []

    doc = Document()

    # ===== 封面 =====
    title_p = doc.add_paragraph()
    title_p.alignment = 1
    title_run = title_p.add_run(f"{project_code}项目\n软件架构&概要设计书")
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

    # ===== 历史记录 =====
    doc.add_heading("历史记录", level=1)
    hist_rows = []
    for h in history:
        hist_rows.append([
            h.get("date", ""),
            h.get("version", ""),
            h.get("author", ""),
            h.get("change", ""),
        ])
    _add_table(doc, ["日期", "版本号", "作者", "修改内容"], hist_rows)

    # ===== 评审记录 =====
    doc.add_heading("评审记录", level=1)
    if reviews:
        rev_rows = [[
            r.get("version", ""),
            r.get("date", ""),
            r.get("reviewer", ""),
            r.get("approver", ""),
            r.get("comment", ""),
        ] for r in reviews]
    else:
        rev_rows = [["", "", "", "", ""]]
    _add_table(doc, ["版本号", "评审日期", "评审人", "审批人", "评审意见"], rev_rows)

    # ===== 目录提示 =====
    doc.add_heading("目录", level=1)
    toc_p = doc.add_paragraph()
    toc_p.add_run("（在 Word 中打开后，右键此处或按 F9 更新域即可生成目录）").italic = True

    doc.add_page_break()

    # ===== 1 概述 =====
    doc.add_heading("1 概述（架构&概要）", level=1)

    doc.add_heading("1.1 目的", level=2)
    doc.add_paragraph(
        (overview.get("purpose") or "").strip()
        or arch_sections.default_overview_purpose(project_code)
    )

    doc.add_heading("1.2 范围", level=2)
    doc.add_paragraph((overview.get("scope") or "").strip() or arch_sections.DEFAULT_OVERVIEW_SCOPE)

    doc.add_heading("1.3 术语定义", level=2)
    terms = overview.get("terms") or arch_sections.DEFAULT_TERMS
    _add_table(doc, ["缩写和术语", "定义"], [[t.get("term", ""), t.get("definition", "")] for t in terms])

    doc.add_heading("1.4 参考文档", level=2)
    ref_docs = overview.get("ref_docs") or arch_sections.build_ref_docs_from_project(project)
    _add_table(doc, ["NO", "参考文献名称", "文件版本", "说明"],
               [[r.get("no", ""), r.get("name", ""), r.get("version", ""), r.get("note", "")] for r in ref_docs])

    doc.add_heading("1.5 假设及依赖", level=2)
    doc.add_paragraph("关键依赖：")
    assumptions = overview.get("assumptions") or arch_sections.DEFAULT_ASSUMPTIONS
    _add_table(doc, ["输入项", "输入时间", "描述"],
               [[a.get("input", ""), a.get("time", ""), a.get("description", "")] for a in assumptions])
    doc.add_paragraph("项目假设：")
    for s in overview.get("project_assumptions") or arch_sections.DEFAULT_PROJECT_ASSUMPTIONS:
        doc.add_paragraph(s, style="List Bullet")

    # ===== 2 需求列表 =====
    doc.add_heading("2 需求列表（架构&概要）", level=1)
    if mappings:
        _add_table(doc, ["SWE.1", "SWE.2", "ID含义", "备注", "发布版本"],
                   [[m.get("swe1_id", ""), m.get("swe2_id", ""), m.get("component", ""),
                     m.get("description", "")[:60], m.get("release_version", "")] for m in mappings])
    else:
        doc.add_paragraph('<尚未生成映射，可在 SWE.2 页面点击"规则生成"或"AI 生成映射">')

    # ===== 3 软件设计（简版） =====
    doc.add_heading("3 软件设计（架构&概要）", level=1)
    doc.add_heading("3.1 简介", level=2)
    doc.add_paragraph("通过图表描述模块/功能的边界，简要描述模块依赖的接口以及提供的接口，描述细化的 Component 以及内部接口。")
    doc.add_heading("3.2 静态信息", level=2)
    doc.add_paragraph("此软件系统使用了 Nvidia Drive-OS NvSIPL 架构。SIPL 架构是 DriveOS 中 NvMedia 中的一个组成部分，"
                      "抽象了与相机相关硬件设备（相机、EEPROM、Serializer、Deserializer 等）的操作，"
                      "并提供对平台的编程接口来捕捉和处理图片（ISP）。")
    doc.add_paragraph("<架构图：推送 B 的 AI 生成后以 PNG 嵌入>")
    doc.add_heading("3.3 接口信息", level=2)
    doc.add_paragraph("外部接口与内部接口详见第 4 章各组件的接口信息小节。")
    doc.add_heading("3.4 动态行为信息", level=2)
    doc.add_paragraph("状态迁移图与时序图详见第 4 章各组件的场景小节。")

    # ===== 4 模块设计 =====
    doc.add_heading("4 模块设计（概要设计）", level=1)
    for idx, comp in enumerate(components, start=1):
        cid = comp.get("id", "")
        linked = _collect_linked_reqs_for_component(mappings, cid)
        _render_component_section(doc, comp, chapter_no=idx, linked_reqs=linked)

    # ===== 5 资源消耗 =====
    doc.add_heading("5 资源消耗", level=1)
    doc.add_heading("5.1 内存", level=2)
    _add_table(doc, ["指标", "目标值", "实测值", "备注"], [["", "", "", ""]])
    doc.add_heading("5.2 CPU", level=2)
    _add_table(doc, ["指标", "目标值", "实测值", "备注"], [["", "", "", ""]])
    doc.add_paragraph("KPI 指标按需求文档定义执行。")

    # ===== 6 备选软件架构 =====
    doc.add_heading("6 备选软件架构（概要设计）", level=1)
    doc.add_paragraph("当前架构基于 NVIDIA Drive-OS NvSIPL，已覆盖项目需求；无其他备选架构。"
                      "若后续硬件平台变更，可考虑切换到对应平台 SDK 的等价组件。")

    # ===== 7 系统集成 =====
    doc.add_heading("7 系统集成（概要设计）", level=1)
    doc.add_heading("7.1 各模块的集成顺序", level=2)
    doc.add_paragraph(integration.get("order") or arch_sections.DEFAULT_INTEGRATION_ORDER)

    doc.add_heading("7.2 集成注意事项", level=2)
    for i, p in enumerate(integration.get("principles") or arch_sections.DEFAULT_INTEGRATION_PRINCIPLES, start=1):
        doc.add_heading(f"7.2.{i} {p.get('title', '')}", level=3)
        doc.add_paragraph(p.get("description", ""))

    doc.save(out_path)
    return out_path


# ---- xlsx 导出（程序化）----

def export_swe2_xlsx(project: dict, out_path: str) -> str:
    """程序化生成 SWE.2 映射表 xlsx（4 个 sheet：需求映射 + 组件属性 + 术语定义 + 参考文档）。"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

    aspice = project.get("aspice", {}) or {}
    swe2 = aspice.get("swe2", {}) or {}
    mappings = swe2.get("mappings", []) or []
    components = swe2.get("components", []) or []
    overview = swe2.get("overview") or arch_sections.default_overview()

    wb = Workbook()

    header_font = Font(bold=True)
    header_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    thin = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    wrap = Alignment(wrap_text=True, vertical="top")

    def _write_sheet(ws, headers: list[str], rows: list[list], col_widths: list[int]):
        for ci, h in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=ci, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.border = border
            cell.alignment = wrap
        for ri, row_data in enumerate(rows, start=2):
            for ci, val in enumerate(row_data, start=1):
                cell = ws.cell(row=ri, column=ci, value=val)
                cell.border = border
                cell.alignment = wrap
        for ci, w in enumerate(col_widths, start=1):
            ws.column_dimensions[chr(64 + ci)].width = w

    # 映射表 sheet
    ws = wb.active
    ws.title = "需求映射"
    map_rows = [[
        m.get("swe1_id", ""),
        m.get("swe2_id", ""),
        m.get("component", ""),
        m.get("description", ""),
        m.get("release_version", ""),
    ] for m in mappings]
    _write_sheet(ws, ["SWE.1", "SWE.2", "ID含义", "备注", "发布版本"], map_rows, [22, 28, 18, 40, 14])

    # 组件属性 sheet
    ws2 = wb.create_sheet("组件属性")
    comp_rows = []
    for comp in components:
        for attr in ["Name", "I2C Address", "Model"]:
            val = comp.get("name" if attr == "Name" else
                           "i2c_addr" if attr == "I2C Address" else "model", "")
            comp_rows.append([comp.get("name", ""), attr, val])
    _write_sheet(ws2, ["组件", "属性", "数值"], comp_rows, [20, 18, 24])

    # 术语定义 sheet
    ws3 = wb.create_sheet("术语定义")
    term_rows = [[t.get("term", ""), t.get("definition", "")] for t in (overview.get("terms") or [])]
    _write_sheet(ws3, ["缩写和术语", "定义"], term_rows, [18, 60])

    # 参考文档 sheet
    ws4 = wb.create_sheet("参考文档")
    ref_rows = [[r.get("no", ""), r.get("name", ""), r.get("version", ""), r.get("note", "")]
                for r in (overview.get("ref_docs") or [])]
    _write_sheet(ws4, ["NO", "参考文献名称", "文件版本", "说明"], ref_rows, [8, 40, 14, 30])

    wb.save(out_path)
    return out_path


# ============================================================================
# v2：模板引擎版本（docxtpl + swe2_arch.docx）
# ============================================================================
# 推送 E 引入。老的 export_swe2_docx 用 python-docx 手工拼装样式对不齐；
# v2 走模板引擎，样式/编号/页眉由 swe2_arch.docx 承载，Python 只做 context 组装。
# 老函数标记 DEPRECATED 保留做 fallback，推送 G 结束后删除。


def _build_swe2_context(project: dict) -> dict:
    """
    把 project dict 规整成 Swe2Context（Pydantic 校验）再 dump 回 dict 给模板用。
    字段映射做在这里，模板只认 schema 里的字段名（content / review_date / opinion）。
    """
    from app.schemas.aspice.swe2_schema import Swe2Context  # 延迟导入，避免 loop
    from app.core import arch_sections

    aspice = project.get("aspice", {}) or {}
    swe2 = aspice.get("swe2", {}) or {}
    project_code = aspice.get("project_code", "") or project.get("name", "") or ""
    meta = project.get("meta", {}) or {}

    # history: project 里字段叫 change，schema 叫 content
    history_src = project.get("history") or [{
        "date": datetime.now().strftime("%Y/%m/%d"),
        "version": meta.get("doc_version", "V1.0"),
        "author": meta.get("modifier", ""),
        "change": "初版",
    }]
    history_rows = [
        {
            "date": h.get("date", ""),
            "version": h.get("version", ""),
            "author": h.get("author", ""),
            "content": h.get("content") or h.get("change", ""),
        }
        for h in history_src
    ]

    # reviews: date→review_date, comment→opinion
    reviews_src = project.get("reviews") or []
    review_rows = [
        {
            "version": r.get("version", ""),
            "review_date": r.get("review_date") or r.get("date", ""),
            "reviewer": r.get("reviewer", ""),
            "approver": r.get("approver", ""),
            "opinion": r.get("opinion") or r.get("comment", ""),
        }
        for r in reviews_src
    ]

    project_block = {
        "name": f"{project_code}项目 软件架构&概要设计书" if project_code else "软件架构&概要设计书",
        "version": meta.get("doc_version", "V1.0"),
        "company": meta.get("company", "中科创达软件股份有限公司"),
        "history": history_rows,
        "reviews": review_rows,
    }

    # overview: 用户已存则用用户的，否则兜底 default_overview + 派生 purpose/scope
    overview_src = swe2.get("overview") or {}
    overview_block = {
        "purpose": overview_src.get("purpose") or arch_sections.default_overview_purpose(project_code),
        "scope": overview_src.get("scope") or arch_sections.DEFAULT_OVERVIEW_SCOPE,
        "terms": overview_src.get("terms") or arch_sections.default_overview()["terms"],
        "ref_docs": overview_src.get("ref_docs") or arch_sections.build_ref_docs_from_project(project),
        "assumptions": overview_src.get("assumptions") or arch_sections.default_overview()["assumptions"],
        "project_assumptions": overview_src.get("project_assumptions") or list(arch_sections.DEFAULT_PROJECT_ASSUMPTIONS),
    }

    # mappings: SWE.1 → SWE.2 映射（现有字段名已和 schema 对齐，兜底空串）
    mappings_src = swe2.get("mappings") or []
    mapping_rows = [
        {
            "swe1_id": m.get("swe1_id", ""),
            "swe2_id": m.get("swe2_id", ""),
            "id_meaning": m.get("id_meaning") or m.get("component_name", ""),
            "remark": m.get("remark", ""),
            "version": m.get("version", ""),
        }
        for m in mappings_src
    ]

    # components: 模板按 ID 固定索引（components_by_id.A001 ~ A009），
    # 任何缺失的组件都要补齐占位，否则 Jinja 渲染会报 "no attribute AXXX"
    components_src = swe2.get("components") or []
    user_by_id = {c.get("id", ""): c for c in components_src if c.get("id")}
    merged = []
    for cid, cname in _COMPONENTS.items():
        if cid in user_by_id:
            merged.append(user_by_id[cid])
        else:
            merged.append({"id": cid, "name": cname, **arch_sections.default_component_fields(cid, cname)})
    # 用户自定义但不在骨架里的组件（例如 A010 以后）追加在后面
    for c in components_src:
        cid = c.get("id", "")
        if cid and cid not in _COMPONENTS:
            merged.append(c)
    components_src = merged

    comp_rows = []
    for c in components_src:
        cid = c.get("id", "")
        cname = c.get("name", "")
        defaults = arch_sections.default_component_fields(cid, cname)
        comp_rows.append({
            "id": cid,
            "name": cname,
            "model": c.get("model", "") or "",
            "i2c_addr": c.get("i2c_addr", "") or "",
            "function_desc": c.get("function_desc") or defaults["function_desc"],
            "linked_req_ids": c.get("linked_req_ids") or [],
            "external_interfaces": c.get("external_interfaces") or [],
            "internal_interfaces": c.get("internal_interfaces") or [],
            "classes": c.get("classes") or [],
            "scenarios": c.get("scenarios") or [],
            "security_goals": c.get("security_goals") or defaults.get("security_goals", ""),
            "security_modules": c.get("security_modules") or defaults.get("security_modules", ""),
        })

    # integration
    integration_src = swe2.get("integration") or {}
    integration_block = {
        "order": integration_src.get("order") or arch_sections.DEFAULT_INTEGRATION_ORDER,
        "principles": integration_src.get("principles") or list(arch_sections.DEFAULT_INTEGRATION_PRINCIPLES),
    }

    raw = {
        "project": project_block,
        "overview": overview_block,
        "mappings": mapping_rows,
        "components": comp_rows,
        "integration": integration_block,
    }
    # 过 Pydantic 校验 + 补 computed_field (components_by_id / principles_by_key)
    ctx = Swe2Context(**raw)
    return ctx.model_dump()


def export_swe2_docx_v2(project: dict, out_path: str) -> str:
    """SWE.2 模板引擎版导出（推送 E）。

    走 app/templates/aspice/swe2_arch.docx 模板，样式/编号/页眉页脚由模板承载。
    对比旧版 export_swe2_docx:
      - 不再手工 add_heading / add_paragraph 拼样式
      - 循环表格通过 {%tr for %} 由 docxtpl 展开
      - 字段单一来源 = app/schemas/aspice/swe2_schema.py
    """
    from app.core.template_engine import TemplateRenderer

    context = _build_swe2_context(project)
    renderer = TemplateRenderer("swe2_arch")
    buf = renderer.render(context)
    with open(out_path, "wb") as f:
        f.write(buf.getvalue())
    return out_path
