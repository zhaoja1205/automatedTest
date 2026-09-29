"""
把 ClassInfo（目标类 + 它向上追踪到的祖先们）渲染成 PlantUML 类图。

设计范围（跟用户确认过）：
- 默认追踪 2 层（父类 + 祖父类），前端可以调（1..10）
- 显示 public/protected/private 三段成员，由 options 决定过滤
- 接口判定：所有方法都是纯虚且无字段 → PlantUML `interface` + `<|..`
  否则 `class`/`abstract class` + `<|--`
- 名字含 `::` 或 `<>` 用别名（`class "ns::Foo<T>" as Foo`）避免破坏 PlantUML 语法
- 继承线由**每个类自己的 bases 列表**决定，不再假设「只有 target 有继承边」——
  这样多层继承的箭头能一路画到顶。
"""
from __future__ import annotations

from typing import Iterable

from app.core.cpp_class_parser import ClassInfo, Member


# 用户在前端能勾的过滤项，默认全开
DEFAULT_OPTIONS = {
    "show_private": True,
    "show_protected": True,
    "show_static": True,
}


def emit_class_diagram(target: ClassInfo,
                        ancestors: list[ClassInfo],
                        options: dict | None = None) -> str:
    """输出完整 PlantUML 源码字符串（含 @startuml / @enduml）。

    Args:
        target: 目标类
        ancestors: 递归解析出的祖先（去重后），BFS 顺序。emit 层不关心「哪层」，
            按每个类自己的 `.bases` 连线即可。
        options: {show_private, show_protected, show_static}

    找不到定义的 base（既不在 target 也不在 ancestors 里）走
    `_emit_placeholder_base()`，只画类名 + 继承线，避免箭头悬空。
    """
    opts = {**DEFAULT_OPTIONS, **(options or {})}
    lines: list[str] = [
        "@startuml",
        "skinparam classAttributeIconSize 0",
        "skinparam linetype ortho",
        "hide empty members",
        "top to bottom direction",
        "",
    ]

    # 所有已知类：target + ancestors。alias 用短名，做冲突时的自然合并
    # （例如 ns1::Base 和 ns2::Base 共享 alias `Base`，PlantUML 会把它们
    # 画成一个节点——这是 acceptable behaviour：正则解析层已经优先按
    # 全限定名匹配，走到这里的短名冲突大多是「用户 zip 里同名类」实际不区分）。
    known_by_short: dict[str, ClassInfo] = {}
    for ci in [target, *ancestors]:
        known_by_short.setdefault(_short_name(ci.qualified_name), ci)

    # 先画祖先，再画 target，让 PlantUML 布局从上到下更自然
    for a in ancestors:
        lines.extend(_emit_class_block(a, opts))
        lines.append("")

    # 目标类
    lines.extend(_emit_class_block(target, opts))
    lines.append("")

    # 找不到定义的 base：画占位（每个只画一次）
    placeholder_shorts: set[str] = set()
    for ci in [target, *ancestors]:
        for base in ci.bases:
            short = _short_name(base.name)
            if short in known_by_short or short in placeholder_shorts:
                continue
            lines.extend(_emit_placeholder_base(base.name))
            lines.append("")
            placeholder_shorts.add(short)

    # 继承连线：遍历每个已知类的 bases（去重后画一次）
    edges_seen: set[tuple[str, str]] = set()
    for ci in [target, *ancestors]:
        child_short = _short_name(ci.qualified_name)
        for base in ci.bases:
            base_short = _short_name(base.name)
            edge_key = (base_short, child_short)
            if edge_key in edges_seen:
                continue
            edges_seen.add(edge_key)
            base_info = known_by_short.get(base_short)
            arrow = _inheritance_arrow(base_info)
            lines.append(f"{_class_alias(base_short)} {arrow} {_class_alias(child_short)}")

    lines.append("@enduml")
    return "\n".join(lines)


# --------- 内部 ---------

def _emit_class_block(info: ClassInfo, opts: dict) -> list[str]:
    """输出单个类的完整声明块（含成员）。"""
    lines: list[str] = []
    keyword = _class_keyword(info)
    header = _class_header(keyword, info)
    lines.append(header + " {")

    for m in _filter_members(info.members, opts):
        lines.append("    " + _format_member(m))
    lines.append("}")
    return lines


