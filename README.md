# 测试执行管理系统 (Test Runner Web)

基于原 `demo_testcamera` 工程转换的 Web 版测试执行管理系统。

## 技术栈

- **后端**: Python 3.10+ / FastAPI / WebSocket / paramiko
- **前端**: React 18 / TypeScript / Vite / Ant Design / Zustand

## 项目结构

```
test_runner_web/
├── backend/                    # 后端服务
│   ├── app/
│   │   ├── main.py            # FastAPI 入口 + session 中间件
│   │   ├── api/
│   │   │   ├── routes.py       # 执行管理 REST API
│   │   │   └── creator_routes.py  # 用例创建 REST API（A1→A5 向导）
│   │   ├── core/
│   │   │   ├── test_case.py    # 用例数据模型
│   │   │   ├── ssh_manager.py  # SSH 连接管理
│   │   │   ├── executor_adapter.py  # 执行器适配
│   │   │   ├── excel_handler.py     # Excel 读写
│   │   │   ├── expected_parser.py   # 预期结果解析
│   │   │   ├── creator_store.py    # 用例创建项目存储
│   │   │   └── case_generator.py   # 矩阵驱动用例骨架生成器
│   │   ├── ai/                # AI 能力层（判定/分析/报告/步骤解析）
│   │   └── websocket/manager.py
│   ├── scripts/gen_cases.py   # cases.json → xlsx 导出
│   └── requirements.txt
├── frontend/                   # 前端应用
│   ├── src/
│   │   ├── App.tsx            # 路由
│   │   ├── api/               # API 封装
│   │   ├── components/creator/  # 用例创建向导组件
│   │   ├── pages/             # Dashboard / History / Reports / creator 等
│   │   ├── stores/            # useStore + useCreatorStore
│   │   ├── types/             # index.ts + creator.ts
│   │   └── utils/caseRules.ts  # 用例规范校验
│   ├── package.json
│   └── vite.config.ts
├── docs/                      # 架构/图示/版本路线/使用说明
├── start.sh                   # 一键启动脚本
├── stop.sh
└── VERSION                    # 当前版本号
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

## 功能说明

### 测试执行管理

1. **上传用例**: 上传 Excel 测试用例文件（支持 AI 步骤智能解析）
2. **配置管理**: SSH 连接配置（直连/跳板机）、工作区配置
3. **执行测试**: 通过 SSH 在目标设备上执行测试，PTY 交互式
4. **实时日志**: WebSocket 推送执行日志
5. **人工确认**: 需要人工判断的步骤弹窗确认
6. **AI 判定**: 规则引擎 + AI 语义判定（始终/不确定时/关闭三种模式）
7. **结果下载**: 下载测试结果 Excel + AI 报告
8. **历史记录**: 执行历史 + 报告管理 + 对比分析

### 测试用例创建（A1→A5 问答向导）

1. **A1 文档元信息**: 标题、文件编号、文档版本、参考资料
2. **A2 被测对象维度**: 程序名、配置名、逐模组帧率、路径、跳板机、故障变体
3. **A3 公共前置条件**: 驱动部署目录、测试工具路径、异常处理
4. **A4 分类与优先级**: 测试类型、设计方法、优先级、ID 编号规则
5. **硬件拓扑表**: Group/Link/模组型号/I2C地址/mask位 → 自动生成覆盖矩阵与 -m mask
6. **按矩阵生成用例**: 规则模板生成可判定用例骨架（支持 AI 增强开关）
7. **规范校验**: 预期结果实时校验是否含可判定观测点
8. **导出**: 生成内部版/客户版 xlsx，可直接上传到执行侧

> 项目特定信息（命令、路径、IP、阈值、帧率）不会自动编造，缺失时保留 `<待补充:xxx>` 占位符。

## 设计文档

- [架构说明文档](docs/ARCHITECTURE.md)
- [模块关系图与时序图说明](docs/DIAGRAMS.md)
- [版本规划路线图](docs/VERSION_ROADMAP.md)
- [使用说明](docs/user-guide.html)