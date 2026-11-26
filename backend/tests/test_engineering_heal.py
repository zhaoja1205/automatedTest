"""SWE.2 / SWE.3 共享 engineering_src/ 的 push_d.engineering 自愈冒烟。

场景：
  工程 zip/目录已落到 engineering_src/，engineering_meta.json 也在，
  但 project JSON 里 swe3.push_d.engineering 莫名其妙为 None（跨标签页上传、
  旧会话未保存、tree_finish 竞态写回失败都会造成这种漂移）。
  → `_heal_engineering(pid, push_d)` 必须从磁盘把 meta 贴回来，返回 True。
  → push_d.engineering 已存在时必须不动，返回 False。
  → 磁盘没有 meta 时必须不动，返回 False。
"""
from __future__ import annotations

import json
import os
import tempfile
from unittest import mock

from app.api import aspice_routes
from app.core import engineering_store


def test_heal_pulls_meta_from_disk_when_push_d_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        # patch engineering_meta_path 到 tmp 下，避免污染真实 runtime/
        meta_path = os.path.join(tmp, "engineering_meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({
                "total_files": 445, "total_bytes": 12700000,
                "zip_name": "Bazinga-nv-dev.zip",
            }, f)
        with mock.patch.object(
            engineering_store, "engineering_meta_path", return_value=meta_path,
        ):
            push_d: dict = {"engineering": None}
            healed = aspice_routes._heal_engineering("fake_pid", push_d)
        assert healed is True
        assert push_d["engineering"]["total_files"] == 445


def test_heal_noop_when_push_d_already_has_engineering() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        meta_path = os.path.join(tmp, "engineering_meta.json")
        # 磁盘上有新 meta
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"total_files": 999}, f)
        with mock.patch.object(
            engineering_store, "engineering_meta_path", return_value=meta_path,
        ):
            push_d: dict = {"engineering": {"total_files": 1, "zip_name": "old.zip"}}
            healed = aspice_routes._heal_engineering("fake_pid", push_d)
        # 已有就不碰，避免覆盖用户上一次的真实 meta
        assert healed is False
        assert push_d["engineering"]["total_files"] == 1


def test_heal_noop_when_disk_has_no_meta() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.object(
            engineering_store, "engineering_meta_path",
            return_value=os.path.join(tmp, "nowhere.json"),
        ):
            push_d: dict = {"engineering": None}
            healed = aspice_routes._heal_engineering("fake_pid", push_d)
        assert healed is False
        assert push_d["engineering"] is None
