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
from docx.oxml import OxmlElement
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


def _delete_paragraph(p):
    """从文档里真删除一个 python-docx Paragraph。"""
    el = p._element
    el.getparent().remove(el)


def _delete_table(tbl):
    el = tbl._tbl
    el.getparent().remove(el)


def _insert_paragraph_before_table(tbl, text, style_from_para=None):
    """在表格 tbl 之前插入一个新段落，可选沿用某 paragraph 的样式。"""
    if style_from_para is not None:
        new_el = deepcopy(style_from_para._element)
        for r in new_el.findall(qn('w:r')):
            new_el.remove(r)
        tbl._tbl.addprevious(new_el)
        from docx.text.paragraph import Paragraph
        new_p = Paragraph(new_el, style_from_para._parent)
    else:
        from docx.text.paragraph import Paragraph
        new_el = OxmlElement('w:p')
        tbl._tbl.addprevious(new_el)
        new_p = Paragraph(new_el, None)
    new_p.add_run(text)
    return new_p


def _insert_paragraph_after_table(tbl, text, style_from_para=None):
    if style_from_para is not None:
        new_el = deepcopy(style_from_para._element)
        for r in new_el.findall(qn('w:r')):
            new_el.remove(r)
        tbl._tbl.addnext(new_el)
        from docx.text.paragraph import Paragraph
        new_p = Paragraph(new_el, style_from_para._parent)
    else:
        from docx.text.paragraph import Paragraph
        new_el = OxmlElement('w:p')
        tbl._tbl.addnext(new_el)
        new_p = Paragraph(new_el, None)
    new_p.add_run(text)
    return new_p


def _rebuild_config_db_sensor_section(d):
    """把 §3.3.3.2 两张硬编码 sensor 表（IMX623 / IMX728）清掉，改成按
    software_design.config_database.sensors 循环的事实表。

    原结构（样本摸底结果）：
      P192  "3.3.3.2.1 sensor IMX623"
      T6    Serializer/EEPROM/Sensor 事实表（17 行，带真实 IMX623 值）
      P193  "3.3.3.2.2 sensor IMX728"
      T7    同样结构（17 行，IMX728 值）
      P194  "该配置文件依赖于 Serializer、eeprom 和 sensor..."

    新结构：
      P192  "{%p for s in software_design.config_database.sensors %}
             3.3.3.2.{{ loop.index }} sensor {{ s.name }}"   （原标题样式复用）
      T6    事实表只保留标题行 + 若干 jinja 占位行
      P?    "{%p endfor %}"
      P194  保留
    T7 和 P193 整段删除。
    """
    # 1) 定位 P192 和 P193
    p_imx623 = None
    p_imx728 = None
    for i, p in enumerate(d.paragraphs):
        t = p.text.strip()
        if t.startswith('3.3.3.2.1') and 'IMX623' in t:
            p_imx623 = p
        elif t.startswith('3.3.3.2.2') and 'IMX728' in t:
            p_imx728 = p
    if p_imx623 is None:
        print('   ⚠ 找不到 3.3.3.2.1 sensor IMX623 段，跳过清洗')
        return

    # 2) 把 IMX623 段文本替换为 {%p for%}（单独一段 —— docxtpl 要求段落级
    #    控制标签独占段落，否则会把剩余 XML 吞掉导致渲染截断）
    #    然后紧接着插入一段循环标题："3.3.3.2.{{ loop.index }} sensor {{ s.name }}"
    #
    #    注意 schema 里字段叫 config_files（不是 config_database），底下真正装 sensor
    #    记录的是 ConfigDbSensor（无 .serializer / .eeprom 嵌套，那两个落在
    #    ConfigDbModule）。所以这里的循环按 sensors 走，模块级关联表单独由 modules
    #    循环产出（如果 schema 后续演进可以再拓）。
    set_paragraph_text(
        p_imx623,
        '{%p for s in software_design.config_files.sensors %}',
    )
    # 在 {%p for %} 后紧跟一段"动态标题"，样式沿用原 IMX623 标题段
    append_paragraph_after(
        p_imx623,
        '3.3.3.2.{{ loop.index }} sensor {{ s.name }}',
    )
    print('   P 3.3.3.2.1 → {%p for sensors %} + 独立动态标题段')

    # 3) 删 P193（IMX728 段）
    if p_imx728 is not None:
        _delete_paragraph(p_imx728)
        print('   P 3.3.3.2.2 sensor IMX728 → 删除')

    # 4) 清 T6 内容：只留 header 行，剩下行按 jinja 占位重填
    t6 = d.tables[6]
    # 删掉除第 0 行以外所有数据行
    for row in list(t6.rows[1:]):
        row._element.getparent().remove(row._element)
    rows = [
        ('Sensor', 'Name', '', '{{ s.name }}'),
        ('Sensor', 'Description', '', '{{ s.description }}'),
        ('Sensor', 'I2C Address', '', '{{ s.i2c_address }}'),
    ]
    for cells in rows:
        row = t6.add_row()
        for i, val in enumerate(cells):
            if i < len(row.cells):
                row.cells[i].text = val
    # 虚拟通道 fields 循环（每个 field 一行；s.fields 里 vc.* 和其它扁平键都算）
    row_vc_open = t6.add_row()
    row_vc_open.cells[0].text = '{%tr for f in s.fields %}'
    row_vc = t6.add_row()
    if len(row_vc.cells) >= 4:
        row_vc.cells[0].text = 'Sensor'
        row_vc.cells[1].text = '{{ f.key }}'
        row_vc.cells[2].text = ''
        row_vc.cells[3].text = '{{ f.value }}'
    row_vc_close = t6.add_row()
    row_vc_close.cells[0].text = '{%tr endfor %}'

    # 5) 在 T6 之后插入 {%p endfor %}
    _insert_paragraph_after_table(
        t6, '{%p endfor %}', style_from_para=p_imx623,
    )
    print('   T6 → 事实表 + 虚拟通道循环 + {%p endfor %}')

    # 6) 删 T7（原 IMX728 事实表）—— 顺位在 T6 之后第一个 table
    if len(d.tables) > 7:
        tbl7 = d.tables[7]
        try:
            b1 = tbl7.rows[1].cells[0].text.strip() if len(tbl7.rows) > 1 else ''
        except Exception:
            b1 = ''
        if b1.startswith('Serializer'):
            _delete_table(tbl7)
            print('   T7（IMX728 事实表）→ 删除')
        else:
            print(f'   ⚠ T7 不像 IMX728 事实表（b1={b1!r}），跳过删除')


