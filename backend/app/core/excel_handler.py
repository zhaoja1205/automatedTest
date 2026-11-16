"""
Excel 用例表加载与结果回写。

与原 PyQt 版保持兼容的列映射与动态表头识别。
"""
import os
import re
from dataclasses import asdict
from datetime import datetime, date
from typing import List, Optional, Dict, Any, Tuple
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

from app.core.test_case import TestCase
from app.core.remarks import (
    build_judgment_from_case,
    build_log_remark_from_case,
    extract_evidence_lines,
    extract_log_section,
    read_log_content,
)


class ExcelHandler:
    """
    Excel 工作簿的加载、布局探测、用例构建与结果保存。
    """

    @staticmethod
    def is_supported_test_sheet(sheet_name: str) -> bool:
        """判断工作表是否视为「用例表」"""
        if not sheet_name or not str(sheet_name).strip():
            return False
        n = str(sheet_name).strip()
        nl = n.lower()
        if "功能" in n or "functional" in nl:
            return True
        if "故障" in n or "fault" in nl:
            return True
        if "稳定" in n or "stability" in nl:
            return True
        if "异常" in n or "abnormal" in nl or "exception" in nl:
            return True
        if "压力" in n or "stress" in nl or "pressure" in nl:
            return True
        return False

    @staticmethod
    def sheet_category(sheet_name: str) -> Optional[str]:
        """将工作表名归类到界面套件：functional / fault / stability / abnormal / stress"""
        if not sheet_name or not str(sheet_name).strip():
            return None
        s = str(sheet_name).strip()
        sl = s.lower()
        if "功能" in s or "functional" in sl:
            return "functional"
        if "故障" in s or "fault" in sl:
            return "fault"
        if "稳定" in s or "stability" in sl:
            return "stability"
        if "异常" in s or "abnormal" in sl or "exception" in sl:
            return "abnormal"
        if "压力" in s or "stress" in sl or "pressure" in sl:
            return "stress"
        return None

    @staticmethod
    def ordered_test_sheet_names(workbook: Workbook) -> List[str]:
        """按 功能 → 故障 → 异常 → 压力 → 稳定 → 其它已识别 的顺序排列工作表名"""
        names = [x for x in workbook.sheetnames if ExcelHandler.is_supported_test_sheet(x)]

        def sort_key(name: str):
            s = name.strip()
            sl = s.lower()
            if "功能" in s or "functional" in sl:
                return (0, s)
            if "故障" in s or "fault" in sl:
                return (1, s)
            if "异常" in s or "abnormal" in sl or "exception" in sl:
                return (2, s)
            if "压力" in s or "stress" in sl or "pressure" in sl:
                return (3, s)
            if "稳定" in s or "stability" in sl:
                return (4, s)
            return (5, s)

        return sorted(names, key=sort_key)

    # ===== BugList 工作表（与 Excel 中的 BugList统计 页同步） =====
    BUGLIST_FIELDS = (
        'no', 'bug_id', 'module', 'description', 'version', 'severity',
        'status', 'tester', 'date', 'effective', 'comment',
    )

    BUGLIST_HEADER_KEYWORDS = {
        'no': ['no.', '序号', '#'],
        'bug_id': ['bug id', 'bug_id', 'bug编号', 'defect id', '缺陷id'],
        'module': ['module', '模块'],
        'description': ['description', '问题描述', '缺陷描述', '描述'],
        'version': ['version', '版本'],
        'severity': ['severity', '严重程度', '严重等级', '等级'],
        'status': ['status', '状态'],
        'tester': ['tester', '测试人员', '实施者'],
        'date': ['date', '日期'],
        'effective': ['effective', '有效性', '是否有效'],
        'comment': ['comment', '备注', '说明'],
    }

    @staticmethod
    def is_buglist_sheet(sheet_name: str) -> bool:
        """判断工作表是否为 BugList / 缺陷列表页"""
        if not sheet_name or not str(sheet_name).strip():
            return False
        n = str(sheet_name).strip()
        nl = n.lower()
        if "buglist" in nl or "bug list" in nl or "defect" in nl:
            return True
        if "bug" in nl and ("统计" in n or "列表" in n or "list" in nl):
            return True
        if "缺陷" in n and ("列表" in n or "统计" in n or "清单" in n):
            return True
        return False

    def find_buglist_sheet_name(self) -> str:
        """返回工作簿中的 BugList 工作表名；不存在时返回空字符串"""
        if not self.workbook:
            return ""
        for name in self.workbook.sheetnames:
            if self.is_buglist_sheet(name):
                return name
        return ""

    # ===== 数据统计页（测试基本信息 / 质量效率目标 / 测试总结） =====

    STATISTICS_LABELS = ("测试基本信息", "质量/效率目标", "测试总结")

    @staticmethod
    def is_statistics_sheet(sheet_name: str) -> bool:
        """判断工作表是否为「数据统计」页（排除 BugList统计）"""
        if not sheet_name or not str(sheet_name).strip():
            return False
        if ExcelHandler.is_buglist_sheet(sheet_name):
            return False
        n = str(sheet_name).strip()
        if n in ("数据统计", "测试数据统计", "统计", "统计表"):
            return True
        return "数据统计" in n

    def find_statistics_sheet_name(self) -> str:
        """返回工作簿中的数据统计页名；不存在时返回空字符串"""
        if not self.workbook:
            return ""
        for name in self.workbook.sheetnames:
            if self.is_statistics_sheet(name):
                return name
        return ""

    @staticmethod
    def _normalize_statistics_label(value: Any) -> str:
        """去掉空白和末尾冒号，便于匹配模板中的栏目标签"""
        text = str(value or "").strip()
        text = text.replace(" ", "").replace("　", "")
        text = text.replace("／", "/")
        return re.sub(r"[：:]$", "", text)

    def fill_statistics_summary(
        self,
        *,
        basic_info: str = "",
        quality_goal: str = "",
        summary: str = "",
    ) -> List[str]:
        """把 AI 文案写入「数据统计」页的三个栏目，返回已填写的栏目名。

        按栏目标签动态定位（标签右侧/合并区域的左上角单元格），
        不依赖固定行号；找不到统计页或栏目时静默跳过。
        """
        import copy

        if not self.workbook:
            return []
        sheet_name = self.find_statistics_sheet_name()
        if not sheet_name:
            return []

        ws = self.workbook[sheet_name]
        texts = {
            "测试基本信息": basic_info or "",
            "质量/效率目标": quality_goal or "",
            "测试总结": summary or "",
        }
        merged_ranges = list(ws.merged_cells.ranges)
        filled: List[str] = []

        for row in range(1, (ws.max_row or 0) + 1):
            for col in range(1, min(ws.max_column or 0, 10) + 1):
                label = self._normalize_statistics_label(
                    ws.cell(row=row, column=col).value
                )
                if label not in texts:
                    continue

                text = texts[label]
                if not text:
                    continue
                text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text).strip()
                if not text:
                    continue
                if len(text) > 8000:
                    text = text[:8000] + "\n... (内容过长已截断)"

                target_row, target_col = row, col + 1
                for merged in merged_ranges:
                    if (merged.min_row <= target_row <= merged.max_row
                            and merged.min_col <= target_col <= merged.max_col):
                        target_row, target_col = merged.min_row, merged.min_col
                        break

                target = ws.cell(row=target_row, column=target_col)
                target.value = text
                alignment = copy.copy(target.alignment)
                alignment.wrap_text = True
                alignment.vertical = "top"
                if not alignment.horizontal:
                    alignment.horizontal = "left"
                target.alignment = alignment

                # 粗略估算行高，避免文字被截断；已有更高行高时保持不变
                chars_per_line = 30
                lines = sum(
                    max(1, (len(part) + chars_per_line - 1) // chars_per_line)
                    for part in (text.splitlines() or [""])
                )
                required = lines * 15 + 4
                current = ws.row_dimensions[target_row].height or 0
                if required > current:
                    ws.row_dimensions[target_row].height = min(required, 300)

                filled.append(label)

        return filled

    # ===== 数据统计页：测试结果汇总公式修复 =====

    STATISTICS_SUMMARY_HEADER = "测试分类"

    @classmethod
    def _sheet_stat_cells(cls, ws) -> Dict[str, str]:
        """定位用例 Sheet 顶部的统计块，返回 {字段: 单元格坐标}。

        模板在每个用例 Sheet 的第 4~9 行放置 Total / Pass / Fail / NT /
        BLOCK / NA，这里按标签动态定位，兼容 A/B 列与 B/C 列两种布局。
        """
        from openpyxl.utils import get_column_letter

        max_row = min(ws.max_row or 0, 20)
        max_col = min(ws.max_column or 0, 10)
        label_col = total_row = None
        for row in range(1, max_row + 1):
            for col in range(1, max_col + 1):
                text = str(ws.cell(row=row, column=col).value or "").strip().lower()
                if text == "total":
                    label_col, total_row = col, row
                    break
            if total_row is not None:
                break
        if total_row is None or label_col is None:
            return {}

        value_col = label_col + 1
        letter = get_column_letter(value_col)
        cells = {"total": f"{letter}{total_row}"}
        last_row = min(total_row + 8, (ws.max_row or total_row) + 1)
        for row in range(total_row + 1, last_row):
            label = str(ws.cell(row=row, column=label_col).value or "").strip().lower()
            if label in ("pass", "fail", "nt", "block", "na"):
                cells[label] = f"{letter}{row}"
        return cells

    @classmethod
    def _statistics_summary_columns(cls, ws, header_row: int, label_col: int) -> Dict[str, int]:
        """定位数据统计页表头的汇总列（总数/执行数/各状态/各比率）。"""
        from openpyxl.utils import get_column_letter

        max_col = min(ws.max_column or 0, 20)
        columns: Dict[str, int] = {}
        fallback = (
            "total", "executed", "pass", "fail", "nt", "block", "na",
            "execute_rate", "pass_rate", "fail_rate", "block_rate",
        )
        for offset, field in enumerate(fallback, start=1):
            columns[field] = label_col + offset

        for col in range(label_col + 1, max_col + 1):
            text = cls._normalize_statistics_label(
                ws.cell(row=header_row, column=col).value
            )
            if not text:
                continue
            key = text.lower()
            if key == "总数":
                columns["total"] = col
            elif key.startswith("执行数量"):
                columns["executed"] = col
            elif key == "pass":
                columns["pass"] = col
            elif key == "fail":
                columns["fail"] = col
            elif key == "nt":
                columns["nt"] = col
            elif key == "block":
                columns["block"] = col
            elif key == "na":
                columns["na"] = col
            elif key == "执行率":
                columns["execute_rate"] = col
            elif key == "pass率":
                columns["pass_rate"] = col
            elif key == "fail率":
                columns["fail_rate"] = col
            elif key == "block率":
                columns["block_rate"] = col
        return columns

    @classmethod
    def refresh_statistics_summary(cls, workbook) -> bool:
        """按工作簿中实际存在的用例 Sheet 重写「数据统计」页汇总公式。

        人工增删或重建 Sheet 后，Excel 的跨表引用很容易变成 #REF!，
        导致「测试结果汇总」无法统计。这里按行标签重新匹配 Sheet：
        - 找到同名（或同类）Sheet 时，引用其 Total / Pass / Fail / NT /
          BLOCK / NA 统计单元格；
        - 找不到对应 Sheet 的分类行填 0；
        - 「合计」行统一改为 SUM，避免遗留手写的固定引用。

        返回是否找到并处理了「数据统计」页。
        """
        from openpyxl.utils import get_column_letter

        stat_ws = None
        for name in workbook.sheetnames:
            if cls.is_statistics_sheet(name):
                stat_ws = workbook[name]
                break
        if stat_ws is None:
            return False

        max_row = stat_ws.max_row or 0
        max_col = min(stat_ws.max_column or 0, 20)
        header_row = label_col = None
        for row in range(1, min(max_row, 20) + 1):
            for col in range(1, min(max_col, 10) + 1):
                text = cls._normalize_statistics_label(
                    stat_ws.cell(row=row, column=col).value
                )
                if text == cls.STATISTICS_SUMMARY_HEADER:
                    header_row, label_col = row, col
                    break
            if header_row is not None:
                break
        if header_row is None or label_col is None:
            return False

        columns = cls._statistics_summary_columns(stat_ws, header_row, label_col)

        total_row = None
        for row in range(header_row + 1, max_row + 1):
            label = cls._normalize_statistics_label(
                stat_ws.cell(row=row, column=label_col).value
            )
            if label.lower() in ("合计", "总计", "total"):
                total_row = row
                break

        def _match_sheet(label: str) -> Optional[str]:
            test_sheets = [
                name for name in workbook.sheetnames
                if cls.is_supported_test_sheet(name)
            ]
            for name in test_sheets:
                if str(name).strip() == label:
                    return name
            category = cls.sheet_category(label)
            if category:
                for name in test_sheets:
                    if cls.sheet_category(name) == category:
                        return name
            return None

        def _ref(sheet_name: str, cell: str) -> str:
            escaped = sheet_name.replace("'", "''")
            return f"'{escaped}'!{cell}"

        status_fields = ("pass", "fail", "nt", "block", "na")
        data_last_row = (total_row - 1) if total_row else max_row
        for row in range(header_row + 1, data_last_row + 1):
            label = cls._normalize_statistics_label(
                stat_ws.cell(row=row, column=label_col).value
            )
            if not label:
                continue

            sheet_name = _match_sheet(label)
            if not sheet_name and not cls.sheet_category(label):
                # 非测试分类行（说明文字、备注等）：清掉残留的 #REF!，
                # 避免其污染「合计」行的 SUM 公式
                for field in ("total", "executed") + status_fields:
                    cell = stat_ws.cell(row=row, column=columns[field])
                    if isinstance(cell.value, str) and "#REF" in cell.value:
                        cell.value = 0
                continue
            stat_cells = cls._sheet_stat_cells(workbook[sheet_name]) if sheet_name else {}
            if stat_cells.get("total"):
                stat_ws.cell(
                    row=row, column=columns["total"],
                    value=f"={_ref(sheet_name, stat_cells['total'])}",
                )
                executed_parts = [
                    _ref(sheet_name, stat_cells[field])
                    if field in stat_cells else "0"
                    for field in ("pass", "fail", "block")
                ]
                stat_ws.cell(
                    row=row, column=columns["executed"],
                    value="=" + "+".join(executed_parts),
                )
                for field in status_fields:
                    value = (
                        f"={_ref(sheet_name, stat_cells[field])}"
                        if field in stat_cells else 0
                    )
                    stat_ws.cell(row=row, column=columns[field], value=value)
            else:
                for field in ("total", "executed") + status_fields:
                    stat_ws.cell(row=row, column=columns[field], value=0)

            totals_col = get_column_letter(columns["total"])
            executed_col = get_column_letter(columns["executed"])
            stat_ws.cell(
                row=row, column=columns["execute_rate"],
                value=f'=IFERROR({executed_col}{row}/{totals_col}{row},"")',
            )
            for field, numerator in (
                ("pass_rate", "pass"), ("fail_rate", "fail"), ("block_rate", "block"),
            ):
                numerator_col = get_column_letter(columns[numerator])
                stat_ws.cell(
                    row=row, column=columns[field],
                    value=f'=IFERROR({numerator_col}{row}/{executed_col}{row},"")',
                )

        if total_row:
            for field in ("total", "executed") + status_fields:
                col = get_column_letter(columns[field])
                stat_ws.cell(
                    row=total_row, column=columns[field],
                    value=f"=SUM({col}{header_row + 1}:{col}{data_last_row})",
                )
            totals_col = get_column_letter(columns["total"])
            executed_col = get_column_letter(columns["executed"])
            stat_ws.cell(
                row=total_row, column=columns["execute_rate"],
                value=f'=IFERROR({executed_col}{total_row}/{totals_col}{total_row},"")',
            )
            for field, numerator in (
                ("pass_rate", "pass"), ("fail_rate", "fail"), ("block_rate", "block"),
            ):
                numerator_col = get_column_letter(columns[numerator])
                stat_ws.cell(
                    row=total_row, column=columns[field],
                    value=f'=IFERROR({numerator_col}{total_row}/{executed_col}{total_row},"")',
                )
        return True

    @staticmethod
    def _format_cell_value(value: Any) -> str:
        """把 BugList 单元格值规范化为前端可展示的字符串"""
        if value is None:
            return ""
        if isinstance(value, datetime):
            if value.hour == 0 and value.minute == 0 and value.second == 0:
                return value.strftime("%Y-%m-%d")
            return value.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(value, date):
            return value.strftime("%Y-%m-%d")
        if isinstance(value, bool):
            return "是" if value else "否"
        return str(value).strip()

    @classmethod
    def _map_header_columns(
        cls, ws, header_row: int, keywords: Dict[str, List[str]]
    ) -> Dict[str, int]:
        """按表头关键词定位列号"""
        col_map: Dict[str, int] = {}
        max_col = ws.max_column or 30
        for col in range(1, max_col + 1):
            cell = cls._cell_text(ws, header_row, col)
            if not cell:
                continue
            for field, kws in keywords.items():
                if field in col_map:
                    continue
                for kw in kws:
                    if kw.lower() in cell:
                        col_map[field] = col
                        break
        return col_map

    def load_bug_list(self) -> List[Dict[str, Any]]:
        """解析 BugList 页，返回与 Excel 中该页一致的结构化数据"""
        self.bug_list = []
        self.bug_sheet_name = self.find_buglist_sheet_name()
        self._buglist_header_row = 0
        self._buglist_col_map = {}
        if not self.bug_sheet_name:
            return self.bug_list

        ws = self.workbook[self.bug_sheet_name]
        header_row, col_map = self._detect_buglist_layout(ws)
        if header_row is None or not col_map:
            return self.bug_list

        self._buglist_header_row = header_row
        self._buglist_col_map = col_map
        max_row = ws.max_row or 0

        for row in range(header_row + 1, max_row + 1):
            values = {
                field: self._format_cell_value(ws.cell(row=row, column=col).value)
                for field, col in col_map.items()
            }
            # 跳过整行空数据（模板预留了大量空白行）
            if not any(values.values()):
                continue
            entry: Dict[str, Any] = {
                field: values.get(field, "") for field in self.BUGLIST_FIELDS
            }
            entry["row_number"] = row
            entry["source_sheet"] = self.bug_sheet_name
            self.bug_list.append(entry)

        # 已有结果文件中新增 Bug 行可能还没有表格样式，加载时补齐，
        # 保证下载结果里的 BugList 页行数与样式一致。
        max_row = max(
            (int(e.get("row_number") or 0) for e in self.bug_list), default=0
        )
        if max_row > self._buglist_header_row:
            try:
                self._extend_buglist_row_styles(
                    ws, self._buglist_header_row, col_map, max_row
                )
            except Exception:
                pass
        return self.bug_list

    def _detect_buglist_layout(self, ws) -> tuple:
        """定位 BugList 表头行与列映射；表头不存在时返回 (None, {})"""
        max_row = ws.max_row or 0
        scan_rows = min(max_row, 20)

        header_row = None
        best_count = 1
        for row in range(1, scan_rows + 1):
            count = self._count_header_matches(ws, row, self.BUGLIST_HEADER_KEYWORDS)
            if count > best_count:
                best_count = count
                header_row = row
        if header_row is None:
            return None, {}

        return header_row, self._map_header_columns(
            ws, header_row, self.BUGLIST_HEADER_KEYWORDS
        )

    @staticmethod
    def _default_buglist_col_map() -> Dict[str, int]:
        """模板默认列位（B 列开始，1-based）"""
        return {
            "no": 2, "bug_id": 3, "module": 4, "description": 5,
            "version": 6, "severity": 7, "status": 8, "tester": 9,
            "date": 10, "effective": 11, "comment": 12,
        }

    def _ensure_buglist_sheet(self):
        """确保工作簿中存在 BugList 页和表头，返回 (worksheet, header_row, col_map)"""
        if not self.bug_sheet_name:
            self.bug_sheet_name = self.find_buglist_sheet_name()
        if not self.bug_sheet_name:
            # 工作簿没有 BugList 页时自动创建，保证失败用例有登记位置
            self.bug_sheet_name = "BugList统计"
            ws = self.workbook.create_sheet(self.bug_sheet_name)
            self._buglist_header_row = 0
            self._buglist_col_map = {}
        else:
            ws = self.workbook[self.bug_sheet_name]

        header_row, col_map = self._detect_buglist_layout(ws)
        if header_row is not None and col_map:
            self._buglist_header_row = header_row
            self._buglist_col_map = col_map
            return ws, header_row, col_map

        # 新页或空白页：写入表头（与模板保持一致：第 2 行、B~L 列）
        header_row = 2
        col_map = self._default_buglist_col_map()
        for field, col in col_map.items():
            title = {
                "no": "No.", "bug_id": "Bug ID", "module": "Module",
                "description": "Description", "version": "Version",
                "severity": "Severity", "status": "Status", "tester": "Tester",
                "date": "Date", "effective": "Effective", "comment": "Comment",
            }[field]
            cell = ws.cell(row=header_row, column=col)
            cell.value = title
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(
                start_color="4472C4", end_color="4472C4", fill_type="solid"
            )
            cell.alignment = Alignment(horizontal="center", vertical="center")

        widths = {
            "B": 9, "C": 17, "D": 27, "E": 56, "F": 30,
            "G": 14, "H": 12, "I": 11, "J": 11, "K": 10, "L": 18,
        }
        for letter, width in widths.items():
            ws.column_dimensions[letter].width = max(
                width, ws.column_dimensions[letter].width or 0
            )

        self._buglist_header_row = header_row
        self._buglist_col_map = col_map
        return ws, header_row, col_map

    @staticmethod
    def _buglist_last_formatted_row(ws, header_row: int, col_map: Dict[str, int]) -> int:
        """返回 BugList 页最后一个画有边框的数据行（没有时为 header_row）。"""
        last = header_row
        for row in range(header_row + 1, (ws.max_row or header_row) + 1):
            for col in col_map.values():
                border = ws.cell(row=row, column=col).border
                if any(
                    side is not None and side.style
                    for side in (border.left, border.right, border.top, border.bottom)
                ):
                    last = row
                    break
        return last

    def _extend_buglist_row_styles(
        self, ws, header_row: int, col_map: Dict[str, int], last_row: int
    ):
        """把 BugList 数据行的表格样式向下扩展到 ``last_row``。

        模板只预先画了少量带边框的数据行，新增 Bug 超出行数时如果不复制样式，
        后面的行会变成没有边框、行高很小的“裸行”，看起来就像行数没有增加。
        """
        from copy import copy

        if last_row <= header_row:
            return
        cols = sorted(set(col_map.values()))
        formatted_last = self._buglist_last_formatted_row(ws, header_row, col_map)

        if formatted_last <= header_row:
            # 没有可参考的数据行样式：补一套基础边框
            thin = Side(style="thin")
            border = Border(left=thin, right=thin, top=thin, bottom=thin)
            for row in range(header_row + 1, last_row + 1):
                for col in cols:
                    cell = ws.cell(row=row, column=col)
                    cell.border = border
                    alignment = copy(cell.alignment)
                    alignment.vertical = "top"
                    alignment.wrap_text = True
                    cell.alignment = alignment
                if (ws.row_dimensions[row].height or 0) < 30:
                    ws.row_dimensions[row].height = 30
            return

        if last_row <= formatted_last:
            return

        # 复制“中间行”的样式，避免把模板最后一行的加粗底边复制到每一行
        source_row = formatted_last - 1 if formatted_last - 1 > header_row else formatted_last
        final_bottom = {
            col: copy(ws.cell(row=formatted_last, column=col).border.bottom)
            for col in cols
        }

        # 原来的最后一行变成中间行，底边恢复成普通边框
        for col in cols:
            cell = ws.cell(row=formatted_last, column=col)
            border = cell.border
            source_border = ws.cell(row=source_row, column=col).border
            cell.border = Border(
                left=border.left, right=border.right, top=border.top,
                bottom=copy(source_border.bottom),
            )

        row_height = (
            ws.row_dimensions[formatted_last].height
            or ws.row_dimensions[header_row].height
        )
        for row in range(formatted_last + 1, last_row + 1):
            for col in cols:
                ws.cell(row=row, column=col)._style = copy(
                    ws.cell(row=source_row, column=col)._style
                )
            if row_height:
                ws.row_dimensions[row].height = row_height

        # 新增区域的最后一行保留模板的加粗底边
        for col in cols:
            cell = ws.cell(row=last_row, column=col)
            border = cell.border
            cell.border = Border(
                left=border.left, right=border.right, top=border.top,
                bottom=final_bottom[col],
            )

    def save_bug_list(self, entries: List[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """将 BugList 条目写回 BugList统计 页（工作簿需已加载）。"""
        if not self.workbook:
            raise ValueError("未加载 Excel 文件")

        entries = self.bug_list if entries is None else entries
        ws, header_row, col_map = self._ensure_buglist_sheet()

        # 已有条目沿用解析出的行号；新条目追加到最后一行之后
        used_rows = {
            int(entry.get("row_number") or 0)
            for entry in entries
            if int(entry.get("row_number") or 0) > header_row
        }
        next_row = max([header_row] + list(used_rows)) + 1
        assigned_rows = set()

        for entry in entries:
            row = int(entry.get("row_number") or 0)
            if row <= header_row or row in assigned_rows:
                while next_row in assigned_rows:
                    next_row += 1
                row = next_row
                next_row += 1
            entry["row_number"] = row
            assigned_rows.add(row)
            entry["source_sheet"] = self.bug_sheet_name

        # 新增行超出模板预留的表格线时，同步复制样式，避免出现无边框的裸行
        if assigned_rows:
            self._extend_buglist_row_styles(
                ws, header_row, col_map, max(assigned_rows)
            )

        for entry in entries:
            row = int(entry.get("row_number") or 0)
            entry["source_sheet"] = self.bug_sheet_name

            for field, col in col_map.items():
                value = entry.get(field, "")
                if value is None:
                    value = ""
                text = str(value)
                text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
                if len(text) > 32000:
                    text = text[:32000] + "\n... (内容过长已截断)"
                ws.cell(row=row, column=col).value = text

        self.bug_list = entries
        return self.bug_list

    # 默认列号兜底（1-based）
    COLUMN_MAP = {
        'case_id': 2,
        'test_type': 3,
        'requirement_id': 4,
        'design_method': 5,
        'description': 6,
        'prerequisites': 7,
        'test_steps': 8,
        'expected_result': 9,
        'priority': 10,
    }

    RESULT_COLUMN_MAP = {
        'actual_result': 12,
        'judgment': 13,
        'remarks': 14,
        'test_version': 15,
        'tester': 16,
        'test_date': 17,
    }

    # 表头关键词
    HEADER_KEYWORDS = {
        'case_id': ['测试用例id', 'test case id', '用例id', 'case id', '用例编号'],
        'test_type': ['测试类型', 'test type'],
        'requirement_id': ['需求id', 'requirement id', '需求编号'],
        'design_method': ['设计方法', 'design method', '用例设计'],
        'description': ['测试用例描述', 'test case desc', '用例描述', 'description'],
        'prerequisites': ['前置条件', 'prerequisites', 'precondition', 'pre-condition'],
        'test_steps': ['测试步骤', 'testing steps', 'test steps', '步骤'],
        'expected_result': ['预期结果', 'expected result', 'expected results'],
        'priority': ['优先级', 'priority'],
    }

    RESULT_HEADER_KEYWORDS = {
        'actual_result': ['实际结果', 'actual result', 'actual results'],
        # BUG 列承载 AI 判定信息；「判断依据」为历史版本用过的表头，保留别名兼容旧文件
        'judgment': ['bug', 'defect', 'bug id', '判断依据'],
        'remarks': ['备注', 'remark', 'note', '测试结果的log'],
        'test_version': ['测试版本', 'test version'],
        'tester': ['实施者', 'implementer', 'tester', '测试人员'],
        'test_date': ['测试日期', 'date', 'test date'],
    }

    HEADER_ROW = 13
    DATA_START_ROW = 15

    # 历史版本曾把 BUG 列表头改为「判断依据」；加载时统一改回 BUG
    LEGACY_BUG_HEADERS = {'判断依据'}

    @classmethod
    def _normalize_bug_header(cls, ws, header_row: Optional[int], col: int) -> bool:
        """把旧版本的「判断依据」列标题改回「BUG」。

        上传的用例文件、历史结果文件都可能保留「判断依据」表头；
        这里在内存中改名，下载副本与执行回写都会使用「BUG」列名。
        返回是否发生了改名。
        """
        if not header_row or not col:
            return False
        for row in range(header_row, header_row + 4):
            cell = ws.cell(row=row, column=col)
            value = str(cell.value or "").strip()
            if value in cls.LEGACY_BUG_HEADERS:
                cell.value = "BUG"
                return True
        return False

    STATUS_COLORS = {
        'Pass': '90EE90',
        'Fail': 'FF6B6B',
        'NT': 'FFFFE0',
        'BLOCK': 'FFA500',
        'NA': 'D3D3D3',
        'Review': '87CEEB',  # 待确认 — 浅蓝色
    }

    def __init__(self, file_path: str = None):
        self.file_path = file_path
        self.workbook: Optional[Workbook] = None
        self.test_cases: List[TestCase] = []
        # BugList 页解析结果（与 Excel 中的 BugList统计 页同步）
        self.bug_list: List[Dict[str, Any]] = []
        self.bug_sheet_name: str = ""
        self._buglist_header_row: int = 0
        self._buglist_col_map: Dict[str, int] = {}

    @classmethod
    def _cell_text(cls, ws, row: int, col: int) -> str:
        """读取单元格并规范化为用于匹配的文本"""
        raw = ws.cell(row=row, column=col).value
        if not raw:
            return ""
        return str(raw).replace('\n', ' ').replace('\r', '').strip().lower()

    @classmethod
    def _count_header_matches(cls, ws, row: int, all_keywords: Dict[str, List[str]]) -> int:
        """计算某行中命中关键词的字段个数"""
        max_col = ws.max_column or 30
        matched_fields = set()
        for col in range(1, max_col + 1):
            cell = cls._cell_text(ws, row, col)
            if not cell:
                continue
            for field, kws in all_keywords.items():
                if field in matched_fields:
                    continue
                for kw in kws:
                    if kw.lower() in cell:
                        matched_fields.add(field)
                        break
        return len(matched_fields)

    @classmethod
    def _find_header_and_data_rows(
        cls, ws, all_keywords: Dict[str, List[str]], scan_rows: int = 25, min_matches: int = 2
    ) -> tuple:
        """定位表头行和数据起始行"""
        best_row = None
        best_count = min_matches - 1

        for row in range(1, scan_rows + 1):
            cnt = cls._count_header_matches(ws, row, all_keywords)
            if cnt > best_count:
                best_count = cnt
                best_row = row

        if best_row is None:
            return None, None

        data_start = best_row + 1
        for r in range(best_row + 1, best_row + 5):
            if r > ws.max_row:
                break
            max_col = ws.max_column or 30
            non_empty = sum(
                1 for c in range(1, max_col + 1)
                if ws.cell(row=r, column=c).value not in (None, "")
            )
            if non_empty >= 2:
                data_start = r
                break

        return best_row, data_start

    @classmethod
    def _detect_column_map(
        cls, ws, header_keywords: Dict[str, List[str]], default_map: Dict[str, int],
        header_row: Optional[int] = None, extra_scan_rows: int = 5,
    ) -> Dict[str, int]:
        """在表头区域扫描单元格，将列标题映射为字段名"""
        detected: Dict[str, int] = {}
        start = header_row if header_row else 1
        end = start + extra_scan_rows

        for row in range(start, end + 1):
            if row > (ws.max_row or 9999):
                break
            max_col = ws.max_column or 30
            for col in range(1, max_col + 1):
                cell = cls._cell_text(ws, row, col)
                if not cell:
                    continue
                for field, keywords in header_keywords.items():
                    if field in detected:
                        continue
                    for kw in keywords:
                        if kw.lower() == cell or kw.lower() in cell:
                            detected[field] = col
                            break

        result = dict(default_map)
        result.update(detected)
        return result

    CONTENT_FEATURES = {
        'test_steps': [
            'sudo ', '执行指令', '执行命令', '输入命令', './nvsipl', 'nvsipl_camera',
            'i2cmastercmd', 'ssh登录', 'ssh nvidia', '1、执行', '1.执行',
        ],
        'prerequisites': [
            '硬件正确连接', '硬件设备正确', '将驱动文件', '将测试so', 'ssh登录',
            '前提：', '前提条件', '先执行',
        ],
        'expected_result': [
            'fps稳定输出', '无报错', '正常输出', '无异常', '稳定在', 'pass',
            '可生成', '正确抓出',
        ],
        'description': [
            '出图', '起流', '拍照', '故障诊断', '解串器', '加串器', '传感器', '帧率',
        ],
    }

    @classmethod
    def _infer_columns_by_content(cls, ws, data_start_row: int) -> Dict[str, int]:
        """无表头时依据数据格文本推断列语义"""
        max_col = ws.max_column or 15
        field_scores: Dict[str, Dict[int, int]] = {
            field: {} for field in cls.CONTENT_FEATURES
        }
        sample_rows = min(data_start_row + 10, (ws.max_row or 9999) + 1)
        for row in range(data_start_row, sample_rows):
            for col in range(1, max_col + 1):
                cell = cls._cell_text(ws, row, col)
                if not cell:
                    continue
                for field, kws in cls.CONTENT_FEATURES.items():
                    for kw in kws:
                        if kw.lower() in cell:
                            field_scores[field][col] = field_scores[field].get(col, 0) + 1
                            break

        inferred: Dict[str, int] = {}
        for field, scores in field_scores.items():
            if not scores:
                continue
            best_col = max(scores, key=lambda c: scores[c])
            if scores[best_col] >= 2:
                inferred[field] = best_col
        return inferred

    def _detect_sheet_layout(self, ws) -> tuple:
        """单张 Sheet 的完整布局解析"""
        all_kw = {**self.HEADER_KEYWORDS, **self.RESULT_HEADER_KEYWORDS}
        header_row, data_start_row = self._find_header_and_data_rows(ws, all_kw)

        if header_row is not None:
            col_map = self._detect_column_map(
                ws, self.HEADER_KEYWORDS, self.COLUMN_MAP,
                header_row=header_row, extra_scan_rows=2,
            )
            result_col_map = self._detect_column_map(
                ws, self.RESULT_HEADER_KEYWORDS, self.RESULT_COLUMN_MAP,
                header_row=header_row, extra_scan_rows=3,
            )
            return header_row, data_start_row, col_map, result_col_map

        inferred_data_start = self.DATA_START_ROW
        for r in range(1, (ws.max_row or 30) + 1):
            max_col = ws.max_column or 15
            non_empty = sum(
                1 for c in range(1, max_col + 1)
                if ws.cell(row=r, column=c).value not in (None, "")
            )
            if non_empty >= 3:
                inferred_data_start = r
                break

        inferred = self._infer_columns_by_content(ws, inferred_data_start)
        col_map = dict(self.COLUMN_MAP)
        col_map.update(inferred)

        return None, inferred_data_start, col_map, dict(self.RESULT_COLUMN_MAP)

    def load(self, file_path: str = None) -> List[TestCase]:
        """打开 Excel，按「功能 / 故障 / 稳定」类 Sheet 顺序解析用例"""
        if file_path:
            self.file_path = file_path

        if not self.file_path or not os.path.exists(self.file_path):
            raise FileNotFoundError(f"文件不存在: {self.file_path}")

        if self.workbook:
            try:
                self.workbook.close()
            except Exception:
                pass
            self.workbook = None

        self.workbook = load_workbook(
            self.file_path, data_only=False, read_only=False
        )
        self.test_cases = []

        # 加载时是否把历史「判断依据」表头改成了「BUG」
        self.bug_header_renamed = False

        sheet_names = self.ordered_test_sheet_names(self.workbook)
        if not sheet_names:
            raise ValueError(
                "未找到用例工作表。请确认存在名称中含「功能」「故障」「稳定」"
                "或 Functional / Fault / Stability 的 Sheet。"
            )

        if not hasattr(self, '_sheet_col_maps'):
            self._sheet_col_maps: Dict[str, tuple] = {}

        for sheet_name in sheet_names:
            ws = self.workbook[sheet_name]

            header_row, data_start_row, col_map, result_col_map = self._detect_sheet_layout(ws)
            if self._normalize_bug_header(ws, header_row, result_col_map.get('judgment', 0)):
                self.bug_header_renamed = True
            self._sheet_col_maps[sheet_name] = (col_map, result_col_map)

            cat = self.sheet_category(sheet_name)
            default_selected = cat == "functional"
            seq = 0

            for row_idx in range(data_start_row, (ws.max_row or 0) + 1):
                case_id = self._get_cell_value(ws, row_idx, col_map['case_id'])

                max_col = ws.max_column or 30
                row_has_content = any(
                    ws.cell(row=row_idx, column=c).value not in (None, "")
                    for c in range(1, max_col + 1)
                )
                if not row_has_content:
                    continue

                if not case_id:
                    steps = self._get_cell_value(ws, row_idx, col_map['test_steps'])
                    expected = self._get_cell_value(ws, row_idx, col_map['expected_result'])
                    prerequisites = self._get_cell_value(ws, row_idx, col_map['prerequisites'])
                    if not steps and not expected and not prerequisites:
                        continue
                    seq += 1
                    case_id = f"{sheet_name[:4]}_{row_idx:03d}"
                else:
                    seq += 1

                tc = TestCase(
                    case_id=case_id,
                    case_key=f"{sheet_name}:{row_idx}:{case_id}",
                    test_type=self._get_cell_value(ws, row_idx, col_map['test_type']),
                    requirement_id=self._get_cell_value(ws, row_idx, col_map['requirement_id']),
                    design_method=self._get_cell_value(ws, row_idx, col_map['design_method']),
                    description=self._get_cell_value(ws, row_idx, col_map['description']),
                    prerequisites=self._get_cell_value(ws, row_idx, col_map['prerequisites']),
                    test_steps=self._get_cell_value(ws, row_idx, col_map['test_steps']),
                    expected_result=self._get_cell_value(ws, row_idx, col_map['expected_result']),
                    priority=self._get_cell_value(ws, row_idx, col_map['priority']),
                    row_number=row_idx,
                    source_sheet=sheet_name,
                    selected=default_selected,
                    status="NT"
                )

                # 回填 Excel 中已存在的结果数据（上次执行留下的痕迹）
                tc.actual_result = self._get_cell_value(ws, row_idx, result_col_map.get('actual_result', 0))
                tc.judgment = self._get_cell_value(ws, row_idx, result_col_map.get('judgment', 0))
                tc.remarks = self._get_cell_value(ws, row_idx, result_col_map.get('remarks', 0))
                tc.test_version = self._get_cell_value(ws, row_idx, result_col_map.get('test_version', 0))
                tc.tester = self._get_cell_value(ws, row_idx, result_col_map.get('tester', 0))
                tc.test_date = self._get_cell_value(ws, row_idx, result_col_map.get('test_date', 0))

                # 从实际结果列解析 status（可能包含多行："PASS\nxxx" 或纯 "PASS"）
                if tc.actual_result:
                    first_line = tc.actual_result.split('\n')[0].strip()
                    if first_line in self.STATUS_COLORS:
                        tc.status = first_line

                tc.expected_keywords = self._parse_expected_keywords(tc.expected_result)
                self.test_cases.append(tc)

        # 修复「数据统计」页的汇总公式（模板被人工增删 Sheet 后可能出现 #REF!）
        try:
            self.refresh_statistics_summary(self.workbook)
        except Exception:
            pass  # 统计公式修复失败不影响用例解析

        # 同步解析 BugList统计 页（不存在时返回空列表）
        self.load_bug_list()
        return self.test_cases

    def _get_cell_value(self, ws, row: int, col: int) -> str:
        """读取单元格原始值并转为字符串"""
        cell = ws.cell(row=row, column=col)
        return str(cell.value).strip() if cell.value else ""

    def update_test_steps(self, case_key: str, test_steps: str, save: bool = True) -> bool:
        """更新指定用例的「测试步骤」并写回工作簿。

        返回是否找到对应用例；``case_key`` 采用 ``Sheet:行号:用例ID`` 格式。
        """
        if not self.workbook:
            raise ValueError("未加载 Excel 文件")

        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', test_steps or "")
        if len(text) > 32000:
            text = text[:32000] + "\n... (内容过长已截断)"

        for tc in self.test_cases:
            key = tc.case_key or (
                f"{tc.source_sheet}:{tc.row_number}:{tc.case_id}"
            )
            if key != case_key:
                continue
            col_map = self._sheet_col_maps.get(tc.source_sheet, (self.COLUMN_MAP, {}))[0]
            col = col_map.get('test_steps') or self.COLUMN_MAP['test_steps']
            ws = self._worksheet_for_case(tc)
            ws.cell(row=tc.row_number, column=col).value = text
            tc.test_steps = text
            if save:
                self.workbook.save(self.file_path)
            return True
        return False

    def update_expected_result(self, case_key: str, expected_result: str, save: bool = True) -> bool:
        """更新指定用例的「预期结果」并写回工作簿。

        返回是否找到对应用例；``case_key`` 采用 ``Sheet:行号:用例ID`` 格式。
        """
        if not self.workbook:
            raise ValueError("未加载 Excel 文件")

        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', expected_result or "")
        if len(text) > 32000:
            text = text[:32000] + "\n... (内容过长已截断)"

        for tc in self.test_cases:
            key = tc.case_key or (
                f"{tc.source_sheet}:{tc.row_number}:{tc.case_id}"
            )
            if key != case_key:
                continue
            col_map = self._sheet_col_maps.get(tc.source_sheet, (self.COLUMN_MAP, {}))[0]
            col = col_map.get('expected_result') or self.COLUMN_MAP['expected_result']
            ws = self._worksheet_for_case(tc)
            ws.cell(row=tc.row_number, column=col).value = text
            tc.expected_result = text
            tc.expected_keywords = self._parse_expected_keywords(text)
            if save:
                self.workbook.save(self.file_path)
            return True
        return False

    def update_remarks(self, case_key: str, remarks: str, save: bool = True) -> bool:
        """更新指定用例的「备注」列（执行日志）并可选写回工作簿。

        返回是否找到对应用例；``case_key`` 采用 ``Sheet:行号:用例ID`` 格式。
        """
        if not self.workbook:
            raise ValueError("未加载 Excel 文件")

        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', remarks or "")
        if len(text) > 32000:
            text = text[:32000] + "\n... (内容过长已截断)"

        for tc in self.test_cases:
            key = tc.case_key or (
                f"{tc.source_sheet}:{tc.row_number}:{tc.case_id}"
            )
            if key != case_key:
                continue
            rcm = self._result_col_for(tc)
            col = rcm.get('remarks') or self.RESULT_COLUMN_MAP['remarks']
            ws = self._worksheet_for_case(tc)
            ws.cell(row=tc.row_number, column=col).value = text
            tc.remarks = text
            if save:
                self.workbook.save(self.file_path)
            return True
        return False

    @staticmethod
    def _parse_expected_keywords(expected_text: str) -> List[str]:
        """解析预期结果文本，填充 expected_keywords 供前端预览与执行器匹配使用"""
        if not expected_text:
            return []
        try:
            from app.core.expected_parser import ExpectedResultParser
            criteria = ExpectedResultParser().parse(expected_text)
            return criteria.keywords
        except Exception:
            return []

    def save_results(self, test_cases: List[TestCase] = None, output_path: str = None,
                     include_log: bool = True):
        """将内存中用例的执行结果写回工作簿并保存

        Args:
            test_cases: 待写回的用例；为空时使用已加载的用例
            output_path: 输出路径；为空时覆盖源文件
            include_log: 是否把实际执行日志写入备注列
        """
        if test_cases is None:
            test_cases = self.test_cases

        if not self.workbook:
            raise ValueError("未加载 Excel 文件")

        def _sanitize_cell_value(value: str, max_len: int = 32000) -> str:
            """清理单元格值：移除非法字符，截断过长内容。

            openpyxl 不允许控制字符（\x00-\x08, \x0b, \x0c, \x0e-\x1f）
            Excel 单元格最大 32767 字符。
            """
            if not value:
                return value
            # 移除 openpyxl 不支持的控制字符
            value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', value)
            # 截断过长内容
            if len(value) > max_len:
                value = value[:max_len] + "\n... (内容过长已截断)"
            return value

        def _worksheet_for_case(tc: TestCase):
            return self._worksheet_for_case(tc)

        def _result_col_for(tc: TestCase) -> Dict[str, int]:
            return self._result_col_for(tc)

        for tc in test_cases:
            if tc.row_number <= 0:
                continue

            row = tc.row_number
            ws = _worksheet_for_case(tc)
            rcm = _result_col_for(tc)

            # --- Actual Result column: status only (PASS / FAIL / NT / BLOCK / NA / Review) ---
            cell = ws.cell(row=row, column=rcm['actual_result'])
            if tc.status:
                cell.value = tc.status
            else:
                cell.value = "NT"

            if tc.status in self.STATUS_COLORS:
                cell.fill = PatternFill(
                    start_color=self.STATUS_COLORS[tc.status],
                    end_color=self.STATUS_COLORS[tc.status],
                    fill_type='solid'
                )

            # --- BUG column: AI 判定状态 / 判定依据 / 证据 ---
            bug_cell = ws.cell(row=row, column=rcm['judgment'])
            if bool(getattr(tc, "ai_judged", False)):
                judgment = build_judgment_from_case(tc)
                bug_cell.value = _sanitize_cell_value(judgment) or None
            elif tc.status.upper() != "NT" and "[AI判定]" in str(bug_cell.value or ""):
                # 本次执行没有 AI 判定：清掉上一次的系统判定，但不覆盖用户手填的 BUG 内容
                bug_cell.value = None

            # --- Remarks column: execution log only ---
            remark = build_log_remark_from_case(tc, include_log=include_log)
            if remark or tc.status.upper() != "NT":
                ws.cell(row=row, column=rcm['remarks']).value = _sanitize_cell_value(remark) or None

            if tc.test_version:
                ws.cell(row=row, column=rcm['test_version']).value = tc.test_version

            if tc.tester:
                ws.cell(row=row, column=rcm['tester']).value = tc.tester

            if tc.test_date:
                ws.cell(row=row, column=rcm['test_date']).value = tc.test_date

            # --- Test steps: 同步在线编辑后的步骤（执行结束时随结果一起保存） ---
            steps_col = (
                self._sheet_col_maps.get(tc.source_sheet, (self.COLUMN_MAP, {}))[0]
                .get('test_steps') or self.COLUMN_MAP['test_steps']
            )
            current_steps = str(ws.cell(row=row, column=steps_col).value or '')
            if tc.test_steps != current_steps:
                ws.cell(row=row, column=steps_col).value = _sanitize_cell_value(
                    tc.test_steps
                )

            # --- Expected result: 同步在线编辑后的预期结果 ---
            expected_col = (
                self._sheet_col_maps.get(tc.source_sheet, (self.COLUMN_MAP, {}))[0]
                .get('expected_result') or self.COLUMN_MAP['expected_result']
            )
            current_expected = str(ws.cell(row=row, column=expected_col).value or '')
            if tc.expected_result != current_expected:
                ws.cell(row=row, column=expected_col).value = _sanitize_cell_value(
                    tc.expected_result
                )

        save_path = output_path or self.file_path
        self.workbook.save(save_path)
        return save_path

    def _worksheet_for_case(self, tc: TestCase):
        """按用例来源 Sheet 找到对应工作表（找不到时回退功能测试表）"""
        name = (tc.source_sheet or "").strip()
        if name and name in self.workbook.sheetnames:
            return self.workbook[name]
        for cand in self.workbook.sheetnames:
            if "功能" in cand or "Functional" in cand.lower():
                return self.workbook[cand]
        return self.workbook[self.workbook.sheetnames[0]]

    def _result_col_for(self, tc: TestCase) -> Dict[str, int]:
        """取该用例所在 Sheet 的结果列映射"""
        sheet_maps = getattr(self, '_sheet_col_maps', {})
        entry = sheet_maps.get(tc.source_sheet or "")
        if entry:
            return entry[1]
        return self.RESULT_COLUMN_MAP

    @staticmethod
    def _remove_images_at_cell(ws, col: int, row: int) -> int:
        """移除锚定在指定单元格上的图片，返回移除数量。

        重新下载结果时，源文件可能已经包含上一次嵌入的用例截图；
        若不去除，新截图会与旧截图锚定在同一单元格而重叠。
        """
        images = getattr(ws, "_images", None)
        if not images:
            return 0
        keep = []
        for img in images:
            anchor = getattr(img, "anchor", None)
            frm = getattr(anchor, "_from", None)
            if (
                frm is not None
                and getattr(frm, "col", None) == col - 1
                and getattr(frm, "row", None) == row - 1
            ):
                continue
            keep.append(img)
        removed = len(images) - len(keep)
        if removed:
            ws._images = keep
        return removed

    def clear_result_images(self) -> int:
        """移除所有锚定在「备注」结果单元格上的图片，返回移除数量。"""
        count = 0
        for tc in self.test_cases:
            if tc.row_number <= 0:
                continue
            ws = self._worksheet_for_case(tc)
            rcm = self._result_col_for(tc)
            col = rcm.get('remarks') or self.RESULT_COLUMN_MAP['remarks']
            count += self._remove_images_at_cell(ws, col, tc.row_number)
        return count

    def embed_log_images(self, max_width: int = 320, max_height: int = 520,
                         font_size: int = 10, remove_existing: bool = True,
                         clear_text: bool = True,
                         evidence_by_key: Optional[Dict[str, List[str]]] = None,
                         render_width: int = 400,
                         ) -> Dict[tuple, int]:
        """把每条用例执行日志渲染成终端风格图片并嵌入「备注」列。

        优先按终端分别渲染：执行器为每个终端单独落盘的日志各生成一张图片，
        按终端顺序在同一单元格内自上而下堆叠（图片顶部标注终端名）；
        没有终端级日志的旧记录回退为聚合日志的一张图片。
        图片按 ``max_width`` 显示宽度缩放（默认 320px，比原始渲染的
        ``render_width`` 小），避免备注列占用过宽过高；多个终端时按数量
        均分 ``max_height``，保证整格高度不会成倍膨胀。
        clear_text=True 时，图片嵌入成功后清空该单元格里的日志文字，
        备注列只保留图片；图片渲染失败时保留文字作为兜底。
        evidence_by_key 可按 case_key 提供 AI 证据行，用于图片关键行高亮。
        返回 ``{(sheet, row): 图片总高度(px)}``，供后续截图从日志图片下方继续排列。
        """
        if not self.workbook:
            return {}

        try:
            from io import BytesIO

            from openpyxl.drawing.image import Image as XLImage
            from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, OneCellAnchor
            from openpyxl.drawing.xdr import XDRPositiveSize2D
            from openpyxl.utils import get_column_letter
            from openpyxl.utils.units import pixels_to_EMU
            from app.core.log_image import read_terminal_logs, render_log_image
            from app.core.terminal_log import parse_terminal_log
        except Exception:
            return {}

        bottoms: Dict[tuple, int] = {}
        for tc in self.test_cases:
            if tc.row_number <= 0:
                continue

            ws = self._worksheet_for_case(tc)
            rcm = self._result_col_for(tc)
            col = rcm.get('remarks') or self.RESULT_COLUMN_MAP['remarks']
            row = tc.row_number
            key = (tc.source_sheet or "", row)

            if remove_existing:
                self._remove_images_at_cell(ws, col, row)

            # 证据优先取会话状态（BUG 列已不再写证据行）
            evidence: List[str] = []
            if evidence_by_key:
                case_key = tc.case_key or (
                    f"{tc.source_sheet}:{tc.row_number}:{tc.case_id}"
                )
                evidence = list(evidence_by_key.get(case_key, []) or [])
            if not evidence:
                evidence = extract_evidence_lines(getattr(tc, "judgment", ""))
            if not evidence:
                evidence = list(getattr(tc, "ai_evidence", []) or [])

            # 每个终端单独渲染一张图片。终端级日志优先取执行器落盘文件；
            # 草稿恢复的用例没有终端文件，但备注日志已按 ``===== 终端 =====``
            # 分段存储，拆回各终端后同样分别渲染。
            bufs: List[Tuple[BytesIO, str]] = []
            terminal_logs = read_terminal_logs(tc.log_file or "")
            log_text = ""
            if not terminal_logs:
                log_text = extract_log_section(tc.remarks)
                if not log_text and tc.log_file:
                    log_text = read_log_content(tc.log_file)
                if log_text.strip():
                    terminal_logs = parse_terminal_log(log_text)
            if terminal_logs:
                per_max_height = max(120, int(max_height / len(terminal_logs)))
                for label, terminal_text in terminal_logs:
                    header = f"===== {label} ====="
                    if terminal_text.startswith(header):
                        terminal_text = terminal_text[len(header):].lstrip("\r\n")
                    if not terminal_text.strip():
                        continue
                    terminal_buf = render_log_image(
                        terminal_text,
                        status=tc.status or "",
                        evidence=evidence,
                        width=render_width,
                        max_height=per_max_height,
                        font_size=font_size,
                        title=label,
                    )
                    if terminal_buf is not None:
                        bufs.append((terminal_buf, label))
            if not bufs:
                if not log_text:
                    log_text = extract_log_section(tc.remarks)
                    if not log_text and tc.log_file:
                        log_text = read_log_content(tc.log_file)
                if not log_text.strip():
                    continue
                buf = render_log_image(
                    log_text,
                    status=tc.status or "",
                    evidence=evidence,
                    width=render_width,
                    max_height=max_height,
                    font_size=font_size,
                )
                if buf is None:
                    continue
                bufs.append((buf, ""))

            # 多个终端图片锚定在同一「备注」单元格内，按顺序纵向堆叠
            row_off = 2
            total_disp_h = 0
            max_disp_w = 1
            for buf, _label in bufs:
                xl_img = XLImage(buf)
                src_w = xl_img.width or max_width
                src_h = xl_img.height or max_height
                scale = min(1.0, max_width / float(src_w))
                disp_w = max(1, int(src_w * scale))
                disp_h = max(1, int(src_h * scale))
                xl_img.width, xl_img.height = disp_w, disp_h

                marker = AnchorMarker(
                    col=col - 1, colOff=pixels_to_EMU(2),
                    row=row - 1, rowOff=pixels_to_EMU(row_off),
                )
                xl_img.anchor = OneCellAnchor(
                    _from=marker,
                    ext=XDRPositiveSize2D(pixels_to_EMU(disp_w), pixels_to_EMU(disp_h)),
                )
                ws.add_image(xl_img)
                max_disp_w = max(max_disp_w, disp_w)
                total_disp_h += disp_h
                row_off += disp_h + 6
            bottoms[key] = total_disp_h

            # 备注列只保留日志图片，不再保留日志文字
            if clear_text:
                cell = ws.cell(row=row, column=col)
                if isinstance(cell.value, str) and "--- 执行日志 ---" in cell.value:
                    cell.value = None

            # 备注列宽度跟随图片显示宽度（Excel 宽度单位约 7px/字符）
            letter = get_column_letter(col)
            target_width = max(20, int(max_disp_w / 7))
            if (ws.column_dimensions[letter].width or 0) != target_width:
                ws.column_dimensions[letter].width = target_width

            needed = (total_disp_h + 6) * 0.75 + 2
            current = ws.row_dimensions[row].height
            if (current or 0) < needed:
                ws.row_dimensions[row].height = min(409, needed)

        return bottoms

    def embed_case_images(self, image_base: str, max_width: int = 170,
                          source_max_width: int = 480,
                          start_offsets: Optional[Dict[tuple, int]] = None,
                          remove_existing: bool = True,
                          executed_keys: Optional[set] = None) -> int:
        """把每条用例目录下的 PNG 图片嵌入「备注」列，返回嵌入的图片数。

        - 图片浮动覆盖在备注单元格上，行高会自动调大以容纳图片；
        - 先按 ``source_max_width`` 缩图再嵌入，避免结果 Excel 过大；
        - 重复下载时先移除备注单元格上的旧图片，避免截图层层叠加；
        - 需要 Pillow（openpyxl 插入图片时依赖），缺失时返回 0，不影响其余内容。

        图片目录按 Sheet 维度查找（见 ``app.core.image_store``）：不同 Sheet
        里 case_id 相同（如「功能测试」「故障测试」都有 001）时互不串台。
        只有旧布局（``<下载路径>/<case_id>/``）且该 case_id 在本工作簿里
        出现在多个 Sheet 时，才用 ``executed_keys``（本会话实际执行过的
        case_key 集合）决定归属；不传 ``executed_keys`` 时保持旧行为。
        """
        if not self.workbook or not image_base:
            return 0
        try:
            from io import BytesIO

            from openpyxl.drawing.image import Image as XLImage
            from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, OneCellAnchor
            from openpyxl.drawing.xdr import XDRPositiveSize2D
            from openpyxl.utils.units import pixels_to_EMU
            from PIL import Image as PILImage
        except Exception:
            return 0

        from app.core.image_store import resolve_case_image_dir

        base = os.path.abspath(os.path.expanduser(image_base))
        start_offsets = start_offsets or {}
        # case_id 在本工作簿里跨 Sheet 重复的次数（旧布局无法区分归属）
        id_counts: Dict[str, int] = {}
        for item in self.test_cases:
            if item.case_id:
                id_counts[item.case_id] = id_counts.get(item.case_id, 0) + 1
        count = 0
        for tc in self.test_cases:
            if tc.row_number <= 0 or not tc.case_id:
                continue
            case_dir, layout = resolve_case_image_dir(
                base, tc.case_id, tc.source_sheet or "")
            if not os.path.isdir(case_dir):
                continue
            if layout == "legacy" and id_counts.get(tc.case_id, 0) > 1:
                # 旧布局 + case_id 跨 Sheet 重复：只有实际执行过的用例才嵌入，
                # 否则没执行该用例的 Sheet 会显示出别的 Sheet 的图片。
                if executed_keys is not None and tc.case_key not in executed_keys:
                    continue
            names = sorted(
                n for n in os.listdir(case_dir)
                if n.lower().endswith(".png") and os.path.isfile(os.path.join(case_dir, n))
            )
            if not names:
                continue

            ws = self._worksheet_for_case(tc)
            rcm = self._result_col_for(tc)
            col = rcm.get('remarks') or self.RESULT_COLUMN_MAP['remarks']
            row = tc.row_number
            key = (tc.source_sheet or "", row)
            # 日志图片在上方时，截图从日志图片下方继续排列
            y_offset = int(start_offsets.get(key, 0)) + 2

            # 结果文件可能已经被下载/重新上传过，备注单元格里已有上次嵌入的
            # 图片；先清掉同一锚点的旧图片，避免每次下载反复叠加。
            if remove_existing:
                self._remove_images_at_cell(ws, col, row)

            for name in names:
                path = os.path.join(case_dir, name)
                try:
                    with PILImage.open(path) as im:
                        im = im.convert("RGB")
                        if im.width > source_max_width:
                            ratio = source_max_width / float(im.width)
                            im = im.resize(
                                (source_max_width, max(1, int(im.height * ratio))),
                                PILImage.LANCZOS,
                            )
                        buf = BytesIO()
                        im.save(buf, format="PNG", optimize=True)
                    buf.seek(0)
                    xl_img = XLImage(buf)
                except Exception:
                    continue

                src_w = xl_img.width or max_width
                src_h = xl_img.height or max_width
                scale = min(1.0, max_width / float(src_w))
                disp_w = max(1, int(src_w * scale))
                disp_h = max(1, int(src_h * scale))
                xl_img.width, xl_img.height = disp_w, disp_h

                marker = AnchorMarker(
                    col=col - 1, colOff=pixels_to_EMU(2),
                    row=row - 1, rowOff=pixels_to_EMU(y_offset),
                )
                xl_img.anchor = OneCellAnchor(
                    _from=marker,
                    ext=XDRPositiveSize2D(pixels_to_EMU(disp_w), pixels_to_EMU(disp_h)),
                )
                ws.add_image(xl_img)
                y_offset += disp_h + 4
                count += 1

            # 行高至少容纳图片（1px ≈ 0.75pt），避免图片压住下一行
            current = ws.row_dimensions[row].height
            needed = y_offset * 0.75 + 2
            if (current or 0) < needed:
                ws.row_dimensions[row].height = needed

        return count

    def strip_evidence_from_judgment(self) -> int:
        """移除「BUG」列中的 AI 证据行（原地修改已加载的工作簿）。

        仅处理系统生成的 ``[AI判定]`` 内容，用户自定义的 BUG 描述不受影响；
        返回被处理的单元格数。
        """
        from app.core.remarks import strip_evidence_lines

        if not self.workbook:
            return 0

        count = 0
        for sheet_name, (_, result_col_map) in getattr(self, '_sheet_col_maps', {}).items():
            if sheet_name not in self.workbook.sheetnames:
                continue
            ws = self.workbook[sheet_name]
            judgment_col = result_col_map.get('judgment')
            if not judgment_col:
                continue
            for row in range(1, (ws.max_row or 0) + 1):
                cell = ws.cell(row=row, column=judgment_col)
                if not isinstance(cell.value, str):
                    continue
                stripped = strip_evidence_lines(cell.value)
                if stripped != cell.value:
                    cell.value = stripped or None
                    count += 1
        return count

    def strip_log_from_remarks(self) -> int:
        """移除备注列中的执行日志段（原地修改已加载的工作簿）。

        备注列现只保存执行日志（AI 判定在「BUG」列），
        仅处理包含「--- 执行日志 ---」标记的单元格；返回被处理的单元格数。
        """
        from app.core.remarks import strip_log_section

        if not self.workbook:
            return 0

        count = 0
        for sheet_name, (_, result_col_map) in getattr(self, '_sheet_col_maps', {}).items():
            if sheet_name not in self.workbook.sheetnames:
                continue
            ws = self.workbook[sheet_name]
            remarks_col = result_col_map.get('remarks')
            if not remarks_col:
                continue
            for row in range(1, (ws.max_row or 0) + 1):
                cell = ws.cell(row=row, column=remarks_col)
                if isinstance(cell.value, str) and "--- 执行日志 ---" in cell.value:
                    cell.value = strip_log_section(cell.value) or None
                    count += 1
        return count

    def save(self, output_path: str = None) -> str:
        """保存已加载的工作簿（默认覆盖源文件）"""
        if not self.workbook:
            raise ValueError("未加载 Excel 文件")
        save_path = output_path or self.file_path
        self.workbook.save(save_path)
        return save_path

    def get_statistics(self, test_cases: List[TestCase] = None) -> Dict[str, int]:
        """统计用例数量"""
        if test_cases is None:
            test_cases = self.test_cases

        return {
            'total': len(test_cases),
            'selected': sum(1 for tc in test_cases if tc.selected),
            'pass': sum(1 for tc in test_cases if tc.status == 'Pass'),
            'fail': sum(1 for tc in test_cases if tc.status == 'Fail'),
            'nt': sum(1 for tc in test_cases if tc.status == 'NT'),
            'block': sum(1 for tc in test_cases if tc.status == 'BLOCK'),
            'na': sum(1 for tc in test_cases if tc.status == 'NA'),
        }

    def close(self):
        if self.workbook:
            self.workbook.close()
            self.workbook = None