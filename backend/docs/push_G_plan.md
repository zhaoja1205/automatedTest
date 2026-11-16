# 推送 G：代码扫描 + 函数识别 + 流程图生成

## 背景与目标

推送 F 之前，SWE.3 的"函数详细设计"只是按人工维护的 `functions[]` 直接渲染，用户无法区分哪些是自己改动的、哪些是 SDK 原装；流程图也没法自动出。

推送 G 的目标：
- 用户上传完整工程代码（或授权前端读本地 git 工作区），自动识别"相对某个基线 commit 的改动函数"
- 改动过的 / 新增的函数 → 生成完整详细设计（声明 + 参数 + 流程图）
- 未改动的 SDK 原装函数 → 只出声明表，不画流程图
- 给用户手动"豁免"复杂函数的能力，这些函数走人工流程图
- 导出 SWE.3 docx 时按改动/未改动/豁免三类分别渲染

---

## 用户 4 点决策（本次方案依据）

> 1、可以锁住，但需要前端提醒用户是否需要不操作，什么时候完毕可以操作了；
> 2、流程图用方式A即可；
> 3、完全人工，用户在前端清单上勾选；
> 4、用AI生成的，异常了可以retry操作，最终无生成后标记异常由人工在调整

| # | 决策 | 落地方式 |
|---|------|---------|
| 1 | 扫描/AI 过程可锁 UI | 前端全局 `scanBusy/aiBusy` 状态 + Spin 遮罩 + 禁用相关按钮；Toast 提示"扫描中，约需 X 秒，请勿关闭页面"，完成/失败均显式通知 |
| 2 | 流程图走方式 A（AI 读完整函数体生成 PlantUML activity） | 复用已有 `Swe3AI.generate_function_flowchart(fn)`；prompt 中带 `fn.body` 字段 |
| 3 | 复杂函数豁免 = 纯人工勾选 | 函数清单表加 `exempt_from_ai: bool` 列 + Checkbox；豁免的函数流程图留空待人工在 Word 里补 |
| 4 | AI 失败可 retry，最终失败标记异常 | AI 响应里加 `status: ok / failed / exception`；失败态前端展示 ⚠️ 图标 + "重试"按钮；达到 retry 上限（默认 3）后，`exception_marked=true`，渲染时在流程图位置落占位文本"⚠️ AI 生成失败，请人工补充" |

---

## 现有基础设施（本推送复用，不新写）

| 文件 | 行数 | 本推送角色 |
|------|------|----------|
| [app/core/engineering_store.py](../app/core/engineering_store.py) | 已就位 | zip 上传 / 解压 / SDK 关键字识别（nvsipl/nvmedia/drive-os...） |
| [app/core/code_scanner.py](../app/core/code_scanner.py) | 561 行 | 正则函数抽取，输出 `{classes[{functions[{key,declaration,parameters,returns,doc_comment,body_lines,is_sdk}]}]}`；key = `{file}::{class_or___free__}::{name}::{param_sig_sha1[0:8]}` |
| [app/core/swe3_ai.py](../app/core/swe3_ai.py) | 156 行 | 已有 `generate_function_flowchart(fn)` / `generate_function_intro(fn)` / `strip_plantuml_fences()`；独立 cache 命名空间 |
| [app/ai/service.py](../app/ai/service.py) | 645 行 | Provider 管线 |
| [app/api/aspice_routes.py:878-1200](../app/api/aspice_routes.py) | 已就位 | `/swe3/engineering/upload`、`/swe3/modules/{cid}/scan`、`/swe3/ai/augment`、`/swe3/ai/augment-one` 端点齐全 |

**存量基础设施评估：推送 G 核心 60% 工作已被 Push D 覆盖。** 本次主要缺口是：
1. `code_scanner.py` 没有 body 抽取 → 流程图 prompt 里要能塞函数体
2. 没有"基线 commit 比对"机制 → 需要新增 baseline_commit 字段 + diff 逻辑
3. AI augment 当前 all-or-nothing → 需要加 retry 状态机
4. 前端没有扫描向导 UI + 豁免勾选表
5. docx 渲染不区分 modified/unchanged/exempt

---

## 范围边界

