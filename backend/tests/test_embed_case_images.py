"""下载结果时重复嵌入用例图片不应叠加。"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND_DIR)

from openpyxl import Workbook, load_workbook  # noqa: E402
from openpyxl.drawing.image import Image as XLImage  # noqa: E402
from PIL import Image as PILImage  # noqa: E402

from app.core.excel_handler import ExcelHandler  # noqa: E402


def _build_case_workbook(path, logo_path="", case_id="FT_001"):
    wb = Workbook()
    ws = wb.active
    ws.title = "功能测试"
    headers = {
        "B": "测试用例ID", "C": "测试类型", "E": "测试用例描述",
        "K": "实际结果", "L": "BUG", "M": "备注",
        "N": "测试版本", "O": "实施者", "P": "测试日期",
    }
    for col, title in headers.items():
        ws[f"{col}13"] = title
    ws["B15"] = case_id
    ws["C15"] = "功能"
    ws["E15"] = "起流测试"
    if logo_path:
        # 非备注列的图片不应被清理
        ws.add_image(XLImage(logo_path), "A1")
    wb.save(path)
    return path


def _make_png(path, color):
    PILImage.new("RGB", (120, 80), color).save(path)
    return path


def _case_image_dir(base, case_id, count=2):
    case_dir = os.path.join(base, case_id)
    os.makedirs(case_dir, exist_ok=True)
    for index in range(count):
        _make_png(os.path.join(case_dir, f"{index + 1}.png"), (255, 0, 0))
    return base


def test_embed_case_images_is_idempotent_across_downloads(tmp_path):
    path = _build_case_workbook(tmp_path / "case.xlsx", _make_png(tmp_path / "logo.png", (0, 0, 255)))
    image_base = _case_image_dir(tmp_path / "images", "FT_001")

    handler = ExcelHandler()
    handler.load(str(path))
    assert handler.embed_case_images(image_base) == 2
    handler.save(str(path))

    ws = load_workbook(str(path))["功能测试"]
    # 1 张 A1 的图片 + 2 张备注列截图
    assert len(ws._images) == 3

    # 模拟下载结果被重新上传后再下载：旧截图应被替换而不是叠加
    handler = ExcelHandler()
    handler.load(str(path))
    assert handler.embed_case_images(image_base) == 2
    handler.save(str(path))

    ws = load_workbook(str(path))["功能测试"]
    assert len(ws._images) == 3
    anchors = [(img.anchor._from.col, img.anchor._from.row) for img in ws._images]
    assert anchors.count((0, 0)) == 1
    assert anchors.count((12, 14)) == 2
