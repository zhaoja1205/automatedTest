# 变更日志 (CHANGELOG)

本文件记录 `test_runner_web` 项目每个版本的功能变更、修复和改进。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/) `MAJOR.MINOR.PATCH`。

---

## [未发布] — 2026-11-25 — 步骤解析支持逗号分隔与多行数字参数输入

### 新增 — 「输入1500, 1080, ...」及后续单独成行的数字参数行

- **`backend/app/core/command_parser.py`** — `parse_nvsipl_interactive_inputs` 的数字参数行模式支持逗号 / 全角逗号 / 顿号分隔：`输入1500, 1080, 800, 600, 2, 4` 解析为一条 `nvsipl_input`，整行原样下发（保留逗号写法）；数字片段限定为十进制与 `0x` 十六进制，避免把 `输入 0, dl 2` 误判为参数行
- **`backend/app/core/command_parser.py`** — 新增「省略『输入』、单独成行」的数字参数行识别：同一步骤里第一行写 `输入1500, 1080, 800, 600, 2, 4`、下一行写 `1000, 500, 2000, 1000, 2, 1` 时解析为 `1500, 1080, 800, 600, 2, 4;1000, 500, 2000, 1000, 2, 1`，两行各自作为一次交互输入依次下发；`执行 sr` 后再跟参数行的写法同样生效；整步只有数字参数行（无「输入」前缀、无子命令）时也识别为交互输入；含说明文字的行（如 `记录当前参数 1500, 1080, 800`、`e.g. 8000 256`）仍不误判；两组参数完全相同的 ROI 输入不会被去重
- **`backend/app/ai/prompts/step_parse.py`** — 步骤解析提示词补充数字参数行示例：按原文每行一条 `nvsipl_input`、用分号连接，不拆单个数、不改写或去掉逗号
- **`backend/app/ai/prompts/step_rewrite.py`** — 步骤重写提示词要求数字参数行保持原样、逐行保留，不合并、不改写分隔符
- **`frontend/src/components/TestStepRulesModal.tsx`** — 「nvsipl 交互命令」规则说明补充数字参数行写法与多行下发规则
- **`docs/TEST_CASE_WRITING_RULES.md`** — §4.1 补充逗号分隔 / 多行数字参数行的写法示例
- **`backend/tests/test_terminal_parse.py`** — 新增测试：逗号/全角逗号/顿号参数行、后续裸数字行合并、整步裸数字、`执行 sr` + 参数行、含说明文字不误判、`输入 0, dl 2` 不被截断

---


## [未发布] — 2026-11-24 — 多张 yuv 截图改为横向并排

### 修复 — 备注列有多张 yuv 图时表格行高不够、图片压到下一行

- **`backend/app/core/excel_handler.py`** — `embed_case_images()` 的多张 yuv 截图改为**同一行横向并排**（保持各自的显示尺寸 170px 宽），不再纵向堆叠：日志图片仍在上方按终端纵向排列，截图统一排在日志图片下方。此前日志图片（默认显示宽 320px、高可达 400px+）加 2 张截图时纵向总高约 630px，超过 Excel 单行行高上限 409 磅（约 545px），行高被截断而图片锚点仍按原像素偏移排列，越出单元格压住下一行，表现为「表格没有正确扩充、图片位置错乱」
- **`backend/app/core/excel_handler.py`** — 新增 `_layout_vertical_images()` / `_layout_horizontal_images()` / `_cell_images()`：横向排列按「左侧留白 + 图宽 + 图间距」计算锚点与列宽；整行总宽超过 Excel 列宽上限（255 字符）时截图整体等比缩小；高度超过 409 磅上限时**优先压缩上方日志图片**，尽量保持截图原尺寸，仍不够才缩小截图。`embed_log_images()` 的纵向排列复用同一套适配
- **`backend/app/core/excel_handler.py`** — 备注列宽按截图行总宽（含左右留白）计算并放宽到 Excel 上限 255 字符；行高只按「日志图片 + 一行截图」计算
- **`backend/tests/test_embed_case_images.py`** — 留白/间距/零留白测试改为横向排布断言；新增：2 张截图并排保持原尺寸且落在行高上限内、12 张截图超出列宽上限时等比缩小并保持在 255 字符内

---

## [未发布] — 2026-11-24 — 修复 -f 文件名前缀导致文件检查漏检

### 修复 — `-f ./picture/1` 拍图成功但「未找到 .yuv 文件」

- **`backend/app/core/executor_adapter.py`** — `_collect_image_dirs()` 按 nvsipl 实际语义解析 `-f`：`-f` 是**文件名前缀**（相机写出 `<前缀>_cam_<sensor>_out_<n>.yuv`），文件落在前缀所在目录；以 `/` 结尾的写法仍按目录处理（执行器会再补 `default`/`rotate` 前缀），不以 `/` 结尾时取前缀的父目录。此前把整个 `-f` 值当目录，`-f ./picture/1` 会去搜 `/storage/yxy/picture/1`（并不存在）而漏掉 `picture/1_cam_0_out_1.yuv`；执行前清空目录同样改到正确目录，避免历史产物残留
- **`backend/tests/test_image_dirs.py`** — 新增测试：前缀取父目录（相对/绝对/裸文件名）、`/` 结尾保持目录、无 `-f` 用工作目录、`cd` 后基准目录、多前缀去重

---

## [未发布] — 2026-11-24 — 步骤解析支持「执行指令」引导语

### 新增 — 「执行指令 xxx」按命令解析

- **`backend/app/core/command_parser.py`** — 命令提取模式新增「执行指令」显式引导（`_EXPLICIT_PATTERN_COUNT` 7→8）：`执行指令：ls /tmp` 与省略冒号的 `执行指令 ls /tmp` 都解析为 `command`，正文整体下发；显式引导不做命令关键字白名单校验，`执行指令 reboot` / `执行指令 pwd` 等不在 `_CMD_KEYWORDS` 中的命令也能执行；引导语与命令体之间必须有冒号或空白，`执行指令后确认画面正常` 这类说明文字仍按跳过处理；支持「终端B执行指令 …」终端标签与「然后执行指令 …」前置语；`执行指令 gc 3` 等交互子命令仍优先识别为 `nvsipl_input`
- **`backend/tests/test_exec_instruction.py`** — 新增测试：冒号可省略、白名单外命令、终端标签、说明文字不误判、交互子命令优先

### 修复 — 「执行指令‘th’查看内参」识别不到

- **`backend/app/core/command_parser.py`** — `parse_nvsipl_interactive_inputs()` 新增「执行/执行指令」引导模式（模式3）：引导语后带引号（`'` `"` `‘’“”`）或直接跟已知 nvsipl 子命令（`gc`/`ro`/`hs`/`al`/`dl`/`el`/`th` 等）时解析为 `nvsipl_input`，冒号与引号均可省略，如 `执行指令‘th’查看内参`、`执行指令 th`、`执行‘th’`、`执行指令：'th'` 均下发 `th`；引导语后不是已知子命令的内容（`执行指令 ls /tmp`、`执行指令 threshold`）仍按 shell 命令解析；该模式放在子命令列表模式之后，`执行dl 0, dl 2, dl 3` 等多条子命令不会被截断；`执行指令 gc3` 仍补空格为 `gc 3`
- **`backend/tests/test_exec_instruction.py`** — 新增测试：引号/弯引号/冒号各写法识别为 `nvsipl_input th`、非子命令仍按命令解析、多条子命令列表完整提取

---

## [未发布] — 2026-11-24 — 支持 nvsipl_multicast 阻塞型前台程序

### 修复 — nvsipl_multicast 起流步骤被当成普通命令，用例卡在第一步

- **`backend/app/core/command_parser.py`** — 新增 `is_nvsipl_tool_command()`：同时识别 `nvsipl_camera` 与 `nvsipl_multicast`；`is_blocking_nvsipl()` 改为基于该判定，`nvsipl_multicast` 不带 `-r N` 时同样视为阻塞型前台程序（起流后一直运行，输入 `q` 才退出）。此前只识别 `nvsipl_camera`，`./nvsipl_multicast ...` 会被当成同步命令执行，执行器一直等它返回（等满命令超时），表现为用例卡在起流步骤，后续 `gc/ro/hs/q` 交互输入也无法送达；`nvsipl_camera` 专属的 `-f` 出图与拍照命名逻辑仍只按 camera 判定
- **`backend/app/core/command_parser.py`** — 步骤主体含 `nvsipl_multicast` 起流命令时按 `command` 解析，不再因「输入 xx」子命令被整步误判为 `nvsipl_input`
- **`backend/app/core/executor_adapter.py`** — `_find_previous_nvsipl_pc()`（反复起流回跳）同时支持 `nvsipl_multicast`；交互输入查表键改为取命令字母前缀（`gc3` 按 `gc` 处理，避免落到默认 8 秒超时且不触发帧率检查）；执行预览说明改为「阻塞型 nvsipl 前台程序」
- **`backend/app/ai/prompts/step_parse.py`** — 步骤解析提示词补充 `nvsipl_multicast` 起流与交互子命令示例
- **`backend/tests/test_nvsipl_multicast.py`** — 新增测试：multicast 识别为阻塞型、camera `-r` 非阻塞、用例步骤解析为 `command + nvsipl_input`、交互输入查表键归一化



### 新增 — 下载结果时可关闭 BugList 自动登记

- **`backend/app/core/test_case.py`** — `WorkspaceConfig` 新增 `generate_bug_list`（默认 `true`）：下载结果报告时是否把失败用例自动登记到 BugList统计 页
- **`backend/app/api/routes.py`** — `/download/results` 生成下载副本时按 `generate_bug_list` 决定是否登记 BugList；关闭时下载副本保留工作簿原有的 BugList 内容，不做登记
- **`backend/app/api/routes.py`** — 执行结束时同样按 `generate_bug_list` 决定是否调用 AI 为失败用例生成 Bug 描述与 Severity：关闭时跳过该 AI 调用，不再输出「AI 已为 N 条失败用例生成 Bug 描述与 Severity」日志
- **`frontend/src/pages/WorkspaceConfigPage.tsx`** — 新增「报告生成配置」分组，提供「下载结果时生成 BugList」复选框
- **`frontend/src/types/index.ts`** — `WorkspaceConfig` 类型同步新增 `generate_bug_list`
- **`backend/tests/test_buglist_parser.py`** — 新增测试：开关关闭时不登记，开启时正常写入失败用例

## [未发布] — 2026-11-24 — 日志弹窗来源与下载结果保持一致

