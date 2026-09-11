"""
ASPICE 适配器层 — 把 creator project 的 aspice 段转为 skill 脚本期望的 project.json。

skill 的 build_excel.py / build_docx.py / aspice_validate.py 操作的是 skill 自己的
project.json 结构（project/document/inputs/requirements/risks/srs 六块），与我们
project.json["aspice"] 的结构不同。本模块负责两者间的转换。

转换方向：
    project.json["aspice"]  →  to_skill_project()  →  skill project.json

字段映射规则见 plan 文档中的字段映射表。
"""
from typing import Optional


# software_mark（中文枚举）→ flag（skill 英文枚举）
FLAG_MAP = {
    "原始": "Original",
    "新增": "Add",
    "删除": "Deleted",
    "变更": "Modified",
    # 兼容已存的英文值
    "Original": "Original",
    "Add": "Add",
    "Deleted": "Deleted",
    "Modified": "Modified",
}

# skill category 枚举（全角逗号）
CATEGORY_OPTIONS = [
    "Functional Requirements，Basic Functions",
    "Functional Requirements，Safety Requirements",
    "Functional Requirements，Cybersecurity Requirements",
    "Non-Functional Requirements",
    "Non-camera driver/tuning requirements",
]

# ASIL 枚举
ASIL_OPTIONS = ["QM", "ASIL A", "ASIL B", "ASIL C", "ASIL D", "N/A"]

# Deleted 行固定话术
DELETED_BOILERPLATE = {
    "or_id": "N/A", "or_desc": "N/A", "req_id": "N/A",
    "sw_req_desc": "N/A", "test_case_id": "NA",
    "module": "Software Requirements",
    "category": "Non-camera driver/tuning requirements",
    "asil": "N/A", "correctness": "N/A", "feasibility": "N/A",
    "exception": "N/A", "priority": "N/A",
    "release_time": "N/A", "ra_deadline": "N/A",
    "actual_time": "N/A", "release_version": "N/A",
    "owner": "N/A", "memo": "Guaranteed by other modules",
    "arch_doc": "N/A",
}


def _is_cjk(text: str) -> bool:
    """判断文本是否含 CJK 字符。"""
    return any('一' <= c <= '鿿' for c in text)


def _split_bilingual(text: str) -> tuple[list[str], list[str]]:
    """把一段文本拆成 (EN, CN) 双语列表。

    如果文本含 ' / ' 分隔，按语言检测分配前后半到 EN/CN（不假设顺序）；
    否则按是否含 CJK 分配到 CN 或 EN。
    """
    if not text:
        return [], []
    text = text.strip()
    if " / " in text:
        parts = text.split(" / ", 1)
        a, b = parts[0].strip(), parts[1].strip()
        # 按语言检测：含 CJK 的归 CN，纯英文的归 EN
        if _is_cjk(a) and not _is_cjk(b):
            en, cn = b, a
        elif _is_cjk(b) and not _is_cjk(a):
            en, cn = a, b
        elif _is_cjk(a) and _is_cjk(b):
            # 两半都是中文 → 全归 CN
            en, cn = [], text
        else:
            # 两半都是英文 → 全归 EN
            en, cn = text, []
        return ([en] if en else []), ([cn] if cn else [])
    # 无分隔符：按是否含 CJK 分配
    if _is_cjk(text):
        return [], [text]
    return [text], []


def _apply_deleted_boilerplate(req: dict) -> dict:
    """Deleted 行补全固定话术，仅保留 A/B/C/D/E/S 列实际值。"""
    result = dict(DELETED_BOILERPLATE)
    result["input"] = req.get("input_source", "")
    result["chapter"] = req.get("chapter", "")
    result["no"] = req.get("no", "")
    result["content"] = req.get("content", "")
    result["flag"] = "Deleted"
    return result


def _build_requirement_row(req: dict, swe2_mappings: list[dict]) -> dict:
    """把 aspice requirement 映射为 skill requirement 24 列。"""
    flag = FLAG_MAP.get(req.get("software_mark", "原始"), "Original")

    # Deleted 行走固定话术
    if flag == "Deleted":
        return _apply_deleted_boilerplate(req)

    # 反查 arch_doc（X 列）：该 req_id 对应的所有 swe2_id
    req_id = req.get("req_id", "")
    arch_docs = []
    for m in swe2_mappings:
        if m.get("swe1_id") == req_id and m.get("swe2_id"):
            arch_docs.append(m["swe2_id"])
    arch_doc = "、".join(arch_docs) if arch_docs else "N/A"

    return {
        "input": req.get("input_source", "") or "客户原始需求",
        "chapter": req.get("chapter", "") or None,
        "no": req.get("no", "") or None,
        "content": req.get("content", "") or None,
        "flag": flag,
        "or_id": req.get("or_id", "") or None,
        "or_desc": req.get("or_desc", "") or None,
        "req_id": req_id or None,
        "sw_req_desc": req.get("sw_req_desc", "") or req.get("content", "") or None,
        "test_case_id": req.get("test_case_id", "") or "NA",
        "module": "Software Requirements",
        "category": _normalize_category(req.get("category", "")),
        "asil": req.get("asil", "QM") or "QM",
        "correctness": req.get("correctness", "Correct") or "Correct",
        "feasibility": req.get("feasibility", "Feasible") or "Feasible",
        "exception": req.get("exception", "N/A") or "N/A",
        "priority": req.get("priority", 2) if req.get("priority") else 2,
        "release_time": req.get("milestone", "") or None,
        "ra_deadline": req.get("ra_deadline", "") or None,
        "actual_time": req.get("actual_time", "NA") or "NA",
        "release_version": req.get("release_version", "V1.0") or "V1.0",
        "owner": req.get("owner", "") or None,
        "memo": req.get("memo", "") or None,
        "arch_doc": arch_doc,
    }


