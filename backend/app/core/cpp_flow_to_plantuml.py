"""C++ 函数体 → PlantUML activity 流程图（后端版）。

从前端 `frontend/src/utils/cppFlowchart.ts` 的 `buildPlantUML` 移植。
两套实现保持输出一致，这样导出 docx 时拿到的图和前端"代码分析"页看到的图是同一张。

比 AI 生成流程图的优势：
  - **真实分支结构**：直接解析源码的 if/else/for/while/return/log，不会丢分支
  - **离线确定性**：相同 body 永远产出相同 PlantUML，没有 AI 调用成本和失败回退
  - **自动降级**：解析不到有效主体时返回空字符串，调用方走 AI 兜底或源码块

**长流程折叠**：参考用户反馈"图太长了横向放置"，大于阈值的流程会在 PlantUML 里
用 `|分区名|` 泳道切成多列。阈值 `LONG_FLOW_THRESHOLD` 默认 25 条节点以上触发。
"""
from __future__ import annotations

import re
from typing import Optional


# ---- 词法辅助 ----

def strip_comments(s: str) -> str:
    """去掉 C/C++ 注释（/* … */ 和 // … \\n），保留字符串字面量。"""
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        if i + 1 < n and s[i] == "/" and s[i + 1] == "*":
            i += 2
            while i + 1 < n and not (s[i] == "*" and s[i + 1] == "/"):
                i += 1
            i += 2
            out.append(" ")
            continue
        if i + 1 < n and s[i] == "/" and s[i + 1] == "/":
            while i < n and s[i] != "\n":
                i += 1
            continue
        if s[i] == '"' or s[i] == "'":
            q = s[i]
            out.append(s[i]); i += 1
            while i < n and s[i] != q:
                if s[i] == "\\":
                    out.append(s[i]); i += 1
                    if i < n:
                        out.append(s[i]); i += 1
                    continue
                out.append(s[i]); i += 1
            if i < n:
                out.append(s[i]); i += 1
            continue
        out.append(s[i]); i += 1
    return "".join(out)


def match_bracket(src: str, open_idx: int) -> int:
    """从 open_idx 位置的括号/花括号起找到匹配的闭括号；未匹配返回 -1。"""
    opener = src[open_idx]
    closer = {"(": ")", "{": "}", "[": "]"}.get(opener)
    if not closer:
        return -1
    depth = 0
    i, n = open_idx, len(src)
    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if c == '"' or c == "'":
            q = c; i += 1
            while i < n and src[i] != q:
                if src[i] == "\\":
                    i += 1
                    if i >= n:
                        break
                i += 1
            i += 1
            continue
        if c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def skip_ws(src: str, i: int) -> int:
    while i < len(src) and src[i].isspace():
        i += 1
    return i


def read_until_semi(src: str, p: int) -> tuple[str, int]:
    """从 p 读到最外层分号；返回 (文本, 新 pos)。"""
    i, n = p, len(src)
    pd = bd = 0
    in_str: Optional[str] = None
    buf: list[str] = []
    while i < n:
        c = src[i]
        if in_str is not None:
            buf.append(c)
            if c == in_str and src[i - 1] != "\\":
                in_str = None
            i += 1
            continue
        if c == '"' or c == "'":
            in_str = c
            buf.append(c)
            i += 1
            continue
        if c == "(" or c == "[":
            pd += 1
        elif c == ")" or c == "]":
            pd -= 1
        elif c == "{":
            bd += 1
        elif c == "}":
            bd -= 1
        if c == ";" and pd == 0 and bd == 0:
            return "".join(buf), i + 1
        buf.append(c)
        i += 1
    return "".join(buf), i


def read_cond(src: str, p: int) -> tuple[str, int]:
    """读 (cond)；p 指向 '('，返回 (cond 内文, '(' 对应 ')' 之后的位置)。"""
    close = match_bracket(src, p)
    if close < 0:
        return "", p
    return src[p + 1:close].strip(), close + 1


# ---- 节点类型 ----

