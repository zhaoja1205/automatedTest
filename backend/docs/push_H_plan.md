# 推送 H — SWE.3 详细设计文档重写（基于用户精简骨架）

## 背景

- 用户把 `backend/app/templates/aspice/swe3_detail.docx` 从**原 51MB 带 179 张历史样例图**整版手工精简为 **1.4MB 纯骨架**，章节按四/五/六/七章样板给出了可识别的框架（当前位于 `backend/runtime/creator_projects/663856cf4f19/output/PreDev_详细设计.docx`，用户直接在那里改的，没覆盖回模板目录）
- 骨架**没有任何 `{{ }}` / `{% for %}` 占位** — 不走 docxtpl 填空路径，必须改为"**python-docx 读骨架 → 定位 heading → 在定位点原地插表/插图/追加段落**"的拼装方案
- 用户希望 4/5/6/7 之外的 1/2/3/8/9/10/11 几章仍按模板现状当"定稿"，程序只负责补齐 1~3 章的个别表、以及完整生成 4~11 的 8 个模块详设 + 13.2 边界值
- 所有 PlantUML 图（3.2 功能模块图 / 模块类图 / 单元时序图 / 函数流程图）在本推送中**全部走本地 PlantUML server（10.10.134.116:8080）渲染 PNG 嵌入**，含 1600px 降采样兜底（已在推送 G 后期加过 `_shrink_png_if_huge`）
- 本推送**不改**：前端 UI、创建流程、SWE.1/SWE.2 导出

---

## 范围

### 本推送做

| 项 | 做什么 |
|---|---|
| 模板入库 | 把 1.4MB 的精简骨架覆盖到 `backend/app/templates/aspice/swe3_detail.docx`，老版做 `.bak-YYYYMMDD` 备份 |
| 模板解析器 | 新文件 `app/core/arch_skeleton_scanner.py` — 读骨架并**索引所有 heading** 位置，供插入操作定位 |
| 新渲染器 | 新文件 `app/core/arch_generator_swe3_v3.py` — 完整的拼装生成器，取代 `export_swe3_docx_v2` |
| 1.3 参考文档表 | 读 `project.meta.docs` 填充 NO/名称/版本/说明 |
| 2 术语定义追加 | 现有 4 行基础 + `swe3.overview.terms` 项目追加行 |
| 3.2 功能模块图 | 用规则预置的 PlantUML 架构图（8 模块 + 彩色分区）渲 PNG 插入 |
| 3.2 映射表 | 遍历 swe1 × swe2 × swe3 构造 6 列映射行 |
| 4~11 各模块详设 | 按统一骨架为 8 个模块生成完整内容：类图/类列表/每类子节/函数列表/函数详情表/原始NV/单元时序图 |
| 函数详情表 | 统一 B 格式（中文表头 + 返回值行 + 函数流程图行），参数动态扩行 |
| 13.2 边界值 | 遍历所有模块的 focus_functions，聚合为一表 |
| 章节号自动纠正 | 修 heading 层级（5.2.1.1→5.3.3.1 之类）与 13.x 遗留编号 |

### 本推送不做

| 项 | 推迟原因 |
|---|---|
| 前端 UI 调整 | SWE.3 页面当前已能跑，表单充足，等推送 I 做章节树 |
| AI 推导类描述 / 函数介绍润色 | 推送 G 的 `swe3_ai.py` 保持现状，由 SWE.3 的"派生" 阶段按 kb 缓存走原路径 |
| 回灌 docx 为数据 | 单向导出，回灌是单独迭代 |
| SWE.1 / SWE.2 导出改动 | 本推送只碰 SWE.3 |

---

## 关键设计

### 1. 模板定位策略

骨架 docx 的 `document.xml` 里**每个 heading 都是独立的 `<w:p>` 带 `w:pStyle` 指向 `Heading1/2/3/4/5`**。
- 扫描时**顺序遍历 body 子元素**，建索引 `{(level, title): element}` 且记录**每个 heading 在 body 中的 index**
- 插入点 = `(heading_index + 1)` → 把新段落/表 `body.insert(idx, new_element)` 推进去，之后 heading index 维护一张**偏移表**
- 对 "模板尾部的`模板历史记录`表" / "保留但要动态增补内容的空表（如 4.2 类列表）" 用**表标题 + 列头签名**双重匹配，避免误伤

