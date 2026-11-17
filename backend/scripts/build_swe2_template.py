"""
从 swe2_arch_sample.docx 一次性构造生产模板 swe2_arch.docx。

跑法：
    cd backend
    venv/bin/python scripts/build_swe2_template.py

产出：backend/app/templates/aspice/swe2_arch.docx

策略（基于样本结构摸底）：
  1. 封面 V1.0 → {{ project.version }}（run 级替换，保留字号粗体）
  2. T0 历史 / T1 评审 → {%tr for %} 循环
  3. 保留目录区（P50~140）不动（Word 用户手工更新或忽略）
  4. P142+ 正文改造：
     - 1.3 术语表 T2 → 循环
     - 1.4 参考文档 T3 → 循环
     - 1.5 假设表 T4 → 循环
     - 2. 需求映射 T5 → 循环
     - 4.1~4.9 组件段落 → by_id 字典访问：{{ components_by_id.A001.function_desc }}
       每张接口表（T8~T26）→ {%tr for i in components_by_id.AXXX.external_interfaces %}
     - 7.1 集成顺序 → {{ integration.order }}
     - 7.2.1~7.2.6 → 直接用 {{ integration.principles_by_key.usability.description }}
"""

from pathlib import Path
from docx import Document
from docx.oxml.ns import qn
from copy import deepcopy

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / 'app' / 'templates' / 'aspice' / 'swe2_arch_sample.docx'
DST = ROOT / 'app' / 'templates' / 'aspice' / 'swe2_arch.docx'

# 样本里 P50~141 是"冻结目录区"（上一版本 TOC 字段的文本镜像），
# 正文从 P142 "1. 概述（架构&概要）" 开始。所有按文本定位的占位替换
# 都从 BODY_START 开始，跳过目录区避免误替换（目录区显示旧版本的章节名）。
BODY_START = 142


# ============ 工具函数 ============

def replace_in_run(paragraph, needle, replacement):
    """在段落里按 run 替换，保留样式。返回是否替换过。"""
    hit = False
    for run in paragraph.runs:
        if needle in run.text:
            run.text = run.text.replace(needle, replacement)
            hit = True
    return hit


def rebuild_loop_table(tbl, loop_var, iter_expr, data_exprs, *, keep_header_rows=1):
    """
    把一个数据表改成 jinja 循环表。
    tbl:              python-docx Table
    loop_var:         迭代变量名，如 'h'
    iter_expr:        迭代表达式，如 'project.history'
    data_exprs:       数据占位列表（len == 列数），如 ['{{ h.date }}', '{{ h.version }}', ...]
    keep_header_rows: 保留的表头行数（默认 1）
    """
    # 删掉数据行
    for row in list(tbl.rows[keep_header_rows:]):
        row._element.getparent().remove(row._element)
    # 开标签行
    r_open = tbl.add_row()
    r_open.cells[0].text = '{%%tr for %s in %s %%}' % (loop_var, iter_expr)
    # 数据行
    r_data = tbl.add_row()
    for i, expr in enumerate(data_exprs):
        if i < len(tbl.columns):
            r_data.cells[i].text = expr
    # 闭标签行
    r_close = tbl.add_row()
    r_close.cells[0].text = '{%tr endfor %}'


def find_paragraph_index(d, needle, start=BODY_START):
    """按文本内容找段落索引（contains 匹配）。默认从 BODY_START 开始跳过目录区。"""
    for i, p in enumerate(d.paragraphs[start:], start):
        if needle in p.text:
            return i
    return -1


def set_paragraph_text(p, new_text):
    """清空段落所有 run，只保留第一个 run 的样式，把文本设成 new_text."""
    runs = p.runs
    if runs:
        first_style_run = runs[0]
        # 删除除第一个外的 run
        for r in runs[1:]:
            r._element.getparent().remove(r._element)
        first_style_run.text = new_text
    else:
        p.add_run(new_text)


