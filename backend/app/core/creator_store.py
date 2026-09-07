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

def list_projects() -> list[dict]:
    """扫描项目目录，返回摘要列表。"""
    os.makedirs(BASE_DIR, exist_ok=True)
    result = []
    for name in sorted(os.listdir(BASE_DIR)):
        pf = _project_file(name)
        if not os.path.isfile(pf):
            continue
        try:
            with open(pf, "r", encoding="utf-8") as f:
                data = json.load(f)
            result.append({
                "project_id": data.get("project_id", name),
                "name": data.get("name", ""),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
                "functional_count": len(data.get("functional_cases", [])),
                "fault_count": len(data.get("fault_cases", [])),
                "has_placeholders": _has_placeholders(data),
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


def create_project(name: str) -> dict:
    """创建空白项目，返回完整项目数据。"""
    project_id = uuid4().hex[:12]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    project = {
        "project_id": project_id,
        "name": name,
        "created_at": now,
        "updated_at": now,
        "meta": _default_meta(),
        "coverage_matrix": {"modules": [], "features": [], "matrix": []},
        "functional_cases": [],
        "fault_cases": [],
        "defaults_used": [],
        "current_step": 0,
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
        "fault_id_from_start": False,
    }


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
