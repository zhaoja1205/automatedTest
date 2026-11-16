# 变更日志 (CHANGELOG)

本文件记录 `test_runner_web` 项目每个版本的功能变更、修复和改进。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/) `MAJOR.MINOR.PATCH`。

---

## [未发布] — 2026-11-16 — 步骤解析：终端字样在任意位置均可识别

### 变更 — 终端识别更宽松

- **`backend/app/core/command_parser.py`** — 终端标签不再要求写在步骤开头、也不再要求带冒号：步骤中任意位置出现「终端A」「终端B」「终端2」等字样即归属该终端；支持 `[终端B]`、`（终端B）` 及命令末尾的标注（`./tool --flag（终端B）`）；同一步骤出现多个终端字样时按出现位置切分，各管其后的命令；「另一个终端」「辅终端」等旧写法仍兼容；标签只取单个字母/数字/中文数字，避免把「终端上」「终端中」等普通词误判成终端。新增 `find_terminal_mentions` / `_split_segments_by_terminal`，等待与交互输入步骤同样带上标注的终端；提取正文时去掉终端标注及「执行」「运行」等引导语
- **`backend/app/ai/prompts/step_parse.py`** — 步骤解析 prompt 同步放宽：不要求终端字样位于开头或带冒号，一个步骤内多个终端字样时命令分别归属各自终端
- **`backend/tests/test_terminal_parse.py`** — 新增任意位置识别、无冒号、命令后标注、单步骤多终端、等待/交互输入带终端、普通词不误判等用例

---

## [未发布] — 2026-11-16 — 日志草稿箱 / 备注列统一按终端存储日志

### 变更 — 统一日志存储方式

- **`backend/app/core/terminal_log.py`（新增）** — 集中定义按终端日志的统一读写格式：`read_terminal_logs`（读取 `<基名>.terminals.json` / `<基名>.<终端>.term.log`）、`format_terminal_log`、`parse_terminal_log`、`load_terminal_log_text`；`log_image.py` 改为复用该模块，不再各写一份读取逻辑
- **`backend/app/api/routes.py`** — `GET /logs/terminals` 改用统一读取函数，并在没有终端级文件时从备注日志的 `===== 终端 =====` 分段解析；`POST /cases/restore-logs` 新增 `terminals` 字段，恢复时按终端分段写入备注（与板端日志系统同一文本格式）
- **`backend/app/core/remarks.py`** — 新增 `read_case_log`：聚合日志缺失时回退到按终端落盘的日志并拼成同一分段格式，备注列 / 历史记录 / 预览保持一致
- **`backend/app/core/excel_handler.py`** — 下载结果嵌日志图片时，若没有终端级文件则从备注的终端分段拆回各终端，仍按终端分别渲染
- **`frontend/src/utils/terminalLogFormat.ts`（新增）** — 统一的终端日志分段解析 / 拼接工具（`parseTerminalLog` / `formatTerminalLog` / `toTerminalSections`）
- **`frontend/src/utils/executionDraft.ts`** — 草稿用例日志改为 `terminals: [{ label, content }]`；收集日志时优先读取 `/logs/terminals` 的按终端日志，旧草稿自动从 `log_text` 迁移；恢复与导出均使用终端分段格式
- **`frontend/src/components/ExecutionDraftBox.tsx`** — 「查看」弹窗按终端标签页展示每个用例的日志，列表展示终端数量与总字符数
- **`frontend/src/components/CaseLogModal.tsx`** — 接口无终端级日志时，从备注 / 聚合日志的终端分段拆出标签页，仍按终端分别展示

### 修复 — 日志分隔线被误识别为终端分段

- **`backend/app/core/terminal_log.py` / `frontend/src/utils/terminalLogFormat.ts`** — 终端标题识别改为「恰好 5 个等号 + 非空标签 + 恰好 5 个等号」，标签内不允许再出现 `=`；`========================================` 等分隔线不再触发分段，系统分区标题（`完整执行日志` / `板端系统日志`）也不会被当作终端
- **`backend/tests/test_terminal_log.py`（新增）** — 覆盖分隔线、系统分区标题、拼接往返与终端清单读取

---

## [未发布] — 2026-11-16 — 执行测试新增「多终端实时板端日志」

### 新增 — 多终端实时板端日志

