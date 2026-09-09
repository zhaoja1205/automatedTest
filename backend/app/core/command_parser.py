"""命令解析（Web 版）。

从用例「测试步骤」自然语言文本中提取可在板端执行的 shell 命令序列，
替代早期「整段 test_steps 当一条命令」的简化做法。移植自桌面版
test_runner_app/core/executor.py 的命令解析与 NA 识别部分，保留：
- 步骤按数字序号切分
- 多模式命令提取（执行命令：/ ./xxx / i2cmastercmd / 反引号 / cd / sudo ...）
- 自动跳过 SSH 连接、注释、纯英文说明、描述性文字、人工操作步骤
- 工作目录追踪（cd / 进入调试目录）
- NA 自动识别

不包含桌面版的并行执行 / PTY 交互式 nvsipl / 十六进制比对等高级场景：
多终端步骤在这里退化为「按顺序执行各终端命令」，并在说明里标注，
避免一次性引入与 SSHManager 不支持的 PTY 依赖。
"""
import re
from typing import List, Optional, Tuple


class CommandStep:
    """解析出的单条可执行步骤。"""

    def __init__(self, kind: str, command: str = "", description: str = "", terminal: str = "主终端", step_num: int = 0):
        # kind: "command" / "skip" / "enter_dir" / "cd" / "manual" / "confirm" / "nvsipl_input" / "repeat" / "repeat_stream"
        self.kind = kind
        self.command = command
        self.description = description
        self.terminal = terminal
        self.step_num = step_num  # 原始步骤编号（1-based），0 表示未知

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
            if s:
                out.append(s)
        if out:
            return out

        # 模式1: 「输入 xxx」格式（无引号）
        pat1 = re.compile(
            r"输入(?!命令)(?:\s*)([a-zA-Z_][a-zA-Z0-9_]*(?:\s+[a-zA-Z0-9_\-.x]+)*)",
            re.UNICODE,
        )
        for m in pat1.finditer(main_text):
            s = m.group(1).strip().rstrip("，。；、")
            if s:
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
            cmd = re.sub(r'[。，；、\s]*$', '', cmd)
            cmd = re.split(r'\s*注[：:]', cmd)[0].strip()
            cmd = re.split(r'\s*[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑯⑰⑱⑲⑳]', cmd)[0].strip()
            if not cmd or len(cmd) < 2:
                continue
            # 显式引导模式（执行命令：/ 指令：等）直接信任
            if idx < cls._EXPLICIT_PATTERN_COUNT:
                return cmd
            if cls.is_valid_command(cmd):
                return cmd
        return None

    @classmethod
    def extract_all_commands(cls, text: str) -> List[Tuple[str, str]]:
        """返回 [(命令, 终端标签)]，支持多终端 + 同一步骤多行命令。

        同一步骤中多行独立命令的典型场景：
            输入如下命令注入故障：
            sudo ./fault_simulation_728.sh -i 7 -a 0x1a -n 5
            sudo ./fault_simulation_728.sh -i 7 -a 0x1a -n 6
            sudo ./fault_simulation_728.sh -i 7 -a 0x1a -n 7
        """
        if not text:
            return []
        commands: List[Tuple[str, str]] = []
        has_another = bool(re.search(
            r'另一个终端|第二个终端|新终端|新开终端|另开终端', text,
        ))
        if has_another:
            parts = re.split(
                r'(?=另一个终端|第二个终端|新终端|新开终端|另开终端)', text,
            )
            for part in parts:
                if not part.strip():
                    continue
                is_another = bool(re.match(
                    r'\s*(?:另一个终端|第二个终端|新终端|新开终端|另开终端)', part,
                ))
                label = "另一个终端" if is_another else "主终端"
                multi = cls._extract_multiline_commands(part)
                if multi:
                    for cmd in multi:
                        commands.append((cmd, label))
                else:
                    cmd = cls.extract_command(part)
                    if cmd:
                        commands.append((cmd, label))
        else:
            multi = cls._extract_multiline_commands(text)
            if multi:
                for cmd in multi:
                    commands.append((cmd, "主终端"))
            else:
                cmd = cls.extract_command(text)
                if cmd:
                    commands.append((cmd, "主终端"))
        return commands

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
                # 清理尾部中文标点
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

            # 反复起流N次（压力测试循环）
            repeat_stream_match = re.search(
                r'(?:反复|重复|循环)\s*(?:起流|启动|执行|运行)\s*(\d+)\s*次', raw)
            if repeat_stream_match:
                count = int(repeat_stream_match.group(1))
                steps.append(CommandStep(
                    kind="repeat_stream", command=str(count),
                    description=raw, step_num=step_num))
                continue

            # 重复步骤指令（"重复2-4步骤"、"重复第2~4步"）
            repeat_match = re.search(r'重复[第]?(\d+)\s*[-~到至]\s*(\d+)\s*[步]?', raw)
            if repeat_match:
                start_idx = int(repeat_match.group(1))
                end_idx = int(repeat_match.group(2))
                steps.append(CommandStep(
                    kind="repeat", command=f"{start_idx}-{end_idx}",
                    description=raw, step_num=step_num))
                continue

            # 单步重复指令（"重复步骤1"、"重复第1步"、"重复1步骤"）
            repeat_single_match = re.search(r'重复[第]?\s*(?:步骤)?\s*(\d+)\s*(?:步(?:骤)?)?', raw)
            if repeat_single_match:
                idx = int(repeat_single_match.group(1))
                steps.append(CommandStep(
                    kind="repeat", command=f"{idx}-{idx}",
                    description=raw, step_num=step_num))
                continue

            # 人工确认（前置条件专用语法）
            if raw.startswith(cls.MANUAL_CONFIRM_PREFIX):
                steps.append(CommandStep(
                    kind="confirm",
                    description=raw.replace(cls.MANUAL_CONFIRM_PREFIX, "").strip(),
                    step_num=step_num,
                ))
                continue

            # 跳过 SSH 连接命令
            if cls.is_ssh_command(raw):
                steps.append(CommandStep(kind="skip", description="SSH 连接命令（已跳过）", step_num=step_num))
                continue

            # 跳过注释
            if cls.is_comment(raw):
                steps.append(CommandStep(kind="skip", description="注释说明（已跳过）", step_num=step_num))
                continue

            # 进入调试目录
            enter_dir = cls.detect_enter_dir(raw, default_remote_path)
            if enter_dir:
                steps.append(CommandStep(kind="enter_dir", command=enter_dir, description=raw, step_num=step_num))
                continue

            # 人工操作步骤
            if cls.is_manual_operation_step(raw):
                steps.append(CommandStep(kind="manual", description=raw, step_num=step_num))
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
                steps.append(CommandStep(kind="command", command=shell_cmd, description=raw, step_num=step_num))
                continue

            # nvsipl_camera 交互输入优先检测（"输入 gc 10"、"输入'al'"、"执行 dl 0, el 11"）
            # 需要在 extract_all_commands 之前，防止 "起流后输入al" 被误匹配为命令
            if cls.is_nvsipl_interactive_step(raw):
                # 额外判断：如果步骤主体（①②③前的第一行）含独立 nvsipl_camera 命令，
                # 则走 command 路径而非 nvsipl_input
                main_text = re.split(r'[①②③④⑤⑥⑦⑧⑨⑩]', raw)[0].split('\n')[0]
                if not cls.is_nvsipl_camera_command(main_text):
                    subcmds = cls.parse_nvsipl_interactive_inputs(raw)
                    steps.append(CommandStep(kind="nvsipl_input", command=";".join(subcmds), description=raw, step_num=step_num))
                    continue

            # 提取命令（含多终端）
            cmds = cls.extract_all_commands(raw)
            if cmds:
                for cmd, terminal in cmds:
                    # cd 命令单独标记以更新工作目录
                    cd_target = cls.detect_cd(cmd)
                    if cd_target is not None and cmd.strip().lower().startswith("cd "):
                        steps.append(CommandStep(kind="cd", command=cd_target, description=raw, terminal=terminal, step_num=step_num))
                    else:
                        steps.append(CommandStep(kind="command", command=cmd, description=raw, terminal=terminal, step_num=step_num))
                continue

            # 跳过纯英文说明
            if cls.is_english_non_command_step(raw):
                steps.append(CommandStep(kind="skip", description="纯英文说明（已跳过）", step_num=step_num))
                continue

            # 跳过描述性文字
            if cls.is_description_only(raw):
                steps.append(CommandStep(kind="skip", description="描述性文字（已跳过）", step_num=step_num))
                continue

            # 既无命令又不属于明确跳过类，记录为未识别（不执行，但留痕）
            steps.append(CommandStep(kind="skip", description=f"未识别步骤（已跳过）：{raw[:80]}", step_num=step_num))

        return steps

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

            replaced = False
            for ai_step in ai_matches:
                kind = ai_step.get("kind", "skip")
                command = ai_step.get("command", "")
                confidence = ai_step.get("confidence", 0.0)
                terminal = ai_step.get("terminal", "主终端")
                desc = ai_step.get("description", "")

                if kind == "skip" or not command:
                    continue

                if confidence >= MIN_CONFIDENCE:
                    new_steps.append(CommandStep(
                        kind=kind,
                        command=command,
                        description=f"[AI 识别] {desc}" if desc else f"[AI 识别] {command}",
                        terminal=terminal,
                        step_num=step.step_num,
                    ))
                    replaced = True

            if not replaced:
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
