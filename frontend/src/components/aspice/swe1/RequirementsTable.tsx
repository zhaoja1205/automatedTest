/**
 * SWE.1 R1 - 需求台账主表
 *
 * 职责：
 *   - 展示 swe1.requirements[]（包含 R1 新字段：external_id / review_status / source_doc 等）
 *   - 顶部过滤器：按 review_status / source_type / 模块 / 关键字
 *   - coverage 行（review_status=note）淡灰显示
 *   - 冲突 / pending 行高亮
 *   - 支持单条编辑、批量删除、批量改状态
 *
 * 不负责解析/上传（SourcesPanel + IngestWizard 的事）。
 */
import { useMemo, useState } from 'react'
import {
  Table, Space, Tag, Input, Select, Button, Popconfirm, message, Tooltip, Badge, Dropdown,
} from 'antd'
import type { MenuProps } from 'antd'
import {
  DeleteOutlined, EditOutlined, CheckOutlined, PlusOutlined, FilterOutlined,
} from '@ant-design/icons'
import type {
  Requirement, Swe1ReviewStatus, Swe1SourceType,
} from '../../../types/aspice'

const { Search } = Input
const { Option } = Select

interface ArchRef {
  component_id: string
  component: string
}

interface Props {
  requirements: Requirement[]
  onChange: (next: Requirement[]) => void
  /** R1 只读溯源：req_id → 下游 SWE.2 组件引用（来自 swe2.mappings）。 */
  archMap?: Map<string, ArchRef[]>
}

const STATUS_TAG: Record<Swe1ReviewStatus, { color: string; text: string }> = {
  accepted: { color: 'green', text: '已采纳' },
  pending: { color: 'gold', text: '待评审' },
  rejected: { color: 'red', text: '已驳回' },
  note: { color: 'default', text: '说明' },
}

const SOURCE_TAG: Record<Swe1SourceType, { color: string; text: string }> = {
  engineer_processed: { color: 'green', text: '已处理' },
  customer_raw: { color: 'orange', text: '客户原文' },
  manual: { color: 'blue', text: '手工' },
  ai_suggested: { color: 'purple', text: 'AI 候选' },
  legacy: { color: 'default', text: '遗留' },
}

