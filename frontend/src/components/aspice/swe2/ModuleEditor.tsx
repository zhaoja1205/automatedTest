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
  Alert, Button, Card, Collapse, Input, Radio, Select, Space, Switch,
  Tag, Tooltip, message,
} from 'antd'
import {
  DeleteOutlined, PlusOutlined, RobotOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
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
import PaginatedTable from './PaginatedTable'
import { aiGenerateFunctionBriefs } from '../../../api/aspiceApi'
import type { FuncBriefTarget } from '../../../api/aspiceApi'

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
    { title: (
        <Tooltip title="一句话函数功能简介（做什么 + 产物/副作用），不要写返回类型签名。例：初始化 serializer 并校验 PID。">
          <span>说明 <span style={{ color: '#999', fontSize: 11 }}>ⓘ</span></span>
        </Tooltip>
      ), dataIndex: 'description',
      render: (t: string, _: InterfaceItem, idx: number) => (
        <Input size="small" value={t}
          placeholder="一句话函数功能（不写返回类型）"
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

  /**
   * AI 补全接口表"说明"列 —— 一键整表。
   *
   * 策略固定 `only_returns_or_empty`：只覆盖 `[returns: xxx]` 或空的行，
   * 用户手填内容不动。回填后调 onChange 触发脏标。
   *
   * 并发安全：请求期间用户可能增删行 / 改别的字段。回填时**不能**用点击那一刻
   * 的 list 快照 `setList(next)`，否则新加的行会被吞。改法：row_id 用
   * `函数名|来源` 这种稳定键（不依赖行号），回填时把回调改成"基于最新 state 合并"。
   */
  const fillInterfaceBriefs = async (
    field: 'external_interfaces' | 'internal_interfaces',
    tag: string,
  ) => {
    if (!projectId) {
      message.warning('项目未就绪')
      return
    }
    const list: InterfaceItem[] = (c[field] || []) as InterfaceItem[]
    if (!list.length) return

    const returnsPat = /^\s*\[returns\s*:\s*([^\]]*)\]\s*$/i
    // 稳定键：同一张表里 方法名+接口溯源 基本唯一；重复的加 #n 后缀
    const seen = new Map<string, number>()
    const stableKey = (it: InterfaceItem) => {
      const base = `${it.method || ''}@@${it.source || ''}`
      const n = seen.get(base) || 0
      seen.set(base, n + 1)
      return n === 0 ? base : `${base}#${n}`
    }
    const keyOf: string[] = list.map(stableKey)

    const targets: FuncBriefTarget[] = list.map((it, idx) => {
      const m = (it.description || '').match(returnsPat)
      return {
        row_id: keyOf[idx],
        function: it.method || '',
        returns: m ? (m[1] || '').trim() : '',
        params: it.params || '',
        source_path: it.source || '',
        current_description: it.description || '',
      }
    })

    const msgKey = `fill-briefs-${c.id}-${tag}`
    const hide = message.loading({ content: `AI 生成${tag}说明…`, key: msgKey, duration: 0 })
    try {
      const resp = await aiGenerateFunctionBriefs(projectId, targets, 'only_returns_or_empty')
      const { results, skipped, _tokens, _cache_hits, _errors } = resp.data
      const briefByKey: Record<string, string> = {}
      for (const r of results) if (r.ok && r.brief) briefByKey[r.row_id] = r.brief

      // 回填：基于最新组件状态，按稳定键匹配
      let filled = 0
      const latest: InterfaceItem[] = (c[field] || []) as InterfaceItem[]
      const seen2 = new Map<string, number>()
      const next = latest.map((it) => {
        const base = `${it.method || ''}@@${it.source || ''}`
        const n = seen2.get(base) || 0
        seen2.set(base, n + 1)
        const k = n === 0 ? base : `${base}#${n}`
        const brief = briefByKey[k]
        if (!brief) return it
        // 只有当前值仍为 [returns:*] 或空才写（用户期间手填了就尊重）
        const cur = (it.description || '').trim()
        if (cur && !returnsPat.test(cur)) return it
        filled += 1
        return { ...it, description: brief }
      })
      if (filled > 0) onChange({ ...c, [field]: next })
      hide()
      const errMsg = _errors && _errors.length ? `，${_errors.length} 批失败` : ''
      if (filled > 0) {
        message.success(
          `${tag}：${filled} 行已补 / ${skipped.length} 跳过（手填保留） ` +
          `/ 缓存命中 ${_cache_hits}${_tokens ? ` / tokens ${_tokens}` : ''}${errMsg}`,
        )
      } else {
        message.info(`${tag}：无变化（行已被你手填或已删除）`)
      }
    } catch (e: any) {
      hide()
      message.error(e?.response?.data?.detail || e?.message || 'AI 生成失败')
    }
  }

  /** 接口表上方"[AI 补说明]"按钮；isManualOnly 不出。 */
  const aiBriefButton = (
    field: 'external_interfaces' | 'internal_interfaces',
    tag: string,
  ) => {
    if (isManualOnly) return null
    const list = (c[field] || []) as InterfaceItem[]
    const needCount = list.filter((it) => {
      const d = (it.description || '').trim()
      return !d || /^\s*\[returns\s*:/i.test(d)
    }).length
    return (
      <Tooltip title={
        needCount
          ? `只覆盖"[returns: xxx]"或空的 ${needCount} 行，用户手填的保留`
          : '没有需要 AI 补全的行（都已手填）'
      }>
        <Button size="small" type="primary" ghost
          icon={<ThunderboltOutlined />}
          disabled={!needCount || !list.length}
          onClick={() => fillInterfaceBriefs(field, tag)}>
          AI 补"说明"列 ({needCount})
        </Button>
      </Tooltip>
    )
  }

  const linkedIds = c.linked_req_ids || []
  const reqOptions = useMemo(
    () => reqIds.map((id) => ({ value: id, label: id })),
    [reqIds],
  )

  // §4.X 是否参与导出（enabled=false 时整章在 docx 里不出）。
  // 旧项目 c.enabled 可能 undefined，当成 true 走兜底。
  const enabled = c.enabled !== false

  // A008 Camera Security 三态：full / manual_brief / disabled
  // UI 上把 "disabled" 映射成 "enabled=false"：用户选 disabled 的语义就是
  // "本项目不需要 Camera Security" ——等价于把 §4.8 整块关掉。
  const securityMode: 'full' | 'manual_brief' = (c.security_mode as 'full' | 'manual_brief') || 'full'

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="middle">
      {/* §4.X 启用开关 —— 关掉以后整章（标题+表+时序图）不参与导出 */}
      <Card size="small" style={{ background: enabled ? undefined : '#fff1f0' }}>
        <Space wrap>
          <Tag color={enabled ? 'green' : 'red'}>
            §4.{c.id.slice(-1)} {enabled ? '启用' : '已关闭'}
          </Tag>
          <Tooltip title={
            '关闭后整个 §4.X 模块（标题 + 接口表 + 时序图）不会出现在导出文档里。'
            + '适用于项目实际不包含此模块的场景（例如没有外部 PMIC、或项目不含 Camera Security）。'
          }>
            <Switch size="small" checked={enabled}
              checkedChildren="启用" unCheckedChildren="跳过"
              onChange={(v) => patch({ enabled: v })} />
          </Tooltip>
          <span style={{ color: '#888', fontSize: 12 }}>
            {enabled
              ? '按正常流程导出本章。'
              : '本模块将从导出的软件架构&概要设计书中跳过，前端数据仍保留以备启用。'}
          </span>
        </Space>
      </Card>

      {/* A008 Camera Security 三态策略 */}
      {isManualOnly && enabled && (
        <Card size="small"
          title={<Space><Tag color="volcano">§4.8</Tag><span>Camera Security 渲染策略</span></Space>}>
          <Space direction="vertical" style={{ width: '100%' }}>
            <Radio.Group
              value={securityMode}
              onChange={(e) => patch({ security_mode: e.target.value })}
              optionType="button"
              buttonStyle="solid"
              options={[
                { value: 'full',         label: '完整 (§4.8.1–§4.8.5 全出)' },
                { value: 'manual_brief', label: '简述 (仅功能描述 + 安全目标)' },
              ]}
            />
            <span style={{ color: '#888', fontSize: 12 }}>
              {securityMode === 'full'
                ? '安全性目标 / 功能模块构成 / 接口表 / 时序图 全部渲染。'
                : '仅渲染 §4.8.1 功能描述 + §4.8.2 安全性目标，其余子节（§4.8.3/§4.8.4/§4.8.5）从文档隐藏。适用于安全描述未落地、仅需保留纲要的项目。'}
            </span>
            <span style={{ color: '#d46b08', fontSize: 12 }}>
              若本项目完全不涉及 Camera Security，请直接在上方把 §4.8 整体关掉，无需在此选择。
            </span>
          </Space>
        </Card>
      )}

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
                <PaginatedTable<InterfaceItem>
                  title="4.X.2.1 外部接口"
                  rows={ext}
                  columns={ifaceColumns(ext, (v) => patch({ external_interfaces: v }))}
                  onAdd={() => patch({
                    external_interfaces: [...ext,
                      { source: '', method: '', type: '外部接口', params: '', description: '' }],
                  })}
                  rowKeyPrefix="ext"
                  searchFields={['source', 'method', 'params', 'description']}
                  extraActions={aiBriefButton('external_interfaces', '外部接口')}
                />
                <PaginatedTable<InterfaceItem>
                  title="4.X.2.2 内部接口"
                  rows={int}
                  columns={ifaceColumns(int, (v) => patch({ internal_interfaces: v }))}
                  onAdd={() => patch({
                    internal_interfaces: [...int,
                      { source: '', method: '', type: '内部接口', params: '', description: '' }],
                  })}
                  rowKeyPrefix="int"
                  searchFields={['source', 'method', 'params', 'description']}
                  extraActions={aiBriefButton('internal_interfaces', '内部接口')}
                />
              </Space>
            ),
          },
          ...(hasClasses ? [{
            key: 'classes',
            label: `4.4.2 类列表（${classes.length}）`,
            extra: aiButton('AI 补类'),
            children: (
              <PaginatedTable<ClassItem>
                title="4.4.2 类描述"
                rows={classes}
                columns={classColumns}
                onAdd={() => patch({
                  classes: [...classes, { seq: classes.length + 1, class_name: '', description: '' }],
                })}
                rowKeyPrefix="cls"
                searchFields={['class_name', 'description']}
              />
            ),
          }] : []),
          {
            key: 'scenarios',
            label: `4.X.3 场景（${scenarios.length}）`,
            extra: aiButton('AI 补场景'),
            children: (
              <PaginatedTable<ScenarioItem>
                title="4.X.3 场景（状态迁移 / 时序）"
                rows={scenarios}
                columns={scenarioColumns}
                onAdd={() => patch({
                  scenarios: [...scenarios, { kind: '状态迁移', title: '', description: '', plantuml: '' }],
                })}
                rowKeyPrefix="sc"
                searchFields={['title', 'description', 'plantuml']}
              />
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