- **`backend/app/core/terminal_session.py`** — `PersistentShell` / `TerminalPool` 新增 `on_output` 回调：读泵每收到一段 PTY 原始输出即回调执行器，用于实时推送与落盘
- **`backend/app/core/executor_adapter.py`** — 新增按终端的实时日志采集：PTY 输出按行清洗（去除 `__RCn__` 退出码标记、还原命令回显、统一换行）、攒批推送 WebSocket、按 `<用例日志基名>.<终端名>.term.log` 落盘，并写出 `<基名>.terminals.json` 终端清单；新增 `case_start` 推送（用例编号/描述/类型/优先级/步骤/预期结果/终端列表）；`live_terminal_snapshot()` 提供执行中的实时快照
- **`backend/app/websocket/session_ws_manager.py`** — 新增 `send_case_start` 与 `send_terminal_log` 消息
- **`backend/app/api/routes.py`** — 新增 `GET /logs/terminals/live`（当前任务实时快照）与 `GET /logs/terminals`（按 case_key / path / run_id 读取已保存的按终端日志，旧记录回退聚合日志）
- **`frontend/src/pages/BoardLogPage.tsx`（新增）** — 「板端实时日志」页：多终端并列（网格布局、每终端自动滚动/复制/下载）、当前用例信息与执行进度、实时/历史回看切换、WebSocket 断线或中途打开时用快照补齐
- **`frontend/src/stores/useStore.ts` / `frontend/src/hooks/useWebSocket.ts` / `frontend/src/types/index.ts`** — 新增板端终端状态与 `case_start` / `terminal_log` 消息处理（终端文本上限 20 万字符，超出保留尾部）
- **`backend/app/core/log_image.py` / `excel_handler.py`** — 下载测试结果时按终端渲染日志图片：新增 `read_terminal_logs` 读取 `<基名>.terminals.json`（兼容按命名扫描），每个终端单独渲染一张图片并在「备注」单元格内纵向堆叠、顶部标注终端名；终端较多时均分高度避免整格膨胀；无终端级日志的旧记录回退为原聚合日志图片
- **`frontend/src/components/CaseLogModal.tsx`** — 执行日志弹窗改为按终端分页展示（每个终端独立标签页、可单独复制/下载，AI 证据行高亮按终端分别生效）；无终端级日志的旧记录自动回退到原聚合日志
- **`frontend/src/pages/Dashboard.tsx` / `components/Layout.tsx` / `App.tsx`** — 工具栏新增「板端日志」入口（执行中显示状态点）、进度卡片新增「板端实时日志 →」链接、侧边菜单新增「板端实时日志」路由 `/logs/board`

### 修复 — 命令执行完但用例/执行状态一直不结束

- **`backend/app/websocket/session_ws_manager.py`** — 广播改为各连接并发发送 + 单条超时（`_SEND_TIMEOUT`，含等待发送锁）；慢/失联连接会被移除并关闭，终端实时流不再能阻塞 `case_complete` / `execution_finished`
- **`backend/app/main.py`** — WebSocket 断开时顺带清理该连接的发送锁
- **`frontend/src/hooks/useWebSocket.ts`** — 页面卸载不再无条件关闭共享连接（仍有订阅者时保持）；连接（重连）成功后调用 `getCurrentExecution()` 校准运行态，补齐断线期间错过的结束消息；发送指令以模块级共享连接为准，避免重连后用旧连接发送失败

---

## [未发布] — 2026-11-16 — 统一为多终端持久化 Shell 执行器

### 变更 — 执行引擎统一

- **`backend/app/core/terminal_session.py`（新增）** — 新增 `PersistentShell` / `TerminalPool`：一个终端标签对应一个长期存活的交互式 shell，后台泵任务持续收取输出，`run()` 用 `__RC<token>__=$?` 标记回收退出码，`launch()` / `wait_exit()` 支持阻塞型前台程序，`read_until()` 按特征输出/静默收敛，终端断开自动重建
- **`backend/app/core/executor_adapter.py`** — 删除 `_execute_with_persistent_shell` / `_execute_parallel_fault_test` / `_merge_nvsipl_interactive` / `_find_blocking_nvsipl_index` 及三模式分流，改为单一 `_execute_unified`：程序计数器驱动，`repeat` / `repeat_stream` 通过回跳实现，交互输入按 `_NVSIPL_INPUT_EXPECT` 表等待特征输出；日志按终端分组、AI 判定输入按时间序；用例结束时统一退出各终端的前台程序
- **`backend/app/core/executor_adapter.py`** — 移除已无引用的 `_filter_pty_output` / `_match_dl_elr_stages` / `_check_round_fps`；`preview_commands` 改为展示统一执行器模式与终端清单
- **`backend/app/core/command_parser.py`** — 新增「终端A：」「[终端B]」「A>」步骤前缀解析与 `normalize_terminal_label()`；`DEFAULT_TERMINAL` 由「主终端」改为「终端A」；旧写法「另一个终端」「辅终端」统一归一为终端B；带终端前缀的步骤正文整体视为命令
- **`backend/app/ai/prompts/step_parse.py` / `backend/app/ai/service.py`** — 步骤解析 prompt 的 `terminal` 字段改为开放标签（终端A/终端B/终端C…），AI 返回结果统一经 `normalize_terminal_label()` 归一
- **`frontend/src/types/index.ts` / `CommandPreviewModal.tsx`** — 预览结果新增 `terminals` 字段并展示终端标签
- **`backend/tests/test_terminal_parse.py`（新增）** — 覆盖终端前缀、开放标签、旧写法兼容与默认终端