### 2. 表格复制与扩行

模板里 4/5/6/7 都给了样板表（如表 13 的 10 行 × 3 列），模板里**一张样板** = **一个 `<w:tbl>` 元素**。生成策略：
- **表头 + 格式**：从模板样板表克隆（保留 `w:tblPr` / `w:tblGrid` / 列宽设置），只替换行内容
- **动态扩行**：拷贝样板表的一行作为模板行（保留 `w:trPr` + cell 的 `w:tcPr` + 字体），按实际数据数 `deepcopy` + 文本替换，追加到表中
- **样板表删除**：模板里除"样板表"之外的空表（例 4.2 类列表预留的 3 行空行）扫到后整体删，由代码重新生成

### 3. 函数详情表统一 B 格式

模板样板分两种（A: 10 行英文表头 / B: 8 行中文表头），统一按 B 格式生成：
```
行 1 (2 列合并): [函数声明] | <declaration>
行 2 (2 列合并): [函数介绍] | <intro>
行 3 (3 列):    Parameter | Type | 说明
行 4~X:         <参数名> | <类型> | <说明>       ← N 个参数 N 行
                (0 参数时写 1 行 "void" | - | -)
行 X+1 (3 列): 返回值 | Type | 说明
行 X+2:         <返回类型> | <类型> | <返回说明>  (void 也写)
行 X+3 (3 列合并): 函数流程图
行 X+4 (3 列合并): <PlantUML 流程图 PNG>         (空则一行文字 "无流程图")
```

### 4. 设计 ID 生成规则

```python
# 类
f"D{mod_idx:03d}-{mod_short_name}-class-{cls_idx:03d}"
# 函数
f"D{mod_idx:03d}-{host_short_name}-function-{fn_idx:03d}"
```
其中 `host_short_name` 优先取**类名或设备型号**（如 Serializer 下的 `MAX96717`、EEPROM 下的 `m24c04`），没有则 fallback 到 `mod_short_name`。
`mod_short_name` 由规则预置映射：
```python
MODULE_SHORT = {
    "A001": "Serializer", "A002": "Deserializer", "A003": "EEPROM",
    "A004": "CameraModule", "A005": "CameraSecurity", "A006": "nvsipl_camera",
    "A007": "nvsipl_multicast", "A008": "PMIC",
}
```

### 5. PlantUML 渲染路径

统一走 `template_engine.fetch_plantuml_png`（已配置 `PLANTUML_BACKEND=local`），在插入 docx 前走 `_shrink_png_if_huge` 降采样到 ≤1600px。
- 函数流程图 PlantUML 来源：`fn.get("flowchart_plantuml")` 优先（用户填 / AI retry 生成），fallback 走 `cpp_flow_to_plantuml.build_plantuml_from_body(fn["body_text"])`
- 类图 / 单元时序图：`module.class_diagram_plantuml` / `module.sequence_plantuml`，空则该节保留 heading + 一行"（本模块暂无 X 图）"
- 3.2 功能模块图：规则预置的 PlantUML（8 模块 + SIPL 框架彩色），单次生成，缓存到 `arch_sections.py::DEFAULT_MODULE_DIAGRAM_PLANTUML`

---

## 新/改文件清单

### 新文件

**`backend/app/core/arch_skeleton_scanner.py`** （约 200 行）
- 读骨架 docx，构建索引：
  - `headings: list[(level, title, body_index)]`
  - `tables_by_signature: dict[sig, (index, template_table_xml)]`，sig = `(前文 heading 标题, 列头元组)`
- 对外接口：
  - `insert_after_heading(doc, heading_title, new_element)`
  - `append_rows_to_table(table, rows: list[list[str]])`
  - `clone_sample_table_with_rows(sample_table, rows, headers=None)`
  - `delete_table_at(doc, table_index)`

