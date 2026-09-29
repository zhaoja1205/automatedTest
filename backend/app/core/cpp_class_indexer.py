"""
libclang 增强解析 —— Commit 4。

libclang 是**可选依赖**：`clang` 模块 import 失败时，`enrich_class_info` 直接返回
`(class_infos_unchanged, {"clang_status": "unavailable", ...})`，前端会看到
`clang: unavailable` 标签，正则版结果仍然可用。

合并策略：
- clang 解析到的成员/基类 **覆盖** 同名的正则版结果（clang 类型信息更准）
- 正则独有的成员/基类 **保留**（clang 因为缺 include 可能会漏，正则至少给个占位）
- ClassInfo 的 is_abstract、template_params 等元字段以 clang 为准

缓存：按 `(header_path, mtime, include_dirs_tuple)` 缓存单个头文件的解析结果，
避免同一个 header 在多次查询里反复解析；bounded 到 64 个 header。

不阻塞事件循环：`enrich_class_info_async` 用 `run_in_executor` 把 CPU 密集的 clang
遍历丢到默认线程池。
"""
from __future__ import annotations

import asyncio
import os
from collections import OrderedDict
from dataclasses import replace
from typing import Iterable

from app.core.cpp_class_parser import Base, ClassInfo, Member

# ---- 可选依赖：libclang ----
_CLANG_AVAILABLE = False
_CLANG_INIT_ERR = ""
try:
    from clang import cindex  # type: ignore
    _CLANG_AVAILABLE = True
except Exception as e:  # pragma: no cover - 环境相关
    _CLANG_INIT_ERR = f"{type(e).__name__}: {e}"


# 单头文件解析结果缓存：(path, mtime_ns, include_dirs) -> list[ClassInfo]
_CACHE: "OrderedDict[tuple, list[ClassInfo]]" = OrderedDict()
_CACHE_MAX = 64


def clang_available() -> bool:
    return _CLANG_AVAILABLE


def clang_init_error() -> str:
    return _CLANG_INIT_ERR


# --------------------------------------------------------------------------- #
# 公共入口
# --------------------------------------------------------------------------- #

