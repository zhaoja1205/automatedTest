/**
 * C++ 函数流程图生成页面
 *
 * 生成链路：
 *   C++ 源码 → parseBody() 得 FlowNode[] → buildPlantUML() 得 @startuml…@enduml
 *   → plantUmlToUrl() 得 https://www.plantuml.com/plantuml/svg/<deflate+base64>
 *   → <img>/fetch 拉回 SVG，内嵌到画布
 *   （URL 拉不动时自动回退到 plantUmlToHexUrl() 的 ~h<hex> 长格式）
 *
 * 引入 PlantUML 作为中间源码，是为了让"生成不完美"的地方可以人工微调 ——
 * 右侧画布顶栏有 Tabs：
 *   - [流程图]      —— 展示实时渲染的 SVG，支持缩放/画布拖拽/节点拖拽
 *   - [PlantUML 源码] —— TextArea，用户改完点"重新渲染"即刷新流程图
 *
 * 生成默认纵向布局，方向不再由 UI 切换（PlantUML activity beta 默认纵向）。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Card, Input, Button, Space, Typography, message, Tag, Tooltip, Tabs, Spin } from 'antd'
import {
  ApartmentOutlined, ThunderboltOutlined, DownloadOutlined, FileTextOutlined,
  ZoomInOutlined, ZoomOutOutlined, FullscreenOutlined, ExpandOutlined,
  ReloadOutlined, CodeOutlined, FileImageOutlined,
} from '@ant-design/icons'
import {
  extractFunction, buildPlantUML, plantUmlToUrl, plantUmlToHexUrl, EXAMPLE_CPP,
} from '../../utils/cppFlowchart'

const { Text } = Typography
const { TextArea } = Input

/**
 * 从 Mermaid v10 生成的 SVG 里，解析每个节点的中心点、
 * 以及每条 edge 起止节点 id，用于拖拽后重绘连接线。
 * PlantUML 生成的 SVG 结构不同 —— 每个 "块" 是一个带 `id="..."` 的 <g>，
 * 内部包含一个 <polygon>/<rect>/<path> 和多个 <text>；
 * 连线则是独立的 <path> / <polygon>（箭头）。
 * 为了通用拖拽体验，我们只做"整块 <g> translate 偏移" —— 连线不重绘，
 * 保持视觉上"节点被推离原位、留一条弯折线连回"的效果。用户主�用拖拽
 * 微调局部布局，不追求精确重连。
 */
type NodeGeom = {
  id: string
  g: SVGGElement
  // <g> 原始 transform 里的 translate(tx, ty)
  tx: number
  ty: number
  // 拖拽产生的额外偏移
  dx: number
  dy: number
}

function readTranslate(g: SVGGElement): { tx: number; ty: number } {
  const tr = g.getAttribute('transform') || ''
  const m = tr.match(/translate\(\s*(-?[\d.]+)[,\s]+(-?[\d.]+)\s*\)/)
  if (m) return { tx: parseFloat(m[1]), ty: parseFloat(m[2]) }
  return { tx: 0, ty: 0 }
}

