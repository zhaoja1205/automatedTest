"""
C++ 类的正则扫描器 —— 「先出粗图」阶段用。

目标：
- 不装 libclang 也能秒出一张够用的 UML：给 `.h/.hpp/.hxx/.hh` 走一遍正则，
  抽出类名 / kind / 基类 / public·protected·private 成员 / namespace。
- 快、独立、无外部依赖；有识别边界（下面「已知漏识别」列了），
  更精细的东西留给 [[cpp_class_indexer]] 用 libclang 补。

被 [[classdiag_routes]] 的 /generate 调用；抽独立模块方便 pytest。

**已知漏识别**（记入模块 docstring，测试里也断言这些跳过是**故意**的）：
1. 函数指针字段 `void (*handler)(int);`  —— 星号在名字左边，字段正则匹配不到
2. 宏展开出的成员声明（`DECLARE_PROPERTY(foo)`）—— 正则不预处理宏
3. 模板全特化 `template<> class Foo<int>` —— 模板参数为空，name 里带 `<...>`
4. 嵌套类不合成到外层类的成员里（作为独立类查询是可行的）
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional


# --------- 数据结构 ---------

@dataclass
class Member:
    """一个成员：字段或方法。"""
    name: str
    kind: str                    # "field" | "method"
    access: str                  # "public" | "protected" | "private"
    type_str: str = ""           # 字段类型 or 方法返回类型
    params: str = ""             # 方法参数原文（含括号内），字段留空
    is_static: bool = False
    is_virtual: bool = False
    is_pure_virtual: bool = False
    is_override: bool = False
    is_const: bool = False       # 方法 const


@dataclass
class Base:
    """一个基类。"""
    name: str
    access: str = "public"       # class 默认 private / struct 默认 public，调用方决定
    is_virtual: bool = False


@dataclass
class ClassInfo:
    name: str
    qualified_name: str          # ns::Sub::Foo
    kind: str                    # "class" | "struct"
    template_params: str = ""     # 原文如 "typename T, int N"
    bases: list[Base] = field(default_factory=list)
    members: list[Member] = field(default_factory=list)
    source_file: str = ""
    line: int = 1
    namespace_path: list[str] = field(default_factory=list)  # ["ns","Sub"]
    is_abstract: bool = False    # 有任一纯虚方法就 True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "qualified_name": self.qualified_name,
            "kind": self.kind,
            "template_params": self.template_params,
            "is_abstract": self.is_abstract,
            "bases": [
                {"name": b.name, "access": b.access, "is_virtual": b.is_virtual}
                for b in self.bases
            ],
            "members": [
                {
                    "name": m.name, "kind": m.kind, "access": m.access,
                    "type_str": m.type_str, "params": m.params,
                    "is_static": m.is_static, "is_virtual": m.is_virtual,
                    "is_pure_virtual": m.is_pure_virtual,
                    "is_override": m.is_override, "is_const": m.is_const,
                }
                for m in self.members
            ],
            "source_file": self.source_file,
            "line": self.line,
            "namespace_path": self.namespace_path,
        }


# --------- 顶层入口 ---------

# 跳过的目录：这些一般是产物 / 三方库 / 编辑器元数据，扫上百 M 会拖慢一切
_SKIP_DIRS = {"build", ".git", "third_party", "third-party", "node_modules",
              ".vscode", ".idea", ".cache", "out", "dist", "cmake-build-debug"}
_HEADER_EXTS = (".h", ".hpp", ".hxx", ".hh")


def collect_headers(root: str) -> list[str]:
    """遍历目录，返回全部头文件绝对路径。跳过 _SKIP_DIRS。"""
    result: list[str] = []
    root_abs = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root_abs):
        # 就地过滤，os.walk 才不进去
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(_HEADER_EXTS):
                result.append(os.path.join(dirpath, fn))
    return result


def parse_project(root: str) -> list[ClassInfo]:
    """扫整个源码根，返回所有类。"""
    classes: list[ClassInfo] = []
    for path in collect_headers(root):
        try:
            classes.extend(parse_header(path))
        except Exception:
            # 单个头解析崩不应该拖累整个项目；实际部署会加日志，这里静默跳过
            continue
    return classes


def parse_projects(roots: list[str]) -> list[ClassInfo]:
    """扫多个根（source_dir + 各 include_dirs），合成一个 ClassInfo 列表。

    顺序按 `roots` 传入的顺序 —— 调用方把 source 放前面，include 放后面，
    这样 `_resolve_parents` 的 `candidates[0]` 兜底就自然偏向 source 里的定义，
    避免 include 里的同名占位类抢过来。

    同一个头文件（realpath 相同）只解析一次，避免 include 目录嵌到 source 里
    或多个 include 互相有重叠时重复扫。
    """
    classes: list[ClassInfo] = []
    seen: set[str] = set()
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for path in collect_headers(root):
            real = os.path.realpath(path)
            if real in seen:
                continue
            seen.add(real)
            try:
                classes.extend(parse_header(path))
            except Exception:
                continue
    return classes


def parse_header(path: str) -> list[ClassInfo]:
    """解析一个头文件，返回其中定义的所有类。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            src = f.read()
    except OSError:
        return []
    stripped = strip_comments(src)
    return _scan_classes(stripped, path)


