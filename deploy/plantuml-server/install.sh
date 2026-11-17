#!/usr/bin/env bash
# PlantUML Server 一键安装脚本（在部署机本地执行）
#
# 用法：
#   在 10.10.134.116 这台机器上，把本目录放到任意位置，然后：
#     bash install.sh
#
# 做的事：
#   1. 建安装目录 ~/plantuml-server/
#   2. 复制 docker-compose.yml + 生成 systemd unit
#   3. docker compose pull + up -d
#   4. 注册 systemd 开机自启（plantuml-server.service）
#   5. 等健康检查通过 → 自测渲染 "hello 中文"
#
# 卸载：bash uninstall.sh

set -euo pipefail

# ---- 可通过环境变量覆盖的配置 ----
# 安装目录：挂载盘路径历史上被清过，默认用家目录更保险
INSTALL_DIR="${INSTALL_DIR:-$HOME/plantuml-server}"
SERVICE_NAME="plantuml-server"

script_dir="$(cd "$(dirname "$0")" && pwd)"

echo "→ [1/6] 建安装目录 $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"

echo "→ [2/6] 复制 docker-compose.yml 和生成 systemd unit"
cp "$script_dir/docker-compose.yml" "$INSTALL_DIR/docker-compose.yml"
# 把 service 模板里的 WorkingDirectory 占位符替换成实际路径
sed "s|@@INSTALL_DIR@@|$INSTALL_DIR|g" \
  "$script_dir/plantuml.service" > "/tmp/${SERVICE_NAME}.service"

echo "→ [3/6] docker compose pull + up -d"
cd "$INSTALL_DIR"
# pull 失败不阻塞 up：本地已有镜像的话也能启动，没网也能自愈
docker compose pull || echo "  (pull 失败，尝试用现有镜像启动)"
docker compose up -d

echo "→ [4/6] 注册 systemd 单元 ${SERVICE_NAME}.service（需要 sudo）"
sudo cp "/tmp/${SERVICE_NAME}.service" "/etc/systemd/system/${SERVICE_NAME}.service"
sudo systemctl daemon-reload
sudo systemctl enable --now "${SERVICE_NAME}.service"

echo "→ [5/6] 等容器健康检查"
tries=0
while [ $tries -lt 30 ]; do
  status=$(docker inspect --format '{{.State.Health.Status}}' plantuml-server 2>/dev/null || echo "none")
  if [ "$status" = "healthy" ]; then
    echo "  容器健康 ✓"
    break
  fi
  sleep 2
  tries=$((tries + 1))
done
if [ $tries -ge 30 ]; then
  echo "  ⚠ 健康检查未在 60s 内通过，查日志：docker logs plantuml-server" >&2
fi

echo "→ [6/6] 自测：渲染一张 'hello 中文' 图"
# SoWkIImgAStDuRBAICt9oLTuicFjisdjrbmEgNafG640 = deflate+base64 of ":hello 中文;"
sample="SoWkIImgAStDuRBAICt9oLTuicFjisdjrbmEgNafG640"
http_code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:8080/png/$sample")
if [ "$http_code" = "200" ]; then
  echo "  ✓ 本地渲染 OK (HTTP 200)"
else
  echo "  ✗ 本地渲染异常 (HTTP $http_code)" >&2
  echo "    手工复查：curl -v http://127.0.0.1:8080/png/$sample" >&2
  exit 1
fi

cat <<EOF

========================================
PlantUML Server 安装完成！
========================================

容器：    docker ps --filter name=plantuml-server
日志：    docker logs plantuml-server
systemd:  sudo systemctl status ${SERVICE_NAME}
重启：    sudo systemctl restart ${SERVICE_NAME}
停止：    sudo systemctl stop ${SERVICE_NAME}
卸载：    bash uninstall.sh

渲染入口（内网）：
  http://<本机 IP>:8080/<svg|png|txt>/<plantuml-encoded>

test_runner_web 后端默认的 allowlist 已含 10.10.134.116；
在 test_runner_web 的前端 UI 工具栏里选 "本地内网 server" 即可。
EOF
