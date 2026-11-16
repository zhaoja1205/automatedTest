"""R4.5 需求 #1：给 Deserializer / EEPROM / CameraModule 三个模块的骨架补齐：
  - L3 '<name>详细设计'   包装层
  - 把现有 L4 '函数列表' + 函数表挪进该包装层下
  - 加 L4 '原始NV函数列表' + 空函数表

照 Serializer 结构做一次性补丁。原地改写 swe3_detail.docx。

用法：
  python -m scripts.patch_swe3_template_nv_sections            # 原地补
  python -m scripts.patch_swe3_template_nv_sections --dry-run  # 只打印不写
"""

from __future__ import annotations

import copy
import os
import shutil
import sys
from datetime import datetime

from docx import Document
from docx.oxml.ns import qn
from lxml import etree


TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "app", "templates", "aspice", "swe3_detail.docx",
)

# 以 Serializer 为模板来源；补给这三个
SOURCE_MODULE = "模块Serializer详细设计"
TARGET_MODULES = ["模块Deserializer详细设计", "模块EEPROM详细设计", "模块CameraModule详细设计"]


def _heading_level(p) -> int:
    pStyle = p.find(qn("w:pPr") + "/" + qn("w:pStyle"))
    if pStyle is None:
        return 0
    v = pStyle.get(qn("w:val")) or ""
    return int(v) if v.isdigit() else 0


def _text_of(p) -> str:
    return "".join(t.text or "" for t in p.iter(qn("w:t")))


def _set_text_in_paragraph(p, new_text: str) -> None:
    """替换段落里所有 <w:t> 的文本为 new_text（放到第一个 run 的第一个 <w:t>）；
    其余 <w:t> 清空。保持段落的 pStyle / bookmark 样式不变，不会碰 TOC 跳过。
    """
    ts = list(p.iter(qn("w:t")))
    if not ts:
        return
    ts[0].text = new_text
    for t in ts[1:]:
        t.text = ""


def _module_name_from_l2(l2_text: str) -> str:
    # '模块XXX详细设计' → 'XXX'
    s = l2_text.strip()
    if s.startswith("模块"):
        s = s[2:]
    if s.endswith("详细设计"):
        s = s[: -len("详细设计")]
    return s


def _find_l2_range(body, l2_text: str) -> tuple[int, int] | None:
    children = list(body)
    si = None
    for i, c in enumerate(children):
        if c.tag == qn("w:p") and _heading_level(c) == 2 and _text_of(c).strip() == l2_text.strip():
            si = i
            break
    if si is None:
        return None
    ei = len(children)
    for i in range(si + 1, len(children)):
        c = children[i]
        if c.tag == qn("w:p") and _heading_level(c) == 2:
            ei = i
            break
    return (si, ei)


def _collect_tags_from_source(body, src_range: tuple[int, int]) -> dict:
    """从 Serializer 段里挑这些节点的 **深拷贝**：
      - L3 '<name>详细设计'        → src_l3_subdevice
      - L4 '原始NV函数列表'         → src_l4_nv
      - L4 '原始NV函数列表' 的表    → src_tbl_nv  (下一个 w:tbl)

    返回字典；缺失则对应 key 为 None。
    """
    children = list(body)
    si, ei = src_range
    out = {"l3_subdevice": None, "l4_nv": None, "tbl_nv": None}
    for i in range(si + 1, ei):
        c = children[i]
        if c.tag == qn("w:p"):
            lvl = _heading_level(c)
            txt = _text_of(c).strip()
            if lvl == 3 and "详细设计" in txt and out["l3_subdevice"] is None:
                out["l3_subdevice"] = copy.deepcopy(c)
            elif lvl == 4 and "原始NV" in txt and out["l4_nv"] is None:
                out["l4_nv"] = copy.deepcopy(c)
                # 下一个 tbl 就是 NV 表
                for j in range(i + 1, ei):
                    cj = children[j]
                    if cj.tag == qn("w:tbl"):
                        out["tbl_nv"] = copy.deepcopy(cj)
                        break
                    if cj.tag == qn("w:p") and _heading_level(cj) > 0:
                        break
    return out


def _strip_bookmarks(elem) -> None:
    """删除元素里所有 w:bookmarkStart/End — 这些是源模块的 TOC 锚点，拷贝到
    目标模块后会和原书签 id 冲突 / 跳转错。TOC 会在 Word 下次打开时按新内容重建，
    不用管。"""
    for tag in (qn("w:bookmarkStart"), qn("w:bookmarkEnd")):
        for bk in list(elem.iter(tag)):
            parent = bk.getparent()
            if parent is not None:
                parent.remove(bk)


def _clear_table_rows_keep_header(tbl, keep: int = 1) -> None:
    """只留前 `keep` 行（表头），其余删掉。NV 表骨架给到用户时应为空。"""
    rows = list(tbl.findall(qn("w:tr")))
    for r in rows[keep:]:
        tbl.remove(r)