---

## [未发布] — 2026-11-13 — 测试执行新增「执行日志草稿箱」

### 新增 — 执行日志草稿箱

- **`frontend/src/utils/executionDraft.ts`** — 新增日志草稿的本地持久化（localStorage）：保存每条用例的日志全文、执行状态、AI 判定与证据、运行日志，支持保存 / 恢复 / 重命名 / 删除 / 指纹去重与文本导出；执行结束或停止时可按开关自动保存；备注中没有日志时回退读取后端日志文件
- **`frontend/src/components/ExecutionDraftBox.tsx`** — 新增草稿箱内容：保存当前执行日志、自动保存开关、草稿列表（恢复 / 查看全文 / 导出 txt / 重命名 / 删除）
- **`frontend/src/pages/Dashboard.tsx`** — 「测试执行」工具栏新增「日志草稿箱」入口与数量徽标；恢复弹窗支持重新上传用例文件后写回日志（当前用例已匹配时也可直接恢复），恢复后同步到后端会话
- **`frontend/src/stores/useStore.ts`** — 新增上传文件名、批量写回用例补丁与追加运行日志等状态，支撑草稿恢复
- **`frontend/src/hooks/useWebSocket.ts`** — 执行结束 / 停止时自动保存日志草稿并提示
- **`backend/app/api/routes.py`** — 新增 `POST /cases/restore-logs`：按 case_key（或唯一 case_id）恢复日志文本、执行状态、BUG 判定与证据；下载结果时把恢复的日志写回工作簿副本，再次下载仍可附带日志
- **`backend/app/core/excel_handler.py`** — 新增 `update_remarks`，用于下载结果时更新备注列日志
- **`backend/tests/test_execution_log_draft.py`** — 新增备注写回、下载副本恢复日志、`/cases/restore-logs` 匹配与未匹配用例、保留原有非日志备注的回归测试
- **`frontend/src/api/axios.ts`** — 新增 `restoreCaseLogs` 接口

---

## [未发布] — 2026-11-13 — YUV 转 PNG 支持 UYVY，并可在预期结果中指定像素格式

### 新增 — YUV 出图格式选择

- **`backend/app/core/yuv2img.py`** — 新增 UYVY422（Y422/UYNV）支持：新增 `PACKED_422_LAYOUTS` 布局表与通用 `_packed422_to_rgb`，`yuyv_to_rgb` / 新 `uyvy_to_rgb` 仅传入不同字节偏移；`CONVERTERS` 注册 `uyvy`，命令行 `-f` 自动多出该选项；新增 `frame_bytes_for()` 统一 422（`w*h*2`）与 420（`w*h*1.5`）帧长计算，CLI 与 `convert_frame_to_png` 共用；无 Pillow 的内置编码器同步支持 UYVY；`detect_pixfmt` 的 422 判定说明改为提示「YUYV 与 UYVY 帧长相同无法区分，错位时改 -f uyvy」；`infer_resolution()` 新增 `pixfmt` 参数，422 格式按 `w*h*2` 推断分辨率
- **`backend/app/core/executor_adapter.py`** — 预期结果支持在分辨率后追加像素格式标注，如 `yuv图（1920x1080, uyvy）`：新增 `_parse_pixfmt_from_text`（支持 `nv12` / `i420`(yuv420p、yv12) / `yuyv`(yuy2、yuyv422) / `uyvy`(uyvy422、y422、uynv)，大小写与半角/全角逗号均可）；`_parse_resolution_from_text` 放宽括号内匹配，兼容旧写法 `（1920x1536）`；`_convert_yuv_to_png` 按标注格式转换并推送日志，标注格式与实际数据不符（如帧长不匹配）时自动回退 `auto` 重新转换并告警；分辨率推断按标注格式计算帧长
- **`frontend/src/utils/casegen/functionalCases.ts`** — 分辨率文本字段提示更新为「YUV 可带像素格式，如（1920x1080, uyvy）」

---

## [未发布] — 2026-11-13 — 修复跳板机模式下图片/文件传输失败

### 修复 — 跳板机模式 SCP 传输

