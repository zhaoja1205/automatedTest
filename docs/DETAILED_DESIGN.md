# 测试执行管理系统 详细设计说明

## 0. 文档控制信息

| 项目 | 内容 |
|---|---|
| 文档名称 | 测试执行管理系统 详细设计说明 |
| 适用工程 | `test_runner_web` |
| 文档类型 | 软件详细设计说明书（Detailed Design Description） |
| 当前版本 | v4.0.0 |
| 主要读者 | 开发、代码评审人、维护人员 |
| 配套文档 | `docs/ARCHITECTURE.md`（架构说明）、`docs/DIAGRAMS.md`（模块关系与时序图） |

### 0.0 变更记录

| 版本 | 日期 | 变更说明 |
|---|---|---|
| 初版 | 2026-11-26 | 基于 v4.0.0 代码状态编写，覆盖后端/前端全模块详细设计 |

### 0.1 文档定位

本文档是 `ARCHITECTURE.md` 的下层文档，聚焦于**模块内部设计**：

- 每个模块的职责边界、类/函数级接口说明
- 数据模型的字段定义与约束
- 模块间的调用关系与依赖
- 关键算法与设计决策

本文档**不覆盖**：

- 系统级架构决策（参见 ARCHITECTURE.md §13 ADR）
- 模块间交互时序（参见 DIAGRAMS.md §2）
- 具体测试脚本或设备指令

---

## 1. 后端详细设计

### 1.1 应用入口：`main.py`

#### 职责

- FastAPI 应用实例创建与生命周期管理
- 路由注册（7 个路由模块）
- CORS 中间件配置
- **Session 中间件**：HTTP 请求注入 `request.state.session`
- **WebSocket 入口**：`/ws` 端点，按 `session_id` 隔离
- **后台任务**：session 超时清理、过期文件清理

#### 关键设计

