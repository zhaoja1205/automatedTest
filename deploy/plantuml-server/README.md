# PlantUML Server —— 10.10.134.116 内网渲染加速

部署在 `10.10.134.116:8080` 的 PlantUML Jetty 容器，为 test_runner_web 后端
`/api/plantuml/render` 的 "本地后端" 模式提供渲染服务。

## 性能对比（实测，IReadRegisterSensor 真实函数）

| 后端 | 中位数延迟 | 成功率 | 备注 |
|---|---|---|---|
| plantuml.com | 24.82 s | 2/3 | 公网，504 偶发 |
| 本地 10.10.134.116:8080 | **0.21 s** | 100% | 118× 快，挂主机 41 款 CJK 字体 |

## 目录说明

- `docker-compose.yml` —— 容器定义（Jetty 变体 + CJK 字体挂载 + 健康检查）
- `install.sh` —— 一键安装（建目录 / 拉镜像 / 启动 / 注册 systemd 开机自启 / 自测）
- `plantuml.service` —— systemd unit 模板
- `uninstall.sh` —— 卸载（停容器、删 systemd、保留镜像便于复用）
- `README.md` —— 当前文档

## 使用步骤（在部署机本机执行）

```bash
# 1. 把本目录拷到部署机 10.10.134.116 的任意位置（家目录即可）
#    举例：从开发机推过去
scp -r deploy/plantuml-server tstj@10.10.134.116:~/

# 2. 登上部署机，运行安装脚本（需要 sudo 权限注册 systemd）
ssh tstj@10.10.134.116
cd ~/plantuml-server
bash install.sh
```

脚本会打印 6 个步骤的进度，最后一步自测通过就安装完成了。

## 验证

```bash
# 在同网段任何机器上
curl -s http://10.10.134.116:8080/ -o /dev/null -w "HTTP %{http_code}\n"
# 应返回 HTTP 200
```

## 开机自启机制

install 后，systemd 托管容器，常用命令：

```bash
sudo systemctl status plantuml-server    # 查看状态
sudo systemctl restart plantuml-server   # 重启
sudo systemctl stop plantuml-server      # 停止
sudo journalctl -u plantuml-server -n 50 # 查日志
```

Unit 配置 `Restart=on-failure` + `RestartSec=10s`，容器崩了自动拉起；
机器重启也自动起来。

## 前端如何调到本地 server

前端 4 个页面（流程图/时序图/时序图工作台/类图工作台）工具栏右上
都有 **"渲染后端"** 下拉选择器：
- 默认（cloud）—— 走 plantuml.com
- **本地内网 server** —— 走 http://10.10.134.116:8080
- plantuml.com —— 强制走线上

选择保存在浏览器 `localStorage` 里，切一次全站生效。

## 换部署机的注意事项

如果换部署机（例如 10.10.134.XXX），test_runner_web 后端代码的 **allowlist** 要同步改：

- `backend/app/api/plantuml_routes.py` 里的 `_ALLOWED_LOCAL_HOSTS`
- 把新 IP 加进去
- 后端启动时通过 `PLANTUML_LOCAL_URL=http://新IP:8080` 覆盖默认

不改 allowlist 直接设环境变量 → 后端会在启动日志里打 "host 不在 allowlist；UI
切 local 会被拒绝"，这是故意的 SSRF 防护，不是 bug。

## 安全考虑

- `ALLOW_PLANTUML_INCLUDE=false`：禁用 `!includeurl` 等远程包含指令，防
  通过 UML 源码触发 SSRF
- `PLANTUML_LIMIT_SIZE=16384`：限制单图像素尺寸
- 容器只开 8080 一个端口，仅内网可达
- 没挂主机根目录、没挂 docker.sock，容器逃逸面控制在 Jetty + PlantUML 已知漏洞
