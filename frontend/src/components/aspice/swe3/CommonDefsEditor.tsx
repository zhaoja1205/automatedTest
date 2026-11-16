/**
 * SWE.3 第 13 章 共通定义编辑器。
 *
 * Tabs：常量 / 变量 / 枚举 / 结构体 / 配置文件。
 * 每类用行内编辑表格；枚举/结构体支持嵌套的值列表字段。
 */
import {
  Tabs, Table, Input, Button, Space, Popconfirm, Card, Tag, Collapse,
} from 'antd'
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons'
import type {
  Swe3CommonDefs, Swe3CommonConstant, Swe3CommonVariable,
  Swe3EnumValue, Swe3Structure, Swe3StructField, Swe3ConfigFile,
} from '../../../types/aspice'

interface Props {
  commonDefs: Swe3CommonDefs
  onChange: (cd: Swe3CommonDefs) => void
}

export default function CommonDefsEditor({ commonDefs, onChange }: Props) {
  // ---- 常量 ----
  const updConst = (idx: number, field: keyof Swe3CommonConstant, val: string) => {
    const updated = [...(commonDefs.constants || [])]
    updated[idx] = { ...updated[idx], [field]: val }
    onChange({ ...commonDefs, constants: updated })
  }
  const addConst = () => onChange({
    ...commonDefs,
    constants: [...(commonDefs.constants || []), { seq: '', name: '', value: '', desc: '' }],
  })
  const delConst = (idx: number) => onChange({
    ...commonDefs,
    constants: (commonDefs.constants || []).filter((_, i) => i !== idx),
  })

  // ---- 变量 ----
  const updVar = (idx: number, field: keyof Swe3CommonVariable, val: string) => {
    const updated = [...(commonDefs.variables || [])]
    updated[idx] = { ...updated[idx], [field]: val }
    onChange({ ...commonDefs, variables: updated })
  }
  const addVar = () => onChange({
    ...commonDefs,
    variables: [...(commonDefs.variables || []),
      { seq: '', name: '', type: '', value: '', desc: '' }],
  })
  const delVar = (idx: number) => onChange({
    ...commonDefs,
    variables: (commonDefs.variables || []).filter((_, i) => i !== idx),
  })

  // ---- 枚举 ----
  const addEnum = () => onChange({
    ...commonDefs,
    enums: [...(commonDefs.enums || []), { name: '', values: [] }],
  })
  const delEnum = (idx: number) => onChange({
    ...commonDefs,
    enums: (commonDefs.enums || []).filter((_, i) => i !== idx),
  })
  const updEnumName = (idx: number, name: string) => {
    const updated = [...(commonDefs.enums || [])]
    updated[idx] = { ...updated[idx], name }
    onChange({ ...commonDefs, enums: updated })
  }
  const addEnumValue = (eIdx: number) => {
    const updated = [...(commonDefs.enums || [])]
    updated[eIdx] = {
      ...updated[eIdx],
      values: [...(updated[eIdx].values || []), { seq: '', value: '', desc: '' }],
    }
    onChange({ ...commonDefs, enums: updated })
  }
  const updEnumValue = (eIdx: number, vIdx: number, field: keyof Swe3EnumValue, val: string) => {
    const updated = [...(commonDefs.enums || [])]
    const vs = [...updated[eIdx].values]
    vs[vIdx] = { ...vs[vIdx], [field]: val }
    updated[eIdx] = { ...updated[eIdx], values: vs }
    onChange({ ...commonDefs, enums: updated })
  }
  const delEnumValue = (eIdx: number, vIdx: number) => {
    const updated = [...(commonDefs.enums || [])]
    updated[eIdx] = {
      ...updated[eIdx],
      values: updated[eIdx].values.filter((_, i) => i !== vIdx),
    }
    onChange({ ...commonDefs, enums: updated })
  }

  // ---- 结构体 ----
  const addStruct = () => onChange({
    ...commonDefs,
    structures: [...(commonDefs.structures || []),
      { name: '', declaration: '', intro: '', fields: [] }],
  })
  const delStruct = (idx: number) => onChange({
    ...commonDefs,
    structures: (commonDefs.structures || []).filter((_, i) => i !== idx),
  })
  const updStruct = (idx: number, field: keyof Swe3Structure, val: any) => {
    const updated = [...(commonDefs.structures || [])]
    updated[idx] = { ...updated[idx], [field]: val }
    onChange({ ...commonDefs, structures: updated })
  }
  const addStructField = (sIdx: number) => {
    const updated = [...(commonDefs.structures || [])]
    updated[sIdx] = {
      ...updated[sIdx],
      fields: [...(updated[sIdx].fields || []), { seq: '', name: '', type: '', desc: '' }],
    }
    onChange({ ...commonDefs, structures: updated })
  }
  const updStructField = (sIdx: number, fIdx: number, field: keyof Swe3StructField, val: string) => {
    const updated = [...(commonDefs.structures || [])]
    const fs = [...updated[sIdx].fields]
    fs[fIdx] = { ...fs[fIdx], [field]: val }
    updated[sIdx] = { ...updated[sIdx], fields: fs }
    onChange({ ...commonDefs, structures: updated })
  }
  const delStructField = (sIdx: number, fIdx: number) => {
    const updated = [...(commonDefs.structures || [])]
    updated[sIdx] = {
      ...updated[sIdx],
      fields: updated[sIdx].fields.filter((_, i) => i !== fIdx),
    }
    onChange({ ...commonDefs, structures: updated })
  }

  // ---- 配置文件 ----
  const updCfg = (idx: number, field: keyof Swe3ConfigFile, val: string) => {
    const updated = [...(commonDefs.config_files || [])]
    updated[idx] = { ...updated[idx], [field]: val }
    onChange({ ...commonDefs, config_files: updated })
  }
  const addCfg = () => onChange({
    ...commonDefs,
    config_files: [...(commonDefs.config_files || []),
      { seq: '', location: '', function: '' }],
  })
  const delCfg = (idx: number) => onChange({
    ...commonDefs,
    config_files: (commonDefs.config_files || []).filter((_, i) => i !== idx),
  })

  return (
    <Tabs
      size="small"
      items={[
        {
          key: 'const', label: `常量 (${(commonDefs.constants || []).length})`,
          children: (
            <Card size="small" extra={<Button size="small" icon={<PlusOutlined />} onClick={addConst}>添加</Button>}>
              <Table rowKey={(_, i) => String(i)} size="small" pagination={false}
                dataSource={commonDefs.constants || []}
                columns={[
                  { title: '序号', dataIndex: 'seq', width: 70,
                    render: (v: string, _r: any, idx: number) =>
                      <Input size="small" value={v} onChange={(e) => updConst(idx, 'seq', e.target.value)} /> },
                  { title: '常量名', dataIndex: 'name', width: 220,
                    render: (v: string, _r: any, idx: number) =>
                      <Input size="small" value={v} onChange={(e) => updConst(idx, 'name', e.target.value)} /> },
                  { title: '值', dataIndex: 'value', width: 120,
                    render: (v: string, _r: any, idx: number) =>
                      <Input size="small" value={v} onChange={(e) => updConst(idx, 'value', e.target.value)} /> },
                  { title: '说明', dataIndex: 'desc',
                    render: (v: string, _r: any, idx: number) =>
                      <Input size="small" value={v} onChange={(e) => updConst(idx, 'desc', e.target.value)} /> },
                  { title: '操作', key: 'actions', width: 60,
                    render: (_: any, _r: any, idx: number) =>
                      <Popconfirm title="删除？" onConfirm={() => delConst(idx)}>
                        <Button type="link" size="small" danger icon={<DeleteOutlined />} />
                      </Popconfirm> },
                ]}
              />
            </Card>
          ),
        },
        {
          key: 'var', label: `变量 (${(commonDefs.variables || []).length})`,
          children: (
            <Card size="small" extra={<Button size="small" icon={<PlusOutlined />} onClick={addVar}>添加</Button>}>
              <Table rowKey={(_, i) => String(i)} size="small" pagination={false}
                dataSource={commonDefs.variables || []}
                columns={[
                  { title: '序号', dataIndex: 'seq', width: 70,
                    render: (v: string, _r: any, idx: number) =>
                      <Input size="small" value={v} onChange={(e) => updVar(idx, 'seq', e.target.value)} /> },
                  { title: '变量名', dataIndex: 'name', width: 220,
                    render: (v: string, _r: any, idx: number) =>
                      <Input size="small" value={v} onChange={(e) => updVar(idx, 'name', e.target.value)} /> },
                  { title: '类型', dataIndex: 'type', width: 140,
                    render: (v: string, _r: any, idx: number) =>
                      <Input size="small" value={v} onChange={(e) => updVar(idx, 'type', e.target.value)} /> },
                  { title: '值', dataIndex: 'value', width: 120,
                    render: (v: string, _r: any, idx: number) =>
                      <Input size="small" value={v} onChange={(e) => updVar(idx, 'value', e.target.value)} /> },
                  { title: '说明', dataIndex: 'desc',
                    render: (v: string, _r: any, idx: number) =>
                      <Input size="small" value={v} onChange={(e) => updVar(idx, 'desc', e.target.value)} /> },
                  { title: '操作', key: 'actions', width: 60,
                    render: (_: any, _r: any, idx: number) =>
                      <Popconfirm title="删除？" onConfirm={() => delVar(idx)}>
                        <Button type="link" size="small" danger icon={<DeleteOutlined />} />
                      </Popconfirm> },
                ]}
              />
            </Card>
          ),
        },
        {
          key: 'enum', label: `枚举 (${(commonDefs.enums || []).length})`,
          children: (
            <Card size="small" extra={<Button size="small" icon={<PlusOutlined />} onClick={addEnum}>添加枚举</Button>}>
              <Collapse size="small"
                items={(commonDefs.enums || []).map((enm, eIdx) => ({
                  key: String(eIdx),
                  label: (
                    <Space>
                      <Tag color="geekblue">Enum</Tag>
                      <Input size="small" style={{ width: 220 }}
                        value={enm.name}
                        onClick={(e) => e.stopPropagation()}
                        onChange={(e) => updEnumName(eIdx, e.target.value)} />
                      <Tag>{enm.values?.length || 0} 值</Tag>
                    </Space>
                  ),
                  extra: (
                    <Popconfirm title="删除此枚举？" onConfirm={() => delEnum(eIdx)}>
                      <Button type="link" size="small" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  ),
                  children: (
                    <>
                      <Button size="small" style={{ marginBottom: 8 }}
                        icon={<PlusOutlined />} onClick={() => addEnumValue(eIdx)}>添加值</Button>
                      <Table rowKey={(_, i) => String(i)} size="small" pagination={false}
                        dataSource={enm.values || []}
                        columns={[
                          { title: '序号', dataIndex: 'seq', width: 70,
                            render: (v: string, _r: any, vIdx: number) =>
                              <Input size="small" value={v} onChange={(e) => updEnumValue(eIdx, vIdx, 'seq', e.target.value)} /> },
                          { title: '枚举值', dataIndex: 'value', width: 240,
                            render: (v: string, _r: any, vIdx: number) =>
                              <Input size="small" value={v} onChange={(e) => updEnumValue(eIdx, vIdx, 'value', e.target.value)} /> },
                          { title: '说明', dataIndex: 'desc',
                            render: (v: string, _r: any, vIdx: number) =>
                              <Input size="small" value={v} onChange={(e) => updEnumValue(eIdx, vIdx, 'desc', e.target.value)} /> },
                          { title: '操作', key: 'actions', width: 60,
                            render: (_: any, _r: any, vIdx: number) =>
                              <Popconfirm title="删除？" onConfirm={() => delEnumValue(eIdx, vIdx)}>
                                <Button type="link" size="small" danger icon={<DeleteOutlined />} />
                              </Popconfirm> },
                        ]}
                      />
                    </>
                  ),
                }))}
              />
            </Card>
          ),
        },
        {
          key: 'struct', label: `结构体 (${(commonDefs.structures || []).length})`,
          children: (
            <Card size="small" extra={<Button size="small" icon={<PlusOutlined />} onClick={addStruct}>添加结构体</Button>}>
              <Collapse size="small"
                items={(commonDefs.structures || []).map((s, sIdx) => ({
                  key: String(sIdx),
                  label: (
                    <Space>
                      <Tag color="purple">Struct</Tag>
                      <Input size="small" style={{ width: 220 }}
                        value={s.name}
                        onClick={(e) => e.stopPropagation()}
                        onChange={(e) => updStruct(sIdx, 'name', e.target.value)} />
                      <Tag>{s.fields?.length || 0} 字段</Tag>
                    </Space>
                  ),
                  extra: (
                    <Popconfirm title="删除此结构体？" onConfirm={() => delStruct(sIdx)}>
                      <Button type="link" size="small" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  ),
                  children: (
                    <>
                      <div style={{ marginBottom: 8 }}>
                        <div style={{ fontWeight: 500 }}>结构体声明</div>
                        <Input value={s.declaration}
                          onChange={(e) => updStruct(sIdx, 'declaration', e.target.value)} />
                        <div style={{ marginTop: 6, fontWeight: 500 }}>结构体介绍</div>
                        <Input.TextArea rows={2} value={s.intro}
                          onChange={(e) => updStruct(sIdx, 'intro', e.target.value)} />
                      </div>
                      <Button size="small" style={{ marginBottom: 8 }}
                        icon={<PlusOutlined />} onClick={() => addStructField(sIdx)}>添加字段</Button>
                      <Table rowKey={(_, i) => String(i)} size="small" pagination={false}
                        dataSource={s.fields || []}
                        columns={[
                          { title: '字段', dataIndex: 'name', width: 200,
                            render: (v: string, _r: any, fIdx: number) =>
                              <Input size="small" value={v} onChange={(e) => updStructField(sIdx, fIdx, 'name', e.target.value)} /> },
                          { title: '类型', dataIndex: 'type', width: 160,
                            render: (v: string, _r: any, fIdx: number) =>
                              <Input size="small" value={v} onChange={(e) => updStructField(sIdx, fIdx, 'type', e.target.value)} /> },
                          { title: '说明', dataIndex: 'desc',
                            render: (v: string, _r: any, fIdx: number) =>
                              <Input size="small" value={v} onChange={(e) => updStructField(sIdx, fIdx, 'desc', e.target.value)} /> },
                          { title: '操作', key: 'actions', width: 60,
                            render: (_: any, _r: any, fIdx: number) =>
                              <Popconfirm title="删除？" onConfirm={() => delStructField(sIdx, fIdx)}>
                                <Button type="link" size="small" danger icon={<DeleteOutlined />} />
                              </Popconfirm> },
                        ]}
                      />
                    </>
                  ),
                }))}
              />
            </Card>
          ),
        },
        {
          key: 'cfg', label: `配置文件 (${(commonDefs.config_files || []).length})`,
          children: (
            <Card size="small" extra={<Button size="small" icon={<PlusOutlined />} onClick={addCfg}>添加</Button>}>
              <Table rowKey={(_, i) => String(i)} size="small" pagination={false}
                dataSource={commonDefs.config_files || []}
                columns={[
                  { title: '序号', dataIndex: 'seq', width: 70,
                    render: (v: string, _r: any, idx: number) =>
                      <Input size="small" value={v} onChange={(e) => updCfg(idx, 'seq', e.target.value)} /> },
                  { title: '位置', dataIndex: 'location', width: 280,
                    render: (v: string, _r: any, idx: number) =>
                      <Input size="small" value={v} onChange={(e) => updCfg(idx, 'location', e.target.value)} /> },
                  { title: '功能', dataIndex: 'function',
                    render: (v: string, _r: any, idx: number) =>
                      <Input size="small" value={v} onChange={(e) => updCfg(idx, 'function', e.target.value)} /> },
                  { title: '操作', key: 'actions', width: 60,
                    render: (_: any, _r: any, idx: number) =>
                      <Popconfirm title="删除？" onConfirm={() => delCfg(idx)}>
                        <Button type="link" size="small" danger icon={<DeleteOutlined />} />
                      </Popconfirm> },
                ]}
              />
            </Card>
          ),
        },
      ]}
    />
  )
}
