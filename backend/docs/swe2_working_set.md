# SWE.2 侧 并发开发占位 —— phase4-dev 分支

> **用途**：另一个终端同分支做 SWE.1 时，请先看本清单。本清单只列**SWE.2
> 这边正在持续改动的文件 / 正要改的文件**。只要双方不同时碰同一文件，就
> 不会有合并冲突；若必须碰同一文件，请在 Slack 同步后再改。
>
> 最后更新：2026-11-23 （SWE.2 侧负责人：当前 session）

---

## 🔴 SWE.2 侧 已改但尚未提交的文件（working tree 脏）

若你要改这些文件，先告知 SWE.2 侧再动。

### Backend
- `backend/app/schemas/aspice/swe2_schema.py`
  - 新字段：`Component.enabled`、`Component.security_mode`、`Component.security_goals`、`Component.security_modules`、`Resources.kpi_adjustment`
  - 影响面：SWE.2 context 校验、前端类型同步
- `backend/app/core/arch_generator.py`
  - `_build_swe2_context`：补 enabled / security_mode 落盘
  - 影响面：**和 SWE.1 无交集**（SWE.1 的 generator 在 `req_generator.py`）
- `backend/app/core/arch_sections.py`
  - `default_resources()` 加 `kpi_adjustment: ""`
  - 影响面：仅 SWE.2 默认数据
- `backend/scripts/build_swe2_template.py`
  - 新增 3 个 hook：`_wire_component_enable_wrappers` / `_wire_a008_security_mode` / `_wire_a008_security_goals_and_modules`
  - 全局给数据表 + 自由文本加 `| e` 过滤
  - 影响面：**仅 SWE.2 模板生成脚本**
- `backend/app/templates/aspice/swe2_arch.docx`（二进制产物）
  - 由上面脚本重新生成；SWE.1 不碰
- `backend/tests/test_swe2_docx_render.py`
  - 新增 3 个回归锁：disabled 跳章 / manual_brief 两节 / full 全出
  - 影响面：**仅 SWE.2 测试**

### Frontend
- `frontend/src/types/aspice.ts`
  - `AspiceComponent` 加 `enabled?: boolean` + `security_mode?: 'full' | 'manual_brief'`
  - **⚠ 与 SWE.1 共享类型文件** —— SWE.1 若也在这里加字段请隔开接口（如 `Swe1*` 前缀），避免 git 冲突
- `frontend/src/components/aspice/Swe2Step.tsx`
  - `COMPONENT_OPTIONS` 补 A009 Campwr
  - 影响面：**仅 SWE.2 页面**
- `frontend/src/components/aspice/swe2/ModuleEditor.tsx`
  - 顶部 enabled Switch + A008 security_mode Radio
  - 4 处表（§4.X.2.1 外部 / §4.X.2.2 内部 / §4.4.2 类 / §4.X.3 场景）已换成 `PaginatedTable<T>`
  - 影响面：**仅 SWE.2 组件**
- `frontend/src/components/aspice/swe2/SoftwareDesignEditor.tsx`
  - §3.3.1 / §3.3.2 临时接口表也换成 `PaginatedTable<T>`（原来 pagination={false}）
  - 影响面：**仅 SWE.2 组件**
- `frontend/src/components/aspice/swe2/PaginatedTable.tsx` 【**新文件**】
  - 可搜索分页表格外壳：fixed-height + sticky + pagination + __idx 透传原始数组 index
  - 影响面：**仅 SWE.2 内部组件**，SWE.1 别直接依赖（想要可以 ping 我提到公共目录）
- `frontend/src/components/aspice/swe2/ResourcesEditor.tsx`
  - 加 "§5 §KPI 原目标 & 客户变更记录" Card + V4.0 示例填充按钮
  - 影响面：**仅 SWE.2 组件**

---

## 🟡 SWE.2 侧 接下来会改的文件（预告区）

按 Phase B / C / D 顺序推进：

### Phase B（已收尾 ✅）
- enabled / security_mode / A009 Campwr / KPI 调整表 / §4.4.2 空态提示 / PaginatedTable 全部落地
- §4.4 类表增强多列 —— V4.0 参考只用 3 列，**不做**

### Phase C（§7 系统集成前端编辑器 ✅）
- 核对发现：§7 schema/模板/生成器**后端早已完成**（Integration + 6 principles + principles_by_key 都在）
- Phase C 实际差距：前端 UI 没有编辑入口 → 用户没法改 "集成顺序 / 6 条原则"
- 新增 `frontend/src/components/aspice/swe2/IntegrationEditor.tsx`：
  - §7.1 自由 textarea（placeholder = DEFAULT_INTEGRATION_ORDER）
  - §7.2.1-6 固定 6 条 Collapse（key/title 固定，只能改 description）
  - "全走默认 / N 处已覆盖" Tag
