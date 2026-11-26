/**
 * SWE.1 R1 - 需求回灌向导（Modal）
 *
 * 流程 A3/A4/A6：
 *   step 1 (A3) - 列映射：命中已有模板 → 显示 + 允许改；没命中 → 启发式推断
 *   step 2 (A4) - 预览：按行类型分区展示（group/main/sub/coverage/skip）+ 行勾选
 *                 冲突行以浅红色标记，可选 overwrite/skip/mark_pending
 *   step 3 (A6) - 确认：显示统计 + 可选"保存为模板"
 *
 * 入库完成后 onSuccess 回调；父组件刷项目重新 fetch。
 */
import { useEffect, useMemo, useState } from 'react'
import {
  Modal, Steps, Table, Tag, Button, Space, Input, Select, Alert, Checkbox,
  Tooltip, Statistic, Row, Col, Switch, Spin, Empty, Collapse, message,
} from 'antd'
import {
  CheckCircleOutlined, WarningOutlined, InfoCircleOutlined,
} from '@ant-design/icons'
import {
  ingestSwe1Preview, ingestSwe1Confirm,
} from '../../../api/aspiceApi'
import type {
  Swe1ColumnMapping, Swe1IngestPreviewResponse, Swe1ParsedRow,
} from '../../../types/aspice'

const { Option } = Select

interface Props {
  projectId: string
  fileId: string                 // 要回灌的源文件
  open: boolean
  onClose: () => void
  onSuccess: () => void          // 入库完成；父组件刷项目
}

// Requirement 可映射的字段（和 backend _HEADER_FIELD_RULES 对齐）
const FIELD_OPTIONS: { value: string; label: string; required?: boolean }[] = [
  { value: '', label: '(忽略此列)' },
  { value: 'input_source', label: '来源文档' },
  { value: 'chapter', label: '章节' },
  { value: 'external_id', label: '客户原始 ID (external_id) *', required: true },
  { value: 'content', label: '需求描述 (content) *', required: true },
  { value: 'software_mark', label: '软件标识' },
  { value: 'or_id', label: 'OR ID' },
  { value: 'req_id', label: 'Req ID' },
  { value: 'sw_req_desc', label: '功能描述' },
  { value: 'test_case_id', label: '测试用例 ID' },
  { value: 'requirement_module', label: '需求模块' },
  { value: 'category', label: '分类' },
  { value: 'asil', label: 'ASIL' },
  { value: 'correctness', label: '正确性' },
  { value: 'feasibility', label: '可行性' },
  { value: 'exception', label: '异常处理' },
  { value: 'priority', label: '优先级' },
  { value: 'milestone', label: '发布时间' },
  { value: 'ra_deadline', label: 'RA 截止' },
  { value: 'actual_time', label: '实际完成' },
  { value: 'release_version', label: '发布版本' },
  { value: 'owner', label: '负责人' },
  { value: 'memo', label: '备注' },
  { value: 'arch_doc_hint', label: '架构文档提示' },
]

const ROW_TYPE_COLOR: Record<string, string> = {
  main: 'blue',
  sub: 'geekblue',
  group: 'purple',
  coverage: 'orange',
  skip: 'default',
  header: 'default',
}

const ROW_TYPE_LABEL: Record<string, string> = {
  main: '主需求',
  sub: '子需求',
  group: '分组行',
  coverage: '覆盖说明',
  skip: '跳过',
  header: '表头',
}

