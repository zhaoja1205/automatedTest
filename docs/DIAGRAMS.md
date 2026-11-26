# 测试执行管理系统模块关系图与时序图说明

本文档聚焦于当前工程的模块关系与核心业务时序，便于做设计评审、开发交接和后续重构。

## 0. 文档定位

| 项目 | 内容 |
|---|---|
| 文档名称 | 模块关系图与时序图说明 |
| 适用工程 | `test_runner_web` |
| 文档用途 | 辅助理解模块依赖、通信边界和关键业务流程 |
| 推荐读者 | 架构评审人、开发、测试、维护人员 |

### 0.1 阅读说明

本文件中的图示分为两类：

- **模块关系图**：回答“系统由哪些部分组成、彼此如何依赖”
- **时序图**：回答“关键业务流程在运行时如何协作”

建议与 `docs/ARCHITECTURE.md` 配合阅读：

- 架构文档负责解释“为什么这样设计”
- 图示文档负责表达“这些模块如何协作”

## 1. 模块关系图

### 1.0 图示边界说明

本节图示采用“逻辑组件视图”，重点表达职责与依赖方向，不严格等同于进程级部署图或 C4 完整模型。

阅读时请注意：

- 箭头表示主要调用、依赖或事件流向
- 图中省略了部分通用基础库与框架内部细节
- 图示聚焦主链路，不覆盖所有异常分支

### 1.1 端到端模块关系

```mermaid
graph TD
    User[用户] --> Layout[前端 Layout 导航]
    Layout --> Dashboard[执行管理 Dashboard]
    Layout --> CodeAnalysis[代码分析模块]
    Layout --> Creator[用例创建向导]
    Layout --> ASPICE[ASPICE 文档向导]

    Dashboard --> Store[Zustand Store]
    Dashboard --> Api[Axios API]
    Dashboard --> WsHook[useWebSocket Hook]

    CodeAnalysis --> ClassDiag[类图分析页]
    CodeAnalysis --> SeqDiag[函数时序图页]
    CodeAnalysis --> Flowchart[函数流程图页]

    ASPICE --> Swe1[Swe1Step 需求分析]
    ASPICE --> Swe2[Swe2Step 架构设计]
    ASPICE --> Swe3[Swe3Step 详细设计]

    Api --> Rest[FastAPI REST API]
    WsHook --> WsEndpoint[WebSocket /ws]

    Rest --> SessionStore[SessionStore 多会话注册表]
    Rest --> ExcelHandler[ExcelHandler]
    Rest --> Executor[ExecutorAdapter]
    Rest --> ClassDiagRoutes[classdiag_routes.py]
    Rest --> SeqDiagRoutes[seqdiag_routes.py]
    Rest --> AspiceRoutes[aspice_routes.py]
    Rest --> PlantUmlRoutes[plantuml_routes.py]

    WsEndpoint --> WsManager[SessionWSManager per-session]
    Executor --> WsManager
    Executor --> SSH[SSHManager]

    ClassDiagRoutes --> ClassDiagStore[classdiag_store.py]
    ClassDiagRoutes --> CppClassParser[cpp_class_parser.py]

    SeqDiagRoutes --> SeqDiagStore[seqdiag_store.py]
    SeqDiagRoutes --> CppSeqParser[cpp_seq_parser.py]
    SeqDiagRoutes --> SeqUmlEmit[seq_uml_emit.py]

    AspiceRoutes --> Swe1Ingest[swe1_ingest.py]
    AspiceRoutes --> ArchGenerator[arch_generator.py]
    AspiceRoutes --> AspiceAdapter[aspice_adapter.py]
    AspiceRoutes --> TemplateEngine[template_engine.py]

    SSH --> Target[远端目标设备]
    WsManager --> Dashboard
```

### 1.2 前端内部模块关系