### 变更 — 日志弹窗改用备注中的日志（与下载结果同一份）

- **`frontend/src/components/CaseLogModal.tsx`** — 日志弹窗不再优先请求 `/logs/terminals` 的终端日志文件，改为优先使用用例备注中的日志文本：与「下载结果」写入备注列的日志来源一致，在线编辑过日志或草稿恢复的记录在弹窗与下载中看到的内容相同；仍按 `===== 终端 =====` 分段拆出终端标签页展示，备注没有日志时才回退读取 `/logs/content` 聚合日志
- **`frontend/src/components/CaseLogModal.tsx`** — 打开弹窗时少一次终端日志请求；来源说明按实际来源显示「备注日志」或「聚合日志」

## [未发布] — 2026-11-24 — 修复日志截断导致备注只剩最后一个终端

### 修复 — 用例日志按大小截断后，备注/弹窗中靠前的终端整段消失

- **`backend/app/core/executor_adapter.py`** — `_cap_log_text()` 改为按终端分段截断：先按 `===== 终端 =====` 标题把聚合日志拆成各终端段落，再把字符预算平均分给各段，每段保留标题与末尾输出；此前是对整份日志做一次全局尾部截取，日志超过上限时会把靠前终端的标题连同整段内容一起截掉，而备注与日志弹窗依赖该标题按终端解析，于是只显示最后一个终端（如只看到终端B）。预算不足以完整保留标题时退回整体尾部截断
- **`backend/tests/test_case_log_limit.py`** — 新增测试：多终端日志截断后两个终端标题都在、短终端完整保留、长终端保留末尾输出、截断结果仍能被 `parse_terminal_log` 解析出两个终端；追加写入异常日志后终端标题仍保留

## [未发布] — 2026-11-24 — 工作区配置全量持久化到 localStorage

### 修复 — 未展开折叠分组的配置未写入 localStorage / 后端

- **`frontend/src/pages/WorkspaceConfigPage.tsx`** — 保存时改用 `form.getFieldsValue(true)` 读取整个表单 store，并与加载时的完整配置合并后再提交：此前 `validateFields()` 只返回已挂载字段，折叠面板中未展开过的分组（路径覆盖、拍图下载、日志备注、AI 判定）以及条件隐藏字段不会被保存，后端收到缺省字段后又会回落默认值；现在所有 `WorkspaceConfig` 字段（含 `auto_save`、`output_dir` 等无表单项字段）都会写入后端和 localStorage
- **`frontend/src/pages/WorkspaceConfigPage.tsx`** — 四个配置分组设置 `forceRender`，折叠状态下也挂载全部表单字段，避免依赖字段/条件字段因未渲染而丢失
- **`frontend/src/pages/WorkspaceConfigPage.tsx` / `frontend/src/pages/Dashboard.tsx`** — 加载并合并后端与本地配置后，立即把合并后的完整配置写回 localStorage，补齐旧版本保存时缺失的字段

## [未发布] — 2026-11-24 — 用例执行日志增加大小上限

### 新增 — 执行结果日志超过上限时从后往前截取

- **`backend/app/core/test_case.py`** — `WorkspaceConfig` 新增 `case_log_max_kb`（默认 2048 KB，`0` 表示不限制）：用例执行结果日志超过上限时从末尾截取，只保留最近的输出
- **`backend/app/core/executor_adapter.py`** — `_write_case_log()` 保存/追加日志时按 `case_log_max_kb` 截断：超过上限时在文件开头写入截断标记，保留末尾内容（标记计入上限，重复截断不叠加标记）；追加写入先只读回文件末尾再合并截断，避免把超大文件整个读入内存，最终文件不超过上限
- **`frontend/src/pages/WorkspaceConfigPage.tsx`** — 工作区配置「日志备注配置」分组新增「执行日志上限 (KB)」输入项，说明截断规则
- **`frontend/src/types/index.ts`** — `WorkspaceConfig` 类型同步新增 `case_log_max_kb`
- **`backend/tests/test_case_log_limit.py`** — 新增测试：从末尾保留、标记不叠加、0 表示不限制、追加写入后总长度仍受限且保留最新输出

## [未发布] — 2026-11-24 — 人工操作步骤自动转为人工确认

### 变更 — 拔插 / 手动切换类步骤执行时暂停等待人工确认

- **`backend/app/core/command_parser.py`** — 步骤文本命中人工操作关键字（`人为手动`、`手动切换`、`手动操作`、`手动拔`、`手动插`、`人工操作`、`人工切换`、`人为操作`、`物理操作`、`拔插`、`插拔`）时，解析为 `kind="confirm"`（等价于步骤开头写 `MANUAL_CONFIRM`），不再解析为 `kind="manual"` 后直接跳过；原文保留在 `description` 作为确认弹窗说明，终端标签与「等待N秒」照常生效
- **`backend/app/core/executor_adapter.py`** — 无需改动：`confirm` 步骤沿用既有 `request_manual_confirm` 流程（默认等待 300 秒；未通过或超时判用例 Fail 并停止后续步骤）
- **`backend/tests/test_manual_confirm.py`** — 新增测试：人工关键字转 `confirm`、终端标签与等待时长保留、`MANUAL_CONFIRM` 显式写法兼容、人工动作与命令混写时整步按人工确认处理

## [未发布] — 2026-11-23 — 新增「写回原测试用例」

### 新增 — 用例定义信息写回上传的 Excel

- **`backend/app/core/excel_handler.py`** — 新增 `write_case_content()`：只写测试类型、需求 ID、设计方法、用例描述、前置条件、测试步骤、预期结果、优先级；按 `case_key` 定位工作簿实际行，不触碰实际结果、状态、BUG 判定、备注日志、测试人员与测试日期
- **`backend/app/api/routes.py`** — 新增 `POST /cases/writeback`：把当前会话中在线修改的用例定义信息写回上传的 Excel，返回写回用例数、变更单元格数与文件名；请求可携带前端当前展示的用例定义字段，写回前先同步到会话，避免本地修改尚未落库被旧数据覆盖；执行进行中拒绝操作
- **`backend/app/api/routes.py`** — 新增 `GET /cases/writeback/download`：下载刚写回的上传用例 Excel。浏览器无法直接覆盖用户本地选择的文件，因此写回后由前端自动下载更新后的文件
- **`frontend/src/api/axios.ts`** — 新增 `writeBackCases()`、`downloadWrittenBackCases()` 与相关类型
- **`frontend/src/pages/Dashboard.tsx`** — 工具栏新增「写回原测试用例」按钮：点击后弹窗确认，明确提示只写用例定义信息、不写执行状态/结果/日志；成功后自动下载更新后的 Excel，提示浏览器不能直接覆盖本地原文件，需用下载文件替换
- **`backend/tests/test_write_back_cases.py`** — 新增测试：验证定义字段写回成功，且执行结果、判定、日志、测试人员/日期保持原样；内容无变化时不重写文件

## [未发布] — 2026-11-23 — AI 重写测试步骤并以 Diff 确认替换

### 变更 — 测试步骤列的「AI 解析」改为「AI 重写为程序可识别写法」

- **`backend/app/ai/prompts/step_rewrite.py`** — 新增步骤重写提示词：要求 AI 在不改动命令、参数和执行顺序的前提下，把口语化步骤改写为带连续编号、显式命令前缀、终端标签、交互输入、等待/重复/人工确认等可识别句式，并输出 `rewritten_steps` / `summary` / `changes`；明确 `①`、`②`、`③` 等带圈数字是注释标记而非步骤编号，原有注释行（含带圈数字标记与说明文字）必须原样保留，不删除、合并或改写；输出编号只允许 `1.` / `2.` / `3.`；单终端用例不添加任何终端标签（程序默认终端A），仅多终端用例才在每一步标注 `终端A：` / `终端B：`
- **`backend/app/ai/prompts/step_parse.py`** — 同步修正：带圈数字不再作为多命令分隔符，其后的内容按注释处理
- **`backend/app/ai/service.py`** — 新增 `rewrite_steps()`：调用 AI 并清洗代码围栏与换行，返回原文、改写文、改写说明及是否变化；结果带缓存，`force_refresh` 供手动按钮强制重新生成
- **`backend/app/ai/prompts/registry.py`** — 注册 `step_rewrite` 提示词功能，系统设置页可直接查看/自定义
- **`backend/app/api/routes.py`** — 新增 `POST /ai/rewrite-steps`；同时用 `CommandParser` 校验改写前后文本，返回 `validation` / `original_validation`（可执行步骤数、仍无法识别的步骤），不写入命令解析缓存

### 新增 — GitHub 风格差异确认弹窗

- **`frontend/src/components/TestStepsRewriteDiffModal.tsx`** — 新增确认弹窗：展示 AI 改写说明、主要改写点、规则识别数量对比和未识别步骤提示；支持「并排对比 / 统一视图」切换，红色删除行、绿色新增行并带行号
- **`frontend/src/utils/textDiff.ts`** — 新增无依赖的行级 LCS diff：生成并排视图行、带 `@@` 分块的统一视图及增删行统计
- **`frontend/src/pages/Dashboard.tsx`** — 测试步骤列的 AI 按钮改为调用重写接口并打开 diff 弹窗；用户点击「替换测试步骤」后才写回后端与本地用例，同时清除该用例旧的 AI 解析缓存；「保留原步骤」不修改任何内容
- **`frontend/src/types/index.ts` / `frontend/src/api/axios.ts` / `frontend/src/stores/useStore.ts`** — 增加重写响应类型、`aiRewriteSteps` 接口与 `removeAIParsedCase`；步骤编辑说明与命令预览提示同步更新

### 测试

- **`backend/tests/test_ai_prompts.py`** — 注册表用例补充 `step_rewrite`，并新增重写结果字段与提示词调用测试

## [未发布] — 2026-11-23 — 修复测试执行页刷新后筛选、页码与滚动位置丢失

### 修复 — 刷新页面后筛选条件、页码与滚动距离不再丢失

- **`frontend/src/pages/Dashboard.tsx`** — 测试类型筛选、执行状态筛选（含状态下拉中待应用的值及筛选行快照）和当前页码写入 `sessionStorage`（key 带 sessionId），刷新页面后自动恢复；恢复的页码超出筛选后总页数时自动收敛到最后一页；切换页签、重新上传用例时的重置仍会同步记录

### 新增 — 记录并恢复滚动距离

- **`frontend/src/pages/Dashboard.tsx`** — 在内容区捕获滚动事件，节流写回内容区纵向滚动距离与用例表格横向滚动距离（`pagehide`/卸载时兜底保存）；刷新后等首屏布局完成再恢复，避免滚动范围未就绪时被截断