# ============ Group 4：§3 全章 / §5 / §6 / scenarios 循环 ============

def _wire_section3_placeholders(d):
    """把样本 docx 里 §3.1 / §3.2 / §3.3.1 / §3.3.2 下面的硬编码正文段，
    改成 Jinja 占位，字段由 arch_sections.default_software_design() 兜底。

    结构（从 tpl2 摸底）：
      P175 '3.1 简介'            → 下一段(P176) 文本改成 {{ software_design.intro }}
      P177 '3.2 静态信息'        → P178 / P179 两段 NvSIPL 介绍 → 第一段挂 intro，第二段删
      P181 '3.3 接口信息'（节头，不动）
      P182 '3.3.1 外部接口'      → P183 / P184 两段 → P183 挂 external_iface_intro，P184 删
      P185 '3.3.2 内部接口'      → P186 / P187 两段 → P186 挂 internal_iface_intro，P187 删

    留意：本函数前面已经跑过 _rebuild_config_db_sensor_section，
    会在 §3.3.3 塞 `{%p for%}` / `{%p endfor %}` 两段进去（增加段落数）。
    但我们按文字"3.1 简介" / "3.2 静态信息" / "3.3.1 外部接口" / "3.3.2 内部接口"
    定位标题、再按"标题后首个非空正文段"定位内容段，不依赖固定索引。
    """
    # 3.1 简介
    idx = find_paragraph_index(d, '3.1 简介')
    if idx >= 0:
        for ofs in range(1, 5):
            if idx + ofs >= len(d.paragraphs):
                break
            p = d.paragraphs[idx + ofs]
            txt = p.text.strip()
            if not txt:
                continue
            # 遇到下一节标题就停（没正文可改）
            if txt.startswith('3.') and (' ' in txt[:4] or '简' in txt or '静' in txt):
                break
            set_paragraph_text(p, '{{ software_design.intro | e }}')
            print(f'   3.1 简介 → 占位 (P{idx+ofs})')
            break

    # 3.2 静态信息（原正文 2 段 → 保留第一段作占位，删后续冗余段，遇到 3.3 停）
    idx = find_paragraph_index(d, '3.2 静态信息')
    if idx >= 0:
        wired = False
        trash_ps = []
        for ofs in range(1, 8):
            if idx + ofs >= len(d.paragraphs):
                break
            p = d.paragraphs[idx + ofs]
            txt = p.text.strip()
            if not txt:
                continue
            if txt.startswith('3.3') or txt.startswith('3.2.'):
                break
            if not wired:
                # ⚠ 用 | e 过滤：PlantUML 源码里有 '<<app>>' / '<<nv>>' 这类 << >>
                # 文本，docxtpl 没开 jinja autoescape，裸 '<' / '>' 直接进 <w:t>
                # 会把后面的 XML 全吞掉，导出截断到这一段为止。| e 把 <>&"' 转义成
                # 实体引用，Word 正常显示原字符。
                set_paragraph_text(p, '{{ software_design.module_diagram_plantuml | e }}')
                print(f'   3.2 静态信息 → 占位 (P{idx+ofs})')
                wired = True
            else:
                trash_ps.append(p)
        for p in trash_ps:
            _delete_paragraph(p)
        if trash_ps:
            print(f'   3.2 冗余样本段 → 删 {len(trash_ps)} 段')

    # 3.3.1 外部接口
    idx = find_paragraph_index(d, '3.3.1 外部接口')
    if idx >= 0:
        wired = False
        trash_ps = []
        for ofs in range(1, 8):
            if idx + ofs >= len(d.paragraphs):
                break
            p = d.paragraphs[idx + ofs]
            txt = p.text.strip()
            if not txt:
                continue
            if txt.startswith('3.3.2') or txt.startswith('3.3.3'):
                break
            if not wired:
                set_paragraph_text(p, '{{ software_design.external_iface_intro | e }}')
                print(f'   3.3.1 外部接口 → 占位 (P{idx+ofs})')
                wired = True
            else:
                trash_ps.append(p)
        for p in trash_ps:
            _delete_paragraph(p)

    # 3.3.2 内部接口
    idx = find_paragraph_index(d, '3.3.2 内部接口')
    if idx >= 0:
        wired = False
        trash_ps = []
        for ofs in range(1, 8):
            if idx + ofs >= len(d.paragraphs):
                break
            p = d.paragraphs[idx + ofs]
            txt = p.text.strip()
            if not txt:
                continue
            if txt.startswith('3.3.3') or txt.startswith('3.4'):
                break
            if not wired:
                set_paragraph_text(p, '{{ software_design.internal_iface_intro | e }}')
                print(f'   3.3.2 内部接口 → 占位 (P{idx+ofs})')
                wired = True
            else:
                trash_ps.append(p)
        for p in trash_ps:
            _delete_paragraph(p)


