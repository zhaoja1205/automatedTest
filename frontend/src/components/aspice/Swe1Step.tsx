/**
 * SWE.1 需求分析步骤（R1 重构）
 *
 * 核心定位转变（见 backend/docs/swe1_refactor_plan.md）：
 *   - 80% 场景：工程师已处理好的需求表 → 结构化回灌（SourcesPanel + IngestWizard）
 *   - 20% 场景：客户原始文档 → 旧 AI 解析（保留在"AI 候选"折叠面板）
 *
 * 顶部 Collapse：
 *   - 📥 需求源管理（上传/回灌）
 *   - 📋 列映射模板（跨项目复用）
 *   - 🤖 AI 候选（旧流程，默认收起）
 *
 * 主区域：RequirementsTable（新台账，带 external_id / review_status 等 R1 字段）
 * 底部 Tabs：硬件拓扑 / KPI / 校验结果 / 导出
 */
import { useMemo, useState } from 'react'
import {
  Input, Button, Space, Upload, Card, Alert, message, Tabs, Modal,
  Collapse, Badge, Progress, Tag,
} from 'antd'
import {
  RobotOutlined, ImportOutlined, ExportOutlined, DownloadOutlined, PlusOutlined, DeleteOutlined,
  SafetyCertificateOutlined, CheckCircleOutlined, WarningOutlined, ExclamationCircleOutlined,
  CloudUploadOutlined, FolderOpenOutlined,
} from '@ant-design/icons'
import type { UploadFile } from 'antd'
import { createDefaultAspice, useAspiceStore } from '../../stores/useAspiceStore'
import {
  parseRequirements, exportSwe1, downloadAspiceFile, validateSwe1,
} from '../../api/aspiceApi'
import type { Requirement, ValidateResult } from '../../types/aspice'
import SourcesPanel from './swe1/SourcesPanel'
import IngestWizard from './swe1/IngestWizard'
import RequirementsTable from './swe1/RequirementsTable'
import TemplatesPanel from './swe1/TemplatesPanel'

const { TextArea } = Input