def append_paragraph_after(p, text, style=None):
    """在段落 p 后面插入一个新段落（复用 p 的样式）。"""
    new_p_xml = deepcopy(p._element)
    # 清空 runs
    for r in new_p_xml.findall(qn('w:r')):
        new_p_xml.remove(r)
    p._element.addnext(new_p_xml)
    # 构造新的段落对象
    from docx.text.paragraph import Paragraph
    new_p = Paragraph(new_p_xml, p._parent)
    run = new_p.add_run(text)
    if style is not None:
        new_p.style = style
    return new_p


# ============ 组件接口表位置映射 ============
# 基于样本摸底的实际位置（表格 index → 组件 + 接口类型）
# 格式: (table_idx, comp_id, loop_var, iter_field)
COMPONENT_IFACE_TABLES = [
    # Serializer A001
    (8,  'A001', 'i', 'components_by_id.A001.external_interfaces'),
    (9,  'A001', 'i', 'components_by_id.A001.internal_interfaces'),
    # Deserializer A002
    (10, 'A002', 'i', 'components_by_id.A002.external_interfaces'),
    (11, 'A002', 'i', 'components_by_id.A002.internal_interfaces'),
    # EEPROM A003
    (12, 'A003', 'i', 'components_by_id.A003.external_interfaces'),
    (13, 'A003', 'i', 'components_by_id.A003.internal_interfaces'),
    # Camera Module A004（T14 是类表，跳过；T15/T16 才是接口表）
    (15, 'A004', 'i', 'components_by_id.A004.external_interfaces'),
    (16, 'A004', 'i', 'components_by_id.A004.internal_interfaces'),
    # nvsipl_camera A005
    (17, 'A005', 'i', 'components_by_id.A005.external_interfaces'),
    (18, 'A005', 'i', 'components_by_id.A005.internal_interfaces'),
    # nvsipl_multicast A006
    (19, 'A006', 'i', 'components_by_id.A006.external_interfaces'),
    (20, 'A006', 'i', 'components_by_id.A006.internal_interfaces'),
    # PMIC A007
    (21, 'A007', 'i', 'components_by_id.A007.external_interfaces'),
    (22, 'A007', 'i', 'components_by_id.A007.internal_interfaces'),
    # Camera Security A008
    (23, 'A008', 'i', 'components_by_id.A008.external_interfaces'),
    (24, 'A008', 'i', 'components_by_id.A008.internal_interfaces'),
    # Campwr A009
    (25, 'A009', 'i', 'components_by_id.A009.external_interfaces'),
    (26, 'A009', 'i', 'components_by_id.A009.internal_interfaces'),
]

# 接口表的标准 5 列占位（T9/T11/T18 多一列"备注"，但循环体也写 5 列即可，
# 第 6 列保持原样为空）
INTERFACE_COLS = [
    '{{ i.source }}',
    '{{ i.method }}',
    '{{ i.type }}',
    '{{ i.params }}',
    '{{ i.description }}',
]


# ============ 功能描述段落映射（段落 index → 组件 + 占位）============
# 基于样本 P 位置，每个组件都有 "4.X.1 功能描述" 后紧跟功能说明段
# 规律：找 "编号：AXXX" 段，往下走 2 段（"4.X.1 功能描述" + 功能说明段）
COMPONENT_FUNC_DESC = [
    # (num_label, comp_id)
    ('编号：A001', 'A001'),
    ('编号：A002', 'A002'),
    ('编号：A003', 'A003'),
    ('编号：A004', 'A004'),
    ('编号：A005', 'A005'),
    ('编号：A006', 'A006'),
    ('编号：A007', 'A007'),
    ('编号：A008', 'A008'),
    ('编号：A009', 'A009'),  # 样本里 Campwr 写的是 "编号：A007"（样本 bug），这里按新 ID 改
]


# ============ 主流程 ============