```mermaid
graph LR
    App[App.tsx] --> Layout[Layout.tsx]

    Layout --> Dashboard[Dashboard.tsx]
    Layout --> ClassDiagProjects[classdiag/ProjectsPage]
    Layout --> ClassDiagWorkspace[classdiag/WorkspacePage]
    Layout --> SeqDiagProjects[seqdiag/ProjectsPage]
    Layout --> SeqDiagWorkspace[seqdiag/WorkspacePage]
    Layout --> Flowchart[flowchart/FlowchartPage]
    Layout --> Creator[creator/...]
    Layout --> ASPICE[aspice/ASPICEWizard]

    Dashboard --> Store[useStore.ts]
    Dashboard --> Axios[api/axios.ts]
    Dashboard --> WsHook[hooks/useWebSocket.ts]

    ClassDiagWorkspace --> ClassDiagApi[api/classDiagApi.ts]
    SeqDiagWorkspace --> SeqDiagApi[api/seqDiagApi.ts]
    ASPICE --> AspiceApi[api/aspiceApi.ts]

    ClassDiagApi --> ClassDiagTypes[types/classDiag.ts]
    SeqDiagApi --> SeqDiagTypes[types/seqDiag.ts]
    AspiceApi --> AspiceTypes[types/aspice.ts]

    ASPICE --> Swe1Step[Swe1Step.tsx]
    ASPICE --> Swe2Step[Swe2Step.tsx]
    ASPICE --> Swe3Step[Swe3Step.tsx]

    Swe1Step --> Swe1Sub[swe1/子组件]
    Swe2Step --> Swe2Sub[swe2/子组件]
    Swe3Step --> Swe3Sub[swe3/子组件]

    WsHook --> Store
    Axios --> Store
```

### 1.3 后端内部模块关系

```mermaid
graph LR
    Main[main.py] --> Routes[routes.py]
    Main --> CreatorRoutes[creator_routes.py]
    Main --> ClassDiagRoutes[classdiag_routes.py]
    Main --> SeqDiagRoutes[seqdiag_routes.py]
    Main --> AspiceRoutes[aspice_routes.py]
    Main --> PlantUmlRoutes[plantuml_routes.py]
    Main --> SessionStore[session_store.py]
    Main --> WsManager[websocket/session_ws_manager.py]

    Routes --> TestCase[test_case.py]
    Routes --> Excel[excel_handler.py]
    Routes --> Executor[executor_adapter.py]
    Routes --> SSH[ssh_manager.py]

    ClassDiagRoutes --> ClassDiagStore[classdiag_store.py]
    ClassDiagRoutes --> CppClassParser[cpp_class_parser.py]
    ClassDiagRoutes --> ZipUtils[zip_utils.py]

    SeqDiagRoutes --> SeqDiagStore[seqdiag_store.py]
    SeqDiagRoutes --> CppSeqParser[cpp_seq_parser.py]
    SeqDiagRoutes --> SeqUmlEmit[seq_uml_emit.py]
    SeqDiagRoutes --> ZipUtils

    AspiceRoutes --> Swe1Ingest[swe1_ingest.py]
    AspiceRoutes --> ArchGenerator[arch_generator.py]
    AspiceRoutes --> ArchSections[arch_sections.py]
    AspiceRoutes --> AspiceAdapter[aspice_adapter.py]
    AspiceRoutes --> AspiceValidate[aspice_validate.py]
    AspiceRoutes --> TemplateEngine[template_engine.py]
    AspiceRoutes --> MappingTplStore[mapping_template_store.py]
    AspiceRoutes --> AiService[ai/service.py]

    ArchGenerator --> Swe1Schema[swe1_schema.py]
    ArchGenerator --> Swe2Schema[swe2_schema.py]
    ArchGenerator --> Swe3Schema[swe3_schema.py]

    AiService --> FuncBrief[func_brief.py]
    AiService --> Swe3Augment[swe3_augment.py]

    Executor --> SSH
    Executor --> TestCase
    Executor --> WsManager
    Excel --> TestCase
```

