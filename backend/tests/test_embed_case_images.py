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


def test_case_image_padding_and_gap(tmp_path):
    """备注列截图上下左右留白一致，多张截图之间按 REMARK_IMAGE_GAP 间隔。"""
    from openpyxl.utils.units import EMU_to_pixels

    path = _build_case_workbook(tmp_path / "case.xlsx")
    image_base = _case_image_dir(tmp_path / "images", "FT_001")

    handler = ExcelHandler()
    handler.load(str(path))
    assert handler.embed_case_images(image_base) == 2
    handler.save(str(path))

    ws = load_workbook(str(path))["功能测试"]
    pad = ExcelHandler.REMARK_IMAGE_PAD
    gap = ExcelHandler.REMARK_IMAGE_GAP
    images = sorted(ws._images, key=lambda img: img.anchor._from.rowOff)
    assert len(images) == 2

    # 左侧留白：图片从 colOff = pad 处开始
    for img in images:
        assert round(EMU_to_pixels(img.anchor._from.colOff)) == pad

    # 顶部留白 + 图间距：第二张 = 顶部留白 + 第一张高度 + 图间距
    first = round(EMU_to_pixels(images[0].anchor._from.rowOff))
    second = round(EMU_to_pixels(images[1].anchor._from.rowOff))
    assert first == pad
    assert second == first + images[0].height + gap

    # 行高在最后一张图片下方再留 pad（1px ≈ 0.75pt）
    expected = (second + images[1].height + pad) * 0.75 + 2
    assert ws.row_dimensions[15].height == expected

    # 列宽按「图片宽 + 左右各 pad」计算，右侧留白与左侧一致
    width_chars = ws.column_dimensions["M"].width
    assert width_chars * 7 >= images[0].width + 2 * pad


def _build_two_sheet_workbook(path, case_id="001", row=15):
    """功能测试 / 故障测试各有一行，case_id 相同（真实模板的常见情况）。"""
    wb = Workbook()
    ft = wb.active
    ft.title = "功能测试"
    fault = wb.create_sheet("故障测试")
    for ws in (ft, fault):
        ws["B13"] = "测试用例ID"
        ws["C13"] = "测试类型"
        ws["E13"] = "测试用例描述"
        ws["K13"] = "实际结果"
        ws["L13"] = "BUG"
        ws["M13"] = "备注"
        ws[f"B{row}"] = case_id
        ws[f"C{row}"] = "功能"
        ws[f"E{row}"] = "起流测试"
    wb.save(path)
    return path


def test_case_images_are_scoped_by_sheet(tmp_path):
    path = _build_two_sheet_workbook(tmp_path / "cases.xlsx")
    # 新布局：图片在 <base>/<Sheet>/<case_id>/ 下，只有功能测试表执行过
    image_base = tmp_path / "images"
    case_dir = image_base / "功能测试" / "001"
    case_dir.mkdir(parents=True)
    _make_png(str(case_dir / "1.png"), (255, 0, 0))

    handler = ExcelHandler()
    handler.load(str(path))
    assert handler.embed_case_images(str(image_base)) == 1
    handler.save(str(path))

    wb = load_workbook(str(path))
    assert len(getattr(wb["功能测试"], "_images", [])) == 1
    assert len(getattr(wb["故障测试"], "_images", [])) == 0


def test_legacy_duplicate_case_id_only_embeds_executed_sheet(tmp_path):
    path = _build_two_sheet_workbook(tmp_path / "cases.xlsx")
    # 旧布局：图片在 <base>/<case_id>/ 下，两个 Sheet 无法靠目录区分归属
    image_base = _case_image_dir(tmp_path / "images", "001", count=1)

    handler = ExcelHandler()
    handler.load(str(path))
    embedded = handler.embed_case_images(
        str(image_base), executed_keys={"功能测试:15:001"}
    )
    handler.save(str(path))

    wb = load_workbook(str(path))
    assert embedded == 1
    assert len(getattr(wb["功能测试"], "_images", [])) == 1
    assert len(getattr(wb["故障测试"], "_images", [])) == 0


def test_image_store_layout(tmp_path):
    from app.core.image_store import case_image_dir, resolve_case_image_dir

    base = str(tmp_path)
    ft_dir = case_image_dir(base, "001", "功能测试")
    assert ft_dir == os.path.join(os.path.abspath(base), "功能测试", "001")
    # Sheet 名里的非法路径字符会被替换
    assert "/" not in case_image_dir(base, "001", "功能/测试").split(
        os.path.abspath(base) + os.sep)[1].split(os.sep)[0]

    # 新布局目录存在时优先使用
    os.makedirs(ft_dir)
    _make_png(os.path.join(ft_dir, "1.png"), (255, 0, 0))
    resolved, layout = resolve_case_image_dir(base, "001", "功能测试")
    assert layout == "sheet" and resolved == ft_dir

    # 故障测试没有自己的目录时回退旧布局（历史数据）
    legacy = os.path.join(os.path.abspath(base), "001")
    os.makedirs(legacy, exist_ok=True)
    resolved2, layout2 = resolve_case_image_dir(base, "001", "故障测试")
    assert layout2 == "legacy" and resolved2 == legacy