def _emit_placeholder_base(qualified: str) -> list[str]:
    """基类在项目里找不到定义（比如来自外部 include 且未解析）时的占位。

    只画一个空的 `class`，让继承线不孤零零地悬在半空。
    """
    short = _short_name(qualified)
    if short == qualified:
        return [f"class {short}"]
    return [f'class "{qualified}" as {short}']


def _class_keyword(info: ClassInfo) -> str:
    """决定 PlantUML 用 class / abstract class / interface。

    interface 判定：**排除析构**后，所有 method 都是纯虚 + 没有 field；
    否则纯虚存在的用 `abstract class`，一般走 `class`。
    析构常写作 `virtual ~Foo() = default`，本身不是纯虚但也不影响接口本质。
    """
    def is_dtor(m: Member) -> bool:
        return m.name.startswith("~")

    methods = [m for m in info.members if m.kind == "method" and not is_dtor(m)]
    fields = [m for m in info.members if m.kind == "field"]
    if methods and not fields and all(m.is_pure_virtual for m in methods):
        return "interface"
    if info.is_abstract:
        return "abstract class"
    return "class"


def _class_header(keyword: str, info: ClassInfo) -> str:
    """输出类头：如果名字带 `::` 或 `<>` 就用别名语法。"""
    display = info.qualified_name if info.qualified_name != info.name else info.name
    if info.template_params:
        display = f"{display}<{info.template_params}>"

    needs_alias = ("::" in display) or ("<" in display) or (">" in display)
    if needs_alias:
        return f'{keyword} "{display}" as {_class_alias(info.name)}'
    return f"{keyword} {info.name}"


def _class_alias(name: str) -> str:
    """给带模板/命名空间的类做别名——去掉 `<...>`、`::` 之类不友好的字符。"""
    short = name.split("<", 1)[0].split("::")[-1]
    return short or "Anon"


def _short_name(qualified: str) -> str:
    """`ns::Sub::Foo<T>` → `Foo`。"""
    return qualified.split("<", 1)[0].split("::")[-1]


def _inheritance_arrow(base_info: ClassInfo | None) -> str:
    """决定继承箭头。

    - 已知基类是 interface → `<|..`（虚线，实现关系）
    - 否则 → `<|--`（实线，继承关系）
    """
    if base_info and _class_keyword(base_info) == "interface":
        return "<|.."
    return "<|--"


def _filter_members(members: Iterable[Member], opts: dict) -> list[Member]:
    """按 options 过滤。private/protected 关掉时排掉对应可见性；
    static 关掉时排掉 static 成员。"""
    result: list[Member] = []
    for m in members:
        if not opts.get("show_private", True) and m.access == "private":
            continue
        if not opts.get("show_protected", True) and m.access == "protected":
            continue
        if not opts.get("show_static", True) and m.is_static:
            continue
        result.append(m)
    return result


def _format_member(m: Member) -> str:
    """把一个 Member 渲染成 PlantUML 成员行。"""
    vis = _visibility(m.access)
    stereo: list[str] = []
    if m.is_static:
        stereo.append("{static}")
    if m.is_pure_virtual:
        stereo.append("{abstract}")
    stereo_prefix = " ".join(stereo)

    if m.kind == "field":
        # `- name : Type` 是 PlantUML 通行格式
        body = f"{vis} {m.name}"
        if m.type_str:
            body += f" : {_clean_type(m.type_str)}"
        if stereo_prefix:
            body = f"{stereo_prefix} {body}"
        return body

    # method
    ret_disp = _clean_type(m.type_str) if m.type_str else ""
    body = f"{vis} {m.name}({_clean_params(m.params)})"
    if ret_disp:
        body += f" : {ret_disp}"
    # 常见后缀 stereotype，方便读者一眼看清
    tail_stereos: list[str] = []
    if m.is_const:
        tail_stereos.append("<<const>>")
    if m.is_override:
        tail_stereos.append("<<override>>")
    elif m.is_virtual:
        tail_stereos.append("<<virtual>>")
    if tail_stereos:
        body += " " + " ".join(tail_stereos)
    if stereo_prefix:
        body = f"{stereo_prefix} {body}"
    return body


def _visibility(access: str) -> str:
    return {"public": "+", "protected": "#", "private": "-"}.get(access, "+")


def _clean_type(t: str) -> str:
    """把类型字符串里过量空白压平，别把 PlantUML 编译器搞崩。"""
    return " ".join(t.split()).strip()


def _clean_params(p: str) -> str:
    """参数原文只做最小清理——保留原样能让读者看到默认值/const 等信息。"""
    return " ".join(p.split()).strip()
