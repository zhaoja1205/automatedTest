"""SWE.3 详细设计骨架扫描器（推送 H）。

用户把 swe3_detail.docx 从带占位的"填空模板"精简成了"纯静态章节骨架"：
- 没有 {{ }} / {% %} Jinja 标签
- 1~3/8~11 章内容已定稿，4~7 章只给了样板空壳
- 模板尾部还有「模板历史记录」表（保留）

本扫描器负责：
1) 读骨架，构建 heading 索引（按 (style_level, title) 定位）
2) 构建"样板表"签名（按 前文heading + 列头元组 定位）
3) 提供原地插入/克隆表/追加行的操作，便于 arch_generator_swe3_v3 按章填内容

设计原则：
- 不用 python-docx 的高层 Document，直接操作底层 lxml（document.xml 的 w:body）
  因为我们要做"在某 heading 后插一组段落"这种 docxtpl 和 python-docx 都没有
  直接对应方法的操作
- 所有对 body 的变动都走 `_body.insert(idx, elem)` 或 `elem.addnext(...)`，不打乱
  其他 part（styles.xml / rels / media），保证页眉页脚/样式/编号全部承袭
- 一旦 heading 位置变动（插入后），我们**不维护全量索引**，而是在每次插入前
  重新定位目标 heading，代价 O(n) 但 n < 200，完全可接受
"""
from __future__ import annotations

import copy
import logging
import re
from pathlib import Path
from typing import Optional

from docx import Document
from docx.document import Document as _DocDoc
from docx.oxml.ns import qn
from lxml import etree

logger = logging.getLogger(__name__)

# ---------------- 常量 ----------------
# python-docx 的样式 id 和 docx 文件里的 w:val 形式都可能出现
# ("Heading1", "1", "heading 1" 都见过)
_HEADING_STYLE_RE = re.compile(r"^(heading|标题)\s*(\d+)$", re.IGNORECASE)


def _text_of_paragraph(p_elem) -> str:
    """提取一个 <w:p> 的纯文本（拼接所有 w:t）。"""
    parts = []
    for t in p_elem.iter(qn("w:t")):
        if t.text:
            parts.append(t.text)
    return "".join(parts).strip()


def _heading_level(p_elem) -> Optional[int]:
    """若段落是 Heading N，返回 N (1~9)；否则返回 None。

    Word 的 heading 样式写法众多：Heading1 / Heading 1 / heading1 / 标题 1 /
    自定义样式（如中科创达模板里的"1 标题"），我们按"样式名含数字且前缀标识"的
    宽松规则匹配。
    """
    pPr = p_elem.find(qn("w:pPr"))
    if pPr is None:
        return None
    pStyle = pPr.find(qn("w:pStyle"))
    if pStyle is None:
        return None
    val = pStyle.get(qn("w:val"))
    if not val:
        return None
    # 直接数字：模板里见过 w:val="2" 这种裸数字
    if val.isdigit():
        try:
            n = int(val)
            if 1 <= n <= 9:
                return n
        except ValueError:
            pass
    m = _HEADING_STYLE_RE.match(val.replace("-", "").replace("_", ""))
    if m:
        return int(m.group(2))
    return None


def _table_headers(tbl_elem) -> tuple[str, ...]:
    """返回表格第一行的文本列表（列头签名）。"""
    rows = tbl_elem.findall(qn("w:tr"))
    if not rows:
        return ()
    cells = rows[0].findall(qn("w:tc"))
    out = []
    for tc in cells:
        parts = []
        for p in tc.findall(qn("w:p")):
            parts.append(_text_of_paragraph(p))
        out.append(" ".join(parts).strip())
    return tuple(out)


