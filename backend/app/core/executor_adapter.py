"""执行器适配器（异步版）。

将原 PyQt 执行逻辑适配为异步，支持 WebSocket 实时推送。
- 命令解析：CommandParser 把测试步骤拆成可执行命令序列，不再整段当一条命令
- 结果判定：仅使用 AI；规则引擎（ExpectedResultParser.match 等）已弃用
- 预期解析：ExpectedResultParser.parse 仅用于文件检查/故障测试等执行前信息
- NA 识别：命中待写入/TBD 等关键字自动标记 NA 并跳过执行
- 工作目录：追踪 cd / 进入调试目录，命令以 ``cd <dir> && <cmd>`` 形式下发
- 非阻塞：SSH 同步调用通过 run_in_executor 移出事件循环，避免长时间执行卡死后端
"""
import asyncio
import os
import re
import time
from datetime import datetime
from typing import Optional, Tuple
from app.core.test_case import TestCase, TestResult
from app.core.command_parser import CommandParser
from app.core.expected_parser import ExpectedResultParser
from app.core.remarks import build_remark_from_case


def _nvsipl_has_real_error(output: str, is_fault_test: bool = False) -> bool:
    """判断 nvsipl 输出是否包含真正的错误。

    排除正常统计行中的 "failed" 关键字，如：
      "Frames failed to authenticate: 0"
    这类行在 nvsipl_camera 正常运行时固定出现，不是错误。

    故障测试(is_fault_test=True)时：输出中的 ERROR 是预期行为，
    仅检测 nvsipl 启动失败相关的硬错误（如 "Cannot bind", "Init failed"）。
    """
    if is_fault_test:
        # 故障测试中 ERROR 是正常的，只检测 nvsipl 自身启动失败
        hard_error_patterns = [
            r'Cannot bind',
            r'Init.*failed',
            r'No such file or directory',
            r'Permission denied',
        ]
        for pat in hard_error_patterns:
            if re.search(pat, output):
                return True
        return False

    if "ERROR" in output:
        return True
    for line in output.split('\n'):
        low = line.lower()
        if "failed" not in low:
            continue
        # 排除 nvsipl 正常统计行（"failed to authenticate: 0" 等）
        if re.search(r'failed\s+to\s+authenticate\s*:\s*0', low):
            continue
        # 排除 "Frames failed to authenticate: 0" 格式的统计行
        if re.search(r'frames\s+failed\s+to\s+authenticate\s*:\s*0', low):
            continue
        # 其他含 failed 的行视为真正错误
        return True
    return False


def _has_real_fps(output: str) -> bool:
    """判断输出中是否包含真实的帧率数值（区分菜单提示行）。

    真实帧率行格式：
        Sensor0_Out0\tFrame rate (fps):\t\t29.999
    菜单提示行格式（不是真实帧率）：
        Frame rate (fps):\t\tEnter 'q' to quit the application
    PTY 缓冲区拼接的混合行（也不是真实帧率）：
        Sensor3_Out0\tFrame rate (fps):\t\tEnter 'el' followed by sensor ID
    """
    return bool(re.search(
        r'Frame rate[^:]*:\s*[\d.]+',
        output
    ))


# stop_pattern：只匹配 "Frame rate" 后面紧跟数字的真实帧率行，
# 不会被菜单提示行（Frame rate 后跟 Enter/文字）误触发。
_REAL_FPS_PATTERN = r"Frame rate[^:]*:\s*[\d.]+"

# 图片/视频产物后缀：执行前清空目录与执行后文件检查共用
_IMAGE_OUTPUT_GLOBS = (
    "*.raw", "*.yuv", "*.png", "*.jpg", "*.jpeg", "*.bmp", "*.h264", "*.hevc",
)

# 用例预期结果中的分辨率标注，例如「yuv图（1920x1536）可正常查看」
# 括号内允许追加像素格式等说明，例如「yuv图（1920x1080, uyvy）」
_RESOLUTION_PATTERN = re.compile(
    r'[（(]\s*(\d{3,5})\s*[xX×]\s*(\d{3,5})\s*[^)）]*[)）]'
)

# 预期结果里可选的像素格式标注 -> yuv2img 支持的格式名
_PIXFMT_ALIASES = {
    "nv12": "nv12",
    "i420": "i420", "yuv420p": "i420", "yv12": "i420",
    "yuyv": "yuyv", "yuy2": "yuyv", "yuyv422": "yuyv",
    "uyvy": "uyvy", "uyvy422": "uyvy", "y422": "uyvy", "uynv": "uyvy",
}
_PIXFMT_PATTERN = re.compile(
    r'(?<![0-9A-Za-z])('
    + '|'.join(sorted(_PIXFMT_ALIASES, key=len, reverse=True))
    + r')(?![0-9A-Za-z])',
    re.IGNORECASE,
)

# nvsipl_camera 交互子命令 → (等待的输出特征, 超时秒数)
# 新增子命令只需在这里加一行，统一执行器不需要改动。
_NVSIPL_INPUT_EXPECT = {
    "gc": (r"Frame rate[^:]*:\s*[\d.]+|(?-i:ERROR)", 20.0),
    "sr": (r"ROI values|enter two sets|Sucess|Success", 10.0),
    "hs": (r"histogramInfo|Histogram|histogram", 10.0),
    "al": (r"Vertical|horizontal|active_w|active_h|active|pixel|belongs to", 10.0),
    "ro": (r"[Rr]eadout.*\d|readout_time", 10.0),
    "cm": (r"module|available", 10.0),
    "ed": (r"eeprom|data", 10.0),
    "th": (r"[Tt]emp|histogram", 10.0),
    "df": (r"fault|detect|Fault|Detect|error|Error", 10.0),
    "ex": (r"Index|0x[0-9a-fA-F]{2}|Failed|ERROR", 10.0),
    "dl": (r"Link|link|LED", 10.0),
    "elr": (r"Link|link|LED", 10.0),
    "el": (r"Link|link|LED", 10.0),
    "les": (r"Link|link|LED", 10.0),
    "lds": (r"Link|link|LED", 10.0),
}


class ManualConfirmFailed(Exception):
    """人工确认未通过：携带已产生的输出，供调用方写日志后提前结束用例。"""

    def __init__(self, description: str, outputs: list):
        super().__init__(description)
        self.description = description
        self.outputs = list(outputs or [])


def _parse_resolution_from_text(text: str) -> Optional[Tuple[int, int]]:
    """从预期结果文本中解析分辨率，如 ``（1920x1536）`` → (1920, 1536)。

    括号内可带其他说明，如 ``（1920x1080, uyvy）``。
    """
    match = _RESOLUTION_PATTERN.search(text or "")
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _parse_pixfmt_from_text(text: str) -> Optional[str]:
    """从预期结果文本中解析像素格式，如 ``yuv图（1920x1080, uyvy）`` → ``uyvy``。

    未标注时返回 None，由 yuv2img 自动识别。
    """
    match = _PIXFMT_PATTERN.search(text or "")
    if not match:
        return None
    return _PIXFMT_ALIASES[match.group(1).lower()]


