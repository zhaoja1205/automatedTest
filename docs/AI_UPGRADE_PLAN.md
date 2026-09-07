# 测试执行管理系统 — AI 智能化升级规划

## 文档信息

| 项目 | 内容 |
|---|---|
| 文档名称 | AI 智能化升级规划 |
| 适用工程 | `test_runner_web` |
| 创建日期 | 2026-08-14 |
| 最后更新 | 2026-09-07 |
| 状态 | Phase 2 ✅ 已完成 / Phase 3 🔧 开发中 |

---

## 一、升级方向总览

| 方向 | 优先级 | 说明 | 状态 |
|---|---|---|---|
| **AI 结果判定** | P0 | 用例执行后 AI 根据 log 语义判定 Pass/Fail | ✅ 已完成 |
| **AI 失败分析** | P0 | 用例 Fail 时 AI 自动分析根因并给出建议 | ✅ 已完成 |
| **AI 报告生成** | P1 | 执行完成后 AI 生成结构化测试报告 | ✅ 已完成 |
| **AI 步骤解析** | P1 | LLM 理解自然语言步骤，提取命令和操作类型 | ✅ 已完成 |
| **AI 用例推荐** | P2 — 远期 | 基于变更/历史推荐执行范围 | 📋 规划中 |
| **AI 自适应执行** | P2 — 远期 | 动态调整超时、重试、执行顺序 | 📋 规划中 |

---

## 二、已完成：AI 结果判定 ✅

### 实现方式

三种判定模式可配：

| 模式 | 配置值 | 触发时机 |
|---|---|---|
| 始终 AI 判定 | `always`（默认） | 每条用例执行完后自动调 AI 分析 log |
| 仅不确定时 | `uncertain` | 规则引擎置信度 < 0.7 时才调 AI |
| 关闭 | `off` | 仅用规则引擎判定 |

### 判定输入/输出

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

### 相关文件

- `backend/app/ai/prompts/judge_result.py` — 判定 Prompt
- `backend/app/ai/service.py` → `judge_result()` — 判定方法
- `backend/app/core/executor_adapter.py` — 执行后调用判定

---

## 三、已完成：AI 失败分析 ✅

### 触发方式

- 手动：前端 Fail 行点击 "AI 分析" 按钮
- 自动（可配 `ai_auto_analyze`）：所有 Fail 用例执行完自动分析

### 输出结构

| 字段 | 说明 |
|---|---|
| root_cause_category | environment / defect / test_issue / flaky / mismatch |
| root_cause_summary | 一句话根因概述 |
| evidence[] | 日志中的关键证据行 |
| explanation | 详细分析过程 |
| suggestion[] | 可操作修复建议 |
| confidence | 0.0 ~ 1.0 |
| is_likely_real_bug | bool，是否可能是真实缺陷 |

### 相关文件

- `backend/app/ai/prompts/analyze_failure.py` — 分析 Prompt
- `backend/app/ai/service.py` → `analyze_failure()` — 分析方法
- `backend/app/api/routes.py` → `POST /api/ai/analyze/{case_id}` — API 端点

---

## 四、已完成：AI 报告生成 ✅

### 输出内容

1. 执行概况（总数/通过/失败/NA/通过率/耗时）
2. 失败用例逐条分析（根因分类+建议）
3. 趋势观察（与历史对比）
4. 综合建议（优先处理项）

### 输出格式

| 格式 | 场景 |
|---|---|
| Markdown | 前端展示（AI 报告页） |

### 相关文件

- `backend/app/ai/prompts/generate_report.py` — 报告 Prompt
- `backend/app/ai/service.py` → `generate_report()` — 报告方法
- `backend/app/api/routes.py` → `POST /api/report/generate` — API 端点
- `frontend/src/pages/ReportPage.tsx` — 报告展示页

---

## 五、已完成：AI 步骤解析 ✅

### 功能定义

上传 Excel 用例后，系统自动调用 AI 逐条解析自然语言测试步骤，提取可执行命令、交互指令和操作类型。

### 解析输入/输出

**输入**：自然语言测试步骤文本 + 用例描述上下文

**输出**：结构化 `AIParsedStep[]`

| 字段 | 说明 |
|---|---|
| command | 提取的命令 |
| description | 步骤描述 |
| kind | `command` / `cd` / `nvsipl_input` / `manual` / `skip` |
| terminal | 终端标识（可选） |
| confidence | 0.0 ~ 1.0 |
| step_num | 步骤序号 |

