/**
 * SWE.1 需求分析步骤。
 *
 * 项目代号 + 客户原始需求（文本粘贴 / 文件上传）→ AI 解析 → 需求项可编辑 Table。
 * 需求项对齐 skill 24 列 Excel 模板：ASIL 安全等级、Test Case ID、架构映射（SWE.2 反查只读）等。
 * 支持硬件拓扑、KPI 非功能需求编辑；导出需求说明书 docx + 需求详细表 xlsx + 校验。
 */
import { useState } from 'react'
import {
  Input, Button, Space, Table, Upload, Card, Alert, message, Tag, Select, Popconfirm, Tabs,
  Modal, Collapse, Badge, Tooltip,
} from 'antd'
import {
  RobotOutlined, ImportOutlined, ExportOutlined, DownloadOutlined, PlusOutlined, DeleteOutlined,
  SafetyCertificateOutlined, CheckCircleOutlined, WarningOutlined, ExclamationCircleOutlined,
} from '@ant-design/icons'
import { useAspiceStore } from '../../stores/useAspiceStore'
import {
  parseRequirements, exportSwe1, downloadAspiceFile, validateSwe1,
} from '../../api/aspiceApi'
import type { Requirement, ValidateResult } from '../../types/aspice'

const { TextArea } = Input

// skill 枚举（全角逗号）
const CATEGORY_OPTIONS = [
  'Functional Requirements，Basic Functions',
  'Functional Requirements，Safety Requirements',
  'Functional Requirements，Cybersecurity Requirements',
  'Non-Functional Requirements',
  'Non-camera driver/tuning requirements',
]
const ASIL_OPTIONS = ['QM', 'ASIL A', 'ASIL B', 'ASIL C', 'ASIL D', 'N/A']
// software_mark 英文枚举（与 skill flag 对齐）
const MARK_OPTIONS = [
  { value: '原始', label: 'Original' },
  { value: '新增', label: 'Add' },
  { value: '删除', label: 'Deleted' },
  { value: '变更', label: 'Modified' },
]
const PRIORITY_OPTIONS = [1, 2, 3]

