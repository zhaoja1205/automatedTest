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


def _make_request_with_cases(image_root: str, test_cases: list):
    session = SimpleNamespace(
        workspace=SimpleNamespace(image_download_path=image_root),
        test_cases=test_cases,
    )
    return SimpleNamespace(state=SimpleNamespace(session=session), headers={})


def test_legacy_dir_is_scoped_by_execution_state():
    """旧布局（<base>/<case_id>）没有 Sheet 维度：没执行的 Sheet 不该看到图片。"""
    image_root = tempfile.mkdtemp(prefix="case_image_legacy_")
    case_dir = os.path.join(image_root, "001")
    os.makedirs(case_dir)
    with open(os.path.join(case_dir, "1.png"), "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"0" * 1024)

    cases = [
        {"case_key": "功能测试:15:001", "case_id": "001",
         "source_sheet": "功能测试", "status": "Pass"},
        {"case_key": "故障测试:15:001", "case_id": "001",
         "source_sheet": "故障测试", "status": "NT"},
    ]
    ft = asyncio.run(routes.list_case_images(
        _make_request_with_cases(image_root, cases), "001", "功能测试"))
    fault = asyncio.run(routes.list_case_images(
        _make_request_with_cases(image_root, cases), "001", "故障测试"))
    assert [i["name"] for i in ft["images"]] == ["1.png"]
    assert fault["images"] == []


def test_availability_is_keyed_by_case_key():
    image_root = tempfile.mkdtemp(prefix="case_image_avail_")
    case_dir = os.path.join(image_root, "001")
    os.makedirs(case_dir)
    with open(os.path.join(case_dir, "1.png"), "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"0" * 1024)

    cases = [
        {"case_key": "功能测试:15:001", "case_id": "001",
         "source_sheet": "功能测试", "status": "Pass"},
        {"case_key": "故障测试:15:001", "case_id": "001",
         "source_sheet": "故障测试", "status": "NT"},
    ]
    refs = [
        routes.CaseImageRef(case_key="功能测试:15:001", case_id="001",
                            source_sheet="功能测试"),
        routes.CaseImageRef(case_key="故障测试:15:001", case_id="001",
                            source_sheet="故障测试"),
    ]
    result = asyncio.run(routes.case_images_availability(
        _make_request_with_cases(image_root, cases), refs))
    assert result["cases"] == {"功能测试:15:001": True, "故障测试:15:001": False}