class ExecutorAdapter:
    def __init__(self, ssh_manager, ws_manager, workspace=None, log_dir="logs",
                 ai_service=None, ai_parsed_steps=None):
        self.ssh = ssh_manager
        self.ws = ws_manager
        self.workspace = workspace
        self.log_dir = log_dir
        self._stop = False
        self.parser = ExpectedResultParser()
        self._image_path_checked = False
        self._ai_service = ai_service  # AI 判定服务（可选）
        self._ai_parsed_steps = ai_parsed_steps or {}  # AI 预解析步骤缓存
        # 当前用例的执行进度上下文（用于推送细分阶段到前端进度条）
        self._progress_current = 0
        self._progress_total = 0
        self._progress_case_id = ""
        self._progress_case_key = ""
        # 板端系统日志采集后端（None=未检测，''=不可用，journalctl/slog2info）
        self._syslog_backend: Optional[str] = None

    async def _send_progress(self, message: str):
        """推送当前用例的细分执行阶段（沿用用例级 current/total）。"""
        if not self._progress_total:
            return
        await self.ws.send_progress(
            self._progress_current, self._progress_total,
            self._progress_case_id, self._progress_case_key, message,
        )

    @staticmethod
    def _format_wait(seconds: float) -> str:
        """把等待秒数格式化成便于阅读的文案。"""
        if seconds >= 60 and seconds % 60 == 0:
            return f"{int(seconds // 60)} 分钟"
        return f"{seconds:g} 秒"

    async def _wait_step_delay(self, case: TestCase, step, prefix: str = ""):
        """执行步骤命令后按「等待N秒」的时长等待（可被 Stop 中断）。"""
        seconds = float(getattr(step, "wait_seconds", 0.0) or 0.0)
        if seconds <= 0 or self._stop:
            return
        await self.ws.send_log(
            f"[{case.case_id}] {prefix}等待 {self._format_wait(seconds)}"
            f"（步骤等待）...", "info")
        deadline = time.monotonic() + seconds
        while not self._stop:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(0.5, remaining))
        if self._stop:
            await self.ws.send_log(
                f"[{case.case_id}] {prefix}步骤等待被用户停止", "warning")

    @staticmethod
    def _step_progress_message(prefix: str, index: int, total: int, command: str = "") -> str:
        """构造带步骤序号的阶段文案，命令过长时截断。"""
        cmd = " ".join((command or "").split())
        if len(cmd) > 60:
            cmd = cmd[:57] + "..."
        text = f"{prefix} ({index}/{total})"
        return f"{text}: {cmd}" if cmd else text

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

            self._progress_current = idx
            self._progress_total = total
            self._progress_case_id = case.case_id
            self._progress_case_key = case.case_key
            await self._send_progress("正在开始执行用例")
            result = await self._execute_single(case, run_prerequisites)
            results.append(result)
            await self.ws.send_case_complete(
                case.case_id, result.status, result.match_reason,
                case.case_key, case.actual_result, result.log_file or case.log_file,
                build_remark_from_case(case),
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
            self._write_case_log(
                case, result,
                f"[NA] {na_reason}\n\n用例: {case.case_id}\n描述: {case.description}\n"
                f"判定: 命中 NA 关键字，未执行测试步骤\n",
            )
            await self.ws.send_log(f"[{case.case_id}] 标记为 NA：{na_reason}", "info")
            return result

        # 前置条件
        if run_prerequisites and case.prerequisites:
            await self._send_progress("正在执行前置条件")
            await self.ws.send_log(f"[{case.case_id}] 执行前置条件...", "info")
            ok, prereq_output = await self._run_prerequisites(case.prerequisites)
            if not ok:
                result.status = "Fail"
                result.error_msg = "前置条件失败"
                result.actual_output = prereq_output
                result.end_time = datetime.now()
                case.status = "Fail"
                case.actual_result = "前置条件失败"
                self._write_case_log(
                    case, result,
                    f"[前置条件失败]\n前置条件:\n{case.prerequisites}\n\n"
                    f"执行记录:\n{prereq_output}\n",
                )
                return result

        # 执行测试步骤
        await self._send_progress("正在解析测试步骤")
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

        # AI 兜底：如有未识别步骤且 AI 已启用，尝试用 AI 解析补充
        # has_unrecognized = any(
        #     s.kind == "skip" and "未识别步骤" in s.description for s in steps
        # )
        # if has_unrecognized and self._ai_service and self._ai_service.enabled:
        #     case_key = case.case_key or f"{case.source_sheet}:{case.row_number}:{case.case_id}"
        #     # 优先使用预解析缓存
        #     if case_key not in self._ai_parsed_steps:
        #         await self._send_progress("正在 AI 解析测试步骤")
        #         try:
        #             parsed = await asyncio.wait_for(
        #                 self._ai_service.parse_steps(
        #                     step_text=case.test_steps,
        #                     context=case.description,
        #                 ),
        #                 timeout=60,
        #             )
        #             if parsed and "_error" not in parsed:
        #                 self._ai_parsed_steps[case_key] = parsed.get("parsed_steps", [])
        #                 await self.ws.send_log(
        #                     f"[{case.case_id}] AI 实时解析步骤完成，"
        #                     f"识别 {parsed.get('ai_recognized', 0)} 条命令",
        #                     "info",
        #                 )
        #         except Exception as e:
        #             await self.ws.send_log(
        #                 f"[{case.case_id}] AI 步骤解析失败: {e}", "warning"
        #             )
        #     steps = CommandParser.apply_ai_parsed_steps(
        #         steps, self._ai_parsed_steps, case_key
        #     )

        # 注：不再把 nvsipl_camera 与后续交互输入合并成管道命令。
        # 统一执行器持有多终端持久会话，交互输入按步骤顺序直接发给对应终端，
        # 因此 _merge_nvsipl_interactive 已随旧的三模式分流一起移除。

        combined_outputs = []
        last_exit_code = 0
        last_cmd = ""

        # 早期判断是否为故障测试（预期结果中要求观察 _ERROR/_FAULT 等关键字）
        # 用于后续 _nvsipl_has_real_error 和结果判定时抑制 ERROR 误判
        criteria_early = self.parser.parse(case.expected_result or "")
        is_fault_test = criteria_early.is_fault_test
        if is_fault_test:
            await self.ws.send_log(
                f"[{case.case_id}] 检测到故障测试用例（输出中的 ERROR 为预期行为）", "info")

        # 执行前清空板端图片目录：保证执行后的文件检查只看到本次产物。
        # 仅清空 nvsipl 实际写入的目录（-f 指定目录；未带 -f 时才用当前目录），
        # 避免 -f 已指定出图目录时仍去清空 / 搜索工作目录。
        image_dirs = self._collect_image_dirs(
            steps, default_remote_path, include_work_dir=False)
        if (criteria_early.file_check
                and not self._image_storage_path()
                and not image_dirs):
            image_dirs = self._collect_image_dirs(
                steps, default_remote_path, include_work_dir=True)
        storage_path = self._image_storage_path()
        if storage_path:
            image_dirs.insert(0, storage_path)
        image_cleanup_note = await self._clear_board_images(case.case_id, image_dirs)

        # 用例执行期间采集板端系统日志（Linux journalctl / QNX slog2info）
        syslog_ctx = await self._start_syslog_capture(case.case_id)

        try:
            work_dir = default_remote_path
            # 统一执行器：所有步骤都在「按终端标签复用的持久化 shell」中执行，
            # 不再区分顺序执行 / 持久 Shell / 并行 PTY 三种模式。
            # 返回 (时间序输出, 退出码, 最后命令, 按终端分组的日志)
            combined_outputs, last_exit_code, last_cmd, terminal_log = \
                await self._execute_unified(
                    case, steps, default_remote_path, is_fault_test=is_fault_test)

            combined = "\n".join(combined_outputs)

            # 文件检查的「命令/目录/结果」说明只用于日志与 AI 判定，
            # 不并入规则匹配输入，否则说明文本里的 ".raw" 会让关键字永远命中。
            # 日志保持精简：只记录查找命令与查找结果。
            file_check_notes: list = []

            # 文件类预期检查：执行后在板端查找本次生成的产物
            criteria = criteria_early  # 复用早期解析结果，避免重复 parse
            if criteria.file_check:
                search_dirs = self._resolve_file_search_dirs(
                    steps, default_remote_path, work_dir)
                if search_dirs:
                    file_list: list = []
                    for search_dir in search_dirs:
                        file_block, files = await self._check_remote_files(
                            case.case_id, search_dir, criteria.file_check,
                            case.expected_result)
                        file_check_notes.append(file_block)
                        for item in files:
                            if item not in file_list:
                                file_list.append(item)
                    if file_list:
                        # 只把真实文件路径并入匹配输入，供关键字检查
                        combined += "\n" + "\n".join(file_list)
                    # 汇总行只进日志/AI 输入，不参与关键字匹配
                    file_check_notes.append(
                        f"[文件检查] 汇总: "
                        f"{'找到 ' + str(len(file_list)) + ' 个' if file_list else '未找到'}"
                        f" {criteria.file_check} 文件")
                    # 文件数量验证（仅当预期结果中明确了数量时）
                    if criteria.file_count > 0:
                        if len(file_list) >= criteria.file_count:
                            combined += (
                                f"\n[文件数量检查] 找到 {len(file_list)} 个文件 "
                                f">= 预期 {criteria.file_count} 个: PASS")
                        else:
                            combined += (
                                f"\n[文件数量检查] 找到 {len(file_list)} 个文件 "
                                f"< 预期 {criteria.file_count} 个: FAIL")
                else:
                    file_check_notes.append(
                        "[文件检查] 未配置远端工作路径/图片存储目录，已跳过文件检查")

            file_check_log = "\n".join(n for n in file_check_notes if n)

            # 两份内容分别面向不同读者：
            # - log_content：按终端分组的日志，便于人工回溯每个终端的完整过程；
            # - combined：按时间顺序的输出，保留跨终端的因果顺序，供 AI 判定。
            log_content = terminal_log or combined
            if file_check_log:
                log_content = f"{log_content}\n{file_check_log}"
            # 板端系统日志只写入用例日志文件，不参与 AI 判定
            syslog_block = await self._stop_syslog_capture(syslog_ctx)
            if syslog_block:
                log_content = f"{log_content}\n\n{syslog_block}"
            self._write_case_log(case, result, log_content, log_file=log_file)

            # 判定输入：去掉命令回显后的时间序输出 + 文件检查说明
            combined = self._strip_command_echoes(combined)
            if file_check_log:
                combined = f"{combined}\n{file_check_log}"
            result.actual_output = combined

            # ---- 判定：仅使用 AI，规则引擎已弃用 ----
            # 不再调用 ExpectedResultParser.match / FrameSyncChecker.check /
            # _match_dl_elr_stages 产生 Pass/Fail。以下特殊处理只负责收集原始 log，
            # 供 AI 不可用或 AI 要求人工确认时展示，不产生规则判定。
            await self._send_progress("正在分析执行输出")
            from app.core.frame_sync_checker import FrameSyncChecker

            is_metadata_embedded = (
                FrameSyncChecker.is_metadata_embedded_case(case.expected_result)
                and 'Camera ID:' in combined
                and 'Frame Counter:' in combined
            )
            is_sr_hs_review = (
                FrameSyncChecker.is_sr_hs_review_case(case.expected_result)
                and ('set ROI' in combined or 'histogramInfo' in combined
                     or 'ROI values' in combined or 'Histogram' in combined
                     or 'Please enter' in combined or 'histogram' in combined.lower())
            )
            if is_metadata_embedded:
                result._metadata_log = FrameSyncChecker.extract_metadata_frames(
                    combined, max_frames=10)
                await self.ws.send_log(
                    f"[{case.case_id}] 嵌入行信息检测 — 已截取 metadata log，交由 AI 判定",
                    "info")
            elif is_sr_hs_review:
                result._sr_hs_log = combined
                await self.ws.send_log(
                    f"[{case.case_id}] sr/hs 用例 — 已收集输出，交由 AI 判定",
                    "info")

            passed, reason, _ = await self._apply_ai_judgment(
                case=case,
                result=result,
                combined=combined,
                last_exit_code=last_exit_code,
            )
            await self._send_progress("正在生成判定结果")
            result.match_reason = reason
            result.match_log_file = log_file

            # 推送 AI 判定详情到前端日志
            await self.ws.send_log(
                f"[{case.case_id}] === AI 判定（规则引擎已弃用）===", "info")
            expected_preview = (case.expected_result or "(无)").strip()
            if len(expected_preview) > 500:
                expected_preview = expected_preview[:500] + "..."
            await self.ws.send_log(
                f"[{case.case_id}] 预期结果: {expected_preview}", "info")
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

        except ManualConfirmFailed as confirm_err:
            # 人工确认未通过：不再是「异常」，判定为 Fail 并保留已完成步骤的输出
            result.status = "Fail"
            result.error_msg = f"人工确认未通过：{confirm_err.description}"
            result.actual_output = "\n".join(confirm_err.outputs)
            result.match_reason = result.error_msg
            await self.ws.send_log(
                f"[{case.case_id}] {result.error_msg}", "warning")
            fail_log = "\n".join(confirm_err.outputs + [result.error_msg])
            syslog_block = await self._stop_syslog_capture(syslog_ctx)
            if syslog_block:
                fail_log = f"{fail_log}\n\n{syslog_block}"
            self._write_case_log(case, result, fail_log, log_file=log_file)

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

            # 保存异常现场（若已写过日志则追加，避免覆盖完整输出）
            log_content = f"[执行异常] {type(e).__name__}: {e}\n{tb}\n"
            if combined_outputs:
                log_content = "\n".join(combined_outputs) + "\n\n" + log_content
            # 异常现场也保留板端系统日志，便于定位驱动/内核问题
            syslog_block = await self._stop_syslog_capture(syslog_ctx)
            if syslog_block:
                log_content = f"{log_content}\n\n{syslog_block}"
            log_exists = bool(result.log_file and os.path.exists(result.log_file))
            self._write_case_log(
                case, result, log_content,
                log_file=result.log_file or log_file,
                append=log_exists,
            )
        finally:
            # 兜底清理：任何提前返回/异常都要停止板端后台采集进程
            await self._cleanup_syslog_capture(syslog_ctx)

        result.end_time = datetime.now()
        case.status = result.status
        case.ai_judged = getattr(result, "ai_judged", False)
        case.ai_status = getattr(result, "ai_status", "") or ""
        case.ai_confidence = getattr(result, "ai_confidence", 0.0) or 0.0
        case.ai_reason = getattr(result, "ai_reason", "") or ""
        case.ai_evidence = getattr(result, "ai_evidence", []) or []
        # AI 已给出明确结论时，实际结果统一展示 AI 证据摘要；
        # AI 未参与或要求人工确认时，保留特殊分支的原始 log 供人工核对。
        ai_decided = bool(getattr(result, "ai_judged", False)) and result.status in ("Pass", "Fail")
        if not ai_decided and hasattr(result, '_metadata_log') and result._metadata_log:
            case.actual_result = f"[待确认] 嵌入行信息 metadata log:\n{result._metadata_log}"
        elif not ai_decided and hasattr(result, '_sr_hs_log') and result._sr_hs_log:
            # sr/hs 用例：提取有效输出作为实际结果
            sr_hs_lines = []
            for line in self._strip_command_echoes(result._sr_hs_log).split('\n'):
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
            summary_passed = None if result.status == "Review" else (result.status == "Pass")
            case.actual_result = self._build_evidence_summary(result, summary_passed, is_fault_test=is_fault_test)
        return result

    async def _apply_ai_judgment(
        self,
        *,
        case: TestCase,
        result: TestResult,
        combined: str,
        last_exit_code: int,
    ) -> Tuple[Optional[bool], str, bool]:
        """AI 是唯一的判定引擎。

        规则引擎（ExpectedResultParser.match / FrameSyncChecker.check /
        _match_dl_elr_stages）已弃用：不产生 Pass/Fail，也不作为 AI 失败时的兜底。
        AI 未启用、调用失败、返回异常状态或 NEED_REVIEW 时统一转人工确认
        （``passed=None`` → Review）。

        返回 ``(passed, reason, ai_judge_attempted)``。
        """
        if not self._ai_service or not self._ai_service.enabled:
            reason = "[AI判定] AI 服务未启用，规则引擎已弃用，需人工确认"
            await self.ws.send_log(f"[{case.case_id}] {reason}", "warning")
            return None, reason, False

        await self._send_progress("正在 AI 分析判定结果")
        await self.ws.send_log(
            f"[{case.case_id}] AI 判定中（规则引擎已弃用）...", "info")
        try:
            ai_result = await asyncio.wait_for(
                self._ai_service.judge_result(
                    expected_text=case.expected_result,
                    actual_output=combined[-5000:],  # 截断避免 token 浪费
                    case_description=case.description,
                    test_steps=case.test_steps,
                    exit_code=last_exit_code,
                ),
                timeout=90,
            )

            ai_error = ai_result.get("_error") if ai_result else None
            if ai_error:
                reason = (f"[AI判定] 调用失败({ai_error})，"
                          f"规则引擎已弃用，需人工确认")
                await self.ws.send_log(
                    f"[{case.case_id}] AI 判定失败: {ai_error}", "warning")
                return None, reason, True

            if not ai_result:
                reason = "[AI判定] 未返回结果，规则引擎已弃用，需人工确认"
                await self.ws.send_log(
                    f"[{case.case_id}] AI 未返回判定结果", "warning")
                return None, reason, True

            ai_status = ai_result.get("status", "")
            ai_conf = ai_result.get("confidence", 0) or 0
            ai_reason_text = ai_result.get("reason", "") or ""
            ai_source = "AI(cached)" if ai_result.get("_from_cache") else "AI"

            if ai_status in ("Pass", "Fail"):
                passed = ai_status == "Pass"
                reason = (f"[AI判定] {ai_source}: {ai_status} "
                          f"(置信度={ai_conf:.2f}，{ai_reason_text})")
                result.ai_judged = True
                result.ai_status = ai_status
                result.ai_confidence = ai_conf
                result.ai_reason = ai_reason_text
                result.ai_evidence = ai_result.get("evidence") or []
                await self.ws.send_log(
                    f"[{case.case_id}] AI 判定: {ai_status} (置信度={ai_conf:.2f})",
                    "info")
                return passed, reason, True

            if ai_status == "NEED_REVIEW":
                reason = (f"[AI判定] {ai_source}: NEED_REVIEW "
                          f"(置信度={ai_conf:.2f}，{ai_reason_text})")
                result.ai_judged = True
                result.ai_status = ai_status
                result.ai_confidence = ai_conf
                result.ai_reason = ai_reason_text
                result.ai_evidence = ai_result.get("evidence") or []
                await self.ws.send_log(
                    f"[{case.case_id}] AI 判定: NEED_REVIEW (置信度={ai_conf:.2f})",
                    "warning")
                return None, reason, True

            reason = (f"[AI判定] 返回无法识别的状态({ai_status!r})，"
                      f"规则引擎已弃用，需人工确认")
            await self.ws.send_log(
                f"[{case.case_id}] AI 返回状态异常: {ai_status!r}", "warning")
            return None, reason, True
        except Exception as ai_err:
            reason = (f"[AI判定] 异常: {ai_err}，"
                      f"规则引擎已弃用，需人工确认")
            await self.ws.send_log(
                f"[{case.case_id}] AI 判定异常: {ai_err}", "warning")
            return None, reason, True

    @staticmethod
    def _strip_nvsipl_menu(text: str) -> str:
        """移除 nvsipl_camera 交互菜单提示行，避免菜单在日志中反复出现。

        只清理日志展示内容（如 ``Enter 'les' followed by sensor ID ...``
        以及配套的 ``-`` 分隔行），不影响判定与 AI 分析的输入。
        """
        if not text:
            return text
        kept = []
        for line in text.split("\n"):
            stripped = line.strip()
            if re.match(r"^Enter\s+['\"‘’“”]", stripped, re.IGNORECASE):
                continue
            if stripped == "-":
                continue
            kept.append(line)
        return "\n".join(kept)

    # ---------- 板端系统日志采集（Linux journalctl / QNX slog2info） ----------

    _SYSLOG_MAX_LINES = 2000
    _SYSLOG_MAX_CHARS = 300_000

    @staticmethod
    def _tool_exists_expr(tool: str) -> str:
        """返回一段 shell 条件表达式，用于判断板端是否可执行指定工具。"""
        return (
            f"command -v {tool} >/dev/null 2>&1 || "
            f"which {tool} >/dev/null 2>&1 || "
            f"[ -x /usr/bin/{tool} ] || [ -x /sbin/{tool} ] || "
            f"[ -x /proc/boot/{tool} ]"
        )

    async def _detect_syslog_backend(self) -> str:
        """检测板端可用的系统日志工具，返回 ``journalctl`` / ``slog2info`` / ``""``。

        结果按执行器实例缓存，避免每条用例都额外发一次探测命令。
        """
        if self._syslog_backend is not None:
            return self._syslog_backend

        mode = (
            getattr(self.workspace, "syslog_capture_mode", "auto") or "auto"
        ).strip().lower()
        candidates = (
            ["journalctl", "slog2info"] if mode == "auto" else [mode]
        )
        candidates = [c for c in candidates if c in ("journalctl", "slog2info")]

        backend = ""
        if candidates:
            checks = "\n".join(
                f"if {self._tool_exists_expr(tool)}; then echo {tool}; fi"
                for tool in candidates
            )
            try:
                _, stdout, _ = await self._ssh_execute(checks, timeout=15)
                found = [ln.strip() for ln in (stdout or "").splitlines() if ln.strip()]
                backend = found[0] if found else ""
            except Exception as e:
                if self.ws:
                    await self.ws.send_log(
                        f"系统日志工具检测失败: {e}", "warning")
                backend = ""

        self._syslog_backend = backend
        return backend

    async def _syslog_privilege_mode(self) -> str:
        """返回板端权限模式：``root`` / ``sudo`` / ``none``。"""
        cmd = (
            'uid=$(id -u 2>/dev/null); '
            'if [ "$uid" = "0" ]; then echo root; '
            'elif command -v sudo >/dev/null 2>&1 || which sudo >/dev/null 2>&1; '
            'then echo sudo; else echo none; fi'
        )
        _, stdout, _ = await self._ssh_execute(cmd, timeout=15)
        mode = (stdout or "").strip().splitlines()
        mode = mode[0].strip() if mode else "none"
        return mode if mode in ("root", "sudo", "none") else "none"

    def _sudo_password(self) -> str:
        """读取 SSH 配置中的板端密码（用于 sudo 提权）。"""
        if self.ssh and hasattr(self.ssh, "config"):
            config = self.ssh.config
            return (getattr(config, "target_password", "")
                    or getattr(config, "password", "") or "")
        return ""

    async def _start_syslog_capture(self, case_id: str) -> Optional[dict]:
        """在板端后台启动系统日志采集，返回采集上下文（未启用/不可用时返回 None）。

        做法：``journalctl -f`` / ``slog2info -w`` 持续写入 /tmp 临时文件，
        用例结束后停止进程、读回内容并清理临时文件。日志内容随后追加到
        该用例的 .log 文件，不参与 AI 判定，避免额外 token 消耗。
        """
        if not self.workspace:
            return None
        if not getattr(self.workspace, "syslog_capture_enabled", False):
            return None

        try:
            backend = await self._detect_syslog_backend()
        except Exception as e:
            if self.ws:
                await self.ws.send_log(
                    f"[{case_id}] 系统日志采集不可用: {e}", "warning")
            return None

        if not backend:
            if self.ws:
                await self.ws.send_log(
                    f"[{case_id}] 未检测到 journalctl / slog2info，已跳过系统日志采集",
                    "warning")
            return None

        import shlex

        try:
            priv_mode = await self._syslog_privilege_mode()
        except Exception:
            priv_mode = "none"

        extra = (getattr(self.workspace, "syslog_capture_extra_args", "") or "").strip()
        if backend == "journalctl":
            tool_cmd = f"journalctl -f -o short-iso {extra}".strip()
        else:
            # QNX slog2info：-w 持续跟踪输出；extra 可指定 -b 缓冲区等
            tool_cmd = f"slog2info {extra} -w".strip()

        safe_case = re.sub(r"[^A-Za-z0-9_.-]+", "_", case_id or "case")[:50]
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        base = f"/tmp/at_syslog_{safe_case}_{stamp}"
        log_path = f"{base}.log"
        pid_path = f"{base}.pid"
        pw_path = f"{base}.pw"
        log_q, pid_q, pw_q = (
            shlex.quote(log_path), shlex.quote(pid_path), shlex.quote(pw_path)
        )

        password = self._sudo_password()
        use_pw = bool(priv_mode == "sudo" and password)
        if priv_mode == "root":
            inner = f"{tool_cmd} < /dev/null"
        elif priv_mode == "sudo" and password:
            inner = f"sudo -S {tool_cmd} < {pw_q}"
        elif priv_mode == "sudo":
            # 无密码时尝试 NOPASSWD sudo，失败会在日志里体现
            inner = f"sudo -n {tool_cmd} < /dev/null"
        else:
            inner = f"{tool_cmd} < /dev/null"
        inner = f"{inner} > {log_q} 2>&1"

        # 采集前清空板端系统日志缓冲，保证日志只包含本次用例执行期间的内容。
        clear_lines: list = []
        if getattr(self.workspace, "syslog_capture_clear", True):
            if backend == "journalctl":
                # rotate 把当前 journal 归档，vacuum 删除归档，等效清空
                clear_targets = [
                    "journalctl --rotate",
                    "journalctl --vacuum-time=1s",
                ]
            else:
                # QNX：-c 清空 slog2 缓冲区（可用 -b 指定缓冲区）
                clear_targets = [f"slog2info {extra} -c".strip()]
            for target in clear_targets:
                if priv_mode == "sudo" and password:
                    clear_lines.append(
                        f"sudo -S {target} < {pw_q} >/dev/null 2>&1")
                elif priv_mode == "sudo":
                    clear_lines.append(
                        f"sudo -n {target} < /dev/null >/dev/null 2>&1")
                else:
                    clear_lines.append(
                        f"{target} >/dev/null 2>&1 < /dev/null")
            if self.ws:
                await self.ws.send_log(
                    f"[{case_id}] 采集前清空板端系统日志（{backend}）", "info")

        # 用 sh -c 记录 PID 后 exec，kill PID 即可精确停止采集进程。
        # trap '' HUP 防止 SSH 会话关闭时后台任务被挂断。
        script = f"trap '' HUP; echo $$ > {pid_q}; exec {inner}"
        start_cmd = "\n".join([
            f"rm -f {log_q} {pid_q} {pw_q}",
            (f"umask 077; printf '%s\\n' {shlex.quote(password)} > {pw_q}"
             if use_pw else "true"),
            *clear_lines,
            f"sh -c {shlex.quote(script)} >/dev/null 2>&1 < /dev/null &",
            "sleep 1",
            f"if [ -f {pid_q} ] && kill -0 $(cat {pid_q}) 2>/dev/null; "
            f"then echo started; else echo failed; fi",
        ])

        try:
            _, stdout, stderr = await self._ssh_execute(start_cmd, timeout=25)
        except Exception as e:
            if self.ws:
                await self.ws.send_log(
                    f"[{case_id}] 启动系统日志采集失败: {e}", "warning")
            return None

        if "started" not in (stdout or ""):
            detail = (stderr or "").strip() or (stdout or "").strip()
            if self.ws:
                await self.ws.send_log(
                    f"[{case_id}] 系统日志采集启动失败（{backend}）"
                    f"{(': ' + detail) if detail else ''}", "warning")
            # 清理可能残留的临时文件
            try:
                await self._ssh_execute(
                    f"rm -f {log_q} {pid_q} {pw_q}", timeout=10)
            except Exception:
                pass
            return None

        grep_pattern = (
            getattr(self.workspace, "syslog_capture_grep", "") or ""
        ).strip()
        filter_note = f"，过滤: {grep_pattern}" if grep_pattern else ""
        if self.ws:
            await self.ws.send_log(
                f"[{case_id}] 开始采集板端系统日志（{backend}{filter_note}）", "info")

        return {
            "backend": backend,
            "log_path": log_path,
            "pid_path": pid_path,
            "pw_path": pw_path if use_pw else "",
            "case_id": case_id,
            "grep": grep_pattern,
            "done": False,
        }

    async def _stop_syslog_capture(self, ctx: Optional[dict]) -> str:
        """停止采集并读回日志，返回可直接写入用例日志的文本块。"""
        if not ctx or ctx.get("done"):
            return ""

        ctx["done"] = True
        import shlex
        log_q = shlex.quote(ctx["log_path"])
        pid_q = shlex.quote(ctx["pid_path"])
        pw_q = shlex.quote(ctx["pw_path"]) if ctx.get("pw_path") else ""

        text = ""
        try:
            # 终止后台采集进程（journalctl/slog2info 由 exec 接管 PID）
            await self._ssh_execute(
                f"if [ -f {pid_q} ]; then P=$(cat {pid_q} 2>/dev/null); "
                f"kill $P 2>/dev/null; sleep 0.3; kill -9 $P 2>/dev/null; fi",
                timeout=15,
            )
            # 读取日志：普通用户可读直接 cat，root 所有的文件用 sudo 读回。
            # 配置了过滤关键字时在板端直接 grep，避免回传大量无关日志。
            grep_pattern = (ctx.get("grep") or "").strip()
            if grep_pattern:
                pat_q = shlex.quote(grep_pattern)
                if pw_q:
                    read_cmd = (
                        f"if cat {log_q} >/dev/null 2>&1; then cat {log_q}; "
                        f"else sudo -S cat {log_q} < {pw_q} 2>/dev/null; fi "
                        f"| grep -e {pat_q}"
                    )
                else:
                    read_cmd = f"cat {log_q} 2>/dev/null | grep -e {pat_q}"
            elif pw_q:
                read_cmd = (
                    f"if cat {log_q} >/dev/null 2>&1; then cat {log_q}; "
                    f"else sudo -S cat {log_q} < {pw_q} 2>/dev/null; fi"
                )
            else:
                read_cmd = f"cat {log_q} 2>/dev/null"
            _, stdout, _ = await self._ssh_execute(read_cmd, timeout=30)
            text = (stdout or "").strip()
        except Exception as e:
            if self.ws:
                await self.ws.send_log(
                    f"[{ctx.get('case_id', '')}] 读取系统日志失败: {e}", "warning")
        finally:
            try:
                await self._ssh_execute(
                    f"rm -f {log_q} {pid_q} {pw_q}", timeout=10)
            except Exception:
                pass

        grep_pattern = (ctx.get("grep") or "").strip()
        filter_note = f", grep {grep_pattern}" if grep_pattern else ""
        header = f"===== 板端系统日志 ({ctx['backend']}{filter_note}) ====="
        if not text:
            reason = (
                f"（用例执行期间未采集到包含「{grep_pattern}」的日志）"
                if grep_pattern
                else "（用例执行期间未采集到日志，可能无权限或日志服务未运行）"
            )
            block = f"{header}\n{reason}"
        else:
            lines = text.splitlines()
            truncated = False
            if len(lines) > self._SYSLOG_MAX_LINES:
                lines = lines[-self._SYSLOG_MAX_LINES:]
                truncated = True
            body = "\n".join(lines)
            if len(body) > self._SYSLOG_MAX_CHARS:
                body = body[-self._SYSLOG_MAX_CHARS:]
                truncated = True
            block = f"{header}\n"
            if truncated:
                block += (
                    f"（日志过长，仅保留最后 {self._SYSLOG_MAX_LINES} 行）\n")
            block += body

        if self.ws:
            line_count = len(text.splitlines()) if text else 0
            filter_msg = (
                f"，过滤关键字: {grep_pattern}" if grep_pattern else "")
            await self.ws.send_log(
                f"[{ctx.get('case_id', '')}] 板端系统日志采集完成，共 {line_count} 行"
                f"（{ctx['backend']}{filter_msg}）", "info")
        return block

    async def _cleanup_syslog_capture(self, ctx: Optional[dict]):
        """兜底清理：异常/提前返回时确保后台采集进程与临时文件被清除。"""
        if not ctx or ctx.get("done"):
            return
        await self._stop_syslog_capture(ctx)

    def _write_case_log(self, case: TestCase, result: TestResult, content: str,
                        log_file: str = "", append: bool = False) -> str:
        """保存单个用例的实际执行日志，并同步路径到 TestCase/TestResult。"""
        if not log_file:
            log_file = (
                f"{self.log_dir}/{case.case_id}_"
                f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            )
        try:
            os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
            content = self._strip_nvsipl_menu(content or "")
            with open(log_file, "a" if append else "w", encoding="utf-8") as f:
                f.write(content or "")
        except Exception as exc:
            # 日志保存失败不应影响测试执行与判定
            print(f"[WARN] 保存用例日志失败 {log_file}: {exc}")
            return ""
        result.log_file = log_file
        case.log_file = log_file
        return log_file

    @staticmethod
    def _strip_command_echoes(text: str) -> str:
        """移除日志中的命令回显行（以 ``$ `` 开头）。

        命令回显只用于执行日志展示，不参与预期匹配、证据提取与 AI 判定。
        """
        return "\n".join(
            line for line in text.split("\n") if not line.startswith("$ ")
        )

    def preview_commands(self, case: TestCase, ai_parsed_steps=None) -> dict:
        """预览某条用例将要下发到远端的命令（不连接 SSH、不执行任何命令）。

        解析流程与 _execute_single 保持一致：
        NA 判定 → 规则解析 → AI 缓存替换未识别步骤 → nvsipl 交互合并
        → 执行模式判定 → 命令改写。
        出于安全考虑，展示的命令不包含 sudo 密码，仅标注「执行时自动注入」。
        """
        case_key = case.case_key or f"{case.source_sheet}:{case.row_number}:{case.case_id}"
        result = {
            "case_id": case.case_id,
            "case_key": case_key,
            "description": case.description,
            "na": False,
            "na_reason": "",
            "mode": "",
            "mode_label": "",
            "prerequisites_enabled": bool(
                getattr(self.workspace, "run_prerequisites", True)
            ),
            "prerequisites": [],
            "steps": [],
            "unrecognized_count": 0,
            "ai_cache_used": False,
            "notes": [],
            "error": "",
        }

        # NA 用例不会执行任何命令
        is_na, na_reason = CommandParser.should_mark_na(
            case.test_steps, case.expected_result,
            case.prerequisites, case.description,
        )
        if is_na:
            result.update(
                na=True,
                na_reason=na_reason,
                mode="na",
                mode_label="不执行（NA）",
                notes=[f"判定为 NA（{na_reason}），该用例不会下发任何命令。"],
            )
            return result

        # 前置条件在执行时按 ; 拆分并原样下发（MANUAL_CONFIRM 除外）
        for item in (case.prerequisites or "").split(";"):
            item = item.strip()
            if not item:
                continue
            if item.startswith(CommandParser.MANUAL_CONFIRM_PREFIX):
                result["prerequisites"].append({
                    "command": item[len(CommandParser.MANUAL_CONFIRM_PREFIX):].strip(),
                    "manual_confirm": True,
                })
            else:
                result["prerequisites"].append({
                    "command": item,
                    "manual_confirm": False,
                })

        default_remote_path = getattr(self.workspace, "default_remote_path", "") or ""
        steps = CommandParser.parse(case.test_steps, default_remote_path=default_remote_path)

        # AI 兜底：只使用预解析缓存，预览阶段不触发实时 AI 调用
        has_unrecognized = any(
            s.kind == "skip" and "未识别步骤" in s.description for s in steps
        )
        ai_steps = (ai_parsed_steps or {}).get(case_key)
        if has_unrecognized and ai_steps:
            steps = CommandParser.apply_ai_parsed_steps(
                steps, ai_parsed_steps or {}, case_key
            )
            result["ai_cache_used"] = True

        result["unrecognized_count"] = sum(
            1 for s in steps
            if s.kind == "skip" and "未识别步骤" in s.description
        )

        # 统一执行器只有一种模式：多终端持久化 Shell。
        # 终端数量仅用于给用户提示，不再影响执行分支。
        terminals: list = []
        for s in steps:
            label = s.terminal or "终端A"
            if label not in terminals:
                terminals.append(label)
        has_blocking_nvsipl = any(
            s.kind == "command" and CommandParser.is_blocking_nvsipl(s.command)
            for s in steps
        )
        mode = "unified_shell"
        mode_label = "统一执行器（多终端持久化 Shell）"
        result["mode"] = mode
        result["mode_label"] = mode_label
        result["terminals"] = terminals

        notes = [
            f"所有步骤在持久化 Shell 会话中执行，共 {len(terminals)} 个终端："
            + "、".join(terminals) + "。",
            "环境变量、工作目录与 sudo 凭证在各自终端会话内保留，不再拼接 cd 前缀。",
        ]
        if has_blocking_nvsipl:
            notes.append(
                "存在阻塞型 nvsipl_camera（无 -r）：启动后立即返回，"
                "后续步骤继续向该终端注入交互输入，用例结束时统一退出。")
        result["notes"].extend(notes)
        if not result["prerequisites_enabled"]:
            result["notes"].append("工作区已关闭「执行前置条件」，前置条件不会下发。")
        if result["unrecognized_count"] > 0:
            result["notes"].append(
                f"有 {result['unrecognized_count']} 个步骤未识别为命令，执行时会被跳过；"
                "可先用「AI 解析步骤」补充后再预览。"
            )

        def finalize(raw_cmd: str, current_work_dir: str):
            """返回 (实际下发命令, 改写说明, 是否需要 TTY)。"""
            notes = []
            shell_cmd = self._normalize_quotes(raw_cmd)

            before = shell_cmd
            shell_cmd = self._apply_nito_override(shell_cmd)
            if shell_cmd != before:
                notes.append("--nito 路径已按工作区配置覆盖")

            before = shell_cmd
            shell_cmd = self._apply_image_path_override(shell_cmd)
            if shell_cmd != before:
                notes.append("-f 图片路径已按工作区配置覆盖")

            if re.search(r"\bsudo\b", shell_cmd):
                notes.append("执行时自动注入 sudo 密码")

            is_nvsipl = CommandParser.is_nvsipl_camera_command(raw_cmd)
            if is_nvsipl:
                if CommandParser.is_blocking_nvsipl(raw_cmd):
                    notes.append(
                        "阻塞型 nvsipl（无 -r）：启动后立即返回，"
                        "后续交互输入按步骤发送给该终端")
                else:
                    notes.append("nvsipl 会自动退出，执行后回收退出码")
            # 持久会话内已 cd 过，命令不再拼接 cd 前缀
            return shell_cmd, notes, is_nvsipl

        work_dir = default_remote_path
        capture_idx = 0
        rows = []
        for idx, step in enumerate(steps, 1):
            row = {
                "index": idx,
                "step_num": step.step_num,
                "kind": step.kind,
                "action": "skip",
                "terminal": step.terminal,
                "description": step.description,
                "raw_command": step.command,
                "command": "",
                "notes": [],
                "needs_tty": False,
                "wait_seconds": float(getattr(step, "wait_seconds", 0.0) or 0.0),
            }

            if step.kind == "command":
                command, notes, needs_tty = finalize(step.command, work_dir)
                if (command.strip().startswith("export ")
                        and "CAM_ROTATE_CFG_PATH" in command
                        and getattr(self.workspace, "cam_rotate_cfg_enabled", False)
                        and getattr(self.workspace, "cam_rotate_cfg_path", "")):
                    command = (
                        f"export CAM_ROTATE_CFG_PATH="
                        f"{self.workspace.cam_rotate_cfg_path}"
                    )
                    notes.append("CAM_ROTATE_CFG_PATH 已按工作区配置覆盖")
                if needs_tty:
                    injected = self._inject_capture_name(
                        command, capture_idx, ["default", "rotate"]
                    )
                    if injected != command:
                        notes.append("拍照文件名前缀已自动补充")
                    command = injected
                    capture_idx += 1
                row.update(
                    action="execute", command=command,
                    notes=notes, needs_tty=needs_tty,
                )
            elif step.kind in ("enter_dir", "cd"):
                work_dir = step.command
                row.update(
                    action="change_dir",
                    command=f"cd {step.command}",
                    notes=["后续命令将在该目录下执行"],
                )
            elif step.kind == "wait":
                row.update(
                    action="wait",
                    notes=[f"在此等待 {self._format_wait(step.wait_seconds)}"],
                )
            elif step.kind == "nvsipl_input":
                row.update(
                    action="input",
                    command=step.command,
                    notes=[f"发送给 {step.terminal} 上运行的前台程序"],
                )
            elif step.kind == "manual":
                row.update(
                    action="manual",
                    notes=["人工操作步骤，不会自动下发"],
                )
            elif step.kind == "confirm":
                row.update(
                    action="confirm",
                    notes=["执行到此步骤时弹出人工确认"],
                )
            elif step.kind in ("repeat", "repeat_stream"):
                row.update(action="repeat")
                if step.kind == "repeat_stream":
                    row["notes"].append(
                        f"反复起流 {step.command} 次"
                        if step.command.isdigit() else "反复起流指令"
                    )
                if step.kind == "repeat":
                    row["notes"].append("执行到此步骤时回跳并再执行一次")
                else:
                    row["notes"].append("执行到此步骤时回到起流命令重新起一轮")
            else:  # skip
                row["notes"].append(step.description or "已跳过")

            # 步骤执行完成后需要等待时，在预览里标注
            if row["kind"] != "wait" and row["wait_seconds"] > 0:
                row["notes"].append(
                    f"执行后等待 {self._format_wait(row['wait_seconds'])}")

            rows.append(row)

        result["steps"] = rows
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

    # ------------------------------------------------------------------
    # 统一执行器：多终端持久化 Shell
    # ------------------------------------------------------------------
    async def _execute_unified(self, case, steps, work_dir, is_fault_test=False):
        """逐步执行测试步骤，所有命令都跑在按终端标签复用的持久化 shell 里。

        设计要点：
        - 每个终端标签（终端A/终端B/……）一个长期存活的交互式会话，
          环境变量、工作目录、sudo 凭证在会话内自然保留；
        - 阻塞的前台程序（无 -r 的 nvsipl_camera）在 ``launch()`` 后立即返回，
          由后续步骤继续向该终端注入交互输入，最后一个终端收尾时统一退出；
        - 交互输入按 ``_NVSIPL_INPUT_EXPECT`` 表等待特征输出，不在执行器里
          硬编码具体子命令语义；
        - 返回值与旧实现一致：``(combined_outputs, last_exit_code, last_cmd, raw)``，
          其中 log 按 ``parts`` 分段，日志侧按终端汇总。
        """
        from app.core.terminal_session import TerminalPool

        parts: list = []          # 供日志使用的分段文本
        terminal_logs: dict = {}  # 终端标签 → 该终端的全部输出
        seq_outputs: list = []    # 供判定/AI 使用的按时间序输出
        last_exit_code = 0
        last_cmd = ""

        async def _log(message: str, level: str = "info"):
            await self.ws.send_log(f"[{case.case_id}] {message}", level)

        last_seq_label = {"label": None}  # 时间序输出里当前分段对应的终端

        async def _record(label: str, text: str):
            """把某终端的输出追加到日志分段与判定输入。"""
            if not text:
                return
            terminal_logs.setdefault(label, []).append(text)
            # 时间序输出只在终端切换处插入分段标记，避免同一终端反复打断
            if last_seq_label["label"] != label:
                seq_outputs.append(f"----- [{label}] -----")
                last_seq_label["label"] = label
            seq_outputs.append(text)

        pool = TerminalPool(
            self.ssh,
            work_dir=work_dir,
            driver_export=self._driver_lib_path_export(),
            # 持久会话内 sudo -n 依赖会话级凭证缓存，建立终端时先缓存一次
            setup_commands=[self._sudo_cache_command()],
            on_log=_log,
        )

        async def _dropdown_nvsipl_cmd() -> None:
            """收尾：长时间前台运行的程序统一尝试正常退出，失败再中断终端。"""
            for label in pool.labels():
                shell = pool.get_existing(label)
                if shell is None or not shell.busy:
                    continue
                try:
                    await shell.send("q")
                    exit_code, out = await shell.wait_exit(timeout=20)
                    await _record(label, out)
                    if exit_code not in (0, -1):
                        await _log(f"[{label}] nvsipl 退出码 {exit_code}", "warning")
                except Exception as exc:
                    await _log(f"[{label}] 退出前台程序失败: {exc}", "warning")
                    await shell.interrupt()

        capture_idx = 0

        # 循环控制：repeat / repeat_stream 通过回跳 pc 实现，不复制步骤列表。
        # 计数器键为「循环指令自身的位置」，因此回跳后再次到达同一指令时可判断轮数。
        loop_rounds: dict = {}
        stream_rounds: dict = {}
        pc = 0
        total = len(steps)
        while pc < total:
            if self._stop:
                await _log("执行被用户停止", "warning")
                break

            step = steps[pc]
            index = pc + 1
            label = step.terminal or "终端A"

            try:
                if step.kind == "wait":
                    await self._send_progress(self._step_progress_message(
                        "正在等待", index, total))
                    await self._wait_step_delay(case, step)
                    pc += 1
                    continue

                if step.kind == "skip":
                    await _log(step.description, "info")
                    await self._wait_step_delay(case, step)
                    pc += 1
                    continue

                if step.kind == "manual":
                    await _log(f"需人工操作：{step.description}（已跳过自动执行）", "warning")
                    await self._wait_step_delay(case, step)
                    pc += 1
                    continue

                if step.kind in ("enter_dir", "cd"):
                    await self._send_progress(self._step_progress_message(
                        "正在切换目录", index, total, step.command))
                    shell = await pool.get(label)
                    exit_code, out = await shell.set_cwd(step.command)
                    await _record(label, out)
                    if exit_code != 0:
                        await _log(
                            f"[{label}] 切换工作目录失败: {step.command}", "warning")
                    else:
                        await _log(f"[{label}] 切换工作目录 -> {step.command}", "info")
                    await self._wait_step_delay(case, step)
                    pc += 1
                    continue

                if step.kind == "confirm":
                    ok = await self.ws.request_manual_confirm(step.description)
                    if not ok:
                        raise ManualConfirmFailed(
                            step.description, seq_outputs)
                    await self._wait_step_delay(case, step)
                    pc += 1
                    continue

                if step.kind == "repeat":
                    # 「重复2-4步骤」= 再执行一次，共 2 轮。
                    # 计数器按指令自身位置记录，第 1 次到达时回跳块首，
                    # 第 2 次到达时顺序越过（不再回跳），避免无限循环。
                    start_num, end_num = self._parse_repeat_range(step.command)
                    target = self._find_pc_by_step_num(steps, start_num)
                    if target is None or target >= pc:
                        await _log(
                            f"重复指令范围无效（{step.command}），已跳过", "warning")
                        pc += 1
                        continue
                    done = loop_rounds.get(pc, 0)
                    if done >= 1:
                        loop_rounds.pop(pc, None)
                        pc += 1
                        continue
                    loop_rounds[pc] = done + 1
                    await _log(
                        f"重复执行步骤 {start_num}-{end_num} 一次", "info")
                    pc = target
                    continue

                if step.kind == "repeat_stream":
                    # 「反复起流 N 次」：回到起流命令重新起流，
                    # 每轮结束后顺序回到本指令判断剩余轮数。
                    count = int(step.command) if step.command.isdigit() else 1
                    target = self._find_previous_nvsipl_pc(steps, pc)
                    if target is None:
                        await _log("反复起流指令前没有可重复的起流命令，已跳过", "warning")
                        pc += 1
                        continue
                    done = stream_rounds.get(pc, 0)
                    if done >= count - 1:
                        stream_rounds.pop(pc, None)
                        pc += 1
                        continue
                    stream_rounds[pc] = done + 1
                    await _log(
                        f"反复起流 第 {done + 2}/{count} 轮", "info")
                    pc = target
                    continue

                if step.kind == "command":
                    await self._send_progress(self._step_progress_message(
                        "正在执行命令", index, total, step.command))
                    shell = await pool.get(label)
                    shell_cmd = self._prepare_step_command(
                        step.command, capture_idx)
                    is_nvsipl = CommandParser.is_nvsipl_camera_command(step.command)
                    blocking = CommandParser.is_blocking_nvsipl(step.command)
                    if is_nvsipl:
                        capture_idx += 1
                    last_cmd = shell_cmd
                    seq_outputs.append(f"$ [{label}] {shell_cmd}")
                    await _log(f"[{label}] 执行: {shell_cmd}", "info")
                    await _record(label, f"$ {shell_cmd}")

                    if blocking:
                        # 阻塞型前台程序：启动后立即返回，后续步骤继续注入交互
                        out = await shell.launch(
                            shell_cmd, timeout=25,
                            stop_pattern=r"Enter\s+'gc|" + _REAL_FPS_PATTERN)
                        await _record(label, out)
                        if _nvsipl_has_real_error(out, is_fault_test=is_fault_test):
                            await _log(
                                f"[{label}] nvsipl 启动失败: {out[-200:]}", "error")
                            last_exit_code = 1
                        else:
                            await _log(f"[{label}] 前台程序已启动", "info")
                    else:
                        exit_code, out = await shell.run(
                            shell_cmd, timeout=self._command_timeout(step))
                        last_exit_code = exit_code
                        await _record(label, out)
                        key_lines = self._extract_key_output_lines(out)
                        if key_lines:
                            await _log(f"[{label}] 命令关键输出:\n{key_lines}", "info")
                        if exit_code != 0:
                            await _log(
                                f"[{label}] 命令返回码非0: exit_code={exit_code}",
                                "warning")

                    await self._wait_step_delay(case, step)
                    pc += 1
                    continue

                if step.kind == "nvsipl_input":
                    shell = await pool.get(label)
                    for sub_cmd in step.command.split(";"):
                        sub_cmd = sub_cmd.strip()
                        if not sub_cmd:
                            continue
                        await self._send_progress(self._step_progress_message(
                            "正在发送交互输入", index, total, sub_cmd))
                        await _log(f"[{label}] 发送: {sub_cmd}", "info")
                        seq_outputs.append(f"$ [{label}] {sub_cmd}")
                        await _record(label, f"$ {sub_cmd}")

                        if sub_cmd.lower() == "q":
                            # 退出前台程序，等待其退出并回收退出码
                            await shell.send("q")
                            exit_code, out = await shell.wait_exit(
                                timeout=20, stop_pattern=r"Deinit|quit|exit")
                            if exit_code not in (0, -1):
                                last_exit_code = exit_code
                            await _record(label, out)
                            continue

                        key = sub_cmd.split()[0].lower()
                        pattern, timeout_sec = _NVSIPL_INPUT_EXPECT.get(
                            key, (None, 8.0))
                        if shell.busy:
                            # 前台程序仍在运行：输入直接写进它的 stdin（不追加 RC 标记）
                            await shell.send(sub_cmd)
                            out = await shell.read_until(
                                pattern, timeout=timeout_sec,
                                quiet=None if pattern else 1.0)
                        else:
                            # 前台程序已退出（或该终端当前是普通 shell）：
                            # 按普通命令执行，保证退出码可回收
                            exit_code, out = await shell.run(
                                sub_cmd, timeout=timeout_sec)
                            if exit_code != 0:
                                last_exit_code = exit_code
                        await _record(label, out)
                        if key == "gc":
                            if _has_real_fps(out):
                                await _log(f"[{label}] 出帧正常", "info")
                            else:
                                await _log(
                                    f"[{label}] gc 后未检测到帧率输出", "warning")
                    await self._wait_step_delay(case, step)
                    pc += 1
                    continue

                # 未知类型：记录后跳过，不中断用例
                await _log(f"未处理的步骤类型 {step.kind}，已跳过", "warning")
                pc += 1

            except ManualConfirmFailed:
                await _dropdown_nvsipl_cmd()
                raise
            except (OSError, EOFError) as exc:
                # 终端断开：重建该终端后继续，避免单点故障拖垮整条用例
                await _log(f"[{label}] 终端异常: {exc}，尝试重建会话", "warning")
                try:
                    await pool.get(label)
                except Exception as rebuild_err:
                    await _log(
                        f"[{label}] 重建会话失败: {rebuild_err}", "error")
                    last_exit_code = -1
                    pc += 1
                    continue
                pc += 1

        await _dropdown_nvsipl_cmd()
        await pool.close_all()

        # 日志按终端分组，判定输入按时间序（seq_outputs 已带终端标记）
        blocks = []
        for label, chunks in terminal_logs.items():
            blocks.append(f"===== {label} =====\n" + "\n".join(c for c in chunks if c))
        terminal_log = "\n\n".join(blocks)
        seq_raw = "\n".join(seq_outputs)
        return seq_outputs, last_exit_code, last_cmd, terminal_log

    @staticmethod
    def _parse_repeat_range(command: str) -> Tuple[int, int]:
        """解析重复指令的步骤范围 ``"2-4"``。"""
        match = re.match(r'(\d+)-(\d+)', (command or "").strip())
        if not match:
            return 0, 0
        return int(match.group(1)), int(match.group(2))

    @staticmethod
    def _find_pc_by_step_num(steps, step_num: int) -> Optional[int]:
        """按原始步骤编号定位程序计数器。"""
        for idx, step in enumerate(steps):
            if step.step_num >= step_num:
                return idx
        return None

    @staticmethod
    def _find_previous_nvsipl_pc(steps, pc: int) -> Optional[int]:
        """找到「反复起流」指令之前最近的起流命令位置。"""
        for idx in range(pc - 1, -1, -1):
            if CommandParser.is_nvsipl_camera_command(steps[idx].command or ""):
                return idx
        return None

    @staticmethod
    def _command_timeout(step) -> float:
        """单条命令的等待上限：按步骤等待时长放宽，最少 60 秒。"""
        wait = float(getattr(step, "wait_seconds", 0.0) or 0.0)
        return max(60.0, wait + 30.0)

    def _sudo_cache_command(self) -> str:
        """生成缓存 sudo 凭证的命令（持久会话内只需执行一次）。"""
        import shlex
        if not self.ssh or not hasattr(self.ssh, "config"):
            return ""
        config = self.ssh.config
        password = (getattr(config, "target_password", "")
                    or getattr(config, "password", ""))
        if not password:
            return ""
        escaped = shlex.quote(password)
        return f"echo {escaped} | sudo -S -v 2>/dev/null; true"

    def _prepare_step_command(self, command: str, capture_idx: int) -> str:
        """命令改写链：引号归一 → 路径覆盖 → sudo 注入 → 拍照命名。"""
        shell_cmd = self._normalize_quotes(command)
        shell_cmd = self._apply_nito_override(shell_cmd)
        shell_cmd = self._apply_image_path_override(shell_cmd)

        # CAM_ROTATE_CFG_PATH 环境变量按工作区配置覆盖
        if shell_cmd.strip().startswith("export ") and "CAM_ROTATE_CFG_PATH" in shell_cmd:
            if (self.workspace
                    and getattr(self.workspace, "cam_rotate_cfg_enabled", False)
                    and getattr(self.workspace, "cam_rotate_cfg_path", "")):
                shell_cmd = (
                    f"export CAM_ROTATE_CFG_PATH="
                    f"{self.workspace.cam_rotate_cfg_path}")

        # 持久会话中 stdin 仍是 PTY；凭证已在终端建立时缓存过，
        # 这里只把 sudo 换成 sudo -n，避免每条命令都重复注入密码
        shell_cmd = self._apply_sudo_password(shell_cmd, pty_mode=True)
        # pty_mode 会前置「echo <pwd> | sudo -S -v 2>/dev/null; 」缓存凭证，
        # 该动作已由 _sudo_cache_command 在各终端建立时完成，这里去掉重复部分。
        shell_cmd = re.sub(
            r'^echo\s+(?:\'[^\']*\'|"[^"]*"|\S+)\s*\|\s*sudo -S -v 2>/dev/null;\s*',
            '', shell_cmd)
        if CommandParser.is_nvsipl_camera_command(shell_cmd):
            shell_cmd = self._inject_capture_name(
                shell_cmd, capture_idx, ["default", "rotate"])
        return shell_cmd

    @staticmethod
    def _normalize_quotes(cmd: str) -> str:
        """Replace Chinese/fullwidth quotes with ASCII equivalents."""
        cmd = cmd.replace('\u201c', '"').replace('\u201d', '"')
        cmd = cmd.replace('\u2018', "'").replace('\u2019', "'")
        cmd = cmd.replace('\uff02', '"')
        cmd = cmd.replace('\u300c', '"').replace('\u300d', '"')
        return cmd

    @staticmethod
    def _build_evidence_summary(result, passed: Optional[bool], is_fault_test: bool = False) -> str:
        """\u4ece\u6267\u884c\u7ed3\u679c\u548c\u5339\u914d\u539f\u56e0\u4e2d\u63d0\u53d6\u5173\u952e\u8bc1\u636e\u6458\u8981\u3002

        \u751f\u6210\u683c\u5f0f: [Pass/Fail/\u5f85\u786e\u8ba4] \u5224\u5b9a\u4f9d\u636e | \u5173\u952e\u8f93\u51fa\u884c
        \u82e5\u7531 AI \u5224\u5b9a\uff0c\u5c55\u793a AI \u5224\u5b9a\u72b6\u6001\u3001\u7406\u7531\u4e0e\u8bc1\u636e\u660e\u7ec6\u3002
        \u7528\u4e8e\u524d\u7aef\u5c55\u793a\u548c Excel \u56de\u5199\uff0c\u4f7f\u5224\u5b9a\u4f9d\u636e\u4e00\u76ee\u4e86\u7136\u3002
        """
        import re

        status_label = "[Pass]" if passed is True else ("[\u5f85\u786e\u8ba4]" if passed is None else "[Fail]")
        # \u5b9e\u9645\u7ed3\u679c\u6587\u672c\u4e0d\u5c55\u793a\u547d\u4ee4\u56de\u663e\uff08\u547d\u4ee4\u4ec5\u4fdd\u7559\u5728\u65e5\u5fd7\u6587\u4ef6\u4e2d\uff09
        actual = ExecutorAdapter._strip_command_echoes(result.actual_output or "")
        reason = result.match_reason or ""
        error_msg = result.error_msg or ""

        # --- Part 1: \u5224\u5b9a\u4f9d\u636e\uff08AI \u4f18\u5148\uff0c\u5176\u6b21 match_reason\uff09---
        reason_summary = ""
        ai_judged = getattr(result, "ai_judged", False)
        ai_reason = getattr(result, "ai_reason", "") or ""
        if ai_judged:
            ai_status = getattr(result, "ai_status", "") or ""
            reason_text = ai_reason or "(AI 未提供文字说明)"
            evidence = [
                str(item).strip()
                for item in (getattr(result, "ai_evidence", []) or [])
                if str(item).strip()
            ]
            summary = f"{status_label} [AI判定] {ai_status} 判定依据: {reason_text}"
            if evidence:
                summary += "\nAI证据:\n" + "\n".join(f"- {line}" for line in evidence)
            return summary[:2000]
        elif passed is not True and error_msg:
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
                # Pass \u65f6\u8df3\u8fc7"\u5ffd\u7565\u9000\u51fa\u7801"\u7c7b\u964d\u7ea7\u4fe1\u606f\uff08\u5df2\u901a\u8fc7\u5c31\u4e0d\u9700\u8981\u5c55\u793a\uff09
                if passed and "\u5ffd\u7565\u9000\u51fa\u7801" in item:
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
                # \u4fdd\u7559\u9519\u8bef\u4fe1\u606f\uff08\u4ec5 Fail \u65f6\uff09
                elif not passed and ("\u9519\u8bef" in item or "Fail" in item or "\u975e0" in item):
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
            elif is_fault_test:
                # \u6545\u969c\u6d4b\u8bd5\uff1a\u5b8c\u6574\u622a\u53d6\u542b ERROR/FAULT/error \u7684\u884c\u4f5c\u4e3a\u8bc1\u636e
                # \u8fd9\u4e9b error \u662f\u9884\u671f\u884c\u4e3a\uff0c\u9700\u8981\u5728\u7ed3\u679c\u4e2d\u5c55\u793a
                error_lines = []
                for line in output_lines:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    if stripped.startswith("Enter '") or stripped in ('-', 'Output', 'gc 0', 'q'):
                        continue
                    # \u63d0\u53d6\u542b ERROR/FAULT/fault/error \u7684\u884c\uff08\u6545\u969c\u62a5\u51fa\u8bc1\u636e\uff09
                    if re.search(r'(ERROR|FAULT|error|fault)', stripped, re.IGNORECASE):
                        error_lines.append(stripped)
                    # \u4e5f\u4fdd\u7559\u5e27\u7387\u884c
                    elif re.search(r'rate\s*\(fps\)\s*:\s+[\d.]+', stripped):
                        error_lines.append(stripped)
                if error_lines:
                    evidence_lines = error_lines[:30]  # \u6545\u969c\u6d4b\u8bd5\u5141\u8bb8\u66f4\u591a error \u884c
                else:
                    # \u6ca1\u627e\u5230 error \u884c\uff0c\u53d6\u8f93\u51fa\u5c3e\u90e8
                    tail = [l.strip() for l in output_lines[-15:] if l.strip()]
                    evidence_lines = tail[-10:]
            elif passed:
                # Pass: \u63d0\u53d6\u5e27\u7387\u884c\u3001\u50cf\u7d20\u4fe1\u606f\u3001\u6210\u529f\u6807\u5fd7\u3001\u751f\u6210\u6587\u4ef6\u3001Sensor\u7edf\u8ba1
                for line in output_lines:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    # \u5e27\u7387\u884c\uff08\u517c\u5bb9 PTY \u622a\u65ad\uff0c\u5982 "e rate (fps): 29.5"\uff09
                    if re.search(r'rate\s*\(fps\)\s*:\s+[\d.]+', stripped):
                        evidence_lines.append(stripped)
                    elif re.search(r'(Vertical|horizontal|active_[wh]|active\s*=|pixel)',
                                   stripped, re.IGNORECASE):
                        evidence_lines.append(stripped)
                    # \u751f\u6210\u6587\u4ef6\u8def\u5f84
                    elif re.search(r'\.(raw|yuv|png|jpg|bmp|h264|hevc)\b', stripped):
                        evidence_lines.append(stripped)
                    # \u6210\u529f\u6807\u5fd7
                    elif re.search(r'(SUCCESS|success|PASSED|streaming started)', stripped):
                        evidence_lines.append(stripped)
                    # Sensor \u7edf\u8ba1\u884c\uff08Frame captured / drops\uff09
                    elif re.search(r'Frame captured:\s+\d+', stripped):
                        evidence_lines.append(stripped)
                    # \u6587\u4ef6\u68c0\u67e5/\u6587\u4ef6\u6570\u91cf\u68c0\u67e5\u7ed3\u679c
                    elif re.search(r'\[\u6587\u4ef6(?:\u68c0\u67e5|\u6570\u91cf\u68c0\u67e5)\]', stripped):
                        evidence_lines.append(stripped)
                    if len(evidence_lines) >= 8:
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
                # Fail: \u5148\u63d0\u53d6 fps \u884c\uff08\u5e27\u7387\u68c0\u6d4b\u5931\u8d25\u65f6\u76f4\u63a5\u5c55\u793a\u5b9e\u9645 fps \u6570\u636e\uff09
                fps_evidence = []
                for line in output_lines:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    if re.search(r'rate\s*\(fps\)\s*:\s+[\d.]+', stripped):
                        fps_evidence.append(stripped)
                if fps_evidence:
                    evidence_lines.extend(fps_evidence[:6])

                # \u518d\u63d0\u53d6\u9519\u8bef\u884c\u53ca\u4e0a\u4e0b\u6587
                for idx, line in enumerate(output_lines):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    if re.search(r'(ERROR|FAIL|failed|timeout|crash|abort|\u5f02\u5e38|\u5931\u8d25)',
                                 stripped, re.IGNORECASE):
                        evidence_lines.append(stripped)
                        if idx + 1 < len(output_lines) and output_lines[idx + 1].strip():
                            evidence_lines.append(output_lines[idx + 1].strip())
                        if len(evidence_lines) >= 10:
                            break
                # \u5982\u679c\u6ca1\u627e\u5230\u660e\u663e\u9519\u8bef\u884c\u4e5f\u6ca1\u6709 fps \u884c\uff0c\u53d6\u8f93\u51fa\u5c3e\u90e8\u51e0\u884c
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
        elif is_fault_test:
            max_len = 1500  # \u6545\u969c\u6d4b\u8bd5\u9700\u8981\u5c55\u793a\u5b8c\u6574 error log
        else:
            max_len = 500
        return summary[:max_len]

    def _driver_lib_path_export(self) -> str:
        """根据工作区配置生成 LD_LIBRARY_PATH 的 export 语句。

        生成：export LD_LIBRARY_PATH="<驱动目录>${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
        未配置驱动存放路径时返回空串。
        """
        if not self.workspace:
            return ""
        driver_path = getattr(self.workspace, "driver_path", "")
        if not driver_path:
            return ""
        driver_path = driver_path.rstrip("/")
        return (
            f'export LD_LIBRARY_PATH="'
            f'{driver_path}${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}"'
        )

    def _apply_driver_lib_path(self, cmd: str) -> str:
        """给命令前置驱动库搜索路径（LD_LIBRARY_PATH）。

        export 在同一个 shell 中执行，驱动目录会追加到 LD_LIBRARY_PATH 之前，
        保证板端优先加载配置目录下的 .so。
        """
        export = self._driver_lib_path_export()
        if not export:
            return cmd
        return f"{export} && {cmd}"

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
        # \u786e\u4fdd\u8def\u5f84\u4ee5 / \u7ed3\u5c3e\uff08--nito \u8981\u6c42\u76ee\u5f55\u8def\u5f84\uff09
        if not nito_path.endswith('/'):
            nito_path += '/'
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

    def _apply_sudo_password(self, cmd: str, pty_mode: bool = False) -> str:
        """对含 sudo 的命令自动注入密码。

        策略：
        - pty_mode=True（PTY 交互模式）：先 echo pwd | sudo -S -v 缓存凭证，
          然后 sudo -n <cmd>，这样 cmd 的 stdin 仍是 PTY（可接收交互输入），
          不会因管道 stdin 残留导致 nvsipl 菜单循环打印。
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

        if pty_mode:
            # PTY 模式：先缓存 sudo 凭证，再用 -n（non-interactive）执行
            # 这样 nvsipl_camera 的 stdin 保持为 PTY，可接收 gc/q 等交互输入
            prefix = f"echo {escaped_pwd} | sudo -S -v 2>/dev/null; "
            cmd = re.sub(r'\bsudo\s+', 'sudo -n ', cmd)
            return prefix + cmd

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
        result = "\n".join(key_lines) if key_lines else output[-300:].strip()
        # 关键行里也可能残留菜单提示（尤其是兜底的最后 300 字符）
        return ExecutorAdapter._strip_nvsipl_menu(result)

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

    async def _run_prerequisites(self, prereq: str) -> Tuple[bool, str]:
        """执行前置条件，返回 (是否通过, 执行记录)。

        支持 ``MANUAL_CONFIRM <说明>`` 触发人工确认，其余按命令执行。
        兼容用 ``;`` 分隔的多条命令。
        """
        outputs: list[str] = []
        cmds = [c.strip() for c in prereq.split(";") if c.strip()]
        for idx, cmd in enumerate(cmds, 1):
            if cmd.startswith(CommandParser.MANUAL_CONFIRM_PREFIX):
                desc = cmd.replace(CommandParser.MANUAL_CONFIRM_PREFIX, "").strip()
                ok = await self.ws.request_manual_confirm(desc)
                outputs.append(f"[人工确认] {desc}: {'通过' if ok else '未通过'}")
                if not ok:
                    return False, "\n".join(outputs)
            else:
                await self._send_progress(self._step_progress_message(
                    "正在执行前置条件", idx, len(cmds), cmd))
                cmd = self._apply_driver_lib_path(cmd)
                await self.ws.send_log(f"前置条件执行: {cmd}", "info")
                exit_code, stdout, stderr = await self._ssh_execute(cmd, timeout=60)
                outputs.append(
                    f"$ {cmd}\n{stdout or ''}{stderr or ''}\nexit_code={exit_code}"
                )
                if exit_code != 0:
                    await self.ws.send_log(f"前置条件失败: {cmd} (exit={exit_code})", "error")
                    return False, "\n".join(outputs)
        return True, "\n".join(outputs)

    def _image_storage_path(self) -> str:
        """返回工作区配置的板端图片存储目录（未启用时为空）。"""
        if not self.workspace:
            return ""
        if not getattr(self.workspace, "image_storage_enabled", False):
            return ""
        return (getattr(self.workspace, "image_storage_path", "") or "").rstrip("/")

    def _resolve_file_search_dirs(self, steps, base_dir: str, work_dir: str) -> list:
        """执行后文件检查目录。

        配置了 image 存储路径时：nvsipl 的 -f 已被强制改写到该目录，
        但未带 -f 的命令仍写当前目录，因此两者都查；
        未配置时只查 nvsipl 实际写入的目录（-f 指定目录；未带 -f 时为当前目录）。
        只有完全没有 nvsipl 出图目录时，才兜底查工作目录。
        """
        dirs = self._collect_image_dirs(steps, base_dir, include_work_dir=False)
        storage = self._image_storage_path()
        if storage:
            dirs.insert(0, storage)
        elif not dirs and work_dir:
            dirs.append(work_dir)

        result: list = []
        for d in dirs:
            if d and d not in result:
                result.append(d)
        return result

    @staticmethod
    def _collect_image_dirs(steps, default_remote_path: str,
                            include_work_dir: bool = True) -> list:
        """收集执行前需要清空的板端图片目录（去重、保序）。

        - nvsipl_camera 命令 ``-f`` 参数指定的出图目录；
        - include_work_dir=True 时补充当前工作目录（未配置 image 存储路径时使用）。
        """
        import posixpath

        dirs: list = []

        def _add(path: str):
            path = (path or "").strip().strip("'\"")
            if not path:
                return
            path = posixpath.normpath(path)
            if path not in dirs:
                dirs.append(path)

        def _resolve(path: str, base: str) -> str:
            path = (path or "").strip().strip("'\"")
            if not path:
                return ""
            if path.startswith("/"):
                return posixpath.normpath(path)
            if not base:
                return posixpath.normpath(path)
            return posixpath.normpath(f"{base.rstrip('/')}/{path}")

        cur = default_remote_path or ""
        for step in steps:
            if step.kind in ("cd", "enter_dir") and step.command:
                cur = step.command
                continue
            if step.kind == "command" and CommandParser.is_nvsipl_camera_command(step.command):
                resolved_any = False
                for m in re.finditer(r'-f\s+([^\s;|&]+)', step.command or ""):
                    _add(_resolve(m.group(1), cur))
                    resolved_any = True
                # 没有 -f 时 nvsipl 默认写入当前工作目录
                if not resolved_any and cur:
                    _add(cur)

        if include_work_dir and cur:
            _add(cur)
        return dirs

    async def _clear_board_images(self, case_id: str, dirs: list) -> str:
        """执行前清空板端图片产物，返回可写入用例日志的说明文本。"""
        if not dirs:
            return ""

        import shlex

        name_expr = " -o ".join(f"-iname {shlex.quote(p)}" for p in _IMAGE_OUTPUT_GLOBS)
        notes = []
        for directory in dirs:
            quoted = shlex.quote(directory)
            cmd = (
                f"if [ -d {quoted} ]; then "
                f"find {quoted} -maxdepth 1 -type f \\( {name_expr} \\) -print -delete; "
                f"fi"
            )
            deleted = 0
            try:
                exit_code, stdout, _ = await self._ssh_execute(cmd, timeout=15)
                deleted = len([ln for ln in (stdout or "").splitlines() if ln.strip()])
                if exit_code != 0:
                    # 图片可能由 sudo 运行的 nvsipl 生成（root 所有），普通用户删不掉
                    password = ""
                    if self.ssh and hasattr(self.ssh, "config"):
                        config = self.ssh.config
                        password = (getattr(config, "target_password", "")
                                    or getattr(config, "password", ""))
                    if password:
                        sudo_find = (
                            f"echo {shlex.quote(password)} | sudo -S find {quoted} "
                            f"-maxdepth 1 -type f \\( {name_expr} \\) -print -delete"
                        )
                        sudo_cmd = f"if [ -d {quoted} ]; then {sudo_find}; fi"
                        exit_code, stdout, _ = await self._ssh_execute(
                            sudo_cmd, timeout=15)
                        deleted += len([
                            ln for ln in (stdout or "").splitlines() if ln.strip()
                        ])
                    if exit_code != 0:
                        warn = (
                            f"[文件检查] 执行前清空图片目录 {directory} 失败"
                            f"（权限不足？），历史文件可能影响判定")
                        notes.append(warn)
                        await self.ws.send_log(f"[{case_id}] {warn}", "warning")
            except Exception as e:
                await self.ws.send_log(
                    f"[{case_id}] 清空图片目录失败 {directory}: {e}", "warning")
                notes.append(f"[文件检查] 执行前清空图片目录 {directory} 失败: {e}")
                continue

            note = f"[文件检查] 执行前清空图片目录 {directory}: 删除 {deleted} 个历史文件"
            notes.append(note)
            await self.ws.send_log(f"[{case_id}] {note}", "info")
        return "\n".join(notes)

    async def _check_remote_files(self, case_id: str, search_dir: str,
                                  file_ext: str,
                                  expected_text: str = "") -> Tuple[str, list]:
        """在板端查找本次执行生成的指定后缀文件。

        返回 ``(记录文本, 文件列表)``。记录文本包含检查命令与查询结果，
        会被写入用例日志，并随 actual_output 一起交给 AI 判定。
        expected_text 用于从预期结果中解析 YUV 分辨率。
        """
        find_cmd = (
            f"find {search_dir} -maxdepth 1 -name '*{file_ext}' "
            f"2>/dev/null | head -20"
        )
        # 日志只保留「查找命令」与「查找结果」，清空目录/退出码/下载/转换等细节
        # 只走 WebSocket 实时日志，避免用例日志过长。
        lines = [f"[文件检查] 查找: {find_cmd}"]

        try:
            await self._send_progress("正在检查生成文件")
            await self.ws.send_log(f"[{case_id}] 文件检查: {find_cmd}", "info")
            exit_code, stdout, _ = await self._ssh_execute(find_cmd, timeout=15)
        except Exception as e:
            await self.ws.send_log(f"[{case_id}] 检查文件异常: {e}", "warning")
            lines.append(f"[文件检查] 结果: 执行异常: {e}")
            return "\n".join(lines), []

        files = [f.strip() for f in (stdout or "").strip().split("\n") if f.strip()]
        if files:
            await self.ws.send_log(
                f"[{case_id}] 检测到生成文件 ({len(files)} 个): {files[:5]}", "info")
            lines.append(f"[文件检查] 结果: 找到 {len(files)} 个文件:")
            lines.extend(files)
            # 下载到 PC + 删除板端文件（细节只推 WS，不写入用例日志）
            await self._download_and_cleanup_files(
                case_id, files, search_dir, expected_text)
        else:
            await self.ws.send_log(
                f"[{case_id}] 未检测到 {file_ext} 文件（{search_dir}）", "warning")
            lines.append("[文件检查] 结果: 未找到匹配文件")

        return "\n".join(lines), files

    async def _download_and_cleanup_files(self, case_id: str, remote_files: list,
                                          work_dir: str,
                                          expected_text: str = "") -> str:
        """将板端生成的图片文件 SCP 下载到 PC，然后删除板端文件。

        下载回来的 .yuv 会自动转换出同名 .png（首帧），方便直接查看。
        下载/删除/转换的细节只通过 WebSocket 实时日志反馈，不再写入用例日志。
        返回说明文本供调用方按需使用（当前调用方不写入日志）。
        """
        if not self.workspace:
            return ""
        if not getattr(self.workspace, "image_download_enabled", False):
            return ""
        download_path = getattr(self.workspace, "image_download_path", "")
        if not download_path:
            return ""

        await self._send_progress(f"正在下载图片到本机 ({len(remote_files)} 个文件)")

        import shlex

        # 按 case_id 创建本地子目录
        local_dir = os.path.join(download_path, case_id)
        os.makedirs(local_dir, exist_ok=True)

        # 复用 SSHManager 的传输能力：优先 SFTP（直连/跳板机通用），
        # 必要时回退 scp（自动带跳板机 ProxyCommand）
        if not self.ssh or not hasattr(self.ssh, "download_file"):
            return ""

        downloaded = 0
        downloaded_files: list = []
        loop = asyncio.get_event_loop()
        for remote_file in remote_files:
            filename = os.path.basename(remote_file)
            local_file = os.path.join(local_dir, filename)
            try:
                await loop.run_in_executor(
                    None, lambda r=remote_file, l=local_file: self.ssh.download_file(
                        r, l, timeout=60))
                downloaded += 1
                downloaded_files.append(local_file)
            except Exception as e:
                await self.ws.send_log(
                    f"[{case_id}] 图片下载失败 {filename}: {e}", "warning")

        if downloaded > 0:
            await self.ws.send_log(
                f"[{case_id}] 已下载 {downloaded} 个文件到 PC: {local_dir}", "info")

            # .yuv 自动转 PNG（首帧），方便直接在 PC 上查看
            png_notes = await self._convert_yuv_to_png(
                case_id, downloaded_files, expected_text)

            # 删除板端文件（防止后续用例误判）
            rm_files = " ".join(shlex.quote(f) for f in remote_files)
            rm_cmd = f"rm -f {rm_files}"
            await self._ssh_execute(rm_cmd, timeout=10)
            await self.ws.send_log(
                f"[{case_id}] 已清理板端文件 ({len(remote_files)} 个)", "info")
            note = (
                f"[文件检查] 已下载 {downloaded} 个文件到 PC: {local_dir}\n"
                f"[文件检查] 已删除板端文件 {len(remote_files)} 个"
            )
            if png_notes:
                note += "\n" + "\n".join(png_notes)
            return note

        await self.ws.send_log(
            f"[{case_id}] 文件下载失败，未清理板端文件", "warning")
        return "[文件检查] 文件下载失败，未清理板端文件"

    async def _convert_yuv_to_png(self, case_id: str, local_files: list,
                                  expected_text: str = "") -> list:
        """把已下载到本机的 .yuv 首帧转成同名 .png。

        分辨率优先取预期结果中的标注（如 ``yuv图（1920x1536）``），
        取不到时按文件大小推断；像素格式取括号内标注（如 ``, uyvy``），
        未标注时自动识别，标注格式转换失败会回退自动识别。
        转换模块不可用时只告警，不影响用例判定。
        转换结果只通过 WebSocket 实时日志反馈，不再写入用例日志。
        """
        yuv_files = [p for p in local_files if p.lower().endswith(".yuv")]
        if not yuv_files:
            return []

        try:
            from app.core import yuv2img
        except Exception as exc:
            msg = f"[图片转换] 转换模块不可用，已跳过 YUV->PNG: {exc}"
            await self.ws.send_log(f"[{case_id}] {msg}", "warning")
            return [msg]

        resolution = _parse_resolution_from_text(expected_text)
        pixfmt = _parse_pixfmt_from_text(expected_text)
        if pixfmt:
            await self.ws.send_log(
                f"[{case_id}] 按预期结果指定像素格式 {pixfmt} 转换 YUV->PNG", "info")
        loop = asyncio.get_event_loop()

        def _convert_all():
            outputs: list = []
            errors: list = []
            fallbacks: list = []
            for path in yuv_files:
                width, height = (resolution
                                 or yuv2img.infer_resolution(path, pixfmt=pixfmt or "auto")
                                 or (0, 0))
                if not width or not height:
                    errors.append(
                        f"{os.path.basename(path)}: 无法确定分辨率，已跳过 PNG 转换")
                    continue
                try:
                    outputs.append(yuv2img.convert_frame_to_png(
                        path, width, height, frame=0, pixfmt=pixfmt or "auto"))
                except Exception as exc:
                    if not pixfmt:
                        errors.append(f"{os.path.basename(path)}: {exc}")
                        continue
                    # 标注格式与实际数据不符时回退自动识别，保证仍能出图
                    try:
                        outputs.append(yuv2img.convert_frame_to_png(
                            path, width, height, frame=0))
                        fallbacks.append(
                            f"{os.path.basename(path)}: 按 {pixfmt} 转换失败（{exc}），"
                            f"已改用自动识别")
                    except Exception as exc2:
                        errors.append(f"{os.path.basename(path)}: {exc2}")
            return outputs, errors, fallbacks

        try:
            outputs, errors, fallbacks = await loop.run_in_executor(None, _convert_all)
        except Exception as exc:
            await self.ws.send_log(f"[{case_id}] YUV->PNG 转换异常: {exc}", "warning")
            return [f"[图片转换] 转换异常: {exc}"]

        notes: list = []
        if outputs:
            names = ", ".join(os.path.basename(p) for p in outputs)
            await self.ws.send_log(
                f"[{case_id}] 已生成 {len(outputs)} 张 PNG: {names}", "info")
            notes.append(f"[图片转换] 已生成 {len(outputs)} 张 PNG: {names}")
        for fb in fallbacks:
            await self.ws.send_log(f"[{case_id}] YUV->PNG 回退: {fb}", "warning")
            notes.append(f"[图片转换] 回退: {fb}")
        for err in errors:
            await self.ws.send_log(f"[{case_id}] YUV->PNG 失败: {err}", "warning")
            notes.append(f"[图片转换] 失败: {err}")
        return notes
