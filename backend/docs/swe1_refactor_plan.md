# SWE.1 需求分析重构方案

**版本**：v1.0（2026-11-20）
**分支**：phase4-dev（与 SWE.2 / SWE.3 并行开发）
**作者**：Camera Driver 开发组 × AI 助手讨论产出

---

## 0. 背景与定位转变

### 现状问题

当前 SWE.1 的工作模型是 **"客户原始需求文本 → AI 粗解析 → 自动分 OR/R ID → 塞进 24 列表"**：

1. **解析对象错位**：AI 吃客户原始文档（PPT/邮件/中英混杂需求书），无法区分哪些是 camera driver 该关注的，一视同仁切条 → 大量无效需求
2. **工作者的专业判断无入口**：资深驱动工程师读完客户需求后会在脑子里过一遍 "这条我做 / 这条忽略 / 这条拆成 3 条"，这个判断过程**没有地方承载**，解析完只能删删删
3. **溯源 ID 本末倒置**：OR_ID 由工具自动编（`req_generator.py:48`），但客户文档里**本来就有自己的编号**（Req_Sensor_135、章节号），工具生成的 ID 和客户 ID 无关联，客户问"你们对 REQ-CAM-042 做了什么"答不出
4. **无闭环反馈**：AI 错了工程师改了，这个"改法"不回流成经验，每个项目从零开始

### 重构后的定位

SWE.1 从 **"AI 自动化需求解析器"** 重构为 **"需求工程台账 + 可学习的推荐助手"**：

- AI 永远给**候选不给结论**，工程师永远是决策者
- 80% 场景（工程师已处理好需求表）走**结构化回灌**，不走 AI
- 20% 场景（拿到客户原始文档）走 AI 候选面板，候选 + 置信度 + 人工打勾
- 工程师的每次决策（收录/驳回/修改）自动成为**跨项目样本**，RAG 推动下个项目更准

### 关键约束

- **ID 规则**遵循 [Pangu_ASPICE ID编号规则V1.0.docx](../../../../../home/tstj/下载/Pangu_ASPICE%20ID编号规则V1.0.docx)：
  ```
  OR:    项目代号_序号           例: Pangu_001
  SWE.1: OR + -R + 序号          例: Pangu_001-R001         ← req_id
  SWE.2: SWE.1 + -A + 序号       例: Pangu_001-R001-A001
  SWE.3: SWE.2 + -D + 序号       例: ...-A001-D001
  ```
- **SWE.1 只传 req_id 给 SWE.2**，不管 SWE.2 组件归属。组件（A001-A009）由工程师**在 SWE.2 页面手工选**
- **回灌尊重工程师已填的 OR/ReqID**，不重编；仅工程师未填时才派生新 ID

---

## 1. 架构图

```
┌─────────────────────────────────────────────────────────┐
│  L1  需求源（Requirement Sources）                      │
│   ├─ 客户原始文档（PDF/DOCX/XLSX）  → 20% 场景          │
│   └─ 工程师已处理需求表（XLSX/DOCX） → 80% 场景（主）   │
└─────────────────────────────────────────────────────────┘
                     ↓ 回灌向导 A1-A6 / AI 候选 + 人工打勾
┌─────────────────────────────────────────────────────────┐
│  L2  需求项台账（Requirements）                         │
│   external_id | or_id | req_id | 中文描述 | 原文        │
│    | 分类 | ASIL | 来源 | 审阅状态 | requirement_module │
└─────────────────────────────────────────────────────────┘
                     ↓ 导出 / SWE.2 透传
┌─────────────────────────────────────────────────────────┐
│  L3  产物                                               │
│   SRS docx / 需求详表 xlsx / 溯源表 / req_id → SWE.2    │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  侧车：跨项目样本库 runtime/aspice_samples/             │
│   samples.jsonl + BM25 索引 + 技术名词词典              │
│   每次收录/驳回自动落盘 → 下个项目 AI 候选时注入 prompt │
└─────────────────────────────────────────────────────────┘
```

---

## 2. 数据模型变更

### 2.1 Requirement 新增字段

