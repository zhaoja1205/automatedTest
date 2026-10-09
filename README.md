# 测试执行管理系统 (Test Runner Web)

基于原 `demo_testcamera` 工程转换的 Web 版测试执行管理系统。当前版本：**v3.9.0**

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
│   │   │   ├── creator_routes.py     # 用例创建 REST API（A1→A5 向导）
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
│   │   │   ├── case_generator.py     # 矩阵驱动用例骨架生成器
│   │   │   ├── classdiag_store.py    # 类图项目存储（runtime/classdiag_projects/）
│   │   │   ├── seqdiag_store.py      # 时序图项目存储（runtime/seqdiag_projects/）
│   │   │   ├── cpp_class_parser.py   # C++ 类结构解析器
│   │   │   ├── cpp_seq_parser.py     # C++ 函数/调用链解析器
│   │   │   ├── seq_uml_emit.py       # PlantUML 时序图生成器
│   │   │   └── zip_utils.py          # 安全 zip 解压工具
│   │   ├── ai/                       # AI 能力层（判定/分析/报告/步骤解析）
│   │   │   ├── service.py
│   │   │   ├── providers/            # claude / openai_compat / ollama
│   │   │   ├── prompts/              # judge / analyze / report / parse_steps
│   │   │   └── cache.py
│   │   └── websocket/
│   │       └── session_ws_manager.py  # per-session WebSocket 管理器
│   ├── scripts/gen_cases.py           # cases.json → xlsx 导出
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx                   # 路由
│   │   ├── api/                      # axios.ts + 各业务 API 封装
│   │   ├── components/
│   │   │   ├── Layout.tsx            # 顶部 Tab + 左侧 Sider 导航布局
│   │   │   └── creator/              # 用例创建向导组件（A1→A5）
│   │   ├── hooks/useWebSocket.ts
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx         # 执行管理主页
│   │   │   ├── HistoryPage.tsx       # 执行历史
│   │   │   ├── ReportPage.tsx        # AI 报告
│   │   │   ├── creator/              # 用例创建向导页
│   │   │   ├── classdiag/            # 类图分析（项目列表 + 工作区）
│   │   │   ├── seqdiag/              # 函数时序图（项目列表 + 工作区）
│   │   │   └── flowchart/            # 函数流程图
│   │   ├── stores/                   # useStore.ts + useCreatorStore.ts
│   │   ├── types/                    # index.ts + creator.ts + classDiag.ts + seqDiag.ts
│   │   └── utils/caseRules.ts        # 用例规范校验
│   ├── package.json
│   └── vite.config.ts
├── docs/                             # 架构/图示/版本路线/使用说明
├── start.sh                          # 一键启动脚本
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
6. **AI 判定**: 规则引擎 + AI 语义判定（始终/不确定时/关闭三种模式）
7. **结果下载**: 下载测试结果 Excel + AI 报告
8. **历史记录**: 执行历史 + 报告管理 + 对比分析（支持批量选中/批量删除）

### 测试用例创建（A1→A5 问答向导）

1. **A1 文档元信息**: 标题、文件编号、文档版本、参考资料
2. **A2 被测对象维度**: 程序名、配置名、逐模组帧率、路径、跳板机、故障变体
3. **A3 公共前置条件**: 驱动部署目录、测试工具路径、异常处理
4. **A4 分类与优先级**: 测试类型、设计方法、优先级、ID 编号规则
5. **硬件拓扑表**: Group/Link/模组型号/I2C地址/mask位 → 自动生成覆盖矩阵与 -m mask
6. **按矩阵生成用例**: 规则模板生成可判定用例骨架
7. **规范校验**: 预期结果实时校验是否含可判定观测点
8. **导出**: 生成内部版/客户版 xlsx，可直接上传到执行侧

> 项目特定信息（命令、路径、IP、阈值、帧率）不会自动编造，缺失时保留 `<待补充:xxx>` 占位符。

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

### ASPICE 文档生成

- SWE.1 深度集成：模板 + 脚本驱动，生成标准 ASPICE 测试文档

---

## AI 配置

AI 功能通过侧边导航的「AI 配置」页面统一管理：

| 配置项 | 默认值 | 说明 |
|---|---|---|
| Provider | claude | claude / openai / ollama |
| API Key | — | 对应 Provider 的密钥 |
| 模型 | ts-pri-auto | 默认中智网关自动路由 |
| Base URL | llm.thundersoft.com | 中智网关地址 |
| AI 判定模式 | always | off / uncertain / always |
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
