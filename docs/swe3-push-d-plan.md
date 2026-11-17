# ASPICE SWE.3 推送 D — 完整方案文档

> 本文档记录 SWE.3 推送 D「工程代码集成 + AI 关注函数展开」的最终方案，含决策、数据流、UI、后端、落地计划。
>
> 本次 commit 已完成的只是 **UI 版本**（前端 Mock），后端真实实现见下文第二阶段。

---

## 一、业务目标

SWE.3 软件详细设计需要跟工程代码紧密结合：

| 模块 | 对应代码 | 关注程度 |
|---|---|---|
| A001 Serializer（MAX96717F） | include + src | 项目新增，重点关注 |
| A002 Deserializer（MAX96712） | include + src | 项目新增 + 部分 SDK |
| A003 EEPROM | include + src | 项目新增 |
| A004 Camera Module（IMX728） | include + src | 项目新增 |
| A005 NvSIPL Camera | SDK + 项目调用 | 混合 |
| A006 Multicast | 项目代码 | 项目新增 |
| A007 PMIC / A009 Campwr | 项目代码 | 项目新增 |
| A008 Camera Security | 无代码，纯框架 | 可选（Switch 控制） |

**核心需求**：
1. 用户上传工程 zip（含 include/ 头文件 + 工程代码）
2. 为每个模块配置其源码目录（glob）
3. 用户勾选"主要关注函数"
4. 系统批量调用 AI 生成函数介绍 + PlantUML 流程图
5. 导出 docx 时：**关注函数展开详细段落**；SDK 未关注函数归入"原始 NV 函数列表"章节

---

## 二、10 项决策（Q&A 定稿）

| # | 问题 | 决策 |
|---|---|---|
| 1 | 代码抽取技术 | **混合**：regex（基础）+ libclang（可选，默认不装）+ AI（关注函数） |
| 2 | 工程上传格式 | **zip**，内含 `include/` 和 `工程代码/`（如 `src/`） |
| 3 | 路径识别方式 | **用户输入**模块目录名；**支持一模块多目录**（path_patterns 多条） |
| 4 | 持久化范围 | **完整扫描结果**存盘；用符号 key `{file}::{class_or___free__}::{name}::{param_sig_sha1[0:8]}` 解决同名函数歧义 |
| 5 | 流程图渲染 | **PlantUML 源码存储**，不渲染 PNG；用户手动贴到 plantuml.com 预览 |
| 6 | 推送 D 边界 | **一次全做**（code scanner + AI + docx 改造） |
| 7 | AI 入口 | **独立 `swe3_ai.py`**（4 方法）不折叠进现有 AIService |
| 8 | 扫描结果存储 | **独立文件** `scan_cache/<module_id>.json`，不塞 project.json |
| 9 | 关注函数分组 | **按文件分组**（文件 → 类/`__free__` → 函数） |
| 10 | Camera Security | **顶部 Switch 可选**，关闭则 UI 隐藏 A008、docx 跳过第 10 章 |

---

## 三、数据存储布局

```
runtime/
└── aspice-projects/
    └── <project_id>/
        ├── project.json                 # 推送 C 已有
        └── swe3/                        # 推送 D 新增
            ├── engineering_src/         # 解压后的 zip 内容
            │   ├── include/...
            │   └── src/...
            ├── engineering_meta.json    # 工程元信息
            └── scan_cache/              # 一模块一文件
                ├── A001.json            # 完整扫描结果
                ├── A002.json
                └── ...
```

**project.json** 的 `swe3.push_d` 只存轻量引用：

