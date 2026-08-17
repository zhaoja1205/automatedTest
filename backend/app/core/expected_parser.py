"""预期结果解析与匹配（Web 版）。

从用例「预期结果」自然语言文本中提取可执行的判断标准（关键字、错误词、
帧率、文件后缀等），并与实际终端输出比对。移植自桌面版 test_runner_app，
保留核心 parse / match / 帧率 / 严重错误检查逻辑。
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
        for pattern in fps_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                groups = match.groups()
                fps_value = groups[-1] if len(groups) > 1 else groups[0]
                criteria.keywords.append(f"{fps_value}fps")
                criteria.keywords.append(f"{fps_value} fps")
                criteria.keywords.append(f"{fps_value}FPS")
                criteria.keywords.append(f"Frame rate: {fps_value}")
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

        # 无报错
        no_error_patterns = [
            r'无报错', r'无异常', r'无错误', r'不报错',
            r'no error', r'without error', r'no exception',
        ]
        for pattern in no_error_patterns:
            if re.search(pattern, text_lower):
                criteria.exit_code_check = True
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
            english_keyword_pattern = r'\b([A-Za-z][A-Za-z0-9_]{3,}(?:\s+[A-Za-z][A-Za-z0-9_]+)*)\b'
            eng_matches = re.findall(english_keyword_pattern, text)
            for em in eng_matches:
                em = em.strip()
                skip_words = [
                    'log', 'the', 'and', 'with', 'that', 'this', 'can', 'for', 'not',
                    'sensorid', 'sensor', 'linkid', 'link', 'sudo', 'nvsipl', 'camera',
                    'nvsipl_camera', 'group', 'groupa', 'groupc', 'linka', 'linkb',
                    'linkc', 'linkd', 'exec', 'execute', 'command', 'step',
                    'note', 'info', 'test', 'check', 'result', 'pass', 'fail',
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
    ) -> Tuple[bool, str]:
        output_lower = actual_output.lower()
        reasons: List[str] = []
        passed = True
        fps_check_failed = False
        exit_code_failed = False

        if criteria.exit_code_check and exit_code != 0:
            exit_code_failed = True
            reasons.append(f"命令返回码非0: exit_code={exit_code}")
        else:
            reasons.append(f"返回码检查: OK (exit_code={exit_code})")

        fps_result = self._check_fps(criteria.keywords, actual_output, executed_cmd)
        if fps_result:
            fps_passed, fps_reason = fps_result
            reasons.append(fps_reason)
            if not fps_passed:
                passed = False
                fps_check_failed = True

        # 如果帧率检查通过，exit_code 非零不再判 Fail（nvsipl_camera 等程序正常退出常非零）
        if exit_code_failed:
            if fps_result and fps_result[0]:
                # 帧率 Pass → exit_code 降级为 warning，不影响最终判定
                reasons[0] = f"命令返回码非0: exit_code={exit_code}（帧率检查已通过，忽略退出码）"
            else:
                passed = False

        fps_passed_ok = fps_result and fps_result[0]
        if not fps_check_failed:
            found_errors: List[str] = []
            critical_errors = [
                'exception', 'timeout', 'crash', 'abort',
                'segmentation fault', 'core dump', '崩溃', '超时',
                'sudo: a password is required',
                'sudo: a terminal is required',
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
                # 从 critical_errors 检查中移除 segmentation fault
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
                passed = False
                reasons.append(f"发现错误: {found_errors}")
            else:
                reasons.append("无严重错误: OK")

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
            else:
                match_ratio = matched_count / total_keywords
                reasons.append(f"关键字匹配率: {match_ratio*100:.1f}% ({matched_count}/{total_keywords})")

                if matched_keywords:
                    reasons.append(f"匹配成功的关键字: {matched_keywords}")
                if unmatched_keywords:
                    reasons.append(f"未匹配的关键字: {unmatched_keywords}")

                MATCH_THRESHOLD = 0.80
                if match_ratio >= MATCH_THRESHOLD:
                    if unmatched_keywords:
                        reasons.append(f"匹配率 {match_ratio*100:.1f}% >= {MATCH_THRESHOLD*100:.0f}%，判定为 Pass")
                else:
                    passed = False
                    reasons.append(f"匹配率 {match_ratio*100:.1f}% < {MATCH_THRESHOLD*100:.0f}%，判定为 Fail")

        for pattern in criteria.patterns:
            try:
                if re.search(pattern, actual_output, re.IGNORECASE):
                    reasons.append(f"正则匹配成功: {pattern}")
                else:
                    reasons.append(f"正则匹配失败: {pattern}")
            except re.error:
                reasons.append(f"正则表达式错误: {pattern}")

        # 最终降级：exit_code 是唯一失败原因，但关键字/帧率均通过且无严重错误 → 恢复 Pass
        # 场景：system ssh 返回 255（SSH 层退出码）或 nvsipl segfault 退出码
        if not passed and exit_code_failed and not fps_check_failed:
            other_failures = [r for r in reasons if 'Fail' in r and '退出码' not in r and 'exit_code' not in r]
            if not other_failures:
                passed = True
                reasons[0] = f"命令返回码非0: exit_code={exit_code}（其他检查均通过，忽略退出码）"

        return passed, "; ".join(reasons)

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

    def quick_check(self, expected_text: str, actual_output: str, exit_code: int) -> Tuple[bool, str]:
        criteria = self.parse(expected_text)
        return self.match(criteria, actual_output, exit_code)
