"""
项目存储 — 基于文件系统的 CRUD（当前由 ASPICE 文档模块使用）。

每个项目存储为 runtime/creator_projects/<project_id>/project.json，
导出产物存储在 runtime/creator_projects/<project_id>/output/ 下。
"""
import json
import os
import shutil
from datetime import datetime
from typing import Optional
from uuid import uuid4


BASE_DIR = os.path.join("runtime", "creator_projects")


def _project_dir(project_id: str) -> str:
    return os.path.join(BASE_DIR, project_id)


def _project_file(project_id: str) -> str:
    return os.path.join(_project_dir(project_id), "project.json")


def _output_dir(project_id: str) -> str:
    return os.path.join(_project_dir(project_id), "output")


# ---- CRUD ----

def list_projects(project_type: Optional[str] = None) -> list[dict]:
    """扫描项目目录，返回摘要列表。

    project_type 可选：creator / aspice。历史项目可能没有 project_type，
    通过已有内容和项目名做兼容推断，避免两个入口互相串项目。
    """
    os.makedirs(BASE_DIR, exist_ok=True)
    result = []
    for name in sorted(os.listdir(BASE_DIR)):
        pf = _project_file(name)
        if not os.path.isfile(pf):
            continue
        try:
            with open(pf, "r", encoding="utf-8") as f:
                data = json.load(f)
            inferred_type = _project_type(data)
            if project_type and inferred_type != project_type:
                continue
            result.append({
                "project_id": data.get("project_id", name),
                "name": data.get("name", ""),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
                "project_type": inferred_type,
            })
        except Exception:
            continue
    return result


def get_project(project_id: str) -> Optional[dict]:
    """读取完整项目数据（含读时迁移：补齐 SWE.2 新增字段）。"""
    pf = _project_file(project_id)
    if not os.path.isfile(pf):
        return None
    with open(pf, "r", encoding="utf-8") as f:
        data = json.load(f)
    return _migrate_project_inplace(data)


def create_project(name: str, project_type: str = "aspice") -> dict:
    """创建空白项目，返回完整项目数据。"""
    project_id = uuid4().hex[:12]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    project = {
        "project_id": project_id,
        "project_type": project_type,
        "name": name,
        "created_at": now,
        "updated_at": now,
        "aspice": _default_aspice(),
    }
    os.makedirs(_project_dir(project_id), exist_ok=True)
    _save(project)
    return project


