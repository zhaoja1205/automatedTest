"""SWE.3 详细设计文档 — v3 生成器（推送 H）。

替代 arch_generator.py 中的 export_swe3_docx_v2：
- 不再用 docxtpl 的 {{ }} / {% for %} 填空
- 改为 python-docx + lxml 直接在骨架 docx 上原地插入内容

骨架模板 = `templates/aspice/swe3_detail.docx`（用户手工精简的 1.4MB 版）
- 1/2/3/8/9/10/11/14/15 章内容定稿不动（只补 1.3 参考文档、2 术语追加、3.2 图+表）
- 4/5/6/7 章用样板展开为 8 个模块的完整详设
- 13.2 边界值表遍历所有 focus_functions 聚合

对外入口: `export_swe3(project: dict, out_dir: Path) -> dict`
"""
from __future__ import annotations

import copy
import io
import logging
import re
from pathlib import Path
from typing import Any, Optional

from docx.oxml.ns import qn
from lxml import etree

from app.core import arch_sections
from app.core.arch_skeleton_scanner import SkeletonScanner, _text_of_paragraph
from app.core.template_engine import (
    _shrink_png_if_huge,
    fetch_plantuml_png,
    plantuml_encode,
)

logger = logging.getLogger(__name__)

# ---- 模块顺序（对应新骨架的 4~11 章）----
# 新模板物理章节顺序：Serializer → EEPROM → Deserializer → CameraModule
#   → CameraSecurity → nvsipl_camera → nvsipl_multicast → PMIC
# 对应 PreDev 口径 ID（见 arch_sections.MODULE_SHORT）：
#   A001 → A003 → A002 → A004 → A008 → A005 → A006 → A007
# 2026-11-17 由旧口径（A005=CameraSecurity/A008=PMIC）统一到 PreDev 口径：
# ID 维度 A005=nvsipl_camera / A008=CameraSecurity；模板物理章节位置不变，
# 仅 MODULE_ORDER / MODULE_CHAPTERS 的 ID 映射调整。
MODULE_ORDER = ["A001", "A003", "A002", "A004", "A008", "A005", "A006", "A007"]

# (chapter_no, anchor_title_kw, short_name, name_match_keywords, manual_only)
# - anchor_title_kw: 模板里 L2 heading 的核心关键字（唯一定位章节）
# - short_name: 用于设计 ID / 节标题
# - name_match_keywords: 从 project 数据里按模块 name 模糊匹配（不绑死 ID；大小写/空格不敏感）
# - manual_only: True 时只保留章节骨架 + 占位，不构造 L4/L5
# chapter_no 对应模板物理章节位置；short_name 遵循 PreDev 口径。
MODULE_CHAPTERS: list[tuple[int, str, str, tuple[str, ...], bool]] = [
    (4,  "Serializer详细设计",        "Serializer",       ("serializer",),                                 False),
    (5,  "EEPROM详细设计",            "EEPROM",           ("eeprom",),                                     False),
    (6,  "Deserializer详细设计",      "Deserializer",     ("deserializer",),                               False),
    (7,  "CameraModule详细设计",      "CameraModule",     ("cameramodule", "camera module"),               False),
    (8,  "CameraSecurity详细设计",    "CameraSecurity",   ("camerasecurity", "camera security"),           True),  # 由人工维护（A008）
    (9,  "nvsipl_camera详细设计",     "nvsipl_camera",    ("nvsipl_camera", "cnvsiplmaster"),              False),
    (10, "nvsipl_multicast详细设计",  "nvsipl_multicast", ("nvsipl_multicast", "multicast"),               False),
    (11, "PMIC详细设计",              "PMIC",             ("pmic",),                                       False),
]


def _norm(s: str) -> str:
    """小写化 + 去空格/下划线，用于模块名模糊匹配。"""
    return (s or "").lower().replace(" ", "").replace("_", "").replace("-", "")


def _match_module_by_keywords(modules: dict[str, dict], keywords: tuple[str, ...]) -> dict:
    """在 modules dict 里找 name 含任一关键字的模块；找不到返回空 dict。"""
    kws = [_norm(k) for k in keywords]
    for mid, m in modules.items():
        nm_norm = _norm(m.get("name") or "")
        id_norm = _norm(mid or "")
        for k in kws:
            if k and (k in nm_norm or k in id_norm):
                return m
    return {}


# ============================================================================
# 数据归一化：swe3.modules 可能是 list 也可能是 dict，统一成 dict[id, module]
# ============================================================================
# 模块 name → ID 的反向映射（骨架里 heading 用 name 写，project 里 id 常为空）
_NAME_TO_ID = {v: k for k, v in arch_sections.MODULE_SHORT.items()}


def _module_richness(m: dict) -> int:
    """估算模块的数据丰度（classes + functions + nv_original_functions 的总数）。"""
    if not isinstance(m, dict):
        return 0
    return (
        len(m.get("classes") or [])
        + len(m.get("functions") or [])
        + len(m.get("nv_original_functions") or [])
    )


def _normalize_modules(raw: Any) -> dict[str, dict]:
    """把 swe3.modules 归一成 dict，key 是 MODULE_SHORT 的 ID（A001~A008）。

    - list[{id?, component_id?, name, ...}] → dict[id, module]
    - dict[id, module]                       → 原样返回
    - 同 id 出现多次（_migrate_swe3 会追加默认空模块）：保留数据最丰富的一份
    """
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    out: dict[str, dict] = {}
    for m in raw:
        if not isinstance(m, dict):
            continue
        mid = m.get("id") or m.get("component_id")
        if not mid:
            name = (m.get("name") or "").strip()
            mid = _NAME_TO_ID.get(name)
            if not mid:
                for nm, pid in _NAME_TO_ID.items():
                    if name.replace(" ", "").lower() == nm.replace(" ", "").lower():
                        mid = pid
                        break
        if not mid:
            continue
        # 同 ID 重复时：保留数据最丰富的一份（避免迁移追加的空模块覆盖真实模块）
        if mid in out and _module_richness(out[mid]) >= _module_richness(m):
            continue
        out[mid] = m
    return out


# ============================================================================
# 工具：段落 / run 构造
# ============================================================================
def _make_p(text: str, style: Optional[str] = None):
    """构造一个独立的 <w:p> 元素（未挂载）。"""
    p = etree.Element(qn("w:p"))
    if style:
        pPr = etree.SubElement(p, qn("w:pPr"))
        pStyle = etree.SubElement(pPr, qn("w:pStyle"))
        pStyle.set(qn("w:val"), style)
    if text:
        r = etree.SubElement(p, qn("w:r"))
        t = etree.SubElement(r, qn("w:t"))
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = text
    return p


def _set_cell_text(tc, text: str) -> None:
    """清掉 tc 的段落（保 tcPr），写入一段文字。"""
    for child in list(tc):
        if child.tag in (qn("w:p"), qn("w:tbl")):
            tc.remove(child)
    p = etree.SubElement(tc, qn("w:p"))
    if text:
        r = etree.SubElement(p, qn("w:r"))
        t = etree.SubElement(r, qn("w:t"))
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = str(text)


def _rebuild_table_rows(tbl, data_rows: list[list[str]], keep_header: int = 1):
    """把一张表的数据行替换成 data_rows（保表头，保格式）。

    - 保留前 keep_header 行（通常是 1 行表头）
    - 其余行先全部删掉
    - 然后把最后一行（表头或样板）当模板，deepcopy 出 N 行，填入 data_rows
    """
    rows = tbl.findall(qn("w:tr"))
    if not rows:
        return
    header_rows = rows[:keep_header]
    template_row = rows[-1] if len(rows) > keep_header else copy.deepcopy(rows[0])
    # 删除除表头外的所有行
    for tr in rows[keep_header:]:
        tbl.remove(tr)
    # 按 data_rows 追加
    for cells in data_rows:
        new_tr = copy.deepcopy(template_row)
        # R4.10：剥掉数据行单元格的底色（shading / fill）。模板里样板数据行
        # 可能带着和表头同样的浅灰底色（w:shd），deepcopy 过来会让所有
        # 数据行都是灰的，视觉上和表头混在一起 —— 数据行背景应为透明/白。
        _strip_tc_shading(new_tr)
        tcs = new_tr.findall(qn("w:tc"))
        for i, tc in enumerate(tcs):
            txt = cells[i] if i < len(cells) else ""
            _set_cell_text(tc, str(txt))
        tbl.append(new_tr)


def _strip_tc_shading(tr_elem) -> None:
    """从一行里所有单元格的 <w:tcPr> 中删除 <w:shd> 底色节点。

    用在数据行上，让它们不再继承表头/样板的灰色填充。表头行调用方不传入即可。
    """
    for tc in tr_elem.findall(qn("w:tc")):
        tcPr = tc.find(qn("w:tcPr"))
        if tcPr is None:
            continue
        for shd in list(tcPr.findall(qn("w:shd"))):
            tcPr.remove(shd)


# ============================================================================
# PlantUML → PNG → 嵌入 docx
# ============================================================================
# 存最近一次 PlantUML 渲染失败原因，供上层写占位文本用（线程不安全，但本流程单线程）
_last_plantuml_error: Optional[str] = None


def _plantuml_to_png_bytes(src: str) -> Optional[bytes]:
    """PlantUML 源码 → 降采样 PNG bytes；失败返回 None 且把原因记到 _last_plantuml_error。"""
    global _last_plantuml_error
    _last_plantuml_error = None
    if not src or "@startuml" not in src:
        _last_plantuml_error = "源码为空或无 @startuml"
        return None
    try:
        encoded = plantuml_encode(src)
        png = fetch_plantuml_png(encoded, timeout=15.0)
        return _shrink_png_if_huge(png)
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        _last_plantuml_error = msg
        logger.warning("PlantUML 渲染失败：%s", msg)
        return None