# 日志/打印宏白名单：来自 drive-linux/samples/nvmedia/nvsipl/devblk/common/utils/sipl_error.h
# 以及 C 标准 printf。完整列表、严格全词匹配 —— 这样"长得像日志的用户函数"
# （例如 `MyLogWrapper()`）不会被误伤。
#
# 为什么是白名单而不是正则 `.*LOG.*`：
#   1. 严格可控：规则由用户给定的头文件决定，命中集合不随意扩散
#   2. 不误伤：业务层可能有 `GetFirmwareLogSize()` / `LogToDisk()` 等名字里带 Log
#      但本质是业务逻辑的函数，泛匹配会把它们吞掉
#   3. 易维护：新增宏就加名字，不用调正则
#
# 这些节点会在 _emit 阶段被整条跳过，不在流程图里画出来 —— 日志是副作用、
# 不是业务逻辑。
_LOG_MACROS = frozenset({
    # sipl_error.h 里所有日志宏（66 个）
    "LOG_DBG", "LOG_DEBUG", "LOG_INFO", "LOG_MSG",
    "SIPL_LOG_2STR", "SIPL_LOG_2STR_INT", "SIPL_LOG_3STR", "SIPL_LOG_3STR_UINT",
    "SIPL_LOG_ERR_2STR", "SIPL_LOG_ERR_2STR_INT", "SIPL_LOG_ERR_3STR",
    "SIPL_LOG_ERR_STR", "SIPL_LOG_ERR_STR_2DOUBLE", "SIPL_LOG_ERR_STR_2FLOAT",
    "SIPL_LOG_ERR_STR_2HEX", "SIPL_LOG_ERR_STR_2INT", "SIPL_LOG_ERR_STR_2SLONG",
    "SIPL_LOG_ERR_STR_2UINT", "SIPL_LOG_ERR_STR_2ULONG",
    "SIPL_LOG_ERR_STR_DOUBLE", "SIPL_LOG_ERR_STR_FLOAT",
    "SIPL_LOG_ERR_STR_HEX_2ULONG", "SIPL_LOG_ERR_STR_HEX_3ULONG",
    "SIPL_LOG_ERR_STR_HEX_AND_UINT", "SIPL_LOG_ERR_STR_HEX_UINT",
    "SIPL_LOG_ERR_STR_INT", "SIPL_LOG_ERR_STR_SLONG", "SIPL_LOG_ERR_STR_UINT",
    "SIPL_LOG_ERR_STR_UINT_AND_HEX", "SIPL_LOG_ERR_STR_ULONG",
    "SIPL_LOG_INFO_2STR", "SIPL_LOG_INFO_2STR_UINT", "SIPL_LOG_INFO_3STR_UINT",
    "SIPL_LOG_INFO_STR", "SIPL_LOG_INFO_STR_2HEX", "SIPL_LOG_INFO_STR_2UINT",
    "SIPL_LOG_INFO_STR_3UINT", "SIPL_LOG_INFO_STR_FLOAT",
    "SIPL_LOG_INFO_STR_HEX_UINT", "SIPL_LOG_INFO_STR_INT",
    "SIPL_LOG_INFO_STR_UINT", "SIPL_LOG_INFO_STR_ULONG",
    "SIPL_LOG_LINE", "SIPL_LOG_STR",
    "SIPL_LOG_STR_2DOUBLE", "SIPL_LOG_STR_2FLOAT", "SIPL_LOG_STR_2HEX",
    "SIPL_LOG_STR_2INT", "SIPL_LOG_STR_2SLONG", "SIPL_LOG_STR_2UINT",
    "SIPL_LOG_STR_2ULONG", "SIPL_LOG_STR_3UINT",
    "SIPL_LOG_STR_DOUBLE", "SIPL_LOG_STR_FLOAT",
    "SIPL_LOG_STR_HEX_2ULONG", "SIPL_LOG_STR_HEX_3ULONG",
    "SIPL_LOG_STR_HEX_AND_UINT", "SIPL_LOG_STR_HEX_UINT",
    "SIPL_LOG_STR_INT", "SIPL_LOG_STR_SLONG", "SIPL_LOG_STR_UINT",
    "SIPL_LOG_STR_UINT_AND_HEX", "SIPL_LOG_STR_UINT_FLOAT", "SIPL_LOG_STR_ULONG",
    "SIPL_LOG_WARN_2STR", "SIPL_LOG_WARN_STR", "SIPL_LOG_WARN_STR_UINT",
    # C 标准打印
    "printf",
})
# 预构造一个"行首是某个日志宏名、紧跟 `(` 或空白"的正则，严格全词匹配。
# 示例命中：`SIPL_LOG_ERR_STR("x")` / `printf ( "x" )`
# 不命中：  `MyLogWrapper()` / `printf_safe()` / `std::printf(...)`
LOG_RE = re.compile(
    r"^\s*(?:" + "|".join(sorted(_LOG_MACROS, key=len, reverse=True)) + r")\s*\("
)
DECL_RE = re.compile(
    r"^(static\s+)?(const\s+)?(inline\s+)?[A-Za-z_][\w:<>*\s&]*?\s+\*?\s*[A-Za-z_]\w*\s*(\=|\[)"
)
BRANCH_KW_RE = re.compile(r"^(if|else if|for|while|switch)\b")


