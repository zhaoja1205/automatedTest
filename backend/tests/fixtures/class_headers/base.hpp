// 抽象基类：IShape。
// 全部方法纯虚 + 无字段 → PlantUML 会渲成 interface。
#pragma once

namespace geo {

class IShape {
public:
    virtual ~IShape() = default;
    virtual double area() const = 0;
    virtual double perimeter() const = 0;
};

// 前置声明不该出现在类列表里
class Circle;

// enum class 不该被当成 class 匹配
enum class ShapeKind {
    Circle,
    Square,
};

}  // namespace geo