def _normalize_category(cat: str) -> str:
    """归一化 category 到 skill 枚举（全角逗号）。"""
    if not cat:
        return "Functional Requirements，Basic Functions"
    # 直接匹配已知枚举
    for opt in CATEGORY_OPTIONS:
        if cat == opt:
            return cat
    # 尝试映射常见中文/简写
    cat_lower = cat.lower()
    if "safety" in cat_lower or "安全" in cat:
        return "Functional Requirements，Safety Requirements"
    if "security" in cat_lower or "网络安全" in cat or "安全网络" in cat:
        return "Functional Requirements，Cybersecurity Requirements"
    if "non" in cat_lower and "functional" in cat_lower or "非功能" in cat:
        return "Non-Functional Requirements"
    # 其他归到 Basic Functions
    return "Functional Requirements，Basic Functions"


def _build_srs(swe1: dict, swe2: dict, project_code: str) -> dict:
    """从 SWE.1 需求 + SWE.2 映射组装 SRS 双语四小节结构。"""
    requirements = swe1.get("requirements", [])
    topology = swe1.get("topology", [])
    kpi = swe1.get("kpi", [])
    mappings = swe2.get("mappings", [])

    # 按分类分章：功能需求（ch2）+ 非功能需求（ch3）
    functional_sections = []
    nonfunctional_sections = []

    for i, req in enumerate(requirements, start=1):
        flag = FLAG_MAP.get(req.get("software_mark", "原始"), "Original")
        if flag == "Deleted":
            continue

        category = _normalize_category(req.get("category", ""))
        is_nonfunctional = "Non-Functional" in category

        content = req.get("content", "")
        desc_en, desc_cn = _split_bilingual(content)
        op_en, op_cn = _split_bilingual(req.get("operation", ""))
        analysis_en, analysis_cn = _split_bilingual(req.get("analysis", ""))

        req_id = req.get("req_id", "")
        asil = req.get("asil", "QM") or "QM"

        section = {
            "title_en": req.get("sw_req_desc", "") or content[:50] if content else f"Requirement {i}",
            "title_cn": "",
            "req_ids": [req_id] if req_id else [],
            "desc_en": desc_en,
            "desc_cn": desc_cn,
            "op_en": op_en or ["<TBD: operation description>"],
            "op_cn": op_cn or ["<待补：操作描述>"],
            "asil": asil,
            "analysis_en": analysis_en or ["[TBD: need interface-level design from engineering team]"],
            "analysis_cn": analysis_cn or ["[待补：需人工/设计库补充接口级设计]"],
        }

        if is_nonfunctional:
            nonfunctional_sections.append(section)
        else:
            functional_sections.append(section)

    chapters = []
    if functional_sections:
        chapters.append({
            "title_en": "Functional requirements",
            "title_cn": "功能需求",
            "kind": "functional",
            "intro_en": ["This chapter describes the functional requirements of the camera driver software."],
            "intro_cn": ["本章描述相机驱动软件的功能需求。"],
            "sections": functional_sections,
        })
    if nonfunctional_sections:
        chapters.append({
            "title_en": "Non functional requirements",
            "title_cn": "非功能需求",
            "kind": "nonfunctional",
            "intro_en": ["This chapter describes the non-functional requirements of the camera driver software."],
            "intro_cn": ["本章描述相机驱动软件的非功能需求。"],
            "sections": nonfunctional_sections,
        })

    # 第 4 章：其他需求
    kpi_body = []
    for item in kpi:
        kpi_body.append(f"KPI{item.get('seq', '')}: {item.get('desc', '')}")

    chapter4 = {
        "title": "Other requirements其他需求",
        "sections": [
            {"title": "Quality requirements质量需求", "body_style": "Body Text",
             "body": ["Follow the software quality specification to control the software development process.",
                      "遵循软件质量规格书内同意之内容进行软件开发过程的管控。"]},
            {"title": "Software design constraints and limitations软件设计约束和限制", "body_style": "Body Text",
             "body": ["The development shall use the NVIDIA Drive-OS NvSIPL framework. Programming language: C/C++.",
                      "需使用NVIDIA框架进行开发，编程语言：C/C++。"]},
        ],
    }
    if kpi_body:
        chapter4["sections"].append({
            "title": "Performance requirements性能需求", "body_style": "Body Text",
            "body": kpi_body,
        })

    return {"chapters": chapters, "chapter4": chapter4}


