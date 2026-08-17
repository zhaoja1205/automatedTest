# 测试执行管理系统 — AI 智能化升级规划

## 文档信息

| 项目 | 内容 |
|---|---|
| 文档名称 | AI 智能化升级规划 |
| 适用工程 | `test_runner_web` |
| 创建日期 | 2026-08-14 |
| 状态 | 规划分析（未实施） |

---

## 一、升级方向总览

经过对当前系统的完整分析，确定以下三个 AI 引入方向：

| 方向 | 优先级 | 说明 |
|---|---|---|
| **AI 失败分析** | P0 — 首批落地 | 用例 Fail 时 AI 自动分析根因并给出建议 |
| **AI 报告生成** | P1 — 第二批 | 执行完成后 AI 生成结构化测试报告 |
| **命令解析** | 暂不引入 AI | 通过规则+用例格式统一解决，后续有扩展需求再考虑 |

---

## 二、当前系统判定机制分析

### 2.1 现有结果判定流程

```
expected_result (自然语言) → ExpectedResultParser.parse() → 提取判定条件
                                                              │
actual_output (命令日志)   → ExpectedResultParser.match() ←──┘
                                │
                                ▼
                        {status: Pass/Fail, reason: "..."}
```

### 2.2 现有判定能力与局限

| 判定类型 | 现有能力 | 局限 |
|---|---|---|
| 关键字匹配 | 从预期文本提取关键词，匹配率≥80%判Pass | 阈值固定、不理解语义 |
| FPS 检测 | 提取帧率数值，容差±20% | 无法判断"稳定"、"波动" |
| 错误检测 | 14个关键字（error/crash/fault等） | 无法区分"致命错误"和"可忽略warning" |
| 文件检测 | 检查远端是否生成特定扩展名文件 | 无法验证文件内容正确性 |
| 退出码 | 非0=潜在失败 | 某些工具非0是正常的 |

### 2.3 现有判定失效的典型场景

**场景 A：语义模糊**
```
预期: "帧率稳定在30fps左右，无异常"
实际: Sensor10_Out0 Frame rate (fps): 29.986 (Pass? 规则判Pass)
实际: Sensor10_Out0 Frame rate (fps): 28.500 (Pass? 规则也判Pass，因为容差20%)
→ 用户期望: 28.5 应该是 Fail（偏差>5%对该项目不可接受）
```

**场景 B：日志分析**
```
预期: "相机正常出流，无报错"
实际: [大量正常日志] + [一行 WARNING: buffer underrun] + [继续正常]
→ 规则判: Fail（命中 error 关键字附近）
→ 实际: Pass（warning 是已知可忽略的）
```

**场景 C：失败定位困难**
```
状态: Fail
actual_output: [300行日志]
match_reason: "关键字匹配率 60% < 80%"
→ 用户: 到底哪里错了？需要人工逐行看日志
```

---

## 三、AI 失败分析设计（P0）

### 3.1 功能定义

当用例执行结果为 **Fail** 时，用户可点击"AI 分析"按钮，系统将执行日志和上下文发送给 LLM，返回结构化的失败分析报告。

### 3.2 系统架构

```
┌─ Frontend ──────────────────────────────────────────┐
│                                                      │
│  Test Case Table                                     │
│  ┌─────────────────────────────────────────┐        │
│  │ FT_002_01 │ Fail │ [AI分析] │ [查看日志] │        │
│  └─────────────────────────────────────────┘        │
│           │ click                                     │
│           ▼                                          │
│  ┌─ AI Analysis Card ─────────────────────┐         │
│  │ 🔴 根因: 设备初始化失败                    │         │
│  │ 📋 证据: "ERROR: NvSIPLCamera Init      │         │
│  │         failed, status: 9"              │         │
│  │ 💡 建议: 检查是否有残留 nvsipl 进程       │         │
│  │ 📊 置信度: 92%                           │         │
│  └─────────────────────────────────────────┘        │
└──────────────────────────────────────────────────────┘
         │
         │ POST /api/ai/analyze-failure
         ▼
┌─ Backend ────────────────────────────────────────────┐
│  AIService.analyze_failure()                         │
│    1. 收集上下文 (用例信息 + 日志 + 预期)              │
│    2. 构造 prompt                                    │
│    3. 调用 LLM API                                   │
│    4. 解析结构化响应                                   │
│    5. 返回分析结果                                    │
└──────────────────────────────────────────────────────┘
         │
         │ LLM API Call
         ▼
┌─ LLM Provider ───────────────────────────────────────┐
│  Claude Haiku 4.5 / Sonnet 5 / 本地模型              │
└──────────────────────────────────────────────────────┘
```

### 3.3 API 接口设计