def _wire_section5_resources(d):
    """把 §5 资源消耗下面的 KPI1-KPI8 硬编码块、§5.1 内存、§5.2 CPU 自由段
    一次性清掉，挂上 `{{ resources.memory_summary }}` / `{{ resources.cpu_summary }}`。

    `items[]` 当前 schema 只是 list[ResourceKpi]，样本里没现成的表格可以循环，
    这一版先把两个 summary 文案占位接上，保证"用户什么都没填 → 回落 PreDev 默认文案"
    的最小闭环；items 循环等 §5 真正加表时再补。
    """
    # 5.1 内存：找到"5.1  内存"（docx 里是**双空格**），把后续到"5.2  CPU"之间所有非空段
    # 变成一个 memory_summary 占位 + 删掉其余。
    # ⚠ 不能用裸 '5.1' / '5.2' 做 needle：会把 '4.5.1 功能描述' / '4.5.2 接口信息' 命中
    start = find_paragraph_index(d, '5.1  内存')
    end = find_paragraph_index(d, '5.2  CPU')
    # §5 主区可能先有一大段"资源消耗原目标：KPI1..KPI8"，这些段落在 5.1 之前。
    sec5 = find_paragraph_index(d, '5. 资源消耗')
    if sec5 >= 0 and start > sec5:
        trash = []
        for i in range(sec5 + 1, start):
            p = d.paragraphs[i]
            if p.text.strip():
                trash.append(p)
        for p in trash:
            _delete_paragraph(p)
        if trash:
            print(f'   5. 资源消耗 KPI1-KPI8 硬编码块 → 删 {len(trash)} 段')
        # 关键：删了段之后 paragraphs 列表位移，start/end 需重新找
        start = find_paragraph_index(d, '5.1  内存')
        end = find_paragraph_index(d, '5.2  CPU')

    if start >= 0 and end > start:
        wired = False
        trash = []
        for i in range(start + 1, end):
            p = d.paragraphs[i]
            if not p.text.strip():
                continue
            if not wired:
                set_paragraph_text(p, '{{ resources.memory_summary | e }}')
                print(f'   5.1 内存 → 占位 (P{i})')
                wired = True
            else:
                trash.append(p)
        for p in trash:
            _delete_paragraph(p)

    # 5.2 CPU：从"5.2  CPU"到 §6 之间
    start = find_paragraph_index(d, '5.2  CPU')
    end = find_paragraph_index(d, '6. 备选软件架构')
    if start >= 0 and end > start:
        wired = False
        trash = []
        for i in range(start + 1, end):
            p = d.paragraphs[i]
            if not p.text.strip():
                continue
            if not wired:
                set_paragraph_text(p, '{{ resources.cpu_summary | e }}')
                print(f'   5.2 CPU → 占位 (P{i})')
                wired = True
            else:
                trash.append(p)
        for p in trash:
            _delete_paragraph(p)


