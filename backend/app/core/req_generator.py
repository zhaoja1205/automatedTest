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
    existing_or_max = id_chain.next_or_seq(existing) - 1

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

    requirements = []
    idx = 0
    for line in lines:
        idx += 1
        or_id = id_chain.derive_or(project_code, existing_or_max + idx)
        req_id = id_chain.derive_req(or_id, 1)
        requirements.append({
            "or_id": or_id,
            "req_id": req_id,
            "software_mark": "原始",
            "content": line[:200],
            "or_desc": line[:200],
            "sw_req_desc": line[:120],
            "category": "Functional Requirements，Basic Functions",
            "asil": "QM",
            "correctness": "Correct",
            "feasibility": "Feasible",
            "exception": "N/A",
            "milestone": "",
            "owner": "",
            "input_source": "客户原始需求",
            "priority": 2,
            "actual_time": "NA",
            "release_version": "V1.0",
            "operation": "",
            "analysis": "",
        })

    return requirements


# ---- 导出（委托 skill 脚本：build_docx / build_excel，模板填充）----

def export_swe1_docx(project: dict, out_path: str) -> str:
    """SWE.1 软件需求说明书 docx — 通过 aspice_adapter 转 skill project.json，
    再调 build_docx.build() 填充双语四小节 SRS 模板。"""
    from app.core import aspice_adapter
    from app.core import build_docx

    skill_json = aspice_adapter.to_skill_project(project)
    return build_docx.build(skill_json, out_path)


def export_swe1_xlsx(project: dict, out_path: str) -> str:
    """SWE.1 需求详细表 xlsx — 通过 aspice_adapter 转 skill project.json，
    再调 build_excel.build() 填充 24 列 7 sheet Excel 模板。"""
    from app.core import aspice_adapter
    from app.core import build_excel

    skill_json = aspice_adapter.to_skill_project(project)
    return build_excel.build(skill_json, out_path)