## 2. 时序图说明

### 2.0 时序图使用约定

本节时序图中的参与者分为四类：

- **用户侧**：用户、前端 Dashboard
- **接口侧**：FastAPI 路由、WebSocket 管理器
- **业务侧**：执行器、状态容器、ExcelHandler
- **基础设施侧**：SSHManager、目标设备、文件系统

时序图重点表达：

- 谁发起动作
- 谁负责业务编排
- 谁承担实时反馈
- 最终结果如何沉淀

### 2.1 Excel 上传与解析

```mermaid
sequenceDiagram
    participant U as 用户
    participant FE as Dashboard
    participant API as routes.py
    participant EH as ExcelHandler
    participant S as app_state

    U->>FE: 选择 Excel 文件
    FE->>API: POST /api/excel/upload
    API->>API: 保存文件到 uploads/
    API->>EH: load(file_path)
    EH-->>API: TestCase[]
    API->>S: 保存 test_cases / excel_path
    API-->>FE: case_count / sheets
    FE->>API: GET /api/cases
    API-->>FE: 返回测试用例列表
```

### 2.2 执行启动与逐条执行

```mermaid
sequenceDiagram
    participant U as 用户
    participant FE as Dashboard
    participant API as routes.py
    participant EXEC as ExecutorAdapter
    participant SSH as SSHManager
    participant WS as ConnectionManager
    participant DEV as 目标设备

    U->>FE: 点击开始执行
    FE->>API: POST /api/execute/start
    API->>API: 校验运行态/配置/用例
    API->>API: create_task(_run_execution)
    API-->>FE: 返回执行已启动

    API->>SSH: connect()
    SSH->>DEV: 建立连接
    DEV-->>SSH: 连接结果

    API->>EXEC: execute_all(cases)
    loop 每条已选用例
        EXEC->>WS: send_progress
        EXEC->>SSH: execute(cmd)
        SSH->>DEV: 执行远程命令
        DEV-->>SSH: stdout/stderr/exit_code
        EXEC->>WS: send_log
        EXEC->>WS: send_case_complete
        WS-->>FE: 实时推送
    end
```

### 2.3 人工确认交互

```mermaid
sequenceDiagram
    participant EXEC as ExecutorAdapter
    participant WS as ConnectionManager
    participant FE as Dashboard
    participant U as 用户

    EXEC->>WS: request_manual_confirm(step_desc)
    WS-->>FE: manual_confirm_request
    FE-->>U: 展示确认操作
    U->>FE: 点击确认/取消
    FE->>WS: confirm_response
    WS-->>EXEC: set event / 返回结果
```

### 2.4 执行结束与结果回写

```mermaid
sequenceDiagram
    participant EXEC as ExecutorAdapter
    participant API as routes.py
    participant EH as ExcelHandler
    participant WS as ConnectionManager
    participant FE as Dashboard

    EXEC-->>API: 返回 results
    API->>EH: load(excel_path)
    API->>EH: save_results(cases, excel_path)
    API->>WS: send_execution_finished(results)
    WS-->>FE: execution_finished
    FE->>FE: 清理进度/切换运行态
```

### 2.5 ASPICE 文档生成时序图

#### 2.5.1 SWE.1 需求回灌流程

```mermaid
sequenceDiagram
    participant U as 用户
    participant FE as Swe1Step
    participant API as aspice_routes.py
    participant Ingest as swe1_ingest.py
    participant Validate as aspice_validate.py
    participant Store as creator_store.py

    U->>FE: 上传需求源文件（Excel/Word）
    FE->>API: POST /api/aspice/swe1/ingest
    API->>Ingest: parse_source_file(file_path)
    Ingest-->>API: ParsedRow[]
    API->>Validate: validate_requirements(rows)
    Validate-->>API: validation_result
    API->>Store: save_requirements(project_id, rows)
    Store-->>API: success
    API-->>FE: 返回回灌结果
    FE->>FE: 刷新需求台账
```