# --------- 注释剥离（状态机） ---------

def strip_comments(src: str) -> str:
    """去掉 `//` 行注释、`/* */` 块注释；保留字符串和字符字面量里的注释样字符。

    做成显式状态机是因为一堆边界（转义、raw string、字符字面量、字符串里嵌 `//`）
    单纯 re.sub 处理不干净。行号保留（换行不吃），后续 line 定位靠得住。
    """
    out: list[str] = []
    i = 0
    n = len(src)
    state = "code"   # code / line_comment / block_comment / string / char / raw_string
    raw_delim = ""   # C++11 R"delim(...)delim"

    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""

        if state == "code":
            # raw string R"delim(...)delim"
            if c == "R" and nxt == '"':
                # 找结束定界符
                j = src.find("(", i + 2)
                if j != -1:
                    raw_delim = src[i + 2:j]
                    out.append(src[i:j + 1])
                    i = j + 1
                    state = "raw_string"
                    continue
            if c == "/" and nxt == "/":
                state = "line_comment"
                i += 2
                continue
            if c == "/" and nxt == "*":
                state = "block_comment"
                i += 2
                continue
            if c == '"':
                state = "string"
                out.append(c)
                i += 1
                continue
            if c == "'":
                state = "char"
                out.append(c)
                i += 1
                continue
            out.append(c)
            i += 1

        elif state == "line_comment":
            if c == "\n":
                out.append(c)
                state = "code"
            i += 1

        elif state == "block_comment":
            if c == "\n":
                out.append(c)   # 保行号
            if c == "*" and nxt == "/":
                i += 2
                state = "code"
                continue
            i += 1

        elif state == "string":
            if c == "\\" and nxt:
                out.append(c)
                out.append(nxt)
                i += 2
                continue
            out.append(c)
            if c == '"':
                state = "code"
            i += 1

        elif state == "char":
            if c == "\\" and nxt:
                out.append(c)
                out.append(nxt)
                i += 2
                continue
            out.append(c)
            if c == "'":
                state = "code"
            i += 1

        elif state == "raw_string":
            end_marker = ')' + raw_delim + '"'
            if src.startswith(end_marker, i):
                out.append(end_marker)
                i += len(end_marker)
                state = "code"
                continue
            out.append(c)
            i += 1

    return "".join(out)


# --------- 类扫描 ---------

# 类头：可选 template<...>、class/struct、名字、可选 <tparam>、可选 final、可选 : bases。
# 前置 (?<!\benum\s) 用来排除 `enum class Foo`。
# `friend class Foo;` 因为要求跟 `{` 才启动，天然被跳过。
# 前置声明 `class Foo;` 同理。
_CLASS_HEAD_RE = re.compile(
    r"""
    (?P<template>template\s*<[^;{}]*?>\s*)?
    (?<!\benum\s)(?P<kind>class|struct)\s+
    (?P<name>[A-Za-z_]\w*(?:\s*<[^{};]*?>)?)   # 名字，允许后跟 <...>（模板全特化）
    (?:\s+final)?
    (?:\s*:\s*(?P<bases>[^{;]*))?
    \s*\{
    """,
    re.VERBOSE,
)

_NAMESPACE_RE = re.compile(r"\bnamespace\s+([A-Za-z_][\w:]*)\s*\{")
_ACCESS_RE = re.compile(r"^\s*(public|protected|private)\s*:\s*$", re.MULTILINE)


