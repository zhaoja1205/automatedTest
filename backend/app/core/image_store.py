"""从板端下载的用例图片的本地目录约定。

同一 ``case_id`` 会在「功能测试」「故障测试」等不同 Sheet 里重复出现，
按 ``case_id`` 平铺存放会让两个表共享同一批图片（下载结果 Excel 时
图片会同时出现在两个 Sheet 的同一行上）。新布局因此带上 Sheet 维度：

新布局::

    <image_download_path>/<sheet_dir>/<case_id>/*.png

旧布局（历史数据，仅在没有对应 Sheet 目录时作为兜底）::

    <image_download_path>/<case_id>/*.png
"""
from __future__ import annotations

import os
import re

_INVALID_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')
_MAX_SHEET_DIR_LEN = 60


def sheet_dir_name(source_sheet: str) -> str:
    """把 Sheet 名转成可安全用作目录名的片段（空串表示不使用 Sheet 维度）。"""
    name = _INVALID_CHARS.sub("_", (source_sheet or "").strip())
    return name.strip(" .")[:_MAX_SHEET_DIR_LEN]


def case_image_dir(base: str, case_id: str, source_sheet: str = "") -> str:
    """该用例本轮应写入的目录（带 Sheet 维度；Sheet 为空时退回旧布局）。"""
    base_abs = os.path.abspath(os.path.expanduser(base))
    slug = sheet_dir_name(source_sheet)
    if not slug:
        return os.path.join(base_abs, case_id)
    return os.path.join(base_abs, slug, case_id)


def legacy_case_image_dir(base: str, case_id: str) -> str:
    """旧布局目录（不带 Sheet 维度）。"""
    return os.path.join(os.path.abspath(os.path.expanduser(base)), case_id)


def resolve_case_image_dir(
    base: str, case_id: str, source_sheet: str = ""
) -> tuple[str, str]:
    """解析读取用的图片目录。

    返回 ``(目录, 布局)``，布局为 ``"sheet"`` / ``"legacy"`` / ``"none"``：
    - 带 Sheet 维度且目录存在 → 新布局，直接使用；
    - 否则旧布局目录存在 → 兜底使用（历史数据）；
    - 都不存在 → ``(旧布局路径, "none")``，供调用方判断是否真的没有图片。
    """
    slug = sheet_dir_name(source_sheet)
    if slug:
        new_dir = case_image_dir(base, case_id, source_sheet)
        if os.path.isdir(new_dir):
            return new_dir, "sheet"
    legacy = legacy_case_image_dir(base, case_id)
    if os.path.isdir(legacy):
        return legacy, "legacy"
    if slug:
        return case_image_dir(base, case_id, source_sheet), "none"
    return legacy, "none"
