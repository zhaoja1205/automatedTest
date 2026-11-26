# 测试执行管理系统 (Test Runner Web)

基于原 `demo_testcamera` 工程转换的 Web 版测试执行管理系统。当前版本：**v4.0.0**

## 技术栈

- **后端**: Python 3.10+ / FastAPI / WebSocket / Paramiko / openpyxl
- **前端**: React 18 / TypeScript / Vite / Ant Design / Zustand

## 项目结构

```
test_runner_web/
├── backend/
│   ├── app/
│   │   ├── main.py                   # FastAPI 入口 + session 中间件
│   │   ├── api/
│   │   │   ├── routes.py             # 执行管理 REST API
│   │   │   ├── casegen_routes.py     # 生成测试用例 API（平台配置解析）
│   │   │   ├── aspice_routes.py      # ASPICE 文档生成 REST API
│   │   │   ├── classdiag_routes.py   # 类图分析 REST API
│   │   │   ├── seqdiag_routes.py     # 函数时序图 REST API
│   │   │   └── plantuml_routes.py    # PlantUML 代理 API
│   │   ├── core/
│   │   │   ├── test_case.py          # 用例数据模型
│   │   │   ├── ssh_manager.py        # SSH 连接管理（直连/跳板机/sshpass 回退）
│   │   │   ├── executor_adapter.py   # 执行器适配（PTY 交互/故障测试/AI 判定）
│   │   │   ├── excel_handler.py      # Excel 读写
│   │   │   ├── expected_parser.py    # 预期结果解析（关键字/fps/file_check）
│   │   │   ├── session_store.py      # 多会话 session 注册表
│   │   │   ├── config_store.py       # 配置持久化（JSON）
│   │   │   ├── creator_store.py      # 用例创建项目存储
│   │   │   ├── classdiag_store.py    # 类图项目存储（runtime/classdiag_projects/）
│   │   │   ├── seqdiag_store.py      # 时序图项目存储（runtime/seqdiag_projects/）
│   │   │   ├── cpp_class_parser.py   # C++ 类结构解析器
│   │   │   ├── cpp_seq_parser.py     # C++ 函数/调用链解析器
│   │   │   ├── seq_uml_emit.py       # PlantUML 时序图生成器
│   │   │   ├── zip_utils.py          # 安全 zip 解压工具
│   │   │   ├── arch_generator.py     # SWE.2 架构文档生成器（docx 渲染上下文构建）
│   │   │   ├── arch_sections.py      # SWE.2 规则预置层（术语/假设/集成原则/组件模板）
│   │   │   ├── aspice_adapter.py     # ASPICE ↔ skill project.json 适配器
│   │   │   ├── aspice_validate.py    # SWE.1 校验引擎（V01-V19 规则）
│   │   │   ├── template_engine.py    # docxtpl 模板引擎（PlantUML 嵌入/图片降采样）
│   │   │   ├── swe1_ingest.py        # SWE.1 需求回灌解析器（Excel/Word → ParsedRow）
│   │   │   └── mapping_template_store.py  # SWE.1 列映射模板跨项目存盘
│   │   ├── schemas/aspice/           # ASPICE Pydantic 模型（单一来源）
│   │   │   ├── swe1_schema.py        # SWE.1 需求/源文件/列映射/回灌 API 模型
│   │   │   ├── swe2_schema.py        # SWE.2 架构文档渲染上下文模型
│   │   │   └── swe3_schema.py        # SWE.3 详细设计数据模型
│   │   ├── templates/aspice/         # docx 模板文件
│   │   │   ├── swe2_arch.docx        # SWE.2 架构&概要设计书模板
│   │   │   └── swe3_detail.docx      # SWE.3 详细设计书模板
│   │   ├── ai/                       # AI 能力层（判定/分析/报告/步骤解析/函数简介）
│   │   │   ├── service.py
│   │   │   ├── providers/            # anthropic / openai / ollama（按协议区分）
│   │   │   ├── prompts/              # judge / analyze / report / parse_steps / func_brief / swe3_augment
│   │   │   └── cache.py
│   │   └── websocket/
│   │       └── session_ws_manager.py  # per-session WebSocket 管理器
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx                   # 路由
│   │   ├── api/                      # axios.ts + 各业务 API 封装
│   │   │   ├── aspiceApi.ts          # ASPICE 文档 API
│   │   │   ├── classDiagApi.ts       # 类图分析 API
│   │   │   └── seqDiagApi.ts         # 时序图 API
│   │   ├── components/
│   │   │   ├── Layout.tsx            # 顶部 Tab + 左侧 Sider 导航布局
│   │   │   ├── aspice/               # ASPICE 文档向导组件
│   │   │   │   ├── Swe1Step.tsx      # SWE.1 需求分析（源管理/回灌/台账）
│   │   │   │   ├── Swe2Step.tsx      # SWE.2 架构设计（9 组件/文档元信息/集成原则）
│   │   │   │   ├── Swe3Step.tsx      # SWE.3 详细设计（工程扫描/函数详情/模块组合）
│   │   │   │   ├── swe1/             # SWE.1 子组件（SourcesPanel/IngestWizard/RequirementsTable/TemplatesPanel）
│   │   │   │   ├── swe2/             # SWE.2 子组件（OverviewEditor/ModuleEditor/SoftwareDesignEditor 等 8 组件）
│   │   │   │   └── swe3/             # SWE.3 子组件（EngineeringScanner/FunctionDetailEditor/ModuleCompositionEditor 等 12 组件）
│   │   │   ├── casegen/              # 生成测试用例向导组件
│   │   │   ├── classdiag/            # 类图分析组件
│   │   │   ├── seqdiag/              # 时序图组件
│   │   │   └── flowchart/            # 流程图组件
│   │   ├── hooks/useWebSocket.ts
│   │   ├── pages/                    # Dashboard / Reports / History / 代码分析等
│   │   ├── stores/                   # useStore.ts + useAspiceStore.ts
│   │   └── types/                    # index.ts + aspice.ts + casegen.ts + classDiag.ts + seqDiag.ts
│   ├── package.json
│   └── vite.config.ts
├── docs/                             # 架构/图示/版本路线/使用说明
├── start.sh                          # 一键启动脚本（含依赖检测）
├── stop.sh
└── VERSION                           # 当前版本号
```

