"""日志图片渲染缓存：输入完全一致时复用缓存，任一参数变化则重新渲染。"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND_DIR)

from PIL import Image as PILImage  # noqa: E402

from app.core import log_image  # noqa: E402

_LOG_TEXT = "line one\nline two\nline three\nline four"


def _render(**overrides):
    kwargs = dict(status="pass", width=400, max_height=520, font_size=10)
    kwargs.update(overrides)
    return log_image.render_log_image(_LOG_TEXT, **kwargs)


def _count_renders(monkeypatch):
    """统计实际创建画布（即真实渲染）的次数。"""
    calls = {"count": 0}
    original_new = PILImage.new

    def counting_new(*args, **kwargs):
        calls["count"] += 1
        return original_new(*args, **kwargs)

    monkeypatch.setattr(PILImage, "new", counting_new)
    log_image.clear_log_image_cache()
    return calls


def test_same_inputs_reuse_cache(monkeypatch):
    calls = _count_renders(monkeypatch)

    first = _render()
    second = _render()

    assert first is not None and second is not None
    assert calls["count"] == 1
    assert first.getvalue() == second.getvalue()


def test_cached_buffer_is_independent(monkeypatch):
    """返回给调用方的是独立流，消费一次不会影响下一次复用。"""
    _count_renders(monkeypatch)

    first = _render()
    assert first is not None
    first.read()
    first.close()

    second = _render()
    assert second is not None
    assert second.getvalue()


def test_cache_can_hold_a_full_report(monkeypatch):
    """容量必须大于一次导出的图片数，否则顺序渲染会边写边淘汰（命中率≈0）。"""
    _count_renders(monkeypatch)
    # 典型报告约 100~500 条用例，每条 1~2 个终端。
    assert log_image._LOG_IMAGE_CACHE_MAX_ENTRIES >= 1024
    assert log_image._LOG_IMAGE_CACHE_MAX_BYTES >= 64 * 1024 * 1024


def test_changed_log_text_rerenders(monkeypatch):
    calls = _count_renders(monkeypatch)

    _render()
    log_image.render_log_image(_LOG_TEXT + "\nline five", status="pass")

    assert calls["count"] == 2


def test_changed_highlight_lines_rerenders(monkeypatch):
    calls = _count_renders(monkeypatch)

    _render(highlight_lines=[1])
    _render(highlight_lines=[2])

    assert calls["count"] == 2


def test_changed_render_size_or_max_height_rerenders(monkeypatch):
    calls = _count_renders(monkeypatch)

    _render(width=400, max_height=520)
    _render(width=401, max_height=520)
    _render(width=401, max_height=521)

    assert calls["count"] == 3
