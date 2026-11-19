"""SWE.2 docx 渲染冒烟测试（Phase 4 Group 4）。

覆盖面：
1. `_build_swe2_context` 把扩展后的 project dict 构造成合法 Swe2Context
2. 新 schema 字段（software_design / resources / alternative_arch /
   function_desc_segments / config_files）都正确地出现在 context
3. legacy 单段 function_desc 能被自动包装成 1 个 segment（**强制多段**策略）
4. `export_swe2_docx_v2` 走现有 swe2_arch.docx 模板能跑完渲染不报错

不检查 docx 产物的具体字节；只保证 pipeline 跑通、字段都对得上。
docx 模板本身的 §3/§5/§6 新章节由下一轮手工挂 Jinja 标签后补充用例。
"""
from __future__ import annotations

import os
import tempfile

import pytest

from app.core import arch_generator, arch_sections


def _sample_project(
    *,
    with_new_fields: bool = True,
    use_segments_for_a005: bool = True,
) -> dict:
    """构造一个覆盖新 schema 的最小 project dict。"""
    swe2 = {
        "mappings": [
            {
                "swe1_id": "PRED_001-R001",
                "swe2_id": "PRED_001-R001-A001",
                "component_id": "A001",
                "component_name": "Serializer",
                "remark": "起流依赖 ser 配置",
                "version": "V1.0",
            },
        ],
        "components": [
            {
                "id": "A001", "name": "Serializer",
                "model": "MAX96717F", "i2c_addr": "0x40",
                "function_desc": "完成对串行器配置与故障读取。",
                "linked_req_ids": ["PRED_001-R001-A001"],
                "external_interfaces": [
                    {"source": "Camera Module", "method": "ser_init",
                     "type": "外部接口", "params": "handle", "description": "初始化"},
                ],
                "internal_interfaces": [],
                "scenarios": [
                    {"kind": "状态迁移", "title": "Serializer 状态机",
                     "description": "init→ready→streaming", "plantuml": "@startuml\n[*] --> ready\n@enduml"},
                ],
            },
        ],
    }
    # A005 有两种模式：多段 vs legacy 单段
    a005 = {
        "id": "A005", "name": "nvsipl_camera",
        "external_interfaces": [], "internal_interfaces": [], "scenarios": [],
    }
    if use_segments_for_a005:
        a005["function_desc_segments"] = [
            {"title": "起流", "description": "SIPL start → sensor stream",
             "linked_req_ids": ["PRED_001-R002-A005"]},
            {"title": "停流", "description": "SIPL stop → sensor idle",
             "linked_req_ids": ["PRED_001-R003-A005"]},
        ]
    else:
        a005["function_desc"] = "基于 NVIDIA SIPL 的单路相机接入与控制。"
    swe2["components"].append(a005)
    # A008 Camera Security：manual_only，带安全字段
    swe2["components"].append({
        "id": "A008", "name": "Camera Security",
        "function_desc": "三级认证模块。",
        "security_goals": "防篡改/防注入/防重放",
        "security_modules": "AuthManager + KeyStore + Verifier",
    })

    if with_new_fields:
        swe2["software_design"] = {
            "intro": "本软件基于 NvSIPL 框架实现。",
            "module_diagram_plantuml": "@startuml\n[A] --> [B]\n@enduml",
            "external_interfaces": [
                {"source": "SIPL", "method": "sipl_get_status",
                 "type": "外部接口", "params": "handle", "description": "读状态"},
            ],
            "internal_interfaces": [],
            "config_files": {
                "database_path": "nvsipl/query/database/predev_mixgroup",
                "description": "PreDev 混合 group 配置",
                "platform": None,     # 还没扫出来，走 default None
                "modules": [],
                "sensors": [{
                    "name": "imx728", "description": "6MP RGGB",
                    "i2c_address": "0x1A",
                    "fields": [{"key": "fps", "value": "30", "note": ""}],
                }],
                "eeproms": [],
                "crypto": None,
                "diagram_plantuml": "",
            },
            "state_diagrams": [],
            "sequence_diagrams": [],
        }
        swe2["resources"] = {
            "memory_summary": "峰值 120 MB",
            "cpu_summary": "20% @ 4 核",
            "items": [{
                "category": "内存", "item": "峰值",
                "target": "<128 MB", "measured": "120 MB",
                "method": "PMU 监控", "note": "4 路同点",
            }],
        }
        swe2["alternative_arch"] = ""  # 空 → 应该填回 DEFAULT_ALTERNATIVE_ARCH

    return {
        "name": "预研项目",
        "meta": {"doc_version": "V1.0", "modifier": "tester"},
        "aspice": {"project_code": "PRED_001", "swe2": swe2},
    }


# ---------------- _build_swe2_context 结构校验 ----------------

def test_build_context_with_new_fields_passes_schema_validation():
    """覆盖 §3/§5/§6 + function_desc_segments 的完整 project 能通过 Swe2Context 校验。"""
    project = _sample_project(with_new_fields=True, use_segments_for_a005=True)
    ctx = arch_generator._build_swe2_context(project)

    # §3 软件设计全出现
    assert ctx["software_design"]["intro"].startswith("本软件基于 NvSIPL")
    assert ctx["software_design"]["external_interfaces"][0]["method"] == "sipl_get_status"
    cf = ctx["software_design"]["config_files"]
    assert cf["database_path"].endswith("predev_mixgroup")
    assert cf["sensors"][0]["name"] == "imx728"
    assert cf["sensors"][0]["fields"][0]["key"] == "fps"
    # 用户没扫出来的字段保持 null / 空
    assert cf["platform"] is None
    assert cf["crypto"] is None

    # §5 资源
    assert ctx["resources"]["memory_summary"] == "峰值 120 MB"
    assert ctx["resources"]["items"][0]["measured"] == "120 MB"

    # §6 空输入时自动填回 DEFAULT_ALTERNATIVE_ARCH
    assert ctx["alternative_arch"] == arch_sections.DEFAULT_ALTERNATIVE_ARCH


