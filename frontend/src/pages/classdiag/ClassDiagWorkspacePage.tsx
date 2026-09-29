/**
 * 类图分析 — 项目工作区。
 *
 * 左列：源码 zip 上传、include zips 追加、类名输入、options、生成按钮、状态标签
 * 右列：Tabs [类图 SVG / PlantUML 源码 / 匹配的头文件]，SVG 支持 zoom/pan/下载
 *
 * SVG 拉取 / zoom / pan / 下载 逻辑从 FlowchartPage 复制过来，
 * 不做抽取（YAGNI；类图 vs 流程图后续如果差异变大再重构）。
 * 类图不支持节点拖拽 —— PlantUML 类图连线走 Graphviz 布局，拖节点会导致连线错位。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Alert,
  AutoComplete,
  Button,
  Card,
  Checkbox,
  Divider,
  Input,
  InputNumber,
  List,
  message,
  Modal,
  Progress,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Upload,
} from 'antd'
import type { UploadFile } from 'antd'
import type { AxiosError } from 'axios'
import {
  ArrowLeftOutlined,
  DeleteOutlined,
  DownloadOutlined,
  FileZipOutlined,
  FullscreenOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
  ZoomInOutlined,
  ZoomOutOutlined,
} from '@ant-design/icons'
import { plantUmlToUrl, plantUmlToHexUrl } from '../../utils/cppFlowchart'
import {
  deleteInclude,
  generateClassDiagram,
  getClassDiagProject,
  listProjectHeaders,
  uploadIncludeZip,
  uploadSourceZip,
} from '../../api/classDiagApi'
import type {
  ClassDiagOptions,
  ClassDiagProject,
  MultiMatchCandidate,
  MultiMatchError,
} from '../../types/classDiag'

const DEFAULT_OPTIONS: ClassDiagOptions = {
  show_private: true,
  show_protected: true,
  show_static: true,
}

export default function ClassDiagWorkspacePage() {
  const { projectId = '' } = useParams<{ projectId: string }>()
  const navigate = useNavigate()

  // ---- 项目数据 ----
  const [project, setProject] = useState<ClassDiagProject | null>(null)
  const [projectLoading, setProjectLoading] = useState(false)

  // ---- 上传状态 ----
  const [sourceUploading, setSourceUploading] = useState(false)
  const [sourcePercent, setSourcePercent] = useState(0)
  const [includeName, setIncludeName] = useState('')
  const [includeUploading, setIncludeUploading] = useState(false)
  const [includePercent, setIncludePercent] = useState(0)
  const includeFileList = useRef<UploadFile[]>([])

  // ---- 查询 ----
  const [className, setClassName] = useState('')
  const [options, setOptions] = useState<ClassDiagOptions>(DEFAULT_OPTIONS)
  // 向上追踪的继承层数。默认 2（父类 + 祖父类），后端会 clamp 到 1..10
  const [depth, setDepth] = useState<number>(2)
  const [generating, setGenerating] = useState(false)
  const [uml, setUml] = useState('')
  const [umlDirty, setUmlDirty] = useState('')  // 用户在源码 Tab 手改后的版本
  const [matchedHeaders, setMatchedHeaders] = useState<string[]>([])
  const [clangStatus, setClangStatus] =
    useState<'unavailable' | 'ok' | 'partial' | 'error' | ''>('')
  const [renderError, setRenderError] = useState('')

  // ---- 多命中冲突 ----
  const [conflictOpen, setConflictOpen] = useState(false)
  const [conflictCandidates, setConflictCandidates] = useState<MultiMatchCandidate[]>([])

  // ---- 类名输入框的头文件 hints（辅助用户找到类所在文件）----
  const [headerHints, setHeaderHints] = useState<{ value: string; label: string }[]>([])
  const headerFetchSeq = useRef(0)

  // ---- SVG 画布 ----
  const flowRef = useRef<HTMLDivElement | null>(null)
  const svgWrapRef = useRef<HTMLDivElement | null>(null)
  const lastSvgRef = useRef<string>('')
  const [scale, setScale] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [rendering, setRendering] = useState(false)
  const [activeTab, setActiveTab] = useState('diagram')

  // ---- 拉项目 ----
  const fetchProject = useCallback(async () => {
    if (!projectId) return
    setProjectLoading(true)
    try {
      const res = await getClassDiagProject(projectId)
      setProject(res.data)
      // 恢复上次查询
      if (res.data.last_query) {
        const lq = res.data.last_query
        setClassName(lq.class_name)
        setOptions({ ...DEFAULT_OPTIONS, ...(lq.options || {}) })
        // last_query.depth 是 Commit 后加的字段，老项目 undefined 时回落到默认 2
        if (typeof lq.depth === 'number' && lq.depth >= 1) {
          setDepth(Math.min(10, Math.max(1, Math.round(lq.depth))))
        }
        setUml(lq.uml)
        setUmlDirty(lq.uml)
        setMatchedHeaders(lq.matched_headers || [])
        setClangStatus(lq.clang_status)
      }
    } catch {
      message.error('加载项目失败')
    } finally {
      setProjectLoading(false)
    }
  }, [projectId])

  useEffect(() => { fetchProject() }, [fetchProject])

  // ---- 上传源码 zip ----
  const beforeSourceUpload = (file: File) => {
    if (!file.name.toLowerCase().endsWith('.zip')) {
      message.error('仅支持 zip 文件')
      return Upload.LIST_IGNORE
    }
    handleSourceUpload(file)
    return false   // 阻止 antd 自动上传，我们走自己的 axios
  }
  const handleSourceUpload = async (file: File) => {
    if (!projectId) return
    setSourceUploading(true)
    setSourcePercent(0)
    try {
      await uploadSourceZip(projectId, file, setSourcePercent)
      message.success(`源码 zip 上传解压完成：${file.name}`)
      fetchProject()
    } catch (e) {
      const err = e as AxiosError<{ detail: string }>
      message.error('上传失败：' + (err.response?.data?.detail || err.message))
    } finally {
      setSourceUploading(false)
      setSourcePercent(0)
    }
  }

  // ---- 追加 include zip ----
  const beforeIncludeUpload = (file: File) => {
    if (!file.name.toLowerCase().endsWith('.zip')) {
      message.error('仅支持 zip 文件')
      return Upload.LIST_IGNORE
    }
    const raw = includeName.trim()
    if (!raw) {
      message.warning('请先在上方"Include 名称"输入一个名字')
      return Upload.LIST_IGNORE
    }
    handleIncludeUpload(raw, file)
    return false
  }
  const handleIncludeUpload = async (name: string, file: File) => {
    if (!projectId) return
    setIncludeUploading(true)
    setIncludePercent(0)
    try {
      await uploadIncludeZip(projectId, name, file, setIncludePercent)
      message.success(`Include "${name}" 上传解压完成`)
      setIncludeName('')
      includeFileList.current = []
      fetchProject()
    } catch (e) {
      const err = e as AxiosError<{ detail: string }>
      message.error('上传失败：' + (err.response?.data?.detail || err.message))
    } finally {
      setIncludeUploading(false)
      setIncludePercent(0)
    }
  }

  const handleIncludeDelete = async (name: string) => {
    if (!projectId) return
    try {
      await deleteInclude(projectId, name)
      message.success(`已删除 include "${name}"`)
      fetchProject()
    } catch (e) {
      const err = e as AxiosError<{ detail: string }>
      message.error('删除失败：' + (err.response?.data?.detail || err.message))
    }
  }

  // ---- 头文件搜索（AutoComplete 数据源）----
  // 用户在类名框里输入时，按当前 token 的短名段做搜索；
  // 返回候选头文件路径，label 用短名 + 相对路径，value 保留用户已有前缀
  // （比如输入 "ns::Foo"，只用 "Foo" 触发搜索，选中后把 "Foo" 部分替换成候选短名）
  const fetchHeaderHints = useCallback(async (input: string) => {
    if (!projectId) return
    const raw = (input || '').trim()
    // 取最后一段做搜索 token（用户输 `ns::Sub::Foo`，搜 `Foo`）
    const lastSeg = raw.split('::').pop() || ''
    if (lastSeg.length < 2) {
      setHeaderHints([])
      return
    }
    const seq = ++headerFetchSeq.current
    try {
      const res = await listProjectHeaders(projectId, lastSeg, 20)
      // 忽略过期请求
      if (seq !== headerFetchSeq.current) return
      const prefix = raw.slice(0, raw.length - lastSeg.length)  // "ns::Sub::"
      const opts = res.data.items.map((path) => {
        const base = path.split('/').pop() || path
        const short = base.replace(/\.(hpp|hxx|hh|h)$/i, '')
        return { value: prefix + short, label: `${short}  —  ${path}` }
      })
      setHeaderHints(opts)
    } catch {
      // 搜索失败静默，别打扰用户
      setHeaderHints([])
    }
  }, [projectId])

  // ---- 生成类图（两阶段：regex 秒出 → clang 后台增强热更） ----
  const [clangEnriching, setClangEnriching] = useState(false)

  const handleGenerate = useCallback(async (nameOverride?: string) => {
    const q = (nameOverride ?? className).trim()
    if (!q) { message.warning('请输入类名'); return }
    if (!projectId) return
    if (!project?.source_zip_name) { message.warning('请先上传主源码 zip'); return }

    setGenerating(true)
    setRenderError('')
    try {
      // 第一发：只跑正则，秒出粗图
      const res = await generateClassDiagram(projectId, {
        class_name: q,
        stage: 'regex',
        options,
        depth,
      })
      setUml(res.data.uml)
      setUmlDirty(res.data.uml)
      setMatchedHeaders(res.data.matched_headers || [])
      setClangStatus(res.data.clang_status)
      await renderSvgFromUml(res.data.uml)

      // 第二发：若后端提示 clang 可用，后台再发一发拿增强结果，热更画布
      if (res.data.next_stage === 'clang') {
        setClangEnriching(true)
        // 用解析后的 qualified_name 精确重跑，避免 clang 再次遇到多命中
        const enrichName = res.data.resolved_qualified_name || q
        generateClassDiagram(projectId, {
          class_name: enrichName,
          stage: 'clang',
          options,
          depth,
        }).then(async (res2) => {
          setUml(res2.data.uml)
          setUmlDirty(res2.data.uml)
          setMatchedHeaders(res2.data.matched_headers || [])
          setClangStatus(res2.data.clang_status)
          await renderSvgFromUml(res2.data.uml)
        }).catch((e2) => {
          // 增强失败不影响正则结果，只提示一下
          const err = e2 as AxiosError<{ detail?: string }>
          const detail = err.response?.data?.detail || err.message
          message.warning('clang 增强失败，仅使用正则结果：' + detail)
        }).finally(() => {
          setClangEnriching(false)
        })
      }
    } catch (e) {
      const err = e as AxiosError<MultiMatchError | { detail: string }>
      if (err.response?.status === 409) {
        const body = err.response.data as MultiMatchError
        setConflictCandidates(body.matches || [])
        setConflictOpen(true)
      } else if (err.response?.status === 404) {
        message.error(`未找到类：${q}`)
      } else {
        const detail = (err.response?.data as { detail?: string })?.detail || err.message
        message.error('生成失败：' + detail)
      }
    } finally {
      setGenerating(false)
    }
    // renderSvgFromUml/options 引用会被 hook 稳定化，避免每次 render 重建整个函数
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [className, projectId, project?.source_zip_name, options, depth])

  // ---- SVG 渲染 ----
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

  useEffect(() => {
    const svg = flowRef.current?.querySelector('svg') as SVGSVGElement | null
    if (!svg) return
    svg.style.transformOrigin = 'top left'
    svg.style.transform = `translate(${pan.x}px, ${pan.y}px) scale(${scale})`
    svg.style.transition = 'transform 0.08s'
  }, [scale, pan])

  const renderSvgFromUml = useCallback(async (umlSrc: string) => {
    const host = flowRef.current
    if (!host) return
    setRendering(true)
    setRenderError('')
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
      setTimeout(() => fitToWindow(), 60)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setRenderError('PlantUML 在线渲染失败：\n' + msg +
        '\n\n检查项：\n' +
        '1) 网络能否访问 https://www.plantuml.com\n' +
        '2) PlantUML 源码是否合法（切到"PlantUML 源码"标签检查）')
    } finally {
      setRendering(false)
    }
  }, [fitToWindow])

  // 首次拿到 uml（从上次查询恢复出来）后渲一遍
  useEffect(() => {
    if (uml && activeTab === 'diagram') {
      renderSvgFromUml(uml)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uml])

  const reRenderFromUml = () => {
    if (!umlDirty.trim()) { message.warning('PlantUML 源码为空'); return }
    setUml(umlDirty)
    renderSvgFromUml(umlDirty)
    setActiveTab('diagram')
  }

  // ---- 下载 ----
  const downloadSvg = () => {
    const svgEl = flowRef.current?.querySelector('svg') as SVGSVGElement | null
    const svgOut = svgEl ? new XMLSerializer().serializeToString(svgEl) : lastSvgRef.current
    if (!svgOut) { message.warning('请先生成类图'); return }
    const blob = new Blob([svgOut], { type: 'image/svg+xml' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${className || 'classdiag'}.svg`
    a.click()
    URL.revokeObjectURL(a.href)
    message.success('已下载 SVG')
  }

  const downloadPng = async (dpi: number = 2) => {
    const svgEl = flowRef.current?.querySelector('svg') as SVGSVGElement | null
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
          img.onerror = () => reject(new Error('SVG 转 Image 失败'))
          img.src = url
        })
        URL.revokeObjectURL(url)
        const a = document.createElement('a')
        a.href = URL.createObjectURL(png)
        a.download = `${className || 'classdiag'}.png`
        a.click()
        URL.revokeObjectURL(a.href)
        message.success(`已下载 PNG（${dpi}x）`)
        return
      } catch (e) {
        console.warn('本地 SVG→PNG 失败，回退在线：', e)
      }
    }
    if (!uml.trim()) { message.warning('请先生成类图'); return }
    try {
      let blob: Blob
      try {
        const pngUrl = plantUmlToUrl(uml, 'png')
        const resp = await fetch(pngUrl)
        if (!resp.ok) throw new Error(`plantuml.com 返回 HTTP ${resp.status}`)
        blob = await resp.blob()
      } catch {
        const pngUrl = plantUmlToHexUrl(uml, 'png')
        const resp = await fetch(pngUrl)
        if (!resp.ok) throw new Error(`plantuml.com 返回 HTTP ${resp.status}`)
        blob = await resp.blob()
      }
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `${className || 'classdiag'}.png`
      a.click()
      URL.revokeObjectURL(a.href)
      message.success('已下载 PNG（在线）')
    } catch (e) {
      message.error('下载 PNG 失败：' + (e instanceof Error ? e.message : String(e)))
    }
  }

  const downloadPuml = () => {
    if (!uml.trim()) { message.warning('PlantUML 源码为空'); return }
    const blob = new Blob([uml], { type: 'text/plain; charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${className || 'classdiag'}.puml`
    a.click()
    URL.revokeObjectURL(a.href)
    message.success('已下载 PlantUML 源码')
  }

  // ---- 缩放 / 平移 ----
  const onWheel = (e: React.WheelEvent) => {
    if (!e.ctrlKey && !e.metaKey) return
    e.preventDefault()
    const delta = e.deltaY < 0 ? 1.1 : 0.9
    setScale(s => Math.max(0.1, Math.min(4, s * delta)))
  }
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

  // ---- 冲突弹层：点候选自动填回 Input + 重跑 ----
  const pickCandidate = (c: MultiMatchCandidate) => {
    setClassName(c.qualified_name)
    setConflictOpen(false)
    handleGenerate(c.qualified_name)
  }

  // ---- 渲染 ----
  const clangTag = (() => {
    if (!clangStatus) return null
    if (clangStatus === 'ok') return <Tag color="success">clang: ok</Tag>
    if (clangStatus === 'partial') return <Tag color="warning">clang: partial</Tag>
    if (clangStatus === 'error') return <Tag color="error">clang: error</Tag>
    return <Tag>clang: unavailable</Tag>
  })()

  return (
    <Spin spinning={projectLoading}>
      <div style={{ padding: 16, height: 'calc(100vh - 64px)',
                    display: 'flex', flexDirection: 'column' }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
          <Button icon={<ArrowLeftOutlined />}
                   onClick={() => navigate('/classdiag/projects')}
                   style={{ marginRight: 12 }}>
            返回项目列表
          </Button>
          <h3 style={{ margin: 0 }}>
            {project?.name || '类图工作区'}
          </h3>
          {project?.source_zip_name && (
            <Tag color="blue" style={{ marginLeft: 12 }}>
              <FileZipOutlined /> {project.source_zip_name}
            </Tag>
          )}
        </div>

        <div style={{ display: 'flex', flex: 1, gap: 12, minHeight: 0 }}>
          {/* 左列 */}
          <Card size="small" style={{ width: 380, overflow: 'auto' }} title="配置">
            {/* 源码 zip */}
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontWeight: 500, marginBottom: 6 }}>1. 主源码 zip</div>
              <Upload beforeUpload={beforeSourceUpload}
                       maxCount={1}
                       showUploadList={false}
                       disabled={sourceUploading}>
                <Button icon={<PlusOutlined />} loading={sourceUploading}
                         block>
                  {project?.source_zip_name ? '重新上传源码 zip' : '选择源码 zip'}
                </Button>
              </Upload>
              {sourceUploading && (
                <Progress percent={sourcePercent} size="small" style={{ marginTop: 6 }} />
              )}
              {project?.source_summary?.file_count !== undefined && (
                <div style={{ marginTop: 6, color: '#888', fontSize: 12 }}>
                  已解压 {project.source_summary.file_count} 个文件
                  {project.source_summary.top_dirs?.length
                    ? `，顶层目录：${project.source_summary.top_dirs.slice(0, 3).join(' / ')}`
                    : ''}
                </div>
              )}
            </div>

            <Divider style={{ margin: '12px 0' }} />

            {/* Include zips */}
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontWeight: 500, marginBottom: 6 }}>2. Include 依赖包（可多个）</div>
              <Input value={includeName}
                      onChange={(e) => setIncludeName(e.target.value)}
                      placeholder="Include 名称（如 nvidia_headers）"
                      style={{ marginBottom: 6 }}
                      disabled={includeUploading} />
              <Upload beforeUpload={beforeIncludeUpload}
                       maxCount={1}
                       showUploadList={false}
                       disabled={includeUploading}>
                <Button icon={<PlusOutlined />} loading={includeUploading}
                         block>
                  上传 Include zip
                </Button>
              </Upload>
              {includeUploading && (
                <Progress percent={includePercent} size="small" style={{ marginTop: 6 }} />
              )}
              <List size="small"
                     bordered
                     style={{ marginTop: 8 }}
                     dataSource={project?.include_dirs || []}
                     locale={{ emptyText: '暂无 include 包' }}
                     renderItem={item => (
                       <List.Item actions={[
                         <Tooltip title="删除" key="del">
                           <Button type="text" danger size="small"
                                    icon={<DeleteOutlined />}
                                    onClick={() => handleIncludeDelete(item.name)} />
                         </Tooltip>
                       ]}>
                         <span style={{ fontWeight: 500 }}>{item.name}</span>
                         {item.summary?.file_count !== undefined && (
                           <span style={{ color: '#888', marginLeft: 8, fontSize: 12 }}>
                             {item.summary.file_count} 文件
                           </span>
                         )}
                       </List.Item>
                     )} />
            </div>

            <Divider style={{ margin: '12px 0' }} />

            {/* 查询 */}
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontWeight: 500, marginBottom: 6 }}>3. 类查询</div>
              <AutoComplete
                value={className}
                options={headerHints}
                onChange={(v) => { setClassName(v); fetchHeaderHints(v) }}
                onSelect={(v) => setClassName(v)}
                onFocus={() => fetchHeaderHints(className)}
                disabled={generating || !project?.source_zip_name}
                popupMatchSelectWidth={360}
                style={{ width: '100%' }}
              >
                <Input placeholder="输入全限定名，如 ns::Sub::Foo"
                        onPressEnter={() => handleGenerate()}
                        allowClear />
              </AutoComplete>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12 }}>
                <span style={{ color: 'rgba(0,0,0,0.65)', fontSize: 13 }}>
                  <Tooltip title="向上追踪几层父类。1 = 只画直接父类；2 = 加上祖父类；以此类推。范围 1-10。">
                    继承深度
                  </Tooltip>
                </span>
                <InputNumber
                  min={1}
                  max={10}
                  value={depth}
                  onChange={(v) => setDepth(typeof v === 'number' ? v : 2)}
                  disabled={generating}
                  size="small"
                  style={{ width: 80 }}
                />
                <span style={{ color: 'rgba(0,0,0,0.45)', fontSize: 12 }}>
                  层（默认 2）
                </span>
              </div>
              <Checkbox.Group
                value={Object.entries(options).filter(([, v]) => v).map(([k]) => k)}
                onChange={(vals) => {
                  const set = new Set(vals as string[])
                  setOptions({
                    show_private: set.has('show_private'),
                    show_protected: set.has('show_protected'),
                    show_static: set.has('show_static'),
                  })
                }}
                style={{ display: 'flex', flexDirection: 'column', marginTop: 8 }}
              >
                <Checkbox value="show_private">显示 private 成员</Checkbox>
                <Checkbox value="show_protected">显示 protected 成员</Checkbox>
                <Checkbox value="show_static">显示 static 成员</Checkbox>
              </Checkbox.Group>
              <Button type="primary"
                       icon={<PlayCircleOutlined />}
                       block
                       style={{ marginTop: 10 }}
                       loading={generating}
                       onClick={() => handleGenerate()}
                       disabled={!project?.source_zip_name}>
                生成类图
              </Button>
            </div>

            {/* 状态标签 */}
            {(clangTag || clangEnriching) && (
              <div style={{ marginTop: 8 }}>
                <Space size={6} wrap>
                  <Tag color="processing">正则已完成</Tag>
                  {clangEnriching
                    ? <Tag color="processing" icon={<ReloadOutlined spin />}>clang 增强中…</Tag>
                    : clangTag}
                </Space>
              </div>
            )}
          </Card>

          {/* 右列 */}
          <Card size="small" style={{ flex: 1, display: 'flex', flexDirection: 'column',
                                        minWidth: 0 }}
                bodyStyle={{ flex: 1, display: 'flex', flexDirection: 'column',
                              padding: 8, minHeight: 0 }}>
            <Tabs activeKey={activeTab} onChange={setActiveTab}
                   style={{ flex: 1, display: 'flex', flexDirection: 'column',
                            minHeight: 0 }}
                   items={[
                     {
                       key: 'diagram',
                       label: '类图',
                       children: (
                         <div style={{ position: 'relative', flex: 1, height: '100%',
                                        minHeight: 400 }}>
                           {/* 左侧浮动工具栏 */}
                           <div style={{ position: 'absolute', top: 8, left: 8, zIndex: 10,
                                          display: 'flex', flexDirection: 'column', gap: 6 }}>
                             <Tooltip title="放大" placement="right">
                               <Button size="small" icon={<ZoomInOutlined />}
                                        onClick={() => setScale(s => Math.min(4, s * 1.15))} />
                             </Tooltip>
                             <Tooltip title="缩小" placement="right">
                               <Button size="small" icon={<ZoomOutOutlined />}
                                        onClick={() => setScale(s => Math.max(0.1, s / 1.15))} />
                             </Tooltip>
                             <Tooltip title="适应窗口" placement="right">
                               <Button size="small" icon={<FullscreenOutlined />}
                                        onClick={fitToWindow} />
                             </Tooltip>
                             <Divider style={{ margin: '2px 0' }} />
                             <Tooltip title="下载 SVG" placement="right">
                               <Button size="small" icon={<DownloadOutlined />}
                                        onClick={downloadSvg}>SVG</Button>
                             </Tooltip>
                             <Tooltip title="下载 PNG" placement="right">
                               <Button size="small" icon={<DownloadOutlined />}
                                        onClick={() => downloadPng(2)}>PNG</Button>
                             </Tooltip>
                             <Tooltip title="下载 PlantUML 源码" placement="right">
                               <Button size="small" icon={<DownloadOutlined />}
                                        onClick={downloadPuml}>PUML</Button>
                             </Tooltip>
                           </div>
                           <div ref={svgWrapRef}
                                 style={{ width: '100%', height: '100%',
                                          background: '#fafafa', border: '1px solid #eee',
                                          overflow: 'hidden', position: 'relative',
                                          cursor: dragRef.current ? 'grabbing' : 'grab' }}
                                 onWheel={onWheel}
                                 onMouseDown={onMouseDown}
                                 onMouseMove={onMouseMove}
                                 onMouseUp={onMouseUp}
                                 onMouseLeave={onMouseUp}>
                             <Spin spinning={rendering}>
                               <div ref={flowRef} />
                             </Spin>
                           </div>
                           {renderError && (
                             <Alert type="error" showIcon
                                     message="渲染失败"
                                     description={<pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{renderError}</pre>}
                                     style={{ marginTop: 8 }} />
                           )}
                           {!uml && !rendering && (
                             <div style={{ position: 'absolute', top: '50%', left: '50%',
                                            transform: 'translate(-50%,-50%)', color: '#bbb' }}>
                               请在左侧输入类名并点击"生成类图"
                             </div>
                           )}
                         </div>
                       ),
                     },
                     {
                       key: 'source',
                       label: 'PlantUML 源码',
                       children: (
                         <div style={{ display: 'flex', flexDirection: 'column',
                                        height: '100%', minHeight: 400 }}>
                           <Input.TextArea value={umlDirty}
                                            onChange={(e) => setUmlDirty(e.target.value)}
                                            onKeyDown={(e) => {
                                              if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                                                e.preventDefault()
                                                reRenderFromUml()
                                              }
                                            }}
                                            style={{ flex: 1, fontFamily: 'monospace', fontSize: 12 }}
                                            placeholder="尚未生成任何 PlantUML 源码" />
                           <div style={{ marginTop: 6, textAlign: 'right' }}>
                             <Space>
                               <span style={{ color: '#888', fontSize: 12 }}>
                                 Ctrl+Enter 重渲染
                               </span>
                               <Button size="small" icon={<ReloadOutlined />}
                                        onClick={reRenderFromUml}>重新渲染</Button>
                             </Space>
                           </div>
                         </div>
                       ),
                     },
                     {
                       key: 'headers',
                       label: `匹配的头文件 (${matchedHeaders.length})`,
                       children: (
                         <Table size="small"
                                 rowKey={(r) => r}
                                 dataSource={matchedHeaders}
                                 pagination={false}
                                 locale={{ emptyText: '尚未匹配到任何头文件' }}
                                 columns={[
                                   { title: '相对路径', dataIndex: undefined,
                                     render: (_, p) => <code>{p}</code> },
                                 ]} />
                       ),
                     },
                   ]} />
          </Card>
        </div>

        {/* 冲突弹层：多命中时让用户改用全限定名 */}
        <Modal open={conflictOpen}
                title={`存在 ${conflictCandidates.length} 个同名符号`}
                onCancel={() => setConflictOpen(false)}
                footer={<Button onClick={() => setConflictOpen(false)}>关闭</Button>}
                width={780}>
          <Alert type="warning" showIcon style={{ marginBottom: 12 }}
                  message="点击某一行的全限定名即可自动填回类名框并重新生成。" />
          <Table size="small"
                  rowKey={(r) => r.qualified_name + r.file + r.line}
                  dataSource={conflictCandidates}
                  pagination={false}
                  columns={[
                    { title: '全限定名', dataIndex: 'qualified_name',
                      render: (v, r) => <a onClick={() => pickCandidate(r)}>{v}</a> },
                    { title: '文件', dataIndex: 'file',
                      ellipsis: true,
                      render: (v: string) => <span style={{ color: '#666' }}>{v}</span> },
                    { title: '行', dataIndex: 'line', width: 60, align: 'right' as const },
                    { title: '类型', dataIndex: 'kind', width: 80,
                      render: (v: string) => {
                        const color = v === 'class' ? 'blue'
                                    : v === 'struct' ? 'purple'
                                    : v === 'interface' ? 'green' : undefined
                        return <Tag color={color}>{v}</Tag>
                      } },
                  ]} />
        </Modal>
      </div>
    </Spin>
  )
}