def _wire_section6_alternative(d):
    """§6 备选软件架构 → {{ alternative_arch }}。"""
    idx = find_paragraph_index(d, '6. 备选软件架构')
    end = find_paragraph_index(d, '7. 系统集成')
    if idx >= 0 and end > idx:
        wired = False
        trash = []
        for i in range(idx + 1, end):
            p = d.paragraphs[i]
            if not p.text.strip():
                continue
            if not wired:
                set_paragraph_text(p, '{{ alternative_arch | e }}')
                print(f'   6. 备选软件架构 → 占位 (P{i})')
                wired = True
            else:
                trash.append(p)
        for p in trash:
            _delete_paragraph(p)


# ---------- 4.X.1 多段功能描述循环（A005 / A006） ----------

def _wire_a005_a006_segments(d):
    """A005 / A006 的 §4.X.1 多段功能描述。

    样本现状（A005 为例，P262 起）：
        P262  {{ components_by_id.A005.function_desc }}             ← 已有单段占位
        P263  实现测试同步曝光跑马灯...                             ← 硬编码正文段 1
        P264  PREDEV_007-R001-A005、PREDEV_007-R002-A005             ← 硬编码溯源
        ...（若干对正文+溯源，到 '4.5.2 接口信息' 为止）

    PreDev 把 A005/A006 写成多段（每段单独 title + description + linked_req_ids），
    schema 已经加了 function_desc_segments（list[FunctionDescSegment]）。
    这里把 P262 的 function_desc 占位扩展成：
        {% if components_by_id.AXXX.function_desc_segments %}
        {%p for seg in components_by_id.AXXX.function_desc_segments %}
        {{ seg.title }}
        {{ seg.description }}
        {% for rid in seg.linked_req_ids %}{{ rid }}{% if not loop.last %}、{% endif %}{% endfor %}
        {%p endfor %}
        {% else %}
        {{ components_by_id.AXXX.function_desc }}
        {% endif %}
    并把 P263 开始的硬编码正文段整段删除，直到 "4.X.2 接口信息"。
    """
    for comp_id, next_title in [
        ('A005', '4.5.2 接口信息'),
        ('A006', '4.6.2 接口信息'),
    ]:
        anchor = f'{{{{ components_by_id.{comp_id}.function_desc }}}}'
        idx = find_paragraph_index(d, anchor)
        if idx < 0:
            print(f'   ⚠ {comp_id} function_desc 锚点未找到')
            continue
        end = find_paragraph_index(d, next_title)
        if end <= idx:
            print(f'   ⚠ {comp_id} {next_title} 未找到或位置异常')
            continue

        # 1) 删除 P(idx+1) ~ P(end-1) 之间所有硬编码样本段
        trash = []
        for i in range(idx + 1, end):
            p = d.paragraphs[i]
            if p.text.strip():
                trash.append(p)
        for p in trash:
            _delete_paragraph(p)
        if trash:
            print(f'   {comp_id} 4.X.1 样本正文 → 删 {len(trash)} 段')

        # 2) 把单段占位改成"优先多段、回落单段"的 {%p if %} / {%p else %} / {%p endif %} 块
        #    注意：docxtpl 要段落级（整段消失）用 {%p ... %}；行内的 {% if %} 会残留空段
        p = d.paragraphs[idx]
        set_paragraph_text(
            p, f'{{%p if components_by_id.{comp_id}.function_desc_segments %}}'
        )

        # 3) 在 if 段后依次插入: {%p for%} / {{ seg.title }} / {{ seg.description }} /
        #    溯源段（行内 for，让其拼在同段里） / {%p endfor %} / {%p else %} /
        #    {{ components_by_id.XXX.function_desc }} / {%p endif %}
        inserts = [
            f'{{%p for seg in components_by_id.{comp_id}.function_desc_segments %}}',
            '{{ seg.title | e }}',
            '{{ seg.description | e }}',
            ('{% for rid in seg.linked_req_ids %}{{ rid | e }}'
             '{% if not loop.last %}、{% endif %}{% endfor %}'),
            '{%p endfor %}',
            '{%p else %}',
            f'{{{{ components_by_id.{comp_id}.function_desc | e }}}}',
            '{%p endif %}',
        ]
        cursor = p
        for text in inserts:
            cursor = append_paragraph_after(cursor, text)
        print(f'   {comp_id} 4.X.1 → 多段 for 循环 (P{idx})')


