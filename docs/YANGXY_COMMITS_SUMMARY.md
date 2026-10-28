# Yangxy 提交记录总结（2026-10-19 ~ 2026-10-27）

> 统计口径：`git log --all --author='Yangxy'`，共 **21 个提交**，全部位于 master 主线。
> 时间范围：2026-10-19 ~ 2026-10-27，涉及 **36 个文件，+4739 / -500 行**。
> 提交类型：feat 11 个、fix 6 个、refactor 1 个、docs 1 个、ui 1 个、revert 1 个。

## 一、总体概览

这段时间的改动集中在四条主线：

1. **AI 判定与分析**：判定优先级调整、流式输出、强制刷新、多套配置方案、协议抽象。
2. **用例执行**：单用例日志、远端命令预览、驱动库路径注入、细粒度进度、WebSocket 重连。
3. **Excel 导入导出**：结果数据回填、实际结果/备注列写入规则统一。
4. **前端体验**：表格显示、显示列配置、用例与工作区配置的本地持久化。

按日期分布：

| 日期 | 提交数 | 主要内容 |
| --- | --- | --- |
| 2026-10-19 | 1 | 表格文本换行修复 |
| 2026-10-21 | 7 | AI 判定优先、日志查看、命令预览、状态卡死修复、配置持久化 |
| 2026-10-22 | 8 | 驱动库路径、执行进度、AI 流式输出与配置方案、WebSocket 重连、Excel 结果列 |
| 2026-10-27 | 5 | AI 判定数据集成、Excel 结果回填、备注/日志展示、一次 UI 回滚 |

---

## 二、新增功能

### 1. AI 判定与分析

#### 1.1 AI 判定优先策略（6f5aa31）
- AI 明确返回 Pass/Fail 时直接采用判定结果，不再按置信度回退到规则引擎。
- 仅在 AI 不可用或返回异常时回退规则引擎。
- 移除故障测试关键字 100% 匹配的特殊保护逻辑。
- 实际结果栏优先展示 AI 判定依据与证据；Review 状态显示「待确认」。

#### 1.2 AI 判定信息落库与导出（2f21996）
- `TestCase` 新增 AI 判定字段：`ai_judged`、`ai_status`、`ai_confidence`、`ai_reason`、`ai_evidence`。
- `ExecutorAdapter` 在测试结果生成后，将 AI 判定信息同步到 `TestCase`。
- Excel 导出时实际结果列只显示状态，备注列展示 AI 判定详情与执行日志。

#### 1.3 AI 失败分析流式输出（7b30753）
- 新增 `POST /ai/analyze/stream` SSE 接口，逐块推送 `delta` / `thinking` / `done` / `error`。
- Anthropic、OpenAI 使用原生流式，Ollama 使用 NDJSON；流式不可用时自动退化为一次性调用。
- 思考型模型的 reasoning 增量单独透传，前端抽屉实时展示思考过程与生成内容；切换用例或关闭抽屉时中断旧流。
- 提高分析类调用上限（judge 1024→4096、analyze 1536→8192、步骤解析 2048→8192），超时放宽到 180s。
- JSON 解析增强：支持嵌套括号配对与截断自动补齐；解析失败返回具体错误，批量分析返回 `errors` 列表。
- AI 判定依据只保留判定状态与理由，不再追加关键输出行。

#### 1.4 跳过缓存强制重新分析（575144c）
- AI 失败分析接口新增 `force` 参数，`force=True` 时跳过缓存重新调用。
- 抽屉中的「重新分析」「重试」按钮均强制刷新，避免一直看到旧结论。

#### 1.5 多套 AI 配置方案与模型列表（b3a2af8）
- 新增 `AIProfileStore`，AI 配置以「方案」形式保存与切换；激活方案时快照写回 `ai_config.json`，其余业务代码无需感知方案存在。
- 新增 `/ai/profiles` 增删查及激活接口，列表只返回掩码后的 API Key。
- 保存 AI 配置前要求存在激活方案，避免产生无法编辑的游离配置。
- 新增 `/ai/models` 接口，按协议查询 Anthropic / OpenAI / Ollama 可用模型列表；失败时返回空列表并回退手动输入。
- 前端配置面板支持方案切换/新增/删除、模型列表自动拉取与刷新，空密钥不再回填到表单。