- 挂到 `Swe2Step.tsx` Collapse 末尾（§6 之后）
- 顺手修 generator 隐藏 bug：用户只填部分 principles 时按 key 合并，避免 UndefinedError
  - 影响：`backend/app/core/arch_generator.py` _build_swe2_context 的 integration 块
- 测试：新增 2 用例覆盖"用户覆盖"和"完全留空" → 15/15 passed

### 2026-11-23 用户反馈 5 条 ⑤→③→②→④→① ✅

- **⑤ 接口表列宽错位修复** — `harden_interface_table` widths 重排 + 10 列特判 + T13/T26 出 `COMPONENT_IFACE_TABLES`
- **③ TOC** — 延后（需先补 142+ 章 Heading 样式）
- **② 文档版本号/公司/修订人可配**：
  - 前端：新 `DocMetaEditor.tsx` 挂 Swe2Step 顶部；`Swe2DocMeta` 类型 + `setSwe2DocMeta` store
  - 后端：`_build_swe2_context` 优先读 `swe2.doc_meta`，留空回落 `project.meta`
  - 模板：封面公司名硬编码换成 `{{ project.company | e }}` 占位
- **④ 静态信息 PlantUML → PNG 真嵌入**：
  - `TemplateRenderer.auto_embed_plantuml_in_context` 深度扫 context，`node.plantuml` → `node.image` InlineImage
  - schema `DiagramImage`；`SoftwareDesign.module_diagram`；模板 `{{ software_design.module_diagram.image }}` / `{{ sc.image }}`
  - 失败兜底：单张异常只记 warning
- **① 说明列是函数简介** — 本次只改 UI 提示（Tooltip + placeholder "一句话函数功能（不写返回类型）"），真 AI 生成归 Phase D

**测试**：18/18 passed  **前端 TS**：SWE.2 侧零错误

### 2026-11-23 用户第二轮反馈（3 个 bug 修复）✅

- **Bug A**：版本号 UI 填了但 docx 没变 → 根因：`handleExport` 没先保存就调导出，后端读的还是旧 `project.json`。修：`Swe2Step.handleExport` 导出前 `await saveAspiceProject(projectId, store.aspice)` 落盘
- **Bug B**：溯源表 ID含义/备注/发布版本 三列全空 → 根因：前端存 `component / description / release_version`，generator 读 `id_meaning / remark / version`，名字对不上。修：`_build_swe2_context.mapping_rows` 两套字段名都认，前端优先
- **Bug C**：§3.2 模块图总被默认 PlantUML 盖掉 → 根因：generator 把 `sd_defaults["module_diagram_plantuml"]` 塞给 walker，于是每次都渲染一张"相机模组集成"占位图盖在模板原图上方。修：`module_diagram.plantuml` 只用 `sd_src.get("module_diagram_plantuml")`，用户没填就留空，walker 跳过→模板原图保留

**回归锁新增**：
- `test_mapping_row_field_names_match_frontend_persistence`：前端字段 `component/description/release_version` 必须出现在 docx 对应三列
- `test_module_diagram_empty_preserves_template_original`：用户未填 PUML → `software_design.module_diagram.plantuml` 为空 + 没有 `@startuml` 残留

**测试**：20/20 passed

### 2026-11-23 第三轮用户反馈（说明列仍是签名文本）✅

截图：§4.X.2 接口表"说明"列大量是 `[returns: float_t]` / `[returns: NvMediaStatus]` —— 这是 `InterfacePickerFromScan.tsx:220` 扫描时填的占位（注释原本就说"AI 后续可覆盖"），现在真正接通 AI 链路。

**后端**：
- 新 `app/ai/prompts/func_brief.py`：系统 prompt 要求"一句话中文、15~35 字、做什么+产物、禁止只写返回类型"
- `AIService.generate_func_briefs(targets, batch_size=10)`：batch 调 LLM、缓存键 = sha1(function|returns|params)、单批失败不断
- 新路由 `POST /aspice/projects/{id}/swe2/ai/function-briefs`：
  - body `{targets: [{row_id, function, returns, params, source_path, current_description}], strategy: "only_returns_or_empty"|"all"}`
  - 服务端按 `[returns:*]` 正则 + 空判筛选，手填不覆盖
  - 响应 `{results: [{row_id, brief, ok}], skipped, _tokens, _cache_hits, _model}`
  - 不动 project.json，避免并发写冲突

