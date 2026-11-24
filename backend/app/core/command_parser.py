"""命令解析（Web 版）。

从用例「测试步骤」自然语言文本中提取可在板端执行的 shell 命令序列，
替代早期「整段 test_steps 当一条命令」的简化做法。移植自桌面版
test_runner_app/core/executor.py 的命令解析与 NA 识别部分，保留：
- 步骤按数字序号切分
- 多模式命令提取（执行命令：/ ./xxx / i2cmastercmd / 反引号 / cd / sudo ...）
- 自动跳过 SSH 连接、注释、纯英文说明、描述性文字
- 人工操作步骤（拔插线缆 / 手动切换设备等）自动转为人工确认（kind="confirm"）
- 工作目录追踪（cd / 进入调试目录）
- NA 自动识别

不包含桌面版的并行执行 / PTY 交互式 nvsipl / 十六进制比对等高级场景：
多终端步骤在这里退化为「按顺序执行各终端命令」，并在说明里标注，
避免一次性引入与 SSHManager 不支持的 PTY 依赖。
"""
import re
from typing import List, Optional, Tuple


DEFAULT_TERMINAL = "终端A"


class CommandStep:
    """解析出的单条可执行步骤。"""

    def __init__(self, kind: str, command: str = "", description: str = "",
                 terminal: str = DEFAULT_TERMINAL, step_num: int = 0,
                 wait_seconds: float = 0.0,
                 expect_pattern: str = "",
                 expect_is_regex: bool = False,
                 expect_timeout: Optional[float] = None):
        # kind: "command" / "skip" / "wait" / "enter_dir" / "cd" / "manual" / "confirm" / "nvsipl_input" / "repeat" / "repeat_stream"
        self.kind = kind
        self.command = command
        self.description = description
        # 终端标签是开放字符串：默认「终端A」，步骤里写「终端B：」等前缀即切换
        self.terminal = terminal or DEFAULT_TERMINAL
        self.step_num = step_num  # 原始步骤编号（1-based），0 表示未知
        # 步骤命令执行完成后需要等待的秒数（从「等待2秒」「延时1.5s」等文本解析）
        self.wait_seconds = wait_seconds
        # nvsipl_input 步骤可选的「等待输出 / 超时」覆盖项：
        # 例如「输入 gc 0，等待输出：Frame rate，超时20秒」。
        # expect_pattern 为空表示沿用 _NVSIPL_INPUT_EXPECT 表。
        self.expect_pattern = expect_pattern
        self.expect_is_regex = expect_is_regex
        self.expect_timeout = expect_timeout

    def __repr__(self):
        return f"<CommandStep {self.kind}: {self.command or self.description}>"