def _scan_classes(src: str, path: str) -> list[ClassInfo]:
    """在已去注释的源码上扫类定义。

    实现思路：
      1. 建一个「offset → 当前 namespace 栈」的辅助结构（简单预扫）
      2. 用 _CLASS_HEAD_RE 找类头；对每个匹配，配对 `{` `}` 找类体
      3. 类体内部做「访问段切换 + 花括号深度」的扫描，只在 depth==0 层收成员
      4. 类体内部也再跑一遍 _CLASS_HEAD_RE，把嵌套类作为独立 ClassInfo 收进结果，
         其 namespace_path 追加外层类名（`outer_ns::Outer::Inner`）
    """
    ns_events = _collect_namespace_events(src)
    results: list[ClassInfo] = []

    pos = 0
    while True:
        m = _CLASS_HEAD_RE.search(src, pos)
        if not m:
            break

        body_start = m.end()   # 类体第一个字符位置（`{` 之后）
        body_end = _match_brace(src, body_start - 1)
        if body_end == -1:
            # 花括号不配对，跳过这一处,往后继续
            pos = m.end()
            continue

        # 名字里如果带 `<...>`（模板全特化）就拆出来
        raw_name = m.group("name").strip()
        base_name = re.split(r"\s*<", raw_name, 1)[0]
        template_params = ""
        if m.group("template"):
            tp = m.group("template").strip()
            inner = re.search(r"template\s*<(.*)>\s*$", tp, re.DOTALL)
            template_params = inner.group(1).strip() if inner else ""

        # 计算 namespace 栈
        ns_stack = _ns_stack_at(ns_events, m.start())
        qualified = "::".join(ns_stack + [base_name])

        default_access = "public" if m.group("kind") == "struct" else "private"
        bases = _parse_bases(m.group("bases") or "", default_access)

        members = _parse_class_body(src, body_start, body_end, default_access)
        is_abstract = any(x.is_pure_virtual for x in members)

        results.append(ClassInfo(
            name=base_name,
            qualified_name=qualified,
            kind=m.group("kind"),
            template_params=template_params,
            bases=bases,
            members=members,
            source_file=path,
            line=src.count("\n", 0, m.start()) + 1,
            namespace_path=list(ns_stack),
            is_abstract=is_abstract,
        ))

        # 嵌套类：把当前类体也扫一遍。让它们出现在结果里但不合成到 outer.members；
        # namespace_path 追加当前类名，这样 `outer_ns::Outer::Inner` 的全限定名能正确形成。
        body = src[body_start:body_end]
        nested = _scan_nested(body, path,
                              parent_ns=ns_stack + [base_name],
                              body_offset=body_start,
                              full_src=src)
        results.extend(nested)

        pos = body_end + 1

    return results


def _scan_nested(body: str, path: str, parent_ns: list[str],
                 body_offset: int, full_src: str) -> list[ClassInfo]:
    """在类体里再扫嵌套类。用同一套规则，但 namespace_path 用 parent_ns。

    需要在**类体内部**做扫描，所以直接对 body 跑 _CLASS_HEAD_RE。
    body_offset 用于把行号回算到 full_src 里。
    """
    results: list[ClassInfo] = []
    pos = 0
    while True:
        m = _CLASS_HEAD_RE.search(body, pos)
        if not m:
            break
        body_start = m.end()
        body_end = _match_brace(body, body_start - 1)
        if body_end == -1:
            pos = m.end()
            continue

        raw_name = m.group("name").strip()
        base_name = re.split(r"\s*<", raw_name, 1)[0]
        template_params = ""
        if m.group("template"):
            tp = m.group("template").strip()
            inner = re.search(r"template\s*<(.*)>\s*$", tp, re.DOTALL)
            template_params = inner.group(1).strip() if inner else ""

        qualified = "::".join(parent_ns + [base_name])
        default_access = "public" if m.group("kind") == "struct" else "private"
        bases = _parse_bases(m.group("bases") or "", default_access)
        members = _parse_class_body(body, body_start, body_end, default_access)
        is_abstract = any(x.is_pure_virtual for x in members)

        # 行号：body_offset + m.start() 落在 full_src
        abs_pos = body_offset + m.start()
        line_no = full_src.count("\n", 0, abs_pos) + 1

        results.append(ClassInfo(
            name=base_name,
            qualified_name=qualified,
            kind=m.group("kind"),
            template_params=template_params,
            bases=bases,
            members=members,
            source_file=path,
            line=line_no,
            namespace_path=list(parent_ns),
            is_abstract=is_abstract,
        ))

        # 递归：嵌套里再有嵌套（如 Outer::Inner::Deeper）
        inner_body = body[body_start:body_end]
        results.extend(_scan_nested(
            inner_body, path,
            parent_ns=parent_ns + [base_name],
            body_offset=body_offset + body_start,
            full_src=full_src,
        ))

        pos = body_end + 1
    return results


