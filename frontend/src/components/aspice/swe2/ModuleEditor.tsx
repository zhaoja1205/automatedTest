/**
 * SWE.2 §4 组件详细设计（4.X）单模块编辑面板（Phase 4 Group 5）。
 *
 * 1 个 ModuleEditor = AspiceComponent 一行的完整编辑器（4.X.1 功能描述、
 * 4.X.2.1 外部接口、4.X.2.2 内部接口、4.X.3 场景，Camera Module 还有 4.4.2 类）。
 *
 * 特殊约定：
 *   - A005 nvsipl_camera / A006 nvsipl_multicast → 功能描述走 "function_desc_segments" 多段编辑；
 *   - A004 Camera Module → 显示"类列表"（classes）；
 *   - A008 Camera Security → **manual_only**：不显示任何 "AI 生成" 按钮（后端 generator 也不会碰）。
 *
 * AI 生成按钮本推送仅挂占位（onClick 走 message.info）；后续推送在接通 SWE.2 AI 侧时填实。
 */
import { useMemo } from 'react'
import {
  Alert, Button, Card, Collapse, Input, Select, Space, Table, Tag, message,
} from 'antd'
import { DeleteOutlined, PlusOutlined, RobotOutlined } from '@ant-design/icons'
import type {
  AspiceComponent,
  InterfaceItem,
  ClassItem,
  ScenarioItem,
  FunctionDescSegment,
} from '../../../types/aspice'
import { useAspiceStore } from '../../../stores/useAspiceStore'
import { ModuleCard } from '../swe3/ModulePathConfigEditor'
import InterfacePickerFromScan from './InterfacePickerFromScan'

/** nvsipl_* 模块启用多段功能描述。 */
const MULTI_SEG_IDS = new Set(['A005', 'A006'])
/** Camera Security 走 manual_only，所有 AI 按钮一律不显示。 */
const MANUAL_ONLY_IDS = new Set(['A008'])
/** Camera Module 独占 "4.4.2 类" 栏目。 */
const HAS_CLASSES_IDS = new Set(['A004'])

interface Props {
  component: AspiceComponent
  onChange: (v: AspiceComponent) => void
  /** SWE.1 已有的 requirement ID（供 linked_req_ids 下拉）。 */
  reqIds?: string[]
}

