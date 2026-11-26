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
    # 全部走 | e 过滤：sensor 名字 / 描述里可能带 "<" ">" "&" 这些要转义的字符
    # （Sony IMX728 原厂文档里 "Virtual Channel #0" 就带 "#"，描述里也可能含 "<...>")
    rows = [
        ('Sensor', 'Name', '', '{{ s.name | e }}'),
        ('Sensor', 'Description', '', '{{ s.description | e }}'),
        ('Sensor', 'I2C Address', '', '{{ s.i2c_address | e }}'),
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
        row_vc.cells[1].text = '{{ f.key | e }}'
        row_vc.cells[2].text = ''
        row_vc.cells[3].text = '{{ f.value | e }}'
    row_vc_close = t6.add_row()
    row_vc_close.cells[0].text = '{%tr endfor %}'

    # 5) 在 T6 之后插入 {%p else %}暂无提示{%p endfor %}
    #    jinja2 支持 for..else：当 sensors 为空列表时整段跳到 else 分支，
    #    渲染一句提示段代替 "空白 3.3.3.2 节 + 无表" 的视觉空白。
    p_else = _insert_paragraph_after_table(
        t6, '{%p else %}', style_from_para=p_imx623,
    )
    p_hint = append_paragraph_after(
        p_else,
        '暂无配置文件信息。请在上方 §3.3.3 配置文件区下拉选择 database '
        '路径并点"立即解析"，解析成功后此处会按解析结果自动渲染每个 sensor '
        '的 Name / I2C / Virtual Channel 等事实表。',
    )
    append_paragraph_after(p_hint, '{%p endfor %}')
    print('   T6 → 事实表 + 虚拟通道循环 + for..else 空态提示 + {%p endfor %}')

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
                # 2026-11-23 ④ 换成 InlineImage：让 auto_embed_plantuml_in_context 把
                # software_design.module_diagram.plantuml 渲染成 PNG，模板里直接 {{ ...image }}
                set_paragraph_text(p, '{{ software_design.module_diagram.image }}')
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
    # V4.0 参考模板里这块是 KPI1-8 原目标 + "2023/10/20 经过跟客户沟通 ..." 变更说明，
    # 作为一整个 kpi_adjustment 自由文本字段挂一个 `{%p if ... %}` 条件段放在原位置，
    # 用户没填就不出，填了就按原样出（含多行、含 KPI 枚举）。
    sec5 = find_paragraph_index(d, '5. 资源消耗')
    if sec5 >= 0 and start > sec5:
        trash = []
        for i in range(sec5 + 1, start):
            p = d.paragraphs[i]
            if p.text.strip():
                trash.append(p)
        kept_anchor = None
        if trash:
            # 第一段改成 `{%p if %}` + `{{ ... | e }}`，后面段落用 `{%p endif %}` 收口
            # —— 用三段独立 paragraph，别写进同一段，避免 docxtpl 的 jinja 标签与文本混放时
            # <w:p> runs 顺序被打乱
            kept_anchor = trash[0]
            set_paragraph_text(
                kept_anchor,
                '{%p if resources.kpi_adjustment %}',
            )
            body_p = append_paragraph_after(
                kept_anchor, '{{ resources.kpi_adjustment | e }}',
            )
            append_paragraph_after(body_p, '{%p endif %}')
            # 其余 KPI 硬编码段全删
            for p in trash[1:]:
                _delete_paragraph(p)
            print(f'   5. 资源消耗 KPI 原目标段 → `{{%p if resources.kpi_adjustment %}}` 条件段（原 {len(trash)} 段）')
        # 关键：删/插了段之后 paragraphs 列表位移，start/end 需重新找
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


# ---------- §4.X 组件启用开关 + A008 security_mode 三态 ----------

# 每个组件 §4.X 整章的起止 anchor：
#   start_anchor：章首标题 (如 '4.1 组件名称Serializer')
#   end_anchor：  下一章起点标题（最后一章用 §5 顶）
# 顺序必须和 docx 里一致。
COMPONENT_SECTION_RANGES = [
    ('A001', '4.1 组件名称Serializer',     '4.2 组件名称Deserializer'),
    ('A002', '4.2 组件名称Deserializer',   '4.3 组件名称EEPROM'),
    ('A003', '4.3 组件名称EEPROM',         '4.4 组件名称Camera Module'),
    ('A004', '4.4 组件名称Camera Module',  '4.5 组件名称nvsipl_camera'),
    ('A005', '4.5 组件名称nvsipl_camera',  '4.6 组件名称nvsipl_multicast'),
    ('A006', '4.6 组件名称nvsipl_multicast', '4.7 组件名称PMIC'),
    ('A007', '4.7 组件名称PMIC',           '4.8 组件名称Camera Security'),
    ('A008', '4.8 组件名称Camera Security', '4.9 组件名称Campwr'),
    ('A009', '4.9 组件名称Campwr',         '5. 资源消耗'),
]


def _wire_component_enable_wrappers(d):
    """把每个 §4.X 组件章整章包进 `{%p if components_by_id.AXXX.enabled %}...{%p endif %}`。

    用户在 ModuleEditor 里把某个组件 enabled=false（或根本没出现在 components 列表里）
    就让整个 §4.X 标题 + 表 + 时序图 都从导出 docx 里消失，而不是空白显示
    "4.X 组件名称 XX / 暂无接口条目"。这样部分项目覆盖面 = 实际 §4，纯净。

    实现：
      - 在章首标题（如 "4.1 组件名称Serializer"）前**插入**一段 `{%p if ... %}`
      - 在下一章起点标题（如 "4.2 组件名称Deserializer"）前**插入**一段 `{%p endif %}`
      - jinja 用 `components_by_id.AXXX.enabled | default(true)` 兜底，确保老项目
        没有 enabled 字段时按 true 走，保持向后兼容。

    Camera Security (A008) 有自己的三态 security_mode，但即便 security_mode=full
    也走 enabled 这一层 —— 两者独立：enabled 管"要不要出 §4.X"，security_mode 管
    "§4.X.1-§4.X.5 里哪些子节可见"。disabled 等价 enabled=false，由 UI 层转化。
    """
    for comp_id, start_anchor, end_anchor in COMPONENT_SECTION_RANGES:
        start_idx = find_paragraph_index(d, start_anchor)
        if start_idx < 0:
            print(f'   ⚠ {comp_id} 章首 "{start_anchor}" 未找到，跳过包裹')
            continue
        end_idx = find_paragraph_index(d, end_anchor)
        if end_idx <= start_idx:
            print(f'   ⚠ {comp_id} 章尾 "{end_anchor}" 未找到或位置异常，跳过包裹')
            continue
        # 在章首前**插入**一段开 if（样式沿用章首标题，不会撞字体）
        # append_paragraph_after(p_prev, ...) 用前一段（空段也行）插入
        if start_idx == 0:
            print(f'   ⚠ {comp_id} 章首已在文档首段，跳过')
            continue
        p_prev = d.paragraphs[start_idx - 1]
        append_paragraph_after(
            p_prev,
            f'{{%p if components_by_id.{comp_id}.enabled | default(true) %}}',
        )
        # 插入后 paragraphs 列表位移一位，重新找 end_idx
        end_idx = find_paragraph_index(d, end_anchor)
        if end_idx <= 0:
            print(f'   ⚠ {comp_id} 插入 if 后找不到 "{end_anchor}"')
            continue
        p_end_prev = d.paragraphs[end_idx - 1]
        append_paragraph_after(p_end_prev, '{%p endif %}')
        print(f'   {comp_id} §4.X → `{{%p if {comp_id}.enabled %}}..{{%p endif %}}` 包裹')


def _wire_a008_security_mode(d):
    """§4.8 Camera Security 三态 mode：full / manual_brief / disabled。

    全局的 enabled 开关由 _wire_component_enable_wrappers 挂载。这里**再嵌套一层**
    security_mode 分支细控 §4.8 里的子节可见性：
      - full          → 走正常 enabled 路径，§4.8.1-§4.8.5 全出
      - manual_brief  → §4.8.1 功能描述 + §4.8.2 安全性目标 两段简述，§4.8.3/§4.8.4/§4.8.5
                        子节标题全隐（接口表/模块构成/时序图都不出）
      - disabled      → 用户上层应把 enabled 也置 false；这里不管

    实现上在 §4.8.3 "功能模块构成" 前插 `{%p if ...security_mode != 'manual_brief' %}`，
    在 §4.8.5 时序图末尾（也就是 §4.9 Campwr 开头前）插 `{%p endif %}`。
    这样 manual_brief 下 §4.8.3/§4.8.4/§4.8.5 全块隐藏，只留 §4.8.1/§4.8.2。
    """
    start_anchor = '4.8.3 功能模块构成'
    end_anchor = '4.9 组件名称Campwr'
    start_idx = find_paragraph_index(d, start_anchor)
    end_idx = find_paragraph_index(d, end_anchor)
    if start_idx < 0 or end_idx <= start_idx:
        print(f'   ⚠ A008 security_mode 包裹找不到 anchor: '
              f'{start_anchor}={start_idx} / {end_anchor}={end_idx}')
        return
    p_before_start = d.paragraphs[start_idx - 1] if start_idx > 0 else None
    if p_before_start is None:
        print('   ⚠ A008 §4.8.3 已在首段，跳过')
        return
    append_paragraph_after(
        p_before_start,
        '{%p if components_by_id.A008.security_mode != "manual_brief" %}',
    )
    end_idx = find_paragraph_index(d, end_anchor)
    p_before_end = d.paragraphs[end_idx - 1]
    append_paragraph_after(p_before_end, '{%p endif %}')
    print('   A008 §4.8.3-§4.8.5 → `{%p if security_mode != "manual_brief" %}` 包裹')


def _wire_a008_security_goals_and_modules(d):
    """§4.8.2 安全性目标 / §4.8.3 功能模块构成 → security_goals / security_modules 占位段。

    V4.0 参考模板里这两节是**自由文本段**，当前模板残留着一堆硬编码英文 Goal 1 / Goal 2
    之类的样本。清理成占位（挂 `| e` 过滤）。
    """
    # §4.8.2
    for anchor, placeholder, nxt in [
        ('4.8.2 功能目标（安全性目标）',
         '{{ components_by_id.A008.security_goals | e }}',
         '4.8.3 功能模块构成'),
        ('4.8.3 功能模块构成',
         '{{ components_by_id.A008.security_modules | e }}',
         '4.8.4 Camera Security'),
    ]:
        start = find_paragraph_index(d, anchor)
        end = find_paragraph_index(d, nxt)
        if start < 0 or end <= start:
            print(f'   ⚠ {anchor} 未找到/位置异常')
            continue
        wired = False
        trash = []
        for i in range(start + 1, end):
            p = d.paragraphs[i]
            if not p.text.strip():
                continue
            if not wired:
                set_paragraph_text(p, placeholder)
                wired = True
            else:
                trash.append(p)
        for p in trash:
            _delete_paragraph(p)
        print(f'   {anchor} → 占位（{"写入" if wired else "无段可改"}, 删 {len(trash)} 残段）')


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

        # 2) 在标题段后依次插入循环体
        #    2026-11-23 ④：新增一行 {{ sc.image }} —— auto_embed_plantuml_in_context
        #    遍历 scenario 字典时若含非空 plantuml 源码会渲染 PNG 并挂到 sc.image。
        #    没填 plantuml 的 scenario 不会报错，image 字段直接 Undefined 走空。
        cursor = d.paragraphs[idx]
        for text in [
            f'{{%p for sc in components_by_id.{comp_id}.scenarios %}}',
            '场景说明：{{ sc.title | e }}',
            '{{ sc.description | e }}',
            '{{ sc.image }}',
            '{%p endfor %}',
        ]:
            cursor = append_paragraph_after(cursor, text)
        print(f'   {comp_id} {title} → scenarios for 循环 (P{idx})')


def collapse_interleaved_spacer_columns(tbl):
    """把 10 列「真实列 + 分隔列」交错结构的表压回 5 列。

    原样本 T8（A001 外部接口）每真实列后面跟一列空的分隔列，物理 10 列：
        idx  0     1    2     3    4     5    6     7    8    9
             溯源  空   方法  空   类型  空   参数  空   空   说明
    docxtpl 渲染后数据只落在 0/2/4/6/9，1/3/5/7/8 永远是空单元格。
    这些空格子在 Word 里仍有边框，视觉上像"多出一张表"（用户截图里的
    §4.1.2.2 下方空壳表格）。这里把分隔列用 gridSpan=2 并进左边内容列：
        [0+1] [2+3] [4+5] [6+7+8] [9]
    并同步 tblGrid 为 5 列。必须在 rebuild_loop_table 之后、harden 之前调用。
    """
    merge_map = [(0, 1, 2), (2, 3, 2), (4, 5, 2), (6, 7, 3), (9, 9, 1)]
    for tr in tbl._tbl.findall(qn('w:tr')):
        tcs = tr.findall(qn('w:tc'))
        if len(tcs) != 10:
            continue
        # 收集要保留的 tc 及其 span
        kept = []
        for start, _end, span in merge_map:
            if start >= len(tcs):
                continue
            tc = tcs[start]
            tcPr = tc.find(qn('w:tcPr'))
            if tcPr is None:
                tcPr = OxmlElement('w:tcPr')
                tc.insert(0, tcPr)
            for old in tcPr.findall(qn('w:gridSpan')):
                tcPr.remove(old)
            if span > 1:
                gs = OxmlElement('w:gridSpan')
                gs.set(qn('w:val'), str(span))
                tcPr.append(gs)
            kept.append(tc)
        # 删除没保留的 tc
        keep_set = set(id(tc) for tc in kept)
        for tc in tcs:
            if id(tc) not in keep_set:
                tr.remove(tc)
    # 同步 tblGrid 为 5 列
    grid = tbl._tbl.find(qn('w:tblGrid'))
    if grid is not None:
        for g in list(grid):
            grid.remove(g)
        for w in (1700 + 90, 1900 + 90, 850 + 90, 1700 + 90 + 90, 1665):
            gc = OxmlElement('w:gridCol')
            gc.set(qn('w:w'), str(w))
            grid.append(gc)


def harden_interface_table(tbl, widths_dxa=None):
    """修 §4 接口表的 3 个老毛病，让长接口行跨页不糊成一坨：

    1. 列宽重算：原样本 col1 接口溯源只有 840dxa（1.5cm），长文件名
       `WriteUint8VerifyMAX96717F.cpp` 挤成一列一字；col3 接口类型 1125dxa
       （2cm），`内部接口` 也被竖过来排。
       **2026-11-23 R2 修**：历史默认 `(2200,2400,1200,2000,465)` 把"说明"列
       压到 465dxa (~0.82cm)，Word 会强行把它扩到最小可见宽度再反过来挤前面的
       列，最终 col1 接口溯源被挤成一字宽（见截图 12 - Serializer 内部接口）。
       **新默认** 5 列总宽 8265dxa 不变，但各列均衡：
         接口溯源 1800 / 方法名 2000 / 接口类型  900 / 参数 1800 / 说明 1765
       10 列变种（T8：原样本每真实列后面跟一个空"分隔"列）由 widths_dxa 显式传。
       6 列变种（T10/T17：5 真实列 + 1 冗余空列）同样显式传，让冗余列仅 200dxa。
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

    # 1) widths —— 5 列默认（接口溯源 / 方法名 / 接口类型 / 参数 / 说明）
    cols = widths_dxa or (1800, 2000, 900, 1800, 1765)
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
    # T12 是 A003 EEPROM 的**内部接口表**（5 列，样本里有 M24C04xxx 行）。
    # 2026-11-24 修：之前误判为「类描述表」而剔除 → 样本行原样留在产物里，
    # 用户填的内部接口下面会多出一串 M24C04xxx 空壳行。T13 才是类表（3 列）。
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
    # T25 是 A009 Campwr 的**内部接口表**（5 列，样本里有 campwr SetConfig 等 8 行）。
    # 2026-11-24 修：之前误判为「修改历史表」而剔除 → 样本 8 行原样留在产物里，
    # 用户截图里的"多余空壳表格"就是这个。T26 才是修改历史表（6 列版本号/日期/…）。
    (26, 'A009', 'i', 'components_by_id.A009.internal_interfaces'),
]

# 接口表的标准 5 列占位（T9/T11/T18 多一列"备注"，但循环体也写 5 列即可，
# 第 6 列保持原样为空）
INTERFACE_COLS = [
    # ⚠ 必须统一 | e 过滤：接口表这几列全是**从工程源码扫出来的 C++ 符号**，
    #    `std::unique_ptr<CNvMDevice::DriverContext>` / `CNvMMax96724_Fusa::SetControlLinkSoc`
    #    / 模板参数 `<T>` / 引用参数 `T&` 这些都带 '<' '>' '&' 字符，
    #    docxtpl 没开 jinja autoescape，裸 '<CNvMDevice::DriverContext>' 直接进 <w:t>，
    #    Word 的 lxml 把它当成合法元素名（QName 校验失败，`::` 不是合法 XML 名字符），
    #    打开 docx 时整个 document.xml 失败 —— 即用户看到的"第 4 章 A002 之后全没了"。
    #    对齐 §3/§5/§6 文本占位统一补 | e。
    # 接口溯源列：分组首行显示「⚑ 文件名（N 项）」小标题；同组后续行留空
    # （小标题已交代来源，几百行里重复文件名只会淹没内容）；无来源的手填行照常显示。
    # group_first / group_size / group_name 由 _group_interfaces_by_file 打上。
    ('{% if i.group_first %}⚑ {{ i.group_name | e }}（{{ i.group_size }} 项）'
     '{% elif not i.group_name %}{{ i.source | e }}{% endif %}'),
    '{{ i.method | e }}',
    '{{ i.type | e }}',
    '{{ i.params | e }}',
    '{{ i.description | e }}',
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

    # ---- 1. 封面 V1.0 → {{ project.version }} + 公司名 → {{ project.company }} ----
    print('→ [1/7] 封面版本号 / 公司名占位')
    hit_v = 0
    hit_c = 0
    for p in d.paragraphs[:60]:
        if replace_in_run(p, 'V1.0', '{{ project.version | e }}'):
            hit_v += 1
        if replace_in_run(p, '中科创达软件股份有限公司', '{{ project.company | e }}'):
            hit_c += 1
    print(f'   版本号替换 {hit_v} 处，公司名替换 {hit_c} 处')

    # ---- 2. T0 历史记录 / T1 评审记录 ----
    #
    # ⚠ 统一 | e 过滤，对齐 §3/§5/§6 文本占位和 §4 接口表的教训：
    # 用户在前端填的 reviewer/content/remark 这些自由文本字段**可能带 "<" ">" "&"**
    # （例如 content="修复 vcard<Overview> 字段映射", remark="参考 §3.2.1<Note>"），
    # docxtpl 没开 jinja autoescape，裸 "<Overview>" 进 <w:t> 后 Word/lxml 会把它当
    # 成合法 XML 元素名，整段 docx body 失败无法打开。
    print('→ [2/7] T0 历史 / T1 评审 循环')
    rebuild_loop_table(
        d.tables[0], 'h', 'project.history',
        ['{{ h.date | e }}', '{{ h.version | e }}', '{{ h.author | e }}', '{{ h.content | e }}'],
    )
    rebuild_loop_table(
        d.tables[1], 'r', 'project.reviews',
        ['{{ r.version | e }}', '{{ r.review_date | e }}', '{{ r.reviewer | e }}',
         '{{ r.approver | e }}', '{{ r.opinion | e }}', ''],
    )

    # ---- 3. §1.3~1.5 术语/参考/假设 表 ----
    print('→ [3/7] 1.3 术语 / 1.4 参考 / 1.5 假设 循环')
    rebuild_loop_table(
        d.tables[2], 't', 'overview.terms',
        ['{{ t.term | e }}', '{{ t.definition | e }}'],
    )
    rebuild_loop_table(
        d.tables[3], 'r', 'overview.ref_docs',
        ['{{ r.no | e }}', '{{ r.name | e }}', '{{ r.version | e }}', '{{ r.note | e }}'],
    )
    rebuild_loop_table(
        d.tables[4], 'a', 'overview.assumptions',
        ['{{ a.input | e }}', '{{ a.time | e }}', '{{ a.description | e }}'],
    )

    # ---- 4. §2 需求映射表 T5 ----
    print('→ [4/7] 2. 需求映射 T5 循环')
    rebuild_loop_table(
        d.tables[5], 'm', 'mappings',
        ['{{ m.swe1_id | e }}', '{{ m.swe2_id | e }}', '{{ m.id_meaning | e }}',
         '{{ m.remark | e }}', '{{ m.version | e }}'],
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
                                   f'编号：{{{{ components_by_id.{comp_id}.id | e }}}}')
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
            placeholder = f'{{{{ components_by_id.{comp_id}.function_desc | e }}}}'
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
                            f'{{{{ rid | e }}}}{{% if not loop.last %}}、{{% endif %}}'
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
        # 原模板样本里物理列数三种：
        #   5  : 常规（接口溯源 / 方法名 / 接口类型 / 参数 / 说明）
        #   6  : 5 真实列 + 1 冗余空"备注"列（T10/T17 外部接口）
        #   10 : 5 真实列 × (真实 + 分隔) 的交错结构（T8 A001 外部接口）
        # INTERFACE_COLS 是 5 个表达式；多余物理列补空串让 rebuild_loop_table 不越界。
        cols_in_tbl = len(t.columns)
        if cols_in_tbl == 10:
            # 交错布局：index 1/3/5/7/9 是内容列，0/2/4/6/8 是分隔列
            # 按 r0_text 实际位置（[接口溯源, '', 方法名, '', 接口类型, '', 参数, '', '', 说明]）
            # 映射到 INTERFACE_COLS 的 [{{src}}, {{method}}, {{type}}, {{params}}, {{desc}}]
            exprs = ['', '', '', '', '', '', '', '', '', '']
            exprs[0] = INTERFACE_COLS[0]  # 接口溯源 → col0 (header 在 col0)
            exprs[2] = INTERFACE_COLS[1]  # 方法名 → col2
            exprs[4] = INTERFACE_COLS[2]  # 接口类型 → col4
            exprs[6] = INTERFACE_COLS[3]  # 参数 → col6
            exprs[9] = INTERFACE_COLS[4]  # 说明 → col9
        else:
            exprs = list(INTERFACE_COLS)
            while len(exprs) < cols_in_tbl:
                exprs.append('')
        rebuild_loop_table(t, loop_var, iter_expr, exprs)
        # 10 列交错结构先压成 5 列（合并分隔列），否则渲染后空分隔列
        # 会留下边框，看起来像"多出一张空表"。
        if cols_in_tbl == 10:
            collapse_interleaved_spacer_columns(t)
            cols_in_tbl = 5
        # 修列宽 + 禁行跨页 + 表头重复：rebuild 完再调，否则新 add 的行没有 trPr
        if cols_in_tbl == 5:
            # 用新默认：(1800, 2000, 900, 1800, 1765) —— 总宽保持 ≈8265dxa
            harden_interface_table(t)
        elif cols_in_tbl == 6:
            # T10/T17：5 真实列 + 1 冗余 → 冗余列 100dxa，5 真实列按 (1800,2000,900,1800,1665) ≈8265
            harden_interface_table(t, widths_dxa=(1800, 2000, 900, 1800, 1665, 100))
        elif cols_in_tbl == 10:
            # T8 (A001 外部接口)：真实列按 (1700,1900,850,1700,1665) = 7815 + 5 分隔列 (90×5=450) ≈8265
            harden_interface_table(
                t,
                widths_dxa=(1700, 90, 1900, 90, 850, 90, 1700, 90, 90, 1665),
            )
        else:
            print(f'   ⚠ T{tbl_idx} 异常列数 {cols_in_tbl}，跳过 harden')
        # 空态暗器提示：当该组件的 external/internal_interfaces 为空时，
        # 表只有标题行，视觉上是一张空表 —— 在表后紧跟一个 `{%p if ... | length == 0 %}`
        # 提示段，告诉用户到上方 Picker 去扫描/导入。
        iface_kind = '外部接口' if 'external_interfaces' in iter_expr else '内部接口'
        hint = (
            f'（暂无{iface_kind}条目。可在上方「§4 {comp_id} 接口 ← 工程扫描」'
            f'面板里从扫描结果里挑选导入，或在接口表编辑器里手动添加。）'
        )
        # 用 `(expr | default([])) | length == 0` 包一层，防止组件缺失时
        # jinja 的 undefined 让整段渲染炸掉；默认走空列表 → 提示段照常出。
        # 以三段独立 paragraph 落地，别把 {%p if %} 和文本挤在一行，docxtpl 更稳。
        p_if = _insert_paragraph_after_table(
            t,
            f'{{%p if ({iter_expr} or []) | length == 0 %}}',
        )
        p_hint = append_paragraph_after(p_if, hint)
        append_paragraph_after(p_hint, '{%p endif %}')

    # Camera Module A004 的类描述表 T14
    print('→ [6.5] 4.4.2 Class Description T14 循环 + 空态提示')
    rebuild_loop_table(
        d.tables[14], 'cls', 'components_by_id.A004.classes',
        # class_name 就是 C++ 类名，必然含 `<` `>`（模板类）；description 也可能含
        ['{{ cls.seq | e }}', '{{ cls.class_name | e }}', '{{ cls.description | e }}'],
    )
    # 类表空时（用户完全没在前端填 classes）贴一行占位提示，避免只剩空表头。
    # 和 §4.X.2 接口表的空态策略一致。
    try:
        class_tbl = d.tables[14]
        # 在 T14 后插入 if/提示/endif 三段
        p_if = _insert_paragraph_after_table(
            class_tbl,
            '{%p if (components_by_id.A004.classes or []) | length == 0 %}',
        )
        p_hint = append_paragraph_after(
            p_if,
            '（暂无类条目。可在 §4.4 Camera Module 面板的 "4.4.2 类描述" 区手动添加，'
            '或后续推送接通 AI 类描述扫描后自动填充。）',
        )
        append_paragraph_after(p_hint, '{%p endif %}')
        print('   §4.4.2 空态提示 → 挂载成功')
    except Exception as e:  # noqa: BLE001
        print(f'   ⚠ §4.4.2 空态提示挂载失败: {e}')

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

    # ---- §4.8 Camera Security 自由文本 + security_mode 三态 + §4.X enabled ----
    # 顺序严格：先挂 §4.8.2/§4.8.3 自由文本 → 再 wrap security_mode
    #   → 最后 wrap §4.X enabled（最外层）。
    # 反过来的话，外层 if 的 anchor 已经被 jinja 符号占掉，内层 find_paragraph_index
    # 就找不到纯中文章标题了。
    try:
        _wire_a008_security_goals_and_modules(d)
    except Exception as e:  # noqa: BLE001
        print(f'   ⚠ A008 §4.8.2/§4.8.3 自由文本挂载失败: {e}')
    try:
        _wire_a008_security_mode(d)
    except Exception as e:  # noqa: BLE001
        print(f'   ⚠ A008 security_mode 三态包裹失败: {e}')
    try:
        _wire_component_enable_wrappers(d)
    except Exception as e:  # noqa: BLE001
        print(f'   ⚠ §4.X enabled 包裹失败: {e}')

    # ---- 7. §7 系统集成 ----
    print('→ [7/7] 7.1 集成顺序 / 7.2 集成原则')
    # 7.1 顺序段
    order_idx = find_paragraph_index(d, '各个模块集成的顺序')
    if order_idx >= 0:
        set_paragraph_text(d.paragraphs[order_idx], '{{ integration.order | e }}')
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
                           f'.description | e }}}}')
            set_paragraph_text(desc_p, placeholder)
            print(f'   {title} → 描述段占位 (P{tidx+ofs})')
            break

    # ---- 保存 ----
    DST.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(DST))
    print(f'\n✓ 生产模板已保存：{DST}')


if __name__ == '__main__':
    main()