class CommandParser:
    """测试步骤文本 → 可执行命令序列。"""

    NA_KEYWORDS = [
        '验证方案待写入', '方案待写入', '待写入', '待补充', '待完善',
        '暂不测试', '不适用', 'TBD', 'N/A', 'TODO',
    ]
    NA_EXACT_KEYWORDS = ['NA']

    MANUAL_CONFIRM_PREFIX = "MANUAL_CONFIRM"

    # 终端标签允许的字符：字母/数字/中文数字/天干，避免把「终端执行」「终端上」
    # 这类正文当成标签（如「终端B执行命令：…」里的「B执行命令」）。
    _TERMINAL_LABEL_CHARS = r'A-Za-z0-9一二三四五六七八九十甲乙丙丁戊己庚辛壬癸'

    # 终端前缀：``终端A：`` / ``终端B:`` / ``[终端A]`` / ``A>``。
    # 终端标签是开放字符串，默认终端A。
    # 这里只识别步骤开头的显式前缀，避免误伤命令正文中的冒号。
    _TERMINAL_PREFIX_PATTERN = re.compile(
        rf'^\s*(?:'
        rf'终端\s*([{_TERMINAL_LABEL_CHARS}]{{1,3}})\s*[：:]'
        rf'|\[\s*终端\s*([{_TERMINAL_LABEL_CHARS}]{{1,3}})\s*\]'
        rf'|(?<![A-Za-z0-9])([A-Za-z])\s*(?:>|：:)'
        rf')'
    )

    # 终端字样（任意位置）：步骤里只要出现「终端A」「终端B」「终端2」等字样，
    # 就识别为该终端——不再要求写在步骤开头，也不再要求后面带冒号。
    # 标签只取单个字母/数字/中文数字，避免把「终端上」「终端中」等普通词误判成终端。
    _TERMINAL_MENTION_PATTERN = re.compile(
        rf'终端\s*([{_TERMINAL_LABEL_CHARS}])'
    )

    # 切分片段开头的终端标签写法（含方括号/圆括号标注）与旧写法
    _TERMINAL_LABEL_PREFIX = re.compile(
        rf'^\s*(?:'
        rf'\[\s*终端\s*[{_TERMINAL_LABEL_CHARS}]+\s*\]'
        rf'|[（(]\s*终端\s*[{_TERMINAL_LABEL_CHARS}]+\s*[）)]'
        rf'|终端\s*[{_TERMINAL_LABEL_CHARS}]+\s*[：:]?'
        rf'|另一个终端|第二个终端|新终端|新开终端|另开终端|辅终端|辅助终端|其他终端'
        rf')\s*'
    )

    # 命令里的终端标注，如「./tool --flag（终端B）」
    _TERMINAL_ANNOTATION_PATTERN = re.compile(
        rf'\s*[（(]\s*终端\s*[{_TERMINAL_LABEL_CHARS}]+\s*[）)]'
    )

    # 正文开头的引导语（「执行命令：echo hi」→「echo hi」）
    _LEADING_PROSE_PATTERN = re.compile(
        r'^(?:(?:请|然后|接着|再|并|就|在|使用|执行|运行|输入|键入|敲入|按下|确认)\s*)+'
        r'(?:命令|指令)?\s*[：:]?\s*'
    )

    # 旧写法兼容：「另一个终端」「第二个终端」「辅终端」等 → 终端B
    _LEGACY_OTHER_TERMINAL = re.compile(
        r'另一个终端|第二个终端|新终端|新开终端|另开终端|辅终端|辅助终端|其他终端'
    )

    # 步骤等待：从「等待2秒」「延时1.5s」「等待1分钟」等文本中提取等待时长。
    # 不匹配 sleep，因为 sleep 本身就是可执行命令，避免与命令重复等待。
    MAX_WAIT_SECONDS = 600.0
    _WAIT_UNIT_PATTERN = re.compile(
        r'(?:等待|延时|延迟|停留|休眠|间隔|wait(?:ing)?)\s*[：:]?\s*'
        r'(\d+(?:\.\d+)?)\s*'
        r'(毫秒|ms|秒(?:钟)?|s(?:ec(?:ond)?s?)?|分(?:钟)?|m(?:in(?:ute)?s?)?)'
        r'(?![A-Za-z0-9])',
        re.IGNORECASE,
    )
    _FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")

    # nvsipl_input 步骤内的可选「等待输出 / 超时」配置：
    #   输入 gc 0，等待输出：Frame rate，超时20秒
    #   输入 al，等待输出:/Vertical|active_w/，超时10秒
    # 等待输出可以是普通文本（执行时转义后按正则需要匹配），也可以写成 /.../ 正则。
    _EXPECT_OUTPUT_MARKER = re.compile(r'等待输出\s*[：:]')
    _EXPECT_TIMEOUT_PATTERN = re.compile(
        r'(?:超时|最长等待|最多等待)\s*[：:]?\s*'
        r'(\d+(?:\.\d+)?)\s*'
        r'(毫秒|ms|秒(?:钟)?|s(?:ec(?:ond)?s?)?|分(?:钟)?|m(?:in(?:ute)?s?)?)?'
        r'(?![A-Za-z0-9])',
        re.IGNORECASE,
    )

    # 命令提取模式（按优先级），移植自桌面版 _extract_command
    # 前 7 个模式为"显式引导"（用户用「执行命令：」等明确标注），提取后不需要再做
    # is_valid_command 检查；后续模式为"隐式提取"，需验证是否为有效 shell 命令。
    _EXPLICIT_PATTERN_COUNT = 7  # 前 N 个模式属于显式引导
    _EXTRACT_PATTERNS = [
        r"执行命令\s*[：:]\s*([^\n①②③④⑤]+)",
        r"需执行(?:的)?命令\s*[：:]\s*([^\n①②③④⑤]+)",
        r"所执行命令\s*[：:]\s*([^\n①②③④⑤]+)",
        r"指令\s*[：:]\s*([^\n①②③④⑤]+)",
        r"起流\s*[：:]\s*([^\n①②③④⑤]+)",
        r"测试指令\s*[：:]\s*([^\n①②③④⑤]+)",
        r'((?:sudo\s+)?\.\/nvsipl_camera\s+[^\n①②③④⑤]+)',
        r'((?:sudo\s+)?\.\/\S+\s+[^\n①②③④⑤]*)',
        r'(?:^|\s)((?:sudo\s+)?nvsipl_camera\s+-[^\n①②③④⑤]+)',
        r"(i2cmastercmd\s+[^\n①②③④⑤'\"]+(?:['\"][^'\"]*['\"][^\n①②③④⑤]*)*)",
        r'(?:输入)?命令[：:]\s*([^\n①②③④⑤]+)',
        r'[：:]\s*(\.\/[^\n①②③④⑤]+)',
        r'[：:]\s*(sudo\s+[^\n①②③④⑤]+)',
        r'[：:]\s*(i2ctransfer\s+[^\n①②③④⑤]+)',
        r'[：:]\s*(i2cget\s+[^\n①②③④⑤]+)',
        r'[：:]\s*(i2cset\s+[^\n①②③④⑤]+)',
        r"另一个终端执行\s*['\"]([^'\"]+)['\"]",
        r"另一个终端执行\s*[：:]\s*([^\n①②③④⑤'\"]+)",
        r"在另一个终端\s*[^\n]*['\"]([^'\"]+)['\"]",
        r'`([^`]+)`',
        r"'(\./[^']+)'",
        r"'(i2cmastercmd[^']+)'",
        r'(scp\s+[^\n①②③④⑤]+)',
        r'(cd\s+[^\n①②③④⑤]+)',
        r'(devopen\s+[^\n①②③④⑤]+)',
        r'(devclose\s+[^\n①②③④⑤]+)',
        r'(?:故障注入|注入故障|故障恢复|恢复故障)\s*(?:命令)?\s*[：:]\s*([^\n①②③④⑤]+)',
    ]

    _CMD_KEYWORDS = [
        'cd', './', 'nvsipl', 'i2c', 'echo', 'cat',
        'ls', 'pwd', 'mkdir', 'cp', 'mv', 'rm', 'chmod',
        'grep', 'awk', 'sed', 'python', 'bash', 'sh', 'scp',
        'fault_simulation', 'i2cmastercmd', 'export', 'source',
        'kill', 'ps', 'top', 'ifconfig', 'ip ', 'ping',
        'dmesg', 'mount', 'umount', 'modprobe', 'insmod', 'rmmod',
        'devopen', 'devclose', 'fault_inject', 'error_inject',
        'fault_test', 'err_inject', 'fsi_',
    ]

    _ENTER_DIR_KEYWORDS = ['进入测试目录', '进入调试目录', '进入目录', '进入工作目录']

    _MANUAL_KEYWORDS = [
        '人为手动', '手动切换', '手动操作', '手动拔', '手动插',
        '人工操作', '人工切换', '人为操作',
        '物理操作', '拔插', '插拔',
    ]

    # ------------------------------------------------------------------
    # nvsipl_camera 交互输入检测
    # ------------------------------------------------------------------
    @classmethod
    def parse_nvsipl_interactive_inputs(cls, text: str) -> List[str]:
        """从步骤文本解析 nvsipl_camera 交互子命令列表。

        支持格式：
          - 「输入 dl 8」「输入 el 11」「输入 ro」「输入'ro'」
          - 「执行dl 0,dl 2, dl 3, dl 8」
          - 逗号/全角逗号/顿号分隔的裸子命令列表
          - 引号包裹：「输入'ro'指令」「输入"gc 1"」
          - 数字/十六进制参数行：「输入 8000 256」「输入 0x8000 256」
            （用于 sh0 等先提示 ``Please enter <address_hex> <length_dec>``
            再等待二次输入的子命令）
        """
        if not text:
            return []
        # 只取主文本（①之前 + 第一行）用于解析，去掉后续说明文字
        main_text = re.split(r'[①②③④⑤⑥⑦⑧⑨⑩]', text)[0].split('\n')[0].strip()
        # 含尖括号模板占位符（如 <sensor ID>）的主行是说明文字，不是实际命令
        if re.search(r'<[a-zA-Z\s]+>', main_text):
            return []
        out: List[str] = []

        # 模式0: 引号包裹的命令 「输入'ro'」「输入"gc 1"」「输入'al'」
        # 字符类中覆盖：ASCII引号 ' " + Unicode弯引号 ‘’“”
        pat0 = re.compile(
            r"输入(?!命令)\s*['\"‘’“”]([a-zA-Z][a-zA-Z0-9_ ]*)['\"‘’“”]",
            re.UNICODE,
        )
        for m in pat0.finditer(main_text):
            s = m.group(1).strip()
            if s and s not in out:
                out.append(s)

        # 模式1: 「输入 xxx」格式（无引号）
        pat1 = re.compile(
            r"输入(?!命令)(?:\s*)([a-zA-Z_][a-zA-Z0-9_]*(?:\s+[a-zA-Z0-9_\-.x]+)*)",
            re.UNICODE,
        )
        for m in pat1.finditer(main_text):
            s = m.group(1).strip().rstrip("，。；、")
            if s and s not in out:
                out.append(s)

        # 模式1b: 「输入 8000 256」数字/十六进制参数行
        # nvsipl 部分交互子命令（如 sh0）先提示输入地址/长度，随后等待用户
        # 再输入一行「<address_hex> <length_dec>」。这类参数不是子命令名，
        # 用单独模式识别；结果与模式0/1 合并，避免同一步骤里
        # 「输入sh0 … 输入8000 256」只解析出 sh0 而丢掉后续输入。
        pat1b = re.compile(
            r"输入(?!命令)(?:\s*)((?:0x)?[0-9A-Fa-f]+(?:\s+(?:0x)?[0-9A-Fa-f]+)+)",
            re.UNICODE,
        )
        for m in pat1b.finditer(main_text):
            s = m.group(1).strip().rstrip("，。；、")
            if s and s not in out:
                out.append(s)

        if out:
            return out

        # 模式2: 逐个提取 dl/elr/el/dlo/gc/ro/al/ed/th/df/bp/sr/hs + 可选数字 子命令
        # 仅当主文本看起来像命令列表时才用（如"执行dl 0, dl 2"或"dl 8; el 11"）
        # 不在普通说明性文字中全文扫描，避免误匹配
        _SUBCMD_NAMES = r'dlo|dl|elr|el|les|lds|cm|ckf|gc|ro|al|ed|th|df|bp|sr|hs|ex|q'
        is_cmd_list = bool(re.search(
            r'(?:执行|输入|发送)\s*(?:' + _SUBCMD_NAMES + r')',
            main_text, re.IGNORECASE,
        )) or bool(re.match(
            r'^(?:' + _SUBCMD_NAMES + r')\s*\d',
            main_text, re.IGNORECASE,
        ))
        # 补充：文本中嵌入了子命令（如 "模组gc 12"、"q退出应用"）
        if not is_cmd_list:
            is_cmd_list = bool(re.search(
                r'(?:' + _SUBCMD_NAMES + r')\s+\d+',
                main_text, re.IGNORECASE,
            )) or bool(re.match(r'^q\s*[退关]', main_text))
        if is_cmd_list:
            nvsipl_subcmd_pat = re.compile(
                r'(?:^|[^a-zA-Z])((?:' + _SUBCMD_NAMES + r')\s*(\d*))',
                re.IGNORECASE,
            )
            for m in nvsipl_subcmd_pat.finditer(main_text):
                raw = m.group(1).strip()
                cmd_parts = re.match(r'([a-zA-Z]+)\s*(\d*)', raw)
                if cmd_parts:
                    cmd_name = cmd_parts.group(1).lower()
                    cmd_num = cmd_parts.group(2)
                    s = f"{cmd_name} {cmd_num}".strip() if cmd_num else cmd_name
                    if s not in out:
                        out.append(s)
        return out

    @classmethod
    def is_nvsipl_interactive_step(cls, text: str) -> bool:
        """步骤是否为 nvsipl_camera 交互输入（能解析出至少一条子命令）。"""
        return len(cls.parse_nvsipl_interactive_inputs(text)) > 0

    @classmethod
    def is_nvsipl_camera_command(cls, cmd: str) -> bool:
        """命令是否为 nvsipl_camera。"""
        if not cmd:
            return False
        return bool(re.search(r'(?:^|\s|/)nvsipl_camera\b', cmd))

    @classmethod
    def is_blocking_nvsipl(cls, cmd: str) -> bool:
        """判断是否为阻塞型 nvsipl_camera（不会自动退出）。

        -r N（小写）：延时 N 秒后退出进程（非阻塞）
        不带 -r：一直运行直到手动输入 q 退出（阻塞型）

        注意：-R 是功能参数（使能通道），不控制退出。
        """
        if not cls.is_nvsipl_camera_command(cmd):
            return False
        # 有 -r <数字> 参数的会自动退出
        if re.search(r'\s-r\s+\d+', cmd):
            return False
        return True

    # 跟随型命令：持续输出、不会自行退出（类似 tail -f），
    # 直接同步执行会把持久会话的前台终端永久占住。
    # 执行器识别到后转入后台运行，用例结束时统一结束并收集日志。
    _FOLLOW_PATTERNS = (
        # slog2info -w / -W / -aW ...
        r'\bslog2info\b[^|;&]*\s-[a-zA-Z]*[wW][a-zA-Z]*\b',
        # journalctl -f / -xf / --follow[=...]
        r'\bjournalctl\b[^|;&]*\s(?:-[a-zA-Z]*f[a-zA-Z]*\b|--follow)',
        # dmesg -w / -W / --follow
        r'\bdmesg\b[^|;&]*\s(?:-[a-zA-Z]*[wW][a-zA-Z]*\b|--follow)',
        # tail -f / -F / -fn 10 / --follow
        r'\btail\b[^|;&]*\s(?:-[a-zA-Z]*[fF][a-zA-Z]*\b|--follow)',
    )

    @classmethod
    def is_follow_command(cls, cmd: str) -> bool:
        """命令是否为「跟随型」：启动后持续输出、不会自行结束。

        ``slog2info -W | grep nvsipl`` 这类命令同步执行时 shell 会一直等待，
        框架也只能等满超时；识别出来后由执行器转入后台，用例结束时再结束。
        """
        if not cmd:
            return False
        return any(re.search(pat, cmd) for pat in cls._FOLLOW_PATTERNS)

    @staticmethod
    def build_nvsipl_piped_command(base_cmd: str, stdin_lines: List[str]) -> str:
        """合并 nvsipl_camera + 交互输入为管道命令。

        支持 'sleep N' 作为特殊指令——不作为 nvsipl 子命令，
        而是在管道输入流中插入真实的 shell sleep 延迟。
        """
        def _sq(s: str) -> str:
            return "'" + s.replace("'", "'\"'\"'") + "'"

        # 检查是否有 sleep 指令（需要用 shell 组合命令实现延迟）
        has_sleep = any(line.startswith("sleep ") for line in stdin_lines)

        if not has_sleep:
            # 简单模式：printf 管道
            quoted = " ".join(_sq(line) for line in stdin_lines)
            return f"printf '%s\\n' {quoted} | {base_cmd.strip()}"
        else:
            # 延迟模式：用 { echo ...; sleep N; echo ...; } | cmd
            parts = []
            for line in stdin_lines:
                if line.startswith("sleep "):
                    parts.append(f"{line}")
                else:
                    parts.append(f"echo {_sq(line)}")
            shell_block = "{ " + "; ".join(parts) + "; }"
            return f"{shell_block} | {base_cmd.strip()}"

    # ------------------------------------------------------------------
    # NA 识别
    # ------------------------------------------------------------------
    @classmethod
    def should_mark_na(cls, *texts: str) -> Tuple[bool, str]:
        """合并多个字段文本判断是否标记 NA。"""
        combined = " ".join(t or "" for t in texts)
        for kw in cls.NA_KEYWORDS:
            if kw.lower() in combined.lower():
                return True, f"命中 NA 关键字: {kw}"
        for field_text in texts:
            if field_text and field_text.strip() in cls.NA_EXACT_KEYWORDS:
                return True, "命中 NA 精确关键字"
        return False, ""

    # ------------------------------------------------------------------
    # 步骤等待解析
    # ------------------------------------------------------------------
    @classmethod
    def extract_wait_seconds(cls, text: str) -> float:
        """从步骤文本中提取等待秒数。

        支持「等待2秒」「等待 2 秒钟」「延时1.5s」「等待1分钟」「wait 2s」等写法；
        同一文本中出现多处等待时累加。返回 0 表示该步骤无需额外等待。
        """
        if not text:
            return 0.0
        normalized = str(text).translate(cls._FULLWIDTH_DIGITS)
        total = 0.0
        for match in cls._WAIT_UNIT_PATTERN.finditer(normalized):
            value = float(match.group(1))
            unit = match.group(2).lower()
            if unit.startswith(("毫秒", "ms")):
                total += value / 1000.0
            elif unit.startswith(("分", "m")):
                total += value * 60.0
            else:  # 秒 / s / sec / second ...
                total += value
        return min(total, cls.MAX_WAIT_SECONDS)

    @staticmethod
    def _duration_seconds(value: float, unit: str) -> float:
        """把 (数值, 单位) 转成秒；unit 为空时按秒处理。"""
        unit = (unit or "秒").lower()
        if unit.startswith(("毫秒", "ms")):
            return value / 1000.0
        if unit.startswith(("分", "m")):
            return value * 60.0
        return value

    @classmethod
    def extract_nvsipl_expect(
        cls, text: str,
    ) -> Tuple[str, bool, Optional[float]]:
        """解析 nvsipl_input 步骤内的「等待输出 / 超时」配置。

        支持：
          等待输出：Frame rate
          等待输出:/Frame rate[^:]*:\\s*[\\d.]+/，超时20秒
          等待输出：Link，超时：2s

        返回 ``(pattern, is_regex, timeout_seconds)``：
        - pattern 为空表示未配置，执行时沿用 _NVSIPL_INPUT_EXPECT 表；
        - ``/.../`` 包裹的内容按正则使用，其余按普通文本（执行时转义）。
        """
        if not text:
            return "", False, None
        normalized = str(text).translate(cls._FULLWIDTH_DIGITS)

        marker = cls._EXPECT_OUTPUT_MARKER.search(normalized)
        if not marker:
            return "", False, None

        rest = normalized[marker.end():]
        timeout_match = cls._EXPECT_TIMEOUT_PATTERN.search(rest)
        timeout_seconds: Optional[float] = None
        if timeout_match:
            timeout_seconds = cls._duration_seconds(
                float(timeout_match.group(1)), timeout_match.group(2) or ""
            )
            rest = rest[:timeout_match.start()]

        raw = rest.strip()
        if not raw:
            return "", False, timeout_seconds

        # /.../ 视为正则；否则按普通文本，截到第一个分隔符/换行
        if raw.startswith("/"):
            close = raw.find("/", 1)
            if close > 0:
                return raw[1:close].strip(), True, timeout_seconds

        raw = re.split(r'[\n，,；;。]', raw, maxsplit=1)[0].strip()
        return raw, False, timeout_seconds

    @classmethod
    def is_wait_only_step(cls, text: str) -> bool:
        """判断步骤是否只是等待指令（如「等待2秒」，不含其他动作）。"""
        if not text:
            return False
        normalized = str(text).translate(cls._FULLWIDTH_DIGITS)
        # 终端标注（如「等待2秒（终端B）」）不是动作，判断前先去掉
        normalized = cls._TERMINAL_ANNOTATION_PATTERN.sub('', normalized)
        if not cls._WAIT_UNIT_PATTERN.search(normalized):
            return False
        remainder = cls._WAIT_UNIT_PATTERN.sub("", normalized)
        remainder = re.sub(r"[：:，,。．.；;、\s（）()【】\[\]]+", "", remainder)
        return not remainder

    @classmethod
    def _attach_step_waits(cls, steps: List["CommandStep"], text: str) -> List["CommandStep"]:
        """把每个原始步骤文本里的等待时长挂到该步骤产出的最后一条 CommandStep 上。

        同一步骤可能拆出多条命令（多终端/多行），等待应发生在整步执行完成之后，
        因此只挂到最后一条，避免每条命令后都重复等待。
        """
        wait_by_num = {
            num: cls.extract_wait_seconds(raw)
            for num, raw in cls.parse_steps_numbered(text)
        }
        last_by_num = {}
        for step in steps:
            if step.step_num:
                last_by_num[step.step_num] = step
        for num, step in last_by_num.items():
            seconds = wait_by_num.get(num, 0.0)
            if seconds <= 0:
                continue
            # 命令本身即 sleep N 时不再重复等待
            if step.kind == "command" and re.match(r"^\s*sleep\s+\d", step.command or ""):
                continue
            step.wait_seconds = seconds
        return steps

    # ------------------------------------------------------------------
    # 步骤切分
    # ------------------------------------------------------------------
    @staticmethod
    def parse_steps(text: str) -> List[str]:
        if not text:
            return []
        steps = re.split(r'(?:^|\n)\s*\d+[、.．]\s*', text)
        return [s.strip() for s in steps if s.strip()]

    @staticmethod
    def parse_steps_numbered(text: str) -> List[Tuple[int, str]]:
        """切分步骤并保留原始编号。返回 [(step_num, step_text), ...]"""
        if not text:
            return []
        # 找到所有编号标记及其位置
        pattern = re.compile(r'(?:^|\n)\s*(\d+)[、.．]\s*', re.MULTILINE)
        matches = list(pattern.finditer(text))
        if not matches:
            # 无编号，整段作为一个步骤
            stripped = text.strip()
            return [(1, stripped)] if stripped else []
        result = []
        for i, m in enumerate(matches):
            step_num = int(m.group(1))
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[start:end].strip()
            if content:
                result.append((step_num, content))
        return result

    # ------------------------------------------------------------------
    # 命令提取
    # ------------------------------------------------------------------
    @classmethod
    def extract_command(cls, text: str) -> Optional[str]:
        if not text:
            return None
        # 去掉带圈数字注释与「注：」
        text = re.split(r'[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]', text)[0]
        text = re.split(r'注[：:]', text)[0]
        text = text.replace('\n', ' ').replace('\r', '')

        for idx, pattern in enumerate(cls._EXTRACT_PATTERNS):
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            cmd = match.group(1).strip()
            # 去掉命令尾部的「等待N秒」等等待说明，避免被当作命令参数下发
            cmd = cls._WAIT_UNIT_PATTERN.sub('', cmd)
            cmd = re.sub(r'[。，；、\s]*$', '', cmd)
            cmd = re.split(r'\s*注[：:]', cmd)[0].strip()
            cmd = re.split(r'\s*[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑯⑰⑱⑲⑳]', cmd)[0].strip()
            # 去掉命令里夹带的终端标注（如「./tool --flag（终端B）」）
            cmd = cls._TERMINAL_ANNOTATION_PATTERN.sub('', cmd).strip()
            if not cmd or len(cmd) < 2:
                continue
            # 显式引导模式（执行命令：/ 指令：等）直接信任
            if idx < cls._EXPLICIT_PATTERN_COUNT:
                return cmd
            if cls.is_valid_command(cmd):
                return cmd
        return None

    @classmethod
    def find_terminal_mentions(cls, text: str) -> List[Tuple[int, str]]:
        """返回文本中所有终端字样 ``[(位置, 归一化标签)]``。

        只要出现「终端A」「终端B」「终端2」等字样即识别，不限出现在步骤
        的开头还是句中，也不要求后面带冒号；``[终端B]`` / ``（终端B）``
        这类标注写法同样识别。位置取标注整体的起点（含紧邻左括号）。
        """
        if not text:
            return []
        mentions: List[Tuple[int, str]] = []
        for m in cls._TERMINAL_MENTION_PATTERN.finditer(text):
            start = m.start()
            # 标注常带括号，片段切分时把左括号一起算进去，便于整体剥离
            if start > 0 and text[start - 1] in "[（(":
                start -= 1
            mentions.append((start, cls.normalize_terminal_label(m.group(1))))
        for m in cls._LEGACY_OTHER_TERMINAL.finditer(text):
            mentions.append((m.start(), "终端B"))
        mentions.sort(key=lambda item: item[0])
        return mentions

    @classmethod
    def split_terminal_prefix(cls, text: str) -> Tuple[str, str]:
        """拆出步骤的终端标签，返回 ``(终端标签, 正文)``。

        支持 ``终端A：`` / ``终端B:`` / ``[终端B]`` / ``A>`` 三种写法，
        也兼容旧写法「另一个终端」「辅终端」（统一归一为终端B）。
        只要文本中任意位置出现「终端A」等字样就识别为该终端；标签位于
        开头时顺带截掉，位于句中时保留原文（避免把命令正文截断）。
        没有任何终端字样时返回默认终端与原文。
        """
        if not text:
            return DEFAULT_TERMINAL, ""
        match = cls._TERMINAL_PREFIX_PATTERN.match(text)
        if match:
            label = (match.group(1) or match.group(2) or "").strip()
            if not label and match.group(3):
                label = f"终端{match.group(3).upper()}"
            body = text[match.end():].lstrip(" 　")
            return cls.normalize_terminal_label(label), body
        # 终端字样出现在任意位置即识别（不再要求写在开头、也不再要求带冒号）
        mention = cls._TERMINAL_MENTION_PATTERN.search(text)
        if mention:
            label = cls.normalize_terminal_label(mention.group(1))
            if not text[:mention.start()].strip(" 　[（("):
                # 位于开头：截掉标签及其后的冒号/括号，正文交给下游提取
                body = text[mention.end():].lstrip(" 　：:]）)")
                return label, body
            # 位于句中：标签已识别，正文原样返回
            return label, text
        legacy = cls._LEGACY_OTHER_TERMINAL.search(text)
        if legacy:
            # 旧写法只说明「在另一个终端」，正文里通常还带着引导语，原样交给下游提取
            return "终端B", text
        return DEFAULT_TERMINAL, text

    @staticmethod
    def normalize_terminal_label(label: str) -> str:
        """把各种终端写法归一成 ``终端X`` 形式（开放标签，不做白名单限制）。"""
        label = (label or "").strip()
        if not label:
            return DEFAULT_TERMINAL
        if label in ("主终端", "主", "A", "a"):
            return DEFAULT_TERMINAL
        if label in ("辅终端", "辅助终端", "另一个终端", "第二个终端"):
            return "终端B"
        if label.startswith("终端"):
            rest = label[2:].strip()
            return f"终端{rest.upper()}" if rest else DEFAULT_TERMINAL
        # ``A>`` / ``b：`` 之类的单字母写法标准化为大写
        if len(label) == 1:
            return f"终端{label.upper()}"
        return label

    @classmethod
    def extract_all_commands(cls, text: str,
                             default_terminal: str = DEFAULT_TERMINAL,
                             trust_body: bool = False,
                             ) -> List[Tuple[str, str]]:
        """返回 [(命令, 终端标签)]，支持多终端 + 同一步骤多行命令。

        终端标签的识别规则：步骤里只要出现「终端A」「终端B」等字样就识别，
        不限开头、不要求冒号；同一步骤出现多个终端字样时各管其后的命令。
        多终端写法（任一方式均可，标签开放）：
            终端A：./nvsipl_camera -c cfg -m 0
            终端B：./fault_simulation.sh -i 7
            [终端C] ls /tmp
            在终端D执行命令：cat /tmp/log
            A> pwd
            执行命令：./tool --flag（终端E）

        同一步骤中多行独立命令的典型场景：
            输入如下命令注入故障：
            sudo ./fault_simulation_728.sh -i 7 -a 0x1a -n 5
            sudo ./fault_simulation_728.sh -i 7 -a 0x1a -n 6
            sudo ./fault_simulation_728.sh -i 7 -a 0x1a -n 7
        """
        if not text:
            return []
        commands: List[Tuple[str, str]] = []

        # 先按终端字样切分：一个原始步骤里可能写了多个终端
        # （如「终端A：… 终端B：…」），各自后面的命令归属各自终端。
        mentions = cls.find_terminal_mentions(text)
        segments = cls._split_segments_by_terminal(text, default_terminal)
        for idx, (label, segment) in enumerate(segments):
            multi = cls._extract_multiline_commands(segment)
            if multi:
                for cmd in multi:
                    commands.append((cmd, label))
                continue
            cmd = cls.extract_command(segment)
            if not cmd and trust_body and idx == 0:
                # 显式终端前缀后的正文整体视为该终端要执行的命令，
                # 避免 echo/ls 等没有行内冒号的普通命令被漏掉。
                cmd = cls._strip_decorations(segment)
            if cmd:
                commands.append((cmd, label))
        if commands:
            # 终端字样只作为标注出现时（如「执行命令：xxx（终端B）」），
            # 整步命令其实都属于该终端，这里按标注重新归属。
            if len(mentions) == 1 and all(
                label == default_terminal for _, label in commands
            ):
                commands = [(cmd, mentions[0][1]) for cmd, _ in commands]
            # 「分别在终端A和终端B执行以下命令」并列多终端、命令却只有一个归属时，
            # 按终端出现顺序逐条分配，避免所有命令都落到最后一个终端。
            labels = list(dict.fromkeys(label for _, label in mentions))
            if (len(labels) > 1 and len(commands) >= len(labels)
                    and all(label == commands[0][1] for _, label in commands)):
                commands = [
                    (cmd, labels[i % len(labels)])
                    for i, (cmd, _) in enumerate(commands)
                ]
        return commands

    @classmethod
    def _strip_decorations(cls, text: str) -> Optional[str]:
        """去掉步骤正文里的注释、等待说明与引导语，返回可执行的命令正文。"""
        clean = re.split(r'[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]', text or "")[0]
        clean = re.split(r'注[：:]', clean)[0]
        clean = cls._WAIT_UNIT_PATTERN.sub('', clean)
        clean = clean.replace('\n', ' ').replace('\r', ' ')
        # 「终端B 执行 echo hi」→「echo hi」：去掉正文开头的引导语
        clean = cls._LEADING_PROSE_PATTERN.sub('', clean).strip()
        clean = re.sub(r'[。，；、\s]*$', '', clean).strip()
        return clean or None

    @classmethod
    def _split_segments_by_terminal(cls, text: str,
                                    default_terminal: str = DEFAULT_TERMINAL,
                                    ) -> List[Tuple[str, str]]:
        """按终端字样把一段步骤文本切成 ``[(终端标签, 片段正文)]``。

        多个终端字样（如「终端A：… 终端B：…」）各管其后的内容；
        第一个终端字样之前的内容归属默认终端。没有终端字样时整体作为
        一个默认终端片段返回，保证后续逻辑与旧行为一致。
        """
        mentions = cls.find_terminal_mentions(text)
        if not mentions:
            return [(default_terminal, text)] if text.strip() else []
        segments: List[Tuple[str, str]] = []
        head = text[:mentions[0][0]].strip()
        if head:
            segments.append((default_terminal, head))
        for idx, (start, label) in enumerate(mentions):
            end = mentions[idx + 1][0] if idx + 1 < len(mentions) else len(text)
            piece = text[start:end].strip()
            # 去掉片段开头的终端标签（含「：」「[终端B]」「（终端B）」等写法）
            piece = cls._TERMINAL_LABEL_PREFIX.sub("", piece, count=1)
            piece = piece.lstrip(" 　：:]）),，、。；;")
            if piece:
                segments.append((label, piece))
        return segments

    @classmethod
    def _extract_multiline_commands(cls, text: str) -> Optional[List[str]]:
        """检测并拆分同一步骤内的多行独立命令。

        当步骤文本中有多行（≥2行）各自以 sudo ./ 或 ./ 或 sudo <命令关键字>
        或其他可执行命令开头时，逐行提取而非合并。

        返回 None 表示不是多行命令场景（交给 extract_command 处理）。
        """
        # 按行去掉带圈数字注释
        clean = re.split(r'[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]', text)[0]
        clean = re.split(r'注[：:]', clean)[0]
        lines = clean.strip().split('\n')

        # 只看像命令的行（以 sudo / ./ / i2c / devopen / cd / scp / export 等开头）
        _CMD_LINE_RE = re.compile(
            r'^\s*(?:sudo\s+)?(?:\./|nvsipl_camera\s|fault_simulation|'
            r'i2cmastercmd|i2ctransfer|i2cget|i2cset|devopen|devclose|'
            r'scp\s|cat\s|echo\s|export\s|source\s)', re.IGNORECASE)

        cmd_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if _CMD_LINE_RE.match(stripped):
                # 去掉行尾的「等待N秒」等等待说明，再清理尾部中文标点
                stripped = cls._WAIT_UNIT_PATTERN.sub('', stripped)
                stripped = re.sub(r'[。，；、\s]*$', '', stripped)
                cmd_lines.append(stripped)

        # 只有 ≥2 条命令行时才视为多行命令场景
        if len(cmd_lines) >= 2:
            return cmd_lines
        return None

    # ------------------------------------------------------------------
    # 步骤分类判断
    # ------------------------------------------------------------------
    @staticmethod
    def is_ssh_command(text: str) -> bool:
        if not text:
            return False
        return bool(re.match(r'^ssh\s+\S+', text.lower().strip()))

    @staticmethod
    def is_comment(text: str) -> bool:
        if not text:
            return False
        text = text.strip()
        if re.match(r'^(注[：:]|注意[：:]|备注[：:]|说明[：:]|Note[：:])', text, re.IGNORECASE):
            return True
        if re.match(r'^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑯⑰⑱⑲⑳]', text):
            return True
        return False

    @staticmethod
    def is_english_non_command_step(text: str, extracted_cmd: Optional[str] = None) -> bool:
        if extracted_cmd:
            return False
        if not text or not str(text).strip():
            return False
        if re.search(r"[一-鿿]", text):
            return False
        s = text.strip()
        if len(s) < 10:
            return False
        if not re.search(r"[A-Za-z]{4,}", s):
            return False
        return True

    @staticmethod
    def is_description_only(text: str) -> bool:
        if not text:
            return True
        text = text.strip()
        description_keywords = ['scp出来', '查看', '打开', '确认', '验证', '检查']
        has_description = any(kw in text for kw in description_keywords)
        cmd_features = [
            './', 'cd ', 'echo ', 'cat ', 'ls ', 'mkdir ', 'cp ', 'mv ',
            'rm ', 'sudo ', 'i2ctransfer', 'i2cget', 'i2cset', 'devopen', 'devclose',
        ]
        has_cmd = any(feat in text for feat in cmd_features)
        return has_description and not has_cmd

    @classmethod
    def is_manual_operation_step(cls, text: str) -> bool:
        if not text:
            return False
        return any(kw in text for kw in cls._MANUAL_KEYWORDS)

    @classmethod
    def is_valid_command(cls, cmd: str) -> bool:
        if not cmd or len(cmd) < 3:
            return False
        if cls.is_ssh_command(cmd):
            return False
        cmd_lower = cmd.lower()
        return any(kw in cmd_lower for kw in cls._CMD_KEYWORDS)

    # ------------------------------------------------------------------
    # 工作目录追踪
    # ------------------------------------------------------------------
    @classmethod
    def detect_enter_dir(cls, step_text: str, default_remote_path: str = "") -> Optional[str]:
        """若步骤是「进入调试目录」类，返回应切换到的绝对路径。"""
        if not step_text:
            return None
        if not any(kw in step_text for kw in cls._ENTER_DIR_KEYWORDS):
            return None
        # 优先用界面配置路径
        if default_remote_path:
            return default_remote_path
        # 其次从步骤文本里抠一个路径
        m = re.search(r'(/[\w./\-]+)', step_text)
        return m.group(1) if m else None

    @staticmethod
    def detect_cd(step_text: str) -> Optional[str]:
        """从 cd 命令中解析目标目录。"""
        if not step_text:
            return None
        m = re.search(r'\bcd\s+([^\s①②③④⑤；;]+)', step_text)
        return m.group(1).strip() if m else None

    # ------------------------------------------------------------------
    # 主入口：步骤文本 → CommandStep 序列
    # ------------------------------------------------------------------
    @classmethod
    def parse(cls, text: str, default_remote_path: str = "") -> List[CommandStep]:
        """将测试步骤文本解析为 CommandStep 列表（已过滤跳过项）。"""
        if not text:
            return []

        steps: List[CommandStep] = []
        for step_num, raw in cls.parse_steps_numbered(text):
            raw = raw.strip()
            if not raw:
                continue

            # 终端标签（终端A：/ [终端B] / A>）在这里统一拆出，
            # 只要步骤里出现「终端A」等字样就识别（不限开头、不要求冒号），
            # 后续所有分支产出的 CommandStep 都带上该终端标签。
            terminal, raw_body = cls.split_terminal_prefix(raw)
            had_prefix = bool(raw_body.strip()) and raw_body.strip() != raw
            if raw_body.strip():
                raw = raw_body.strip()

            # 反复起流N次（压力测试循环）
            repeat_stream_match = re.search(
                r'(?:反复|重复|循环)\s*(?:起流|启动|执行|运行)\s*(\d+)\s*次', raw)
            if repeat_stream_match:
                count = int(repeat_stream_match.group(1))
                steps.append(CommandStep(
                    kind="repeat_stream", command=str(count),
                    description=raw, terminal=terminal, step_num=step_num))
                continue

            # 重复步骤指令（"重复2-4步骤"、"重复第2~4步"）
            repeat_match = re.search(r'重复[第]?(\d+)\s*[-~到至]\s*(\d+)\s*[步]?', raw)
            if repeat_match:
                start_idx = int(repeat_match.group(1))
                end_idx = int(repeat_match.group(2))
                steps.append(CommandStep(
                    kind="repeat", command=f"{start_idx}-{end_idx}",
                    description=raw, terminal=terminal, step_num=step_num))
                continue

            # 单步重复指令（"重复步骤1"、"重复第1步"、"重复1步骤"）
            repeat_single_match = re.search(r'重复[第]?\s*(?:步骤)?\s*(\d+)\s*(?:步(?:骤)?)?', raw)
            if repeat_single_match:
                idx = int(repeat_single_match.group(1))
                steps.append(CommandStep(
                    kind="repeat", command=f"{idx}-{idx}",
                    description=raw, terminal=terminal, step_num=step_num))
                continue

            # 纯等待步骤（如「等待2秒」）：不执行命令，仅等待指定时长
            if cls.is_wait_only_step(raw):
                wait_seconds = cls.extract_wait_seconds(raw)
                steps.append(CommandStep(
                    kind="wait", command=f"{wait_seconds:g}",
                    description=raw, terminal=terminal, step_num=step_num))
                continue

            # 人工确认（前置条件专用语法）
            if raw.startswith(cls.MANUAL_CONFIRM_PREFIX):
                steps.append(CommandStep(
                    kind="confirm",
                    description=raw.replace(cls.MANUAL_CONFIRM_PREFIX, "").strip(),
                    terminal=terminal, step_num=step_num,
                ))
                continue

            # 跳过 SSH 连接命令
            if cls.is_ssh_command(raw):
                steps.append(CommandStep(kind="skip", description="SSH 连接命令（已跳过）", terminal=terminal, step_num=step_num))
                continue

            # 跳过注释
            if cls.is_comment(raw):
                steps.append(CommandStep(kind="skip", description="注释说明（已跳过）", terminal=terminal, step_num=step_num))
                continue

            # 进入调试目录
            enter_dir = cls.detect_enter_dir(raw, default_remote_path)
            if enter_dir:
                steps.append(CommandStep(kind="enter_dir", command=enter_dir, description=raw, terminal=terminal, step_num=step_num))
                continue

            # 人工操作步骤：自动转为人工确认（等价于在步骤开头写 MANUAL_CONFIRM）。
            # 执行到此暂停并弹出确认框，人工确认通过后继续；未通过/超时则用例失败。
            if cls.is_manual_operation_step(raw):
                steps.append(CommandStep(kind="confirm", description=raw, terminal=terminal, step_num=step_num))
                continue

            # Shell 内置命令检测（export/source）— 避免被误识别为 nvsipl 交互输入
            # "输入export VAR=value"、"执行 source /path"
            shell_builtin_match = re.search(
                r'(?:输入|执行)\s*((?:export|source)\s+\S+.*)', raw, re.IGNORECASE)
            if not shell_builtin_match:
                # 也匹配直接以 export/source 开头的步骤
                shell_builtin_match = re.match(r'((?:export|source)\s+\S+.*)', raw.strip(), re.IGNORECASE)
            if shell_builtin_match:
                shell_cmd = shell_builtin_match.group(1).strip()
                steps.append(CommandStep(kind="command", command=shell_cmd, description=raw, terminal=terminal, step_num=step_num))
                continue

            # nvsipl_camera 交互输入优先检测（"输入 gc 10"、"输入'al'"、"执行 dl 0, el 11"）
            # 需要在 extract_all_commands 之前，防止 "起流后输入al" 被误匹配为命令
            if cls.is_nvsipl_interactive_step(raw):
                # 额外判断：如果步骤主体（①②③前的第一行）含独立 nvsipl_camera 命令，
                # 则走 command 路径而非 nvsipl_input
                main_text = re.split(r'[①②③④⑤⑥⑦⑧⑨⑩]', raw)[0].split('\n')[0]
                if not cls.is_nvsipl_camera_command(main_text):
                    subcmds = cls.parse_nvsipl_interactive_inputs(raw)
                    expect_pattern, expect_is_regex, expect_timeout = (
                        cls.extract_nvsipl_expect(raw)
                    )
                    steps.append(CommandStep(
                        kind="nvsipl_input",
                        command=";".join(subcmds),
                        description=raw,
                        terminal=terminal,
                        step_num=step_num,
                        expect_pattern=expect_pattern,
                        expect_is_regex=expect_is_regex,
                        expect_timeout=expect_timeout,
                    ))
                    continue

            # 提取命令（含多终端）
            # 仅当步骤开头就标明了终端（前缀已截掉）时，才把正文整体当命令，
            # 防止句中提到终端但并没有可执行指令的步骤被误下发。
            cmds = cls.extract_all_commands(
                raw, default_terminal=terminal, trust_body=had_prefix)
            if cmds:
                for cmd, cmd_terminal in cmds:
                    # cd 命令单独标记以更新工作目录
                    cd_target = cls.detect_cd(cmd)
                    if cd_target is not None and cmd.strip().lower().startswith("cd "):
                        steps.append(CommandStep(kind="cd", command=cd_target, description=raw, terminal=cmd_terminal, step_num=step_num))
                    else:
                        steps.append(CommandStep(kind="command", command=cmd, description=raw, terminal=cmd_terminal, step_num=step_num))
                continue

            # 跳过纯英文说明
            if cls.is_english_non_command_step(raw):
                steps.append(CommandStep(kind="skip", description="纯英文说明（已跳过）", terminal=terminal, step_num=step_num))
                continue

            # 跳过描述性文字
            if cls.is_description_only(raw):
                steps.append(CommandStep(kind="skip", description="描述性文字（已跳过）", terminal=terminal, step_num=step_num))
                continue

            # 既无命令又不属于明确跳过类，记录为未识别（不执行，但留痕）
            steps.append(CommandStep(kind="skip", description=f"未识别步骤（已跳过）：{raw[:80]}", terminal=terminal, step_num=step_num))

        # 为每条原始步骤挂上「等待N秒」的等待时长
        return cls._attach_step_waits(steps, text)

    # ------------------------------------------------------------------
    # AI 解析结果后处理：替换未识别步骤
    # ------------------------------------------------------------------
    @staticmethod
    def apply_ai_parsed_steps(
        steps: List[CommandStep],
        ai_results: dict,
        case_key: str = "",
    ) -> List[CommandStep]:
        """将 AI 解析结果应用到正则解析的步骤列表中。

        只替换 kind="skip" 且描述含"未识别步骤"的项。
        AI 结果中 confidence >= 0.6 的替换为实际步骤，低于阈值的保留 skip
        但在 description 中附加 AI 建议信息。

        Args:
            steps: CommandParser.parse() 输出的步骤列表
            ai_results: { case_key: [ {command, description, kind, terminal, confidence, step_num}, ... ] }
            case_key: 当前用例的 key，用于在 ai_results 中查找
        Returns:
            替换后的步骤列表（原地修改 + 可能插入新步骤）
        """
        ai_steps = ai_results.get(case_key, [])
        if not ai_steps:
            return steps

        # 按 step_num 建立 AI 解析结果的索引
        ai_by_step: dict[int, list] = {}
        for ai_step in ai_steps:
            sn = ai_step.get("step_num", 0)
            ai_by_step.setdefault(sn, []).append(ai_step)

        MIN_CONFIDENCE = 0.6
        new_steps: List[CommandStep] = []

        for step in steps:
            # 只处理未识别步骤
            if step.kind != "skip" or "未识别步骤" not in step.description:
                new_steps.append(step)
                continue

            # 查找该步骤编号对应的 AI 解析结果
            ai_matches = ai_by_step.get(step.step_num, [])
            if not ai_matches:
                new_steps.append(step)
                continue

            replaced_steps: List[CommandStep] = []
            for ai_step in ai_matches:
                kind = ai_step.get("kind", "skip")
                command = ai_step.get("command", "")
                confidence = ai_step.get("confidence", 0.0)
                terminal = ai_step.get("terminal", "主终端")
                desc = ai_step.get("description", "")

                if kind == "skip" or not command:
                    continue

                if confidence >= MIN_CONFIDENCE:
                    replaced_steps.append(CommandStep(
                        kind=kind,
                        command=command,
                        description=f"[AI 识别] {desc}" if desc else f"[AI 识别] {command}",
                        terminal=terminal,
                        step_num=step.step_num,
                    ))

            if replaced_steps:
                # 等待时长从原步骤继承；原步骤文本被截断丢失时再从 AI 描述中补解析
                wait_seconds = step.wait_seconds
                if wait_seconds <= 0:
                    wait_seconds = max(
                        (CommandParser.extract_wait_seconds(s.description) for s in replaced_steps),
                        default=0.0,
                    )
                replaced_steps[-1].wait_seconds = wait_seconds
                new_steps.extend(replaced_steps)

            if not replaced_steps:
                # 低置信度：保留 skip 但附加 AI 建议
                suggestions = [
                    f"{a.get('command', '')} (置信度:{a.get('confidence', 0):.0%})"
                    for a in ai_matches if a.get("command")
                ]
                if suggestions:
                    hint = "；".join(suggestions)
                    step.description = f"{step.description} [AI 建议: {hint}]"
                new_steps.append(step)

        return new_steps