def _match_brace(src: str, open_pos: int) -> int:
    """给定 `{` 的位置，返回配对 `}` 的位置；不配对返回 -1。

    扫描过程中忽略字符串 / 字符字面量里的花括号；注释已在 strip_comments 干掉了。
    """
    if open_pos < 0 or open_pos >= len(src) or src[open_pos] != "{":
        return -1
    depth = 0
    i = open_pos
    n = len(src)
    in_str = False
    in_char = False
    while i < n:
        c = src[i]
        if in_str:
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if in_char:
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == "'":
                in_char = False
            i += 1
            continue
        if c == '"':
            in_str = True
            i += 1
            continue
        if c == "'":
            in_char = True
            i += 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


# --------- namespace 上下文 ---------

def _collect_namespace_events(src: str) -> list[tuple[int, str, list[str]]]:
    """预扫描 namespace 事件：每个事件是 (position, action, added_parts)。

    action ∈ {"enter","exit"}；enter 时 added_parts 是本条 namespace 加进去的段
    （处理 `namespace a::b { ... }` 一次加两段的情形），exit 时为空。

    这里用「配对花括号」而不是花括号计数：给每个 namespace `{` 找到它的 `}` 位置作为 exit。
    """
    events: list[tuple[int, str, list[str]]] = []
    for m in _NAMESPACE_RE.finditer(src):
        # anonymous namespace 已被 `\s+[A-Za-z_]` 排掉；`inline namespace` 会漏 —— 不影响 UML
        name = m.group(1)
        parts = name.split("::")
        open_pos = src.find("{", m.end() - 1)
        # 我们的正则末尾就吃了 `{`；m.end() 是 `{` 之后一位
        open_brace = m.end() - 1
        close_pos = _match_brace(src, open_brace)
        events.append((m.start(), "enter", parts))
        events.append((close_pos if close_pos != -1 else len(src), "exit", parts))
    events.sort(key=lambda x: (x[0], 0 if x[1] == "enter" else 1))
    return events


def _ns_stack_at(events: list[tuple[int, str, list[str]]], pos: int) -> list[str]:
    """给定源码偏移，返回当时的 namespace 栈。"""
    stack: list[str] = []
    for evt_pos, action, parts in events:
        if evt_pos > pos:
            break
        if action == "enter":
            stack.extend(parts)
        else:  # exit
            # 从栈顶弹掉这些 parts
            for _ in parts:
                if stack:
                    stack.pop()
    return stack


# --------- 基类子句 ---------

def _parse_bases(clause: str, default_access: str) -> list[Base]:
    """把 `public A, virtual private B<int, float>, C` 这样的子句拆开。

    尖括号深度感知的顶层逗号切分，避免把模板参数里的 `,` 当分隔符。
    """
    if not clause.strip():
        return []
    parts = _split_toplevel(clause, ",")
    bases: list[Base] = []
    for p in parts:
        raw = p.strip().rstrip(",").strip()
        if not raw:
            continue
        access = default_access
        is_virtual = False
        # 前置修饰词
        while True:
            m = re.match(r"^(public|protected|private|virtual)\b\s*(.*)", raw)
            if not m:
                break
            kw = m.group(1)
            raw = m.group(2)
            if kw == "virtual":
                is_virtual = True
            else:
                access = kw
        # 剩下的当基类名字（可能带 ::, <...>）
        name = raw.strip()
        if name:
            bases.append(Base(name=name, access=access, is_virtual=is_virtual))
    return bases


def _split_toplevel(text: str, sep: str) -> list[str]:
    """按 `sep` 切分文本，但忽略 `<...>`、`(...)`、`[...]` 内部的分隔符。"""
    result: list[str] = []
    depth_angle = 0
    depth_paren = 0
    depth_brack = 0
    buf: list[str] = []
    for c in text:
        if c == "<":
            depth_angle += 1
        elif c == ">":
            if depth_angle > 0:
                depth_angle -= 1
        elif c == "(":
            depth_paren += 1
        elif c == ")":
            if depth_paren > 0:
                depth_paren -= 1
        elif c == "[":
            depth_brack += 1
        elif c == "]":
            if depth_brack > 0:
                depth_brack -= 1
        if c == sep and depth_angle == 0 and depth_paren == 0 and depth_brack == 0:
            result.append("".join(buf))
            buf = []
        else:
            buf.append(c)
    if buf:
        result.append("".join(buf))
    return result


