#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 YUV 裸数据转成 PNG / JPG（纯 Pillow 实现，不需要 numpy / opencv / ffmpeg）。

支持的像素格式
  nv12   Y 平面(3840x2160) + UV 交错平面        —— 摄像头 / USB Cam / Android 常见
  i420   Y + U + V 三个平面（=YUV420p）         —— x264 / ffmpeg 默认
  yuyv   YUYV422 打包格式，每像素 2 字节         —— 部分 UVC 相机
  auto   按文件大小 + 色度平面行宽自动判断（默认）

色彩范围
  limited  Y 16-235 / C 16-240（TV range，摄像头 ISP 输出默认）
  full     0-255（PC range）

用法
  python3 yuv2img.py in.yuv -W 3840 -H 2160                    # 自动识别 -> PNG
  python3 yuv2img.py in.yuv -W 3840 -H 2160 --jpg             # 存 JPG
  python3 yuv2img.py in.yuv -W 3840 -H 2160 -f i420 -o out.png
  python3 yuv2img.py in.yuv -W 3840 -H 2160 --frame 0 --jpg   # 只取第 0 帧
  python3 yuv2img.py in.yuv -W 3840 -H 2160 --range full     # 若片源是全范围
  python3 yuv2img.py in.yuv -W 3840 -H 2160 --autocontrast   # 偏暗时拉一下对比
