# 测试执行管理系统 — 版本规划路线图

## 文档信息

| 项目 | 内容 |
|---|---|
| 文档名称 | 版本规划路线图 (Roadmap) |
| 适用工程 | `test_runner_web` |
| 创建日期 | 2026-08-17 |
| 状态 | 规划中 |

---

## 版本总览

```
V1.0.0                    V2.0.0                      V3.0.0
规则引擎版                 AI 辅助判定版                 全智能版
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
┌────────────┐      ┌──────────────────┐      ┌──────────────────────┐
│ 规则解析    │      │ 规则解析(不变)     │      │ AI 智能解析步骤       │
│ 规则判定    │  →   │ AI 结果判定       │  →   │ AI 结果判定           │
│ 规则匹配    │      │ AI 失败分析       │      │ AI 失败分析           │
│            │      │ AI 报告生成       │      │ AI 报告生成           │
└────────────┘      └──────────────────┘      │ AI 用例推荐           │
                                              │ AI 自适应执行         │
 当前                  下一阶段                 └──────────────────────┘
                                                 远期目标
```

---

## V1.0.0 — 规则引擎版（当前）

### 定位

纯代码逻辑 + 正则规则驱动，无 AI 依赖。稳定可靠的基线版本。

### 核心能力

| 模块 | 能力 | 实现方式 |
|---|---|---|
| 命令解析 | 从自然语言步骤提取可执行命令 | 26 条正则 + 关键字白名单 |
| 执行引擎 | 顺序执行 + nvsipl 并行模式 | SSH/PTY channel |
| 结果判定 | 关键字匹配 + FPS 检测 + 错误扫描 | 规则引擎（阈值固定） |
| NA 识别 | 自动识别不适用用例 | 关键字匹配 |
| 报告输出 | Excel 回写状态和结果 | openpyxl 原地修改 |

### 技术栈

- 后端：Python / FastAPI / Paramiko / openpyxl
- 前端：React / TypeScript / Ant Design / Zustand
- 通信：WebSocket 实时推送
- 无外部 AI 服务依赖

### 当前状态

- [x] 基本执行流程
- [x] PTY 交互式 nvsipl 执行
- [x] Unicode 引号兼容
- [x] 跳板机模式
- [ ] 稳定性打磨（残留进程清理、异常恢复）
- [ ] 用例编写规范文档

### V1.0.0 收尾待办

| 事项 | 说明 |
|---|---|
| 稳定性 | 执行前自动清理残留 nvsipl 进程 |
| 异常恢复 | SSH 断连自动重连 |
| 规范文档 | 输出《测试用例编写规范》，统一步骤格式 |
| 调试日志开关 | DEBUG 日志可在配置中关闭 |
| 代码清理 | 移除已废弃的 FIFO 方案相关代码 |

---

## V2.0.0 — AI 辅助判定版（下一阶段）

### 定位

在 V1 规则引擎基础上，**结果判定和失败分析**引入 AI 能力。命令解析保持规则方式不变。

### 新增能力

| 能力 | 说明 | 触发方式 |
|---|---|---|
| **AI 结果判定** | LLM 对比预期结果文本与实际输出，语义级 Pass/Fail 判定 | 规则引擎不确定时自动调用 |
| **AI 失败分析** | 失败用例自动分析根因、给出证据和修复建议 | 用户点击 / 可配自动 |
| **AI 报告生成** | 执行完成后生成结构化测试报告 | 用户触发 |

### 架构变化

```
V1.0.0 流程:
  步骤解析(规则) → 执行 → 结果判定(规则) → Excel 回写

V2.0.0 流程:
  步骤解析(规则) → 执行 → 结果判定(规则+AI) → AI失败分析 → AI报告 → 输出
                                │                      │            │
                                ▼                      ▼            ▼
                         ┌─────────────┐      ┌─────────────┐ ┌────────┐
                         │ 规则判定     │      │ 根因分析     │ │ 报告   │
                         │   ↓ 不确定   │      │ 证据提取     │ │ 趋势   │
                         │ AI语义判定   │      │ 修复建议     │ │ 建议   │
                         └─────────────┘      └─────────────┘ └────────┘
```

### 模块设计

#### 2.1 AI Service 层（新增）