def test_a005_multi_segment_passes_through():
    """强制多段模式：用户填的 function_desc_segments 应原样进 context。"""
    project = _sample_project(use_segments_for_a005=True)
    ctx = arch_generator._build_swe2_context(project)
    a005 = ctx["components_by_id"]["A005"]

    segs = a005["function_desc_segments"]
    assert len(segs) == 2
    assert segs[0]["title"] == "起流"
    assert segs[0]["linked_req_ids"] == ["PRED_001-R002-A005"]

    # function_desc 作为 flat 兼容字段应该是两段拼接
    assert "起流" in a005["function_desc"]
    assert "SIPL start" in a005["function_desc"]
    assert "停流" in a005["function_desc"]


def test_legacy_single_segment_wraps_into_one_segment():
    """旧项目只填了 function_desc → 强制多段策略把它包装成 1 段。"""
    project = _sample_project(use_segments_for_a005=False)
    ctx = arch_generator._build_swe2_context(project)
    a005 = ctx["components_by_id"]["A005"]

    segs = a005["function_desc_segments"]
    assert len(segs) == 1
    assert segs[0]["title"] == ""
    assert segs[0]["description"] == "基于 NVIDIA SIPL 的单路相机接入与控制。"
    # 这段没写 linked_req_ids → 走组件级兜底空列表
    assert segs[0]["linked_req_ids"] == []


def test_legacy_project_without_new_fields_still_builds():
    """旧项目（完全没有 software_design / resources / alternative_arch）应回落到 defaults。"""
    project = _sample_project(with_new_fields=False)
    ctx = arch_generator._build_swe2_context(project)

    # §3 回落到 default_software_design()：有 intro + 模块图，但接口/场景全空
    assert ctx["software_design"]["intro"] == arch_sections.DEFAULT_SOFTWARE_DESIGN_INTRO
    assert ctx["software_design"]["external_interfaces"] == []
    assert ctx["software_design"]["config_files"]["database_path"] == ""

    # §5 回落到 default_resources()
    assert ctx["resources"]["memory_summary"] == arch_sections.DEFAULT_RESOURCES_MEMORY_SUMMARY
    assert ctx["resources"]["items"] == []

    # §6 走默认文案
    assert ctx["alternative_arch"] == arch_sections.DEFAULT_ALTERNATIVE_ARCH


def test_a008_manual_only_fields_preserved():
    """A008 Camera Security 的 security_goals / security_modules 必须流到 context。"""
    project = _sample_project()
    ctx = arch_generator._build_swe2_context(project)
    a008 = ctx["components_by_id"]["A008"]
    assert "防篡改" in a008["security_goals"]
    assert "AuthManager" in a008["security_modules"]


def test_missing_components_filled_with_defaults():
    """只填了 A001/A005/A008，剩下 5 个模块应自动补齐 defaults。"""
    project = _sample_project()
    ctx = arch_generator._build_swe2_context(project)
    cbi = ctx["components_by_id"]
    for cid in ["A001", "A002", "A003", "A004", "A005", "A006", "A007", "A008", "A009"]:
        assert cid in cbi, f"component {cid} missing from context"
        # 补齐出来的占位组件也要有 function_desc_segments（强制多段）
        assert len(cbi[cid]["function_desc_segments"]) >= 1


# ---------------- 实际 docx 渲染冒烟 ----------------

@pytest.mark.skipif(
    not os.path.exists(
        os.path.join(os.path.dirname(__file__), "..", "app",
                     "templates", "aspice", "swe2_arch.docx"),
    ),
    reason="swe2_arch.docx 模板未就位",
)
def test_export_swe2_docx_v2_renders_without_crash(tmp_path):
    """用现有模板跑一次完整渲染，产物是合法 docx。

    注意：swe2_arch.docx 还没挂 §3/§5/§6 的 Jinja 标签，
    所以这些新字段此轮只在 context 里存在、不会出现在产物里。
    但老字段（封面/映射/4.X.1 平文/4.X.2 接口）必须照常渲染。
    """
    project = _sample_project()
    out = tmp_path / "swe2_render.docx"
    result = arch_generator.export_swe2_docx_v2(project, str(out))
    assert result == str(out)
    assert out.exists() and out.stat().st_size > 1024

    # 产物是合法 docx（能被 zipfile 打开，含 word/document.xml）
    import zipfile
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        assert "word/document.xml" in names
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")

    # 老字段真的渲染出来了（兼容性）
    assert "MAX96717F" not in xml or "ser_init" in xml or "完成对串行器" in xml
    # Jinja 标签必须被消化，不能残留 {{ 到产物里
    assert "{{" not in xml, "docxtpl 标签残留：模板渲染不完整"
    assert "{%" not in xml, "docxtpl 语句残留：模板渲染不完整"
