"""
从 swe3_detail_sample.docx 构造生产模板 swe3_detail.docx。

F1 范围（仅 A001/A003 两模块样板，剩下留 F2）：
  1. 封面 V1.0 → {{ project.version }}
  2. T0 历史 / T1 评审 → 循环
  3. 1.2 范围 T2 / 1.3 参考 T3 / 1.4 字符集 T4 / 2 术语 T6 → 循环
  4. 需求映射 T7 → 循环
  5. A001 Serializer：类列表 T8 / 常量表 T9 / 变量表 T10 / 函数列表 T11 / 函数声明表 T12 → 循环
  6. A003 EEPROM：同 A001 样板（仅处理一个函数表样板，剩余靠 F2 实现）

跑法：
  cd backend
  venv/bin/python scripts/build_swe3_template.py
"""

from pathlib import Path
from copy import deepcopy
from docx import Document
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / 'app' / 'templates' / 'aspice' / 'swe3_detail_sample.docx'
DST = ROOT / 'app' / 'templates' / 'aspice' / 'swe3_detail.docx'


# ============ 工具函数（和 build_swe2_template.py 同款，复制过来避免跨文件依赖）============

def replace_in_run(paragraph, needle, replacement):
    hit = False
    for run in paragraph.runs:
        if needle in run.text:
            run.text = run.text.replace(needle, replacement)
            hit = True
    return hit


def replace_in_paragraph_runs(paragraph, needle, replacement):
    """跨 run 替换：如果 needle 被拆在相邻 run 里（比如 'V'+'1.0'），
    把第 1 个 run 改成 replacement，把后续 run 的对应字符清空。
    返回是否命中。
    """
    # 优先尝试单 run 命中
    if replace_in_run(paragraph, needle, replacement):
        return True
    # 跨 run：拼接所有 run，找到 needle 的位置
    full = ''.join(r.text for r in paragraph.runs)
    pos = full.find(needle)
    if pos < 0:
        return False
    # 计算 needle 覆盖了哪些 run 的哪些字符
    cursor = 0
    nd_end = pos + len(needle)
    first_run_idx = None
    for ri, run in enumerate(paragraph.runs):
        rtxt = run.text
        rstart, rend = cursor, cursor + len(rtxt)
        if rend <= pos:
            cursor = rend
            continue
        if rstart >= nd_end:
            break
        # 这个 run 和 needle 重叠
        overlap_s = max(rstart, pos) - rstart
        overlap_e = min(rend, nd_end) - rstart
        if first_run_idx is None:
            # 第一个重叠 run：保留 needle 之前的部分 + replacement + needle 之后的部分
            new_text = rtxt[:overlap_s] + replacement + rtxt[overlap_e:]
            run.text = new_text
            first_run_idx = ri
        else:
            # 后续 run：删除重叠部分
            run.text = rtxt[:overlap_s] + rtxt[overlap_e:]
        cursor = rend
    return first_run_idx is not None


def rebuild_loop_table(tbl, loop_var, iter_expr, data_exprs, *, keep_header_rows=1):
    """把数据表改成 {%tr for %} 循环。3 行结构：开标签 + 数据 + 闭标签。"""
    for row in list(tbl.rows[keep_header_rows:]):
        row._element.getparent().remove(row._element)
    r_open = tbl.add_row()
    r_open.cells[0].text = '{%%tr for %s in %s %%}' % (loop_var, iter_expr)
    r_data = tbl.add_row()
    for i, expr in enumerate(data_exprs):
        if i < len(tbl.columns):
            r_data.cells[i].text = expr
    r_close = tbl.add_row()
    r_close.cells[0].text = '{%tr endfor %}'


def find_paragraph_index(d, needle, start=0):
    for i, p in enumerate(d.paragraphs[start:], start):
        if needle in p.text:
            return i
    return -1


def set_paragraph_text(p, new_text):
    runs = p.runs
    if runs:
        first = runs[0]
        for r in runs[1:]:
            r._element.getparent().remove(r._element)
        first.text = new_text
    else:
        p.add_run(new_text)