def _insert_image_after(scanner: SkeletonScanner, anchor_elem, png: bytes, width_mm: float = 140.0):
    """在 anchor_elem 之后插入一个居中图片段落。

    通过 python-docx 的高级 API 添加图片（复用 scanner.doc），然后把生成的
    paragraph 元素 move 到锚点之后。
    """
    import tempfile

    from docx.shared import Mm

    tmp_dir = Path(tempfile.mkdtemp(prefix="aspice_v3_"))
    fp = tmp_dir / "img.png"
    fp.write_bytes(png)
    # 1) 先在文档末尾加一个段落 + 图
    p_doc = scanner.doc.add_paragraph()
    p_doc.alignment = 1  # center
    run = p_doc.add_run()
    run.add_picture(str(fp), width=Mm(width_mm))
    # 2) 把新段落的 lxml 从末尾取出来，插到锚点后
    new_p = p_doc._p
    new_p.getparent().remove(new_p)
    anchor_elem.addnext(new_p)
    return new_p


def _insert_image_into_table_cell(scanner: SkeletonScanner, tbl_elem, png: bytes,
                                  row_index: int = -1, cell_index: int = 0,
                                  width_mm: float = 140.0) -> bool:
    """把 PNG 插入表格指定行/列的单元格内（作为该单元格的段落）。

    用于"函数详情表"的最后一行"函数流程图"占位单元格 — 让图呈现在表格内部，而不是表格下方。
    row_index=-1 表示最后一行；cell_index=0 表示第一个 tc（gridspan 已跨 3 列）。
    成功返回 True；表结构不符或插入失败返回 False（调用方可回落到 _insert_image_after）。
    """
    import tempfile

    from docx.shared import Mm

    rows = tbl_elem.findall(qn("w:tr"))
    if not rows:
        return False
    tr = rows[row_index]
    tcs = tr.findall(qn("w:tc"))
    if cell_index >= len(tcs):
        return False
    tc = tcs[cell_index]

    tmp_dir = Path(tempfile.mkdtemp(prefix="aspice_v3_cell_"))
    fp = tmp_dir / "img.png"
    fp.write_bytes(png)
    # 用临时段落产出图 run，再把段落 move 进单元格
    p_doc = scanner.doc.add_paragraph()
    p_doc.alignment = 1  # center
    p_doc.add_run().add_picture(str(fp), width=Mm(width_mm))
    new_p = p_doc._p
    new_p.getparent().remove(new_p)

    # 清掉单元格里原有的空段落（占位），把图段落放进去
    for child in list(tc):
        if child.tag == qn("w:p"):
            tc.remove(child)
    tc.append(new_p)
    return True


def _insert_text_into_table_cell(scanner: SkeletonScanner, tbl_elem, text: str,
                                 row_index: int = -1, cell_index: int = 0,
                                 italic: bool = True) -> bool:
    """把一段文字放进表格指定行/列的单元格（替换原有占位段落）。

    用于复杂函数（body_lines > 阈值）的"函数流程图"单元格 — 放一句"请手工绘制"提示，
    避免 AI 流程图图太大/模糊；也避免整个单元格空白。
    """
    rows = tbl_elem.findall(qn("w:tr"))
    if not rows:
        return False
    tr = rows[row_index]
    tcs = tr.findall(qn("w:tc"))
    if cell_index >= len(tcs):
        return False
    tc = tcs[cell_index]

    p_doc = scanner.doc.add_paragraph()
    p_doc.alignment = 1  # center
    run = p_doc.add_run(text or "")
    if italic:
        run.italic = True
    new_p = p_doc._p
    new_p.getparent().remove(new_p)

    for child in list(tc):
        if child.tag == qn("w:p"):
            tc.remove(child)
    tc.append(new_p)
    return True


# ============================================================================
# 章节 1：概述 — 1.3 参考文档表
# ============================================================================
def _fill_chapter_1_overview(scanner: SkeletonScanner, project: dict) -> None:
    """补齐 1.3 参考文档表的内容。

    骨架里 1.3 的表头是 ('NO.', '参考⽂献名称', '⽂件版本')，只有 1 行表头。
    从 project.meta.docs 或 overview.ref_docs 读行。
    """
    h = scanner.find_heading(level=3, title_contains="参考文档")
    if h is None:
        h = scanner.find_heading(level=3, title_contains="参考⽂档")
    if h is None:
        logger.warning("1.3 参考文档 heading 未找到，跳过")
        return
    tbl = scanner.find_table_after(h, stop_at_next_heading_level=3)
    if tbl is None:
        logger.warning("1.3 参考文档表未找到，跳过")
        return
    # 组装行
    overview = (project.get("aspice", {}).get("swe2", {}) or {}).get("overview") or {}
    ref_docs = overview.get("ref_docs") or arch_sections.build_ref_docs_from_project(project)
    rows = []
    for i, d in enumerate(ref_docs, start=1):
        rows.append(
            [
                d.get("no") or f"[{i:02d}]",
                d.get("name", ""),
                d.get("version", ""),
                d.get("note", ""),
            ]
        )
    # 骨架表只有 3 列（NO./名称/版本），但 overview 可能带 4 列
    headers = len(tbl.findall(qn("w:tr"))[0].findall(qn("w:tc"))) if tbl.findall(qn("w:tr")) else 3
    rows = [r[:headers] for r in rows]
    _rebuild_table_rows(tbl, rows, keep_header=1)
    logger.info("1.3 参考文档表已填 %d 行", len(rows))


# ============================================================================
# 章节 2：术语定义 — 追加项目术语到现有表
# ============================================================================
def _append_terms(scanner: SkeletonScanner, project: dict) -> None:
    """2 术语定义表追加项目术语。

    骨架表头 ('缩写和术语', '定义')，已有 5 行（4 行定稿术语 + 1 行表头）。
    追加 swe3.overview.terms 的项目术语，不动已有行。
    """
    h = scanner.find_heading(level=2, title_contains="术语定义")
    if h is None:
        logger.warning("2 术语定义 heading 未找到")
        return
    tbl = scanner.find_table_after(h, stop_at_next_heading_level=2)
    if tbl is None:
        logger.warning("2 术语定义表未找到")
        return
    overview = (project.get("aspice", {}).get("swe2", {}) or {}).get("overview") or {}
    extra = overview.get("terms") or []
    # 过滤掉和骨架重复的
    existing = set()
    for tr in tbl.findall(qn("w:tr")):
        tcs = tr.findall(qn("w:tc"))
        if tcs:
            existing.add(_text_of_paragraph(tcs[0]).strip())
    rows = tbl.findall(qn("w:tr"))
    template_row = rows[-1] if rows else None
    added = 0
    for t in extra:
        term = (t.get("term") or "").strip()
        if not term or term in existing:
            continue
        new_tr = copy.deepcopy(template_row) if template_row is not None else etree.Element(qn("w:tr"))
        tcs = new_tr.findall(qn("w:tc"))
        if len(tcs) >= 2:
            _set_cell_text(tcs[0], term)
            _set_cell_text(tcs[1], t.get("definition", ""))
        tbl.append(new_tr)
        existing.add(term)
        added += 1
    logger.info("2 术语定义追加 %d 行", added)


# ============================================================================
# 章节 3：软件功能概述 — 3.2 功能模块图 + 映射表
# ============================================================================
def _fill_chapter_3_functional_overview(scanner: SkeletonScanner, project: dict) -> None:
    """3.1 功能概述段落 + 3.2 功能模块图（PlantUML PNG）+ 3.2 映射表。"""
    # 3.2 功能模块图：找 "模块构成" heading（骨架里 L3 title="模块构成"）
    h = scanner.find_heading(level=3, title_contains="模块构成")
    if h is None:
        logger.warning("3.2 模块构成 heading 未找到")
        return
    # 在 heading 之后插入 PlantUML 图
    src = arch_sections.DEFAULT_MODULE_DIAGRAM_PLANTUML
    png = _plantuml_to_png_bytes(src)
    if png:
        _insert_image_after(scanner, h, png, width_mm=140)
        logger.info("3.2 功能模块图已嵌入 (%.1f KB)", len(png) / 1024)
    else:
        scanner.insert_paragraph_after(h, "（功能模块图待渲染）")
        logger.warning("3.2 功能模块图渲染失败，写占位文字")
    # 映射表：骨架里有一张 7 列映射表（SWE.1/需求描述/SWE.2/组件/SWE.3/模块/设计 ID），
    # 签名是 ('SWE.1', '需求描述', 'SWE.2', ...)。遍历 swe1/swe2/swe3 聚合。
    # 当前骨架只放了 1 行表头，追加数据行即可。
    _fill_chapter_3_mapping_table(scanner, project)