- **`backend/app/core/ssh_manager.py`** — 新增 `_build_jump_proxycommand` / `build_scp_command` / `download_file`：SCP 命令统一按登录方式构建，跳板机模式自动附加 `ProxyCommand`（内层 sshpass 提供跳板机密码，外层 sshpass 提供板端密码），不再退化为直连；`download_file` 优先复用已建立的 SSH 连接走 SFTP（直连/跳板机通用、不依赖 sshpass），板端未启用 SFTP 或已回退 OpenSSH 时再回退 scp，并在异常信息中返回板端错误
- **`backend/app/core/executor_adapter.py`** — 板端图片下载改用 `SSHManager.download_file`，跳板机模式下可正常下载；下载失败不再静默忽略，改为推送带原因的 WebSocket 警告日志
- **`backend/app/api/routes.py`** — 文件/目录推送到板端（`/files/push`、`/files/push-local`）改用 `SSHManager.build_scp_command`，跳板机模式同样穿越跳板机
- **`backend/tests/test_scp_transfer.py`** — 新增 SCP/SFTP 命令构建与下载路径单测（含跳板机 ProxyCommand、sshpass 缺失提示、SFTP 优先与 scp 回退）

---

## [未发布] — 2026-11-12 — 新增内置测试「dl el 热插拔」

### 新增 — dl el 热插拔测试预设

- **`frontend/src/types/casegen.ts`** — 新增 `dl_el` 预设 key、`TEST_TYPE_DL_EL` 测试类型与 `FunctionalTestSelection.dl_el` 开关（默认参与生成）
- **`frontend/src/utils/casegen/functionalCases.ts`** — 新增内置预设默认模板：起流命令 `./nvsipl_camera -c {config} -m "{mask}" -R -0 -1 -2 -s -Z`，依次输入 `gc {sensorid}`、`dl {sensorid}`、`el {sensorid}`；预期结果为「执行命令无报错 / 输入dl后帧率降为0,输入el后帧率恢复」
- **`frontend/src/components/casegen/FunctionalGenStep.tsx`** — 新增「dl el测试」预设标签与说明
- **`frontend/src/pages/casegen/CaseGenPage.tsx`** — 生成校验与旧草稿恢复逻辑纳入 `dl_el`

---

## [未发布] — 2026-11-12 — 内置预设用例命令改为基础占位符写法

### 变更 — 去掉 `{xxx_command}` 整条命令占位符

- **`frontend/src/utils/casegen/functionalCases.ts`** — 内置预设（raw图 / YUV / ro / al / 内参 / th）的默认步骤不再使用 `{lighting_command}`、`{yuv_command}`、`{readout_command}`、`{intrinsic_command}`、`{th_command}`，改为像自定义用例一样直接写出完整命令，仅使用 `{config}`、`{mask}`、`{image_path}`、`{nito_path}`、`{skip_frames}`、`{write_frames}`、`{yuv_channel_args}` 等基础占位符；生成结果与旧版命令完全一致
  - 占位符候选列表移除上述整条命令占位符，编辑内置预设时可直接看到并修改命令中的每一项参数
  - `yuv_channel_args` 取值带前导空格（未选中通道时为空），保证 `"{mask}"{yuv_channel_args} -s` 在不同通道配置下都不会粘连或产生多余空格
  - 新增 `upgradeLegacyCommandPlaceholders` / `upgradeLegacyPresetCaseEdits`：恢复草稿 / 自动保存时把旧预设编辑内容中残留的 `{xxx_command}` 就地升级为基础占位符命令，保留用户的其他编辑
- **`frontend/src/pages/casegen/CaseGenPage.tsx`** — 恢复功能测试参数时调用上述升级逻辑，兼容旧草稿

---

## [未发布] — 2026-11-12 — 测试步骤支持「等待N秒」

### 新增 — 步骤级等待

- **`backend/app/core/command_parser.py`** — 新增 `extract_wait_seconds` / `is_wait_only_step`：逐条解析测试步骤中的「等待2秒」「等待 2 秒钟」「延时1.5s」「等待1分钟」「wait 2s」等写法（支持小数、全角数字、同一文本多处累加），并把等待时长挂到该步骤产出的最后一条 `CommandStep` 上
  - 纯等待步骤（如「1. 等待3秒」）解析为新的 `kind="wait"` 步骤；命令行尾部的等待说明会从实际下发命令中剔除，避免被当作命令参数
  - 命令本身即 `sleep N` 时不再重复等待；AI 解析替换后的步骤同样继承原步骤的等待时长
- **`backend/app/core/executor_adapter.py`** — 新增 `_wait_step_delay`：在顺序执行、持久 Shell、并行故障测试三种模式下，步骤命令执行完成后按解析出的时长等待，等待过程可被「停止执行」中断并推送日志
  - `_merge_nvsipl_interactive` 合并管道命令时累加被合并步骤的等待时长，避免等待丢失
  - `preview_commands` 输出 `wait_seconds` 并在预览说明中标注「执行后等待 N 秒」