def save_project(project: dict) -> None:
    """保存项目（覆盖写入）。"""
    project["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(_project_dir(project["project_id"]), exist_ok=True)
    _save(project)


def delete_project(project_id: str) -> bool:
    """删除项目目录。"""
    d = _project_dir(project_id)
    if os.path.isdir(d):
        shutil.rmtree(d)
        return True
    return False


def get_download_path(project_id: str, filename: str) -> Optional[str]:
    """返回可下载文件的绝对路径。仅允许 output/ 目录下的文件。"""
    safe_name = os.path.basename(filename)
    path = os.path.join(_output_dir(project_id), safe_name)
    if os.path.isfile(path):
        return os.path.abspath(path)
    return None


# ---- 内部辅助 ----

def _save(project: dict) -> None:
    pf = _project_file(project["project_id"])
    with open(pf, "w", encoding="utf-8") as f:
        json.dump(project, f, ensure_ascii=False, indent=2)


def _default_aspice() -> dict:
    """ASPICE 文档板块的默认数据结构（SWE.1 需求分析 + SWE.2 架构设计）。

    8 组件 A001~A008 默认属性取自 SWE.2 模板组件属性表，用户可改。
    SWE.1 需求项字段对齐 skill 24 列 Excel 模板（含 ASIL/Test Case ID/架构映射等）。

    SWE.2 新增字段：overview（术语/参考/假设）、integration（集成顺序+6 原则）、
    components[i] 内部结构扩展（function_desc / linked_req_ids / 内外接口 / scenarios 等），
    用于对齐 PreDev 参考文档的 1/4/7 章完整骨架。
    """
    from app.core import arch_sections

    components = [
        {"id": "A001", "name": "Serializer", "model": "MAX96717F", "i2c_addr": "0x40"},
        {"id": "A002", "name": "Deserializer", "model": "MAX96712", "i2c_addr": ""},
        {"id": "A003", "name": "EEPROM", "model": "M24C04", "i2c_addr": "0x54"},
        {"id": "A004", "name": "Camera Module", "model": "", "i2c_addr": ""},
        {"id": "A005", "name": "nvsipl_camera", "model": "", "i2c_addr": ""},
        {"id": "A006", "name": "nvsipl_multicast", "model": "", "i2c_addr": ""},
        {"id": "A007", "name": "PMIC", "model": "MAX20087", "i2c_addr": ""},
        {"id": "A008", "name": "Camera Security", "model": "", "i2c_addr": ""},
    ]
    # 为每个组件补上新增字段的默认空容器
    for comp in components:
        comp.update(arch_sections.default_component_fields(comp["id"], comp["name"]))

    from app.core import arch_sections_swe3

    return {
        "project_code": "",          # 项目代号，大小写不限，原样用于 ID 派生
        "swe1": {
            "requirements": [],       # 需求项列表（字段见 _default_requirement）
            "topology": [],            # 硬件拓扑（Group/sensor 位置）
            "kpi": [],                 # 非功能需求 KPI 列表
            "risks": [],               # 风险表（SWE.1 风险 sheet）
            "current_step": 0,
        },
        "swe2": {
            "mappings": [],            # SWE.1→SWE.2 映射表
            "components": components,
            "overview": arch_sections.default_overview(),       # 概述 (1.1 ~ 1.5)
            "integration": arch_sections.default_integration(), # 系统集成 (7.x)
            "current_step": 0,
        },
        # SWE.3 软件详细设计（14 章骨架 + 9 模块默认结构）
        "swe3": arch_sections_swe3.default_swe3(components),
    }


def _migrate_swe2(swe2: dict) -> dict:
    """老项目兼容：读时补齐缺失字段，不改写盘上文件。

    下次用户主动保存 SWE.2 时才落盘，避免打开列表就全量重写项目。
    """
    from app.core import arch_sections

    if not isinstance(swe2, dict):
        return swe2

    # overview / integration 整段补齐
    if "overview" not in swe2 or not isinstance(swe2.get("overview"), dict):
        swe2["overview"] = arch_sections.default_overview()
    else:
        ov = swe2["overview"]
        default_ov = arch_sections.default_overview()
        for k, v in default_ov.items():
            if k not in ov:
                ov[k] = v

    if "integration" not in swe2 or not isinstance(swe2.get("integration"), dict):
        swe2["integration"] = arch_sections.default_integration()
    else:
        ig = swe2["integration"]
        default_ig = arch_sections.default_integration()
        for k, v in default_ig.items():
            if k not in ig:
                ig[k] = v

    # 组件新增字段补齐
    comps = swe2.get("components") or []
    for comp in comps:
        if not isinstance(comp, dict):
            continue
        comp_id = comp.get("id", "")
        comp_name = comp.get("name", "")
        defaults = arch_sections.default_component_fields(comp_id, comp_name)
        for k, v in defaults.items():
            if k not in comp:
                comp[k] = v

    return swe2


def _migrate_swe3(swe3: dict, swe2: dict) -> dict:
    """SWE.3 读时迁移：补齐缺失的章节字段 / 模块默认结构。

    swe2 作为参考用于派生第 3 章 modular composition（当 swe3 中没有时）。
    """
    from app.core import arch_sections_swe3

    if not isinstance(swe3, dict):
        return swe3

    components = (swe2 or {}).get("components") or []
    defaults = arch_sections_swe3.default_swe3(components)

    for k, v in defaults.items():
        if k not in swe3:
            swe3[k] = v

    # modules 字段若存在但模块数不足，按组件 ID 补齐缺失模块
    try:
        existing_ids = {m.get("component_id") for m in (swe3.get("modules") or []) if isinstance(m, dict)}
        for m in defaults.get("modules", []):
            if m.get("component_id") not in existing_ids:
                swe3.setdefault("modules", []).append(m)
    except Exception:
        pass

    # overview / composition / common_defs / integration / performance / function_evaluation 子字段补齐
    for section_key in ("overview", "composition", "common_defs", "integration",
                        "performance", "function_evaluation"):
        if not isinstance(swe3.get(section_key), dict):
            swe3[section_key] = defaults.get(section_key, {}) or {}
        else:
            sub_default = defaults.get(section_key, {}) or {}
            for k, v in sub_default.items():
                if k not in swe3[section_key]:
                    swe3[section_key][k] = v

    # push_d 补齐（推送 D 新增字段，老项目直接读默认结构）
    pd_defaults = arch_sections_swe3.default_push_d()
    if not isinstance(swe3.get("push_d"), dict):
        swe3["push_d"] = pd_defaults
    else:
        for k, v in pd_defaults.items():
            if k not in swe3["push_d"]:
                swe3["push_d"][k] = v

    return swe3


def _migrate_project_inplace(project: dict) -> dict:
    """对完整项目字典做读时迁移：SWE.2 + SWE.3 字段补齐。"""
    if not isinstance(project, dict):
        return project
    aspice = project.get("aspice")
    if isinstance(aspice, dict):
        swe2 = aspice.get("swe2")
        if isinstance(swe2, dict):
            _migrate_swe2(swe2)
        # SWE.3：缺失时整段默认，存在时逐字段补齐
        if "swe3" not in aspice or not isinstance(aspice.get("swe3"), dict):
            from app.core import arch_sections_swe3
            comps = (aspice.get("swe2") or {}).get("components") or []
            aspice["swe3"] = arch_sections_swe3.default_swe3(comps)
        else:
            _migrate_swe3(aspice["swe3"], aspice.get("swe2") or {})
    return project


def _default_requirement() -> dict:
    """SWE.1 需求项默认字段（对齐 skill 24 列 Excel 模板）。

    字段 → Excel 列映射：
      input_source→A, chapter→B, no→C, content→D, software_mark→E(flag),
      or_id→F, or_desc→G, req_id→H, sw_req_desc→I, test_case_id→J,
      module→K, category→L, asil→M, correctness→N, feasibility→O,
      exception→P, priority→Q, milestone→R(release_time), ra_deadline→S,
      actual_time→T, release_version→U, owner→V, memo→W, arch_doc→X(自动)
    SRS 四小节：operation→.2, analysis→.4（.1=content, .3=asil 自动生成）
    """
    return {
        "or_id": "",                    # F 列 OR ID
        "req_id": "",                   # H 列 ReqID
        "software_mark": "原始",        # E 列 flag（原始/新增/删除/变更 → Original/Add/Deleted/Modified）
        "content": "",                  # D 列 需求描述（双语用 ' / ' 分隔）
        # 新增字段（对齐 skill 24 列）：
        "input_source": "",             # A 列 输入文档名
        "chapter": "",                   # B 列 章节号
        "no": "",                        # C 列 原始序号
        "or_desc": "",                   # G 列 OR 描述
        "sw_req_desc": "",               # I 列 软件需求功能描述
        "test_case_id": "",              # J 列 测试用例 ID
        "category": "",                  # L 列 分类（全角逗号枚举）
        "asil": "QM",                    # M 列 安全等级
        "correctness": "Correct",        # N 列 需求正确性
        "feasibility": "Feasible",       # O 列 需求可行性
        "exception": "N/A",             # P 列 异常处理
        "priority": 2,                   # Q 列 优先级 1-3
        "milestone": "",                 # R 列 项目发布时间
        "ra_deadline": "",               # S 列 RA 截止时间
        "actual_time": "NA",             # T 列 实际完成时间
        "release_version": "V1.0",       # U 列 功能发布版本
        "owner": "",                     # V 列 负责人
        "memo": "",                      # W 列 备注
        "operation": "",                 # SRS .2 操作描述（双语）
        "analysis": "",                  # SRS .4 分析（双语）
    }


def _project_type(project: dict) -> str:
    """返回项目类型：creator / aspice。

    新项目直接读 project_type；历史项目没有该字段时做兼容推断：
    已有测试用例的归 creator；已有 ASPICE 内容或名称包含 ASPICE 的归 aspice；
    其余默认归 creator，避免旧普通项目从用例创建入口消失。
    """
    explicit = project.get("project_type")
    if explicit in ("creator", "aspice"):
        return explicit

    if project.get("functional_cases") or project.get("fault_cases"):
        return "creator"

    aspice = project.get("aspice") or {}
    swe1 = aspice.get("swe1") or {}
    swe2 = aspice.get("swe2") or {}
    has_aspice_content = bool(
        aspice.get("project_code")
        or swe1.get("requirements")
        or swe1.get("topology")
        or swe1.get("kpi")
        or swe1.get("risks")
        or swe2.get("mappings")
    )
    if has_aspice_content or "aspice" in str(project.get("name", "")).lower():
        return "aspice"

    return "creator"