export default function IngestWizard({ projectId, fileId, open, onClose, onSuccess }: Props) {
  const [current, setCurrent] = useState(0)
  const [loading, setLoading] = useState(false)
  const [preview, setPreview] = useState<Swe1IngestPreviewResponse | null>(null)
  const [mapping, setMapping] = useState<Swe1ColumnMapping[]>([])
  const [acceptedRows, setAcceptedRows] = useState<Set<number>>(new Set())
  const [conflictStrategy, setConflictStrategy] = useState<Record<string, 'overwrite' | 'skip' | 'mark_pending'>>({})
  const [saveAsTemplate, setSaveAsTemplate] = useState(false)
  const [templateName, setTemplateName] = useState('')
  const [confirming, setConfirming] = useState(false)

  // 首次打开：请求 preview
  useEffect(() => {
    if (!open || !fileId || !projectId) return
    ;(async () => {
      setLoading(true)
      setCurrent(0)
      setPreview(null)
      setMapping([])
      setAcceptedRows(new Set())
      setConflictStrategy({})
      setSaveAsTemplate(false)
      setTemplateName('')
      try {
        const res = await ingestSwe1Preview(projectId, { file_id: fileId })
        setPreview(res.data)
        setMapping(res.data.suggested_mapping)
        // 默认勾上所有 main/sub/coverage
        const defaultAccepted = new Set<number>()
        res.data.rows.forEach((r) => {
          if (r.row_type === 'main' || r.row_type === 'sub' || r.row_type === 'coverage') {
            defaultAccepted.add(r.excel_row)
          }
        })
        setAcceptedRows(defaultAccepted)
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || '预览失败'
        message.error(msg)
        onClose()
      } finally {
        setLoading(false)
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, fileId, projectId])

  const stats = preview?.stats || {}
  const conflictRows = useMemo(
    () => (preview?.rows || []).filter((r) => r.conflict_with_existing),
    [preview],
  )

  const handleMappingChange = (colIdx: number, newField: string) => {
    setMapping((prev) => {
      // 如果新 field 被别的列用了，先清掉
      const cleared = prev.map((m) =>
        m.field === newField && m.excel_col_index !== colIdx
          ? { ...m, field: '' }
          : m,
      )
      // 更新本列
      const idx = cleared.findIndex((m) => m.excel_col_index === colIdx)
      if (idx >= 0) {
        cleared[idx] = { ...cleared[idx], field: newField }
      } else {
        const header = preview?.headers[colIdx] || ''
        cleared.push({
          excel_header: header,
          excel_col_index: colIdx,
          field: newField,
        })
      }
      return cleared
    })
  }

  const handleConfirm = async () => {
    if (!preview) return
    // 校验必填：external_id + content 必须映射
    const mappedFields = new Set(mapping.map((m) => m.field).filter(Boolean))
    const required = ['external_id', 'content']
    const missing = required.filter((f) => !mappedFields.has(f))
    if (missing.length > 0) {
      message.error(`缺少必填字段映射: ${missing.join(', ')}`)
      setCurrent(0)
      return
    }
    if (acceptedRows.size === 0) {
      message.warning('请至少勾选 1 行')
      return
    }

    setConfirming(true)
    try {
      const res = await ingestSwe1Confirm(projectId, {
        file_id: fileId,
        mapping: mapping.filter((m) => m.field),
        accepted_excel_rows: Array.from(acceptedRows),
        save_as_template: saveAsTemplate,
        template_name: templateName,
        conflict_resolution: conflictStrategy,
      })
      const d = res.data
      message.success(
        `入库完成：新增 ${d.inserted} · 更新 ${d.updated} · ` +
        `待审 ${d.marked_pending} · 跳过 ${d.skipped} · 覆盖说明 ${d.coverage_notes_added}`,
      )
      onSuccess()
      onClose()
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || '入库失败'
      message.error(msg)
    } finally {
      setConfirming(false)
    }
  }

  // ---- Step 1: 列映射 ----
  const mappingTable = (
    <div>
      {preview?.suggested_template_id && (
        <Alert
          type="success"
          showIcon
          style={{ marginBottom: 12 }}
          message={`已自动套用历史模板（template_id=${preview.suggested_template_id.slice(0, 8)}...），你可以直接下一步`}
        />
      )}
      <Table
        size="small"
        bordered
        pagination={false}
        rowKey={(r) => String(r.excel_col_index)}
        dataSource={(preview?.headers || []).map((h, i) => {
          const m = mapping.find((x) => x.excel_col_index === i)
          return {
            excel_col_index: i,
            excel_header: h,
            field: m?.field || '',
          }
        })}
        columns={[
          { title: '列#', dataIndex: 'excel_col_index', width: 60,
            render: (v) => `${v + 1}` },
          { title: 'Excel 列头', dataIndex: 'excel_header', width: 220,
            render: (v) => v || <span style={{ color: '#ccc' }}>(空)</span> },
          {
            title: '映射到 Requirement 字段',
            dataIndex: 'field',
            render: (v, rec) => (
              <Select
                value={v || ''}
                style={{ width: '100%' }}
                size="small"
                onChange={(nv) => handleMappingChange(rec.excel_col_index, nv)}
                showSearch
                optionFilterProp="label"
              >
                {FIELD_OPTIONS.map((opt) => (
                  <Option key={opt.value || '__none__'} value={opt.value} label={opt.label}>
                    {opt.label}
                  </Option>
                ))}
              </Select>
            ),
          },
        ]}
      />
    </div>
  )

  // ---- Step 2: 预览行 ----
  const rowsData = (preview?.rows || []).filter((r) => r.row_type !== 'header')

  const toggleRow = (excel_row: number) => {
    setAcceptedRows((prev) => {
      const next = new Set(prev)
      if (next.has(excel_row)) next.delete(excel_row)
      else next.add(excel_row)
      return next
    })
  }

  const toggleAllByType = (type: string, accept: boolean) => {
    setAcceptedRows((prev) => {
      const next = new Set(prev)
      rowsData.forEach((r) => {
        if (r.row_type === type) {
          if (accept) next.add(r.excel_row)
          else next.delete(r.excel_row)
        }
      })
      return next
    })
  }

  const rowsTable = (
    <div>
      <Space style={{ marginBottom: 8 }} wrap>
        <span>批量：</span>
        <Button size="small" onClick={() => toggleAllByType('main', true)}>勾选所有主需求</Button>
        <Button size="small" onClick={() => toggleAllByType('sub', true)}>勾选所有子需求</Button>
        <Button size="small" onClick={() => toggleAllByType('coverage', true)}>勾选所有覆盖</Button>
        <Button size="small" danger onClick={() => setAcceptedRows(new Set())}>全不选</Button>
      </Space>
      <Table
        size="small"
        bordered
        pagination={{ pageSize: 20, showSizeChanger: true, pageSizeOptions: ['10', '20', '50', '100'] }}
        rowKey={(r) => String(r.excel_row)}
        dataSource={rowsData}
        scroll={{ y: 420 }}
        rowClassName={(r) => {
          if (r.conflict_with_existing) return 'ingest-conflict-row'
          if (r.row_type === 'skip' || r.row_type === 'group') return 'ingest-muted-row'
          if (r.row_type === 'coverage') return 'ingest-coverage-row'
          return ''
        }}
        columns={[
          {
            title: '选',
            width: 50,
            render: (_, r: Swe1ParsedRow) => {
              if (r.row_type === 'skip' || r.row_type === 'group' || r.row_type === 'header') {
                return <Checkbox disabled />
              }
              return (
                <Checkbox
                  checked={acceptedRows.has(r.excel_row)}
                  onChange={() => toggleRow(r.excel_row)}
                />
              )
            },
          },
          { title: 'Excel#', dataIndex: 'excel_row', width: 70 },
          {
            title: '类型', dataIndex: 'row_type', width: 90,
            render: (v) => <Tag color={ROW_TYPE_COLOR[v] || 'default'}>{ROW_TYPE_LABEL[v] || v}</Tag>,
          },
          {
            title: 'OR_ID',
            width: 120,
            render: (_, r) => (r.data?.or_id as string) || '',
          },
          {
            title: 'Req_ID',
            width: 150,
            render: (_, r) => (r.data?.req_id as string) || '',
          },
          {
            title: '客户 ID',
            width: 140,
            render: (_, r) => (r.data?.external_id as string) || '',
          },
          {
            title: '模块',
            width: 110,
            render: (_, r) => (r.data?.requirement_module as string) || (r.data?.module as string) || '',
          },
          {
            title: '内容摘要',
            render: (_, r) => {
              const c = (r.data?.content as string) || ''
              return (
                <Tooltip title={c}>
                  <span>{c.length > 60 ? c.slice(0, 60) + '…' : c}</span>
                </Tooltip>
              )
            },
          },
          {
            title: '冲突',
            width: 110,
            render: (_, r) => {
              if (!r.conflict_with_existing) return null
              const reqId = (r.data?.req_id as string) || ''
              const current = conflictStrategy[reqId] || 'mark_pending'
              return (
                <Select
                  size="small"
                  value={current}
                  style={{ width: 100 }}
                  onChange={(v) =>
                    setConflictStrategy((prev) => ({ ...prev, [reqId]: v }))
                  }
                >
                  <Option value="mark_pending">标待审</Option>
                  <Option value="overwrite">覆盖</Option>
                  <Option value="skip">跳过</Option>
                </Select>
              )
            },
          },
        ]}
      />
      {/* 行类型配色 */}
      <style>{`
        .ingest-conflict-row td { background: #fff1f0 !important; }
        .ingest-muted-row td { background: #fafafa !important; color: #999; }
        .ingest-coverage-row td { background: #fff7e6 !important; }
      `}</style>
    </div>
  )

  // ---- Step 3: 确认 ----
  const summaryPanel = (
    <div>
      <Row gutter={16} style={{ marginBottom: 20 }}>
        <Col span={6}>
          <Statistic title="解析总行数" value={stats.total || 0} />
        </Col>
        <Col span={6}>
          <Statistic title="将入库需求" value={acceptedRows.size}
            valueStyle={{ color: '#3f8600' }} />
        </Col>
        <Col span={6}>
          <Statistic title="冲突" value={conflictRows.length}
            valueStyle={{ color: conflictRows.length ? '#cf1322' : undefined }} />
        </Col>
        <Col span={6}>
          <Statistic title="跳过" value={stats.skip || 0} />
        </Col>
      </Row>
      <Alert
        type="info"
        showIcon
        message="入库规则"
        description={
          <ul style={{ marginBottom: 0, paddingLeft: 20 }}>
            <li>工程师已填 or_id/req_id → <b>原样保留</b>，不重编</li>
            <li>or_id 为空/NA → 用项目代号 + 下一个 OR 序号派生</li>
            <li>req_id 为空 → 在该 OR 下续 R 序号</li>
            <li>coverage 行 → review_status=note，UI 淡灰显示</li>
            <li>相同 req_id 冲突 → 按你上步选的策略处理（默认标待审）</li>
          </ul>
        }
        style={{ marginBottom: 16 }}
      />
      <Space direction="vertical" style={{ width: '100%' }}>
        <Space>
          <Switch
            checked={saveAsTemplate}
            onChange={setSaveAsTemplate}
          />
          <span>保存当前列映射为模板（下次同格式文件自动套用）</span>
        </Space>
        {saveAsTemplate && (
          <Input
            placeholder="模板名称，如 'PreDev 23 列标准模板'"
            value={templateName}
            onChange={(e) => setTemplateName(e.target.value)}
            maxLength={60}
          />
        )}
      </Space>
    </div>
  )

  const steps = [
    { title: '列映射', content: mappingTable },
    { title: '预览行', content: rowsTable },
    { title: '确认入库', content: summaryPanel },
  ]

  return (
    <Modal
      open={open}
      title="需求回灌向导"
      onCancel={onClose}
      width={1100}
      maskClosable={false}
      footer={
        <Space>
          <Button onClick={onClose}>取消</Button>
          {current > 0 && (
            <Button onClick={() => setCurrent(current - 1)}>上一步</Button>
          )}
          {current < steps.length - 1 && (
            <Button type="primary" onClick={() => setCurrent(current + 1)}>
              下一步
            </Button>
          )}
          {current === steps.length - 1 && (
            <Button
              type="primary"
              icon={<CheckCircleOutlined />}
              loading={confirming}
              onClick={handleConfirm}
            >
              确认入库
            </Button>
          )}
        </Space>
      }
    >
      {loading ? (
        <div style={{ padding: 60, textAlign: 'center' }}>
          <Spin tip="正在解析文件..." />
        </div>
      ) : !preview ? (
        <Empty description="未加载预览数据" />
      ) : (
        <>
          <Steps current={current} items={steps.map(s => ({ title: s.title }))} style={{ marginBottom: 16 }} />
          {/* 统计 bar */}
          <Alert
            type="info"
            showIcon
            icon={<InfoCircleOutlined />}
            style={{ marginBottom: 12 }}
            message={
              <Space wrap size={12}>
                <span>解析 <b>{stats.total || 0}</b> 行</span>
                <span>主需求 <Tag color="blue">{stats.main || 0}</Tag></span>
                <span>子需求 <Tag color="geekblue">{stats.sub || 0}</Tag></span>
                <span>分组 <Tag color="purple">{stats.group || 0}</Tag></span>
                <span>覆盖 <Tag color="orange">{stats.coverage || 0}</Tag></span>
                <span>跳过 <Tag>{stats.skip || 0}</Tag></span>
                {(stats.conflict || 0) > 0 && (
                  <span>
                    <WarningOutlined style={{ color: '#cf1322' }} /> 冲突 <Tag color="red">{stats.conflict}</Tag>
                  </span>
                )}
              </Space>
            }
          />
          <div style={{ minHeight: 420 }}>
            {steps[current].content}
          </div>
        </>
      )}
    </Modal>
  )
}