| 字段 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `external_id` | str? | 否（强推荐） | 客户原文编号（PreDev 表 NO. 列，如 `Req_Sensor_135`） |
| `source_doc` | str? | 否 | 来源文件名（Input 列，如 `Harz_L3_Mmt_BSW_req-20260417-TS`） |
| `source_section` | str? | 否 | 章节号（Chapter 列，如 `sheet：sensor`） |
| `source_type` | enum | 必填 | `customer_raw` / `engineer_processed` / `manual` / `ai_suggested` / `legacy` |
| `review_status` | enum | 必填 | `pending` / `accepted` / `rejected` / `note`，默认 `accepted` |
| `confidence` | float? | 否 | 0~1，仅 `ai_suggested` 来源有值 |
| `coverage_of` | str? | 否 | `note` 类型时指向覆盖它的 or_id |
| `requirement_module` | str? | 否 | 分组行标签（帧同步/接口调用/性能稳定性等），**展示用，不参与 SWE.2 组件映射** |
| `arch_doc_hint` | str? | 否 | PreDev 表 Architecture Design Document 列，SWE.2 阶段参考用 |

### 2.2 swe1 顶层新增

```python
swe1:
    requirements: list[Requirement]      # 现有
    topology: list[Topology]             # 现有
    kpi: list[KpiItem]                   # 现有
    sources: list[SourceFile]            # 新：需求源文件记录
    coverage_notes: list[CoverageNote]   # 新：覆盖关系冗余表（备查）

class SourceFile:
    id: str                              # 文件 UUID
    file: str                            # 原始文件名
    file_path: str                       # 服务器存储相对路径
    type: Literal["customer_raw", "engineer_processed"]
    uploaded_at: str
    sheet: Optional[str] = None          # xlsx 时记录
    ingested_count: int = 0              # 已入库条数
    mapping_template_id: Optional[str] = None

class CoverageNote:
    note_req_id: str                     # 被标 note 的需求 ID
    covered_by_or_id: str                # 覆盖它的 PREDEV_xxx
    original_text: str                   # 客户原文
```

### 2.3 冲突智能更新策略

主键：**`(project_id, req_id)`**

- 回灌到**同一项目**：
  - `req_id` 已存在，**字段全同** → 跳过，计入 skipped 计数
  - `req_id` 已存在，**字段有变** → 标 `review_status=pending`，UI 显示 diff（旧值 vs 新值），工程师点"接受变更/保留原值/双向比对"
  - `req_id` **不存在** → 直接入库 `review_status=accepted`
- **跨项目**：互不影响（project_id 隔离）

---

## 3. 跨项目资源

```
runtime/
├── creator_projects/<id>/
│   └── swe1_sources/                 # 每个项目的需求源文件
│       └── <uuid>_<原始文件名>
├── swe1_mapping_templates/           # 列映射模板库（跨项目共享）
│   ├── predev_23col_v1.json
│   └── ...
└── aspice_samples/                   # RAG 样本库（跨项目共享）
    ├── samples.jsonl                 # 一行一条
    ├── bm25_index.pickle             # 启动懒加载，变更后异步重建
    └── tech_terms.txt                # 技术名词词典
```

### 3.1 映射模板 Schema

```json
{
  "id": "predev_23col_v1",
  "name": "PreDev 需求详细表 23 列",
  "header_row": 1,
  "skip_rows": [2],
  "header_fingerprint": "md5_of_sorted_column_names",
  "column_mapping": {
    "Input": "source_doc",
    "Chapter": "source_section",
    "NO.": "external_id",
    "Content": "or_desc",
    "软件需求标识": "software_mark",
    "OR": "or_id",
    "ReqID": "req_id",
    "Software Requirement Function Description": "sw_req_desc",
    "Test Case ID": "test_case_id",
    "Requirement module": "requirement_module",
    "Category": "category",
    "ASIL": "asil",
    "Requirement correctness": "correctness",
    "Demand feasibility": "feasibility",
    "exception handling": "exception",
    "Demand Priority": "priority",
    "Project Release Time": "milestone",
    "RA DeadLine": "ra_deadline",
    "Actual Time of Revise": "actual_time",
    "Feature Release Version": "release_version",
    "Owner": "owner",
    "Memo": "memo",
    "Architecture Design Document": "arch_doc_hint"
  },
  "group_detection": {
    "rule": "only_col1",
    "exclude_contains": ["PREDEV_", "Req_Sensor_"],
    "exclude_source_doc_names": true
  },
  "coverage_detection": {
    "or_is_na": true,
    "req_id_is_na": true,
    "content_pattern": ".*(覆盖|PREDEV_\\w+).*"
  },
  "created_at": "2026-11-20",
  "usage_count": 1
}
```

### 3.2 RAG 样本 Schema

