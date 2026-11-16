#!/usr/bin/env bash
# PlantUML Server 卸载脚本
# 做的事：
#   1. 停 systemd 服务 + 删除 unit 文件
#   2. docker compose down（容器停并删，镜像保留便于后续复用）
#   3. 保留安装目录和 compose yml（便于手工恢复）
#
# 彻底清理：
#   rm -rf ~/plantuml-server
#   docker rmi plantuml/plantuml-server:jetty

set -euo pipefail

SERVICE_NAME="plantuml-server"
INSTALL_DIR="${INSTALL_DIR:-$HOME/plantuml-server}"
REMOTE_PASS="${REMOTE_PASS:-}"

sudo_cmd="sudo -n"
if [ -n "$REMOTE_PASS" ]; then
  sudo_cmd="echo $REMOTE_PASS | sudo -S"
fi

echo "→ 停止并禁用 systemd 服务 $SERVICE_NAME"
eval "$sudo_cmd systemctl disable --now $SERVICE_NAME 2>/dev/null || true"
eval "$sudo_cmd rm -f /etc/systemd/system/${SERVICE_NAME}.service"
eval "$sudo_cmd systemctl daemon-reload"

echo "→ docker compose down"
if [ -f "$INSTALL_DIR/docker-compose.yml" ]; then
  cd "$INSTALL_DIR"
  docker compose down || true
fi

echo "→ 已清理 systemd 和容器；镜像和 $INSTALL_DIR 目录保留（彻底删手工 rm）"
