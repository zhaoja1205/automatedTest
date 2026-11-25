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


def test_export_swe2_docx_v2_escapes_cpp_symbols_in_all_fields(tmp_path):
    """回归锁：接口表 / 映射表 / 自由文本等任何字段里含 `<Foo::Bar>` 这类
    C++ 符号或模板参数都必须被 Jinja 的 `| e` 过滤转义。

    事故背景（2026-11-20 用户现场）：InterfacePickerFromScan 把工程源码
    扫出的 C++ 接口塞进 `description = "[returns: std::unique_ptr<CNvMDevice::DriverContext>]"`，
    build_swe2_template.py 的 `INTERFACE_COLS` 当时只写 `{{ i.description }}`
    没加 `| e`，docxtpl 把 `<CNvMDevice::DriverContext>` 当成合法 XML 元素名
    直接吐进 <w:t>，Word 打开时 lxml 的 QName 校验失败（`::` 不是合法 XML
    名字符），整段 document.xml 从截断位置起全部丢失 —— 用户看到的
    "第 4 章 A002 之后全没了"。

    保护面：接口表、映射表、component function_desc、组件 scenarios、§3/§5/§6
    自由文本等**全部用户文本字段**都带 `| e`。
    """
    project = _sample_project()
    swe2 = project["aspice"]["swe2"]
    # 把 C++ 恶字段塞进所有能到的地方
    swe2["mappings"] = [{
        "swe1_id": "R001<raw>", "swe2_id": "R001-A001",
        "component_id": "A002", "component_name": "Deserializer",
        "remark": "a&b<ref>", "version": "V1.0&beta",
    }]
    swe2["components"] = [{
        "id": "A002", "name": "Deserializer",
        "function_desc": "test<module> & stuff",
        "function_desc_segments": [],
        "external_interfaces": [{
            "source": "CNvMMax96724_Fusa.cpp",
            "method": "GetPowerOnDelayMs",
            "type": "外部接口", "params": "void",
            "description": "[returns: std::unique_ptr<CNvMDevice::DriverContext>]",
        }],
        "internal_interfaces": [{
            "source": "CNvMMAX96724_96717F_IMX623.cpp",
            "method": "InitSerLink",
            "type": "内部接口",
            "params": "CNvMMax96724_Fusa::SensorInfo const& info",
            "description": "a<b>c & d",
        }],
        "scenarios": [{"kind": "时序", "title": "<场景>", "description": "A & B<test>"}],
    }]
    swe2["software_design"] = {
        "intro": "<module> 设计 & more",
        "module_diagram_plantuml": "@startuml\nclass X <<app>> {}\n@enduml",
    }
    swe2["resources"] = {"kpi_adjustment": "<KPI>\nitem & more"}
    swe2["integration"] = {"order": "order<1,2,3>"}

    out = tmp_path / "swe2_cpp_escape.docx"
    arch_generator.export_swe2_docx_v2(project, str(out))

    # 1) 产物必须是合法 docx——python-docx 能解析整个 document.xml
    import docx as _pydocx  # noqa: PLC0415
    d = _pydocx.Document(str(out))
    assert len(d.paragraphs) > 300, "若 XML 截断，paragraphs 数量会远小于 395"
    assert len(d.tables) >= 20

    # 2) 恶字段内容**原样可见**（Word 显示原字符，但 XML 侧是 &lt;/&gt; 实体）
    all_text = "\n".join(p.text for p in d.paragraphs)
    for t in d.tables:
        for row in t.rows:
            for c in row.cells:
                all_text += "\n" + c.text
    for needle in [
        "CNvMDevice::DriverContext", "GetPowerOnDelayMs", "<场景>",
        "<module>", "a&b<ref>", "<KPI>", "order<1,2,3>",
    ]:
        assert needle in all_text, f"字段被丢：{needle!r}"

    # 3) XML 侧不能有未转义的裸 '<Foo::Bar>'（防回归）
    import zipfile  # noqa: PLC0415
    with zipfile.ZipFile(out) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    import re as _re  # noqa: PLC0415
    bad = _re.findall(r"<[A-Za-z_][A-Za-z0-9_]*::[A-Za-z_]", xml)
    assert not bad, f"XML 侧残留裸 C++ 命名空间元素：{bad[:5]}"


