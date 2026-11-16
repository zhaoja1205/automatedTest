"""
REST API 路由。

提供：用例管理、Excel 上传/下载、SSH 配置、工作区配置、执行控制、
执行历史记录、测试报告生成与管理。

所有路由通过 request.state.session (SessionState) 访问当前会话的隔离状态，
支持多个 PC 端同时独立测试。
"""
import asyncio
import json
import os
import shutil
import tempfile
from datetime import datetime
from typing import Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Request, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse, Response, StreamingResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, Field

from app.core.test_case import TestCase, SSHConfig, SSHStatus, WorkspaceConfig, AIConfig, CleanupConfig
from app.core.execution_state import ExecutionTask
from app.core.ssh_manager import SSHManager
from app.core.config_store import ConfigStore, AIProfileStore, AIProfileEntry
from app.core.command_parser import CommandParser, CommandStep

router = APIRouter()

# AI 配置使用全局 ConfigStore，所有 session 共享同一份配置
# （区别于 SSH/workspace 等 per-session 配置）
_global_config_store = ConfigStore(base_dir="runtime")
# AI 配置方案（多套配置的快照，激活时写回 ai_config）
_ai_profile_store = AIProfileStore(base_dir="runtime")


class ExecuteRequest(BaseModel):
    """执行请求，可指定待执行用例列表（case_key 唯一标识）。"""
    case_ids: List[str] = []  # 兼容旧逻辑，实际传的是 case_key


class CommandPreviewRequest(BaseModel):
    """命令预览请求；case_keys 为空时预览当前所有已选用例。"""
    case_keys: List[str] = []


class CaseUpdateRequest(BaseModel):
    """更新单条用例字段；支持测试步骤与预期结果。"""
    case_key: str = ""
    case_id: str = ""
    test_steps: Optional[str] = None
    expected_result: Optional[str] = None


class RestoreCaseTerminalLog(BaseModel):
    """日志草稿中的单个终端日志。"""
    label: str = ""
    content: str = ""


class RestoreCaseLogItem(BaseModel):
    """日志草稿箱中的单条用例日志。"""
    case_key: str = ""
    case_id: str = ""
    log_text: str = ""
    remarks: str = ""
    status: str = ""
    actual_result: str = ""
    judgment: str = ""
    ai_evidence: List[str] = Field(default_factory=list)
    # 按终端分开的日志（与板端日志系统同一存储格式）
    terminals: List[RestoreCaseTerminalLog] = Field(default_factory=list)


class RestoreCaseLogsRequest(BaseModel):
    """恢复执行日志草稿请求。"""
    cases: List[RestoreCaseLogItem] = Field(default_factory=list)


@router.post("/excel/upload")
async def upload_excel(request: Request, file: UploadFile = File(...)):
    """上传 Excel 用例文件"""
    session = request.state.session
    # 用 basename 清洗文件名，避免路径穿越
    safe_name = os.path.basename(file.filename or "upload.xlsx")
    if not safe_name:
        safe_name = "upload.xlsx"
    file_path = os.path.join("uploads", session.session_id, safe_name)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    # 加载用例
    from app.core.excel_handler import ExcelHandler
    handler = ExcelHandler()
    cases = handler.load(file_path)
    session.test_cases = [c.model_dump() for c in cases]
    session.excel_path = file_path
    # 同步 Excel 中的 BugList统计 页，供前端 BugList 页签展示
    session.bug_list = list(handler.bug_list)
    session.bug_sheet = handler.bug_sheet_name

    ordered_sheets = []
    seen = set()
    for c in cases:
        if c.source_sheet and c.source_sheet not in seen:
            ordered_sheets.append(c.source_sheet)
            seen.add(c.source_sheet)

    # 异步触发 AI 步骤预解析（不阻塞上传响应）
    try:
        ai_config = _global_config_store.load(
            "ai_config",
            AIConfig, AIConfig(),
        )
        if ai_config.ai_enabled and ai_config.ai_auto_parse_steps:
            asyncio.create_task(_async_ai_parse_steps(session))
    except Exception:
        pass  # 异步解析失败不影响上传响应

    return {
        "message": "上传成功",
        "case_count": len(cases),
        "sheets": ordered_sheets,
        "bug_sheet": session.bug_sheet,
        "bug_list": session.bug_list,
    }


# 规则解析可执行步骤的 kind 集合（无需 AI 介入即可判定）
_RULE_EXECUTABLE_KINDS = {"command", "cd", "nvsipl_input", "enter_dir"}


def _rule_parse_steps(step_text: str) -> Optional[dict]:
    """规则先行：用 CommandParser 解析测试步骤文本。

    若规则已能解出至少 1 条可执行命令（command/cd/nvsipl_input/enter_dir），
    则直接返回与 AI parse_steps 同构的结果，跳过 AI 调用。
    观察类/确认类步骤规则会标为 skip，这与 AI 的处理一致，无需 AI 介入。
    返回 None 表示规则未解出任何可执行命令，仍需调用 AI。
    """
    if not step_text or not step_text.strip():
        return None
    try:
        csteps: list[CommandStep] = CommandParser.parse(step_text)
    except Exception:
        return None
    if not csteps:
        return None

    total = len(csteps)
    parsed = []
    for cs in csteps:
        kind = cs.kind if cs.kind in {"command", "cd", "nvsipl_input", "manual", "skip"} else "skip"
        parsed.append({
            "command": cs.command or "",
            "description": cs.description or "",
            "kind": kind,
            "terminal": cs.terminal or "主终端",
            "confidence": 1.0 if kind in _RULE_EXECUTABLE_KINDS else 0.5,
            "step_num": cs.step_num or 0,
        })

    executable = sum(1 for s in parsed if s["kind"] in _RULE_EXECUTABLE_KINDS)
    # 至少 1 条可执行命令即采用规则结果——观察/确认步骤规则标 skip 与 AI 一致
    if executable == 0:
        return None

    return {
        "parsed_steps": parsed,
        "total": total,
        "ai_recognized": executable,
        "_source": "rule",
    }


async def _async_ai_parse_steps(session):
    """上传后异步触发 AI 步骤解析（不阻塞上传响应）。

    当 session.is_running 变为 True 时自动停止，避免与执行期间的
    AI 判定竞争 API 配额。
    """
    try:
        service = _get_ai_service(session)
        if not service.enabled:
            return

        cases = _get_cases_as_objects(session)
        if not cases:
            return

        if not hasattr(session, 'ai_parsed_steps'):
            session.ai_parsed_steps = {}

        total = len(cases)
        success = 0
        failed = 0
        rule_hit = 0  # 规则先行命中数（未调 AI）

        await session.ws_manager.broadcast({
            "type": "ai_parse_progress",
            "current": 0,
            "total": total,
            "message": "步骤解析开始（规则先行 + AI 兜底）...",
        })

        # ---- 第一遍：规则先行 + 步骤文本去重 ----
        # 对每条用例先用 CommandParser 规则解析；命中即直接采用，不调 AI。
        # 剩余用例按 test_steps 文本去重，相同文本只调一次 AI，结果广播给所有同文用例。
        pending_ai: list[tuple[int, str, TestCase]] = []  # (原始序号, case_key, case)
        text_to_keys: dict[str, list[str]] = {}  # 去重后的步骤文本 → 需要回填的 case_key 列表

        for i, case in enumerate(cases):
            if not case.test_steps or not case.test_steps.strip():
                continue
            case_key = case.case_key or f"{case.source_sheet}:{case.row_number}:{case.case_id}"

            # 规则先行
            rule_result = _rule_parse_steps(case.test_steps)
            if rule_result is not None:
                session.ai_parsed_steps[case_key] = rule_result["parsed_steps"]
                success += 1
                rule_hit += 1
                continue

            # 规则未解出，加入 AI 待解析队列（按文本去重）
            pending_ai.append((i, case_key, case))
            text_to_keys.setdefault(case.test_steps, []).append(case_key)

        # ---- 第二遍：对剩余用例并发调 AI（限流 + 去重） ----
        # 仅对去重后的唯一文本发起 AI 调用；相同文本的结果复用。
        unique_texts = list(text_to_keys.keys())
        sem = asyncio.Semaphore(5)  # 限制 5 并发，避免 API 限流

        async def _parse_one(text: str, context: str) -> Optional[dict]:
            async with sem:
                return await service.parse_steps(step_text=text, context=context)

        # 执行已启动 → 在发起 AI 前再检查一次
        if session.is_running and unique_texts:
            await session.ws_manager.broadcast({
                "type": "ai_parse_complete",
                "success": success,
                "failed": failed,
                "total": total,
                "message": f"步骤解析中断（执行已启动）：规则 {rule_hit}，AI {success - rule_hit}/{len(unique_texts)}",
            })
            return

        if unique_texts:
            # 为每个唯一文本取一个代表性 context（用第一条对应用例的 description）
            tasks = []
            for text in unique_texts:
                rep_key = text_to_keys[text][0]
                rep_case = next(c for _, _, c in pending_ai if (c.case_key or f"{c.source_sheet}:{c.row_number}:{c.case_id}") == rep_key)
                tasks.append(_parse_one(text, rep_case.description))
            ai_results = await asyncio.gather(*tasks, return_exceptions=True)

            for text, res in zip(unique_texts, ai_results):
                keys = text_to_keys[text]
                if isinstance(res, Exception) or not res or "_error" in res:
                    failed += len(keys)
                    continue
                parsed = res.get("parsed_steps", [])
                ai_recognized = res.get("ai_recognized", 0)
                for ck in keys:
                    session.ai_parsed_steps[ck] = parsed
                    success += 1
                    await session.ws_manager.broadcast({
                        "type": "ai_parse_case_done",
                        "case_key": ck,
                        "ai_recognized": ai_recognized,
                    })

            # 进度：规则命中的 + AI 已处理
            done = rule_hit + sum(1 for r in ai_results if not isinstance(r, Exception) and r and "_error" not in r)
            await session.ws_manager.broadcast({
                "type": "ai_parse_progress",
                "current": total,
                "total": total,
                "message": f"已解析 {done}/{total}（规则 {rule_hit}）",
            })

        await session.ws_manager.broadcast({
            "type": "ai_parse_complete",
            "success": success,
            "failed": failed,
            "total": total,
            "message": f"步骤解析完成：规则命中 {rule_hit}，AI {success - rule_hit}，失败 {failed}",
        })
    except Exception:
        # 异步任务失败不影响主流程
        pass


@router.get("/cases")
async def get_cases(request: Request, sheet: str = None):
    """获取用例列表"""
    session = request.state.session
    cases = session.test_cases
    if sheet:
        cases = [c for c in cases if c.get("source_sheet") == sheet]
    return cases


@router.get("/buglist")
async def get_bug_list(request: Request):
    """获取上传 Excel 中 BugList统计 页的内容（与工作簿保持同步）"""
    session = request.state.session
    return {
        "bug_sheet": session.bug_sheet,
        "bug_list": session.bug_list,
    }


@router.post("/cases/preview-commands")
async def preview_case_commands(request: Request, payload: Optional[CommandPreviewRequest] = None):
    """预览用例将要下发到远端的命令（不执行、不连接 SSH）。

    - 传 case_keys：预览指定用例
    - 不传：预览当前所有已选用例
    """
    session = request.state.session
    if not session.test_cases:
        raise HTTPException(status_code=400, detail="请先上传用例文件")

    from dataclasses import fields
    from app.core.executor_adapter import ExecutorAdapter

    requested = [k for k in (payload.case_keys if payload else []) if k]
    requested_set = set(requested)
    targets = []
    for c in session.test_cases:
        case_key = c.get("case_key") or (
            f"{c.get('source_sheet', '')}:{c.get('row_number', '')}:{c.get('case_id', '')}"
        )
        if requested_set:
            if case_key in requested_set or c.get("case_id") in requested_set:
                targets.append(c)
        elif c.get("selected"):
            targets.append(c)

    if not targets:
        detail = "未找到要预览的用例" if requested_set else "请先选择要执行的用例"
        raise HTTPException(status_code=400, detail=detail)

    valid_fields = {f.name for f in fields(TestCase)}
    # 预览不需要 SSH 连接；仅借用工作区配置做路径覆盖展示
    previewer = ExecutorAdapter(None, None, workspace=session.workspace)
    ai_parsed = getattr(session, "ai_parsed_steps", {}) or {}

    results = []
    for c in targets:
        case = TestCase(**{k: v for k, v in c.items() if k in valid_fields})
        try:
            results.append(previewer.preview_commands(case, ai_parsed))
        except Exception as exc:
            results.append({
                "case_id": c.get("case_id", ""),
                "case_key": c.get("case_key", ""),
                "description": c.get("description", ""),
                "error": f"解析失败: {exc}",
                "steps": [],
                "prerequisites": [],
                "notes": [],
            })
    return {"cases": results}


