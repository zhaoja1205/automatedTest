"""SWE.3 推送 D — 工程代码扫描器（regex 层 + libclang 可选层）。

**输出结构**（供 scan_cache/<component_id>.json 直接落盘）：

```json
{
  "component_id": "A001",
  "scanned_at": "...",
  "scanner_version": "regex-1.0",
  "files": [
    {
      "path": "include/serializer/MAX96717F.h",
      "sha1": "...",
      "is_sdk": false,
      "classes": [
        {
          "name": "MAX96717FDeviceDriver",   // 或 "__free__" 表示自由函数
          "base": "NvMDeviceDriver",
          "doc_comment": "...",
          "constants": [{ "name": "...", "value": "..." }],
          "variables": [{ "type": "...", "name": "...", "init": "..." }],
          "functions": [
            {
              "key": "include/serializer/MAX96717F.h::MAX96717FDeviceDriver::DriverCreate::a1b2c3d4",
              "name": "DriverCreate",
              "declaration": "NvMediaStatus DriverCreate(NvMDevice *handle)",
              "parameters": [{"name":"handle", "type":"NvMDevice *", "desc":""}],
              "returns": [{"type":"NvMediaStatus", "desc":""}],
              "doc_comment": "...",
              "body_lines": 48,
              "extracted_by": "regex",
              "is_sdk": false
            }
          ]
        }
      ]
    }
  ],
  "stats": { "total_files": 3, "total_classes": 4, "total_functions": 12 }
}
```

**符号 key**：`{file}::{class_or___free__}::{name}::{param_sig_sha1[0:8]}`
  - 同类同名函数通过参数签名 sha1 区分
  - 自由函数挂在特殊类 "__free__" 下

**libclang**：默认关；检测到 python-libclang 安装则增强（本次 regex 够用，libclang 的
            钩子留桩，具体代码补齐留给需要时再做）。
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime
from typing import Optional

from app.core import engineering_store

logger = logging.getLogger(__name__)

SCANNER_VERSION = "regex-1.2-hdrdedup"  # 2026-11-13: header 同名函数去重（保留 .c 定义）

# ---- 正则 ----

# 类定义：  class Foo [final] : public Bar { ...
#          struct Foo { ...
#          class Foo : public Bar, public Baz { ...   （多继承）
#          template <...> class Foo : public Bar { ...  （模板类头的 template<...> 由 _grab 做剪枝）
_CLASS_RE = re.compile(
    r"""
    (?:^|\n)\s*
    (?P<kind>class|struct)\s+
    (?P<name>[A-Za-z_]\w*)
    (?:\s+(?:final|sealed))?
    (?:\s*:\s*(?P<base>[^{;]+?))?        # base list: 允许多继承、access specifier、template base
    \s*\{
    """,
    re.VERBOSE,
)

# 函数定义/声明：候选 anchor —— 一个 (可带 ClassName:: 限定) 标识符后紧跟 '('，参数区允许嵌套。
# 返回类型用 _grab_return_type_before 线性抓，避免 catastrophic backtracking。
_FUNC_ANCHOR_RE = re.compile(
    r"""
    (?:(?P<qualifier>[A-Za-z_]\w*(?:\s*::\s*[A-Za-z_]\w*)*)\s*::\s*)?
    (?P<name>~?[A-Za-z_]\w*)
    \s*\(
    """,
    re.VERBOSE,
)

# 过滤掉这些明显非函数的 anchor 名字
_FUNC_NAME_BLACKLIST = {
    "if", "while", "for", "switch", "return", "sizeof", "throw",
    "typeof", "static_assert", "decltype", "alignof", "offsetof",
    "catch", "do", "else", "goto", "case", "default",
    "defined", "and", "or", "not", "xor",  # 预处理器
    "assert", "static_cast", "const_cast", "dynamic_cast", "reinterpret_cast",
}

# 常量：#define FOO 1 / const int FOO = 1 / constexpr int FOO = 1
_CONST_DEFINE_RE = re.compile(r"^\s*#\s*define\s+(?P<name>[A-Z_][A-Z0-9_]{2,})\s+(?P<value>[^\n/]+)")
_CONST_VAR_RE = re.compile(
    r"^\s*(?:const|constexpr|static\s+const)\s+(?:[A-Za-z_][\w:]*\s*[*&]?\s+)+"
    r"(?P<name>[A-Z_][A-Z0-9_]+)\s*=\s*(?P<value>[^;]+);"
)

# 类成员常量：行级匹配（在 class body 内扫），只认 static (constexpr|const)
#   static constexpr uint32_t kMaxLink = 4;
#   static const char* const kDefaultName = "foo";
#   static constexpr size_t kBufSize{256};
_MEMBER_CONST_RE = re.compile(
    r"^\s*static\s+(?:constexpr|const\s+(?!\s*=))"
    r"(?:\s+[A-Za-z_][\w:<>,\s*&]*?)"
    r"\s+(?P<name>[A-Za-z_]\w*)"
    r"(?:\s*\[[^\]]*\])?"              # 数组
    r"\s*(?:=\s*(?P<value>[^;]+)|\{\s*(?P<value2>[^}]*)\s*\})?"
    r"\s*;",
    re.MULTILINE,
)

# 类成员变量：匹配 "<type> m_xxx[={init}];"
#   NvMediaStatus m_status;
#   std::unique_ptr<Foo> m_bar{};
#   uint32_t m_count = 0U;
# 要求 name 以 m_ 开头（约定）或以小驼峰（首字母小写、含下划线）命名；跳过 static 行（归常量）
_MEMBER_VAR_RE = re.compile(
    r"^\s*(?!static\b|typedef\b|using\b|friend\b|public\b|private\b|protected\b|virtual\b|constexpr\b|explicit\b)"
    r"(?P<type>(?:const\s+)?[A-Za-z_][\w:]*(?:\s*<[^;{}\n]{0,120}>)?(?:\s*[*&])*)"
    r"\s+(?P<name>m_[A-Za-z_]\w*|k[A-Z]\w*)"
    r"(?:\s*\[[^\]]*\])?"
    r"\s*(?:=\s*(?P<init>[^;{]+)|\{\s*(?P<init2>[^}]*)\s*\})?\s*;",
    re.MULTILINE,
)

# doc 注释：函数/类前方紧跟的 /** ... */ 或 /// 多行
_DOC_RE = re.compile(r"(?:/\*\*[\s\S]*?\*/|(?:(?:\s*///[^\n]*\n)+))", re.MULTILINE)


# ---- 低层工具 ----

def _normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _extract_member_type(decl: str) -> str:
    """从一条形如 'static constexpr uint32_t kFoo = 1;' 的声明里抓出裸类型。

    去掉 static / constexpr / const 前缀和末尾的 '= ...;'，保留中间的"类型 + 修饰"。
    """
    s = _normalize_ws(decl.rstrip(";").split("=")[0].split("{")[0])
    for kw in ("static ", "constexpr ", "const "):
        while s.startswith(kw):
            s = s[len(kw):].strip()
    # 最后一个 token 通常是变量名，去掉
    toks = s.rsplit(" ", 1)
    if len(toks) == 2:
        s = toks[0].strip()
    return s


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", errors="replace")).hexdigest()


def _strip_comments(src: str) -> str:
    """粗暴剥除块注释和行注释，避免 regex 命中注释里的 'class X {'。

    保留换行以维持行号参考，但不参与匹配。
    """
    src = re.sub(r"/\*[\s\S]*?\*/", lambda m: "\n" * m.group(0).count("\n"), src)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def _find_matching_brace(src: str, open_idx: int) -> int:
    """从 src[open_idx] = '{' 起，返回配对 '}' 的索引（含）。"""
    assert src[open_idx] == "{"
    depth = 0
    i = open_idx
    while i < len(src):
        c = src[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return len(src) - 1  # 未闭合时兜底


def _grab_leading_doc(src: str, pos: int, max_back: int = 400) -> str:
    """返回位于 pos 之前紧挨着的 doc 注释文本（去掉 /** */ 包壳），没有则返回 ''。"""
    start = max(0, pos - max_back)
    chunk = src[start:pos]
    m = None
    for cand in _DOC_RE.finditer(chunk):
        m = cand
    if not m:
        return ""
    tail = chunk[m.end():]
    if tail.strip():
        return ""
    text = m.group(0)
    text = re.sub(r"^\s*/\*+", "", text)
    text = re.sub(r"\*+/\s*$", "", text)
    text = re.sub(r"^\s*\*\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*///\s?", "", text, flags=re.MULTILINE)
    return text.strip()


def _find_matching_paren(src: str, open_idx: int) -> int:
    """从 src[open_idx] = '(' 起，返回配对 ')' 的索引（含）。遇末尾返回 -1。"""
    assert src[open_idx] == "("
    depth = 0
    i = open_idx
    n = len(src)
    while i < n:
        c = src[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        elif c in ";{}":
            # 参数列表里不该出现分号或花括号 → 这不是函数签名
            return -1
        i += 1
    return -1


def _grab_return_type_before(src: str, name_start: int) -> Optional[str]:
    """从 name 之前"回退一小段"抓返回类型；无法抓到合理返回类型则返回 None（代表非函数）。

    规则（线性，无 regex 回溯）：
      - 从 name_start-1 开始向左扫，跳过空白
      - 收集直到遇到 ';' '{' '}' '(' 或行首 '#' 或文件起点为止
      - 中间允许模板尖括号 '<...>' 嵌套（跟踪 depth）
      - 若抓到的字符串里一个标识符都没有，返回 None
    """
    i = name_start - 1
    n = len(src)
    # 跳过紧挨 name 的空白
    while i >= 0 and src[i].isspace():
        i -= 1
    if i < 0:
        return None
    # 向左扫
    end = i + 1
    depth_angle = 0
    stop_pos = -1
    while i >= 0:
        c = src[i]
        if c == ">":
            depth_angle += 1
        elif c == "<":
            if depth_angle > 0:
                depth_angle -= 1
            else:
                stop_pos = i
                break
        elif depth_angle > 0:
            pass  # 模板里允许任何字符
        elif c in ";{}()":
            stop_pos = i
            break
        elif c == "\n":
            # 允许跨 1 行；再往上若遇到预处理器 '#' 行则停止
            # 简化：遇到 '\n' 后再往上继续，但如果再次遇到 '\n' 前仅出现 '#...' 则截断
            # 这里直接允许跨多行，容忍 'inline\nvoid foo(...)' 这种，上限 400 字符
            if end - i > 400:
                stop_pos = i
                break
        i -= 1
    start = stop_pos + 1 if stop_pos >= 0 else 0
    raw = src[start:end]
    # 去前导：行首 '#...' 预处理器行与 '::' 粘连
    raw = re.sub(r"(?m)^\s*#[^\n]*\n", "", raw).strip()
    if not raw:
        return None
    # 去掉行末的 ',' —— 如果出现这是个参数场景，拒绝
    if raw.endswith(","):
        return None
    # 必须以标识符或 ')' / '>' 结尾才可能是类型
    if not re.search(r"[A-Za-z_\w>*&]\s*$", raw):
        return None
    # 若 raw 本身就是 "else" "return" 等，不算
    tail = re.split(r"[\s*&]+", raw)[-1]
    if tail in _FUNC_NAME_BLACKLIST:
        return None
    # 若太短且没有字母（例如只是 '*'），拒绝
    if not re.search(r"[A-Za-z_]", raw):
        return None
    # 长度上限保护
    if len(raw) > 300:
        return None
    return raw



    """返回位于 pos 之前紧挨着的 doc 注释文本（去掉 /** */ 包壳），没有则返回 ''。"""
    start = max(0, pos - max_back)
    chunk = src[start:pos]
    # 从后往前找最近的 /** ... */ 或连续 ///
    m = None
    for cand in _DOC_RE.finditer(chunk):
        m = cand  # 保留最后一个（最靠近 pos）
    if not m:
        return ""
    # 中间不能夹代码（允许空白）
    tail = chunk[m.end():]
    if tail.strip():
        return ""
    text = m.group(0)
    text = re.sub(r"^\s*/\*+", "", text)
    text = re.sub(r"\*+/\s*$", "", text)
    text = re.sub(r"^\s*\*\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*///\s?", "", text, flags=re.MULTILINE)
    return text.strip()


# ---- 参数解析 ----

def _parse_params(raw: str) -> list[dict]:
    """逗号拆参数，但要跳过模板尖括号/圆括号内嵌逗号。"""
    raw = raw.strip()
    if not raw or raw == "void":
        return []
    out: list[dict] = []
    depth_angle = 0
    depth_paren = 0
    buf: list[str] = []
    for ch in raw:
        if ch == "<":
            depth_angle += 1
        elif ch == ">":
            depth_angle = max(0, depth_angle - 1)
        elif ch == "(":
            depth_paren += 1
        elif ch == ")":
            depth_paren = max(0, depth_paren - 1)
        if ch == "," and depth_angle == 0 and depth_paren == 0:
            seg = "".join(buf).strip()
            if seg:
                out.append(_split_type_name(seg))
            buf = []
        else:
            buf.append(ch)
    seg = "".join(buf).strip()
    if seg:
        out.append(_split_type_name(seg))
    return out


def _split_type_name(seg: str) -> dict:
    """从 "const char * name" 这类片段中拆 type / name。"""
    # 去默认值
    seg = re.sub(r"\s*=\s*[^,]+$", "", seg).strip()
    tokens = re.split(r"\s+", seg)
    if len(tokens) == 1:
        return {"type": tokens[0], "name": "", "desc": ""}
    # 最后一个单词作为 name，前面全是 type；若最后一个单词是指针/引用符号也归 type
    last = tokens[-1]
    if last in ("*", "&") or last.endswith("*") or last.endswith("&"):
        return {"type": seg, "name": "", "desc": ""}
    # name 可能带前导 '*'/'&'（如 "char *name" → 这里 tokens = ["char","*name"]）
    name = last.lstrip("*&")
    stars = last[:len(last) - len(name)]
    type_part = " ".join(tokens[:-1]).strip()
    if stars:
        type_part = (type_part + " " + stars).strip()
    return {"type": type_part, "name": name, "desc": ""}


def _parse_return_type(ret_raw: str) -> list[dict]:
    """返回类型描述，去修饰词留裸类型。"""
    ret = _normalize_ws(ret_raw)
    for keyword in ("virtual", "static", "inline", "explicit", "constexpr", "extern \"C\"", "extern"):
        if ret.startswith(keyword + " "):
            ret = ret[len(keyword) + 1:].strip()
    if not ret or ret == "void":
        return [{"type": "void", "desc": ""}]
    return [{"type": ret, "desc": ""}]


def _param_signature(params: list[dict]) -> str:
    """构造参数签名：仅用 type 拼接（忽略 name，避免同声明不同参数名的误区分）。"""
    return ",".join(_normalize_ws(p.get("type", "")) for p in params)


# ---- 单文件扫描 ----

def _scan_source(path_rel: str, text: str) -> dict:
    """扫描单个文件文本，返回 Swe3ScannedFile 结构。"""
    is_sdk = engineering_store.file_is_sdk(path_rel)
    sha1 = _sha1(text)
    stripped = _strip_comments(text)

    # 1) 先确定所有 class/struct 的开始/结束位置
    class_ranges: list[dict] = []
    for cm in _CLASS_RE.finditer(stripped):
        open_idx = cm.end() - 1  # '{' 位置
        if open_idx < 0 or open_idx >= len(stripped) or stripped[open_idx] != "{":
            continue
        end_idx = _find_matching_brace(stripped, open_idx)
        class_ranges.append({
            "name": cm.group("name"),
            "base": (cm.group("base") or "").strip(),
            "body_start": open_idx + 1,
            "body_end": end_idx,
            "doc_comment": _grab_leading_doc(text, cm.start()),
            "constants": [],
            "variables": [],
            "functions": [],
        })

    # 2) 识别常量 / #define（文件级 → __free__；类作用域内留给 regex 粗抽）
    free_constants = []
    for line_m in _CONST_DEFINE_RE.finditer(text):
        free_constants.append({
            "name": line_m.group("name"),
            "value": line_m.group("value").strip(),
        })

    # 2.5) 扫类成员常量 / 成员变量（仅在 class body 范围内）
    #     - static (constexpr|const) ... name = value;    → constants
    #     - type m_name[= init];                           → variables
    #     跳过函数签名范围（后面 3) 识别函数时会自然用 body_start/end 校验归属）
    for cr in class_ranges:
        body = stripped[cr["body_start"]:cr["body_end"]]
        # 成员常量
        for m in _MEMBER_CONST_RE.finditer(body):
            val = (m.group("value") or m.group("value2") or "").strip()
            cr["constants"].append({
                "name": m.group("name"),
                "type": _extract_member_type(m.group(0)),
                "value": val,
                "desc": "",
            })
        # 成员变量（跳过已经作为常量匹配上的行）
        taken_name = {c["name"] for c in cr["constants"]}
        for m in _MEMBER_VAR_RE.finditer(body):
            nm = m.group("name")
            if nm in taken_name:
                continue
            # 粗判：这一行后面紧跟 '(' → 其实是函数，跳过
            tail_start = m.end() - 1  # 指向 ';'
            if tail_start < 0:
                continue
            typ = (m.group("type") or "").strip()
            init = (m.group("init") or m.group("init2") or "").strip()
            cr["variables"].append({
                "name": nm,
                "type": typ,
                "init": init,
                "desc": "",
            })
            taken_name.add(nm)

    # 3) 识别所有函数定义/声明 —— 用线性方法避免 regex 回溯爆炸
    functions_by_scope: dict[str, list[dict]] = {}  # key=class_name 或 "__free__"
    seen_keys: set[str] = set()
    n = len(stripped)
    for am in _FUNC_ANCHOR_RE.finditer(stripped):
        name = am.group("name")
        qualifier = am.group("qualifier") or ""
        if name in _FUNC_NAME_BLACKLIST:
            continue
        # anchor 的真正起点：若有 qualifier，匹配整个 "Qual::name" 的起点
        anchor_start = am.start("qualifier") if qualifier else am.start("name")
        name_start = am.start("name")
        paren_open = am.end() - 1
        if paren_open >= n or stripped[paren_open] != "(":
            continue
        paren_close = _find_matching_paren(stripped, paren_open)
        if paren_close < 0:
            continue
        tail_start = paren_close + 1
        tail_end = min(n, tail_start + 80)
        tail = stripped[tail_start:tail_end]
        tm = re.match(
            r"\s*(?:(?:const|override|noexcept|final|mutable|&|&&)\s*)*"
            r"(?:=\s*(?:0|default|delete)\s*)?"
            r"(?P<end>[;{])",
            tail,
        )
        if not tm:
            continue
        end_char = tm.group("end")
        end_pos = tail_start + tm.end("end") - 1

        # 返回类型从 anchor 起点（含 qualifier）向左抓
        ret_raw = _grab_return_type_before(stripped, anchor_start)
        if ret_raw is None:
            continue
        if re.match(r"^\s*(class|struct|enum|namespace|typedef|using|template)\b", ret_raw):
            continue

        params_raw = stripped[paren_open + 1:paren_close]
        params = _parse_params(params_raw)
        returns = _parse_return_type(ret_raw)

        # 归属：优先用 qualifier 指定的类名；否则落在哪个 class 的 body 内就归该类，否则 __free__
        scope_name = "__free__"
        if qualifier:
            # 取 qualifier 的最后一段作为类名（忽略命名空间）
            parts = [p.strip() for p in qualifier.split("::") if p.strip()]
            if parts:
                scope_name = parts[-1]
        else:
            for cr in class_ranges:
                if cr["body_start"] <= name_start <= cr["body_end"]:
                    scope_name = cr["name"]
                    break

        decl_whole = stripped[anchor_start:end_pos]
        decl_full = (ret_raw + " " + decl_whole).strip()
        decl_raw = _normalize_ws(decl_full.rstrip("{; \t\n"))
        body_lines = 0
        body_text = ""  # 为后端"真实源码 → 流程图"重用做准备（≤8 KB，长函数截断）
        # 2026-11-11 推送 G 粒度升级：记录函数在 head 版源文件里的行范围
        # （stripped 保留换行，与 text 行号对齐；1-indexed）。用于 classify_functions
        # 把文件级 git diff hunk 映射到具体函数 — 文件在 changed_files 里但 hunk
        # 不落在 [line_start, line_end] 范围内的函数回落 unchanged，杜绝"3 个文件
        # 改动 → 176 个函数全连坐 modified"的粒度 bug。
        line_start = stripped.count("\n", 0, anchor_start) + 1
        line_end = line_start  # 无 body（纯声明）时 end = start，交集判定仍可用
        if end_char == "{":
            open_brace = end_pos
            end_idx = _find_matching_brace(stripped, open_brace)
            body = text[open_brace:end_idx + 1] if end_idx > open_brace else ""
            body_lines = body.count("\n")
            # 结束行 = open_brace 所在行 + body 跨越的换行数
            line_end = stripped.count("\n", 0, end_idx + 1) + 1 if end_idx > open_brace else line_start
            # 存一份函数体以便后端"源码 → PlantUML 流程图"复用
            # —— 真实分支结构远比 AI 推断的流程图准，缺点是极长函数会撑大 scan_cache。
            # 8 KB 已经够覆盖参考文档里出现的所有函数（流程图再长也是分支多，不是行多）。
            if body:
                MAX_BODY = 8 * 1024
                body_text = body if len(body) <= MAX_BODY else body[:MAX_BODY] + "\n// …<truncated>"

        sig = _param_signature(params)
        key = f"{path_rel}::{scope_name}::{name}::{_sha1(sig)[:8]}"
        if key in seen_keys:
            continue
        seen_keys.add(key)

        fn = {
            "key": key,
            "name": name,
            "declaration": decl_raw,
            "parameters": params,
            "returns": returns,
            "doc_comment": _grab_leading_doc(text, anchor_start),
            "body_lines": body_lines,
            "body_text": body_text,
            "line_start": line_start,     # 1-indexed；hunk 相交判定用
            "line_end":   line_end,
            "extracted_by": "regex",
            "is_sdk": is_sdk,
        }
        functions_by_scope.setdefault(scope_name, []).append(fn)

    # 4) 汇总
    classes_out: list[dict] = []
    for cr in class_ranges:
        cr["functions"] = functions_by_scope.pop(cr["name"], [])
        classes_out.append({
            "name": cr["name"],
            "base": cr["base"],
            "doc_comment": cr["doc_comment"],
            "constants": cr["constants"],
            "variables": cr["variables"],
            "functions": cr["functions"],
        })
    free_funcs = functions_by_scope.pop("__free__", [])
    # 剩下的都是 qualifier 命中的类（本文件无 class 声明，典型是 .cpp 里 ClassName::Method）
    for orphan_name, orphan_fns in sorted(functions_by_scope.items()):
        classes_out.append({
            "name": orphan_name,
            "base": "",
            "doc_comment": "",
            "constants": [],
            "variables": [],
            "functions": orphan_fns,
        })
    if free_funcs or free_constants:
        classes_out.append({
            "name": "__free__",
            "base": "",
            "doc_comment": "",
            "constants": free_constants,
            "variables": [],
            "functions": free_funcs,
        })

    return {
        "path": path_rel,
        "sha1": sha1,
        "is_sdk": is_sdk,
        "classes": classes_out,
    }


# ---- 对外主入口 ----

_HEADER_EXTS = (".h", ".hpp", ".hh", ".hxx", ".H")
_IMPL_EXTS   = (".c", ".cpp", ".cc", ".cxx", ".C")


def _dedup_header_decls(files_out: list[dict]) -> None:
    """R4 需求 #1：同名 (class_name, fn_name) 若同时在 .c/.cpp 与 .h/.hpp 出现，
    删掉 .h 侧那一份。原地修改 files_out；只在 header 里独有的条目（inline 定义
    或纯声明没有实现）保留，以免误伤。

    注意：
      - 比较用 (class_name, fn_name)，不看参数签名，正则扫描拿不到可靠签名；
        头文件最常见是重载/默认参数带不同签名，但这类函数在"同名"列表里给用户看到
        两条也没意义，直接合并。
      - 仅凭扩展名区分 header/impl，不去碰没有 .h/.c 后缀的文件（.inl、无扩展等
        保持原样）。
    """
    # 1) 收集 impl 侧已有的 (class_name, fn_name)
    impl_keys: set[tuple[str, str]] = set()
    for info in files_out:
        path = (info.get("path") or "")
        if not path.endswith(_IMPL_EXTS):
            continue
        for c in info.get("classes") or []:
            cname = c.get("name") or ""
            for fn in c.get("functions") or []:
                fname = (fn.get("name") or "").strip()
                if fname:
                    impl_keys.add((cname, fname))
    if not impl_keys:
        return
    # 2) 从 header 文件里删掉这些同名函数
    for info in files_out:
        path = (info.get("path") or "")
        if not path.endswith(_HEADER_EXTS):
            continue
        for c in info.get("classes") or []:
            cname = c.get("name") or ""
            fns = c.get("functions") or []
            if not fns:
                continue
            kept = [
                fn for fn in fns
                if (cname, (fn.get("name") or "").strip()) not in impl_keys
            ]
            if len(kept) != len(fns):
                c["functions"] = kept


def scan_module(project_id: str, component_id: str,
                hit_paths: list[str]) -> dict:
    """扫描一组文件，产出 Swe3ScanIndex 并落盘到 scan_cache。"""
    root = engineering_store.engineering_root(project_id)
    files_out: list[dict] = []
    total_classes = 0
    total_functions = 0
    for rel in hit_paths:
        abs_path = os.path.join(root, rel)
        if not os.path.isfile(abs_path):
            continue
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        if len(text) > 1_500_000:  # 1.5 MB 单文件上限，防爆
            continue
        info = _scan_source(rel, text)
        files_out.append(info)

    # R4 需求 #1：头文件 vs 实现文件同名函数去重
    # 场景：MPQ5864Init 在 .h 里有 declaration，在 .c 里有 definition，
    # 两份同名条目都进扫描结果 → 下游 L5 列表出两个 ...-function-029/-030 空壳。
    # 规则：(class_name, fn_name) 同时出现在 .c/.cpp/.cc/.cxx 和 .h/.hpp/.hh/.hxx →
    # 删掉 .h 侧条目；只在 .h 里出现的（inline 定义 / 纯声明）保留。
    _dedup_header_decls(files_out)

    # 去重后再统计
    total_classes = 0
    total_functions = 0
    for info in files_out:
        total_classes += sum(1 for c in info["classes"] if c["name"] != "__free__")
        total_functions += sum(len(c.get("functions") or []) for c in info["classes"])

    result = {
        "component_id": component_id,
        "scanned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scanner_version": SCANNER_VERSION,
        "files": files_out,
        "stats": {
            "total_files": len(files_out),
            "total_classes": total_classes,
            "total_functions": total_functions,
        },
    }
    # 推送 G：若已有 baseline_diff，为每个函数打 diff_status
    diff_summary = engineering_store.read_baseline_diff(project_id)
    classify_functions(result, diff_summary)
    # 保留旧 scan 里 AI 回写字段（ai_intro / ai_flowchart / ai_status / ai_retry_count /
    # ai_last_error / extracted_by）。不合并会在每次"重扫"时把用户昂贵 AI 结果清掉。
    _merge_ai_fields_from_old(project_id, component_id, result)
    engineering_store.write_scan_cache(project_id, component_id, result)
    return result


_AI_FIELDS_TO_PRESERVE = (
    "ai_intro", "ai_flowchart", "ai_status", "ai_retry_count",
    "ai_last_error", "flowchart_plantuml",
)


def _merge_ai_fields_from_old(project_id: str, component_id: str, new_scan: dict) -> None:
    """重扫前 scan_cache 里的 AI 字段，按 key 透传到新 scan 对应函数上。

    key 包含参数签名的 sha1，源码未改时 key 稳定；若用户改动了函数，key 变了找不到，
    旧 AI 字段不透传（符合预期：改过的函数流程图应该重新生成）。
    """
    old = engineering_store.read_scan_cache(project_id, component_id)
    if not old:
        return
    # 建 key → old_fn 索引
    old_by_key: dict[str, dict] = {}
    for f in old.get("files") or []:
        for c in f.get("classes") or []:
            for fn in c.get("functions") or []:
                k = fn.get("key")
                if k:
                    old_by_key[k] = fn
    # 透传
    kept = 0
    for f in new_scan.get("files") or []:
        for c in f.get("classes") or []:
            for fn in c.get("functions") or []:
                k = fn.get("key")
                if not k or k not in old_by_key:
                    continue
                old_fn = old_by_key[k]
                touched = False
                for field in _AI_FIELDS_TO_PRESERVE:
                    if old_fn.get(field) and not fn.get(field):
                        fn[field] = old_fn[field]
                        touched = True
                # extracted_by 单独处理：合并 "regex+ai" 保留 "+ai" 标记
                old_eb = old_fn.get("extracted_by") or ""
                if "ai" in old_eb.split("+") and "ai" not in (fn.get("extracted_by") or "").split("+"):
                    cur = fn.get("extracted_by") or "regex"
                    fn["extracted_by"] = cur + "+ai"
                    touched = True
                if touched:
                    kept += 1
    if kept:
        logger.info("重扫 %s：保留 %d 个函数的 AI 回写字段", component_id, kept)


def find_function_by_key(scan: dict, key: str) -> Optional[dict]:
    """按 symbol key 在 scan 结果里定位单个函数。"""
    for file_info in scan.get("files") or []:
        for cls in file_info.get("classes") or []:
            for fn in cls.get("functions") or []:
                if fn.get("key") == key:
                    return fn
    return None


# ---- 推送 G：按 baseline diff 给函数打 diff_status ----

def classify_functions(scan: dict, diff_summary: Optional[dict] = None) -> dict:
    """为 scan 结果中每个 function 打 `diff_status` 字段。

    规则（按优先级从高到低）—— 2026-11-06 A 方案调整：
      1. diff_summary 缺省                                 → 保守起见，全部 "modified"
      2. 文件在 diff_summary.added_files                   → "added"
      3. 文件在 diff_summary.changed_files                 → "modified"
      4. 文件未出现在任何改动清单 且 is_sdk=True           → "unchanged_sdk"
      5. 文件未出现在任何改动清单 且 is_sdk=False          → "unchanged"

    **历史坑**：原规则 1 是 "is_sdk=True → unchanged_sdk" 高优先级，
    配合 engineering_store._is_sdk_path 的子串匹配，会把 nvsipl/ 下的
    用户二次开发源码整个标 SDK，diff 永远盖不上。现在：
      - is_sdk 字段保留（标注意义：这是 NVIDIA 规范的 reference impl 风格）
      - 分类排序改成 "diff 为准"：git 跟踪了的文件就是你管理的代码
      - is_sdk 只在"没进 diff 清单"时才沉淀成 unchanged_sdk（而非 unchanged）

    diff_summary 由前端 isomorphic-git 预计算后通过 baseline_diff.json 传入；本函数幂等。
    对 scan 本体就地修改并返回统计。

    **退化规则（2026-11-09 加）**：若 diff_summary 的 baseline_commit 和 head_commit
    相等（或两者都为空），说明 baseline 没有实际比较意义（空 diff 不是"没改动"而是
    "压根没对比"）。这种情形当作 diff_summary=None 处理，让 "modified" 保守策略兜住
    所有函数，避免 bridge 看见一片 unchanged 把所有函数都踢去 nv_original_functions。
    """
    diff_trustworthy = True  # 由 bridge 读取，决定 diff_status=modified 是否足以入 functions[]
    if isinstance(diff_summary, dict):
        baseline_commit = (diff_summary.get("baseline_commit") or "").strip()
        head_commit = (diff_summary.get("head_commit") or "").strip()
        has_changes = bool(
            diff_summary.get("changed_files")
            or diff_summary.get("added_files")
            or diff_summary.get("deleted_files")
        )
        # baseline==head 或两者都空 且 没有任何改动清单 → 当作没 baseline
        if not has_changes and (not baseline_commit or baseline_commit == head_commit):
            logger.warning(
                "baseline_diff 退化为空 (baseline=%s head=%s)：全部函数回落 modified 保守策略；"
                "bridge 将忽略该 diff_status，仅按 focus + AI 产物分流",
                baseline_commit[:12] or "<empty>", head_commit[:12] or "<empty>",
            )
            diff_summary = None
            diff_trustworthy = False
    else:
        # diff_summary=None 的场景也一样不可信
        diff_trustworthy = False

    changed = set((diff_summary or {}).get("changed_files") or [])
    added = set((diff_summary or {}).get("added_files") or [])
    # 2026-11-11 推送 G 粒度升级：hunk 区间映射
    #   file_hunks: {path: [{"new_start": int, "new_lines": int}, ...]}
    #   由前端 EngineeringScanner 解析 git diff header `@@ -a,b +c,d @@` 填入。
    #   new_start/new_lines 指 HEAD 版（扫描的源文件）里改动落在 [c, c+d) 的行范围。
    #   对 changed_files 里的文件：若函数 [line_start, line_end] 与任一 hunk 区间相交 → modified；
    #   否则 → unchanged（避免"文件改一行就连坐 129 个函数全标 modified"）。
    #   added_files 继续整文件标 added（新增文件里的函数本来就不存在 baseline）。
    #   若某 changed_file 没拿到 hunks（schema 旧 / 前端未升级）→ 回落文件级，保持向后兼容。
    raw_hunks = ((diff_summary or {}).get("file_hunks") or {}) if isinstance(diff_summary, dict) else {}
    # file_hunks: path → 区间列表；记录"前端已给过答案"的文件，即使答案是空列表。
    #   空列表 = 内容实际一致（CRLF 噪音等），该文件所有函数回落 unchanged
    #   path 不在 file_hunks = 前端未提供该文件的 hunks（旧版本或超大文件）→ 文件级回落
    file_hunks: dict[str, list[tuple[int, int]]] = {}
    for p, hunks in raw_hunks.items():
        if not isinstance(hunks, list):
            continue
        ivs: list[tuple[int, int]] = []
        for h in hunks:
            if not isinstance(h, dict):
                continue
            try:
                ns = int(h.get("new_start") or 0)
                nl = int(h.get("new_lines") or 0)
            except (TypeError, ValueError):
                continue
            if ns <= 0:
                continue
            # 纯删除 hunk：new_lines=0，上下文锚点行是 ns，交集时按单行 [ns, ns] 处理
            end = ns + nl - 1 if nl > 0 else ns
            ivs.append((ns, end))
        # 即使 ivs=[] 也记进去 → 表示"前端给过答案，文件内无实际改动"
        file_hunks[p] = ivs

    def _fn_touches_hunks(fn: dict, ivs: list[tuple[int, int]]) -> bool:
        ls = fn.get("line_start")
        le = fn.get("line_end")
        if not isinstance(ls, int) or not isinstance(le, int) or ls <= 0:
            # 老扫描缓存没 line_start → 回落文件级（保守标 modified）
            return True
        if le < ls:
            le = ls
        for (a, b) in ivs:
            if a <= le and ls <= b:
                return True
        return False

    stats = {"added": 0, "modified": 0, "unchanged": 0, "unchanged_sdk": 0}
    for file_info in scan.get("files") or []:
        path = file_info.get("path", "")
        for cls in file_info.get("classes") or []:
            for fn in cls.get("functions") or []:
                if diff_summary is None:
                    status = "modified"  # 没有 baseline 时保守全标 modified
                elif path in added:
                    status = "added"
                elif path in changed:
                    ivs = file_hunks.get(path)
                    if ivs is None:
                        # 没拿到 hunks → 回落文件级，保守标 modified（旧前端兼容路径）
                        status = "modified"
                    elif _fn_touches_hunks(fn, ivs):
                        status = "modified"
                    else:
                        # 文件改了但 hunk 不落在这个函数的行范围 → 该函数未动
                        status = "unchanged_sdk" if fn.get("is_sdk") else "unchanged"
                elif fn.get("is_sdk"):
                    status = "unchanged_sdk"
                else:
                    status = "unchanged"
                fn["diff_status"] = status
                stats[status] = stats.get(status, 0) + 1
    stats["trustworthy"] = diff_trustworthy
    stats["hunk_resolved_files"] = len(file_hunks)
    scan.setdefault("stats", {})["diff"] = stats
    return stats