# ---------------- 核心类 ----------------
class SkeletonScanner:
    """加载骨架 docx 并提供定位/插入/克隆接口。

    用法：
        s = SkeletonScanner("swe3_detail")       # 从 templates/aspice/ 读
        doc = s.doc                               # python-docx Document
        heading = s.find_heading(level=2, title="概述")
        s.insert_paragraph_after(heading, "一行普通正文")
        sample = s.find_table_after(heading, headers=("序号","设计 ID","类名","说明"))
        new_tbl = s.clone_table_with_rows(sample, rows=[...])
        s.replace_table(sample, new_tbl)
        buf = s.save_to_bytes()
    """

    TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "aspice"

    def __init__(self, template_name: str):
        self.template_name = template_name
        self.path = self.TEMPLATE_DIR / f"{template_name}.docx"
        if not self.path.exists():
            raise FileNotFoundError(f"骨架模板不存在: {self.path}")
        self.doc: _DocDoc = Document(str(self.path))
        self._body = self.doc.element.body

    # ---- 索引 ----
    def headings(self) -> list[tuple[int, int, str]]:
        """返回 [(body_index, level, title), ...]，按 body 顺序。"""
        out = []
        for i, child in enumerate(self._body):
            if child.tag != qn("w:p"):
                continue
            lvl = _heading_level(child)
            if lvl is None:
                continue
            title = _text_of_paragraph(child)
            if not title:
                continue
            out.append((i, lvl, title))
        return out

    def tables(self) -> list[tuple[int, tuple[str, ...], int]]:
        """返回 [(body_index, headers, rows_count), ...]。"""
        out = []
        for i, child in enumerate(self._body):
            if child.tag != qn("w:tbl"):
                continue
            headers = _table_headers(child)
            rows = len(child.findall(qn("w:tr")))
            out.append((i, headers, rows))
        return out

    # ---- 定位 ----
    def find_heading(
        self,
        level: Optional[int] = None,
        title: Optional[str] = None,
        title_contains: Optional[str] = None,
        after_index: int = -1,
    ):
        """定位一个 heading，返回 lxml 元素；找不到返回 None。

        - level: 必须等于指定层级（None 表示不限）
        - title: 完全匹配（忽略首尾空白）
        - title_contains: 子串匹配
        - after_index: 从 body 中该索引之后开始找（用于处理同名 heading）
        """
        for i, child in enumerate(self._body):
            if i <= after_index:
                continue
            if child.tag != qn("w:p"):
                continue
            lvl = _heading_level(child)
            if lvl is None:
                continue
            if level is not None and lvl != level:
                continue
            txt = _text_of_paragraph(child)
            if title is not None and txt != title:
                continue
            if title_contains is not None and title_contains not in txt:
                continue
            return child
        return None

    def find_table_after(
        self,
        anchor_elem,
        headers: Optional[tuple[str, ...]] = None,
        stop_at_next_heading_level: Optional[int] = None,
    ):
        """在 anchor_elem 之后找第一张满足条件的表。

        - headers: 第一行列头必须等于这个元组（忽略空白差异）
        - stop_at_next_heading_level: 遇到不深于该层的 heading 就停（防跨章节误配）
        """
        anchor_idx = list(self._body).index(anchor_elem)
        norm = lambda s: " ".join(s.split())
        want = tuple(norm(h) for h in headers) if headers else None
        for i in range(anchor_idx + 1, len(self._body)):
            child = self._body[i]
            if child.tag == qn("w:p") and stop_at_next_heading_level is not None:
                lvl = _heading_level(child)
                if lvl is not None and lvl <= stop_at_next_heading_level:
                    return None
            if child.tag != qn("w:tbl"):
                continue
            if want is None:
                return child
            got = tuple(norm(h) for h in _table_headers(child))
            if got == want:
                return child
        return None

    # ---- 原地插入 ----
    def insert_after(self, anchor_elem, new_elem) -> None:
        """在 anchor_elem 之后插入 new_elem（body 里相邻）。"""
        anchor_elem.addnext(new_elem)

    def insert_paragraph_after(
        self,
        anchor_elem,
        text: str,
        style: Optional[str] = None,
    ):
        """插入一个普通段落，返回新段落的 lxml 元素。

        style 可指定正文样式名（如 "Normal" / "a"）；None 则继承 Normal。
        """
        # 构造 <w:p><w:pPr><w:pStyle/></w:pPr><w:r><w:t>text</w:t></w:r></w:p>
        p = etree.SubElement(anchor_elem.getparent(), qn("w:p"))
        # 从父节点取出放回：此处不方便，改成直接构造 element
        anchor_elem.getparent().remove(p)
        p = etree.Element(qn("w:p"))
        if style:
            pPr = etree.SubElement(p, qn("w:pPr"))
            pStyle = etree.SubElement(pPr, qn("w:pStyle"))
            pStyle.set(qn("w:val"), style)
        r = etree.SubElement(p, qn("w:r"))
        t = etree.SubElement(r, qn("w:t"))
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = text
        anchor_elem.addnext(p)
        return p

    def insert_heading_after(
        self,
        anchor_elem,
        level: int,
        title: str,
    ):
        """插入一个 Heading<level> 段落，返回新段落元素。

        样式名规则：Word 自带 Heading1 / Heading2 ...（docxtpl 模板也是这套）。
        若模板用了别的命名规则需要 override，这里统一默认。
        """
        p = etree.Element(qn("w:p"))
        pPr = etree.SubElement(p, qn("w:pPr"))
        pStyle = etree.SubElement(pPr, qn("w:pStyle"))
        pStyle.set(qn("w:val"), f"{level}")  # 骨架模板里我们看到的是裸数字样式 id
        r = etree.SubElement(p, qn("w:r"))
        t = etree.SubElement(r, qn("w:t"))
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = title
        anchor_elem.addnext(p)
        return p

    # ---- 表格操作 ----
    def clone_table(self, src_tbl):
        """深拷贝一张表，返回新 w:tbl 元素（未挂到 body，调用方负责插入）。"""
        return copy.deepcopy(src_tbl)

    def clear_table_data_rows(self, tbl, keep_header_rows: int = 1) -> None:
        """清掉表格除表头外的所有行。"""
        rows = tbl.findall(qn("w:tr"))
        for tr in rows[keep_header_rows:]:
            tbl.remove(tr)

    def append_row(self, tbl, cell_texts: list[str], template_row=None):
        """追加一行到表格末尾。

        - cell_texts: 每个单元格的文本
        - template_row: 用于复制 w:trPr 和每个 w:tcPr 的模板行；None 则用表的
          最后一行作为模板（保证格式继承）
        """
        rows = tbl.findall(qn("w:tr"))
        if template_row is None:
            if not rows:
                # 没有任何行可参考，构建最简单的行
                tr = etree.SubElement(tbl, qn("w:tr"))
                for txt in cell_texts:
                    tc = etree.SubElement(tr, qn("w:tc"))
                    _set_cell_text(tc, txt)
                return tr
            template_row = rows[-1]
        new_tr = copy.deepcopy(template_row)
        # 清空每个 cell 的文本，再按 cell_texts 填回
        tcs = new_tr.findall(qn("w:tc"))
        for i, tc in enumerate(tcs):
            txt = cell_texts[i] if i < len(cell_texts) else ""
            _set_cell_text(tc, txt)
        # 若 cell_texts 比 tc 多，只能截断（防意外越界）
        tbl.append(new_tr)
        return new_tr

    def replace_row_cells(self, tr, cell_texts: list[str]) -> None:
        """就地替换一行里每个单元格的文本（保留 tcPr 样式）。"""
        tcs = tr.findall(qn("w:tc"))
        for i, tc in enumerate(tcs):
            txt = cell_texts[i] if i < len(cell_texts) else ""
            _set_cell_text(tc, txt)

    # ---- 保存 ----
    def save_to(self, path: str) -> None:
        self.doc.save(path)


# ---------------- 单元格操作辅助 ----------------
def _set_cell_text(tc, text: str) -> None:
    """清空 tc 的所有 w:p，再插入一个带 text 的段落。保留 w:tcPr。

    重要：必须保留 tc 的 tcPr（宽度/合并/垂直对齐），只重建段落。
    """
    # 删除所有子段落和子表（不碰 tcPr）
    for child in list(tc):
        if child.tag in (qn("w:p"), qn("w:tbl")):
            tc.remove(child)
    # 新建一个段落
    p = etree.SubElement(tc, qn("w:p"))
    if text:
        r = etree.SubElement(p, qn("w:r"))
        t = etree.SubElement(r, qn("w:t"))
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = text


__all__ = [
    "SkeletonScanner",
    "_text_of_paragraph",
    "_heading_level",
    "_table_headers",
]