## 快速启动

```bash
cd test_runner_web
chmod +x start.sh
./start.sh
```

或分别启动：

```bash
# 后端
cd backend
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 前端
cd frontend
npm install
npm run dev
```

访问 http://localhost:3000

---

## 功能模块

### 测试执行管理

1. **上传用例**: 上传 Excel 测试用例文件，上传后自动触发 AI 步骤智能解析
2. **配置管理**: SSH 连接配置（直连/跳板机，支持 sshpass 双密码回退）、工作区配置
3. **执行测试**: 通过 SSH 在目标设备上执行测试，支持 PTY 交互式命令和故障测试交错执行
4. **实时日志**: WebSocket 推送执行日志，每个标签页 session 隔离互不干扰
5. **人工确认**: 需要人工判断的步骤弹窗确认
6. **AI 判定**: 规则引擎 + AI 语义判定（始终/不确定时/关闭三种模式）；AI 返回明确判定时**优先采用 AI 结果**，AI 不可用时回退规则引擎
7. **结果下载**: 下载测试结果 Excel + AI 报告
8. **历史记录**: 执行历史 + 报告管理 + 对比分析（支持批量选中/批量删除）

### 代码分析（「代码分析」统一 Tab）

三个子功能通过左侧 Sider 菜单切换，进入时默认落地到「类图分析」项目列表：

#### 类图分析（`/classdiag`）

- **项目管理**: 新建/删除 C++ 代码分析项目，每个项目持久化到 `runtime/classdiag_projects/<id>/`
- **源码上传**: 上传主源码 zip + 追加 include zip（安全解压，zip bomb 检测）
- **类图生成**: 输入类名（支持全限定名），后端扫描 `.h/.cpp` 提取类成员与继承关系，生成 PlantUML 类图 SVG
- **两阶段增强**: 可选 clang 增强模式，提升解析精度