export default function Swe1Step() {
  const store = useAspiceStore()
  const { projectId, setProjectCode, setRequirements, setTopology, setKpi } = store
  const aspice = store.aspice || createDefaultAspice()
  const [rawText, setRawText] = useState('')
  const [uploadFiles, setUploadFiles] = useState<UploadFile[]>([])
  const [parsing, setParsing] = useState(false)
  const [parseProgress, setParseProgress] = useState(0)
  const [parseStage, setParseStage] = useState('')
  const [exporting, setExporting] = useState(false)
  const [exportFiles, setExportFiles] = useState<{ docx: string; xlsx: string } | null>(null)
  const [validating, setValidating] = useState(false)
  const [validateResult, setValidateResult] = useState<ValidateResult | null>(null)
  const [validateVisible, setValidateVisible] = useState(false)

  // R1 新增：IngestWizard 控制
  const [wizardOpen, setWizardOpen] = useState(false)
  const [wizardFileId, setWizardFileId] = useState<string>('')

  const requirements = aspice.swe1.requirements || []

  // AI 解析（旧流程，R1 保留在折叠面板里）
  const runParse = async (text: string, files: File[] | null) => {
    if (!projectId) { message.warning('项目未创建'); return }
    if (!text.trim() && (!files || files.length === 0)) { message.warning('请粘贴或上传客户需求'); return }

    setParsing(true)
    setParseProgress(12)
    setParseStage(files?.length ? `读取 ${files.length} 个客户需求文件...` : '准备客户需求文本...')
    const tick = window.setInterval(() => {
      setParseProgress((p) => (p < 88 ? p + 6 : p))
      setParseStage((s) => s || 'AI 正在识别需求项...')
    }, 700)

    try {
      setParseProgress(28)
      setParseStage('AI 正在识别需求项、翻译英文并保留原文...')
      const res = await parseRequirements(projectId, text, files)
      setParseProgress(92)
      setParseStage('整理 OR / ReqID 与 ASPICE 字段...')
      const { source, count, requirements: reqs, ai_error } = res.data
      // AI 产出标记为 ai_suggested + pending（R1 约定）
      const marked = reqs.map((r: Requirement) => ({
        ...r,
        source_type: 'ai_suggested',
        review_status: 'pending',
      }))
      setRequirements([...requirements, ...marked])
      setParseProgress(100)
      setParseStage(source === 'ai' ? `AI 解析完成并追加：${count} 条需求` : `规则解析完成并追加：${count} 条需求`)
      if (source === 'ai') {
        message.success(`AI 解析并追加 ${count} 条需求（已标为"待评审"）`)
      } else {
        message.info(`规则解析并追加 ${count} 条需求（AI 未启用或失败）`)
      }
      if (files?.length) setUploadFiles([])
      if (ai_error) message.warning(ai_error)
    } catch (e: any) {
      setParseStage('解析失败')
      message.error(e?.response?.data?.detail || '解析失败')
    } finally {
      window.clearInterval(tick)
      window.setTimeout(() => {
        setParsing(false)
        setParseProgress(0)
        setParseStage('')
      }, 600)
    }
  }

  const handleParse = async () => { await runParse(rawText, null) }
  const handleFileParse = async () => {
    const files = uploadFiles
      .map((f) => f.originFileObj)
      .filter(Boolean) as File[]
    await runParse('', files)
  }

  const handleExport = async () => {
    if (!projectId) return
    setExporting(true)
    try {
      const res = await exportSwe1(projectId)
      setExportFiles(res.data)
      message.success('导出成功')
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '导出失败')
    } finally {
      setExporting(false)
    }
  }

  const handleValidate = async () => {
    if (!projectId) return
    setValidating(true)
    try {
      const res = await validateSwe1(projectId)
      setValidateResult(res.data)
      setValidateVisible(true)
      if (res.data.has_errors) {
        message.error(`校验发现 ${res.data.errors.length} 个错误`)
      } else {
        message.success(`校验通过：${res.data.passed.length} 项检查，${res.data.warnings.length} 个警告`)
      }
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '校验失败')
    } finally {
      setValidating(false)
    }
  }

  const handleDownload = async (filename: string) => {
    if (!projectId) return
    try {
      const res = await downloadAspiceFile(projectId, filename)
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      message.error('下载失败')
    }
  }

  // IngestWizard 完成后重新拉项目
  const refreshProject = async () => {
    // 走 store 外层：触发父组件重新 fetch
    // 简化实现：reload 整个 ASPICE 项目数据
    if (!projectId) return
    try {
      const api = await import('../../api/aspiceApi')
      const res = await api.getAspiceProject(projectId)
      store.setAspice(res.data)
    } catch {
      message.warning('刷新项目失败，请手动切换页签重试')
    }
  }

  const sourcesCount = aspice.swe1.sources?.length || 0
  const pendingCount = requirements.filter(
    (r) => r.review_status === 'pending',
  ).length

  // R1 只读溯源：SWE.1 req_id → SWE.2 组件引用（反向索引 swе2.mappings）
  const archMap = useMemo(() => {
    const m = new Map<string, { component_id: string; component: string }[]>()
    for (const mp of aspice.swe2?.mappings || []) {
      const key = (mp.swe1_id || '').trim()
      if (!key) continue
      const list = m.get(key) || []
      const cid = mp.component_id || ''
      if (!list.some((x) => x.component_id === cid)) {
        list.push({ component_id: cid, component: mp.component || '' })
      }
      m.set(key, list)
    }
    return m
  }, [aspice.swe2?.mappings])

  return (
    <div style={{ maxWidth: 1400 }}>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="SWE.1 软件需求分析（R1 重构）"
        description="80% 场景：导入工程师已处理好的需求表 → 解析为台账。20% 场景：客户原始文档走 AI 解析（AI 候选面板）。入库后 req_id 将传递给 SWE.2。"
      />

      {/* 项目代号 */}
      <Card size="small" title="项目代号（ID 派生根，大小写不限）" style={{ marginBottom: 16 }}>
        <Input
          placeholder="如 Pangu / Atlas / PREDEV"
          value={aspice.project_code}
          onChange={(e) => setProjectCode(e.target.value)}
          style={{ maxWidth: 300 }}
        />
        <span style={{ marginLeft: 12, color: '#999', fontSize: 12 }}>
          OR ID 示例：{aspice.project_code || 'PREDEV'}_001 → {aspice.project_code || 'PREDEV'}_001-R001 → -A001（SWE.2）
        </span>
      </Card>

      {/* R1 顶部 Collapse：需求源 + 模板 + AI 候选 */}
      <Collapse
        defaultActiveKey={['sources']}
        style={{ marginBottom: 16 }}
        items={[
          {
            key: 'sources',
            label: (
              <Space>
                <CloudUploadOutlined />
                <span style={{ fontWeight: 500 }}>需求源管理（80% 场景 - 工程师已处理需求表）</span>
                <Tag color="green">{sourcesCount} 个源文件</Tag>
              </Space>
            ),
            children: projectId ? (
              <SourcesPanel
                projectId={projectId}
                onOpenWizard={(fileId) => {
                  setWizardFileId(fileId)
                  setWizardOpen(true)
                }}
              />
            ) : (
              <Alert type="warning" message="请先创建或选择项目" showIcon />
            ),
          },
          {
            key: 'templates',
            label: (
              <Space>
                <FolderOpenOutlined />
                <span>列映射模板（跨项目复用）</span>
              </Space>
            ),
            children: <TemplatesPanel />,
          },
          {
            key: 'ai',
            label: (
              <Space>
                <RobotOutlined />
                <span>AI 候选（20% 场景 - 客户原始文档）</span>
                {pendingCount > 0 && <Tag color="gold">{pendingCount} 条待评审</Tag>}
              </Space>
            ),
            children: (
              <>
                <Alert
                  type="warning"
                  message="AI 解析的需求会标为'ai_suggested + pending'，需要人工评审确认"
                  style={{ marginBottom: 12 }}
                  showIcon
                />
                <Tabs
                  defaultActiveKey="text"
                  items={[
                    {
                      key: 'text',
                      label: '文本粘贴',
                      children: (
                        <Space direction="vertical" style={{ width: '100%' }}>
                          <TextArea
                            rows={6}
                            placeholder="粘贴客户原始需求文本"
                            value={rawText}
                            onChange={(e) => setRawText(e.target.value)}
                          />
                          <Button
                            type="primary"
                            icon={<RobotOutlined />}
                            loading={parsing}
                            onClick={handleParse}
                          >
                            AI 解析并追加（标为待评审）
                          </Button>
                        </Space>
                      ),
                    },
                    {
                      key: 'file',
                      label: '文件上传',
                      children: (
                        <Space direction="vertical" style={{ width: '100%' }}>
                          <Upload
                            accept=".txt,.docx,.xlsx,.xls,.pdf"
                            multiple
                            fileList={uploadFiles}
                            beforeUpload={() => false}
                            onChange={({ fileList }) => setUploadFiles(fileList)}
                          >
                            <Button icon={<ImportOutlined />} disabled={parsing}>
                              选择客户需求文件（多选）
                            </Button>
                          </Upload>
                          <Button
                            type="primary"
                            icon={<RobotOutlined />}
                            loading={parsing}
                            disabled={uploadFiles.length === 0}
                            onClick={handleFileParse}
                          >
                            AI 解析上传文件
                          </Button>
                        </Space>
                      ),
                    },
                  ]}
                />
                {parsing && (
                  <div style={{ marginTop: 12 }}>
                    <Progress
                      percent={parseProgress}
                      status={parseProgress >= 100 ? 'success' : 'active'}
                    />
                    <div style={{ color: '#666', fontSize: 12, marginTop: 4 }}>
                      {parseStage || 'AI 正在解析客户需求...'}
                    </div>
                  </div>
                )}
              </>
            ),
          },
        ]}
      />

      {/* 需求台账 */}
      <Card
        size="small"
        title={`需求台账 (${requirements.length})`}
        style={{ marginBottom: 16 }}
        extra={
          <Space>
            <Button
              size="small"
              icon={<SafetyCertificateOutlined />}
              loading={validating}
              onClick={handleValidate}
            >
              校验
            </Button>
            <Button
              size="small"
              type="primary"
              icon={<ExportOutlined />}
              loading={exporting}
              onClick={handleExport}
            >
              导出需求文档
            </Button>
          </Space>
        }
      >
        <RequirementsTable
          requirements={requirements}
          onChange={setRequirements}
          archMap={archMap}
        />
      </Card>

      {/* 导出文件 */}
      {exportFiles && (
        <Card size="small" title="导出文件" style={{ marginBottom: 16 }}>
          <Space>
            <Button icon={<DownloadOutlined />} onClick={() => handleDownload(exportFiles.docx)}>
              {exportFiles.docx}
            </Button>
            <Button icon={<DownloadOutlined />} onClick={() => handleDownload(exportFiles.xlsx)}>
              {exportFiles.xlsx}
            </Button>
          </Space>
        </Card>
      )}

      {/* 硬件拓扑 + KPI */}
      <Tabs
        items={[
          {
            key: 'topology',
            label: '硬件拓扑（sensor 位置）',
            children: (
              <TopologyEditor topology={aspice.swe1.topology} onChange={setTopology} />
            ),
          },
          {
            key: 'kpi',
            label: `KPI 非功能需求 (${aspice.swe1.kpi?.length || 0})`,
            children: (
              <KpiEditor kpi={aspice.swe1.kpi} onChange={setKpi} />
            ),
          },
        ]}
      />

      {/* R1 新增：IngestWizard */}
      {projectId && (
        <IngestWizard
          projectId={projectId}
          fileId={wizardFileId}
          open={wizardOpen}
          onClose={() => setWizardOpen(false)}
          onSuccess={refreshProject}
        />
      )}

      {/* 校验结果 Modal */}
      <ValidateModal
        visible={validateVisible}
        result={validateResult}
        onClose={() => setValidateVisible(false)}
      />
    </div>
  )
}

