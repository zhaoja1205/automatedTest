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
  Modal, Collapse, Badge, Tooltip, Progress,
} from 'antd'
import {
  RobotOutlined, ImportOutlined, ExportOutlined, DownloadOutlined, PlusOutlined, DeleteOutlined,
  SafetyCertificateOutlined, CheckCircleOutlined, WarningOutlined, ExclamationCircleOutlined,
} from '@ant-design/icons'
import type { UploadFile } from 'antd'
import { createDefaultAspice, useAspiceStore } from '../../stores/useAspiceStore'
import {
  parseRequirements, exportSwe1, downloadAspiceFile, validateSwe1,
} from '../../api/aspiceApi'
import type { Requirement, ValidateResult } from '../../types/aspice'

const { TextArea } = Input

// skill 枚举（全角逗号），界面显示中文，保存仍用模板枚举值。
const CATEGORY_OPTIONS = [
  { value: 'Functional Requirements，Basic Functions', label: '功能需求 / 基础功能' },
  { value: 'Functional Requirements，Safety Requirements', label: '功能需求 / 安全需求' },
  { value: 'Functional Requirements，Cybersecurity Requirements', label: '功能需求 / 网络安全' },
  { value: 'Non-Functional Requirements', label: '非功能需求' },
  { value: 'Non-camera driver/tuning requirements', label: '非 Camera 驱动/调校需求' },
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

  const requirements = aspice.swe1.requirements || []
  const mappings = aspice.swe2?.mappings || []

  // SWE.2 映射反查：req_id → 所有 swe2_id 列表（X 列 arch_doc）
  const archDocMap = new Map<string, string[]>()
  for (const m of mappings) {
    const rid = m.swe1_id
    if (!archDocMap.has(rid)) archDocMap.set(rid, [])
    if (m.swe2_id) archDocMap.get(rid)!.push(m.swe2_id)
  }

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
      setRequirements([...requirements, ...reqs])
      setParseProgress(100)
      setParseStage(source === 'ai' ? `AI 解析完成并追加：${count} 条需求` : `规则解析完成并追加：${count} 条需求`)
      if (source === 'ai') {
        message.success(`AI 解析并追加 ${count} 条需求`)
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

  // AI 解析
  const handleParse = async () => {
    await runParse(rawText, null)
  }

  // 多文件上传解析
  const handleFileParse = async () => {
    const files = uploadFiles
      .map(f => f.originFileObj)
      .filter(Boolean) as File[]
    await runParse('', files)
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
  const splitBilingual = (text?: string) => {
    const value = text || ''
    const parts = value.split(' / ')
    if (parts.length < 2) return { cn: value, en: '' }
    return { cn: parts[0], en: parts.slice(1).join(' / ') }
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
    { title: 'ReqID', dataIndex: 'req_id', key: 'req_id', width: 190,
      render: (t: string) => (
        <Tooltip title={t}>
          <Tag color="blue" style={{ maxWidth: 170, overflow: 'hidden', textOverflow: 'ellipsis' }}>{t}</Tag>
        </Tooltip>
      ) },
    { title: '标识', dataIndex: 'software_mark', key: 'software_mark', width: 100,
      render: (t: string, _r: Requirement, idx: number) => (
        <Select size="small" value={t} style={{ width: '100%' }} onChange={(v) => updateReq(idx, 'software_mark', v)}
          options={MARK_OPTIONS} />
      ) },
    { title: '需求描述（中文 / 原文）', dataIndex: 'content', key: 'content', width: 380,
      render: (t: string, _r: Requirement, idx: number) => {
        const parts = splitBilingual(t)
        return (
          <Space direction="vertical" size={4} style={{ width: '100%' }}>
            {parts.en && (
              <div style={{ fontSize: 12, color: '#666', lineHeight: 1.4 }}>
                <Tag color="processing" style={{ marginRight: 4 }}>中文</Tag>{parts.cn}
              </div>
            )}
            {parts.en && (
              <div style={{ fontSize: 12, color: '#999', lineHeight: 1.4 }}>
                <Tag style={{ marginRight: 4 }}>原文</Tag>{parts.en}
              </div>
            )}
            <TextArea value={t} onChange={(e) => updateReq(idx, 'content', e.target.value)}
              autoSize={{ minRows: parts.en ? 2 : 1, maxRows: 4 }} />
          </Space>
        )
      } },
    { title: '软件需求描述', dataIndex: 'sw_req_desc', key: 'sw_req_desc', width: 260,
      render: (t: string, _r: Requirement, idx: number) => (
        <TextArea value={t} onChange={(e) => updateReq(idx, 'sw_req_desc', e.target.value)}
          autoSize={{ minRows: 1, maxRows: 3 }} placeholder="中文功能描述（I 列）" />
      ) },
    { title: '分类', dataIndex: 'category', key: 'category', width: 240,
      render: (t: string, _r: Requirement, idx: number) => (
        <Select size="small" value={t || undefined} placeholder="分类" style={{ width: '100%' }}
          onChange={(v) => updateReq(idx, 'category', v)} allowClear
          options={CATEGORY_OPTIONS} optionRender={(option) => (
            <Space direction="vertical" size={0}>
              <span>{option.label}</span>
              <span style={{ fontSize: 11, color: '#999' }}>{option.value}</span>
            </Space>
          )} />
      ) },
    { title: 'ASIL', dataIndex: 'asil', key: 'asil', width: 100,
      render: (t: string, _r: Requirement, idx: number) => (
        <Select size="small" value={t || 'QM'} style={{ width: '100%' }} onChange={(v) => updateReq(idx, 'asil', v)}
          options={ASIL_OPTIONS.map(o => ({ value: o, label: o }))} />
      ) },
    { title: 'Test Case ID', dataIndex: 'test_case_id', key: 'test_case_id', width: 150,
      render: (t: string, _r: Requirement, idx: number) => (
        <Input size="small" value={t} placeholder="J 列" onChange={(e) => updateReq(idx, 'test_case_id', e.target.value)} />
      ) },
    { title: '架构映射', key: 'arch_doc', width: 160,
      render: (_: unknown, r: Requirement) => {
        const docs = archDocMap.get(r.req_id) || []
        return docs.length > 0
          ? <Tooltip title={docs.join('、')}><Tag color="green">{docs.join('、')}</Tag></Tooltip>
          : <Tag>N/A</Tag>
      } },
    { title: 'Owner', dataIndex: 'owner', key: 'owner', width: 120,
      render: (t: string, _r: Requirement, idx: number) => (
        <Input size="small" value={t} onChange={(e) => updateReq(idx, 'owner', e.target.value)} />
      ) },
    { title: '优先级', dataIndex: 'priority', key: 'priority', width: 90,
      render: (t: number, _r: Requirement, idx: number) => (
        <Select size="small" value={t} style={{ width: '100%' }} onChange={(v) => updateReq(idx, 'priority', v)}
          options={PRIORITY_OPTIONS.map(p => ({ value: p, label: String(p) }))} />
      ) },
    { title: '发布版本', dataIndex: 'release_version', key: 'release_version', width: 110,
      render: (t: string, _r: Requirement, idx: number) => (
        <Input size="small" value={t} onChange={(e) => updateReq(idx, 'release_version', e.target.value)} />
      ) },
    { title: '操作', key: 'actions', width: 80,
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
                  <Space>
                    <Button type="primary" icon={<RobotOutlined />} loading={parsing} onClick={handleParse}>
                      AI 解析并追加需求
                    </Button>
                    <span style={{ color: '#999', fontSize: 12 }}>
                      不会覆盖已有需求，新增项会接续当前 OR 编号
                    </span>
                  </Space>
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
                      选择客户需求文件（支持多选）
                    </Button>
                  </Upload>
                  <Space>
                    <Button
                      type="primary"
                      icon={<RobotOutlined />}
                      loading={parsing}
                      disabled={uploadFiles.length === 0}
                      onClick={handleFileParse}
                    >
                      AI 解析上传文件
                    </Button>
                    <span style={{ color: '#999', fontSize: 12 }}>
                      已选择 {uploadFiles.length} 个文件；解析结果会追加到当前需求列表
                    </span>
                  </Space>
                </Space>
              ),
            },
          ]}
        />
        {parsing && (
          <div style={{ marginTop: 12 }}>
            <Progress percent={parseProgress} status={parseProgress >= 100 ? 'success' : 'active'} />
            <div style={{ color: '#666', fontSize: 12, marginTop: 4 }}>
              {parseStage || 'AI 正在解析客户需求...'}
            </div>
          </div>
        )}
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
          tableLayout="fixed"
          scroll={{ x: 1880 }}
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