**`backend/app/core/arch_generator_swe3_v3.py`** （约 1200 行，分段清晰）
- 入口：`export_swe3(project, out_dir) -> dict` （返回 `{docx, xlsx}`）
- 主流程：
  1. 加载骨架 → `scanner = SkeletonScanner(template_path)`
  2. **1 章补齐**：`_fill_chapter_1_overview(doc, scanner, project)`
  3. **2 章追加**：`_append_terms(doc, scanner, project)`
  4. **3 章填 + 图**：`_fill_chapter_3_functional_overview(doc, scanner, project)`
  5. **4-11 模块循环**：
     ```python
     for i, mid in enumerate(MODULE_ORDER, start=4):
         module = project["aspice"]["swe3"]["modules"].get(mid, {})
         _render_module_chapter(doc, scanner, module, chapter_no=i)
     ```
  6. **12 章不动**（性能）
  7. **13.2 边界值填**：`_fill_boundary_table(doc, scanner, all_focus_fns)`
  8. **14/15 章不动**
  9. 保存 docx + 生成 xlsx

**`backend/docs/push_H_plan.md`** （本文件）

### 改动文件

**`backend/app/core/arch_sections.py`** （+100 行）
- 新增 `MODULE_SHORT` / `MODULE_FUNCTION_DESC` 映射
- 新增 `DEFAULT_MODULE_DIAGRAM_PLANTUML`（3.2 功能模块图源码）
- 新增 `build_design_id(mod_idx, mod_name, cat, idx, host=None)` 辅助

**`backend/app/api/aspice_routes.py`** （+5 行）
- `export_swe3` 路由把 `ASPICE_TEMPLATE_ENGINE` 新增 "v3" 分支，默认走 v3；v2 保留做回滚
- v2 保留的目的：模板从带占位 docx 版本切 v3 骨架版本是单向，若 v3 出锅可以 env 切回 v2 + 换回老模板

**`backend/app/templates/aspice/swe3_detail.docx`** （整体替换）
- 备份老版到 `swe3_detail.docx.bak-20261109`
- 把用户的精简骨架覆盖过来

---

## 分阶段实施

| 阶段 | 做什么 | 验收 |
|---|---|---|
| H1 | 模板入库 + 骨架 scanner | `python -c "from app.core.arch_skeleton_scanner import SkeletonScanner; s = SkeletonScanner(...); print(len(s.headings))"` 打印 >50 个 heading |
| H2 | 1/2/3 章补齐（含 3.2 功能模块图） | 导出 docx，前 15 页完整 |
| H3 | 单个模块 (Serializer) 完整生成 | 第 4 章完整，含类图/类列表/类子节/函数列表/函数详情表/原始NV/时序图 |
| H4 | 8 模块循环铺开 + 13.2 边界值 | docx 4~13 全部生成 |
| H5 | 回归验证 + 端到端 | 前端点"导出" → 成功下载，docx < 15MB，Word 打开结构完整 |

---

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| 骨架 heading 层级错位（5.2.1.1 本该 5.3.3.1） | 不依赖骨架 heading 的数字编号，用 `title + style` 匹配定位 |
| 样板表的列宽/字体样式丢失 | 克隆整张样板表而不是手工建表，再按行替换文本 |
| PlantUML 渲染超时拖慢导出 | 复用推送 G 的 `_safe_build_plantuml` watchdog，单图 3s 预算；总导出预算 180s |
| 图太多导致 docx 又膨胀 | `_shrink_png_if_huge` 已生效（≤1600px + optimize），单图 ≤500KB |
| 用户后续再改骨架 | scanner 用 title + style 匹配，对加/减/改章节有容忍度；加新 heading 无影响，改 heading 文字只需更新 scanner 的查找键 |

---

## 验证清单

- [ ] `python -m py_compile` 四个改动文件
- [ ] `from app.main import app` 不报错
- [ ] 单元测试 `arch_skeleton_scanner.py`（mock 一个简单 docx 骨架）
- [ ] `POST /api/aspice/projects/663856cf4f19/swe3/export` 返回 200
- [ ] 导出 docx < 15MB
- [ ] Word 打开无布局错乱，章节号 1~15 连续
- [ ] 第 3.2 功能模块图可见、第 4~11 章 8 个模块齐全、13.2 边界值表有行