def classify(t: str) -> Optional[dict]:
    """分类单条语句：return/log/decl/stmt。"""
    t = t.strip().rstrip(";")
    if not t:
        return None
    if re.match(r"^return\b", t):
        return {"type": "return", "text": t}
    if LOG_RE.search(t):
        return {"type": "log", "text": t}
    if DECL_RE.match(t) and not re.match(r"^(if|for|while|switch)\b", t):
        return {"type": "decl", "text": t}
    return {"type": "stmt", "text": t}


def read_sub_block(src: str, p: int) -> tuple[list[dict], int]:
    i = skip_ws(src, p)
    if i < len(src) and src[i] == "{":
        close = match_bracket(src, i)
        inner = src[i + 1:close]
        return parse_body(inner), close + 1
    text, end = read_until_semi(src, i)
    st = text.strip().rstrip(";")
    node = classify(st)
    return ([node] if node else []), end


def read_else_chain(src: str, k: int) -> tuple[list[dict], int]:
    """消化 `else [if (cond) { ... }] [else ...]?` —— 把整条
    `else if … else if … else` 吃到当前 if 的 else 分支里，形成嵌套
    `{type:'if', then, else: [{type:'if', then, else:[...]}]}` 结构。

    不这么做的话，`else if (B)` 会被外层循环的 kwMatch 当成独立顶层
    if 处理 → 外层 if 条件为真时流程继续走 else if 判断，违反 C/C++
    的 if/else if 互斥语义（issue: 代码分析页流程图里 if 条件满足
    后仍走 else if）。
    """
    if not re.match(r"^else\b", src[k:]):
        return [], k
    k = skip_ws(src, k + 4)
    # `else if (cond) { ... }` —— 读完后继续递归拉链
    if re.match(r"^if\b", src[k:]):
        ec = src.find("(", k)
        ec_cond, after_ec = read_cond(src, ec)
        eb_nodes, eb_end = read_sub_block(src, skip_ws(src, after_ec))
        next_nodes, next_end = read_else_chain(src, skip_ws(src, eb_end))
        return [{"type": "if", "cond": ec_cond, "then": eb_nodes, "else": next_nodes}], next_end
    # 普通 `else { ... }` —— 链到此结束
    eb_nodes, eb_end = read_sub_block(src, k)
    return eb_nodes, eb_end