```json
{
  "swe3": {
    ...
    "push_d": {
      "has_camera_security": true,
      "engineering": { "zip_name": "...", "total_files": 847, ... },
      "module_code_sources": [
        {
          "component_id": "A001",
          "path_patterns": [
            { "pattern": "include/serializer/**", "exclude": false },
            { "pattern": "src/serializer/**",    "exclude": false }
          ],
          "last_scanned_at": "2026-10-12 10:32:15",
          "scan_hit_count": 3
        }
      ],
      "scan_indices": [ /* 完整扫描结果（可选：也可只存 pointer，运行时从 scan_cache 读） */ ],
      "focus_functions": [
        {
          "component_id": "A001",
          "focused_keys": ["include/serializer/MAX96717F.h::MAX96717FDeviceDriver::DriverCreate::a1b2c3d4", ...],
          "manual_additions": []
        }
      ]
    }
  }
}
```

---

## 四、Symbol Key 设计

```
<file_rel_path>::<class_or___free__>::<func_name>::<param_sig_sha1[0:8]>
```

### 示例

```
include/serializer/MAX96717F.h::MAX96717FDeviceDriver::DriverCreate::a1b2c3d4
src/serializer/MAX96717F.cpp::MAX96717FDeviceDriver::DriverCreate::a1b2c3d4   ← .cpp 同名实现
src/serializer/MAX96717F.cpp::__free__::i2c_write_wrapper::f5e6d7c8           ← 自由函数
```

### 同名函数联动勾选

同类同名函数（如 .h 声明与 .cpp 实现）在 UI 中共享勾选状态：
- 在任一位置勾选 → 自动勾选所有同 `{class}::{name}` 的 key
- 显示 "联动 N 处" 标签提示用户

---

## 五、后端模块设计（第二阶段落地）

### 5.1 新建文件

| 文件 | 职责 |
|---|---|
| `backend/app/core/engineering_store.py` | zip 上传、解压、工程元数据管理、glob 匹配 |
| `backend/app/core/code_scanner.py` | 三层抽取（regex base / libclang optional / AI augment） |
| `backend/app/core/swe3_ai.py` | 独立 AI 服务（4 方法：函数介绍 / 函数流程图 / 类图 / 时序图） |
| `backend/app/core/arch_sections_swe3_focus.py` | focus → docx 布局规则 |
| `backend/app/core/arch_sections_swe3_plantuml.py` | PlantUML 提示词模板 |

### 5.2 修改文件

| 文件 | 变动 |
|---|---|
| `backend/app/core/arch_sections_swe3.py` | 加 `has_camera_security` 默认 True / 加 `code_source` / `focus_functions` 字段 |
| `backend/app/core/arch_generator_swe3.py` | 第 4 章按关注分组：顶层详细段 + "原始 NV 函数列表"子章节 |
| `backend/app/core/creator_store.py` | `_migrate_swe3` 补齐 push_d 新字段 |
| `backend/app/api/aspice_routes.py` | 新增 9 个端点 |

### 5.3 新增 API 端点

| Method | Path | 作用 |
|---|---|---|
| POST | `/projects/{id}/swe3/engineering/upload` | 上传 zip，解压，返回元信息 |
| DELETE | `/projects/{id}/swe3/engineering` | 清空工程 |
| GET | `/projects/{id}/swe3/engineering/preview-match` | 命中预览（query: patterns） |
| POST | `/projects/{id}/swe3/modules/{cid}/scan` | 扫描单模块 → 写 scan_cache |
| GET | `/projects/{id}/swe3/modules/{cid}/scan` | 读 scan_cache |
| PUT | `/projects/{id}/swe3/modules/{cid}/path-config` | 保存 glob 规则 |
| PUT | `/projects/{id}/swe3/modules/{cid}/focus` | 保存关注函数 keys |
| POST | `/projects/{id}/swe3/ai/augment` (SSE) | 流式 AI 补齐，按 key 推进 |
| PUT | `/projects/{id}/swe3/camera-security` | 切换 Switch |

### 5.4 swe3_ai.py 4 方法

