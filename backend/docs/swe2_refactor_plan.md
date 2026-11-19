# SWE.2 架构&概要设计书 对齐 PreDev 的重构计划（v3）

> **v3 补丁 2026-11-17：MODULE_SHORT 已经改成 PreDev 口径**（旧 v2 "不动编号" 的前提不成立）
>
> - 旧 `MODULE_SHORT`（已废弃）：A005=CameraSecurity / A006=nvsipl_camera / A007=nvsipl_multicast / A008=PMIC
> - 新 `MODULE_SHORT`（PreDev 口径，已落地）：A005=nvsipl_camera / A006=nvsipl_multicast / A007=PMIC / A008=CameraSecurity
> - 以下正文中所有 "A005 Camera Security" / "4.8 ... 编号：A005" 的措辞，应读作 **A008 Camera Security** / **4.8 ... 编号：A008**。
> - 原因：audit 发现 `arch_sections_swe3.py` / `arch_generator.py` / `arch_generator_swe3.py` / `creator_store.py` / 前端 `Swe2Step.tsx` / `Swe3Step.tsx` / `ModuleDesignEditor.tsx` / `project.json` 本来就是 PreDev 口径，只有 `MODULE_SHORT` / `MODULE_FUNCTION_DESC` / `MODULE_ORDER` / `MODULE_CHAPTERS` 这 4 处用的是旧口径；统一到 PreDev 口径代码面最小。
> - `arch_generator_swe3_v3.MODULE_ORDER` 已改为 `["A001","A003","A002","A004","A008","A005","A006","A007"]`（物理章节顺序对应 PreDev）。
> - **数据零迁移**：所有现有项目的 project.json / scan_cache 本来就是 PreDev 口径。


> 参考文档：`/home/tstj/下载/PreDev_软件架构&概要设计书V1.0.docx`
> 配置目录样例：`/media/tstj/2t/work/sdk/qnx_stand_7.2.4.0/nvidia/Qnx_Standard_7.2.4.0/drive-qnx/samples/nvmedia/nvsipl/query/database/predev_mixgroup`
> 当前代码：`backend/app/core/arch_sections.py` + `backend/app/schemas/aspice/swe2_schema.py` + `backend/app/core/engineering_store.py` + `backend/app/core/arch_generator_swe3_v3.py`
>
> **本计划只谈"每章要什么 / 哪里会变 / 和 SWE.3 共用什么"，不写代码。**
> v2 相对 v1：收编了"配置文件 AI 识别"子方案，收编了"模块编号/顺序对齐 SWE.3"子方案，去掉了之前过度的"编号迁移"。

---

## 0. 结论先行（v2）

1. 现 SWE.2 schema 覆盖了 PreDev 约 **55%** 的章节；缺 3.1/3.2 挂字段/3.3.1/3.3.2/3.3.3/3.4.x 总章/5/6。
2. `arch_sections.py` 作为 SWE.2/SWE.3 共用规则层**不需要重起另一个模块**，继续扩充。
3. **模块编号不动，只调顺序**。`MODULE_SHORT` 的 A001-A008 保留现状；SWE.3 的 `MODULE_ORDER` 和 SWE.2 的 4.X 遍历顺序统一调成 PreDev 的顺序。
4. **代码仓库扫描 / 函数聚合 / PlantUML 渲染已在 SWE.3 成熟**，SWE.2 应消费它们，不新写。
5. **3.3.3 配置文件章节是新增能力**：让用户选 `query/database/<project>/` 路径，AI 读取 7 份 JSON 自动生成关系图 + 字段表。

---

## 1. 模块编号 / 顺序 对齐（高优，影响后续所有 4.X 工作）

### 1.1 现状（v1 方案里误判为"错位 bug"的部分，重新定性）

**结论：MODULE_SHORT 编号本身和 SWE.3 一致（内部自洽），只是和 PreDev 顺序不一样。** 保编号、调顺序即可。

