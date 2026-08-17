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
from app.core.expected_parser import ExpectedResultParser


class ExecutorAdapter:
    def __init__(self, ssh_manager, ws_manager, workspace=None):
        self.ssh = ssh_manager
        self.ws = ws_manager
        self.workspace = workspace
        self._stop = False
        self.parser = ExpectedResultParser()
        self._image_path_checked = False

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
            await self.ws.send_case_complete(case.case_id, result.status, result.match_reason, case.case_key)

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
        log_file = f"logs/{case.case_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        os.makedirs("logs", exist_ok=True)

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

            # 检测是否为并行执行场景（阻塞型 nvsipl + 后续命令）
            blocking_idx = self._find_blocking_nvsipl_index(steps)
            if blocking_idx is not None:
                # DEBUG: 打印 merge 后的步骤，确认 al 是否存在
                step_summary = [(s.kind, s.command[:40] if s.command else '') for s in steps]
                await self.ws.send_log(f"[{case.case_id}] [DEBUG] merged steps: {step_summary}", "info")
            if blocking_idx is not None and blocking_idx < len(steps) - 1:
                # 并行执行模式（故障测试），全局 120s 超时保护
                try:
                    combined_outputs, last_exit_code, last_cmd = await asyncio.wait_for(
                        self._execute_parallel_fault_test(case, steps, blocking_idx, work_dir),
                        timeout=180,
                    )
                except asyncio.TimeoutError:
                    await self.ws.send_log(
                        f"[{case.case_id}] [并行模式] 执行超时(120s)，强制终止", "error")
                    combined_outputs = ["执行超时(120s)"]
                    last_exit_code = -1
                    last_cmd = "parallel_fault_test"
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
                file_output = await self._check_remote_files(case.case_id, work_dir, criteria.file_check)
                if file_output:
                    combined += "\n" + file_output

            result.actual_output = combined
            result.log_file = log_file

            with open(log_file, "w", encoding="utf-8") as f:
                f.write(combined)
            result.log_file = log_file

            # 预期结果匹配
            # 判断是否为 dl/elr 交互式用例（输出中含 Disable Link / Enable Link）
            is_dl_elr_case = "Disable Link" in combined and "Enable Link" in combined
            if is_dl_elr_case:
                passed, reason = await self._match_dl_elr_stages(case.case_id, combined)
            else:
                passed, reason = self.parser.match(criteria, combined, last_exit_code, last_cmd)
            result.match_reason = reason
            result.match_log_file = log_file

            # 推送匹配判定详情到前端日志
            await self.ws.send_log(
                f"[{case.case_id}] === 匹配判定 ===", "info")
            if not is_dl_elr_case:
                await self.ws.send_log(
                    f"[{case.case_id}] 预期关键字: {case.expected_keywords or '(无)'}", "info")
            for reason_line in reason.split("; "):
                level = "info"
                if "FAIL" in reason_line or "Fail" in reason_line or "非0" in reason_line:
                    level = "warning"
                elif "PASS" in reason_line or "Pass" in reason_line or "OK" in reason_line:
                    level = "info"
                await self.ws.send_log(f"[{case.case_id}]   {reason_line}", level)
            result.status = "Pass" if passed else "Fail"

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            result.status = "Fail"
            result.error_msg = f"{type(e).__name__}: {e}"
            result.match_reason = f"执行异常: {type(e).__name__}: {e}"
            await self.ws.send_log(f"[{case.case_id}] 异常: {type(e).__name__}: {e}", "error")
            await self.ws.send_log(f"[{case.case_id}] Traceback:\n{tb}", "error")

        result.end_time = datetime.now()
        case.status = result.status
        case.actual_result = (result.actual_output or result.error_msg or "")[:500]
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

    @staticmethod
    def _normalize_quotes(cmd: str) -> str:
        """Replace Chinese/fullwidth quotes with ASCII equivalents."""
        cmd = cmd.replace('\u201c', '"').replace('\u201d', '"')
        cmd = cmd.replace('\u2018', "'").replace('\u2019', "'")
        cmd = cmd.replace('\uff02', '"')
        cmd = cmd.replace('\u300c', '"').replace('\u300d', '"')
        return cmd

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
                    # 保留后续 nvsipl_input 步骤（跳过 skip）
                    while i < len(steps):
                        if steps[i].kind == "nvsipl_input":
                            merged.append(steps[i])
                            i += 1
                        elif steps[i].kind == "skip":
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

        流程：
        1. 打开 PTY channel 运行 nvsipl_camera
        2. 等待 nvsipl 初始化完成（菜单出现）
        3. 逐条注入交互命令（gc → 等出帧 → al/ro 等查询）
        4. 捕获每条命令的输出
        5. 执行后续 shell 命令（故障注入等）
        6. 发送 q 退出 nvsipl

        返回: (combined_outputs, last_exit_code, last_cmd)
        """
        import re
        import time as _time

        combined_outputs = []
        last_exit_code = 0
        last_cmd = ""

        # 获取阻塞命令
        blocking_step = steps[blocking_idx]
        nvsipl_cmd = self._normalize_quotes(blocking_step.command)
        nvsipl_cmd = self._apply_nito_override(nvsipl_cmd)
        nvsipl_cmd = self._apply_image_path_override(nvsipl_cmd)
        nvsipl_cmd = self._apply_sudo_password(nvsipl_cmd)

        cd_prefix = f"cd {work_dir} && " if work_dir else ""
        full_cmd = f"{cd_prefix}{nvsipl_cmd}"

        await self.ws.send_log(f"[{case.case_id}] [并行模式] PTY启动: {nvsipl_cmd}", "info")

        # Step 1: 打开 PTY channel
        loop = asyncio.get_event_loop()
        channel = await loop.run_in_executor(
            None, lambda: self.ssh.open_interactive_channel(full_cmd, timeout=180)
        )

        all_output = ""  # 累积所有 PTY 输出

        async def _read_channel(timeout_sec: float, stop_pattern: str = None) -> str:
            """异步读取 channel 输出，直到超时或匹配到 stop_pattern。"""
            nonlocal all_output
            buf = ""
            start = _time.time()
            while _time.time() - start < timeout_sec:
                if self._stop:
                    break
                ready = await loop.run_in_executor(None, channel.recv_ready)
                if ready:
                    data = await loop.run_in_executor(None, lambda: channel.recv(65536))
                    text = data.decode("utf-8", errors="replace")
                    buf += text
                    all_output += text
                    if stop_pattern and re.search(stop_pattern, buf, re.IGNORECASE):
                        break
                else:
                    await asyncio.sleep(0.3)
            return buf

        try:
            # Step 2: 等待 nvsipl 初始化完成（菜单 "Enter 'gc" 出现）
            await self.ws.send_log(f"[{case.case_id}] [并行模式] 等待 nvsipl 初始化...", "info")
            init_output = await _read_channel(30.0, stop_pattern=r"Enter\s+'gc")

            if "ERROR" in init_output or "failed" in init_output.lower():
                await self.ws.send_log(
                    f"[{case.case_id}] [并行模式] nvsipl 启动失败: {init_output[-200:]}", "error")
                combined_outputs.append(init_output)
                return combined_outputs, 1, full_cmd

            if not re.search(r"Enter\s+'gc", init_output):
                await self.ws.send_log(
                    f"[{case.case_id}] [并行模式] nvsipl 初始化超时（30s），继续尝试", "warning")

            # Step 3: 注入交互命令
            gc_inputs = [s for s in steps[blocking_idx + 1:] if s.kind == "nvsipl_input"]
            if gc_inputs:
                gc_cmds = []
                for s in gc_inputs:
                    gc_cmds.extend(s.command.split(";"))
                gc_cmds = [c.strip().lower() for c in gc_cmds if c.strip()]
            else:
                gc_cmds = []

            if gc_cmds:
                await self.ws.send_log(
                    f"[{case.case_id}] [并行模式] 注入交互命令: {gc_cmds}", "info")

                fps_detected = False
                for i, gc_cmd in enumerate(gc_cmds):
                    if self._stop:
                        break

                    # 发送命令
                    await loop.run_in_executor(None, lambda cmd=gc_cmd: channel.send(cmd + "\n"))
                    await self.ws.send_log(
                        f"[{case.case_id}] [并行模式] 发送: {gc_cmd}", "info")

                    # gc 命令：等待出帧（Frame rate）
                    if gc_cmd.startswith("gc"):
                        gc_output = await _read_channel(20.0, stop_pattern=r"Frame rate")
                        if "Frame rate" in gc_output:
                            fps_detected = True
                            await self.ws.send_log(
                                f"[{case.case_id}] [并行模式] 出帧正常", "info")
                            # 多等几秒让帧率稳定
                            await asyncio.sleep(3)
                            # 读取积累的输出
                            extra = await _read_channel(1.0)
                        else:
                            await self.ws.send_log(
                                f"[{case.case_id}] [并行模式] gc 后未检测到出帧（20s）", "warning")

                    # al/ro 等查询命令：等待特征输出
                    elif gc_cmd in ('al', 'ro', 'cm', 'ed', 'th', 'df'):
                        feature_patterns = {
                            'al': r'Vertical|horizontal|active_w|active_h|active|pixel|belongs to',
                            'ro': r'[Rr]eadout.*\d|readout_time',
                            'cm': r'module|available',
                            'ed': r'eeprom|data',
                            'th': r'[Tt]emp|histogram',
                            'df': r'fault|detect',
                        }
                        feat_pat = feature_patterns.get(gc_cmd, r'\w+')
                        cmd_output = await _read_channel(10.0, stop_pattern=feat_pat)

                        # 提取该命令的有效输出（去掉菜单提示和fps）
                        useful_lines = []
                        for line in cmd_output.split('\n'):
                            stripped = line.strip()
                            if not stripped:
                                continue
                            # 跳过菜单行和 fps 行
                            if stripped.startswith("Enter '") or "Frame rate" in stripped:
                                continue
                            if stripped in ('-', 'Output'):
                                continue
                            useful_lines.append(stripped)

                        if useful_lines:
                            useful_text = "\n".join(useful_lines)
                            combined_outputs.append(useful_text)
                            await self.ws.send_log(
                                f"[{case.case_id}] [并行模式] [{gc_cmd}] 有效输出:\n{useful_text}", "info")
                        else:
                            await self.ws.send_log(
                                f"[{case.case_id}] [并行模式] [{gc_cmd}] 未检测到有效输出", "warning")
                            # 即使没有特征输出也将原始输出加入
                            if cmd_output.strip():
                                combined_outputs.append(cmd_output)

                    # dl/elr/el 等链路操作命令
                    elif gc_cmd.startswith(("dl", "elr", "el", "les", "lds")):
                        cmd_output = await _read_channel(10.0, stop_pattern=r"Link|link|LED")
                        if cmd_output.strip():
                            combined_outputs.append(cmd_output)
                            key_lines = self._extract_key_output_lines(cmd_output, max_lines=10)
                            if key_lines:
                                await self.ws.send_log(
                                    f"[{case.case_id}] [并行模式] [{gc_cmd}] 输出:\n{key_lines}", "info")

                    else:
                        # 其他命令等1秒
                        await asyncio.sleep(1)
                        extra = await _read_channel(2.0)
                        if extra.strip():
                            combined_outputs.append(extra)

                # 注入完成后再读一些输出（可能有延迟数据）
                await asyncio.sleep(2)
                trailing = await _read_channel(2.0)

            # Step 4: 执行后续 shell 命令（故障注入 + 检测，排除 nvsipl_input）
            subsequent_steps = [s for s in steps[blocking_idx + 1:] if s.kind == "command"]
            for step in subsequent_steps:
                if self._stop:
                    break
                if re.search(r'输入\s*(gc|dl|elr|el|q)', step.command):
                    continue
                shell_cmd = self._normalize_quotes(step.command)
                shell_cmd = self._apply_nito_override(shell_cmd)
                shell_cmd = self._apply_image_path_override(shell_cmd)
                shell_cmd = self._apply_sudo_password(shell_cmd)
                if work_dir:
                    shell_cmd = f"cd {work_dir} && {shell_cmd}"
                last_cmd = shell_cmd
                await self.ws.send_log(f"[{case.case_id}] [并行模式] 执行: {shell_cmd}", "info")

                exit_code, stdout, stderr = await self._ssh_execute(shell_cmd, timeout=60)
                last_exit_code = exit_code
                combined_outputs.append(stdout or "")
                if stderr:
                    combined_outputs.append(stderr)

                key_lines = self._extract_key_output_lines(stdout or "")
                if key_lines:
                    await self.ws.send_log(
                        f"[{case.case_id}] 命令关键输出:\n{key_lines}", "info")
                if exit_code != 0:
                    await self.ws.send_log(
                        f"[{case.case_id}] 命令返回码非0: exit_code={exit_code}", "warning")

        finally:
            # Step 5: 发送 q 退出 nvsipl，关闭 channel
            try:
                await self.ws.send_log(f"[{case.case_id}] [并行模式] 发送 q 退出 nvsipl", "info")
                await loop.run_in_executor(None, lambda: channel.send("q\n"))
                await asyncio.sleep(3)
                # 读取退出后输出
                quit_output = await _read_channel(5.0, stop_pattern=r"Deinit|quit|exit")
                all_output += quit_output
            except Exception:
                pass
            finally:
                try:
                    await loop.run_in_executor(None, channel.close)
                except Exception:
                    pass

            # 将完整输出的关键行也加入
            if all_output:
                key_lines = self._extract_key_output_lines(all_output, max_lines=20)
                if key_lines:
                    await self.ws.send_log(
                        f"[{case.case_id}] [并行模式] nvsipl 完整输出关键行:\n{key_lines}", "info")
                # 确保 combined_outputs 里有完整数据供判定
                if not combined_outputs:
                    combined_outputs.append(all_output)

        return combined_outputs, last_exit_code, last_cmd

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
        """检测 nvsipl 输出中是否有 gc 提示，如有则注入 gc 命令。

        检测标志：输出含 "Enter 'gc" 字样（表示此配置需要 gc 才能正常出帧）。
        注入内容：从后台启动命令的 -m 掩码解析出所有活跃 sensor ID，逐个发 gc <id>。
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

            gc_cmds = [f"gc {sid}" for sid in sensor_ids]
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

    @staticmethod
    def _generate_gc_commands(nvsipl_cmd: str) -> list:
        """从 nvsipl_camera 命令的 -m 掩码解析活跃 sensor ID，生成 gc 命令列表。"""
        import re
        from app.core.expected_parser import ExpectedResultParser
        sensor_ids = ExpectedResultParser._parse_sensor_mask(nvsipl_cmd)
        if not sensor_ids:
            return []
        return [f"gc {sid}" for sid in sensor_ids]

    def _wrap_nvsipl_with_gc(self, shell_cmd: str, original_cmd: str) -> str:
        """对 nvsipl_camera 命令自动包裹 gc 注入管道。

        将命令从：
          nvsipl_camera -c xxx -m "mask" -r 5
        改为：
          { sleep 5; echo 'gc 0'; echo 'gc 2'; ... } | nvsipl_camera -c xxx -m "mask" -r 5

        这样 nvsipl 启动后等到 gc 提示时管道里已有 gc 命令可读，不会卡住。
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
