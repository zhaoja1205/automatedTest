"""取图接口的缓存语义：Cache-Control: no-store，永不回 304。"""
import asyncio
import os
import sys
import tempfile
from types import SimpleNamespace

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND_DIR)

from app.api import routes  # noqa: E402

_CASE_ID = "case1"
_FILENAME = "a.png"


def _make_request(image_root: str, if_none_match: str = ""):
    session = SimpleNamespace(
        workspace=SimpleNamespace(image_download_path=image_root)
    )
    headers = {"if-none-match": if_none_match} if if_none_match else {}
    return SimpleNamespace(
        state=SimpleNamespace(session=session), headers=headers
    )


def _setup_image(payload=b"\x89PNG\r\n\x1a\n" + b"0" * 2048):
    image_root = tempfile.mkdtemp(prefix="case_image_cache_")
    case_dir = os.path.join(image_root, _CASE_ID)
    os.makedirs(case_dir)
    path = os.path.join(case_dir, _FILENAME)
    with open(path, "wb") as f:
        f.write(payload)
    return image_root, path


def _call(image_root: str, if_none_match: str = ""):
    return asyncio.run(
        routes.get_case_image(
            _make_request(image_root, if_none_match), _CASE_ID, _FILENAME
        )
    )


def test_image_response_disables_caching():
    image_root, _ = _setup_image()
    response = _call(image_root)
    headers = dict(response.headers)
    assert response.status_code == 200
    assert headers["cache-control"] == "no-store"


def test_conditional_header_never_yields_304():
    """即使客户端带回 ETag，也返回完整 200（接口不做任何校验缓存）。"""
    image_root, _ = _setup_image()
    etag = dict(_call(image_root).headers).get("etag", "")
    assert etag
    response = _call(image_root, etag)
    assert response.status_code == 200
    assert dict(response.headers)["cache-control"] == "no-store"


def test_overwritten_image_is_served_from_disk():
    image_root, path = _setup_image()
    _call(image_root)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"1" * 4096)
    response = _call(image_root)
    assert response.status_code == 200
    assert getattr(response.stat_result, "st_size", None) == os.path.getsize(path)