## [未发布] — 2026-11-23 — 用例生成新增 IMX728 故障测试步骤

### 变更 — 调整故障用例默认测试步骤

- **`frontend/src/utils/casegen/faultCases.ts`** — 默认步骤中的「查看模组名称 / 改为需要的模组名称」改为「查看配置名称 / 改为需要的配置名称」；清除故障命令改为 `<脚本> -i 9 -a 4c -n {fault_no} -c 1清除故障`

### 新增 — 故障测试支持按标签页选择用例使用的 Sensor

- **`frontend/src/components/casegen/FaultGenStep.tsx`** — 每个故障标签页内新增「用例使用的 Sensor」下拉，列出平台拓扑中已启用的相机（显示 Group / Link / Sensor / Sensor ID / 掩码）；选择结果写入 `FaultTestTabOptions.camera_key`，该标签页模板中的 `{sensorid}`、`{mask}` 以及生成用例的起流掩码都随之切换，未选择时仍回退到第一台已启用相机
- **`frontend/src/types/casegen.ts` / `frontend/src/utils/casegen/faultCases.ts`** — `camera_key` 从全局 `FaultTestOptions` 移至各标签页 `FaultTestTabOptions`；`selectFaultCamera()` 改为按相机 key 取相机，生成时逐标签页解析；旧草稿中的全局 `camera_key` 恢复时迁移到各标签页

### 变更 — 移除「生成『清除故障』步骤」开关

- **`frontend/src/components/casegen/FaultGenStep.tsx`** — 删除故障测试页面顶部的「生成『清除故障』步骤」勾选项及模板区相关提示
- **`frontend/src/types/casegen.ts` / `frontend/src/utils/casegen/faultCases.ts`** — 移除 `FaultTestOptions.clear_fault`；用例模板固定保留清除故障步骤与对应预期结果，旧草稿中的该字段在恢复时自动忽略

### 新增 — 故障单新增 IMX623

- **`frontend/src/types/casegen.ts`** — 新增 `IMX623_FAULT_CATALOG`：22 项故障名与 CDI 故障码对照（1~22 号），脚本默认路径 `./fault_simulation_623_qnx.sh`；追加到 `FAULT_CATALOGS`，故障测试标签页的故障单下拉中可直接选择
- **`frontend/src/utils/casegen/faultCases.ts`** — 内置默认模板按标签页所选故障单的 `script_path` 生成：默认步骤 / 前置条件中的注入脚本路径与 `{script}` 占位符都会随 IMX728 / IMX623 切换
- **`frontend/src/components/casegen/FaultGenStep.tsx`** — 页面说明文案补充 IMX623；模板预览按当前标签页故障单解析脚本路径

### 变更 — 故障测试标签页支持动态新增、重命名与选择故障单

- **`frontend/src/types/casegen.ts`** — `FaultTestTabOptions` 增加 `label` / `catalog`，标签页改为由配置动态生成（`FaultTabInstance`）；移除固定的 `FaultTestTabConfig` / `FAULT_TEST_TABS` / `findFaultTestTab`，未来新增故障单只需在 `FAULT_CATALOGS` 中追加，即可在标签页的故障单下拉中直接选择
- **`frontend/src/utils/casegen/faultCases.ts`** — 新增 `faultTabsOf()` / `nextFaultTabKey()` / `uniqueFaultTabLabel()`；`enabledFaultTabs()` / `selectedFaultItems()` 改为基于动态标签页实例；`normalizeFaultTestOptions()` 兼容旧草稿（旧标签 key 作为故障单标识并补全名称与所选故障单）
- **`frontend/src/components/casegen/FaultGenStep.tsx`** — 标签栏改为 `editable-card`：右侧「+」新建标签页，标签可关闭；每个标签页内可自定义名称、选择故障单、启用与勾选故障，切换故障单时保留在新故障单中仍然有效的故障号

### 新增 — 按故障清单批量生成故障注入用例

- **`frontend/src/types/casegen.ts`** — 新增 `TEST_TYPE_FAULT`（`故障上报`）、`FaultCatalogItem` / `FaultCatalog`、`IMX728_FAULT_CATALOG`（27 项故障名与 CDI 故障码对照）、`FaultTestOptions` 及默认值；`GeneratedCase` 增加 `requirement_id`
- **`frontend/src/types/casegen.ts`** — 新增 `FaultTestTabConfig` / `FAULT_TEST_TABS`：故障测试按标签页组织，每个标签对应一个故障清单并带有 `test_type`（当前均为「故障上报」，未来新增其它故障时追加标签即可）；`FaultTestOptions` 改为按标签页保存启用状态、勾选故障与模板
- **`frontend/src/utils/casegen/faultCases.ts`** — 新增故障用例生成：按启用标签页中勾选的故障号逐条生成用例（起流命令、注入命令 `-n <故障号>`、清除命令 `-n <故障号> -c`、预期结果含对应 `CDI_SENSOR_*_ERR` 故障码），同一相机的多条故障共用起流参数
- **`frontend/src/components/casegen/FaultGenStep.tsx`** — 新增「故障测试」步骤页，交互与功能测试一致：顶部标签栏点击切换故障类型，标签内独立启用、编辑模板并勾选故障项
- **`frontend/src/pages/casegen/CaseGenPage.tsx`** — 接入故障步骤（步骤序号随之后移），生成时把故障用例追加到结果并汇总提示；自动保存 / 恢复与「重置」一并处理故障配置
- **`frontend/src/utils/casegen/storage.ts`** — 自动保存数据增加 `faultOptions`
- **`frontend/src/components/casegen/CasePreviewStep.tsx`** — 预览列表补充 `故障上报` 类型颜色

### 变更 — 故障用例模板支持占位符自定义编辑

- **`frontend/src/types/casegen.ts`** — 新增 `FaultCaseTemplate` / `FaultCaseTemplatePatch`，`FaultTestTabOptions` 按标签页保存共享模板 `case_template` 与按故障号覆盖的 `fault_templates`
- **`frontend/src/utils/casegen/faultCases.ts`** — 新增 `DEFAULT_FAULT_CASE_TEMPLATE`、`FAULT_CASE_PLACEHOLDERS`（`{fault_no}` / `{error_code}` / `{script}` / `{i2c_bus}` / `{sensor_addr}` / `{observe_command}` / `{requirement_id}` 及相机占位符）与 `faultCaseTemplateOf()` / `effectiveFaultCaseTemplate()`；生成时逐条按模板替换占位符，单条覆盖优先于标签页共享模板
- **`frontend/src/types/casegen.ts` / `frontend/src/components/casegen/FaultGenStep.tsx`** — 故障清单只保留故障号与 CDI 故障码：移除 `FaultCatalogItem.name` 属性、故障表格的「故障名称」列、`{fault_name}` 占位符及界面文案中的故障名称；默认用例描述改为 `第{fault_no}号故障验证`
- **`frontend/src/utils/casegen/faultCases.ts`** — 恢复旧草稿时把模板中的 `{fault_name}` 自动替换为 `{error_code}`，避免生成结果残留未解析的占位符
- **`frontend/src/utils/casegen/faultCases.ts`** — 新增 `faultTabOptionsOf()` / `enabledFaultTabs()` / `normalizeFaultTestOptions()`：按标签页读取配置、筛选参与生成的标签，并把旧版单清单草稿迁移到标签页结构（旧 `selection.fault` 迁移为标签页启用状态）
- **`frontend/src/utils/casegen/faultCases.ts`** — 默认模板中的脚本路径 / I2C 总线 / Sensor 地址 / 观察指令 / nito 目录直接写成实际值（`./fault_simulation_728_qnx.sh`、`-i 9`、`-a 4c`、`df`、`./nito/`），用户可在模板中直接修改；占位符写法仍保留
- **`frontend/src/utils/casegen/faultCases.ts`** — 未自定义测试步骤 / 预期结果时，关闭「生成『清除故障』步骤」会同时去掉默认模板中的清除故障步骤与对应预期行（此前只去掉预期行）
- **`frontend/src/components/casegen/FaultGenStep.tsx`** — 每个标签页内新增用例模板编辑区：描述 / 前置条件 / 步骤 / 预期 / 优先级，占位符点击插入、步骤与预期实时预览、一键恢复默认；故障表格新增「编辑」入口，可对单条故障单独调整模板并恢复标签页共享模板
- **`frontend/src/components/casegen/FaultGenStep.tsx`** — 移除标签页底部的「生成结果预览」，只保留模板编辑区内的步骤 / 预期实时预览
- **`frontend/src/components/casegen/FaultGenStep.tsx`** — 全局启用开关改为标签页内的「参与本次生成」，移除 `FunctionalTestSelection.fault`；「生成『清除故障』步骤」仍为所有标签页共用
- **`frontend/src/components/casegen/FaultGenStep.tsx`** — 移除「故障注入脚本 / I2C 总线 / Sensor 地址 / 起流相机 / 观察指令 / 需求ID / --nito 目录」等独立配置项，这些参数直接在用例模板中编辑，不再需要在页面上单独设置

### 变更 — 导出的故障用例写入「故障测试」Sheet

- **`backend/app/api/casegen_routes.py`** — 新增 `FAULT_SHEET_NAME`、`_is_fault_case()`、`_partition_cases()`：按测试类型把用例分到功能 / 压力 / 稳定性 / 故障四类，故障用例写入「故障测试」Sheet；`_is_fault_case()` 同时识别以 `fault-` 开头的用例 key，未来新增其它故障测试类型时仍能正确归类；列映射补充「需求ID」，写入时填充 `requirement_id`
- **`backend/app/api/casegen_routes.py`** — `_build_case_ids()` 增加 `group_by_key` 参数：故障测试忽略每条用例各不相同的 `key`，按相机组合归组，编号为 `FT_001_01 … FT_001_27`；导出接口与响应增加 `fault_count`
- **`backend/tests/test_casegen_export_fault.py`** — 新增测试：故障用例识别与分类、写入模板「故障测试」Sheet（含需求ID、预期结果故障码）、编号归组、导出请求结构

- **`frontend/src/pages/casegen/CaseGenPage.tsx`** — 用例生成步骤条支持点击任意步骤跳转：向前跳转无需逐步点「下一步」，离开「基本信息」或跳到「Sensors 配置」及之后的步骤时仍会校验必填项与平台配置，校验失败则停留在当前步骤

---

## [未发布] — 2026-11-20 — 追加用例超出模板框线范围时自动补齐框线