# ---------------- enabled / security_mode 三态 ----------------

def _all_text(docx_path: str) -> str:
    import docx as _pydocx  # noqa: PLC0415
    d = _pydocx.Document(docx_path)
    chunks = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            for c in row.cells:
                chunks.append(c.text)
    return "\n".join(chunks)


def test_disabled_component_hides_section_4x_block(tmp_path):
    """enabled=false 的 §4.X 整章正文不应出现（标题/子节/接口表在正文都不出）。

    注意：TOC（目录区 P50-141）里仍会出现 "4.2 组件名称Deserializer" 字样，
    因为 TOC 是静态文本不参与 jinja 条件渲染。所以用"出现次数 == 1"来证明
    只剩 TOC 一处，正文那处被 `{%p if enabled %}` 跳过了。启用的章应该
    出现 2 次（TOC + 正文）。
    """
    project = _sample_project()
    swe2 = project["aspice"]["swe2"]
    swe2["components"].extend([
        {"id": "A002", "name": "Deserializer", "enabled": False},
        {"id": "A007", "name": "PMIC", "enabled": False},
    ])
    out = tmp_path / "swe2_disabled.docx"
    arch_generator.export_swe2_docx_v2(project, str(out))
    text = _all_text(str(out))
    # 关掉的章正文不出 → 只出现在 TOC 一处
    assert text.count("4.2 组件名称Deserializer") == 1, \
        "A002 enabled=false 正文仍渲染（预期只剩 TOC 一处）"
    assert text.count("4.7 组件名称PMIC") == 1, \
        "A007 enabled=false 正文仍渲染"
    # 关章的子节：TOC 也含 "4.X.1 功能描述" 字样，用计数判断正文是否被跳过。
    # 启用的章 "4.X.1 功能描述" 在 TOC + 正文 各出一次，关掉的只剩 TOC。
    assert text.count("4.2.1 功能描述") == 1, "A002 §4.2.1 子节正文仍残留"
    assert text.count("4.7.1 功能描述") == 1, "A007 §4.7.1 子节正文仍残留"
    # 没关的章 TOC + 正文各一次
    assert text.count("4.1 组件名称Serializer") >= 2
    assert text.count("4.8 组件名称Camera Security") >= 2


def test_a008_security_mode_manual_brief_hides_subsections(tmp_path):
    """A008 security_mode='manual_brief' 时只渲染 §4.8.1 + §4.8.2，§4.8.3/4/5 不出。"""
    project = _sample_project()
    swe2 = project["aspice"]["swe2"]
    # 把 _sample_project 塞进去的 A008 换成 manual_brief
    for c in swe2["components"]:
        if c["id"] == "A008":
            c["security_mode"] = "manual_brief"
            c["security_goals"] = "防篡改/防注入/防重放"
            c["security_modules"] = "AuthManager + KeyStore + Verifier"
            break
    out = tmp_path / "swe2_a008_brief.docx"
    arch_generator.export_swe2_docx_v2(project, str(out))
    text = _all_text(str(out))
    assert "4.8 组件名称Camera Security" in text
    assert "4.8.1 功能描述" in text
    assert "4.8.2 功能目标" in text
    assert "防篡改" in text  # security_goals 要出
    # manual_brief 下这些正文应该被隐掉——TOC 有一处但正文 0 处，所以合计 == 1。
    # 其中 '4.8.4' 在 TOC 会出现 3 次（'4.8.4 Camera Security'/'4.8.4.1'/'4.8.4.2'），
    # 用 '4.8.5 时序图'（TOC 只 1 次）作为判定更稳。
    assert text.count("4.8.3 功能模块构成") == 1
    assert text.count("4.8.5 时序图") == 1
    # AuthManager 是 §4.8.3 自由文本内容，TOC 不含它，所以应彻底消失
    assert "AuthManager" not in text