```python
class Swe3AI:
    async def generate_function_intro(fn: ScannedFunction) -> str: ...
    async def generate_function_flowchart(fn: ScannedFunction) -> str: ...  # PlantUML
    async def generate_class_diagram(cls_list: list[ScannedClass]) -> str: ...  # PlantUML
    async def generate_sequence_diagram(module_name: str, fns: list[ScannedFunction]) -> str: ...  # PlantUML
```

---

## 六、前端模块设计

### 6.1 已完成文件（UI 版本 —— 本次 commit）

| 文件 | 行数 | 作用 |
|---|---|---|
| 新 `components/aspice/swe3/EngineeringUploadPanel.tsx` | ~110 | zip 拖拽上传 + 文件统计 |
| 新 `components/aspice/swe3/ModulePathConfigEditor.tsx` | ~180 | glob 规则编辑 + 实时命中预览 + "扫描本模块" |
| 新 `components/aspice/swe3/FocusFunctionsPicker.tsx` | ~220 | 文件分组 + 搜索/过滤 + 联动勾选 + 手工添加 |
| 新 `components/aspice/swe3/FunctionDetailEditor.tsx` | ~140 | 单函数详情编辑（声明/介绍/参数/返回值/PlantUML） |
| 新 `mocks/swe3MockData.ts` | ~220 | A001/A002 完整 scan 样例 + 4 个 mock 异步函数 |
| 改 `components/aspice/Swe3Step.tsx` | +~120 | 顶部 Switch + 3 个新 Collapse + AI 进度浮层 |
| 改 `components/aspice/swe3/ModuleDesignEditor.tsx` | +~10 | 加 `hasCameraSecurity` prop，受控隐藏 A008 Tab |
| 改 `types/aspice.ts` | +~90 | 11 个推送 D 新类型 |
| 改 `stores/useAspiceStore.ts` | +~60 | 5 个 push_d setter |

### 6.2 UI 结构

```
┌─ Alert（14 章说明） ─────────────────────────┐
├─ Card 顶部工具栏 ───────────────────────────┤
│  [Switch 包含 Camera Security]              │
│  [规则派生] [AI 批量补齐 N] [导出]           │
│  Tag: 模块/扫描/关注                         │
├─ Collapse ─────────────────────────────────┤
│  🗂 工程代码上传（推送 D）                   │
│  📂 模块代码路径配置（推送 D，Tabs 9 模块） │
│  🎯 关注函数选择（推送 D，Tabs 9 模块）      │
│  📜 第 1~2 章 概述 + 术语                    │
│  🧩 第 3 章 构成追溯                         │
│  🔧 第 4~10 章 模块详细设计（A008 可隐）    │
│  📘 第 13 章 共通定义                        │
│  ⚡ 第 11/12/14 章 性能/评估/集成            │
└────────────────────────────────────────────┘
AI 进度浮层：固定右下，Progress + 当前函数名
```

### 6.3 关键交互

**流程 Demo（可点通跑完全程，全 mock）**：

1. 展开 "🗂 工程代码上传" → 拖入 `.zip` → 500ms 后显示 23 文件统计
2. 展开 "📂 路径配置" → 点开 A001 → 点 "自动推测" → 自动追加 2 条规则 → 命中预览 3 文件
3. 点 "扫描本模块" → 1.5s loading → Tab 徽章 "已扫 10 函数"
4. 展开 "🎯 关注函数" → 切 A001 → 在 .h 勾选 DriverCreate → .cpp 同名自动勾选并显 "联动 2 处"
5. 顶部搜索 "Init" → 实时过滤 → 剩 2 条
6. 回顶部点 "AI 批量补齐 3 关注函数" → 确认 → 右下角 Progress 浮层 → 2.4s 后完成
7. 展开 "第 4~10 章" → A001 Tab 下已见 scan 填充的类列表
8. 切换 Switch 关闭 Camera Security → A008 Tab 瞬间隐藏 → docx 导出时自动跳过第 10 章

---

## 七、docx 第 4 章 最终结构（后端落地时实现）

每个模块（以 A001 Serializer 为例）：