### 修复 — 合并后新增行出现无边框的“裸行”

- **`backend/app/core/case_merger.py`** — 新增 `_reference_row_borders()`：在目标 Sheet 已有数据行中找一条带框线的行作为样式参考，优先取倒数第二条，避免把表格最后一行的收口底边（可能是 medium 粗线）复制到每条新增行
- **`backend/app/core/case_merger.py`** — 新增 `_fill_row_borders()`：只补齐新增行缺失的框线，已有框线保持不变；参考行也没有的边退回 thin 细线。目标 Sheet 还没有带框线的数据行（如新建 Sheet）时改用来源表参考
- **`backend/app/core/case_merger.py`** — 追加用例、`_copy_merged_ranges()` 之后调用上述逻辑，参考列取参考行框线列与内容列的并集

### 变更 — 用例模板新增「异常场景测试」Sheet

- **`docs/case.xlsx`** — 新增「异常场景测试」Sheet，与其他类别表结构一致
- **`backend/tests/test_case_merge.py`** — 新增框线补齐用例；`test_merge_creates_sheet_when_target_category_missing` 先移除模板中的「异常场景测试」，保证仍能覆盖“目标 Sheet 缺失时新建”的分支

---

## [未发布] — 2026-11-20 — 跟随型命令转入后台，用例结束统一收集日志

### 变更 — slog2info -W / journalctl -f / tail -f 不再占住前台终端

- **`backend/app/core/command_parser.py`** — 新增 `is_follow_command()`：识别 `slog2info -w/-W`、`journalctl -f`、`dmesg -w`、`tail -f/-F` 等持续输出、不会自行退出的命令，供执行器转入后台
- **`backend/app/core/terminal_session.py`** — 新增 `launch_background()`：在 `set -m` 下后台运行（独立进程组便于整组结束），stdin 指向 `/dev/null` 防止后台作业读终端被挂起，输出重定向到板端临时文件，返回 pid
- **`backend/app/core/terminal_session.py`** — 新增 `probe_line_buffered()` / `grep_supports_line_buffered`：终端建立时探测板端 `grep` 是否支持 `--line-buffered`
- **`backend/app/core/executor_adapter.py`** — 跟随型命令转后台后立即返回，用例结束时结束进程组、只取回末尾 512KB 日志写入该终端日志分段，再删除板端临时文件
- **`backend/app/core/executor_adapter.py`** — 输出重定向到文件时 `grep` 默认块缓冲、结束进程会丢日志；管道段的 `grep/egrep/fgrep` 自动注入 `--line-buffered`（只改段首 token）
- **`backend/app/core/executor_adapter.py`** — 收尾统一走 `_cleanup()`：先退出前台程序，再结束后台跟随命令、取回日志，最后关闭会话；`ManualConfirmFailed` 异常分支同样执行

---

## [未发布] — 2026-11-20 — 前台程序启动失败时快速判定并跳过后续交互

### 修复 — 命令没跑起来时不再逐个等满超时

- **`backend/app/core/terminal_session.py`** — `launch()` 返回值改为 `(exit_code, output)`：退出码标记并入等待条件，程序在启动窗口内就已退出（命令不存在、无执行权限、路径写错等）时立即返回退出码，并置 `start_failed=True`，不再空等整段 `timeout`
- **`backend/app/core/terminal_session.py`** — 新增 `start_failed` 状态、`pending_marker` 属性与 `mark_foreground_exited()`；`reset()` 一并清空这些状态。`read_until()` 在会话已关闭 / EOF / 通道断开时立即返回，不必等满超时
- **`backend/app/core/executor_adapter.py`** — 前台程序在启动窗口内退出时记录 `exit_code` 与末尾输出并标记失败，后续交互步骤不再发送
- **`backend/app/core/executor_adapter.py`** — `nvsipl_input` 步骤遇到 `start_failed` 直接跳过；前台程序未在运行时忽略 `q`，避免它被 shell 当命令执行并白等超时
- **`backend/app/core/executor_adapter.py`** — 交互输入把挂起的退出码标记并入等待条件：程序中途退出时标记出现即返回，跳过剩余输入并回收退出码；收尾阶段跳过已失败的终端
- **`backend/app/core/executor_adapter.py`** — `_nvsipl_has_real_error()` 增加 `cannot execute`、`No such file or directory`、`command not found`、`not found`、`Permission denied` 等硬错误模式，并统一忽略大小写，故障测试与正常测试共用

---

## [未发布] — 2026-11-20 — SSH 配置页改为测试连接即同步

### 变更 — 移除「保存配置」，测试连接直接同步后端

- **`frontend/src/pages/SSHConfigPage.tsx`** — 删除「保存配置」按钮及 `handleSave`；页面只保留「测试连接」作为提交入口。表单改动仍自动保存到本地配置，点击「测试连接」时用表单当前值测试并同步到后端
- **`backend/app/api/routes.py`** — `POST /ssh/test` 在连接成功后除更新 `session.ssh_config` 外，同步写入 `config_store`（`ssh_config`），后端重启后仍沿用这份已测试通过的配置

### 变更 — 配置名称并入表单，移除「重命名」

- **`frontend/src/pages/SSHConfigPage.tsx`** — 移除「重命名」按钮及其弹窗；表单首项新增「配置名称」，与连接参数一起 600ms 防抖自动保存到当前选中的本地配置，下拉框中的名称同步更新
- 重名校验排除自身；自动保存时若名称为空或与他份重名，则保留原名，字段校验会在表单内提示
- 「新建配置」不再弹窗询问名称，直接以「配置 N」创建空白配置并选中，名称随即可在表单中修改
- 「测试连接」只提交 `SSHConfig`，表单中仅本地使用的 `name` 字段在提交前被剔除

### 变更 — 移除「保存到本地」，表单改动自动保存

- **`frontend/src/pages/SSHConfigPage.tsx`** — 删除「保存到本地」按钮；表单任意字段变化后 600ms 防抖写回当前选中的本地配置。载入/切换配置等程序化赋值通过抑制标记跳过自动保存，避免误写；切换/删除前取消未触发的自动保存，防止闭包写入旧数据
- 同步到后端通过「测试连接」完成

### 变更 — 「另存为」改为「新建配置」，表单需选中配置才可编辑

- **`frontend/src/pages/SSHConfigPage.tsx`** — 「新建配置」直接创建一份空白配置（默认直连、端口 22、超时 30）并自动选中，名称自动避开重名；不再复制当前表单内容
- 表单设为 `disabled={!activeProfile}`：未选中（或未新建）本地配置时表单不可编辑，「测试连接」一并置灰，并在表单上方提示先新建/选择配置
- **`frontend/src/utils/sshConfigStorage.ts`** — 新增 `EMPTY_SSH_CONFIG` 常量；移除不再使用的 `suggestSSHProfileName`

---

## [未发布] — 2026-11-20 — 修复历史日志关键输出块吞掉后续日志

### 修复 — 关键输出块结束判断

- **`frontend/src/components/CollapsibleLogText.tsx`** — 时间戳正则 `LOG_LINE_PREFIX_RE` 的量词少写 `}`（`\d{1,2]`），导致没有汇总行的新日志无法识别下一条日志，第一个关键输出块会把后面全部内容纳入自身；收起时看起来像“把下面所有内容都收起了”。修正为 `\d{1,2}` 后，每个关键输出块只包含自己的明细行

---

## [未发布] — 2026-11-20 — 修复 AI 判定日志重复输出

### 修复 — case_complete 不再重复追加已推送的判定原因

- **`frontend/src/hooks/useWebSocket.ts`** — 收到 `case_complete` 时，如果 `reason` 已出现在最近的日志中（后端判定阶段已逐行推送），就不再追加；按 `; ` 拆分后逐段比对，兼容缩进与空格差异，避免同一条 AI 判定原因显示两次

---

## [未发布] — 2026-11-20 — 命令关键输出不再限制行数

### 变更 — 关键输出展示全部命中行

- **`backend/app/core/executor_adapter.py`** — `_extract_key_output_lines` 的 `max_lines` 默认改为 `None`，输出所有命中的关键行，不再追加 `... (total N lines, showing M key lines)` 汇总提示；显式传入 `max_lines` 时仍按原逻辑截断
- 历史日志中的旧汇总行仍可被前端折叠组件识别并切块，不影响回看

---

## [未发布] — 2026-11-20 — 命令关键输出改为可折叠

### 变更 — 执行日志中的关键输出默认折叠

- **`frontend/src/components/CollapsibleLogText.tsx`** — 新增日志折叠组件：识别 `命令关键输出:` 日志并拆分为标题与明细，默认折叠，点击「展开（N 行）」/「收起」切换；历史日志按 `[时间] [level]` 行与 `... (total N lines, showing M key lines)` 汇总行切块
- **`frontend/src/pages/LogViewer.tsx`** — 实时日志与历史日志内容中的命令关键输出块使用折叠组件
- **`frontend/src/pages/Dashboard.tsx`** — 首页「执行日志」面板同样支持命令关键输出折叠

---

## [未发布] — 2026-11-20 — 命令关键输出从 15 行改为 5 行

### 变更 — 精简执行日志中的命令关键输出

- **`backend/app/core/executor_adapter.py`** — `_extract_key_output_lines` 默认 `max_lines` 由 15 调整为 5；执行日志中的「命令关键输出」最多展示 5 条命中的关键行，仍保留末尾的 `... (total N lines, showing 5 key lines)` 汇总提示

---

## [未发布] — 2026-11-20 — 执行日志页：历史记录可折叠、实时日志框可拖动调整

### 变更 — 调整「执行日志」页面布局

- **`frontend/src/pages/LogViewer.tsx`** — 实时执行日志移到页面上方；历史执行日志改为 `Collapse` 折叠面板并放在实时日志下方，默认折叠，标题显示记录数量
- **`frontend/src/pages/LogViewer.tsx`** — 实时日志显示框新增底部拖拽条，按住上下拖动调整高度（最小 160px，最大不超过窗口可视高度），双击拖拽条恢复默认 360px；调整后的高度写入 `localStorage`，刷新页面后保持

---

## [未发布] — 2026-11-20 — 去掉判定日志中的「规则引擎已弃用」文案

### 变更 — AI 判定日志与转人工原因精简

- **`backend/app/core/executor_adapter.py`** — 判定日志改为 `AI 判定中...` / `=== AI 判定 ===`；AI 未启用、调用失败、未返回结果、状态异常等转人工原因去掉「规则引擎已弃用」，只保留具体原因与「需人工确认」
- **`backend/app/ai/prompts/judge.py`** — 判定 Prompt 说明同步移除该表述，避免 AI 判定理由里复述