**前端**：
- `aspiceApi.ts` 加 `aiGenerateFunctionBriefs` + 类型
- `ModuleEditor.tsx` §4.X.2.1 / §4.X.2.2 PaginatedTable `extraActions` 槽挂"AI 补说明列 (N)"按钮
  - 按钮会实时统计需补全行数，为 0 时 disabled + Tooltip 提示
  - 从 description 反解 `[returns: XXX]` 作 AI 的 returns 输入
  - 回填触发 setDirty，用户导出前自动落盘
  - `MANUAL_ONLY_IDS` (A008 Camera Security) 不显示该按钮

**测试**：25/25 passed

### 2026-11-24 第四轮（多余表格 + AI 阻塞）✅

- **问题 1 多余无用表格**：根因不在渲染、在模板脚本 `COMPONENT_IFACE_TABLES` 漏接两张表
  - `T12` = A003 EEPROM **内部接口表**（5 列，样本含 4 行 M24C04xxx），上轮误判成类表剔除 → 样本行原样留在产物
  - `T25` = A009 Campwr **内部接口表**（5 列，样本含 8 行 campwr SetConfig…），上轮误判成修改历史表剔除 → 同样污染
  - 修：两张表接回循环。T13 才是类表（3 列）、T26 才是修改历史表（6 列），剔除它们是对的
  - 校验脚本：遍历所有 5/6/10 列且首行含「接口溯源」的表，必须含 `{%tr for` → 现在 0 张遗漏
- **问题 2 AI 补全是否阻塞**：后端无阻塞（route `async def` + provider `await` httpx）
  - **但发现真 bug**：回填用的是点击那一刻的 `list` 快照，等待期间用户增删行会被吞
  - 修：row_id 改用稳定键 `方法名@@来源`（重名加 `#n`），回填基于最新 `c[field]` 合并，并二次校验当前值仍是 `[returns:*]` 或空才写
  - 函数签名简化：`fillInterfaceBriefs(field, tag)` / `aiBriefButton(field, tag)`，不再传 list/setList

**测试**：25/25 passed（模板重建后全套无回退）（+5 条：基础回填 / cache 命中 / 分批 / 空列表 / 路由 strategy 筛选）

### Phase D（§8 追踪矩阵 —— 下一步）
- 核对：模板现在 §8 是什么？schema 有没有 Traceability 字段？
- 可能同 Phase C 的轨迹：发现"后端早已完成，只缺前端 editor"，也可能真的需要新建 schema
- 若需新建：`backend/app/schemas/aspice/swe2_schema.py` 加 TraceabilityRow / `arch_generator.py` 落盘 / `build_swe2_template.py` 加章节循环 / 新 `TraceabilityEditor.tsx`

---

## 🟢 保证不碰的区域（SWE.1 可以随便改）

- `backend/app/core/req_generator.py`           — SWE.1 生成器
- `backend/app/routers/swe1*.py`                — SWE.1 路由
- `backend/app/schemas/aspice/swe1_schema.py`   — SWE.1 schema
- `backend/scripts/build_swe1_template.py`      — SWE.1 模板脚本
- `backend/app/templates/aspice/swe1_*.docx`    — SWE.1 模板
- `frontend/src/components/aspice/Swe1Step.tsx` — SWE.1 Step 页
- `frontend/src/components/aspice/swe1/`        — 整个 SWE.1 子目录
- `frontend/src/stores/useAspiceStore.ts`       — 只要 SWE.1 加的字段放 `swe1` 命名空间，不会撞

---

## ⚠ 共享文件 —— 两边都可能改，碰到请 Slack 对齐

| 文件 | SWE.2 这边改了什么 | 建议 |
|------|---------------------|------|
| `frontend/src/types/aspice.ts` | AspiceComponent 加了 enabled / security_mode | SWE.1 在同文件别的 interface 加字段就无冲突 |
| `frontend/src/stores/useAspiceStore.ts` | 暂未改 | 若双方都要加 action/selector，按命名空间 `setSwe1X` / `setSwe2X` 区分 |
| `backend/app/schemas/aspice/__init__.py`（若存在） | 暂未改 | 只 re-export 不改导出顺序即可 |
| `backend/tests/conftest.py` | 暂未改 | 共享 fixture 请加前缀隔离 |
| `backend/app/routers/aspice.py` （若 SWE.1/2 路由共文件） | 暂未改 | 建议两边分到不同文件后再 import 聚合 |

---

## 📋 Git 建议

- SWE.2 侧暂不主动 push；用户要求"不着急提交，一边用一边调"
- SWE.1 侧若要 merge / rebase 主分支，先 ping SWE.2
- 真要联合提交时按 Phase 分 commit，以 `swe2(phaseA):` / `swe1(xxx):` 前缀区分

---

## ✅ 当前测试绿

- Backend：`tests/test_swe2_docx_render.py` 11/11 passed
- 未动 SWE.1 测试
- 前端 `npx tsc --noEmit` 零错误
