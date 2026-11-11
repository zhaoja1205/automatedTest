"""
测试用例合并。

把「来源」用例 Excel 中选中的用例行复制到「主用例」Excel 对应的 Sheet：

- 主用例文件保持原有模板、封面、数据统计页与 BugList 页不动；
- 来源 Sheet 优先按同名 Sheet 匹配，其次按类别（功能/故障/异常/压力/稳定）
  匹配主用例中的 Sheet；主用例缺少对应 Sheet 时新建并复制来源表头；
- 只复制用例定义列（用例ID/类型/描述/前置条件/步骤/预期结果/优先级等），
  默认不复制上一次的执行结果；可选保留结果列；
- 复制单元格样式、行高与合并单元格，并按原表布局追加到末尾；
- 合并后延长 Sheet 顶部统计公式的统计范围，并刷新「数据统计」页公式。
"""
from __future__ import annotations

import copy
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from openpyxl.utils import get_column_letter, range_boundaries

from app.core.excel_handler import ExcelHandler

# 用例定义列（合并时默认复制）
DEFINITION_FIELDS = (
    "case_id",
    "test_type",
    "requirement_id",
    "design_method",
    "description",
    "prerequisites",
    "test_steps",
    "expected_result",
    "priority",
)

# 执行结果列（include_results=True 时复制）
RESULT_FIELDS = (
    "actual_result",
    "judgment",
    "remarks",
    "test_version",
    "tester",
    "test_date",
)

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_CELL_MAX_LEN = 32000

# 用于识别表头续行（case.xlsx 模板表头占 13、14 两行）
_HEADER_LABELS = {
    "测试用例id", "测试类型", "需求id", "设计方法", "测试用例描述",
    "前置条件", "测试步骤", "预期结果", "优先级", "实际结果", "判断依据",
    "备注", "测试版本", "实施者", "测试日期", "版本变更记录",
}


class CaseMergeError(Exception):
    """合并失败（文件格式不符、没有可用用例等），由 API 层转为 400。"""


def _sanitize_value(value: Any) -> Any:
    """清理单元格值：去掉 openpyxl 不支持的控制字符与 WPS 图片公式。"""
    if not isinstance(value, str):
        return value
    # WPS 的 DISPIMG 图片公式依赖 cellimages.xml，跨工作簿复制会变成坏公式
    if "_xlfn.DISPIMG" in value:
        return ""
    value = _CONTROL_CHARS_RE.sub("", value)
    if len(value) > _CELL_MAX_LEN:
        value = value[:_CELL_MAX_LEN] + "\n... (内容过长已截断)"
    return value


def _copy_cell_style(src, dst) -> None:
    """复制单元格样式（字体/填充/边框/对齐/数字格式）。"""
    try:
        dst.font = copy.copy(src.font)
        dst.fill = copy.copy(src.fill)
        dst.border = copy.copy(src.border)
        dst.alignment = copy.copy(src.alignment)
        dst.protection = copy.copy(src.protection)
        dst.number_format = src.number_format
    except Exception:
        # 个别自定义样式复制失败时不阻塞合并，保留目标表原有样式
        pass


def _is_header_row(ws, row: int) -> bool:
    """判断某行是否仍是表头（模板的表头可能跨两行）。"""
    hits = 0
    for col in range(1, min(ws.max_column or 0, 30) + 1):
        value = ws.cell(row=row, column=col).value
        if value in (None, ""):
            continue
        text = str(value).replace("\n", " ").replace("\r", "").strip().lower()
        if not text:
            continue
        if any(label in text for label in _HEADER_LABELS):
            hits += 1
    return hits >= 2


def _effective_data_start(ws, header_row: Optional[int], data_start: int) -> int:
    """跳过表头续行，返回第一条真正可写入用例的行号。"""
    row = data_start
    limit = (header_row or data_start) + 5
    while row <= limit and row <= (ws.max_row or data_start) and _is_header_row(ws, row):
        row += 1
    return row


def _last_content_row(ws, data_start: int, columns: Iterable[int]) -> int:
    """返回数据区最后一个有内容的行号（没有内容时返回 data_start-1）。"""
    last = data_start - 1
    max_row = ws.max_row or 0
    columns = [c for c in columns if c]
    for row in range(data_start, max_row + 1):
        for col in columns:
            if ws.cell(row=row, column=col).value not in (None, ""):
                last = row
                break
    return last