---

## [未发布] — 2026-11-19 — 修复重新判定后板端日志与 AI 证据行消失

### 修复 — 重新判定不再覆盖备注中的执行日志

- **`backend/app/core/remarks.py`** — `compose_remark` 在重建 AI 判定段时，若日志文件缺失（草稿恢复 / 历史导入的日志只存在备注中），回退使用兜底备注里的 `--- 执行日志 ---` 段，不再直接丢弃；`build_log_remark_from_case` 同样从备注日志段回退，保证写入结果 Excel / 下载时备注列仍有日志
- **`backend/app/api/routes.py`** — 重新判定返回的 `case_patch` 在 `log_file` 非空时一并带回，前端可继续按路径读取板端日志
- **`frontend/src/pages/Dashboard.tsx`** — 「实际结果」栏展示 BUG 列内容时补齐 `ai_evidence`（或备注中的 `- 证据` 行），修复重新判定后 `judgment` 覆盖备注、导致 AI 证据行不再显示的问题
- **`backend/tests/test_remarks.py`** — 新增无 `log_file` 时重新判定保留备注日志、剔除旧 AI 段保留日志、备注列回退日志与优先日志文件四条回归测试

---

## [未发布] — 2026-11-19 — 执行日志持久化与历史回看

### 新增 — 执行日志记录（不是板端原始日志）

- **`backend/app/core/execution_log.py`** — 新建执行日志落盘模块：每次执行写入 `logs/execution/<时间>_<run_id>.log`，并用同名 `.json` 保存 run_id、用例文件、测试人员、开始/结束时间与状态；提供列表、按 run_id 查找、读取、删除能力
- **`backend/app/websocket/session_ws_manager.py`** — `send_log` 在推送给浏览器的同时写入本次执行日志文件；新增 `start_execution_log` / `end_execution_log`，执行开始创建、结束收尾
- **`backend/app/api/routes.py`** — `_run_execution` 启动时记录、`finally` 中关闭执行日志；新增 `GET /logs/execution`（历史列表）与 `GET /logs/execution/content`（按 path / run_id 读取全文）
- **`frontend/src/pages/LogViewer.tsx`** — 「执行日志」页新增历史执行日志表格（开始时间、状态、用例文件、测试人员、大小），可查看全文并下载文本；原有实时执行日志保留
- **`frontend/src/api/axios.ts`** / **`frontend/src/types/index.ts`** — 新增 `listExecutionLogs`、`getExecutionLogContent` 与 `ExecutionLogRecord` 类型
- **`backend/tests/test_execution_log.py`** — 覆盖日志落盘、元数据、列表排序、按 run_id 查找、删除与孤儿元数据跳过

---

## [未发布] — 2026-11-19 — 手动高亮去掉按内容选择，只保留按行号选择

### 变更 — 手动选择高亮行统一按行号

- **`frontend/src/components/CaseLogModal.tsx`** — 移除「按行号 / 按内容」切换（`Segmented`）与按内容匹配逻辑；点击或拖拽只按 `[终端标签, 行号]` 标识选择日志行，选择模式下行号列常显；工具栏、图例文案统一为「按行号匹配」
- **`frontend/src/components/CaseLogModal.tsx`** — 旧记录只保存了内容快照、没有行号时，日志加载后把命中的行转换为行号标识再展示，之后新增 / 清除选择都按行号保存，不再保留按内容选择入口
- **`frontend/src/api/axios.ts`** / **`frontend/src/pages/Dashboard.tsx`** — `ManualEvidencePayload` 去掉 `mode`，保存手动高亮固定发送 `manual_evidence_mode: "line"`；保存提示与同步到草稿的高亮方式统一为按行号
- **`backend/app/core/test_case.py`** / **`backend/app/api/routes.py`** — 手动高亮默认方式改为 `line`；日志变更 / 新一轮执行重置 / 会话同步时同样使用 `line`，接口仍接受旧的 `content` 便于兼容历史数据

---

## [未发布] — 2026-11-19 — 修复部分执行时未选用例 BUG 列被清空

### 修复 — 结果保存只清理本次执行用例的旧判定

- **`backend/app/core/excel_handler.py`** — `save_results` 新增 `executed_case_keys` 参数：传入后只清理这些用例上一次的系统 `[AI判定]` 内容；未执行用例的 BUG 列保持原样，不再因为本次没有 AI 判定而被置空
- **`backend/app/api/routes.py`** — 执行结束保存结果时传入本次实际执行过的 `case_key`（按执行结果对齐），修复「只勾选一条用例执行」时其它未选用例 BUG 列被一并清空的问题
- **`backend/tests/test_execution_log_draft.py`** — 新增「只执行部分用例时未执行用例 BUG 列保留」回归测试

---

## [未发布] — 2026-11-19 — 修复草稿箱导出再导入后无法恢复到用例

### 修复 — 草稿导入后的用例匹配

- **`frontend/src/utils/executionDraft.ts`** — 导出文本在用例头后新增 `用例标识：Sheet:行号:用例ID`，导入时解析回 `case_key`；之前只导出 case_id，重新导入后跨表 / 重复用例 ID 的工作簿无法定位到正确行
- **`frontend/src/utils/executionDraft.ts`** — `findCaseForDraftItem` 对旧版导出（没有 `用例标识`）在 case_id 重复时依次用来源表 / 用例描述 / 执行状态区分；仍无法唯一确定时返回未匹配，避免恢复到错误的行
- **`frontend/src/pages/Dashboard.tsx`** / **`frontend/src/api/axios.ts`** — 恢复请求改为只发送前端已匹配的用例，并带上解析后的 `case_key` 与 `description`，保证前后端定位到同一行
- **`backend/app/api/routes.py`** — 恢复接口的 `RestoreCaseLogItem` 新增 `description`；case_id 重复时依次按来源表 / 描述 / 执行状态区分，无法唯一确定则计入 `missing`，不再默认写到第一条重复用例
- **`backend/tests/test_execution_log_draft.py`** — 新增重复 case_id 按描述恢复、以及描述也相同则跳过恢复两条测试

### 修复 — 导入后实际结果 / AI 判定丢失

- **`frontend/src/utils/executionDraft.ts`** — 导出文本新增 `实际结果：`、`AI判定：`、`AI证据：`、`手动证据：`、`手动高亮：`、`高亮方式：`；多行文本用 JSON 字符串单行保存，避免破坏终端分段
- **`frontend/src/utils/executionDraft.ts`** — `parseDraftPlainText` 解析上述字段并写回草稿用例：实际结果与 AI 判定进入恢复补丁的 `actual_result` / `judgment`，同时还原 AI / 手动证据与高亮方式；「实际结果」栏不再因导入丢失 AI 判定内容
- 旧版已导出的 txt 没有这些字段，无法补回实际结果 / AI 判定；需要用新版重新导出（原草稿仍在浏览器草稿箱时可直接重新导出）

---

## [未发布] — 2026-11-19 — 下载结果支持只覆盖选中的用例

### 新增 — 按勾选用例导出结果

- **`frontend/src/pages/Dashboard.tsx`** — 「下载结果」弹窗新增「只覆盖选中的用例（当前勾选 N 条）」选项：勾选后忽略用例表选择，只提交当前列表勾选的用例；未勾选用例时该选项与「下载」按钮均不可用，并提示先勾选用例
- **`frontend/src/pages/Dashboard.tsx`** — 选中模式下的下载文件名追加 `_选中N条用例`，进度提示按选中用例数显示；「数据统计」页重新生成选项在该模式下禁用
- **`frontend/src/api/axios.ts`** — `downloadResults` 新增 `caseKeys` 参数，非空时以 `case_keys` 传给后端
- **`backend/app/api/routes.py`** — `download_results` 新增 `case_keys` 查询参数（优先于 `sheets`）：按 `case_key` 在结果工作簿中定位用例，缺失的 key 返回 400；只对选中用例执行会话编辑写回、BUG 列证据行清理、备注图片清理与日志 / 截图嵌入，其它用例行与工作表保留原内容；选中模式下不登记 BugList、不重新生成「数据统计」页
- **`backend/app/core/excel_handler.py`** — `clear_result_images` / `strip_evidence_from_judgment` / `embed_log_images` / `embed_case_images` 新增 `case_keys` 过滤参数，处理范围可精确到单条用例

### 修复 — 选中用例的测试人员 / 测试日期

- **`backend/app/api/routes.py`** — 下载副本的「测试人员」不再要求必须有执行日志：只要用例已执行（有日志或状态非 NT）就写入工作区配置的测试人员，未配置时回退到会话里记录的测试人员；修复了选中用例已判定但旧结果文件没有日志文本时测试人一栏不更新的问题
- **`backend/app/api/routes.py`** — 「测试日期」统一精确到天：`_date_only_text` 兼容 `2026-11-19 09:30:00` / `2026/11/17 08:00` / `2026年11月19日` 等写法；已执行用例按「会话执行日期 → 已有日期 → 当天」补全，未执行用例的已有日期也规整为日期，不再带时间
- **`backend/tests/test_execution_log_draft.py`** — 新增「已判定但无日志仍更新测试人员」「未执行用例已有斜杠日期规整到天」两条回归测试

---

## [未发布] — 2026-11-19 — 日志草稿箱支持导入导出的日志 txt

### 新增 — 从导出的日志文本恢复草稿

- **`frontend/src/utils/executionDraft.ts`** — 新增 `parseDraftPlainText`，把草稿箱导出的 txt 反向解析为 `ExecutionDraft`：头部还原草稿名 / 工作簿 / 保存时间，用例按 `===== 用例ID [状态] =====` 分段，日志按 `----- 终端 -----` 还原终端分段，末尾运行日志还原为 `LogEntry`；用例按 `case_id` 匹配，实际结果 / AI 判定等导出文本中没有的字段按空值处理
- **`frontend/src/utils/executionDraft.ts`** — 解析失败（没有可识别的用例日志）时返回 `null`；运行日志时间戳解析失败时用草稿保存时间兜底
- **`frontend/src/components/ExecutionDraftBox.tsx`** — 草稿箱顶部新增「导入日志」按钮（`Upload`，支持 `.txt` / `.log` / `.text`）：读取文件并保存为新草稿，刷新列表并提示导入的草稿名与用例数；提示文案补充「可以导入之前导出的日志 txt」

---

## [未发布] — 2026-11-19 — 执行日志草稿箱迁移到 IndexedDB

