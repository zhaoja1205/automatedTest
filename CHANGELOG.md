# 变更日志 (CHANGELOG)

本文件记录 `test_runner_web` 项目每个版本的功能变更、修复和改进。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/) `MAJOR.MINOR.PATCH`。

---

## [3.5.0] — 2026-09-07 — Phase 3: AI 测试步骤智能识别

### 新增 — AI 步骤解析全链路

上传 Excel 用例后，系统自动调用 AI 逐条解析自然语言测试步骤，提取可执行命令、交互指令和操作类型。

- **`backend/app/ai/prompts/parse_steps.py`** — 新建
  - 步骤解析专用 Prompt 模板，输入自然语言步骤，输出结构化 `AIParsedStep[]`
  - 识别 5 种 kind：`command` / `cd` / `nvsipl_input` / `manual` / `skip`
- **`backend/app/ai/service.py`** — 新增 `parse_steps()` 方法
  - 带缓存的异步步骤解析，缓存 key 为步骤文本哈希
  - 返回 `{parsed_steps, total, ai_recognized, _model, _tokens, _from_cache}`
- **`backend/app/api/routes.py`** — 新增 AI 步骤解析端点与异步触发
  - `POST /api/ai/parse-steps` — 单条用例解析
  - `POST /api/ai/parse-steps/batch` — 批量解析（带进度 WebSocket 推送）
  - `GET /api/ai/parsed-steps/{case_key}` — 查询已解析结果
  - 上传用例后自动触发 `_async_ai_parse_steps()`，通过 `asyncio.create_task` 不阻塞上传响应
- **`frontend/src/types/index.ts`** — 新增类型
  - `AIParsedStep`、`AIParseStepsResponse`、`AIParseStepsBatchResponse`
  - `WsAIParseProgressMessage`、`WsAIParseCompleteMessage`、`WsAIParseCaseDoneMessage`
- **`frontend/src/stores/useStore.ts`** — 新增状态字段
  - `aiParsedSteps: Record<string, AIParsedStep[]>`
  - `aiParsedCases: Set<string>`（已解析完成的用例 key 集合）
  - `aiParseProgress: { current, total, status, message, success, failed } | null`
- **`frontend/src/hooks/useWebSocket.ts`** — 新增消息处理
  - `ai_parse_progress` → 更新解析进度
  - `ai_parse_case_done` → 标记用例已解析，前端显示 🤖 标记
  - `ai_parse_complete` → 解析完成，30 秒后自动清除完成状态
- **`frontend/src/pages/Dashboard.tsx`** — 用例表增强
  - 已 AI 解析的用例行显示 🤖 标记（Tooltip 提示 AI 已识别步骤数）
  - 底部全局进度条：AI 步骤解析实时进度（parsing / done / interrupted 三态）
- **`frontend/src/api/axios.ts`** — 新增 AI 步骤解析 API 函数

### 新增 — AI 自动解析配置开关

- **`backend/app/core/test_case.py`** — `AIConfig` 新增 `ai_auto_parse_steps: bool = True`
- **`backend/app/api/routes.py`** — 上传后同时检查 `ai_enabled` 和 `ai_auto_parse_steps`
- **`frontend/src/components/AIConfigPanel.tsx`** — "功能开关" 区域新增 "AI 识别测试步骤" Switch

### 修复

- **AI 解析二次上传不显示**：上传前先清除旧 AI 解析状态（`aiParsedSteps` / `aiParsedCases` / `aiParseProgress`），避免 WS 消息与清除操作时序冲突
- **进度条消失过快**：`ai_parse_complete` 自动清除延长至 30 秒

---

## [3.4.0] — 2026-09-05 — 跳板机 SSH 回退增强

### 修复 — 跳板机 system SSH 回退

Paramiko 3.4.0 不支持 AES-GCM cipher（目标板端仅支持 AES-GCM），连接触发 `IncompatiblePeer`。

