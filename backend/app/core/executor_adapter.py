"""执行器适配器（异步版）。

将原 PyQt 执行逻辑适配为异步，支持 WebSocket 实时推送。
- 命令解析：CommandParser 把测试步骤拆成可执行命令序列，不再整段当一条命令
- 预期匹配：ExpectedResultParser 做关键字/帧率/错误词匹配
- NA 识别：命中待写入/TBD 等关键字自动标记 NA 并跳过执行
- 工作目录：追踪 cd / 进入调试目录，命令以 ``cd <dir> && <cmd>`` 形式下发
- 非阻塞：SSH 同步调用通过 run_in_executor 移出事件循环，避免长时间执行卡死后端
"""
import asyncio
import os
from datetime import datetime
from app.core.test_case import TestCase, TestResult
from app.core.command_parser import CommandParser
from app.core.expected_parser import ExpectedResultParser, MatchResult


class ExecutorAdapter:
    def __init__(self, ssh_manager, ws_manager, workspace=None, log_dir="logs",
                 ai_service=None):
        self.ssh = ssh_manager
        self.ws = ws_manager
        self.workspace = workspace
        self.log_dir = log_dir
        self._stop = False
        self.parser = ExpectedResultParser()
        self._image_path_checked = False
        self._ai_service = ai_service  # AI 判定服务（可选）

    def stop(self):
        self._stop = True
        # 立即终止正在执行的 SSH 子进程，避免阻塞
        if self.ssh and hasattr(self.ssh, 'abort'):
            self.ssh.abort()

    async def execute_all(self, cases: list, run_prerequisites: bool = True) -> list:
        results = []
        selected = [c for c in cases if c.selected]
        total = len(selected)

        for idx, case in enumerate(selected, 1):
            if self._stop:
                await self.ws.send_log("执行被用户停止", "warning")
                break

            await self.ws.send_progress(idx, total, case.case_id, case.case_key)
            result = await self._execute_single(case, run_prerequisites)
            results.append(result)
            await self.ws.send_case_complete(
                case.case_id, result.status, result.match_reason,
                case.case_key, case.actual_result
            )

        return results

    async def _execute_single(self, case: TestCase, run_prerequisites: bool) -> TestResult:
        result = TestResult(case_id=case.case_id, start_time=datetime.now())

        # NA 自动识别
        is_na, na_reason = CommandParser.should_mark_na(
            case.test_steps, case.expected_result, case.prerequisites, case.description,
        )
        if is_na:
            result.status = "NA"
            result.match_reason = na_reason
            result.end_time = datetime.now()
            case.status = "NA"
            case.actual_result = na_reason
            await self.ws.send_log(f"[{case.case_id}] 标记为 NA：{na_reason}", "info")
            return result

        # 前置条件
        if run_prerequisites and case.prerequisites:
            await self.ws.send_log(f"[{case.case_id}] 执行前置条件...", "info")
            ok = await self._run_prerequisites(case.prerequisites)
            if not ok:
                result.status = "Fail"
                result.error_msg = "前置条件失败"
                result.end_time = datetime.now()
                case.status = "Fail"
                case.actual_result = "前置条件失败"
                return result

        # 执行测试步骤
        await self.ws.send_log(f"[{case.case_id}] 执行测试步骤...", "info")
        log_file = f"{self.log_dir}/{case.case_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        os.makedirs(self.log_dir, exist_ok=True)

        # 回写 tester / version / date（Bug 9）
        self._fill_execution_meta(case)

        # 检查/创建板端 image 存储路径（只检查一次）
        if not self._image_path_checked:
            await self._ensure_image_storage_path(case.case_id)
            self._image_path_checked = True

        default_remote_path = getattr(self.workspace, "default_remote_path", "") or ""
        steps = CommandParser.parse(case.test_steps, default_remote_path=default_remote_path)

        # 合并 nvsipl_camera + 后续交互输入为管道命令
        steps = self._merge_nvsipl_interactive(steps)

        combined_outputs = []
        last_exit_code = 0
        last_cmd = ""

        try:
            work_dir = default_remote_path

            # 检测是否需要持久化 shell 模式（export + repeat + nvsipl 组合）
            has_export = any(s.kind == "command" and s.command.strip().startswith("export ") for s in steps)
            has_repeat = any(s.kind == "repeat" for s in steps)
            has_nvsipl = any(s.kind == "command" and CommandParser.is_nvsipl_camera_command(s.command) for s in steps)
            if has_export and has_repeat and has_nvsipl:
                try:
                    combined_outputs, last_exit_code, last_cmd = await asyncio.wait_for(
                        self._execute_with_persistent_shell(case, steps, work_dir),
                        timeout=300,
                    )
                except asyncio.TimeoutError:
                    await self.ws.send_log(
                        f"[{case.case_id}] [持久Shell] 执行超时(300s)，强制终止", "error")
                    combined_outputs = ["执行超时(300s)"]
                    last_exit_code = -1
                    last_cmd = "persistent_shell"
            else:
                # 原有逻辑：检测并行/阻塞/顺序执行模式
                blocking_idx = self._find_blocking_nvsipl_index(steps)
                if blocking_idx is not None:
                    # DEBUG: 打印 merge 后的步骤，确认 al 是否存在
                    step_summary = [(s.kind, s.command[:40] if s.command else '') for s in steps]
                    await self.ws.send_log(f"[{case.case_id}] [DEBUG] merged steps: {step_summary}", "info")
                if blocking_idx is not None and blocking_idx < len(steps) - 1:
                    # 并行执行模式（故障测试），动态超时保护
                    # 反复起流模式需要更长超时：每轮 ~45s
                    pty_timeout = 180
                    for s in steps:
                        if s.kind == "repeat_stream":
                            n = int(s.command) if s.command.isdigit() else 10
                            pty_timeout = max(180, n * 50 + 60)  # 每轮50s + 60s余量
                            break
                        if s.kind == "repeat":
                            pty_timeout = 360  # 重复步骤给更多时间
                            break
                    try:
                        combined_outputs, last_exit_code, last_cmd = await asyncio.wait_for(
                            self._execute_parallel_fault_test(case, steps, blocking_idx, work_dir),
                            timeout=pty_timeout,
                        )
                    except asyncio.TimeoutError:
                        await self.ws.send_log(
                            f"[{case.case_id}] [并行模式] 执行超时({pty_timeout}s)，强制终止", "error")
                        combined_outputs = [f"执行超时({pty_timeout}s)"]
                        last_exit_code = -1
                        last_cmd = "parallel_fault_test"
                elif blocking_idx is not None:
                    # 阻塞型 nvsipl 作为唯一步骤（无后续命令）：走 PTY 模式执行 gc → 等出帧 → q 退出
                    try:
                        combined_outputs, last_exit_code, last_cmd = await asyncio.wait_for(
                            self._execute_parallel_fault_test(case, steps, blocking_idx, work_dir),
                            timeout=180,
                        )
                    except asyncio.TimeoutError:
                        await self.ws.send_log(
                            f"[{case.case_id}] [PTY模式] 执行超时(180s)，强制终止", "error")
                        combined_outputs = ["执行超时(180s)"]
                        last_exit_code = -1
                        last_cmd = "blocking_nvsipl_single"
                else:
                    # 普通顺序执行模式
                    for step in steps:
                        if self._stop:
                            await self.ws.send_log(f"[{case.case_id}] 执行被用户停止", "warning")
                            break

                        if step.kind == "skip":
                            await self.ws.send_log(f"[{case.case_id}] {step.description}", "info")
                            continue

                        if step.kind == "manual":
                            await self.ws.send_log(
                                f"[{case.case_id}] 需人工操作：{step.description}（已跳过自动执行）", "warning")
                            continue

                        if step.kind == "enter_dir":
                            work_dir = step.command
                            await self.ws.send_log(f"[{case.case_id}] 切换工作目录 -> {work_dir}", "info")
                            continue

                        if step.kind == "cd":
                            work_dir = step.command
                            await self.ws.send_log(f"[{case.case_id}] cd -> {work_dir}", "info")
                            continue

                        if step.kind == "confirm":
                            ok = await self.ws.request_manual_confirm(step.description)
                            if not ok:
                                result.status = "Fail"
                                result.error_msg = f"人工确认未通过：{step.description}"
                                result.end_time = datetime.now()
                                case.status = "Fail"
                                case.actual_result = result.error_msg
                                return result
                            continue

                        if step.kind == "command":
                            shell_cmd = self._normalize_quotes(step.command)
                            shell_cmd = self._apply_nito_override(shell_cmd)
                            shell_cmd = self._apply_image_path_override(shell_cmd)
                            shell_cmd = self._apply_sudo_password(shell_cmd)

                            # nvsipl_camera 命令：自动注入 gc（防止卡在等 gc 输入）
                            if CommandParser.is_nvsipl_camera_command(step.command):
                                shell_cmd = self._wrap_nvsipl_with_gc(shell_cmd, step.command)

                            if work_dir:
                                shell_cmd = f"cd {work_dir} && {shell_cmd}"
                            last_cmd = shell_cmd
                            await self.ws.send_log(f"[{case.case_id}] [{step.terminal}] 执行: {shell_cmd}", "info")

                            # nvsipl_camera 需要 TTY 才能正常交互和初始化
                            needs_tty = CommandParser.is_nvsipl_camera_command(step.command)
                            exit_code, stdout, stderr = await self._ssh_execute(
                                shell_cmd, timeout=300, force_tty=needs_tty)
                            last_exit_code = exit_code
                            combined_outputs.append(stdout or "")
                            if stderr:
                                combined_outputs.append(stderr)

                            # 推送命令输出关键行（帧率、成功、错误等关键信息）
                            key_lines = self._extract_key_output_lines(stdout or "")
                            if key_lines:
                                await self.ws.send_log(
                                    f"[{case.case_id}] 命令关键输出:\n{key_lines}", "info")

                            if exit_code != 0:
                                await self.ws.send_log(
                                    f"[{case.case_id}] 命令返回码非0: exit_code={exit_code}", "warning")

            combined = "\n".join(combined_outputs)

            # 文件类预期检查：在板端查找最近生成的文件，把文件名加入 combined 供匹配
            criteria = self.parser.parse(case.expected_result)
            if criteria.file_check and work_dir:
                # 搜索目录优先使用 image_storage_path（如果启用），否则用 work_dir
                search_dir = work_dir
                if (self.workspace
                        and getattr(self.workspace, "image_storage_enabled", False)
                        and getattr(self.workspace, "image_storage_path", "")):
                    search_dir = self.workspace.image_storage_path.rstrip("/")

                file_output = await self._check_remote_files(case.case_id, search_dir, criteria.file_check)
                if file_output:
                    combined += "\n" + file_output
                    # 文件数量验证（仅当预期结果中明确了数量时）
                    if criteria.file_count > 0:
                        file_list = [f for f in file_output.split('\n') if f.strip()]
                        if len(file_list) >= criteria.file_count:
                            combined += (
                                f"\n[文件数量检查] 找到 {len(file_list)} 个文件 "
                                f">= 预期 {criteria.file_count} 个: PASS")
                        else:
                            combined += (
                                f"\n[文件数量检查] 找到 {len(file_list)} 个文件 "
                                f"< 预期 {criteria.file_count} 个: FAIL")
                elif criteria.file_count > 0:
                    combined += (
                        f"\n[文件数量检查] 找到 0 个文件 "
                        f"< 预期 {criteria.file_count} 个: FAIL")

            result.actual_output = combined
            result.log_file = log_file

            with open(log_file, "w", encoding="utf-8") as f:
                f.write(combined)
            result.log_file = log_file

            # 预期结果匹配
            # 判断用例类型并选择对应的匹配策略
            from app.core.frame_sync_checker import FrameSyncChecker

            # 优先级 1: 嵌入行信息人工确认（预期含曝光/增益/帧序号关键字 + metadata 输出）
            is_metadata_embedded = (
                FrameSyncChecker.is_metadata_embedded_case(case.expected_result)
                and 'Camera ID:' in combined
                and 'Frame Counter:' in combined
            )

            # 优先级 1.5: sr/hs 待确认用例（预期含 ROI/直方图 + 输出含相关特征）
            is_sr_hs_review = (
                FrameSyncChecker.is_sr_hs_review_case(case.expected_result)
                and ('set ROI' in combined or 'histogramInfo' in combined
                     or 'ROI values' in combined or 'Histogram' in combined
                     or 'Please enter' in combined or 'histogram' in combined.lower())
            )

            # 优先级 2: 帧同步自动判定
            is_frame_sync = False
            if not is_metadata_embedded and not is_sr_hs_review:
                is_frame_sync = FrameSyncChecker.is_frame_sync_case(last_cmd)
                # 即使 last_cmd 被后续命令覆盖，也通过 combined 输出特征检测帧同步
                if not is_frame_sync and 'Camera ID:' in combined and 'TSC SOF:' in combined:
                    is_frame_sync = True

            is_dl_elr_case = "Disable Link" in combined and "Enable Link" in combined

            if is_metadata_embedded:
                # 嵌入行信息 — 截取 metadata log 写入实际结果，标记"待确认"
                metadata_log = FrameSyncChecker.extract_metadata_frames(combined, max_frames=10)
                await self.ws.send_log(
                    f"[{case.case_id}] 嵌入行信息检测 — 已截取 metadata log，标记待确认", "info")
                passed = None  # 特殊标记：非 Pass 非 Fail
                reason = f"嵌入行信息: 待确认 (已截取 metadata log，需人工核对曝光/增益/帧序号)"
                # 直接将 metadata log 写入 actual_result（覆盖后续 _build_evidence_summary）
                result._metadata_log = metadata_log
            elif is_sr_hs_review:
                # sr/hs 用例 — 将输出 log 写入实际结果，标记"待确认"
                await self.ws.send_log(
                    f"[{case.case_id}] sr/hs 用例 — 已收集输出，标记待确认", "info")
                passed = None
                reason = "sr/hs: 待确认 (已收集 ROI/直方图输出，需人工核对)"
                result._sr_hs_log = combined
            elif is_frame_sync:
                # 帧同步检测（--showmetadata 模式）
                passed, reason = FrameSyncChecker.check(combined, case.expected_result, last_cmd)
            elif is_dl_elr_case:
                passed, reason = await self._match_dl_elr_stages(case.case_id, combined)
            else:
                match_result = self.parser.match(criteria, combined, last_exit_code, last_cmd)
                passed = match_result.passed
                reason = match_result.reason

                # ---- AI Fallback 判定 ----
                # 当规则引擎置信度 < 0.8 且 AI judge 功能已启用时，
                # 调用 AI 做语义级 Pass/Fail 判定
                ai_judge_attempted = False
                if (self._ai_service
                        and self._ai_service.enabled
                        and self._ai_service.config.get("ai_judge_uncertain", True)
                        and match_result.confidence < 0.8):
                    try:
                        await self.ws.send_log(
                            f"[{case.case_id}] 规则置信度 {match_result.confidence:.2f} < 0.8，尝试 AI 判定...",
                            "info")
                        ai_result = await self._ai_service.judge_result(
                            expected_text=case.expected_result,
                            actual_output=combined[-5000:],  # 截断避免 token 浪费
                            case_description=case.description,
                            test_steps=case.test_steps,
                            exit_code=last_exit_code,
                        )
                        if ai_result and ai_result.get("confidence", 0) >= 0.7:
                            ai_status = ai_result.get("status", "")
                            ai_conf = ai_result.get("confidence", 0)
                            ai_reason_text = ai_result.get("reason", "")
                            ai_source = "AI(cached)" if ai_result.get("_from_cache") else "AI"

                            if ai_status in ("Pass", "Fail"):
                                passed = ai_status == "Pass"
                                reason += f"; [AI判定] {ai_source}: {ai_status} (置信度={ai_conf:.2f}，{ai_reason_text})"
                                match_result = MatchResult(
                                    passed=passed,
                                    confidence=ai_conf,
                                    reason=reason,
                                    source="ai",
                                )
                                ai_judge_attempted = True
                                await self.ws.send_log(
                                    f"[{case.case_id}] AI 判定: {ai_status} (置信度={ai_conf:.2f})",
                                    "info")
                            elif ai_status == "NEED_REVIEW":
                                passed = None
                                reason += f"; [AI判定] {ai_source}: NEED_REVIEW (置信度={ai_conf:.2f}，{ai_reason_text})"
                                ai_judge_attempted = True
                                await self.ws.send_log(
                                    f"[{case.case_id}] AI 判定: NEED_REVIEW (置信度={ai_conf:.2f})",
                                    "warning")
                        elif ai_result:
                            await self.ws.send_log(
                                f"[{case.case_id}] AI 置信度 {ai_result.get('confidence', 0):.2f} < 0.7，保留规则判定",
                                "info")
                    except Exception as ai_err:
                        await self.ws.send_log(
                            f"[{case.case_id}] AI 判定异常（降级为规则结果）: {ai_err}",
                            "warning")

                if not ai_judge_attempted:
                    reason += f"; [规则置信度={match_result.confidence:.2f}]"
            result.match_reason = reason
            result.match_log_file = log_file

            # 推送匹配判定详情到前端日志
            await self.ws.send_log(
                f"[{case.case_id}] === 匹配判定 ===", "info")
            if not is_dl_elr_case and not is_frame_sync and not is_metadata_embedded:
                await self.ws.send_log(
                    f"[{case.case_id}] 预期关键字: {case.expected_keywords or '(无)'}", "info")
            for reason_line in reason.split("; "):
                level = "info"
                if "[WARN]" in reason_line:
                    level = "warning"
                elif "FAIL" in reason_line or "Fail" in reason_line or "非0" in reason_line:
                    level = "warning"
                elif "PASS" in reason_line or "Pass" in reason_line or "OK" in reason_line:
                    level = "info"
                await self.ws.send_log(f"[{case.case_id}]   {reason_line}", level)
            if passed is None:
                result.status = "Review"  # 待确认：需人工核对 metadata log
            else:
                result.status = "Pass" if passed else "Fail"

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            result.status = "Fail"
            result.error_msg = f"{type(e).__name__}: {e}"
            result.match_reason = f"执行异常: {type(e).__name__}: {e}"
            await self.ws.send_log(f"[{case.case_id}] 异常: {type(e).__name__}: {e}", "error")
            await self.ws.send_log(f"[{case.case_id}] Traceback:\n{tb}", "error")

            # 检查 SSH 传输层是否仍然存活，如果已断开则尝试重连
            # 确保后续用例不受当前用例异常影响
            try:
                transport = self.ssh.client.get_transport() if self.ssh.client else None
                if transport is None or not transport.is_active():
                    await self.ws.send_log(
                        f"[{case.case_id}] SSH 传输层已断开，尝试重连...", "warning")
                    loop = asyncio.get_event_loop()
                    reconnected = await loop.run_in_executor(None, self.ssh.connect)
                    if reconnected:
                        await self.ws.send_log(
                            f"[{case.case_id}] SSH 重连成功，后续用例可继续执行", "info")
                    else:
                        await self.ws.send_log(
                            f"[{case.case_id}] SSH 重连失败: {self.ssh.last_error}", "error")
            except Exception as reconnect_err:
                await self.ws.send_log(
                    f"[{case.case_id}] SSH 状态检查/重连异常: {reconnect_err}", "error")

        result.end_time = datetime.now()
        case.status = result.status
        # 嵌入行信息用例：直接将 metadata log 作为实际结果
        if hasattr(result, '_metadata_log') and result._metadata_log:
            case.actual_result = f"[待确认] 嵌入行信息 metadata log:\n{result._metadata_log}"
        elif hasattr(result, '_sr_hs_log') and result._sr_hs_log:
            # sr/hs 用例：提取有效输出作为实际结果
            sr_hs_lines = []
            for line in result._sr_hs_log.split('\n'):
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("Enter '"):
                    continue
                if stripped in ('-', 'Output'):
                    continue
                sr_hs_lines.append(stripped)
            case.actual_result = f"[待确认] sr/hs 输出 log:\n" + "\n".join(sr_hs_lines[:60])
        else:
            case.actual_result = self._build_evidence_summary(result, result.status == "Pass")
        return result

    def _fill_execution_meta(self, case: TestCase):
        """把工作区配置的 tester / version / date 回写到用例，供 Excel 保存时写入。"""
        if self.workspace:
            if getattr(self.workspace, "tester_name", "") and not case.tester:
                case.tester = self.workspace.tester_name
            if getattr(self.workspace, "test_version", "") and not case.test_version:
                case.test_version = self.workspace.test_version
        if not case.test_date:
            case.test_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    async def _execute_with_persistent_shell(self, case, steps, work_dir):
        """持久化 shell 模式：所有步骤在同一 PTY invoke_shell 中顺序执行。

        适用于 export 环境变量 + repeat 步骤组合，确保变量在 shell session 内持久生效。
        nvsipl_camera -s --writeFrames N 拍照模式：发送 gc 后自动拍帧退出。

        返回: (combined_outputs, last_exit_code, last_cmd)
        """
        import re
        import time as _time

        combined_outputs = []
        last_exit_code = 0
        last_cmd = ""

        loop = asyncio.get_event_loop()

        await self.ws.send_log(
            f"[{case.case_id}] [持久Shell] 启动持久化 shell 模式（export+repeat 组合）", "info")

        # 打开持久化 shell
        channel = await loop.run_in_executor(
            None, lambda: self.ssh.open_shell_channel(timeout=300)
        )

        all_output = ""

        async def _read_shell(timeout_sec: float, stop_pattern: str = None) -> str:
            """读取 shell 输出，直到超时或匹配 stop_pattern。"""
            nonlocal all_output
            buf = ""
            start = _time.time()
            while _time.time() - start < timeout_sec:
                if self._stop:
                    break
                try:
                    ready = await loop.run_in_executor(None, channel.recv_ready)
                except (OSError, EOFError):
                    break
                if ready:
                    try:
                        data = await loop.run_in_executor(None, lambda: channel.recv(65536))
                    except (OSError, EOFError):
                        break
                    text = data.decode("utf-8", errors="replace")
                    buf += text
                    all_output += text
                    if stop_pattern and re.search(stop_pattern, buf, re.IGNORECASE):
                        break
                else:
                    await asyncio.sleep(0.2)
            return buf

        async def _send_cmd(cmd_text: str):
            """向 shell 发送一条命令。"""
            await loop.run_in_executor(None, lambda: channel.send(cmd_text + "\n"))

        try:
            # 等待 shell 提示符就绪
            init_output = await _read_shell(5.0, stop_pattern=r"[#\$>]\s*$")
            await self.ws.send_log(f"[{case.case_id}] [持久Shell] shell 就绪", "info")

            # cd 到工作目录
            if work_dir:
                await _send_cmd(f"cd {work_dir}")
                await _read_shell(3.0, stop_pattern=r"[#\$>]\s*$")
                await self.ws.send_log(f"[{case.case_id}] [持久Shell] cd -> {work_dir}", "info")

            # 展开 repeat 步骤为实际步骤序列
            resolved_steps = []
            for step in steps:
                if step.kind == "repeat":
                    m = re.match(r'(\d+)-(\d+)', step.command)
                    if m:
                        start_idx = int(m.group(1))
                        end_idx = int(m.group(2))
                        # 步骤编号从 1 开始，对应 steps 列表索引 0-based
                        for ref_idx in range(start_idx - 1, end_idx):
                            if 0 <= ref_idx < len(steps):
                                ref_step = steps[ref_idx]
                                if ref_step.kind != "repeat":
                                    resolved_steps.append(ref_step)
                    else:
                        resolved_steps.append(step)
                else:
                    resolved_steps.append(step)

            await self.ws.send_log(
                f"[{case.case_id}] [持久Shell] 展开后步骤: "
                f"{[(s.kind, s.command[:50]) for s in resolved_steps]}", "info")

            # 拍照命名：多次 nvsipl 拍照按含义命名区分
            CAPTURE_NAMES = ["default", "rotate"]
            capture_idx = 0

            # 逐步执行
            for step_idx, step in enumerate(resolved_steps):
                if self._stop:
                    await self.ws.send_log(f"[{case.case_id}] [持久Shell] 被用户停止", "warning")
                    break

                if step.kind == "skip":
                    await self.ws.send_log(
                        f"[{case.case_id}] [持久Shell] 跳过: {step.description}", "info")
                    continue

                if step.kind == "command":
                    shell_cmd = self._normalize_quotes(step.command)
                    shell_cmd = self._apply_nito_override(shell_cmd)
                    shell_cmd = self._apply_image_path_override(shell_cmd)
                    shell_cmd = self._apply_sudo_password(shell_cmd)

                    # 环境变量覆盖：如果配置了 cam_rotate_cfg 且当前是 CAM_ROTATE_CFG_PATH export
                    if shell_cmd.strip().startswith("export ") and "CAM_ROTATE_CFG_PATH" in shell_cmd:
                        if (self.workspace
                                and getattr(self.workspace, "cam_rotate_cfg_enabled", False)
                                and getattr(self.workspace, "cam_rotate_cfg_path", "")):
                            override_path = self.workspace.cam_rotate_cfg_path
                            shell_cmd = f"export CAM_ROTATE_CFG_PATH={override_path}"
                            await self.ws.send_log(
                                f"[{case.case_id}] [持久Shell] 环境变量被工作区配置覆盖: "
                                f"CAM_ROTATE_CFG_PATH={override_path}", "info")

                    if CommandParser.is_nvsipl_camera_command(shell_cmd):
                        # 自动为 -f 路径补充区分名（多次拍照区分文件）
                        shell_cmd = self._inject_capture_name(shell_cmd, capture_idx, CAPTURE_NAMES)
                        capture_idx += 1

                        # nvsipl_camera 拍照命令：发送 → 等初始化 → 发送 gc → 等退出
                        await self.ws.send_log(
                            f"[{case.case_id}] [持久Shell] [{step_idx+1}] 执行 nvsipl: {shell_cmd}", "info")
                        last_cmd = shell_cmd
                        await _send_cmd(shell_cmd)

                        # 等待 nvsipl 初始化完成（"Enter 'gc" 提示出现）
                        nvsipl_init = await _read_shell(30.0, stop_pattern=r"Enter\s+'gc")
                        if "ERROR" in nvsipl_init or "failed" in nvsipl_init.lower():
                            await self.ws.send_log(
                                f"[{case.case_id}] [持久Shell] nvsipl 启动失败: "
                                f"{nvsipl_init[-200:]}", "error")
                            combined_outputs.append(nvsipl_init)
                            last_exit_code = -1
                            break

                        # 发送 gc 触发出帧
                        gc_cmds = self._generate_gc_commands(shell_cmd)
                        gc_cmd = gc_cmds[0] if gc_cmds else "gc 0"
                        await self.ws.send_log(
                            f"[{case.case_id}] [持久Shell] 发送 {gc_cmd}", "info")
                        await _send_cmd(gc_cmd)

                        # -s --writeFrames 模式：拍完指定帧数后进程自动退出
                        # 等待 shell 提示符重新出现（说明 nvsipl 进程已退出）
                        capture_output = await _read_shell(
                            60.0, stop_pattern=r"[#\$>]\s*$")
                        combined_outputs.append(nvsipl_init + capture_output)

                        await self.ws.send_log(
                            f"[{case.case_id}] [持久Shell] [{step_idx+1}] nvsipl 执行完成", "info")

                    else:
                        # 普通 shell 命令（export 等）
                        await self.ws.send_log(
                            f"[{case.case_id}] [持久Shell] [{step_idx+1}] 执行: {shell_cmd}", "info")
                        last_cmd = shell_cmd
                        await _send_cmd(shell_cmd)
                        # 等待命令完成（提示符出现）
                        cmd_output = await _read_shell(10.0, stop_pattern=r"[#\$>]\s*$")
                        combined_outputs.append(cmd_output)

        except Exception as e:
            await self.ws.send_log(
                f"[{case.case_id}] [持久Shell] 执行异常: {type(e).__name__}: {e}", "error")
            combined_outputs.append(f"持久Shell异常: {e}")
            last_exit_code = -1
        finally:
            # 关闭 PTY channel
            try:
                await loop.run_in_executor(None, channel.close)
            except Exception:
                pass

        return combined_outputs, last_exit_code, last_cmd

    @staticmethod
    def _normalize_quotes(cmd: str) -> str:
        """Replace Chinese/fullwidth quotes with ASCII equivalents."""
        cmd = cmd.replace('\u201c', '"').replace('\u201d', '"')
        cmd = cmd.replace('\u2018', "'").replace('\u2019', "'")
        cmd = cmd.replace('\uff02', '"')
        cmd = cmd.replace('\u300c', '"').replace('\u300d', '"')
        return cmd

    @staticmethod
    def _build_evidence_summary(result, passed: bool) -> str:
        """\u4ece\u6267\u884c\u7ed3\u679c\u548c\u5339\u914d\u539f\u56e0\u4e2d\u63d0\u53d6\u5173\u952e\u8bc1\u636e\u6458\u8981\u3002

        \u751f\u6210\u683c\u5f0f: [Pass/Fail] \u5224\u5b9a\u4f9d\u636e | \u5173\u952e\u8f93\u51fa\u884c
        \u7528\u4e8e\u524d\u7aef\u5c55\u793a\u548c Excel \u56de\u5199\uff0c\u4f7f\u5224\u5b9a\u4f9d\u636e\u4e00\u76ee\u4e86\u7136\u3002
        """
        import re

        status_label = "[Pass]" if passed else "[Fail]"
        actual = result.actual_output or ""
        reason = result.match_reason or ""
        error_msg = result.error_msg or ""

        # --- Part 1: \u5224\u5b9a\u4f9d\u636e\uff08\u6765\u81ea match_reason\uff09---
        reason_summary = ""
        if not passed and error_msg:
            # \u6267\u884c\u5f02\u5e38\u76f4\u63a5\u7528 error_msg
            reason_summary = error_msg[:150]
        elif reason:
            reason_items = reason.split("; ")
            key_parts = []
            for item in reason_items:
                # \u8df3\u8fc7\u5197\u4f59/\u65e0\u4fe1\u606f\u91cf\u6761\u76ee
                if "\u8df3\u8fc7" in item or "\u5df2\u7531\u5e27\u7387" in item:
                    continue
                if passed and ("OK" in item or "\u65e0\u4e25\u91cd\u9519\u8bef" in item):
                    continue
                # \u4fdd\u7559\u5e27\u540c\u6b65\u7ed3\u679c
                if "\u5e27\u540c\u6b65\u68c0\u6d4b" in item:
                    key_parts.append(item)
                # \u4fdd\u7559\u5e27\u7387\u76f8\u5173
                elif "\u5e27\u7387" in item or "Frame rate" in item or "fps" in item.lower():
                    key_parts.append(item)
                # \u4fdd\u7559\u5339\u914d\u7387
                elif "\u5339\u914d\u7387" in item:
                    key_parts.append(item)
                # \u4fdd\u7559\u9519\u8bef\u4fe1\u606f
                elif "\u9519\u8bef" in item or "Fail" in item or "\u975e0" in item:
                    key_parts.append(item)
                # \u4fdd\u7559\u5339\u914d\u6210\u529f\u7684\u5173\u952e\u5b57\u5217\u8868\uff08Pass \u65f6\u6709\u610f\u4e49\uff09
                elif passed and "\u5339\u914d\u6210\u529f" in item:
                    key_parts.append(item)
            reason_summary = " | ".join(key_parts[:3]) if key_parts else reason_items[0][:100]

        # --- Part 2: \u5173\u952e\u8f93\u51fa\u884c\uff08\u6765\u81ea actual_output\uff09---
        evidence_lines = []
        interactive_output_lines = []
        if actual:
            output_lines = actual.split('\n')

            # \u68c0\u6d4b\u662f\u5426\u542b nvsipl \u4ea4\u4e92\u547d\u4ee4\u7684\u6709\u6548\u8f93\u51fa\uff08ed/al/ro/cm/th/df \u67e5\u8be2\u7ed3\u679c\uff09
            # \u8fd9\u7c7b\u8f93\u51fa\u672c\u8eab\u5c31\u662f\u5b8c\u6574\u8bc1\u636e\uff0c\u5e94\u5c3d\u91cf\u4fdd\u7559
            in_interactive_block = False
            for line in output_lines:
                stripped = line.strip()
                if not stripped:
                    continue
                # \u8df3\u8fc7 PTY \u566a\u97f3\u884c
                if stripped.startswith("Enter '") or "Frame rate" in stripped:
                    in_interactive_block = False
                    continue
                if stripped in ('-', 'Output', 'gc 0', 'q'):
                    continue
                # \u4fdd\u7559\u8f6e\u6b21\u6807\u8bb0
                if re.match(r'^=+\s*\u7b2c\d+/\d+\u8f6e\s*=+$', stripped):
                    interactive_output_lines.append(stripped)
                    continue
                # \u8bc6\u522b\u4ea4\u4e92\u547d\u4ee4\u8f93\u51fa\u7684\u8d77\u59cb\u7279\u5f81
                if re.search(
                    r'(belongs to|Camera Intrinsic|Serial Number|Module Name|'
                    r'eeprom|EEPROM|Readout|readout_time|'
                    r'Image Width|Image Height|Polynom|RMS ERROR|MAE ERROR|'
                    r'Horizontal|Vertical|active_[wh]|active\s*=|'
                    r'HW Version|OEM Part|Linear\s+[CDE]\b|'
                    r'Center [XY]|Start [XY]|Spec/Meas|Model\s*=|'
                    r'Sensor ID\s+\d+|temperature|histogram|'
                    r'fault|detect|link|Link)',
                    stripped, re.IGNORECASE
                ):
                    in_interactive_block = True
                    interactive_output_lines.append(stripped)
                elif in_interactive_block:
                    # \u7ee7\u7eed\u6536\u96c6\u540c\u4e00\u5757\u5185\u5bb9
                    interactive_output_lines.append(stripped)

            if interactive_output_lines:
                # \u6709\u4ea4\u4e92\u547d\u4ee4\u7684\u6709\u6548\u8f93\u51fa \u2192 \u76f4\u63a5\u4f5c\u4e3a\u8bc1\u636e
                # \u591a\u8f6e\u65f6\u4fdd\u7559\u66f4\u591a\u884c\u786e\u4fdd\u6bcf\u8f6e\u6570\u636e\u90fd\u5305\u542b
                has_multi_round = any('\u8f6e' in l for l in interactive_output_lines[:5])
                max_evidence = 100 if has_multi_round else 50
                evidence_lines = interactive_output_lines[:max_evidence]
            elif passed:
                # Pass: \u63d0\u53d6\u5e27\u7387\u884c\u3001\u50cf\u7d20\u4fe1\u606f\u3001\u6210\u529f\u6807\u5fd7
                for line in output_lines:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    if re.search(r'Frame rate \(fps\):\s+[\d.]+', stripped):
                        evidence_lines.append(stripped)
                    elif re.search(r'(Vertical|horizontal|active_[wh]|active\s*=|pixel)',
                                   stripped, re.IGNORECASE):
                        evidence_lines.append(stripped)
                    elif re.search(r'\.(raw|yuv|png|jpg|bmp|h264|hevc)\b', stripped):
                        evidence_lines.append(stripped)
                    elif re.search(r'(SUCCESS|success|PASSED|streaming started)', stripped):
                        evidence_lines.append(stripped)
                    if len(evidence_lines) >= 5:
                        break
                # \u5982\u679c\u6ca1\u63d0\u53d6\u5230\u7279\u5f81\u884c\uff0c\u53d6\u8f93\u51fa\u7684\u524d\u51e0\u884c\u4f5c\u4e3a\u8bc1\u636e
                if not evidence_lines:
                    for line in output_lines[:10]:
                        stripped = line.strip()
                        if stripped and not stripped.startswith("Enter '"):
                            evidence_lines.append(stripped)
                            if len(evidence_lines) >= 5:
                                break
            else:
                # Fail: \u63d0\u53d6\u9519\u8bef\u884c\u53ca\u4e0a\u4e0b\u6587
                for idx, line in enumerate(output_lines):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    if re.search(r'(ERROR|FAIL|failed|timeout|crash|abort|\u5f02\u5e38|\u5931\u8d25)',
                                 stripped, re.IGNORECASE):
                        evidence_lines.append(stripped)
                        # \u8ffd\u52a0\u4e0b\u4e00\u884c\u4f5c\u4e3a\u4e0a\u4e0b\u6587
                        if idx + 1 < len(output_lines) and output_lines[idx + 1].strip():
                            evidence_lines.append(output_lines[idx + 1].strip())
                        if len(evidence_lines) >= 6:
                            break
                # \u5982\u679c\u6ca1\u627e\u5230\u660e\u663e\u9519\u8bef\u884c\uff0c\u53d6\u8f93\u51fa\u5c3e\u90e8\u51e0\u884c
                if not evidence_lines:
                    tail_lines = [l.strip() for l in output_lines[-10:] if l.strip()]
                    evidence_lines = tail_lines[-5:]

        # --- \u7ec4\u88c5 ---
        parts = []
        # \u5982\u679c\u6709\u4ea4\u4e92\u547d\u4ee4\u6709\u6548\u8f93\u51fa\uff0creason_summary \u4e2d\u4ec5\u542b"\u8fd4\u56de\u7801OK"\u8fd9\u79cd\u901a\u7528\u4fe1\u606f\u5c31\u7701\u7565
        if reason_summary:
            is_generic_reason = all(
                k in reason_summary for k in ['OK']
            ) and '\u5e27' not in reason_summary and '\u5339\u914d' not in reason_summary
            if not (interactive_output_lines and is_generic_reason):
                parts.append(reason_summary)
        if evidence_lines:
            parts.append("\n".join(evidence_lines))

        if parts:
            summary = f"{status_label} {' | '.join(parts)}"
        else:
            # \u515c\u5e95
            fallback = actual[:300] if actual else reason[:300]
            summary = f"{status_label} {fallback}"

        # \u5bf9\u4e8e\u542b\u6709\u4ea4\u4e92\u547d\u4ee4\u6709\u6548\u8f93\u51fa\u7684\u7528\u4f8b\uff0c\u5141\u8bb8\u66f4\u957f\u7684\u6458\u8981\uff1b\u591a\u8f6e\u65f6\u66f4\u5927
        has_multi_round = any('\u8f6e' in l for l in interactive_output_lines[:5])
        if has_multi_round:
            max_len = 2000
        elif interactive_output_lines:
            max_len = 1000
        else:
            max_len = 500
        return summary[:max_len]

    def _apply_nito_override(self, cmd: str) -> str:
        """\u5982\u679c\u542f\u7528\u4e86 nito \u8def\u5f84\u8986\u76d6\uff0c\u66ff\u6362\u547d\u4ee4\u4e2d\u7684 --nito \u53c2\u6570\u8def\u5f84\u3002

        \u66ff\u6362\u89c4\u5219\uff1a
        - --nito ./ \u2192 --nito /configured/path
        - --nito ./some/relative \u2192 --nito /configured/path
        - --nito /old/path \u2192 --nito /configured/path
        """
        import re
        if not self.workspace:
            return cmd
        if not getattr(self.workspace, "nito_override_enabled", False):
            return cmd
        nito_path = getattr(self.workspace, "nito_override_path", "")
        if not nito_path:
            return cmd
        # \u66ff\u6362 --nito \u540e\u9762\u7684\u8def\u5f84\u53c2\u6570
        cmd = re.sub(r'--nito\s+\S+', f'--nito {nito_path}', cmd)
        return cmd

    def _apply_image_path_override(self, cmd: str) -> str:
        """如果启用了 image 存储路径，替换命令中 -f 参数后的路径。

        识别 -f ./path/ 或 -f /some/path/ 并替换为配置的 image 存储路径。
        """
        import re
        if not self.workspace:
            return cmd
        if not getattr(self.workspace, "image_storage_enabled", False):
            return cmd
        image_path = getattr(self.workspace, "image_storage_path", "")
        if not image_path:
            return cmd
        # 确保路径以 / 结尾
        if not image_path.endswith("/"):
            image_path += "/"
        # 替换 -f 后面的路径参数
        cmd = re.sub(r'-f\s+\S+', f'-f {image_path}', cmd)
        return cmd

    @staticmethod
    def _inject_capture_name(cmd: str, capture_idx: int, names: list) -> str:
        """在 nvsipl -f 路径末尾补充文件名前缀以区分多次拍照。

        规则：
        - -f /path/dir/  (以 / 结尾，无文件名前缀) → -f /path/dir/default 或 -f /path/dir/rotate
        - -f /path/dir/prefix (已有前缀，不以 / 结尾) → 不修改
        - 无 -f 参数 → 不修改
        """
        import re
        m = re.search(r'-f\s+(\S+)', cmd)
        if not m:
            return cmd
        f_path = m.group(1)
        # 仅当路径以 / 结尾（无前缀）时补充
        if f_path.endswith('/'):
            name = names[capture_idx] if capture_idx < len(names) else f"shot{capture_idx + 1}"
            new_path = f_path + name
            cmd = cmd[:m.start(1)] + new_path + cmd[m.end(1):]
        return cmd

    async def _ensure_image_storage_path(self, case_id: str):
        """执行前检查板端 image 存储路径是否存在，不存在则创建。"""
        if not self.workspace:
            return
        if not getattr(self.workspace, "image_storage_enabled", False):
            return
        image_path = getattr(self.workspace, "image_storage_path", "")
        if not image_path:
            return
        try:
            mkdir_cmd = f"mkdir -p {image_path}"
            exit_code, _, _ = await self._ssh_execute(mkdir_cmd, timeout=10)
            if exit_code == 0:
                await self.ws.send_log(
                    f"[{case_id}] 板端 image 存储路径已就绪: {image_path}", "info")
            else:
                await self.ws.send_log(
                    f"[{case_id}] 创建 image 路径失败，尝试 sudo", "warning")
                sudo_mkdir = f"echo {self._get_sudo_password()} | sudo -S mkdir -p {image_path}"
                await self._ssh_execute(sudo_mkdir, timeout=10)
        except Exception as e:
            await self.ws.send_log(f"[{case_id}] 检查 image 路径异常: {e}", "warning")

    def _get_sudo_password(self) -> str:
        """获取 sudo 密码。"""
        import shlex
        if self.ssh and hasattr(self.ssh, 'config'):
            pwd = getattr(self.ssh.config, 'target_password', '') or getattr(self.ssh.config, 'password', '')
            return shlex.quote(pwd)
        return "''"

    def _apply_sudo_password(self, cmd: str) -> str:
        """对含 sudo 的命令自动注入密码。

        策略：
        - 简单命令（无管道到 sudo 前）：echo pwd | sudo -S <cmd>
        - 管道命令（如 { ... } | sudo <cmd>）：用 sudo -S sh -c 包裹整体
        """
        import re
        import shlex
        if not re.search(r'\bsudo\b', cmd):
            return cmd
        password = ""
        if self.ssh and hasattr(self.ssh, 'config'):
            config = self.ssh.config
            password = getattr(config, 'target_password', '') or getattr(config, 'password', '')
        if not password:
            return cmd
        escaped_pwd = shlex.quote(password)

        # 检测是否为「输入管道 | sudo cmd」的形式（如 { echo ...; } | sudo nvsipl）
        pipe_to_sudo = re.match(r'^(.+\|)\s*sudo\s+(.+)$', cmd)
        if pipe_to_sudo:
            # 管道形式：把 sudo 替换为 sudo -S，并在管道前通过子 shell 注入密码
            # 用 "echo pwd | sudo -S -v" 先缓存凭证，然后用 sudo -n 执行
            prefix = f"echo {escaped_pwd} | sudo -S -v 2>/dev/null; "
            cmd = re.sub(r'\bsudo\s+', 'sudo -n ', cmd)
            return prefix + cmd

        # 普通命令：echo pwd | sudo -S <rest>
        cmd = re.sub(r'\bsudo\s+', f'echo {escaped_pwd} | sudo -S ', cmd)
        return cmd

    @staticmethod
    def _extract_key_output_lines(output: str, max_lines: int = 15) -> str:
        """Extract key diagnostic lines from command output."""
        import re as _re
        if not output:
            return ""
        key_patterns = [
            r"Frame rate",
            r"SUCCESS",
            r"FAIL",
            r"Error|error|ERROR",
            r"Segmentation fault",
            r"terminate called",
            r"Frame captured",
            r"Frame drops:\s*[1-9]",
            r"Init.*current local time",
            r"Deinit.*current local time",
            r"Cannot bind",
            r"\.raw|\.yuv|\.jpg|\.png",
            r"[Rr]eadout",
            r"[Aa]ction\s*[Ll]ine",
            r"active_w|active_h|pixel",
            r"Disable Link|Enable Link",
        ]
        lines = output.split("\n")
        key_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            for pat in key_patterns:
                if _re.search(pat, stripped, _re.IGNORECASE):
                    key_lines.append(stripped)
                    break
            if len(key_lines) >= max_lines:
                key_lines.append(f"... (total {len(lines)} lines, showing {max_lines} key lines)")
                break
        return "\n".join(key_lines) if key_lines else output[-300:].strip()

    async def _ssh_execute(self, cmd: str, timeout: int = 60, force_tty: bool = False) -> tuple:
        """把同步阻塞的 SSH 调用放到线程池，避免卡住事件循环。

        如果执行被 abort（用户停止），返回 (-1, '', 'aborted by user')。
        """
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(
                None, lambda: self.ssh.execute(cmd, timeout=timeout, force_tty=force_tty),
            )
        except Exception as e:
            if self._stop:
                return (-1, "", "执行被用户中止")
            raise

    async def _run_prerequisites(self, prereq: str) -> bool:
        """执行前置条件。

        支持 ``MANUAL_CONFIRM <说明>`` 触发人工确认，其余按命令执行。
        兼容用 ``;`` 分隔的多条命令。
        """
        for cmd in prereq.split(";"):
            cmd = cmd.strip()
            if not cmd:
                continue
            if cmd.startswith(CommandParser.MANUAL_CONFIRM_PREFIX):
                desc = cmd.replace(CommandParser.MANUAL_CONFIRM_PREFIX, "").strip()
                ok = await self.ws.request_manual_confirm(desc)
                if not ok:
                    return False
            else:
                await self.ws.send_log(f"前置条件执行: {cmd}", "info")
                exit_code, _, _ = await self._ssh_execute(cmd, timeout=60)
                if exit_code != 0:
                    await self.ws.send_log(f"前置条件失败: {cmd} (exit={exit_code})", "error")
                    return False
        return True

    async def _check_remote_files(self, case_id: str, work_dir: str, file_ext: str) -> str:
        """在板端查找最近 3 分钟内生成的指定后缀文件。

        流程：
        1. find 查找生成的文件
        2. 如果启用了图片下载：SCP 下载到 PC 本地（按 case_id 分目录）
        3. 下载完成后删除板端文件（防止后续用例误判）
        4. 返回文件列表文本供关键字匹配
        """
        try:
            find_cmd = f"find {work_dir} -maxdepth 1 -name '*{file_ext}' -mmin -3 2>/dev/null | head -20"
            exit_code, stdout, _ = await self._ssh_execute(find_cmd, timeout=15)
            files = [f.strip() for f in stdout.strip().split('\n') if f.strip()]
            if files:
                await self.ws.send_log(
                    f"[{case_id}] 检测到生成文件 ({len(files)} 个): {files[:5]}", "info")

                # 下载到 PC + 删除板端文件
                await self._download_and_cleanup_files(case_id, files, work_dir)

                return "\n".join(files)
            else:
                await self.ws.send_log(
                    f"[{case_id}] 未检测到 {file_ext} 文件（{work_dir}）", "warning")
                return ""
        except Exception as e:
            await self.ws.send_log(f"[{case_id}] 检查文件异常: {e}", "warning")
            return ""

    async def _download_and_cleanup_files(self, case_id: str, remote_files: list, work_dir: str):
        """将板端生成的图片文件 SCP 下载到 PC，然后删除板端文件。"""
        if not self.workspace:
            return
        if not getattr(self.workspace, "image_download_enabled", False):
            return
        download_path = getattr(self.workspace, "image_download_path", "")
        if not download_path:
            return

        import subprocess
        import shlex
        import tempfile

        # 按 case_id 创建本地子目录
        local_dir = os.path.join(download_path, case_id)
        os.makedirs(local_dir, exist_ok=True)

        # 获取 SSH 配置
        config = self.ssh.config if self.ssh and hasattr(self.ssh, 'config') else None
        if not config:
            return

        password = getattr(config, 'target_password', '') or getattr(config, 'password', '')

        # SCP 下载每个文件
        downloaded = 0
        askpass_dir = tempfile.mkdtemp(prefix="scp_dl_")
        askpass_path = os.path.join(askpass_dir, "askpass.sh")
        try:
            with open(askpass_path, "w") as f:
                f.write("#!/bin/sh\n")
                f.write(f"echo {shlex.quote(password)}\n")
            os.chmod(askpass_path, 0o700)

            env = os.environ.copy()
            env["DISPLAY"] = env.get("DISPLAY", ":999")
            env["SSH_ASKPASS"] = askpass_path
            env["SSH_ASKPASS_REQUIRE"] = "force"

            for remote_file in remote_files:
                filename = os.path.basename(remote_file)
                local_file = os.path.join(local_dir, filename)
                scp_cmd = [
                    "scp", "-o", "StrictHostKeyChecking=no",
                    "-o", "UserKnownHostsFile=/dev/null",
                    "-P", str(config.port),
                    f"{config.username}@{config.host}:{remote_file}",
                    local_file,
                ]
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, lambda cmd=scp_cmd: subprocess.run(
                    cmd, capture_output=True, text=True, timeout=60,
                    env=env, start_new_session=True,
                ))
                if result.returncode == 0:
                    downloaded += 1
        finally:
            try:
                os.remove(askpass_path)
            except Exception:
                pass
            try:
                os.rmdir(askpass_dir)
            except Exception:
                pass

        if downloaded > 0:
            await self.ws.send_log(
                f"[{case_id}] 已下载 {downloaded} 个文件到 PC: {local_dir}", "info")

            # 删除板端文件（防止后续用例误判）
            rm_files = " ".join(shlex.quote(f) for f in remote_files)
            rm_cmd = f"rm -f {rm_files}"
            await self._ssh_execute(rm_cmd, timeout=10)
            await self.ws.send_log(
                f"[{case_id}] 已清理板端文件 ({len(remote_files)} 个)", "info")
        else:
            await self.ws.send_log(
                f"[{case_id}] 文件下载失败，未清理板端文件", "warning")

    @staticmethod
    def _merge_nvsipl_interactive(steps) -> list:
        """合并 nvsipl_camera 命令与后续的交互输入步骤为管道命令。

        场景1（紧邻）：
          步骤1：执行命令：./nvsipl_camera -c xxx -m 0
          步骤2：输入 dl 8 / 输入 el 11
          → printf '%s\\n' 'dl 8' 'el 11' | ./nvsipl_camera ...

        场景2（分阶段，中间有观察/等待步骤）：
          步骤1：起流 nvsipl_camera ...
          步骤2：等待观测fps（skip）
          步骤3：执行 dl 0, dl 2...（nvsipl_input）
          步骤4：观察fps变0（skip）
          步骤5：执行 elr 0, elr 2...（nvsipl_input）
          步骤6：观察fps恢复（skip）
          → 收集所有 nvsipl_input，合并为管道命令 + 增加 sleep 间隔
        """
        from app.core.command_parser import CommandParser, CommandStep

        merged = []
        i = 0
        while i < len(steps):
            step = steps[i]
            if step.kind == "command" and CommandParser.is_nvsipl_camera_command(step.command):
                # 阻塞型 nvsipl（无 -r）不合并管道——保留原样，由并行模式处理
                # 后续的 nvsipl_input 也保留（并行模式会用它们做 gc 注入）
                if CommandParser.is_blocking_nvsipl(step.command):
                    merged.append(step)
                    i += 1
                    # 保留后续所有步骤（nvsipl_input / command / repeat / skip 等）
                    # 它们将由 _execute_parallel_fault_test 按原始顺序交错执行
                    while i < len(steps):
                        if steps[i].kind in ("nvsipl_input", "command", "repeat",
                                              "repeat_stream", "skip", "manual"):
                            merged.append(steps[i])
                            i += 1
                        else:
                            break
                    continue
                # 非阻塞型：向后扫描收集 nvsipl_input（跳过中间的 skip 步骤）
                subcmd_groups = []
                j = i + 1
                while j < len(steps):
                    if steps[j].kind == "nvsipl_input":
                        subcmd_groups.append(steps[j].command.split(";"))
                        j += 1
                    elif steps[j].kind == "skip":
                        j += 1
                    else:
                        break
                if subcmd_groups:
                    # 将多组子命令合并，组间加 sleep 让 nvsipl 有时间响应
                    all_subcmds = []
                    # 初始等待：让 nvsipl 完成初始化并开始出帧
                    all_subcmds.append("sleep 8")
                    # 自动注入 gc 命令：仅当步骤中没有显式 gc 命令时
                    all_flat = [cmd for group in subcmd_groups for cmd in group]
                    has_explicit_gc = any(c.lower().startswith("gc") for c in all_flat)
                    if not has_explicit_gc:
                        gc_cmds = self._generate_gc_commands(step.command)
                        if gc_cmds:
                            all_subcmds.extend(gc_cmds)
                            all_subcmds.append("sleep 3")
                    for group_idx, group in enumerate(subcmd_groups):
                        all_subcmds.extend(group)
                        if group_idx < len(subcmd_groups) - 1:
                            # 组间等待：让 sensor 关闭/恢复并输出帧率
                            all_subcmds.append("sleep 10")
                    # 最后等待：让所有 sensor 完全恢复并输出稳定帧率
                    all_subcmds.append("sleep 15")
                    all_subcmds.append("q")
                    piped_cmd = CommandParser.build_nvsipl_piped_command(step.command, all_subcmds)
                    merged.append(CommandStep(
                        kind="command",
                        command=piped_cmd,
                        description=f"{step.description} + 交互: {len(all_subcmds)} 条子命令",
                        terminal=step.terminal,
                    ))
                    i = j
                    continue
                else:
                    merged.append(step)
                    i += 1
                    continue
            # 独立的 nvsipl_input 无前置 nvsipl 命令时，记录跳过
            if step.kind == "nvsipl_input":
                merged.append(CommandStep(
                    kind="skip",
                    description=f"交互输入无前置 nvsipl_camera 命令（已跳过）：{step.command}",
                ))
                i += 1
                continue
            merged.append(step)
            i += 1
        return merged

    @staticmethod
    def _find_blocking_nvsipl_index(steps) -> int:
        """查找步骤列表中第一个阻塞型 nvsipl_camera 命令的索引。"""
        for i, step in enumerate(steps):
            if step.kind == "command" and CommandParser.is_blocking_nvsipl(step.command):
                return i
        return None

    async def _execute_parallel_fault_test(self, case, steps, blocking_idx, work_dir):
        """并行执行阻塞型 nvsipl_camera 交互测试（PTY channel 方案）。

        按步骤原始顺序交错执行：
        - nvsipl_input → 注入 PTY channel（gc/df/al/ro/q 等交互命令）
        - command（非 nvsipl）→ 通过独立 SSH channel 执行（故障注入脚本等）
        - repeat → 循环回指定步骤范围

        支持场景：
        1. nvsipl + gc + al/ro 查询
        2. nvsipl + 故障注入(shell) + df 查看(PTY) + q 退出 + 重复
        3. nvsipl + dl/elr 链路操作
        4. 反复起流 N 次压力测试
        5. showmetadata 帧同步检测

        返回: (combined_outputs, last_exit_code, last_cmd)
        """
        import re
        import time as _time

        combined_outputs = []
        last_exit_code = 0

        # 获取阻塞命令
        blocking_step = steps[blocking_idx]
        nvsipl_cmd = self._normalize_quotes(blocking_step.command)
        nvsipl_cmd = self._apply_nito_override(nvsipl_cmd)
        nvsipl_cmd = self._apply_image_path_override(nvsipl_cmd)
        nvsipl_cmd = self._apply_sudo_password(nvsipl_cmd)

        cd_prefix = f"cd {work_dir} && " if work_dir else ""
        full_cmd = f"{cd_prefix}{nvsipl_cmd}"
        last_cmd = nvsipl_cmd

        await self.ws.send_log(f"[{case.case_id}] [并行模式] PTY启动: {nvsipl_cmd}", "info")

        # === 解析重复指令 ===
        repeat_count = 1
        repeat_range = None
        is_repeat_stream = False
        for s in steps:
            if s.kind == "repeat_stream":
                repeat_count = int(s.command) if s.command.isdigit() else 10
                is_repeat_stream = True
                await self.ws.send_log(
                    f"[{case.case_id}] [并行模式] 检测到反复起流指令: 共{repeat_count}次", "info")
                break
            if s.kind == "repeat":
                m = re.match(r'(\d+)-(\d+)', s.command)
                if m:
                    repeat_range = (int(m.group(1)), int(m.group(2)))
                    repeat_count = 2  # "重复" = 再执行一次，共 2 轮
                    await self.ws.send_log(
                        f"[{case.case_id}] [并行模式] 检测到重复指令: 步骤{repeat_range[0]}-{repeat_range[1]}，共{repeat_count}轮", "info")
                    break

        # === 构建每轮执行的步骤序列 ===
        # 第一轮：blocking_idx 之后的全部非 repeat/repeat_stream 步骤
        all_subsequent = [s for s in steps[blocking_idx + 1:]
                          if s.kind not in ("repeat", "repeat_stream")]
        # 有 repeat 指令时，重复轮只执行 repeat 范围内的步骤
        if repeat_range:
            start_num, end_num = repeat_range
            repeat_round_steps = [s for s in steps
                                  if start_num <= s.step_num <= end_num
                                  and s.kind not in ("repeat", "repeat_stream")]
        else:
            repeat_round_steps = all_subsequent

        # 反复起流模式特殊处理：每轮只需 auto gc → 检测fps → q
        if is_repeat_stream:
            from app.core.command_parser import CommandStep
            auto_gc = self._generate_gc_commands(nvsipl_cmd)
            gc_cmd_str = auto_gc[0].lower() if auto_gc else "gc 0"
            repeat_round_steps = [
                CommandStep(kind="nvsipl_input", command=gc_cmd_str, description="auto gc"),
                CommandStep(kind="nvsipl_input", command="q", description="auto q"),
            ]
            all_subsequent = repeat_round_steps
            await self.ws.send_log(
                f"[{case.case_id}] [并行模式] 反复起流模式: 每轮自动注入 [{gc_cmd_str}, q]", "info")

        # 检测每轮步骤中是否包含 q 命令
        def _steps_have_q(step_list):
            for s in step_list:
                if s.kind == "nvsipl_input":
                    for c in s.command.split(";"):
                        if c.strip().lower() == "q":
                            return True
            return False

        has_q_in_round = _steps_have_q(repeat_round_steps)

        # 检测是否有显式 gc 命令
        def _steps_have_gc(step_list):
            for s in step_list:
                if s.kind == "nvsipl_input":
                    for c in s.command.split(";"):
                        if c.strip().lower().startswith("gc"):
                            return True
            return False

        await self.ws.send_log(
            f"[{case.case_id}] [并行模式] 第一轮步骤: "
            f"{[(s.kind, s.command[:40]) for s in all_subsequent]}", "info")
        if repeat_range:
            await self.ws.send_log(
                f"[{case.case_id}] [并行模式] 重复轮步骤: "
                f"{[(s.kind, s.command[:40]) for s in repeat_round_steps]}", "info")

        loop = asyncio.get_event_loop()
        all_output = ""

        # === 多轮执行主循环 ===
        for round_idx in range(repeat_count):
            if self._stop:
                break

            round_label = f"第{round_idx + 1}/{repeat_count}轮"
            await self.ws.send_log(
                f"[{case.case_id}] [并行模式] === {round_label} 开始 ===", "info")

            if repeat_count > 1:
                combined_outputs.append(f"\n===== {round_label} =====")

            round_failed = False
            round_output_start = len(all_output)

            # 本轮要执行的步骤：第一轮用 all_subsequent，后续轮用 repeat_round_steps
            current_round_steps = all_subsequent if round_idx == 0 else repeat_round_steps

            # Step 1: 打开 PTY channel
            channel = await loop.run_in_executor(
                None, lambda: self.ssh.open_interactive_channel(full_cmd, timeout=180)
            )

            async def _read_channel(timeout_sec: float, stop_pattern: str = None) -> str:
                """异步读取 channel 输出，直到超时或匹配到 stop_pattern。"""
                nonlocal all_output
                buf = ""
                start = _time.time()
                while _time.time() - start < timeout_sec:
                    if self._stop:
                        break
                    try:
                        ready = await loop.run_in_executor(None, channel.recv_ready)
                    except (OSError, EOFError):
                        break
                    if ready:
                        try:
                            data = await loop.run_in_executor(None, lambda: channel.recv(65536))
                        except (OSError, EOFError):
                            break
                        text = data.decode("utf-8", errors="replace")
                        buf += text
                        all_output += text
                        if stop_pattern and re.search(stop_pattern, buf, re.IGNORECASE):
                            break
                    else:
                        await asyncio.sleep(0.3)
                return buf

            async def _send_pty(cmd_text: str) -> bool:
                """向 PTY channel 发送命令，返回是否成功。"""
                try:
                    await loop.run_in_executor(None, lambda c=cmd_text: channel.send(c + "\n"))
                    return True
                except (OSError, EOFError, Exception) as err:
                    await self.ws.send_log(
                        f"[{case.case_id}] [并行模式] [{round_label}] "
                        f"发送 '{cmd_text}' 失败: {type(err).__name__}: {err} "
                        f"（nvsipl 可能已异常退出）", "error")
                    try:
                        residual = await _read_channel(2.0)
                        if residual.strip():
                            combined_outputs.append(residual)
                    except Exception:
                        pass
                    combined_outputs.append(f"[PTY异常] 发送 '{cmd_text}' 时通道已关闭")
                    return False

            try:
                # Step 2: 等待 nvsipl 初始化完成
                await self.ws.send_log(
                    f"[{case.case_id}] [并行模式] [{round_label}] 等待 nvsipl 初始化...", "info")
                init_output = await _read_channel(30.0, stop_pattern=r"Enter\s+'gc")

                if "ERROR" in init_output or "failed" in init_output.lower():
                    await self.ws.send_log(
                        f"[{case.case_id}] [并行模式] [{round_label}] nvsipl 启动失败: {init_output[-200:]}", "error")
                    combined_outputs.append(init_output)
                    try:
                        await loop.run_in_executor(None, channel.close)
                    except Exception:
                        pass
                    if round_idx == 0:
                        return combined_outputs, 1, full_cmd
                    if is_repeat_stream:
                        combined_outputs.append(f"[第{round_idx+1}次起流失败] nvsipl 启动失败")
                        last_exit_code = -1
                        round_failed = True
                    break

                if not re.search(r"Enter\s+'gc", init_output):
                    await self.ws.send_log(
                        f"[{case.case_id}] [并行模式] [{round_label}] nvsipl 初始化超时（30s），继续尝试", "warning")
                    if is_repeat_stream:
                        combined_outputs.append(f"[第{round_idx+1}次起流失败] nvsipl 初始化超时")
                        last_exit_code = -1
                        round_failed = True
                        break

                # Step 2.5: 自动注入 gc 触发出帧（如果当前轮步骤中无显式 gc）
                if not _steps_have_gc(current_round_steps):
                    auto_gc = self._generate_gc_commands(nvsipl_cmd)
                    if auto_gc:
                        gc_cmd_text = auto_gc[0]
                        await self.ws.send_log(
                            f"[{case.case_id}] [并行模式] [{round_label}] 自动注入: {gc_cmd_text}", "info")
                        if await _send_pty(gc_cmd_text):
                            gc_output = await _read_channel(20.0, stop_pattern=r"Frame rate")
                            if "Frame rate" in gc_output:
                                await self.ws.send_log(
                                    f"[{case.case_id}] [并行模式] [{round_label}] 出帧正常", "info")
                                await asyncio.sleep(3)
                                await _read_channel(1.0)
                            else:
                                await self.ws.send_log(
                                    f"[{case.case_id}] [并行模式] [{round_label}] 自动gc后未检测到出帧（20s）", "warning")

                # Step 3: 按步骤顺序交错执行
                q_sent = False
                pty_broken = False

                for step in current_round_steps:
                    if self._stop or pty_broken:
                        break

                    # --- nvsipl 交互命令 → PTY ---
                    if step.kind == "nvsipl_input":
                        for sub_cmd in step.command.split(";"):
                            sub_cmd = sub_cmd.strip().lower()
                            if not sub_cmd or self._stop or pty_broken:
                                continue

                            if not await _send_pty(sub_cmd):
                                pty_broken = True
                                last_exit_code = -1
                                break

                            await self.ws.send_log(
                                f"[{case.case_id}] [并行模式] [{round_label}] 发送: {sub_cmd}", "info")

                            # q 命令：退出 nvsipl
                            if sub_cmd == 'q':
                                q_sent = True
                                await asyncio.sleep(3)
                                quit_output = await _read_channel(5.0, stop_pattern=r"Deinit|quit|exit")
                                if quit_output.strip():
                                    combined_outputs.append(quit_output)
                                break

                            # gc 命令：等待出帧
                            elif sub_cmd.startswith("gc"):
                                gc_output = await _read_channel(20.0, stop_pattern=r"Frame rate")
                                if "Frame rate" in gc_output:
                                    await self.ws.send_log(
                                        f"[{case.case_id}] [并行模式] [{round_label}] 出帧正常", "info")
                                    stabilize_wait = 5 if is_repeat_stream else 3
                                    await asyncio.sleep(stabilize_wait)
                                    extra = await _read_channel(3.0 if is_repeat_stream else 1.0)

                                    # 反复起流模式：验证 fps
                                    if is_repeat_stream:
                                        round_full_output = all_output[round_output_start:]
                                        combined_outputs.append(round_full_output[-2000:] if len(round_full_output) > 2000 else round_full_output)
                                        fps_ok, fps_msg = self._check_round_fps(round_full_output, case.case_id, round_idx + 1)
                                        await self.ws.send_log(
                                            f"[{case.case_id}] [并行模式] [{round_label}] fps检测: {fps_msg}",
                                            "info" if fps_ok else "error")
                                        if not fps_ok:
                                            combined_outputs.append(f"[第{round_idx+1}次起流失败] {fps_msg}")
                                            last_exit_code = -1
                                            round_failed = True
                                            try:
                                                await _send_pty("q")
                                            except Exception:
                                                pass
                                            break
                                else:
                                    await self.ws.send_log(
                                        f"[{case.case_id}] [并行模式] [{round_label}] gc后未检测到出帧（20s）", "warning")
                                    if is_repeat_stream:
                                        combined_outputs.append(f"[第{round_idx+1}次起流失败] gc后20s未检测到帧率输出")
                                        last_exit_code = -1
                                        round_failed = True
                                        try:
                                            await _send_pty("q")
                                        except Exception:
                                            pass
                                        break

                            # sr 命令：设置 ROI
                            elif sub_cmd == 'sr':
                                sr_output = await _read_channel(10.0, stop_pattern=r"ROI values|enter two sets")
                                await self.ws.send_log(
                                    f"[{case.case_id}] [并行模式] [{round_label}] [sr] 等待ROI提示...", "info")
                                roi_pattern = re.compile(r'(\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*\d+)')
                                roi_lines = roi_pattern.findall(sr_output)
                                if len(roi_lines) >= 2:
                                    roi_send_ok = True
                                    for roi_val in roi_lines[:2]:
                                        roi_val = roi_val.strip()
                                        if not await _send_pty(roi_val):
                                            roi_send_ok = False
                                            break
                                        await self.ws.send_log(
                                            f"[{case.case_id}] [并行模式] [{round_label}] [sr] 回填ROI: {roi_val}", "info")
                                        await asyncio.sleep(0.5)
                                    if roi_send_ok:
                                        set_output = await _read_channel(10.0, stop_pattern=r"[Ss]ucesss|[Ss]uccess|set ROI")
                                        sr_full = sr_output + set_output
                                        useful_lines = self._filter_pty_output(sr_full)
                                        if useful_lines:
                                            useful_text = "\n".join(useful_lines)
                                            combined_outputs.append(useful_text)
                                            await self.ws.send_log(
                                                f"[{case.case_id}] [并行模式] [{round_label}] [sr] 有效输出:\n{useful_text}", "info")
                                    elif sr_output.strip():
                                        combined_outputs.append(sr_output)
                                else:
                                    await self.ws.send_log(
                                        f"[{case.case_id}] [并行模式] [{round_label}] [sr] 未检测到ROI示例值", "warning")
                                    if sr_output.strip():
                                        combined_outputs.append(sr_output)

                            # hs 命令：直方图
                            elif sub_cmd == 'hs':
                                hs_output = await _read_channel(10.0, stop_pattern=r"histogramInfo|Histogram|histogram")
                                useful_lines = self._filter_pty_output(hs_output)
                                if useful_lines:
                                    useful_text = "\n".join(useful_lines)
                                    combined_outputs.append(useful_text)
                                    await self.ws.send_log(
                                        f"[{case.case_id}] [并行模式] [{round_label}] [hs] 有效输出:\n{useful_text}", "info")
                                else:
                                    await self.ws.send_log(
                                        f"[{case.case_id}] [并行模式] [{round_label}] [hs] 未检测到直方图输出", "warning")
                                    if hs_output.strip():
                                        combined_outputs.append(hs_output)

                            # al/ro/cm/ed/th/df 查询命令
                            elif sub_cmd in ('al', 'ro', 'cm', 'ed', 'th', 'df'):
                                feature_patterns = {
                                    'al': r'Vertical|horizontal|active_w|active_h|active|pixel|belongs to',
                                    'ro': r'[Rr]eadout.*\d|readout_time',
                                    'cm': r'module|available',
                                    'ed': r'eeprom|data',
                                    'th': r'[Tt]emp|histogram',
                                    'df': r'fault|detect|Fault|Detect|error|Error',
                                }
                                feat_pat = feature_patterns.get(sub_cmd, r'\w+')
                                cmd_output = await _read_channel(10.0, stop_pattern=feat_pat)
                                useful_lines = self._filter_pty_output(cmd_output)
                                if useful_lines:
                                    useful_text = "\n".join(useful_lines)
                                    combined_outputs.append(useful_text)
                                    await self.ws.send_log(
                                        f"[{case.case_id}] [并行模式] [{round_label}] [{sub_cmd}] 有效输出:\n{useful_text}", "info")
                                else:
                                    await self.ws.send_log(
                                        f"[{case.case_id}] [并行模式] [{round_label}] [{sub_cmd}] 未检测到有效输出", "warning")
                                    if cmd_output.strip():
                                        combined_outputs.append(cmd_output)

                            # dl/elr/el 链路操作
                            elif sub_cmd.startswith(("dl", "elr", "el", "les", "lds")):
                                cmd_output = await _read_channel(10.0, stop_pattern=r"Link|link|LED")
                                if cmd_output.strip():
                                    combined_outputs.append(cmd_output)
                                    key_lines = self._extract_key_output_lines(cmd_output, max_lines=10)
                                    if key_lines:
                                        await self.ws.send_log(
                                            f"[{case.case_id}] [并行模式] [{round_label}] [{sub_cmd}] 输出:\n{key_lines}", "info")

                            else:
                                # 其他交互命令
                                await asyncio.sleep(1)
                                extra = await _read_channel(2.0)
                                if extra.strip():
                                    combined_outputs.append(extra)

                        if q_sent or round_failed:
                            break

                    # --- Shell 命令 → 独立 SSH channel ---
                    elif step.kind == "command":
                        shell_cmd = self._normalize_quotes(step.command)
                        shell_cmd = self._apply_nito_override(shell_cmd)
                        shell_cmd = self._apply_image_path_override(shell_cmd)
                        shell_cmd = self._apply_sudo_password(shell_cmd)
                        if work_dir:
                            shell_cmd = f"cd {work_dir} && {shell_cmd}"
                        last_cmd = shell_cmd
                        await self.ws.send_log(
                            f"[{case.case_id}] [并行模式] [{round_label}] SSH执行: {shell_cmd}", "info")

                        exit_code, stdout, stderr = await self._ssh_execute(shell_cmd, timeout=60)
                        last_exit_code = exit_code
                        combined_outputs.append(stdout or "")
                        if stderr:
                            combined_outputs.append(stderr)

                        key_lines = self._extract_key_output_lines(stdout or "")
                        if key_lines:
                            await self.ws.send_log(
                                f"[{case.case_id}] [并行模式] [{round_label}] 命令输出:\n{key_lines}", "info")
                        if exit_code != 0:
                            await self.ws.send_log(
                                f"[{case.case_id}] [并行模式] [{round_label}] 返回码非0: exit_code={exit_code}", "warning")

                        # shell 命令执行后等一下再继续（给板端时间响应）
                        await asyncio.sleep(1)

                    elif step.kind == "skip":
                        await self.ws.send_log(
                            f"[{case.case_id}] [并行模式] [{round_label}] 跳过: {step.description[:60]}", "info")
                        continue

                    elif step.kind == "manual":
                        await self.ws.send_log(
                            f"[{case.case_id}] [并行模式] [{round_label}] 需人工操作: {step.description[:60]}（已跳过）", "warning")
                        continue

                # 步骤执行完后读取残余输出
                if not q_sent and not pty_broken:
                    await asyncio.sleep(2)
                    await _read_channel(2.0)

                # showmetadata 模式：额外等待收集 metadata 输出
                if not (has_q_in_round and round_idx < repeat_count - 1):
                    is_showmetadata = '--showmetadata' in nvsipl_cmd.lower() or '--showmetadata' in nvsipl_cmd
                    if is_showmetadata and not q_sent:
                        await self.ws.send_log(
                            f"[{case.case_id}] [并行模式] [{round_label}] 检测到 --showmetadata，收集帧同步数据(10s)...", "info")
                        metadata_output = await _read_channel(10.0)
                        if metadata_output.strip():
                            combined_outputs.append(metadata_output)
                            cam_count = len(re.findall(r'Camera ID:', metadata_output))
                            await self.ws.send_log(
                                f"[{case.case_id}] [并行模式] [{round_label}] 收集到 {cam_count} 条 Camera 记录", "info")

            finally:
                # 发送 q 退出 nvsipl（如果本轮未通过步骤中的 q 退出），关闭 channel
                try:
                    if not q_sent and not round_failed:
                        await self.ws.send_log(
                            f"[{case.case_id}] [并行模式] [{round_label}] 发送 q 退出 nvsipl", "info")
                        await loop.run_in_executor(None, lambda: channel.send("q\n"))
                        await asyncio.sleep(3)
                        await _read_channel(5.0, stop_pattern=r"Deinit|quit|exit")
                except Exception:
                    pass
                finally:
                    try:
                        await loop.run_in_executor(None, channel.close)
                    except Exception:
                        pass

                await self.ws.send_log(
                    f"[{case.case_id}] [并行模式] === {round_label} 结束 ===", "info")

            # 反复起流模式：本轮失败则中止后续轮次
            if round_failed:
                await self.ws.send_log(
                    f"[{case.case_id}] [并行模式] 第{round_idx+1}次起流失败，中止后续轮次", "error")
                break

            # 轮间等待
            if round_idx < repeat_count - 1:
                await self.ws.send_log(
                    f"[{case.case_id}] [并行模式] 轮间等待 3s...", "info")
                await asyncio.sleep(3)

        # 反复起流模式：全部通过
        if is_repeat_stream and not round_failed and last_exit_code == 0:
            combined_outputs.append(f"[反复起流{repeat_count}次] 全部通过，所有轮次 fps 正常")
            await self.ws.send_log(
                f"[{case.case_id}] [并行模式] 反复起流{repeat_count}次全部通过", "info")

        # 完整输出关键行
        if all_output:
            key_lines = self._extract_key_output_lines(all_output, max_lines=20)
            if key_lines:
                await self.ws.send_log(
                    f"[{case.case_id}] [并行模式] nvsipl 完整输出关键行:\n{key_lines}", "info")
            if not combined_outputs:
                combined_outputs.append(all_output)

        return combined_outputs, last_exit_code, last_cmd

    @staticmethod
    def _filter_pty_output(raw_output: str) -> list:
        """过滤 PTY 输出中的菜单提示行和 fps 行，返回有效输出行列表。"""
        useful = []
        for line in raw_output.split('\n'):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("Enter '") or "Frame rate" in stripped:
                continue
            if stripped in ('-', 'Output'):
                continue
            useful.append(stripped)
        return useful

    async def _match_dl_elr_stages(self, case_id: str, output: str) -> tuple:
        """对 dl/elr 交互式用例做分阶段帧率判定。

        逻辑：
        1. 找到所有 'Disable Link: N' 和 'Enable Link: N'
        2. dl 后帧率：取所有 dl 完成后的帧率块（所有被 dl 的 sensor 应为 0）
        3. elr 后帧率：取最后一个帧率输出块（所有被 elr 的 sensor 应恢复 >24fps）
        """
        import re
        reasons = []
        all_pass = True

        lines = output.split('\n')

        # 收集被 dl 和 elr 的 sensor id
        dl_sensors = set()
        elr_sensors = set()
        for line in lines:
            m = re.search(r'Disable Link:\s*(\d+)', line)
            if m:
                dl_sensors.add(int(m.group(1)))
            m = re.search(r'Enable Link:\s*(\d+)', line)
            if m:
                elr_sensors.add(int(m.group(1)))

        reasons.append(f"检测到 dl sensors: {sorted(dl_sensors)}")
        reasons.append(f"检测到 elr sensors: {sorted(elr_sensors)}")

        # 收集所有帧率输出块（每个 "Output" 标志后面的帧率行）
        fps_blocks = []  # [(start_line_idx, {sensor_id: fps})]
        current_block = None
        for i, line in enumerate(lines):
            if line.strip() == 'Output' or line.strip().startswith('Output'):
                if current_block is not None:
                    fps_blocks.append(current_block)
                current_block = (i, {})
            else:
                m = re.search(r'Sensor(\d+)_Out\d+\s+Frame rate \(fps\):\s+([\d.]+)', line)
                if m and current_block is not None:
                    current_block[1][int(m.group(1))] = float(m.group(2))
        if current_block is not None and current_block[1]:
            fps_blocks.append(current_block)

        # 找关键位置
        last_dl_line = -1
        first_elr_line = len(lines)
        for i, line in enumerate(lines):
            if 'Disable Link' in line:
                last_dl_line = i
        for i, line in enumerate(lines):
            if 'Enable Link' in line:
                first_elr_line = i
                break

        # dl 后帧率：找最后一个 dl 之后、第一个 elr 之前（或之后紧邻）的帧率块
        # 其中所有 dl_sensors 都应为 0
        dl_fps_block = None
        for block_idx, (block_start, block_fps) in enumerate(fps_blocks):
            if block_start > last_dl_line:
                # 检查这个块里 dl_sensors 是否都为 0
                dl_all_zero = all(block_fps.get(sid, -1) == 0 for sid in dl_sensors if sid in block_fps)
                if dl_all_zero and any(sid in block_fps for sid in dl_sensors):
                    dl_fps_block = block_fps
                    break

        if dl_fps_block:
            reasons.append("--- dl 后帧率 ---")
            dl_pass = True
            for sid in sorted(dl_sensors):
                fps = dl_fps_block.get(sid, -1)
                if fps < 0:
                    reasons.append(f"  Sensor{sid}: 未检测到")
                elif fps == 0:
                    reasons.append(f"  Sensor{sid}: fps={fps} [PASS - 已关闭]")
                else:
                    reasons.append(f"  Sensor{sid}: fps={fps} [FAIL - 未关闭]")
                    dl_pass = False
            if dl_pass:
                reasons.append("dl 阶段判定: Pass")
            else:
                reasons.append("dl 阶段判定: Fail")
                all_pass = False
        else:
            reasons.append("dl 后未找到所有目标 sensor 均为 0 的帧率块（可能等待时间不足）")
            await self.ws.send_log(f"[{case_id}] dl 后未检测到全部关闭的帧率块", "warning")

        # elr 后帧率：取最后一个帧率输出块
        # 检查所有 dl_sensors（被关闭的）是否都恢复，而不仅是检测到 Enable Link 的
        if fps_blocks:
            last_block_fps = fps_blocks[-1][1]
            reasons.append("--- elr 后帧率（最终输出） ---")
            elr_pass = True
            # 用 dl_sensors 作为检查对象：所有被关闭的都应恢复
            check_sensors = dl_sensors if dl_sensors else elr_sensors
            for sid in sorted(check_sensors):
                fps = last_block_fps.get(sid, -1)
                if fps < 0:
                    reasons.append(f"  Sensor{sid}: 未检测到帧率输出 [FAIL]")
                    elr_pass = False
                elif fps >= 24:
                    reasons.append(f"  Sensor{sid}: fps={fps} [PASS - 已恢复]")
                else:
                    reasons.append(f"  Sensor{sid}: fps={fps} [FAIL - 未恢复]")
                    elr_pass = False
            # 补充报告 elr 未成功的 sensor（dl 了但没检测到 Enable Link）
            missing_elr = dl_sensors - elr_sensors
            if missing_elr:
                reasons.append(f"  未检测到 Enable Link 的 sensor: {sorted(missing_elr)} (可能硬件断开)")
            if elr_pass:
                reasons.append("elr 阶段判定: Pass")
            else:
                reasons.append("elr 阶段判定: Fail")
                all_pass = False
        else:
            reasons.append("未找到帧率输出块")
            all_pass = False

        if all_pass:
            reasons.append("=== 最终判定: Pass (dl 关闭成功 + elr 恢复成功) ===")
        else:
            reasons.append("=== 最终判定: Fail ===")

        return all_pass, "; ".join(reasons)

    async def _auto_inject_gc(self, case_id: str, pid: str, tmp_log: str, tmp_fifo: str):
        """检测 nvsipl 输出中是否有 gc 提示，如有则注入一条 gc 命令。

        检测标志：输出含 "Enter 'gc" 字样（表示此配置需要 gc 才能正常出帧）。
        注入内容：从日志中检测第一个活跃 sensor ID，发送一条 gc 即可触发全部出帧。
        """
        import re
        try:
            # 检查输出中是否有 gc 提示
            check_cmd = f"grep -c \"gc\" {tmp_log} 2>/dev/null || echo 0"
            _, count_out, _ = await self._ssh_execute(check_cmd, timeout=5)
            try:
                has_gc_prompt = int(count_out.strip()) > 0
            except ValueError:
                has_gc_prompt = False

            if not has_gc_prompt:
                return

            # 从 nvsipl 命令的 -m 掩码解析活跃 sensor
            # 读取启动命令（从日志文件推断或用已知命令）
            cat_cmd = f"head -5 {tmp_log} 2>/dev/null"
            _, head_out, _ = await self._ssh_execute(cat_cmd, timeout=5)

            # 用 _generate_gc_commands 从已知的起流命令解析
            # 这里直接从 tmp_log 内容检测实际的 sensor ID
            sensor_cmd = f"grep -oP 'Sensor\\K\\d+' {tmp_log} 2>/dev/null | sort -un"
            _, sensor_out, _ = await self._ssh_execute(sensor_cmd, timeout=5)
            sensor_ids = [int(x.strip()) for x in sensor_out.strip().split('\n') if x.strip().isdigit()]

            if not sensor_ids:
                # 退回用检测到的所有可能 gc 行
                await self.ws.send_log(
                    f"[{case_id}] [并行模式] 检测到 gc 提示但无法确定 sensor ID", "warning")
                return

            gc_cmds = [f"gc {sensor_ids[0]}"]  # 只需一条 gc 即可触发全部出帧
            await self.ws.send_log(
                f"[{case_id}] [并行模式] 检测到需要 gc，注入: {gc_cmds}", "info")

            # 通过 FIFO 写入
            for gc_cmd in gc_cmds:
                inject_cmd = f"echo '{gc_cmd}' > {tmp_fifo}"
                await self._ssh_execute(inject_cmd, timeout=5)
                await asyncio.sleep(0.5)

            await self.ws.send_log(f"[{case_id}] [并行模式] gc 注入完成，等待响应...", "info")
            await asyncio.sleep(3)
        except Exception as e:
            await self.ws.send_log(f"[{case_id}] [并行模式] gc 注入异常(非致命): {e}", "warning")

    def _check_round_fps(self, output: str, case_id: str, round_num: int) -> tuple:
        """检查单轮起流的 fps 输出，验证所有 sensor 都有帧率 > 0。

        返回: (passed: bool, message: str)
        """
        import re
        # 匹配多种 fps 输出格式：
        #   Sensor0_Out0  Frame rate (fps):    29.9907
        #   Sensor0_Out0  Frame rate:          29.9907
        fps_pattern = re.compile(
            r'(Sensor\d+_Out\d+)\s+Frame rate[^:]*:\s*([\d.]+)')
        matches = fps_pattern.findall(output)

        if not matches:
            return False, f"第{round_num}次起流: 未检测到任何 sensor 帧率输出"

        failed_sensors = []
        passed_sensors = []
        for sensor_name, fps_str in matches:
            try:
                fps_val = float(fps_str)
            except ValueError:
                fps_val = 0.0
            if fps_val <= 0:
                failed_sensors.append(f"{sensor_name}={fps_val}")
            else:
                passed_sensors.append(f"{sensor_name}={fps_val:.1f}")

        if failed_sensors:
            return False, f"第{round_num}次起流: sensor帧率异常 {failed_sensors}"

        return True, f"第{round_num}次起流正常: {len(passed_sensors)}个sensor均有帧率"

    @staticmethod
    def _generate_gc_commands(nvsipl_cmd: str) -> list:
        """从 nvsipl_camera 命令的 -m 掩码解析活跃 sensor ID，生成一条 gc 命令。

        只需任意一条 gc 命令即可触发所有 sensor 出帧，无需为每个 sensor 单独发送。
        """
        import re
        from app.core.expected_parser import ExpectedResultParser
        sensor_ids = ExpectedResultParser._parse_sensor_mask(nvsipl_cmd)
        if not sensor_ids:
            return []
        # 只取第一个 sensor ID，一条 gc 即可触发全部出帧
        return [f"gc {sensor_ids[0]}"]

    def _wrap_nvsipl_with_gc(self, shell_cmd: str, original_cmd: str) -> str:
        """对 nvsipl_camera 命令自动包裹 gc 注入管道。

        将命令从：
          nvsipl_camera -c xxx -m "mask" -r 5
        改为：
          { sleep 5; echo 'gc 0'; } | nvsipl_camera -c xxx -m "mask" -r 5

        只需一条 gc（任意 sensor）即可触发所有 sensor 出帧。
        如果 nvsipl 不需要 gc（没有提示），多余的 gc 输入会被忽略。
        """
        gc_cmds = self._generate_gc_commands(original_cmd)
        if not gc_cmds:
            return shell_cmd

        # 构建延迟输入：等 nvsipl 初始化后发 gc
        parts = ["sleep 5"]
        for gc in gc_cmds:
            parts.append(f"echo '{gc}'")
        # 加长等待确保 nvsipl 有时间处理
        parts.append("sleep 3")

        input_block = "{ " + "; ".join(parts) + "; }"
        return f"{input_block} | {shell_cmd}"