def to_skill_project(project: dict) -> dict:
    """把 creator project（含 aspice 段）转为 skill 脚本期望的 project.json 结构。

    输出六块：project / document / inputs / requirements / risks / srs
    """
    aspice = project.get("aspice", {})
    swe1 = aspice.get("swe1", {})
    swe2 = aspice.get("swe2", {})
    meta = project.get("meta", {})
    code = aspice.get("project_code", "") or project.get("name", "")
    requirements_raw = swe1.get("requirements", [])
    mappings = swe2.get("mappings", [])
    topology = swe1.get("topology", [])
    risks_raw = swe1.get("risks", [])

    # ---- project 块 ----
    # 环境表
    environment = [
        {"label": "Hardware environment", "value": "NVIDIA Orin-X"},
        {"label": "OS", "value": "QNX"},
    ]
    for item in topology:
        environment.append({
            "label": f"{item.get('group', 'Group')} Sensor",
            "value": f"{item.get('sensor_model', '')} {item.get('fov', '')}".strip(),
        })

    # 依赖
    dependencies = [
        {"item": "Documentation", "time": "", "description": "Camera module specification"},
        {"item": "Camera module", "time": "", "description": "Hardware samples provided"},
        {"item": "Development board", "time": "", "description": "NVIDIA Orin evaluation board"},
    ]

    skill_project = {
        "name": code,
        "module_name": "Camera",
        "overview_en": (
            f"This document specifies the software requirements for the {code} camera driver "
            "based on the NVIDIA Drive-OS NvSIPL framework. It covers functional and "
            "non-functional requirements for camera bring-up, configuration, and operation."
        ),
        "overview_cn": (
            f"本文档规定了基于 NVIDIA Drive-OS NvSIPL 框架的 {code} 相机驱动软件需求。"
            "涵盖相机点亮、配置和操作的功能需求与非功能需求。"
        ),
        "dependencies": dependencies,
        "assumptions": [
            ["Camera module parameters meet the specification.", "相机模组参数达成规格书要求。"],
            ["NVIDIA platform has built-in ISP.", "NV平台自带ISP。"],
        ],
        "standards": ["ASPICE", "ISO26262", "ISO SAE 21434"],
        "reference_docs": [
            f"{code}_Detailed Software Requirements Table需求详细表",
        ],
        "environment": environment,
        "sensor_location": [
            f"{item.get('group', '')}: {item.get('sensor_model', '')} ({item.get('fov', '')})"
            for item in topology
        ] or None,
    }

    # ---- document 块 ----
    # created_at 形如 "2026-09-11 10:00:00"，Excel 日期单元格只存日期，截取到天
    created_at = project.get("created_at", "")
    hist_date = created_at[:10] if created_at else ""

    skill_document = {
        "doc_number": meta.get("doc_number", "") or "ThunderSoft-SVB-06-ZY10",
        "doc_number_word": meta.get("doc_number_word", "") or meta.get("doc_number", "") or "ThunderSoft-SVB-06-ZY07",
        "version": meta.get("doc_version", "V1.0"),
        "history": [{
            "version": meta.get("doc_version", "V1.0"),
            "date": hist_date,
            "description": "Initial version / 初版",
            "author": meta.get("modifier", ""),
            "reviewers": "",
            "approver": "/",
            "status": "PASS",
        }],
        "reviews": [],
    }

    # ---- inputs 块 ----
    # 从 requirements 的 input_source 去重
    input_names = []
    seen = set()
    for req in requirements_raw:
        src = req.get("input_source", "") or "客户原始需求"
        if src not in seen:
            seen.add(src)
            input_names.append({"name": src})

    # ---- requirements 块（24 列）----
    skill_requirements = [_build_requirement_row(req, mappings) for req in requirements_raw]

    # ---- risks 块 ----
    skill_risks = []
    for rk in risks_raw:
        skill_risks.append({
            "req_id": rk.get("req_id", ""),
            "function": rk.get("function", ""),
            "risk": rk.get("risk", ""),
            "solution": rk.get("solution", ""),
            "owner": rk.get("owner", ""),
        })

    # ---- srs 块 ----
    srs = _build_srs(swe1, swe2, code)

    return {
        "project": skill_project,
        "document": skill_document,
        "inputs": input_names,
        "requirements": skill_requirements,
        "risks": skill_risks,
        "srs": srs,
    }