- **`backend/app/core/ssh_manager.py`** — 跳板机模式 system SSH 回退
  - 新增 `_has_sshpass()` 静态方法：检测 `sshpass` 是否可用
  - `_should_fallback_to_system_ssh()` — 跳板机模式允许回退（前提：`sshpass` 可用）
  - `_build_ssh_base_command()` — 跳板机模式从 `-J` 改为 `ProxyCommand="sshpass -p jump_pwd ssh -W %h:%p ..."`
  - `_run_system_ssh()` — 外层 `sshpass -p target_pwd` 包裹 SSH 命令（双密码传递）
  - `_open_system_ssh_pty()` — 同样支持 sshpass 包裹的 PTY 交互
  - `connect()` — 跳板机 Paramiko 失败时走 system SSH 回退，无 sshpass 时提示安装

### 修复 — SSH/Workspace 配置页无限轮询

- **`frontend/src/pages/SSHConfigPage.tsx`** — 替换 `useStore()` 为精确 selector
  - `useStore(s => s.setSSHConfig)` 等精确选择器，避免 Zustand 全量引用导致无限重渲染
  - 删除 `useCallback` 无限依赖循环，改用带 cancelled flag 的 `useEffect`
- **`frontend/src/pages/WorkspaceConfigPage.tsx`** — 同样修复

---

## [3.3.0] — 2026-09-02 — 记录报告模块

### 新增 — 执行历史与报告管理

- **`backend/app/core/history_store.py`** — 新建
  - 执行历史持久化存储（JSON 文件）
  - 支持按日期范围查询、分页
- **`backend/app/api/routes.py`** — 新增端点
  - `GET /api/history` — 查询执行历史列表
  - `GET /api/history/{run_id}` — 查询单次执行详情
  - `POST /api/report/generate` — 触发 AI 报告生成
  - `GET /api/reports` — 报告列表
  - `GET /api/reports/{report_id}` — 报告详情
- **`frontend/src/pages/HistoryPage.tsx`** — 新建
  - 执行历史列表（表格 + 筛选 + 对比分析）
- **`frontend/src/pages/ReportPage.tsx`** — 新建
  - AI 报告渲染（Markdown）
  - 报告管理与下载

---

## [3.2.0] — 2026-09-01 — 前端 UI 重构

### 改进 — Jira 清淡风格 + 侧边导航布局

- **`frontend/src/App.tsx`** — 侧边栏导航布局重构
  - 替换顶部 Tab 为左侧 Sider 导航
  - 图标化菜单项 + 可折叠侧边栏
- **`frontend/src/pages/`** — 所有页面适配新布局
  - 统一卡片风格、间距、配色
  - Jira 风格的清淡色调（低饱和灰蓝主色）

---

## [3.1.0] — 2026-09-02

### 改进 — 故障测试交错执行

重写 `_execute_parallel_fault_test` 方法，支持 shell 命令（故障注入脚本）与 PTY 交互命令（df/q）按步骤原始顺序交替执行。

- **`backend/app/core/executor_adapter.py`** — `_execute_parallel_fault_test` 方法重写
  - 去除提前收集 `gc_cmds` 列表的逻辑，改为按步骤原始顺序遍历
  - `nvsipl_input` 步骤 → 注入 PTY channel（gc/df/al/ro/q 等交互命令）
  - `command` 步骤 → 通过 `_ssh_execute` 在独立 SSH channel 执行（故障注入脚本等）
  - 支持 `repeat` 指令：第一轮执行 blocking_idx 后全部步骤，后续轮仅执行 repeat 范围内步骤
  - 新增 `_filter_pty_output` 静态方法：提取 PTY 输出中有效行（去除菜单提示和 fps 行）
  - 新增 `_send_pty` 内部方法：统一 PTY 发送逻辑，channel 关闭时安全降级
  - 保持反复起流、showmetadata、dl/elr 链路操作等原有功能不受影响

**典型用例支持**：
```
1、nvsipl_camera（PTY 阻塞运行）
2、fault_simulation（独立 SSH channel 执行）
3、df 查看故障（PTY 交互）
4、q 退出（PTY 交互）
5、重复 2-4 步骤
```
执行顺序：PTY(nvsipl) → auto gc → 等出帧 → fault_sim(SSH) → df(PTY) → q(PTY) → 重复

---

## [3.0.0] — 2026-09-01

### 新增 — 多会话隔离（多 PC 端并行测试）