export default function ModuleEditor({ component: c, onChange, reqIds = [] }: Props) {
  const patch = (p: Partial<AspiceComponent>) => onChange({ ...c, ...p })

  const isMultiSeg = MULTI_SEG_IDS.has(c.id)
  const isManualOnly = MANUAL_ONLY_IDS.has(c.id)
  const hasClasses = HAS_CLASSES_IDS.has(c.id)

  // ---- 代码路径配置（与 SWE.3 共享 push_d.module_code_sources） ----
  const {
    projectId, aspice, setSwe3ModuleCodeSource, setSwe3ScanIndex,
  } = useAspiceStore()
  const push_d = aspice?.swe3?.push_d
  const codeSrc = push_d?.module_code_sources?.find((m) => m.component_id === c.id)
  // SWE.3 已登记的同 id 模块 → slug/name 以 SWE.3 为准（二者 component_id 一致）；
  // 没有就用 SWE.2 这边的 name 当 slug 兜底（guessPathPatterns 会按 slug 推测模式）。
  const swe3Mod = aspice?.swe3?.modules?.find((m) => m.component_id === c.id)
  const slug = swe3Mod?.slug || c.name || c.id
  const modInfo = { component_id: c.id, slug, name: c.name || swe3Mod?.name || c.id }

  // 4.X.1 功能描述（两种模式二选一视图）
  const segments: FunctionDescSegment[] = c.function_desc_segments || []
  const addSegment = () => patch({
    function_desc_segments: [...segments, { title: '', description: '', linked_req_ids: [] }],
  })
  const patchSegment = (idx: number, p: Partial<FunctionDescSegment>) => patch({
    function_desc_segments: segments.map((s, i) => i === idx ? { ...s, ...p } : s),
  })
  const delSegment = (idx: number) => patch({
    function_desc_segments: segments.filter((_, i) => i !== idx),
  })

  // 4.X.2 接口通用列（和 SoftwareDesignEditor 保持一致）
  const ifaceColumns = (
    list: InterfaceItem[],
    setList: (v: InterfaceItem[]) => void,
  ) => [
    { title: '来源', dataIndex: 'source', width: 120,
      render: (t: string, _: InterfaceItem, idx: number) => (
        <Input size="small" value={t}
          onChange={(e) => setList(list.map((r, i) => i === idx ? { ...r, source: e.target.value } : r))} />
      ) },
    { title: '方法名', dataIndex: 'method', width: 180,
      render: (t: string, _: InterfaceItem, idx: number) => (
        <Input size="small" value={t}
          onChange={(e) => setList(list.map((r, i) => i === idx ? { ...r, method: e.target.value } : r))} />
      ) },
    { title: '类型', dataIndex: 'type', width: 110,
      render: (t: InterfaceItem['type'], _: InterfaceItem, idx: number) => (
        <Select<InterfaceItem['type']> size="small" value={t} style={{ width: 100 }}
          options={[{ value: '外部接口', label: '外部接口' }, { value: '内部接口', label: '内部接口' }]}
          onChange={(v) => setList(list.map((r, i) => i === idx ? { ...r, type: v } : r))} />
      ) },
    { title: '参数', dataIndex: 'params',
      render: (t: string, _: InterfaceItem, idx: number) => (
        <Input.TextArea size="small" rows={1} value={t}
          onChange={(e) => setList(list.map((r, i) => i === idx ? { ...r, params: e.target.value } : r))} />
      ) },
    { title: '说明', dataIndex: 'description',
      render: (t: string, _: InterfaceItem, idx: number) => (
        <Input size="small" value={t}
          onChange={(e) => setList(list.map((r, i) => i === idx ? { ...r, description: e.target.value } : r))} />
      ) },
    { title: '', width: 50,
      render: (_: unknown, __: InterfaceItem, idx: number) => (
        <Button type="link" size="small" danger icon={<DeleteOutlined />}
          onClick={() => setList(list.filter((_r, i) => i !== idx))} />
      ) },
  ]

  const ext = c.external_interfaces || []
  const int = c.internal_interfaces || []
  const classes = c.classes || []
  const scenarios = c.scenarios || []

  const scenarioColumns = [
    { title: '类型', dataIndex: 'kind', width: 110,
      render: (t: ScenarioItem['kind'], _: ScenarioItem, idx: number) => (
        <Select<ScenarioItem['kind']> size="small" value={t} style={{ width: 100 }}
          options={[{ value: '状态迁移', label: '状态迁移' }, { value: '时序', label: '时序' }]}
          onChange={(v) => patch({
            scenarios: scenarios.map((s, i) => i === idx ? { ...s, kind: v } : s),
          })} />
      ) },
    { title: '标题', dataIndex: 'title', width: 180,
      render: (t: string, _: ScenarioItem, idx: number) => (
        <Input size="small" value={t}
          onChange={(e) => patch({
            scenarios: scenarios.map((s, i) => i === idx ? { ...s, title: e.target.value } : s),
          })} />
      ) },
    { title: '说明', dataIndex: 'description',
      render: (t: string, _: ScenarioItem, idx: number) => (
        <Input size="small" value={t}
          onChange={(e) => patch({
            scenarios: scenarios.map((s, i) => i === idx ? { ...s, description: e.target.value } : s),
          })} />
      ) },
    { title: 'PlantUML', dataIndex: 'plantuml',
      render: (t: string, _: ScenarioItem, idx: number) => (
        <Input.TextArea size="small" rows={2} value={t} placeholder="@startuml ... @enduml"
          onChange={(e) => patch({
            scenarios: scenarios.map((s, i) => i === idx ? { ...s, plantuml: e.target.value } : s),
          })} />
      ) },
    { title: '', width: 50,
      render: (_: unknown, __: ScenarioItem, idx: number) => (
        <Button type="link" size="small" danger icon={<DeleteOutlined />}
          onClick={() => patch({ scenarios: scenarios.filter((_r, i) => i !== idx) })} />
      ) },
  ]

  const classColumns = [
    { title: '#', dataIndex: 'seq', width: 50,
      render: (t: number, _: ClassItem, idx: number) => (
        <Input size="small" type="number" value={t}
          onChange={(e) => patch({
            classes: classes.map((r, i) => i === idx ? { ...r, seq: Number(e.target.value) } : r),
          })} />
      ) },
    { title: '类名', dataIndex: 'class_name', width: 220,
      render: (t: string, _: ClassItem, idx: number) => (
        <Input size="small" value={t}
          onChange={(e) => patch({
            classes: classes.map((r, i) => i === idx ? { ...r, class_name: e.target.value } : r),
          })} />
      ) },
    { title: '说明', dataIndex: 'description',
      render: (t: string, _: ClassItem, idx: number) => (
        <Input size="small" value={t}
          onChange={(e) => patch({
            classes: classes.map((r, i) => i === idx ? { ...r, description: e.target.value } : r),
          })} />
      ) },
    { title: '', width: 50,
      render: (_: unknown, __: ClassItem, idx: number) => (
        <Button type="link" size="small" danger icon={<DeleteOutlined />}
          onClick={() => patch({ classes: classes.filter((_r, i) => i !== idx) })} />
      ) },
  ]

  // AI 按钮占位：Camera Security 不出
  const aiButton = (label: string) => isManualOnly ? null : (
    <Button size="small" icon={<RobotOutlined />}
      onClick={() => message.info(`${label}：AI 生成功能在下一推送接入`)}>
      {label}
    </Button>
  )

  const linkedIds = c.linked_req_ids || []
  const reqOptions = useMemo(
    () => reqIds.map((id) => ({ value: id, label: id })),
    [reqIds],
  )

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="middle">
      {isManualOnly && (
        <Alert type="warning" showIcon
          message="Camera Security 走 manual_only 模式"
          description="按 PreDev 规范，该章节完全由人工维护，不触发 AI 生成、不扫描工程代码。" />
      )}

      <Collapse size="small" defaultActiveKey={['desc', 'iface']}
        items={[
          {
            key: 'desc',
            label: `4.X.1 功能描述${isMultiSeg ? `（多段 ${segments.length}）` : ''}`,
            extra: aiButton('AI 补功能描述'),
            children: isMultiSeg ? (
              <Space direction="vertical" style={{ width: '100%' }}>
                {segments.map((seg, i) => (
                  <Card key={i} size="small" type="inner"
                    title={
                      <Space>
                        <Tag color="geekblue">段 #{i + 1}</Tag>
                        <Input size="small" value={seg.title} placeholder="段标题"
                          style={{ width: 240 }}
                          onChange={(e) => patchSegment(i, { title: e.target.value })} />
                      </Space>
                    }
                    extra={<Button size="small" danger icon={<DeleteOutlined />}
                      onClick={() => delSegment(i)} />}>
                    <Input.TextArea rows={3} value={seg.description} placeholder="段正文"
                      style={{ marginBottom: 8 }}
                      onChange={(e) => patchSegment(i, { description: e.target.value })} />
                    <Select<string[]> mode="multiple" style={{ width: '100%' }}
                      placeholder="溯源 SWE.2 ID（可多选）"
                      value={seg.linked_req_ids}
                      options={reqOptions}
                      onChange={(v) => patchSegment(i, { linked_req_ids: v })} />
                  </Card>
                ))}
                <Button size="small" icon={<PlusOutlined />} onClick={addSegment} block>
                  追加段
                </Button>
              </Space>
            ) : (
              <Space direction="vertical" style={{ width: '100%' }}>
                <Input.TextArea rows={4} value={c.function_desc || ''}
                  placeholder="4.X.1 功能描述正文"
                  onChange={(e) => patch({ function_desc: e.target.value })} />
                <Select<string[]> mode="multiple" style={{ width: '100%' }}
                  placeholder="溯源 SWE.2 ID（可多选）"
                  value={linkedIds}
                  options={reqOptions}
                  onChange={(v) => patch({ linked_req_ids: v })} />
              </Space>
            ),
          },
          {
            key: 'iface',
            label: `4.X.2 接口（外部 ${ext.length} / 内部 ${int.length}）`,
            extra: aiButton('AI 补接口'),
            children: (
              <Space direction="vertical" style={{ width: '100%' }} size="small">
                {!isManualOnly && (
                  <>
                    <Alert type="info" showIcon
                      message="接口来源：工程代码扫描 + 用户三态勾选"
                      description={
                        <>
                          1) 在下方「代码路径配置」卡片填 glob 规则 → 点「扫描本模块」；<br />
                          2) 底部表格列出该模块每个函数的 diff 状态，用户选「外部 / 内部 / 忽略」；<br />
                          3) 点「应用到接口表」→ 填进 4.X.2.1 / 4.X.2.2；原有手填条目保留，description 留白等 AI 补。<br />
                          路径配置与 SWE.3 共享（<code>push_d.module_code_sources</code>），任一处修改两边同步。
                        </>
                      } />
                    <ModuleCard mod={modInfo} src={codeSrc} projectId={projectId}
                      onSrcChange={(ns) => setSwe3ModuleCodeSource(c.id, ns)}
                      onScanned={(idx) => setSwe3ScanIndex(c.id, idx)} />
                    <InterfacePickerFromScan component={c} onChange={onChange} />
                  </>
                )}
                <Card size="small" title="4.X.2.1 外部接口"
                  extra={<Button size="small" icon={<PlusOutlined />}
                    onClick={() => patch({
                      external_interfaces: [...ext,
                        { source: '', method: '', type: '外部接口', params: '', description: '' }],
                    })}>添加</Button>}>
                  <Table rowKey={(_, idx) => `ext-${idx}`} size="small" pagination={false}
                    dataSource={ext}
                    columns={ifaceColumns(ext, (v) => patch({ external_interfaces: v }))} />
                </Card>
                <Card size="small" title="4.X.2.2 内部接口"
                  extra={<Button size="small" icon={<PlusOutlined />}
                    onClick={() => patch({
                      internal_interfaces: [...int,
                        { source: '', method: '', type: '内部接口', params: '', description: '' }],
                    })}>添加</Button>}>
                  <Table rowKey={(_, idx) => `int-${idx}`} size="small" pagination={false}
                    dataSource={int}
                    columns={ifaceColumns(int, (v) => patch({ internal_interfaces: v }))} />
                </Card>
              </Space>
            ),
          },
          ...(hasClasses ? [{
            key: 'classes',
            label: `4.4.2 类列表（${classes.length}）`,
            extra: aiButton('AI 补类'),
            children: (
              <Card size="small"
                extra={<Button size="small" icon={<PlusOutlined />}
                  onClick={() => patch({
                    classes: [...classes, { seq: classes.length + 1, class_name: '', description: '' }],
                  })}>添加类</Button>}>
                <Table rowKey={(_, idx) => `cls-${idx}`} size="small" pagination={false}
                  dataSource={classes} columns={classColumns} />
              </Card>
            ),
          }] : []),
          {
            key: 'scenarios',
            label: `4.X.3 场景（${scenarios.length}）`,
            extra: aiButton('AI 补场景'),
            children: (
              <Card size="small"
                extra={<Button size="small" icon={<PlusOutlined />}
                  onClick={() => patch({
                    scenarios: [...scenarios, { kind: '状态迁移', title: '', description: '', plantuml: '' }],
                  })}>添加场景</Button>}>
                <Table rowKey={(_, idx) => `sc-${idx}`} size="small" pagination={false}
                  dataSource={scenarios} columns={scenarioColumns} />
              </Card>
            ),
          },
          ...(isManualOnly ? [{
            key: 'security',
            label: '4.8.X Camera Security 专有字段',
            children: (
              <Space direction="vertical" style={{ width: '100%' }}>
                <Input.TextArea rows={2} value={c.security_goals || ''}
                  placeholder="安全目标（Security Goals）"
                  onChange={(e) => patch({ security_goals: e.target.value })} />
                <Input.TextArea rows={2} value={c.security_modules || ''}
                  placeholder="安全模块（Security Modules）"
                  onChange={(e) => patch({ security_modules: e.target.value })} />
              </Space>
            ),
          }] : []),
        ]} />
    </Space>
  )
}