### 实现特性

- 上传后自动触发异步批量解析（`asyncio.create_task`），不阻塞上传响应
- WebSocket 实时推送解析进度（`ai_parse_progress` / `ai_parse_case_done` / `ai_parse_complete`）
- 前端 🤖 标记标识已解析用例
- 解析结果缓存（相同步骤文本不重复调用 AI）
- 可通过 AI 配置面板开关控制（`ai_auto_parse_steps`，默认开启）
- 执行启动时自动中断未完成的批量解析，避免 API 资源竞争

### API 端点

| 端点 | 说明 |
|---|---|
| `POST /api/ai/parse-steps` | 单条用例步骤解析 |
| `POST /api/ai/parse-steps/batch` | 批量解析（带进度推送） |
| `GET /api/ai/parsed-steps/{case_key}` | 查询已解析结果 |

### 相关文件

- `backend/app/ai/prompts/parse_steps.py` — 步骤解析 Prompt
- `backend/app/ai/service.py` → `parse_steps()` — 解析方法
- `backend/app/api/routes.py` → 上传后 `_async_ai_parse_steps()` 异步触发
- `frontend/src/pages/Dashboard.tsx` — 🤖 标记 + 进度条
- `frontend/src/hooks/useWebSocket.ts` — WS 消息处理
- `frontend/src/stores/useStore.ts` — `aiParsedSteps` / `aiParsedCases` / `aiParseProgress`

---

## 六、AI Service 架构（已实现）

### 模块结构

```
backend/app/ai/
├── __init__.py
├── service.py              # AIService 主入口
│                           #   judge_result()    — 结果判定
│                           #   analyze_failure() — 失败分析
│                           #   generate_report() — 报告生成
│                           #   parse_steps()     — 步骤解析
├── providers/
│   ├── __init__.py
│   ├── base.py             # Provider 抽象接口
│   ├── claude.py           # Claude API + 中智网关兼容
│   ├── openai_compat.py    # OpenAI 兼容 API
│   └── ollama.py           # 本地模型 (Ollama)
├── prompts/
│   ├── judge_result.py     # 结果判定 prompt
│   ├── analyze_failure.py  # 失败分析 prompt
│   ├── generate_report.py  # 报告生成 prompt
│   └── parse_steps.py      # 步骤解析 prompt
└── cache.py                # 磁盘缓存（MD5 哈希 key，可配 TTL）
```

### 多 Provider 支持

| Provider | 适用场景 | 说明 |
|---|---|---|
| Claude (Anthropic) | 推荐 | 通过中智网关 `https://llm.thundersoft.com` 或直连 Anthropic |
| OpenAI 兼容 | 备选 | 任何 OpenAI 兼容 API |
| Ollama | 离线 | 本地模型（Qwen2.5-7B 等） |

### 中智网关模型

| 模型 ID | 说明 |
|---|---|
| `ts-pri-auto` | 自动路由（默认，均衡推荐） |
| `ts-gpt-55` | GPT-5.5 |
| `ts-opus-46` | Claude Opus 4.6（最强） |
| `ts-pri-glm` | GLM（快速） |
| `ts-pri-kimi` | Kimi（中文优化） |
| `ts-pri-deepseek` | DeepSeek |

### 配置项

```python
class AIConfig(BaseModel):
    ai_enabled: bool = True
    ai_provider: str = "claude"               # claude / openai / ollama
    ai_api_key: str = ""
    ai_model: str = "ts-pri-auto"             # 默认中智网关自动路由
    ai_base_url: str = "https://llm.thundersoft.com"
    ai_auto_analyze: bool = False             # 自动分析所有 Fail
    ai_auto_parse_steps: bool = True          # 上传后自动 AI 识别步骤
    ai_judge_mode: str = "always"             # off / uncertain / always
    ai_cache_ttl_hours: int = 24
```

### 缓存策略

| 策略 | 说明 |
|---|---|
| 缓存 key | 输入内容 MD5 哈希 |
| TTL | 可配，默认 24 小时 |
| 存储 | 磁盘文件（`runtime/ai_cache/`） |
| 命中标记 | 响应中 `_from_cache: true` |

---

## 七、前端 AI 组件（已实现）