```json
{
  "id": "smp_20261120_dualthor_001",
  "created_at": "2026-11-20T16:00:00",
  "project_code": "DualThor",
  "source_type": "engineer_processed",
  "original_text": "底软支持YUV图像输出：1. 计算YUV所用的颜色标准要求是BT.601_ER或BT.709_ER...",
  "action": "accepted",              // accepted / rejected / note
  "coverage_of": null,
  "result": {
    "sw_req_desc": "驱动可正常配置SerDes和Sensor...",
    "category": "Functional Requirements，Basic Functions-bring up",
    "asil": "ASIL B",
    "requirement_module": "sheet：sensor",
    "or_id": "PREDEV_001"
  },
  "tags": ["sensor", "SerDes", "RAW", "imx728", "YUV", "ISP"]
}
```

**tags 生成算法**（R3）：
- 对 `original_text` 分词（jieba 或简单正则切英文/中文片段）
- 命中 `tech_terms.txt` 的词 → 加入 tags
- `tech_terms.txt` 初版：`camera, sensor, I2C, MIPI, PMIC, EEPROM, ASIL, SerDes, YUV, RAW, ISP, MAX96xxx, imx728, imx623, OX08D, OX03C, FSYNC, SOF, EOF, metadata, 热插拔, 哨兵模式, 帧同步, 内参, ROI, 温度`

---

## 4. 回灌向导 A1-A6（R1 核心）

### A1. 文件 + Sheet 选择
- 自动过滤辅助 sheet（Cover / Document record / Input / Risk / Field description / TM Rev Hist）
- 推荐主 sheet（最大行数 + 列数 ≥ 10 的 sheet）
- 允许用户指定

### A2. 表头行定位
- 默认 r1 为英文表头，r2 中文说明跳过
- 允许改表头行号
- 预览"识别到的表头"

### A3. 列映射（★关键）
- 算当前表头的 **MD5 指纹** → 查 `swe1_mapping_templates/*.json`
- 命中已有模板 → 自动填充映射，工程师只需确认
- 未命中 → 手工映射，完成后"另存为新模板"

**必填字段**（红星）：`external_id` / `or_id` / `req_id` / `sw_req_desc`
**强推荐**：`source_doc` / `category` / `asil`

### A4. 分组行识别

默认规则 **`only_col1`**（根据你的决定）：
```
分组行判定 = (col 1 非空) ∧ (col 2..N 全空) ∧ (col 1 不含 "PREDEV_") ∧ (col 1 不在 sources 文件名列表)
→ 缓存 current_requirement_module = col 1 值
→ 后面主需求行入库时自动继承
```

### A5. 合并单元格展开 + 覆盖行 + 子需求继承

**行类型识别**：

```python
for row in rows[header_row+1:]:
    if is_fully_empty(row):
        continue

    if is_group_row(row):       # A4 规则
        current_module = row[0]
        continue

    if row[OR] == "NA" and row[ReqID] == "NA" and row[Content]:
        # 【覆盖说明行】
        covered_by = extract_predev_id(row[Content])  # 正则抓 PREDEV_\w+
        insert_requirement(
            external_id=row[NO.],
            source_doc=row[Input],
            source_section=row[Chapter],
            content=row[Content],
            source_type="engineer_processed",
            review_status="note",
            coverage_of=covered_by,
            requirement_module=current_module,
        )
        continue

    if row[OR] and row[ReqID] matches "PREDEV_\d+-R\d+":
        # 【主需求行 或 子需求行】
        # 合并单元格由 openpyxl 读 → 子行的 col 1-6 已自动填充
        insert_requirement(
            external_id=row[NO.],
            source_doc=row[Input],
            ...
            or_id=row[OR],
            req_id=row[ReqID],
            sw_req_desc=row[SRFD],
            requirement_module=current_module,
            source_type="engineer_processed",
            review_status="accepted",
        )
        continue

    # 【异常行】
    insert_requirement(..., review_status="pending")
```

### A6. 预览 + 确认
- 展示前 20 条解析结果
- 统计 "识别到 N 条主需求 + M 条覆盖说明 + K 条异常"
- 冲突统计："新增 X / 更新 Y / 跳过 Z / 待确认 W"
- 用户点确认后入库

---

## 5. API 路由（R1）

所有路由加到 `aspice_routes.py` 的 SWE.1 段（171-460 行区间内），不侵入 SWE.2/3 段。

