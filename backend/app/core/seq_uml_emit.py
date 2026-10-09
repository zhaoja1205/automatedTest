"""
PlantUML 时序图生成器 — Python 移植自前端 cppSeqDiagram.ts:buildSeqUml。

公开 API：
  build_seq_uml(func_a, calls_a, func_b=None, calls_b=None, opts={})
      → str   PlantUML @startuml … @enduml 文本

opts 键（全部可选）：
  caller_name  str   外部调用方 actor 名（默认「调用方」）
  autonumber   bool  是否加 autonumber（默认 True）
  show_returns bool  是否画返回虚线（默认 True）
"""
from __future__ import annotations

import re
from typing import Optional

from app.core.cpp_seq_parser import FuncMatch, CallEvent


# ─────────────────────────── 文本工具 ───────────────────────────

_MAX_LABEL = 180


def _seq_label(s: str) -> str:
    """PlantUML message label 转义：双引号全角化、冒号全角化、截断过长。"""
    out = str(s)
    out = out.replace('"', '＂').replace(':', '：')
    out = re.sub(r'\r?\n', ' ', out)
    out = re.sub(r'\s+', ' ', out).strip()
    if len(out) > _MAX_LABEL:
        out = out[:_MAX_LABEL] + ' …⟨截断⟩'
    return out


def _alias(name: str) -> str:
    """把 lifeline 名字清理成合法 PlantUML alias（只允许字母数字下划线）。"""
    a = re.sub(r'[^A-Za-z0-9_]', '_', name)
    if a and a[0].isdigit():
        a = '_' + a
    return a or 'X'


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


# ─────────────────────────── 主函数 ───────────────────────────

def build_seq_uml(
    func_a: FuncMatch,
    calls_a: list[CallEvent],
    func_b: Optional[FuncMatch] = None,
    calls_b: Optional[list[CallEvent]] = None,
    opts: dict | None = None,
) -> str:
    """从一个（或两个）函数构建 PlantUML sequence 图文本。"""
    if opts is None:
        opts = {}
    caller_name: str = opts.get('caller_name', '调用方')
    autonumber: bool = bool(opts.get('autonumber', True))
    show_returns: bool = bool(opts.get('show_returns', True))

    a_class = func_a.class_name or 'FuncA'
    b_class = (func_b.class_name or 'FuncB') if func_b else ''
    _calls_b = calls_b or []

    # 汇总 lifelines（保持首次出现顺序）
    seen: set[str] = set()
    lifelines: list[str] = []

    def add(name: str) -> None:
        if not name or name in seen:
            return
        seen.add(name)
        lifelines.append(name)

    add(a_class)
    for c in calls_a:
        add(c.callee)
    if b_class:
        add(b_class)
    for c in _calls_b:
        add(c.callee)

    lines: list[str] = []
    lines.append('@startuml')
    lines.append('skinparam defaultFontName "PingFang SC, Microsoft YaHei, Segoe UI"')
    lines.append('skinparam defaultFontSize 12')
    lines.append('skinparam sequenceArrowThickness 1.2')
    lines.append('skinparam sequenceParticipant underline')
    lines.append('skinparam sequence {')
    lines.append('  ParticipantBackgroundColor #F1F5F9')
    lines.append('  ParticipantBorderColor #475569')
    lines.append('  ActorBackgroundColor #E0F2FE')
    lines.append('  ActorBorderColor #0284C7')
    lines.append('  LifeLineBorderColor #94A3B8')
    lines.append('  ArrowColor #334155')
    lines.append('}')
    if autonumber:
        lines.append('autonumber')

    caller_alias = 'Caller'
    lines.append(f'actor "{_seq_label(caller_name)}" as {caller_alias}')
    for name in lifelines:
        lines.append(f'participant "{_seq_label(name)}" as {_alias(name)}')

    # 外部 → A：只显示形参名，不带类型
    a_alias = _alias(a_class)
    a_arg_names = [
        m.group(1)
        for p in _split_top_commas(func_a.params)
        for m in [re.search(r'([A-Za-z_]\w*)\s*(?:\[\s*\d*\s*\])?\s*$',
                             re.sub(r'\s*=.*$', '', p.strip()))]
        if m
    ]
    a_msg = f"{func_a.func_name}({_seq_label(', '.join(a_arg_names))})"
    lines.append(f'{caller_alias} -> {a_alias}: {a_msg}')
    lines.append(f'activate {a_alias}')

    call_edges = 0

    for c in calls_a:
        dst_alias = _alias(c.callee)
        msg = f'{c.method}({_seq_label(c.args)})'

        if c.is_self:
            lines.append(f'{a_alias} -> {a_alias}: {msg}')
        else:
            lines.append(f'{a_alias} -> {dst_alias}: {msg}')
            lines.append(f'activate {dst_alias}')
        call_edges += 1

        # 若该调用正好是 B，展开 B 的内部调用
        if func_b and c.method == func_b.func_name:
            b_alias = _alias(b_class)
            expand_on = a_alias if c.is_self else dst_alias
            if not c.is_self and expand_on != b_alias:
                lines.append(
                    f'note over {expand_on}, {b_alias}: '
                    f'以下展开自 {b_class}::{func_b.func_name}'
                )
            for cb in _calls_b:
                inner_alias = _alias(cb.callee)
                inner_msg = f'{cb.method}({_seq_label(cb.args)})'
                if cb.is_self:
                    lines.append(f'{expand_on} -> {expand_on}: {inner_msg}')
                else:
                    lines.append(f'{expand_on} -> {inner_alias}: {inner_msg}')
                    if show_returns:
                        ret_label = _seq_label(cb.ret_var) if cb.ret_var else 'return'
                        lines.append(f'{inner_alias} --> {expand_on}: {ret_label}')
                call_edges += 1

        if show_returns and not c.is_self:
            ret_label = _seq_label(c.ret_var) if c.ret_var else 'return'
            lines.append(f'{dst_alias} --> {a_alias}: {ret_label}')
            lines.append(f'deactivate {dst_alias}')

    lines.append(f'{a_alias} --> {caller_alias}: return')
    lines.append(f'deactivate {a_alias}')
    lines.append('@enduml')

    return '\n'.join(lines)
