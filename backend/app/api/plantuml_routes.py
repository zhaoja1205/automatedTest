"""
PlantUML 渲染代理。

浏览器直连公网 plantuml.com 常见失败：
- 公司/校园/国内网络间歇性 TLS 握手失败（跟 GitHub HTTPS 一个套路）
- 浏览器 fetch 报 `Failed to fetch`（没有 HTTP 状态码，没法自愈）
- 部分环境 DNS 污染直接把域名解析歪
- plantuml.com 公网服务不稳：实测 median 24.82s，1/3 请求 504

后端代理这一步，服务器侧的网络通常比用户浏览器稳；即便走代理也能在
后端配 https_proxy 集中处理。前端只需要把 PlantUML 已编码好的 URL
片段（deflate+base64 或 ~hHEX）转发给后端。

## 后端选择（env 配置）

两种渲染后端，通过环境变量 `PLANTUML_BACKEND` 切换：

- `cloud`（默认）：走 https://www.plantuml.com/plantuml/<fmt>/<enc>
- `local`：走 `PLANTUML_LOCAL_URL`（默认 http://10.10.134.116:8080）
  本地 Jetty server 路径是 `/<fmt>/<enc>`，没有 /plantuml 前缀

实测对比（IReadRegisterSensor 真实函数）：
- cloud: median 24.82s（1/3 请求 504），依赖公网
- local: median 0.21s（118×），CJK 字体挂主机 /usr/share/fonts

以后稳定了会加 "本地优先 + 云回退" 模式（1s 本地失败即回退 cloud）。

## 安全边界

防止把这个端点当成 SSRF 跳板，target host 是 allowlist：
- cloud 模式：硬编码 `www.plantuml.com` / `plantuml.com`
- local 模式：`PLANTUML_LOCAL_URL` 必须是 http(s):// 开头、host 列入 _ALLOWED_LOCAL_HOSTS
  默认白名单是部署在 10.10.134.116:8080 的内网 server；运维要换机器就改环境变量
  同时更新白名单（或直接把白名单也 env 化，这版先写死足够）。
"""
from __future__ import annotations

import logging
import os
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response


router = APIRouter()
logger = logging.getLogger(__name__)

# ---- 后端选择 ----

# `cloud` = plantuml.com；`local` = 内网 Jetty server
# env 读取时机：模块 import，热重启就能换。启动参数 / docker run -e / .env 都行
_BACKEND = os.getenv("PLANTUML_BACKEND", "cloud").strip().lower()
if _BACKEND not in ("cloud", "local"):
    # 不抛异常是因为启动阶段配错 env 把整个后端拉崩不值得，静默回退 cloud
    # 控制台里会打一行；运维看日志就知道拼错了
    logger.warning(
        "PLANTUML_BACKEND=%r 无效，回退 cloud。有效值：cloud / local", _BACKEND,
    )
    _BACKEND = "cloud"

# 本地 server 根 URL。Jetty 镜像的路径是 /<fmt>/<enc>（不是 /plantuml/<fmt>/<enc>）
_LOCAL_URL = os.getenv("PLANTUML_LOCAL_URL", "http://10.10.134.116:8080").rstrip("/")

# cloud 模式的 allowlist（历史版本就在这，保留）
_ALLOWED_CLOUD_HOSTS = {"www.plantuml.com", "plantuml.com"}
# local 模式的 allowlist：防 SSRF。默认的本地 server + localhost 回环都允许
_ALLOWED_LOCAL_HOSTS = {"10.10.134.116", "localhost", "127.0.0.1"}

# 校验 local URL 合法性。**不抛异常** —— 因为前端 UI 可以让用户在运行时切换
# backend，我们希望"env 默认 cloud、UI 临时切 local"也能工作。所以这里只打一个
# 标志位：URL 合法且 host 在 allowlist → OK；不 OK 时 UI 切 local 会被 400 拒
_LOCAL_URL_OK = False
_p = urlparse(_LOCAL_URL)
if _p.scheme in ("http", "https") and _p.hostname:
    if _p.hostname in _ALLOWED_LOCAL_HOSTS:
        _LOCAL_URL_OK = True
    else:
        logger.warning(
            "PLANTUML_LOCAL_URL host=%r 不在 allowlist %s；UI 切 local 会被拒绝。"
            "要用新机器请加到 _ALLOWED_LOCAL_HOSTS 或改环境变量。",
            _p.hostname, sorted(_ALLOWED_LOCAL_HOSTS),
        )