支持多个浏览器标签页/多台 PC 同时访问同一服务，各自独立运行不同项目的测试，互不干扰。

- **`backend/app/core/session_store.py`** — 新建
  - `SessionState` 类：封装单个会话的全量状态（用例、SSH、配置、执行器、WS 连接）
  - `SessionStore` 类：全局会话注册表，`asyncio.Lock` 保护并发创建
  - `is_valid_session_id()` 验证 32 位十六进制 session ID 格式
- **`backend/app/websocket/session_ws_manager.py`** — 新建
  - `SessionWSManager` 类：session 隔离的 WebSocket 管理器
  - 与原 `ConnectionManager` 接口完全一致（`send_log`、`send_progress`、`broadcast`、`request_manual_confirm` 等）
  - `broadcast()` 仅向该 session 的 WS 连接发送
  - `_pending_confirmations` / `_confirm_results` per-session 独立
- **`frontend/src/api/axios.ts`**
  - 自动生成 UUID session ID，存入 `localStorage`
  - Axios 请求拦截器自动注入 `X-Session-ID` HTTP Header
  - 导出 `sessionId` 供 WebSocket 使用
- **`frontend/src/hooks/useWebSocket.ts`**
  - WebSocket URL 追加 `?session_id=${sessionId}` 参数

### 变更

- **`backend/app/main.py`** — 重写
  - 移除全局 `app_state`、`manager`、`config_store` 单例
  - 新增全局 `session_store = SessionStore()` 注册表
  - HTTP 中间件：从 `X-Session-ID` Header 解析 → `session_store.get_or_create()` → 注入 `request.state.session`
  - WebSocket 端点：从 `?session_id=` 查询参数解析，加入 `session.ws_connections`
  - 后台定时任务：每 5 分钟清理超时 session（无 WS 连接 + 未执行 + 1 小时无活动）
  - 应用关闭时停止所有 session 的执行器
  - FastAPI 版本号更新至 `3.0.0`
- **`backend/app/api/routes.py`** — 重写
  - 所有路由从 `app_state["key"]` 字典访问改为 `session.key` 属性访问
  - 文件上传路径隔离：`uploads/{filename}` → `uploads/{session_id}/{filename}`
  - 日志路径隔离：`logs/` → `logs/{session_id}/`
  - `_run_execution(session)` 使用 session 的 `ws_manager` 和隔离 `log_dir`
  - `_sync_cases_to_state(session, cases)` 参数改为 session 对象
- **`backend/app/core/executor_adapter.py`**
  - 构造函数新增 `log_dir="logs"` 参数，日志目录 per-session 隔离

### 隔离机制

| 维度 | 隔离方式 |
|------|---------|
| HTTP 请求 | `X-Session-ID` Header → 路由到对应 `SessionState` |
| WebSocket | `?session_id=` 查询参数 → 加入对应 session 的连接列表 |
| 文件存储 | `uploads/{session_id}/`、`logs/{session_id}/`、`runtime/{session_id}/` |
| SSH 连接 | 每个 session 独立 `SSHManager` 实例 |
| 执行器 | 每个 session 独立 `ExecutorAdapter` 实例 |
| 配置持久化 | `runtime/{session_id}/` 下独立 `ConfigStore` |

---

## [2.2.0] — 2026-08-31

### 新增 — 多拍照自动命名 & 文件计数校验

- **`backend/app/core/executor_adapter.py`**
  - 新增 `_inject_capture_name()` 静态方法：自动为 nvsipl 拍照命令注入唯一文件名
  - 第一次拍照路径 `-f /storage/zja/` → `-f /storage/zja/default`
  - 第二次拍照路径 `-f /storage/zja/` → `-f /storage/zja/rotate`（按配置含义命名）
  - `_execute_with_persistent_shell` 中维护 `capture_idx` 计数器
- **`backend/app/core/expected_parser.py`**
  - `ExpectedCriteria` 新增 `file_count: int = 0` 字段
  - 支持解析中文数量词（"两个文件"→2、"三个"→3，支持 两~十 及阿拉伯数字）
  - 在 `file_check` 检测后自动解析文件计数要求

### 新增 — 持久化 Shell 执行模式

