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
    # 多张截图横向并排：按水平偏移排序
    images = sorted(ws._images, key=lambda img: img.anchor._from.colOff)
    assert len(images) == 2

    widths = [round(EMU_to_pixels(img.anchor.ext.cx)) for img in images]
    heights = [round(EMU_to_pixels(img.anchor.ext.cy)) for img in images]
    offsets = [round(EMU_to_pixels(img.anchor._from.rowOff)) for img in images]
    col_offsets = [
        round(EMU_to_pixels(img.anchor._from.colOff)) for img in images
    ]

    # 同一行并排：顶部留白一致
    assert offsets == [pad, pad]

    # 左侧留白 + 图间距：第二张 = 第一张左侧 + 宽度 + 图间距
    assert col_offsets[0] == pad
    assert col_offsets[1] == col_offsets[0] + widths[0] + gap

    # 行高 = 顶部留白 + 最高截图 + 底部留白（1px ≈ 0.75pt）
    expected = (pad + max(heights) + pad) * 0.75 + 2
    assert ws.row_dimensions[15].height == expected

    # 列宽按「截图行总宽 + 左右各 pad」计算，右侧留白与左侧一致
    total = pad + sum(widths) + gap * (len(images) - 1) + pad
    assert ws.column_dimensions["M"].width * 7 >= total


def test_case_image_padding_and_gap_from_config(tmp_path):
    """工作区配置传入的 pad / gap 生效（覆盖类默认常量）。"""
    from openpyxl.utils.units import EMU_to_pixels

    path = _build_case_workbook(tmp_path / "case.xlsx")
    image_base = _case_image_dir(tmp_path / "images", "FT_001", count=3)

    pad, gap = 30, 40
    handler = ExcelHandler()
    handler.load(str(path))
    assert handler.embed_case_images(image_base, pad=pad, gap=gap) == 3
    handler.save(str(path))

    ws = load_workbook(str(path))["功能测试"]
    images = sorted(ws._images, key=lambda img: img.anchor._from.colOff)
    assert len(images) == 3

    widths = [round(EMU_to_pixels(img.anchor.ext.cx)) for img in images]
    heights = [round(EMU_to_pixels(img.anchor.ext.cy)) for img in images]
    offsets = [round(EMU_to_pixels(img.anchor._from.rowOff)) for img in images]
    col_offsets = [
        round(EMU_to_pixels(img.anchor._from.colOff)) for img in images
    ]

    assert offsets == [pad, pad, pad]
    assert col_offsets[0] == pad
    assert col_offsets[1] == col_offsets[0] + widths[0] + gap
    assert col_offsets[2] == col_offsets[1] + widths[1] + gap

    expected = (pad + max(heights) + pad) * 0.75 + 2
    assert ws.row_dimensions[15].height == expected
    total = pad + sum(widths) + gap * (len(images) - 1) + pad
    assert ws.column_dimensions["M"].width * 7 >= total


def test_case_image_zero_padding_allowed(tmp_path):
    """pad / gap 允许设为 0：图片贴着单元格排列、互不间隔。"""
    from openpyxl.utils.units import EMU_to_pixels

    path = _build_case_workbook(tmp_path / "case.xlsx")
    image_base = _case_image_dir(tmp_path / "images", "FT_001")

    handler = ExcelHandler()
    handler.load(str(path))
    assert handler.embed_case_images(image_base, pad=0, gap=0) == 2
    handler.save(str(path))

    ws = load_workbook(str(path))["功能测试"]
    images = sorted(ws._images, key=lambda img: img.anchor._from.colOff)
    widths = [round(EMU_to_pixels(img.anchor.ext.cx)) for img in images]
    offsets = [round(EMU_to_pixels(img.anchor._from.rowOff)) for img in images]
    col_offsets = [
        round(EMU_to_pixels(img.anchor._from.colOff)) for img in images
    ]
    # pad=0 / gap=0：图片贴单元格左上角，第二张紧接第一张宽度处
    assert offsets == [0, 0]
    assert col_offsets == [0, widths[0]]


def test_log_image_padding_and_gap_from_config(tmp_path):
    """日志图片同样按配置的 pad / gap 排列，返回底边含顶部留白。"""
    from openpyxl.utils.units import EMU_to_pixels

    path = _build_case_workbook(tmp_path / "case.xlsx")
    wb = load_workbook(str(path))
    wb["功能测试"]["M15"] = (
        "--- 执行日志 ---\n"
        "===== 终端1 =====\nline a\nline b\n"
        "===== 终端2 =====\nsecond terminal\n"
    )
    wb.save(str(path))

    pad, gap = 20, 30
    handler = ExcelHandler()
    handler.load(str(path))
    bottoms = handler.embed_log_images(pad=pad, gap=gap)
    handler.save(str(path))

    ws = load_workbook(str(path))["功能测试"]
    images = sorted(ws._images, key=lambda img: img.anchor._from.rowOff)
    assert len(images) == 2
    for img in images:
        assert round(EMU_to_pixels(img.anchor._from.colOff)) == pad

    first = round(EMU_to_pixels(images[0].anchor._from.rowOff))
    second = round(EMU_to_pixels(images[1].anchor._from.rowOff))
    disp_h = round(EMU_to_pixels(images[0].anchor.ext.cy))
    assert first == pad
    assert second == first + disp_h + gap

    # 返回的底边 = 最后一张图片的底边（含顶部留白，不含底部留白）
    last_h = round(EMU_to_pixels(images[1].anchor.ext.cy))
    assert bottoms[("功能测试", 15)] == second + last_h


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