# --------- 类体成员 ---------

# 方法：可选修饰 + 返回类型 + 名字 + (...) + 可选 const/override/= 0/;
# 相较字段更贪 —— 见到 `(` 就当方法。构造/析构没有返回类型，单独一条正则匹配。
_METHOD_RE = re.compile(
    r"""
    ^\s*
    (?P<mods>(?:(?:static|virtual|inline|constexpr|explicit|friend)\s+)*)
    (?P<ret>[\w:<>\s\*&,]+?)      # 返回类型（尽量非贪）
    \s+(?P<name>~?[A-Za-z_]\w*)     # 名字（析构 `~Foo` 罕见但也放行）
    \s*\((?P<params>[^;]*?)\)
    (?P<post>[^;{]*)               # const / override / final / = 0 / noexcept 等
    \s*(?:=\s*(?:default|delete))?
    \s*(?:;|\{)
    """,
    re.VERBOSE | re.MULTILINE,
)

# 构造/析构（无返回类型）；名字必须与类名一致，但类名不在这里能拿到，
# 所以匹配所有形如 `Name(...)` 或 `~Name(...)`，调用方按类名过滤。
_CTOR_RE = re.compile(
    r"""
    ^\s*
    (?P<mods>(?:(?:explicit|constexpr|inline|virtual)\s+)*)
    (?P<name>~?[A-Za-z_]\w*)
    \s*\((?P<params>[^;]*?)\)
    (?P<post>[^;{]*)
    \s*(?:=\s*(?:default|delete))?
    \s*(?:;|\{)
    """,
    re.VERBOSE | re.MULTILINE,
)

# 字段：类型 + 名字（可能带数组 []），到 `;` 结束；不能含 `(`（否则是方法）。
_FIELD_RE = re.compile(
    r"""
    ^\s*
    (?P<mods>(?:(?:static|mutable|constexpr|inline|thread_local)\s+)*)
    (?P<type>(?:const\s+|volatile\s+)?[\w:<>\s\*&]+?)
    \s+(?P<name>[A-Za-z_]\w*)
    (?P<array>(?:\s*\[[^\]]*\])*)
    \s*(?:=\s*[^;]+)?
    \s*;
    """,
    re.VERBOSE | re.MULTILINE,
)


def _parse_class_body(src: str, body_start: int, body_end: int,
                       default_access: str) -> list[Member]:
    """扫类体拿成员。

    在 depth==0 层解析，深层跳过（自动忽略方法体、嵌套类体、初值列表）。
    访问段用 _ACCESS_RE 切换。
    """
    body = src[body_start:body_end]

    # 按 depth==0 段切片：拿到一个 (start_offset, text) 列表
    top_segments = _split_top_level_segments(body)

    members: list[Member] = []
    access = default_access
    # 需要类名来识别构造/析构 —— 从类头往回看太脏；对每个 top 段先跑方法，
    # 抓不到再跑构造/析构；构造/析构判定的是「无返回类型 + name 是标识符」。
    for text in top_segments:
        # 切访问段
        pieces = _split_by_access(text, access)
        for cur_access, chunk in pieces:
            access = cur_access
            # 把 chunk 按 `;` 拆成语句片段，逐个尝试匹配
            for stmt in _statements(chunk):
                m = _match_member(stmt, cur_access)
                if m:
                    members.append(m)
    return members


def _split_top_level_segments(body: str) -> list[str]:
    """把类体按 `{...}` 深层扒掉。返回 depth==0 的文本片段列表（拼起来还是原顺序）。

    做法：从头扫，遇到 `{` 就找配对 `}`，把内部整段 skip，只保留 depth==0 的字符。
    """
    out: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(body)
    in_str = False
    in_char = False
    while i < n:
        c = body[i]
        if in_str:
            if c == "\\" and i + 1 < n:
                buf.append(c); buf.append(body[i + 1]); i += 2; continue
            buf.append(c)
            if c == '"':
                in_str = False
            i += 1
            continue
        if in_char:
            if c == "\\" and i + 1 < n:
                buf.append(c); buf.append(body[i + 1]); i += 2; continue
            buf.append(c)
            if c == "'":
                in_char = False
            i += 1
            continue
        if c == '"':
            in_str = True; buf.append(c); i += 1; continue
        if c == "'":
            in_char = True; buf.append(c); i += 1; continue
        if c == "{":
            # 保留一个占位 `;`，让上层 statement 切分不粘连
            close = _match_brace(body, i)
            if close == -1:
                # 花括号不闭合：把剩下的都丢掉
                break
            i = close + 1
            buf.append(" ; ")
            continue
        buf.append(c)
        i += 1
    out.append("".join(buf))
    return out