# ---------- §4.X.3 / 4.X.4 场景段循环 ----------

# (component_id, 锚点 '场景说明：...' 的子串前缀, 下一节标题串)
# 用来界定该场景段的开始和结束范围；该范围内所有非空段都变成循环体的一次。
# 其中 4.1 / 4.2 / 4.3 / 4.4 / 4.7 原本每个组件只有 1-2 段场景；
# 4.4 (Camera Module) 场景段含 IMX728_CustomInterface / IMX623_CustomInterface
# 两条上版本样本残留，一并由循环体代替。
COMPONENT_SCENARIO_RANGES = [
    ('A001', '4.1.4 时序图', '4.2 组件名称'),
    ('A002', '4.2.3 时序图', '4.3 组件名称'),
    ('A003', '4.3.3 时序图', '4.4 组件名称'),
    ('A004', '4.4.5 时序图', '4.5 组件名称'),
    ('A005', '4.5.3 时序图', '4.6 组件名称'),
    ('A006', '4.6.3 时序图', '4.7 组件名称'),
    ('A007', '4.7.3 时序图', '4.8 组件名称'),
    # A008 的场景段在 4.8.5（前面 4.8.2 安全目标 / 4.8.3 功能模块构成 / 4.8.4 接口信息）
    ('A008', '4.8.5 时序图', '4.9 组件名称'),
    ('A009', '4.9.3 时序图', '5. 资源消耗'),
]