```
POST /aspice/projects/{id}/swe1/sources/upload
  multipart (file, source_type: customer_raw|engineer_processed)
  → 保存到 runtime/creator_projects/<id>/swe1_sources/<uuid>_<name>
  → 追加 swe1.sources[]，返回 SourceFile

GET /aspice/projects/{id}/swe1/sources
  → 返回 swe1.sources

DELETE /aspice/projects/{id}/swe1/sources/{source_id}
  → 删除文件和记录

POST /aspice/projects/{id}/swe1/ingest-preview
  body: {source_id, sheet_name?, mapping_template_id?}
  → 不入库，仅解析预览
  → 返回 {
      headers: [{col, english, chinese}],
      sample_rows: [[...], ...20],
      detected_groups: ["帧同步", "接口调用", ...],
      suggested_mapping: {...},
      template_match: {id, confidence} | null,
      stats: {main: N, sub: M, coverage: K, anomaly: P}
    }

POST /aspice/projects/{id}/swe1/ingest-confirm
  body: {
    source_id,
    sheet_name,
    column_mapping: {...},
    group_detection_rule: "only_col1",
    coverage_detection: {...},
    conflict_strategy: "smart_update" | "skip" | "overwrite",
    save_as_template: {name, id} | null
  }
  → 实际入库，更新 swe1.requirements 和 swe1.sources[].ingested_count
  → 返回 {new: X, updated: Y, skipped: Z, pending: W, notes: V}

GET /aspice/mapping-templates
  → 列全部模板（跨项目）

POST /aspice/mapping-templates
  → 存新模板

DELETE /aspice/mapping-templates/{template_id}
  → 删模板
```

---

## 6. UI 布局（R1 + 扩展）

```
┌──────────────────────────────────────────────────────────┐
│ SWE.1 软件需求分析                                        │
│                                                          │
│ [项目代号输入 + ID 示例]                                  │
├──────────────────────────────────────────────────────────┤
│ [Collapse 📁] 需求源管理 (可折叠，有源时自动展开)         │
│   ├─ 已上传文件列表                                        │
│   └─ [+ 上传客户原始文档]  [+ 上传工程师已处理表→回灌]    │
├──────────────────────────────────────────────────────────┤
│ [Collapse 🤖] AI 候选（R2 实现，默认折叠）                │
│   列: 置信度 | 外部ID | 原文 | 推荐分类 | 引用历史        │
│   [全选高置信] [全不选] [收录选中] [驳回选中]            │
├──────────────────────────────────────────────────────────┤
│ [主区域 📋] 需求项台账                                    │
│   筛选: [全部|accepted|pending|rejected|note]            │
│   列: 外部ID | ReqID | 分组 | 中文描述 | 原文              │
│        | 分类 | ASIL | 来源 | 状态 | 操作                  │
│   [+ 手动添加] [校验] [导出 SRS + xlsx]                  │
│   note 行：淡灰背景 + "📎 已覆盖" 标签 + hover 说明        │
│   pending 行：橘色左边框 + "⚠ 待确认变更" + 查看 diff     │
├──────────────────────────────────────────────────────────┤
│ [Tabs] 硬件拓扑 | KPI 非功能需求（保留现状）              │
└──────────────────────────────────────────────────────────┘
```

**R3 实现后，顶部再加一个 Tab/按钮：[📚 样本库管理]**（弹 Modal 或独立页）

---

## 7. 分阶段 PR 规划

| 阶段 | 内容 | 预估 | 独立交付价值 |
|---|---|---|---|
| **R1** | Schema 新字段 + 需求源管理 + 回灌向导 A1-A6 + 列映射模板 + 需求项台账 UI（状态筛选 + 覆盖行展示）+ 冲突智能更新 | 3-4 天 | ★★★★★ 立即支撑 80% 日常使用 |
| **R2** | AI 候选面板 + 置信度算法 + 收录/驳回 → 样本自动落盘（为 R3 铺路） | 2 天 | ★★★ 服务 20% 场景 |
| **R3** | BM25 检索器 + prompt 注入 + Tab 5 样本库管理 + 冷启动脚本（扫 project.json + 技术名词 tags） | 2-3 天 | ★★ 跨项目学习 |
| **R4** | SRS 导出含 external_id 溯源列 + traceability 表（OR→SWE.1→SWE.2）+ req_id 向 SWE.2 页面提供 | 1 天 | ★★★ 等 SWE.2 稳定后做 |

---

## 8. 置信度算法（R2）