class CaseMerger:
    """主用例 / 来源用例两个工作簿的合并器。"""

    def __init__(self):
        self.main_handler: Optional[ExcelHandler] = None
        self.source_handler: Optional[ExcelHandler] = None
        self._source_cases: Dict[str, Any] = {}
        self._sheet_layouts: Dict[Tuple[str, str], tuple] = {}

    # ------------------------------------------------------------------
    # 加载与布局
    # ------------------------------------------------------------------
    def _load(self, main_path: str, source_path: str) -> None:
        for label, path in (("主用例", main_path), ("来源用例", source_path)):
            if not path or not os.path.exists(path):
                raise CaseMergeError(f"{label}文件不存在")
            if not path.lower().endswith((".xlsx", ".xlsm")):
                raise CaseMergeError(f"{label}文件必须是 .xlsx 格式")

        self.main_handler = ExcelHandler()
        self.source_handler = ExcelHandler()
        try:
            self.main_handler.load(main_path)
        except Exception as exc:  # noqa: BLE001
            raise CaseMergeError(f"主用例文件解析失败：{exc}") from exc
        try:
            self.source_handler.load(source_path)
        except Exception as exc:  # noqa: BLE001
            raise CaseMergeError(
                f"来源用例文件解析失败：{exc}（请确认表格为 case.xlsx 模板格式）"
            ) from exc

        self._source_cases = {
            (getattr(tc, "case_key", "") or f"{tc.source_sheet}:{tc.row_number}:{tc.case_id}"): tc
            for tc in self.source_handler.test_cases
        }

    def _layout(self, role: str, sheet_name: str) -> tuple:
        """返回 (worksheet, header_row, data_start_row, col_map, result_map)。"""
        key = (role, sheet_name)
        if key in self._sheet_layouts:
            return self._sheet_layouts[key]

        handler = self.main_handler if role == "main" else self.source_handler
        if handler is None or not handler.workbook:
            raise CaseMergeError("工作簿尚未加载")
        ws = handler.workbook[sheet_name]
        header_row, data_start, col_map, result_map = handler._detect_sheet_layout(ws)  # noqa: SLF001
        data_start = _effective_data_start(ws, header_row, data_start)
        handler._normalize_judgment_header(  # noqa: SLF001
            ws, header_row, result_map.get("judgment", 0)
        )
        info = (ws, header_row, data_start, col_map, result_map)
        self._sheet_layouts[key] = info
        return info

    @staticmethod
    def _match_target_sheet(main_wb, source_sheet_name: str) -> Optional[str]:
        """在同名 / 同类别中寻找主工作簿的目标 Sheet。"""
        if source_sheet_name in main_wb.sheetnames:
            return source_sheet_name
        category = ExcelHandler.sheet_category(source_sheet_name)
        if not category:
            return None
        for name in main_wb.sheetnames:
            if (
                ExcelHandler.is_supported_test_sheet(name)
                and ExcelHandler.sheet_category(name) == category
            ):
                return name
        return None

    def _explicit_case_id(self, sheet_name: str, row: int, col_map: Dict[str, int]) -> str:
        """来源行是否真的写了用例ID（而非 ExcelHandler 自动生成的占位ID）。"""
        if not self.source_handler or not self.source_handler.workbook:
            return ""
        ws = self.source_handler.workbook[sheet_name]
        col = col_map.get("case_id")
        if not col:
            return ""
        value = ws.cell(row=row, column=col).value
        return str(value).strip() if value not in (None, "") else ""

    # ------------------------------------------------------------------
    # 预览
    # ------------------------------------------------------------------
    def preview(self, main_path: str, source_path: str) -> Dict[str, Any]:
        """解析两个工作簿，返回主用例 Sheet 概况与来源可选用例列表。"""
        self._load(main_path, source_path)
        assert self.main_handler and self.main_handler.workbook
        assert self.source_handler and self.source_handler.workbook

        main_wb = self.main_handler.workbook
        source_wb = self.source_handler.workbook

        main_sheets: List[Dict[str, Any]] = []
        for name in ExcelHandler.ordered_test_sheet_names(main_wb):
            count = sum(
                1 for tc in self.main_handler.test_cases if tc.source_sheet == name
            )
            main_sheets.append({
                "name": name,
                "category": ExcelHandler.sheet_category(name) or "",
                "case_count": count,
            })

        source_sheets: List[Dict[str, Any]] = []
        cases: List[Dict[str, Any]] = []

        for name in ExcelHandler.ordered_test_sheet_names(source_wb):
            ws, header_row, data_start, col_map, _result_map = self._layout("source", name)
            target = self._match_target_sheet(main_wb, name)
            source_cases = [
                tc for tc in self.source_handler.test_cases if tc.source_sheet == name
            ]
            source_sheets.append({
                "name": name,
                "category": ExcelHandler.sheet_category(name) or "",
                "target_sheet": target or "",
                "case_count": len(source_cases),
            })

            for tc in source_cases:
                key = tc.case_key or f"{tc.source_sheet}:{tc.row_number}:{tc.case_id}"
                explicit = self._explicit_case_id(name, tc.row_number, col_map)
                cases.append({
                    "case_key": key,
                    "case_id": tc.case_id,
                    "explicit_id": explicit,
                    "source_sheet": name,
                    "target_sheet": target or name,
                    "category": ExcelHandler.sheet_category(name) or "",
                    "row_number": tc.row_number,
                    "test_type": tc.test_type,
                    "requirement_id": tc.requirement_id,
                    "description": tc.description,
                    "prerequisites": tc.prerequisites,
                    "test_steps": tc.test_steps,
                    "expected_result": tc.expected_result,
                    "priority": tc.priority,
                })

        if not cases:
            raise CaseMergeError(
                "来源文件中没有解析到用例，请确认表格为 case.xlsx 模板格式"
                "（Sheet 名含「功能」「故障」「压力」「稳定」等）"
            )

        return {
            "main_sheets": main_sheets,
            "source_sheets": source_sheets,
            "cases": cases,
        }

    # ------------------------------------------------------------------
    # 合并
    # ------------------------------------------------------------------
    @staticmethod
    def _copy_header_area(src_ws, dst_ws, header_end_row: int) -> None:
        """新建目标 Sheet 时复制来源表头区（含合并单元格、行高、列宽）。"""
        max_col = max(src_ws.max_column or 1, dst_ws.max_column or 1)
        for row in range(1, header_end_row + 1):
            for col in range(1, max_col + 1):
                src_cell = src_ws.cell(row=row, column=col)
                dst_cell = dst_ws.cell(row=row, column=col, value=_sanitize_value(src_cell.value))
                _copy_cell_style(src_cell, dst_cell)
            height = src_ws.row_dimensions[row].height
            if height:
                dst_ws.row_dimensions[row].height = height

        for col_letter, dimension in src_ws.column_dimensions.items():
            if dimension.width:
                dst_ws.column_dimensions[col_letter].width = dimension.width

        for rng in src_ws.merged_cells.ranges:
            if rng.max_row <= header_end_row:
                try:
                    dst_ws.merge_cells(
                        start_row=rng.min_row, start_column=rng.min_col,
                        end_row=rng.max_row, end_column=rng.max_col,
                    )
                except Exception:
                    pass

    @staticmethod
    def _copy_row_values(
        src_ws,
        dst_ws,
        src_row: int,
        dst_row: int,
        pairs: Sequence[Tuple[int, int]],
    ) -> None:
        """复制一行中指定列的值与样式，并复制来源行高。"""
        for src_col, dst_col in pairs:
            src_cell = src_ws.cell(row=src_row, column=src_col)
            dst_cell = dst_ws.cell(row=dst_row, column=dst_col)
            dst_cell.value = _sanitize_value(src_cell.value)
            _copy_cell_style(src_cell, dst_cell)
        height = src_ws.row_dimensions[src_row].height
        if height:
            dst_ws.row_dimensions[dst_row].height = height

    @staticmethod
    def _copy_merged_ranges(
        src_ws,
        dst_ws,
        row_map: Dict[int, int],
        allowed_columns: set,
    ) -> None:
        """把落在已复制行/列内的合并单元格映射到目标行。"""
        for rng in src_ws.merged_cells.ranges:
            src_rows = list(range(rng.min_row, rng.max_row + 1))
            if not all(r in row_map for r in src_rows):
                continue
            dst_rows = [row_map[r] for r in src_rows]
            if dst_rows != list(range(min(dst_rows), max(dst_rows) + 1)):
                continue
            columns = range(rng.min_col, rng.max_col + 1)
            if not all(c in allowed_columns for c in columns):
                continue
            try:
                dst_ws.merge_cells(
                    start_row=min(dst_rows), start_column=rng.min_col,
                    end_row=max(dst_rows), end_column=rng.max_col,
                )
            except Exception:
                pass

    @staticmethod
    def _extend_stat_formulas(ws, data_start: int, final_last_row: int) -> None:
        """把 Sheet 顶部统计公式（如 =COUNTA(B15:B194)）覆盖到最新数据末行。"""
        if final_last_row <= data_start:
            return
        pattern = re.compile(r"([A-Za-z$]+)(\d+):([A-Za-z$]+)(\d+)")

        def replace(match: re.Match) -> str:
            start, end = int(match.group(2)), int(match.group(4))
            if start >= data_start and end < final_last_row:
                return f"{match.group(1)}{start}:{match.group(3)}{final_last_row}"
            return match.group(0)

        for row in range(1, max(1, data_start)):
            for col in range(1, min(ws.max_column or 0, 10) + 1):
                value = ws.cell(row=row, column=col).value
                if isinstance(value, str) and value.startswith("="):
                    ws.cell(row=row, column=col).value = pattern.sub(replace, value)

    @staticmethod
    def _extend_auto_filter(ws, header_row: Optional[int], data_last_row: int) -> None:
        """自动筛选区域随数据向下延伸（只扩大，不缩小）。"""
        if not header_row or data_last_row <= 0:
            return
        if ws.auto_filter.ref:
            min_col, min_row, max_col, max_row = range_boundaries(ws.auto_filter.ref)
            if max_row < data_last_row:
                ws.auto_filter.ref = (
                    f"{get_column_letter(min_col)}{min_row}:"
                    f"{get_column_letter(max_col)}{data_last_row}"
                )
        else:
            ws.auto_filter.ref = (
                f"A{header_row}:"
                f"{get_column_letter(max(ws.max_column or 1, 1))}{data_last_row}"
            )

    def merge(
        self,
        main_path: str,
        source_path: str,
        case_keys: Sequence[str],
        output_path: str,
        *,
        include_results: bool = False,
        skip_duplicates: bool = True,
    ) -> Dict[str, Any]:
        """把选中的来源用例追加到主用例，保存为 ``output_path``。"""
        if not case_keys:
            raise CaseMergeError("请至少选择一条来源用例")

        self._load(main_path, source_path)
        assert self.main_handler and self.main_handler.workbook
        assert self.source_handler and self.source_handler.workbook

        selected = []
        for key in case_keys:
            tc = self._source_cases.get(key)
            if tc is None:
                raise CaseMergeError(f"来源用例不存在或已失效：{key}")
            selected.append(tc)

        main_wb = self.main_handler.workbook
        source_wb = self.source_handler.workbook

        # 主用例中已存在的用例ID，用于跳过重复
        existing_ids = {
            str(tc.case_id).strip().lower()
            for tc in self.main_handler.test_cases
            if str(tc.case_id).strip()
        }

        grouped: Dict[str, List[Any]] = {}
        for tc in selected:
            grouped.setdefault(tc.source_sheet, []).append(tc)

        merged_count = 0
        skipped: List[str] = []
        warnings: List[str] = []
        sheet_counts: Dict[str, int] = {}
        created_sheets: List[str] = []

        for source_sheet, source_cases in grouped.items():
            src_ws, src_header_row, src_data_start, src_col_map, src_result_map = (
                self._layout("source", source_sheet)
            )
            target_sheet = self._match_target_sheet(main_wb, source_sheet)
            created = False
            if not target_sheet:
                # 主用例缺少同类 Sheet：新建并复制来源表头
                base = source_sheet
                target_sheet = base
                suffix = 2
                while target_sheet in main_wb.sheetnames:
                    target_sheet = f"{base}_{suffix}"
                    suffix += 1
                main_wb.create_sheet(target_sheet)
                self._copy_header_area(
                    src_ws, main_wb[target_sheet], max(src_data_start - 1, 1)
                )
                created = True
                created_sheets.append(target_sheet)
                warnings.append(
                    f"主用例中没有「{source_sheet}」对应的 Sheet，已新建「{target_sheet}」"
                )

            if created:
                dst_ws = main_wb[target_sheet]
                dst_header_row = src_header_row
                dst_data_start = src_data_start
                dst_col_map = src_col_map
                dst_result_map = src_result_map
            else:
                dst_ws, dst_header_row, dst_data_start, dst_col_map, dst_result_map = (
                    self._layout("main", target_sheet)
                )

            # 复制列：定义列按列号对齐；结果列按字段名对齐
            if src_col_map and dst_col_map:
                src_def_cols = sorted({c for c in src_col_map.values() if c})
                dst_def_cols = sorted({c for c in dst_col_map.values() if c})
                if src_def_cols and dst_def_cols and src_def_cols == dst_def_cols:
                    definition_pairs = [(c, c) for c in src_def_cols]
                else:
                    definition_pairs = []
                    seen = set()
                    for field in DEFINITION_FIELDS:
                        src_col = src_col_map.get(field)
                        dst_col = dst_col_map.get(field)
                        if src_col and dst_col and (src_col, dst_col) not in seen:
                            definition_pairs.append((src_col, dst_col))
                            seen.add((src_col, dst_col))

                result_pairs = []
                if include_results:
                    seen = set()
                    for field in RESULT_FIELDS:
                        src_col = src_result_map.get(field)
                        dst_col = dst_result_map.get(field)
                        if src_col and dst_col and (src_col, dst_col) not in seen:
                            result_pairs.append((src_col, dst_col))
                            seen.add((src_col, dst_col))
            else:
                definition_pairs = []
                result_pairs = []

            if not definition_pairs:
                raise CaseMergeError(
                    f"无法识别「{source_sheet}」或「{target_sheet}」的用例列布局"
                )

            # 过滤重复用例
            rows_to_copy: List[Tuple[int, Any]] = []
            for tc in source_cases:
                explicit_id = self._explicit_case_id(
                    source_sheet, tc.row_number, src_col_map
                )
                if (
                    skip_duplicates
                    and explicit_id
                    and explicit_id.strip().lower() in existing_ids
                ):
                    skipped.append(
                        tc.case_key
                        or f"{tc.source_sheet}:{tc.row_number}:{tc.case_id}"
                    )
                    continue
                rows_to_copy.append((tc.row_number, tc))
                if explicit_id:
                    existing_ids.add(explicit_id.strip().lower())

            if not rows_to_copy:
                continue

            allowed_columns = {dst for _src, dst in definition_pairs + result_pairs}
            # 判断“最后一条用例”时同时查看定义列与结果列，避免覆盖已有内容
            content_columns = sorted(
                allowed_columns
                | {c for c in dst_col_map.values() if c}
                | {c for c in dst_result_map.values() if c}
            )
            target_last = _last_content_row(dst_ws, dst_data_start, content_columns)
            # 避免写入与已有合并单元格重叠的区域
            start_row = max(dst_data_start, target_last + 1)
            for rng in dst_ws.merged_cells.ranges:
                if rng.min_row >= dst_data_start and rng.max_row >= start_row:
                    start_row = max(start_row, rng.max_row + 1)

            row_map: Dict[int, int] = {}
            for offset, (src_row, _tc) in enumerate(rows_to_copy):
                dst_row = start_row + offset
                row_map[src_row] = dst_row
                self._copy_row_values(
                    src_ws, dst_ws, src_row, dst_row,
                    definition_pairs + result_pairs,
                )
                merged_count += 1
                sheet_counts[target_sheet] = sheet_counts.get(target_sheet, 0) + 1

            self._copy_merged_ranges(src_ws, dst_ws, row_map, allowed_columns)

            final_last = start_row + len(rows_to_copy) - 1
            self._extend_stat_formulas(dst_ws, dst_data_start, final_last)
            self._extend_auto_filter(dst_ws, dst_header_row, final_last)

        if merged_count == 0:
            raise CaseMergeError("没有可合并的用例（所选用例均已跳过）")

        # 修复「数据统计」页跨表汇总公式（统计块引用本 Sheet 的 Total 等）
        try:
            ExcelHandler.refresh_statistics_summary(main_wb)
        except Exception:
            pass

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        main_wb.save(output_path)

        return {
            "merged_count": merged_count,
            "skipped_duplicates": skipped,
            "warnings": warnings,
            "sheet_counts": sheet_counts,
            "created_sheets": created_sheets,
        }