def _fill_chapter_3_mapping_table(scanner: SkeletonScanner, project: dict) -> None:
    """3.2 的 SWE.1×SWE.2×SWE.3 映射表。"""
    # 骨架表头前三列：('SWE.1', '需求描述', 'SWE.2', ...)
    h = scanner.find_heading(level=3, title_contains="模块构成")
    if h is None:
        return
    # 找锚点之后、下一个 L2 heading 之前的表
    tbl = scanner.find_table_after(h, stop_at_next_heading_level=2)
    if tbl is None:
        logger.warning("3.2 映射表未找到")
        return
    aspice = project.get("aspice", {}) or {}
    swe1 = aspice.get("swe1", {}) or {}
    swe2 = aspice.get("swe2", {}) or {}
    swe3 = aspice.get("swe3", {}) or {}
    # swe1.items: list of {req_id, description, ...}
    swe1_items = swe1.get("items") or []
    # swe2.mappings: [{req_id, component_id, ...}]
    swe2_maps = swe2.get("mappings") or []
    components = {c["id"]: c for c in (swe2.get("components") or [])}
    modules = _normalize_modules(swe3.get("modules"))
    rows = []
    # 针对每个 req_id，找 swe2 组件，找 swe3 模块，产出 1~N 行
    req_desc = {r.get("req_id"): r.get("description", "") for r in swe1_items}
    for m in swe2_maps:
        rid = m.get("req_id", "")
        cid = m.get("component_id", "")
        comp = components.get(cid, {}) or {}
        comp_name = comp.get("name", cid)
        # SWE.3 侧：模块 ID → 模块 name
        mod = modules.get(cid, {}) or {}
        mod_name = mod.get("name") or arch_sections.MODULE_SHORT.get(cid, "")
        # 设计 ID: 聚合取第一个类 / 函数的 D-id（若已生成），否则留空
        did = ""
        if mod.get("classes"):
            did = (mod["classes"][0] or {}).get("design_id", "") or ""
        rows.append([rid, req_desc.get(rid, ""), cid, comp_name, cid, mod_name, did])
    # 空行时也写一条占位，提醒用户映射未配置
    if not rows:
        rows = [["", "（映射数据待 SWE.2 填充）", "", "", "", "", ""]]
    # 适配骨架表的列数
    rows0 = tbl.findall(qn("w:tr"))
    cols = len(rows0[0].findall(qn("w:tc"))) if rows0 else 7
    rows = [r[:cols] + [""] * max(0, cols - len(r)) for r in rows]
    _rebuild_table_rows(tbl, rows, keep_header=1)
    logger.info("3.2 映射表已填 %d 行", len(rows))


# ============================================================================
# H3：模块区块（样板捕获 / 克隆 / 填充）
# ============================================================================
# 骨架里 Serializer 模块那段（body[93..123) ）包含了所有子节的样板：
#   类图 / 类列表表 / 类子节(常量/变量) / 函数列表表 / 函数详情表(B格式) /
#   原始NV函数列表 / 单元时序图
# 复用策略：
#   1. 首次扫描时抓取 Serializer 区块的"节点序列"做深拷贝模板
#   2. 清掉骨架里除 Serializer heading(L2)之外的所有 4~11 章样板节点
#   3. 按 MODULE_ORDER 为 8 个模块每个克隆一份，边克隆边填充真实数据


_PLACEHOLDER_FN_RE = re.compile(r"^Fn\d+$", re.IGNORECASE)


def _extract_identifier_from_decl(decl: str) -> str:
    """从函数 declaration 里提取函数名标识符。

    形如 'SIPLStatus GetMax96717FErrorInfo(...)' -> 'GetMax96717FErrorInfo'
    拿不到合法 identifier 返回 ''.
    """
    if not decl:
        return ""
    s = str(decl).strip()
    if "(" in s:
        s = s.split("(", 1)[0].strip()
    tokens = s.split()
    if not tokens:
        return ""
    name = tokens[-1].lstrip("*&").strip()
    # 必须是合法 C/C++ identifier（不能是关键字、类型名等）
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        return name
    return ""


def _clean_fn_name(raw: str, fallback_decl: Optional[str] = None) -> str:
    """把 ProjectJson 里带 declaration 文本的 fn.name 清洗成纯函数名。

    真实数据：
      - 'NvMediaStatus\\nMAX96717FReadErrorStatus(\\nDevBlkCDIDevice *handle, ...)' -> 'MAX96717FReadErrorStatus'
      - 'setCameraFlip(uint8_t rotateAngle)' -> 'setCameraFlip'
      - 'Fn27' (占位) -> 尝试从 fallback_decl 提取，失败返回 ''
    """
    if not raw:
        return _extract_identifier_from_decl(fallback_decl) if fallback_decl else ""
    s = str(raw).strip()
    # 占位 name 'Fn27' 'FN9' -> 优先走 declaration
    if _PLACEHOLDER_FN_RE.match(s):
        alt = _extract_identifier_from_decl(fallback_decl) if fallback_decl else ""
        return alt or ""  # 返回空串，让上游走 func_{idx:03d}
    # 若带括号/换行，取括号前最后一个 token
    if "(" in s:
        s = s.split("(", 1)[0].strip()
    # 按空白拆，取最后一个 token（去掉返回类型前缀）
    tokens = s.split()
    name = tokens[-1] if tokens else s
    # 去掉前导 * / &（指针返回类型粘连的情况）
    name = name.lstrip("*&").strip()
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        return name
    # name 看着不像合法标识符，试一下 declaration
    alt = _extract_identifier_from_decl(fallback_decl) if fallback_decl else ""
    return alt or (name[:40] if name else "")


# 伪类判定：class_name 看起来是文件路径（含 '/' 和 .hpp/.cpp/.h/.hxx 扩展）
_FAKE_CLASS_PATH_RE = re.compile(r"\.(hpp|cpp|h|hxx|cc|c)(\s|$)", re.IGNORECASE)

# 数据生成器塞的"表头占位行"文本（见 nvsipl_camera 真实数据）
_FAKE_CLASS_HEADER_NAMES = {"类名", "设计 ID", "设计id", "designid", "name", "class name"}


def _is_path_row(c: dict) -> bool:
    """判断 class 项是否其实是"头文件/源文件路径"伪行（相邻的真实类上一行的路径）。"""
    nm = (c.get("class_name") or c.get("name") or "").strip()
    if not nm:
        return False
    # 真实类名以 Class / Interface / Struct / Union 开头或为单驼峰标识符
    if nm.startswith(("Class ", "Interface ", "Struct ", "Union ", "Enum ")):
        return False
    # 看起来像路径
    if "/" in nm and _FAKE_CLASS_PATH_RE.search(nm + " "):
        return True
    return False


def _is_header_row(c: dict) -> bool:
    """判断 class 项是否为数据生成器塞入的"表头占位行"（class_name == '类名' 等）。"""
    nm = (c.get("class_name") or c.get("name") or "").strip().lower()
    return nm in _FAKE_CLASS_HEADER_NAMES or nm == "类名"


def _coalesce_class_list(raw_classes: list[dict]) -> list[dict]:
    """把"类名 + 路径 + 类名 + 路径..."的交错 classes 合并为"类（含路径到 source_files）"列表。

    真实数据样例（同 index）：
      [{class_name: 'Class CNvMDevice', description: '通用设备的基类'},
       {class_name: 'devblk/common/ddi/CNvMDevice.hpp', description: '同左'},
       {class_name: 'Class CNvMDeserializer', description: '封装反序列化'},
       ...]
    合并后：
      [{class_name:'Class CNvMDevice', description:'通用设备的基类',
        source_files:['devblk/common/ddi/CNvMDevice.hpp']}, ...]
    """
    merged: list[dict] = []
    for c in raw_classes or []:
        if _is_header_row(c):
            # 数据生成器塞入的表头占位行，直接丢弃
            continue
        if _is_path_row(c) and merged:
            # 合并到上一个真实类
            nm = (c.get("class_name") or c.get("name") or "").strip()
            # 可能是多行路径（.hpp\n.cpp），按行拆
            paths = [p.strip() for p in re.split(r"[\n;,]+", nm) if p.strip()]
            prev = merged[-1]
            prev.setdefault("source_files", []).extend(paths)
        else:
            merged.append(dict(c))
    return merged


def _module_host_short(module: dict, fallback: str) -> str:
    """从模块的 classes 里挑一个"宿主短名"（类名/型号），用于设计 ID 的 host 位。

    会跳过"路径伪行"，并把 'Class XxxYyy' 剥成 'XxxYyy'。
    """
    cls = module.get("classes") or []
    for c in cls:
        if _is_path_row(c):
            continue
        name = (c.get("name") or c.get("class_name") or "").strip()
        if name:
            # 剥掉 'Class ' / 'Interface ' 前缀
            for prefix in ("Class ", "Interface ", "Struct ", "Union ", "Enum "):
                if name.startswith(prefix):
                    name = name[len(prefix):].strip()
                    break
            return name or fallback
    return fallback


def _list_functions(cls: dict) -> list[dict]:
    """从类里统一拿函数列表（兼容 focus_functions / functions 两种字段）。"""
    return (cls.get("focus_functions") or cls.get("functions") or [])