| | A001 | A002 | A003 | A004 | A005 | A006 | A007 | A008 | A009 |
|---|---|---|---|---|---|---|---|---|---|
| **当前代码** `MODULE_SHORT` | Serializer | Deserializer | EEPROM | CameraModule | CameraSecurity | nvsipl_camera | nvsipl_multicast | PMIC | Campwr |
| **当前代码** `MODULE_ORDER`（arch_generator_swe3_v3.py:40） | 1 | 3 | 2 | 4 | 5 | 6 | 7 | 8 | — |
| **PreDev 顺序** | 1 | 2 | 3 | 4 | 7（放到末尾） | 5 | 6 | 7→8（最后一个） | 9 |

→ 要做的改动：
- **保留** `MODULE_SHORT` 现状（所有历史项目数据零迁移）
- **修改** 两处顺序：
  1. SWE.3 `MODULE_ORDER` 调成 `["A001","A002","A003","A004","A006","A007","A008","A005"]`
     （把 CameraSecurity 从第 5 挪到第 8；EEPROM/Deserializer 回到自然编号序）
  2. SWE.2 导出器遍历 `components[]` 时同样按上述顺序渲染 4.X
- 新增一个常量 `PREDEV_MODULE_ORDER`（或复用 MODULE_ORDER，但必须两边共用）

### 1.2 Camera Security 作为 A005 保留的影响

A005 = CameraSecurity 在 PreDev 里排 4.8，这没问题 —— 顺序和编号本来就不需要一致。只需要：
- 4.X 章节标题仍按**顺序**自然编号："4.8 组件名称 Camera Security / 编号：A005"
- docx 里的"编号：A005"这一行是展示用的，不参与排序

### 1.2.1 Camera Security 处理方式：**和 SWE.3 保持一致 —— 只预留框架**

**重要原则（来自用户 2026-11-16 决定）**：
Camera Security 在 SWE.3 里走的是 `manual_only=True` 路径（见 `arch_generator_swe3_v3.py:52` `MODULE_CHAPTERS` 里 CameraSecurity 行 manual_only 位），只生成章节骨架 + 占位，**不自动填接口/类/函数/时序内容**，完全交给用户在导出后的 docx 里补充修改。

SWE.2 里的 4.8 Camera Security **沿用同一策略**：

- 导出器只写：
  - "4.8 组件名称 Camera Security / 编号：A005" 标题
  - "4.8.1 功能描述" 骨架（预填 `COMPONENT_FUNCTION_DESC["A005"]` 一行作为提示占位）
  - "4.8.2 功能目标（安全性目标）" 骨架 + `DEFAULT_SECURITY_GOALS` 占位
  - "4.8.3 功能模块构成" 骨架 + `DEFAULT_SECURITY_MODULES` 占位（含"此处插入功能模块构成图"提示段，不塞图片）
  - "4.8.4 Camera Security" 骨架 → 4.8.4.1 外部接口 / 4.8.4.2 内部接口 **空表（表头保留，无数据行）**
  - "4.8.5 时序图" 骨架 → 列出 4 个子标题占位（CA / I2C read / I2C write / image authentication），**不塞 PlantUML 图**
- 导出器**不**：
  - 不 AI 生成接口/时序/关系图
  - 不从 scan_cache 提取函数（和 SWE.3 manual 路径一致）
  - 不从 cryptoConfig.json 自动灌密钥矩阵（即便 §2 解析出来了）
- 前端 Swe2Step 的 A005 面板：
  - 保留现有 `security_goals` / `security_modules` 文本编辑
  - 保留接口表 / `scenarios[]` 编辑
  - **不提供"AI 生成"按钮**（和 A005 的 manual_only 定位呼应）

**理由**：
- 和 SWE.3 保持口径一致，避免同一个 A005 在两份文档里策略不同
- Camera Security 内容涉及证书/密钥矩阵，错一个字就是安全事故；完全交人工把关
- cryptoConfig.json 虽然能解析，但那是**部署配置**（linkID × key），不是 **设计文档**；两者格式/口径差异大，不适合自动灌

