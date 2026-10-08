/**
 * C++ 函数时序图生成页面
 *
 * 输入两个相关函数：
 *   - 函数 A：发起方；时序图的入口
 *   - 函数 B（可选）：被 A 调用链最终触达的函数；若非空且 A 中有一条调用的方法名
 *     正好等于 B 的方法名，B 的内部调用会在那里"就地展开"
 *
 * 生成链路：C++ 源码 → extractSeqFunction → buildSeqUml → plantUmlToUrl → SVG
 * 复用现有 `/api/plantuml/render` 后端代理和 FlowchartPage 的渲染/缩放/下载组件。
 *
 * 规则识别有局限（见 cppSeqDiagram.ts 顶部注释），用户可以切到「PlantUML 源码」
 * tab 手工微调；后续迭代再加 AI 兜底开关。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Card, Input, Button, Space, Typography, message, Tag, Tooltip, Tabs, Spin } from 'antd'
import {
  ClusterOutlined, ThunderboltOutlined, DownloadOutlined, FileTextOutlined,
  ZoomInOutlined, ZoomOutOutlined, FullscreenOutlined, ExpandOutlined,
  ReloadOutlined, CodeOutlined, FileImageOutlined,
} from '@ant-design/icons'
import { plantUmlToUrl, plantUmlToHexUrl } from '../../utils/cppFlowchart'
import {
  extractSeqFunction, buildSeqUml, SEQ_EXAMPLE_A, SEQ_EXAMPLE_B,
} from '../../utils/cppSeqDiagram'

const { Text } = Typography
const { TextArea } = Input

export default function SeqDiagPage() {
  const [codeA, setCodeA] = useState(SEQ_EXAMPLE_A)
  const [codeB, setCodeB] = useState(SEQ_EXAMPLE_B)
  const [uml, setUml] = useState('')
  const [stat, setStat] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [activeTab, setActiveTab] = useState<'seq' | 'uml'>('seq')

  const canvasRef = useRef<HTMLDivElement>(null)
  const svgWrapRef = useRef<HTMLDivElement>(null)
  const lastSvgRef = useRef('')
  const [scale, setScale] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })

  // 应用缩放 + 平移到 SVG（和 FlowchartPage 一样的策略）
  useEffect(() => {
    const svg = canvasRef.current?.querySelector('svg') as SVGElement | null
    if (!svg) return
    svg.style.transformOrigin = '0 0'
    svg.style.transform = `translate(${pan.x}px, ${pan.y}px) scale(${scale})`
    svg.style.transition = 'transform 0.08s'
  }, [scale, pan])

  const fitToWindow = useCallback(() => {
    const host = svgWrapRef.current
    const svg = canvasRef.current?.querySelector('svg') as SVGSVGElement | null
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

  const renderSvgFromUml = useCallback(async (umlSrc: string) => {
    const host = canvasRef.current
    if (!host) return
    setLoading(true)
    setError('')
    try {
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
      if (!svgText || !svgText.trim().startsWith('<')) {
        throw new Error(
          'plantuml.com 返回空 SVG（很可能是 PlantUML 语法错）。\n' +
          '请切到「PlantUML 源码」标签检查 message label 是否有特殊字符。',
        )
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
      setTimeout(() => { fitToWindow() }, 60)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(
        'PlantUML 渲染失败：\n' + msg +
        '\n\n渲染走「浏览器 → 后端 /api/plantuml/render → plantuml.com」\n' +
        '检查项：\n' +
        '1) 后端是否在跑（默认 http://localhost:8000）\n' +
        '2) 后端所在机器能否访问 https://www.plantuml.com\n' +
        '3) PlantUML 源码是否合法（切到"PlantUML 源码"标签检查）',
      )
    } finally {
      setLoading(false)
    }
  }, [fitToWindow])

  const generate = useCallback(async () => {
    const a = extractSeqFunction(codeA)
    if (!a) {
      setError('函数 A 解析失败：需要形如 `RetType Class::Method(...) { ... }` 的完整定义。')
      setStat(''); setUml('')
      if (canvasRef.current) canvasRef.current.innerHTML = ''
      return
    }
    // B 允许留空；用户只想看 A 内部调用链时直接出 A 的时序图
    const b = codeB.trim() ? extractSeqFunction(codeB) : null
    if (codeB.trim() && !b) {
      setError('函数 B 解析失败：需要形如 `RetType Class::Method(...) { ... }` 的完整定义。\n' +
               '如不需要展开 B，直接把下面「函数 B」文本框清空即可。')
      setStat(''); setUml('')
      return
    }
    try {
      const { uml: newUml, participants, calls } = buildSeqUml(a, b)
      setUml(newUml)
      const bInfo = b ? ` · 展开 ${b.className || ''}::${b.funcName}` : ''
      setStat(`${participants} 参与者 · ${calls} 调用 · 入口 ${a.className || ''}::${a.funcName}${bInfo}`)
      await renderSvgFromUml(newUml)
    } catch (err) {
      setError('生成失败：\n' + (err instanceof Error ? err.message : String(err)))
      setStat('')
    }
  }, [codeA, codeB, renderSvgFromUml])

  const reRenderFromUml = useCallback(() => {
    if (!uml.trim()) { message.warning('PlantUML 源码为空'); return }
    renderSvgFromUml(uml)
  }, [uml, renderSvgFromUml])

  // 首次挂载跑一次，让用户进来就有图看
  useEffect(() => { generate() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const downloadSvg = () => {
    const svgEl = canvasRef.current?.querySelector('svg') as SVGSVGElement | null
    const svgOut = svgEl ? new XMLSerializer().serializeToString(svgEl) : lastSvgRef.current
    if (!svgOut) { message.warning('请先生成时序图'); return }
    const blob = new Blob([svgOut], { type: 'image/svg+xml' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'sequence.svg'
    a.click()
    URL.revokeObjectURL(a.href)
    message.success('已下载 SVG')
  }

  const downloadPng = async (dpi: number = 2) => {
    const svgEl = canvasRef.current?.querySelector('svg') as SVGSVGElement | null
    if (svgEl) {
      try {
        const vb = svgEl.viewBox && svgEl.viewBox.baseVal
        const w = vb && vb.width ? vb.width : parseFloat(svgEl.getAttribute('width') || '800')
        const h = vb && vb.height ? vb.height : parseFloat(svgEl.getAttribute('height') || '600')
        const clone = svgEl.cloneNode(true) as SVGSVGElement
        clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
        clone.setAttribute('xmlns:xlink', 'http://www.w3.org/1999/xlink')
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
            ctx.fillStyle = '#ffffff'
            ctx.fillRect(0, 0, canvas.width, canvas.height)
            ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
            canvas.toBlob(b => b ? resolve(b) : reject(new Error('canvas toBlob 返回空')), 'image/png')
          }
          img.onerror = () => reject(new Error('SVG 转 Image 失败（字体加载被跨域拦截）'))
          img.src = url
        })

        URL.revokeObjectURL(url)
        const a = document.createElement('a')
        a.href = URL.createObjectURL(png)
        a.download = 'sequence.png'
        a.click()
        URL.revokeObjectURL(a.href)
        message.success(`已下载 PNG（${dpi}x 清晰度）`)
        return
      } catch (e) {
        console.warn('本地 SVG→PNG 失败，回退到在线 PNG：', e)
      }
    }

    if (!uml.trim()) { message.warning('请先生成时序图'); return }
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
      a.download = 'sequence.png'
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
    a.download = 'sequence.puml'
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

  // 画布空白拖拽平移（序列图不做节点拖拽：lifeline 的位置由 PlantUML 布局固定，
  // 挪一个 participant 不会重排箭头起点/终点，会错位，YAGNI）
  const dragRef = useRef<{ startX: number; startY: number; panX: number; panY: number } | null>(null)
  const onMouseDown = (e: React.MouseEvent) => {
    dragRef.current = { startX: e.clientX, startY: e.clientY, panX: pan.x, panY: pan.y }
  }
  const onMouseMove = (e: React.MouseEvent) => {
    if (!dragRef.current) return
    const d = dragRef.current
    setPan({ x: d.panX + (e.clientX - d.startX), y: d.panY + (e.clientY - d.startY) })
  }
  const onMouseUp = () => { dragRef.current = null }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(360px, 420px) 1fr', gap: 16, alignItems: 'start', height: 'calc(100vh - 76px)' }}>
      <Card
        title={<><ClusterOutlined style={{ marginRight: 8 }} />函数源码</>}
        size="small"
        style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
        styles={{ body: { flex: 1, overflow: 'auto' } }}
      >
        <Space direction="vertical" style={{ width: '100%' }} size="small">
          <div>
            <Text strong style={{ fontSize: 13 }}>函数 A（入口 / 发起方）</Text>
            <TextArea
              value={codeA}
              onChange={(e) => setCodeA(e.target.value)}
              autoSize={{ minRows: 10, maxRows: 14 }}
              spellCheck={false}
              style={{ fontFamily: '"JetBrains Mono","Fira Code","Consolas",monospace', fontSize: 12.5, marginTop: 4 }}
            />
          </div>
          <div>
            <Text strong style={{ fontSize: 13 }}>函数 B（可选，被 A 调用）</Text>
            <TextArea
              value={codeB}
              onChange={(e) => setCodeB(e.target.value)}
              autoSize={{ minRows: 8, maxRows: 12 }}
              spellCheck={false}
              placeholder="函数 B 可留空；留空时只画 A 的调用序列"
              style={{ fontFamily: '"JetBrains Mono","Fira Code","Consolas",monospace', fontSize: 12.5, marginTop: 4 }}
            />
          </div>
          <Space wrap>
            <Button type="primary" icon={<ThunderboltOutlined />} onClick={generate} loading={loading}>
              生成时序图
            </Button>
            <Button icon={<FileTextOutlined />} onClick={() => {
              setCodeA(SEQ_EXAMPLE_A); setCodeB(SEQ_EXAMPLE_B); setTimeout(generate, 0)
            }}>
              载入示例
            </Button>
            <Button icon={<DownloadOutlined />} onClick={downloadSvg}>下载 SVG</Button>
            <Button icon={<FileImageOutlined />} onClick={() => downloadPng(2)}>下载 PNG</Button>
            <Button icon={<CodeOutlined />} onClick={downloadUml}>下载 PUML</Button>
          </Space>
          <Text type="secondary" style={{ fontSize: 12 }}>
            识别规则：函数签名提取类名；函数体顶层扫描 <code>obj-&gt;method()</code> /{' '}
            <code>Class::method()</code> / <code>method()</code>（自调用）；
            通过局部变量声明把 <code>obj</code> 的 lifeline 还原成类型名。
          </Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            参数里嵌套的调用（如 <code>X(f())</code> 的 f）、虚函数真实实现、宏展开后的调用不展开。
            识别有偏差时可切「PlantUML 源码」tab 手工微调，按 <kbd>Ctrl+Enter</kbd> 重渲染。
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
        title={
          <Tabs
            size="small"
            activeKey={activeTab}
            onChange={(k) => setActiveTab(k as 'seq' | 'uml')}
            items={[
              { key: 'seq', label: <span><ClusterOutlined /> 时序图</span> },
              { key: 'uml', label: <span><CodeOutlined /> PlantUML 源码</span> },
            ]}
            tabBarStyle={{ margin: 0 }}
          />
        }
        extra={
          activeTab === 'uml' ? (
            <Button size="small" type="primary" icon={<ReloadOutlined />} onClick={reRenderFromUml} loading={loading}>
              重新渲染
            </Button>
          ) : (
            <span style={{ color: '#5e6c84', fontSize: 11 }}>
              Ctrl+滚轮缩放 · 空白拖拽平移
            </span>
          )
        }
      >
        {activeTab === 'seq' ? (
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
              <div ref={canvasRef} style={{ display: 'inline-block' }} />

              {loading && (
                <div style={{
                  position: 'absolute', inset: 0, display: 'flex',
                  alignItems: 'center', justifyContent: 'center',
                  background: 'rgba(255,255,255,0.55)',
                }}>
                  <Spin tip="正在向 plantuml.com 请求 SVG…" />
                </div>
              )}

              {/* 左侧悬浮工具条 */}
              <div
                onMouseDown={(e) => e.stopPropagation()}
                onWheel={(e) => e.stopPropagation()}
                style={{
                  position: 'absolute',
                  left: 12, top: 12,
                  display: 'flex', flexDirection: 'column', gap: 8, padding: 8,
                  background: 'rgba(255,255,255,0.94)',
                  border: '1px solid #e5e7eb', borderRadius: 8,
                  boxShadow: '0 2px 8px rgba(15,23,42,0.06)',
                  zIndex: 10, userSelect: 'none',
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
              </div>
            </div>
          )
        ) : (
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', padding: 12, gap: 8, minHeight: 0 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              PlantUML sequence 语法。修改后点右上角「<b>重新渲染</b>」或按 <kbd>Ctrl+Enter</kbd> 即可更新时序图。
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
