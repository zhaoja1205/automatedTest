"""
REST API 路由。

提供：用例管理、Excel 上传/下载、SSH 配置、工作区配置、执行控制。

所有路由通过 request.state.session (SessionState) 访问当前会话的隔离状态，
支持多个 PC 端同时独立测试。
"""
import os
from typing import List, Optional

from fastapi import APIRouter, Request, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core.test_case import TestCase, SSHConfig, SSHStatus, WorkspaceConfig
from app.core.execution_state import ExecutionTask
from app.core.ssh_manager import SSHManager

router = APIRouter()


class ExecuteRequest(BaseModel):
    """执行请求，可指定待执行用例列表（case_key 唯一标识）。"""
    case_ids: List[str] = []  # 兼容旧逻辑，实际传的是 case_key


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

    ordered_sheets = []
    seen = set()
    for c in cases:
        if c.source_sheet and c.source_sheet not in seen:
            ordered_sheets.append(c.source_sheet)
            seen.add(c.source_sheet)

    return {
        "message": "上传成功",
        "case_count": len(cases),
        "sheets": ordered_sheets,
    }


@router.get("/cases")
async def get_cases(request: Request, sheet: str = None):
    """获取用例列表"""
    session = request.state.session
    cases = session.test_cases
    if sheet:
        cases = [c for c in cases if c.get("source_sheet") == sheet]
    return cases


@router.post("/cases/select")
async def select_cases(request: Request, case_ids: List[str], selected: bool = True):
    """批量选择/取消选择用例"""
    session = request.state.session
    for c in session.test_cases:
        if c.get("case_id") in case_ids:
            c["selected"] = selected
    return {"message": "更新成功"}


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

    # 重置选中用例的状态为 NT，清除旧的执行结果
    for c in cases:
        if c.get("selected", False):
            c["status"] = "NT"
            c["actual_result"] = ""

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
            if ec.tester:
                sc["tester"] = ec.tester
            if ec.test_version:
                sc["test_version"] = ec.test_version
            if ec.test_date:
                sc["test_date"] = ec.test_date


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
        executor = ExecutorAdapter(ssh, manager, workspace=workspace, log_dir=log_dir)
        session.executor = executor

        # 转换用例
        cases = [TestCase(**c) for c in session.test_cases]
        results = await executor.execute_all(
            cases,
            run_prerequisites=workspace.run_prerequisites,
        )

        # 将执行结果同步回 session，确保下次执行/查询能看到最新结果
        _sync_cases_to_state(session, cases)

        # 保存结果
        if session.excel_path:
            from app.core.excel_handler import ExcelHandler
            handler = ExcelHandler()
            handler.load(session.excel_path)
            handler.save_results(cases, session.excel_path)

        current_task.completed_count = len(results)

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
        await manager.send_log(f"执行异常: {e}", "error")
        await manager.broadcast({
            "type": "execution_stopped",
            "message": f"执行异常: {e}",
        })
    finally:
        # 无论正常结束、用户停止、还是异常退出，都将已执行的结果同步回 state
        if cases:
            _sync_cases_to_state(session, cases)
        session.is_running = False
        session._stop_requested = False
        session.executor = None
        if ssh:
            try:
                ssh.disconnect()
            except Exception:
                pass


@router.get("/download/results")
async def download_results(request: Request):
    """下载结果 Excel"""
    session = request.state.session
    path = session.excel_path
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="结果文件不存在")
    return FileResponse(path, filename=os.path.basename(path))


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
    import shlex
    import subprocess
    import tempfile

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

    askpass_dir = tempfile.mkdtemp(prefix="scp_askpass_")
    askpass_path = os.path.join(askpass_dir, "askpass.sh")
    try:
        with open(askpass_path, "w") as f:
            f.write("#!/bin/sh\n")
            f.write(f"echo {shlex.quote(ssh_config.password)}\n")
        os.chmod(askpass_path, 0o700)

        scp_cmd = [
            "scp", "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-P", str(ssh_config.port),
        ]
        if is_dir:
            scp_cmd.append("-r")
        scp_cmd.extend([
            local_path,
            f"{ssh_config.username}@{ssh_config.host}:{target_path}",
        ])
        env = os.environ.copy()
        env["DISPLAY"] = env.get("DISPLAY", ":999")
        env["SSH_ASKPASS"] = askpass_path
        env["SSH_ASKPASS_REQUIRE"] = "force"

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
            os.remove(askpass_path)
        except Exception:
            pass
        try:
            os.rmdir(askpass_dir)
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
