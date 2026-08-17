#!/bin/bash
# 停止前后端服务

cd "$(dirname "$0")"
PROJECT_ROOT="$(pwd)"

echo "=== 停止测试执行管理系统 ==="

# 停止后端
echo "[1/2] 停止后端服务..."
BACKEND_PIDS=$(pgrep -f "uvicorn app.main:app.*--port 8000" 2>/dev/null)
if [ -n "$BACKEND_PIDS" ]; then
    echo "$BACKEND_PIDS" | xargs kill 2>/dev/null
    echo "后端已停止 (PID: $BACKEND_PIDS)"
else
    echo "后端未在运行"
fi

# 停止前端
echo "[2/2] 停止前端服务..."
FRONTEND_PIDS=$(pgrep -f "node.*vite.*--port 3000" 2>/dev/null)
if [ -n "$FRONTEND_PIDS" ]; then
    echo "$FRONTEND_PIDS" | xargs kill 2>/dev/null
    echo "前端已停止 (PID: $FRONTEND_PIDS)"
else
    echo "前端未在运行"
fi

# 等待进程退出
sleep 1

# 确认清理
REMAINING_8000=$(ss -ltnp 2>/dev/null | grep ":8000 ")
REMAINING_3000=$(ss -ltnp 2>/dev/null | grep ":3000 ")

if [ -z "$REMAINING_8000" ] && [ -z "$REMAINING_3000" ]; then
    echo ""
    echo "所有服务已停止"
else
    [ -n "$REMAINING_8000" ] && echo "警告: 端口 8000 仍有进程占用，尝试强制终止..." && fuser -k 8000/tcp 2>/dev/null
    [ -n "$REMAINING_3000" ] && echo "警告: 端口 3000 仍有进程占用，尝试强制终止..." && fuser -k 3000/tcp 2>/dev/null
    echo "强制终止完成"
fi