- **`frontend/src/types/index.ts`**、**`frontend/src/components/CommandPreviewModal.tsx`** — 命令预览支持「等待」类型与等待时长展示
- **`backend/tests/test_step_wait.py`** — 覆盖中英文等待写法、纯等待步骤、命令尾剔除、多命令步骤挂载、`sleep` 去重与 AI 步骤继承

---

## [未发布] — 2026-11-12 — 预期结果支持在线编辑

### 新增 — 预期结果列编辑

- **`frontend/src/components/TestCaseStepsEditModal.tsx`** — 文本编辑弹窗通用化：新增 `hint` / `placeholder` / `monospace` 参数，测试步骤保持等宽字体，预期结果使用普通字体和专用说明文案
- **`frontend/src/components/casegen/CasePreviewStep.tsx`** — 生成用例预览的「预期结果」列新增编辑按钮，保存后按用例 key 更新本地生成用例并提示
- **`frontend/src/pages/Dashboard.tsx`** — 用例列表的「预期结果」列新增编辑按钮（执行进行中禁用），保存后同步后端当前会话与前端 store
- **`frontend/src/api/axios.ts`** — 新增 `updateCaseExpected` 接口
- **`backend/app/api/routes.py`** — `/cases/update` 的 `CaseUpdateRequest` 支持 `test_steps` / `expected_result` 可选字段；编辑预期结果时同步更新会话用例及 `expected_keywords`；下载结果时 `_apply_session_case_edits` 同时应用在线编辑的测试步骤与预期结果
- **`backend/app/core/excel_handler.py`** — 新增 `update_expected_result`，编辑后重新解析预期关键字；`save_results` 执行结束时同步写回在线编辑的「预期结果」列

---

## [未发布] — 2026-11-12 — 功能测试标签页式自定义用例（内置预设可编辑）

### 新增 — 内置测试类型预设 + 标签页交互

- **`frontend/src/components/casegen/FunctionalGenStep.tsx`** — 功能测试步骤改为浏览器标签页式交互：raw图 / YUV图 / ro / al / 内参 / th 六类内置测试作为预设标签，点击标签切换配置
  - **预设与自定义标签均可通过 `×` 关闭**：关闭的预设不显示、不参与本次生成，其启用状态与编辑内容仍保留；重新打开后恢复原状
  - 点击标签栏末尾的 `+`：存在已关闭的预设时弹出选择框，可重新打开任一预设（也可直接新增自定义用例）；没有任何已关闭预设时直接新增自定义用例标签
  - 预设面板内提供「参与本次生成」开关，左上角状态圆点显示启用 / 禁用状态；关闭的预设圆点状态在重新打开选择框中仍可见
  - **内置预设与自定义用例使用同一套可编辑字段**：描述 / 前置条件 / 测试步骤 / 预期结果 / 优先级 / 「每台已启用相机各生成一条」，预设编辑后显示「恢复默认」按钮，可一键还原默认模板
  - 预设与自定义面板均提供测试步骤占位符预览与一键插入占位符
  - 「将生成 N 条用例」按预设的 `per_camera` 设置与 th sensor 匹配情况统计，与生成结果一致
- **`frontend/src/utils/casegen/functionalCases.ts`** — 新增占位符上下文与替换逻辑，支持 `{config}`、`{mask}`、`{sensorid}`、`{group}`、`{link_index}`、`{module}`、`{sensor}`、`{sensor_i2c}`、`{resolution}`、`{fps}`、`{image_path}`、`{nito_path}` 等；生成时按相机属性自动替换，未识别占位符保持原样
  - 内置六类测试改为默认模板 `PRESET_CASE_DEFAULTS`，通过 `resolvePresetCaseTemplate` 合并用户编辑；默认内容与原硬编码生成结果完全一致，用例顺序与 key 格式保持不变
  - 生成时跳过 `closed_presets` 中的预设标签，同时保留其启用状态与编辑内容
  - 自定义用例按模板自身的「参与本次生成」开关逐条生成
- **`frontend/src/types/casegen.ts`** — 新增 `CustomCaseTemplate` 类型与「自定义测试」类型名；新增 `PresetCaseKey` / `PresetCaseEdit` / `PresetCaseEdits` 与 `PRESET_CASE_KEYS`；`FunctionalTestOptions` 增加 `custom_cases`、`preset_cases` 与 `closed_presets`，自定义模板增加 `enabled` 独立开关
- **`frontend/src/pages/casegen/CaseGenPage.tsx`** — 生成校验按「存在已启用的有效自定义模板」和「未关闭的功能测试预设」判断，已关闭的预设不再触发 YUV / th 参数校验；在草稿 / 自动保存恢复中兼容旧数据（旧草稿缺少 `preset_cases` / `closed_presets` 时回退默认值）
- **`frontend/src/components/casegen/CasePreviewStep.tsx`** — 预览表为「自定义测试」增加标签颜色

