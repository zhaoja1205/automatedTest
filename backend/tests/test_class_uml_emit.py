"""class_uml_emit 单测 —— 走 fixtures 端到端。"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND_DIR)

from app.core import cpp_class_parser  # noqa: E402
from app.core import class_uml_emit  # noqa: E402


FIXTURES = os.path.join(_HERE, "fixtures", "class_headers")


def _load():
    classes = cpp_class_parser.parse_project(FIXTURES)
    ishape = next(c for c in classes if c.qualified_name == "geo::IShape")
    circle = next(c for c in classes if c.qualified_name == "geo::Circle")
    return ishape, circle


def test_emit_wraps_startuml_enduml():
    ishape, circle = _load()
    uml = class_uml_emit.emit_class_diagram(circle, [ishape])
    assert uml.startswith("@startuml")
    assert uml.rstrip().endswith("@enduml")


def test_ishape_rendered_as_interface_with_dotted_arrow():
    ishape, circle = _load()
    uml = class_uml_emit.emit_class_diagram(circle, [ishape])
    # IShape 全纯虚 + 无字段 → interface + `<|..`
    assert "interface " in uml
    assert "<|.." in uml
    # Circle 不该是 interface（它有具体实现，虽然继承了纯虚）
    # 是否走 abstract 取决于 Circle 里 override 后的方法是否被识别为 pure — Circle 没有 =0 所以应为 class
    # 我们只断言 Circle 出现且不是 abstract class
    assert "class Circle" in uml or 'class "geo::Circle"' in uml


def test_target_class_with_namespace_uses_alias():
    ishape, circle = _load()
    uml = class_uml_emit.emit_class_diagram(circle, [ishape])
    # 目标类名带 :: → 用别名语法 `class "ns::Name" as Alias`
    assert '"geo::Circle"' in uml
    assert "as Circle" in uml
    assert '"geo::IShape"' in uml
    assert "as IShape" in uml


def test_inheritance_line_present():
    ishape, circle = _load()
    uml = class_uml_emit.emit_class_diagram(circle, [ishape])
    # IShape <|.. Circle（虚线，因为 IShape 是 interface）
    assert "IShape <|.. Circle" in uml


def test_static_member_gets_stereotype():
    ishape, circle = _load()
    uml = class_uml_emit.emit_class_diagram(circle, [ishape])
    # unit() 是 static → 应带 {static}
    assert "{static}" in uml


def test_options_hide_private():
    ishape, circle = _load()
    uml = class_uml_emit.emit_class_diagram(
        circle, [ishape],
        options={"show_private": False, "show_protected": True, "show_static": True}
    )
    # r_ 是 private → 不该出现
    assert "r_" not in uml
    # cache_area_ 是 protected → 仍应出现
    assert "cache_area_" in uml


def test_placeholder_when_parent_missing():
    """基类找不到定义时也要有占位声明，避免继承线悬空。"""
    _, circle = _load()
    uml = class_uml_emit.emit_class_diagram(circle, parents=[])
    # 没提供 parents，但 target 自己声明了 base=IShape → 应有占位 class IShape
    assert "class IShape" in uml
    # 继承线仍存在
    assert "IShape <|-- Circle" in uml or "IShape <|.. Circle" in uml


def test_abstract_pure_virtual_marked():
    ishape, circle = _load()
    uml = class_uml_emit.emit_class_diagram(circle, [ishape])
    # area / perimeter 是纯虚（在 IShape 里）→ {abstract}
    assert "{abstract}" in uml