# ----------------------------------------------------------------------------
# H3b：单模块 in-place 填充（对应骨架 body[93..122] 的 Serializer 章）
# ----------------------------------------------------------------------------
def _collect_module_block(scanner: SkeletonScanner, module_l2_title_contains: str) -> dict:
    """抓取新骨架模块章节的"节点地标"（无 L4 Class / L5 函数样板）。

    新模板结构：
      L2 模块XXX详细设计
        L3 类图
        L3 类列表            → 表(序号/设计 ID/类名/说明)
        L3 XXX详细设计       → L4 函数列表 → 表(设计ID/函数名/说明)
                             → L4 原始NV函数列表 → 表(设计ID/函数名/说明)
        L3 XXX单元时序图

    返回 dict 只含：l2_heading / l3_class_diagram / l3_class_list /
      tbl_class_list / l3_subdevice / l4_fn_list / tbl_fn_list /
      l4_nv_list / tbl_nv_list / l3_sequence
    """
    from app.core.arch_skeleton_scanner import _heading_level as _hl

    body = scanner.doc.element.body
    l2 = scanner.find_heading(level=2, title_contains=module_l2_title_contains)
    if l2 is None:
        return {}
    si = list(body).index(l2)
    # 下一个 L2 heading 的位置
    ei = len(body)
    for i in range(si + 1, len(body)):
        c = body[i]
        if c.tag == qn("w:p") and _hl(c) == 2:
            ei = i
            break

    out: dict = {"l2_heading": l2, "_start": si, "_end": ei}
    seg = list(body)[si + 1 : ei]
    for e in seg:
        if e.tag == qn("w:p"):
            lvl = _hl(e)
            txt = _text_of_paragraph(e).strip()
            if lvl == 3:
                if txt == "类图":
                    out["l3_class_diagram"] = e
                elif txt == "类列表":
                    out["l3_class_list"] = e
                elif "单元时序图" in txt or "时序图" in txt:
                    out["l3_sequence"] = e
                elif "详细设计" in txt:
                    out["l3_subdevice"] = e
            elif lvl == 4:
                if txt == "函数列表":
                    out["l4_fn_list"] = e
                elif "原始NV" in txt:
                    out["l4_nv_list"] = e
        elif e.tag == qn("w:tbl"):
            hdrs = tuple(h.strip() for h in _table_headers_safe(e))
            if hdrs[:3] == ("序号", "设计 ID", "类名") or hdrs[:3] == ("序号", "设计ID", "类名"):
                out["tbl_class_list"] = e
            elif hdrs[:3] == ("设计ID", "函数名", "说明") or hdrs[:3] == ("设计 ID", "函数名", "说明"):
                # 第一张 = 函数列表，第二张 = 原始 NV
                if "tbl_fn_list" not in out:
                    out["tbl_fn_list"] = e
                else:
                    out["tbl_nv_list"] = e
    return out


def _table_headers_safe(tbl_elem) -> tuple[str, ...]:
    from app.core.arch_skeleton_scanner import _table_headers
    return _table_headers(tbl_elem)


def _fill_class_list_table(tbl, classes: list[dict], mod_idx: int, mod_short: str) -> None:
    """填充"类列表表" (序号/设计 ID/类名/说明)，动态扩行。

    classes 已由 `_coalesce_class_list` 预处理，源文件路径归并到 c["source_files"]，
    说明列 = description +（可选）\\n源文件: path1; path2。
    """
    rows = []
    for i, c in enumerate(classes, start=1):
        design_id = c.get("design_id") or arch_sections.build_design_id(mod_idx, mod_short, "class", i)
        cname = (c.get("class_name") or c.get("name") or f"Class{i}").strip()
        desc = (c.get("description") or c.get("desc") or "").strip()
        src_files = c.get("source_files") or []
        if src_files:
            path_str = "; ".join(src_files)
            desc = f"{desc}\n源文件：{path_str}" if desc else f"源文件：{path_str}"
        rows.append([str(i), design_id, cname, desc])
    if not rows:
        rows = [["", "", "（本模块暂无类）", ""]]
    _rebuild_table_rows(tbl, rows, keep_header=1)
    _apply_class_table_col_widths(tbl)


# 类列表表列宽（twips）: 序号 800 / 设计 ID 2500 / 类名 3200 / 说明 剩余
_W_CLASS_LIST_4 = [800, 2500, 3200, 3000]


def _apply_class_table_col_widths(tbl) -> None:
    """强制给"类列表"表设定列宽（tblGrid + 每行 tcW），防止说明列把类名列挤成折行。"""
    try:
        # 1) 替换 w:tblGrid
        tblGrid = tbl.find(qn("w:tblGrid"))
        if tblGrid is not None:
            tbl.remove(tblGrid)
        tblGrid = etree.SubElement(tbl, qn("w:tblGrid"))
        for w in _W_CLASS_LIST_4:
            gc = etree.SubElement(tblGrid, qn("w:gridCol"))
            gc.set(qn("w:w"), str(w))
        # tblGrid 必须排在 w:tr 之前，重排一下
        tbl.remove(tblGrid)
        # 找到第一个 w:tr 的位置
        first_tr = tbl.find(qn("w:tr"))
        if first_tr is not None:
            first_tr.addprevious(tblGrid)
        else:
            tbl.append(tblGrid)
        # 2) 每行每个 tc 的 tcW
        for tr in tbl.findall(qn("w:tr")):
            tcs = tr.findall(qn("w:tc"))
            for i, tc in enumerate(tcs):
                if i >= len(_W_CLASS_LIST_4):
                    break
                tcPr = tc.find(qn("w:tcPr"))
                if tcPr is None:
                    tcPr = etree.Element(qn("w:tcPr"))
                    tc.insert(0, tcPr)
                tcW = tcPr.find(qn("w:tcW"))
                if tcW is None:
                    tcW = etree.SubElement(tcPr, qn("w:tcW"))
                tcW.set(qn("w:w"), str(_W_CLASS_LIST_4[i]))
                tcW.set(qn("w:type"), "dxa")
        # 3) 表格自身 tblW 设成固定（或 pct 100）避免整表被撑开
        tblPr = tbl.find(qn("w:tblPr"))
        if tblPr is not None:
            tblW = tblPr.find(qn("w:tblW"))
            if tblW is None:
                tblW = etree.SubElement(tblPr, qn("w:tblW"))
            tblW.set(qn("w:w"), str(sum(_W_CLASS_LIST_4)))
            tblW.set(qn("w:type"), "dxa")
            # tblLayout = fixed 防自动等宽
            tblLayout = tblPr.find(qn("w:tblLayout"))
            if tblLayout is None:
                tblLayout = etree.SubElement(tblPr, qn("w:tblLayout"))
            tblLayout.set(qn("w:type"), "fixed")
    except Exception as e:
        logger.warning("_apply_class_table_col_widths failed: %s", e)


def _fill_const_or_var_table(tbl, items: list[dict], kind: str) -> None:
    """kind: 'const' (5 列 序号/常量/类型/值/说明) | 'var' (4 列 序号/变量/类型/说明)."""
    rows = []
    for i, it in enumerate(items or [], start=1):
        name = it.get("name") or ""
        typ = it.get("type") or ""
        desc = it.get("desc") or it.get("description") or ""
        if kind == "const":
            val = it.get("value") or ""
            rows.append([str(i), name, typ, val, desc])
        else:
            rows.append([str(i), name, typ, desc])
    if not rows:
        rows = [["", "（无）", "", "", ""]] if kind == "const" else [["", "（无）", "", ""]]
    _rebuild_table_rows(tbl, rows, keep_header=1)


def _fill_fn_list_table(tbl, funcs: list[dict], mod_idx: int, host_short: str, *, force_na_design_id: bool = False) -> None:
    """填充函数列表表 (设计ID/函数名/说明).

    占位函数（Fn\\d+ 且无 declaration）函数名显示 "xxx（待补充）"，说明列同样。
    force_na_design_id=True 时，设计 ID 列一律写 "N/A"（用于 NV 原始 SDK 函数表，
    这类函数不是我方设计产物，不给 D-id）。
    """
    rows = []
    for i, f in enumerate(funcs or [], start=1):
        if force_na_design_id:
            did = "N/A"
        else:
            did = f.get("design_id") or arch_sections.build_design_id(mod_idx, host_short, "function", i)
        if _is_placeholder_fn(f):
            fname = _PLACEHOLDER_TEXT
            intro = _PLACEHOLDER_TEXT
        else:
            fname = _clean_fn_name(
                f.get("name") or f.get("func_name") or "",
                fallback_decl=f.get("declaration"),
            ) or _PLACEHOLDER_TEXT
            intro = (f.get("intro") or f.get("brief") or f.get("description") or "").strip()
            if not intro:
                # intro 空时回落到"返回类型 + 函数名(参数概要)"，让说明列至少能看懂签名
                decl = (f.get("declaration") or "").strip()
                intro = _brief_from_declaration(decl) if decl else _PLACEHOLDER_TEXT
        rows.append([did, fname, intro])
    if not rows:
        rows = [["", "（无函数）", ""]]
    _rebuild_table_rows(tbl, rows, keep_header=1)


# ============================================================================
# 新：代码自动构造 L4 Class 子节 / L5 函数子节 / B 格式函数详情表
# 不再依赖骨架里任何 L4/L5 样板节点，纯 lxml + python-docx 构造
# ============================================================================


def _new_heading(level: int, text: str):
    """构造一个 Heading<level> 段落（样式名用骨架里见到的裸数字，如 "4"/"5"）。"""
    p = etree.Element(qn("w:p"))
    pPr = etree.SubElement(p, qn("w:pPr"))
    pStyle = etree.SubElement(pPr, qn("w:pStyle"))
    pStyle.set(qn("w:val"), str(level))
    r = etree.SubElement(p, qn("w:r"))
    t = etree.SubElement(r, qn("w:t"))
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = text
    return p


def _new_para(text: str, style: Optional[str] = None):
    """普通段落。"""
    return _make_p(text, style=style)


def _mk_tc(text: str, width_twips: Optional[int] = None, gridspan: Optional[int] = None):
    """构造一个 <w:tc>（单元格）：段落里放 text；可选宽度 / 水平合并数."""
    tc = etree.Element(qn("w:tc"))
    tcPr = etree.SubElement(tc, qn("w:tcPr"))
    if width_twips is not None:
        tcW = etree.SubElement(tcPr, qn("w:tcW"))
        tcW.set(qn("w:w"), str(width_twips))
        tcW.set(qn("w:type"), "dxa")
    if gridspan and gridspan > 1:
        gs = etree.SubElement(tcPr, qn("w:gridSpan"))
        gs.set(qn("w:val"), str(gridspan))
    # 加个默认边框
    tcBorders = etree.SubElement(tcPr, qn("w:tcBorders"))
    for side in ("top", "left", "bottom", "right"):
        b = etree.SubElement(tcBorders, qn(f"w:{side}"))
        b.set(qn("w:val"), "single")
        b.set(qn("w:sz"), "4")
        b.set(qn("w:color"), "auto")
    # 段落
    p = etree.SubElement(tc, qn("w:p"))
    if text:
        r = etree.SubElement(p, qn("w:r"))
        t = etree.SubElement(r, qn("w:t"))
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = str(text)
    return tc