---

## [未发布] — 2026-11-11 — 合并测试用例

### 新增 — 主用例 + 来源用例合并

- **`backend/app/core/case_merger.py`** — 新增用例合并核心：解析两个 case.xlsx 格式工作簿，按 Sheet 同名 / 同类别匹配目标表，把选中的来源用例行追加到主用例末尾
  - 只复制用例定义列（用例ID / 类型 / 需求ID / 描述 / 前置条件 / 步骤 / 预期结果 / 优先级），默认不复制来源的执行结果，可选用 `include_results` 保留
  - 复制单元格样式、行高、合并单元格；主用例缺少对应类别 Sheet 时自动新建并复制来源表头
  - 合并后延长 Sheet 顶部 `Total` 统计公式的统计范围、扩展自动筛选区域，并刷新「数据统计」页汇总公式
  - 支持按用例ID跳过主用例中已存在的重复用例；无真实用例ID的自动编号行不参与重复判断
- **`backend/app/api/merge_routes.py`** — 新增合并 API：`POST /api/merge/preview`（上传两个文件并解析来源用例）、`POST /api/merge/execute`（按选中用例生成合并文件）、`GET /api/merge/download/{token}`（下载结果）；临时文件保存在 `uploads/merge/<token>/`
- **`backend/app/main.py`** — 注册合并路由与 `uploads/merge` 目录
- **`frontend/src/pages/casegen/MergeCasesPage.tsx`** — 新增「合并测试用例」页面：拖拽上传主用例 / 来源用例，按 Sheet 过滤与关键字搜索来源用例，勾选后合并；支持“同时复制执行结果”“跳过重复用例 ID”“自定义输出文件名”，合并完成后可直接下载
- **`frontend/src/api/mergeApi.ts`**、**`frontend/src/types/merge.ts`** — 合并接口与类型
- **`frontend/src/App.tsx`**、**`frontend/src/components/Layout.tsx`** — 「用例生成」模块新增 `/casegen/merge` 路由与侧边菜单
- **`backend/tests/test_case_merge.py`** — 覆盖来源用例解析、追加合并、重复跳过、缺失 Sheet 新建、统计公式范围延长

---

## [未发布] — 2026-11-10 — 测试步骤支持在线编辑

### 新增 — 测试步骤编辑入口

- **`frontend/src/components/TestCaseStepsEditModal.tsx`** — 新增通用测试步骤编辑弹窗
- **`frontend/src/pages/Dashboard.tsx`** — 「测试步骤」列新增编辑按钮；保存后同步更新会话用例并清理该用例的 AI 解析缓存；执行进行中禁止编辑
- **`frontend/src/components/casegen/CasePreviewStep.tsx`** — 生成用例预览的「测试步骤」列新增编辑按钮，修改后同步到本地缓存与草稿
- **`frontend/src/pages/casegen/CaseGenPage.tsx`** — 新增 `handleUpdateCase`，按用例 key 更新生成的用例并写入 localStorage
- **`frontend/src/api/axios.ts`**、**`frontend/src/stores/useStore.ts`** — 新增 `updateCaseSteps` 接口与 `updateCaseFields` 状态更新方法
- **`backend/app/api/routes.py`** — 新增 `POST /cases/update`，仅更新当前会话内存；下载结果时把编辑后的步骤覆盖到下载副本
- **`backend/app/core/excel_handler.py`** — `save_results` 执行结束时同步写回「测试步骤」列，保证结果文件与下载内容一致

---

## [未发布] — 2026-11-10 — 取消 gc 自动注入，仅执行显式 gc

### 变更 — gc 发送策略

- **`backend/app/core/executor_adapter.py`**
  - 移除所有自动注入 gc 的逻辑：普通顺序模式的 `{ sleep; echo gc; } | nvsipl_camera` 管道包裹、非阻塞起流的合并管道 gc、持久 Shell 的自动 gc、PTY 模式初始化后的自动 gc，以及反复起流每轮自动生成 `gc` 步骤
  - 只有测试步骤中显式写出的 `nvsipl_input`（如 `输入 gc 0`）才会发送 gc；PTY/持久 Shell/管道模式均按步骤执行
  - 反复起流模式每轮执行显式交互步骤；未检测到真实帧率时该轮判定失败并提示需显式写 gc
  - 删除不再使用的 `_auto_inject_gc`、`_generate_gc_commands`、`_wrap_nvsipl_with_gc`
- **`frontend/src/utils/casegen/functionalCases.ts`**
  - raw图 / YUV图 / 压力测试 / 稳定性测试生成的步骤中补充显式 `输入gc <sensorId>` 步骤，避免取消自动注入后无法出帧