```
POST /api/ai/analyze-failure

Request:
{
  "case_id": "FT_002_01",
  "description": "检查相机有效像素信息",
  "test_steps": "1、输入命令：./nvsipl_camera ...\n2、输入gc 10\n3、起流后输入'al'指令",
  "expected_result": "成功读到相机有效像素信息，Vertical和horizontal有有效值",
  "actual_output": "...[执行日志，截断到最后2000字符]...",
  "match_reason": "关键字匹配率 60%",
  "error_msg": "ERROR: NvSIPLCamera Init failed"
}

Response:
{
  "analysis": {
    "root_cause_category": "environment",  // environment|defect|test_issue|flaky|mismatch
    "root_cause_summary": "nvsipl_camera 初始化失败，设备资源被占用",
    "evidence": [
      "ERROR: NvSIPLCamera Init failed",
      "status: 9"
    ],
    "detailed_explanation": "nvsipl_camera 在执行 Init 阶段失败，错误码 9 通常表示...",
    "suggestion": [
      "执行前运行 pkill -9 nvsipl_camera 清理残留进程",
      "检查设备 /dev/nvsipl* 是否被其他进程锁定",
      "如果持续出现，尝试重启板端后再执行"
    ],
    "confidence": 0.92,
    "is_likely_real_bug": false
  }
}
```

### 3.4 根因分类体系

| 类别 | 标识 | 说明 | 典型特征 |
|---|---|---|---|
| 环境问题 | `environment` | 设备/连接/配置问题 | SSH 断连、Init failed、timeout、设备未就绪 |
| 真实缺陷 | `defect` | 功能确实有 bug | 功能异常输出、崩溃、返回值错误 |
| 用例问题 | `test_issue` | 步骤/预期写得不对 | 命令不存在、预期过严、步骤遗漏 |
| 间歇性 | `flaky` | 偶发失败 | 历史时通时不通、竞态、timing 敏感 |
| 不匹配 | `mismatch` | 执行成功但判定逻辑认为失败 | 格式变化、阈值过严、无关 warning |

### 3.5 Prompt 设计思路

```
System: 你是一个嵌入式测试失败分析专家。分析以下测试用例的失败原因。

Context:
- 设备: QNX 8.0 嵌入式板 (nvsipl_camera 相机测试)
- 工具: nvsipl_camera (NVIDIA 相机管道测试工具)

Rules:
1. 基于实际日志证据分析，不要猜测
2. 明确区分"环境问题"和"真实bug"
3. 给出可操作的修复建议
4. 如果不确定，标明置信度较低

Test Case: {case_id} - {description}
Steps: {test_steps}
Expected: {expected_result}
Actual Output: {actual_output}
Match Reason: {match_reason}

请以 JSON 格式输出分析结果...
```

### 3.6 降本策略

| 策略 | 说明 |
|---|---|
| 按需触发 | 只在用户点击时调用，不自动对所有 Fail 分析 |
| 日志截断 | 只发送最后 2000 字符 + 错误行上下文 |
| 缓存 | 同一 case_id + 同一 error_msg 的分析结果缓存 24h |
| 模型选择 | 默认 Haiku 4.5（$0.25/M input + $1.25/M output），复杂分析可切 Sonnet |
| 本地备选 | 支持配置本地模型（Ollama + Qwen2.5-7B）用于离线环境 |

---

## 四、AI 报告生成设计（P1）

### 4.1 功能定义

执行完成后，用户可点击"生成报告"按钮，AI 基于本轮执行结果生成结构化测试报告。

### 4.2 报告内容

```
┌─────────────────────────────────────────────────────┐
│           📋 测试执行报告                              │
│           2026-08-14 FT 功能测试                      │
├─────────────────────────────────────────────────────┤
│                                                      │
│ 📊 执行概况                                          │
│   总计: 25 例 | 通过: 20 | 失败: 3 | NA: 2           │
│   通过率: 87% | 执行时长: 15m32s                      │
│                                                      │
│ ❌ 失败用例分析                                       │
│                                                      │
│   FT_002_01 - 相机有效像素检查                        │
│   │ 根因: 设备初始化失败（环境问题）                    │
│   │ 建议: 清理残留进程后重跑                           │
│   │                                                  │
│   FT_005_03 - 30fps 帧率验证                         │
│   │ 根因: 帧率 28.5fps 低于预期（可能的真实缺陷）       │
│   │ 建议: 确认是否为硬件温漂，多次验证                  │
│   │                                                  │
│   FT_008_02 - 多路输出一致性                          │
│   │ 根因: Sensor3 超时无输出（间歇性问题）              │
│   │ 建议: 增加等待时间后重试                           │
│                                                      │
│ 🔍 趋势观察                                          │
│   - FT_002_01 连续 3 轮 Fail，建议优先排查             │
│   - 本轮通过率较上轮 (92%) 下降 5%                    │
│   - 新增失败: FT_008_02（上轮 Pass）                  │
│                                                      │
│ 💡 建议                                              │
│   1. 优先解决 FT_002_01 环境问题（清理残留进程）        │
│   2. FT_005_03 需研发确认帧率指标                      │
│   3. FT_008_02 建议重跑验证是否为偶发                  │
│                                                      │
└─────────────────────────────────────────────────────┘
```

### 4.3 数据输入

AI 报告生成需要以下数据：