/** 校验项：把 "[V04] OR ID 格式或序号不连续：row9: ..." 拆成代码/标签/详情 */
function ValidateItem({ text, color }: { text: string; color: string }) {
  // 后端格式：[Vxx] 中文标签：详情
  const m = text.match(/^\[([A-Z]\d+)\]\s*([^：]*)[：]?\s*(.*)$/s)
  const code = m?.[1] || ''
  const label = (m?.[2] || '').trim()
  const detail = m?.[3] || text
  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'baseline', marginBottom: 4 }}>
      <Tag
        color={color}
        style={{ fontFamily: 'monospace', fontSize: 11, margin: 0, flexShrink: 0 }}
      >
        {code || '—'}
      </Tag>
      {label && (
        <span style={{ color, fontWeight: 500, flexShrink: 0 }}>{label}</span>
      )}
      <span style={{ color: '#555', fontFamily: 'monospace', fontSize: 12, wordBreak: 'break-all' }}>
        {detail}
      </span>
    </div>
  )
}

/** 校验结果展示 Modal */
function ValidateModal({ visible, result, onClose }: {
  visible: boolean
  result: ValidateResult | null
  onClose: () => void
}) {
  if (!result) return null

  // 按校验码分组，避免几百条平铺
  const groupBy = (items: string[]) => {
    const map = new Map<string, string[]>()
    items.forEach((t) => {
      const code = (t.match(/^\[([A-Z]\d+)\]/) || [])[1] || '其他'
      const list = map.get(code) || []
      list.push(t)
      map.set(code, list)
    })
    return Array.from(map.entries()).sort((a, b) => b[1].length - a[1].length)
  }

  const renderGroups = (items: string[], color: string) => {
    const groups = groupBy(items)
    return (
      <div style={{ maxHeight: 460, overflow: 'auto' }}>
        {groups.map(([code, list]) => (
          <div key={code} style={{ marginBottom: 12 }}>
            <div style={{ fontWeight: 500, marginBottom: 4, color: '#333' }}>
              <Tag color={color} style={{ fontFamily: 'monospace' }}>{code}</Tag>
              <span style={{ color: '#999', fontSize: 12 }}>{list.length} 条</span>
            </div>
            {list.slice(0, 3).map((t, i) => (
              <ValidateItem key={i} text={t} color={color} />
            ))}
            {list.length > 3 && (
              <Collapse
                ghost
                size="small"
                style={{ marginTop: 2 }}
                items={[{
                  key: code,
                  label: (
                    <span style={{ color: '#999', fontSize: 12 }}>
                      展开剩余 {list.length - 3} 条同类问题
                    </span>
                  ),
                  children: list.slice(3).map((t, i) => (
                    <ValidateItem key={i} text={t} color={color} />
                  )),
                }]}
              />
            )}
          </div>
        ))}
      </div>
    )
  }

  return (
    <Modal
      open={visible}
      onCancel={onClose}
      footer={null}
      width={860}
      title={
        <Space>
          <Badge count={result.errors.length} offset={[0, 0]} size="small">
            <ExclamationCircleOutlined style={{ color: result.has_errors ? '#ff4d4f' : '#52c41a' }} />
          </Badge>
          SWE.1 校验报告
          <span style={{ fontSize: 12, color: '#999' }}>
            {result.errors.length} 错误 · {result.warnings.length} 警告 · {result.passed.length} 通过
          </span>
        </Space>
      }
    >
      <Collapse
        defaultActiveKey={result.has_errors ? ['errors'] : ['passed']}
        items={[
          ...(result.errors.length > 0 ? [{
            key: 'errors',
            label: <span style={{ color: '#ff4d4f' }}><ExclamationCircleOutlined /> 错误 ({result.errors.length})</span>,
            children: renderGroups(result.errors, 'red'),
          }] : []),
          ...(result.warnings.length > 0 ? [{
            key: 'warnings',
            label: <span style={{ color: '#faad14' }}><WarningOutlined /> 警告 ({result.warnings.length})</span>,
            children: renderGroups(result.warnings, 'orange'),
          }] : []),
          {
            key: 'passed',
            label: <span style={{ color: '#52c41a' }}><CheckCircleOutlined /> 通过 ({result.passed.length})</span>,
            children: (
              <div style={{ maxHeight: 400, overflow: 'auto' }}>
                {result.passed.map((p, i) => <ValidateItem key={i} text={p} color="green" />)}
              </div>
            ),
          },
        ]}
      />
    </Modal>
  )
}