- **`frontend/src/components/TestStepRulesModal.tsx`**、**`frontend/src/components/casegen/StressGenStep.tsx`** — 同步更新步骤规则与压力测试说明
- **`docs/TEST_CASE_WRITING_RULES.md`** — 4.4 改为「gc 必须显式写出」，同步更新重复/压力测试与执行模式说明

---

## [未发布] — 2026-11-06 — 功能测试新增内参读取用例

### 新增 — 内参读取用例生成

- **`frontend/src/types/casegen.ts`** — 新增测试类型 `TEST_TYPE_INTRINSIC = '内参测试'`，`FunctionalTestSelection` 增加 `intrinsic` 开关（默认开启）
- **`frontend/src/utils/casegen/functionalCases.ts`** — 新增 `buildIntrinsicCommand()`，按相机生成 `./nvsipl_camera -c <平台> -m "<掩码>" -R -0 -1 -2 -e -r 4` 命令（-r 4 让进程运行 4 秒后自动退出）；每个相机生成一条内参读取用例，预期结果为「执行命令无报错；日志中打印出eeprom芯片内容；CRC校验通过」
- **`frontend/src/utils/casegen/functionalCases.ts`** — `-m` 掩码组数改为按平台配置 `enableMasks` 数量生成：单组配置只输出一个掩码值（如 `"0x0001"`），不再固定补成四组；功能测试、压力测试、稳定性测试及命令预览同步生效
- **平台配置支持逐台启用/禁用相机**
  - `frontend/src/types/casegen.ts` — `PlatformTopologyRow` 新增 `enabled` 字段（缺省视为启用）
  - `frontend/src/components/casegen/PlatformStep.tsx` — 拓扑表新增「启用」勾选列，并显示已启用相机数量；启用状态写回平台配置并随自动保存/草稿持久化
  - `frontend/src/utils/casegen/functionalCases.ts` — 功能 / 压力 / 稳定性用例生成均跳过未启用相机（保留拓扑原始下标，草稿中的组合 key 仍可解析）
  - `frontend/src/components/casegen/FunctionalGenStep.tsx`、`StressGenStep.tsx`、`StabilityGenStep.tsx` — 用例计数、命令预览、相机组合选项与快捷按钮均只使用已启用相机
- **`frontend/src/components/casegen/FunctionalGenStep.tsx`** — 功能测试配置新增「内参测试」勾选项、命令预览与用例数统计
- **`frontend/src/components/casegen/CasePreviewStep.tsx`** — 预览列表补充内参测试类型标签颜色
- **`frontend/src/pages/casegen/CaseGenPage.tsx`** — 生成校验与旧草稿恢复兼容 `intrinsic` 开关
- **生成的测试步骤附带参数备注** — `frontend/src/utils/casegen/functionalCases.ts` 新增 `appendCommandNotes()`，在命令步骤后追加带圈数字备注行（从 `①` 开始，如 `①、-m 指定模组位置`、`②、-c 指定平台配置`），作用于 raw图 / YUV图 / ro / al / 内参 / th 及压力、稳定性用例；①②… 开头的行按执行器约定视为注释，不参与命令执行

---

## [未发布] — 2026-11-02 — 用例执行期间采集板端系统日志

### 新增 — 板端系统日志采集（journalctl / QNX slog2info）

- **`backend/app/core/executor_adapter.py`**
  - `_detect_syslog_backend()` — 自动识别板端可用工具：Linux 优先 `journalctl`，QNX 使用 `slog2info`，结果按执行器缓存
  - `_start_syslog_capture()` / `_stop_syslog_capture()` — 用例执行期间在板端后台运行 `journalctl -f -o short-iso` 或 `slog2info -w`，结束后停止进程、读回日志并清理 `/tmp` 临时文件
  - 自动处理权限：root 直接读取；普通用户有 sudo 密码时用 `sudo -S` 提权，无密码时尝试 `sudo -n`
  - 采集前清空板端系统日志缓冲：Linux `journalctl --rotate` + `--vacuum-time=1s`，QNX `slog2info -c`（可用 `syslog_capture_clear` 关闭）
  - 采集结果按关键字过滤：默认 `grep nvsipl_camera`，在板端执行 grep 后再回传（可用 `syslog_capture_grep` 修改，留空不过滤）
  - 系统日志追加到用例 `.log` 末尾（`===== 板端系统日志 (journalctl, grep nvsipl_camera) =====`），不参与 AI 判定；单用例最多保留最后 2000 行 / 300 KB
  - 覆盖普通顺序、PTY、持久 Shell、并行故障测试等所有执行模式；异常与人工确认失败路径同样保留日志