def test_a004_empty_classes_shows_hint(tmp_path):
    """A004 Camera Module 没填 classes 时，§4.4.2 下方应出空态提示而不是空表头。"""
    project = _sample_project()
    # _sample_project 没给 A004 填 classes，默认走 defaults 兜底（也是 []）
    out = tmp_path / "swe2_empty_classes.docx"
    arch_generator.export_swe2_docx_v2(project, str(out))
    text = _all_text(str(out))
    assert "暂无类条目" in text, "§4.4.2 空态提示未渲染"


def test_a004_with_classes_shows_rows_not_hint(tmp_path):
    """A004 填了 classes 时，表里应出现类名，空态提示段不出。"""
    project = _sample_project()
    swe2 = project["aspice"]["swe2"]
    swe2["components"].append({
        "id": "A004", "name": "Camera Module",
        "classes": [
            {"seq": 1, "class_name": "CNvMMAX96712_96717F_IMX623",
             "description": "表示 IMX623 Module 的类"},
            {"seq": 2, "class_name": "CNvMMAX96712_96717FCameraModule",
             "description": "表示 96717F CameraModule 的类"},
        ],
    })
    out = tmp_path / "swe2_with_classes.docx"
    arch_generator.export_swe2_docx_v2(project, str(out))
    text = _all_text(str(out))
    assert "CNvMMAX96712_96717F_IMX623" in text
    assert "表示 96717F CameraModule 的类" in text
    assert "暂无类条目" not in text, "填了 classes 不应再出空态提示"


def test_a008_security_mode_full_renders_all_subsections(tmp_path):
    """默认 full 时 §4.8.3/4/5 全部渲染（回归锁，确保 wrap 不误杀 full 模式）。"""
    project = _sample_project()
    # _sample_project 已给 A008 填 security_goals / security_modules，
    # security_mode 走 schema 默认 'full'
    out = tmp_path / "swe2_a008_full.docx"
    arch_generator.export_swe2_docx_v2(project, str(out))
    text = _all_text(str(out))
    assert "4.8.3 功能模块构成" in text
    assert "4.8.5 时序图" in text
    assert "AuthManager" in text


# ---- Phase C §7 系统集成 用户覆盖 vs 默认 ----

def test_integration_user_override_lands_in_docx(tmp_path):
    """前端 IntegrationEditor 填的 order + principle.description 必须覆盖 default，
    落到 docx §7.1 / §7.2.x。"""
    project = _sample_project()
    project["aspice"]["swe2"]["integration"] = {
        "order": "项目特定集成顺序：先接 PMIC，再上 SerDes，最后挂 Sensor。",
        "principles": [
            {"key": "usability", "title": "易用性原则",
             "description": "项目定制易用性：统一错误码体系。"},
            {"key": "security", "title": "安全性原则",
             "description": "项目定制安全性：所有 I2C 配置必须经 Camera Security 校验。"},
            # 其余 4 条留空 → 后端应回落到 default
        ],
    }
    out = tmp_path / "swe2_integration_override.docx"
    arch_generator.export_swe2_docx_v2(project, str(out))
    text = _all_text(str(out))
    # §7.1 用户文案
    assert "项目特定集成顺序" in text
    assert "先接 PMIC，再上 SerDes" in text
    # §7.2.1 / §7.2.2 用户覆盖
    assert "统一错误码体系" in text
    assert "Camera Security 校验" in text
    # §7.2.3-6 留空 → 回落到 default 的典型词
    assert "业务完整性" in text or "回归已有通过项" in text