export default function Swe1Step() {
  const store = useAspiceStore()
  const { aspice, projectId, setProjectCode, setRequirements, setTopology, setKpi } = store
  const [rawText, setRawText] = useState('')
  const [parsing, setParsing] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exportFiles, setExportFiles] = useState<{ docx: string; xlsx: string } | null>(null)
  const [validating, setValidating] = useState(false)
  const [validateResult, setValidateResult] = useState<ValidateResult | null>(null)
  const [validateVisible, setValidateVisible] = useState(false)

  if (!aspice) return null
  const requirements = aspice.swe1.requirements || []
  const mappings = aspice.swe2?.mappings || []

  // SWE.2 映射反查：req_id → 所有 swe2_id 列表（X 列 arch_doc）
  const archDocMap = new Map<string, string[]>()
  for (const m of mappings) {
    const rid = m.swe1_id
    if (!archDocMap.has(rid)) archDocMap.set(rid, [])
    if (m.swe2_id) archDocMap.get(rid)!.push(m.swe2_id)
  }

  // AI 解析
  const handleParse = async () => {
    if (!projectId) { message.warning('项目未创建'); return }
    if (!rawText.trim()) { message.warning('请粘贴或上传客户需求'); return }
    setParsing(true)
    try {
      const res = await parseRequirements(projectId, rawText, null)
      const { source, count, requirements: reqs, ai_error } = res.data
      setRequirements(reqs)
      if (source === 'ai') {
        message.success(`AI 解析出 ${count} 条需求`)
      } else {
        message.info(`规则解析出 ${count} 条需求（AI 未启用或失败）`)
      }
      if (ai_error) message.warning(ai_error)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '解析失败')
    } finally {
      setParsing(false)
    }
  }

  // 文件上传解析
  const handleFileParse = async (file: File) => {
    if (!projectId) { message.warning('项目未创建'); return false }
    setParsing(true)
    try {
      const res = await parseRequirements(projectId, '', file)
      const { source, count, requirements: reqs, ai_error } = res.data
      setRequirements(reqs)
      if (source === 'ai') message.success(`AI 解析出 ${count} 条需求`)
      else message.info(`规则解析出 ${count} 条需求`)
      if (ai_error) message.warning(ai_error)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '解析失败')
    } finally {
      setParsing(false)
    }
    return false
  }

  // 导出
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

  // 校验
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

  // 编辑需求项
  const updateReq = (idx: number, field: keyof Requirement, value: any) => {
    const updated = [...requirements]
    updated[idx] = { ...updated[idx], [field]: value }
    setRequirements(updated)
  }
  const deleteReq = (idx: number) => {
    setRequirements(requirements.filter((_, i) => i !== idx))
  }
  const addReq = () => {
    const seq = requirements.length + 1
    const code = aspice.project_code || 'Proj'
    const or_id = `${code}_${String(seq).padStart(3, '0')}`
    const req_id = `${or_id}-R001`
    setRequirements([...requirements, {
      or_id, req_id, software_mark: '原始', content: '', category: '',
      milestone: '', owner: '', input_source: '手动添加', priority: 2,
      asil: 'QM', test_case_id: '', sw_req_desc: '', or_desc: '',
      chapter: '', no: '', correctness: 'Correct', feasibility: 'Feasible',
      exception: 'N/A', ra_deadline: '', actual_time: 'NA',
      release_version: 'V1.0', memo: '', operation: '', analysis: '',
    }])
  }

  const reqColumns = [
    { title: 'ReqID', dataIndex: 'req_id', key: 'req_id', width: 170, fixed: 'left' as const,
      render: (t: string) => <Tag color="blue">{t}</Tag> },
    { title: '标识', dataIndex: 'software_mark', key: 'software_mark', width: 90,
      render: (t: string, _r: Requirement, idx: number) => (
        <Select size="small" value={t} onChange={(v) => updateReq(idx, 'software_mark', v)}
          options={MARK_OPTIONS} />
      ) },
    { title: '需求描述', dataIndex: 'content', key: 'content', width: 260,
      render: (t: string, _r: Requirement, idx: number) => (
        <TextArea value={t} onChange={(e) => updateReq(idx, 'content', e.target.value)}
          autoSize={{ minRows: 1, maxRows: 3 }} />
      ) },
    { title: '软件需求描述', dataIndex: 'sw_req_desc', key: 'sw_req_desc', width: 200,
      render: (t: string, _r: Requirement, idx: number) => (
        <TextArea value={t} onChange={(e) => updateReq(idx, 'sw_req_desc', e.target.value)}
          autoSize={{ minRows: 1, maxRows: 2 }} placeholder="I 列 软件需求功能描述" />
      ) },
    { title: '分类', dataIndex: 'category', key: 'category', width: 180,
      render: (t: string, _r: Requirement, idx: number) => (
        <Select size="small" value={t || undefined} placeholder="分类"
          onChange={(v) => updateReq(idx, 'category', v)} allowClear
          options={CATEGORY_OPTIONS.map(o => ({ value: o, label: o }))} />
      ) },
    { title: 'ASIL', dataIndex: 'asil', key: 'asil', width: 90,
      render: (t: string, _r: Requirement, idx: number) => (
        <Select size="small" value={t || 'QM'} onChange={(v) => updateReq(idx, 'asil', v)}
          options={ASIL_OPTIONS.map(o => ({ value: o, label: o }))} />
      ) },
    { title: 'Test Case ID', dataIndex: 'test_case_id', key: 'test_case_id', width: 120,
      render: (t: string, _r: Requirement, idx: number) => (
        <Input size="small" value={t} placeholder="J 列" onChange={(e) => updateReq(idx, 'test_case_id', e.target.value)} />
      ) },
    { title: '架构映射', key: 'arch_doc', width: 140,
      render: (_: unknown, r: Requirement) => {
        const docs = archDocMap.get(r.req_id) || []
        return docs.length > 0
          ? <Tooltip title={docs.join('、')}><Tag color="green">{docs.join('、')}</Tag></Tooltip>
          : <Tag>N/A</Tag>
      } },
    { title: 'Owner', dataIndex: 'owner', key: 'owner', width: 90,
      render: (t: string, _r: Requirement, idx: number) => (
        <Input size="small" value={t} onChange={(e) => updateReq(idx, 'owner', e.target.value)} />
      ) },
    { title: '优先级', dataIndex: 'priority', key: 'priority', width: 70,
      render: (t: number, _r: Requirement, idx: number) => (
        <Select size="small" value={t} onChange={(v) => updateReq(idx, 'priority', v)}
          options={PRIORITY_OPTIONS.map(p => ({ value: p, label: String(p) }))} />
      ) },
    { title: '发布版本', dataIndex: 'release_version', key: 'release_version', width: 80,
      render: (t: string, _r: Requirement, idx: number) => (
        <Input size="small" value={t} onChange={(e) => updateReq(idx, 'release_version', e.target.value)} />
      ) },
    { title: '操作', key: 'actions', width: 60, fixed: 'right' as const,
      render: (_: unknown, _r: Requirement, idx: number) => (
        <Popconfirm title="删除此需求？" onConfirm={() => deleteReq(idx)}>
          <Button type="link" size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ) },
  ]

  return (
    <div style={{ maxWidth: 1400 }}>
      <Alert
        type="info" showIcon style={{ marginBottom: 16 }}
        message="SWE.1 软件需求分析"
        description="输入项目代号和客户原始需求，AI 自动解析为结构化需求项并分配 ID（OR→R）。需求 ID 格式：{代号}_001-R001。需求对齐 skill 24 列模板（含 ASIL/Test Case/架构映射）。"
      />

      {/* 项目代号 */}
      <Card size="small" title="项目代号（ID 派生根，大小写不限）" style={{ marginBottom: 16 }}>
        <Input
          placeholder="如 Pangu / Atlas"
          value={aspice.project_code}
          onChange={(e) => setProjectCode(e.target.value)}
          style={{ maxWidth: 300 }}
        />
        <span style={{ marginLeft: 12, color: '#999', fontSize: 12 }}>
          OR ID 示例：{aspice.project_code || 'Pangu'}_001 → {aspice.project_code || 'Pangu'}_001-R001 → -A001（SWE.2）
        </span>
      </Card>

      {/* 客户需求输入 */}
      <Card size="small" title="客户原始需求输入" style={{ marginBottom: 16 }}>
        <Tabs
          defaultActiveKey="text"
          items={[
            {
              key: 'text',
              label: '文本粘贴',
              children: (
                <Space direction="vertical" style={{ width: '100%' }}>
                  <TextArea
                    rows={8}
                    placeholder="粘贴客户原始需求文本（每条一行或带编号）"
                    value={rawText}
                    onChange={(e) => setRawText(e.target.value)}
                  />
                  <Button type="primary" icon={<RobotOutlined />} loading={parsing} onClick={handleParse}>
                    AI 解析需求
                  </Button>
                </Space>
              ),
            },
            {
              key: 'file',
              label: '文件上传',
              children: (
                <Space>
                  <Upload accept=".txt,.docx,.xlsx,.xls,.pdf" showUploadList={false}
                    beforeUpload={handleFileParse}>
                    <Button icon={<ImportOutlined />} loading={parsing}>
                      上传客户需求文件（txt/docx/xlsx/pdf）
                    </Button>
                  </Upload>
                  <span style={{ color: '#999', fontSize: 12 }}>
                    上传后自动调用 AI 解析
                  </span>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      {/* 需求项列表 */}
      <Card size="small" title={`需求项列表 (${requirements.length})`} style={{ marginBottom: 16 }}
        extra={
          <Space>
            <Button size="small" icon={<PlusOutlined />} onClick={addReq}>添加</Button>
            <Button size="small" icon={<SafetyCertificateOutlined />} loading={validating} onClick={handleValidate}>
              校验
            </Button>
            <Button size="small" type="primary" icon={<ExportOutlined />} loading={exporting} onClick={handleExport}>
              导出需求文档
            </Button>
          </Space>
        }>
        <Table
          rowKey={(_, idx) => String(idx)}
          columns={reqColumns}
          dataSource={requirements}
          pagination={requirements.length > 15 ? { pageSize: 15 } : false}
          size="small"
          scroll={{ x: 1600 }}
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

      {/* 校验结果 Modal */}
      <ValidateModal
        visible={validateVisible}
        result={validateResult}
        onClose={() => setValidateVisible(false)}
      />
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
  return (
    <Modal
      open={visible}
      onCancel={onClose}
      footer={null}
      width={720}
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
            children: (
              <ul style={{ marginBottom: 0, paddingLeft: 20 }}>
                {result.errors.map((e, i) => <li key={i} style={{ color: '#ff4d4f' }}>{e}</li>)}
              </ul>
            ),
          }] : []),
          ...(result.warnings.length > 0 ? [{
            key: 'warnings',
            label: <span style={{ color: '#faad14' }}><WarningOutlined /> 警告 ({result.warnings.length})</span>,
            children: (
              <ul style={{ marginBottom: 0, paddingLeft: 20 }}>
                {result.warnings.map((w, i) => <li key={i} style={{ color: '#faad14' }}>{w}</li>)}
              </ul>
            ),
          }] : []),
          {
            key: 'passed',
            label: <span style={{ color: '#52c41a' }}><CheckCircleOutlined /> 通过 ({result.passed.length})</span>,
            children: (
              <ul style={{ marginBottom: 0, paddingLeft: 20 }}>
                {result.passed.map((p, i) => <li key={i} style={{ color: '#52c41a' }}>{p}</li>)}
              </ul>
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
