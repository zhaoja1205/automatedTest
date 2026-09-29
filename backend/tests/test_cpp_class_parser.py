"""cpp_class_parser 单测 —— 用 fixtures/class_headers 里的头文件跑。"""
import os
import sys

# 让 pytest 能从任意工作目录跑起来
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND_DIR)

from app.core import cpp_class_parser  # noqa: E402


FIXTURES = os.path.join(_HERE, "fixtures", "class_headers")


def _by_qn(classes):
    return {c.qualified_name: c for c in classes}


def test_parse_project_finds_all_classes():
    classes = cpp_class_parser.parse_project(FIXTURES)
    m = _by_qn(classes)
    # IShape / Circle / FixedArray / Outer / Outer::Inner
    assert "geo::IShape" in m
    assert "geo::Circle" in m
    assert "container::FixedArray" in m
    assert "outer_ns::Outer" in m
    assert "outer_ns::Outer::Inner" in m


def test_skips_forward_decl_enum_class_friend():
    classes = cpp_class_parser.parse_project(FIXTURES)
    names = {c.qualified_name for c in classes}
    # 前置声明不应作为类被识别（只算 class Circle 的定义体那一次）
    assert sum(1 for c in classes if c.qualified_name == "geo::Circle") == 1
    # enum class 不该出现
    assert "geo::ShapeKind" not in names


def test_ishape_is_abstract_and_interface_like():
    classes = cpp_class_parser.parse_project(FIXTURES)
    ishape = _by_qn(classes)["geo::IShape"]
    assert ishape.is_abstract is True
    # 所有方法都是纯虚
    methods = [m for m in ishape.members if m.kind == "method"]
    # 析构 + area + perimeter，共 3 个方法
    assert len(methods) >= 3
    # area / perimeter 明确是纯虚
    area = next(m for m in methods if m.name == "area")
    perimeter = next(m for m in methods if m.name == "perimeter")
    assert area.is_pure_virtual is True
    assert perimeter.is_pure_virtual is True
    # 无字段
    assert all(m.kind != "field" for m in ishape.members)


def test_circle_bases_and_members():
    classes = cpp_class_parser.parse_project(FIXTURES)
    circle = _by_qn(classes)["geo::Circle"]
    # 基类：public IShape
    assert len(circle.bases) == 1
    assert circle.bases[0].name == "IShape"
    assert circle.bases[0].access == "public"

    # 成员按访问段拆分正确
    names = {(m.name, m.access) for m in circle.members}
    assert ("area", "public") in names
    assert ("perimeter", "public") in names
    assert ("set_radius", "public") in names
    assert ("unit", "public") in names          # static
    assert ("invalidate_cache", "protected") in names
    assert ("cache_area_", "protected") in names
    assert ("r_", "private") in names
    assert ("kMaxRadius", "private") in names   # static const

    # static 标记
    unit = next(m for m in circle.members if m.name == "unit")
    assert unit.is_static is True
    kmax = next(m for m in circle.members if m.name == "kMaxRadius")
    assert kmax.is_static is True

    # override 识别
    area = next(m for m in circle.members if m.name == "area")
    assert area.is_override is True


def test_template_params_extracted():
    classes = cpp_class_parser.parse_project(FIXTURES)
    fa = _by_qn(classes)["container::FixedArray"]
    # template<typename T, int N>
    assert "T" in fa.template_params
    assert "N" in fa.template_params


def test_nested_class_is_independent():
    """嵌套类作为独立类可识别，但不合成到外层 Outer 的成员里。"""
    classes = cpp_class_parser.parse_project(FIXTURES)
    outer = _by_qn(classes)["outer_ns::Outer"]
    inner = _by_qn(classes)["outer_ns::Outer::Inner"]

    # Outer 应看到 outer_field / outer_method（不该混进 Inner 的成员）
    outer_names = {m.name for m in outer.members}
    assert "outer_field" in outer_names
    assert "outer_method" in outer_names
    assert "inner_field" not in outer_names
    assert "inner_method" not in outer_names

    # Inner 的 namespace_path 应包含 Outer
    assert inner.namespace_path == ["outer_ns", "Outer"]


def test_strip_comments_preserves_line_numbers():
    src = "class A {\n    // hello\n    int x;\n    /* block\n multi */\n    int y;\n};"
    out = cpp_class_parser.strip_comments(src)
    assert out.count("\n") == src.count("\n")   # 行号不变
    assert "hello" not in out
    assert "block" not in out
    assert "int x;" in out
    assert "int y;" in out
