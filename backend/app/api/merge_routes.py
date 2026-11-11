"""
测试用例合并 REST API。

流程：
1. ``POST /api/merge/preview`` 上传主用例与来源用例，返回来源可选用例列表；
2. ``POST /api/merge/execute`` 提交选中的用例 key，生成合并后的 Excel；
3. ``GET /api/merge/download/{token}`` 下载合并结果。
"""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from typing import List
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core.case_merger import CaseMergeError, CaseMerger

router = APIRouter()

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_MERGE_ROOT = os.path.join(_BACKEND_ROOT, "uploads", "merge")
_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
_INVALID_NAME_RE = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def _merge_dir(token: str) -> str:
    if not _TOKEN_RE.match(token or ""):
        raise HTTPException(status_code=400, detail="无效的合并任务标识")
    return os.path.join(_MERGE_ROOT, token)


def _safe_suffix(filename: str) -> str:
    lower = (filename or "").lower()
    if lower.endswith((".xlsx", ".xlsm")):
        return os.path.splitext(lower)[1]
    return ""


def _safe_output_name(filename: str) -> str:
    name = _INVALID_NAME_RE.sub("_", os.path.basename(filename or "")).strip()
    if not name.lower().endswith(".xlsx"):
        name = (name or "merged") + ".xlsx"
    return name[:120]


class MergeExecuteRequest(BaseModel):
    """合并执行请求。"""
    token: str
    case_keys: List[str] = []
    include_results: bool = False
    skip_duplicates: bool = True
    output_filename: str = ""


@router.post("/preview")
async def preview_merge(
    main_file: UploadFile = File(..., description="主用例 Excel"),
    source_file: UploadFile = File(..., description="来源用例 Excel"),
):
    """上传两个用例表，返回来源用例清单与主用例 Sheet 信息。"""
    token = uuid4().hex
    dir_path = os.path.join(_MERGE_ROOT, token)
    os.makedirs(dir_path, exist_ok=True)

    saved = {}
    try:
        for key, upload in (("main", main_file), ("source", source_file)):
            suffix = _safe_suffix(upload.filename or "")
            if not suffix:
                raise HTTPException(
                    status_code=400,
                    detail="仅支持 .xlsx / .xlsm 格式的用例文件",
                )
            path = os.path.join(dir_path, f"{key}{suffix}")
            content = await upload.read()
            if not content:
                raise HTTPException(status_code=400, detail="上传文件为空")
            with open(path, "wb") as fh:
                fh.write(content)
            saved[key] = path

        try:
            data = CaseMerger().preview(saved["main"], saved["source"])
        except CaseMergeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"用例解析失败：{exc}") from exc
    except Exception:
        shutil.rmtree(dir_path, ignore_errors=True)
        raise

    data["token"] = token
    data["main_file"] = main_file.filename or ""
    data["source_file"] = source_file.filename or ""
    return data


@router.post("/execute")
async def execute_merge(req: MergeExecuteRequest):
    """按选中的来源用例执行合并，返回下载地址。"""
    dir_path = _merge_dir(req.token)
    if not os.path.isdir(dir_path):
        raise HTTPException(status_code=404, detail="合并任务不存在或已过期，请重新上传文件")

    files = os.listdir(dir_path)
    main_files = [f for f in files if f.startswith("main.")]
    source_files = [f for f in files if f.startswith("source.")]
    if not main_files or not source_files:
        raise HTTPException(status_code=404, detail="合并任务缺少源文件，请重新上传")

    main_path = os.path.join(dir_path, main_files[0])
    source_path = os.path.join(dir_path, source_files[0])
    out_path = os.path.join(dir_path, "merged.xlsx")

    filename = _safe_output_name(req.output_filename)
    if not req.output_filename:
        filename = f"merged_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

    try:
        result = CaseMerger().merge(
            main_path,
            source_path,
            req.case_keys,
            out_path,
            include_results=req.include_results,
            skip_duplicates=req.skip_duplicates,
        )
    except CaseMergeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"合并失败：{exc}") from exc

    with open(os.path.join(dir_path, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump({"filename": filename}, fh, ensure_ascii=False)

    return {
        "message": (
            f"已合并 {result['merged_count']} 条用例"
            + (f"，跳过重复 {len(result['skipped_duplicates'])} 条"
               if result["skipped_duplicates"] else "")
        ),
        "filename": filename,
        "download_url": f"/api/merge/download/{req.token}",
        "merged_count": result["merged_count"],
        "skipped_duplicates": result["skipped_duplicates"],
        "warnings": result["warnings"],
        "sheet_counts": result["sheet_counts"],
        "created_sheets": result["created_sheets"],
    }


@router.get("/download/{token}")
async def download_merged(token: str):
    """下载合并后的 Excel。"""
    dir_path = _merge_dir(token)
    path = os.path.join(dir_path, "merged.xlsx")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="合并结果不存在，请先执行合并")

    filename = "merged.xlsx"
    meta_path = os.path.join(dir_path, "meta.json")
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as fh:
                filename = (json.load(fh).get("filename") or filename)
        except Exception:
            pass

    from urllib.parse import quote

    encoded = quote(filename)
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )
