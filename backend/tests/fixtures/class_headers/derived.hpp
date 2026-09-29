// Circle：继承 IShape，同时实现所有纯虚方法（→ 具体类）。
// 覆盖 public/protected/private + static + virtual/override。
#pragma once
#include "base.hpp"

namespace geo {

// 前置声明的友元，不应识别成类
class Renderer;

class Circle : public IShape {
public:
    Circle(double r);
    ~Circle() override = default;

    // 覆盖父接口
    double area() const override;
    double perimeter() const override;

    // 普通方法
    void set_radius(double r);
    double radius() const;

    // 静态方法
    static Circle unit();

    // friend 声明不该被识别为类
    friend class Renderer;

protected:
    void invalidate_cache();
    double cache_area_{0.0};

private:
    double r_{0.0};
    static const int kMaxRadius = 1000;
};

}  // namespace geo
