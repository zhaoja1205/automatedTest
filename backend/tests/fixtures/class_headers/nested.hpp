// 嵌套类 —— 目前设计上不合成到外层，Outer 应只识别自己的成员。
// Inner 作为独立类可被查询（namespace_path=["outer_ns","Outer"]）。
#pragma once

namespace outer_ns {

class Outer {
public:
    class Inner {
    public:
        int inner_field;
        void inner_method();
    };

    int outer_field;
    void outer_method();
};

}  // namespace outer_ns
