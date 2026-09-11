/**
 * SWE.1 需求分析步骤。
 *
 * 项目代号 + 客户原始需求（文本粘贴 / 文件上传）→ AI 解析 → 需求项可编辑 Table。
 * 支持硬件拓扑、KPI 非功能需求编辑；导出需求说明书 docx + 需求详细表 xlsx。
 */
import { useState } from 'react'
import {
  Input, Button, Space, Table, Upload, Card, Alert, message, Tag, Select, Popconfirm, Tooltip, Tabs,
} from 'antd'
import {
  RobotOutlined, ImportOutlined, ExportOutlined, DownloadOutlined, PlusOutlined, DeleteOutlined,
} from '@ant-design/icons'
import { useAspiceStore } from '../../stores/useAspiceStore'
import {
  parseRequirements, exportSwe1, downloadAspiceFile,
} from '../../api/aspiceApi'
import type { Requirement } from '../../types/aspice'

const { TextArea } = Input
const PRIORITY_OPTIONS = [1, 2, 3, 4]
const CATEGORY_OPTIONS = [
  'Driver Basic Function', 'Trigger Sync and Timestamp', 'EEPROM', 'Fault Detection',
  'Security', 'Performance', 'Histogram', 'Other',
]

export default function Swe1Step() {
  const store = useAspiceStore()
  const { aspice, projectId, setProjectCode, setRequirements, setTopology, setKpi } = store
  const [rawText, setRawText] = useState('')
  const [parsing, setParsing] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exportFiles, setExportFiles] = useState<{ docx: string; xlsx: string } | null>(null)

  if (!aspice) return null
  const requirements = aspice.swe1.requirements || []

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
    }])
  }

  const reqColumns = [
    { title: 'ReqID', dataIndex: 'req_id', key: 'req_id', width: 180,
      render: (t: string) => <Tag color="blue">{t}</Tag> },
    { title: '软件需求标识', dataIndex: 'software_mark', key: 'software_mark', width: 100,
      render: (t: string, _r: Requirement, idx: number) => (
        <Select size="small" value={t} onChange={(v) => updateReq(idx, 'software_mark', v)}
          options={['原始', '新增', '删除', '变更'].map(o => ({ value: o, label: o }))} />
      ) },
    { title: '需求描述', dataIndex: 'content', key: 'content',
      render: (t: string, _r: Requirement, idx: number) => (
        <TextArea value={t} onChange={(e) => updateReq(idx, 'content', e.target.value)}
          autoSize={{ minRows: 1, maxRows: 3 }} />
      ) },
    { title: '分类', dataIndex: 'category', key: 'category', width: 150,
      render: (t: string, _r: Requirement, idx: number) => (
        <Select size="small" value={t || undefined} placeholder="分类"
          onChange={(v) => updateReq(idx, 'category', v)} allowClear
          options={CATEGORY_OPTIONS.map(o => ({ value: o, label: o }))} />
      ) },
    { title: 'Owner', dataIndex: 'owner', key: 'owner', width: 100,
      render: (t: string, _r: Requirement, idx: number) => (
        <Input size="small" value={t} onChange={(e) => updateReq(idx, 'owner', e.target.value)} />
      ) },
    { title: '优先级', dataIndex: 'priority', key: 'priority', width: 80,
      render: (t: number, _r: Requirement, idx: number) => (
        <Select size="small" value={t} onChange={(v) => updateReq(idx, 'priority', v)}
          options={PRIORITY_OPTIONS.map(p => ({ value: p, label: String(p) }))} />
      ) },
    { title: '操作', key: 'actions', width: 60,
      render: (_: unknown, _r: Requirement, idx: number) => (
        <Popconfirm title="删除此需求？" onConfirm={() => deleteReq(idx)}>
          <Button type="link" size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ) },
  ]

  return (
    <div style={{ maxWidth: 1200 }}>
      <Alert
        type="info" showIcon style={{ marginBottom: 16 }}
        message="SWE.1 软件需求分析"
        description="输入项目代号和客户原始需求，AI 自动解析为结构化需求项并分配 ID（OR→R）。需求 ID 格式：{代号}_001-R001。"
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
          OR ID 示例：{aspice.project_code || 'Pangu'}_001 → {aspice.project_code || 'Pangu'}_001-R001
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
          scroll={{ x: 800 }}
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
    </div>
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