else:
    logger.warning(
        "PLANTUML_LOCAL_URL=%r 不是合法 http(s)://host 形式；UI 切 local 会被拒绝。",
        _LOCAL_URL,
    )

# env 默认是 local 但 local URL 不可用 → 强行回退 cloud，并打警告
if _BACKEND == "local" and not _LOCAL_URL_OK:
    logger.warning("PLANTUML_BACKEND=local 但本地 URL 不可用，回退 cloud")
    _BACKEND = "cloud"


# 请求超时：SVG 一般秒级，PNG 稍长；local 快得多但保留一致超时逻辑简单
_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


def _resolve_backend(override: Optional[str]) -> str:
    """决定本次请求实际走哪个 backend。

    优先级：
      1. query `?backend=local|cloud` —— 前端用户 UI 里主动选，当次生效
      2. env `PLANTUML_BACKEND` —— 部署默认
    空值 / 其他 → 回退到 env 默认，不抛错
    """
    if override in ("local", "cloud"):
        if override == "local" and not _LOCAL_URL_OK:
            # 用户选了 local 但部署时 local URL 校验没过（host 不在 allowlist）；
            # 直接 400 比静默回退 cloud 诚实，用户能看到为什么没切过去
            raise HTTPException(
                status_code=400,
                detail="后端未配置可用的本地 PlantUML server（PLANTUML_LOCAL_URL 为空或不在 allowlist）。"
            )
        return override
    return _BACKEND


def _build_url(backend: str, fmt: str, encoded: str) -> str:
    """按选定 backend 拼目标 URL —— cloud 带 /plantuml 前缀，local 不带。"""
    if backend == "local":
        return f"{_LOCAL_URL}/{fmt}/{encoded}"
    return f"https://www.plantuml.com/plantuml/{fmt}/{encoded}"


@router.get("/render")
async def render(
    fmt: str = Query("svg", pattern="^(svg|png)$"),
    encoded: str = Query(..., min_length=1, max_length=200000),
    backend: Optional[str] = Query(None, pattern="^(local|cloud)$"),
):
    """代理渲染请求。URL 按（query `backend` → env `PLANTUML_BACKEND`）决定。

    Args:
        fmt: svg 或 png（前端只用这两个格式）
        encoded: PlantUML 官方编码，deflate+base64 或 ~hHEX 都支持——透传即可
        backend: 前端 UI 的"本地/线上"选择；不填走 env 默认

    Returns:
        原样透传上游响应体和 content-type。
    """
    active = _resolve_backend(backend)
    url = _build_url(active, fmt, encoded)
    tag = "本地 PlantUML server" if active == "local" else "plantuml.com"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url)
    except httpx.TimeoutException as e:
        raise HTTPException(status_code=504, detail=f"{tag} 请求超时：{e}")
    except httpx.HTTPError as e:
        # 网络/DNS/TLS 类错误一律 502，用户看得懂
        raise HTTPException(status_code=502, detail=f"{tag} 连接失败：{e}")

    if resp.status_code >= 400:
        # 4xx 通常是 UML 语法问题（plantuml 会把错误图作为 200 返回，很少走这里）
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"{tag} HTTP {resp.status_code}",
        )

    # content-type 透传，SVG 是 image/svg+xml，PNG 是 image/png
    content_type = resp.headers.get("content-type", "application/octet-stream")
    return Response(content=resp.content, media_type=content_type)


@router.get("/backend")
async def backend_info():
    """暴露当前 backend 配置给前端/运维 —— 便于排障、前端 UI 显示可选项。

    返回：
    - backend: "cloud" / "local"（env 默认，前端 UI 初始化时用）
    - local_available: bool，local server URL 是否可用（UI 决定是否禁用 local 选项）
    - local_url_hint: 当前 local server 根 URL（便于肉眼核对）
    - cloud_url_hint: 当前 cloud URL 模式
    """
    return {
        "backend": _BACKEND,
        "local_available": _LOCAL_URL_OK,
        "local_url_hint": _LOCAL_URL if _LOCAL_URL_OK else None,
        "cloud_url_hint": "https://www.plantuml.com/plantuml/{fmt}/{encoded}",
    }
