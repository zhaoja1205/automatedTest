"""用例执行日志上限单测：超过上限时从后往前截取（保留末尾最近输出）。"""
import os
import sys
from types import SimpleNamespace

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND_DIR)

from app.core.executor_adapter import (  # noqa: E402
    ExecutorAdapter, _LOG_TRUNCATED_NOTE,
)
from app.core.terminal_log import parse_terminal_log  # noqa: E402


def _multi_terminal_log(a_lines=2000, b_lines=20):
    """模拟聚合日志：终端A 输出很多，终端B 输出很少。"""
    a = "===== 终端A =====\n" + "\n".join(f"a{i:04d}" for i in range(a_lines))
    b = "===== 终端B =====\n" + "\n".join(f"b{i:04d}" for i in range(b_lines))
    return a + "\n\n" + b


class _Workspace:
    """最小工作区替身：1 KB 上限。"""
    case_log_max_kb = 1


def test_cap_log_text_keeps_tail():
    text = "\n".join(f"line {i:04d}" for i in range(2000))
    capped = ExecutorAdapter._cap_log_text(text, 1024)
    assert len(capped) <= 1024
    assert capped.startswith(_LOG_TRUNCATED_NOTE)
    assert capped.endswith("line 1999")
    assert "line 0000" not in capped


def test_cap_log_text_no_limit_when_zero_or_within_limit():
    assert ExecutorAdapter._cap_log_text("abc", 0) == "abc"
    assert ExecutorAdapter._cap_log_text("abc", 10) == "abc"


def test_cap_log_text_does_not_stack_markers():
    capped = ExecutorAdapter._cap_log_text(_LOG_TRUNCATED_NOTE + "x" * 5000, 1024)
    assert capped.count(_LOG_TRUNCATED_NOTE) == 1
    assert len(capped) <= 1024


def test_write_case_log_truncates_from_end(tmp_path):
    adapter = ExecutorAdapter(None, None, workspace=_Workspace(), log_dir=str(tmp_path))
    case = SimpleNamespace(case_id="TC1", log_file="")
    result = SimpleNamespace(log_file="")
    content = "\n".join(f"line {i:04d}" for i in range(2000))

    path = adapter._write_case_log(case, result, content)
    assert path

    with open(path, encoding="utf-8") as f:
        saved = f.read()
    assert len(saved) <= 1024
    assert saved.startswith(_LOG_TRUNCATED_NOTE)
    assert saved.rstrip("\n").endswith("line 1999")
    assert "line 0000" not in saved
    assert result.log_file == path and case.log_file == path


def test_append_respects_limit_and_keeps_newest_output(tmp_path):
    adapter = ExecutorAdapter(None, None, workspace=_Workspace(), log_dir=str(tmp_path))
    case = SimpleNamespace(case_id="TC2", log_file="")
    result = SimpleNamespace(log_file="")

    path = adapter._write_case_log(case, result, "FIRST\n" + "a" * 900)
    path = adapter._write_case_log(
        case, result, "SECOND\n" + "b" * 900, log_file=path, append=True)

    with open(path, encoding="utf-8") as f:
        saved = f.read()
    assert len(saved) <= 1024
    assert saved.rstrip("\n").endswith("b" * 20)
    assert "SECOND" in saved


def test_write_case_log_without_limit_keeps_full_content(tmp_path):
    adapter = ExecutorAdapter(
        None, None, workspace=SimpleNamespace(case_log_max_kb=0), log_dir=str(tmp_path))
    case = SimpleNamespace(case_id="TC3", log_file="")
    result = SimpleNamespace(log_file="")
    content = "\n".join(f"line {i:04d}" for i in range(2000))

    path = adapter._write_case_log(case, result, content)
    with open(path, encoding="utf-8") as f:
        saved = f.read()
    assert "line 0000" in saved
    assert len(saved) == len(content)


def test_cap_log_text_keeps_each_terminal_section():
    capped = ExecutorAdapter._cap_log_text(_multi_terminal_log(), 1024)
    assert len(capped) <= 1024
    assert capped.startswith(_LOG_TRUNCATED_NOTE)
    # 每个终端的标题都要保留，否则备注里会整段丢失该终端
    assert "===== 终端A =====" in capped
    assert "===== 终端B =====" in capped
    assert "a0000" not in capped          # 终端A 前部被截掉
    assert "a1999" in capped               # 终端A 保留末尾
    assert "b0000" in capped and "b0019" in capped  # 终端B 短，完整保留

    labels = [label for label, _ in parse_terminal_log(capped)]
    assert labels == ["终端A", "终端B"]


def test_cap_log_text_marks_truncated_terminal_with_body():
    capped = ExecutorAdapter._cap_log_text(_multi_terminal_log(a_lines=4000), 2048)
    assert len(capped) <= 2048
    labels = [label for label, _ in parse_terminal_log(capped)]
    assert labels == ["终端A", "终端B"]
    # 终端A 段落里有内容（不只标题），说明截断保留了该终端的尾部输出
    a_text = dict(parse_terminal_log(capped))["终端A"]
    assert "a3999" in a_text


def test_append_keeps_terminal_headers(tmp_path):
    adapter = ExecutorAdapter(None, None, workspace=_Workspace(), log_dir=str(tmp_path))
    case = SimpleNamespace(case_id="TC4", log_file="")
    result = SimpleNamespace(log_file="")

    path = adapter._write_case_log(case, result, _multi_terminal_log())
    path = adapter._write_case_log(
        case, result, "[执行异常] boom\n", log_file=path, append=True)

    with open(path, encoding="utf-8") as f:
        saved = f.read()
    assert len(saved) <= 1024
    assert saved.count(_LOG_TRUNCATED_NOTE) == 1
    assert [label for label, _ in parse_terminal_log(saved)] == ["终端A", "终端B"]
