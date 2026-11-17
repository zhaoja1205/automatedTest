/**
 * SWE.3 第 3 章 模块构成追溯编辑器。
 *
 * 表格：SWE.1 | 需求描述 | SWE.2 | 对应组件 | 功能模块图中的类 | SWE.3
 * 可添加/删除/行内编辑；功能概述 TextArea。
 */
import { Table, Input, Button, Space, Popconfirm, Card } from 'antd'
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons'
import type { Swe3Composition, Swe3CompositionRow } from '../../../types/aspice'

interface Props {
  composition: Swe3Composition
  onChange: (composition: Swe3Composition) => void
}

export default function ModuleCompositionEditor({ composition, onChange }: Props) {
  const rows = composition.composition_rows || []

  const updateRow = (idx: number, field: keyof Swe3CompositionRow, value: string) => {
    const updated = [...rows]
    updated[idx] = { ...updated[idx], [field]: value }
    onChange({ ...composition, composition_rows: updated })
  }

  const addRow = () => {
    onChange({
      ...composition,
      composition_rows: [...rows, {
        swe1_id: '', req_desc: '', swe2_id: '', component: '', classes: '', swe3_ids: '',
      }],
    })
  }

  const deleteRow = (idx: number) => {
    onChange({ ...composition, composition_rows: rows.filter((_, i) => i !== idx) })
  }

  const columns = [
    { title: 'SWE.1', dataIndex: 'swe1_id', key: 'swe1_id', width: 160,
      render: (v: string, _r: Swe3CompositionRow, idx: number) =>
        <Input size="small" value={v} onChange={(e) => updateRow(idx, 'swe1_id', e.target.value)} /> },
    { title: '需求描述', dataIndex: 'req_desc', key: 'req_desc',
      render: (v: string, _r: Swe3CompositionRow, idx: number) =>
        <Input size="small" value={v} onChange={(e) => updateRow(idx, 'req_desc', e.target.value)} /> },
    { title: 'SWE.2', dataIndex: 'swe2_id', key: 'swe2_id', width: 190,
      render: (v: string, _r: Swe3CompositionRow, idx: number) =>
        <Input size="small" value={v} onChange={(e) => updateRow(idx, 'swe2_id', e.target.value)} /> },
    { title: '对应组件', dataIndex: 'component', key: 'component', width: 140,
      render: (v: string, _r: Swe3CompositionRow, idx: number) =>
        <Input size="small" value={v} onChange={(e) => updateRow(idx, 'component', e.target.value)} /> },
    { title: '类', dataIndex: 'classes', key: 'classes', width: 180,
      render: (v: string, _r: Swe3CompositionRow, idx: number) =>
        <Input size="small" value={v} onChange={(e) => updateRow(idx, 'classes', e.target.value)} /> },
    { title: 'SWE.3', dataIndex: 'swe3_ids', key: 'swe3_ids', width: 240,
      render: (v: string, _r: Swe3CompositionRow, idx: number) =>
        <Input size="small" value={v} onChange={(e) => updateRow(idx, 'swe3_ids', e.target.value)} /> },
    { title: '操作', key: 'actions', width: 60,
      render: (_: unknown, _r: Swe3CompositionRow, idx: number) =>
        <Popconfirm title="删除此行？" onConfirm={() => deleteRow(idx)}>
          <Button type="link" size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm> },
  ]

  return (
    <Card size="small">
      <div style={{ marginBottom: 12 }}>
        <div style={{ marginBottom: 4, fontWeight: 500 }}>3.1 功能概述</div>
        <Input.TextArea rows={2} value={composition.function_overview}
          onChange={(e) => onChange({ ...composition, function_overview: e.target.value })} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <div style={{ fontWeight: 500 }}>3.2 模块构成追溯表</div>
        <Space>
          <Button size="small" icon={<PlusOutlined />} onClick={addRow}>添加行</Button>
        </Space>
      </div>
      <Table
        rowKey={(_, idx) => String(idx)}
        columns={columns}
        dataSource={rows}
        pagination={rows.length > 20 ? { pageSize: 20 } : false}
        size="small"
        scroll={{ x: 1100 }}
      />
    </Card>
  )
}