```
4.1 Serializer（MAX96717F）
    4.1.1 功能描述
    4.1.2 类图（PlantUML 源码 / 占位）
    4.1.3 类描述
        4.1.3.1 MAX96717FDeviceDriver
            - 类名 / 继承 / 简介
            - 成员常量表 / 成员变量表
            4.1.3.1.1 函数列表（表格：D-ID / 函数名 / 介绍）
            4.1.3.1.2 关注函数详情（展开）     ← AI 填充
                [D001-Serializer-function-001] DriverCreate
                  - 函数介绍（AI）
                  - 参数表 / 返回值表
                  - PlantUML 流程图源码
                [D001-Serializer-function-002] InitializeDevice
                  ...
            4.1.3.1.3 原始 NV 函数列表           ← SDK 未关注函数
                表格：函数名 / 简介（doc_comment 自动截取）
    4.1.4 独立函数（自由函数）
    4.1.5 单元时序图（PlantUML 源码）
```

**关键区分**：
- `is_sdk=false` + `focused=true` → 4.1.3.1.2 详细展开
- `is_sdk=true` + `focused=true` → 同上
- `is_sdk=true` + `focused=false` → 4.1.3.1.3 原始 NV 列表
- `is_sdk=false` + `focused=false` → 4.1.3.1.1 函数列表（不展开）

---

## 八、落地计划（第二阶段，约 11~12 天）

### 后端 S1~S6

| 阶段 | 内容 | 预计 |
|---|---|---|
| S1 | engineering_store：zip 上传/解压/元数据 | 1d |
| S2 | code_scanner regex 层：类/函数/参数提取 | 2d |
| S3 | code_scanner libclang 层（可选，默认关） | 1d |
| S4 | swe3_ai.py 4 方法 + SSE 补齐端点 | 2d |
| S5 | arch_generator_swe3 第 4 章改造 | 2d |
| S6 | 9 个 API 端点 + migrate + 集成测试 | 1d |

### 前端 F1~F4（UI 版本已完成，剩联调）

| 阶段 | 内容 | 预计 |
|---|---|---|
| F1 | 替换 mock 为真实 axios 调用 | 0.5d |
| F2 | SSE 进度接入 | 0.5d |
| F3 | 扫描结果 → ModuleDesignEditor 填充 | 0.5d |
| F4 | 自测 + E2E | 0.5d |

### E2E & 文档

| 阶段 | 内容 | 预计 |
|---|---|---|
| E2E | 完整走一遍：上传 → 扫描 → 关注 → AI → 导出 docx | 1d |
| Doc | 更新本文档 / 用户手册 | 0.5d |

---

## 九、决策附录

### 9.1 libclang 为何默认不装

- 用户默认跑的是公司内嵌入式 Linux 开发机，无管控权限安装额外库
- libclang 价值主要在**参数签名精确度**（含模板展开），本场景大多数函数是普通 C/C++ 声明，regex 够用
- 若需精确签名，用户手动 `pip install libclang` 后 scanner 自动启用

### 9.2 PlantUML 为何不渲染 PNG

- 后端代理渲染（Kroki / 公网 plantuml.com）需外网
- 用户内网环境**无稳定渲染服务**；本地部署 Java + PlantUML 增加运维负担
- 存源码可随时搬到任何地方渲染，灵活性最大

### 9.3 scan_cache 为何独立存

- 单模块扫描结果可达数十 KB（大项目几百 KB）
- 塞 project.json 会拖慢项目加载（现在 project.json <50KB，希望保持）
- 独立文件便于按模块增量更新，不污染主 project.json 的 git diff

---

## 十、本次 commit 范围（UI 版本）