def _mk_tr(cells: list):
    """构造一行 <w:tr>，cells 是预构造好的 <w:tc> 列表."""
    tr = etree.Element(qn("w:tr"))
    for tc in cells:
        tr.append(tc)
    return tr


def _mk_table(col_widths_twips: list[int], rows: list[list] = None, header_shading: bool = True):
    """构造一张 <w:tbl> 元素。

    - col_widths_twips: 每列宽度（twips），长度 = 列数
    - rows: list[list[str | dict]]；dict 支持 {text, gridspan, shd}
    - header_shading: 是否给第 1 行加浅灰底色
    """
    tbl = etree.Element(qn("w:tbl"))
    # tblPr
    tblPr = etree.SubElement(tbl, qn("w:tblPr"))
    tblW = etree.SubElement(tblPr, qn("w:tblW"))
    tblW.set(qn("w:w"), str(sum(col_widths_twips)))
    tblW.set(qn("w:type"), "dxa")
    # 全表边框
    tblBorders = etree.SubElement(tblPr, qn("w:tblBorders"))
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        b = etree.SubElement(tblBorders, qn(f"w:{side}"))
        b.set(qn("w:val"), "single")
        b.set(qn("w:sz"), "4")
        b.set(qn("w:color"), "auto")
    # tblGrid
    tblGrid = etree.SubElement(tbl, qn("w:tblGrid"))
    for w in col_widths_twips:
        g = etree.SubElement(tblGrid, qn("w:gridCol"))
        g.set(qn("w:w"), str(w))

    for ri, row in enumerate(rows or []):
        tcs = []
        col_i = 0
        for cell in row:
            if isinstance(cell, dict):
                text = cell.get("text", "")
                gridspan = cell.get("gridspan", 1)
                shd = cell.get("shd")
            else:
                text = cell
                gridspan = 1
                shd = None
            # 单元格宽 = 合并列宽之和
            width = sum(col_widths_twips[col_i : col_i + gridspan]) if col_i + gridspan <= len(col_widths_twips) else None
            tc = _mk_tc(text, width_twips=width, gridspan=gridspan)
            if shd is None and ri == 0 and header_shading:
                shd = "E7E6E6"
            if shd:
                tcPr = tc.find(qn("w:tcPr"))
                shd_el = etree.SubElement(tcPr, qn("w:shd"))
                shd_el.set(qn("w:val"), "clear")
                shd_el.set(qn("w:color"), "auto")
                shd_el.set(qn("w:fill"), shd)
            tcs.append(tc)
            col_i += gridspan
        tbl.append(_mk_tr(tcs))
    return tbl


# 常用列宽（twips；A4 可用宽约 9300 twips）
_W_FN_DECL = [1800, 7500]           # 函数声明/介绍 — 2 列
_W_PARAM_3 = [2800, 2000, 4500]     # Parameter | Type | 说明
_W_FLOW_1 = [9300]                  # 流程图行（单列）
_W_CONST_5 = [900, 2400, 1800, 1700, 2500]  # 序号/常量名/类型/值/说明
_W_VAR_4 = [900, 2800, 1800, 3800]  # 序号/变量名/类型/说明


_PLACEHOLDER_TEXT = "xxx（待补充）"


def _is_placeholder_fn(fn: dict) -> bool:
    """判断函数是否为"占位函数"（AI/扫描未识别到真实签名）。

    判据：name 匹配 ^Fn\\d+$ 且 declaration 为空/无合法标识符。
    """
    raw_name = str(fn.get("name") or fn.get("func_name") or "").strip()
    if not _PLACEHOLDER_FN_RE.match(raw_name):
        return False
    decl = str(fn.get("declaration") or "").strip()
    return not _extract_identifier_from_decl(decl)


def _brief_from_declaration(decl: str) -> str:
    """没有 doc_comment / ai_intro 时，从函数签名摘一句简短描述给"说明"列。

    形如：
      "static NvMediaStatus DriverCreateM24C04(DevBlkCDIDevice *handle, void const *clientContext)"
      →  "返回 NvMediaStatus；参数 handle, clientContext"
    失败则返回空串，由调用方决定是否补占位。
    """
    import re as _re
    decl = _re.sub(r"\s+", " ", decl).strip()
    # 抓括号内参数
    m = _re.search(r"\(([^)]*)\)", decl)
    params_str = (m.group(1) if m else "").strip()
    # 抓签名前半部分（返回类型 + 函数名前面）
    head = decl[: m.start()] if m else decl
    # 去掉修饰词
    for kw in ("virtual ", "static ", "inline ", "explicit ", "constexpr ", "extern "):
        head = head.replace(kw, "")
    head = head.strip()
    # 最后一个 token = 函数名，前面是返回类型
    tokens = head.rsplit(" ", 1)
    ret_type = tokens[0].strip() if len(tokens) == 2 else ""
    ret_type = ret_type.replace(" *", "*").replace(" &", "&")
    # 参数名提取
    pnames = []
    if params_str and params_str != "void":
        for seg in params_str.split(","):
            seg = seg.strip()
            if not seg:
                continue
            # 取最后一个标识符作参数名
            mp = _re.search(r"([A-Za-z_]\w*)\s*$", seg.rstrip("*&[]0123456789 "))
            if mp:
                pnames.append(mp.group(1))
    parts = []
    if ret_type and ret_type != "void":
        parts.append(f"返回 {ret_type}")
    if pnames:
        parts.append("参数 " + ", ".join(pnames))
    elif params_str.strip() in ("", "void"):
        parts.append("无参")
    return "；".join(parts) if parts else ""


def _build_fn_detail_table(fn: dict):
    """按 B 格式从零构造函数详情表（非克隆）。

    行序：
      r0  函数声明 | <declaration>
      r1  函数介绍 | <intro>
      r2  Parameter | Type | 说明         （表头底色）
      r3+ 参数行 (N 行)
      rN+1 返回值 | Type | 说明            （表头底色）
      rN+2 返回值数据
      末   函数流程图（合并单元格，底色）
      末+1 流程图占位行（空行供后续插入 PNG）

    占位函数（无真实签名）统一填充 "xxx（待补充）"，不编造参数/返回值。
    """
    is_placeholder = _is_placeholder_fn(fn)

    if is_placeholder:
        decl = _PLACEHOLDER_TEXT
        intro = _PLACEHOLDER_TEXT
        params = [{"name": _PLACEHOLDER_TEXT, "type": "-", "desc": "-"}]
        returns = [{"name": _PLACEHOLDER_TEXT, "type": "-", "desc": "-"}]
    else:
        decl = fn.get("declaration") or _PLACEHOLDER_TEXT
        intro = fn.get("intro") or fn.get("brief") or fn.get("description") or _PLACEHOLDER_TEXT
        params = fn.get("parameters") or fn.get("params") or []
        if not params:
            params = [{"name": "void", "type": "-", "desc": "-"}]
        returns = fn.get("returns") or fn.get("return_values") or []
        if not returns:
            ret_type = fn.get("return_type") or "void"
            returns = [{"name": "returnValue", "type": ret_type, "desc": "-"}]

    rows: list[list] = []
    # 函数声明 / 介绍：第一列带底色，第二列全宽合并（Parameter 表 3 列，所以这里用 3 列表格并 gridspan=2）
    # 为了表格对齐，整个详情表用 3 列（匹配 Parameter 表）
    cw = _W_PARAM_3  # 3 列
    rows.append([{"text": "函数声明", "shd": "E7E6E6"},
                 {"text": decl, "gridspan": 2}])
    rows.append([{"text": "函数介绍", "shd": "E7E6E6"},
                 {"text": intro, "gridspan": 2}])
    rows.append([{"text": "Parameter", "shd": "E7E6E6"},
                 {"text": "Type", "shd": "E7E6E6"},
                 {"text": "说明", "shd": "E7E6E6"}])
    for p in params:
        rows.append([p.get("name") or "",
                     p.get("type") or "",
                     p.get("desc") or p.get("description") or "-"])
    rows.append([{"text": "返回值", "shd": "E7E6E6"},
                 {"text": "Type", "shd": "E7E6E6"},
                 {"text": "说明", "shd": "E7E6E6"}])
    for r in returns:
        rows.append([r.get("name") or "",
                     r.get("type") or "",
                     r.get("desc") or r.get("description") or "-"])
    # 流程图标题行（合并 3 列）
    rows.append([{"text": "函数流程图", "gridspan": 3, "shd": "E7E6E6"}])
    # 流程图占位行（PNG 由 _render_module_block 插入该单元格内）
    rows.append([{"text": "", "gridspan": 3}])

    return _mk_table(cw, rows=rows, header_shading=False)


def _set_cell_text_in_paragraph(p_elem, text: str) -> None:
    """把 <w:p> 的所有 run 清空后写一段新文字（保留 pPr/样式）。"""
    for child in list(p_elem):
        if child.tag != qn("w:pPr"):
            p_elem.remove(child)
    r = etree.SubElement(p_elem, qn("w:r"))
    t = etree.SubElement(r, qn("w:t"))
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = text