def _split_by_access(text: str, current_access: str) -> list[tuple[str, str]]:
    """按 `public:` / `protected:` / `private:` 切段。返回 [(access, chunk), ...]。"""
    result: list[tuple[str, str]] = []
    last = 0
    access = current_access
    for m in _ACCESS_RE.finditer(text):
        chunk = text[last:m.start()]
        if chunk.strip():
            result.append((access, chunk))
        access = m.group(1)
        last = m.end()
    tail = text[last:]
    if tail.strip():
        result.append((access, tail))
    return result


def _statements(chunk: str) -> list[str]:
    """把段落按 `;` 拆成语句列表。空的和纯空白的过滤掉。"""
    return [s.strip() + ";" for s in chunk.split(";") if s.strip()]


# 关键词，不能被当类型（会误把 `using x = y;` 之类识成字段）
_STMT_SKIP_PREFIX = ("using ", "typedef ", "friend ", "template", "static_assert",
                     "enum ", "namespace ", "public:", "protected:", "private:")


def _match_member(stmt: str, access: str) -> Optional[Member]:
    """给一条语句字符串（以 `;` 结尾），尝试识别成 field/method。

    顺序：先跑 method 正则，命中就返回；否则跑 ctor（对返回类型缺席的情形），
    再退 field。识别不出的返回 None（enum、using、typedef、宏、内嵌类占位等）。
    """
    s = stmt.strip()
    if not s or s == ";":
        return None
    if any(s.startswith(p) for p in _STMT_SKIP_PREFIX):
        return None
    # 忽略访问段自身（split_by_access 已处理，但被拆分后还有可能残留）
    if _ACCESS_RE.match(s):
        return None

    # 方法优先
    m = _METHOD_RE.match(s + "\n")
    if m and "(" in s:
        name = m.group("name")
        # 析构 `~Foo` 走 ctor/dtor 分支（无返回类型，`virtual` 前缀会被误当返回类型）
        if not name.startswith("~"):
            mods = m.group("mods") or ""
            ret = (m.group("ret") or "").strip()
            params = (m.group("params") or "").strip()
            post = m.group("post") or ""
            return Member(
                name=name,
                kind="method",
                access=access,
                type_str=ret,
                params=params,
                is_static="static" in mods,
                is_virtual="virtual" in mods,
                is_pure_virtual=bool(re.search(r"=\s*0\s*[;{]", s)),
                is_override=("override" in post) or ("final" in post),
                is_const=bool(re.search(r"\)\s*const\b", s)),
            )

    # 构造/析构：无返回类型；判定条件是「析构 ~Name(」或「无返回类型的 Name(」
    prefix_head = s.split("(", 1)[0].strip()
    is_dtor_like = "~" in prefix_head
    if "(" in s and (is_dtor_like or not _looks_like_method_with_return(s)):
        cm = _CTOR_RE.match(s + "\n")
        if cm:
            name = cm.group("name")
            params = (cm.group("params") or "").strip()
            mods = cm.group("mods") or ""
            return Member(
                name=name,
                kind="method",
                access=access,
                type_str="",              # ctor/dtor 无返回类型
                params=params,
                is_static=False,
                is_virtual="virtual" in mods,
                is_pure_virtual=bool(re.search(r"=\s*0\s*[;{]", s)),
                is_override=False,
                is_const=False,
            )

    # 字段
    fm = _FIELD_RE.match(s)
    if fm:
        mods = fm.group("mods") or ""
        return Member(
            name=fm.group("name"),
            kind="field",
            access=access,
            type_str=(fm.group("type") or "").strip() + (fm.group("array") or ""),
            is_static="static" in mods,
        )
    return None


def _looks_like_method_with_return(s: str) -> bool:
    """粗判：`(` 前面是否有 >= 2 个 token（有返回类型的方法特征）。

    这样能把 `Foo(int)` 认成 ctor、把 `int Foo(int)` 认成方法。
    """
    prefix = s.split("(", 1)[0].strip()
    # 拆 token：去掉 `,` 之类杂符后按空格切
    tokens = re.split(r"[\s\*&]+", prefix)
    tokens = [t for t in tokens if t]
    # 至少 2 个 token 才认为「返回类型 + 名字」
    return len(tokens) >= 2