| 数据 | 来源 | 说明 |
|---|---|---|
| 本轮执行结果 | `execute_all()` 返回的 TestResult[] | 每例的 status、reason、duration |
| 用例信息 | TestCase[] | description、priority、expected |
| 执行日志 | WebSocket logs | 关键事件和错误 |
| 失败分析 | AI 分析结果缓存 | 如果已经做了失败分析 |
| 历史数据（可选） | 持久化的历史结果 | 上轮通过率、连续失败次数 |

### 4.4 输出格式

| 格式 | 场景 | 说明 |
|---|---|---|
| Markdown | 前端展示 | 内嵌在页面中的报告卡片 |
| Excel | 正式交付 | 追加到结果 Excel 的"报告"sheet |
| 文本 | 飞书/企微通知 | 精简版推送 |

### 4.5 API 设计

```
POST /api/ai/generate-report

Request:
{
  "results": [...TestResult],
  "cases": [...TestCase (简化)],
  "execution_summary": {
    "total": 25, "pass": 20, "fail": 3, "na": 2,
    "duration_seconds": 932,
    "date": "2026-08-14"
  },
  "format": "markdown"  // markdown|text|json
}

Response:
{
  "report": "# 测试执行报告\n\n## 执行概况\n...",
  "highlights": [
    {"type": "warning", "msg": "FT_002_01 连续3轮Fail"},
    {"type": "info", "msg": "通过率较上轮下降5%"}
  ]
}
```

---

## 五、不引入 AI 的部分（规则维护策略）

### 5.1 命令解析 — 规则 + 用例格式规范

**决策**：通过统一用例编写规范来保证现有规则引擎的覆盖率，而非引入 AI。

**用例编写规范（建议推行）**：

```
✅ 规范写法:
  1、输入命令：./nvsipl_camera -c MIXGROUP_PREDEV_30FPS ...
  2、输入 gc 10
  3、输入 al

❌ 不规范写法:
  起流后在终端输入al看看像素信息对不对
  → 需要改为标准格式
```

**规则维护策略**：
- 遇到新工具时，往 `_CMD_KEYWORDS` 和 `_EXTRACT_PATTERNS` 中添加
- 遇到新交互命令时，往 nvsipl 子命令白名单中添加
- 定期检查"未识别步骤（已跳过）"的日志，发现漏识别及时补充规则

**后续升级条件**：
- 当项目数量 > 5 且各项目用例格式差异大时
- 当规则维护成本（改代码频率）> 每周 1 次时
- 考虑引入 LLM 辅助解析

---

## 六、实施路径

### Phase 1：AI 失败分析（建议首批）

| 步骤 | 工作内容 | 预估工时 |
|---|---|---|
| 1 | 后端 AI Service 模块搭建（LLM 调用封装、provider 抽象） | 1d |
| 2 | `/api/ai/analyze-failure` 接口实现 | 0.5d |
| 3 | Prompt 设计与调优（基于真实失败日志） | 1d |
| 4 | 前端 "AI分析" 按钮和分析结果卡片 | 1d |
| 5 | 缓存机制 + 错误处理 + 降级逻辑 | 0.5d |
| 6 | 联调测试 | 0.5d |
| **合计** | | **4.5d** |

### Phase 2：AI 报告生成

| 步骤 | 工作内容 | 预估工时 |
|---|---|---|
| 1 | 报告数据收集和组织 | 0.5d |
| 2 | `/api/ai/generate-report` 接口 | 0.5d |
| 3 | Prompt 设计（报告模板 + 趋势分析） | 1d |
| 4 | 前端 "生成报告" 按钮和报告展示页 | 1.5d |
| 5 | 多格式输出（Markdown/Excel/文本） | 1d |
| 6 | 历史数据持久化（供趋势对比） | 1d |
| **合计** | | **5.5d** |

### Phase 3（远期）：扩展

- 多项目适配时再评估 AI 命令解析需求
- 智能用例推荐（需历史数据积累）
- 自适应执行参数（需统计学习）

---

## 七、技术依赖

| 依赖 | 必要性 | 备选方案 |
|---|---|---|
| LLM API（Claude/OpenAI） | 推荐 | 本地模型（Ollama + Qwen2.5） |
| API Key 管理 | 必须 | 环境变量 / 配置文件 |
| 网络连通（API 调用） | 在线模式 | 离线模式走本地模型 |
| 前端组件（分析卡片） | 必须 | Ant Design Collapse/Descriptions |

---

## 八、配置项（新增到 WorkspaceConfig）

```python
# AI 相关配置
ai_enabled: bool = False           # AI 功能总开关
ai_provider: str = "claude"        # claude / openai / ollama
ai_api_key: str = ""               # API Key (加密存储)
ai_model: str = "claude-haiku-4-5" # 默认模型
ai_base_url: str = ""              # 自定义 API URL（本地模型用）
ai_auto_analyze: bool = False      # 是否自动分析所有 Fail（false=手动触发）
ai_report_format: str = "markdown" # 报告默认格式
```