| 本推送包含 | 本推送不包含 |
|---|---|
| 前端 Chrome FS API + isomorphic-git 读本地工程 | 后端 ssh/git clone 远程仓库（放弃方案） |
| 基线 commit 指定 + diff 识别改动函数 | 基线之前的历史分析 |
| `code_scanner.py` 加 body 字段 | libclang 替换 regex（继续用 regex-1.0，libclang 下迭代） |
| `swe3_ai.py` + retry 包装器 | prompt 质量迭代（后续按样例回归调优） |
| 函数清单 UI（改动标记/豁免 Checkbox/重试按钮/异常标记） | 流程图 PlantUML 可视化编辑器（放 PlantUML 本地渲染流程里） |
| docx 渲染三态（AI/SDK/exempt） | 流程图 PNG 嵌入优化（本地渲染已就位，直接复用） |

---

## 数据模型扩展

### [frontend/src/types/aspice.ts](../../frontend/src/types/aspice.ts) 增量

```ts
export interface ScanFunctionItem {
  key: string                       // scanner 输出的 symbol key
  name: string
  file: string
  class_name: string | null
  declaration: string
  is_sdk: boolean                   // 来自 engineering_store SDK 识别
  diff_status: 'added' | 'modified' | 'unchanged'  // 新增：baseline 比对结果
  exempt_from_ai: boolean           // 新增：用户勾选"复杂函数豁免"
  // AI 产出
  intro?: string
  flowchart_plantuml?: string
  ai_status?: 'pending' | 'ok' | 'failed' | 'exception'
  ai_retry_count?: number
  ai_last_error?: string
}

export interface Swe3BaselineConfig {
  baseline_commit: string           // SHA 或 ref
  baseline_branch?: string          // 可选，便于显示
  pinned_at: string                 // ISO 时间串
}
```

### `code_scanner.py` 增量

- `_scan_source` 结果里的 function dict 加 `"body": "..."` 字段（去注释后的函数体源码），供 AI prompt 使用
- 增加 `scan_with_baseline(project_id, component_id, baseline_sha)` → 用 isomorphic-git 的 diff（走前端上送的 diff 清单）或后端 `git diff baseline..HEAD` 标 `diff_status`

### [backend/app/core/engineering_store.py](../app/core/engineering_store.py) 增量

- 存 `engineering_meta.json` 里加 `baseline_commit` 字段
- 上传入口可携带 "git_diff_summary"（前端 isomorphic-git 预计算结果），落盘 `runtime/creator_projects/<id>/swe3/baseline_diff.json`

---

## 模块 1：前端 isomorphic-git 接入

### 新文件：`frontend/src/components/aspice/swe3/EngineeringScanner.tsx`

- 用 `window.showDirectoryPicker()` 请求本地工程目录读权限
- 用 isomorphic-git 的 `FS`（实现基于 FileSystemDirectoryHandle 的 fs adapter）
- 流程：
  1. 列分支，让用户选"基线 commit"（默认取最早的 tag 或用户手动粘 SHA）
  2. `git.log()` 拉 baseline..HEAD 的提交清单
  3. `git.walk()` 对两个 tree diff，得到改动文件列表
  4. 读改动文件内容，连同整个工程目录 zip 一起上传
  5. 把 diff 清单传到 `/swe3/engineering/upload` 的 `git_diff_summary` 字段
- **全程 Spin + Progress** 覆盖整个页面，禁用其他操作；完成后 Toast "扫描就绪，可以进入函数清单操作"

### [frontend/src/stores/useAspiceStore.ts](../../frontend/src/stores/useAspiceStore.ts) 增量

- `scanBusy: boolean` / `aiBusy: boolean` 全局状态
- action: `setBaseline(sha)` / `startEngineeringScan()` / `markFunctionExempt(key, exempt)` / `retryAIForFunction(key)`

---

## 模块 2：后端 code_scanner 增强

### [backend/app/core/code_scanner.py](../app/core/code_scanner.py) 改动

- `_scan_source`：解析函数时额外抓函数体（`src[open_brace:close_brace+1]`，去注释，保留原缩进），塞到 function dict 的 `body` 字段
- 新增 `classify_functions(scan: dict, diff_summary: dict) -> dict`：
  - `diff_summary` 来自前端 isomorphic-git 上送，形如 `{changed_files: [path], added_functions: [key], modified_functions: [key]}`（可选，如果前端没传，走路径粗分：SDK 路径 → unchanged_sdk，工程路径 → modified）
  - 为每个 function 打 `diff_status` 和 `is_sdk`