### 变更 — 日志草稿的浏览器存储

- **`frontend/src/utils/executionDraft.ts`** — 草稿改存 IndexedDB（数据库 `automatedTest.executionLogDrafts`、对象仓库 `drafts`，按草稿 `id` 单条读写）；日志全文很容易超过 localStorage 的 5MB 配额，迁移后不再受此限制
- **`frontend/src/utils/executionDraft.ts`** — 启动时异步把 IndexedDB 全量草稿预热到内存缓存，`getAllExecutionDrafts()` 仍保持同步读取；缓存就绪后派发 `execution-drafts-changed` 事件，Dashboard 徽标与草稿箱列表自动刷新
- **`frontend/src/utils/executionDraft.ts`** — 首次加载自动迁移旧版 localStorage 草稿：仅导入 IndexedDB 中不存在的草稿，成功后删除旧 key；浏览器不支持 IndexedDB 时降级回 localStorage
- **`frontend/src/utils/executionDraft.ts`** — `saveExecutionDraft` / `deleteExecutionDraft` / `renameExecutionDraft` / `syncCaseEditToDrafts` / `autoSaveCurrentExecution` 改为异步写入，并保持自动草稿最多保留 10 条；单条写入失败不会改动内存缓存
- **`frontend/src/components/ExecutionDraftBox.tsx`** / **`frontend/src/pages/Dashboard.tsx`** / **`frontend/src/hooks/useWebSocket.ts`** — 同步更新调用方为 `await` / `void ... .then(...)`，保存失败的提示改为「浏览器存储不可用或空间不足」

---

## [未发布] — 2026-11-19 — 备注列图片留白 / 间距改为工作区配置

### 变更 — 备注列图片排版的配置化

- **`backend/app/core/test_case.py`** — `WorkspaceConfig` 新增 `remark_image_padding`（备注图片四周留白，默认 12px）与 `remark_image_gap`（同一单元格内多张图片的间距，默认 16px）
- **`backend/app/core/excel_handler.py`** — `embed_log_images` / `embed_case_images` 新增 `pad` / `gap` 参数，缺省取类常量 `REMARK_IMAGE_PAD` / `REMARK_IMAGE_GAP`；列宽、行高、图片锚点全部改用传入值，设为 0 时图片贴着单元格排列
- **`backend/app/api/routes.py`** — 下载结果时按工作区配置传入 `pad` / `gap`（留白 0~60、间距 0~100）；`_workspace_int` 修正为「0 是有效值」，只有缺失 / 空值才回退默认，配置为 0 不会被默认值覆盖
- **`frontend/src/pages/WorkspaceConfigPage.tsx`** / **`frontend/src/types/index.ts`** — 工作区配置页「日志备注配置」新增「备注图片留白 (px)」「备注多图间距 (px)」两个输入项
- **`backend/tests/test_embed_case_images.py`** — 新增按配置排列日志图片 / 截图、以及 `pad = gap = 0` 场景的单测

---

## [未发布] — 2026-11-19 — 备注列图片留白与图片间距加大

### 变更 — 下载结果中「备注」列图片的排版

- **`backend/app/core/excel_handler.py`** — 新增类常量 `REMARK_IMAGE_PAD = 12` / `REMARK_IMAGE_GAP = 16`（像素），统一日志图片与用例截图的排版：图片距单元格上、左各 12px，列宽按「图片宽 + 左右各 12px」计算、行高按「顶部留白 + 各图高度 + 图间距 + 底部 12px」计算，右侧与下方留白与左侧、上方一致；同一单元格内多张日志图片 / 截图之间由 4~6px 增至 16px
- **`backend/app/core/excel_handler.py`** — `embed_log_images` 返回的底部偏移改为含顶部留白的图片实际底边，截图在此基础上再加一个图间距排列，日志图片与截图不再贴在一起；`embed_case_images` 仅在图片宽于现有列宽时加宽备注列，图片全部读取失败时不再改动行高与列宽
- **`backend/tests/test_embed_case_images.py`** — 新增留白与间距单测：左侧留白、顶部留白、截图间距、底部行高与列宽

---

## [未发布] — 2026-11-19 — 下载结果报告时补全测试日期

### 新增 — 下载结果的测试日期

- **`backend/app/api/routes.py`** — `_apply_session_case_edits` 新增「测试日期」写回：已执行用例（有执行日志或状态非 NT）在下载副本中补全日期，优先用会话里的执行日期；会话没有记录（如草稿恢复、重新上传工作簿）时用当天日期，工作簿已有的带时间日期统一规整为 `YYYY-MM-DD`，精确到天
- **`backend/app/core/excel_handler.py`** — 新增 `update_test_date`，按列映射写入「测试日期」栏；`update_case_status` 同步更新内存用例的 `actual_result`，保证状态写回后内存与单元格一致
- **`backend/tests/test_execution_log_draft.py`** — 新增测试日期补全（会话日期 / 当天日期兜底 / 已有时间戳规整 / 未执行不填）四条单测

---

## [未发布] — 2026-11-19 — BugList 改为下载报告时生成，测试人员取工作区配置

### 变更 — BugList 登记时机与测试人员来源

- **`backend/app/api/routes.py`** — 执行结束不再把失败用例登记到 BugList统计 页，执行阶段只回写用例结果；改为在 `/download/results` 生成下载副本时，由会话用例（含 AI 生成的 Bug 描述 / Severity）登记到下载副本的 BugList 页，原结果文件保持不变；登记成功后同步刷新会话 BugList，供前端页签展示
- **`backend/app/api/routes.py`** — 新增 `_sync_bug_list_for_download`：按会话中的失败用例合并 BugList 条目，Tester 取工作区配置的 `tester_name`，Version 取工作区配置的 `test_version`（未配置时回退用例字段）；BugList 生成失败不影响结果文件下载
- **`backend/app/core/bug_list.py`** — `sync_failed_cases_to_bug_list` / `build_bug_entry` 的 Tester 列改为工作区配置优先：传入的 `tester` 非空时覆盖用例自带测试人员，已存在的 Bug 条目也会刷新为该值；未配置时才回退用例的 `tester`
- **`frontend/src/pages/Dashboard.tsx`** — 下载结果成功后重新拉取 `/buglist`，BugList 页签立即展示本次下载登记的数据
- **`frontend/src/api/axios.ts`** / **`frontend/src/hooks/useWebSocket.ts`** — 更新注释：BugList 在下载结果报告时登记
- **`backend/tests/test_buglist_parser.py`** — 新增工作区测试人员优先级与下载时登记 BugList 的单测

---

## [未发布] — 2026-11-18 — 测试用例界面支持按状态过滤

### 新增 — 状态筛选下拉框

- **`frontend/src/pages/Dashboard.tsx`** — 「测试用例」卡片右上角新增多选「按状态筛选」下拉框与「筛选」按钮：选择状态后不立即刷新表格，点击「筛选」才按当时状态生成行快照并应用；之后用例状态变化（例如开始执行后 Fail 被重置为 NT）不会把行移出当前结果，只有再次点击「筛选」才按最新状态重新计算；已生效筛选时按钮仍可点击用于刷新快照，选项按当前表页（及测试类型筛选结果）动态列出状态与数量，可与测试类型筛选叠加使用；应用后回到第一页，切换页签 / 重新上传时清空状态筛选
- **`frontend/src/pages/Dashboard.tsx`** — 「按状态选择」快捷操作的统计范围保持不变（按测试类型筛选后的全部用例统计），不会因为已启用状态筛选而无法选中其它状态

---

## [未发布] — 2026-11-18 — 下载结果时显示逐用例导出进度

### 新增 — 下载弹窗进度条

- **`frontend/src/pages/Dashboard.tsx`** — 下载结果时在弹窗内显示进度条：展示当前阶段（准备 / 渲染日志图片 / 嵌入用例截图 / 生成统计页 / 保存）、已处理用例数与总用例数、当前正在处理的用例编号；点击「下载」时生成一次性 `progress_token`，只接收本次下载的进度消息
- **`frontend/src/api/axios.ts`** — `downloadResults` 新增 `progressToken` 参数，随 `progress_token` 查询参数下发
- **`frontend/src/hooks/useWebSocket.ts`** / **`frontend/src/stores/useStore.ts`** / **`frontend/src/types/index.ts`** — 新增 `download_progress` WebSocket 消息与 `downloadProgress` 状态
- **`backend/app/api/routes.py`** — `/download/results` 新增 `progress_token` 参数；工作簿准备、日志图片 / 用例截图嵌入移到线程池执行，避免阻塞事件循环导致进度消息延迟，并通过 `download_progress` 推送准备、逐用例处理、生成统计页、保存、完成等阶段；导出失败回退原文件的行为保持不变
- **`backend/app/websocket/session_ws_manager.py`** — 新增 `send_download_progress`
- **`backend/app/core/excel_handler.py`** — `embed_log_images` / `embed_case_images` 新增 `progress_callback`，按「当前序号 / 用例总数 / 用例编号」逐用例回调

---

## [未发布] — 2026-11-18 — 日志图片不再把 ERROR 行标红

### 变更 — 仅保留成功行绿色标注

- **`backend/app/core/log_image.py`** — 下载结果时渲染的日志图片不再按 `ERROR` / `ERR` / `FATAL` / `PANIC` / `FAIL` / `ASSERT` 及中文「失败」把日志行标红，避免被测程序正常的 ERROR 输出被误认为失败；AI 证据高亮与 `SUCCESS` 行的绿色标注保持不变

---

## [未发布] — 2026-11-18 — AI 证据高亮不再把证据行的一小段日志当成证据

### 修复 — 公共前缀误高亮

- **`frontend/src/components/CaseLogModal.tsx`** / **`backend/app/core/log_image.py`** — AI 证据匹配从「双向包含」收紧为「日志行包含证据」：此前证据行是 `nvsipl_camera: ERROR: LOCAL SER ERROR: ...` 时，仅含公共前缀 `nvsipl_camera: ERROR:` 的其它日志行也会被当成证据高亮；现在只有实际日志行包含完整证据时才高亮（带时间戳等前缀的日志行仍可命中），弹窗与下载的日志图片行为一致

---

## [未发布] — 2026-11-18 — 下载结果可只更新指定用例表

### 新增 — 保留原工作簿，仅更新选中的用例表