#### 函数时序图（`/seqdiag`）

- **项目管理**: 新建/删除时序图项目，每个项目持久化到 `runtime/seqdiag_projects/<id>/`
- **源码上传**: 上传主源码 zip + 追加 include zip
- **时序图生成**: 输入函数全限定名（`ClassName::methodName`），后端扫描定位函数体、提取变量类型与调用链，生成 PlantUML 时序图 SVG
- **双函数展开**: 可选填函数 B，生成函数 A 调用函数 B 时展开 B 内部调用的详细交互图
- **多匹配处理**: 同名函数多处定义时返回 409 + 候选列表，点选后自动填回输入框重新提交

#### 函数流程图（`/flowchart`）

- 输入 C++ 函数代码，可视化生成函数控制流程图

### ASPICE 文档生成（v4.0.0 新增）

通过「ASPICE 文档」Tab 进入，包含 SWE.1/SWE.2/SWE.3 三个子步骤：

#### SWE.1 需求分析（`/aspice` → SWE.1）

- **需求源管理**: 上传 Excel/Word 需求源文件，支持多源管理
- **需求回灌向导**: 通过列映射模板将源文件中的需求回灌到系统台账（A2-A6 步骤）
- **需求台账**: 统一展示、编辑、校验所有回灌需求（V01-V19 规则校验）
- **列映射模板**: 跨项目复用列映射配置，避免重复配置

#### SWE.2 架构&概要设计（`/aspice` → SWE.2）

- **文档元信息**: 标题、编号、版本、修订历史、参考资料
- **组件编辑**: 9 大组件类型（接口/类/场景/安全模式），支持扫描工程接口自动填充
- **软件设计**: §3 软件设计编辑（架构视图、接口定义、行为描述）
- **资源消耗**: §5 资源消耗编辑（内存/CPU/存储估算）
- **系统集成**: §7 系统集成编辑（集成策略/顺序/验证方法）
- **AI 函数简介补全**: 对组件接口函数自动生成简要描述
- **PlantUML 代理**: 内置 PlantUML 渲染代理，支持前端实时预览架构图
- **docx 导出**: 基于 `swe2_arch.docx` 模板渲染生成标准架构设计书

#### SWE.3 详细设计（`/aspice` → SWE.3）

- **工程扫描**: 上传工程源码，自动扫描模块/函数/类型定义
- **聚焦函数**: 选择需要详细设计的核心函数
- **函数详情编辑**: 逐函数编辑输入/输出/算法/复杂度/安全属性
- **模块组合编辑**: 定义模块间依赖与集成关系
- **AI 增强**: 可选 AI 辅助补全函数描述与算法细节
- **docx 导出**: 基于 `swe3_detail.docx` 模板渲染生成详细设计书

---

## AI 配置

AI 功能通过侧边导航的「AI 配置」页面统一管理：

| 配置项 | 默认值 | 说明 |
|---|---|---|
| AI 协议 | anthropic | anthropic / openai / ollama |
| API Key | — | Anthropic、OpenAI 兼容协议需要；Ollama 不需要 |
| 模型 | ts-pri-auto | 默认中智网关自动路由 |
| 接入地址 | llm.thundersoft.com | 与协议、模型共同决定实际供应商；留空用协议默认地址 |
| AI 判定模式 | always | off / uncertain / always（AI 有结果时优先采用） |
| AI 自动解析步骤 | 开 | 上传 Excel 后自动触发 |
| AI 自动分析失败 | 关 | 失败用例自动根因分析 |

---

## 多会话隔离

每个浏览器标签页自动分配独立 session，各自拥有独立的 SSH 连接、用例列表、配置和执行状态。会话 ID 存储在 `localStorage`，通过 `X-Session-ID` HTTP Header 传递给后端。服务端每 5 分钟清理 1 小时无活动的过期 session。

---

## 设计文档

- [架构说明文档](docs/ARCHITECTURE.md)
- [模块关系图与时序图说明](docs/DIAGRAMS.md)
- [版本规划路线图](docs/VERSION_ROADMAP.md)