- ✅ 完整数据模型（11 类型）
- ✅ 5 个 setter + default push_d
- ✅ 4 个新 UI 组件（Upload / PathConfig / FocusPicker / FunctionDetail）
- ✅ Swe3Step 顶部 Switch + 3 新 Collapse + AI 浮层
- ✅ ModuleDesignEditor 条件隐藏 A008
- ✅ Mock 数据 + 异步函数（上传/扫描/预览/AI 补齐）
- ✅ `npx tsc --noEmit` 0 error

- ⏸ 后端 engineering_store / code_scanner / swe3_ai —— 第二阶段
- ⏸ 真实 zip 解析 / regex 扫描 / AI 调用 —— 第二阶段
- ⏸ docx 第 4 章改造 —— 第二阶段

---

## 十一、第二阶段实现落地记录（2026-10-12）

> 后端 + 前端联调已完成；mock 全部替换为真实 API，`npx tsc --noEmit` 0 error，
> `backend/venv/bin/python -c "from app.main import app"` 导入 98 条路由无误。

### 11.1 后端新增/修改文件（最终形态）

| 文件 | 状态 | 关键内容 |
|---|---|---|
| `backend/app/core/engineering_store.py` | 新建 | `receive_upload()` 流式写盘 + 安全解压；`build_meta()` 聚合统计；`match_files()` fnmatch + `foo/**` 前缀兜底；`read_scan_cache / write_scan_cache`；SDK 识别：`nvsipl / nvmedia / drive-os / drive_os / nvscievent / nvscibuf`；`.h/.hpp/.hh/.c/.cpp/.cc/.cxx` 过滤 |
| `backend/app/core/code_scanner.py` | 新建 | regex 层：`_CLASS_RE / _FUNC_RE / _CONST_DEFINE_RE / _DOC_RE`；`_strip_comments` 保留换行；`_find_matching_brace` 定位 class 体；`_parse_params` 处理模板 `<...>` + 括号 `(...)` 嵌套；`_split_type_name`；1.5 MB 单文件上限；`SCANNER_VERSION = "regex-1.0"` |
| `backend/app/ai/prompts/swe3_augment.py` | 新建 | 4 对 Prompt：`intro / flow / class_diagram / sequence_diagram`；统一指令：无 markdown fence、`@startuml ... @enduml` 包裹、中文叙述、禁止营销语言 |
| `backend/app/core/swe3_ai.py` | 新建 | `Swe3AI` 包装 `AIService`；`AICache(ttl_hours=24)` 命名空间化缓存；`strip_plantuml_fences` 工具；4 个 async 方法，异常/关闭时返回 `None` |
| `backend/app/core/arch_sections_swe3.py` | 修改 | 新增 `default_push_d()`；集成到 `default_swe3()` |
| `backend/app/core/creator_store.py` | 修改 | `_migrate_swe3` 补齐 `push_d` 缺失字段 |
| `backend/app/api/aspice_routes.py` | 修改 | 新增 10 个端点（见下 11.2）；`SaveSwe3Request` 加 `push_d`；`_get_push_d` / `_upsert_by_component` helper |
| `backend/app/core/arch_generator_swe3.py` | 修改 | `export_swe3_docx` 读 `has_camera_security`；跳过 A008 时章节号连续；`_render_module_section(..., push_d=)`；新增 `_render_push_d_scan` 产 6.1 关注函数详情 / 6.2 原始 NV 函数列表 / 6.3 其余项目函数清单 三子节 |

### 11.2 后端 API 端点清单（最终版，10 条）

