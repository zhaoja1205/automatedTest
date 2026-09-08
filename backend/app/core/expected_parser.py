"""预期结果解析与匹配（Web 版）。

从用例「预期结果」自然语言文本中提取可执行的判断标准（关键字、错误词、
帧率、文件后缀等），并与实际终端输出比对。移植自桌面版 test_runner_app，
保留核心 parse / match / 帧率 / 严重错误检查逻辑。

v3.1 新增：MatchResult 含置信度评分，供 AI fallback 判定使用。
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class ExpectedCriteria:
    keywords: List[str] = field(default_factory=list)
    error_keywords: List[str] = field(default_factory=list)
    patterns: List[str] = field(default_factory=list)
    exit_code_check: bool = True
    file_check: str = ""
    file_count: int = 0  # 预期文件数量（0 表示不检查数量，仅检查存在性）
    fps_stability_check: bool = False  # 仅检查帧率>0且稳定，不要求特定值
    is_fault_test: bool = False  # 故障测试：预期输出中含 ERROR/FAULT 是正常的


@dataclass
class MatchResult:
    """规则引擎匹配结果，附带置信度。

    passed:
        True  = 规则明确判定 Pass
        False = 规则明确判定 Fail
        None  = 待人工确认（Review）
    confidence: 0.0~1.0
        >= 0.8 → 高置信度，直接采信规则结果
        0.5~0.8 → 中等置信度，可选 AI fallback
        < 0.5 → 低置信度，建议 AI 判定
    reason: 匹配详情（分号拼接）
    source: "rule" | "ai" — 最终判定来源
    """
    passed: Optional[bool]
    confidence: float
    reason: str
    source: str = "rule"


class ExpectedResultParser:
    """将自然语言预期结果解析为 ExpectedCriteria，并对实际输出执行匹配。"""

    ERROR_KEYWORDS = [
        'error', 'fail', 'failed', 'exception', 'timeout',
        'crash', 'abort', 'segmentation fault', 'core dump',
        '错误', '失败', '异常', '超时', '崩溃',
    ]

    def parse(self, expected_text: str) -> ExpectedCriteria:
        if not expected_text:
            return ExpectedCriteria(
                keywords=[],
                error_keywords=list(self.ERROR_KEYWORDS),
                exit_code_check=True,
            )

        text = expected_text
        text_lower = text.lower()

        criteria = ExpectedCriteria(
            keywords=[],
            error_keywords=list(self.ERROR_KEYWORDS),
            patterns=[],
            exit_code_check=True,
            file_check="",
        )

        match_hint_patterns = [
            r'需要匹配(?:以下|下列)?(?:内容)?',
            r'与以下(?:字段|内容)?(?:可以)?匹配',
            r'匹配(?:以下|下列)?(?:内容|字段)',
            r'(?:log|日志|输出).*?(?:包含|含有|出现|显示)',
            r'认为.*?(?:正确|成功|通过)',
            r'检查关键字',
            r'观察.*?是否',
        ]
        has_match_hint = any(re.search(p, text) for p in match_hint_patterns)

        tool_compare_patterns = [
            r'工具读取(?:的)?(?:内容)?',
            r'i2cmastercmd.*?读取',
            r'与.*?一致',
            r'内容一致认为.*?正确',
            r'得到的内容.*?一致',
        ]
        is_tool_compare = any(re.search(p, text, re.IGNORECASE) for p in tool_compare_patterns)

        if is_tool_compare:
            criteria.keywords.append("工具读取内容与主终端输出一致")
            criteria.error_keywords.extend([
                "工具执行失败",
                "工具读取失败",
                "工具读取内容与主终端输出不一致",
            ])
            return criteria

        if has_match_hint:
            quoted_patterns = [
                '[“]([^”]+)[”]',
                '[‘]([^’]+)[’]',
                r'"([^"]+)"',
                r"'([^']+)'",
            ]
            for quoted_pattern in quoted_patterns:
                quoted_matches = re.findall(quoted_pattern, text, re.MULTILINE | re.DOTALL)
                for match_content in quoted_matches:
                    content = match_content.strip()
                    if content and len(content) >= 2:
                        for line in content.split('\n'):
                            line = line.strip()
                            line = re.sub(r'^[\s|]+', '', line).strip()
                            line = re.sub(r'[\s|]+$', '', line).strip()
                            if line and len(line) >= 2 and line not in criteria.keywords:
                                criteria.keywords.append(line)

            if not criteria.keywords:
                colon_patterns = [
                    r'需要匹配(?:以下|下列)?(?:内容)?[：:]\s*([^\n]+)',
                    r'匹配(?:以下|下列)?(?:内容|字段)[：:]\s*([^\n]+)',
                    r'(?:log|日志|输出).*?(?:包含|含有|出现|显示)[：:]\s*([^\n]+)',
                ]
                for pattern in colon_patterns:
                    matches = re.findall(pattern, text, re.MULTILINE)
                    for match_content in matches:
                        content = match_content.strip().strip('"\'""')
                        if content and len(content) >= 2 and content not in criteria.keywords:
                            for line in content.split('\n'):
                                line = line.strip().strip('"\'|""')
                                if line and len(line) >= 2:
                                    criteria.keywords.append(line)

        # 帧率
        fps_patterns = [
            r'\[(\d+)[~\-](\d+)\]\s*fps',
            r'(\d+)\s*fps',
            r'(\d+)\s*FPS',
            r'(\d+)\s*帧',
        ]
        has_specific_fps = False
        for pattern in fps_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                groups = match.groups()
                fps_value = groups[-1] if len(groups) > 1 else groups[0]
                criteria.keywords.append(f"{fps_value}fps")
                criteria.keywords.append(f"{fps_value} fps")
                criteria.keywords.append(f"{fps_value}FPS")
                criteria.keywords.append(f"Frame rate: {fps_value}")
                has_specific_fps = True
                break

        # 帧率稳定性检查（无具体数值，仅要求帧率正常/稳定/不变）
        if not has_specific_fps:
            fps_stability_patterns = [
                r'帧率不变', r'帧率稳定', r'保证帧率', r'帧率正常',
                r'fps稳定', r'fps不变', r'正常出帧', r'稳定出帧',
                r'起流.*模组', r'所有模组.*起流', r'正常起流',
            ]
            for pattern in fps_stability_patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    criteria.fps_stability_check = True
                    break

        # 文件后缀
        file_patterns = [
            r'\.(raw|yuv|png|jpg|jpeg|log|txt|csv)\s*文件',
            r'\.(raw|yuv|png|jpg|jpeg|log|txt|csv)\s*后缀',
            r'生成.*?\.(raw|yuv|png|jpg|jpeg|log|txt|csv)',
            r'\.(raw|yuv|png|jpg|jpeg|log|txt|csv)\s*file',
            r'存储.*?\.(raw|yuv|png|jpg|jpeg|log|txt|csv)',
        ]
        for pattern in file_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                file_ext = match.group(1).lower()
                criteria.file_check = f".{file_ext}"
                criteria.keywords.append(f".{file_ext}")
                break

        # 文件数量检测：如 "生成两个.yuv文件"、"生成2张.yuv图片"、"两个.yuv文件"
        if criteria.file_check:
            ext_esc = re.escape(criteria.file_check)
            # 中文数字映射
            cn_num_map = {'两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
            count_patterns = [
                # "生成2个.yuv文件"、"2张.yuv"
                rf'(\d+)\s*(?:个|张|份|组).*?{ext_esc}',
                # "生成两个.yuv文件"、"两张.yuv"
                rf'([两三四五六七八九十])\s*(?:个|张|份|组).*?{ext_esc}',
                # ".yuv文件2个"（后置数量）
                rf'{ext_esc}.*?(\d+)\s*(?:个|张|份|组)',
            ]
            for cp in count_patterns:
                cm = re.search(cp, text, re.IGNORECASE)
                if cm:
                    val = cm.group(1)
                    if val.isdigit():
                        criteria.file_count = int(val)
                    elif val in cn_num_map:
                        criteria.file_count = cn_num_map[val]
                    break

        # 无报错
        no_error_patterns = [
            r'无报错', r'无异常', r'无错误', r'不报错',
            r'no error', r'without error', r'no exception',
        ]
        for pattern in no_error_patterns:
            if re.search(pattern, text_lower):
                criteria.exit_code_check = True
                break

        # 故障测试检测：预期结果中要求观察到特定 ERROR/FAULT 关键字
        # 此类用例的输出中 ERROR 是正常预期行为，不应被当作判定失败的依据
        fault_test_patterns = [
            r'[A-Z_]+_ERROR',           # 如 IMX728_CLKMON_ERROR
            r'[A-Z_]+_FAULT',           # 如 SENSOR_FAULT
            r'故障报出', r'故障注入.*成功', r'注入.*故障',
            r'fault.*(?:can be|observed|reported|detected)',
            r'(?:查看|观察).*故障',
        ]
        for pattern in fault_test_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                criteria.is_fault_test = True
                break

        # 数量+单位
        num_patterns = [
            r'(\d+)\s*(张|帧|个|次|ms|秒|s)',
            r'温度.*?(\d+)',
        ]
        for pattern in num_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                if isinstance(match, tuple):
                    criteria.patterns.append(rf'{match[0]}\s*{match[1]}')
                else:
                    criteria.keywords.append(match)

        # 十六进制预期值
        hex_value_patterns = [
            r'(?:值为|返回|等于|为|=|是)\s*(0x[0-9a-fA-F]+)',
            r'(?:寄存器|register).*?(0x[0-9a-fA-F]+)',
            r'(?:读取|读出|得到|获取).*?(0x[0-9a-fA-F]+)',
        ]
        for pattern in hex_value_patterns:
            hex_matches = re.findall(pattern, text, re.IGNORECASE)
            for hm in hex_matches:
                if hm and hm not in criteria.keywords:
                    criteria.keywords.append(hm)

        if not has_match_hint:
            status_patterns = [
                r'正常起流', r'正常启动', r'正常输出',
                r'stream.*start', r'camera.*init',
            ]
            for pattern in status_patterns:
                if re.search(pattern, text_lower):
                    criteria.keywords.extend(['streaming', 'started', 'initialized'])
                    break

        if not has_match_hint:
            # 只提取单个英文技术词汇（≥4字符），不提取多词短语
            # 多词英文短语通常是自然语言描述，不是终端输出关键字
            english_keyword_pattern = r'\b([A-Za-z][A-Za-z0-9_]{3,})\b'
            eng_matches = re.findall(english_keyword_pattern, text)
            for em in eng_matches:
                em = em.strip()
                skip_words = [
                    # 原有
                    'log', 'the', 'and', 'with', 'that', 'this', 'can', 'for', 'not',
                    'sensorid', 'sensor', 'linkid', 'link', 'sudo', 'nvsipl', 'camera',
                    'nvsipl_camera', 'group', 'groupa', 'groupc', 'linka', 'linkb',
                    'linkc', 'linkd', 'exec', 'execute', 'command', 'step',
                    'note', 'info', 'test', 'check', 'result', 'pass', 'fail',
                    # 过滤英文自然语言高频词（预期结果中的英文描述不应参与匹配）
                    'file', 'viewed', 'normally', 'without', 'issues', 'board',
                    'terminal', 'executed', 'errors', 'generated', 'started',
                    'streaming', 'starts', 'initialized', 'should', 'have',
                    'been', 'from', 'into', 'will', 'does', 'each', 'after',
                    'before', 'during', 'output', 'input', 'normal', 'error',
                    'successfully', 'correctly', 'expected', 'actual',
                    # 故障测试描述词
                    'fault', 'faults', 'observed', 'reported', 'being',
                    'detected', 'displayed', 'shown', 'visible',
                ]
                if em.lower() not in skip_words and len(em) >= 4:
                    criteria.keywords.append(em)

        criteria.keywords = list(set(criteria.keywords))
        return criteria

    def match(
        self,
        criteria: ExpectedCriteria,
        actual_output: str,
        exit_code: int,
        executed_cmd: str = "",
    ) -> MatchResult:
        """对实际输出执行匹配判定，返回含置信度的 MatchResult。

        置信度评分策略：
        - 帧率数值完全匹配且无错误 → 0.95
        - 关键字 100% 匹配且无错误 → 0.95
        - 关键字 80-99% 匹配 → 0.6~0.8 (边界区域)
        - 仅 exit_code 失败,无其他证据 → 0.4 (Review)
        - 有降级 warn → 在原有置信度上扣减 0.1
        - 多维度交叉验证通过 → 置信度叠加
        """
        output_lower = actual_output.lower()
        reasons: List[str] = []
        passed = True
        fps_check_failed = False
        exit_code_failed = False

        # ---- 置信度跟踪 ----
        confidence = 0.5  # 基准
        confidence_factors: List[Tuple[str, float]] = []  # (原因, 加/减分)

        if criteria.exit_code_check and exit_code != 0:
            exit_code_failed = True
            reasons.append(f"命令返回码非0: exit_code={exit_code}")
        else:
            reasons.append(f"返回码检查: OK (exit_code={exit_code})")
            confidence_factors.append(("exit_code=0", +0.1))

        fps_result = self._check_fps(criteria.keywords, actual_output, executed_cmd)
        if fps_result:
            fps_passed, fps_reason = fps_result
            reasons.append(fps_reason)
            if not fps_passed:
                passed = False
                fps_check_failed = True
                confidence_factors.append(("fps_fail", +0.2))  # 帧率失败是强信号
            else:
                confidence_factors.append(("fps_pass", +0.3))  # 帧率通过是强信号

        # 帧率稳定性检查（无具体数值，仅验证所有 sensor 帧率 > 0）
        if not fps_result and criteria.fps_stability_check:
            fps_result = self._check_fps_stability(actual_output, executed_cmd)
            if fps_result:
                fps_passed, fps_reason = fps_result
                reasons.append(fps_reason)
                if not fps_passed:
                    passed = False
                    fps_check_failed = True
                    confidence_factors.append(("fps_stability_fail", +0.15))
                else:
                    confidence_factors.append(("fps_stability_pass", +0.25))

        # exit_code 非零的初步处理：
        # - 故障测试 → 退出码非零是正常的（故障注入可能导致 nvsipl 异常退出），直接降级
        # - 帧率通过 → 立即降级为 warning（exit_code 被忽略）
        # - 否则延后到关键字检查完成后在"exit_code 最终判定"块统一处理
        if exit_code_failed:
            if criteria.is_fault_test:
                reasons[0] = f"命令返回码非0: exit_code={exit_code}（故障测试，忽略退出码）"
                exit_code_failed = False  # 故障测试中退出码不参与判定
                confidence_factors.append(("fault_test_exit_code_ignored", +0.0))
            elif fps_result and fps_result[0]:
                # 帧率 Pass → exit_code 降级为 warning，不影响最终判定
                reasons[0] = f"命令返回码非0: exit_code={exit_code}（帧率检查已通过，忽略退出码）"
                confidence_factors.append(("exit_code_degraded", -0.05))
            # 注意：不再在此处直接 passed=False，留给后面统一判定

        fps_passed_ok = fps_result and fps_result[0]
        found_errors: List[str] = []
        if not fps_check_failed:
            # 故障测试：输出中的 ERROR/error 是预期行为，跳过 critical_errors 检测
            # 仅保留 PTY 异常和 sudo 权限等执行层面硬错误
            if criteria.is_fault_test:
                hard_errors = [
                    'sudo: a password is required',
                    'sudo: a terminal is required',
                    '[pty异常]',
                ]
                filtered_output_lower = actual_output.lower()
                for err_kw in hard_errors:
                    if err_kw.lower() in filtered_output_lower:
                        found_errors.append(err_kw)
                if not found_errors:
                    reasons.append("故障测试: 跳过 ERROR 误判检测 (输出中的 ERROR 属于预期故障行为)")
                    confidence_factors.append(("fault_test_no_hard_error", +0.1))
            else:
                critical_errors = [
                    'exception', 'timeout', 'crash', 'abort',
                    'segmentation fault', 'core dump', '崩溃', '超时',
                    'sudo: a password is required',
                    'sudo: a terminal is required',
                    'nvsipl_camera: error',
                    '[pty异常]',
                ]
                filtered_lines = []
                for line in actual_output.split('\n'):
                    if re.search(r'bash:\s*line\s*\d+:.*Segmentation fault', line, re.IGNORECASE):
                        continue
                    filtered_lines.append(line)
                filtered_output_lower = '\n'.join(filtered_lines).lower()

                # 如果输出含 SUCCESS 且末尾有 Segmentation fault，视为 nvsipl 已知退出行为，不判错
                has_success = 'success' in filtered_output_lower
                has_segfault = 'segmentation fault' in filtered_output_lower
                if has_success and has_segfault:
                    critical_errors = [e for e in critical_errors if e != 'segmentation fault']

                for err_kw in critical_errors:
                    if err_kw.lower() in filtered_output_lower:
                        found_errors.append(err_kw)

            tool_compare_errors = [
                '工具执行失败',
                '工具读取失败',
                '工具读取内容与主终端输出不一致',
            ]
            for err_kw in tool_compare_errors:
                if err_kw in actual_output:
                    found_errors.append(err_kw)

            if found_errors:
                # 暂时记录错误，最终判定延迟到帧率/关键字检查之后
                reasons.append(f"发现错误: {found_errors}")
            else:
                reasons.append("无严重错误: OK")
                confidence_factors.append(("no_critical_error", +0.1))

        keyword_passed = False
        match_ratio = 0.0
        if criteria.keywords:
            _stream_status_words = {'streaming', 'started', 'initialized'}
            non_fps_keywords = [
                kw for kw in criteria.keywords
                if 'fps' not in kw.lower()
                and not kw.lower().startswith('frame rate')
                and not (fps_passed_ok and kw.lower() in _stream_status_words)
            ]

            matched_keywords = []
            unmatched_keywords = []
            for kw in non_fps_keywords:
                if kw.lower() in output_lower:
                    matched_keywords.append(kw)
                else:
                    unmatched_keywords.append(kw)

            total_keywords = len(non_fps_keywords)
            matched_count = len(matched_keywords)

            if total_keywords == 0:
                reasons.append("关键字检查: 跳过 (所有关键字已由帧率/专项检查覆盖)")
                keyword_passed = True
            else:
                match_ratio = matched_count / total_keywords
                reasons.append(f"关键字匹配率: {match_ratio*100:.1f}% ({matched_count}/{total_keywords})")

                if matched_keywords:
                    reasons.append(f"匹配成功的关键字: {matched_keywords}")
                if unmatched_keywords:
                    reasons.append(f"未匹配的关键字: {unmatched_keywords}")

                MATCH_THRESHOLD = 0.80
                if match_ratio >= MATCH_THRESHOLD:
                    keyword_passed = True
                    if unmatched_keywords:
                        reasons.append(f"匹配率 {match_ratio*100:.1f}% >= {MATCH_THRESHOLD*100:.0f}%，判定为 Pass")
                    # 关键字置信度：100% = +0.3, 80% = +0.1
                    kw_confidence = 0.1 + (match_ratio - 0.8) * 1.0  # 0.8→0.1, 1.0→0.3
                    confidence_factors.append(("keyword_pass", kw_confidence))
                else:
                    passed = False
                    reasons.append(f"匹配率 {match_ratio*100:.1f}% < {MATCH_THRESHOLD*100:.0f}%，判定为 Fail")
                    confidence_factors.append(("keyword_fail", +0.15))

        for pattern in criteria.patterns:
            try:
                if re.search(pattern, actual_output, re.IGNORECASE):
                    reasons.append(f"正则匹配成功: {pattern}")
                else:
                    reasons.append(f"正则匹配失败: {pattern}")
            except re.error:
                reasons.append(f"正则表达式错误: {pattern}")

        # === 错误降级判定 ===
        # 如果帧率通过或关键字匹配通过，error 降级为 warn 而非 Fail
        # 核心逻辑：结果符合预期（帧率正常/关键字匹配达标）才是判定标准，
        # 有 error 但出帧正常/交互结果正确 → 仅警告，不影响最终判定
        # 例外：PTY异常（通道关闭）属于执行层面硬错误，不可降级
        error_degraded = False
        if found_errors:
            # PTY 异常是硬错误，绝不降级
            has_hard_error = any(
                e in ('[pty异常]',) for e in found_errors
            )
            core_check_passed = fps_passed_ok or keyword_passed
            if core_check_passed and not has_hard_error:
                # 帧率或关键字匹配已通过 → error 降级为 warn
                # 替换之前的"发现错误"记录为 warn 级别
                for i, r in enumerate(reasons):
                    if '发现错误' in r:
                        reasons[i] = f"[WARN] 输出含错误关键字 {found_errors}（帧率/关键字检查已通过，降级为警告）"
                        break
                # 不设置 passed = False
                error_degraded = True
                confidence_factors.append(("error_degraded_to_warn", -0.1))
            else:
                # 核心检查未通过，error 导致 Fail
                passed = False
                confidence_factors.append(("critical_error_fail", +0.2))

        # === exit_code 最终判定 ===
        # exit_code 非零的处理延后到关键字检查完成后统一判定，
        # 因为关键字/帧率通过时 exit_code 应被忽略（nvsipl 等程序正常退出常非零）
        if exit_code_failed:
            core_check_passed = fps_passed_ok or keyword_passed
            if core_check_passed:
                # 帧率或关键字已通过 → exit_code 降级为 warning，恢复为 Pass
                reasons[0] = (
                    f"命令返回码非0: exit_code={exit_code}"
                    f"（{'帧率' if fps_passed_ok else '关键字'}检查已通过，忽略退出码）"
                )
                passed = True
            elif not found_errors:
                # 无帧率/关键字检查通过，也无严重错误 → 待人工确认
                passed = None
                reasons[0] = f"命令返回码非0: exit_code={exit_code}（无其他错误，待人工确认）"
                confidence_factors.append(("exit_code_only_review", -0.2))
            # else: 有其他错误，passed 保持 False

        # ---- 计算最终置信度 ----
        confidence = self._compute_confidence(
            passed, confidence_factors, match_ratio,
            fps_passed_ok, keyword_passed, error_degraded,
            bool(criteria.keywords),
        )

        return MatchResult(
            passed=passed,
            confidence=confidence,
            reason="; ".join(reasons),
        )

    @staticmethod
    def _compute_confidence(
        passed: Optional[bool],
        factors: List[Tuple[str, float]],
        match_ratio: float,
        fps_passed: bool,
        keyword_passed: bool,
        error_degraded: bool,
        has_keywords: bool,
    ) -> float:
        """计算规则引擎置信度（0.0 ~ 1.0）。

        评分策略：
        - 基准 0.5
        - 各维度检查结果叠加
        - 多维度交叉验证通过 → 额外加分
        - Review 状态 → 强制 ≤ 0.5
        """
        score = 0.5
        for _, delta in factors:
            score += delta

        # 交叉验证加分：多个独立维度同时 Pass → 更可信
        cross_dims = sum([bool(fps_passed), bool(keyword_passed and match_ratio >= 0.9)])
        if cross_dims >= 2:
            score += 0.05

        # 无关键字且无帧率检查 → 仅靠 exit_code，置信度偏低
        if not has_keywords and not fps_passed:
            score = min(score, 0.7)

        # Review 状态 → 置信度不超过 0.5
        if passed is None:
            score = min(score, 0.5)

        return max(0.0, min(1.0, round(score, 2)))

    @staticmethod
    def _parse_sensor_mask(cmd: str) -> Optional[List[int]]:
        m = re.search(r'-m\s+"?([^"]+)"?', cmd)
        if not m:
            return None
        parts = m.group(1).strip().split()
        active = []
        for group_idx, part in enumerate(parts[:4]):
            part = part.strip()
            if not part:
                continue
            try:
                val = int(part, 16) if part.lower().startswith('0x') else int(part)
            except ValueError:
                continue
            if val == 0:
                continue
            base_sid = group_idx * 4
            for local_sid in range(4):
                if val & (1 << (local_sid * 4)):
                    active.append(base_sid + local_sid)
        return active if active else None

    def _check_fps(self, keywords: List[str], output: str, executed_cmd: str = "") -> Optional[Tuple[bool, str]]:
        expected_fps = None
        for kw in keywords:
            match = re.search(r'(\d+)\s*fps', kw, re.IGNORECASE)
            if match:
                expected_fps = int(match.group(1))
                break
        if expected_fps is None:
            return None

        tolerance = expected_fps * 0.2
        min_fps = expected_fps - tolerance
        max_fps = expected_fps + tolerance

        expected_sensors = self._parse_sensor_mask(executed_cmd) if executed_cmd else None
        sensor_fps_pattern = r'(Sensor(\d+)_Out\d+\s+Frame rate \(fps\):\s+(\d+\.?\d*))'
        raw_matches = re.findall(sensor_fps_pattern, output)

        if raw_matches:
            sensor_last: dict = {}
            for full_line, sid_str, fps_str in raw_matches:
                sid = int(sid_str)
                sensor_last[sid] = float(fps_str)

            check_ids = expected_sensors if expected_sensors else sorted(sensor_last.keys())
            # 如果 mask 推算的 sensor 在输出中一个都没有，但有其他 sensor 的帧率，
            # 说明 mask→sensorID 映射与实际硬件配置不一致，回退到使用实际输出中的 sensor
            if expected_sensors and not any(sid in sensor_last for sid in expected_sensors):
                check_ids = sorted(sensor_last.keys())
            all_pass = True
            fps_details = []
            for sid in check_ids:
                if sid not in sensor_last:
                    fps_details.append(f"Sensor{sid}=未检测到[FAIL]")
                    all_pass = False
                    continue
                actual = sensor_last[sid]
                ok = min_fps <= actual <= max_fps
                if not ok:
                    all_pass = False
                fps_details.append(f"Sensor{sid}={actual:.2f}fps[{'PASS' if ok else 'FAIL'}]")

            return all_pass, (
                f"帧率检查: {'PASS' if all_pass else 'FAIL'} "
                f"(预期{expected_fps}fps, 允许{min_fps:.0f}-{max_fps:.0f}fps, "
                f"各Sensor: {', '.join(fps_details)})"
            )

        fps_patterns = [
            r'Frame rate[:\s]*\(?fps\)?[:\s]*(\d+\.?\d*)',
            r'Frame rate[:\s]*(\d+\.?\d*)',
            r'(\d+\.?\d*)\s*fps',
            r'fps[:\s]*(\d+\.?\d*)',
        ]
        actual_fps = None
        for pattern in fps_patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                actual_fps = float(match.group(1))
                break
        if actual_fps is None:
            return False, f"帧率检查: FAIL (预期{expected_fps}fps，但未在输出中找到实际帧率)"

        if min_fps <= actual_fps <= max_fps:
            return True, f"帧率检查: PASS (预期{expected_fps}fps, 实际{actual_fps:.1f}fps)"
        return False, f"帧率检查: FAIL (预期{expected_fps}fps, 实际{actual_fps:.1f}fps)"

    def _check_fps_stability(self, output: str, executed_cmd: str = "") -> Optional[Tuple[bool, str]]:
        """帧率稳定性检查：不要求特定帧率值，只验证所有 sensor 正常出帧(fps > 20)。

        用于预期结果中含"帧率不变/帧率稳定/保证帧率"但无具体数字的场景。
        """
        MIN_STABLE_FPS = 20.0

        expected_sensors = self._parse_sensor_mask(executed_cmd) if executed_cmd else None
        sensor_fps_pattern = r'Sensor(\d+)_Out\d+\s+Frame rate \(fps\):\s+(\d+\.?\d*)'
        raw_matches = re.findall(sensor_fps_pattern, output)

        if not raw_matches:
            # 尝试通用帧率模式
            generic_match = re.search(r'Frame rate[:\s]*(\d+\.?\d*)', output, re.IGNORECASE)
            if generic_match:
                fps = float(generic_match.group(1))
                if fps >= MIN_STABLE_FPS:
                    return True, f"帧率稳定性检查: PASS (检测到帧率 {fps:.1f}fps > {MIN_STABLE_FPS}fps)"
                else:
                    return False, f"帧率稳定性检查: FAIL (检测到帧率 {fps:.1f}fps < {MIN_STABLE_FPS}fps)"
            return None  # 未检测到帧率输出，不做判定

        # 取每个 sensor 的最后一次帧率
        sensor_last: dict = {}
        for sid_str, fps_str in raw_matches:
            sid = int(sid_str)
            sensor_last[sid] = float(fps_str)

        check_ids = expected_sensors if expected_sensors else sorted(sensor_last.keys())
        all_pass = True
        fps_details = []
        for sid in check_ids:
            if sid not in sensor_last:
                fps_details.append(f"Sensor{sid}=未检测到[FAIL]")
                all_pass = False
                continue
            actual = sensor_last[sid]
            ok = actual >= MIN_STABLE_FPS
            if not ok:
                all_pass = False
            fps_details.append(f"Sensor{sid}={actual:.2f}fps[{'PASS' if ok else 'FAIL'}]")

        return all_pass, (
            f"帧率稳定性检查: {'PASS' if all_pass else 'FAIL'} "
            f"(要求所有Sensor帧率>{MIN_STABLE_FPS}fps, "
            f"检测到{len(sensor_last)}个Sensor, "
            f"各Sensor: {', '.join(fps_details[:6])}"
            f"{'...' if len(fps_details) > 6 else ''})"
        )

    def quick_check(self, expected_text: str, actual_output: str, exit_code: int) -> MatchResult:
        criteria = self.parse(expected_text)
        return self.match(criteria, actual_output, exit_code)