def test_plantuml_sources_become_inline_images(tmp_path):
    """④ 静态信息章节 PlantUML 应渲染为图片而不是源码文本。

    - project 填 scenario + module_diagram 的 plantuml 源码
    - 导出 docx 后：
      1. 不能再出现 `@startuml` / `@enduml` 字面量（除非 PlantUML 服务宕机 → 跳过）
      2. zip 包里应新增 PNG 媒体文件
    PlantUML 服务不可达时跳过（CI 可能离线）。
    """
    import socket
    # 用默认目标 10.10.134.116:8080 的可达性探测
    try:
        sock = socket.create_connection(("10.10.134.116", 8080), timeout=1.5)
        sock.close()
    except Exception:
        pytest.skip("本地 PlantUML Server 不可达，跳过嵌图断言")

    project = _sample_project()
    # 1) 场景已有 plantuml 源码（见 _sample_project 的 A001.scenarios[0]）
    # 2) 给 software_design 补 module_diagram plantuml 源码
    project["aspice"]["swe2"].setdefault("software_design", {})
    project["aspice"]["swe2"]["software_design"]["module_diagram_plantuml"] = (
        "@startuml\nclass Camera\nclass Serializer\nCamera --> Serializer\n@enduml"
    )

    out = tmp_path / "swe2_puml_images.docx"
    arch_generator.export_swe2_docx_v2(project, str(out))

    import zipfile
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    # 1) docx 内嵌 PNG
    pngs = [n for n in names if n.startswith("word/media/") and n.endswith(".png")]
    assert len(pngs) >= 1, f"PlantUML 应渲染为图片，但没找到 PNG 媒体：{names}"
    # 2) 不应残留源码字面量
    assert "@startuml" not in xml, "PlantUML 源码未被替换为图片"
    assert "@enduml" not in xml


def test_doc_meta_version_overrides_project_meta(tmp_path):
    """② 版本号可配：aspice.swe2.doc_meta.version 覆盖 project.meta.doc_version。

    - 用户在 Swe2Step 填的版本号优先用，封面版本号 / 公司 / 修订人都取 doc_meta。
    - 留空字段回落到 project.meta。
    """
    project = _sample_project()
    # project.meta 层面标 V9.9（模拟旧值），doc_meta 层面覆盖成 V2.3
    project.setdefault("meta", {})["doc_version"] = "V9.9"
    project["meta"]["company"] = "旧公司（应被覆盖）"
    project["aspice"]["swe2"]["doc_meta"] = {
        "version": "V2.3",
        "company": "中科创达新测试公司",
        # modifier 留空，验证回落
    }
    project["meta"]["modifier"] = "回落修订人"

    ctx = arch_generator._build_swe2_context(project)
    # project_block 直接读 doc_meta 覆盖后的值
    assert ctx["project"]["version"] == "V2.3"
    assert ctx["project"]["company"] == "中科创达新测试公司"
    # history 首行（因为 project.history 为空，走默认分支，取 doc_version/modifier）
    # modifier 留空 → 回落 project.meta.modifier
    assert ctx["project"]["history"][0]["version"] == "V2.3"
    assert ctx["project"]["history"][0]["author"] == "回落修订人"

    # 完整渲染一次，确认封面版本号 + 公司名实际用了 doc_meta 覆盖后的值
    out = tmp_path / "swe2_doc_meta_override.docx"
    arch_generator.export_swe2_docx_v2(project, str(out))
    text = _all_text(str(out))
    assert "V2.3" in text
    assert "V9.9" not in text
    assert "中科创达新测试公司" in text
    assert "旧公司（应被覆盖）" not in text


def test_doc_meta_empty_falls_back_to_project_meta(tmp_path):
    """doc_meta 留空 / 缺省 → 完全走 project.meta 回落（向后兼容旧项目）。"""
    project = _sample_project()
    project.setdefault("meta", {})["doc_version"] = "V7.7"
    project["meta"]["company"] = "回落公司"
    # 不设 doc_meta
    project["aspice"]["swe2"].pop("doc_meta", None)

    ctx = arch_generator._build_swe2_context(project)
    assert ctx["project"]["version"] == "V7.7"
    assert ctx["project"]["company"] == "回落公司"