```
backend/app/ai/
├── __init__.py
├── service.py          # AIService 主入口
├── providers/
│   ├── __init__.py
│   ├── base.py         # Provider 抽象接口
│   ├── claude.py       # Claude API (Haiku/Sonnet)
│   ├── openai.py       # OpenAI API (备选)
│   └── ollama.py       # 本地模型 (离线)
├── prompts/
│   ├── judge_result.py    # 结果判定 prompt
│   ├── analyze_failure.py # 失败分析 prompt
│   └── generate_report.py # 报告生成 prompt
└── cache.py            # 结果缓存（避免重复调用）
```

#### 2.2 AI 结果判定

**调用时机**：规则引擎判定 confidence < 0.7 或 status == UNCERTAIN 时

```python
# 判定级联逻辑
rule_result = rule_engine.match(expected, actual, exit_code)

if rule_result.confidence >= 0.8:
    # 规则引擎高置信，直接使用
    final = rule_result
elif ai_enabled:
    # 规则不确定，调用 AI
    ai_result = await ai_service.judge_result(
        expected_text=case.expected_result,
        actual_output=combined_output,
        case_context=case.description,
    )
    if ai_result.confidence >= 0.7:
        final = ai_result
    else:
        final = RuleResult(status="NEED_REVIEW", reason="AI和规则均不确定")
else:
    final = rule_result
```

**AI 判定输入/输出**：

| 输入 | 说明 |
|---|---|
| expected_text | 用例的预期结果原文 |
| actual_output | 命令执行实际输出（截断） |
| case_context | 用例描述、步骤摘要 |

| 输出 | 说明 |
|---|---|
| status | Pass / Fail / NEED_REVIEW |
| confidence | 0.0 ~ 1.0 |
| reason | 中文判定理由 |
| evidence | 实际输出中的关键匹配/不匹配行 |

#### 2.3 AI 失败分析

**触发方式**：
- 手动：前端 Fail 行点击"AI 分析"按钮
- 自动（可配）：所有 Fail 用例执行完自动分析

**输出结构**：

| 字段 | 说明 |
|---|---|
| root_cause_category | environment / defect / test_issue / flaky / mismatch |
| summary | 一句话根因概述 |
| evidence[] | 日志中的关键证据行 |
| explanation | 详细分析过程 |
| suggestion[] | 可操作修复建议 |
| confidence | 0.0 ~ 1.0 |
| is_likely_real_bug | bool，是否可能是真实缺陷 |

#### 2.4 AI 报告生成

**输出内容**：
1. 执行概况（总数/通过/失败/NA/通过率/耗时）
2. 失败用例逐条分析（根因分类+建议）
3. 趋势观察（与历史对比）
4. 综合建议（优先处理项）

**输出格式**：Markdown（前端展示）/ Excel Sheet / 纯文本（通知）

### 新增配置项

```python
class AIConfig(BaseModel):
    enabled: bool = False               # AI 功能总开关
    provider: str = "claude"            # claude / openai / ollama
    api_key: str = ""                   # API Key
    model: str = "claude-haiku-4-5-20251001"  # 默认模型
    base_url: str = ""                  # 自定义 URL（本地模型）
    auto_analyze_failures: bool = False # 自动分析所有 Fail
    judge_when_uncertain: bool = True   # 规则不确定时自动调用 AI 判定
    report_format: str = "markdown"     # 报告默认格式
    cache_ttl_hours: int = 24           # 缓存有效期
```

### 前端新增

| 组件 | 位置 | 说明 |
|---|---|---|
| "AI 分析" 按钮 | 用例表 Fail 行 | 触发失败分析 |
| 分析结果卡片 | 行展开 / 侧边抽屉 | 显示根因、证据、建议 |
| "生成报告" 按钮 | 工具栏 | 触发 AI 报告 |
| 报告展示页 | 新路由 /report | 渲染 Markdown 报告 |
| AI 配置面板 | Workspace 设置中 | AI 开关、模型选择、Key 配置 |
| 判定来源标记 | 状态 Tag 旁 | 标识 "规则判定" 或 "AI判定" |

### 技术依赖

| 依赖 | 说明 |
|---|---|
| anthropic SDK | Claude API 调用 |
| httpx | LLM API HTTP 客户端 |
| diskcache / Redis | 结果缓存 |
| markdown-it (前端) | 报告渲染 |

### 工时预估

| 模块 | 预估 |
|---|---|
| AI Service 基础框架 + Provider 抽象 | 2d |
| AI 结果判定 | 2d |
| AI 失败分析 | 2d |
| AI 报告生成 | 3d |
| 前端 UI（按钮、卡片、配置、报告页） | 3d |
| Prompt 调优 + 联调测试 | 3d |
| **合计** | **~15d** |