**schema 层面不变**：`Component.security_goals` / `security_modules` / `scenarios[]` 字段保留；只是导出路径走"骨架化"分支，和 SWE.3 的 `manual_only` 对齐。

**配置文件 §2 的 crypto 解析**（如果做了）：只在 3.3.3 配置文件章节展示，**不**向 4.8 流入 —— 两个章节数据流独立。

### 1.3 Campwr A009 继续沿用 R4.9 的克隆路径

[[aspice-module-progress]] 里 R4.9 已经把 Campwr 做成"克隆 PMIC 骨架 + 清数据 + 人工填"。SWE.2 也沿用这个策略，不新开路径。

---

## 2. query/database 配置文件 → 3.3.3 章节 的识别方案

### 2.1 目标

把 PreDev §3.3.3 的内容自动化：
- **3.3.3.1 配置文件总体结构** → 画一张关系图（platform → cameraModule → sensor/serializer/eeprom/crypto）
- **3.3.3.2.N sensor 配置详情** → 每个 sensor 一张字段清单表

### 2.2 输入（用户在 UI 里选）

用户已经通过 SWE.3 推送 D 上传了完整工程树到 `runtime/creator_projects/<id>/swe3/engineering_src/`。在上面扫一遍，找出所有候选 **query 配置根目录**：

- 判定规则：**同时包含 `*_platform.json`、`*_module.json`、`cryptoConfig.json`** 的目录即候选
- 典型路径：`.../nvsipl/query/database/predev_mixgroup/`、`.../nvsipl/query/database/max96724_imx728/` 等

前端给一个下拉，用户选一个目录作为"本项目的配置目录"（存到 `swe2.software_design.config_database_path`）。

### 2.3 后端解析（不用 AI）

配置目录固定 6-7 份 JSON，schema 固定，**纯规则解析即可，AI 只用来做后处理**：

| 文件名模式 | schema | 用途 |
|---|---|---|
| `*_platform.json` | `platformConfigs[].deviceBlocks[].{csiPort,phyMode,deserializer,cameraModules[]}` | 3.3.3.1 平台总体结构；每路 linkIndex → cameraModule → i2cAddress |
| `*_module.json` | `cameraModules[].{name,serializer,sensors,eeproms}` | 相机模组构成（ser + sensor + eeprom 组合） |
| `imx623.json` / `imx728.json` / `imx728s.json` ... | `imageSensors[].{name,cfa,width,height,fps,...}` | 3.3.3.2.N sensor 字段表 |
| `m24c04.json` | `eeproms[]` | eeprom 字段表 |
| `cryptoConfig.json` | `platformCryptoConfigs[].cryptoConfigs[].cryptoKeys[]` | A008 Camera Security 的 linkID × keyPurpose 矩阵 |

对应共用 schema 已经存在，位于 SDK 里 `query/database/schema/*.schema`（**官方权威字段字典**）— 后端解析时可用它做字段校验兜底。

### 2.4 AI 做什么（最小必要）

规则解析能产出结构化数据，但两件事规则做不好、交给 AI：
1. **自然语言摘要**：把"GropA:1111-imx728,GropB 1111-imx623,..." 之类的 `description` 字段翻译成中文说明段
2. **关系图 PlantUML 生成**：把平台 → 4 组 deviceBlock → N 个 cameraModule → N 个 serializer/sensor/eeprom 的关系画成一张 PlantUML
   - prompt 输入是规则解析后的 JSON 摘要（已精简，去冗余字段），不是 2064 行原始 JSON
   - 输出 PlantUML 源码，用户可以在前端二次编辑

### 2.5 流程

```
用户推送 D 上传工程树
  ↓
后端扫 engineering_src，用规则找出候选 query 目录（可能多个）
  ↓
前端 Swe2Step 多出一个"3.3.3 配置文件"面板，下拉选目录
  ↓
后端规则解析该目录的 6-7 份 JSON → 结构化 ConfigDatabase 对象
  ↓
AI 兜底：
  - 生成 3.3.3.1 关系图 PlantUML（挂到 ScenarioItem[]）
  - 生成每个 sensor 的中文描述段
  ↓
用户在 UI 里可调整 / 删字段 / 自己写描述
  ↓
导出时按 3.3.3 章节渲染
```