def parse_body(src: str) -> list[dict]:
    """递归解析函数体 → FlowNode[]。支持 if/else if/else, for, while, switch, return, log, decl, stmt。"""
    out: list[dict] = []
    i, n = 0, len(src)
    while i < n:
        prev_i = i  # 进度守卫：下面各分支任何一支若没推进 i 就强推 1，防死循环
        i = skip_ws(src, i)
        if i >= n:
            break
        if src[i] == "{":
            close = match_bracket(src, i)
            if close < 0:
                # 不匹配的 `{`：放弃剩下的输入，避免下游递归卡住
                break
            out.extend(parse_body(src[i + 1:close]))
            i = close + 1
            if i <= prev_i:
                i = prev_i + 1
            continue
        m = BRANCH_KW_RE.match(src[i:])
        if m:
            kw = m.group(1)
            if kw == "if" or kw == "else if":
                cond_start = src.find("(", i)
                if cond_start < 0:
                    i = prev_i + 1
                    continue
                cond, after_cond = read_cond(src, cond_start)
                j = skip_ws(src, after_cond)
                then_nodes, then_end = read_sub_block(src, j)
                k = skip_ws(src, then_end)
                # 整条 else-if-else 链一次性消化，保持嵌套结构，避免后续
                # else if 被下一轮 BRANCH_KW_RE 误当作独立顶层 if
                else_nodes, k = read_else_chain(src, k)
                out.append({
                    "type": "if",
                    "cond": ("else if " if kw == "else if" else "") + cond,
                    "then": then_nodes,
                    "else": else_nodes,
                })
                i = k
                if i <= prev_i:
                    i = prev_i + 1
                continue
            # for / while / switch —— 简化为"进入循环 + 内部顺序执行"
            cond_start = src.find("(", i)
            if cond_start < 0:
                i = prev_i + 1
                continue
            cond, after_cond = read_cond(src, cond_start)
            body_nodes, body_end = read_sub_block(src, skip_ws(src, after_cond))
            out.append({"type": "stmt", "text": f"{kw} ({cond})"})
            out.extend(body_nodes)
            i = body_end
            if i <= prev_i:
                i = prev_i + 1
            continue
        if re.match(r"^else\b", src[i:]):
            # 孤立的 else（我们已经把它纳入上一个 if）—— 把块扁平化
            i = skip_ws(src, i + 4)
            eb_nodes, eb_end = read_sub_block(src, i)
            out.extend(eb_nodes)
            i = eb_end
            if i <= prev_i:
                i = prev_i + 1
            continue
        text, end = read_until_semi(src, i)
        st = text.strip().rstrip(";")
        node = classify(st)
        if node:
            out.append(node)
        i = end
        if i <= prev_i:
            i = prev_i + 1
    return out


# ---- PlantUML 输出 ----

def plant_label(s: str) -> str:
    """PlantUML activity beta 标签清理。

    `{} [] |` 在 activity 语法里是特殊字符（分组、注释、泳道/partition），
    原文本出现会让 plantuml 直接 400；全角替换是视觉接近的无损兜底。

    `< > %` 也是坑（creole 标签 `<color:red>`、`<b>`、`%newline()` 等）：
    C++ 里 `static_cast<T>`、`a >> 2`、`printf("%lld")` 直接 400。
    同样全角替换。
    """
    out = (str(s)
           .replace("\\", "\\\\")
           .replace('"', "＂")
           .replace("{", "❴")
           .replace("}", "❵")
           .replace("[", "⟦")
           .replace("]", "⟧")
           .replace("|", "❘")
           .replace("<", "＜")   # U+FF1C 防 creole 标签 `<color>` / 模板实参 `<T>`
           .replace(">", "＞")   # U+FF1E 配套；`>>` 也顺带被转成 `＞＞`
           .replace("%", "％"))  # U+FF05 防 creole 转义 `%newline()` 等
    out = re.sub(r"\r?\n", " ", out)
    out = re.sub(r"\s+", " ", out).strip()
    MAX = 240
    if len(out) > MAX:
        out = out[:MAX] + " …⟨截断⟩"
    return out


def _count_nodes(nodes: list[dict]) -> int:
    """估算节点数：用于判断是否需要横向泳道。"""
    cnt = 0
    for n in nodes:
        if n["type"] == "if":
            cnt += 1 + _count_nodes(n.get("then") or []) + _count_nodes(n.get("else") or [])
        else:
            cnt += 1
    return cnt


