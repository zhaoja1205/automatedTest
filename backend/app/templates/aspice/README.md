# ASPICE Docx 模板约定

本目录放 ASPICE SWE.1/2/3 的 docx 模板。模板引擎 `app/core/template_engine.py` 基于
[docxtpl](https://docxtpl.readthedocs.io/)（Jinja2 语法扩展）。

## 文件命名

- `swe2_arch_sample.docx` —— 原始参考样本（**只读**，不改造）
- `swe2_arch_poc.docx`    —— 推送 E PoC 验证用（最小化改造）
- `swe2_arch.docx`        —— 生产模板（E.2 完整改造，上线后由此文件产出）
- `swe3_detail_sample.docx` / `swe3_detail.docx`  —— 同上，SWE.3
- `swe1_srs_sample.docx` / `swe1_srs.docx`        —— 同上，SWE.1（推送 G）

## Jinja 占位语法速查

| 场景                  | 语法 | 示例 |
|-----------------------|------|------|
| 标量替换              | `{{ var }}` | `版本号：{{ project.version }}` |
| 段落级 if             | `{%p if cond %}...{%p endif %}` | 场景段隐显 |
| 段落级 for            | `{%p for item in items %}...{%p endfor %}` | 组件循环 |
| 表格行 for（最常用）  | 见下方 3 行结构 | 历史表、术语表、接口表等 |
| InlineImage           | `{{ image_key }}` | PlantUML 图嵌入 |

## 表格行循环（关键，推送 E 踩过的坑）

**docxtpl 的 `{%tr for %}` 要求 for 和 endfor 在表格的两行**，不能挤在同一行。
正确结构是 **3 行**：

| 行号 | 内容 | 说明 |
|---|---|---|
| r0  | 表头                              | 保留，不被循环 |
| r1  | `{%tr for item in items %}`       | 开标签行，首列 cell 里写这一个表达式 |
| r2  | `{{ item.a }}` \| `{{ item.b }}` \| … | 数据行（会被重复） |
| r3  | `{%tr endfor %}`                  | 闭标签行，首列 cell |

**不要** 把 `{%tr for %}` 和 `{{ item.x }}` 塞在数据行的同一个 cell 的两个 paragraph —— jinja 会报 "unknown tag endfor"。

对应 Python 构造模板的工具函数（python-docx）：

```python
def rebuild_loop_table(tbl, loop_var, iter_expr, data_exprs):
    # 删数据行，保留表头
    for row in list(tbl.rows[1:]):
        row._element.getparent().remove(row._element)
    tbl.add_row().cells[0].text = '{%%tr for %s in %s %%}' % (loop_var, iter_expr)
    row = tbl.add_row()
    for i, e in enumerate(data_exprs):
        row.cells[i].text = e
    tbl.add_row().cells[0].text = '{%tr endfor %}'
```

## 变量命名规则

- 所有占位引用的变量**必须**来自 `app/schemas/aspice/*.py` 的 Pydantic schema
- 字段名小蛇形（`project.history`, `overview.terms`）
- 列表字段必复数（`terms`, `components`, `mappings`）
- 嵌套深度不超 3 层（可读性 + jinja 性能）

## 图片嵌入

模板里用 `{{ some_image_key }}`，后端代码：

```python
r = TemplateRenderer("swe2_arch")
r.add_plantuml_image("comp_a001_seq", plant_source=plantuml_source)
# 或已有 PNG：
r.add_png_bytes("flowchart_fn_abc", png=png_bytes)
buf = r.render(ctx.model_dump())
```

`add_plantuml_image` 内部走 `fetch_plantuml_png` → 调配好的本地/云 PlantUML 服务（10.10.134.116:8080 或 plantuml.com）。

## 编号域/目录域

- Word 的 "1 / 1.1 / 1.1.1" 自动编号依赖段落的 numId —— **保留原段落样式**，
  不要手工拼 "4.1" 字符串
- 目录（TOC）在 Word 里是 field，docxtpl 不会渲染它。生成后在 Word 里 `右键 → 更新域`
  或在导出代码里加一行提示段

## 如何验证

```bash
cd backend
venv/bin/python -c "
from app.core.template_engine import TemplateRenderer, extract_template_variables
print('vars:', sorted(extract_template_variables('swe2_arch_poc')))
r = TemplateRenderer('swe2_arch_poc')
buf = r.render({...})
open('/tmp/out.docx', 'wb').write(buf.getvalue())
"
```