def _wire_component_scenarios(d):
    """§4.X.N 时序图段 → 按 components_by_id.AXXX.scenarios 循环。

    样本里每个组件的"4.X.N 时序图"标题下有一段或多段"场景说明：xxx"硬编码文字。
    这些是上一版的样例数据（例如 '场景说明：调用IMX728_CustomInterface'），
    当前用户在 ModuleEditor 里填的 scenarios 还没有模板挂点，就被这些残留覆盖掉。

    方案：把"4.X.N 时序图"标题后到下一节"4.X+1 组件名称"之间所有非空正文段整段删掉，
    统一替换成：
        {%p for sc in components_by_id.AXXX.scenarios %}
        场景说明：{{ sc.title }}
        {{ sc.description }}
        {%p endfor %}

    （PlantUML InlineImage 挂点等 Group 6 导出器里再绑 image_key；这里先把
    硬编码 IMX728 / IMX623 / MAX96717 残留一并清掉，让用户真正填的 scenarios
    能显出来，用户没填就整段空，比现在"永远印着别人家样例"健康得多。）
    """
    for comp_id, title, next_section in COMPONENT_SCENARIO_RANGES:
        idx = find_paragraph_index(d, title)
        if idx < 0:
            print(f'   ⚠ {comp_id} {title} 未找到')
            continue
        end = find_paragraph_index(d, next_section)
        if end <= idx:
            print(f'   ⚠ {comp_id} {next_section} 未找到或位置异常')
            continue

        # 1) 删标题后到下一节前所有非空段
        trash = []
        for i in range(idx + 1, end):
            p = d.paragraphs[i]
            if p.text.strip():
                trash.append(p)
        for p in trash:
            _delete_paragraph(p)
        if trash:
            print(f'   {comp_id} {title} → 清 {len(trash)} 段硬编码场景')

        # 2) 在标题段后依次插入循环体三段
        cursor = d.paragraphs[idx]
        for text in [
            f'{{%p for sc in components_by_id.{comp_id}.scenarios %}}',
            '场景说明：{{ sc.title | e }}',
            '{{ sc.description | e }}',
            '{%p endfor %}',
        ]:
            cursor = append_paragraph_after(cursor, text)
        print(f'   {comp_id} {title} → scenarios for 循环 (P{idx})')