- **`frontend/src/pages/Dashboard.tsx`** — 点击「下载结果」改为打开弹窗：勾选要更新结果的用例表（默认全选，可全选 / 清空 / 仅当前页签），并选择是否重新生成「数据统计」页；只勾选部分用例表时文件名带表名，下载文件仍保留原工作簿的全部工作表
- **`frontend/src/api/axios.ts`** — `downloadResults` 新增 `sheets` 参数，数组以重复 query key 下发（`sheets=故障测试&sheets=功能测试`）
- **`backend/app/api/routes.py`** — `/download/results` 新增 `sheets` 查询参数：校验表名属于当前工作簿的用例表；只对这些表应用会话编辑、BUG 证据清理、日志图片与用例截图，其它工作表及「数据统计」页保持原样；非法表名返回 400 并列出可选用例表
- **`backend/app/core/excel_handler.py`** — `clear_result_images` / `embed_log_images` / `embed_case_images` / `strip_evidence_from_judgment` 新增 `sheet_names` 范围参数，支持按用例表限定修改范围

---

## [未发布] — 2026-11-18 — 上传用例不再自动全选

### 变更 — 用例默认不勾选

- **`backend/app/core/excel_handler.py`** — 移除「功能测试 Sheet 默认全部选中」逻辑，新上传（含修改后重新上传）的所有用例 `selected` 统一默认为 `False`，由用户在表格中手动勾选后再执行

---

## [未发布] — 2026-11-17 — 手动高亮支持「按行号 / 按内容」两种匹配方式

### 变更 — 重复行不再误高亮

- **`frontend/src/components/CaseLogModal.tsx`** — 新增「按行号 / 按内容」切换（`Segmented`）：按行号用 `[终端标签, 行号]` 标识精确选中某一行，内容相同的其它行不会被一起高亮，选择模式下行号列可见；按内容沿用整行文本匹配；按行号保存时自动解析选中行的内容快照供下载日志图片使用；切换方式会放弃未保存的选择
- **`frontend/src/index.css`** — 新增 `.case-log-line-no` 行号列样式
- **`backend/app/api/routes.py`** — `CaseUpdateRequest` 新增 `manual_evidence_lines` / `manual_evidence_mode`；按行号标识去重保存（上限 2000），mode 仅接受 `line` / `content`；编辑日志内容时清空手动高亮（行号已失效）并重置为 `content`；`restore-logs`、新一轮执行重置、结果同步均带上两个新字段
- **`backend/app/core/test_case.py`** — `TestCase` 新增 `manual_evidence_lines` / `manual_evidence_mode` 并加入 `to_dict`
- **`frontend/src/api/axios.ts`** — `updateCaseManualEvidence` 改为提交 `ManualEvidencePayload`（mode / lines / contents）
- **`frontend/src/types/index.ts` / `frontend/src/utils/executionDraft.ts`** — 类型与草稿记录、恢复补丁、编辑同步补齐两个新字段
- **`frontend/src/pages/Dashboard.tsx`** — 手动高亮保存改用 payload，同步用例、弹窗与草稿；编辑日志后同步清空的手动高亮

---

## [未发布] — 2026-11-17 — 日志弹窗可手动选择高亮行（覆盖 AI 证据）

### 新增 — 手动校正日志高亮

- **`frontend/src/components/CaseLogModal.tsx`** — 新增「手动选择高亮行」模式：点击日志行切换高亮，按整行精确匹配（同一行在多个终端出现一起高亮）；手动选择非空时覆盖 AI 证据，工具栏显示已选行数、「未保存」状态、「保存高亮」与「清除手动高亮」；关闭弹窗或进入「编辑实际结果与日志」前自动保存未保存的选择
- **`frontend/src/index.css`** — 新增 `.case-log-select-line`：可点击行的手型光标与虚线描边
- **`backend/app/api/routes.py`** — `CaseUpdateRequest` 新增 `manual_evidence`（按日志图片规则归一化空白、去重，上限 1000 行，空数组表示恢复 AI 证据）；`POST /cases/restore-logs` 支持写入 `manual_evidence`；新一轮执行重置选中用例时清空；下载结果嵌入日志图片时手动高亮优先于 `ai_evidence`
- **`backend/app/core/test_case.py`** — `TestCase` 新增 `manual_evidence` 字段并加入 `to_dict`
- **`frontend/src/api/axios.ts` / `frontend/src/types/index.ts`** — 新增 `updateCaseManualEvidence` 接口与 `manual_evidence` 类型
- **`frontend/src/utils/executionDraft.ts`** — 草稿用例记录与恢复补丁带上 `manual_evidence`，编辑同步时一并写回
- **`frontend/src/pages/Dashboard.tsx`** — 日志弹窗传入当前手动高亮行并接入保存回调；保存成功后同步会话用例、弹窗与当前工作簿草稿

---

## [未发布] — 2026-11-17 — 可在执行测试页直接编辑实际结果与执行日志

### 新增 — 「BUG」列文本与日志均可手动修正

- **`frontend/src/components/CaseResultLogEditModal.tsx`（新增）** — 实际结果 + 执行日志双文本框编辑弹窗，说明保存后写回的位置
- **`frontend/src/pages/Dashboard.tsx`** — 「实际结果」单元格新增编辑按钮（执行中禁用）；日志弹窗（`CaseLogModal`）底部新增「编辑实际结果与日志」入口；抽出 `getCaseResultText` 统一单元格展示文本（BUG 列 → 备注 AI 区块 → 原备注）
- **`frontend/src/components/CaseLogModal.tsx`** — 新增可选 `onEdit`，提供时显示编辑入口
- **`frontend/src/api/axios.ts`** — 新增 `updateCaseResultLog`：提交 `result_text` 与（仅在修改时提交的）`log_text`
- **`backend/app/api/routes.py`** — `CaseUpdateRequest` 新增 `result_text` / `log_text`；`result_text` 写回 `judgment` 并按其中的「- 证据」行刷新 `ai_evidence`；`log_text` 经新增的 `_write_case_log_files` 写回聚合日志、按终端日志文件与 `terminals.json` 清单（无终端分段时删除旧终端文件），同时重建备注中的日志段
- **`frontend/src/utils/executionDraft.ts`** — 新增 `syncCaseEditToDrafts`：保存成功后把判定、证据与日志同步到当前工作簿最近的草稿，恢复草稿时不再拿到编辑前的内容
- **`frontend/src/pages/BoardLogPage.tsx`** — 当前用例信息卡移到日志区域下方，先看日志再看用例信息

---

## [未发布] — 2026-11-17 — 结束执行立即强制停止，不再等当前用例跑完

### 变更 — 停止按钮直接取消后台执行任务

- **`backend/app/core/session_store.py`** — `SessionState` 新增 `execution_task`，保存后台执行任务句柄
- **`backend/app/api/routes.py`** — `start_execution` 保存任务句柄；`_run_execution` 新增 `asyncio.CancelledError` 分支：标记 stopped、保存已执行部分的历史记录、广播 `execution_stopped`，`finally` 统一复位 `is_running` / `_stop_requested` / `executor` / `execution_task`；SSH 连接期间收到停止指令时不再启动任何用例，直接收尾
- **`backend/app/main.py`** — `stop_execution` 消息置 `_stop_requested`、调用 `executor.stop()` 并 `task.cancel()`，不再等待当前步骤 / 当前用例自然结束；无执行器（如 SSH 连接中）或没有任务时分别提示
- **`backend/app/core/executor_adapter.py`** — `stop()` 额外关闭持久化终端池（新增 `_terminal_pool` 引用，调用 `close_now()`），正在等待输出的 `read_until` 立即退出；用例结束清理终端时同步置空引用
- **`frontend/src/pages/Dashboard.tsx`** — 移除统计卡片中的「阻塞」项

---

## [未发布] — 2026-11-17 — 执行页新增底部固定操作条

### 新增 — 已选数量与开始/结束执行常驻可见

- **`frontend/src/index.css`** — 新增 `.execution-action-bar`：`position: sticky` 固定在内容区底部（`page-content` 是滚动容器），半透明白底 + 背景模糊，细边框与上方投影，不再随列表滚出视野
- **`frontend/src/pages/Dashboard.tsx`** — 页面底部新增操作条：左侧显示全局已选用例数与「执行中」标记，右侧为「开始执行」「结束执行」「取消选择全部」按钮，按执行状态与已选数量禁用
- **`frontend/src/pages/Dashboard.tsx`** — 新增 `handleDeselectAllCases`：取消所有表页的已选用例（执行时下发的是跨 Sheet 的全局选择），与后端同步失败时回滚

---

## [未发布] — 2026-11-17 — 修复「重新生成统计页内容」不生效

### 修复 — 统计页标签带英文副标题时匹配失败

- **`backend/app/core/excel_handler.py`** — `_normalize_statistics_label` 只取标签首行，去掉换行后的英文副标题（如 `测试基本信息\nTest Basic Information`）；`fill_statistics_summary` 改为前缀匹配（`label.startswith(key)`），兼容 `测试总结（必填）` 等变体
- **`backend/tests/test_statistics_summary.py`** — 新增双语多行标签用例：Sheet 名为 `数据统计Data Statistics`，B10~B12 为「中文\n英文」，断言 AI 文案仍写入 C10~C12

此前真实模板的栏目标签为两行（中文名 + 英文名），旧逻辑将整段文本（含换行）与「测试基本信息」全等比较，匹配不到时静默跳过，于是 AI 虽被调用并返回内容，却一个字也没写进统计页。

---

## [未发布] — 2026-11-17 — 下载结果改为可选「是否重新生成统计页内容」

### 变更 — 备注列固定包含执行日志

- **`frontend/src/pages/Dashboard.tsx`** — 「下载结果」下拉菜单移除「备注含/不含执行日志」，改为「重新生成统计页内容」/「保留现有统计页内容」；备注列始终附带日志，导出文件名固定为 `test_results.xlsx`，提示文案按选项区分
- **`frontend/src/api/axios.ts`** — `downloadResults(regenerateStats = true)` 改为传 `regenerate_stats`，不再传 `include_log`
- **`backend/app/api/routes.py`** — `GET /download/results` 参数由 `include_log` 改为 `regenerate_stats`：备注列始终按工作区 `log_remark_mode` 输出日志图片/文字；`regenerate_stats=True` 时才调用 AI 填写「数据统计」页，否则保留工作簿已有内容直接导出；下载副本生成失败时统一回退原始结果文件
- **`backend/app/ai/service.py`** — `generate_test_statistics` 新增 `force_refresh`：重新生成时跳过结果缓存，确保拿到新内容
- **`backend/tests/test_statistics_summary.py`** — 更新下载用例签名，并新增「未勾选重新生成时不调用 AI、保留原有统计页」用例