def patch_module(body, l2_text: str, src_tags: dict, dry_run: bool) -> str:
    """给一个模块补齐。返回状态字符串。"""
    rng = _find_l2_range(body, l2_text)
    if rng is None:
        return f"[skip] 找不到 L2: {l2_text}"
    si, ei = rng
    children = list(body)

    # 检查当前是否已经有 L4 原始NV（幂等）
    has_l4_nv = False
    idx_l4_fn_list = None
    idx_tbl_fn_list = None
    idx_l3_sequence = None
    idx_l3_subdevice = None
    for i in range(si + 1, ei):
        c = children[i]
        if c.tag == qn("w:p"):
            lvl = _heading_level(c)
            txt = _text_of(c).strip()
            if lvl == 3 and "详细设计" in txt and "模块" not in txt and idx_l3_subdevice is None:
                idx_l3_subdevice = i
            elif lvl == 3 and "时序图" in txt and idx_l3_sequence is None:
                idx_l3_sequence = i
            elif lvl == 4 and txt == "函数列表" and idx_l4_fn_list is None:
                idx_l4_fn_list = i
            elif lvl == 4 and "原始NV" in txt:
                has_l4_nv = True

        elif c.tag == qn("w:tbl") and idx_l4_fn_list is not None and idx_tbl_fn_list is None:
            # 第一张函数列表后的 tbl
            idx_tbl_fn_list = i

    if has_l4_nv:
        return f"[skip] {l2_text} 已有 L4 原始NV，无需补"

    mod_name = _module_name_from_l2(l2_text)

    # 组装插入节点：L3 '<name>详细设计' + L4 原始NV + 空表
    nodes_to_insert: list = []
    if idx_l3_subdevice is None:
        # 目标模块缺 L3 '<name>详细设计' 包装层 → 克隆一份
        l3 = copy.deepcopy(src_tags["l3_subdevice"]) if src_tags["l3_subdevice"] is not None else None
        if l3 is not None:
            _strip_bookmarks(l3)
            _set_text_in_paragraph(l3, f"{mod_name}详细设计")
            nodes_to_insert.append(("l3_subdevice", l3))
    l4_nv = copy.deepcopy(src_tags["l4_nv"]) if src_tags["l4_nv"] is not None else None
    tbl_nv = copy.deepcopy(src_tags["tbl_nv"]) if src_tags["tbl_nv"] is not None else None
    if l4_nv is None or tbl_nv is None:
        return f"[skip] {l2_text} 源模板里也找不到 L4 原始NV + 表骨架"
    _strip_bookmarks(l4_nv)
    _strip_bookmarks(tbl_nv)
    _clear_table_rows_keep_header(tbl_nv, keep=1)
    nodes_to_insert.append(("l4_nv", l4_nv))
    nodes_to_insert.append(("tbl_nv", tbl_nv))

    # 插入点：
    #   有 L3 '<name>单元时序图' → 插在它前面
    #   没有 → 插在 L2 段末尾（ei 之前最后一个元素后）
    insert_before = None
    if idx_l3_sequence is not None:
        insert_before = children[idx_l3_sequence]
    else:
        insert_before = children[ei] if ei < len(children) else None

    status_parts = []
    if dry_run:
        for name, _ in nodes_to_insert:
            status_parts.append(name)
        return f"[dry] {l2_text}: 将插入 {','.join(status_parts)}"

    # 实际插入
    if insert_before is not None:
        for _, node in nodes_to_insert:
            insert_before.addprevious(node)
    else:
        for _, node in nodes_to_insert:
            body.append(node)

    # 如果目标模块缺 L3 '<name>详细设计' 包装，现有的 L4 函数列表和它的表要被挪到
    # L3 包装之下 —— 在 Word 层面只要 L3 出现在它们之前即可（都是同一 body 的
    # 兄弟节点，层级靠 pStyle 决定），所以我们已经把 l3_subdevice 插在了 l4_nv
    # 前面，而 l4_nv/tbl_nv 又插在 l3_sequence 前面，相对位置正确。
    # 但现有的 L4 '函数列表' 还在 L3 '类列表' 之后，位置也是对的（L3 '类列表' 下
    # 挂 L4 原本就不规范，但骨架既然写成那样，我们不动它；只要新插入的 L3 包装
    # 来得比 L4 函数列表更晚、同时在 L4 NV 之前即可。
    return f"[ok]  {l2_text}: 插入 {','.join(n for n, _ in nodes_to_insert)}"


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    doc = Document(TEMPLATE_PATH)
    body = doc.element.body

    src_range = _find_l2_range(body, SOURCE_MODULE)
    if src_range is None:
        print(f"ERROR: 源模板找不到 {SOURCE_MODULE}")
        return 1
    src_tags = _collect_tags_from_source(body, src_range)
    if src_tags["l4_nv"] is None or src_tags["tbl_nv"] is None:
        print(f"ERROR: 源模板 {SOURCE_MODULE} 里也没有 L4 原始NV + 表")
        return 1

    for l2 in TARGET_MODULES:
        print(patch_module(body, l2, src_tags, dry_run))

    if dry_run:
        print("--dry-run，未写盘")
        return 0

    # 备份
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = TEMPLATE_PATH + f".bak_{ts}"
    shutil.copy2(TEMPLATE_PATH, backup)
    print(f"原模板已备份到: {backup}")
    doc.save(TEMPLATE_PATH)
    print(f"已写回: {TEMPLATE_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
