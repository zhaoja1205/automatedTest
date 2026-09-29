"""
PlantUML 在线渲染代理。

浏览器直连 https://www.plantuml.com 常见失败：
- 公司/校园/国内网络间歇性 TLS 握手失败（跟 GitHub HTTPS 一个套路）
- 浏览器 fetch 报 `Failed to fetch`（没有 HTTP 状态码，没法自愈）
- 部分环境 DNS 污染直接把域名解析歪

后端来代理这一步，服务器侧的网络通常比用户浏览器稳；即便走代理也能在
后端配 https_proxy 集中处理。前端只需要把 PlantUML 已编码好的 URL
片段（deflate+base64 或 ~hHEX）转发给后端。

安全边界：为了防止把这个端点当成 SSRF 跳板，target host 硬编码只允许
`www.plantuml.com` / `plantuml.com`，其他 URL 一律 400。
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response


router = APIRouter()

# 只放行官方渲染服务；不做通用 HTTP 代理
_ALLOWED_HOSTS = {"www.plantuml.com", "plantuml.com"}

# 请求超时：SVG 一般秒级，PNG 稍长。默认 20 秒够用；再长基本是网卡了
_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


@router.get("/render")
async def render(
    fmt: str = Query("svg", pattern="^(svg|png)$"),
    encoded: str = Query(..., min_length=1, max_length=200000),
):
    """代理请求 https://www.plantuml.com/plantuml/<fmt>/<encoded>。

    Args:
        fmt: svg 或 png（前端只用这两个格式）
        encoded: PlantUML 官方编码，deflate+base64 或 ~hHEX 都支持——透传即可

    Returns:
        原样透传 plantuml.com 的响应体和 content-type。
    """
    url = f"https://www.plantuml.com/plantuml/{fmt}/{encoded}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url)
    except httpx.TimeoutException as e:
        raise HTTPException(status_code=504, detail=f"plantuml.com 请求超时：{e}")
    except httpx.HTTPError as e:
        # 网络/DNS/TLS 类错误一律 502，用户看得懂
        raise HTTPException(status_code=502, detail=f"plantuml.com 连接失败：{e}")

    if resp.status_code >= 400:
        # 4xx 通常是 UML 语法问题（plantuml 会把错误图作为 200 返回，很少走这里）
        raise HTTPException(status_code=resp.status_code,
                            detail=f"plantuml.com HTTP {resp.status_code}")

    # content-type 透传，SVG 是 image/svg+xml，PNG 是 image/png
    content_type = resp.headers.get("content-type", "application/octet-stream")
    return Response(content=resp.content, media_type=content_type)