export default function RequirementsTable({ requirements, onChange, archMap }: Props) {
  const [statusFilter, setStatusFilter] = useState<Swe1ReviewStatus | 'all'>('all')
  const [sourceFilter, setSourceFilter] = useState<Swe1SourceType | 'all'>('all')
  const [moduleFilter, setModuleFilter] = useState<string>('all')
  const [keyword, setKeyword] = useState('')
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])

  // 可选模块列表
  const moduleOptions = useMemo(() => {
    const set = new Set<string>()
    requirements.forEach((r) => {
      if (r.requirement_module) set.add(r.requirement_module)
    })
    return Array.from(set).sort()
  }, [requirements])

  // 过滤
  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    return requirements.filter((r) => {
      const rs = (r.review_status || 'accepted') as Swe1ReviewStatus
      const st = (r.source_type || 'manual') as Swe1SourceType
      if (statusFilter !== 'all' && rs !== statusFilter) return false
      if (sourceFilter !== 'all' && st !== sourceFilter) return false
      if (moduleFilter !== 'all' && (r.requirement_module || '') !== moduleFilter) return false
      if (kw) {
        const hay = [r.or_id, r.req_id, r.external_id, r.content, r.sw_req_desc,
          r.requirement_module].join(' ').toLowerCase()
        if (!hay.includes(kw)) return false
      }
      return true
    })
  }, [requirements, statusFilter, sourceFilter, moduleFilter, keyword])

  const counts = useMemo(() => {
    const c = { total: requirements.length, accepted: 0, pending: 0, note: 0, rejected: 0 }
    requirements.forEach((r) => {
      const rs = (r.review_status || 'accepted') as Swe1ReviewStatus
      c[rs] = (c[rs] || 0) + 1
    })
    return c
  }, [requirements])

  const handleAddRow = () => {
    const next: Requirement = {
      or_id: '', req_id: '', software_mark: '新增', content: '',
      input_source: '', chapter: '', no: '', or_desc: '', sw_req_desc: '',
      test_case_id: '', category: '', asil: 'QM', correctness: 'Correct',
      feasibility: 'Feasible', exception: '', priority: 2, milestone: '',
      ra_deadline: '', actual_time: '', release_version: '', owner: '', memo: '',
      operation: '', analysis: '',
      source_type: 'manual',
      review_status: 'accepted',
      confidence: 1,
    }
    onChange([...requirements, next])
  }

  const handleBatchDelete = () => {
    if (selectedRowKeys.length === 0) return
    const keys = new Set(selectedRowKeys)
    const next = requirements.filter((_, i) => !keys.has(i))
    onChange(next)
    setSelectedRowKeys([])
    message.success(`删除 ${keys.size} 条`)
  }

  const handleBatchStatus = (status: Swe1ReviewStatus) => {
    if (selectedRowKeys.length === 0) return
    const keys = new Set(selectedRowKeys)
    const next = requirements.map((r, i) =>
      keys.has(i) ? { ...r, review_status: status } : r,
    )
    onChange(next)
    setSelectedRowKeys([])
    message.success(`已改 ${keys.size} 条为「${STATUS_TAG[status].text}」`)
  }

  const batchMenu: MenuProps['items'] = [
    { key: 'acc', label: '标记为已采纳', onClick: () => handleBatchStatus('accepted') },
    { key: 'pen', label: '标记为待评审', onClick: () => handleBatchStatus('pending') },
    { key: 'rej', label: '标记为已驳回', onClick: () => handleBatchStatus('rejected') },
  ]

  const handleFieldChange = (index: number, field: keyof Requirement, value: unknown) => {
    const next = [...requirements]
    next[index] = { ...next[index], [field]: value }
    onChange(next)
  }

  const dataSource = filtered.map((r, i) => ({ ...r, __idx: requirements.indexOf(r) }))

  return (
    <div>
      <Space wrap style={{ marginBottom: 12, width: '100%', justifyContent: 'space-between' }}>
        <Space wrap>
          <Badge count={counts.total} showZero color="blue">
            <Tag color="blue">总 {counts.total}</Tag>
          </Badge>
          <Tag color="green">已采纳 {counts.accepted}</Tag>
          <Tag color="gold">待评审 {counts.pending}</Tag>
          <Tag color="default">说明 {counts.note}</Tag>
          {counts.rejected > 0 && <Tag color="red">驳回 {counts.rejected}</Tag>}
        </Space>
        <Space wrap>
          <Button icon={<PlusOutlined />} onClick={handleAddRow}>
            新增需求
          </Button>
          {selectedRowKeys.length > 0 && (
            <>
              <Dropdown menu={{ items: batchMenu }}>
                <Button icon={<CheckOutlined />}>
                  批量改状态 ({selectedRowKeys.length})
                </Button>
              </Dropdown>
              <Popconfirm
                title={`删除选中的 ${selectedRowKeys.length} 条？`}
                onConfirm={handleBatchDelete}
              >
                <Button danger icon={<DeleteOutlined />}>
                  批量删除
                </Button>
              </Popconfirm>
            </>
          )}
        </Space>
      </Space>

      <Space wrap style={{ marginBottom: 12 }}>
        <FilterOutlined />
        <Select
          value={statusFilter}
          onChange={setStatusFilter}
          style={{ width: 130 }}
          size="small"
        >
          <Option value="all">全部状态</Option>
          <Option value="accepted">已采纳</Option>
          <Option value="pending">待评审</Option>
          <Option value="note">说明</Option>
          <Option value="rejected">已驳回</Option>
        </Select>
        <Select
          value={sourceFilter}
          onChange={setSourceFilter}
          style={{ width: 130 }}
          size="small"
        >
          <Option value="all">全部来源</Option>
          <Option value="engineer_processed">已处理需求表</Option>
          <Option value="customer_raw">客户原文</Option>
          <Option value="manual">手工</Option>
          <Option value="ai_suggested">AI 候选</Option>
          <Option value="legacy">遗留</Option>
        </Select>
        <Select
          value={moduleFilter}
          onChange={setModuleFilter}
          style={{ width: 160 }}
          size="small"
          showSearch
        >
          <Option value="all">全部模块</Option>
          {moduleOptions.map((m) => (
            <Option key={m} value={m}>{m}</Option>
          ))}
        </Select>
        <Search
          placeholder="搜 req_id / content / 客户 ID"
          allowClear
          onChange={(e) => setKeyword(e.target.value)}
          style={{ width: 260 }}
          size="small"
        />
        <span style={{ color: '#999', fontSize: 12 }}>
          显示 {filtered.length} / {requirements.length}
        </span>
      </Space>

      <Table
        size="small"
        bordered
        rowKey="__idx"
        dataSource={dataSource}
        pagination={{ pageSize: 20, showSizeChanger: true, pageSizeOptions: ['10', '20', '50', '100'] }}
        scroll={{ x: 1430, y: 460 }}
        rowSelection={{
          selectedRowKeys,
          onChange: setSelectedRowKeys,
        }}
        rowClassName={(r) => {
          if (r.review_status === 'note') return 'req-row-note'
          if (r.review_status === 'pending') return 'req-row-pending'
          if (r.review_status === 'rejected') return 'req-row-rejected'
          return ''
        }}
        columns={[
          {
            title: '状态', width: 80, fixed: 'left',
            render: (_, r) => {
              const s = (r.review_status || 'accepted') as Swe1ReviewStatus
              const info = STATUS_TAG[s]
              return <Tag color={info.color}>{info.text}</Tag>
            },
          },
          {
            title: 'OR_ID', dataIndex: 'or_id', width: 120, fixed: 'left',
            render: (v, _r, i) => (
              <Input
                value={v}
                size="small"
                variant="borderless"
                onChange={(e) => handleFieldChange(dataSource[i].__idx, 'or_id', e.target.value)}
              />
            ),
          },
          {
            title: 'Req_ID', dataIndex: 'req_id', width: 140, fixed: 'left',
            render: (v, _r, i) => (
              <Input
                value={v}
                size="small"
                variant="borderless"
                onChange={(e) => handleFieldChange(dataSource[i].__idx, 'req_id', e.target.value)}
              />
            ),
          },
          {
            title: '客户 ID (external)', dataIndex: 'external_id', width: 140,
            render: (v, _r, i) => (
              <Input
                value={v || ''}
                size="small"
                variant="borderless"
                placeholder="(可留空)"
                onChange={(e) => handleFieldChange(dataSource[i].__idx, 'external_id', e.target.value)}
              />
            ),
          },
          {
            title: '来源', width: 90,
            render: (_, r) => {
              const st = (r.source_type || 'manual') as Swe1SourceType
              const info = SOURCE_TAG[st]
              return <Tag color={info.color}>{info.text}</Tag>
            },
          },
          {
            title: '模块', dataIndex: 'requirement_module', width: 110,
            render: (v, _r, i) => (
              <Input
                value={v || ''}
                size="small"
                variant="borderless"
                onChange={(e) => handleFieldChange(dataSource[i].__idx, 'requirement_module', e.target.value)}
              />
            ),
          },
          {
            title: '内容', dataIndex: 'content',
            render: (v, _r, i) => (
              <Input.TextArea
                value={v}
                autoSize={{ minRows: 1, maxRows: 4 }}
                size="small"
                variant="borderless"
                onChange={(e) => handleFieldChange(dataSource[i].__idx, 'content', e.target.value)}
              />
            ),
          },
          {
            title: 'ASIL', dataIndex: 'asil', width: 90,
            render: (v, _r, i) => (
              <Select
                value={v || 'QM'}
                size="small"
                variant="borderless"
                style={{ width: '100%' }}
                onChange={(nv) => handleFieldChange(dataSource[i].__idx, 'asil', nv)}
              >
                {['QM', 'ASIL A', 'ASIL B', 'ASIL C', 'ASIL D', 'N/A'].map((a) => (
                  <Option key={a} value={a}>{a}</Option>
                ))}
              </Select>
            ),
          },
          {
            title: '优先级', dataIndex: 'priority', width: 80,
            render: (v, _r, i) => (
              <Select
                value={v || 2}
                size="small"
                variant="borderless"
                style={{ width: '100%' }}
                onChange={(nv) => handleFieldChange(dataSource[i].__idx, 'priority', nv)}
              >
                {[1, 2, 3].map((p) => <Option key={p} value={p}>{p}</Option>)}
              </Select>
            ),
          },
          {
            title: '源文件', dataIndex: 'source_doc', width: 140,
            render: (v) => (
              <Tooltip title={v}>
                <span style={{ fontSize: 12, color: '#888' }}>
                  {v && v.length > 18 ? v.slice(0, 18) + '…' : v || '-'}
                </span>
              </Tooltip>
            ),
          },
          {
            title: '下游组件', width: 130,
            render: (_, r) => {
              const refs = archMap?.get((r.req_id || '').trim())
              if (!refs || refs.length === 0) {
                if (r.review_status === 'note' || r.review_status === 'rejected') {
                  return <span style={{ color: '#bbb', fontSize: 12 }}>—</span>
                }
                return (
                  <Tooltip title="SWE.2 尚未引用此需求">
                    <Tag color="default" style={{ fontSize: 11 }}>未映射</Tag>
                  </Tooltip>
                )
              }
              return (
                <Tooltip
                  title={refs.map((x) => `${x.component_id} ${x.component}`).join('\n')}
                >
                  <Space size={2} wrap>
                    {refs.slice(0, 3).map((x) => (
                      <Tag key={x.component_id + x.component} color="geekblue" style={{ fontSize: 11 }}>
                        {x.component_id}
                      </Tag>
                    ))}
                    {refs.length > 3 && (
                      <Tag color="default" style={{ fontSize: 11 }}>+{refs.length - 3}</Tag>
                    )}
                  </Space>
                </Tooltip>
              )
            },
          },
          {
            title: '操作', width: 70, fixed: 'right',
            render: (_, r, i) => (
              <Popconfirm
                title="删除此需求？"
                onConfirm={() => {
                  const next = requirements.filter((_, idx) => idx !== dataSource[i].__idx)
                  onChange(next)
                }}
              >
                <Button type="link" danger size="small" icon={<DeleteOutlined />} />
              </Popconfirm>
            ),
          },
        ]}
      />
      <style>{`
        .req-row-note td { background: #fafafa !important; color: #999; }
        .req-row-pending td { background: #fffbe6 !important; }
        .req-row-rejected td { background: #fff1f0 !important; text-decoration: line-through; color: #999; }
      `}</style>
    </div>
  )
}