| # | Method | Path | 作用 | 关键细节 |
|---|---|---|---|---|
| 1 | POST | `/aspice/projects/{id}/swe3/engineering/upload` | 上传 .zip 工程 | 多部分；`UploadTooLarge → 413`；`UnsafeArchive → 400`；流式 `stream_save` + `safe_extractall` |
| 2 | DELETE | `/aspice/projects/{id}/swe3/engineering` | 清空工程 | 保留 `module_code_sources` 结构，`scan_hit_count` 归零 |
| 3 | GET | `/aspice/projects/{id}/swe3/engineering/preview-match` | glob 命中预览 | query `?patterns=...&excludes=...`；返回 `{total, sample[0:100]}` |
| 4 | PUT | `/aspice/projects/{id}/swe3/modules/{cid}/path-config` | 更新模块路径规则 | `PathConfigRequest { path_patterns[] }` |
| 5 | POST | `/aspice/projects/{id}/swe3/modules/{cid}/scan` | 扫描单模块 | 跑 scanner，更新 `scan_indices`（**轻量**：仅 stats + 扫描时间）+ `module_code_sources`；全量 `files` 写 scan_cache 盘上文件 |
| 6 | GET | `/aspice/projects/{id}/swe3/modules/{cid}/scan` | 读完整扫描 | 从 `scan_cache/<cid>.json` 读 |
| 7 | PUT | `/aspice/projects/{id}/swe3/modules/{cid}/focus` | 更新关注集 | `FocusRequest { focused_keys[], manual_additions? }` |
| 8 | POST | `/aspice/projects/{id}/swe3/ai/augment` | **SSE 批量补齐** | `StreamingResponse(text/event-stream)`；`event: progress / done`；完成后批量落盘 scan_cache |
| 9 | POST | `/aspice/projects/{id}/swe3/ai/augment-one` | 单函数 AI 补齐 | `AugmentOneRequest { component_id, key }`；返回 `{ai_intro, ai_flowchart, extracted_by}` |
| 10 | PUT | `/aspice/projects/{id}/swe3/camera-security` | 开关 Camera Security | `CameraSecurityRequest { has_camera_security }` |

### 11.3 前端 mock → 真实 API 映射

| 组件 | 原 mock | 现 API | 补充逻辑 |
|---|---|---|---|
| `EngineeringUploadPanel.tsx` | `mockUploadEngineering` / local-only clear | `uploadEngineering` / `clearEngineering` | 300s timeout；上传前 `projectId` 守卫 |
| `ModulePathConfigEditor.tsx` | `mockPreviewMatch` / `mockScanModule` | `previewMatch`（300ms 防抖）/ `scanModule` / `putPathConfig` | 每次改规则 → `persist()` → PUT 持久化；扫描后 `onScanned` 把全量 scan（含 files）写进 Zustand |
| `FocusFunctionsPicker.tsx` | 直接读 store | `getModuleScan` 懒加载 + `putFocusFunctions` 持久化 | 刷新页面后 `scan.files` 为空 → `useEffect` 拉取补齐；每次 toggle/手工添加 → `persistFocus` PUT |
| `Swe3Step.tsx` | `mockAiAugment` / `setSwe3HasCameraSecurity` 本地 | `augmentFocusFunctions`（SSE） / `setCameraSecurity`（+ 乐观更新 + 失败回滚） | 批量补齐成功后 `Promise.all` 调 `getModuleScan` 回填所有已扫模块 |
| `FunctionDetailEditor.tsx` | `mockAiAugment` 单函数 | `augmentOneFunction` | 需传 `componentId` 入参；从 store 读 `projectId` |

### 11.4 symbol key 落地

- 生成：`code_scanner._scan_source` 产函数时拼 `{file_rel}::{class_or___free__}::{name}::{param_sig_sha1[0:8]}`
- 定位：`find_function_by_key(scan, key)`（线性，O(N)；N ≤ 几千）
- 同名跨文件联动：前端 `sameNameIndex[c.name::fn.name]` → siblings → 一次 toggle 影响全部 → `putFocusFunctions` 批量 PUT

### 11.5 存储布局（最终）

```
runtime/aspice-projects/<pid>/
├── project.json              # push_d.scan_indices 仅 { component_id, scanned_at, scanner_version, stats }
└── swe3/
    ├── engineering_src/      # 解压 zip
    ├── engineering_meta.json # { zip_name, include_root, code_roots, total_files, sdk_files, custom_files, uploaded_at, file_tree_sample }
    └── scan_cache/
        ├── A001.json         # { component_id, scanned_at, scanner_version, files[], stats }
        └── ...
```

