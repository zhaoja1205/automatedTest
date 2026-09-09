"""
Pure-Python HTML report generator for test execution results.

No AI dependency, no external template engine. Self-contained HTML output
with embedded print-friendly CSS.
"""

import html
from datetime import datetime
from typing import Any


class ReportGenerator:
    """
    Generates self-contained HTML test execution reports.

    All text content is escaped with ``html.escape()`` to prevent XSS.
    CSS is embedded; no external dependencies are required.
    """

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def generate_summary_report(self, run_data: dict, results: list[dict]) -> str:
        """
        Generate a complete HTML test execution report.

        Parameters
        ----------
        run_data :
            Execution metadata. Expected keys:
            run_id, started_at, ended_at, duration_seconds, tester_name,
            test_version, excel_filename, sheets_used, total_count, pass_count,
            fail_count, block_count, na_count, nt_count, review_count, pass_rate.
        results :
            List of result dicts for each test case. Expected keys:
            case_id, case_key, source_sheet, description, test_steps,
            expected_result, prerequisites, priority, status, actual_result,
            match_reason, log_file, duration_seconds.

        Returns
        -------
        str
            Complete HTML string.
        """
        title = html.escape(run_data.get("test_version", "未知版本"))
        date = datetime.now().strftime("%Y-%m-%d")
        run_id = html.escape(str(run_data.get("run_id", "")))
        tester = html.escape(str(run_data.get("tester_name", "")))
        version = html.escape(str(run_data.get("test_version", "")))
        started = self._format_datetime(run_data.get("started_at", ""))
        duration = self._format_duration(run_data.get("duration_seconds", 0))
        excel = html.escape(str(run_data.get("excel_filename", "")))
        sheets = html.escape(
            ", ".join(
                s.strip() if isinstance(s, str) else str(s)
                for s in (
                    # sheets_used 在数据库中是逗号分隔的 TEXT 字符串，
                    # 需要先 split 为列表再 join，否则会逐字符遍历
                    run_data.get("sheets_used", "").split(",")
                    if isinstance(run_data.get("sheets_used"), str)
                    else (run_data.get("sheets_used") or [])
                )
                if (s.strip() if isinstance(s, str) else s)
            )
        )

        total = int(run_data.get("total_count", 0))
        passed = int(run_data.get("pass_count", 0))
        failed = int(run_data.get("fail_count", 0))
        blocked = int(run_data.get("block_count", 0))
        na = int(run_data.get("na_count", 0))
        nt = int(run_data.get("nt_count", 0))
        review = int(run_data.get("review_count", 0))
        pass_rate = float(run_data.get("pass_rate", 0.0))

        # ------------------------------------------------------------------ #
        # 1. Header
        # ------------------------------------------------------------------ #
        header_html = f"""
  <div class="report-header">
    <h1>测试执行报告</h1>
    <table class="info-table">
      <tbody>
        <tr><th>测试人员</th><td>{tester}</td></tr>
        <tr><th>测试版本</th><td>{version}</td></tr>
        <tr><th>执行时间</th><td>{started}</td></tr>
        <tr><th>执行耗时</th><td>{duration}</td></tr>
        <tr><th>测试文件</th><td>{excel}</td></tr>
        <tr><th>测试页签</th><td>{sheets}</td></tr>
      </tbody>
    </table>
  </div>
"""

        # ------------------------------------------------------------------ #
        # 2. Summary
        # ------------------------------------------------------------------ #
        summary_html = f"""
  <div class="summary">
    <h2>执行摘要</h2>
    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-value">{total}</div>
        <div class="stat-label">总计</div>
      </div>
      <div class="stat-card stat-pass">
        <div class="stat-value">{passed}</div>
        <div class="stat-label">通过</div>
      </div>
      <div class="stat-card stat-fail">
        <div class="stat-value">{failed}</div>
        <div class="stat-label">失败</div>
      </div>
      <div class="stat-card stat-block">
        <div class="stat-value">{blocked}</div>
        <div class="stat-label">阻塞</div>
      </div>
      <div class="stat-card stat-na">
        <div class="stat-value">{na}</div>
        <div class="stat-label">NA</div>
      </div>
      <div class="stat-card stat-nt">
        <div class="stat-value">{nt}</div>
        <div class="stat-label">未执行</div>
      </div>
      <div class="stat-card stat-review">
        <div class="stat-value">{review}</div>
        <div class="stat-label">待确认</div>
      </div>
      <div class="stat-card stat-rate">
        <div class="stat-value">{pass_rate:.1f}%</div>
        <div class="stat-label">通过率</div>
      </div>
    </div>
    <div class="progress-bar-wrapper">
      <div class="progress-bar" style="width: {pass_rate:.1f}%" aria-valuenow="{pass_rate:.1f}" aria-valuemin="0" aria-valuemax="100"></div>
    </div>
  </div>
"""

        # ------------------------------------------------------------------ #
        # 3. Results table
        # ------------------------------------------------------------------ #
        rows = ""
        for idx, result in enumerate(results, start=1):
            case_id = html.escape(str(result.get("case_id", "")))
            description = html.escape(str(result.get("description", ""))) or "—"
            priority = html.escape(str(result.get("priority", ""))) or "—"
            status = html.escape(str(result.get("status", ""))) or "—"
            duration_str = self._format_duration(result.get("duration_seconds", 0))
            status_class = self._status_to_css_class(status)

            rows += f"""      <tr>
        <td class="col-index">{idx}</td>
        <td class="col-case-id">{case_id}</td>
        <td class="col-desc">{description}</td>
        <td class="col-priority">{priority}</td>
        <td class="col-status {status_class}">{status}</td>
        <td class="col-duration">{duration_str}</td>
      </tr>
"""

        results_html = f"""
  <div class="results">
    <h2>测试结果</h2>
    <table class="results-table">
      <thead>
        <tr>
          <th class="col-index">#</th>
          <th class="col-case-id">用例编号</th>
          <th class="col-desc">描述</th>
          <th class="col-priority">优先级</th>
          <th class="col-status">状态</th>
          <th class="col-duration">耗时(s)</th>
        </tr>
      </thead>
      <tbody>
{rows}      </tbody>
    </table>
  </div>
"""

        # ------------------------------------------------------------------ #
        # 4. Failure details
        # ------------------------------------------------------------------ #
        failures = [r for r in results if str(r.get("status", "")).lower() == "fail"]
        if failures:
            failure_items = ""
            for result in failures:
                case_id = html.escape(str(result.get("case_id", "")))
                description = html.escape(str(result.get("description", ""))) or "—"
                expected = html.escape(str(result.get("expected_result", ""))) or "—"
                actual = html.escape(str(result.get("actual_result", ""))) or "—"
                match_reason = html.escape(str(result.get("match_reason", ""))) or "—"

                failure_items += f"""    <div class="failure-item">
      <h3>{case_id}: {description}</h3>
      <table class="detail-table">
        <tbody>
          <tr><th>预期结果</th><td>{expected}</td></tr>
          <tr><th>实际结果</th><td>{actual}</td></tr>
          <tr><th>匹配原因</th><td>{match_reason}</td></tr>
        </tbody>
      </table>
    </div>
"""

            failures_html = f"""
  <div class="failures">
    <h2>失败用例详情</h2>
{failure_items}  </div>
"""
        else:
            failures_html = """
  <div class="failures">
    <h2>失败用例详情</h2>
    <div class="no-failures">
      <p>所有用例均已通过</p>
    </div>
  </div>
"""

        # ------------------------------------------------------------------ #
        # 5. Footer
        # ------------------------------------------------------------------ #
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        footer_html = f"""
  <div class="footer">
    <p>报告生成时间: {now}</p>
    <p>执行记录 ID: {run_id}</p>
  </div>
"""

        # ------------------------------------------------------------------ #
        # Assemble full HTML
        # ------------------------------------------------------------------ #
        css = self._build_css()
        html_str = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>测试执行报告 — {title} — {date}</title>
  <style>
{css}
  </style>
