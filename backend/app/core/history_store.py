"""
SQLite data access layer for test execution history.

Global (not per-session) history database with WAL mode for
concurrent access.  Stores test runs, per-case results, and
report snapshots.  No ORM, no external dependencies.
"""
import os
import sqlite3
from typing import Any


HISTORY_DB_DEFAULT_PATH = "runtime/history.db"


class HistoryStore:
    """Manages the history SQLite database."""

    def __init__(self, db_path: str = HISTORY_DB_DEFAULT_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Return a new connection with row factory and foreign keys enabled."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        """Create tables and indexes if they don't exist."""
        conn = self._get_conn()
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS test_runs (
                    run_id          TEXT PRIMARY KEY,
                    session_id      TEXT NOT NULL,
                    status          TEXT NOT NULL DEFAULT 'finished',
                    started_at      TEXT NOT NULL,
                    ended_at        TEXT,
                    duration_seconds REAL DEFAULT 0,
                    excel_filename  TEXT DEFAULT '',
                    excel_path      TEXT DEFAULT '',
                    sheets_used     TEXT DEFAULT '',
                    tester_name     TEXT DEFAULT '',
                    test_version    TEXT DEFAULT '',
                    total_count     INTEGER DEFAULT 0,
                    pass_count      INTEGER DEFAULT 0,
                    fail_count      INTEGER DEFAULT 0,
                    block_count     INTEGER DEFAULT 0,
                    na_count        INTEGER DEFAULT 0,
                    nt_count        INTEGER DEFAULT 0,
                    review_count    INTEGER DEFAULT 0,
                    pass_rate       REAL DEFAULT 0,
                    created_at      TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_test_runs_started ON test_runs(started_at DESC);

                CREATE TABLE IF NOT EXISTS test_run_results (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id          TEXT NOT NULL REFERENCES test_runs(run_id) ON DELETE CASCADE,
                    case_id         TEXT NOT NULL,
                    case_key        TEXT DEFAULT '',
                    source_sheet    TEXT DEFAULT '',
                    row_number      INTEGER DEFAULT 0,
                    description     TEXT DEFAULT '',
                    test_steps      TEXT DEFAULT '',
                    expected_result TEXT DEFAULT '',
                    prerequisites   TEXT DEFAULT '',
                    priority        TEXT DEFAULT '',
                    status          TEXT NOT NULL DEFAULT 'NT',
                    actual_result   TEXT DEFAULT '',
                    match_reason    TEXT DEFAULT '',
                    log_file        TEXT DEFAULT '',
                    duration_seconds REAL DEFAULT 0,
                    tester          TEXT DEFAULT '',
                    test_version    TEXT DEFAULT '',
                    test_date       TEXT DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_run_results_run_id ON test_run_results(run_id);
                CREATE INDEX IF NOT EXISTS idx_run_results_case_id ON test_run_results(case_id);

                CREATE TABLE IF NOT EXISTS test_reports (
                    report_id       TEXT PRIMARY KEY,
                    run_id          TEXT REFERENCES test_runs(run_id) ON DELETE SET NULL,
                    title           TEXT DEFAULT '',
                    report_type     TEXT DEFAULT 'summary',
                    format          TEXT DEFAULT 'html',
                    content         TEXT NOT NULL DEFAULT '',
                    total_count     INTEGER DEFAULT 0,
                    pass_count      INTEGER DEFAULT 0,
                    fail_count      INTEGER DEFAULT 0,
                    pass_rate       REAL DEFAULT 0,
                    tester_name     TEXT DEFAULT '',
                    test_version    TEXT DEFAULT '',
                    created_at      TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_reports_run_id ON test_reports(run_id);
                CREATE INDEX IF NOT EXISTS idx_reports_created ON test_reports(created_at DESC);
                """
            )
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Test run CRUD
    # ------------------------------------------------------------------

    def save_run(self, run_data: dict, case_results: list[dict]) -> None:
        """Save a run and its case results in a transaction."""
        with self._get_conn() as conn:
            # Insert run
            run_fields = [
                "run_id", "session_id", "status", "started_at", "ended_at",
                "duration_seconds", "excel_filename", "excel_path", "sheets_used",
                "tester_name", "test_version", "total_count", "pass_count",
                "fail_count", "block_count", "na_count", "nt_count",
                "review_count", "pass_rate",
            ]
            run_placeholders = ",".join([f":{f}" for f in run_fields])
            conn.execute(
                f"INSERT INTO test_runs ({','.join(run_fields)}) "
                f"VALUES ({run_placeholders})",
                {f: run_data.get(f, "") for f in run_fields},
            )

            # Insert results
            if case_results:
                result_fields = [
                    "run_id", "case_id", "case_key", "source_sheet", "row_number",
                    "description", "test_steps", "expected_result", "prerequisites",
                    "priority", "status", "actual_result", "match_reason", "log_file",
                    "duration_seconds", "tester", "test_version", "test_date",
                ]
                result_placeholders = ",".join([f":{f}" for f in result_fields])
                conn.executemany(
                    f"INSERT INTO test_run_results ({','.join(result_fields)}) "
                    f"VALUES ({result_placeholders})",
                    [{f: case.get(f, "") for f in result_fields} for case in case_results],
                )

    def list_runs(self, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        """Return a paginated list of run metadata without case results."""
        with self._get_conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM test_runs"
            ).fetchone()[0]
            rows = conn.execute(
                """
                SELECT * FROM test_runs
                ORDER BY started_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
            runs = [dict(r) for r in rows]
        return runs, total

    def get_run(self, run_id: str) -> dict | None:
        """Return metadata for a single run."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM test_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_run_results(self, run_id: str) -> list[dict]:
        """Return all case results for a run."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM test_run_results WHERE run_id = ?",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_run(self, run_id: str) -> bool:
        """Delete a run and its results (cascading). Return True if found."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "DELETE FROM test_runs WHERE run_id = ?",
                (run_id,),
            )
            return cur.rowcount > 0

    def delete_runs_batch(self, run_ids: list[str]) -> int:
        """批量删除运行记录（级联删除关联结果），返回实际删除数量。"""
        if not run_ids:
            return 0
        with self._get_conn() as conn:
            placeholders = ",".join("?" for _ in run_ids)
            cur = conn.execute(
                f"DELETE FROM test_runs WHERE run_id IN ({placeholders})",
                run_ids,
            )
            return cur.rowcount

    # ------------------------------------------------------------------
    # Compare runs
    # ------------------------------------------------------------------

    def compare_runs(
        self, run_id_1: str, run_id_2: str
    ) -> dict[str, Any]:
        """Compare case results between two runs.

        Returns a dict with:
          - run1 / run2: run metadata
          - diffs: list of per-case comparison records
          - summary: change counts
        """
        run1 = self.get_run(run_id_1)
        run2 = self.get_run(run_id_2)

        results1 = {r["case_id"]: r for r in self.get_run_results(run_id_1)}
        results2 = {r["case_id"]: r for r in self.get_run_results(run_id_2)}

        all_case_ids = sorted(set(results1.keys()) | set(results2.keys()))

        diffs = []
        changed = 0
        improved = 0
        regressed = 0

        for case_id in all_case_ids:
            r1 = results1.get(case_id, {})
            r2 = results2.get(case_id, {})
            status_1 = r1.get("status", "")
            status_2 = r2.get("status", "")
            description = r1.get("description", "") or r2.get("description", "")

            if status_1 == status_2:
                direction = "unchanged"
            else:
                changed += 1
                if self._is_improved(status_1, status_2):
                    direction = "improved"
                    improved += 1
                elif self._is_regressed(status_1, status_2):
                    direction = "regressed"
                    regressed += 1
                else:
                    direction = "different"

            diffs.append(
                {
                    "case_id": case_id,
                    "description": description,
                    "status_1": status_1,
                    "status_2": status_2,
                    "changed": status_1 != status_2,
                    "direction": direction,
                }
            )

        summary = {
            "total": len(all_case_ids),
            "changed": changed,
            "improved": improved,
            "regressed": regressed,
        }

        return {
            "run1": run1,
            "run2": run2,
            "diffs": diffs,
            "summary": summary,
        }

    @staticmethod
    def _is_improved(status_1: str, status_2: str) -> bool:
        """Return True when status changes from a bad state to Pass."""
        return status_2 == "Pass" and status_1 in ("Fail", "BLOCK", "Review")

    @staticmethod
    def _is_regressed(status_1: str, status_2: str) -> bool:
        """Return True when status changes from Pass to a bad state."""
        return status_1 == "Pass" and status_2 in ("Fail", "BLOCK", "Review")

    # ------------------------------------------------------------------
    # Report CRUD
    # ------------------------------------------------------------------

    def save_report(self, report_data: dict) -> None:
        """Save a report snapshot."""
        fields = [
            "report_id", "run_id", "title", "report_type", "format",
            "content", "total_count", "pass_count", "fail_count",
            "pass_rate", "tester_name", "test_version",
        ]
        placeholders = ",".join([f":{f}" for f in fields])
        with self._get_conn() as conn:
            conn.execute(
                f"INSERT INTO test_reports ({','.join(fields)}) "
                f"VALUES ({placeholders})",
                {f: report_data.get(f, "") for f in fields},
            )

    def list_reports(
        self, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict], int]:
        """Return a paginated list of reports without content field."""
        with self._get_conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM test_reports"
            ).fetchone()[0]
            rows = conn.execute(
                """
                SELECT
                    report_id, run_id, title, report_type, format,
                    total_count, pass_count, fail_count, pass_rate,
                    tester_name, test_version, created_at
                FROM test_reports
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
            reports = [dict(r) for r in rows]
        return reports, total

    def get_report(self, report_id: str) -> dict | None:
        """Return a full report including content."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM test_reports WHERE report_id = ?",
                (report_id,),
            ).fetchone()
            return dict(row) if row else None

    def delete_report(self, report_id: str) -> bool:
        """Delete a report. Return True if it existed."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "DELETE FROM test_reports WHERE report_id = ?",
                (report_id,),
            )
            return cur.rowcount > 0


# ------------------------------------------------------------------
# Singleton
# ------------------------------------------------------------------
_instance: HistoryStore | None = None


def get_history_store() -> HistoryStore:
    global _instance
    if _instance is None:
        _instance = HistoryStore()
    return _instance