export default function FlowchartPage() {
  const [code, setCode] = useState(EXAMPLE_CPP)
  const [uml, setUml] = useState('')      // PlantUML 源码，Tabs 里可编辑
  const [stat, setStat] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [activeTab, setActiveTab] = useState<'flow' | 'uml'>('flow')

  const flowRef = useRef<HTMLDivElement>(null)
  const svgWrapRef = useRef<HTMLDivElement>(null)
  const lastSvgRef = useRef('')
  const [scale, setScale] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })

  // 节点几何信息（渲染后填充，拖拽时更新）
  const nodesRef = useRef<Map<string, NodeGeom>>(new Map())
  const nodeDragRef = useRef<{
    id: string
    startClientX: number
    startClientY: number
    startDx: number
    startDy: number
  } | null>(null)

  // 应用缩放 + 平移到 SVG（transform）
  useEffect(() => {
    const svg = flowRef.current?.querySelector('svg') as SVGElement | null
    if (!svg) return
    svg.style.transformOrigin = '0 0'
    svg.style.transform = `translate(${pan.x}px, ${pan.y}px) scale(${scale})`
    svg.style.transition = 'transform 0.08s'
  }, [scale, pan])

  const fitToWindow = useCallback(() => {
    const host = svgWrapRef.current
    const svg = flowRef.current?.querySelector('svg') as SVGSVGElement | null
    if (!host || !svg) return
    const vb = svg.viewBox && svg.viewBox.baseVal
    const w = vb && vb.width ? vb.width : (svg.getBBox().width || 800)
    const h = vb && vb.height ? vb.height : (svg.getBBox().height || 600)
    const availW = host.clientWidth - 20
    const availH = host.clientHeight - 20
    if (availW <= 0 || availH <= 0 || w <= 0 || h <= 0) {
      setScale(1); setPan({ x: 0, y: 0 }); return
    }
    const s = Math.min(availW / w, availH / h)
    const finalScale = s > 0.05 ? s : 1
    const centeredX = Math.max(10, (host.clientWidth - w * finalScale) / 2)
    setScale(finalScale)
    setPan({ x: centeredX, y: 10 })
  }, [])

  /** 扫描 SVG 里可拖拽的 <g>（PlantUML 会给每个 activity 块打 id），绑定 mousedown */
  const indexSvgGraph = useCallback(() => {
    const svg = flowRef.current?.querySelector('svg') as SVGSVGElement | null
    if (!svg) return
    nodesRef.current.clear()

    // PlantUML 生成的 SVG：每个 activity 块是 <g id="xxx"> 且内部至少一个 <text>；
    // 忽略根 <g class="root"> 和纯箭头组
    const groups = svg.querySelectorAll<SVGGElement>('g[id]')
    groups.forEach(g => {
      // 只保留带有 <text>（说明是可视化块）且没有子 <g> 的叶子节点
      if (g.querySelector(':scope > text') === null) return
      const id = g.getAttribute('id') || ''
      if (!id) return
      const { tx, ty } = readTranslate(g)
      const geom: NodeGeom = { id, g, tx, ty, dx: 0, dy: 0 }
      nodesRef.current.set(id, geom)
      g.style.cursor = 'move'
      g.addEventListener('mousedown', (e: MouseEvent) => {
        e.stopPropagation()
        e.preventDefault()
        nodeDragRef.current = {
          id,
          startClientX: e.clientX,
          startClientY: e.clientY,
          startDx: geom.dx,
          startDy: geom.dy,
        }
      })
    })
  }, [])

  /**
   * 拉取 plantuml.com 渲染出的 SVG。
   * 用 fetch 而不是 <img>，因为要把 SVG 拼进 DOM 才能支持后续的节点拖拽、下载等。
   * 先用 deflate+base64（短），拉不动时自动回退到 hex（长但兼容）。
   */
  const renderSvgFromUml = useCallback(async (umlSrc: string) => {
    const host = flowRef.current
    if (!host) return
    setLoading(true)
    setError('')
    try {
      // 优先短 URL；若 fetch 直接抛（比如网络/CORS 边缘问题）就用 hex 长 URL 再试一次
      let svgText: string
      try {
        const url = plantUmlToUrl(umlSrc, 'svg')
        const resp = await fetch(url)
        if (!resp.ok) throw new Error(`plantuml.com 返回 HTTP ${resp.status}`)
        svgText = await resp.text()
      } catch (e1) {
        console.warn('deflate URL 拉取失败，回退 hex：', e1)
        const url = plantUmlToHexUrl(umlSrc, 'svg')
        const resp = await fetch(url)
        if (!resp.ok) throw new Error(`plantuml.com 返回 HTTP ${resp.status}（deflate/hex 均失败）`)
        svgText = await resp.text()
      }
      // plantuml.com 遇到语法错时会返回空响应（text/plain, 0 bytes），
      // 或返回一张带红字的 error SVG。空响应会让画布空白且无提示 —— 显式报错
      if (!svgText || !svgText.trim().startsWith('<')) {
        throw new Error(
          'plantuml.com 返回空 SVG（很可能是 PlantUML 语法错）。\n' +
          '请切到「PlantUML 源码」标签检查 activity 里是否残留 `{` `}` 等特殊字符。',
        )
      }
      // plantuml 语法错时也可能返回 SVG 但里面是红色错误文本，简单探测下
      if (/<text[^>]*>Syntax Error/i.test(svgText) || /class="[^"]*error/i.test(svgText)) {
        // 仍然把错误图渲出来，让用户直观看到哪一行错
      }
      host.innerHTML = svgText
      const svgEl = host.querySelector('svg') as SVGSVGElement | null
      if (svgEl) {
        const vb = svgEl.viewBox && svgEl.viewBox.baseVal
        const w = vb && vb.width ? vb.width : parseFloat(svgEl.getAttribute('width') || '800')
        const h = vb && vb.height ? vb.height : parseFloat(svgEl.getAttribute('height') || '600')
        svgEl.setAttribute('width', String(w))
        svgEl.setAttribute('height', String(h))
        svgEl.style.maxWidth = 'none'
        svgEl.style.display = 'block'
      }
      lastSvgRef.current = svgText
      setTimeout(() => {
        fitToWindow()
        indexSvgGraph()
      }, 60)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(
        'PlantUML 渲染失败：\n' + msg +
        '\n\n渲染走「浏览器 → 后端 /api/plantuml/render → plantuml.com」\n' +
        '检查项：\n' +
        '1) 后端是否在跑（默认 http://localhost:8000）\n' +
        '2) 后端所在机器能否访问 https://www.plantuml.com\n' +
        '   （国内环境可能需要给后端配 https_proxy 环境变量）\n' +
        '3) PlantUML 源码是否合法（切到"PlantUML 源码"标签检查）',
      )
    } finally {
      setLoading(false)
    }
  }, [fitToWindow, indexSvgGraph])

  /** 从 C++ 源码解析 → 生成 PlantUML → 送去渲染。用户点"生成流程图"按钮走这条路 */
  const generateFromCpp = useCallback(async () => {
    const func = extractFunction(code)
    if (!func) {
      if (flowRef.current) flowRef.current.innerHTML = ''
      setError('未找到函数定义：需要一个形如 RetType Class::Method(...) { ... } 的函数。')
      setStat('')
      setUml('')
      return
    }
    try {
      const { uml: newUml, count } = buildPlantUML(func)
      setUml(newUml)
      setStat(`解析完成：${count} 节点 · ${func.signature.slice(0, 70)}`)
      await renderSvgFromUml(newUml)
    } catch (err) {
      setError('C++ 解析失败：\n' + (err instanceof Error ? err.message : String(err)) +
        '\n\n（请检查函数语法是否完整、括号匹配）')
      setStat('')
    }
  }, [code, renderSvgFromUml])

  /** 从 PlantUML 源码手改后重新渲染（不重跑 C++ 解析），用户点"重新渲染"或 Ctrl+Enter */
  const reRenderFromUml = useCallback(() => {
    if (!uml.trim()) { message.warning('PlantUML 源码为空'); return }
    renderSvgFromUml(uml)
  }, [uml, renderSvgFromUml])

  useEffect(() => { generateFromCpp() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const downloadSvg = () => {
    const svgEl = flowRef.current?.querySelector('svg') as SVGSVGElement | null
    const svgOut = svgEl ? new XMLSerializer().serializeToString(svgEl) : lastSvgRef.current
    if (!svgOut) { message.warning('请先生成流程图'); return }
    const blob = new Blob([svgOut], { type: 'image/svg+xml' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'flowchart.svg'
    a.click()
    URL.revokeObjectURL(a.href)
    message.success('已下载 SVG')
  }

  /**
   * 下载 PNG。策略：
   *  1) 优先本地渲染 —— 拿当前 <svg> 的 DOM（含用户拖拽后的位置），
   *     用 Image + Canvas 转成 PNG，这样"拖后效果"也能保存下来；
   *  2) 本地渲染失败（浏览器 taint、字体缺失等）时，fallback 到
   *     plantuml.com 的 /png/~h<hex> 端点直接下发一份 PNG。
   *
   * scale 参数用来做高清导出：默认 2x，即导出图分辨率 = SVG viewBox 尺寸 × 2。
   */
  const downloadPng = async (dpi: number = 2) => {
    const svgEl = flowRef.current?.querySelector('svg') as SVGSVGElement | null
    // 优先尝试本地 SVG→PNG
    if (svgEl) {
      try {
        const vb = svgEl.viewBox && svgEl.viewBox.baseVal
        const w = vb && vb.width ? vb.width : parseFloat(svgEl.getAttribute('width') || '800')
        const h = vb && vb.height ? vb.height : parseFloat(svgEl.getAttribute('height') || '600')
        // 克隆一份，显式补上 xmlns（否则 Image 加载会失败）+ 白底
        const clone = svgEl.cloneNode(true) as SVGSVGElement
        clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
        clone.setAttribute('xmlns:xlink', 'http://www.w3.org/1999/xlink')
        // 去掉视觉 transform（我们在 CSS 上做的缩放/平移不该带进 PNG）
        clone.style.transform = ''
        const svgStr = new XMLSerializer().serializeToString(clone)
        const svgBlob = new Blob([svgStr], { type: 'image/svg+xml;charset=utf-8' })
        const url = URL.createObjectURL(svgBlob)

        const png: Blob = await new Promise((resolve, reject) => {
          const img = new Image()
          img.onload = () => {
            const canvas = document.createElement('canvas')
            canvas.width = Math.max(1, Math.round(w * dpi))
            canvas.height = Math.max(1, Math.round(h * dpi))
            const ctx = canvas.getContext('2d')
            if (!ctx) return reject(new Error('canvas 2d 上下文获取失败'))
            // 白底，避免透明 PNG 贴到深色文档看不清
            ctx.fillStyle = '#ffffff'
            ctx.fillRect(0, 0, canvas.width, canvas.height)
            ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
            canvas.toBlob(b => b ? resolve(b) : reject(new Error('canvas toBlob 返回空')), 'image/png')
          }
          img.onerror = () => reject(new Error('SVG 转 Image 失败（可能字体加载被跨域拦截）'))
          img.src = url
        })

        URL.revokeObjectURL(url)
        const a = document.createElement('a')
        a.href = URL.createObjectURL(png)
        a.download = 'flowchart.png'
        a.click()
        URL.revokeObjectURL(a.href)
        message.success(`已下载 PNG（${dpi}x 清晰度）`)
        return
      } catch (e) {
        // 本地失败继续走 fallback
        console.warn('本地 SVG→PNG 失败，回退到 plantuml.com 在线 PNG：', e)
      }
    }

    // Fallback：直接向 plantuml.com 请求 PNG
    if (!uml.trim()) { message.warning('请先生成流程图'); return }
    try {
      setLoading(true)
      let blob: Blob
      try {
        const pngUrl = plantUmlToUrl(uml, 'png')
        const resp = await fetch(pngUrl)
        if (!resp.ok) throw new Error(`plantuml.com 返回 HTTP ${resp.status}`)
        blob = await resp.blob()
      } catch (e1) {
        console.warn('deflate PNG URL 失败，回退 hex：', e1)
        const pngUrl = plantUmlToHexUrl(uml, 'png')
        const resp = await fetch(pngUrl)
        if (!resp.ok) throw new Error(`plantuml.com 返回 HTTP ${resp.status}（deflate/hex 均失败）`)
        blob = await resp.blob()
      }
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = 'flowchart.png'
      a.click()
      URL.revokeObjectURL(a.href)
      message.success('已下载 PNG（在线渲染）')
    } catch (e) {
      message.error('下载 PNG 失败：' + (e instanceof Error ? e.message : String(e)))
    } finally {
      setLoading(false)
    }
  }

  const downloadUml = () => {
    if (!uml.trim()) { message.warning('PlantUML 源码为空'); return }
    const blob = new Blob([uml], { type: 'text/plain; charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'flowchart.puml'
    a.click()
    URL.revokeObjectURL(a.href)
    message.success('已下载 PlantUML 源码')
  }

  // 滚轮缩放
  const onWheel = (e: React.WheelEvent) => {
    if (!e.ctrlKey && !e.metaKey) return
    e.preventDefault()
    const delta = e.deltaY < 0 ? 1.1 : 0.9
    setScale(s => Math.max(0.1, Math.min(4, s * delta)))
  }

  // 画布空白拖拽平移
  const dragRef = useRef<{ startX: number; startY: number; panX: number; panY: number } | null>(null)
  const onMouseDown = (e: React.MouseEvent) => {
    dragRef.current = { startX: e.clientX, startY: e.clientY, panX: pan.x, panY: pan.y }
  }
  const onMouseMove = (e: React.MouseEvent) => {
    // 优先处理节点拖拽
    if (nodeDragRef.current) {
      const nd = nodeDragRef.current
      const geom = nodesRef.current.get(nd.id)
      if (geom) {
        const sx = (e.clientX - nd.startClientX) / scale
        const sy = (e.clientY - nd.startClientY) / scale
        geom.dx = nd.startDx + sx
        geom.dy = nd.startDy + sy
        geom.g.setAttribute('transform', `translate(${geom.tx + geom.dx}, ${geom.ty + geom.dy})`)
      }
      return
    }
    if (!dragRef.current) return
    const d = dragRef.current
    setPan({ x: d.panX + (e.clientX - d.startX), y: d.panY + (e.clientY - d.startY) })
  }
  const onMouseUp = () => {
    dragRef.current = null
    nodeDragRef.current = null
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(320px, 380px) 1fr', gap: 16, alignItems: 'start', height: 'calc(100vh - 76px)' }}>
      <Card
        title={<><ApartmentOutlined style={{ marginRight: 8 }} />函数源码</>}
        size="small"
        style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
        styles={{ body: { flex: 1, overflow: 'auto' } }}
      >
        <Space direction="vertical" style={{ width: '100%' }} size="small">
          <TextArea
            value={code}
            onChange={(e) => setCode(e.target.value)}
            autoSize={{ minRows: 16, maxRows: 20 }}
            spellCheck={false}
            style={{ fontFamily: '"JetBrains Mono","Fira Code","Consolas",monospace', fontSize: 12.5 }}
          />
          <Space wrap>
            <Button type="primary" icon={<ThunderboltOutlined />} onClick={generateFromCpp} loading={loading}>
              生成流程图
            </Button>
            <Button icon={<FileTextOutlined />} onClick={() => { setCode(EXAMPLE_CPP); setTimeout(generateFromCpp, 0) }}>
              载入示例
            </Button>
            <Button icon={<DownloadOutlined />} onClick={downloadSvg}>下载 SVG</Button>
            <Button icon={<FileImageOutlined />} onClick={() => downloadPng(2)}>下载 PNG</Button>
            <Button icon={<CodeOutlined />} onClick={downloadUml}>下载 PUML</Button>
          </Space>
          <Text type="secondary" style={{ fontSize: 12 }}>
            支持解析：函数入口、变量声明、函数调用、if/else 分支、早返回、日志、赋值、最终返回。
          </Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            渲染走 <a href="https://www.plantuml.com" target="_blank" rel="noreferrer">plantuml.com</a> 在线服务。
            如果生成的图有偏差，可以切到"PlantUML 源码"标签手工修改，改完点<b>重新渲染</b>即可更新流程图。
          </Text>
          {stat && (
            <div style={{ fontSize: 12, color: '#5e6c84' }}>
              <Tag color="blue">解析结果</Tag>
              <code style={{ fontSize: 12 }}>{stat}</code>
            </div>
          )}
        </Space>
      </Card>

      <Card
        size="small"
        style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
        styles={{ body: { flex: 1, padding: 0, overflow: 'hidden', position: 'relative', display: 'flex', flexDirection: 'column' } }}
        // Tabs 直接放到 Card 上部替代 title；这样不用抢 title 栏空间
        title={
          <Tabs
            size="small"
            activeKey={activeTab}
            onChange={(k) => setActiveTab(k as 'flow' | 'uml')}
            items={[
              { key: 'flow', label: <span><FileTextOutlined /> 流程图</span> },
              { key: 'uml', label: <span><CodeOutlined /> PlantUML 源码</span> },
            ]}
            tabBarStyle={{ margin: 0 }}
          />
        }
        extra={
          activeTab === 'uml' ? (
            <Button
              size="small"
              type="primary"
              icon={<ReloadOutlined />}
              onClick={reRenderFromUml}
              loading={loading}
            >
              重新渲染
            </Button>
          ) : (
            <span style={{ color: '#5e6c84', fontSize: 11 }}>
              Ctrl+滚轮缩放 · 拖节点重排 · 空白拖拽平移
            </span>
          )
        }
      >
        {activeTab === 'flow' ? (
          error ? (
            <pre style={{ color: '#dc2626', fontFamily: 'monospace', whiteSpace: 'pre-wrap',
              background: '#fef2f2', border: '1px solid #fecaca', padding: 10, borderRadius: 8, fontSize: 12, margin: 12,
              maxHeight: '100%', overflow: 'auto' }}>
{error}
            </pre>
          ) : (
            <div
              ref={svgWrapRef}
              onWheel={onWheel}
              onMouseDown={onMouseDown}
              onMouseMove={onMouseMove}
              onMouseUp={onMouseUp}
              onMouseLeave={onMouseUp}
              style={{
                width: '100%', flex: 1,
                background: '#fafbfc',
                overflow: 'hidden',
                cursor: dragRef.current ? 'grabbing' : 'grab',
                position: 'relative',
              }}
            >
              <div ref={flowRef} style={{ display: 'inline-block' }} />

              {loading && (
                <div style={{
                  position: 'absolute', inset: 0, display: 'flex',
                  alignItems: 'center', justifyContent: 'center',
                  background: 'rgba(255,255,255,0.55)',
                }}>
                  <Spin tip="正在向 plantuml.com 请求 SVG…" />
                </div>
              )}

              {/* 左侧悬浮工具条：缩放 / 适配 / 图例 */}
              <div
                onMouseDown={(e) => e.stopPropagation()}
                onWheel={(e) => e.stopPropagation()}
                style={{
                  position: 'absolute',
                  left: 12,
                  top: 12,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 8,
                  padding: 8,
                  background: 'rgba(255,255,255,0.94)',
                  border: '1px solid #e5e7eb',
                  borderRadius: 8,
                  boxShadow: '0 2px 8px rgba(15,23,42,0.06)',
                  zIndex: 10,
                  userSelect: 'none',
                }}
              >
                <Tooltip title="放大" placement="right">
                  <Button size="small" icon={<ZoomInOutlined />}
                    onClick={() => setScale(s => Math.min(4, s * 1.18))} />
                </Tooltip>
                <Tag style={{ margin: 0, minWidth: 44, textAlign: 'center', fontSize: 11 }}>
                  {Math.round(scale * 100)}%
                </Tag>
                <Tooltip title="缩小" placement="right">
                  <Button size="small" icon={<ZoomOutOutlined />}
                    onClick={() => setScale(s => Math.max(0.1, s * 0.85))} />
                </Tooltip>
                <Tooltip title="实际大小" placement="right">
                  <Button size="small" icon={<ExpandOutlined />}
                    onClick={() => { setScale(1); setPan({ x: 0, y: 0 }) }} />
                </Tooltip>
                <Tooltip title="适配窗口" placement="right">
                  <Button size="small" icon={<FullscreenOutlined />} onClick={fitToWindow} />
                </Tooltip>

                <div style={{ height: 1, background: '#e5e7eb', margin: '2px 0' }} />

                <Legend color="#e0f2fe" label="起止" />
                <Legend color="#fef3c7" label="判断" />
                <Legend color="#f1f5f9" label="处理" />
                <Legend color="#fff7ed" label="日志/返回" />
              </div>
            </div>
          )
        ) : (
          // PlantUML 源码编辑面板
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', padding: 12, gap: 8, minHeight: 0 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              PlantUML activity beta 语法。修改后点右上角"<b>重新渲染</b>"或按 <kbd>Ctrl+Enter</kbd> 即可更新流程图。
            </Text>
            <TextArea
              value={uml}
              onChange={(e) => setUml(e.target.value)}
              onKeyDown={(e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                  e.preventDefault()
                  reRenderFromUml()
                }
              }}
              spellCheck={false}
              style={{
                flex: 1,
                fontFamily: '"JetBrains Mono","Fira Code","Consolas",monospace',
                fontSize: 12.5,
                resize: 'none',
              }}
            />
          </div>
        )}
      </Card>
    </div>
  )
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, color: '#5e6c84' }}>
      <i style={{ width: 12, height: 12, borderRadius: 3, display: 'inline-block',
        background: color, border: '1px solid #dfe1e6' }} />
      {label}
    </span>
  )
}