</head>
<body>
{header_html}
{summary_html}
{results_html}
{failures_html}
{footer_html}
</body>
</html>"""

        return html_str

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """
        Format a duration in seconds to a human-readable string.

        Parameters
        ----------
        seconds :
            Duration in seconds (may be ``None`` or zero).

        Returns
        -------
        str
            ``"1h 23m 45s"`` or ``"2m 30s"`` or ``"45s"`` depending on magnitude.
        """
        if not seconds:
            return "—"
        total = float(seconds)
        hours = int(total // 3600)
        minutes = int((total % 3600) // 60)
        secs = int(total % 60)
        parts = []
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if secs or (not hours and not minutes):
            parts.append(f"{secs}s")
        return " ".join(parts)

    @staticmethod
    def _format_datetime(iso_str: str) -> str:
        """
        Parse an ISO datetime string to a human-readable format.

        Parameters
        ----------
        iso_str :
            ISO 8601 datetime string, or empty/``None``.

        Returns
        -------
        str
            ``"YYYY-MM-DD HH:MM:SS"`` if parseable, otherwise the original
            string or ``"—"``.
        """
        if not iso_str:
            return "—"
        try:
            # Handle both "Z" suffix and "+00:00" offset
            cleaned = iso_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return str(iso_str)

    @staticmethod
    def _status_to_css_class(status: str) -> str:
        """
        Map a test status string to a CSS class name.

        Parameters
        ----------
        status :
            The status text (e.g., ``"Pass"``, ``"Fail"``, ``"Block"``).

        Returns
        -------
        str
            CSS class name for styling the status cell.
        """
        mapping = {
            "pass": "status-pass",
            "passed": "status-pass",
            "fail": "status-fail",
            "failure": "status-fail",
            "failed": "status-fail",
            "block": "status-block",
            "blocked": "status-block",
            "na": "status-na",
            "n/a": "status-na",
            "nt": "status-nt",
            "not test": "status-nt",
            "nottest": "status-nt",
            "not_test": "status-nt",
            "review": "status-review",
            "pending": "status-review",
        }
        return mapping.get(status.lower(), "")

    @staticmethod
    def _build_css() -> str:
        """
        Build the embedded CSS string.

        Returns
        -------
        str
            Print-friendly, professional CSS.
        """
        return """    /* --- Base --- */
    :root {
      --color-primary: #2f54eb;
      --color-pass: #36b37e;
      --color-fail: #de350b;
      --color-block: #ff8b00;
      --color-review: #2f54eb;
      --color-na: #8c8c8c;
      --color-nt: #bfbfbf;
      --color-text: #262626;
      --color-text-secondary: #595959;
      --color-bg: #ffffff;
      --color-bg-alt: #fafafa;
      --color-border: #d9d9d9;
      --color-border-light: #f0f0f0;
      --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      padding: 40px 20px;
      font-family: var(--font-sans);
      font-size: 14px;
      line-height: 1.6;
      color: var(--color-text);
      background-color: var(--color-bg);
    }

    /* --- Layout --- */
    body > div {
      max-width: 900px;
      margin: 0 auto 32px auto;
    }

    h1, h2, h3 {
      margin: 0 0 16px 0;
      color: var(--color-text);
    }

    h1 {
      font-size: 28px;
      font-weight: 600;
      border-bottom: 2px solid var(--color-primary);
      padding-bottom: 8px;
    }

    h2 {
      font-size: 20px;
      font-weight: 600;
      margin-top: 24px;
    }

    h3 {
      font-size: 16px;
      font-weight: 600;
    }

    /* --- Info table --- */
    .info-table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 16px;
      background: var(--color-bg);
      border: 1px solid var(--color-border);
    }

    .info-table th,
    .info-table td {
      text-align: left;
      padding: 10px 14px;
      border-bottom: 1px solid var(--color-border-light);
    }

    .info-table th {
      width: 120px;
      color: var(--color-text-secondary);
      font-weight: 500;
      background: var(--color-bg-alt);
      border-right: 1px solid var(--color-border-light);
    }

    .info-table tr:last-child th,
    .info-table tr:last-child td {
      border-bottom: none;
    }

    /* --- Stats --- */
    .stats-row {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-bottom: 20px;
    }

    .stat-card {
      flex: 1 1 80px;
      min-width: 70px;
      background: var(--color-bg);
      border: 1px solid var(--color-border-light);
      border-radius: 8px;
      padding: 16px 10px;
      text-align: center;
    }

    .stat-value {
      font-size: 24px;
      font-weight: 700;
      line-height: 1;
      margin-bottom: 6px;
      color: var(--color-text);
    }

    .stat-label {
      font-size: 12px;
      color: var(--color-text-secondary);
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    .stat-pass .stat-value  { color: var(--color-pass); }
    .stat-fail .stat-value  { color: var(--color-fail); }
    .stat-block .stat-value { color: var(--color-block); }
    .stat-na .stat-value    { color: var(--color-na); }
    .stat-nt .stat-value    { color: var(--color-nt); }
    .stat-review .stat-value { color: var(--color-review); }
    .stat-rate .stat-value  { color: var(--color-primary); }

    /* --- Progress bar --- */
    .progress-bar-wrapper {
      width: 100%;
      height: 8px;
      background: var(--color-border-light);
      border-radius: 4px;
      overflow: hidden;
    }

    .progress-bar {
      height: 100%;
      background: var(--color-pass);
      border-radius: 4px;
      transition: width 0.3s ease;
    }

    /* --- Results table --- */
    .results-table {
      width: 100%;
      border-collapse: collapse;
      border: 1px solid var(--color-border);
      background: var(--color-bg);
      margin-top: 12px;
    }

    .results-table thead {
      background: var(--color-bg-alt);
    }

    .results-table th,
    .results-table td {
      padding: 10px 12px;
      text-align: left;
      border-bottom: 1px solid var(--color-border-light);
    }

    .results-table th {
      font-weight: 600;
      font-size: 13px;
      color: var(--color-text-secondary);
      position: sticky;
      top: 0;
    }

    .results-table tbody tr:nth-child(even) {
      background: var(--color-bg-alt);
    }

    .results-table tbody tr:hover {
      background: #f0f5ff;
    }

    .col-index { width: 40px; text-align: center; }
    .col-case-id { width: 140px; }
    .col-desc { }
    .col-priority { width: 60px; text-align: center; }
    .col-status { width: 70px; text-align: center; font-weight: 600; }
    .col-duration { width: 80px; text-align: right; }

    /* Status colours (text, not background) */
    .status-pass  { color: var(--color-pass); }
    .status-fail  { color: var(--color-fail); }
    .status-block { color: var(--color-block); }
    .status-na    { color: var(--color-na); }
    .status-nt    { color: var(--color-nt); }
    .status-review{ color: var(--color-review); }

    /* --- Failures --- */
    .failure-item {
      background: #fff2f0;
      border: 1px solid #ffccc7;
      border-radius: 6px;
      padding: 14px 18px;
      margin-bottom: 14px;
    }

    .failure-item h3 {
      margin: 0 0 10px 0;
      color: var(--color-fail);
      font-size: 15px;
    }

    .detail-table {
      width: 100%;
      border-collapse: collapse;
    }

    .detail-table th,
    .detail-table td {
      text-align: left;
      vertical-align: top;
      padding: 6px 10px;
      border-bottom: 1px solid #ffccc7;
    }

    .detail-table th {
      width: 100px;
      color: var(--color-text-secondary);
      font-weight: 500;
    }

    .detail-table td {
      color: var(--color-text);
      white-space: pre-wrap;
      word-break: break-word;
    }

    .detail-table tr:last-child th,
    .detail-table tr:last-child td {
      border-bottom: none;
    }

    .no-failures {
      text-align: center;
      padding: 30px;
      background: var(--color-bg-alt);
      border: 1px dashed var(--color-border);
      border-radius: 6px;
      color: var(--color-pass);
      font-size: 16px;
      font-weight: 500;
    }

    /* --- Footer --- */
    .footer {
      text-align: center;
      color: var(--color-text-secondary);
      font-size: 12px;
      margin-top: 48px;
      padding-top: 16px;
      border-top: 1px solid var(--color-border-light);
    }

    .footer p {
      margin: 2px 0;
    }

    /* --- Print --- */
    @media print {
      body {
        padding: 0;
        font-size: 12px;
      }

      body > div {
        max-width: 100%;
        margin-bottom: 20px;
      }

      h1 {
        font-size: 22px;
      }

      h2 {
        font-size: 16px;
        margin-top: 16px;
      }

      .stat-card {
        padding: 10px 6px;
      }

      .stat-value {
        font-size: 18px;
      }

      .results-table thead {
        display: table-header-group;
      }

      .results-table tbody tr {
        break-inside: avoid;
      }

      .failure-item {
        break-inside: avoid;
      }

      .progress-bar-wrapper {
        background: #e0e0e0 !important;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }

      .progress-bar {
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }

      .stat-pass .stat-value,
      .stat-fail .stat-value,
      .stat-block .stat-value,
      .stat-review .stat-value,
      .stat-rate .stat-value,
      .status-pass,
      .status-fail,
      .status-block,
      .status-review {
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }

      .no-failures {
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }
    }
"""