#### 1.6 AI 配置按协议抽象（026fbce）
- `ai_provider` 改为 `ai_protocol`，只区分 `anthropic` / `openai` / `ollama`，不再区分具体供应商。
- 旧配置自动迁移：`claude`→`anthropic`、`dgx_spark`/`openai`→`openai`、`ollama`→`ollama`。
- 删除 DGX Spark 专用分支与界面预设，供应商由 `base_url + model + api_key` 决定。
- `ClaudeProvider` 更名为 `AnthropicProvider`，同步前端类型、README 与架构文档。

### 2. 用例执行与日志

#### 2.1 单用例执行日志（6f5aa31）
- 每个用例保存独立日志文件，覆盖 NA、前置条件失败、执行异常等场景。
- 新增 `GET /logs/content` 接口，路径限制在 `logs/` 目录内，避免越权读取。
- WebSocket 推送 `log_file` 字段。
- 前端新增 `CaseLogModal`，Dashboard 与历史详情页均可查看单用例执行日志。

#### 2.2 远端命令预览（f28b5ab）
- 新增 `POST /cases/preview-commands`，复用真实执行解析流程（NA 判定、规则解析、AI 缓存替换、nvsipl 交互合并、执行模式判定、命令改写）。
- 预览过程不连接 SSH、不执行命令、不触发实时 AI 调用，也不展示 sudo 密码。
- `ai_parse_steps` 解析结果写入会话缓存 `ai_parsed_steps`，供执行与预览复用。
- 前端新增 `CommandPreviewModal`：按用例展示执行模式、前置条件、步骤命令、改写说明与不会自动执行的步骤，支持复制命令。
- Dashboard 工具栏新增「查看执行命令」按钮，测试步骤列新增预览入口。

#### 2.3 驱动库路径自动注入（2e1298a）
- 工作区配置新增 `driver_path` 字段（前后端类型 + 用户手册）。
- 执行器在普通步骤、持久 Shell、前置条件、nvsipl 等命令路径前注入 `export LD_LIBRARY_PATH`，使板端优先加载配置目录下的驱动库。
- 未配置时保持原有行为不变。

#### 2.4 执行阶段细粒度进度（587a085）
- 进度条新增 `message` 字段，推送「正在执行命令 (2/5)」「正在 AI 分析判定结果」等细阶段。
- 前端在进度条上方实时展示，过长省略并可悬停查看。
- 执行日志回显输入命令（以 `$ ` 开头），判定与证据提取前自动剔除回显，命令仅保留在日志文件中。

#### 2.5 WebSocket 断线自动重连（2ea8cf3）
- 断线后按 1s → 2s → 4s → … → 15s 指数退避重连，重连成功后重置计数。
- 正常关闭（code 1000/1001）不触发重连，组件卸载时清理定时器。
- 日志中显示重连尝试次数。
- 解决后端重启后 WebSocket 一直连接不上的问题。

### 3. Excel 导入导出

#### 3.1 上传用例时回填历史结果（ecf3277）
- 加载 Excel 时读取结果列（实际结果 / Bug / 备注 / 版本 / 测试人 / 日期）并回填到 `TestCase`。
- 从实际结果列首行解析已有状态（PASS/FAIL 等），覆盖默认的 NT。
- 前端表格在上传、重传用例时可直接展示历史执行结果。

#### 3.2 结果列写入规则统一（f157de5 / 6277d24 / cf1ae31 / 4a0f91a）
经过几轮调整，最终规则为：

| 列 | 写入内容 |
| --- | --- |
| 实际结果 | 仅写状态（Pass / Fail / NT / BLOCK / NA / Review），并按状态填充底色 |
| Bug | 留空 |
| 备注 | AI 判定信息 + `--- 执行日志 ---` + 日志全文（无 AI 判定时只写日志，两者都没有时回退原备注） |

