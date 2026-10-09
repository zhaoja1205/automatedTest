"""
C++ 函数定位 + 调用提取 — 时序图后端解析器。

Python 移植自前端 cppSeqDiagram.ts，逻辑对等，差异只在语言细节。

公开 API：
  find_function(source_roots, qualified_name)
      → list[FuncMatch]  （空 = 未找到；>1 = 多命中 → 409）

  extract_var_types(body, params='')
      → dict[str, str]   varName → TypeName

  extract_calls(body, current_class, var_types)
      → list[CallEvent]

  collect_source_files(root)
      → list[str]   .c/.cpp/.cxx/.cc 文件

已知漏识别（与 TS 版一致，记录在案）：
  - 嵌套在参数里的调用（X(f())） 只识别 X
  - 虚函数/多态真实接收者
  - 模板实例化、宏展开后的调用
  - auto 变量推导（lifeline 回退到变量名）
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional


# ─────────────────────────── 数据结构 ───────────────────────────

@dataclass
class FuncMatch:
    qualified_name: str   # Class::method 或裸函数名
    file: str
    line: int             # 函数定义起始行（1-based）
    class_name: str       # 所在类，自由函数时为 ""
    func_name: str        # 不含类前缀的方法名
    params: str           # 参数列表原文（去括号）
    body: str             # 函数体（去花括号，已剥注释）
    kind: str = "function"


@dataclass
class CallEvent:
    caller: str
    callee: str
    method: str
    args: str
    ret_var: Optional[str] = None
    is_self: bool = False
    raw: str = ""


# ─────────────────────────── 文件发现 ───────────────────────────

_SOURCE_EXTS = {".c", ".cpp", ".cxx", ".cc", ".C", ".CPP"}
_HEADER_EXTS = {".h", ".hpp", ".hxx", ".hh"}


def collect_source_files(root: str) -> list[str]:
    """递归收集 root 下所有 C/C++ 源文件（含头文件）。"""
    result = []
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            ext = os.path.splitext(fn)[1]
            if ext in _SOURCE_EXTS or ext in _HEADER_EXTS:
                result.append(os.path.join(dirpath, fn))
    return result


def collect_headers(root: str) -> list[str]:
    """递归收集 root 下所有头文件（供 autocomplete 用）。"""
    result = []
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if os.path.splitext(fn)[1] in _HEADER_EXTS:
                result.append(os.path.join(dirpath, fn))
    return result


# ─────────────────────────── 注释剥离 ───────────────────────────

def strip_comments(src: str) -> str:
    """剥离 C/C++ 行注释和块注释，保留行数（换行符保留）。"""
    result = []
    i = 0
    n = len(src)
    in_string = False
    string_char = ''
    while i < n:
        c = src[i]
        if in_string:
            result.append(c)
            if c == '\\' and i + 1 < n:
                i += 1
                result.append(src[i])
            elif c == string_char:
                in_string = False
            i += 1
            continue
        if c in ('"', "'"):
            in_string = True
            string_char = c
            result.append(c)
            i += 1
            continue
        if c == '/' and i + 1 < n:
            if src[i + 1] == '/':
                # 行注释：跳到行尾
                while i < n and src[i] != '\n':
                    i += 1
                continue
            if src[i + 1] == '*':
                # 块注释：跳到 */
                i += 2
                while i < n - 1 and not (src[i] == '*' and src[i + 1] == '/'):
                    if src[i] == '\n':
                        result.append('\n')
                    i += 1
                i += 2  # 跳过 */
                continue
        result.append(c)
        i += 1
    return ''.join(result)


# ─────────────────────────── 括号匹配 ───────────────────────────

_OPEN = {'(': ')', '[': ']', '{': '}'}
_CLOSE = set(_OPEN.values())


def match_bracket(s: str, open_pos: int) -> int:
    """返回 s[open_pos] 对应闭合括号的位置；找不到返回 -1。"""
    open_ch = s[open_pos]
    close_ch = _OPEN.get(open_ch)
    if close_ch is None:
        return -1
    depth = 1
    i = open_pos + 1
    n = len(s)
    while i < n and depth > 0:
        c = s[i]
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
        i += 1
    return i - 1 if depth == 0 else -1


# ─────────────────────────── 函数定位 ───────────────────────────

# 匹配 `RetType Class::Method(params) { ...`（或自由函数）
# 组：1=返回类型片段  2=全名（含可能的 Class::）  3=参数原文
_FUNC_DEF_RE = re.compile(
    r'(?:^|(?<=[;{}]))\s*'
    r'((?:(?:inline|static|virtual|explicit|constexpr|override|final|'
    r'template\s*<[^>]*>)\s*)*'
    r'[A-Za-z_][\w:<>,\s\*&~]*?)\s+'
    r'([A-Za-z_][\w]*(?:::[A-Za-z_~][\w]*)*)\s*'
    r'\(([^;{}]*?)\)\s*(?:const\s*)?(?:noexcept[^{;]*)?\{',
    re.MULTILINE | re.DOTALL,
)


def find_function(
    source_roots: list[str],
    qualified_name: str,
) -> list[FuncMatch]:
    """在 source_roots 下的所有 C/C++ 文件里找函数定义。

    qualified_name 格式：
      - `Class::method`  — 类方法
      - `method`         — 裸函数名（模糊匹配，可能多命中）

    返回命中列表：
      - 空   → 未找到
      - 长=1 → 唯一命中，直接用
      - 长>1 → 多命中，交给路由层返回 409
    """
    q = qualified_name.strip().lstrip(':')
    last_sep = q.rfind('::')
    q_class = q[:last_sep] if last_sep >= 0 else ''
    q_method = q[last_sep + 2:] if last_sep >= 0 else q

    results: list[FuncMatch] = []

    for root in source_roots:
        for fpath in collect_source_files(root):
            try:
                with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                    raw = f.read()
            except OSError:
                continue
            src = strip_comments(raw)
            _scan_file(src, fpath, q_class, q_method, results)

    # 精确全限定名命中优先；若有则只返回精确命中
    exact = [m for m in results if m.qualified_name == q]
    if exact:
        return exact
    return results


def _scan_file(
    src: str,
    fpath: str,
    q_class: str,
    q_method: str,
    out: list[FuncMatch],
) -> None:
    for m in _FUNC_DEF_RE.finditer(src):
        full_name = m.group(2).strip()
        last_sep = full_name.rfind('::')
        f_class = full_name[:last_sep] if last_sep >= 0 else ''
        f_method = full_name[last_sep + 2:] if last_sep >= 0 else full_name

        # 方法名不匹配就跳过
        if f_method != q_method:
            continue
        # 有类限定时类名也要匹配（支持短名和全限定名）
        if q_class:
            if not (f_class == q_class or f_class.endswith('::' + q_class)):
                continue

        # 找函数体左花括号
        open_brace = src.index('{', m.start(0) + len(m.group(0)) - 2)
        close_brace = match_bracket(src, open_brace)
        if close_brace < 0:
            continue

        body = src[open_brace + 1:close_brace]
        line = src[:m.start(0)].count('\n') + 1
        params = m.group(3).strip()
        qualified = (f_class + '::' + f_method) if f_class else f_method

        out.append(FuncMatch(
            qualified_name=qualified,
            file=fpath,
            line=line,
            class_name=f_class,
            func_name=f_method,
            params=params,
            body=body,
        ))


# ─────────────────────────── 变量类型推断 ───────────────────────────

def extract_core_type(raw: str) -> str:
    """从类型片段里剥一层 shared_ptr<T> / unique_ptr<T> / std:: 命名空间。"""
    t = raw.strip()
    t = re.sub(r'\b(const|volatile|static|mutable|inline|constexpr)\s+', '', t)
    smart = re.match(
        r'^(?:std::)?(?:shared_ptr|unique_ptr|weak_ptr)\s*<\s*([A-Za-z_][\w:]*)', t
    )
    if smart:
        return smart.group(1).replace('std::', '')
    t = re.sub(r'^std::', '', t)
    id_m = re.match(r'^([A-Za-z_][\w]*(?:::[A-Za-z_][\w]*)*)', t)
    return id_m.group(1) if id_m else ''


def _split_top_commas(s: str) -> list[str]:
    out, depth, buf = [], 0, []
    for c in s:
        if c in ('(', '[', '{', '<'):
            depth += 1
        elif c in (')', ']', '}', '>'):
            depth -= 1
        if c == ',' and depth == 0:
            out.append(''.join(buf))
            buf = []
            continue
        buf.append(c)
    tail = ''.join(buf).strip()
    if tail:
        out.append(tail)
    return out


# 声明模式：锚定到语句开头（前一字符是 ; { } 或串首）
# 类型必须大写开头（区分 C++ 类型与小写关键字）
_DECL_RE = re.compile(
    r'(?:(?:^|(?<=[;{}]))\s*)'
    r'((?:(?:const|volatile|static|mutable)\s+)*'
    r'[A-Z][\w]*(?:::[A-Z][\w]*)*(?:\s*<[^;{}=]*>)?)'
    r'(?:\s+(?:const\s+)?[\*&]*\s*|\s*[\*]+\s*(?:const\s+)?|\s*&\s*)'
    r'([a-z_][\w]*)\s*(?:=|;|\(|\{|\[)',
    re.MULTILINE,
)

_KW_SKIP = frozenset(['return', 'if', 'for', 'while', 'switch', 'else', 'case'])


def extract_var_types(body: str, params: str = '') -> dict[str, str]:
    """扫描函数体和参数列表，建立 varName → TypeName 映射。"""
    types: dict[str, str] = {}

    # 形参
    if params.strip():
        for part in _split_top_commas(params):
            trimmed = re.sub(r'\s*=.*$', '', part.strip())
            pm = re.search(r'([A-Za-z_][\w]*)\s*(?:\[\s*\d*\s*\])?\s*$', trimmed)
            if not pm:
                continue
            var_name = pm.group(1)
            type_str = trimmed[:pm.start()].strip()
            typ = extract_core_type(type_str)
            if typ and var_name not in types:
                types[var_name] = typ

    # 函数体内声明
    for m in _DECL_RE.finditer(body):
        var_name = m.group(2)
        if var_name in _KW_SKIP:
            continue
        typ = extract_core_type(m.group(1))
        if typ and var_name not in types:
            types[var_name] = typ

    return types


# ─────────────────────────── 调用提取 ───────────────────────────

_NON_CALL = frozenset([
    'if', 'for', 'while', 'switch', 'return', 'sizeof', 'typeid',
    'alignof', 'decltype', 'static_cast', 'dynamic_cast', 'const_cast',
    'reinterpret_cast', 'new', 'delete', 'throw', 'catch', 'typeof',
    'and', 'or', 'not', 'xor',
])

_IDENT_CHARS = re.compile(r'[\w:]')
_SPACE_RE = re.compile(r'\s+')


def _fold(s: str) -> str:
    return _SPACE_RE.sub(' ', s).strip()


def extract_calls(
    body: str,
    current_class: str,
    var_types: dict[str, str],
) -> list[CallEvent]:
    """顺序扫描函数体，提取所有顶层调用事件。"""
    calls: list[CallEvent] = []
    s = body
    n = len(s)
    i = 0
    self_class = current_class or 'Self'

    while i < n:
        c = s[i]
        # 跳字符串
        if c in ('"', "'"):
            q = c
            i += 1
            while i < n and s[i] != q:
                if s[i] == '\\':
                    i += 1
                i += 1
            i += 1
            continue
        # 兜底行注释
        if c == '/' and i + 1 < n and s[i + 1] == '/':
            while i < n and s[i] != '\n':
                i += 1
            continue
        if c != '(':
            i += 1
            continue

        close = match_bracket(s, i)
        if close < 0:
            break

        # 往前读方法名
        p = i - 1
        while p >= 0 and s[p].isspace():
            p -= 1
        name_end = p + 1
        while p >= 0 and _IDENT_CHARS.match(s[p]):
            p -= 1
        method_name = s[p + 1:name_end]

        if (
            not method_name
            or not re.match(r'^[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*$', method_name)
            or method_name in _NON_CALL
        ):
            i = close + 1
            continue

        # 判断调用形式
        q2 = p
        while q2 >= 0 and s[q2].isspace():
            q2 -= 1

        caller = self_class
        callee = self_class
        method = method_name
        is_self = False

        if q2 >= 1 and s[q2] == '>' and s[q2 - 1] == '-':
            # obj->method(args)
            r = q2 - 2
            while r >= 0 and s[r].isspace():
                r -= 1
            var_end = r + 1
            while r >= 0 and (s[r].isalnum() or s[r] in ('_', ']')):
                if s[r] == ']':
                    depth = 1
                    r -= 1
                    while r >= 0 and depth > 0:
                        if s[r] == ']':
                            depth += 1
                        elif s[r] == '[':
                            depth -= 1
                        r -= 1
                else:
                    r -= 1
            var_name = re.sub(r'\[.*?\]', '', s[r + 1:var_end]).strip()
            callee = var_types.get(var_name, var_name or 'Obj')
            method = method_name
        elif method_name.find('::') >= 0:
            last_colon = method_name.rfind('::')
            callee = method_name[:last_colon]
            method = method_name[last_colon + 2:]
        elif q2 >= 0 and s[q2] == '.':
            r = q2 - 1
            while r >= 0 and s[r].isspace():
                r -= 1
            var_end2 = r + 1
            while r >= 0 and (s[r].isalnum() or s[r] == '_'):
                r -= 1
            var_name2 = s[r + 1:var_end2]
            callee = var_types.get(var_name2, var_name2 or 'Obj')
            method = method_name
        else:
            is_self = True
            callee = self_class
            method = method_name

        # 返回值绑定
        stmt_start = p + 1
        while stmt_start > 0 and s[stmt_start - 1] not in (';', '{', '}'):
            stmt_start -= 1
        stmt_prefix = s[stmt_start:p + 1].strip()
        ret_var: Optional[str] = None
        assign_m = re.search(r'([A-Za-z_][\w]*)\s*=\s*$', stmt_prefix)
        if assign_m:
            ret_var = assign_m.group(1)

        args_raw = _fold(s[i + 1:close])
        calls.append(CallEvent(
            caller=caller,
            callee=callee,
            method=method,
            args=args_raw,
            ret_var=ret_var,
            is_self=is_self,
            raw=method_name + '(' + args_raw + ')',
        ))

        i = close + 1

    return calls