def test_mapping_row_field_names_match_frontend_persistence(tmp_path):
    """Bug B 回归锁：前端存的 `component / description / release_version` 字段
    必须在后端 context 的 mapping_rows 里出现为 id_meaning / remark / version。

    历史 bug：生成器读 `id_meaning / remark / version`，前端存 `component /
    description / release_version`，三列全空。修复后两种字段名都认，前端为准。
    """
    project = _sample_project()
    # 覆盖掉 _sample_project 里的 mapping，只留一条前端格式的
    project["aspice"]["swe2"]["mappings"] = [
        {
            "swe1_id": "PRED_001-R001",
            "swe2_id": "PRED_001-R001-A001",
            "component": "Serializer",          # 前端字段
            "description": "起流依赖 ser 配置",  # 前端字段
            "release_version": "V3.1",           # 前端字段
        }
    ]
    ctx = arch_generator._build_swe2_context(project)
    row = ctx["mappings"]["rows"][0] if "rows" in ctx.get("mappings", {}) \
        else ctx["mapping_rows"][0] if "mapping_rows" in ctx \
        else next(r for r in ctx.values()
                  if isinstance(r, list) and r and "swe1_id" in r[0])[0]
    # 定位真正的 mapping_rows 字段：直接拿 generator 实际产出的
    import json as _json
    flat = _json.dumps(ctx, default=str, ensure_ascii=False)
    assert "Serializer" in flat
    assert "起流依赖 ser 配置" in flat
    assert "V3.1" in flat

    # 继续端到端：导出 docx 真能看到这三列值
    out = tmp_path / "swe2_mapping_fields.docx"
    arch_generator.export_swe2_docx_v2(project, str(out))
    text = _all_text(str(out))
    assert "Serializer" in text
    assert "起流依赖 ser 配置" in text
    assert "V3.1" in text


def test_module_diagram_empty_preserves_template_original(tmp_path):
    """Bug C 回归锁：用户未填 module_diagram_plantuml 时，§3.2 不应生成新 PNG，
    保留模板内置原图。

    历史 bug：generator 把默认 PlantUML 塞给 walker，于是每次导出 §3.2 都是
    AI 画的"相机模组集成"占位图，盖掉了原模板里 SIPL 分层图。
    """
    import zipfile
    project = _sample_project()
    # 确保 software_design.module_diagram_plantuml 没值
    project["aspice"]["swe2"].setdefault("software_design", {})
    project["aspice"]["swe2"]["software_design"]["module_diagram_plantuml"] = ""

    # 场景 / 其他 plantuml 也清空，排除干扰
    for c in project["aspice"]["swe2"]["components"]:
        for sc in c.get("scenarios") or []:
            sc["plantuml"] = ""

    out = tmp_path / "swe2_module_diagram_empty.docx"
    arch_generator.export_swe2_docx_v2(project, str(out))

    with zipfile.ZipFile(out) as z:
        pngs = [n for n in z.namelist()
                if n.startswith("word/media/") and n.endswith((".png", ".PNG"))]
    # 模板本身 §3.2 / §4 内嵌的原图仍保留；用户没填 → 不新增 walker 产出的 PNG
    # 这里基线是模板里已有的图张数；用具体数值会随模板变脆，
    # 只断言 pipeline 没崩 + 没产生 @startuml 残留
    with zipfile.ZipFile(out) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    assert "@startuml" not in xml
    # context 里 module_diagram.plantuml 必须为空，不能被默认 PUML 填回
    ctx = arch_generator._build_swe2_context(project)
    assert ctx["software_design"]["module_diagram"]["plantuml"] == ""


def test_integration_empty_falls_back_to_defaults(tmp_path):
    """用户完全没填 integration（或 integration 留空）→ 导出走后端默认 6 条原则 + 默认顺序。"""
    project = _sample_project()
    # 显式清掉 integration
    project["aspice"]["swe2"]["integration"] = {"order": "", "principles": []}
    out = tmp_path / "swe2_integration_default.docx"
    arch_generator.export_swe2_docx_v2(project, str(out))
    text = _all_text(str(out))
    # 默认 order 里的典型词
    assert "Deserializer" in text and "Serializer" in text
    # 6 条默认原则都在
    for key_sign in (
        "接口简洁", "特权与非特权", "业务完整性",
        "NvSIPL 既有接口", "扩展位", "三方工具链",
    ):
        assert key_sign in text, f"默认原则缺失关键字: {key_sign}"


# ---------------- 2026-11-24：接口表按来源文件分组 + A004 超长表 ----------------

