"""SWE.2 §3.3.3 config_db 解析器冒烟测试（Phase 4 Group 3）。

覆盖面：
1. 命名风格 A（IM_imx728x96717：`<name>.json` 兼做 cameraModules 载体 + `<name>_platform.json`）
2. 命名风格 B（sc233at：按 `_platform.json` / `_cameramodules.json` / `_sensor.json` 分开）
3. 产出能通过 `ConfigDatabase` schema 校验
4. rel_path 为空 / 目录不存在 → 返回空壳，不抛
5. `..` 逃逸 → 被收敛到 root 外 → 返回空壳

真实样本来自：
  backend/runtime/classdiag_projects/2670a8977c3f/source/nvsipl/query/database/
"""
from __future__ import annotations

import pathlib
from typing import Any

from app.core import config_db_parser, engineering_store
from app.schemas.aspice.swe2_schema import ConfigDatabase


_SAMPLE_ROOT = (
    pathlib.Path(__file__).resolve().parent.parent
    / "runtime" / "classdiag_projects" / "2670a8977c3f"
    / "source" / "nvsipl" / "query" / "database"
)


def _patch_root(monkeypatch=None) -> None:
    """让 engineering_root('fake') → 真实样本 database 目录。"""
    engineering_store.engineering_root = lambda pid: str(_SAMPLE_ROOT)  # type: ignore[assignment]


def test_parse_naming_style_a_imx728() -> None:
    """IM_imx728x96717：`<name>.json` 既是 modules 又无 platform 的那份 + 单独的 `_platform.json`。"""
    _patch_root()
    out: dict[str, Any] = config_db_parser.parse_config_db("fake", "IM_imx728x96717")
    cd = ConfigDatabase(**out)
    assert cd.platform is not None
    assert "IMX728" in (cd.platform.name or "")
    assert any(b.deserializer == "MAX96712_Fusa_nv_A1" for b in cd.platform.device_blocks)
    # IMX728 工程 cameraModules 来自 `<name>.json`（和 platform JSON 不同文件）
    assert any("V728" in m.name for m in cd.modules)
    assert any(s.name == "IMX728" for s in cd.sensors)
    assert any(e.name == "M24128" for e in cd.eeproms)


def test_parse_naming_style_b_sc233at() -> None:
    """sc233at：按 `_platform.json` / `_cameramodules.json` / `_sensor.json` 分开。"""
    _patch_root()
    out: dict[str, Any] = config_db_parser.parse_config_db("fake", "sc233at")
    cd = ConfigDatabase(**out)
    assert cd.platform is not None
    assert "SC233AT" in (cd.platform.name or "")
    assert any(m.name == "HIKAUTO-SC233AT-VCSEL-GMSL2-FUSA" for m in cd.modules)
    # 允许 serializer 为空字串（cameramodules JSON 里只有 name，没有 i2c）
    assert any(s.name == "SC233AT" for s in cd.sensors)
    assert any(e.name == "N24C64" for e in cd.eeproms)


def test_parse_empty_path_returns_empty_shell() -> None:
    _patch_root()
    out = config_db_parser.parse_config_db("fake", "")
    cd = ConfigDatabase(**out)
    assert cd.platform is None
    assert cd.modules == []
    assert cd.database_path == ""


def test_parse_missing_dir_returns_empty_shell() -> None:
    _patch_root()
    out = config_db_parser.parse_config_db("fake", "does/not/exist")
    cd = ConfigDatabase(**out)
    assert cd.platform is None
    assert cd.modules == []


def test_parse_dotdot_escape_is_rejected() -> None:
    _patch_root()
    out = config_db_parser.parse_config_db("fake", "../../../../../../etc")
    cd = ConfigDatabase(**out)
    # 逃逸到 root 外 → 返回空壳
    assert cd.platform is None
    assert cd.modules == []


def test_sensor_fields_are_flattened_from_virtual_channels() -> None:
    """sensor JSON 里 virtualChannels[0] 的键应被扁平成 `vc.*` 字段，方便前端表格展示。"""
    _patch_root()
    out = config_db_parser.parse_config_db("fake", "IM_imx728x96717")
    cd = ConfigDatabase(**out)
    imx = next((s for s in cd.sensors if s.name == "IMX728"), None)
    assert imx is not None
    keys = [f.key for f in imx.fields]
    # 至少应包含一个 vc.* 字段（width/height/fps/cfa 中之一）
    assert any(k.startswith("vc.") for k in keys), f"no vc.* in {keys}"