- libclang hook（继续作为可选升级路径）放在 `_scan_source_libclang` stub，本推送不启用

---

## 模块 3：AI prompt + retry 包装

### [backend/app/core/swe3_ai.py](../app/core/swe3_ai.py) 增量

- `generate_function_flowchart(fn)` 的 prompt 升级，模板：

```
你是一位嵌入式 C/C++ 代码评审专家。
请阅读以下函数源码，输出一个 PlantUML activity diagram（@startuml / @enduml 包裹），
严格使用 start / stop / if / else / endif / while / endwhile 结构表达控制流。
要求：
1. 节点文字用简体中文，描述动作而非直译代码
2. if 条件文字写具体判断含义（如"读 EEPROM 失败?"）
3. 不要超过 20 个节点；复杂循环折叠为一句话
4. 只输出 PlantUML 块，不要解释

函数名：{fn.name}
声明：{fn.declaration}
函数体：
```
{fn.body}
```
```

- 新增 `generate_function_flowchart_with_retry(fn, max_retries=3)` 包装：
  - 捕获 `AIServiceError` / `TimeoutError` / 输出解析失败（`strip_plantuml_fences` 返回空）
  - 每次重试间隔 2s（exponential backoff）
  - 返回 `{status: "ok", plantuml: "..."}` 或 `{status: "failed", retries: 3, last_error: "..."}`

### [backend/app/api/aspice_routes.py:1055](../app/api/aspice_routes.py) 增量

- `/swe3/ai/augment-one` 的单函数 AI 端点加入 `retry_on_error: true` 参数
- 新增 `/swe3/ai/mark-exception/{project_id}/{component_id}/{function_key}` 允许前端手动标 exception 态

---

## 模块 4：UI 向导（含豁免/retry/异常）

### 新文件：`frontend/src/components/aspice/swe3/FunctionList.tsx`

表格形态，每行一个函数：

| 列 | 类型 | 说明 |
|---|------|------|
| 文件路径 | text | `app/.../foo.cpp` |
| 函数名 | text | |
| 是否 SDK | Tag | 灰/蓝 |
| 改动状态 | Tag | added(绿) / modified(橙) / unchanged(灰) |
| 豁免 AI | Checkbox | 决策 3，用户勾 |
| AI 流程图 | State+Action | pending 转圈 / ok ✓ / failed ⚠️ 重试按钮 / exception 🚫 "手动补充" |
| 操作 | Button | 单函数 Augment / 预览流程图 |

顶部 Alert 条：
- 扫描中："⏳ 正在扫描工程代码，请勿操作..."
- AI 批量中："⏳ AI 正在生成 X/Y 个函数的流程图..."
- 完成："✓ 处理完成，Z 个异常需手动处理"

### [frontend/src/components/aspice/Swe3Step.tsx](../../frontend/src/components/aspice/Swe3Step.tsx) 改动

在模块卡片内嵌 `<FunctionList moduleId={...}/>`，取代当前的"函数声明表"静态展示。

---

## 模块 5：docx 回填

### [backend/app/core/arch_generator_swe3.py](../app/core/arch_generator_swe3.py) 改动

- `_fill_function_decl_table` 的流程图行（row -1）渲染逻辑：
  - `fn.ai_status == "ok"` → 调 PlantUML 本地渲染拿 PNG，嵌入
  - `fn.exempt_from_ai == True` → 占位文本"（流程图由人工补充）"
  - `fn.is_sdk && diff_status == "unchanged"` → 跳过流程图行（SDK 原装不画）
  - `fn.ai_status == "exception"` → "⚠️ AI 生成失败，请人工补充"占位文本
- 函数清单（4.X.2）渲染前过滤：
  - `is_sdk && unchanged` 的函数：只出函数名 + 声明，不出 brief 和 params 详述

---

## 文件改动清单

