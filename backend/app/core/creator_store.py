"""
用例创建项目存储 — 基于文件系统的 CRUD。

每个项目存储为 runtime/creator_projects/<project_id>/project.json，
导出产物存储在 runtime/creator_projects/<project_id>/output/ 下。
"""
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from typing import Optional
from uuid import uuid4


BASE_DIR = os.path.join("runtime", "creator_projects")

# gen_cases.py 脚本路径（与本项目一起分发）
_SCRIPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
GEN_SCRIPT = os.path.join(_SCRIPT_DIR, "gen_cases.py")
GEN_TEMPLATE = os.path.join(_SCRIPT_DIR, "templates", "模板_测试用例.xlsx")


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
                "functional_count": len(data.get("functional_cases", [])),
                "fault_count": len(data.get("fault_cases", [])),
                "has_placeholders": _has_placeholders(data),
                "project_type": inferred_type,
            })
        except Exception:
            continue
    return result


def get_project(project_id: str) -> Optional[dict]:
    """读取完整项目数据。"""
    pf = _project_file(project_id)
    if not os.path.isfile(pf):
        return None
    with open(pf, "r", encoding="utf-8") as f:
        return json.load(f)


def create_project(name: str, project_type: str = "creator") -> dict:
    """创建空白项目，返回完整项目数据。"""
    project_id = uuid4().hex[:12]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    project = {
        "project_id": project_id,
        "project_type": project_type,
        "name": name,
        "created_at": now,
        "updated_at": now,
        "meta": _default_meta(),
        "coverage_matrix": {"modules": [], "features": [], "matrix": [], "topology": []},
        "functional_cases": [],
        "fault_cases": [],
        "defaults_used": [],
        "current_step": 0,
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


# ---- 导出 ----

def export_project(project_id: str) -> dict:
    """导出项目：生成 cases.json → 调用 gen_cases.py → 返回文件路径和占位符/默认值清单。"""
    project = get_project(project_id)
    if not project:
        raise FileNotFoundError(f"项目不存在: {project_id}")

    out_dir = _output_dir(project_id)
    os.makedirs(out_dir, exist_ok=True)

    # 组装 cases.json
    cases_data = {
        "meta": project.get("meta", {}),
        "defaults_used": project.get("defaults_used", []),
        "functional_cases": project.get("functional_cases", []),
        "fault_cases": project.get("fault_cases", []),
    }
    cases_json_path = os.path.join(out_dir, "cases.json")
    with open(cases_json_path, "w", encoding="utf-8") as f:
        json.dump(cases_data, f, ensure_ascii=False, indent=2)

    # 内部版 xlsx
    internal_xlsx = os.path.join(out_dir, "测试用例_内部版.xlsx")
    result_internal = subprocess.run(
        [sys.executable, GEN_SCRIPT, cases_json_path,
         "--template", GEN_TEMPLATE,
         "--out", internal_xlsx],
        capture_output=True, text=True, timeout=120,
    )

    # 客户发布版 xlsx
    release_xlsx = os.path.join(out_dir, "测试用例_客户版.xlsx")
    result_release = subprocess.run(
        [sys.executable, GEN_SCRIPT, cases_json_path,
         "--template", GEN_TEMPLATE,
         "--out", release_xlsx,
         "--release"],
        capture_output=True, text=True, timeout=120,
    )

    # 收集占位符信息
    placeholders = _collect_placeholders(project)

    return {
        "json_path": "cases.json",
        "xlsx_internal": "测试用例_内部版.xlsx" if os.path.isfile(internal_xlsx) else None,
        "xlsx_release": "测试用例_客户版.xlsx" if os.path.isfile(release_xlsx) else None,
        "internal_log": result_internal.stdout + result_internal.stderr,
        "release_log": result_release.stdout + result_release.stderr,
        "placeholders": placeholders,
        "defaults_used": project.get("defaults_used", []),
    }


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


def _default_meta() -> dict:
    return {
        "file_number": "",
        "title": "",
        "doc_version": "V1.0",
        "company": "中科创达软件股份有限公司/Thundersoft Co., Ltd.",
        "change_content": "",
        "revision_date": datetime.now().strftime("%Y-%m-%d"),
        "modifier": "",
        "reviewer": "",
        "approver": "",
        "references": [],
        "os": "QNX",
        "equipment_model": "",
        "dev_board": "",
        "test_object": "Camera驱动/Camera Driver",
        "software_version": "",
        "test_version": "",
        "test_cycle": "",
        "tested_components": "",
        "cam_config": "",
        "stream_program": "",
        "fps_by_module": "",
        "debug_dir": "",
        "board_ip": "",
        "board_password": "",
        "command_args": "",
        "feature_criteria": "",
        "jump_host_enabled": False,
        "jump_host_ip": "",
        "jump_host_user": "",
        "jump_host_password": "",
        "jump_host_transfer_dir": "",
        "jump_host_can_ssh": False,
        "execution_mode": "",
        "scp_source_path": "",
        "scp_target_path": "",
        "stream_success_signal": "",
        "functional_timeout": "15",
        "fault_timeout": "30",
        "special_tests": "",
        "fault_expand_mode": "全量展开",
        "fault_source": "",
        "fault_report_mode": "",
        "fault_syslog": False,
        "fault_clear_check": False,
        "driver_deploy_dir": "",
        "test_tool_path": "",
        "exception_handling": "",
        "test_type_scope": "基本功能 / 故障注入 / 异常 / 边界值",
        "method_rule": "功能点=基于需求分析；边界=边界值分析；负向=错误推测法",
        "priority_rule": "多模组并发=P0；单模组基本/故障=P1；压力稳定=P2",
        "id_rule": "功能 001.. 连续；故障接续或按子类分段",
        "generation_scope": "功能+故障",
        "output_format": "先草稿",
        "screenshot_column": "M列",
        "optional_notes": "",
        "fault_id_from_start": False,
    }


def _default_aspice() -> dict:
    """ASPICE 文档板块的默认数据结构（SWE.1 需求分析 + SWE.2 架构设计）。

    8 组件 A001~A008 默认属性取自 SWE.2 模板组件属性表，用户可改。
    SWE.1 需求项字段对齐 skill 24 列 Excel 模板（含 ASIL/Test Case ID/架构映射等）。
    """
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
            "components": [            # 8 组件属性默认模板
                {"id": "A001", "name": "Serializer", "model": "MAX96717F", "i2c_addr": "0x40"},
                {"id": "A002", "name": "Deserializer", "model": "MAX96712", "i2c_addr": ""},
                {"id": "A003", "name": "EEPROM", "model": "M24C04", "i2c_addr": "0x54"},
                {"id": "A004", "name": "Camera Module", "model": "", "i2c_addr": ""},
                {"id": "A005", "name": "nvsipl_camera", "model": "", "i2c_addr": ""},
                {"id": "A006", "name": "nvsipl_multicast", "model": "", "i2c_addr": ""},
                {"id": "A007", "name": "PMIC", "model": "MAX20087", "i2c_addr": ""},
                {"id": "A008", "name": "Camera Security", "model": "", "i2c_addr": ""},
            ],
            "current_step": 0,
        },
    }


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


def _has_placeholders(project: dict) -> bool:
    """快速检查项目是否包含占位符。"""
    for case_list in (project.get("functional_cases", []), project.get("fault_cases", [])):
        for case in case_list:
            for key in ("type", "method", "desc", "pre", "steps", "expected", "priority"):
                val = case.get(key, "")
                if isinstance(val, str) and val.startswith("<待补充"):
                    return True
    return False


def _collect_placeholders(project: dict) -> list[dict]:
    """收集所有占位符。"""
    import re
    placeholders = []
    for category, case_list in [("functional", project.get("functional_cases", [])),
                                 ("fault", project.get("fault_cases", []))]:
        for i, case in enumerate(case_list):
            case_id = case.get("id", f"{i+1:03d}")
            for key in ("type", "method", "desc", "pre", "steps", "expected", "priority"):
                val = case.get(key, "")
                if not isinstance(val, str):
                    continue
                for m in re.finditer(r"<待补充[^>]*>", val):
                    placeholders.append({
                        "category": category,
                        "case_id": case_id,
                        "field": key,
                        "placeholder": m.group(0),
                    })
    return placeholders
