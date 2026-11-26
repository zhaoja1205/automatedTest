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
    # 内存里保存的日志与最终文件一致，备注优先使用这份内容
    assert case._remark_log == saved


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
    assert case._remark_log == saved


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


def test_case_log_paths_do_not_collide_for_same_case_id(tmp_path):
    """同 case_id、同一秒内执行的不同用例不能写成同一个日志文件。

    Excel 中未填用例 ID 时统一按 ``N/A`` 占位，不同 Sheet 的同名 ID 也
    很常见；旧命名只带 case_id + 秒级时间，先写入的日志会被后一条覆盖，
    下载结果时一条用例的「备注」里就会出现另一条用例的日志。
    """
    adapter = ExecutorAdapter(
        None, None, workspace=SimpleNamespace(case_log_max_kb=0),
        log_dir=str(tmp_path))
    first = SimpleNamespace(
        case_id="N/A", source_sheet="稳定性测试", row_number=15, log_file="",
    )
    second = SimpleNamespace(
        case_id="N/A", source_sheet="稳定性测试", row_number=16, log_file="",
    )

    path1 = adapter._new_case_log_path(first)
    path2 = adapter._new_case_log_path(second)

    assert path1 != path2
    # N/A 中的斜杠不能再当成目录分隔符生成子目录
    assert os.path.dirname(path1) == str(tmp_path)
    assert os.path.dirname(path2) == str(tmp_path)

    adapter._write_case_log(first, SimpleNamespace(log_file=""), "LOG_OF_FIRST")
    adapter._write_case_log(second, SimpleNamespace(log_file=""), "LOG_OF_SECOND")
    with open(path1, encoding="utf-8") as f:
        assert f.read() == "LOG_OF_FIRST"
    with open(path2, encoding="utf-8") as f:
        assert f.read() == "LOG_OF_SECOND"


def test_case_log_path_is_not_overwritten_within_same_second(tmp_path):
    """同一条用例在同一秒内重复执行时，也不覆盖上一个日志文件。"""
    adapter = ExecutorAdapter(
        None, None, workspace=SimpleNamespace(case_log_max_kb=0),
        log_dir=str(tmp_path))
    case = SimpleNamespace(
        case_id="TC5", source_sheet="功能测试", row_number=15, log_file="",
    )

    path1 = adapter._new_case_log_path(case)
    with open(path1, "w", encoding="utf-8") as f:
        f.write("first")
    path2 = adapter._new_case_log_path(case)

    assert path2 != path1
    assert path2.startswith(os.path.splitext(path1)[0])