def _is_heading_or_structural(elem) -> bool:
    """判断一个 body 子节点是否为"结构性节点"（heading / 表 / 已插入的 L3 占位段）。

    非结构性的裸文本段将被 `_clear_orphan_paragraphs` 清理。
    """
    if elem.tag == qn("w:tbl"):
        return True
    if elem.tag != qn("w:p"):
        return True  # 其他（w:sectPr 等）保留
    pPr = elem.find(qn("w:pPr"))
    if pPr is not None:
        pStyle = pPr.find(qn("w:pStyle"))
        if pStyle is not None:
            v = pStyle.get(qn("w:val")) or ""
            # 任何 heading（裸数字 1-9 或 "Heading N"）都算结构
            if v.isdigit() and 1 <= int(v) <= 9:
                return True
            if v.lower().startswith("heading") or v.startswith("标题"):
                return True
    return False


def _remove_following_text_paragraphs(anchor_elem, keywords: tuple, max_scan: int = 3) -> int:
    """从 anchor_elem 之后最多扫 max_scan 段（遇 heading/table 停），删掉文本包含任一 keyword 的裸段。

    返回删除个数。用于 manual_only 分支：先清掉模板原有的"（本模块暂无...）"占位，
    再插入"（本模块内容由人工维护）"，避免叠加出现。
    """
    removed = 0
    cur = anchor_elem
    scanned = 0
    while scanned < max_scan:
        nxt = cur.getnext()
        if nxt is None:
            break
        if nxt.tag == qn("w:tbl"):
            break
        if nxt.tag != qn("w:p"):
            cur = nxt
            scanned += 1
            continue
        pPr = nxt.find(qn("w:pPr"))
        if pPr is not None:
            ps = pPr.find(qn("w:pStyle"))
            if ps is not None:
                v = ps.get(qn("w:val")) or ""
                if v.isdigit() and 1 <= int(v) <= 9:
                    break
        txt = "".join(t.text or "" for t in nxt.iter(qn("w:t"))).strip()
        if any(k in txt for k in keywords):
            parent = nxt.getparent()
            if parent is not None:
                parent.remove(nxt)
                removed += 1
                # 不前进 cur，继续从同一 anchor 看下一个
                scanned += 1
                continue
        cur = nxt
        scanned += 1
    return removed


def _has_following_placeholder(anchor_elem, keyword: str, max_lookahead: int = 3) -> bool:
    """检查 anchor_elem 之后 max_lookahead 段范围内是否已有含 keyword 的段。

    用于避免在模板原有占位（如"（本模块暂无类图）"）之上重复插入。
    """
    cur = anchor_elem
    for _ in range(max_lookahead):
        cur = cur.getnext()
        if cur is None:
            return False
        if cur.tag != qn("w:p"):
            # 遇到表则认为模板已给出内容，不再插占位
            if cur.tag == qn("w:tbl"):
                return True
            continue
        txt = "".join(t.text or "" for t in cur.iter(qn("w:t"))).strip()
        if keyword in txt:
            return True
        # 遇到 heading 则结束
        pPr = cur.find(qn("w:pPr"))
        if pPr is not None:
            ps = pPr.find(qn("w:pStyle"))
            if ps is not None:
                v = ps.get(qn("w:val")) or ""
                if v.isdigit() and 1 <= int(v) <= 9:
                    return False
    return False


def _clear_orphan_paragraphs(scanner, l2_heading_elem, aggressive: bool = True) -> None:
    """清掉从 l2_heading_elem 之后到下一个 L2 heading 之前的所有"裸文本段"。

    - aggressive=True（默认，用于 manual_only 模块）：清所有裸段落
    - aggressive=False（用于正常模块）：只清模板遗留的说明性段落
      （以 "注：" / "注:" / "本模块" 开头、或含 "MAX96717" 等型号残留）

    保留规则：
      - 任何 heading（任意 level）
      - 任何表
      - 空段（保留空行间隔）
      - "由人工维护" / "本模块暂无" 开头的段落（本次刚插入的占位）
    """
    body = scanner.doc.element.body
    children = list(body)
    try:
        start_idx = children.index(l2_heading_elem)
    except ValueError:
        return
    # 找下一个 L2 heading
    end_idx = len(children)
    for j in range(start_idx + 1, len(children)):
        c = children[j]
        if c.tag == qn("w:p"):
            pPr = c.find(qn("w:pPr"))
            if pPr is not None:
                ps = pPr.find(qn("w:pStyle"))
                if ps is not None:
                    v = ps.get(qn("w:val")) or ""
                    if v.isdigit() and int(v) <= 2 and j > start_idx:
                        end_idx = j
                        break
    # 扫描区间内的裸段落，按策略移除
    to_remove = []
    for j in range(start_idx + 1, end_idx):
        c = children[j]
        # aggressive 模式还要清掉"列头空"的孤儿表（模板里残留的样板空表）
        if aggressive and c.tag == qn("w:tbl"):
            from app.core.arch_skeleton_scanner import _table_headers as _th
            hdrs = _th(c)
            if not hdrs or all(not h.strip() for h in hdrs):
                to_remove.append(c)
            continue
        if _is_heading_or_structural(c):
            continue
        if c.tag != qn("w:p"):
            continue
        txt = "".join(t.text or "" for t in c.iter(qn("w:t"))).strip()
        if not txt:
            continue  # 空段保留
        # 保留本次插入的占位（含"由人工维护""暂无"字样）
        if "由人工维护" in txt or "暂无" in txt:
            continue
        if aggressive:
            to_remove.append(c)
        else:
            # 仅清理模板残留的"注：..."说明段
            # （典型如模板里的 '注：MAX96717F...不做设计说明'
            #   或 'MAX96717FReadRegisters...等原始 NV 接口未做业务逻辑修改,不在本文档中展开设计说明'）
            if (txt.startswith(("注：", "注:"))
                or "不做设计说明" in txt
                or "未做修改" in txt
                or "未做业务逻辑修改" in txt
                or "不在本文档中展开" in txt
                or ("MAX96" in txt and ("原始" in txt or "NV" in txt))):
                to_remove.append(c)
    for c in to_remove:
        parent = c.getparent()
        if parent is not None:
            parent.remove(c)


def _build_class_subsection(
    class_item: dict,
    mod_idx: int,
    mod_short: str,
    class_idx: int,
) -> list:
    """为一个 class 构造 L4/L5 节点序列（返回 lxml element 列表）。

    [ L4 "Class <name>",
      段 "[D001-Serializer-class-001]",
      L5 "类的成员常量列表", const 表(5列),
      L5 "类的成员变量列表", var 表(4列) ]
    """
    cname = class_item.get("class_name") or class_item.get("name") or f"Class{class_idx}"
    design_id = class_item.get("design_id") or arch_sections.build_design_id(mod_idx, mod_short, "class", class_idx)
    const_items = class_item.get("member_constants") or class_item.get("constants") or []
    var_items = class_item.get("member_variables") or class_item.get("members") or class_item.get("variables") or []

    nodes: list = []
    l4_title = cname if cname.lower().startswith("class") else f"Class {cname}"
    nodes.append(_new_heading(4, l4_title))
    nodes.append(_new_para(f"[{design_id}]"))
    # 常量
    nodes.append(_new_heading(5, "类的成员常量列表"))
    const_rows = []
    for i, it in enumerate(const_items, start=1):
        const_rows.append([
            str(i),
            it.get("name") or "",
            it.get("type") or "",
            it.get("value") or "",
            it.get("desc") or it.get("description") or "",
        ])
    if not const_rows:
        const_rows = [["", "（无）", "", "", ""]]
    nodes.append(_mk_table(
        _W_CONST_5,
        rows=[["序号", "常量名", "类型", "值", "说明"]] + const_rows,
    ))
    # 变量
    nodes.append(_new_heading(5, "类的成员变量列表"))
    var_rows = []
    for i, it in enumerate(var_items, start=1):
        var_rows.append([
            str(i),
            it.get("name") or "",
            it.get("type") or "",
            it.get("desc") or it.get("description") or "",
        ])
    if not var_rows:
        var_rows = [["", "（无）", "", ""]]
    nodes.append(_mk_table(
        _W_VAR_4,
        rows=[["序号", "变量名", "类型", "说明"]] + var_rows,
    ))
    return nodes


def _build_function_subsection(
    fn: dict,
    mod_idx: int,
    host_short: str,
    fn_idx: int,
) -> list:
    """为一个函数构造 L5 节点序列：L5 标题 + designid 段 + B 格式详情表（不含流程图 PNG，由调用方插入）."""
    if _is_placeholder_fn(fn):
        fname = _PLACEHOLDER_TEXT
    else:
        fname = _clean_fn_name(
            fn.get("name") or fn.get("func_name") or "",
            fallback_decl=fn.get("declaration"),
        ) or _PLACEHOLDER_TEXT
    design_id = fn.get("design_id") or arch_sections.build_design_id(mod_idx, host_short, "function", fn_idx)
    nodes: list = []
    nodes.append(_new_heading(5, f"函数 {fname}"))
    nodes.append(_new_para(f"[{design_id}]"))
    nodes.append(_build_fn_detail_table(fn))
    return nodes


