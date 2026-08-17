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
│   │   ├── main.py            # FastAPI 入口
│   │   ├── api/
│   │   │   └── routes.py      # REST API 路由
│   │   ├── core/
│   │   │   ├── test_case.py   # 用例数据模型
│   │   │   ├── ssh_manager.py # SSH 连接管理
│   │   │   ├── executor_adapter.py  # 执行器适配
│   │   │   └── excel_handler.py     # Excel 处理
│   │   └── websocket/
│   │       └── manager.py     # WebSocket 管理
│   └── requirements.txt
├── frontend/                   # 前端应用
│   ├── src/
│   │   ├── main.tsx           # 入口
│   │   ├── App.tsx            # 路由
│   │   ├── api/axios.ts       # API 封装
│   │   ├── stores/useStore.ts # 状态管理
│   │   ├── hooks/useWebSocket.ts  # WebSocket Hook
│   │   ├── types/index.ts     # 类型定义
│   │   ├── components/Layout.tsx  # 布局
│   │   └── pages/Dashboard.tsx    # 主页面
│   ├── package.json
│   └── vite.config.ts
├── start.sh                    # 一键启动脚本
└── README.md
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
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 前端
cd frontend
npm install
npm run dev
```

访问 http://localhost:3000

## 功能说明

1. **上传用例**: 上传 Excel 测试用例文件
2. **配置管理**: SSH 连接配置、工作区配置
3. **执行测试**: 通过 SSH 在目标设备上执行测试
4. **实时日志**: WebSocket 推送执行日志
5. **人工确认**: 需要人工判断的步骤弹窗确认
6. **结果下载**: 下载测试结果 Excel

## 设计文档

- [架构说明文档](docs/ARCHITECTURE.md)
- [模块关系图与时序图说明](docs/DIAGRAMS.md)