| 组件 | 位置 | 说明 |
|---|---|---|
| AI 配置面板 | 侧边导航独立页 | Provider/Key/模型/URL/功能开关/判定模式 |
| AI 分析按钮 | 用例表 Fail 行 | 点击触发失败分析 |
| 分析结果卡片 | Popover 展示 | 根因、证据、建议、置信度 |
| 判定来源标记 | 状态 Tag 旁 | "规则判定" / "AI判定" + 置信度百分比 |
| 🤖 解析标记 | 用例 ID 旁 | AI 已识别步骤数提示 |
| AI 解析进度条 | Dashboard 底部 | 批量解析实时进度 |
| 报告页面 | 侧边导航 | AI 报告列表 + Markdown 渲染 |
| 历史记录页 | 侧边导航 | 执行历史 + 对比分析 |
| 连接测试 | AI 配置面板 | 一键测试 AI 服务连通性 |

---

## 八、远期规划（待评估）

### AI 用例推荐

- 基于变更文件/模块推荐受影响的测试用例
- 基于历史失败频率推荐优先执行范围
- **前提**：需要足够的历史执行数据积累

### AI 自适应执行

- 动态调整命令超时（基于历史耗时统计）
- 智能重试策略（区分偶发/持续失败）
- 执行顺序优化（优先执行高失败率用例）

### AI 用例生成

- 从需求文档自动生成测试用例草稿
- **前提**：需求文档格式标准化

### 多项目适配

- 工具描述文件 + AI 自动适配新项目的命令解析
- **前提**：至少 3+ 不同项目接入需求

### 升级前提

| 前提条件 | 说明 |
|---|---|
| Phase 3 稳定运行 | AI 步骤解析 + 判定/分析/报告已验证可靠 |
| 多项目需求 | 至少 3+ 不同项目接入需求 |
| 历史数据积累 | 用例推荐需要足够历史执行数据 |
| 团队反馈 | 收集使用反馈确定优先级 |

---

## 九、实施路径（实际执行记录）

### Phase 1：AI 失败分析 + AI 判定 ✅

| 步骤 | 工作内容 | 完成日期 |
|---|---|---|
| 1 | AI Service 框架 + Provider 抽象（Claude/OpenAI/Ollama） | 2026-09-01 |
| 2 | AI 结果判定（三种模式） | 2026-09-01 |
| 3 | AI 失败分析（根因/证据/建议） | 2026-09-01 |
| 4 | 中智网关适配（claude_provider 兼容） | 2026-09-01 |
| 5 | 前端 AI 分析卡片 + 判定来源标记 | 2026-09-01 |
| 6 | AI 配置面板 | 2026-09-01 |

### Phase 2：AI 报告生成 + 前端重构 ✅

| 步骤 | 工作内容 | 完成日期 |
|---|---|---|
| 1 | AI 报告生成服务 | 2026-09-02 |
| 2 | 前端 UI 重构（Jira 风格 + 侧边导航） | 2026-09-01 |
| 3 | 执行历史 + 报告管理模块 | 2026-09-02 |

### Phase 3：AI 步骤解析 + 基础设施增强 ✅

| 步骤 | 工作内容 | 完成日期 |
|---|---|---|
| 1 | 多会话隔离架构 | 2026-09-01 |
| 2 | 故障测试交错执行 | 2026-09-02 |
| 3 | AI 步骤解析 Prompt + Service + API | 2026-09-07 |
| 4 | 前端 🤖 标记 + 解析进度条 + WS 消息 | 2026-09-07 |
| 5 | AI 自动解析配置开关 | 2026-09-07 |
| 6 | 跳板机 SSH sshpass 双密码回退 | 2026-09-05 |
| 7 | SSH/Workspace 配置页无限轮询修复 | 2026-09-05 |

---

## 十、技术依赖

| 依赖 | 必要性 | 说明 |
|---|---|---|
| anthropic SDK | 推荐 | Claude API 调用（中智网关 + 直连） |
| httpx | 必须 | LLM API HTTP 客户端 |
| sshpass | 跳板机必须 | 双密码 SSH 传递（`/usr/bin/sshpass`） |
| Ant Design | 前端 | UI 组件库（侧边导航 / 表格 / 卡片） |
| Zustand | 前端 | 状态管理（session 级 AI 解析状态） |