- **`backend/app/core/test_case.py`** — `WorkspaceConfig` 新增 `syslog_capture_enabled` / `syslog_capture_mode` / `syslog_capture_extra_args` / `syslog_capture_clear` / `syslog_capture_grep`
- **`frontend/src/pages/WorkspaceConfigPage.tsx`** — 工作区配置新增「板端系统日志采集」折叠项（开关 + 采集方式 + 附加参数）
- **`frontend/src/types/index.ts`** — 同步新增配置字段类型
- **`docs/user-guide.html`** — 工作区配置章节补充系统日志采集说明

---

## [3.9.0] — 2026-10-09 — 代码分析导航整合 + 函数时序图工程化

### 新增 — 函数时序图项目化（工程化改造）

函数时序图从「粘贴代码」模式升级为与类图分析完全对称的工程项目模式。

- **`backend/app/core/seqdiag_store.py`** — 新建
  - 时序图项目持久化存储（`runtime/seqdiag_projects/<id>/project.json`）
  - CRUD：`list_projects / create_project / get_project / delete_project`
  - 源码目录管理：`source_dir / clear_source / source_absolute_path`
  - include 目录管理：`include_dir / remove_include / include_absolute_paths`
  - 快照更新：`update_last_query`（记录 `func_a_name`、`func_b_name`、`uml`、`matched_files`）
- **`backend/app/core/cpp_seq_parser.py`** — 新建
  - `find_function(source_roots, func_name)` — 扫描 `.h/.cpp` 定位函数体，namespace + class 上下文感知，多匹配返回列表
  - `extract_var_types(body, params)` — 提取变量类型映射
  - `extract_calls(body, class_name, var_types)` — 提取调用链，返回 `CallEvent[]`
  - `collect_headers(source_root)` — 列举头文件（autocomplete 用）
- **`backend/app/core/seq_uml_emit.py`** — 新建
  - `build_seq_uml(func_a, calls_a, func_b?, calls_b?, opts)` → PlantUML `@startuml … @enduml` 文本
  - 支持 `autonumber / show_returns / caller_name` 三个选项
  - 函数 B 存在时，在 A 调用 B 处自动展开 B 的内部调用
- **`backend/app/api/seqdiag_routes.py`** — 新建，挂载到 `/api/seqdiag`
  - `GET/POST /projects`、`GET/DELETE /projects/{id}`
  - `POST /projects/{id}/source` — 流式上传主源码 zip，安全解压（zip bomb 检测），重传自动清空旧目录
  - `POST /projects/{id}/includes` — 追加 include zip（可多次）
  - `DELETE /projects/{id}/includes/{name}`
  - `GET /projects/{id}/headers` — 头文件 autocomplete（mtime 缓存，增量更新）
  - `POST /projects/{id}/generate` — `{func_a_name, func_b_name?, options?}` → `{uml, resolved_func_a, matched_files, …}`；多匹配时返回 409 + 候选列表
- **`backend/app/main.py`** — 注册 seqdiag 路由，`lifespan` 创建 `runtime/seqdiag_projects/` 目录，HTTP 中间件白名单加 `/api/seqdiag/`（session-agnostic，同 classdiag）
- **`frontend/src/types/seqDiag.ts`** — 新建：`SeqDiagProject / SeqDiagProjectSummary / SeqLastQuery / SeqGenerateRequest / MultiMatchCandidate`
- **`frontend/src/api/seqDiagApi.ts`** — 新建：封装所有 `/api/seqdiag/*` 端点（list / create / delete / uploadSource / uploadInclude / deleteInclude / listHeaders / generateSeqDiagram）
- **`frontend/src/pages/seqdiag/SeqDiagProjectsPage.tsx`** — 新建：项目列表页（Table + 新建 Modal + 删除 Popconfirm），与 ClassDiagProjectsPage 对称
- **`frontend/src/pages/seqdiag/SeqDiagWorkspacePage.tsx`** — 新建：工作区页
  - 左列：函数 A 输入框（`ClassName::method`）+ 函数 B 可选输入框 + 生成按钮 + 源码/include 上传管理
  - 右列 Tabs：时序图 SVG / PlantUML 源码 / 匹配的文件
  - 409 多匹配时弹候选 Modal，点选后自动填回输入框并重新提交

### 新增 — 代码分析统一 Tab 导航

- **`frontend/src/components/Layout.tsx`**
  - 删除原独立的 `flowchart / seqdiag / classdiag` 三个顶层 tab
  - 新增 `analysis`「代码分析」顶层 tab，点击落地到 `/classdiag/projects`
  - 新增 `ANALYSIS_SIDER_MENUS`：函数流程图 → 类图分析 → 函数时序图，通过左侧 Sider 切换
- **`frontend/src/App.tsx`** — 新增 `/seqdiag/projects` 和 `/seqdiag/workspace/:projectId` 路由

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
