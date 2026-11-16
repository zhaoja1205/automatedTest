#!/bin/bash
set -e

cd "$(dirname "$0")"

PROJECT_ROOT="$(pwd)"

# --- PlantUML 本地渲染后端（10.10.134.116:8080）---
# 导出 docx 时 arch_generator_* 会把 PlantUML 源渲染成 PNG 嵌入。默认走公网
# plantuml.com 会因 URL 太长 400 / SSL 握手超时，所以在 start.sh 里直接钉到本地服务。
# 如需切回公网：注释掉这行 or 临时 PLANTUML_BACKEND=cloud ./start.sh
export PLANTUML_BACKEND="${PLANTUML_BACKEND:-local}"
export PLANTUML_LOCAL_URL="${PLANTUML_LOCAL_URL:-http://10.10.134.116:8080}"

BACKEND_PID=""
FRONTEND_PID=""

get_listening_pid() {
    local port="$1"
    ss -ltnp 2>/dev/null | awk -v port="$port" '
        $4 ~ ":" port "$" && match($0, /pid=[0-9]+/) {
            print substr($0, RSTART + 4, RLENGTH - 4)
            exit
        }
    '
}

cmdline_contains() {
    local pid="$1"
    local expected="$2"

    [ -r "/proc/$pid/cmdline" ] || return 1
    tr '\0' ' ' < "/proc/$pid/cmdline" | grep -Fq "$expected"
}

cleanup() {
    [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null || true
    [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null || true
    exit
}

trap cleanup INT TERM

echo "=== 启动测试执行管理系统 ==="

# 启动后端（若已在运行则先停再重启，确保加载最新代码）
echo "[1/2] 启动后端服务..."
EXISTING_BACKEND_PID="$(get_listening_pid 8000 || true)"
if [ -n "$EXISTING_BACKEND_PID" ]; then
    if cmdline_contains "$EXISTING_BACKEND_PID" "$PROJECT_ROOT/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000"; then
        echo "检测到后端已在运行 (PID: $EXISTING_BACKEND_PID)，重启以加载最新代码..."
        kill "$EXISTING_BACKEND_PID" 2>/dev/null || true
        sleep 1
        # 确保进程已退出
        kill -0 "$EXISTING_BACKEND_PID" 2>/dev/null && kill -9 "$EXISTING_BACKEND_PID" 2>/dev/null || true
        sleep 0.5
    else
        echo "错误: 端口 8000 已被其他进程占用 (PID: $EXISTING_BACKEND_PID)，请先释放端口后重试。" >&2
        exit 1
    fi
fi
cd backend
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -q --timeout 15 --retries 1 -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
cd ..

# 启动前端（若已在运行则先停再重启）
echo "[2/2] 启动前端服务..."
EXISTING_FRONTEND_PID="$(get_listening_pid 3000 || true)"
if [ -n "$EXISTING_FRONTEND_PID" ]; then
    if cmdline_contains "$EXISTING_FRONTEND_PID" "$PROJECT_ROOT/frontend/node_modules/.bin/vite"; then
        echo "检测到前端已在运行 (PID: $EXISTING_FRONTEND_PID)，重启..."
        kill "$EXISTING_FRONTEND_PID" 2>/dev/null || true
        sleep 1
        kill -0 "$EXISTING_FRONTEND_PID" 2>/dev/null && kill -9 "$EXISTING_FRONTEND_PID" 2>/dev/null || true
        sleep 0.5
    else
        echo "错误: 端口 3000 已被其他进程占用 (PID: $EXISTING_FRONTEND_PID)，请先释放端口后重试。" >&2
        exit 1
    fi
fi
cd frontend
if [ ! -d "node_modules" ]; then
    npm install
fi
# HTTPS 开关：
#   bash start.sh            → HTTP（默认，兼容老行为）
#   HTTPS=1 bash start.sh    → HTTPS 自签（File System Access API 需要，内网 IP 必须）
#     启用后：访问 https://10.10.x.x:3000，Chrome 会弹一次"不安全"警告 → 点"高级/继续访问"即可
#     首次启动会 re-optimize deps，慢几秒；之后正常
if [ "$HTTPS" = "1" ]; then
    echo "  (前端启用 HTTPS 自签：请用 https://<ip>:3000 访问，首次会出证书警告)"
    VITE_HTTPS=1 npm run dev -- --host 0.0.0.0 --strictPort &
else
    npm run dev -- --host 0.0.0.0 --strictPort &
fi
FRONTEND_PID=$!
cd ..

echo ""
echo "后端: http://localhost:8000"
if [ "$HTTPS" = "1" ]; then
    echo "前端: https://localhost:3000  (自签证书，Chrome 首次需手动放行)"
else
    echo "前端: http://localhost:3000"
fi
echo ""
echo "按 Ctrl+C 停止所有服务"

wait