def _emit(nodes: list[dict], out: list[str], indent: str = "", colored: bool = True) -> None:
    """递归把 FlowNode[] 吐成 PlantUML activity beta 行。

    log 节点被整条跳过：日志/打印是副作用，不是业务逻辑，画在流程图里只会
    增加噪音和纵向高度。识别靠的是 `_LOG_MACROS` 显式白名单。

    if 分支里，若 then 分支以 return 结尾，整段用 `detach` 断开，让分支
    停止延展、不画 stop 终止圆圈 —— 避免 7 个 return 分支各挂 7 个圆圈
    把图撑得老长（activity beta 的 `stop` 会画一个圆圈节点）。
    """
    for n in nodes:
        t = n["type"]
        if t == "return":
            out.append(f"{indent}:{plant_label(n['text'])};{' <<#FFE4E6>>' if colored else ''}")
            out.append(f"{indent}stop")
            continue
        if t == "log":
            # 日志/打印节点整条丢弃
            continue
        if t == "decl":
            out.append(f"{indent}:{plant_label(n['text'])};{' <<#DCFCE7>>' if colored else ''}")
            continue
        if t == "stmt":
            out.append(f"{indent}:{plant_label(n['text'])};")
            continue
        if t == "if":
            cond = plant_label(re.sub(r"^else if\s+", "", n["cond"]))
            then_nodes = n.get("then") or []
            else_nodes = n.get("else") or []
            # 判断 then 是否"确定跳出"（以 return 结尾）；如果是，用 detach
            # 让 then 分支独立悬空，no 分支贯穿主流程 —— 节省大量纵向高度
            # （不画 stop 圆圈、不画分支合并线）
            then_jumps_out = bool(then_nodes) and then_nodes[-1].get("type") == "return"
            out.append(f"{indent}if ({cond}) then (yes)")
            if then_jumps_out:
                # 手工生成 then：log 跳过、其他照画，return 后换 detach 而不是 stop
                for sub in then_nodes[:-1]:
                    _emit([sub], out, indent + "  ", colored)
                last = then_nodes[-1]
                out.append(f"{indent}  :{plant_label(last['text'])};{' <<#FFE4E6>>' if colored else ''}")
                out.append(f"{indent}  detach")
            else:
                _emit(then_nodes, out, indent + "  ", colored)
            if else_nodes:
                out.append(f"{indent}else (no)")
                _emit(else_nodes, out, indent + "  ", colored)
            else:
                # 空 else 也要 push `else (no)` —— 这行是给 no 分支的箭头打文字标签
                # 用的（不打的话 no 箭头上没有"no"标注，用户反馈"分支缺少 no 的标志"）；
                # 空 else 不会产生额外方框，只让 PlantUML 把 no 直接连到汇合点，
                # 配合 skinparam ConditionEndStyle hline 汇合点就是一条水平线，无菱形。
                out.append(f"{indent}else (no)")
            out.append(f"{indent}endif")
            continue


# 长流程切分泳道阈值；大于这个节点数的流程会被按主干切分成横向多列（partition）。
LONG_FLOW_THRESHOLD = 25
# 每条泳道容纳的节点上限（切泳道时的粒度）
LANE_BUDGET = 15


def _split_lanes(nodes: list[dict], budget: int = LANE_BUDGET) -> list[list[dict]]:
    """把顶层节点按预算切成多段，每段将渲染到一个 partition 里。

    只在**顶层**切分；if 子分支内部的节点不切（否则图逻辑会断）。
    切点选在 return / 两个 if 之间 / 累计节点数超过预算时。
    """
    lanes: list[list[dict]] = []
    cur: list[dict] = []
    cur_cnt = 0
    for n in nodes:
        n_cnt = 1 if n["type"] != "if" else (1 + _count_nodes(n.get("then") or [])
                                              + _count_nodes(n.get("else") or []))
        if cur and cur_cnt + n_cnt > budget:
            lanes.append(cur)
            cur = []
            cur_cnt = 0
        cur.append(n)
        cur_cnt += n_cnt
        # return 之后必然到达 END，自然切点
        if n["type"] == "return":
            lanes.append(cur)
            cur = []
            cur_cnt = 0
    if cur:
        lanes.append(cur)
    return lanes