---

## V3.0.0 — 全智能版（远期）

### 定位

测试步骤解析也引入 AI，实现从用例加载到报告输出的**全链路 AI 赋能**。

### 新增能力（相对 V2）

| 能力 | 说明 |
|---|---|
| **AI 步骤解析** | LLM 理解自然语言步骤，提取命令、交互模式、等待条件 |
| **AI 用例推荐** | 基于变更/历史推荐执行范围 |
| **AI 自适应执行** | 动态调整超时、重试策略、执行顺序 |
| **AI 用例生成** | 从需求文档自动生成测试用例草稿 |
| **多项目适配** | 工具描述文件 + AI 自动适配新项目 |

### AI 步骤解析

**V1/V2 方式**：正则规则（需统一用例格式）
**V3 方式**：LLM 理解任意格式的步骤描述

```
输入 (任意格式):
  "先把camera跑起来用30fps的配置，等出帧后查一下al看像素对不对"

AI 输出 (结构化):
  [
    {"type": "command", "cmd": "./nvsipl_camera -c MIXGROUP_PREDEV_30FPS ...",
     "mode": "blocking_interactive"},
    {"type": "interactive", "cmd": "gc 10", "wait_for": "Frame rate"},
    {"type": "interactive", "cmd": "al", "wait_for": "Vertical|horizontal",
     "purpose": "检查像素信息"}
  ]
```

**适用场景**：
- 用例格式不统一（多团队/多项目）
- 步骤描述口语化、非标准化
- 新项目快速接入（不需要改写用例格式）

### 架构演进

```
V3.0.0 全链路:

  用例加载 → AI步骤解析 → AI执行策略 → 执行 → AI结果判定 → AI失败分析 → AI报告
     │            │              │                      │            │          │
     ▼            ▼              ▼                      ▼            ▼          ▼
  多格式      语义理解        动态超时             语义匹配      根因定位    趋势+建议
  适配        命令提取        智能重试             模糊判定      证据链      多格式
             交互识别        并行编排                          修复建议
```

### 升级前提

| 前提条件 | 说明 |
|---|---|
| V2 稳定运行 | AI 判定/分析已验证可靠 |
| 多项目需求 | 至少 3+ 不同项目接入需求 |
| 用例格式多样 | 规则引擎维护成本过高 |
| 历史数据积累 | 用例推荐需要足够历史执行数据 |
| LLM 能力验证 | 步骤解析准确率需 > 95%（经对照测试） |

### 风险控制

| 风险 | 对策 |
|---|---|
| AI 解析出错误命令 | 解析结果人工确认 + 白名单兜底 + dry-run 模式 |
| 幻觉命令 | 命令必须通过 `is_valid_command` 校验才能执行 |
| 延迟 | 解析结果缓存（同用例不重复解析） |
| 成本 | 首次解析用 Sonnet，缓存后零成本 |

---

## 版本对比

| 维度 | V1.0.0 | V2.0.0 | V3.0.0 |
|---|---|---|---|
| 命令解析 | 规则 | 规则 | **AI** |
| 执行引擎 | 规则编排 | 规则编排 | **AI 自适应** |
| 结果判定 | 规则 | **规则 + AI** | AI |
| 失败分析 | 无 | **AI** | AI |
| 报告生成 | Excel 回写 | **AI 报告** | AI 报告 |
| 外部依赖 | 无 | LLM API | LLM API |
| 适配新项目 | 改代码 | 改代码/规则 | **配置 + AI** |
| 用例格式要求 | 严格规范 | 严格规范 | **任意格式** |
| 离线可用 | ✅ 完全 | ⚠️ 降级到规则 | ⚠️ 降级到规则 |

---

## 里程碑时间线（建议）

```
2026 Q3                    2026 Q4                     2027 Q1
───────────────────────────────────────────────────────────────────

V1.0.0 稳定发布            V2.0.0 开发                  V3.0.0 评估
  │                          │                           │
  ├─ 稳定性打磨              ├─ AI Service 框架           ├─ 需求评估
  ├─ 用例规范文档            ├─ AI 结果判定               ├─ AI 步骤解析 POC
  ├─ 代码清理               ├─ AI 失败分析               ├─ 多项目试点
  └─ 完成                   ├─ AI 报告生成               └─ 决定是否推进
                            ├─ 前端 UI
                            └─ 联调发布

  ~2-3 周                    ~3-4 周                      ~待定
```