def harden_interface_table(tbl, widths_dxa=None):
    """修 §4 接口表的 3 个老毛病，让长接口行跨页不糊成一坨：

    1. 列宽重算：原样本 col1 接口溯源只有 840dxa（1.5cm），长文件名
       `WriteUint8VerifyMAX96717F.cpp` 挤成一列一字；col3 接口类型 1125dxa
       （2cm），`内部接口` 也被竖过来排。新宽度合计仍 ≈ 8265dxa 不改总宽：
       接口溯源 2200 / 方法名 2400 / 接口类型 1200 / 参数 2000 / 说明 ~465(剩余)。
    2. tblLayout fixed + tblGrid：Word 和 WPS 以 grid 分列；否则 tcW 是建议，
       长内容会强行"挤"相邻列造成错位。
    3. 每个 <w:tr> 加 <w:cantSplit/>，首行加 <w:tblHeader/>：一行不被半道劈到
       下一页；真要跨页时下一页自动重复表头，接口溯源/方法名/… 标题跟数据对齐。
    """
    tblPr = tbl._tbl.find(qn('w:tblPr'))
    if tblPr is None:
        tblPr = OxmlElement('w:tblPr')
        tbl._tbl.insert(0, tblPr)
    # 2) fixed layout
    for child in tblPr.findall(qn('w:tblLayout')):
        tblPr.remove(child)
    tbl_layout = OxmlElement('w:tblLayout')
    tbl_layout.set(qn('w:type'), 'fixed')
    tblPr.append(tbl_layout)

    # 1) widths
    cols = widths_dxa or (2200, 2400, 1200, 2000, 465)
    grid = tbl._tbl.find(qn('w:tblGrid'))
    if grid is not None:
        for g in list(grid):
            grid.remove(g)
        for w in cols:
            gc = OxmlElement('w:gridCol')
            gc.set(qn('w:w'), str(w))
            grid.append(gc)
    # 同步每行每格 tcW
    for row in tbl._tbl.findall(qn('w:tr')):
        tcs = row.findall(qn('w:tc'))
        for i, tc in enumerate(tcs):
            if i >= len(cols):
                break
            tcPr = tc.find(qn('w:tcPr'))
            if tcPr is None:
                tcPr = OxmlElement('w:tcPr')
                tc.insert(0, tcPr)
            for old in tcPr.findall(qn('w:tcW')):
                tcPr.remove(old)
            tcW = OxmlElement('w:tcW')
            tcW.set(qn('w:w'), str(cols[i]))
            tcW.set(qn('w:type'), 'dxa')
            tcPr.append(tcW)

    # 3) cantSplit on every row + tblHeader on row 0
    for i, row in enumerate(tbl._tbl.findall(qn('w:tr'))):
        trPr = row.find(qn('w:trPr'))
        if trPr is None:
            trPr = OxmlElement('w:trPr')
            row.insert(0, trPr)
        if trPr.find(qn('w:cantSplit')) is None:
            trPr.append(OxmlElement('w:cantSplit'))
        if i == 0 and trPr.find(qn('w:tblHeader')) is None:
            trPr.append(OxmlElement('w:tblHeader'))


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
        # 修列宽 + 禁行跨页 + 表头重复：rebuild 完再调，否则新 add 的行没有 trPr
        if cols_in_tbl == 5:
            harden_interface_table(t)
        elif cols_in_tbl == 6:
            # T9/T11/T18 等 6 列变种：把多出来的那列放在末尾，总宽保持
            harden_interface_table(t, widths_dxa=(2200, 2400, 1200, 1800, 465, 200))

    # Camera Module A004 的类描述表 T14
    print('→ [6.5] 4.4.2 Class Description T14 循环')
    rebuild_loop_table(
        d.tables[14], 'cls', 'components_by_id.A004.classes',
        ['{{ cls.seq }}', '{{ cls.class_name }}', '{{ cls.description }}'],
    )

    # ---- 6.6. §3.3.3.2 配置文件详细说明（清掉 IMX623/IMX728 样本数据）----
    #
    # 样本 docx 里 §3.3.3.2.1 sensor IMX623 / §3.3.3.2.2 sensor IMX728 是硬编码的
    # 标题 + T6/T7 两张手填表。这两张表不走任何占位，所以用户哪怕 §3.3.3 什么都没选
    # 也会在导出 docx 里看到别人家的 IMX623 数据 —— 文档污染。
    #
    # 改成一个按 software_design.config_database.sensors 的循环：
    #   - 把 "3.3.3.2.1 sensor IMX623" 段改成 {%p for s in ... %}3.3.3.2.{{loop.index}} sensor {{s.name}}
    #   - T6 改成同一 sensor 的键值事实表（Serializer/EEPROM/Sensor 都从 s / s.serializer / s.eeprom 读）
    #   - "3.3.3.2.2 sensor IMX728" 段和 T7 整段删除（loop 本身会复制 T6 作为模板）
    #   - 在 T6 之后插一个 {%p endfor %} 段封口
    print('→ [6.6] 3.3.3.2 sensor 块样本清洗 + 循环化')
    try:
        _rebuild_config_db_sensor_section(d)
    except Exception as e:  # noqa: BLE001
        print(f'   ⚠ 3.3.3.2 清洗失败（样本结构变了？）: {e}')

    # ---- 6.7. Group 4：§3 全章 / §5 / §6 / 场景循环 挂占位 ----
    # 顺序注意：先处理 §4 (scenarios + A005/A006 多段)，最后再做 §3/§5/§6，
    # 原因：§3/§5 会删段，paragraphs 索引位移，再去找 '4.5.3 时序图' 会失败
    print('→ [6.7] Group 4 占位：scenarios + A005/A006 → §3.1/§3.2/§3.3.1/§3.3.2 + §5 + §6')
    try:
        _wire_a005_a006_segments(d)
    except Exception as e:  # noqa: BLE001
        print(f'   ⚠ A005/A006 多段循环挂载失败: {e}')
    try:
        _wire_component_scenarios(d)
    except Exception as e:  # noqa: BLE001
        print(f'   ⚠ 组件场景循环挂载失败: {e}')
    try:
        _wire_section3_placeholders(d)
    except Exception as e:  # noqa: BLE001
        print(f'   ⚠ §3 占位挂载失败: {e}')
    try:
        _wire_section5_resources(d)
    except Exception as e:  # noqa: BLE001
        print(f'   ⚠ §5 资源占位挂载失败: {e}')
    try:
        _wire_section6_alternative(d)
    except Exception as e:  # noqa: BLE001
        print(f'   ⚠ §6 备选架构占位挂载失败: {e}')

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