def test_multiple_case_images_side_by_side_keep_size(tmp_path):
    """多张 yuv 截图横向并排、保持原尺寸，整行落在 Excel 行高上限内。

    背景：Excel 单行最高 409 磅（约 545px）。截图此前纵向堆叠，日志图片 +
    2 张截图即超过上限，行高被截断后图片压到下一行。改为横向并排后，
    行高只按「日志图片 + 一行截图」计算。
    """
    from openpyxl.utils.units import EMU_to_pixels

    path = _build_case_workbook(tmp_path / "case.xlsx")
    wb = load_workbook(str(path))
    wb["功能测试"]["M15"] = (
        "--- 执行日志 ---\n"
        "===== 终端A =====\n"
        + "\n".join(
            f"line {i} Sensor0_Out1 Frame rate (fps): 29.49" for i in range(80)
        )
    )
    wb.save(str(path))

    # 模拟 3840x2160 的 yuv 转 PNG（embed 前统一缩到 source_max_width=480）
    image_base = tmp_path / "images"
    case_dir = image_base / "功能测试" / "FT_001"
    case_dir.mkdir(parents=True)
    for index in (1, 2):
        PILImage.new("RGB", (480, 270), (index * 40, 0, 0)).save(
            str(case_dir / f"{index}.png"))

    handler = ExcelHandler()
    handler.load(str(path))
    bottoms = handler.embed_log_images()
    assert handler.embed_case_images(
        str(image_base), start_offsets=bottoms,
        remove_existing=False,
    ) == 2
    handler.save(str(path))

    ws = load_workbook(str(path))["功能测试"]
    images = sorted(
        ws._images,
        key=lambda img: (img.anchor._from.rowOff, img.anchor._from.colOff),
    )
    assert len(images) == 3

    heights = [round(EMU_to_pixels(img.anchor.ext.cy)) for img in images]
    widths = [round(EMU_to_pixels(img.anchor.ext.cx)) for img in images]
    offsets = [round(EMU_to_pixels(img.anchor._from.rowOff)) for img in images]
    col_offsets = [
        round(EMU_to_pixels(img.anchor._from.colOff)) for img in images
    ]

    pad = ExcelHandler.REMARK_IMAGE_PAD
    gap = ExcelHandler.REMARK_IMAGE_GAP

    # 日志图片在上方、顶部留白 pad
    assert offsets[0] == pad
    # 截图排在日志图片下方（相隔一个图间距），同一行并排
    screenshot_top = offsets[0] + heights[0] + gap
    assert offsets[1:] == [screenshot_top, screenshot_top]
    assert col_offsets[1] == pad
    assert col_offsets[2] == col_offsets[1] + widths[1] + gap

    # 截图保持原尺寸（170px 宽），未被缩小
    assert widths[1:] == [170, 170]
    assert abs(widths[1] / heights[1] - 480 / 270) < 0.05

    # 行高不超过 Excel 上限，截图底边 + 底部留白落在行内
    row_pt = ws.row_dimensions[15].height
    assert row_pt <= ExcelHandler.EXCEL_MAX_ROW_HEIGHT_PT
    assert screenshot_top + heights[1] + pad <= row_pt * 4 / 3 + 1


def test_many_case_images_shrink_to_excel_column_limit(tmp_path):
    """截图再多也只横向排一行；超出 Excel 列宽上限时等比缩小。"""
    from openpyxl.utils.units import EMU_to_pixels

    path = _build_case_workbook(tmp_path / "case.xlsx")
    image_base = tmp_path / "images"
    case_dir = image_base / "功能测试" / "FT_001"
    case_dir.mkdir(parents=True)
    for index in range(12):
        PILImage.new("RGB", (480, 270), (index * 15, 0, 0)).save(
            str(case_dir / f"{index + 1}.png"))

    handler = ExcelHandler()
    handler.load(str(path))
    assert handler.embed_case_images(str(image_base)) == 12
    handler.save(str(path))

    ws = load_workbook(str(path))["功能测试"]
    images = sorted(ws._images, key=lambda img: img.anchor._from.colOff)
    assert len(images) == 12

    widths = [round(EMU_to_pixels(img.anchor.ext.cx)) for img in images]
    heights = [round(EMU_to_pixels(img.anchor.ext.cy)) for img in images]
    offsets = [round(EMU_to_pixels(img.anchor._from.rowOff)) for img in images]
    col_offsets = [
        round(EMU_to_pixels(img.anchor._from.colOff)) for img in images
    ]

    pad = ExcelHandler.REMARK_IMAGE_PAD
    gap = ExcelHandler.REMARK_IMAGE_GAP

    # 同一行并排，超出列宽上限后截图被等比缩小
    assert offsets == [pad] * 12
    assert widths[0] < 170
    total = pad + sum(widths) + gap * (len(images) - 1) + pad
    assert total <= ExcelHandler.EXCEL_MAX_COLUMN_WIDTH_CHARS * 7 + 1
    assert abs(widths[0] / heights[0] - 480 / 270) < 0.05

    # 列宽在 Excel 上限内，行高只需容纳一行截图
    assert ws.column_dimensions["M"].width <= ExcelHandler.EXCEL_MAX_COLUMN_WIDTH_CHARS
    expected = (pad + max(heights) + pad) * 0.75 + 2
    assert ws.row_dimensions[15].height == expected