# ============ 主流程 ============

def main():
    print(f'→ 读 {SRC}')
    d = Document(str(SRC))

    # ---- 1. 封面 V1.0 占位 ----
    print('→ [1/6] 封面版本号')
    hit = 0
    for p in d.paragraphs[:40]:
        if replace_in_paragraph_runs(p, 'V1.0', '{{ project.version }}'):
            hit += 1
    print(f'   替换 {hit} 处')

    # ---- 2. 历史 T0 / 评审 T1 ----
    print('→ [2/6] T0 历史 / T1 评审')
    rebuild_loop_table(
        d.tables[0], 'h', 'project.history',
        ['{{ h.date }}', '{{ h.version }}', '{{ h.author }}', '{{ h.content }}'],
    )
    rebuild_loop_table(
        d.tables[1], 'r', 'project.reviews',
        ['{{ r.version }}', '{{ r.review_date }}', '{{ r.reviewer }}',
         '{{ r.approver }}', '{{ r.opinion }}'],
    )

    # ---- 3. §1 概述 + §2 术语 ----
    print('→ [3/6] 1.2 范围 / 1.3 参考 / 1.4 字符集 / 2 术语')
    # T2 范围列表 (NO | 范围 | 作用及功能)
    rebuild_loop_table(
        d.tables[2], 's', 'overview.scope_items',
        ['{{ s.no }}', '{{ s.scope }}', '{{ s.function }}'],
    )
    # T3 参考文档
    rebuild_loop_table(
        d.tables[3], 'r', 'overview.ref_docs',
        ['{{ r.no }}', '{{ r.name }}', '{{ r.version }}', '{{ r.note }}'],
    )
    # T4 字符集
    rebuild_loop_table(
        d.tables[4], 'c', 'overview.charsets',
        ['{{ c.charset }}', '{{ c.description }}'],
    )
    # T5 set/get 规则（1 行 1 列）—— 直接占位不循环
    if d.tables[5].rows:
        d.tables[5].rows[0].cells[0].text = '{{ overview.set_get_rule }}'
    # T6 术语
    rebuild_loop_table(
        d.tables[6], 't', 'terms',
        ['{{ t.term }}', '{{ t.definition }}'],
    )

    # ---- 4. 需求映射 T7 (SWE.3 6 列: SWE.1 | SWE.2 | DesignID | Meaning | Remark | Version) ----
    print('→ [4/6] T7 需求映射')
    t7_cols = len(d.tables[7].columns)
    # SWE.2 样本是 5 列，SWE.3 是 6 列 - 多一列 "设计 ID"
    exprs = [
        '{{ m.swe1_id }}',
        '{{ m.swe2_id }}',
        '{{ m.design_id }}',
        '{{ m.id_meaning }}',
        '{{ m.remark }}',
        '{{ m.version }}',
    ]
    while len(exprs) > t7_cols:
        exprs.pop()
    rebuild_loop_table(d.tables[7], 'm', 'mappings', exprs)

    # ---- 5. A001 Serializer 样板 ----
    print('→ [5/6] A001 Serializer: 类列表/常量/变量/函数列表/函数声明')
    # T8 类列表 (序号 | 设计ID | 类名 | 说明)
    rebuild_loop_table(
        d.tables[8], 'cls', 'modules_by_id.A001.classes',
        ['{{ cls.seq }}', '{{ cls.design_id }}', '{{ cls.class_name }}', '{{ cls.description }}'],
    )
    # T9 常量表 (序号 | 常量 | 类型 | 值 | 说明) 2 行 5 列
    # modules_by_id.A001.class_details 可能有多个 class_detail,
    # 简化：F1 只处理 class_details[0] 的 constants
    rebuild_loop_table(
        d.tables[9], 'cm', 'modules_by_id.A001.class_details[0].constants',
        ['{{ cm.seq }}', '{{ cm.name }}', '{{ cm.type }}', '{{ cm.value }}', '{{ cm.description }}'],
    )
    # T10 变量表 (序号 | 变量 | 类型 | 说明) 2 行 4 列
    rebuild_loop_table(
        d.tables[10], 'vm', 'modules_by_id.A001.class_details[0].variables',
        ['{{ vm.seq }}', '{{ vm.name }}', '{{ vm.type }}', '{{ vm.description }}'],
    )
    # T11 函数列表 (设计ID | 函数名 | 说明) 4 行 3 列
    rebuild_loop_table(
        d.tables[11], 'f', 'modules_by_id.A001.function_list',
        ['{{ f.design_id }}', '{{ f.name }}', '{{ f.description }}'],
    )

    # T12 A001 第 1 个函数声明表（10 行 5 列，固定结构不做循环）
    # 把固定行的内容改成占位
    #   row0: 函数声明 | <declaration>
    #   row1: 函数介绍 | <brief>
    #   row2: Parameter | Type | details  (header)
    #   row3-5: 参数行（3 行固定 — F1 简化）
    #   row6: return value | Type | details (header)
    #   row7: 返回值
    #   row8: 函数流程图 (header)
    #   row9: <flowchart>
    print('   T12 函数声明 - 第 1 个函数')
    func0_expr = 'modules_by_id.A001.functions[0]'
    t12 = d.tables[12]
    if len(t12.rows) >= 10:
        # row0: 函数声明
        t12.rows[0].cells[1].text = f'{{{{ {func0_expr}.declaration }}}}'
        # row1: 函数介绍
        t12.rows[1].cells[1].text = f'{{{{ {func0_expr}.brief }}}}'
        # row3,4,5: 3 行参数（如果 F1 只有 1 个函数且参数不超 3 个，可以静态占位）
        # 更灵活：F2 再改成子循环；F1 先把前 3 个参数静态替换
        for i, prow in enumerate([3, 4, 5]):
            if prow < len(t12.rows):
                cells = t12.rows[prow].cells
                p_expr = f'{func0_expr}.parameters'
                cells[0].text = f'{{% if {p_expr}|length > {i} %}}{{{{ {p_expr}[{i}].name }}}}{{% endif %}}'
                cells[1].text = f'{{% if {p_expr}|length > {i} %}}{{{{ {p_expr}[{i}].type }}}}{{% endif %}}'
                cells[2].text = f'{{% if {p_expr}|length > {i} %}}{{{{ {p_expr}[{i}].details }}}}{{% endif %}}'
        # row7: 返回值第 1 行
        if len(t12.rows) > 7:
            r_expr = f'{func0_expr}.return_values'
            cells = t12.rows[7].cells
            cells[0].text = f'{{% if {r_expr} %}}{{{{ {r_expr}[0].name }}}}{{% endif %}}'
            cells[1].text = f'{{% if {r_expr} %}}{{{{ {r_expr}[0].type }}}}{{% endif %}}'
            cells[2].text = f'{{% if {r_expr} %}}{{{{ {r_expr}[0].details }}}}{{% endif %}}'
        # row9: 流程图 (InlineImage)
        if len(t12.rows) > 9:
            # 合并单元格第 1 个 cell 就代表整行
            t12.rows[9].cells[0].text = (
                f'{{% if {func0_expr}.flowchart_image_key %}}'
                f'{{{{ {func0_expr}.flowchart_image_key }}}}'
                f'{{% endif %}}'
            )

    # T13/T14 是 A001 第 2/3 个函数的声明表 - F1 暂不处理（原文留着）
    # 函数后面的描述段（功能说明/输入参数/输出参数/返回值/异常处理）F1 暂保留原文

    # ---- 6. A003 EEPROM 样板 ----
    print('→ [6/6] A003 EEPROM: 类列表/函数列表/前3个函数声明')
    eep_pidx = find_paragraph_index(d, '模块EEPROM详细设计')
    if eep_pidx < 0:
        print('   ⚠ 找不到 "模块EEPROM详细设计"')
    else:
        from docx.oxml.ns import qn as _qn
        body = d.element.body
        hit_para = False
        found_tables_el = []
        for e in body.iterchildren():
            tag = e.tag.split('}')[-1]
            if tag == 'p':
                text = ''.join(t.text or '' for t in e.iter(_qn('w:t')))
                if '模块EEPROM详细设计' in text:
                    hit_para = True
                elif hit_para and ('EEPROM单元时序图' in text or '模块camera module' in text):
                    break
            elif tag == 'tbl' and hit_para:
                found_tables_el.append(e)
        # 映射到 Table 对象
        a003_tbls = [tbl for tbl in d.tables if tbl._element in found_tables_el]
        print(f'   A003 段内表: {len(a003_tbls)} 个')

        # 按表头特征分类
        func_count = 0
        for idx, tbl in enumerate(a003_tbls):
            if not tbl.rows:
                continue
            head0 = tbl.rows[0].cells[0].text.strip()
            head1 = tbl.rows[0].cells[1].text.strip() if len(tbl.rows[0].cells) > 1 else ''
            # 类列表: 序号 + 设计ID header
            if '序号' in head0 and '设计' in head1 and len(tbl.columns) == 4:
                rebuild_loop_table(
                    tbl, 'cls', 'modules_by_id.A003.classes',
                    ['{{ cls.seq }}', '{{ cls.design_id }}',
                     '{{ cls.class_name }}', '{{ cls.description }}'],
                )
                print(f'   ✓ A003 T{idx} 类列表 → loop')
            # 函数列表: 设计ID + 函数名 header
            elif '设计' in head0 and '函数名' in head1:
                rebuild_loop_table(
                    tbl, 'f', 'modules_by_id.A003.function_list',
                    ['{{ f.design_id }}', '{{ f.name }}', '{{ f.description }}'],
                )
                print(f'   ✓ A003 T{idx} 函数列表 → loop')
            # 函数声明表
            elif '函数声明' in head0 and func_count < 3:
                func_expr = f'modules_by_id.A003.functions[{func_count}]'
                if len(tbl.rows) >= 7 and len(tbl.rows[0].cells) > 1:
                    tbl.rows[0].cells[1].text = f'{{{{ {func_expr}.declaration }}}}'
                if len(tbl.rows) >= 2 and len(tbl.rows[1].cells) > 1:
                    tbl.rows[1].cells[1].text = f'{{{{ {func_expr}.brief }}}}'
                # row 3-5 参数（有多少改多少）
                for i, prow in enumerate([3, 4, 5]):
                    if prow < len(tbl.rows) and len(tbl.rows[prow].cells) >= 3:
                        cells = tbl.rows[prow].cells
                        p_expr = f'{func_expr}.parameters'
                        cells[0].text = f'{{% if {p_expr}|length > {i} %}}{{{{ {p_expr}[{i}].name }}}}{{% endif %}}'
                        cells[1].text = f'{{% if {p_expr}|length > {i} %}}{{{{ {p_expr}[{i}].type }}}}{{% endif %}}'
                        cells[2].text = f'{{% if {p_expr}|length > {i} %}}{{{{ {p_expr}[{i}].details }}}}{{% endif %}}'
                # row 7: 返回值（位置和表行数相关，用后数第 2 行兜底）
                ret_row = len(tbl.rows) - 2  # 流程图是最后一行
                if ret_row >= 0 and len(tbl.rows[ret_row].cells) >= 3:
                    r_expr = f'{func_expr}.return_values'
                    cells = tbl.rows[ret_row].cells
                    cells[0].text = f'{{% if {r_expr} %}}{{{{ {r_expr}[0].name }}}}{{% endif %}}'
                    cells[1].text = f'{{% if {r_expr} %}}{{{{ {r_expr}[0].type }}}}{{% endif %}}'
                    cells[2].text = f'{{% if {r_expr} %}}{{{{ {r_expr}[0].details }}}}{{% endif %}}'
                # 最后一行：流程图
                if tbl.rows:
                    tbl.rows[-1].cells[0].text = (
                        f'{{% if {func_expr}.flowchart_image_key %}}'
                        f'{{{{ {func_expr}.flowchart_image_key }}}}'
                        f'{{% endif %}}'
                    )
                print(f'   ✓ A003 T{idx} 函数声明 #{func_count+1} 占位')
                func_count += 1

    # ---- 7. F2：清理 A003 之后到性能章节之前的"样本预置模块段"----
    # 原因：生成器 _append_extra_modules 用深拷贝 A003 段扩展其他模块，
    # 若 A003 段后还残留 A004/A005/A007/A008/A009 的原文段，渲染后会和拷贝段重叠。
    # 这里把这些预置段一次性清掉，模板只留"A001 + A003 两段样板 + 性能/集成等尾章"。
    # 同时：A001 和 A003 之间的 A002 原文段也要清掉（否则 F2 深拷贝 A002 会出现 2 次）。
    print('→ [7] 清理非样板的额外模块段（A002 及 A003 之后所有模块段）')
    from docx.oxml.ns import qn as _qn2
    body = d.element.body

    def _ptxt(e):
        return ''.join(t.text or '' for t in e.iter(_qn2('w:t')))

    # 两段要删：
    # 范围 A: A001 段结尾 → A003 段开头之前（里面是 A002 原文）
    # 范围 B: A003 段结尾 → 性能章节之前（里面是 A004/A005/A007/A008/A009 原文）
    def _find_range_a():
        """A001 结束 (下一个非-Serializer "模块…详细设计" H1) 起 → "模块EEPROM详细设计" 止（不含）"""
        hit_a001 = False
        start = None
        end = None
        for e in list(body.iterchildren()):
            if e.tag.split('}')[-1] == 'p':
                text = _ptxt(e).strip()
                if not hit_a001:
                    if 'Serializer' in text and '详细设计' in text:
                        hit_a001 = True
                    continue
                # A001 之后
                if start is None:
                    if text.startswith('模块') and '详细设计' in text and 'Serializer' not in text and 'EEPROM' not in text:
                        start = e
                else:
                    if 'EEPROM' in text and '详细设计' in text:
                        end = e
                        break
        return start, end

    def _find_range_b():
        """A003 结束 (下一个非-EEPROM "模块…详细设计" H1) 起 → 性能/集成章节 止（不含）"""
        hit_a003 = False
        start = None
        end = None
        for e in list(body.iterchildren()):
            if e.tag.split('}')[-1] == 'p':
                text = _ptxt(e).strip()
                if not hit_a003:
                    if 'EEPROM' in text and '详细设计' in text:
                        hit_a003 = True
                    continue
                if start is None:
                    if text.startswith('模块') and '详细设计' in text and 'EEPROM' not in text:
                        start = e
                else:
                    if any(kw in text for kw in ('性能分析', '函数设计评估', '函数评估', '共通定义', '系统集成')):
                        end = e
                        break
        return start, end

    def _delete_range(start_el, end_el, label):
        if start_el is None:
            print(f'   {label} 无需清理')
            return 0
        to_remove = []
        found = False
        for e in list(body.iterchildren()):
            if e is start_el:
                found = True
            if found:
                if end_el is not None and e is end_el:
                    break
                to_remove.append(e)
        for e in to_remove:
            body.remove(e)
        print(f'   {label} 删除 {len(to_remove)} 个元素')
        return len(to_remove)

    # 先删范围 B（A003 之后），再删范围 A（A001 之后 A003 之前）
    # 顺序重要：先删后面，前面定位才稳
    sb, eb = _find_range_b()
    _delete_range(sb, eb, '范围B(A003→性能)')
    sa, ea = _find_range_a()
    _delete_range(sa, ea, '范围A(A001→A003)')

    # ---- 保存 ----
    DST.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(DST))
    print(f'\n✓ 生产模板已保存：{DST}')
    print(f'  大小: {DST.stat().st_size / 1024 / 1024:.1f} MB')


if __name__ == '__main__':
    main()
