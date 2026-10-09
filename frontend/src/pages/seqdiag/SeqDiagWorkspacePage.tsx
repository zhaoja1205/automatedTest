/**
 * 函数时序图 — 项目工作区。
 *
 * 左列：源码 zip 上传、include zips 追加、函数 A / 函数 B 输入、生成按钮
 * 右列：Tabs [时序图 SVG / PlantUML 源码 / 匹配的文件]，SVG 支持 zoom/pan/下载
 *
 * SVG 渲染逻辑与 ClassDiagWorkspacePage 保持一致（从 FlowchartPage 继承）。
 * 时序图无 clang 增强，故只有一次生成调用，无两阶段热更。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Alert,
  Button,
  Card,
  Divider,
  Input,
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
  generateSeqDiagram,
  getSeqDiagProject,
  uploadIncludeZip,
  uploadSourceZip,
} from '../../api/seqDiagApi'
import type {
  SeqDiagProject,
  MultiMatchCandidate,
  MultiMatchError,
} from '../../types/seqDiag'

export default function SeqDiagWorkspacePage() {
  const { projectId = '' } = useParams<{ projectId: string }>()
  const navigate = useNavigate()

  // ---- 项目数据 ----
  const [project, setProject] = useState<SeqDiagProject | null>(null)
  const [projectLoading, setProjectLoading] = useState(false)

  // ---- 上传状态 ----
  const [sourceUploading, setSourceUploading] = useState(false)
  const [sourcePercent, setSourcePercent] = useState(0)
  const [includeName, setIncludeName] = useState('')
  const [includeUploading, setIncludeUploading] = useState(false)
  const [includePercent, setIncludePercent] = useState(0)
  const includeFileList = useRef<UploadFile[]>([])

  // ---- 查询 ----
  const [funcAName, setFuncAName] = useState('')
  const [funcBName, setFuncBName] = useState('')
  const [generating, setGenerating] = useState(false)
  const [uml, setUml] = useState('')
  const [umlDirty, setUmlDirty] = useState('')
  const [matchedFiles, setMatchedFiles] = useState<string[]>([])
  const [renderError, setRenderError] = useState('')

  // ---- 多命中冲突 ----
  const [conflictOpen, setConflictOpen] = useState(false)
  const [conflictCandidates, setConflictCandidates] = useState<MultiMatchCandidate[]>([])
  const [conflictWhich, setConflictWhich] = useState<'A' | 'B'>('A')

  // ---- SVG 画布 ----
  const flowRef = useRef<HTMLDivElement | null>(null)
  const svgWrapRef = useRef<HTMLDivElement | null>(null)
  const lastSvgRef = useRef<string>('')
  const [scale, setScale] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [rendering, setRendering] = useState(false)
  const [activeTab, setActiveTab] = useState('diagram')
  const dragRef = useRef(false)
  const lastPosRef = useRef({ x: 0, y: 0 })

  // ---- 拉项目 ----
  const fetchProject = useCallback(async () => {
    if (!projectId) return
    setProjectLoading(true)
    try {
      const res = await getSeqDiagProject(projectId)
      setProject(res.data)
      if (res.data.last_query) {
        const lq = res.data.last_query
        setFuncAName(lq.func_a_name || '')
        setFuncBName(lq.func_b_name || '')
        setUml(lq.uml)
        setUmlDirty(lq.uml)
        setMatchedFiles(lq.matched_files || [])
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
    return false
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

  // ---- SVG fit/pan/zoom ----
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

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault()
    const delta = e.deltaY < 0 ? 1.1 : 0.9
    setScale((s) => Math.max(0.05, Math.min(10, s * delta)))
  }
  const onMouseDown = (e: React.MouseEvent) => {
    dragRef.current = true
    lastPosRef.current = { x: e.clientX, y: e.clientY }
  }
  const onMouseMove = (e: React.MouseEvent) => {
    if (!dragRef.current) return
    const dx = e.clientX - lastPosRef.current.x
    const dy = e.clientY - lastPosRef.current.y
    lastPosRef.current = { x: e.clientX, y: e.clientY }
    setPan((p) => ({ x: p.x + dx, y: p.y + dy }))
  }
  const onMouseUp = () => { dragRef.current = false }

  // ---- SVG 渲染 ----
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
      setRenderError('PlantUML 渲染失败：\n' + msg +
        '\n\n渲染走「浏览器 → 后端 /api/plantuml/render → plantuml.com」\n' +
        '检查项：\n' +
        '1) 后端是否在跑\n' +
        '2) 后端所在机器能否访问 https://www.plantuml.com\n' +
        '3) PlantUML 源码是否合法（切到"PlantUML 源码"标签检查）')
    } finally {
      setRendering(false)
    }
  }, [fitToWindow])

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

  // ---- 生成时序图 ----
  const handleGenerate = useCallback(async (aOverride?: string, bOverride?: string) => {
    const qa = (aOverride ?? funcAName).trim()
    if (!qa) { message.warning('请输入函数 A 的全限定名'); return }
    if (!projectId) return
    if (!project?.source_zip_name) { message.warning('请先上传主源码 zip'); return }
    const qb = (bOverride ?? funcBName).trim()

    setGenerating(true)
    setRenderError('')
    try {
      const res = await generateSeqDiagram(projectId, {
        func_a_name: qa,
        func_b_name: qb || undefined,
      })
      setUml(res.data.uml)
      setUmlDirty(res.data.uml)
      setMatchedFiles(res.data.matched_files || [])
      await renderSvgFromUml(res.data.uml)
    } catch (e) {
      const err = e as AxiosError<MultiMatchError | { detail: string }>
      if (err.response?.status === 409) {
        const body = err.response.data as MultiMatchError
        setConflictCandidates(body.matches || [])
        // 判断是 A 还是 B 的冲突：detail 里含 "函数 B"
        setConflictWhich(body.detail?.includes('函数 B') ? 'B' : 'A')
        setConflictOpen(true)
      } else if (err.response?.status === 404) {
        const detail = (err.response?.data as { detail?: string })?.detail || ''
        message.error(detail || `未找到函数`)
      } else {
        const detail = (err.response?.data as { detail?: string })?.detail || err.message
        message.error('生成失败：' + detail)
      }
    } finally {
      setGenerating(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [funcAName, funcBName, projectId, project?.source_zip_name])

  const pickCandidate = (r: MultiMatchCandidate) => {
    setConflictOpen(false)
    if (conflictWhich === 'A') {
      setFuncAName(r.qualified_name)
      handleGenerate(r.qualified_name, funcBName)
    } else {
      setFuncBName(r.qualified_name)
      handleGenerate(funcAName, r.qualified_name)
    }
  }

  // ---- 下载 SVG ----
  const downloadSvg = () => {
    const svgEl = flowRef.current?.querySelector('svg') as SVGSVGElement | null
    const svgOut = svgEl ? new XMLSerializer().serializeToString(svgEl) : lastSvgRef.current
    if (!svgOut) { message.warning('请先生成时序图'); return }
    const blob = new Blob([svgOut], { type: 'image/svg+xml' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${funcAName || 'seqdiag'}.svg`
    a.click()
    URL.revokeObjectURL(a.href)
    message.success('已下载 SVG')
  }

  return (
    <Spin spinning={projectLoading}>
      <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden' }}>
        {/* 顶部面包屑 */}
        <div style={{ padding: '8px 16px', borderBottom: '1px solid #f0f0f0',
                       display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
          <Button type="link" icon={<ArrowLeftOutlined />} size="small"
                   onClick={() => navigate('/seqdiag/projects')}>
            函数时序图项目
          </Button>
          <span style={{ color: '#bbb' }}>/</span>
          <span style={{ fontWeight: 500 }}>{project?.name || projectId}</span>
        </div>

        <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
          {/* ── 左列 ── */}
          <div style={{ width: 300, flexShrink: 0, borderRight: '1px solid #f0f0f0',
                         overflowY: 'auto', padding: 16, display: 'flex',
                         flexDirection: 'column', gap: 16 }}>

            {/* 源码 zip */}
            <Card size="small" title={<span><FileZipOutlined /> 主源码 zip</span>}>
              {project?.source_zip_name && (
                <div style={{ marginBottom: 8, color: '#52c41a', fontSize: 12 }}>
                  已上传：{project.source_zip_name}
                </div>
              )}
              {sourceUploading && (
                <Progress percent={sourcePercent} size="small" style={{ marginBottom: 8 }} />
              )}
              <Upload showUploadList={false} beforeUpload={beforeSourceUpload}
                       accept=".zip" disabled={sourceUploading}>
                <Button icon={<PlusOutlined />} loading={sourceUploading} block>
                  {project?.source_zip_name ? '重新上传' : '上传源码 zip'}
                </Button>
              </Upload>
            </Card>

            {/* Include zips */}
            <Card size="small" title="Include 依赖包">
              <Input
                placeholder="Include 名称（如 opencv）"
                value={includeName}
                onChange={(e) => setIncludeName(e.target.value)}
                style={{ marginBottom: 8 }}
                size="small"
              />
              {includeUploading && (
                <Progress percent={includePercent} size="small" style={{ marginBottom: 8 }} />
              )}
              <Upload showUploadList={false} beforeUpload={beforeIncludeUpload}
                       accept=".zip" disabled={includeUploading}>
                <Button icon={<PlusOutlined />} loading={includeUploading} block size="small">
                  追加 include zip
                </Button>
              </Upload>
              {(project?.include_dirs || []).length > 0 && (
                <List
                  size="small"
                  style={{ marginTop: 8 }}
                  dataSource={project?.include_dirs || []}
                  renderItem={(item) => (
                    <List.Item
                      actions={[
                        <Tooltip title="删除" key="del">
                          <Button type="link" size="small" danger icon={<DeleteOutlined />}
                                   onClick={() => handleIncludeDelete(item.name)} />
                        </Tooltip>,
                      ]}
                    >
                      <span style={{ fontSize: 12 }}>{item.name}</span>
                    </List.Item>
                  )}
                />
              )}
            </Card>

            <Divider style={{ margin: '0' }} />

            {/* 函数输入 */}
            <Card size="small" title="函数">
              <div style={{ marginBottom: 8 }}>
                <div style={{ fontSize: 12, color: '#888', marginBottom: 4 }}>函数 A</div>
                <Input
                  placeholder="如 CameraDriver::init"
                  value={funcAName}
                  onChange={(e) => setFuncAName(e.target.value)}
                  onPressEnter={() => handleGenerate()}
                  size="small"
                />
              </div>
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 12, color: '#888', marginBottom: 4 }}>
                  函数 B（可选，展开交互）
                </div>
                <Input
                  placeholder="如 Sensor::read"
                  value={funcBName}
                  onChange={(e) => setFuncBName(e.target.value)}
                  onPressEnter={() => handleGenerate()}
                  size="small"
                />
              </div>
              <Button type="primary" block icon={<PlayCircleOutlined />}
                       loading={generating}
                       onClick={() => handleGenerate()}>
                生成时序图
              </Button>
            </Card>
          </div>

          {/* ── 右列 ── */}
          <div style={{ flex: 1, overflow: 'hidden', padding: 12 }}>
            <Card style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
                   bodyStyle={{ flex: 1, overflow: 'hidden', padding: 0, display: 'flex',
                                 flexDirection: 'column' }}>
              <Tabs
                activeKey={activeTab}
                onChange={setActiveTab}
                style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}
                tabBarStyle={{ margin: '0 12px' }}
                tabBarExtraContent={
                  <Space size="small" style={{ paddingRight: 8 }}>
                    <Tooltip title="适合窗口">
                      <Button size="small" icon={<FullscreenOutlined />}
                               onClick={fitToWindow} disabled={!uml} />
                    </Tooltip>
                    <Tooltip title="放大">
                      <Button size="small" icon={<ZoomInOutlined />}
                               onClick={() => setScale((s) => Math.min(10, s * 1.2))}
                               disabled={!uml} />
                    </Tooltip>
                    <Tooltip title="缩小">
                      <Button size="small" icon={<ZoomOutOutlined />}
                               onClick={() => setScale((s) => Math.max(0.05, s / 1.2))}
                               disabled={!uml} />
                    </Tooltip>
                    <Tooltip title="下载 SVG">
                      <Button size="small" icon={<DownloadOutlined />}
                               onClick={downloadSvg} disabled={!uml} />
                    </Tooltip>
                  </Space>
                }
                items={[
                  {
                    key: 'diagram',
                    label: '时序图',
                    children: (
                      <div style={{ position: 'relative', flex: 1, overflow: 'hidden' }}>
                        <div ref={svgWrapRef}
                             style={{ width: '100%', height: '100%', minHeight: 400,
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
                            请在左侧输入函数 A 并点击"生成时序图"
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
                            <span style={{ color: '#888', fontSize: 12 }}>Ctrl+Enter 重渲染</span>
                            <Button size="small" icon={<ReloadOutlined />}
                                     onClick={reRenderFromUml}>重新渲染</Button>
                          </Space>
                        </div>
                      </div>
                    ),
                  },
                  {
                    key: 'files',
                    label: `匹配的文件 (${matchedFiles.length})`,
                    children: (
                      <Table size="small"
                              rowKey={(r) => r}
                              dataSource={matchedFiles}
                              pagination={false}
                              locale={{ emptyText: '尚未匹配到任何文件' }}
                              columns={[
                                { title: '相对路径', dataIndex: undefined,
                                  render: (_, p) => <code>{p}</code> },
                              ]} />
                    ),
                  },
                ]} />
            </Card>
          </div>
        </div>

        {/* 冲突弹层 */}
        <Modal open={conflictOpen}
                title={`函数${conflictWhich} 存在 ${conflictCandidates.length} 个同名定义`}
                onCancel={() => setConflictOpen(false)}
                footer={<Button onClick={() => setConflictOpen(false)}>关闭</Button>}
                width={780}>
          <Alert type="warning" showIcon style={{ marginBottom: 12 }}
                  message="点击某一行的全限定名即可自动填回输入框并重新生成。" />
          <Table size="small"
                  rowKey={(r) => r.qualified_name + r.file + r.line}
                  dataSource={conflictCandidates}
                  pagination={false}
                  columns={[
                    { title: '全限定名', dataIndex: 'qualified_name',
                      render: (v, r) => <a onClick={() => pickCandidate(r)}>{v}</a> },
                    { title: '文件', dataIndex: 'file', ellipsis: true,
                      render: (v: string) => <span style={{ color: '#666' }}>{v}</span> },
                    { title: '行', dataIndex: 'line', width: 60, align: 'right' as const },
                    { title: '类型', dataIndex: 'kind', width: 80,
                      render: (v: string) => <Tag>{v}</Tag> },
                  ]} />
        </Modal>
      </div>
    </Spin>
  )
}