"""

import argparse
import os
import statistics
import struct
import sys
import zlib
from typing import Optional

try:  # Pillow 为可选依赖：缺失时后端会使用内置 PNG 编码器（见文件末尾）
    from PIL import Image, ImageOps
    _PIL_AVAILABLE = True
except ImportError:  # pragma: no cover - 取决于部署环境
    Image = None
    ImageOps = None
    _PIL_AVAILABLE = False

def _luts(limited):
    if not limited:
        ident = list(range(256))
        return ident, ident
    y = [max(0, min(255, int(round((v - 16) * 255.0 / 219.0)))) for v in range(256)]
    c = [max(0, min(255, int(round((v - 128) * 255.0 / 224.0 + 128)))) for v in range(256)]
    return y, c


def _plane(raw, size, lut):
    return Image.frombytes("L", size, raw).point(lut)


def _compose(y, cb_small, cr_small, w, h, stretch):
    """把 Y(全分辨率) 与两个半分辨率色度平面合成 RGB"""
    if stretch:
        y = ImageOps.autocontrast(y, cutoff=0.2)
    cb = cb_small.resize((w, h), Image.BILINEAR)
    cr = cr_small.resize((w, h), Image.BILINEAR)
    return Image.merge("YCbCr", (y, cb, cr)).convert("RGB")


def nv12_to_rgb(data, w, h, limited=True, stretch=False):
    ylut, clut = _luts(limited)
    y = _plane(data[: w * h], (w, h), ylut)
    uv = data[w * h:]
    cb = _plane(uv[0::2], (w // 2, h // 2), clut)   # U
    cr = _plane(uv[1::2], (w // 2, h // 2), clut)   # V
    return _compose(y, cb, cr, w, h, stretch)


def i420_to_rgb(data, w, h, limited=True, stretch=False):
    ylut, clut = _luts(limited)
    n = w * h
    q = n // 4
    y = _plane(data[:n], (w, h), ylut)
    cb = _plane(data[n: n + q], (w // 2, h // 2), clut)
    cr = _plane(data[n + q: n + 2 * q], (w // 2, h // 2), clut)
    return _compose(y, cb, cr, w, h, stretch)


def yuyv_to_rgb(data, w, h, limited=True, stretch=False):
    ylut, clut = _luts(limited)
    # Y0 U Y1 V -> Y 交错还原, U/V 各取一半
    yraw = bytearray(w * h)
    yraw[0::2] = data[0::4]
    yraw[1::2] = data[2::4]
    y = _plane(bytes(yraw), (w, h), ylut)
    cb = _plane(data[1::4], (w // 2, h // 2), clut)
    cr = _plane(data[3::4], (w // 2, h // 2), clut)
    return _compose(y, cb, cr, w, h, stretch)


CONVERTERS = {"nv12": nv12_to_rgb, "i420": i420_to_rgb, "yuyv": yuyv_to_rgb}


def _mean_abs_diff(data, shift, samples=150000, step=5):
    limit = min(samples, len(data) - shift - 1)
    if limit <= 0:
        return float("inf")
    s = 0
    c = 0
    for i in range(0, limit, step):
        s += abs(data[i] - data[i + shift])
        c += 1
    return s / c


def detect_pixfmt(data, w, h):
    """返回 (fmt, 说明)"""
    n = w * h
    total = len(data)
    if total % (n * 2) == 0:
        return "yuyv", "总大小 = w*h*2 的整数倍，判定 YUYV422"
    if total % (n * 3 // 2) != 0:
        raise SystemExit(f"文件大小 {total} 不是 {w}x{h} 的 1.5/2 倍，宽高或格式设置不对")

    # 色度区: 若为 i420, 行宽是 w/2; 若为 nv12, 行宽是 w
    uv = data[n: n + n // 2]
    d_half = _mean_abs_diff(uv, w // 2)   # 半行
    d_full = _mean_abs_diff(uv, w)        # 整行
    if d_half < d_full * 0.9:
        return "i420", f"色度行宽≈{w // 2} (半行差 {d_half:.2f} < 整行差 {d_full:.2f})，判定 I420/YUV420p"
    return "nv12", f"色度行宽≈{w} (整行差 {d_full:.2f} <= 半行差 {d_half:.2f})，判定 NV12"


def main():
    ap = argparse.ArgumentParser(description="YUV 裸数据 -> PNG/JPG")
    ap.add_argument("input", help="输入 .yuv 文件")
    ap.add_argument("-W", "--width", type=int, default=3840)
    ap.add_argument("-H", "--height", type=int, default=2160)
    ap.add_argument("-f", "--pixfmt", default="auto", choices=["auto"] + list(CONVERTERS))
    ap.add_argument("-r", "--range", dest="cr_range", default="limited",
                    choices=["limited", "full"])
    ap.add_argument("-o", "--output", default=None, help="输出路径（多帧自动加 _0000 序号）")
    ap.add_argument("--jpg", action="store_true", help="输出 JPG（默认 PNG）")
    ap.add_argument("--quality", type=int, default=95, help="JPG 质量，默认 95")
    ap.add_argument("--frame", type=int, default=None, help="只转第 N 帧（从 0 开始）")
    ap.add_argument("--max-frames", type=int, default=None, help="最多转多少帧")
    ap.add_argument("--autocontrast", action="store_true", help="对亮度做自动对比度拉伸")
    args = ap.parse_args()

    if not _PIL_AVAILABLE:
        # 无 Pillow：使用内置编码器，仅支持单帧 PNG
        out = convert_frame_to_png(
            args.input, args.width, args.height, args.output,
            frame=args.frame or 0, pixfmt=args.pixfmt, cr_range=args.cr_range)
        print(f"未安装 Pillow，已用内置编码器输出单帧 PNG: {out}")
        return

    w, h = args.width, args.height
    total = os.path.getsize(args.input)
    with open(args.input, "rb") as f:
        head = f.read(w * h * 3 // 2)          # 先读一帧做格式判断

    if args.pixfmt == "auto":
        fmt, why = detect_pixfmt(head, w, h)
        print(f"[auto] {why} -> {fmt}")
    else:
        fmt = args.pixfmt
        why = ""

    fb = w * h * 2 if fmt == "yuyv" else w * h * 3 // 2
    nframes = total // fb
    rem = total - nframes * fb
    if nframes == 0:
        raise SystemExit(f"文件太小：{total} 字节，一帧需要 {fb} 字节（{fmt} {w}x{h}）")
    print(f"{args.input}: {total} 字节, {fmt} {w}x{h}, {nframes} 帧"
          + (f"，末尾多余 {rem} 字节已忽略" if rem else ""))

    limited = args.cr_range == "limited"
    conv = CONVERTERS[fmt]
    ext = "jpg" if args.jpg else "png"
    base = os.path.splitext(args.output or args.input)[0]

    frames = range(nframes)
    single = nframes == 1
    if args.frame is not None:
        if not 0 <= args.frame < nframes:
            raise SystemExit(f"--frame 超出范围：0..{nframes - 1}")
        frames, single = [args.frame], True
        base = os.path.splitext(args.output or args.input)[0]
    if args.max_frames is not None:
        frames = list(frames)[: args.max_frames]

    with open(args.input, "rb") as f:
        for i in frames:
            f.seek(i * fb)
            buf = f.read(fb)
            if len(buf) < fb:
                buf = buf + b"\x10" * (fb - len(buf))   # 末帧不足时用黑电平补齐
            img = conv(buf, w, h, limited, args.autocontrast)
            out = f"{base}.{ext}" if single else f"{base}_{i:04d}.{ext}"
            if args.jpg:
                img.save(out, quality=args.quality, subsampling=0)
            else:
                img.save(out)
            print(f"  第 {i} 帧 -> {out}  ({img.size[0]}x{img.size[1]})")

    # 顺带给出亮度统计，方便判断是否需要 --autocontrast
    ylut, _ = _luts(limited)
    hist = Image.frombytes("L", (w, h), head[: w * h]).histogram()
    vals = [v for v, c in enumerate(hist) if c]
    print(f"亮度范围: {vals[0]}..{vals[-1]}  (映射后 {ylut[vals[0]]}..{ylut[vals[-1]]})")


# ============================================================================
# 供后端自动调用（从板端拷贝回 .yuv 后转 PNG）
# ============================================================================

# 常见车载 sensor 分辨率，用于拿不到分辨率时按文件大小兜底推断
COMMON_YUV_RESOLUTIONS = (
    (1920, 1536),   # IMX623
    (3840, 2160),   # IMX728
    (1920, 1080),
    (1280, 720),
    (1280, 960),
    (2560, 1440),
    (2592, 1944),
    (2880, 1860),
    (3840, 1920),
    (2048, 1536),
    (1920, 1200),
    (2560, 1920),
)


def infer_resolution(path: str, candidates=COMMON_YUV_RESOLUTIONS) -> Optional[tuple]:
    """按文件大小推断 YUV420 分辨率，返回 (w, h) 或 None。

    只接受能整除的文件大小；优先单帧且面积最大的候选。
    """
    total = os.path.getsize(path)
    matches = []
    for w, h in candidates:
        frame_bytes = w * h * 3 // 2
        if frame_bytes > 0 and total % frame_bytes == 0:
            matches.append((w, h, total // frame_bytes))
    if not matches:
        return None
    matches.sort(key=lambda item: (item[2] != 1, -(item[0] * item[1])))
    w, h, _frames = matches[0]
    return w, h


# ---- 无 Pillow 时的内置实现（纯标准库）------------------------------------

def _clamp8(v: int) -> int:
    return 0 if v < 0 else (255 if v > 255 else v)


def _fallback_yuv_to_rgb(data: bytes, w: int, h: int, fmt: str,
                         limited: bool) -> bytes:
    """纯 Python 的 YUV420/YUYV -> RGB 转换，返回 ``w*h*3`` 字节。

    色度按最近邻放大（每 2x2 共用一组 UV），与后端出图用途足够。
    """
    ylut, clut = _luts(limited)
    ytab = bytes(ylut)
    ctab = bytes(clut)

    if fmt == "nv12":
        y = data[: w * h].translate(ytab)
        uv = data[w * h:]
        u = uv[0::2].translate(ctab)
        v = uv[1::2].translate(ctab)
    elif fmt == "i420":
        n = w * h
        q = n // 4
        y = data[:n].translate(ytab)
        u = data[n: n + q].translate(ctab)
        v = data[n + q: n + 2 * q].translate(ctab)
    elif fmt == "yuyv":
        yraw = bytearray(w * h)
        yraw[0::2] = data[0::4]
        yraw[1::2] = data[2::4]
        y = bytes(yraw).translate(ytab)
        u = data[1::4].translate(ctab)
        v = data[3::4].translate(ctab)
    else:
        raise ValueError(f"不支持的像素格式: {fmt}")

    # 预计算色彩转换表（YCbCr -> RGB，BT.601）
    r_of = bytearray(65536)      # 索引 (Y<<8)|Cr
    b_of = bytearray(65536)      # 索引 (Y<<8)|Cb
    g_off = [0] * 65536          # 索引 (Cb<<8)|Cr，存放 G 的偏置
    for yy in range(256):
        base = yy << 8
        for c in range(256):
            chroma = c - 128
            r_of[base + c] = _clamp8(int(yy + 1.402 * chroma + 0.5))
            b_of[base + c] = _clamp8(int(yy + 1.772 * chroma + 0.5))
    for cb in range(256):
        base = cb << 8
        cu = cb - 128
        for cr in range(256):
            g_off[base + cr] = int(-0.344136 * cu - 0.714136 * (cr - 128) + 0.5)

    cw = (w + 1) // 2
    out = bytearray(w * h * 3)
    k = 0
    for i in range(h):
        yrow = y[i * w:(i + 1) * w]
        crow = i >> 1
        urow = u[crow * cw:(crow + 1) * cw]
        vrow = v[crow * cw:(crow + 1) * cw]
        for j in range(w):
            yy = yrow[j]
            uu = urow[j >> 1]
            vv = vrow[j >> 1]
            out[k] = r_of[(yy << 8) | vv]
            g = yy + g_off[(uu << 8) | vv]
            out[k + 1] = 0 if g < 0 else (255 if g > 255 else g)
            out[k + 2] = b_of[(yy << 8) | uu]
            k += 3
    return bytes(out)


def _write_png(path: str, width: int, height: int, rgb: bytes) -> None:
    """把 RGB 字节写成 PNG（filter=0，zlib 压缩）。"""
    stride = width * 3
    raw = b"".join(b"\x00" + rgb[i * stride:(i + 1) * stride]
                   for i in range(height))

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", ihdr))
        f.write(chunk(b"IDAT", zlib.compress(raw, 6)))
        f.write(chunk(b"IEND", b""))


def convert_frame_to_png(input_path: str, width: int, height: int,
                         output_path: Optional[str] = None, frame: int = 0,
                         pixfmt: str = "auto", cr_range: str = "limited",
                         autocontrast: bool = False) -> str:
    """把 YUV 文件中指定的一帧转成 PNG，返回输出路径。

    与命令行行为保持一致：单帧输出 ``<原名>.png``。
    有 Pillow 时用 Pillow 转换；没有时自动改用内置编码器（autocontrast 无效）。
    """
    w, h = int(width), int(height)
    if w <= 0 or h <= 0:
        raise ValueError(f"无效分辨率: {width}x{height}")

    total = os.path.getsize(input_path)
    with open(input_path, "rb") as f:
        head = f.read(w * h * 3 // 2)

    fmt = pixfmt
    if fmt == "auto":
        try:
            fmt, _why = detect_pixfmt(head, w, h)
        except SystemExit as exc:
            raise ValueError(str(exc) or "YUV 像素格式识别失败")
    if fmt not in CONVERTERS:
        raise ValueError(f"不支持的像素格式: {fmt}")

    frame_bytes = w * h * 2 if fmt == "yuyv" else w * h * 3 // 2
    nframes = total // frame_bytes
    if nframes == 0:
        raise ValueError(
            f"文件仅 {total} 字节，不足一帧（{fmt} {w}x{h} 需要 {frame_bytes} 字节）")

    frame = max(0, min(int(frame), nframes - 1))
    with open(input_path, "rb") as f:
        f.seek(frame * frame_bytes)
        buf = f.read(frame_bytes)
    if len(buf) < frame_bytes:
        buf = buf + b"\x10" * (frame_bytes - len(buf))   # 末帧不足时用黑电平补齐

    out = output_path or f"{os.path.splitext(input_path)[0]}.png"
    if _PIL_AVAILABLE:
        img = CONVERTERS[fmt](buf, w, h, cr_range == "limited", autocontrast)
        img.save(out)
    else:
        rgb = _fallback_yuv_to_rgb(buf, w, h, fmt, cr_range == "limited")
        _write_png(out, w, h, rgb)
    return out


if __name__ == "__main__":
    main()