async def enrich_class_info_async(
    target: ClassInfo,
    parents: list[ClassInfo],
    header_paths: list[str],
    include_dirs: list[str],
) -> tuple[ClassInfo, list[ClassInfo], dict]:
    """把 CPU 密集的 clang 解析丢到线程池。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        _sync_enrich,
        target, parents, header_paths, include_dirs,
    )


def _sync_enrich(
    target: ClassInfo,
    parents: list[ClassInfo],
    header_paths: list[str],
    include_dirs: list[str],
) -> tuple[ClassInfo, list[ClassInfo], dict]:
    """
    同步入口。返回 (enriched_target, enriched_parents, diagnostics_dict)。

    diagnostics_dict 至少包含：
      - clang_status: 'unavailable' | 'ok' | 'partial' | 'error'
      - clang_diagnostics: list[str]，最多 10 条
    """
    if not _CLANG_AVAILABLE:
        return target, parents, {
            "clang_status": "unavailable",
            "clang_diagnostics": [f"libclang 未安装或加载失败：{_CLANG_INIT_ERR}"],
        }

    diagnostics: list[str] = []
    all_by_qname: dict[str, ClassInfo] = {}

    include_dirs_tuple = tuple(sorted(set(include_dirs)))
    # 目标类的每个头文件 + 各父类头文件，都解析一次
    headers = list(dict.fromkeys(header_paths + [p.source_file for p in parents]))

    had_any_result = False
    had_error = False

    for hpath in headers:
        if not hpath or not os.path.isfile(hpath):
            continue
        try:
            infos = _parse_header_cached(hpath, include_dirs_tuple, diagnostics)
        except Exception as e:  # noqa: BLE001 - libclang 内部各种意外都要吞
            had_error = True
            diagnostics.append(f"clang 解析 {hpath} 抛异常：{type(e).__name__}: {e}")
            continue
        if infos:
            had_any_result = True
            for ci in infos:
                all_by_qname.setdefault(ci.qualified_name, ci)

    # 合并到正则版
    clang_target = all_by_qname.get(target.qualified_name)
    merged_target = _merge_class_info(target, clang_target) if clang_target else target
    merged_parents: list[ClassInfo] = []
    for p in parents:
        cp = all_by_qname.get(p.qualified_name)
        merged_parents.append(_merge_class_info(p, cp) if cp else p)

    # 判定状态
    if had_error and not had_any_result:
        status = "error"
    elif had_error or not clang_target:
        # 有报错但也拿到部分结果；或者根本没找到目标类的 clang 版本
        status = "partial"
    else:
        status = "ok"

    return merged_target, merged_parents, {
        "clang_status": status,
        "clang_diagnostics": diagnostics[-10:],
    }


# --------------------------------------------------------------------------- #
# 头文件解析（带缓存）
# --------------------------------------------------------------------------- #

def _parse_header_cached(
    path: str,
    include_dirs: tuple[str, ...],
    diagnostics: list[str],
) -> list[ClassInfo]:
    try:
        mtime_ns = os.stat(path).st_mtime_ns
    except OSError:
        return []
    key = (os.path.realpath(path), mtime_ns, include_dirs)
    hit = _CACHE.get(key)
    if hit is not None:
        _CACHE.move_to_end(key)
        return hit

    infos = _parse_header(path, include_dirs, diagnostics)
    _CACHE[key] = infos
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return infos


def _parse_header(
    path: str,
    include_dirs: tuple[str, ...],
    diagnostics: list[str],
) -> list[ClassInfo]:
    index = cindex.Index.create()
    args = [
        "-x", "c++",
        "-std=c++17",
        "-fsyntax-only",
        "-w",  # 抑制所有 warning，只留 error
    ]
    for d in include_dirs:
        args.append(f"-I{d}")
    # 头文件所在目录也加进去，方便相对 include
    args.append(f"-I{os.path.dirname(path)}")

    try:
        tu = index.parse(
            path,
            args=args,
            options=(
                cindex.TranslationUnit.PARSE_INCOMPLETE
                | cindex.TranslationUnit.PARSE_SKIP_FUNCTION_BODIES
            ),
        )
    except cindex.TranslationUnitLoadError as e:
        diagnostics.append(f"clang 无法加载 TU：{path}：{e}")
        return []

    # 收集 error 级 diagnostic（fatal / error）
    err_count = 0
    for d in tu.diagnostics:
        if d.severity >= cindex.Diagnostic.Error:
            err_count += 1
    if err_count:
        diagnostics.append(f"{os.path.basename(path)}：{err_count} 条 clang error")

    result: list[ClassInfo] = []
    _walk_cursor(tu.cursor, path, result, ns_stack=[])
    return result


# --------------------------------------------------------------------------- #
# AST 遍历
# --------------------------------------------------------------------------- #

_KIND_MAP = {
    "ClassDecl": "class",
    "StructDecl": "struct",
}


def _walk_cursor(
    cursor,
    header_path: str,
    out: list[ClassInfo],
    ns_stack: list[str],
) -> None:
    """
    深度优先遍历，收集本文件里定义的 class/struct/template。
    只保留 `is_definition()` 的节点，前置声明忽略；只保留位于本 header 的节点，
    避免把系统头里的 std::vector 之类也拉进来。
    """
    for child in cursor.get_children():
        kind_name = child.kind.name  # e.g. 'CLASS_DECL' -> 转成 'ClassDecl'
        pretty_kind = _pretty_kind(kind_name)

        if pretty_kind == "Namespace":
            name = child.spelling or "(anonymous)"
            _walk_cursor(child, header_path, out, ns_stack + [name])
            continue

        if pretty_kind in ("Class", "Struct", "ClassTemplate", "ClassTemplatePartialSpecialization"):
            if not child.is_definition():
                continue
            loc_file = child.location.file
            if loc_file is None or os.path.realpath(loc_file.name) != os.path.realpath(header_path):
                # clang 会把 #include 里的定义也当子节点，过滤掉
                # 但仍然递归进去（有些嵌套 namespace 里的类会出现在本文件）
                _walk_cursor(child, header_path, out, ns_stack)
                continue
            ci = _cursor_to_classinfo(child, header_path, ns_stack)
            if ci:
                out.append(ci)
            # 嵌套类：继续遍历，把 Outer 加进 ns_stack
            _walk_cursor(child, header_path, out, ns_stack + [ci.name] if ci else ns_stack)
            continue

        # 其它节点也递归（模板、typedef 里可能藏 class）
        _walk_cursor(child, header_path, out, ns_stack)


def _pretty_kind(kind_name: str) -> str:
    """CLASS_DECL -> Class；CLASS_TEMPLATE -> ClassTemplate 等。"""
    parts = kind_name.split("_")
    if parts and parts[-1] == "DECL":
        parts = parts[:-1]
    return "".join(p.capitalize() for p in parts)


def _cursor_to_classinfo(cursor, header_path: str, ns_stack: list[str]) -> ClassInfo | None:
    name = cursor.spelling
    if not name:
        return None

    is_struct = cursor.kind.name == "STRUCT_DECL"
    is_template = cursor.kind.name.startswith("CLASS_TEMPLATE")
    kind = "struct" if is_struct else "class"

    # 模板参数
    template_params: list[str] = []
    if is_template:
        for c in cursor.get_children():
            if c.kind.name in ("TEMPLATE_TYPE_PARAMETER",
                                "TEMPLATE_NON_TYPE_PARAMETER",
                                "TEMPLATE_TEMPLATE_PARAMETER"):
                template_params.append(c.spelling or "T")

    # 基类
    bases: list[Base] = []
    for c in cursor.get_children():
        if c.kind.name == "CXX_BASE_SPECIFIER":
            bname = _spelling_stripped(c)
            access = _access_str(c.access_specifier)
            is_virtual = c.is_virtual_base() if hasattr(c, "is_virtual_base") else False
            bases.append(Base(name=bname, access=access, is_virtual=is_virtual))

    # 成员
    members: list[Member] = []
    is_abstract_flag = False
    default_access = "public" if is_struct else "private"

    for c in cursor.get_children():
        knm = c.kind.name
        access = _access_str(c.access_specifier) or default_access

        if knm == "FIELD_DECL":
            members.append(Member(
                name=c.spelling,
                kind="field",
                access=access,
                type_str=(c.type.spelling if c.type else ""),
                is_static=False,
                is_virtual=False,
                is_pure_virtual=False,
                is_override=False,
                is_const=(c.type.is_const_qualified() if c.type else False),
            ))
        elif knm == "VAR_DECL":
            # 类里的 static 成员变量在 clang 里是 VAR_DECL
            members.append(Member(
                name=c.spelling,
                kind="field",
                access=access,
                type_str=(c.type.spelling if c.type else ""),
                is_static=True,
                is_virtual=False,
                is_pure_virtual=False,
                is_override=False,
                is_const=(c.type.is_const_qualified() if c.type else False),
            ))
        elif knm in ("CXX_METHOD", "FUNCTION_TEMPLATE"):
            is_pure = bool(getattr(c, "is_pure_virtual_method", lambda: False)())
            is_virt = bool(getattr(c, "is_virtual_method", lambda: False)())
            is_static = bool(getattr(c, "is_static_method", lambda: False)())
            is_const = bool(getattr(c, "is_const_method", lambda: False)())
            is_override = _has_override_attr(c)
            if is_pure:
                is_abstract_flag = True
            members.append(Member(
                name=c.spelling,
                kind="method",
                access=access,
                type_str=(c.result_type.spelling if c.result_type else ""),
                params=_params_of(c),
                is_static=is_static,
                is_virtual=is_virt,
                is_pure_virtual=is_pure,
                is_override=is_override,
                is_const=is_const,
            ))
        elif knm == "CONSTRUCTOR":
            members.append(Member(
                name=c.spelling,
                kind="ctor",
                access=access,
                type_str="",
                params=_params_of(c),
                is_static=False,
                is_virtual=False,
                is_pure_virtual=False,
                is_override=False,
                is_const=False,
            ))
        elif knm == "DESTRUCTOR":
            is_virt = bool(getattr(c, "is_virtual_method", lambda: False)())
            members.append(Member(
                name=c.spelling,  # ~ClassName
                kind="dtor",
                access=access,
                type_str="",
                params="",
                is_static=False,
                is_virtual=is_virt,
                is_pure_virtual=False,
                is_override=False,
                is_const=False,
            ))

    qualified_name = "::".join(ns_stack + [name]) if ns_stack else name
    return ClassInfo(
        name=name,
        qualified_name=qualified_name,
        kind=kind,
        template_params=template_params,
        bases=bases,
        members=members,
        source_file=header_path,
        line=(cursor.location.line if cursor.location else 0),
        namespace_path=list(ns_stack),
        is_abstract=is_abstract_flag,
    )


def _spelling_stripped(cursor) -> str:
    """`class Foo` / `struct Foo` -> `Foo`；保留模板参数和 namespace。"""
    s = cursor.spelling or (cursor.type.spelling if cursor.type else "")
    for prefix in ("class ", "struct "):
        if s.startswith(prefix):
            s = s[len(prefix):]
    return s.strip()


def _access_str(spec) -> str:
    if spec is None:
        return ""
    n = getattr(spec, "name", "")
    m = {"PUBLIC": "public", "PROTECTED": "protected", "PRIVATE": "private"}
    return m.get(n, "")


def _params_of(cursor) -> str:
    parts: list[str] = []
    for a in cursor.get_arguments():
        t = a.type.spelling if a.type else ""
        n = a.spelling or ""
        parts.append(f"{t} {n}".strip())
    return ", ".join(parts)


def _has_override_attr(cursor) -> bool:
    for c in cursor.get_children():
        if c.kind.name == "CXX_OVERRIDE_ATTR":
            return True
    return False


# --------------------------------------------------------------------------- #
# 合并策略
# --------------------------------------------------------------------------- #

def _merge_class_info(regex_ci: ClassInfo, clang_ci: ClassInfo) -> ClassInfo:
    """
    clang 版本存在时，用它覆盖同名成员；正则独有的成员保留（clang 可能因缺 include 漏识别）。
    """
    # 成员按 (kind, name, params) 去重
    def key(m: Member) -> tuple:
        return (m.kind, m.name, m.params or "")

    merged_members: dict[tuple, Member] = {}
    for m in regex_ci.members:
        merged_members[key(m)] = m
    for m in clang_ci.members:
        merged_members[key(m)] = m  # clang 覆盖

    # 基类按 name 去重，clang 优先
    merged_bases: dict[str, Base] = {b.name: b for b in regex_ci.bases}
    for b in clang_ci.bases:
        merged_bases[b.name] = b

    return replace(
        regex_ci,
        # clang 的元字段更权威
        is_abstract=clang_ci.is_abstract or regex_ci.is_abstract,
        template_params=(clang_ci.template_params or regex_ci.template_params),
        bases=list(merged_bases.values()),
        members=list(merged_members.values()),
    )


def _iter_members(cis: Iterable[ClassInfo]):  # pragma: no cover - 便于调试
    for ci in cis:
        for m in ci.members:
            yield ci.qualified_name, m