#### 2.5.2 SWE.2 架构文档生成流程

```mermaid
sequenceDiagram
    participant U as 用户
    participant FE as Swe2Step
    participant API as aspice_routes.py
    participant Generator as arch_generator.py
    participant Sections as arch_sections.py
    participant AI as ai/service.py
    participant Template as template_engine.py
    participant Store as creator_store.py

    U->>FE: 填写架构信息（组件/接口/场景）
    FE->>API: POST /api/aspice/swe2/generate
    API->>Store: load_project(project_id)
    Store-->>API: project_data
    API->>Generator: generate_architecture_doc(project_data)
    Generator->>Sections: load_arch_sections()
    Sections-->>Generator: 术语/假设/集成原则
    Generator->>AI: generate_func_briefs(components)
    AI-->>Generator: 函数简介
    Generator->>Template: render_docx(context)
    Template-->>Generator: docx_bytes
    Generator-->>API: docx_file
    API-->>FE: 下载架构设计书
```

#### 2.5.3 SWE.3 详细设计生成流程

```mermaid
sequenceDiagram
    participant U as 用户
    participant FE as Swe3Step
    participant API as aspice_routes.py
    participant Scanner as code_scanner.py
    participant AI as ai/service.py
    participant Generator as arch_generator_swe3.py
    participant Template as template_engine.py
    participant Store as creator_store.py

    U->>FE: 上传工程源码
    FE->>API: POST /api/aspice/swe3/scan
    API->>Scanner: scan_project(source_zip)
    Scanner-->>API: modules/functions/types
    API->>Store: save_scan_result(project_id, scan_data)
    
    U->>FE: 选择聚焦函数
    FE->>API: POST /api/aspice/swe3/generate
    API->>Store: load_project(project_id)
    Store-->>API: project_data
    API->>AI: augment_function_details(focus_functions)
    AI-->>API: 增强后的函数描述
    API->>Generator: generate_detailed_design(project_data)
    Generator->>Template: render_docx(context)
    Template-->>Generator: docx_bytes
    Generator-->>API: docx_file
    API-->>FE: 下载详细设计书
```

## 3. 图示阅读建议

如果用于评审或后续开发，可以按下面顺序阅读：

1. 先看“端到端模块关系图”，理解系统分层
2. 再看“后端内部模块关系”，理解执行链路
3. 再看“Excel 上传”和“执行启动”时序图，掌握主流程
4. 最后看“人工确认”和“结果回写”时序图，理解系统亮点与关键差异化能力

## 4. 图示与架构章节映射

| 图示章节 | 对应架构关注点 |
|---|---|
| 1.1 端到端模块关系 | 总体分层、系统边界 |
| 1.2 前端内部模块关系 | 前端职责划分、状态与通信组织 |
| 1.3 后端内部模块关系 | 后端接入层、编排层、适配层关系 |
| 2.1 上传与解析时序 | Excel 导入链路 |
| 2.2 执行启动与逐条执行 | 主执行链路 |
| 2.3 人工确认交互 | 半自动测试交互机制 |
| 2.4 执行结束与结果回写 | 结果沉淀与闭环 |
| 2.5.1 SWE.1 需求回灌流程 | ASPICE 需求分析与回灌链路 |
| 2.5.2 SWE.2 架构文档生成流程 | ASPICE 架构设计文档生成链路 |
| 2.5.3 SWE.3 详细设计生成流程 | ASPICE 详细设计文档生成链路 |

## 5. 结论

从模块关系和时序上看，当前系统的架构核心非常明确：

- **REST 负责命令与查询**
- **WebSocket 负责实时反馈**
- **ExcelHandler 负责测试资产读写兼容**
- **ExecutorAdapter 负责执行编排**
- **SSHManager 负责远端执行落地**

这说明该系统的核心价值不在“平台复杂度”，而在“测试资产兼容 + 执行闭环 + 实时交互”。
