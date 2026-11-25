"""
SWE.1 回灌向导核心 — 解析工程师处理好的需求表（Excel/Word），输出可预览的 ParsedRow 列表。

4 种行类型（见 swe1_refactor_plan.md §4.A5）：
  - header：首行列头（+ r2 中文说明）→ row_type='header'/'skip'
  - group：只 col 1 有值且不含 PREDEV_ 且非文件名 → 缓存 current_module，不入库
  - main / sub：OR 列有 PREDEV_ → 入库；合并单元格自动继承父行 col 1-6
  - coverage：OR=NA / ReqID=NA 且 Content 含 "已覆盖" → 入库但 review_status='note'

真实样本洞察（/home/tstj/下载/PreDev_Detailed Software Requirements Table需求详细表.xlsx）：
  - 23 列 / 122 行 / 56 处合并单元格
  - 合并多为纵向继承（A7:A8 / B3:B6 / E17:E18 / A24:A25 等）
  - 分组行例：row 10 "帧同步" / row 16 "接口调用"
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Optional

from openpyxl import load_workbook

from app.schemas.aspice.swe1_schema import (
    ColumnMapping,
    MappingTemplate,
    ParsedRow,
)


# ---------- PreDev 默认映射（匹配不到模板时的保底推断） ----------

# 列头关键字 → Requirement 字段名；大小写不敏感，取 contains 关系
_HEADER_FIELD_RULES = [
    # (正则 / 关键字小写, 字段名, required)
    (r"\binput\b|需求来源|输入文档", "input_source", False),
    (r"\bchapter\b|章节", "chapter", False),
    (r"\bno\.?$|原始序号|req_sensor|req_\w+_\d+", "external_id", True),
    (r"content|需求描述|用户.*需求", "content", True),
    (r"software requirement id|软件需求标识", "software_mark", False),
    (r"^or$|所属的\s*or", "or_id", False),
    (r"reqid|req\s*id$|需求\s*id", "req_id", False),
    (r"function description|需求功能描述", "sw_req_desc", False),
    (r"test case|测试用例", "test_case_id", False),
    (r"requirement module|需求模块", "requirement_module", False),
    (r"category|需求类别|类别", "category", False),
    (r"asil|安全等级", "asil", False),
    (r"correctness|需求正确性", "correctness", False),
    (r"feasibility|需求可行性", "feasibility", False),
    (r"exception|异常处理", "exception", False),
    (r"priority|优先级", "priority", False),
    (r"project release|发布给客户", "milestone", False),
    (r"ra\s*deadline|需求分析.*完成", "ra_deadline", False),
    (r"actual.*revise|功能完成时间", "actual_time", False),
    (r"feature release|发布版本", "release_version", False),
    (r"owner|负责人", "owner", False),
    (r"memo|备注", "memo", False),
    (r"architecture.*document|架构设计文档", "arch_doc_hint", False),
]

# 标识某行是"分组行"的 col 1 内容白名单：工程师常用的标题
_GROUP_ROW_HINTS = {
    "帧同步", "接口调用", "错误处理", "初始化", "启动", "关闭",
    "sensor", "serdes", "pmic", "eeprom", "camera security",
}


# ---------- 工具 ----------

def file_md5(path: str | Path, chunk_size: int = 65536) -> str:
    """文件 MD5 指纹。"""
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            buf = f.read(chunk_size)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def headers_fingerprint(headers: list[str]) -> str:
    """列头顺序敏感的指纹，用于 MappingTemplate 匹配。

    空列头 → 用占位符 '__empty_{idx}'，避免两张表都有空列却被误判同类。
    """
    normalized = [
        (h or f"__empty_{i}").strip().lower() for i, h in enumerate(headers)
    ]
    return hashlib.md5("||".join(normalized).encode("utf-8")).hexdigest()


# ---------- 列头推断 ----------

def infer_mapping(headers: list[str]) -> list[ColumnMapping]:
    """按 _HEADER_FIELD_RULES 猜列头 → 字段的默认映射。

    一个字段只映射到首个命中的列（PreDev 有部分字段重名如 Software Requirement 行）。
    """
    used_fields: set[str] = set()
    out: list[ColumnMapping] = []
    for idx, h in enumerate(headers):
        if not h:
            continue
        text = str(h).lower()
        for pattern, field, required in _HEADER_FIELD_RULES:
            if field in used_fields:
                continue
            if re.search(pattern, text, re.IGNORECASE):
                out.append(ColumnMapping(
                    excel_header=str(h),
                    excel_col_index=idx,
                    field=field,
                    required=required,
                ))
                used_fields.add(field)
                break
    return out


# ---------- 合并单元格展开 ----------

def _expand_merged_cells(ws) -> dict[tuple[int, int], Any]:
    """返回 {(row, col) -> value}，把合并区都填上左上角的值。

    openpyxl read 合并单元格时，只有左上角有值，其他是 None；
    这里一次性展开为平铺矩阵，方便行类型判定。

    注意：read_only=True 模式不支持 merged_cells.ranges；本函数假定 read_only=False。
    """
    data: dict[tuple[int, int], Any] = {}
    # 先把所有单元格拷贝
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row,
                             min_col=1, max_col=ws.max_column, values_only=False):
        for cell in row:
            data[(cell.row, cell.column)] = cell.value
    # 再把合并区的空位填成左上角值
    for mr in ws.merged_cells.ranges:
        anchor = data.get((mr.min_row, mr.min_col))
        if anchor is None:
            continue
        for r in range(mr.min_row, mr.max_row + 1):
            for c in range(mr.min_col, mr.max_col + 1):
                data[(r, c)] = anchor
    return data


# ---------- 行类型判定 ----------

def _classify_row(
    row_values: list[Any],
    mapping_by_field: dict[str, int],  # field -> col_idx (0-based)
) -> tuple[str, Optional[str]]:
    """判断行类型，返回 (row_type, hint)。

    hint 用于分组行时承载模块名；其他 row_type 为 None。
    """
    # 全空 → skip
    if all(v is None or str(v).strip() == "" for v in row_values):
        return ("skip", None)

    non_empty_cols = [
        i for i, v in enumerate(row_values)
        if v is not None and str(v).strip() != ""
    ]

    # 分组行：只 col 1（0-based idx=0）或 col 1-2 有值，且 or_id 列为空，内容不含 PREDEV_
    or_col = mapping_by_field.get("or_id", -1)
    content_col = mapping_by_field.get("content", -1)
    ext_col = mapping_by_field.get("external_id", -1)

    def _val(col_idx: int) -> str:
        if col_idx < 0 or col_idx >= len(row_values):
            return ""
        v = row_values[col_idx]
        return "" if v is None else str(v).strip()

    or_val = _val(or_col)
    req_val = _val(mapping_by_field.get("req_id", -1))
    content_val = _val(content_col)
    ext_val = _val(ext_col)

    is_na = lambda s: s.upper() in {"NA", "N/A", "N.A."}

    or_missing = is_na(or_val) or not or_val
    req_missing = is_na(req_val) or not req_val

    def _looks_group(text: str) -> bool:
        if not text or len(text) > 40:
            return False
        if is_na(text):
            return False
        if re.search(r"\.\w{1,5}$|_\d{8}", text):  # 文件名
            return False
        if re.match(r"^(PREDEV|REQ|OR)[_-]", text.upper()):  # 像 ID
            return False
        return True

    # group：or_id / req_id 为空 / NA；content 和 external_id 列值相同且是短文本
    # —— 真实样本中"帧同步"等分组行因合并单元格展开导致这两列同值
    if or_missing and req_missing:
        if content_val and ext_val and content_val == ext_val and _looks_group(content_val):
            return ("group", content_val)
        # 或者 content 为空但 ext 像分组名
        if not content_val and _looks_group(ext_val):
            return ("group", ext_val)
        # 或者 content/ext 都空，只有 input_source 列有短文本
        if not content_val and not ext_val and _looks_group(_val(0)):
            return ("group", _val(0))

    # coverage：or_id/req_id 为 NA 或都为空；content 是真实描述（长文本或和 ext 不同）
    if or_missing and req_missing and content_val:
        return ("coverage", None)
    # 或者 OR/ReqID 任一为 NA 且 content 明确含"已覆盖"
    if (is_na(or_val) or is_na(req_val)) and "已覆盖" in content_val:
        return ("coverage", None)

    # main / sub：有 OR_ID + content 非空
    if or_val and not is_na(or_val) and content_val:
        return ("main", None)

    # 最后保留：只有 external_id + content（没有 OR）→ 也算 main，但 or_id 由派生步骤给
    if ext_val and content_val and not or_missing is False:
        pass

    # 其他：有内容但不满足 → 跳过并告警
    return ("skip", None)


# ---------- 主入口 ----------

def list_sheets(file_path: str | Path) -> list[dict]:
    """返回 [{"index": i, "name": name, "rows": r, "cols": c, "is_requirement_candidate": bool}, ...]

    A1-A2 向导要让用户在多 sheet 文件中选 Requirement 那张。
    """
    wb = load_workbook(str(file_path), read_only=True, data_only=True)
    out = []
    for i, name in enumerate(wb.sheetnames):
        ws = wb[name]
        name_lower = name.lower()
        is_req = any(kw in name_lower for kw in ("requirement", "需求", "req"))
        out.append({
            "index": i,
            "name": name,
            "rows": ws.max_row,
            "cols": ws.max_column,
            "is_requirement_candidate": is_req,
        })
    return out


def _auto_pick_sheet(wb) -> int:
    """从多 sheet 文件中启发式选 requirement sheet（命中关键字 + 列数最多）。"""
    best_idx = 0
    best_score = -1
    for i, name in enumerate(wb.sheetnames):
        ws = wb[name]
        name_lower = name.lower()
        score = 0
        if any(kw in name_lower for kw in ("requirement", "需求")):
            score += 100
        if "req" in name_lower:
            score += 20
        # 列数多的更可能是明细表
        score += min(ws.max_column, 50)
        if score > best_score:
            best_score = score
            best_idx = i
    return best_idx


def parse_excel(
    file_path: str | Path,
    sheet_index: int = -1,
    mapping: Optional[list[ColumnMapping]] = None,
    existing_req_ids: Optional[set[str]] = None,
    existing_by_req_id: Optional[dict[str, dict]] = None,
) -> tuple[list[str], list[ColumnMapping], list[ParsedRow], dict]:
    """解析 Excel 需求表。

    Returns:
      (headers, used_mapping, rows, stats)

    - headers：首行列头（r1）
    - used_mapping：若传了 mapping 则原样返回；否则 infer_mapping 推断
    - rows：ParsedRow 列表（含 header 跳过行、group 分组行、main/sub 需求行、coverage 说明行）
    - stats：{"total", "main", "sub", "coverage", "group", "skip", "conflict"}
    """
    existing_req_ids = existing_req_ids or set()
    existing_by_req_id = existing_by_req_id or {}

    wb = load_workbook(str(file_path), read_only=False, data_only=True)
    sheet_names = wb.sheetnames
    if sheet_index < 0:
        sheet_index = _auto_pick_sheet(wb)
    if sheet_index >= len(sheet_names):
        raise ValueError(f"sheet_index {sheet_index} out of range: {sheet_names}")
    ws = wb[sheet_names[sheet_index]]

    # 展开合并单元格
    expanded = _expand_merged_cells(ws)
    max_col = ws.max_column
    max_row = ws.max_row

    def row_vals(r: int) -> list[Any]:
        return [expanded.get((r, c + 1)) for c in range(max_col)]

    # 取列头 r1；若 r2 看起来是"中文说明"（长度 > 15 或包含中文），标记跳过
    headers = [str(expanded.get((1, c + 1)) or "") for c in range(max_col)]

    # 推断 / 使用用户传的映射
    used_mapping = mapping if mapping else infer_mapping(headers)
    mapping_by_field = {m.field: m.excel_col_index for m in used_mapping}
    mapping_by_col = {m.excel_col_index: m.field for m in used_mapping}

    rows_out: list[ParsedRow] = []
    stats = {"total": 0, "main": 0, "sub": 0, "coverage": 0,
             "group": 0, "skip": 0, "header": 0, "conflict": 0}

    # r1 固定 header
    rows_out.append(ParsedRow(
        row_type="header", excel_row=1,
        data={"headers": headers},
    ))
    stats["header"] += 1

    # r2 判定是否"中文说明行"（PreDev 实际样本中 r2 多为中文翻译）
    r2 = row_vals(2) if max_row >= 2 else []
    r2_is_desc = False
    if r2:
        chinese_count = sum(1 for v in r2 if v and re.search(r"[一-鿿]", str(v)))
        r2_is_desc = chinese_count >= max(2, len(r2) // 4)
    if r2_is_desc:
        rows_out.append(ParsedRow(
            row_type="skip", excel_row=2,
            data={"reason": "中文说明行，跳过"},
        ))
        stats["skip"] += 1
        start_row = 3
    else:
        start_row = 2

    current_module = ""   # 分组行缓存
    last_or_id = ""       # 用于 main/sub 判定
    last_excel_row_for_or = 0

    for r in range(start_row, max_row + 1):
        values = row_vals(r)
        row_type, hint = _classify_row(values, mapping_by_field)
        stats["total"] += 1

        if row_type == "skip":
            stats["skip"] += 1
            rows_out.append(ParsedRow(
                row_type="skip", excel_row=r,
                data={"raw": [str(v) if v is not None else "" for v in values[:5]]},
            ))
            continue

        if row_type == "group":
            current_module = hint or ""
            stats["group"] += 1
            rows_out.append(ParsedRow(
                row_type="group", excel_row=r,
                data={"module": current_module},
            ))
            continue

        # 组装 data dict：按 mapping 填字段
        data: dict[str, Any] = {}
        for col_idx, field in mapping_by_col.items():
            if col_idx >= len(values):
                continue
            v = values[col_idx]
            if v is None:
                continue
            s = str(v).strip()
            if not s:
                continue
            if field == "priority":
                # 取首个数字
                m = re.search(r"\d+", s)
                data[field] = int(m.group()) if m else 0
            else:
                data[field] = s

        # 挂上分组模块：若 current_module（来自上方 group 行）更具体，覆盖
        # PreDev 的 col 9 有时是泛泛的 "Software Requirements"，分组行的"帧同步"/"接口调用"更有价值
        existing_module = data.get("requirement_module", "")
        if current_module:
            if not existing_module or existing_module.lower() in {"software requirements", "software requirement"}:
                data["requirement_module"] = current_module

        warnings: list[str] = []

        if row_type == "coverage":
            stats["coverage"] += 1
            # 提取"XXX 已覆盖本条"中的 XXX
            content_text = data.get("content", "")
            m = re.search(r"([A-Z][A-Z0-9_]+-R\d+|PREDEV_\d+|Req_\w+_\d+)", content_text)
            covered_by = m.group(1) if m else ""
            rows_out.append(ParsedRow(
                row_type="coverage", excel_row=r,
                data={**data, "_covered_by": covered_by},
                parent_excel_row=last_excel_row_for_or,
            ))
            continue

        # main / sub
        cur_or = data.get("or_id", "")
        if cur_or and cur_or == last_or_id:
            row_type = "sub"
            stats["sub"] += 1
        else:
            stats["main"] += 1
            if cur_or:
                last_or_id = cur_or
                last_excel_row_for_or = r

        # 冲突检测：按 req_id
        req_id = data.get("req_id", "")
        conflict = False
        diff: dict = {}
        if req_id and req_id in existing_req_ids:
            conflict = True
            stats["conflict"] += 1
            old = existing_by_req_id.get(req_id, {})
            for k, v in data.items():
                old_v = old.get(k, "")
                if str(old_v or "") != str(v or ""):
                    diff[k] = {"old": old_v, "new": v}

        rows_out.append(ParsedRow(
            row_type=row_type,
            excel_row=r,
            data=data,
            parent_excel_row=last_excel_row_for_or if row_type == "sub" else 0,
            conflict_with_existing=conflict,
            conflict_diff=diff,
            warnings=warnings,
        ))

    return headers, used_mapping, rows_out, stats


# ---------- Word 文档（R1 只支持 Excel，Word 走 R2） ----------

def parse_word_stub(file_path: str | Path) -> tuple[list[str], list[ColumnMapping], list[ParsedRow], dict]:
    """Word 需求表（.docx 表格）解析占位。R1 不实现，返回空结果带告警。"""
    return [], [], [
        ParsedRow(
            row_type="skip", excel_row=1,
            data={"reason": "R1 只支持 Excel 回灌；Word 需求表走 R2 AI 候选面板"},
            warnings=["word_not_supported_in_r1"],
        )
    ], {"total": 0, "main": 0, "coverage": 0, "group": 0, "skip": 1}