**公式**：`confidence = 0.6 × RAG_similarity + 0.3 × rule_score + 0.1 × AI_self_assessed`

- **RAG_similarity**：top-1 相似样本的 BM25 得分归一化到 0-1
- **rule_score**：
  - 命中技术名词词典 ≥ 2 个 → +0.5
  - 命中 "camera / sensor / 驱动 / I2C / MIPI / 曝光" 关键词 → +0.3
  - 命中 "deliverable / milestone / Q1-Q4 / 交付 / 项目管理" → -0.5
  - 文本长度 < 10 字 → -0.3
- **AI_self_assessed**：prompt 明确要求 AI 对每条输出自评 0-1

**分档**：
- `confidence > 0.75` → 🟢 高置信，默认勾选
- `0.45 ~ 0.75` → 🟡 待确认，默认不勾
- `< 0.45` → 🔴 低置信，默认不勾 + 置顶提醒

---

## 9. 不冲突保证

**与 SWE.2/3（另一个会话）的边界**：

- **只改**：
  - `backend/app/core/req_generator.py`（重构解析逻辑）
  - `backend/app/api/aspice_routes.py` 的 **171-460 行 SWE.1 段**
  - `backend/app/schemas/aspice/__init__.py` 或新建 `swe1_schema.py`（**不碰** `swe2_schema.py` / `swe3_schema.py`）
  - `frontend/src/components/aspice/Swe1Step.tsx`
  - `frontend/src/types/aspice.ts` 的 `Requirement` 接口（只加字段不删）
- **新建**：
  - `backend/app/core/swe1_ingest.py`（回灌解析引擎）
  - `backend/app/core/requirement_sample_store.py`（R3 样本库）
  - `backend/app/core/mapping_template_store.py`（模板管理）
  - `frontend/src/components/aspice/swe1/`（新目录放子组件）
    - `RequirementSources.tsx`
    - `IngestWizard.tsx`
    - `ConflictReviewModal.tsx`
    - `CandidatePanel.tsx`（R2）
    - `SampleLibraryModal.tsx`（R3）

- **约定**：
  - `aspice_routes.py` 新增 SWE.1 路由一律**追加到 460 行之前**（SWE.2 段之上）
  - 不改 `SaveAspiceRequest` 的顶层字段结构，只扩 `swe1` 的内部 schema
  - 共享的 `_extract_file_text` 等 helper 不改签名，只加新 helper

---

## 10. 冷启动（R3 一次性）

**3 条数据来源**（已与用户确认）：

1. **扫描 `runtime/creator_projects/*/project.json`**（自动）
   - 遍历 `swe1.requirements`，每条生成 `action=accepted` 样本
   - 脚本：`backend/scripts/bootstrap_samples_from_projects.py`

2. **外部需求表导入**（半自动）
   - 用户后续提供需求表路径
   - 复用 R1 的 `swe1_ingest.py` 的解析逻辑 → 转成样本
   - 脚本：`backend/scripts/bootstrap_samples_from_xlsx.py`

3. **工程师手工标注 20-30 条金标准**
   - Tab 5 样本库 UI 里加"新建样本"按钮
   - 存到 `aspice_samples/golden/`（和 `samples.jsonl` 分开，永不删）

---

## 11. 待定 / R1 之后再决定

- **置信度算法的具体权重**：R2 阶段跑一个项目实测后调参
- **外部需求表导入脚本**：等用户提供需求表路径后实现
- **样本库的敏感性标记**：当前假设全局共享；若后续有客户隔离需求再引入 `visibility` 字段
- **分组 → SWE.2 组件的建议字典**：目前不做；若 R4 实际跑完后发现工程师在 SWE.2 侧选组件效率低，再考虑加

---

## 12. 相关文档

- [Pangu_ASPICE ID编号规则V1.0.docx](../../../../../home/tstj/下载/Pangu_ASPICE%20ID编号规则V1.0.docx) — ID 命名规则源文档
- [PreDev_Detailed Software Requirements Table需求详细表.xlsx](../../../../../home/tstj/下载/PreDev_Detailed%20Software%20Requirements%20Table需求详细表.xlsx) — 真实 PreDev 23 列需求表（回灌向导对标）
- [swe2_refactor_plan.md](swe2_refactor_plan.md) — 另一个会话正在做的 SWE.2 重构
- [push_H_plan.md](push_H_plan.md) / [push_G_plan.md](push_G_plan.md) — SWE.3 相关
