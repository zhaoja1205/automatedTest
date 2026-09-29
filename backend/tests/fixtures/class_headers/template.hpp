// 模板类 —— 验证 template_params 提取正确。
#pragma once

namespace container {

template <typename T, int N>
class FixedArray {
public:
    FixedArray();
    T& at(int i);
    const T& at(int i) const;
    int size() const { return N; }
private:
    T data_[N];
};

}  // namespace container