@router.get("/logs/content")
async def get_log_content(request: Request, path: str = "", run_id: str = "", case_key: str = ""):
    """读取单条用例的实际执行日志。

    优先使用显式传入的 path；否则按 case_key 从当前会话或历史记录中查找。
    仅允许读取 logs/ 目录下的文件。
    """
    session = request.state.session
    log_path = (path or "").strip()

    if not log_path and case_key:
        for c in session.test_cases:
            if c.get("case_key") == case_key or c.get("case_id") == case_key:
                log_path = (c.get("log_file") or "").strip()
                break
        if not log_path and run_id:
            from app.core.history_store import get_history_store
            for row in get_history_store().get_run_results(run_id):
                if row.get("case_key") == case_key or row.get("case_id") == case_key:
                    log_path = (row.get("log_file") or "").strip()
                    break

    if not log_path:
        raise HTTPException(status_code=404, detail="该用例暂无可查看的执行日志")

    logs_root = os.path.abspath("logs")
    resolved = os.path.abspath(log_path)
    if resolved != logs_root and not resolved.startswith(logs_root + os.sep):
        raise HTTPException(status_code=400, detail="非法日志路径")
    if not os.path.isfile(resolved):
        raise HTTPException(status_code=404, detail="日志文件不存在（可能已被清理）")

    with open(resolved, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    return {"path": log_path, "content": content}


def _resolve_log_file(session, path: str = "", run_id: str = "", case_key: str = "") -> str:
    """按 path / 当前会话 case_key / 历史 run_id 定位用例日志文件。"""
    log_path = (path or "").strip()
    if log_path:
        return log_path
    if not case_key:
        return ""
    for c in session.test_cases:
        if c.get("case_key") == case_key or c.get("case_id") == case_key:
            log_path = (c.get("log_file") or "").strip()
            break
    if not log_path and run_id:
        from app.core.history_store import get_history_store
        for row in get_history_store().get_run_results(run_id):
            if row.get("case_key") == case_key or row.get("case_id") == case_key:
                log_path = (row.get("log_file") or "").strip()
                break
    return log_path


def _safe_log_path(path: str) -> str:
    """只允许访问 logs/ 目录下的文件，返回绝对路径。"""
    logs_root = os.path.abspath("logs")
    resolved = os.path.abspath(path)
    if resolved != logs_root and not resolved.startswith(logs_root + os.sep):
        raise HTTPException(status_code=400, detail="非法日志路径")
    return resolved


@router.get("/logs/terminals/live")
async def get_live_terminal_logs(request: Request):
    """读取当前执行任务的多终端实时日志快照。

    页面中途打开、WebSocket 断线重连后，用该接口补齐已产生的板端输出。
    """
    session = request.state.session
    executor = session.executor
    if executor is None or not hasattr(executor, "live_terminal_snapshot"):
        return {"running": False, "case": {}, "case_id": "", "case_key": "",
                "log_file": "", "terminals": []}
    return executor.live_terminal_snapshot()


@router.get("/logs/terminals")
async def get_terminal_logs(request: Request, path: str = "", run_id: str = "",
                            case_key: str = ""):
    """读取某个已执行用例的多终端板端日志（执行期间按终端分别落盘）。

    返回 ``terminals: [{label, content}]``；终端级日志由统一的
    ``<基名>.terminals.json`` / ``<基名>.<终端>.term.log`` 存储提供。
    没有终端级日志时，尝试从备注中的终端分段解析（日志草稿恢复的用例），
    仍为空则返回空列表，由前端回退到聚合日志。
    """
    from app.core.remarks import extract_log_section
    from app.core.terminal_log import parse_terminal_log, read_terminal_logs

    session = request.state.session
    log_path = _resolve_log_file(session, path, run_id, case_key)
    if not log_path:
        raise HTTPException(status_code=404, detail="该用例暂无可查看的板端日志")

    resolved = _safe_log_path(log_path)
    if not os.path.isfile(resolved):
        raise HTTPException(status_code=404, detail="日志文件不存在（可能已被清理）")

    terminals: List[dict] = [
        {"label": label, "content": content}
        for label, content in read_terminal_logs(resolved, safe_root="logs")
    ]
    case_id = case_key
    if not case_id:
        for c in session.test_cases:
            if (c.get("log_file") or "").strip() == log_path:
                case_id = c.get("case_id", "")
                break

    matched_case = None
    for c in session.test_cases:
        if (
            (case_id and c.get("case_id") == case_id)
            or (c.get("log_file") or "").strip() == log_path
        ):
            matched_case = c
            break

    # 日志草稿恢复的用例没有终端级文件：备注中的日志已按终端分段存储，
    # 这里直接拆回各终端，保证日志弹窗仍按终端展示。
    if not terminals and matched_case is not None:
        remark_log = extract_log_section(str(matched_case.get("remarks") or ""))
        terminals = [
            {"label": label, "content": content}
            for label, content in parse_terminal_log(remark_log)
        ]

    return {
        "case_id": case_id,
        "case_key": case_key,
        "log_file": log_path,
        "terminals": terminals,
        "message": "" if terminals else "该用例没有按终端保存的板端日志",
    }


@router.get("/cases/remark")
async def get_case_remark(request: Request, path: str = "", run_id: str = "", case_key: str = ""):
    """读取单条用例的备注（AI 判定 + 执行日志），格式与下载结果备注列一致。

    - 当前会话：按 case_key（或 case_id）从 session.test_cases 构建
    - 历史记录：按 run_id + case_key 读取已保存的备注
    - 仅传 path：直接读取该日志文件作为备注内容
    """
    from app.core.remarks import build_remark_from_case, read_case_log

    session = request.state.session
    content = ""

    if case_key:
        # 历史记录优先：避免同一 case_key 被当前会话的用例覆盖
        if run_id:
            from app.core.history_store import get_history_store
            for row in get_history_store().get_run_results(run_id):
                if row.get("case_key") == case_key or row.get("case_id") == case_key:
                    content = (row.get("remarks") or "").strip()
                    if not content:
                        # 兼容旧记录：用判定依据 + 日志拼出备注
                        parts = []
                        reason = (row.get("match_reason") or "").strip()
                        log_content = read_case_log(row.get("log_file") or "")
                        if reason:
                            parts.append(reason)
                        if log_content.strip():
                            if parts:
                                parts.append("--- 执行日志 ---")
                            parts.append(log_content)
                        content = "\n".join(parts)
                    break

        if not content:
            for c in session.test_cases:
                if c.get("case_key") == case_key or c.get("case_id") == case_key:
                    content = build_remark_from_case(c)
                    break

    if not content and path:
        logs_root = os.path.abspath("logs")
        resolved = os.path.abspath(path)
        if resolved == logs_root or resolved.startswith(logs_root + os.sep):
            content = read_log_content(resolved)

    return {"content": content}


@router.get("/cases/images")
async def list_case_images(request: Request, case_id: str = Query("", description="用例 ID")):
    """列出该用例从板端下载到本机的 PNG 图片（供实际结果栏查看 YUV 出图）。"""
    session = request.state.session
    case_id = (case_id or "").strip()
    if not case_id:
        raise HTTPException(status_code=400, detail="请提供 case_id")

    local_dir = _case_image_dir(session.workspace, case_id)
    if not local_dir:
        return {
            "case_id": case_id,
            "images": [],
            "message": "未配置图片下载路径，无法查看生成的图片",
        }
    if not os.path.isdir(local_dir):
        return {
            "case_id": case_id,
            "images": [],
            "message": "未找到该用例的图片目录（可能尚未执行或已被清理）",
        }

    images = []
    entries = sorted(os.listdir(local_dir))
    # 同名 .yuv 视为该 PNG 的源文件（大小写不敏感），便于前端标注来源
    yuv_by_stem = {
        os.path.splitext(name)[0].lower(): name
        for name in entries
        if name.lower().endswith(".yuv") and os.path.isfile(os.path.join(local_dir, name))
    }
    for name in entries:
        path = os.path.join(local_dir, name)
        if name.lower().endswith(".png") and os.path.isfile(path):
            source_name = yuv_by_stem.get(os.path.splitext(name)[0].lower(), "")
            images.append({
                "name": name,
                "size": os.path.getsize(path),
                "source_name": source_name,
            })

    return {
        "case_id": case_id,
        "dir": local_dir,
        "images": images,
        "message": "" if images else "该用例目录下未找到 PNG 图片",
    }


@router.post("/cases/images/availability")
async def case_images_availability(request: Request, case_ids: List[str]):
    """批量查询这些用例在本机是否已生成 PNG 图片（只查目录，不读取图片内容）。

    前端据此决定是否展示「查看 YUV 出图」入口：只要用例目录下存在 PNG 即可，
    与用例 PASS/FAIL 状态无关。
    """
    session = request.state.session
    available: dict = {}
    for raw in case_ids or []:
        case_id = (raw or "").strip()
        if not case_id:
            continue
        try:
            local_dir = _case_image_dir(session.workspace, case_id)
        except HTTPException:
            available[case_id] = False
            continue
        if not local_dir or not os.path.isdir(local_dir):
            available[case_id] = False
            continue
        try:
            available[case_id] = any(
                name.lower().endswith(".png") and os.path.isfile(os.path.join(local_dir, name))
                for name in os.listdir(local_dir)
            )
        except OSError:
            available[case_id] = False
    return {"cases": available}


@router.get("/cases/images/{case_id}/{filename}")
async def get_case_image(request: Request, case_id: str, filename: str):
    """读取单张已下载到本机的用例图片（仅允许 PNG）。"""
    session = request.state.session
    if not filename.lower().endswith(".png"):
        raise HTTPException(status_code=400, detail="仅支持查看 PNG 图片")

    local_dir = _case_image_dir(session.workspace, case_id)
    if not local_dir:
        raise HTTPException(status_code=404, detail="未配置图片下载路径")
    local_dir_abs = os.path.abspath(local_dir)
    resolved = os.path.abspath(os.path.join(local_dir_abs, filename))
    if not resolved.startswith(local_dir_abs + os.sep):
        raise HTTPException(status_code=400, detail="非法图片路径")
    if not os.path.isfile(resolved):
        raise HTTPException(status_code=404, detail="图片不存在（可能已被清理）")

    return FileResponse(resolved, media_type="image/png", filename=filename)


def _case_image_dir(workspace, case_id: str) -> str:
    """返回 ``<image_download_path>/<case_id>`` 的绝对路径；未配置时返回空串。"""
    base = (getattr(workspace, "image_download_path", "") or "").strip()
    if not base:
        return ""
    case_id = (case_id or "").strip()
    if not case_id or case_id in (".", "..") or "/" in case_id or "\\" in case_id:
        raise HTTPException(status_code=400, detail="非法的用例 ID")
    return os.path.join(os.path.abspath(os.path.expanduser(base)), case_id)


@router.post("/cases/select")
async def select_cases(request: Request, case_ids: List[str], selected: bool = True):
    """批量选择/取消选择用例"""
    session = request.state.session
    for c in session.test_cases:
        if c.get("case_id") in case_ids:
            c["selected"] = selected
    return {"message": "更新成功"}


@router.post("/cases/update")
async def update_case(request: Request, payload: CaseUpdateRequest):
    """更新单条用例的测试步骤 / 预期结果（仅在内存中更新，下载/执行时写入结果文件）。"""
    session = request.state.session
    if session.is_running:
        raise HTTPException(status_code=400, detail="执行进行中，暂不能编辑测试步骤或预期结果")

    if payload.test_steps is None and payload.expected_result is None:
        raise HTTPException(status_code=400, detail="缺少要更新的字段")

    key = (payload.case_key or "").strip()
    cid = (payload.case_id or "").strip()
    if not key and not cid:
        raise HTTPException(status_code=400, detail="缺少 case_key 或 case_id")

    matched_case = None
    matched_key = ""
    for c in session.test_cases:
        case_key = c.get("case_key") or (
            f"{c.get('source_sheet', '')}:{c.get('row_number', 0)}:{c.get('case_id', '')}"
        )
        matched = (
            (key and case_key == key)
            or (not key and cid and c.get("case_id") == cid)
        )
        if matched:
            matched_case = c
            matched_key = case_key
            break

    if not matched_case:
        raise HTTPException(status_code=404, detail="未找到对应用例")

    updated_fields = []
    if payload.test_steps is not None:
        matched_case["test_steps"] = payload.test_steps
        updated_fields.append("测试步骤")
        # 步骤已变化，清除旧的解析缓存，避免执行时仍发送旧命令
        parsed_steps = getattr(session, "ai_parsed_steps", None)
        if isinstance(parsed_steps, dict):
            parsed_steps.pop(matched_key, None)
    if payload.expected_result is not None:
        matched_case["expected_result"] = payload.expected_result
        # 预期结果变化后重新提取关键字，保证执行判定使用最新内容
        from app.core.excel_handler import ExcelHandler
        matched_case["expected_keywords"] = ExcelHandler._parse_expected_keywords(
            payload.expected_result
        )
        updated_fields.append("预期结果")

    return {
        "message": f"{'、'.join(updated_fields)}已更新",
        "case_key": matched_key,
        "case": matched_case,
    }


@router.post("/cases/restore-logs")
async def restore_case_logs(request: Request, payload: RestoreCaseLogsRequest):
    """把日志草稿中的执行日志文本恢复到当前会话用例。

    下载结果时备注列可能只剩日志图片，文本由前端草稿箱保存。重新上传用例文件后
    调用本接口把日志写回会话用例，之后下载结果（文字模式）仍可保留日志文本，
    下载图片模式也会用恢复的日志重新渲染。
    """
    session = request.state.session
    if session.is_running:
        raise HTTPException(status_code=400, detail="执行进行中，暂不能恢复执行日志")
    if not session.test_cases:
        raise HTTPException(status_code=400, detail="请先上传测试用例文件")
    if not payload.cases:
        raise HTTPException(status_code=400, detail="草稿中没有可恢复的日志")

    from app.core.remarks import strip_log_section
    from app.core.terminal_log import format_terminal_log

    marker = "--- 执行日志 ---"
    applied = 0
    missing: List[str] = []

    for item in payload.cases:
        key = (item.case_key or "").strip()
        cid = (item.case_id or "").strip()
        # 统一按「板端日志系统」的终端分段格式存储备注日志：
        # 草稿提供 terminals 时重新拼成 ``===== 终端 =====`` 分段，
        # 旧草稿只有 log_text 时原样兼容。
        terminal_text = format_terminal_log(
            [(t.label, t.content) for t in item.terminals]
        )
        log_text = terminal_text or (
            (item.log_text or "").replace("\r\n", "\n").replace("\r", "\n").strip("\n")
        )
        # 限制单条日志长度，避免异常数据占满内存
        if len(log_text) > 2_000_000:
            log_text = log_text[:2_000_000] + "\n... (日志过长已截断)"
        if not log_text and not (item.remarks or "").strip():
            continue

        matched_case = None
        for c in session.test_cases:
            case_key = c.get("case_key") or (
                f"{c.get('source_sheet', '')}:{c.get('row_number', 0)}:{c.get('case_id', '')}"
            )
            if (key and case_key == key) or (not key and cid and c.get("case_id") == cid):
                matched_case = c
                break
        if matched_case is None and cid:
            # case_key 不匹配（例如重新上传后行号变化）时，case_id 唯一才回退匹配
            candidates = [c for c in session.test_cases if c.get("case_id") == cid]
            if len(candidates) == 1:
                matched_case = candidates[0]

        if matched_case is None:
            missing.append(key or cid)
            continue

        existing = str(matched_case.get("remarks") or "")
        base = strip_log_section(existing).strip() if marker in existing else existing.strip()
        if log_text:
            matched_case["remarks"] = (
                (base + "\n" if base else "") + marker + "\n" + log_text
            )
        elif item.remarks.strip():
            matched_case["remarks"] = item.remarks.strip()

        if (item.status or "").strip():
            matched_case["status"] = item.status.strip()
        if item.actual_result:
            matched_case["actual_result"] = item.actual_result
        if item.judgment:
            matched_case["judgment"] = item.judgment
        if item.ai_evidence:
            matched_case["ai_evidence"] = list(item.ai_evidence)
        applied += 1

    if applied:
        print(f"[INFO] 日志草稿已恢复 {applied} 条用例执行日志")

    return {
        "message": f"已恢复 {applied} 条用例执行日志",
        "applied": applied,
        "missing": missing,
    }


@router.post("/ssh/config")
async def set_ssh_config(request: Request, config: SSHConfig):
    """设置 SSH 配置"""
    session = request.state.session
    session.ssh_config = config
    session.ssh_status = SSHStatus(
        connected=False,
        tested=False,
        mode=config.login_mode,
        message="SSH 配置已更新，请重新测试连接",
    )
    session.config_store.save("ssh_config", config)
    return {"message": "SSH 配置已保存"}


@router.get("/ssh/config")
async def get_ssh_config(request: Request):
    """获取 SSH 配置"""
    session = request.state.session
    return session.ssh_config


@router.get("/ssh/status")
async def get_ssh_status(request: Request):
    """获取 SSH 连接状态"""
    session = request.state.session
    return session.ssh_status


@router.post("/ssh/test")
async def test_ssh_connection(request: Request, config: Optional[SSHConfig] = None):
    """测试 SSH 连接"""
    session = request.state.session
    target_config = config or session.ssh_config

    if not target_config.host:
        raise HTTPException(status_code=400, detail="请先填写目标板端 SSH 主机")

    if target_config.login_mode == "jump":
        if not target_config.jump_host:
            raise HTTPException(status_code=400, detail="已选择跳板机模式，请填写跳板机主机")
        if not target_config.jump_username:
            raise HTTPException(status_code=400, detail="已选择跳板机模式，请填写跳板机用户名")

    ssh = SSHManager(target_config)
    success, message = ssh.test_connection()
    status = SSHStatus(
        connected=success,
        tested=True,
        mode=target_config.login_mode,
        message=message,
    )
    session.ssh_status = status

    if not success:
        raise HTTPException(status_code=400, detail=message)

    session.ssh_config = target_config
    return status


@router.post("/workspace/config")
async def set_workspace(request: Request, config: WorkspaceConfig):
    """设置工作区配置"""
    session = request.state.session
    session.workspace = config
    session.config_store.save("workspace", config)
    return {"message": "工作区配置已保存"}


@router.get("/execute/current")
async def get_current_execution(request: Request):
    """获取当前执行任务摘要"""
    session = request.state.session
    return session.current_task


@router.get("/workspace/config")
async def get_workspace(request: Request):
    """获取工作区配置"""
    session = request.state.session
    return session.workspace


@router.post("/execute/start")
async def start_execution(request: Request, payload: Optional[ExecuteRequest] = None):
    """启动测试执行（通过 WebSocket 推送结果）"""
    session = request.state.session

    if session.is_running:
        # 兼容历史异常遗留的“僵尸运行态”：后台任务已是终态（finished/failed/stopped）
        # 但 is_running 未复位时，自动清理后允许启动下一次执行。
        task_status = (session.current_task.status or "") if session.current_task else ""
        if task_status in ("finished", "failed", "stopped"):
            session.is_running = False
            session.executor = None
        else:
            raise HTTPException(status_code=400, detail="执行已在进行中")

    if not session.test_cases:
        raise HTTPException(status_code=400, detail="请先上传用例文件")

    cases = session.test_cases
    if payload and payload.case_ids:
        # case_ids 字段实际传的是 case_key（唯一标识），兼容旧的 case_id 传法
        selected_keys = set(payload.case_ids)
        for c in cases:
            c_key = c.get("case_key", "")
            c_id = c.get("case_id", "")
            c["selected"] = c_key in selected_keys or c_id in selected_keys

    selected_cases = [c for c in cases if c.get("selected", False)]
    if not selected_cases:
        raise HTTPException(status_code=400, detail="请至少选择一条要执行的测试用例")

    # 重置选中用例的状态为 NT，清除旧的执行结果（含备注与 AI 判定）
    for c in cases:
        if c.get("selected", False):
            c["status"] = "NT"
            c["actual_result"] = ""
            c["log_file"] = ""
            c["remarks"] = ""
            c["ai_judged"] = False
            c["ai_status"] = ""
            c["ai_confidence"] = 0.0
            c["ai_reason"] = ""
            c["ai_evidence"] = []

    current_task = ExecutionTask.new_task(len(selected_cases))
    session.current_task = current_task

    ssh_config = session.ssh_config
    if not ssh_config or not ssh_config.host:
        raise HTTPException(status_code=400, detail="请先配置 SSH 连接")

    if ssh_config.login_mode == "jump" and not ssh_config.jump_host:
        raise HTTPException(status_code=400, detail="当前为跳板机模式，请先配置跳板机信息")

    # 在后台启动执行
    import asyncio
    asyncio.create_task(_run_execution(session))
    return {
        "message": "执行已启动",
        "selected_count": len(selected_cases),
        "task_id": current_task.task_id,
    }


def _sync_cases_to_state(session, cases):
    """将执行后的 TestCase 对象同步回 session.test_cases。

    按 case_key 匹配更新 status 和 actual_result，确保下次启动或 GET /cases 时
    能看到最新执行结果。
    """
    from app.core.remarks import build_judgment_from_case, build_remark_from_case

    state_cases = session.test_cases
    # 构建 case_key → 已执行 case 的映射
    executed_map = {}
    for c in cases:
        key = c.case_key or f"{c.source_sheet}:{c.row_number}:{c.case_id}"
        executed_map[key] = c

    for sc in state_cases:
        key = sc.get("case_key", "")
        if key in executed_map:
            ec = executed_map[key]
            sc["status"] = ec.status or sc.get("status", "NT")
            if ec.actual_result:
                sc["actual_result"] = ec.actual_result
            if ec.log_file:
                sc["log_file"] = ec.log_file
            if ec.tester:
                sc["tester"] = ec.tester
            if ec.test_version:
                sc["test_version"] = ec.test_version
            if ec.test_date:
                sc["test_date"] = ec.test_date
            # 同步 AI 判定详情与备注内容，供 GET /cases 重新加载时直接带回
            sc["ai_judged"] = bool(getattr(ec, "ai_judged", False))
            sc["ai_status"] = getattr(ec, "ai_status", "") or ""
            sc["ai_confidence"] = getattr(ec, "ai_confidence", 0.0) or 0.0
            sc["ai_reason"] = getattr(ec, "ai_reason", "") or ""
            sc["ai_evidence"] = getattr(ec, "ai_evidence", []) or []
            sc["bug_description"] = getattr(ec, "bug_description", "") or ""
            sc["bug_severity"] = getattr(ec, "bug_severity", "") or ""
            sc["judgment"] = build_judgment_from_case(ec)
            sc["remarks"] = build_remark_from_case(ec)


async def _generate_ai_bug_descriptions(
    ai_service,
    cases: List[TestCase],
    timeout: float = 45,
    concurrency: int = 4,
) -> int:
    """为失败用例生成 BugList 描述与 Severity，返回成功生成的数量。

    单条失败不影响其它用例；AI 不可用或超时时由调用方回退到判定理由/默认等级。
    """
    if not ai_service or not getattr(ai_service, "enabled", False):
        return 0

    targets = [
        c for c in cases if (c.status or "").strip().lower() == "fail"
    ]
    if not targets:
        return 0

    semaphore = asyncio.Semaphore(max(1, concurrency))
    generated = 0

    async def _one(case: TestCase):
        nonlocal generated
        async with semaphore:
            try:
                result = await asyncio.wait_for(
                    ai_service.generate_bug_description(
                        case_id=case.case_id,
                        case_description=case.description,
                        expected_result=case.expected_result,
                        actual_result=case.actual_result,
                        test_steps=case.test_steps,
                        ai_reason=getattr(case, "ai_reason", "") or "",
                        evidence=getattr(case, "ai_evidence", None) or [],
                    ),
                    timeout=timeout,
                )
                if result and (result.get("description") or result.get("severity")):
                    if result.get("description"):
                        case.bug_description = result["description"]
                    if result.get("severity"):
                        case.bug_severity = result["severity"]
                    generated += 1
            except Exception:
                # 单条生成失败时使用原有的判定理由作为描述
                pass

    await asyncio.gather(*(_one(case) for case in targets))
    return generated


async def _run_execution(session):
    """后台执行测试（per-session 隔离）。

    停止语义：用户点停止只置标志，最终结束态（finished/stopped/failed）在此处统一判定与广播，
    避免中途多次广播 execution_stopped 与状态错乱。
    """
    session.is_running = True
    session._stop_requested = False
    current_task = session.current_task
    manager = session.ws_manager
    ssh = None
    executor = None
    cases = None  # 保持外层引用，用于异常时同步部分结果
    results = None
    _history_saved = False

    try:
        from app.core.executor_adapter import ExecutorAdapter
        from app.core.ssh_manager import SSHManager

        ssh_config = session.ssh_config
        workspace = session.workspace

        # 连接前检查是否已被停止
        if session._stop_requested:
            current_task.mark_stopped("执行已被用户停止")
            await manager.broadcast({"type": "execution_stopped", "message": "执行已被用户停止"})
            return

        # 连接 SSH（同步阻塞，放到线程池避免卡事件循环）
        ssh = SSHManager(ssh_config)
        import asyncio
        loop = asyncio.get_event_loop()
        connected = await loop.run_in_executor(None, ssh.connect)
        if not connected:
            current_task.mark_failed("SSH 连接失败，请检查 SSH 配置或目标设备状态")
            session.ssh_status = SSHStatus(
                connected=False,
                tested=True,
                mode=ssh_config.login_mode,
                message=ssh.last_error or "SSH 连接失败",
            )
            await manager.send_log(f"SSH 连接失败：{ssh.last_error}", "error")
            await manager.broadcast({
                "type": "execution_stopped",
                "message": f"SSH 连接失败：{ssh.last_error}",
            })
            return

        session.ssh_status = SSHStatus(
            connected=True,
            tested=True,
            mode=ssh_config.login_mode,
            message="执行前 SSH 登录成功",
        )
        current_task.mark_running()
        await manager.send_log("SSH 连接成功", "info")

        # 创建执行器（per-session log_dir）
        log_dir = f"logs/{session.session_id}"
        # 获取 AI 服务（如已启用）——安全降级：AI 不可用不影响执行
        ai_svc = None
        try:
            ai_svc = _get_ai_service(session)
        except Exception:
            pass
        executor = ExecutorAdapter(
            ssh, manager, workspace=workspace, log_dir=log_dir,
            ai_service=ai_svc,
            ai_parsed_steps=getattr(session, 'ai_parsed_steps', None),
        )
        session.executor = executor

        # 转换用例
        cases = [TestCase(**c) for c in session.test_cases]
        results = await executor.execute_all(
            cases,
            run_prerequisites=workspace.run_prerequisites,
        )

        # 失败用例的 Bug 描述交给 AI 生成；AI 未启用/失败时回退到判定理由
        failed_for_bug = [
            c for c in cases if (c.status or "").strip().lower() == "fail"
        ]
        if failed_for_bug:
            try:
                generated = await _generate_ai_bug_descriptions(ai_svc, cases)
                if generated:
                    await manager.send_log(
                        f"AI 已为 {generated}/{len(failed_for_bug)} 条失败用例生成 Bug 描述与 Severity",
                        "info",
                    )
                elif getattr(ai_svc, "enabled", False):
                    await manager.send_log(
                        "AI 未能生成 Bug 描述，将使用判定理由作为描述", "warning"
                    )
            except Exception as bug_desc_err:
                await manager.send_log(
                    f"AI 生成 Bug 描述失败（不影响执行结果）: {bug_desc_err}", "warning"
                )

        # 将执行结果同步回 session，确保下次执行/查询能看到最新结果
        _sync_cases_to_state(session, cases)

        # 保存结果
        if session.excel_path:
            from app.core.excel_handler import ExcelHandler
            from app.core.bug_list import sync_failed_cases_to_bug_list

            handler = ExcelHandler()
            handler.load(session.excel_path)

            # 失败用例自动登记到 BugList统计 页，并写回 Excel
            if failed_for_bug:
                try:
                    merged, added = sync_failed_cases_to_bug_list(
                        cases,
                        handler.bug_list,
                        tester=getattr(workspace, "tester_name", "") or "",
                        version=getattr(workspace, "test_version", "") or "",
                    )
                    handler.bug_list = merged
                    handler.save_bug_list()
                    session.bug_list = handler.bug_list
                    session.bug_sheet = handler.bug_sheet_name
                    await manager.send_log(
                        f"失败用例已登记到 BugList：新增 {added} 条，当前共 {len(merged)} 条",
                        "info",
                    )
                except Exception as bug_err:
                    await manager.send_log(
                        f"自动登记 BugList 失败（不影响执行结果）: {bug_err}", "warning"
                    )

            handler.save_results(cases, session.excel_path)

        current_task.completed_count = len(results)

        # ---- 自动保存执行记录到 SQLite ----
        try:
            _save_run_to_history(session, current_task, cases, results)
            _history_saved = True
            await manager.send_log("执行记录已自动保存", "info")
        except Exception as history_err:
            await manager.send_log(f"保存执行记录失败（不影响执行结果）: {history_err}", "warning")

        # 判定结束态：被停止则 mark_stopped，否则 mark_finished
        if executor._stop or session._stop_requested:
            current_task.mark_stopped("执行已被用户停止")
            await manager.send_log("执行已被用户停止", "warning")
            await manager.broadcast({"type": "execution_stopped", "message": "执行已被用户停止"})
        else:
            current_task.mark_finished("执行完成", session.excel_path)
            await manager.send_execution_finished([r.model_dump() for r in results])

    except Exception as e:
        current_task.mark_failed(f"执行异常: {e}")
        # 异常时也尝试保存部分执行记录
        if not _history_saved and cases:
            try:
                _save_run_to_history(session, current_task, cases, results or [])
                _history_saved = True
            except Exception:
                pass
        await manager.send_log(f"执行异常: {e}", "error")
        await manager.broadcast({
            "type": "execution_stopped",
            "message": f"执行异常: {e}",
        })
    finally:
        # 先复位运行态，再做结果同步：同步中的异常绝不能让 is_running 卡在 True，
        # 否则用户结束一次测试后无法再启动下一次（提示"执行已在进行中"）。
        session.is_running = False
        session._stop_requested = False
        session.executor = None
        # 无论正常结束、用户停止、还是异常退出，都将已执行的结果同步回 state
        if cases:
            try:
                _sync_cases_to_state(session, cases)
            except Exception as sync_err:
                print(f"[WARN] 同步执行结果到会话失败: {sync_err}")
        if ssh:
            try:
                ssh.disconnect()
            except Exception:
                pass


_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _resolve_result_excel(session) -> str:
    """定位当前会话的结果 Excel。

    后端重启后 session 内存状态会丢失（excel_path 为空），
    此时回退到该会话上传目录中最近修改的 xlsx，保证仍可下载。
    返回绝对路径或空字符串。
    """
    path = session.excel_path or ""
    if path:
        abs_path = path if os.path.isabs(path) else os.path.join(_BACKEND_ROOT, path)
        if os.path.isfile(abs_path):
            return abs_path

    session_dir = os.path.join(_BACKEND_ROOT, "uploads", session.session_id)
    if not os.path.isdir(session_dir):
        return ""

    candidates = [
        os.path.join(session_dir, name)
        for name in os.listdir(session_dir)
        if name.lower().endswith(".xlsx") and not name.startswith("~$")
    ]
    if not candidates:
        return ""
    return max(candidates, key=os.path.getmtime)


def _apply_session_case_edits(handler, session) -> int:
    """把会话中在线编辑的测试步骤 / 预期结果与恢复的日志覆盖到已加载的工作簿。

    下载结果时调用：下载副本会照常保存，因此无需在编辑接口里同步写入
    整个 Excel（大文件加载+保存可能耗时数秒）。
    """
    from app.core.remarks import extract_log_section, strip_log_section

    marker = "--- 执行日志 ---"
    overrides = {}
    for sc in getattr(session, "test_cases", []) or []:
        if not isinstance(sc, dict):
            continue
        key = sc.get("case_key") or (
            f"{sc.get('source_sheet', '')}:"
            f"{sc.get('row_number', 0)}:{sc.get('case_id', '')}"
        )
        overrides[key] = {
            "test_steps": sc.get("test_steps") or "",
            "expected_result": sc.get("expected_result") or "",
            "remarks": sc.get("remarks") or "",
        }

    applied = 0
    for tc in getattr(handler, "test_cases", []) or []:
        key = tc.case_key or (
            f"{tc.source_sheet}:{tc.row_number}:{tc.case_id}"
        )
        edit = overrides.get(key)
        if not edit:
            continue
        changed = False
        steps = edit["test_steps"]
        if (
            (tc.test_steps or "") != steps
            and handler.update_test_steps(key, steps, save=False)
        ):
            changed = True
        expected = edit["expected_result"]
        if (
            (tc.expected_result or "") != expected
            and handler.update_expected_result(key, expected, save=False)
        ):
            changed = True
        # 草稿箱恢复的日志 / 执行结果：写回备注，供下载时重新渲染或保留文字
        log_text = extract_log_section(edit.get("remarks") or "").strip()
        if log_text:
            existing = tc.remarks or ""
            base = strip_log_section(existing).strip() if marker in existing else existing.strip()
            target = (base + "\n" if base else "") + marker + "\n" + log_text
            if existing != target and handler.update_remarks(key, target, save=False):
                changed = True
        if changed:
            applied += 1
    if applied:
        print(f"[INFO] 下载结果已应用 {applied} 条在线编辑的测试步骤 / 预期结果 / 恢复日志")
    return applied


def _build_statistics_data(session, handler) -> dict:
    """汇总执行数据，供 AI 填写「数据统计」页。"""
    from app.core.test_case import TestCase

    state_cases = session.test_cases or []
    if state_cases:
        cases = state_cases
    else:
        cases = [tc.model_dump() for tc in handler.test_cases]

    def _status_key(value) -> str:
        raw = str(value or "").strip().upper()
        if raw == "PASS":
            return "pass"
        if raw == "FAIL":
            return "fail"
        if raw == "BLOCK":
            return "block"
        if raw == "NA":
            return "na"
        if raw == "REVIEW":
            return "review"
        # 其它未知状态按未执行处理，避免虚增执行数
        return "nt"

    def _field(case, key, default=""):
        if isinstance(case, TestCase):
            return getattr(case, key, default) or default
        return case.get(key, default) or default

    def _rate(numerator, denominator) -> float:
        return round(numerator / denominator * 100, 1) if denominator else 0.0

    sheet_order: List[str] = []
    sheet_stats: dict = {}
    totals = {
        "total": 0, "pass": 0, "fail": 0, "block": 0,
        "na": 0, "nt": 0, "review": 0,
    }
    failures = []
    severity_dist: dict = {}

    for case in cases:
        sheet = _field(case, "source_sheet", "未分类") or "未分类"
        if sheet not in sheet_stats:
            sheet_stats[sheet] = {
                "sheet": sheet, "total": 0, "pass": 0, "fail": 0,
                "block": 0, "na": 0, "nt": 0, "review": 0,
            }
            sheet_order.append(sheet)
        row = sheet_stats[sheet]
        key = _status_key(_field(case, "status"))
        row["total"] += 1
        row[key] += 1
        totals["total"] += 1
        totals[key] += 1

        if key == "fail" and len(failures) < 20:
            reason = _field(case, "ai_reason")
            if not reason:
                actual = str(_field(case, "actual_result")).strip()
                lines = [ln.strip() for ln in actual.splitlines() if ln.strip()]
                if lines and lines[0] in ("Pass", "Fail", "NT", "Block", "NA", "Review"):
                    lines = lines[1:]
                reason = lines[0] if lines else _field(case, "remarks")
            failures.append({
                "case_id": _field(case, "case_id"),
                "sheet": sheet,
                "description": _field(case, "description"),
                "reason": reason,
                "severity": _field(case, "bug_severity") or "待评估",
            })
            severity = _field(case, "bug_severity") or "待评估"
            severity_dist[severity] = severity_dist.get(severity, 0) + 1

    sheet_rows = []
    for sheet in sheet_order:
        row = sheet_stats[sheet]
        executed = row["total"] - row["nt"] - row["na"]
        row.update({
            "executed": executed,
            "execute_rate": _rate(executed, row["total"]),
            "pass_rate": _rate(row["pass"], executed),
            "fail_rate": _rate(row["fail"], executed),
            "block_rate": _rate(row["block"], executed),
        })
        sheet_rows.append(row)

    executed = totals["total"] - totals["nt"] - totals["na"]
    totals.update({
        "executed": executed,
        "execute_rate": _rate(executed, totals["total"]),
        "pass_rate": _rate(totals["pass"], executed),
        "fail_rate": _rate(totals["fail"], executed),
        "block_rate": _rate(totals["block"], executed),
    })

    workspace = session.workspace
    task = session.current_task
    duration_seconds = 0.0
    if getattr(task, "started_at", None) and getattr(task, "ended_at", None):
        try:
            duration_seconds = (
                datetime.fromisoformat(task.ended_at)
                - datetime.fromisoformat(task.started_at)
            ).total_seconds()
        except Exception:
            duration_seconds = 0.0

    ssh_config = session.ssh_config
    environment = ""
    if getattr(ssh_config, "host", ""):
        environment = f"{ssh_config.host}:{ssh_config.port}"
        if getattr(ssh_config, "username", ""):
            environment = f"{ssh_config.username}@{environment}"

    test_date = ""
    if getattr(task, "ended_at", None):
        test_date = str(task.ended_at)[:10]
    if not test_date:
        for case in cases:
            test_date = str(_field(case, "test_date")).strip()[:10]
            if test_date:
                break
    if not test_date:
        test_date = datetime.now().strftime("%Y-%m-%d")

    workbook = os.path.splitext(
        os.path.basename(handler.file_path or session.excel_path or "")
    )[0]

    return {
        "workbook": workbook,
        "tester": getattr(workspace, "tester_name", "") or "",
        "version": getattr(workspace, "test_version", "") or "",
        "test_date": test_date,
        "environment": environment,
        "duration_seconds": duration_seconds,
        "sheets": sheet_order,
        "sheet_rows": sheet_rows,
        "failures": failures,
        "severity_dist": severity_dist,
        **totals,
    }


@router.get("/download/results")
async def download_results(
    request: Request,
    include_log: bool = Query(True, description="备注列是否包含实际执行日志"),
):
    """下载结果 Excel

    下载副本会由 AI 填写「数据统计」页的测试基本信息、质量/效率目标和测试总结；
    include_log=True 时按工作区配置的 ``log_remark_mode`` 输出备注：
    ``image`` 渲染为终端图片（分辨率/尺寸取自工作区配置），``text`` 保留日志文字；
    include_log=False 时备注列去掉「--- 执行日志 ---」及其后的日志内容；
    原结果文件不受影响。
    """
    session = request.state.session
    path = _resolve_result_excel(session)
    if not path:
        raise HTTPException(
            status_code=404,
            detail="当前会话没有可下载的结果文件，请重新上传用例并执行后再下载",
        )
    # 恢复成功后写回，后续请求不再重复查找
    session.excel_path = path

    filename = os.path.basename(path)

    # 生成下载副本：日志渲染为图片、用例截图嵌入「备注」列
    from app.core.excel_handler import ExcelHandler

    tmp_dir = tempfile.mkdtemp(prefix="results_export_")
    tmp_path = os.path.join(tmp_dir, filename)
    handler = ExcelHandler()
    try:
        handler.load(path)
        # 把当前会话中在线编辑的测试步骤 / 预期结果带入下载副本
        _apply_session_case_edits(handler, session)
        # 兼容旧结果文件：BUG 列不再保留 AI 证据行
        handler.strip_evidence_from_judgment()
        image_base = (getattr(session.workspace, "image_download_path", "") or "").strip()

        log_offsets: dict = {}
        workspace = session.workspace
        log_mode = (
            getattr(workspace, "log_remark_mode", "image") or "image"
        ).strip().lower()
        if log_mode not in ("image", "text"):
            log_mode = "image"

        def _workspace_int(name: str, default: int, low: int, high: int) -> int:
            try:
                value = int(getattr(workspace, name, default) or default)
            except (TypeError, ValueError):
                value = default
            return max(low, min(high, value))

        if include_log and log_mode == "image":
            # 先清掉上次嵌入的旧图片，再放日志图片与用例截图，避免叠加
            handler.clear_result_images()
            # 「BUG」列已不再写证据行，图片高亮所需的证据从会话状态取
            evidence_by_key = {}
            for sc in getattr(session, "test_cases", []) or []:
                if not isinstance(sc, dict):
                    continue
                evidence = sc.get("ai_evidence") or []
                if not evidence:
                    continue
                key = sc.get("case_key") or (
                    f"{sc.get('source_sheet', '')}:"
                    f"{sc.get('row_number', '')}:{sc.get('case_id', '')}"
                )
                evidence_by_key[key] = list(evidence)
            log_offsets = handler.embed_log_images(
                max_width=_workspace_int("log_image_display_width", 320, 100, 800),
                max_height=_workspace_int("log_image_max_height", 520, 120, 1200),
                render_width=_workspace_int("log_image_render_width", 400, 200, 1200),
                evidence_by_key=evidence_by_key,
            )
        elif include_log:
            # 文字版日志：移除旧日志图片，保留备注列中的日志文字
            handler.clear_result_images()
        else:
            handler.strip_log_from_remarks()
            handler.clear_result_images()

        if image_base:
            handler.embed_case_images(
                image_base,
                start_offsets=log_offsets,
                remove_existing=False,
            )

        # 下载时由 AI 填写「数据统计」页的测试基本信息/质量目标/测试总结。
        # 失败只影响这三栏，不影响结果文件下载。
        if handler.find_statistics_sheet_name():
            try:
                stats_data = _build_statistics_data(session, handler)
                if stats_data.get("executed"):
                    ai_svc = _get_ai_service(session)
                    if getattr(ai_svc, "enabled", False):
                        ai_result = await asyncio.wait_for(
                            ai_svc.generate_test_statistics(stats_data),
                            timeout=60,
                        )
                        if ai_result and not ai_result.get("_error"):
                            filled = handler.fill_statistics_summary(
                                basic_info=ai_result.get("basic_info", ""),
                                quality_goal=ai_result.get("quality_goal", ""),
                                summary=ai_result.get("summary", ""),
                            )
                            if filled:
                                print(
                                    "[INFO] 数据统计页已由 AI 填写: "
                                    + "、".join(filled)
                                )
                        elif ai_result:
                            print(
                                "[WARN] 数据统计页 AI 填写失败: "
                                + str(ai_result.get("_error"))
                            )
            except Exception as stats_err:
                print(f"[WARN] 数据统计页 AI 填写失败: {stats_err}")

        handler.save(tmp_path)
    except Exception as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        # 包含日志的下载回退为原始文件（仅缺少嵌图），避免解析异常导致无法下载
        if include_log:
            return FileResponse(path, filename=filename)
        raise HTTPException(status_code=500, detail=f"生成下载文件失败: {exc}")
    finally:
        handler.close()

    return FileResponse(
        tmp_path,
        filename=filename,
        background=BackgroundTask(shutil.rmtree, tmp_dir, True),
    )


# =========================================================================
# 执行历史自动保存
# =========================================================================


def _save_run_to_history(session, task, cases, results):
    """将执行记录保存到 SQLite 历史数据库。同步调用，失败不阻塞执行。"""
    from app.core.history_store import get_history_store

    store = get_history_store()
    workspace = session.workspace
    excel_filename = os.path.basename(session.excel_path) if session.excel_path else ""

    executed_cases = [c for c in cases if c.selected]
    total = len(executed_cases)
    pass_count = sum(1 for c in executed_cases if (c.status or "").upper() == "PASS")
    fail_count = sum(1 for c in executed_cases if (c.status or "").upper() == "FAIL")
    block_count = sum(1 for c in executed_cases if (c.status or "").upper() == "BLOCK")
    na_count = sum(1 for c in executed_cases if (c.status or "").upper() == "NA")
    nt_count = sum(1 for c in executed_cases if (c.status or "").upper() == "NT")
    review_count = sum(1 for c in executed_cases if (c.status or "").upper() == "REVIEW")
    pass_rate = round(pass_count / total * 100, 1) if total > 0 else 0

    sheets = list(dict.fromkeys(c.source_sheet for c in executed_cases if c.source_sheet))

    # 计算耗时
    duration = 0.0
    if task.started_at and task.ended_at:
        try:
            t_start = datetime.fromisoformat(task.started_at)
            t_end = datetime.fromisoformat(task.ended_at)
            duration = (t_end - t_start).total_seconds()
        except Exception:
            pass

    run_data = {
        "run_id": task.task_id,
        "session_id": session.session_id,
        "status": task.status or "finished",
        "started_at": task.started_at or datetime.now().isoformat(),
        "ended_at": task.ended_at,
        "duration_seconds": duration,
        "excel_filename": excel_filename,
        "excel_path": session.excel_path or "",
        "sheets_used": ",".join(sheets),
        "tester_name": getattr(workspace, "tester_name", "") if workspace else "",
        "test_version": getattr(workspace, "test_version", "") if workspace else "",
        "total_count": total,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "block_count": block_count,
        "na_count": na_count,
        "nt_count": nt_count,
        "review_count": review_count,
        "pass_rate": pass_rate,
    }

    from app.core.remarks import build_remark_from_case

    run_id = run_data["run_id"]
    result_map = {r.case_id: r for r in results} if results else {}
    case_results = []
    for c in executed_cases:
        r = result_map.get(c.case_id)
        case_results.append({
            "run_id": run_id,
            "case_id": c.case_id,
            "case_key": c.case_key or f"{c.source_sheet}:{c.row_number}:{c.case_id}",
            "source_sheet": c.source_sheet,
            "row_number": c.row_number,
            "description": c.description,
            "test_steps": c.test_steps,
            "expected_result": c.expected_result,
            "prerequisites": c.prerequisites,
            "priority": c.priority,
            "status": c.status or "NT",
            "actual_result": c.actual_result or "",
            "match_reason": r.match_reason if r else "",
            "remarks": build_remark_from_case(c),
            "log_file": r.log_file if r else "",
            "duration_seconds": r.duration if r else 0,
            "tester": c.tester or "",
            "test_version": c.test_version or "",
            "test_date": c.test_date or "",
        })

    store.save_run(run_data, case_results)


@router.post("/files/push")
async def push_file_to_board(request: Request, file: UploadFile = File(...), remote_path: str = ""):
    """上传本地文件并通过 SSH 推送到板端指定路径。"""
    session = request.state.session
    ssh_config = session.ssh_config

    if not ssh_config or not ssh_config.host:
        raise HTTPException(status_code=400, detail="请先配置 SSH 连接")
    if not remote_path:
        raise HTTPException(status_code=400, detail="请指定板端目标路径")

    safe_name = os.path.basename(file.filename or "upload_file")
    local_path = os.path.join("uploads", session.session_id, "push_" + safe_name)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    content = await file.read()
    with open(local_path, "wb") as f:
        f.write(content)

    try:
        result = await _scp_to_board(ssh_config, local_path, remote_path, safe_name)
    finally:
        try:
            os.remove(local_path)
        except Exception:
            pass
    return result


class PushLocalRequest(BaseModel):
    """从 PC 本地路径推送文件/目录到板端。"""
    local_path: str
    remote_path: str


class CopyToSoRequest(BaseModel):
    """推送完成后，在板端将文件复制到运行 so 路径。"""
    source_path: str
    so_path: str
    board_type: str = "linux"  # "linux" or "qnx"


@router.post("/files/push-local")
async def push_local_to_board(request: Request, payload: PushLocalRequest):
    """从 PC 本地路径（文件或目录）推送到板端指定路径。"""
    session = request.state.session
    ssh_config = session.ssh_config

    if not ssh_config or not ssh_config.host:
        raise HTTPException(status_code=400, detail="请先配置 SSH 连接")
    if not payload.local_path:
        raise HTTPException(status_code=400, detail="请指定本地路径")
    if not payload.remote_path:
        raise HTTPException(status_code=400, detail="请指定板端目标路径")
    if not os.path.exists(payload.local_path):
        raise HTTPException(status_code=400, detail=f"本地路径不存在: {payload.local_path}")

    return await _scp_to_board(
        ssh_config, payload.local_path, payload.remote_path,
        os.path.basename(payload.local_path),
        is_dir=os.path.isdir(payload.local_path),
    )


async def _scp_to_board(ssh_config, local_path: str, remote_path: str, filename: str, is_dir: bool = False):
    """SCP 推送文件或目录到板端。"""
    import asyncio
    import subprocess

    loop = asyncio.get_event_loop()

    # 确保板端目标目录存在
    from app.core.ssh_manager import SSHManager
    ssh = SSHManager(ssh_config)
    connected = await loop.run_in_executor(None, ssh.connect)
    if not connected:
        raise HTTPException(status_code=400, detail=f"SSH 连接失败: {ssh.last_error}")

    try:
        remote_dir = remote_path if remote_path.endswith("/") else os.path.dirname(remote_path)
        if remote_dir:
            await loop.run_in_executor(
                None, lambda: ssh.execute(f"mkdir -p {remote_dir}", timeout=10))
    finally:
        ssh.disconnect()

    target_path = remote_path
    if remote_path.endswith("/"):
        target_path = remote_path + filename

    remote_spec = f"{ssh_config.username}@{ssh_config.host}:{target_path}"
    try:
        # 自动适配直连/跳板机（跳板机模式通过 ProxyCommand 穿越）
        scp_cmd, env, cleanup = ssh.build_scp_command(
            local_path, remote_spec, recursive=is_dir)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        result = await loop.run_in_executor(None, lambda: subprocess.run(
            scp_cmd, capture_output=True, text=True,
            timeout=300, env=env, start_new_session=True,
        ))

        if result.returncode != 0:
            raise HTTPException(
                status_code=400,
                detail=f"SCP 推送失败: {result.stderr or result.stdout or f'exit={result.returncode}'}",
            )
    finally:
        try:
            cleanup()
        except Exception:
            pass

    kind = "目录" if is_dir else "文件"
    return {"message": f"{kind}已推送到板端: {target_path}", "remote_path": target_path}


@router.post("/files/copy-to-so")
async def copy_to_so_path(request: Request, payload: CopyToSoRequest):
    """在板端将推送的文件从中转目录复制到运行 so 路径。"""
    import asyncio
    session = request.state.session
    ssh_config = session.ssh_config

    if not ssh_config or not ssh_config.host:
        raise HTTPException(status_code=400, detail="请先配置 SSH 连接")
    if not payload.source_path or not payload.so_path:
        raise HTTPException(status_code=400, detail="请填写源路径和运行 so 路径")

    from app.core.ssh_manager import SSHManager
    ssh = SSHManager(ssh_config)
    loop = asyncio.get_event_loop()
    connected = await loop.run_in_executor(None, ssh.connect)
    if not connected:
        raise HTTPException(status_code=400, detail=f"SSH 连接失败: {ssh.last_error}")

    try:
        # 确保目标 so 路径存在
        source = payload.source_path.rstrip("/")
        so_path = payload.so_path.rstrip("/")

        if payload.board_type == "linux":
            import shlex
            password = getattr(ssh_config, 'target_password', '') or getattr(ssh_config, 'password', '')
            pwd_escaped = shlex.quote(password)
            mkdir_cmd = f"echo {pwd_escaped} | sudo -S mkdir -p {so_path}"
            cp_cmd = f"echo {pwd_escaped} | sudo -S cp -rf {source}/* {so_path}/ 2>/dev/null; echo {pwd_escaped} | sudo -S cp -rf {source}/*.so {so_path}/ 2>/dev/null"
        else:
            # QNX 无 sudo
            mkdir_cmd = f"mkdir -p {so_path}"
            cp_cmd = f"cp -rf {source}/* {so_path}/ 2>/dev/null; cp -rf {source}/*.so {so_path}/ 2>/dev/null"

        # 创建目标目录
        await loop.run_in_executor(None, lambda: ssh.execute(mkdir_cmd, timeout=10))

        # 复制文件
        exit_code, stdout, stderr = await loop.run_in_executor(
            None, lambda: ssh.execute(cp_cmd, timeout=30))

        if exit_code != 0 and "No such file" in (stderr or ""):
            raise HTTPException(status_code=400, detail=f"复制失败: {stderr}")

        # 验证复制结果
        ls_cmd = f"ls {so_path}/*.so 2>/dev/null | wc -l"
        _, count_out, _ = await loop.run_in_executor(None, lambda: ssh.execute(ls_cmd, timeout=5))
        file_count = count_out.strip()

        return {
            "message": f"已复制到运行路径 {so_path}/ ({file_count} 个 so 文件)",
            "board_type": payload.board_type,
        }
    finally:
        ssh.disconnect()


# =========================================================================
# AI 功能接口
# =========================================================================


class AnalyzeRequest(BaseModel):
    """AI 失败分析请求。"""
    case_id: str
    force: bool = False  # 跳过缓存，强制重新分析


class ReportRequest(BaseModel):
    """AI 报告生成请求。"""
    format: str = "markdown"  # markdown / text / json


def _get_ai_service(session):
    """获取 session 的 AIService 实例（延迟创建）。"""
    from app.ai.service import AIService

    if not hasattr(session, '_ai_service') or session._ai_service is None:
        ai_config = _global_config_store.load(
            "ai_config", AIConfig, AIConfig()
        )
        session._ai_service = AIService(ai_config.model_dump())
    return session._ai_service


def _get_cases_as_objects(session) -> list:
    """将 session.test_cases (list of dict) 转换为 TestCase 对象列表。"""
    return [TestCase(**c) for c in session.test_cases]


def _mask_api_key(key: str) -> str:
    """API Key 掩码，不向前端返回完整密钥。"""
    if key and len(key) > 8:
        return key[:4] + "****" + key[-4:]
    return "****" if key else ""


def _profile_summary(entry: AIProfileEntry) -> dict:
    """配置方案摘要（用于列表展示，隐藏完整 API Key）。"""
    return {
        "id": entry.id,
        "name": entry.name,
        "ai_enabled": entry.config.ai_enabled,
        "ai_protocol": entry.config.ai_protocol,
        "ai_model": entry.config.ai_model,
        "ai_base_url": entry.config.ai_base_url,
        "ai_api_key_masked": _mask_api_key(entry.config.ai_api_key),
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
    }


class AIProfileCreateRequest(BaseModel):
    """新建 AI 配置方案请求；config 为空时取当前已生效的 AI 配置。"""
    name: str
    config: Optional[AIConfig] = None


class AISystemPromptsUpdateRequest(BaseModel):
    """仅更新系统提示词，避免覆盖同一方案中其他 AI 配置。"""
    prompts: Dict[str, str] = Field(default_factory=dict)


@router.get("/ai/config")
async def get_ai_config(request: Request):
    """获取 AI 配置（全局共享，不跟 session 绑定）。"""
    config = _global_config_store.load(
        "ai_config", AIConfig, AIConfig()
    )
    # 不返回完整 API Key，只返回掩码
    data = config.model_dump()
    data["ai_api_key_masked"] = _mask_api_key(config.ai_api_key)
    data.pop("ai_api_key", None)
    return data


@router.get("/ai/prompts")
async def list_ai_prompts():
    """列出所有 AI 功能的系统提示词元数据及内置默认值。

    当前用户自定义值随 ``GET /ai/config`` 的 ``ai_system_prompts`` 返回。
    """
    from app.ai.prompts.registry import AI_PROMPT_FEATURES

    return {"prompts": [feature.to_dict() for feature in AI_PROMPT_FEATURES]}


@router.put("/ai/prompts")
async def set_ai_prompts(
    request: Request, payload: AISystemPromptsUpdateRequest
):
    """保存系统提示词配置。

    只更新 ``ai_system_prompts``，保留当前方案中的协议、模型、密钥等设置；
    提示词归属于当前激活的 AI 配置方案。
    """
    session = request.state.session
    if _ai_profile_store.get_active() is None:
        raise HTTPException(status_code=400, detail="请先新增一套配置方案后再编辑")

    old = _global_config_store.load("ai_config", AIConfig, AIConfig())
    # 通过 AIConfig 重新校验，自动清理空白提示词
    config = AIConfig(**{
        **old.model_dump(),
        "ai_system_prompts": payload.prompts,
    })
    _global_config_store.save("ai_config", config)
    _ai_profile_store.update_active(config)
    if hasattr(session, "_ai_service"):
        session._ai_service = None
    return {
        "message": "提示词配置已保存",
        "ai_system_prompts": config.ai_system_prompts,
    }


@router.post("/ai/config")
async def set_ai_config(request: Request, config: AIConfig):
    """保存 AI 配置（全局共享）。

    配置必须归属于某个方案：没有激活方案时拒绝保存，避免产生无法编辑的
    游离配置。
    """
    session = request.state.session
    if _ai_profile_store.get_active() is None:
        raise HTTPException(status_code=400, detail="请先新增一套配置方案后再编辑")
    # 如果前端发来空 key 但之前有 key，保留旧 key
    if not config.ai_api_key:
        old = _global_config_store.load(
            "ai_config", AIConfig, AIConfig()
        )
        if old.ai_api_key:
            config.ai_api_key = old.ai_api_key
    _global_config_store.save("ai_config", config)
    # 若当前选中了配置方案，同步更新该方案的快照
    _ai_profile_store.update_active(config)
    # 重置 AIService 使新配置生效
    if hasattr(session, '_ai_service'):
        session._ai_service = None
    return {"message": "AI 配置已保存"}


@router.get("/ai/profiles")
async def list_ai_profiles():
    """列出所有 AI 配置方案及当前激活方案。"""
    bundle = _ai_profile_store.load_bundle()
    return {
        "profiles": [_profile_summary(p) for p in bundle.profiles],
        "active_id": bundle.active_id,
    }


@router.post("/ai/profiles")
async def create_ai_profile(payload: AIProfileCreateRequest, request: Request):
    """把配置另存为一个新方案并设为激活方案。

    前端会传入未保存的表单配置，此时不会覆盖原激活方案的快照。
    空 API Key 沿用当前生效配置中的密钥（表单不回显完整密钥）。
    """
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="配置方案名称不能为空")
    config = payload.config or _global_config_store.load("ai_config", AIConfig, AIConfig())
    if not config.ai_api_key:
        old = _global_config_store.load("ai_config", AIConfig, AIConfig())
        if old.ai_api_key:
            config.ai_api_key = old.ai_api_key
    try:
        entry = _ai_profile_store.create(name, config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # 新方案即当前表单内容，同步设为生效配置
    _global_config_store.save("ai_config", config)
    session = request.state.session
    if hasattr(session, '_ai_service'):
        session._ai_service = None
    return {"message": f"配置方案「{entry.name}」已保存", "profile": _profile_summary(entry)}


@router.post("/ai/profiles/{profile_id}/activate")
async def activate_ai_profile(profile_id: str, request: Request):
    """切换到指定配置方案：把方案快照写回当前生效配置。"""
    try:
        entry = _ai_profile_store.activate(profile_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="配置方案不存在")
    _global_config_store.save("ai_config", entry.config)
    session = request.state.session
    if hasattr(session, '_ai_service'):
        session._ai_service = None
    return {"message": f"已切换到配置方案「{entry.name}」", "profile": _profile_summary(entry)}


@router.delete("/ai/profiles/{profile_id}")
async def delete_ai_profile(profile_id: str, request: Request):
    """删除指定配置方案。

    删除激活方案时自动激活剩余的第一个方案；没有剩余方案则当前生效配置
    保持不变，但前端将禁止继续编辑，直到新增方案。
    """
    try:
        switched, new_active = _ai_profile_store.delete(profile_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="配置方案不存在")

    if switched and new_active is not None:
        _global_config_store.save("ai_config", new_active.config)
        session = request.state.session
        if hasattr(session, '_ai_service'):
            session._ai_service = None

    return {
        "message": "配置方案已删除",
        "active_id": new_active.id if new_active else None,
    }


@router.get("/cleanup/config")
async def get_cleanup_config(request: Request):
    """获取上传文件清理配置（全局共享）。"""
    config = _global_config_store.load(
        "cleanup_config", CleanupConfig, CleanupConfig()
    )
    return config.model_dump()


@router.post("/cleanup/config")
async def set_cleanup_config(request: Request, config: CleanupConfig):
    """保存上传文件清理配置（全局共享）。"""
    if config.retention_days < 1:
        raise HTTPException(status_code=400, detail="保留天数不能小于 1")
    if config.check_interval_hours < 1:
        raise HTTPException(status_code=400, detail="检查间隔不能小于 1 小时")
    _global_config_store.save("cleanup_config", config)
    return {"message": "清理配置已保存"}


@router.post("/cleanup/run")
async def run_cleanup_now(request: Request):
    """立即执行一次上传文件清理。"""
    from app.core.file_cleanup import cleanup_old_uploads
    config = _global_config_store.load(
        "cleanup_config", CleanupConfig, CleanupConfig()
    )
    removed = cleanup_old_uploads(config.retention_days)
    return {"message": f"清理完成，删除了 {removed} 个过期文件/目录", "removed": removed}


@router.get("/cleanup/stats")
async def get_cleanup_stats(request: Request):
    """获取上传文件存储统计信息。"""
    from app.core.file_cleanup import get_uploads_stats
    stats = get_uploads_stats()
    config = _global_config_store.load(
        "cleanup_config", CleanupConfig, CleanupConfig()
    )
    return {**stats, "config": config.model_dump()}


class AIModelsRequest(BaseModel):
    """查询模型列表请求；字段为空时回退到当前生效的 AI 配置。"""
    ai_protocol: Optional[str] = None
    ai_base_url: Optional[str] = None
    ai_api_key: Optional[str] = None


@router.post("/ai/models")
async def list_ai_models(payload: AIModelsRequest):
    """按接入地址查询可用模型列表。

    查询失败（地址不可达、端点不支持、鉴权失败）返回空列表，
    前端保留手动输入，不视为错误。
    """
    from app.ai.model_listing import list_models

    saved = _global_config_store.load("ai_config", AIConfig, AIConfig())
    protocol = payload.ai_protocol or saved.ai_protocol
    base_url = payload.ai_base_url if payload.ai_base_url is not None else saved.ai_base_url
    api_key = payload.ai_api_key or saved.ai_api_key
    models = await list_models(protocol, base_url, api_key)
    return {"models": models}


@router.post("/ai/test")
async def test_ai_connection(request: Request):
    """测试 AI Provider 连通性。"""
    session = request.state.session
    service = _get_ai_service(session)
    result = await service.test_connection()
    return result


@router.post("/ai/analyze")
async def analyze_failure(request: Request, payload: AnalyzeRequest):
    """AI 失败分析：分析指定用例的失败根因。"""
    session = request.state.session
    service = _get_ai_service(session)

    if not service.enabled:
        raise HTTPException(status_code=400, detail="AI 功能未启用，请先配置 AI 设置")

    # 查找用例
    case = None
    for c in _get_cases_as_objects(session):
        case_key = c.case_key or f"{c.source_sheet}:{c.row_number}:{c.case_id}"
        if case_key == payload.case_id or c.case_id == payload.case_id:
            case = c
            break

    if case is None:
        raise HTTPException(status_code=404, detail=f"用例 {payload.case_id} 不存在")

    if case.status.upper() not in ("FAIL", "REVIEW"):
        raise HTTPException(
            status_code=400,
            detail=f"用例 {case.case_id} 状态为 {case.status}，只有 Fail/Review 可分析"
        )

    result = await service.analyze_failure(
        case_id=case.case_id,
        description=case.description,
        test_steps=case.test_steps,
        expected_result=case.expected_result,
        actual_output=case.actual_result,
        match_reason=case.remarks,
        error_msg="",
        force_refresh=payload.force,
    )

    if not result or result.get("_error"):
        detail = (result or {}).get("_error") or "AI 分析失败，请检查 AI 配置和网络连接"
        raise HTTPException(status_code=502, detail=detail)

    return {"analysis": result}


@router.post("/ai/analyze/stream")
async def analyze_failure_stream(request: Request, payload: AnalyzeRequest):
    """AI 失败分析（SSE 流式输出）。

    事件格式（每行一个 JSON）:
    - {"type": "delta", "text": "..."}
    - {"type": "done", "analysis": {...}}
    - {"type": "error", "message": "..."}
    """
    session = request.state.session
    service = _get_ai_service(session)

    if not service.enabled:
        raise HTTPException(status_code=400, detail="AI 功能未启用，请先配置 AI 设置")

    # 查找用例
    case = None
    for c in _get_cases_as_objects(session):
        case_key = c.case_key or f"{c.source_sheet}:{c.row_number}:{c.case_id}"
        if case_key == payload.case_id or c.case_id == payload.case_id:
            case = c
            break

    if case is None:
        raise HTTPException(status_code=404, detail=f"用例 {payload.case_id} 不存在")

    if case.status.upper() not in ("FAIL", "REVIEW"):
        raise HTTPException(
            status_code=400,
            detail=f"用例 {case.case_id} 状态为 {case.status}，只有 Fail/Review 可分析"
        )

    async def event_stream():
        try:
            async for event in service.stream_analyze_failure(
                case_id=case.case_id,
                description=case.description,
                test_steps=case.test_steps,
                expected_result=case.expected_result,
                actual_output=case.actual_result,
                match_reason=case.remarks,
                error_msg="",
                force_refresh=payload.force,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            raise
        except Exception as e:
            message = f"流式分析异常: {type(e).__name__}: {e}"
            yield f"data: {json.dumps({'type': 'error', 'message': message}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/ai/analyze-all")
async def analyze_all_failures(request: Request):
    """AI 批量失败分析：分析所有 Fail 用例。"""
    session = request.state.session
    service = _get_ai_service(session)

    if not service.enabled:
        raise HTTPException(status_code=400, detail="AI 功能未启用")

    fail_cases = [c for c in _get_cases_as_objects(session) if c.status.upper() in ("FAIL", "REVIEW")]
    if not fail_cases:
        return {"analyses": [], "message": "没有需要分析的失败用例"}

    analyses = []
    errors = []
    for case in fail_cases:
        result = await service.analyze_failure(
            case_id=case.case_id,
            description=case.description,
            test_steps=case.test_steps,
            expected_result=case.expected_result,
            actual_output=case.actual_result,
            match_reason=case.remarks,
        )
        if not result:
            errors.append({"case_id": case.case_id, "error": "AI 分析失败"})
        elif result.get("_error"):
            errors.append({"case_id": case.case_id, "error": result["_error"]})
        else:
            analyses.append(result)

    return {
        "analyses": analyses,
        "errors": errors,
        "total": len(fail_cases),
        "analyzed": len(analyses),
    }


@router.post("/ai/report")
async def generate_report(request: Request, payload: ReportRequest):
    """AI 报告生成：基于当前执行结果生成测试报告。"""
    session = request.state.session
    service = _get_ai_service(session)

    if not service.enabled:
        raise HTTPException(status_code=400, detail="AI 功能未启用")

    cases = _get_cases_as_objects(session)
    if not cases:
        raise HTTPException(status_code=400, detail="没有用例数据，请先上传 Excel")

    # 汇总执行结果
    from datetime import date
    total = len(cases)
    pass_count = sum(1 for c in cases if c.status.upper() == "PASS")
    fail_count = sum(1 for c in cases if c.status.upper() == "FAIL")
    na_count = sum(1 for c in cases if c.status.upper() == "NA")
    skip_count = total - pass_count - fail_count - na_count

    execution_summary = {
        "total": total,
        "pass": pass_count,
        "fail": fail_count,
        "na": na_count,
        "skip": skip_count,
        "duration_seconds": 0,
        "date": date.today().isoformat(),
        "sheet": cases[0].source_sheet if cases else "",
    }

    results = []
    for c in cases:
        results.append({
            "case_id": c.case_id,
            "description": c.description,
            "status": c.status,
            "match_reason": c.remarks,
            "error_msg": "",
        })

    report = await service.generate_report(
        execution_summary=execution_summary,
        results=results,
        format=payload.format,
    )

    if report is None:
        raise HTTPException(status_code=502, detail="AI 报告生成失败")

    return report


@router.post("/ai/judge")
async def ai_judge_result(request: Request, payload: AnalyzeRequest):
    """AI 结果判定：对指定用例进行 AI 语义判定。"""
    session = request.state.session
    service = _get_ai_service(session)

    if not service.enabled:
        raise HTTPException(status_code=400, detail="AI 功能未启用")

    case = None
    for c in _get_cases_as_objects(session):
        case_key = c.case_key or f"{c.source_sheet}:{c.row_number}:{c.case_id}"
        if case_key == payload.case_id or c.case_id == payload.case_id:
            case = c
            break

    if case is None:
        raise HTTPException(status_code=404, detail=f"用例 {payload.case_id} 不存在")

    result = await service.judge_result(
        expected_text=case.expected_result,
        actual_output=case.actual_result,
        case_description=case.description,
        test_steps=case.test_steps,
    )

    if result is None:
        raise HTTPException(status_code=502, detail="AI 判定失败")

    return {"judgment": result}


class ParseStepsRequest(BaseModel):
    """AI 步骤解析请求（单条）。"""
    step_text: str
    context: str = ""
    case_id: str = ""


class ParseStepsBatchRequest(BaseModel):
    """AI 步骤批量解析请求。"""
    case_ids: list[str] = []  # 空 = 解析全部


@router.post("/ai/parse-steps")
async def ai_parse_steps(request: Request, payload: ParseStepsRequest):
    """AI 步骤解析：将测试步骤描述解析为可执行命令序列。"""
    session = request.state.session
    service = _get_ai_service(session)

    if not service.enabled:
        raise HTTPException(status_code=400, detail="AI 功能未启用，请先配置 AI 设置")

    def _cache_parsed_steps(parsed: dict):
        """把单条解析结果写入会话缓存，供执行/命令预览复用。"""
        if not payload.case_id:
            return
        if not hasattr(session, 'ai_parsed_steps'):
            session.ai_parsed_steps = {}
        session.ai_parsed_steps[payload.case_id] = parsed.get("parsed_steps", [])

    # 规则先行：CommandParser 能解出足够可执行步骤则直接返回，不调 AI
    rule_result = _rule_parse_steps(payload.step_text)
    if rule_result is not None:
        _cache_parsed_steps(rule_result)
        return rule_result

    result = await service.parse_steps(
        step_text=payload.step_text,
        context=payload.context,
    )

    if result is None:
        raise HTTPException(status_code=502, detail="AI 步骤解析失败")
    if "_error" in result and not result.get("parsed_steps"):
        raise HTTPException(status_code=502, detail=result["_error"])

    _cache_parsed_steps(result)
    return result


@router.post("/ai/parse-steps-batch")
async def ai_parse_steps_batch(request: Request, payload: ParseStepsBatchRequest):
    """AI 步骤批量解析：对所有（或指定）用例进行步骤解析。

    解析结果缓存到 session.ai_parsed_steps 供执行时使用。
    """
    session = request.state.session
    service = _get_ai_service(session)

    if not service.enabled:
        raise HTTPException(status_code=400, detail="AI 功能未启用")

    cases = _get_cases_as_objects(session)
    if not cases:
        raise HTTPException(status_code=400, detail="尚未上传用例")

    # 过滤指定用例
    if payload.case_ids:
        target_ids = set(payload.case_ids)
        cases = [c for c in cases if (
            (c.case_key or f"{c.source_sheet}:{c.row_number}:{c.case_id}") in target_ids
            or c.case_id in target_ids
        )]

    # 确保 session 有 ai_parsed_steps 字典
    if not hasattr(session, 'ai_parsed_steps'):
        session.ai_parsed_steps = {}

    results = {}
    success = 0
    failed = 0
    rule_hit = 0

    # 第一遍：规则先行，命中即采用；未命中按 test_steps 去重收集待 AI 解析项
    text_to_keys: dict[str, list[str]] = {}
    text_to_context: dict[str, str] = {}
    for case in cases:
        case_key = case.case_key or f"{case.source_sheet}:{case.row_number}:{case.case_id}"
        if not case.test_steps or not case.test_steps.strip():
            continue

        rule_result = _rule_parse_steps(case.test_steps)
        if rule_result is not None:
            results[case_key] = rule_result
            session.ai_parsed_steps[case_key] = rule_result["parsed_steps"]
            success += 1
            rule_hit += 1
            continue

        text_to_keys.setdefault(case.test_steps, []).append(case_key)
        text_to_context.setdefault(case.test_steps, case.description)

    # 第二遍：对剩余去重文本并发调 AI（限流 5）
    if text_to_keys:
        sem = asyncio.Semaphore(5)

        async def _parse_one(text: str, context: str) -> Optional[dict]:
            async with sem:
                return await service.parse_steps(step_text=text, context=context)

        unique_texts = list(text_to_keys.keys())
        tasks = [_parse_one(t, text_to_context[t]) for t in unique_texts]
        ai_results = await asyncio.gather(*tasks, return_exceptions=True)

        for text, res in zip(unique_texts, ai_results):
            for ck in text_to_keys[text]:
                if isinstance(res, Exception) or not res or "_error" in res:
                    failed += 1
                    continue
                results[ck] = res
                session.ai_parsed_steps[ck] = res.get("parsed_steps", [])
                success += 1

    return {
        "results": results,
        "total": len(cases),
        "success": success,
        "failed": failed,
        "rule_hit": rule_hit,
    }


# =========================================================================
# 执行历史记录 & 测试报告 API
# =========================================================================


@router.get("/runs")
async def list_runs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """获取执行记录列表（全局，不限 session）。"""
    from app.core.history_store import get_history_store

    loop = asyncio.get_event_loop()
    store = get_history_store()
    runs, total = await loop.run_in_executor(None, store.list_runs, limit, offset)
    return {"runs": runs, "total": total}


@router.get("/runs/compare")
async def compare_runs_endpoint(
    run1: str = Query(..., min_length=1),
    run2: str = Query(..., min_length=1),
):
    """对比两次执行记录。"""
    from app.core.history_store import get_history_store

    loop = asyncio.get_event_loop()
    store = get_history_store()
    result = await loop.run_in_executor(None, store.compare_runs, run1, run2)
    if result is None:
        raise HTTPException(status_code=404, detail="未找到指定的执行记录")
    return result


@router.get("/runs/{run_id}")
async def get_run_detail(run_id: str):
    """获取单条执行记录详情（含全部用例结果）。"""
    from app.core.history_store import get_history_store

    loop = asyncio.get_event_loop()
    store = get_history_store()
    run = await loop.run_in_executor(None, store.get_run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    results = await loop.run_in_executor(None, store.get_run_results, run_id)
    return {"run": run, "results": results}


@router.delete("/runs/{run_id}")
async def delete_run_endpoint(run_id: str):
    """删除一条执行记录（级联删除用例结果）。"""
    from app.core.history_store import get_history_store

    loop = asyncio.get_event_loop()
    store = get_history_store()
    found = await loop.run_in_executor(None, store.delete_run, run_id)
    if not found:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    return {"message": "执行记录已删除"}


@router.post("/runs/batch-delete")
async def batch_delete_runs(run_ids: List[str]):
    """批量删除执行记录（级联删除用例结果）。"""
    from app.core.history_store import get_history_store

    if not run_ids:
        raise HTTPException(status_code=400, detail="请提供要删除的记录 ID")
    loop = asyncio.get_event_loop()
    store = get_history_store()
    deleted = await loop.run_in_executor(None, store.delete_runs_batch, run_ids)
    return {"message": f"成功删除 {deleted} 条记录", "deleted": deleted}


@router.get("/runs/{run_id}/download")
async def download_run_results(run_id: str):
    """下载执行记录对应的结果 Excel 文件。"""
    from app.core.history_store import get_history_store

    loop = asyncio.get_event_loop()
    store = get_history_store()
    run = await loop.run_in_executor(None, store.get_run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="执行记录不存在")

    excel_path = run.get("excel_path", "")
    if not excel_path:
        raise HTTPException(status_code=404, detail="该记录无关联的 Excel 文件")

    # excel_path 存储为相对路径（如 "uploads/<session_id>/file.xlsx"），
    # 相对于 backend/ 目录。用 __file__ 定位以避免 cwd 依赖。
    if os.path.isabs(excel_path):
        abs_path = excel_path
    else:
        _backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        abs_path = os.path.join(_backend_dir, excel_path)
    if not os.path.exists(abs_path):
        raise HTTPException(status_code=404, detail="结果文件不存在（可能已被清理）")

    filename = run.get("excel_filename", "") or os.path.basename(abs_path)

    # 历史结果文件可能仍保留旧版「判断依据」表头，下载副本中统一改回「BUG」；
    # 不改动原始记录文件（执行历史应保持快照）。
    from app.core.excel_handler import ExcelHandler

    tmp_dir = None
    try:
        handler = ExcelHandler()
        handler.load(abs_path)
        if getattr(handler, "bug_header_renamed", False):
            tmp_dir = tempfile.mkdtemp(prefix="history_download_")
            abs_path = os.path.join(tmp_dir, filename)
            handler.workbook.save(abs_path)
    except Exception:
        # 解析失败时按原文件原样下载
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir = None

    from urllib.parse import quote
    encoded_filename = quote(filename)
    return FileResponse(
        abs_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"},
        background=BackgroundTask(shutil.rmtree, tmp_dir, True) if tmp_dir else None,
    )


@router.post("/reports/generate/{run_id}")
async def generate_run_report(
    request: Request,
    run_id: str,
    type: str = Query("summary", regex="^(summary|ai)$"),
):
    """为指定执行记录生成测试报告。

    type=summary: 使用本地报告生成器（无需 AI）
    type=ai: 调用 AI 生成报告（需已配置 AI）
    """
    from app.core.history_store import get_history_store
    from app.core.report_generator import ReportGenerator

    loop = asyncio.get_event_loop()
    store = get_history_store()
    run = await loop.run_in_executor(None, store.get_run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    results = await loop.run_in_executor(None, store.get_run_results, run_id)

    report_id = uuid4().hex
    started = run.get("started_at", "")[:10]
    version = run.get("test_version", "")

    if type == "ai":
        session = request.state.session
        service = _get_ai_service(session)
        if not service.enabled:
            raise HTTPException(status_code=400, detail="AI 功能未启用")

        total = run.get("total_count", 0)
        pass_c = run.get("pass_count", 0)
        fail_c = run.get("fail_count", 0)
        from datetime import date
        exec_summary = {
            "total": total, "pass": pass_c, "fail": fail_c,
            "na": run.get("na_count", 0),
            "skip": total - pass_c - fail_c - run.get("na_count", 0),
            "duration_seconds": run.get("duration_seconds", 0),
            "date": started or date.today().isoformat(),
            "sheet": run.get("sheets_used", ""),
        }
        ai_results = [
            {"case_id": r["case_id"], "description": r.get("description", ""),
             "status": r["status"], "match_reason": r.get("match_reason", ""), "error_msg": ""}
            for r in results
        ]
        ai_report = await service.generate_report(
            execution_summary=exec_summary, results=ai_results, format="markdown")
        if ai_report is None:
            raise HTTPException(status_code=502, detail="AI 报告生成失败")

        content = ai_report.get("report", str(ai_report))
        title = f"AI 报告 — {version} — {started}"
        fmt = "markdown"
    else:
        generator = ReportGenerator()
        content = generator.generate_summary_report(run, results)
        title = f"测试报告 — {version} — {started}"
        fmt = "html"

    report_data = {
        "report_id": report_id,
        "run_id": run_id,
        "title": title,
        "report_type": type,
        "format": fmt,
        "content": content,
        "total_count": run.get("total_count", 0),
        "pass_count": run.get("pass_count", 0),
        "fail_count": run.get("fail_count", 0),
        "pass_rate": run.get("pass_rate", 0),
        "tester_name": run.get("tester_name", ""),
        "test_version": run.get("test_version", ""),
    }
    await loop.run_in_executor(None, store.save_report, report_data)
    return report_data


@router.get("/reports")
async def list_reports(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """获取报告列表。"""
    from app.core.history_store import get_history_store

    loop = asyncio.get_event_loop()
    store = get_history_store()
    reports, total = await loop.run_in_executor(None, store.list_reports, limit, offset)
    return {"reports": reports, "total": total}


@router.get("/reports/{report_id}/export")
async def export_report(
    report_id: str,
    format: str = Query("html", regex="^(html|xlsx)$"),
):
    """导出报告为 HTML 或 Excel。"""
    from app.core.history_store import get_history_store

    loop = asyncio.get_event_loop()
    store = get_history_store()
    report = await loop.run_in_executor(None, store.get_report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")

    if format == "html":
        content = report.get("content", "")
        filename = f"{report.get('title', 'report')}.html"
        # RFC 5987: 中文文件名需要 URL 编码，否则 latin-1 编码崩溃
        from urllib.parse import quote
        encoded_filename = quote(filename)
        return Response(
            content=content.encode("utf-8"),
            media_type="text/html; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            },
        )
    else:
        # xlsx 导出
        import io
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment

        run_id = report.get("run_id")
        results = []
        if run_id:
            results = await loop.run_in_executor(None, store.get_run_results, run_id)

        wb = Workbook()
        ws = wb.active
        ws.title = "测试摘要"
        ws["A1"] = "测试报告"
        ws["A1"].font = Font(bold=True, size=14)
        ws["A3"] = "测试人员"
        ws["B3"] = report.get("tester_name", "")
        ws["A4"] = "测试版本"
        ws["B4"] = report.get("test_version", "")
        ws["A5"] = "总计"
        ws["B5"] = report.get("total_count", 0)
        ws["A6"] = "通过"
        ws["B6"] = report.get("pass_count", 0)
        ws["A7"] = "失败"
        ws["B7"] = report.get("fail_count", 0)
        ws["A8"] = "通过率"
        ws["B8"] = f"{report.get('pass_rate', 0)}%"

        if results:
            ws_results = wb.create_sheet("测试结果")
            headers = ["用例编号", "描述", "优先级", "状态", "实际结果", "预期结果"]
            header_fill = PatternFill(start_color="E8ECF4", end_color="E8ECF4", fill_type="solid")
            for col_idx, header in enumerate(headers, 1):
                cell = ws_results.cell(row=1, column=col_idx, value=header)
                cell.font = Font(bold=True)
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal="center")

            for row_idx, r in enumerate(results, 2):
                ws_results.cell(row=row_idx, column=1, value=r.get("case_id", ""))
                ws_results.cell(row=row_idx, column=2, value=r.get("description", ""))
                ws_results.cell(row=row_idx, column=3, value=r.get("priority", ""))
                status_cell = ws_results.cell(row=row_idx, column=4, value=r.get("status", ""))
                status_val = (r.get("status", "")).upper()
                if status_val == "PASS":
                    status_cell.font = Font(color="36B37E", bold=True)
                elif status_val == "FAIL":
                    status_cell.font = Font(color="DE350B", bold=True)
                ws_results.cell(row=row_idx, column=5, value=r.get("actual_result", ""))
                ws_results.cell(row=row_idx, column=6, value=r.get("expected_result", ""))

            for col in range(1, 7):
                ws_results.column_dimensions[chr(64 + col)].width = 20

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        filename = f"{report.get('title', 'report')}.xlsx"
        from urllib.parse import quote
        encoded_filename = quote(filename)
        return Response(
            content=buf.read(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            },
        )


@router.get("/reports/{report_id}")
async def get_report_detail(report_id: str):
    """获取单个报告（含完整内容）。"""
    from app.core.history_store import get_history_store

    loop = asyncio.get_event_loop()
    store = get_history_store()
    report = await loop.run_in_executor(None, store.get_report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    return report


@router.delete("/reports/{report_id}")
async def delete_report_endpoint(report_id: str):
    """删除一个报告。"""
    from app.core.history_store import get_history_store

    loop = asyncio.get_event_loop()
    store = get_history_store()
    found = await loop.run_in_executor(None, store.delete_report, report_id)
    if not found:
        raise HTTPException(status_code=404, detail="报告不存在")
    return {"message": "报告已删除"}