**生命周期管理（lifespan）**

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时创建目录
    os.makedirs("uploads", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    os.makedirs("output", exist_ok=True)
    os.makedirs("runtime", exist_ok=True)
    os.makedirs("runtime/creator_projects", exist_ok=True)
    os.makedirs("runtime/classdiag_projects", exist_ok=True)
    os.makedirs("runtime/seqdiag_projects", exist_ok=True)
    os.makedirs("uploads/merge", exist_ok=True)
    # 启动后台清理任务
    cleanup_task = asyncio.create_task(_cleanup_loop())       # 每 5 分钟清理超时 session
    file_cleanup_task = asyncio.create_task(_file_cleanup_loop())  # 按配置间隔清理过期文件
    yield
    # 关闭时清理
    cleanup_task.cancel()
    file_cleanup_task.cancel()
    session_store.shutdown_all()
```

**Session 中间件**

所有 `/api/` 路径的请求通过 `inject_session_state` 中间件注入 session：

1. 从 `X-Session-ID` 请求头读取 session_id
2. 格式校验（32 位十六进制）
3. 通过 `SessionStore.get_or_create()` 获取/创建 session
4. 注入到 `request.state.session`

**豁免路径**（无需 session）：

| 路径前缀 | 原因 |
|---|---|
| `/api/seqdiag/` | session-agnostic 项目管理 |
| `/api/classdiag/` | session-agnostic 项目管理 |
| `/api/plantuml/` | 纯反向代理，无 session 状态 |
| `/api/casegen/download/` | 静态文件下载 |
| `/api/merge/download/` | 按 uuid token 定位文件 |

**WebSocket 端点**

```
ws://host:port/ws?session_id=<32位hex>
```

- 连接时校验 session_id 格式
- 接收消息类型：`confirm_response`（人工确认）、`stop_execution`（停止执行）
- 断开时自动从 session 的 ws_connections 中移除

---

### 1.2 API 路由层

#### 1.2.1 `routes.py` — 执行管理 REST API

| 端点 | 方法 | 职责 |
|---|---|---|
| `/api/excel/upload` | POST | 上传 Excel 用例文件，解析 TestCase 列表，异步触发 AI 步骤预解析 |
| `/api/cases` | GET | 获取当前 session 的测试用例列表（可按 sheet 过滤） |
| `/api/cases/select` | POST | 批量选择/取消选择用例 |
| `/api/cases/update` | POST | 更新单条用例字段（test_steps / expected_result） |
| `/api/cases/preview-commands` | POST | 预览用例将要下发的命令序列 |
| `/api/cases/remark` | GET | 获取单条用例的备注信息（AI 判定 + 执行日志） |
| `/api/cases/images` | GET | 列出某条用例已下载的 PNG 图片 |
| `/api/cases/images/availability` | POST | 批量查询用例图片可用性 |
| `/api/cases/images/<case_id>/<filename>` | GET | 获取单张 PNG 图片（blob） |
| `/api/ssh/config` | GET/POST | 读写 SSH 连接配置 |
| `/api/ssh/status` | GET | 获取 SSH 连接状态 |
| `/api/ssh/test` | POST | 测试 SSH 连接 |
| `/api/workspace/config` | GET/POST | 读写工作区配置 |
| `/api/execute/start` | POST | 启动测试执行（创建后台 asyncio.Task） |
| `/api/execute/stop` | POST | 请求停止执行 |
| `/api/execute/status` | GET | 获取执行任务状态 |
| `/api/download/results` | GET | 下载结果 Excel（含/不含日志） |
| `/api/buglist` | GET | 获取 BugList 统计页数据 |
| `/api/logs/content` | GET | 获取单条用例的执行日志内容 |
| `/api/files/push` | POST | 上传文件到板端 |
| `/api/files/push-local` | POST | 将本地路径文件推送到板端 |
| `/api/ai/config` | GET/POST | 读写 AI 功能配置 |
| `/api/ai/prompts` | GET/PUT | 读写 AI 系统提示词 |
| `/api/ai/profiles` | GET/POST | AI 配置方案管理 |
| `/api/ai/profiles/<id>/activate` | POST | 激活 AI 配置方案 |
| `/api/ai/test` | POST | 测试 AI 连接 |
| `/api/ai/models` | POST | 查询可用 AI 模型 |
| `/api/ai/analyze` | POST | AI 失败分析（同步） |
| `/api/ai/analyze/stream` | POST | AI 失败分析（SSE 流式） |
| `/api/ai/analyze-all` | POST | 批量分析所有失败用例 |
| `/api/ai/report` | POST | 生成测试报告 |
| `/api/ai/judge` | POST | AI 判定单条用例结果 |
| `/api/ai/parse-steps` | POST | AI 解析单条用例测试步骤 |
| `/api/ai/parse-steps-batch` | POST | AI 批量解析测试步骤 |
| `/api/cleanup/config` | GET/POST | 文件清理配置 |
| `/api/cleanup/stats` | GET | 清理统计信息 |
| `/api/cleanup/run` | POST | 手动触发清理 |

**关键内部函数**

- `_rule_parse_steps(step_text)` — 规则先行：用 `CommandParser` 解析步骤文本，若解出 ≥1 条可执行命令则跳过 AI 调用
- `_async_ai_parse_steps(session)` — 异步批量 AI 预解析所有用例步骤（不阻塞上传响应）

#### 1.2.2 `aspice_routes.py` — ASPICE 文档生成 API

| 端点 | 方法 | 职责 |
|---|---|---|
| `/api/aspice/projects` | GET/POST | 项目列表/创建 |
| `/api/aspice/projects/<id>` | GET/DELETE | 项目详情/删除 |
| `/api/aspice/swe1/save` | POST | 保存 SWE.1 需求数据 |
| `/api/aspice/swe1/validate` | POST | SWE.1 需求校验（V01-V19） |
| `/api/aspice/swe1/export` | POST | 导出 SWE.1 需求清单 |
| `/api/aspice/swe1/ingest/upload` | POST | 上传需求源文件（Excel/Word） |
| `/api/aspice/swe1/ingest/preview` | POST | 预览回灌结果（列映射 + 行类型） |
| `/api/aspice/swe1/ingest/confirm` | POST | 确认回灌（入库） |
| `/api/aspice/swe1/templates` | GET | 获取列映射模板列表 |
| `/api/aspice/swe1/templates` | POST | 保存列映射模板 |
| `/api/aspice/swe2/save` | POST | 保存 SWE.2 架构数据 |
| `/api/aspice/swe2/generate` | POST | 生成 SWE.2 架构设计书 |
| `/api/aspice/swe2/func-briefs` | POST | AI 补全函数简介 |
| `/api/aspice/swe3/save` | POST | 保存 SWE.3 详细设计数据 |
| `/api/aspice/swe3/scan` | POST | 扫描工程源码 |
| `/api/aspice/swe3/augment` | POST | AI 增强函数详情 |
| `/api/aspice/swe3/generate` | POST | 生成 SWE.3 详细设计书 |

#### 1.2.3 `classdiag_routes.py` — 类图分析 API

| 端点 | 方法 | 职责 |
|---|---|---|
| `/api/classdiag/projects` | GET/POST | 项目列表/创建 |
| `/api/classdiag/projects/<id>` | GET/DELETE | 项目详情/删除 |
| `/api/classdiag/upload` | POST | 上传 C++ 工程 zip |
| `/api/classdiag/parse` | POST | 解析类结构 |
| `/api/classdiag/projects/<id>/save` | POST | 保存项目数据 |

#### 1.2.4 `seqdiag_routes.py` — 函数时序图 API

| 端点 | 方法 | 职责 |
|---|---|---|
| `/api/seqdiag/projects` | GET/POST | 项目列表/创建 |
| `/api/seqdiag/projects/<id>` | GET/DELETE | 项目详情/删除 |
| `/api/seqdiag/upload` | POST | 上传 C++ 工程 zip |
| `/api/seqdiag/parse` | POST | 解析函数调用链 |
| `/api/seqdiag/generate` | POST | 生成 PlantUML 时序图 |
| `/api/seqdiag/projects/<id>/save` | POST | 保存项目数据 |

#### 1.2.5 `plantuml_routes.py` — PlantUML 代理 API

| 端点 | 方法 | 职责 |
|---|---|---|
| `/api/plantuml/png` | GET | 反向代理 PlantUML PNG 渲染（支持本地/云端） |

设计要点：`<img src>` 无法携带自定义 header，因此该路由不要求 session。上游硬编码为 `plantuml.com`，无 SSRF 风险。

#### 1.2.6 `casegen_routes.py` — 用例生成 API

| 端点 | 方法 | 职责 |
|---|---|---|
| `/api/casegen/generate` | POST | 根据拓扑矩阵生成测试用例 |
| `/api/casegen/export` | POST | 导出用例为 xlsx |
| `/api/casegen/download/<filename>` | GET | 下载已生成的文件 |

#### 1.2.7 `merge_routes.py` — 合并结果 API

| 端点 | 方法 | 职责 |
|---|---|---|
| `/api/merge/submit` | POST | 提交多 session 执行结果 |
| `/api/merge/list` | GET | 列出合并批次 |
| `/api/merge/download/<uuid>` | GET | 下载合并结果 |

---

### 1.3 核心业务层

#### 1.3.1 `session_store.py` — 多会话状态管理

**类：`SessionState`**

单个 session 的完整运行状态：

| 属性 | 类型 | 说明 |
|---|---|---|
| `session_id` | str | 32 位十六进制标识 |
| `created_at` | float | 创建时间戳 |
| `last_active` | float | 最近活跃时间戳 |
| `test_cases` | list | 当前 session 的测试用例列表 |
| `ssh_config` | SSHConfig | SSH 连接配置 |
| `ssh_status` | SSHStatus | SSH 连接状态 |
| `workspace` | WorkspaceConfig | 工作区配置 |
| `sheets` | list | Excel 工作表列表 |
| `bug_list` | list | BugList 统计页数据 |
| `bug_sheet` | str | BugList 页签名 |
| `executor` | ExecutorAdapter \| None | 当前执行器 |
| `is_running` | bool | 是否正在执行 |
| `current_task` | ExecutionTask | 执行任务状态 |
| `excel_path` | str | 已上传 Excel 路径 |
| `_stop_requested` | bool | 停止请求标记 |
| `config_store` | ConfigStore | per-session 配置存储 |
| `ws_connections` | List[WebSocket] | WebSocket 连接列表 |
| `ws_manager` | SessionWSManager | per-session WebSocket 管理器 |

**类：`SessionStore`**

管理所有活跃 session 的注册表（asyncio.Lock 线程安全）：

| 方法 | 说明 |
|---|---|
| `get_or_create(session_id)` | 获取或首次创建 session（自动建目录、加载配置） |
| `get(session_id)` | 获取已有 session |
| `remove(session_id)` | 移除 session（断开 WS、停止执行器） |
| `all_sessions()` | 返回所有活跃 session 列表 |
| `cleanup_stale(timeout=3600)` | 清理超时 session（无 WS 连接 + 非执行中 + 超时无活动） |
| `shutdown_all()` | 应用关闭时停止所有执行器 |

#### 1.3.2 `test_case.py` — 数据模型

**`TestCase`（dataclass）**

| 字段 | 类型 | 说明 |
|---|---|---|
| `case_id` | str | 用例 ID（Excel 行） |
| `case_key` | str | 唯一标识 = `{sheet}:{row}:{case_id}` |
| `test_type` | str | 用例类型（功能/故障/稳定性） |
| `requirement_id` | str | 关联需求 ID |
| `design_method` | str | 设计方法 |
| `description` | str | 用例描述 |
| `prerequisites` | str | 前置条件 |
| `test_steps` | str | 测试步骤 |
| `expected_result` | str | 预期结果 |
| `priority` | str | 优先级 |
| `selected` | bool | 是否选中执行 |
| `row_number` | int | Excel 行号 |
| `source_sheet` | str | 来源工作表名 |
| `actual_result` | str | 实际结果 |
| `status` | str | 状态（NT/PASS/FAIL/NA/BLOCKED） |
| `judgment` | str | Excel「BUG」列（AI 判定信息） |
| `bug_id` | str | Bug ID |
| `log_file` | str | 日志文件路径 |
| `tester` / `test_date` / `test_version` / `remarks` | str | 测试元信息 |
| `expected_keywords` | List[str] | 预期结果关键字列表 |
| `ai_judged` / `ai_status` / `ai_confidence` / `ai_reason` / `ai_evidence` | — | AI 判定详情 |
| `bug_description` / `bug_severity` | str | AI 生成的 Bug 描述/严重程度 |

**`TestResult`（dataclass）**

单次执行产生的结构化结果，包含 `case_id`、`status`、`start_time`/`end_time`、`log_file`、`actual_output`、`match_reason`、`error_msg`、AI 判定详情等。

**`SSHConfig`（Pydantic BaseModel）**

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `login_mode` | str | `"direct"` | `direct` / `jump` |
| `host` | str | `""` | 目标主机 |
| `port` | int | `22` | SSH 端口 |
| `username` | str | `""` | 登录用户名 |
| `password` | str | `""` | 登录密码 |
| `key_path` | str | `""` | SSH 密钥路径 |
| `target_password` | str | `""` | 目标设备密码 |
| `timeout` | int | `30` | 连接超时（秒） |
| `jump_host` / `jump_port` / `jump_username` / `jump_password` | — | — | 跳板机配置 |

**`WorkspaceConfig`（Pydantic BaseModel）**

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `tester_name` | str | `""` | 测试人员 |
| `test_version` | str | `""` | 测试版本 |
| `default_remote_path` | str | `""` | 默认远端路径 |
| `driver_path` | str | `""` | 驱动路径 |
| `nito_override_path` | str | `""` | NITO 覆盖路径 |
| `nito_override_enabled` | bool | `False` | NITO 覆盖开关 |
| `image_storage_path` | str | `""` | 图片存储路径 |
| `image_storage_enabled` | bool | `False` | 图片存储开关 |
| `image_download_path` | str | `""` | 图片下载路径 |
| `image_download_enabled` | bool | `False` | 图片下载开关 |
| `cam_rotate_cfg_path` | str | `""` | 相机旋转配置路径 |
| `cam_rotate_cfg_enabled` | bool | `False` | 相机旋转配置开关 |
| `log_remark_mode` | str | `"image"` | 备注列日志呈现方式：`image` / `text` |
| `log_image_render_width` | int | `400` | 图片渲染分辨率宽度 |
| `log_image_display_width` | int | `320` | 图片在 Excel 中的显示宽度 |
| `log_image_max_height` | int | `520` | 图片最大高度 |
| `syslog_capture_enabled` | bool | `False` | 板端系统日志采集开关 |
| `syslog_capture_mode` | str | `"auto"` | 采集模式：`auto` / `journalctl` / `slog2info` |
| `syslog_capture_extra_args` | str | `""` | 追加参数 |
| `syslog_capture_clear` | bool | `True` | 采集前清空缓冲 |
| `syslog_capture_grep` | str | `"nvsipl_camera"` | 采集内容过滤关键字 |
| `run_prerequisites` | bool | `True` | 是否执行前置条件 |
| `auto_save` | bool | `True` | 自动保存 |
| `output_dir` | str | `"output"` | 输出目录 |

**`AIConfig`（Pydantic BaseModel）**

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `ai_enabled` | bool | `True` | AI 功能总开关 |
| `ai_protocol` | str | `"anthropic"` | 协议：`anthropic` / `openai` / `ollama` |
| `ai_api_key` | str | `""` | API 密钥 |
| `ai_model` | str | `"ts-pri-auto"` | 模型名称 |
| `ai_base_url` | str | `"https://llm.thundersoft.com"` | 接入地址 |
| `ai_auto_analyze` | bool | `False` | 自动分析所有 Fail |
| `ai_auto_parse_steps` | bool | `True` | 上传后自动 AI 识别步骤 |
| `ai_judge_mode` | str | `"always"` | 判定模式（已弃用，保留兼容） |
| `ai_cache_ttl_hours` | int | `24` | AI 缓存 TTL |
| `ai_system_prompts` | Dict[str,str] | `{}` | 各 AI 功能的自定义系统提示词 |

**`CleanupConfig`（Pydantic BaseModel）**

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `enabled` | bool | `True` | 自动清理开关 |
| `retention_days` | int | `3` | 文件保留天数 |
| `check_interval_hours` | int | `6` | 检查间隔（小时） |

#### 1.3.3 `executor_adapter.py` — 执行器适配器

**类：`ExecutorAdapter`**

核心执行引擎，将测试用例逐条下发到远端设备：

| 方法 | 说明 |
|---|---|
| `execute_all(cases)` | 批量执行所有已选用例 |
| `execute_single(case)` | 执行单条用例 |
| `stop()` | 请求停止执行 |

**执行流程（单条用例）**：

```
1. NA 识别 → 命中待写入/TBD 等关键字自动标记 NA 并跳过
2. 前置条件执行 → prerequisites 文本经 CommandParser 解析为命令序列
3. 测试步骤执行 → test_steps 文本经 CommandParser/AI 解析为命令序列
   - 每条命令通过 SSH 下发
   - 支持步骤间等待（wait_seconds）
   - 支持工作目录追踪（cd / 进入调试目录）
   - 支持多终端（PTY 交互）
4. 预期结果判定 → 仅使用 AI 判定（规则引擎已弃用）
   - ExpectedResultParser.parse 仅用于文件检查/故障测试等执行前信息
5. 结果记录 → TestResult 写入 session
6. WebSocket 推送 → 日志/进度/完成事件
```

**关键辅助函数**：

- `_nvsipl_has_real_error(output, is_fault_test)` — 判断 nvsipl 输出是否包含真正错误（排除正常统计行）
- `_has_real_fps(output)` — 判断输出中是否包含真实帧率数值
- `_parse_resolution_from_text(text)` — 从预期结果文本解析分辨率

#### 1.3.4 `ssh_manager.py` — SSH 连接管理

**类：`SSHManager`**

| 方法 | 说明 |
|---|---|
| `connect()` | 建立 SSH 连接（直连/跳板机） |
| `execute(cmd, timeout)` | 执行远程命令，返回 stdout/stderr/exit_code |
| `upload_file(local, remote)` | 上传文件到远端 |
| `download_file(remote, local)` | 从远端下载文件 |
| `close()` | 关闭连接 |
| `test_connection()` | 测试连接可用性 |

支持三种连接模式：

1. **直连**（direct）：直接连接目标主机
2. **跳板机**（jump）：通过跳板机中转
3. **sshpass 回退**：系统无 paramiko 时使用 sshpass 命令行

#### 1.3.5 `excel_handler.py` — Excel 读写

**类：`ExcelHandler`**

| 方法 | 说明 |
|---|---|
| `load(file_path)` | 解析 Excel 工作簿，返回 TestCase 列表 |
| `save_results(cases, file_path)` | 将执行结果回写到 Excel |
| `generate_bug_list(cases)` | 生成 BugList 统计页 |

解析规则：

- 按工作表遍历每行
- 根据列映射提取 case_id、test_steps、expected_result 等字段
- 自动解析 expected_keywords（用于规则引擎兼容）
- 同步读取 BugList 统计页

#### 1.3.6 `command_parser.py` — 命令解析器

**类：`CommandParser`**

将测试步骤/前置条件文本解析为可执行命令序列：

| 方法 | 说明 |
|---|---|
| `parse(text)` → List[CommandStep] | 静态方法，解析文本为命令步骤列表 |

**`CommandStep`** 数据结构：

| 字段 | 说明 |
|---|---|
| `kind` | 命令类型：`command` / `cd` / `nvsipl_input` / `manual` / `skip` / `enter_dir` |
| `command` | 实际命令文本 |
| `description` | 步骤描述 |
| `terminal` | 目标终端（默认"主终端"） |
| `wait_seconds` | 命令后等待时长 |
| `step_num` | 步骤编号 |

#### 1.3.7 `expected_parser.py` — 预期结果解析器

**类：`ExpectedResultParser`**

| 方法 | 说明 |
|---|---|
| `parse(text)` | 解析预期结果文本，提取文件检查/故障测试等执行前信息 |

注：结果判定已全面转为 AI 判定，该模块仅用于执行前信息提取。

#### 1.3.8 `config_store.py` — 配置持久化

**类：`ConfigStore`**

基于 JSON 文件的配置持久化存储：

| 方法 | 说明 |
|---|---|
| `load(name, model_class, default)` | 加载配置（不存在时返回 default） |
| `save(name, data)` | 保存配置到 JSON 文件 |

存储路径：`runtime/<session_id>/<name>.json`（per-session）或 `runtime/<name>.json`（全局）。

**类：`AIProfileStore`**

AI 配置方案管理（多套配置快照）：

| 方法 | 说明 |
|---|---|
| `list_profiles()` | 列出所有配置方案 |
| `create(name, config)` | 创建新方案 |
| `activate(id)` | 激活方案（写回 ai_config） |
| `delete(id)` | 删除方案 |

#### 1.3.9 `creator_store.py` — 用例创建项目存储

**类：`CreatorStore`**

管理用例创建向导和 ASPICE 文档项目的持久化：

存储路径：`runtime/creator_projects/<project_id>/`

| 文件 | 说明 |
|---|---|
| `project.json` | 项目完整数据（meta/aspice/cases 等） |
| `output/` | 导出文件目录 |

#### 1.3.10 `classdiag_store.py` / `seqdiag_store.py` — 代码分析项目存储

管理类图和时序图分析项目的持久化：

存储路径：

- `runtime/classdiag_projects/<project_id>/`
- `runtime/seqdiag_projects/<project_id>/`

#### 1.3.11 `history_store.py` — 执行历史存储

管理测试执行历史记录的持久化与查询。

#### 1.3.12 ASPICE 核心模块

**`arch_generator.py` — SWE.2 架构文档生成器**

| 方法 | 说明 |
|---|---|
| `_build_swe2_context(project)` | 将 project dict 构建为 Swe2Context |
| `_group_interfaces_by_file()` | 接口按 source 文件分组 |
| `generate_architecture_doc(project)` | 生成架构设计书 docx |

**`arch_sections.py` — SWE.2 规则预置层**

| 常量 | 说明 |
|---|---|
| `DEFAULT_TERMS` | 默认术语表 |
| `DEFAULT_ASSUMPTIONS` | 默认假设列表 |
| `DEFAULT_INTEGRATION_PRINCIPLES` | 默认集成原则（6 条） |
| `COMPONENT_FUNCTION_DESC` | 组件功能描述模板（A001-A009） |
| `MODULE_SHORT` | 模块简称映射 |
| `MODULE_SPLIT_POLICY` | 模块分流策略（auto_all/modified_only/manual） |
| `DEFAULT_MODULE_DIAGRAM_PLANTUML` | 默认模块图 PlantUML |

**`aspice_adapter.py` — ASPICE ↔ skill 适配器**

将 creator project 的 aspice 段转为 skill 脚本期望的六块结构。

**`aspice_validate.py` — SWE.1 校验引擎**

| 规则 | 说明 |
|---|---|
| V01-V03 | ID 格式校验 |
| V04-V06 | 枚举值校验 |
| V07-V09 | SRS 覆盖检查 |
| V10-V13 | 模板容量检查 |
| V14-V19 | 下游映射覆盖检查 |

**`template_engine.py` — docxtpl 模板引擎**

**类：`TemplateRenderer`**

| 方法 | 说明 |
|---|---|
| `render_docx(template_path, context)` | 加载模板 → 渲染 context → 返回 BytesIO |
| `plantuml_encode(text)` | PlantUML 文本编码 |
| `fetch_plantuml_png(plantuml_text)` | 下载 PlantUML PNG |
| `auto_embed_plantuml_in_context()` | 自动在 context 中嵌入 PlantUML 图片 |
| `_shrink_png_if_huge(png_data)` | PNG 降采样（最长边 ≤1600px） |

**`swe1_ingest.py` — SWE.1 需求回灌解析器**

| 函数 | 说明 |
|---|---|
| `parse_source_file(file_path)` | 解析 Excel/Word 需求表 |
| `_classify_row(row, prev_module)` | 行类型分类（header/group/main/sub/coverage） |

四种行类型：

| 类型 | 识别规则 |
|---|---|
| header | 列头行 |
| group | 分组行（缓存 current_module） |
| main/sub | OR 列含 `PREDEV_` → 入库 |
| coverage | OR=NA 且含"已覆盖" → review_status=note |

**`mapping_template_store.py` — 列映射模板存储**

存储路径：`runtime/swe1_mapping_templates/`

匹配逻辑：

1. 计算上传文件列头的 `header_fingerprint`（MD5）
2. 精确匹配已有模板 → 自动套用
3. 未命中 → `infer_mapping()` 规则推断

**`code_scanner.py` — 工程源码扫描器**

扫描 C/C++ 工程 zip，提取模块/类/函数/类型信息。

**`arch_generator_swe3.py` — SWE.3 详细设计生成器**

构建 SWE.3 详细设计书的 docxtpl 渲染上下文。

#### 1.3.13 其他核心模块

| 模块 | 职责 |
|---|---|
| `bug_list.py` | BugList 统计页生成 |
| `build_docx.py` | docx 文档构建工具 |
| `build_excel.py` | Excel 文档构建工具 |
| `case_merger.py` | 多 session 结果合并 |
| `class_uml_emit.py` | 类图 PlantUML 生成 |
| `cpp_class_indexer.py` | C++ 类索引器 |
| `cpp_class_parser.py` | C++ 类结构解析器 |
| `cpp_seq_parser.py` | C++ 函数/调用链解析器 |
| `cpp_flow_to_plantuml.py` | C++ 函数流程图 → PlantUML |
| `seq_uml_emit.py` | PlantUML 时序图生成器 |
| `config_db_parser.py` | 配置数据库解析器 |
| `config_db_scanner.py` | 配置数据库扫描器 |
| `engineering_store.py` | 工程数据存储 |
| `execution_state.py` | 执行任务状态模型 |
| `extract_excel.py` | Excel 数据提取 |
| `file_cleanup.py` | 过期文件清理 |
| `frame_sync_checker.py` | 帧同步检查器 |
| `id_chain.py` | ID 链管理 |
| `log_image.py` | 日志图片处理 |
| `remarks.py` | 备注信息构建 |
| `report_generator.py` | 测试报告生成器 |
| `req_generator.py` | 需求生成器 |
| `swe3_ai.py` | SWE.3 AI 增强 |
| `yuv2img.py` | YUV → 图片转换 |
| `zip_utils.py` | 安全 zip 解压工具 |

---

### 1.4 数据模型层（Schemas）

#### 1.4.1 `swe1_schema.py`

| 模型 | 关键字段 | 用途 |
|---|---|---|
| `SourceType` | enum: `excel` / `word` | 源文件类型 |
| `ReviewStatus` | enum: `pending` / `approved` / `rejected` / `note` | 需求审核状态 |
| `RequirementExtFields` | 扩展字段集合 | 需求扩展字段 |
| `SourceFile` | `file_id` / `file_name` / `source_type` / `rows` | 源文件信息 |
| `Requirement` | `req_id` / `title` / `description` / `source` / `status` | 需求条目 |
| `ColumnMapping` | `source_col` → `target_field` 映射 | 列映射规则 |
| `MappingTemplate` | `name` / `header_fingerprint` / `mappings` | 列映射模板 |
| `IngestPreviewRequest` | `file_id` / `mapping` / `row_types` | 回灌预览请求 |
| `IngestPreviewResponse` | `parsed_rows` / `conflicts` / `warnings` | 回灌预览响应 |
| `IngestConfirmRequest` | `file_id` / `conflict_resolution` | 回灌确认请求 |
| `IngestConfirmResponse` | `imported` / `skipped` / `conflicts` | 回灌确认响应 |
| `ParsedRow` | 解析后的行数据 | 回灌中间结果 |

#### 1.4.2 `swe2_schema.py`

| 模型 | 关键字段 | 用途 |
|---|---|---|
| `Swe2Context` | 完整渲染上下文 | SWE.2 docx 模板变量 |
| `Component` | `id` / `name` / `model` / `enabled` / `security_mode` / `interfaces` / `classes` | 组件定义 |
| `InterfaceItem` | `name` / `group_first` / `group_size` / `group_name` | 接口条目 |
| `SoftwareDesign` | 软件设计信息 | 软件设计段 |
| `Integration` | `principles_by_key` (computed) | 集成原则 |
| `Resources` | 资源定义 | 资源段 |

**组件 enabled 开关**：`false` 时整个 §4.X（标题+表+时序图）都不渲染。

**Camera Security 三态**：

| 值 | 行为 |
|---|---|
| `full` | 全章渲染 |
| `manual_brief` | 仅功能描述+安全目标 |
| `disabled` | 整章不出 |

#### 1.4.3 `swe3_schema.py`

| 模型 | 关键字段 | 用途 |
|---|---|---|
| `Swe3Data` | 完整 SWE.3 数据 | 详细设计数据根 |
| `Swe3Module` | 模块信息 | 模块定义 |
| `Swe3Class` | 类信息 | 类定义 |
| `Swe3Function` | 函数信息 | 函数定义 |

---

### 1.5 AI 能力层

#### 1.5.1 `service.py` — AI 服务

**类：`AIService`**

| 方法 | 说明 |
|---|---|
| `judge(case, actual_output)` | AI 判定用例结果 |
| `analyze_failure(case, actual_output)` | AI 分析失败原因 |
| `analyze_failure_stream(case, actual_output)` | SSE 流式分析 |
| `parse_steps(step_text, context)` | AI 解析测试步骤 |
| `generate_report(cases)` | 生成测试报告 |
| `generate_func_briefs(components)` | AI 补全函数简介 |
| `augment_function_details(functions)` | AI 增强函数详情 |
| `test_connection()` | 测试 AI 连接 |
| `list_models()` | 查询可用模型 |

**设计特点**：

- 按协议区分 Provider（anthropic/openai/ollama）
- AICache 缓存（key = sha1(输入)），避免重复调用
- 批量处理按 batch_size 切片，防止长回复截断
- 单批失败不影响其他批

#### 1.5.2 `providers/` — AI 协议适配

| Provider | 协议 | 说明 |
|---|---|---|
| `anthropic_provider.py` | Anthropic Messages API | Claude 系列模型 |
| `openai_provider.py` | OpenAI Chat Completions API | GPT / DGX Spark 兼容 |
| `ollama_provider.py` | Ollama API | 本地 Ollama 模型 |
| `base.py` | 抽象基类 | Provider 接口定义 |

#### 1.5.3 `prompts/` — 提示词管理

| 文件 | 功能标识 | 说明 |
|---|---|---|
| `judge.py` | `judge` | 结果判定提示词 |
| `analyze.py` | `analyze` | 失败分析提示词 |
| `report.py` | `report` | 测试报告提示词 |
| `step_parse.py` | `parse_steps` | 步骤解析提示词 |
| `func_brief.py` | `func_brief` | 函数简介提示词 |
| `swe3_augment.py` | `swe3_augment` | SWE.3 增强提示词 |
| `bug_description.py` | `bug_description` | Bug 描述提示词 |
| `req_parse.py` | `req_parse` | 需求解析提示词 |
| `statistics.py` | `statistics` | 统计提示词 |
| `arch_design.py` | `arch_design` | 架构设计提示词 |
| `registry.py` | — | 提示词注册表（元数据管理） |

#### 1.5.4 `cache.py` — AI 缓存

**类：`AICache`**

基于文件系统的 AI 响应缓存：

- key = sha1(输入内容)
- TTL 可配置（默认 24 小时）
- 缓存目录：`runtime/ai_cache/`

---

### 1.6 WebSocket 层

#### 1.6.1 `manager.py` — 全局 WebSocket 管理器（已弃用）

旧版全局 ConnectionManager，已被 `SessionWSManager` 替代。

#### 1.6.2 `session_ws_manager.py` — per-session WebSocket 管理器

**类：`SessionWSManager`**

| 方法 | 说明 |
|---|---|
| `send_log(message, level)` | 推送日志消息 |
| `send_progress(current, total, case_id, case_key, message)` | 推送进度消息 |
| `send_case_complete(case_key, status, reason, ...)` | 推送用例完成消息 |
| `send_execution_finished(results)` | 推送执行完成消息 |
| `send_execution_stopped(message)` | 推送执行停止消息 |
| `request_manual_confirm(step_desc)` | 请求人工确认 |
| `handle_confirm_response(data)` | 处理确认响应 |

消息类型：

| type | 方向 | 说明 |
|---|---|---|
| `log` | 服务端→客户端 | 日志消息 |
| `progress` | 服务端→客户端 | 执行进度 |
| `case_complete` | 服务端→客户端 | 用例执行完成 |
| `execution_finished` | 服务端→客户端 | 全部执行完成 |
| `execution_stopped` | 服务端→客户端 | 执行已停止 |
| `manual_confirm_request` | 服务端→客户端 | 请求人工确认 |
| `confirm_response` | 客户端→服务端 | 确认响应 |
| `stop_execution` | 客户端→服务端 | 请求停止执行 |

---

## 2. 前端详细设计

### 2.1 应用入口：`App.tsx`

定义路由与布局容器：

| 路由 | 组件 | 说明 |
|---|---|---|
| `/` | `Dashboard` | 执行管理主工作台 |
| `/workspace` | `WorkspaceConfigPage` | 工作区配置 |
| `/ai-config` | `AIConfigPage` | AI 功能配置 |
| `/prompt-config` | `PromptConfigPage` | 提示词配置 |
| `/history` | `ExecutionHistoryPage` | 执行历史 |
| `/reports` | `ReportsPage` | 测试报告 |
| `/casegen` | `CaseGenPage` | 用例生成向导 |
| `/classdiag` | `classdiag/ProjectsPage` | 类图分析项目列表 |
| `/classdiag/:id` | `classdiag/WorkspacePage` | 类图分析工作区 |
| `/seqdiag` | `seqdiag/ProjectsPage` | 时序图项目列表 |
| `/seqdiag/:id` | `seqdiag/WorkspacePage` | 时序图工作区 |
| `/flowchart` | `flowchart/FlowchartPage` | 函数流程图 |
| `/creator` | `creator/...` | 用例创建向导 |
| `/aspice` | `aspice/ASPICEWizard` | ASPICE 文档向导 |

### 2.2 布局组件：`Layout.tsx`

提供顶部 Tab 导航 + 左侧 Sider 导航的统一布局。

顶部 Tab：

| Tab | 说明 |
|---|---|
| 执行管理 | Dashboard 主工作台 |
| 代码分析 | 类图/时序图/流程图 |
| 用例创建 | 用例生成向导 |
| ASPICE | ASPICE 文档向导 |
| 执行历史 | 历史记录查看 |
| 测试报告 | 报告管理 |
| 配置 | SSH/工作区/AI/提示词 |

### 2.3 主工作台：`Dashboard.tsx`

核心功能模块：

| 模块 | 说明 |
|---|---|
| Excel 上传 | 文件选择 + 解析 + 用例加载 |
| 用例表格 | 展示/选择/编辑用例（支持列显示配置） |
| SSH 配置 | 连接配置表单 + 测试连接 |
| 执行控制 | 启动/停止执行 |
| 进度显示 | 实时进度条 + 当前用例 |
| 日志面板 | 实时日志流 |
| 人工确认 | 确认/取消交互 |
| 结果下载 | 下载结果 Excel |
| BugList | Bug 统计页展示 |
| AI 分析 | 失败分析 + 报告生成 |

### 2.4 ASPICE 文档向导

#### 2.4.1 `ASPICEWizard` — 向导容器

三步骤向导：SWE.1 → SWE.2 → SWE.3

#### 2.4.2 `Swe1Step.tsx` — 需求分析

子组件：

| 组件 | 说明 |
|---|---|
| `SourcesPanel` | 源文件管理（上传/列表/删除） |
| `IngestWizard` | 回灌向导（列映射 → 行类型 → 冲突处理 → 确认） |
| `RequirementsTable` | 需求台账（表格展示/编辑/校验） |
| `TemplatesPanel` | 列映射模板管理 |

#### 2.4.3 `Swe2Step.tsx` — 架构设计

子组件：

| 组件 | 说明 |
|---|---|
| `OverviewEditor` | 概述信息编辑 |
| `ModuleEditor` | 模块编辑（9 组件 A001-A009） |
| `SoftwareDesignEditor` | 软件设计编辑 |
| `DocMetaEditor` | 文档元信息编辑 |
| `IntegrationEditor` | 集成原则编辑 |
| `ResourcesEditor` | 资源管理 |
| `InterfacePickerFromScan` | 从扫描结果选择接口 |
| `PaginatedTable` | 分页表格 |

#### 2.4.4 `Swe3Step.tsx` — 详细设计

子组件：

| 组件 | 说明 |
|---|---|
| `EngineeringUploadPanel` | 工程上传 |
| `EngineeringScanner` | 工程扫描 |
| `ModuleDesignEditor` | 模块设计编辑 |
| `ModuleCompositionEditor` | 模块组成编辑 |
| `ModulePathConfigEditor` | 模块路径配置 |
| `FunctionDetailEditor` | 函数详情编辑 |
| `FunctionStatusTable` | 功能状态表格 |
| `FocusFunctionsPicker` | 聚焦函数选择 |
| `CommonDefsEditor` | 公共定义编辑 |

### 2.5 用例创建向导

| 组件 | 说明 |
|---|---|
| `BasicInfoStep` | 基本信息（A1-A5 问答） |
| `PlatformStep` | 平台配置选择 |
| `SensorStep` | 传感器参数选择 |
| `FunctionalGenStep` | 功能测试用例生成 |
| `StressGenStep` | 压力测试用例生成 |
| `StabilityGenStep` | 稳定性测试用例生成 |
| `CasePreviewStep` | 用例预览 |
| `DraftBox` | 草稿箱 |

### 2.6 状态管理层

#### 2.6.1 `useStore.ts` — 全局状态

基于 Zustand 的全局状态管理：

| 状态 | 类型 | 说明 |
|---|---|---|
| `testCases` | TestCase[] | 当前用例列表 |
| `visibleCaseColumnKeys` | string[] | 表格显示列配置 |
| `sheets` | string[] | 工作表列表 |
| `currentSheet` | string | 当前工作表 |
| `bugSheet` | string | BugList 页签名 |
| `bugList` | BugListItem[] | BugList 数据 |
| `logs` | LogEntry[] | 日志列表 |
| `progress` | ExecutionProgress \| null | 执行进度 |
| `isRunning` | boolean | 是否执行中 |
| `isConnected` | boolean | WebSocket 连接状态 |
| `confirmRequest` | ConfirmRequest \| null | 人工确认请求 |
| `sshConfig` | SSHConfig \| null | SSH 配置 |
| `sshStatus` | SSHStatus \| null | SSH 状态 |
| `workspace` | WorkspaceConfig \| null | 工作区配置 |
| `aiParseProgress` | AIParseProgress \| null | AI 步骤解析进度 |
| `aiParsedCases` | Set<string> | 已解析用例集合 |

**持久化策略**：

- `visibleCaseColumnKeys` → localStorage（跨 session 共享）
- 用例快照 → sessionStorage（per-session，key = `automatedTest.cases.${sessionId}`）
- 超出 localStorage 配额（>2MB）时静默放弃

#### 2.6.2 `useAspiceStore.ts` — ASPICE 状态

基于 Zustand 的 ASPICE 专用状态管理，包含 SWE.1/2/3 所有数据字段和 setter。

### 2.7 API 通信层

#### 2.7.1 `axios.ts` — 基础配置

- baseURL: `/api`
- timeout: 30000ms
- 自动注入 `X-Session-ID` header（通过 axios interceptor）

**Session ID 管理**：

```typescript
// 使用 sessionStorage（每个标签页独立）
const SESSION_KEY = 'test_runner_session_id'
function getSessionId(): string {
    let id = sessionStorage.getItem(SESSION_KEY)
    if (!id) {
        id = generateHexId()  // 32 位十六进制
        sessionStorage.setItem(SESSION_KEY, id)
    }
    return id
}
```

特性：
- 刷新页面（F5）→ 保持同一 session
- 新开标签页 → 分配新 session
- 关闭标签页 → 自动清除

#### 2.7.2 业务 API 模块

| 文件 | 职责 |
|---|---|
| `axios.ts` | 执行管理 API（上传/用例/SSH/执行/AI/清理） |
| `aspiceApi.ts` | ASPICE 文档 API |
| `classDiagApi.ts` | 类图分析 API |
| `seqDiagApi.ts` | 时序图 API |
| `casegenApi.ts` | 用例生成 API |
| `historyApi.ts` | 执行历史 API |

### 2.8 类型定义层

#### 2.8.1 `types/index.ts` — 基础类型

| 类型 | 说明 |
|---|---|
| `TestCase` | 测试用例 |
| `SSHConfig` / `SSHStatus` | SSH 配置/状态 |
| `WorkspaceConfig` | 工作区配置 |
| `ExecutionTask` | 执行任务状态 |
| `LogEntry` | 日志条目 |
| `ExecutionProgress` | 执行进度 |
| `ConfirmRequest` | 人工确认请求 |
| `TestResultSummary` | 测试结果摘要 |
| `BugListItem` | BugList 条目 |
| `WsBaseMessage` / `WsLogMessage` / `WsProgressMessage` 等 | WebSocket 消息类型 |

#### 2.8.2 `types/aspice.ts` — ASPICE 类型

SWE.1/2/3 完整的 TypeScript 类型定义，与后端 Pydantic 模型一一对应。

#### 2.8.3 `types/classDiag.ts` / `types/seqDiag.ts` — 代码分析类型

类图和时序图分析的 TypeScript 类型定义。

### 2.9 Hooks

| Hook | 说明 |
|---|---|
| `useWebSocket.ts` | WebSocket 连接管理（自动重连、消息分发） |
| `useCaseImageAvailability.ts` | 用例图片可用性检测 |

### 2.10 工具函数

| 文件 | 说明 |
|---|---|
| `utils/casegen/functionalCases.ts` | 功能测试用例生成逻辑 |
| `utils/casegen/storage.ts` | 用例生成数据持久化 |
| `utils/casegen/sensors.ts` | 传感器信息处理 |
| `utils/workspaceStorage.ts` | 工作区数据本地存储 |

---

## 3. 接口契约

### 3.1 前后端模型对照

| 后端模型 | 前端类型 | 文件 |
|---|---|---|
| `TestCase` (dataclass) | `TestCase` (interface) | `test_case.py` / `types/index.ts` |
| `SSHConfig` (Pydantic) | `SSHConfig` (interface) | `test_case.py` / `types/index.ts` |
| `WorkspaceConfig` (Pydantic) | `WorkspaceConfig` (interface) | `test_case.py` / `types/index.ts` |
| `AIConfig` (Pydantic) | `AIConfig` (interface) | `test_case.py` / `types/index.ts` |
| `swe1_schema.*` | `types/aspice.ts` 对应类型 | `schemas/aspice/` / `types/aspice.ts` |
| `swe2_schema.*` | `types/aspice.ts` 对应类型 | `schemas/aspice/` / `types/aspice.ts` |
| `swe3_schema.*` | `types/aspice.ts` 对应类型 | `schemas/aspice/` / `types/aspice.ts` |

### 3.2 WebSocket 消息协议

**服务端 → 客户端**

```typescript
// 日志
{ type: "log", level: "info"|"warning"|"error", message: string, timestamp: number }

// 进度
{ type: "progress", current: number, total: number, case_id: string, case_key?: string, message?: string }

// 用例完成
{ type: "case_complete", case_id: string, case_key?: string, status: string, reason: string, actual_result?: string, log_file?: string, remarks?: string }

// 执行完成
{ type: "execution_finished", results: TestResultSummary[] }

// 执行停止
{ type: "execution_stopped", message: string }

// 人工确认请求
{ type: "manual_confirm_request", confirm_id: string, step_desc: string, timeout: number }
```

**客户端 → 服务端**

```typescript
// 确认响应
{ type: "confirm_response", confirm_id: string, result: boolean }

// 停止执行
{ type: "stop_execution" }
```

---

## 4. 存储设计

### 4.1 目录结构

```
test_runner_web/
├── uploads/                    # 上传文件
│   ├── <session_id>/          # per-session 上传目录
│   └── merge/                 # 合并结果临时目录
├── logs/                       # 执行日志
│   └── <session_id>/          # per-session 日志目录
├── output/                     # 输出文件
├── runtime/                    # 运行时数据
│   ├── <session_id>/          # per-session 配置
│   │   ├── ssh_config.json
│   │   ├── workspace.json
│   │   └── ai_config.json
│   ├── ai_config.json         # 全局 AI 配置
│   ├── ai_profiles.json       # AI 配置方案
│   ├── cleanup_config.json    # 文件清理配置
│   ├── ai_cache/              # AI 响应缓存
│   ├── creator_projects/      # 用例创建/ASPICE 项目
│   │   └── <project_id>/
│   │       ├── project.json
│   │       └── output/
│   ├── classdiag_projects/    # 类图分析项目
│   │   └── <project_id>/
│   ├── seqdiag_projects/      # 时序图项目
│   │   └── <project_id>/
│   └── swe1_mapping_templates/  # SWE.1 列映射模板
│       └── <fingerprint>.json
```

### 4.2 持久化策略

| 数据类型 | 存储方式 | 生命周期 |
|---|---|---|
| SSH 配置 | JSON 文件（per-session） | 跨请求持久化 |
| 工作区配置 | JSON 文件（per-session） | 跨请求持久化 |
| AI 配置 | JSON 文件（全局） | 跨请求持久化 |
| AI 配置方案 | JSON 文件（全局） | 跨请求持久化 |
| 用例数据 | 内存（per-session） | session 内有效 |
| ASPICE 项目 | JSON 文件 | 持久化 |
| 代码分析项目 | JSON 文件 | 持久化 |
| 列映射模板 | JSON 文件 | 跨项目持久化 |
| AI 缓存 | 文件缓存 | TTL 过期自动清理 |
| 上传文件 | 文件系统 | 按配置自动清理 |
| 执行日志 | 文件系统 | 按配置自动清理 |

### 4.3 前端持久化

| 数据 | 存储方式 | 说明 |
|---|---|---|
| Session ID | sessionStorage | per-tab，刷新保持 |
| 显示列配置 | localStorage | 跨 tab 共享 |
| 用例快照 | sessionStorage | per-tab，>2MB 静默放弃 |
| ASPICE 数据 | Zustand in-memory | 刷新丢失（可从后端重新加载） |

---

## 5. 安全设计

### 5.1 文件上传安全

- 使用 `os.path.basename()` 清洗文件名，避免路径穿越
- 上传文件类型校验（Excel: xlsx/xls, Word: docx）
- zip 文件安全解压（`zip_utils.py` 防止 zip bomb）

### 5.2 Session 安全

- Session ID 格式校验（32 位十六进制正则）
- per-session 目录隔离
- WebSocket 连接强制 session_id 参数

### 5.3 SSH 凭证

- 密码仅存于内存（SessionState）和 per-session JSON 文件
- 不写入日志
- 前端不持久化密码字段

### 5.4 AI API Key

- 存储于 `runtime/ai_config.json`（全局）
- 不在前端持久化
- 日志中脱敏处理

---

## 6. 术语表

参见 `ARCHITECTURE.md` §16 术语表。

---

## 7. 与架构文档的映射关系

| 本文档章节 | 对应架构文档章节 |
|---|---|
| 1.1 main.py | ARCHITECTURE §4.1 |
| 1.2 API 路由层 | ARCHITECTURE §4.2-4.9 |
| 1.3 核心业务层 | ARCHITECTURE §4 各子节 |
| 1.4 数据模型层 | ARCHITECTURE §4.9.2 |
| 1.5 AI 能力层 | ARCHITECTURE §4.9.6 |
| 1.6 WebSocket 层 | ARCHITECTURE §4.2 |
| 2.1-2.10 前端 | ARCHITECTURE §5 |
| 3. 接口契约 | ARCHITECTURE §3 / §9 |
| 4. 存储设计 | ARCHITECTURE §9 / §10 |
| 5. 安全设计 | ARCHITECTURE §10.4 |