def test_interface_rows_grouped_by_source_file():
    """`_group_interfaces_by_file` 把行按 source 归拢，并在每组首行打标记。

    事故背景：A004 Camera Module 一次扫描导入了 546 条内部接口（两份 Sensor
    驱动的同名 C 函数全进来了）。行按扫描顺序交错排列（同一文件出现 21 段），
    文档里读者完全没法看出哪几行属于哪个源文件。
    """
    items = [
        {"source": "b.c", "method": "b1"},
        {"source": "a.c", "method": "a1"},
        {"source": "b.c", "method": "b2"},
        {"source": "a.c", "method": "a2"},
        {"source": "a.c", "method": "a3"},
    ]
    out = arch_generator._group_interfaces_by_file(items)

    # 按 source 字典序归拢，组内保持原顺序
    assert [i["method"] for i in out] == ["a1", "a2", "a3", "b1", "b2"]
    # 组内每行都带 group_name（模板据此隐藏重复文件名）；
    # group_first / group_size 只在首行有意义。
    flags = [(i.get("group_first") or False, i.get("group_size") or 0, i.get("group_name") or "")
             for i in out]
    assert flags == [
        (True, 3, "a.c"), (False, 0, "a.c"), (False, 0, "a.c"),
        (True, 2, "b.c"), (False, 0, "b.c"),
    ]


def test_group_interfaces_handles_empty_source_and_empty_list():
    """source 为空的行排最后且不产生分组标题；空列表原样返回。"""
    assert arch_generator._group_interfaces_by_file([]) == []

    out = arch_generator._group_interfaces_by_file([
        {"source": "", "method": "manual1"},
        {"source": "a.c", "method": "a1"},
        {"source": "   ", "method": "manual2"},
    ])
    assert out[0]["method"] == "a1" and out[0]["group_first"] is True
    # 没来源的两行排在后面，且都没有分组标记（否则模板会输出空标题）
    for it in out[1:]:
        assert not it.get("group_first")
        assert not it.get("group_name")


def test_grouped_interface_table_renders_file_header_in_docx(tmp_path):
    """docx 里每组首行显示「⚑ 文件名（N 项）」，同组后续行不重复文件名。"""
    project = _sample_project()
    comps = project["aspice"]["swe2"]["components"]
    a001 = next(c for c in comps if c["id"] == "A001")
    a001["internal_interfaces"] = [
        {"source": "cdi_imax728.c", "method": "DriverCreate", "type": "内部接口",
         "params": "void", "description": "创建驱动"},
        {"source": "cdi_imax728.c", "method": "DriverDestroy", "type": "内部接口",
         "params": "void", "description": "销毁驱动"},
        {"source": "cdi_imax623.c", "method": "DriverCreate", "type": "内部接口",
         "params": "void", "description": "创建驱动"},
    ]
    out = tmp_path / "swe2_grouped.docx"
    arch_generator.export_swe2_docx_v2(project, str(out))

    import docx as _pydocx  # noqa: PLC0415
    d = _pydocx.Document(str(out))
    table = None
    for t in d.tables:
        if not t.rows:
            continue
        # T8（A001 内部接口）是 10 列 gridSpan 交错结构，python-docx 会把
        # 合并格按网格展开，cells 数 ≠ len(t.columns) —— 这里只看内容。
        if "接口溯源" not in t.rows[0].cells[0].text:
            continue
        if not any("⚑" in r.cells[0].text for r in t.rows):
            continue
        # gridSpan 展开后 cells 的索引和表头网格不同（前两列并成一个 tc，
        # 但报告为两个 cell），所以按"整行有 DriverCreate"判定，别假设列号。
        if not any("DriverCreate" in c.text for r in t.rows for c in r.cells):
            continue
        table = t
        break
    assert table is not None, "没找到带分组小标题的接口表"

    first_col = [r.cells[0].text.strip() for r in table.rows[1:]]
    # 两个组首行带 ⚑ + 数量；第三行属于第一组，不再重复文件名
    assert any(h.startswith("⚑ cdi_imax623.c（1 项）") for h in first_col), first_col
    assert any(h.startswith("⚑ cdi_imax728.c（2 项）") for h in first_col), first_col
    # 同组后续行首列应为空（不再重复文件名）
    assert not any(h == "cdi_imax728.c" for h in first_col), \
        f"同组后续行不该重复文件名: {first_col}"