---

## [未发布] — 2026-11-17 — 结果 Excel 的日志图片不再压到备注列边框

### 修复 — 图片略微超出单元格

- **`backend/app/core/excel_handler.py`** — `embed_log_images` / `embed_case_images` 图片左侧偏移由 2px 调到 6px；备注列宽度由 `图片宽度 / 7` 改为 `图片宽度 / 7 + 2`（约多 14px），图片左右各留出 6~8px 空白，不再压到列边框
- **`backend/app/core/excel_handler.py`** — 行高改按实际堆叠偏移计算（顶部偏移 + 各图高度 + 图间距 + 底部余量），多终端日志上下堆叠时也不会压住下一行

---

## [未发布] — 2026-11-16 — 全选用例不再卡顿

### 修复 — 200 条用例全选时的性能问题

- **`frontend/src/stores/useStore.ts`** — 新增 `updateCasesSelected(caseKeys, selected)`：一次 `set` 合并更新所有选中状态、只持久化一次。此前逐条调用 `updateCaseSelected`，每条都会遍历数组、通知订阅者并把全部用例 `JSON.stringify` 写入 `localStorage`，200 条全选即产生 200 次全量序列化
- **`frontend/src/pages/Dashboard.tsx`** — 表头「全选」、按页选中、按状态快捷选中及其失败回滚改用批量接口，逻辑不变，交互立即响应

---

## [未发布] — 2026-11-16 — 滚动条收进内容区，顶栏与侧栏固定不滚动

### 改进 — 页面整体不再滚动，左侧菜单不跟随内容移动

- **`frontend/src/components/Layout.tsx`** — 外层 `AntLayout` 改为 `className="app-shell"`（原 `minHeight: 100vh`），内层改为 `className="app-body"`
- **`frontend/src/index.css`** — `.app-shell` 固定 `height: 100vh` + `overflow: hidden`；`.app-body` 设 `min-height: 0` + 隐藏溢出；`.page-content` 移除 `min-height: calc(100vh - 44px)`，改为 `overflow: auto` 让滚动条出现在内容区内部；侧栏 `.ant-layout-sider-children` 改为纵向 flex，菜单 `flex: 1` + `overflow-y: auto`，菜单过长时只在侧栏内部滚动
- **`frontend/src/index.css`** — 新增 `@media print` 规则，打印报告时解除外壳固定高度与内部滚动，避免内容被截断

---

## [未发布] — 2026-11-16 — 下载结果时放宽 AI 生成「数据统计」页的超时

### 改进 — 统计页文案生成不再被过早打断

- **`backend/app/api/routes.py`** — `GET /download/results` 中 AI 填写「数据统计」页的 `asyncio.wait_for` 超时由 60s 提高到 120s，给模型汇总多个 Sheet 执行数据留足时间；失败仍只影响三栏文案，不影响文件下载
- **`frontend/src/api/axios.ts`** — `downloadResults` 单独设置 `timeout: 180000`：默认全局 30s 会先于后端（AI 最长 120s + 嵌图）中断，导致浏览器侧拿到超时错误

---

## [未发布] — 2026-11-16 — 用例表格长文本限高，超出后单元格内滚动

### 改进 — 行高不再被超长文本撑高

- **`frontend/src/index.css`** — 新增 `.case-cell-scroll`：单元格内容 `max-height: 120px`，超出后纵向滚动（细滚动条），横向不滚动
- **`frontend/src/pages/Dashboard.tsx`** — 「测试用例」表格的「用例描述」「前置条件」「测试步骤」「预期结果」「实际结果」列改用限高滚动容器，编辑 / 查看日志等操作按钮仍固定在单元格顶部
- **`frontend/src/components/casegen/CasePreviewStep.tsx`** — 用例预览表格的「前置条件」「测试步骤」「预期结果」同样限高滚动，避免长用例把整行撑高

---

## [未发布] — 2026-11-16 — 交互输入步骤可指定「等待输出 / 超时」

### 新增 — `输入 gc 0，等待输出：Frame rate，超时20秒`

- **`backend/app/core/command_parser.py`** — `CommandStep` 新增 `expect_pattern` / `expect_is_regex` / `expect_timeout`；新增 `extract_nvsipl_expect`，识别交互输入步骤里的「等待输出：xxx」（也可写 `等待输出:/正则/`）与可选的「超时N秒 / 500ms / 2s / 分钟」，`/.../` 包裹按正则使用、其余按普通文本；未写超时则沿用内置默认值
- **`backend/app/core/executor_adapter.py`** — 执行交互输入时，步骤内配置覆盖 `_NVSIPL_INPUT_EXPECT` 的默认特征与超时（作用于该步骤最后一个交互子命令，表示整步完成条件），并向日志输出实际等待条件；命令预览备注同步展示「等待输出 + 超时」
- **`frontend/src/components/TestStepRulesModal.tsx`** — 步骤规则说明补充「等待输出 / 超时」写法与正则用法
- **`backend/tests/test_nvsipl_expect.py`（新增）** — 覆盖带超时、不带超时、正则、毫秒与英文单位、无配置沿用默认、多子命令等场景

---

## [未发布] — 2026-11-16 — 执行测试不再调用步骤解析，AI 解析仅按手动触发

### 变更 — 解析时机与触发方式

- **`backend/app/core/executor_adapter.py`** — 执行测试只使用规则解析结果，删除执行过程中「未识别步骤 → AI 实时兜底解析」的逻辑（含按需写回 `_ai_parsed_steps`）；AI 步骤解析仅用于命令预览，由用户在步骤表格中手动触发
- **`backend/app/api/routes.py`** — 上传后的异步预解析任务保存为 `session.ai_parse_task`：同一会话重新上传时取消上一次未完成的任务，`start_execution` 启动执行时也取消，避免结果串扰与执行期间继续调用；`_async_ai_parse_steps` 在发起 AI 前及每条解析前检查 `session.is_running`，已取消时广播「步骤解析已中断（执行已启动）」并礼貌退出
- **`backend/app/api/routes.py`** — `POST /ai/parse-steps`、`POST /ai/parse-steps-batch` 在执行中直接返回 400「测试执行中，不进行步骤解析」
- **`backend/app/ai/service.py`** — `AIService.parse_steps` 新增 `force_refresh` 参数，为 `True` 时跳过结果缓存，保证手动解析拿到模型真实结果
- **`backend/app/api/routes.py`** — `ParseStepsRequest` 新增 `force_ai`：为 `True` 时跳过规则解析与缓存，强制调用大模型（「AI 解析」按钮语义）；规则能解出可执行步骤时仍直接返回、不调 AI
- **`frontend/src/api/axios.ts`** — `aiParseSteps` 增加 `force_ai` 字段
- **`frontend/src/pages/Dashboard.tsx`** — 「AI 解析」按钮改为 `force_ai: true`，执行中禁用；失败时优先展示后端返回的 `detail`（例如「测试执行中，不进行步骤解析」），AI 步骤解析相关文案统一为「步骤解析」

---

## [未发布] — 2026-11-16 — 步骤解析：支持 nvsipl 数字参数行输入

### 修复 — `输入 8000 256` 等二次输入未被解析

- **`backend/app/core/command_parser.py`** — `parse_nvsipl_interactive_inputs` 新增数字/十六进制参数行模式：`输入 8000 256`、`输入8000 256`、`输入 0x8000 256` 均解析为 `nvsipl_input`；该模式结果与引号子命令、`输入 xxx` 子命令结果合并，`输入sh0 … 输入8000 256` 会解析为 `sh0;8000 256`，不再只保留 `sh0` 而丢弃后续参数行；`Please enter <address_hex> <length_dec>, e.g. 8000 256` 这类无「输入」前缀的示例文本，以及 `输入命令：echo …` 不会误判
- **`backend/tests/test_terminal_parse.py`** — 新增数字参数行、同一步骤子命令 + 参数行合并、示例文本 / 命令前缀不误判等用例

---

## [未发布] — 2026-11-16 — 修复：草稿恢复后重新执行仍显示旧 AI 判定

### 修复 — 新一轮执行未清空「BUG」列

- **`backend/app/api/routes.py`** — 启动执行时把选中用例的 `judgment`（「BUG」列 AI 判定）、`bug_description` / `bug_severity` 一并清空，并抽出 `_reset_selected_case_results`；不清 `judgment` 时 `build_judgment_from_case` 会回退到草稿恢复的旧值，本轮没有 AI 判定时实际结果仍显示上一次的 `[AI判定] Pass (置信度=…)`
- **`backend/app/api/routes.py`** — SSH 参数校验提前到清空结果之前：启动失败（如未配置 SSH）时保留草稿恢复的执行记录，便于修正配置后再次执行
- **`frontend/src/stores/useStore.ts`** — `resetSelectedCases` 同步清空 `judgment`、`ai_judged` / `ai_status` / `ai_confidence` / `ai_reason` / `ai_evidence` 与 `bug_description` / `bug_severity`，避免前端本地缓存继续展示草稿里的旧结论
- **`frontend/src/types/index.ts`** — `TestCase` 补齐后端返回的 AI 判定与 Bug 描述字段
- **`backend/tests/test_execution_log_draft.py`** — 新增草稿恢复后启动执行清空旧结果、未选用例不受影响、SSH 校验失败保留恢复结果三类用例

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

### 修复 — 日志中混入 `[?2004l` 等终端控制序列

- **`backend/app/core/terminal_log.py`** — 新增 `strip_ansi_sequences`，统一剔除 ANSI / OSC 控制序列、不可见控制字符，以及早期日志里残留的 `[?2004h` / `[?2004l`（bash 括号粘贴模式开关）；`format_terminal_log` / `parse_terminal_log` / `read_terminal_logs` 均先清理再处理
- **`backend/app/core/executor_adapter.py`** — 聚合日志 `_record`、按终端日志 `_write_case_log`、实时流 `_TerminalStreamFilter` 写入前统一清理控制序列，`ESC[?2004l` 不再出现在 `.log` / `.term.log` 中
- **`backend/app/core/remarks.py` / `backend/app/api/routes.py`** — 读取备注日志、`GET /logs/content` 返回前清理，历史日志也能正常显示
- **`frontend/src/utils/terminalLogFormat.ts`** — 新增 `stripTerminalControl`，终端日志解析 / 拼接 / 草稿迁移时清理控制序列；`CaseLogModal` 展示前同样清理
- **`backend/tests/test_terminal_log.py`** — 新增带 ESC 与只剩 `[?2004l` 两种形态的回归用例

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
