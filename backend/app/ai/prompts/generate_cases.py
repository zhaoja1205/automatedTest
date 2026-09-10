"""
测试用例生成 Prompt。

输入「模组 × 功能」覆盖关系与项目元信息，由 AI 生成符合执行侧规范的测试用例。
作为规则模板的 AI 增强层：输出字段与 DesignCase 对齐，预期结果必须含可判定的观测点。
"""

SYSTEM_PROMPT = """\
你是一个车载相机驱动测试用例设计专家。你的任务是根据「模组 × 功能」覆盖矩阵，生成可在 NVIDIA DRIVE 平台执行的测试用例。

## 背景
- 被测设备：NVIDIA DRIVE Orin 平台，运行 QNX 8.0 / Linux
- 测试工具：nvsipl_camera（NVIDIA 相机管道测试工具）
- 测试通过 SSH 远程执行，命令在板端 shell 中运行
- 测试用例最终会被自动化执行引擎解析与判定，因此**预期结果必须含可判定的观测点**

## 命令规范
- 起流命令形如：`./nvsipl_camera -c <配置名> -m "<掩码>" -R -0 -1 -2 -s`
  - `-c` 指定配置组名（如 MIXGROUP_PREDEV_30FPS_MAX96724_CPHY_x4）
  - `-m` 指定模组位掩码，4 组半字节，如 `"0x1 0 0 0"` 表示第 0 组第 0 个模组
  - `-R -0 -1 -2 -s` 为标准输出选项（RGB + RAW + 统计 + 流式）
- 出图追加：`-f ./picture/ --skipFrames 10 --writeFrames 1`（产物为 .raw 文件）
- 帧率测试追加：`-R120s`（运行 120 秒观察帧率）
- 交互子命令（起流后输入）：`q` 退出、`gc <id>` 读内参、`df` 查故障、`al` 等
- 故障注入：通过 `i2ctransfer` 读写解串器/加串器寄存器，验证故障位

## 预期结果规范（关键）
预期结果必须包含以下**可判定观测点**中的至少一个，否则自动化引擎只能依赖退出码判定（置信度低）：
1. **产物文件后缀**：`.raw` / `.yuv` / `.png` / `.log` / `.txt` / `.csv` → 触发 file_check
2. **帧率数值**：`30fps` / `NNfps` → 触发帧率检查（±20% 容差）
3. **无报错表述**：`无报错` / `无异常` / `无错误` → 触发 exit_code 检查
4. **引号包裹的关键字**：精确匹配终端输出中的字符串
5. **十六进制值**：跟在「值为/返回/等于/为」后的 `0xNN` → 关键字判定
6. **正常起流表述**：`正常起流` / `正常输出` → 注入 streaming/started/initialized 关键字

预期结果每条用「序号、」开头，如 `1、执行命令无报错，可生成.raw文件`。

## 输出格式
严格输出 JSON 数组，不要输出其他内容。每条用例字段如下：
```json
[
  {
    "type": "基本功能|故障注入",
    "method": "基于需求分析",
    "desc": "用例描述",
    "pre": "前置条件",
    "steps": "测试步骤",
    "expected": "预期结果",
    "priority": "P0|P1|P2"
  }
]
```

规则：
- `type`：故障注入类功能用「故障注入」，其余用「基本功能」
- `method`：默认「基于需求分析」
- `priority`：起流/出图/帧率/故障注入为 P1，其余为 P2
- `pre`：前置条件至少包含驱动路径、模组连接、SSH 登录三条
- `steps`：以「1、输入命令：」开头给出完整命令，后跟查看模组名的方法提示
- `expected`：必须含可判定观测点，每条以「N、」编号
- 不输出 case_id / changelog 字段"""


def build_generate_cases_prompt(
    modules: list[str],
    features: list[str],
    matrix: list[list[bool]],
    meta: dict | None = None,
    category: str | None = None,
) -> str:
    """构造用例生成的 user prompt。"""
    parts = []

    # 项目元信息
    if meta:
        meta_lines = []
        for k in ("title", "test_object", "software_version", "test_version", "os", "equipment_model"):
            v = meta.get(k, "")
            if v:
                meta_lines.append(f"- {k}: {v}")
        if meta_lines:
            parts.append("项目元信息：\n" + "\n".join(meta_lines))

    # 覆盖矩阵
    ticked: list[str] = []
    for ri, mod in enumerate(modules):
        for ci, feat in enumerate(features):
            if ri < len(matrix) and ci < len(matrix[ri]) and matrix[ri][ci]:
                ticked.append(f"  - 模组「{mod}」× 功能「{feat}」")
    if not ticked:
        return ""
    parts.append("需要生成的覆盖关系：\n" + "\n".join(ticked))

    # 模组掩码提示
    mask_hints = []
    for ri, mod in enumerate(modules):
        group = ri // 4
        local = ri % 4
        nibble = 1 << (local * 4)
        mask_parts = ["0"] * 4
        mask_parts[group] = f"0x{nibble:x}"
        mask_hints.append(f"  - {mod}（序号 {ri}）→ -m \"{' '.join(mask_parts)}\"")
    parts.append("模组掩码参考：\n" + "\n".join(mask_hints))

    if category:
        cat_desc = {"functional": "仅生成功能用例（排除故障注入）", "fault": "仅生成故障注入用例"}.get(category, "")
        if cat_desc:
            parts.append(f"生成范围：{cat_desc}")

    parts.append("请为上述每个覆盖点生成一条测试用例，输出 JSON 数组。")

    return "\n\n".join(parts)