### 11.6 docx 新章节结构（已实现，模板为模块 6）

对每个模块的 `6.X Focus Scan` 子节：

- **6.X.1 关注函数详情** — 对每个 focused key：
  - 函数声明（code 段）
  - 介绍（`ai_intro`）
  - 参数表 / 返回值表
  - PlantUML 源码块（`ai_flowchart`，用 ```plantuml 包裹便于 docx 阅读）
- **6.X.2 原始 NV 函数列表** — SDK 非关注函数：`is_sdk=True AND key∉focused`，表格形式（函数名 / 源文件 / 参数签名）
- **6.X.3 其余项目函数清单** — 非 SDK 非关注函数：`is_sdk=False AND key∉focused`，表格形式

Camera Security 关闭时：A008 整个模块与下方第 10 章一并跳过，章节号连续递减。

### 11.7 验证记录（已通过）

| 项 | 命令 | 结果 |
|---|---|---|
| 后端 import | `backend/venv/bin/python -c "from app.main import app"` | `OK 98 routes` |
| 前端类型 | `cd frontend && npx tsc --noEmit` | 0 error |
| 回归 | 老项目 `_migrate_swe3` 读时补齐 `push_d` 默认值 | 不改写盘上文件，下次主动保存才落盘 |

### 11.8 已知边界 / 下一步建议

- scan_cache 单模块超过数 MB 时前端 Zustand 持有可能慢 → 后续可按文件级懒加载
- `code_scanner` 对宏模板展开有限（如 `IMX728_FUNC(name)` 这类预处理器把戏需用户手动"手工添加未扫到函数"）
- PlantUML 仍不渲染 PNG；若未来允许外网，可在 docx 导出阶段加代理渲染并嵌图
- 建议 E2E：`bash start.sh` → 上传含 `include/` 和 2~3 个 `.cpp` 的小 zip → 为 A001 配 `include/MAX96717F/**` 规则 → 扫描 → 勾 1 个关注函数 → AI 批量 → 导出 docx → 检查 6.1/6.2/6.3

### 11.9 路径规则写法（matcher 已放宽，支持 5 种写法）

实际用户填的往往是"模块代码目录名"而不是严格 glob。`engineering_store.match_files` 已把匹配器放宽：

| 写法示例 | 行为 |
|---|---|
| `nvsipl/devblk/devices/MAX96717FSerializerDriver` | 子树递归匹配（相对工程根） |
| `nvsipl/devblk/devices/MAX96717FSerializerDriver/` | 同上（自动剥尾斜杠） |
| `nvsipl/devblk/devices/MAX96717FSerializerDriver/**` | 同上（自动剥 `/**`） |
| `MAX96717FSerializerDriver` | **裸目录名**：匹配工程下任意层级的该目录子树 |
| `**/MAX*.cpp` 或 `include/**` | 走标准 fnmatch（通配符存在时） |

实现要点：
- 规则先 `strip` + `\\→/` + 剥首尾 `/` + 剥尾 `/**` 做归一化
- 不含通配符时按子树处理；裸名（无 `/`）作为"任意层级的目录名"检索
- 含通配符时走 fnmatch，`**` 近似退化为 `*`
- 排除规则相同判定逻辑

前端 placeholder 改为 `nvsipl/devblk/devices/MAX96717FSerializerDriver`；
顶部加「写法说明」Tooltip 列三种常用写法；
`guessPathPatterns(slug)` 由 `include/<slug>/**, src/<slug>/**` 改为 `<slug>, src/<slug>` 两条裸目录建议。

---

**撰写**：2026-10-12
**版本**：v2.0（第二阶段落地定稿；§十一记录实际实现）
**后续**：E2E 跑一遍 → 根据实际 zip 调整扫描兜底规则 → 推送 E 或正式合并主干。