### 2.6 落到 schema

新增字段（追加到 §3 的 Group 2）：

```
software_design.config_files: {
  database_path: str          # 用户选的目录相对路径（engineering 下）
  platform: {                 # 从 *_platform.json 解析
    name: str
    description: str
    device_blocks: [{csi_port, phy_mode, deserializer, camera_modules: [...]}]
  }
  modules: [{                 # 从 *_module.json 解析
    name, description, serializer, sensors, eeproms
  }]
  sensors: [{                 # 从 imx*.json 解析（可能多份）
    name, description, i2c_address, fields: [{key, value, note}]
  }]
  eeproms: [{...}]
  crypto: {                   # 从 cryptoConfig.json 解析
    name, configs: [{link_id, keys: [...]}]
  }
  diagram_plantuml: str       # AI 生成的 3.3.3.1 关系图
}
```

### 2.7 为什么不 AI 全包

- 6-7 份 JSON 累计 2000+ 行，塞给 AI 既贵又容易漏字段
- schema 是已知的（官方 `.schema` 文件），规则解析 100% 覆盖
- AI 只做"把数据翻译成话、把关系翻译成图"这两件 LLM 真正擅长的事

---

## 3. PreDev 结构 → 代码现状差距矩阵（继承 v1，微调）

### 3.1 一级章节清单

| 章节 | 内容 | 变化性 | 现代码支持 |
|---|---|---|---|
| 封面 / 历史 / 评审 | 标准三件套 | 变 | ✓ |
| 1.1 目的 | 一句话+项目代号 | 变 | ✓ `default_overview_purpose` |
| 1.2 范围 | 预期读者固定段 | **常** | ✓ `DEFAULT_OVERVIEW_SCOPE` |
| 1.3 术语 | SWE.1/SIPL/... | **常** + 项目增补 | ✓ `DEFAULT_TERMS` |
| 1.4 参考文档 | SOW/SRS/NV Guide | 变（代号派生） | ✓ `build_ref_docs_from_project` |
| 1.5 假设 | 文件/模组/工具链 | **常** + 覆盖 | ✓ |
| 2 需求列表 | SWE.1→SWE.2 映射 | 变 | ✓ `mappings[]` |
| 3.1 简介 | 整体架构一句话 | 变 | **缺** |
| 3.2 静态信息 | 功能模块图 PlantUML | **常**结构 | ✓ 有常量，schema 需挂字段 |
| 3.3.1 外部接口（整体） | SIPL 对外接口表 | 变 | **缺** |
| 3.3.2 内部接口（整体） | 模块间接口表 | 变 | **缺** |
| 3.3.3 配置文件 | query/database 结构 + sensor 配置 | 变 | **缺**（新能力，见 §2） |
| 3.4.1 状态迁移图（总） | sensor 状态机 | 变 | **缺** |
| 3.4.2 时序图（总） | 跨模块时序 | 变 | **缺** |
| 4.1~4.9 模块设计 | 每模块一章 | 详见 3.2 | 部分 ✓ |
| 5.1 内存 / 5.2 CPU | KPI + 测法 | **半常** | **缺** |
| 6 备选架构 | "暂不涉及" | **常** | **缺**字段 |
| 7.1 集成顺序 | Deser→Ser→Sensor | **常** | ✓ `DEFAULT_INTEGRATION_ORDER` |
| 7.2 六原则 | 易/安/完/规/扩/开 | **常** | ✓ `DEFAULT_INTEGRATION_PRINCIPLES` |

### 3.2 4.X 各模块字段差异（PreDev 实测）