- 新增 `backend/app/core/remarks.py` 统一构建备注，导出与前端列表、WebSocket、执行历史共用同一份内容。
- 新增 `frontend/src/utils/remarkDisplay.ts` 解析备注：实际结果栏展示 AI 判定状态与依据，格式不符合约定时原样展示备注；备注弹窗优先展示备注中的日志，缺失时再读取日志文件。

### 4. 前端体验与本地持久化

#### 4.1 表格显示列配置（6f5aa31）
- Dashboard 新增「显示列」配置，可勾选可选列；列全部隐藏时自动取消横向滚动。

#### 4.2 用例数据与显示列持久化（aaeb842）
- 用例快照按 session 存入 localStorage，刷新后恢复用例与表页。
- 显示列配置持久化，非法列名自动过滤。
- 数据超配额或隐私模式下静默降级，不影响主流程。

#### 4.3 工作区配置持久化（587a085）
- 工作区配置保存到 localStorage，刷新 / 新标签页 / 重启浏览器后自动恢复。
- 同步回后端供执行使用（`utils/workspaceStorage.ts`）。

#### 4.4 备注与执行日志展示（4a0f91a）
- 实际结果栏解析备注中的 AI 判定内容；格式不符合约定时原样显示备注。
- 备注弹窗改为执行日志弹窗，优先展示备注中的执行日志，缺失时读取日志文件。
- 统一备注构建逻辑，随用例列表、WebSocket 和历史记录返回。
- 执行历史库自动迁移 `remarks` 列，旧记录兼容「判定依据 + 日志」兜底。

### 5. 文档与规则说明

- 新增 `docs/TEST_CASE_WRITING_RULES.md`（562 行），说明测试步骤编写规则（dd31652）。
- 新增 `TestStepRulesModal`，在 Dashboard 内直接查看与 CommandParser 行为一致的步骤规则（f28b5ab）。
- 同步更新 README、`docs/ARCHITECTURE.md`、`docs/user-guide.html`。

---

## 三、Bug 修复

| # | 问题现象 | 原因 / 处理 | 提交 |
| --- | --- | --- | --- |
| 1 | 测试用例表格文本被截断、长内容显示不全 | 表格单元格未自动换行；补充样式并让表格完整展示文本 | 8a0376c |
| 2 | 一轮执行结束后无法再次执行，界面一直显示运行中 | 后台任务已为终态但 `is_running` 未复位；增加终态自动清理，并在 `finally` 中先复位运行态再同步结果 | 6858aa4 |
| 3 | 后端重启后 WebSocket 一直连接不上，页面不刷新数据 | 前端没有重连逻辑；增加指数退避自动重连 | 2ea8cf3 |
| 4 | 上传/重传用例后，前端看不到 Excel 中已有的执行结果 | 加载 Excel 时没有回填结果列；补齐实际结果、Bug、备注、版本、测试人、日期的回填，并从实际结果首行解析状态 | ecf3277 |
| 5 | Excel 实际结果列内容不符合预期（日志摘要、证据、备注混写） | 写入规则多次调整；最终明确「实际结果=状态、Bug=空、备注=AI 判定+完整日志」，并抽出统一构建逻辑 | f157de5 / 6277d24 / cf1ae31 / 4a0f91a |
| 6 | 旧执行历史记录缺少备注内容，详情页展示不一致 | 历史库没有 `remarks` 列；启动时自动迁移，旧记录用「判定依据 + 日志」兜底 | 4a0f91a |
| 7 | 点击「重新分析」仍返回旧结论 | AI 分析命中缓存；接口增加 `force` 参数，抽屉按钮强制刷新 | 575144c |
| 8 | AI 判定/证据提取被日志中的命令回显干扰 | 日志回显 `$ 命令` 被当作输出；判定与证据提取前剔除回显，命令只留在日志文件 | 587a085 |
| 9 | AI 返回较长 JSON 时解析失败或内容被截断 | 原解析不支持嵌套括号与截断内容；增强括号配对、自动补齐，并提高 max_tokens 与超时 | 7b30753 |