def _render_module_block(
    scanner: SkeletonScanner,
    mid: str,
    mod_idx: int,
    module: dict,
    block: dict,
    short_name: str = "",
    manual_only: bool = False,
) -> None:
    """对已定位到的模块区块做 in-place 填充。

    关键变化（vs 旧版）：
    - 不再依赖 L4 Class / L5 函数的骨架样板（新模板已删）
    - 类子节、函数详情子节全部用代码构造并插入到类列表表/函数列表表之后
    - manual_only=True：只填 L2/L3 骨架 + 占位，不插入 L4/L5（用于 CameraSecurity）
    """
    # 短名优先用章节配置传入的，fallback 从模块数据/MODULE_SHORT 推
    mod_short = short_name or arch_sections.MODULE_SHORT.get(mid, module.get("name") or "Mod")
    # 合并"路径伪行"到真实类里
    classes = _coalesce_class_list(module.get("classes") or [])
    # manual_only 时：host_short 直接用 short_name，不读真实数据里的类名（防被 A005 残留数据污染）
    if manual_only:
        host_short = mod_short
    else:
        host_short = _module_host_short({"classes": classes}, mod_short)

    # 1) L2 标题：改为真实模块名（保留样式）
    _set_cell_text_in_paragraph(block["l2_heading"], f"模块{mod_short}详细设计")

    # 预清理：移除模板里"注：...不做设计说明..."等残留提示段
    # （已经由我们自动构造或填充真实内容，不再需要这些模板提示）
    _clear_orphan_paragraphs(scanner, block["l2_heading"], aggressive=False)

    # —— manual_only：保留 L2/L3 章节骨架，清掉模板残留杂段，不自动构造 L4/L5 ——
    if manual_only:
        tbl_cls = block.get("tbl_class_list")
        if tbl_cls is not None:
            _rebuild_table_rows(
                tbl_cls,
                [["", "", "（本模块内容由人工维护）", ""]],
                keep_header=1,
            )
            _apply_class_table_col_widths(tbl_cls)
        tbl_fn_list = block.get("tbl_fn_list")
        if tbl_fn_list is not None:
            _rebuild_table_rows(
                tbl_fn_list,
                [["", "（本模块内容由人工维护）", ""]],
                keep_header=1,
            )
        tbl_nv = block.get("tbl_nv_list")
        if tbl_nv is not None:
            _rebuild_table_rows(
                tbl_nv,
                [["", "（本模块内容由人工维护）", ""]],
                keep_header=1,
            )
        l3_sub = block.get("l3_subdevice")
        if l3_sub is not None:
            _set_cell_text_in_paragraph(l3_sub, f"{mod_short}详细设计")
        l3_seq = block.get("l3_sequence")
        if l3_seq is not None:
            _set_cell_text_in_paragraph(l3_seq, f"{mod_short}单元时序图")
            # manual_only 下移除模板原有"暂无"占位，让"由人工维护"成为唯一说明
            _remove_following_text_paragraphs(l3_seq, keywords=("暂无",), max_scan=3)
            scanner.insert_paragraph_after(l3_seq, "（本模块内容由人工维护）")
        l3_class_diagram = block.get("l3_class_diagram")
        if l3_class_diagram is not None:
            # 移除模板原有的"（本模块暂无类图）"占位，再插入"（本模块内容由人工维护）"
            _remove_following_text_paragraphs(l3_class_diagram, keywords=("暂无",), max_scan=3)
            scanner.insert_paragraph_after(l3_class_diagram, "（本模块内容由人工维护）")
        # 清理 L2 到下一个 L2 之间的所有"孤儿段落"（非 L3/非表的注释/说明段）
        _clear_orphan_paragraphs(scanner, block["l2_heading"])
        return

    # 2) 类图 PNG（模板已带"暂无类图"占位，有 PNG 时覆盖，否则沿用模板原占位）
    l3_class_diagram = block.get("l3_class_diagram")
    if l3_class_diagram is not None:
        src = (module.get("class_diagram_plantuml") or "").strip()
        png = _plantuml_to_png_bytes(src) if src else None
        if png:
            _insert_image_after(scanner, l3_class_diagram, png, width_mm=140)
        elif src:
            # 有源码但渲染失败：精简提示，不贴长串 URL/异常
            scanner.insert_paragraph_after(l3_class_diagram, "（类图自动渲染失败）")
        elif not _has_following_placeholder(l3_class_diagram, "暂无"):
            scanner.insert_paragraph_after(l3_class_diagram, "（本模块暂无类图）")

    # 3) 类列表表
    tbl_cls = block.get("tbl_class_list")
    if tbl_cls is not None:
        _fill_class_list_table(tbl_cls, classes, mod_idx, mod_short)

    # 4) 类子节：代码构造 L4 Class + L5 常量/变量表，插到类列表表之后
    if classes:
        anchor = tbl_cls if tbl_cls is not None else block.get("l3_class_list")
        if anchor is not None:
            cur = anchor
            for idx, c in enumerate(classes, start=1):
                sub_nodes = _build_class_subsection(c, mod_idx, mod_short, idx)
                for n in sub_nodes:
                    cur.addnext(n)
                    cur = n

    # 5) 子设备详设 L3：替换为真实宿主短名
    l3_sub = block.get("l3_subdevice")
    if l3_sub is not None:
        _set_cell_text_in_paragraph(l3_sub, f"{host_short}详细设计")

    # 6) 聚合函数列表（类内 + 模块级），按 name 去重
    all_focus = []
    for c in classes:
        all_focus.extend(_list_functions(c))
    all_focus.extend(module.get("functions") or [])
    # 去重：name 相同的只保留第一个（bridge 已按文件去重，但类内和模块级可能重叠）
    _seen_names = set()
    _dedup = []
    for fn in all_focus:
        nm = (fn.get("name") or fn.get("func_name") or "").strip()
        if not nm:
            _dedup.append(fn); continue
        if nm in _seen_names:
            continue
        _seen_names.add(nm)
        _dedup.append(fn)
    all_focus = _dedup

    # 7) 函数列表表
    tbl_fn_list = block.get("tbl_fn_list")
    if tbl_fn_list is not None:
        _fill_fn_list_table(tbl_fn_list, all_focus, mod_idx, host_short)

    # 8) 函数详情子节：代码构造 L5 函数XXX + B 格式详情表 + 流程图 PNG，插到函数列表表之后
    if all_focus:
        anchor = tbl_fn_list if tbl_fn_list is not None else block.get("l4_fn_list")
        if anchor is not None:
            cur = anchor
            for idx, fn in enumerate(all_focus, start=1):
                sub_nodes = _build_function_subsection(fn, mod_idx, host_short, idx)
                for n in sub_nodes:
                    cur.addnext(n)
                    cur = n
                # 流程图 PNG（如有）：插到详情表的"函数流程图"占位单元格内
                # 复杂函数（is_complex=True）直接插"请手绘"提示，不生成 PNG
                tbl_elem = cur if cur.tag == qn("w:tbl") else None
                if fn.get("is_complex"):
                    if tbl_elem is not None:
                        body_lines = int(fn.get("body_lines") or 0)
                        _insert_text_into_table_cell(
                            scanner, tbl_elem,
                            f"（本函数体 {body_lines} 行，逻辑较复杂；AI 流程图已跳过，请手工绘制）",
                            row_index=-1, cell_index=0, italic=True,
                        )
                    continue
                src = (fn.get("flowchart_plantuml") or fn.get("ai_flowchart") or "").strip()
                if src:
                    png = _plantuml_to_png_bytes(src)
                    if png:
                        # cur 是刚插入的详情表元素（_build_function_subsection 的最后节点）
                        ok = False
                        if tbl_elem is not None:
                            ok = _insert_image_into_table_cell(
                                scanner, tbl_elem, png,
                                row_index=-1, cell_index=0, width_mm=140,
                            )
                        if not ok:
                            # 兜底：按旧行为插表后
                            _insert_image_after(scanner, cur, png, width_mm=140)
                            nxt = cur.getnext()
                            if nxt is not None:
                                cur = nxt
                    elif tbl_elem is not None:
                        # 渲染失败：留一句简短提示(不贴 URL,避免长串撑表格)
                        _insert_text_into_table_cell(
                            scanner, tbl_elem,
                            "（流程图自动渲染失败）",
                            row_index=-1, cell_index=0, italic=True,
                        )
                    continue  # 继续下一个 fn

    # 9) 原始 NV 函数表
    tbl_nv = block.get("tbl_nv_list")
    nv_funcs_raw = module.get("nv_original_functions") or []
    # 去重：name 相同只留一条（.cpp/.hpp 双份合并）
    _seen_nv = set()
    nv_funcs = []
    for fn in nv_funcs_raw:
        nm = (fn.get("name") or "").strip()
        if not nm:
            nv_funcs.append(fn); continue
        if nm in _seen_nv:
            continue
        _seen_nv.add(nm)
        nv_funcs.append(fn)
    if tbl_nv is not None:
        # NV 原始 SDK 函数：非我方设计产物，设计 ID 一律 N/A（R4 需求 #4）
        _fill_fn_list_table(tbl_nv, nv_funcs, mod_idx, host_short, force_na_design_id=True)

    # 10) 单元时序图 PNG
    l3_seq = block.get("l3_sequence")
    if l3_seq is not None:
        _set_cell_text_in_paragraph(l3_seq, f"{host_short}单元时序图")
        src = (module.get("sequence_plantuml") or "").strip()
        png = _plantuml_to_png_bytes(src) if src else None
        if png:
            _insert_image_after(scanner, l3_seq, png, width_mm=140)
        elif src:
            scanner.insert_paragraph_after(l3_seq, "（时序图自动渲染失败）")
        elif not _has_following_placeholder(l3_seq, "暂无"):
            scanner.insert_paragraph_after(l3_seq, "（本模块暂无时序图）")


def _render_module_chapter(
    scanner: SkeletonScanner,
    mid: str,
    mod_idx: int,
    module: dict,
    anchor_l2_title_contains: str,
    short_name: str = "",
    manual_only: bool = False,
) -> None:
    """对一个模块章节（已被 _collect_module_block 定位到的）做完整填充。"""
    block = _collect_module_block(scanner, anchor_l2_title_contains)
    if not block:
        logger.warning("模块章未定位到: %s", anchor_l2_title_contains)
        return
    _render_module_block(scanner, mid, mod_idx, module, block,
                        short_name=short_name, manual_only=manual_only)