### 后端（0 新 + 5 改）
- 改：`app/core/code_scanner.py` — `body` 字段 + `classify_functions` + libclang stub
- 改：`app/core/swe3_ai.py` — prompt 升级 + retry 包装
- 改：`app/core/engineering_store.py` — `baseline_commit` + `baseline_diff.json` 落盘
- 改：`app/core/arch_generator_swe3.py` — 流程图行三态渲染
- 改：`app/api/aspice_routes.py` — `/swe3/ai/mark-exception` 端点 + augment-one 加 retry 开关

### 前端（3 新 + 3 改）
- 新：`frontend/src/components/aspice/swe3/EngineeringScanner.tsx` — 向导
- 新：`frontend/src/components/aspice/swe3/FunctionList.tsx` — 函数清单表
- 新：`frontend/src/components/aspice/swe3/BusyOverlay.tsx` — 全局遮罩
- 改：`frontend/src/components/aspice/Swe3Step.tsx` — 嵌入 Scanner + FunctionList
- 改：`frontend/src/stores/useAspiceStore.ts` — `scanBusy/aiBusy` + 相关 actions
- 改：`frontend/src/types/aspice.ts` — 新字段

---

## 开发顺序（建议）

| 阶段 | 内容 | 预估 |
|------|------|------|
| G1 | 后端 scanner body + classify + baseline 存储 | 半天 |
| G2 | swe3_ai retry 包装 + augment-one 增强 + mark-exception 端点 | 半天 |
| G3 | 前端 isomorphic-git 接入 + EngineeringScanner | 1 天 |
| G4 | FunctionList 表 + BusyOverlay + 状态流 | 1 天 |
| G5 | docx 三态渲染 | 半天 |
| G6 | 端到端回归（跑一个真实项目） | 半天 |

**总计约 4 天**，用户可按阶段验收。

---

## 验证步骤

1. **G1 单测**：构造一个小 zip + 假 baseline SHA，调 `/swe3/engineering/upload` + `/swe3/modules/A001/scan`，验证返回的 function dict 带 `body`/`diff_status` 字段
2. **G2 回归**：故意让 AI provider 返回空白，验证 retry 3 次后落 `exception` 态；人工调 `/mark-exception` 能复位到 ok 态
3. **G3 浏览器实测**：Chrome + 本地 git 项目，EngineeringScanner 能完成"选基线 → diff → 上传"全流程，期间按钮禁用、Alert 常驻、完成后 Toast
4. **G4 交互**：勾一个函数的"豁免 AI" → 该行 AI 列灰化；点另一个 failed 行的"重试" → 显示转圈 → 成功 / 失败
5. **G5 docx**：生成一份 SWE.3，验证：
   - modified 函数流程图行是 PNG
   - SDK unchanged 函数只有声明没流程图
   - 豁免函数流程图位置是占位文字
   - exception 函数是 ⚠️ 占位
6. **G6 回归**：F1/F2 的样例文档重新导出，确认不回归

---

## 风险与备选

| 风险 | 缓解 |
|------|------|
| Chrome FS API 仅 Chromium 系支持，Firefox/Safari 不行 | 前端检测 `window.showDirectoryPicker` 不存在时降级回"上传 zip + 手动粘 baseline SHA"方案；在页面显著位置标注"推荐 Chrome/Edge" |
| isomorphic-git 读大仓库慢 | 只 diff baseline..HEAD 的 tree，不走全 log；预估 1GB 仓库 < 30s |
| AI 流程图质量不稳 | prompt 迭代；并提供"人工覆写 PlantUML"入口（保留 flowchart_plantuml 字段可编辑） |
| 大仓库 zip 上传超时 | 前端分片上传已在 Push D 做；本推送只增量加 baseline_commit 字段，不改上传链路 |

---

## 与推送 F2 的关系

- F2 已完成模块深拷贝，SWE.3 docx 骨架正确
- G 不动骨架，只升级"流程图/函数清单"两处的填充策略
- G 完成后，F2 导出的 docx 就从"所有函数一视同仁都画 AI 流程图"进化为"按改动状态分层渲染"

## 后续（不在本推送）

- libclang 替换 regex（更稳的函数体抽取，特别是宏展开场景）
- 流程图 PlantUML 前端可视化编辑器（配合本地 PlantUML 服务器）
- AI 类图 / 时序图批量生成（当前 swe3_ai.py 已有 API 但未在流程里调）
