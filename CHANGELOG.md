# 变更日志 (CHANGELOG)

本文件记录 `test_runner_web` 项目每个版本的功能变更、修复和改进。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/) `MAJOR.MINOR.PATCH`。

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