/** 硬件拓扑编辑器 */
function TopologyEditor({ topology, onChange }: {
  topology: any[]
  onChange: (t: any[]) => void
}) {
  const add = () => onChange([...topology, { group: '', sensor_model: '', fov: '' }])
  const update = (i: number, field: string, v: string) => {
    const t = [...topology]; t[i] = { ...t[i], [field]: v }; onChange(t)
  }
  const del = (i: number) => onChange(topology.filter((_, idx) => idx !== i))
  return (
    <div>
      {topology.map((item, i) => (
        <Space key={i} style={{ marginBottom: 8 }}>
          <Input placeholder="GroupA" value={item.group} onChange={(e) => update(i, 'group', e.target.value)} style={{ width: 120 }} />
          <Input placeholder="IMX728" value={item.sensor_model} onChange={(e) => update(i, 'sensor_model', e.target.value)} style={{ width: 120 }} />
          <Input placeholder="FOV30" value={item.fov} onChange={(e) => update(i, 'fov', e.target.value)} style={{ width: 100 }} />
          <Button type="link" size="small" danger icon={<DeleteOutlined />} onClick={() => del(i)} />
        </Space>
      ))}
      <Button size="small" icon={<PlusOutlined />} onClick={add}>添加拓扑项</Button>
    </div>
  )
}

/** KPI 编辑器 */
function KpiEditor({ kpi, onChange }: {
  kpi: any[]
  onChange: (k: any[]) => void
}) {
  const add = () => onChange([...kpi, { seq: String(kpi.length + 1), desc: '' }])
  const update = (i: number, field: string, v: string) => {
    const k = [...kpi]; k[i] = { ...k[i], [field]: v }; onChange(k)
  }
  const del = (i: number) => onChange(kpi.filter((_, idx) => idx !== i))
  return (
    <div>
      {kpi.map((item, i) => (
        <Space key={i} style={{ marginBottom: 8 }}>
          <Input placeholder="1" value={item.seq} onChange={(e) => update(i, 'seq', e.target.value)} style={{ width: 60 }} />
          <Input placeholder="KPI 描述" value={item.desc} onChange={(e) => update(i, 'desc', e.target.value)} style={{ width: 400 }} />
          <Button type="link" size="small" danger icon={<DeleteOutlined />} onClick={() => del(i)} />
        </Space>
      ))}
      <Button size="small" icon={<PlusOutlined />} onClick={add}>添加 KPI</Button>
    </div>
  )
}