def build_plantuml_from_body(body_text: str, signature: str = "", colored: bool = True,
                              long_flow_lanes: bool = True) -> str:
    """从函数体文本生成 PlantUML activity 源码；源码为空或解析不出主体则返回 ""。

    long_flow_lanes=True 时，节点数 > LONG_FLOW_THRESHOLD 的流程会用 partition 切成
    横向泳道，避免 docx 嵌入时图纵向撑超一页。
    """
    if not body_text or not body_text.strip():
        return ""
    try:
        body = strip_comments(body_text)
        nodes = parse_body(body)
    except Exception:
        return ""
    if not nodes:
        return ""

    total = _count_nodes(nodes)
    use_lanes = long_flow_lanes and total > LONG_FLOW_THRESHOLD

    lines: list[str] = ["@startuml"]
    lines.append('skinparam defaultFontName "PingFang SC, Microsoft YaHei, Segoe UI"')
    lines.append("skinparam defaultFontSize 12")
    # 分支汇合点改画水平线而不是菱形；PlantUML activity beta 默认 `endif` 后画一个
    # merge diamond（空菱形），空 else 分支时视觉上就是一个"无内容的菱形"（用户反馈
    # "分支走完后一个菱形空图形"）。hline 让汇合点变成一条水平线，分支语义不变。
    lines.append("skinparam ConditionEndStyle hline")
    lines.append("skinparam activity {")
    if colored:
        lines += [
            "  BackgroundColor #F1F5F9",
            "  BorderColor #64748B",
            "  FontColor #1F2937",
            "  DiamondBackgroundColor #FEF3C7",
            "  DiamondBorderColor #D97706",
            "  DiamondFontColor #92400E",
            "  StartColor #0284C7",
            "  EndColor #DC2626",
            "  ArrowColor #475569",
        ]
    else:
        lines += [
            "  BackgroundColor #FFFFFF",
            "  BorderColor #444444",
            "  FontColor #000000",
            "  DiamondBackgroundColor #FFFFFF",
            "  DiamondBorderColor #444444",
            "  DiamondFontColor #000000",
            "  StartColor #000000",
            "  EndColor #000000",
            "  ArrowColor #444444",
        ]
    lines.append("}")
    # 注：早期这里追加过 `left to right direction` 想让 partition 横向排开。
    # 但 activity beta 并不支持这个指令：节点少时 plantuml 容忍它，一旦节点多、
    # 伴随多个 partition，解析器就直接返回 400（body 是一张错误 PNG，带着
    # "Syntax Error? [From string (line N)]"）。IReadRegisterSensor 这种
    # 长函数就是这么挂的。移除之，让 partition 走默认竖向排布。
    lines.append("start")
    sig = (signature or "").strip()
    if sig:
        lines.append(f":开始 · {plant_label(sig)};{' <<#E0F2FE>>' if colored else ''}")

    if use_lanes:
        # 老方案是每段包一个 `partition "阶段 N" { ... }`，初衷是配合
        # `left to right direction` 把多段横向并排。但那条指令在 activity beta
        # 根本不支持（节点一多就 400），已经被移除；留下的 partition 框此时
        # 就只剩视觉噪音：每段多一圈边框 + 一个"阶段 N"标题，纵向还更长。
        # 这里保留 `_split_lanes` 的切分（后续如需换成 fork / detach / 别的
        # 布局策略仍能用到），只是不再输出 partition 包装。
        lanes = _split_lanes(nodes)
        for lane_nodes in lanes:
            _emit(lane_nodes, lines, indent="", colored=colored)
    else:
        _emit(nodes, lines, indent="", colored=colored)

    # 直接 stop 结束 —— PlantUML 自身会画终止圆圈。再加 `:结束;` 节点会
    # 多出一个方框（用户反馈"最后总有一个单独的结束框图"的来源）。
    # 若最后一个顶层节点是 return，_emit 已经吐了 stop，不再追加
    # （避免 stop\nstop 画两个重叠终止圆圈）。
    last_is_return = nodes and nodes[-1].get("type") == "return"
    if not last_is_return:
        lines.append("stop")
    lines.append("@enduml")
    return "\n".join(lines)