| 模块（按 PreDev 顺序） | 编号 | PreDev 实章 | schema 缺口 |
|---|---|---|---|
| 4.1 Serializer | A001 | 功能描述/外/内/状态迁移/时序 | `scenarios[]` kind=状态迁移 ✓ |
| 4.2 Deserializer | A002 | 功能描述/外/内/时序 | ✓ |
| 4.3 EEPROM | A003 | 功能描述/外/内/时序 | ✓ |
| 4.4 CameraModule | A004 | 功能描述/**Class Description**/外/内/状态迁移/时序 | `classes[]` ✓ |
| 4.5 nvsipl_camera | A006 | **多段功能描述 + 每段溯源 ID**/外/内/时序 | `function_desc: str` 要支持 list |
| 4.6 nvsipl_multicast | A007 | 同上 | 同上 |
| 4.7 PMIC | A008 | 功能描述/外/内/时序 | ✓ |
| 4.8 CameraSecurity | A005 | 功能描述/**安全性目标**/**功能模块构成**/外/内/**4 个时序**(CA/I2C读/I2C写/image) | `security_goals/modules` ✓，4 时序→`scenarios[]` ✓ |
| 4.9 Campwr | A009 | 功能描述/外/内/时序 | 走 R4.9 克隆路径 ✓ |

---

## 4. SWE.2 ↔ SWE.3 共用点

### 4.1 已共用（保持）

| 共用物 | SWE.2 | SWE.3 |
|---|---|---|
| `MODULE_SHORT` | 组件编号映射 | 模块章节定位 |
| `MODULE_SPLIT_POLICY` | — | L5 展开策略 |
| `MODULE_FUNCTION_DESC` | 4.X.1 默认文案 | 模块概述 |
| `DEFAULT_TERMS` / `DEFAULT_ASSUMPTIONS` | ✓ | **应扩给 SWE.3 用** |
| `DEFAULT_INTEGRATION_*` | ✓ | — |
| `DEFAULT_MODULE_DIAGRAM_PLANTUML` | ✓ | ✓ |
| `MODULE_ORDER`（新增，两边共用） | 4.X 遍历 | docx 章节顺序 |

### 4.2 应共用但现在没共用的（**重构重点**）

| 能力 | SWE.3 在哪 | SWE.2 现状 | 共用方式 |
|---|---|---|---|
| 代码仓库上传 | `engineering_store.receive_upload / tree_write_files` | 无 | SWE.2 直接用同一棵工程树 |
| 工程元信息 | `engineering_meta.json` | 无 | 读同一份 |
| 文件扫描 | `code_scanner.scan_module` | 无 | 拿模块组件 ID 复用 |
| 函数/类聚合 | `_list_functions` | 无 | SWE.2 的 4.X 接口表派生自 scan 结果 |
| **query 目录发现** | 无（新能力） | 无 | **新共用**：扫 engineering_src 找 query/database 候选 |
| PlantUML 渲染 | `template_engine.add_plantuml_image` | ✓ | 已共用 |
| AI 功能描述 | `arch_generator_swe3_v3` 内嵌 | 无 | SWE.2 的 4.X.1 可 AI 兜底 |
| 场景图 AI 生成 | 部分 | 无 | 共用 |

### 4.3 不共用

需求映射（SWE.2 独有）、L5 函数详述（SWE.3 独有）、资源消耗/集成（SWE.2 独有）、原始 NV 函数列表（SWE.3 独有）、配置文件章节（SWE.2 独有）。

---

## 5. 改动分组（按依赖排序）

> 每组内先做数据/配置，再做 schema，再做模板，最后做 UI。

### Group 1：顺序对齐 + 常量扩充 (**零风险**，取代 v1 的编号迁移)

1. `arch_sections.py` 新增 `PREDEV_MODULE_ORDER = ["A001","A002","A003","A004","A006","A007","A008","A005"]`，加注释说明"按 PreDev §4 顺序"。
2. `arch_generator_swe3_v3.py:MODULE_ORDER` 改引用上面的常量。
3. `arch_sections.py` 追加 `DEFAULT_SCOPE_READERS`、`DEFAULT_ALTERNATIVE_ARCH = "暂不涉及，目前仅在 NV 框架上实现。"` 等常值文案。
4. `MODULE_FUNCTION_DESC` 补齐 A005~A008 对齐 PreDev 实文（现仅 A001~A004 和部分 A008）。

### Group 2：Schema 扩展

`swe2_schema.py` 新增（追加字段，不删现有）：

```
Swe2Context
├── overview（已有）
├── mappings（已有）
├── software_design           ← 新增 3.x
│   ├── intro: str
│   ├── module_diagram_plantuml: str
│   ├── external_interfaces: list[InterfaceItem]
│   ├── internal_interfaces: list[InterfaceItem]
│   ├── config_files: ConfigDatabase     ← 见 §2.6
│   ├── state_diagrams: list[ScenarioItem]
│   └── sequence_diagrams: list[ScenarioItem]
├── components（已有）
│   └── function_desc: str | list[FunctionDescSegment]  ← 多段 + 溯源
├── resources                 ← 新增 5.x
├── alternative_arch: str     ← 新增 6（默认预填 DEFAULT_ALTERNATIVE_ARCH）
└── integration（已有）
```

### Group 3：扫描共用层（SWE.2 消费 SWE.3 成果）

1. 在 `code_scanner.py` / `arch_skeleton_scanner.py` 里抽出共用方法：
   - `list_module_public_interfaces(scan) -> list[InterfaceItem]`
   - `list_module_internal_interfaces(scan) -> list[InterfaceItem]`
2. 新增 `config_db_scanner.py`（新文件）：
   - `discover_query_dirs(engineering_root) -> list[str]`：按 §2.2 规则找候选
   - `parse_config_db(root) -> ConfigDatabase`：按 §2.3 规则解析
3. 不动 SWE.3 已跑通路径，仅方法抽取 + 新能力。

### Group 4：模板

1. 基于 PreDev 样式重画 `swe2_arch.docx`：
   - 1~7 章骨架 1:1 对齐 PreDev
   - 3.3.3.2 子章用 `{%p for sensor in software_design.config_files.sensors %}` 动态展开
   - 可选章节（如无 sensor 时跳过 3.3.3.2）用 `{%p if %}`
2. 保留 `swe2_arch_sample.docx` 做 diff 参考。

### Group 5：前端编辑器

1. `Swe2Step.tsx` 补 3/5/6 面板：
   - 3.1 简介：textarea
   - 3.2 模块图：PlantUML 编辑 + 预览
   - 3.3.1/3.3.2：接口表 + "从扫描结果导入"按钮
   - **3.3.3 配置文件（新面板）**：
     - 下拉选 query 目录（候选来自 `discover_query_dirs`）
     - 解析预览：显示 platform/modules/sensors/eeproms/crypto 摘要
     - "AI 生成关系图" + "AI 生成描述段" 按钮
     - 字段表可手工调整
   - 3.4.1/3.4.2：ScenarioEditor
   - 5 资源：KPI 表 + 内存/CPU 两段
   - 6 备选架构：textarea，默认自动填
2. 模块编辑器 4.X：
   - A004 保留 Class Description
   - **A005 Camera Security：仅文本/表格编辑，无"AI 生成"按钮，和 SWE.3 的 manual_only 定位一致**
   - A006/A007（nvsipl_camera/multicast）加"分段功能描述"编辑

### Group 6：导出

1. `arch_generator.py` 对齐新 schema。
2. 整合 SWE.3 v3 的 PlantUML 渲染、R4.10 底色清理、R4.9 克隆-清骨架策略。
3. 导出后做 diff：`generated.docx` vs PreDev 参考，章节数量/顺序 1:1。

---

## 6. "哪里会变 / 哪里固定" 决策表

| 位置 | 固定来源 | 变动来源 | 覆盖优先级 |
|---|---|---|---|
| 1.1 目的 | `default_overview_purpose(code)` | 用户 | 用户 > 默认 |
| 1.2 范围 | `DEFAULT_OVERVIEW_SCOPE` | 用户 | 用户 > 默认 |
| 1.3 术语 | `DEFAULT_TERMS` | 用户追加 | 合并 |
| 1.4 参考文档 | `build_ref_docs_from_project` | 用户追加 | 合并 |
| 1.5 假设 | `DEFAULT_ASSUMPTIONS` | 用户 | 用户 > 默认 |
| 2 需求映射 | — | SWE.1 派生 + 用户 | 派生 → 修订 |
| 3.1 简介 | AI 兜底 | 用户 | 用户 > AI |
| 3.2 模块图 | `DEFAULT_MODULE_DIAGRAM_PLANTUML` | 用户 | 用户 > 默认 |
| 3.3.1/3.3.2 接口 | scan 派生 | 用户勾选/增删 | 用户 > 扫描 |
| **3.3.3 配置文件** | **query 目录规则解析 + AI 摘要** | 用户调字段 | 用户 > AI > 规则 |
| 3.4.x 图 | AI 兜底 | 用户 | 用户 > AI |
| 4.X.1 功能描述 | `MODULE_FUNCTION_DESC` | 用户/AI | 用户 > AI > 默认 |
| 4.X.2 接口 | scan 派生 | 用户 | 用户 > 扫描 |
| 4.X.3+ 场景 | AI 兜底 | 用户 | 用户 > AI |
| **4.8 Camera Security (A005)** | **仅骨架 + `DEFAULT_SECURITY_*` 占位** | **用户** | **仅用户**（和 SWE.3 manual_only 对齐，不 AI 不 scan 不 crypto 灌入） |
| 5 资源 | KPI 模板 | 用户填实测 | 合并 |
| 6 备选架构 | `DEFAULT_ALTERNATIVE_ARCH` | 用户 | 用户 > 默认 |
| 7.1 集成顺序 | `DEFAULT_INTEGRATION_ORDER` | 用户 | 用户 > 默认 |
| 7.2 六原则 | `DEFAULT_INTEGRATION_PRINCIPLES` | 用户改 desc | 用户 > 默认 |

---

## 7. 风险与回滚

| 项 | 风险 | 缓解 |
|---|---|---|
| MODULE_ORDER 调顺序 | 低（仅渲染顺序变化，数据零迁移） | 保留原数组做 fallback，env 可切回 |
| schema 扩字段 | 低（都给默认值，向后兼容） | — |
| 模板换新 | 中（docxtpl 语法踩坑） | 保留 `swe2_arch_v1.docx`；env `SWE2_TEMPLATE_VERSION=v1\|v2` |
| query 目录发现误报 | 低 | 规则严格（三文件都存在才报），同时允许手工指定路径 |
| AI 生成 PlantUML 失败 | 中 | 复用 [[push-g-plan]] 的 retry + 占位策略；失败时用占位 PNG |
| SWE.3 侧抽方法 | 低 | 只重命名+加公共签名，不改行为 |

---

## 8. 本次计划 **不包含** 的事

- 任何代码修改
- 具体 SQL/存储迁移脚本
- 前端 UI 的最终布局 mockup
- 3.3.3.1 关系图的 AI prompt 工程细节

用户确认计划后再分 PR 推进；建议 Group 顺序 1→2→3→4→5→6。

---

v2 生成于 2026-11-16（原 v1 后一次迭代）。v2 修正点：
- MODULE_SHORT 不动，改为调 MODULE_ORDER（零风险）
- 加入 §2 query/database 配置文件识别方案（规则解析为主、AI 兜底）
- 模块顺序和 SWE.3 统一到 PreDev 版

v2.1 补丁 2026-11-16：
- **A005 Camera Security 对齐 SWE.3 manual_only 策略** —— SWE.2 的 4.8 章节同样只出骨架 + 占位，不 AI 不 scan 不从 cryptoConfig 自动灌，完全交人工（§1.2.1）