- **`backend/app/core/executor_adapter.py`**
  - 新增 `_execute_with_persistent_shell()` 方法
  - 支持 `export` + `repeat` + `nvsipl` 组合命令在同一 `invoke_shell` 中顺序执行
  - 环境变量通过 `export` 设置后在后续命令中保持有效
  - 自动检测 nvsipl 阻塞型命令并走 PTY 交互模式

---

## [2.1.0] — 2026-08-30

### 新增 — 摄像头旋转配置支持

- **`frontend/src/types/index.ts`**
  - `WorkspaceConfig` 新增 `cam_rotate_cfg_path: string` 和 `cam_rotate_cfg_enabled: boolean`
- **`frontend/src/pages/Dashboard.tsx`**
  - "路径覆盖配置" 折叠面板中新增摄像头旋转配置的开关和路径输入框

---

## [2.0.0] — 2026-08-28

### 新增 — Web UI 前端 + 文件推送

- **前端应用**（React 18 / TypeScript / Vite / Ant Design / Zustand）
  - 仪表板页面：用例管理、SSH 配置、工作区配置、执行控制
  - 日志查看器：实时 WebSocket 日志流
  - 人工确认弹窗：步骤级手动确认机制
  - 文件推送功能：上传文件或指定本地路径推送到板端
  - 板端 so 文件复制：推送后复制到运行 so 路径
- **`backend/app/api/routes.py`**
  - `/files/push` — 上传文件并 SCP 推送到板端
  - `/files/push-local` — 从 PC 本地路径推送文件/目录到板端
  - `/files/copy-to-so` — 板端文件复制到运行 so 路径（支持 Linux/QNX）

---

## [1.2.0] — 2026-08-23

### 新增 — 跳板机模式 & 配置持久化

- **`backend/app/core/ssh_manager.py`**
  - 跳板机模式（`login_mode="jump"`）：通过跳板机 SSH 隧道连接目标板端
  - `test_connection()` 方法：快速验证 SSH 可达性
- **`backend/app/core/test_case.py`**
  - `SSHConfig` 新增 `login_mode`、`jump_host`、`jump_port`、`jump_username`、`jump_password` 字段
- **`backend/app/core/config_store.py`**
  - 通用 JSON 配置持久化，支持 `base_dir` 参数
  - SSH 配置和工作区配置自动保存/恢复

---

## [1.1.0] — 2026-08-17

### 新增 — PTY 交互式 nvsipl 执行

- **`backend/app/core/executor_adapter.py`**
  - `_execute_parallel_fault_test()` 重写为 PTY channel 方案
  - 支持 nvsipl_camera 阻塞型进程的交互命令注入（gc、al、ro 等）
  - 异步 `_read_channel()` 辅助函数：带超时和 `stop_pattern` 的增量读取
- **`backend/app/core/command_parser.py`**
  - 修复 Unicode 弯引号匹配（U+2018/2019/201C/201D）
  - "起流" pattern 加严：必须有冒号，避免 "起流后" 误匹配
  - nvsipl 交互输入检测前置，防止误提取为 shell 命令
- **`backend/app/core/ssh_manager.py`**
  - `execute()` 方法重写：channel 级 polling + timeout，解决 QNX 阻塞问题
  - `open_interactive_channel()` 方法：打开 PTY channel 用于交互式命令

### 修复

- 修复 Excel 中 Unicode 弯引号导致 `al`/`gc` 等交互命令无法识别
- 修复 "起流后" 被误匹配为执行命令
- 修复 Paramiko `exec_command` 在 QNX 后台进程不关 channel 时永久阻塞

---

## [1.0.0] — 2026-08-13

### 初始版本 — 规则引擎版

- **后端**（Python / FastAPI / Paramiko / openpyxl）
  - Excel 用例上传与解析
  - SSH 远程连接管理
  - 命令解析引擎（26 条正则 + 关键字白名单）
  - 顺序执行 + nvsipl 并行模式
  - 结果判定（关键字匹配 + FPS 检测 + 错误扫描）
  - NA 用例自动识别
  - Excel 结果回写
  - WebSocket 实时日志推送
- **前端**（React / TypeScript / Ant Design）
  - 基础仪表板 UI
  - 实时日志显示
  - 执行进度追踪