> 说明：8d15579（Dashboard 新增备注列、日志按钮移至备注栏）随后被 509f217 整体 revert，两者相互抵消，最终由 4a0f91a 以另一种方式实现（执行日志弹窗 + 备注解析），不计入净变更。

---

## 四、完整提交清单

| 日期 | 提交 | 类型 | 说明 |
| --- | --- | --- | --- |
| 10-19 | `8a0376c` | fix | 测试用例表格完整显示文本并自动换行 |
| 10-21 | `6f5aa31` | feat | AI 判定优先 + 用例执行日志查看 + 表格显示列配置 |
| 10-21 | `026fbce` | refactor | AI 配置改为只区分协议，不区分供应商 |
| 10-21 | `f28b5ab` | feat | 远端命令预览 + 测试步骤编写规则说明 |
| 10-21 | `6858aa4` | fix | 修复执行状态卡死并简化 AI 判定依据展示 |
| 10-21 | `dd31652` | docs | 新增测试用例编写规则说明 |
| 10-21 | `575144c` | feat | AI 支持跳过缓存强制重新分析 |
| 10-21 | `aaeb842` | feat | 用例数据与显示列配置本地持久化 |
| 10-22 | `2e1298a` | feat | 配置驱动存放路径并自动设置 LD_LIBRARY_PATH |
| 10-22 | `587a085` | feat | 执行阶段细粒度进度提示 + 工作区配置本地持久化 |
| 10-22 | `7b30753` | feat | AI 失败分析支持流式输出 |
| 10-22 | `b3a2af8` | feat | 多套 AI 配置方案与模型列表自动获取 |
| 10-22 | `f157de5` | fix | Excel 实际结果栏追加执行日志摘要 |
| 10-22 | `2ea8cf3` | feat | WebSocket 断线自动重连（指数退避） |
| 10-22 | `6277d24` | fix | 修正 Excel 结果列写入逻辑 |
| 10-22 | `cf1ae31` | fix | Excel 实际结果列改为 status + 证据摘要 |
| 10-27 | `2f21996` | feat | 集成 AI 自动化判定功能 |
| 10-27 | `ecf3277` | fix | 上传用例时回填已执行结果到前端表格 |
| 10-27 | `8d15579` | ui | Dashboard 新增备注列并将日志弹窗按钮移至备注栏（后回滚） |
| 10-27 | `509f217` | revert | 回滚 8d15579 |
| 10-27 | `4a0f91a` | feat | 实际结果栏展示 AI 判定并恢复执行日志弹窗 |

---

## 五、主要涉及文件

- 后端 AI：`backend/app/ai/service.py`、`backend/app/ai/providers/*`、`backend/app/ai/model_listing.py`
- 后端执行：`backend/app/core/executor_adapter.py`、`backend/app/core/test_case.py`、`backend/app/core/remarks.py`
- 后端 Excel / 历史：`backend/app/core/excel_handler.py`、`backend/app/core/history_store.py`
- 后端接口与推送：`backend/app/api/routes.py`、`backend/app/websocket/*`
- 前端页面与组件：`frontend/src/pages/Dashboard.tsx`、`frontend/src/pages/RunDetailPage.tsx`、`frontend/src/pages/WorkspaceConfigPage.tsx`、`frontend/src/components/AIConfigPanel.tsx`、`AIAnalysisDrawer.tsx`、`CaseLogModal.tsx`、`CommandPreviewModal.tsx`、`TestStepRulesModal.tsx`
- 前端状态与工具：`frontend/src/stores/useStore.ts`、`frontend/src/hooks/useWebSocket.ts`、`frontend/src/utils/remarkDisplay.ts`、`frontend/src/utils/workspaceStorage.ts`
- 文档：`docs/TEST_CASE_WRITING_RULES.md`、`README.md`、`docs/ARCHITECTURE.md`、`docs/user-guide.html`