def _clone_and_render_module(*args, **kwargs):  # noqa: ARG001
    """已废弃：新模板全 8 模块齐全，不再需要克隆。保留 stub 做兜底提示。"""
    logger.warning("_clone_and_render_module 已废弃（新模板全 8 模块齐全），跳过")


# ----------------------------------------------------------------------------
# 模板里没定义的模块（如 A009 Campwr）：克隆 PMIC 章节区块后重命名并渲染
# ----------------------------------------------------------------------------
def _clone_module_chapter_from_template(
    scanner: SkeletonScanner,
    *,
    template_l2_title_contains: str,
    template_short_name: str,
    new_short_name: str,
    insert_before_l2_title_contains: str,
) -> bool:
    """深拷贝一个已有 L2 模块章节（范围：目标 L2 → 下一个 L2 之前），
    把其中文本里的 template_short_name 替换成 new_short_name，
    再整体插入到 insert_before 指定的 L2 章节之前。

    成功返回 True；定位不到源章节或插入位置返回 False。
    """
    from copy import deepcopy
    from app.core.arch_skeleton_scanner import _heading_level as _hl

    body = scanner.doc.element.body
    src_l2 = scanner.find_heading(level=2, title_contains=template_l2_title_contains)
    anchor_l2 = scanner.find_heading(level=2, title_contains=insert_before_l2_title_contains)
    if src_l2 is None or anchor_l2 is None:
        return False

    children = list(body)
    si = children.index(src_l2)
    # 找下一个 L2
    ei = len(children)
    for i in range(si + 1, len(children)):
        c = children[i]
        if c.tag == qn("w:p") and _hl(c) == 2:
            ei = i
            break
    seg = children[si:ei]

    # 深拷贝 + 文本替换
    cloned = [deepcopy(el) for el in seg]
    for el in cloned:
        for t in el.iter(qn("w:t")):
            if t.text and template_short_name in t.text:
                t.text = t.text.replace(template_short_name, new_short_name)

    # R4.9：源章节此刻已被 _render_module_chapter 填充过（本例克隆 PMIC 时
    # PMIC 章里已塞满了它自己的类/函数子章和填好的表格数据行），
    # 直接 clone 过去会把 PMIC 的类/函数数据带给新模块（Campwr）。
    # 这里把 cloned 还原成"空骨架"，保持 _render_module_chapter 需要的锚点结构：
    #   1) 删掉所有「代码构造出来的」动态子章 —— 它们由 _build_class_subsection
    #      和 _build_function_subsection 生成，特征是 L4+ heading 且文本以
    #      "Class "/"类 "/"函数 "/"Function " 开头
    #   2) 其余 L4+ 的骨架 heading（"函数列表"、"原始NV函数列表"、"类的成员
    #      常量/变量列表"）必须保留，否则 _render_module_chapter 的
    #      find_heading 定位不到锚点，整个章节会漏填
    #   3) 清掉所有表格的非表头行（_render_module_chapter 按新模块数据重填）
    #   4) 清掉 <w:drawing>（源章节里残留的类图/流程图 PNG）
    from app.core.arch_skeleton_scanner import _text_of_paragraph as _tp

    def _is_dynamic_subheading(elem) -> bool:
        if elem.tag != qn("w:p"):
            return False
        lvl = _hl(elem)
        if lvl is None or lvl < 4:
            return False
        txt = (_tp(elem) or "").strip()
        # 代码构造的类/函数子章：Class XX / 类 XX / 函数 XX / Function XX
        # 骨架白名单（必须保留）：函数列表、原始NV函数列表、类的成员常量列表、
        #   类的成员变量列表
        return (
            txt.startswith("Class ")
            or txt.startswith("类 ")
            or txt.startswith("函数 ")
            or txt.startswith("Function ")
        )

    skeleton: list = []
    skip = False
    for el in cloned:
        if _is_dynamic_subheading(el):
            skip = True
            continue  # 丢掉这个动态子章 heading
        if el.tag == qn("w:p"):
            lvl = _hl(el)
            if lvl is not None:
                # 遇到任何 heading 都退出 skip 区（骨架 heading 自己保留）
                skip = False
        if skip:
            continue
        skeleton.append(el)

    # 对保留下来的表格，清掉数据行，只留表头
    for el in skeleton:
        if el.tag == qn("w:tbl"):
            rows = el.findall(qn("w:tr"))
            # 只保留第 1 行（表头）；删除其余
            for tr in rows[1:]:
                el.remove(tr)

    # 清掉骨架里残留的图片/绘图（源章节的类图 PNG 等）
    for el in skeleton:
        for drawing in list(el.iter(qn("w:drawing"))):
            parent = drawing.getparent()
            if parent is not None:
                parent.remove(drawing)

    # 插到 insert_before_l2 之前
    anchor_index = list(body).index(anchor_l2)
    for offset, el in enumerate(skeleton):
        body.insert(anchor_index + offset, el)
    return True


# ============================================================================
# 对外入口
# ============================================================================
def export_swe3(project: dict, out_dir, template_name: str = "swe3_detail", project_root=None) -> dict:
    """生成 SWE.3 详细设计 docx + xlsx。

    返回 {"docx": <filename>, "xlsx": <filename | None>}
    （文件名相对于 out_dir，与 export_swe3_v2 保持一致）

    project_root: 项目根目录（含 swe3/scan_cache/ 子目录）。缺省时按 out_dir.parent 推断。
      bridge 层从 scan_cache/<cid>.json 读取推送 D 扫出的 classes/functions 注入
      到 project.aspice.swe3.modules，让 UI 做的扫描真正落到 docx 里。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # —— 推送 D → 推送 H 桥接：把 scan_cache 和 focus_functions 融合进 modules ——
    if project_root is None:
        project_root = out_dir.parent  # runtime/creator_projects/<pid>/output -> <pid>/
    try:
        from app.core import arch_swe3_bridge
        project = arch_swe3_bridge.enrich_modules_from_push_d(project, Path(project_root))
    except Exception as e:
        logger.warning("SWE.3 bridge 注入失败（降级到原始 modules）: %s", e)

    # 文件名复用 v2 的规则（按 project_code 命名）
    project_code = (project.get("aspice", {}) or {}).get("project_code", "") or project.get("name", "project")
    safe = "".join(c for c in project_code if c.isalnum() or c in "._-") or "project"
    docx_name = f"{safe}_详细设计.docx"

    scanner = SkeletonScanner(template_name)

    # 1/2/3 章
    _fill_chapter_1_overview(scanner, project)
    _append_terms(scanner, project)
    _fill_chapter_3_functional_overview(scanner, project)

    # 4~11 模块循环：新模板 L2 已覆盖全部 8 个模块；按模板顺序遍历，用 name 关键字匹配项目里的实际模块
    modules = _normalize_modules((project.get("aspice", {}).get("swe3", {}) or {}).get("modules"))
    matched_mids: set[str] = set()
    for ch_no, anchor_title, short_name, keywords, manual_only in MODULE_CHAPTERS:
        m = _match_module_by_keywords(modules, keywords)
        # 用匹配到的模块 ID；没匹配上就按章节短名兜底（空数据）
        mid = (m.get("id") or m.get("component_id")) if m else short_name
        if not m:
            m = {"id": short_name, "name": short_name}
        if m.get("id") or m.get("component_id"):
            matched_mids.add(m.get("id") or m.get("component_id"))
        try:
            _render_module_chapter(scanner, mid, ch_no, m, anchor_title,
                                   short_name=short_name, manual_only=manual_only)
        except Exception as e:
            logger.error("模块章 %s (%s) 渲染失败: %s", short_name, anchor_title, e, exc_info=True)

    # —— 兜底：模板里没定义但项目数据里出现的模块（如 A009 Campwr）——
    # 克隆 PMIC 章节区块作为新模块章节，插到"性能分析设计"之前再填充
    # Serializer=4、…、PMIC=11；追加从 12 开始（先 +1 再用）
    extra_ch_no = len(MODULE_CHAPTERS) + 4 - 1  # 第一次 += 1 后 → 12
    for mid, m in modules.items():
        if mid in matched_mids:
            continue
        name = (m.get("name") or mid or "").strip()
        if not name:
            continue
        # 跳过明显是模板关键字本身的重名（防呆）
        name_norm = _norm(name)
        if any(_norm(kw) in name_norm or name_norm in _norm(kw)
               for _, _, _, kws, _ in MODULE_CHAPTERS for kw in kws if kw):
            continue
        new_short = name
        try:
            ok = _clone_module_chapter_from_template(
                scanner,
                template_l2_title_contains="PMIC详细设计",
                template_short_name="PMIC",
                new_short_name=new_short,
                # 插到"性能分析设计"之前，与模板里 8 个模块章节连续排列
                insert_before_l2_title_contains="性能分析设计",
            )
            if not ok:
                logger.warning("兜底克隆模块章失败（源 PMIC 或 系统集成 未定位到）: %s", new_short)
                continue
            extra_ch_no += 1
            _render_module_chapter(
                scanner, mid, extra_ch_no, m,
                anchor_l2_title_contains=f"模块{new_short}详细设计",
                short_name=new_short, manual_only=False,
            )
            logger.info("兜底克隆模块章成功: %s (ch=%d, mid=%s)", new_short, extra_ch_no, mid)
        except Exception as e:
            logger.error("兜底克隆模块章 %s 渲染失败: %s", new_short, e, exc_info=True)

    # TODO H4: 13.2 边界值
    # TODO: xlsx

    docx_path = out_dir / docx_name
    scanner.save_to(str(docx_path))
    logger.info("SWE.3 docx 已输出: %s (%.1f KB)", docx_path, docx_path.stat().st_size / 1024)
    return {"docx": docx_name, "xlsx": None}


__all__ = ["export_swe3", "MODULE_ORDER"]