def main():
    print(f'→ 读 {SRC}')
    d = Document(str(SRC))

    # ---- 1. 封面 V1.0 → {{ project.version }} ----
    print('→ [1/7] 封面版本号占位')
    hit = 0
    for p in d.paragraphs[:60]:
        if replace_in_run(p, 'V1.0', '{{ project.version }}'):
            hit += 1
    print(f'   替换 {hit} 处')

    # ---- 2. T0 历史记录 / T1 评审记录 ----
    print('→ [2/7] T0 历史 / T1 评审 循环')
    rebuild_loop_table(
        d.tables[0], 'h', 'project.history',
        ['{{ h.date }}', '{{ h.version }}', '{{ h.author }}', '{{ h.content }}'],
    )
    rebuild_loop_table(
        d.tables[1], 'r', 'project.reviews',
        ['{{ r.version }}', '{{ r.review_date }}', '{{ r.reviewer }}',
         '{{ r.approver }}', '{{ r.opinion }}', ''],
    )

    # ---- 3. §1.3~1.5 术语/参考/假设 表 ----
    print('→ [3/7] 1.3 术语 / 1.4 参考 / 1.5 假设 循环')
    rebuild_loop_table(
        d.tables[2], 't', 'overview.terms',
        ['{{ t.term }}', '{{ t.definition }}'],
    )
    rebuild_loop_table(
        d.tables[3], 'r', 'overview.ref_docs',
        ['{{ r.no }}', '{{ r.name }}', '{{ r.version }}', '{{ r.note }}'],
    )
    rebuild_loop_table(
        d.tables[4], 'a', 'overview.assumptions',
        ['{{ a.input }}', '{{ a.time }}', '{{ a.description }}'],
    )

    # ---- 4. §2 需求映射表 T5 ----
    print('→ [4/7] 2. 需求映射 T5 循环')
    rebuild_loop_table(
        d.tables[5], 'm', 'mappings',
        ['{{ m.swe1_id }}', '{{ m.swe2_id }}', '{{ m.id_meaning }}',
         '{{ m.remark }}', '{{ m.version }}'],
    )

    # ---- 5. §4 组件功能描述段落 ----
    print('→ [5/7] 4.X.1 功能描述段 占位')
    for num_label, comp_id in COMPONENT_FUNC_DESC:
        # 找 "编号：AXXX" 段。样本里 Campwr 写成 A007（和 PMIC 冲突），
        # 这里的 A009 其实在样本里是 A007，所以找两次：精确先，再段落位置兜底
        idx = find_paragraph_index(d, num_label)
        if idx < 0 and comp_id == 'A009':
            # Campwr 兜底：往"4.9 组件名称Campwr"附近找
            cp_idx = find_paragraph_index(d, '4.9 组件名称Campwr')
            if cp_idx >= 0:
                # 编号段紧跟标题后
                idx = cp_idx + 1
                # 顺便把样本里错误的 "编号：A007" 改成 "编号：{{ components_by_id.A009.id }}"
                set_paragraph_text(d.paragraphs[idx],
                                   f'编号：{{{{ components_by_id.{comp_id}.id }}}}')
        if idx < 0:
            print(f'   ⚠ 找不到 {num_label}')
            continue
        # idx 是 "编号：AXXX" 段，往下 2 段是功能描述内容段（4.X.1 功能描述 之后）
        # 不同组件下面的段落数目不同，统一处理：
        # idx+1 = "4.X.1 功能描述"
        # idx+2 = 功能描述文本段（要替换成占位）
        desc_idx = idx + 2
        if desc_idx < len(d.paragraphs):
            # 替换成 {{ components_by_id.AXXX.function_desc }}
            # 为了保留"PREDEV_... 需依赖该模块实现" 溯源段，用 Jinja 的 if 判断
            # 这里简单做法：把这一段替换成完整占位，溯源行留给下一段（或直接合并）
            original = d.paragraphs[desc_idx].text.strip()
            placeholder = f'{{{{ components_by_id.{comp_id}.function_desc }}}}'
            set_paragraph_text(d.paragraphs[desc_idx], placeholder)
            print(f'   {num_label} → desc 段替换为占位 (原: {original[:30]}...)')

            # 下一段可能是溯源 "PREDEV_xxx-Rxxx-AXXX 需依赖该模块实现"
            # 把它改成条件占位
            next_idx = desc_idx + 1
            if next_idx < len(d.paragraphs):
                nxt = d.paragraphs[next_idx].text.strip()
                if '依赖该模块实现' in nxt or 'PREDEV' in nxt:
                    # 构造一个 Jinja 表达式：如果有 linked_req_ids 就拼起来
                    tmpl = (f'{{% if components_by_id.{comp_id}.linked_req_ids %}}'
                            f'{{% for rid in components_by_id.{comp_id}.linked_req_ids %}}'
                            f'{{{{ rid }}}}{{% if not loop.last %}}、{{% endif %}}'
                            f'{{% endfor %}}需依赖该模块实现。'
                            f'{{% endif %}}')
                    set_paragraph_text(d.paragraphs[next_idx], tmpl)

    # ---- 6. §4 组件接口表 ----
    print('→ [6/7] 4.X.2 接口表 循环')
    for tbl_idx, comp_id, loop_var, iter_expr in COMPONENT_IFACE_TABLES:
        if tbl_idx >= len(d.tables):
            print(f'   ⚠ 表格索引 {tbl_idx} 超范围')
            continue
        t = d.tables[tbl_idx]
        # 部分表 6 列（多个空"备注"列）—— 按列数生成占位
        cols_in_tbl = len(t.columns)
        exprs = list(INTERFACE_COLS)
        while len(exprs) < cols_in_tbl:
            exprs.append('')
        rebuild_loop_table(t, loop_var, iter_expr, exprs)

    # Camera Module A004 的类描述表 T14
    print('→ [6.5] 4.4.2 Class Description T14 循环')
    rebuild_loop_table(
        d.tables[14], 'cls', 'components_by_id.A004.classes',
        ['{{ cls.seq }}', '{{ cls.class_name }}', '{{ cls.description }}'],
    )

    # ---- 7. §7 系统集成 ----
    print('→ [7/7] 7.1 集成顺序 / 7.2 集成原则')
    # 7.1 顺序段
    order_idx = find_paragraph_index(d, '各个模块集成的顺序')
    if order_idx >= 0:
        set_paragraph_text(d.paragraphs[order_idx], '{{ integration.order }}')
        print(f'   7.1 集成顺序 → 占位 (P{order_idx})')

    # 7.2.1~7.2.6 原则的描述段（每个 7.2.X 标题后一段）
    principle_keys = ['usability', 'security', 'integrity',
                      'normalize', 'scalability', 'openness']
    principle_titles = ['7.2.1 易用性原则', '7.2.2 安全性原则', '7.2.3 业务完整性原则',
                        '7.2.4 业务规范化原则', '7.2.5 可扩展性原则', '7.2.6 开放性原则']
    for key, title in zip(principle_keys, principle_titles):
        tidx = find_paragraph_index(d, title)
        if tidx < 0:
            print(f'   ⚠ 找不到 {title}')
            continue
        # 描述段在标题下一段，要跳过空段 + 跳过下一个 7.2.X 标题
        for ofs in range(1, 6):
            if tidx + ofs >= len(d.paragraphs):
                break
            desc_p = d.paragraphs[tidx + ofs]
            txt = desc_p.text.strip()
            if not txt:
                continue
            # 下一个原则标题 → 没内容段，跳过
            if txt.startswith('7.') and '原则' in txt:
                break
            placeholder = (f'{{{{ integration.principles_by_key.{key}'
                           f'.description }}}}')
            set_paragraph_text(desc_p, placeholder)
            print(f'   {title} → 描述段占位 (P{tidx+ofs})')
            break

    # ---- 保存 ----
    DST.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(DST))
    print(f'\n✓ 生产模板已保存：{DST}')


if __name__ == '__main__':
    main()
