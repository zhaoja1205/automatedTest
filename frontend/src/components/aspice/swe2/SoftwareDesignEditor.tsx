/**
 * SWE.2 §3 软件设计 面板（Phase 4 Group 5）。
 *
 * 字段结构见 types/aspice.ts: Swe2SoftwareDesign。
 * 本组件只做编辑容器，骨架实现：
 *   - 3.1 简介：textarea
 *   - 3.2 模块图：PlantUML 编辑 + 占位按钮（后续接 PlantUML 预览）
 *   - 3.3.1 / 3.3.2 接口表：InterfaceItem 增删改
 *   - 3.3.3 配置文件：目录下拉占位 + 平台/模组/sensor/eeprom/crypto 预览区（尚未接后端扫描）
 *   - 3.4.1 状态迁移 / 3.4.2 时序：ScenarioItem[] 简表（PlantUML 字段占位）
 *
 * TODO（后续推送）：
 *   - 3.3.1/3.3.2 接入"从 scan 导入"按钮
 *   - 3.3.3 接入 discover_query_dirs + parse_config_db（见 §2.5 流程）
 *   - PlantUML 预览组件统一复用 SWE.3 已成熟的渲染
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert, Button, Card, Collapse, Input, Select, Space, Table, Tag, message,
} from 'antd'
import { DeleteOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import type {
  Swe2SoftwareDesign,
  InterfaceItem,
  ScenarioItem,
  ConfigDatabase,
  ConfigDbSensor,
  ConfigDbSensorField,
} from '../../../types/aspice'
import { useAspiceStore } from '../../../stores/useAspiceStore'
import { discoverConfigDb, parseConfigDb } from '../../../api/aspiceApi'

// 与后端 arch_sections 对齐的 PreDev 参考文案。
// 后端 default_software_design() 也会在空白时自动回落到这些段，前端这里给用户一键"回落到默认"用。
const DEFAULT_EXTERNAL_IFACE_INTRO =
  '外部接口（External Interface）指本软件向外部组件（上层应用、HAL、OS、NV 框架等）暴露、或从外部组件调用的接口。包括：\n'
  + '  • 本软件向 NV 框架注册的回调（如 NvSIPL Device Block 驱动的生命周期入口）；\n'
  + '  • 本软件通过 NV 框架消费的 API（NvSIPL Camera / Multicast）；\n'
  + '  • 本软件对外暴露给集成测试 / 应用层的辅助接口。\n'
  + '注：具体函数清单按模块归在 §4.X.2.1 下，本节仅给出跨模块的统一定义。'

const DEFAULT_INTERNAL_IFACE_INTRO =
  '内部接口（Internal Interface）指本软件内部各模块之间相互调用的接口，不对外暴露。典型形式：\n'
  + '  • Camera Module 聚合 Serializer / Deserializer / EEPROM / PMIC 驱动，通过内部 handle / 回调完成协同；\n'
  + '  • Camera Security 的三级认证模块与 EEPROM、Camera Module 的协作调用。\n'
  + '注：具体函数清单按模块归在 §4.X.2.2 下，本节仅给出跨模块的统一定义。'

const DEFAULT: Swe2SoftwareDesign = {
  intro: '',
  module_diagram_plantuml: '',
  external_iface_intro: '',
  internal_iface_intro: '',
  external_interfaces: [],
  internal_interfaces: [],
  config_files: {
    database_path: '',
    description: '',
    modules: [],
    sensors: [],
    eeproms: [],
    diagram_plantuml: '',
  } as ConfigDatabase,
  state_diagrams: [],
  sequence_diagrams: [],
}

interface Props {
  value?: Swe2SoftwareDesign
  onChange: (v: Swe2SoftwareDesign) => void
}

export default function SoftwareDesignEditor({ value, onChange }: Props) {
  const sd = useMemo<Swe2SoftwareDesign>(() => ({ ...DEFAULT, ...(value || {}) }), [value])

  const patch = (p: Partial<Swe2SoftwareDesign>) => onChange({ ...sd, ...p })
  const patchConfig = (p: Partial<ConfigDatabase>) =>
    patch({ config_files: { ...sd.config_files, ...p } })

  // ---- §3.3.3 候选 database 目录扫描（Phase 4 Group 3） ----
  const { projectId } = useAspiceStore()
  const [candidates, setCandidates] = useState<string[]>([])
  const [engReady, setEngReady] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [manual, setManual] = useState(false)  // true=手动兜底模式（Input）

  const refreshCandidates = useCallback(async () => {
    if (!projectId) return
    setScanning(true)
    try {
      const res = await discoverConfigDb(projectId)
      setCandidates(res.data.candidates)
      setEngReady(res.data.engineering_ready)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '扫描失败')
    } finally {
      setScanning(false)
    }
  }, [projectId])

  // 首次挂载 / projectId 变化时扫一次；之后只响应用户点"重新扫描"或上传完成
  useEffect(() => { void refreshCandidates() }, [refreshCandidates])

  // 当前 database_path 不在候选里 → 自动切换到手动输入，避免 Select 显示空
  const databasePath = sd.config_files.database_path
  const inCandidates = !databasePath || candidates.includes(databasePath)
  const manualEffective = manual || !inCandidates

  // ---- §3.3.3 后端 parse 自动触发（A2） ----
  // database_path 变化 → 800ms 节流 → 调 parseConfigDb → 回填 config_files 的
  // platform / modules / sensors / eeproms / crypto（保留 database_path /
  // description / diagram_plantuml，用户手改的那三项不被覆盖）。
  const [parsing, setParsing] = useState(false)
  const [parseError, setParseError] = useState<string>('')

  const doParse = useCallback(async (p: string) => {
    if (!projectId || !p) return
    setParsing(true)
    setParseError('')
    try {
      const res = await parseConfigDb(projectId, p)
      const d = res.data
      // 用户手改的三项（path / 总述 / 关系图）保留，其余以后端解析为准
      patchConfig({
        platform: d.platform,
        modules: d.modules || [],
        sensors: d.sensors || [],
        eeproms: d.eeproms || [],
        crypto: d.crypto,
      })
    } catch (e: any) {
      setParseError(e?.response?.data?.detail || '解析失败')
    } finally {
      setParsing(false)
    }
  }, [projectId])  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!databasePath) return
    const t = setTimeout(() => { void doParse(databasePath) }, 800)
    return () => clearTimeout(t)
  }, [databasePath, doParse])

  // ---- 3.3.1 / 3.3.2 接口表通用列 ----
  const ifaceColumns = (
    list: InterfaceItem[],
    setList: (v: InterfaceItem[]) => void,
  ) => [
    { title: '来源', dataIndex: 'source', width: 140,
      render: (t: string, _: InterfaceItem, idx: number) => (
        <Input size="small" value={t}
          onChange={(e) => setList(list.map((r, i) => i === idx ? { ...r, source: e.target.value } : r))} />
      ) },
    { title: '方法名', dataIndex: 'method', width: 200,
      render: (t: string, _: InterfaceItem, idx: number) => (
        <Input size="small" value={t}
          onChange={(e) => setList(list.map((r, i) => i === idx ? { ...r, method: e.target.value } : r))} />
      ) },
    { title: '类型', dataIndex: 'type', width: 120,
      render: (t: InterfaceItem['type'], _: InterfaceItem, idx: number) => (
        <Select<InterfaceItem['type']> size="small" value={t} style={{ width: 110 }}
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

  const addIface = (
    list: InterfaceItem[],
    setList: (v: InterfaceItem[]) => void,
    type: '外部接口' | '内部接口',
  ) => setList([...list, { source: '', method: '', type, params: '', description: '' }])

  // ---- 3.4.x scenario 通用 ----
  const scenarioColumns = (
    list: ScenarioItem[],
    setList: (v: ScenarioItem[]) => void,
  ) => [
    { title: '标题', dataIndex: 'title', width: 200,
      render: (t: string, _: ScenarioItem, idx: number) => (
        <Input size="small" value={t}
          onChange={(e) => setList(list.map((r, i) => i === idx ? { ...r, title: e.target.value } : r))} />
      ) },
    { title: '说明', dataIndex: 'description',
      render: (t: string, _: ScenarioItem, idx: number) => (
        <Input size="small" value={t}
          onChange={(e) => setList(list.map((r, i) => i === idx ? { ...r, description: e.target.value } : r))} />
      ) },
    { title: 'PlantUML（折叠编辑）', dataIndex: 'plantuml',
      render: (t: string, _: ScenarioItem, idx: number) => (
        <Input.TextArea size="small" rows={2} value={t} placeholder="@startuml ... @enduml"
          onChange={(e) => setList(list.map((r, i) => i === idx ? { ...r, plantuml: e.target.value } : r))} />
      ) },
    { title: '', width: 50,
      render: (_: unknown, __: ScenarioItem, idx: number) => (
        <Button type="link" size="small" danger icon={<DeleteOutlined />}
          onClick={() => setList(list.filter((_r, i) => i !== idx))} />
      ) },
  ]

  // ---- 3.3.3.2.X sensor 字段表 ----
  const sensorFieldColumns = (
    s: ConfigDbSensor,
    setS: (v: ConfigDbSensor) => void,
  ) => [
    { title: '字段名', dataIndex: 'key', width: 180,
      render: (t: string, _: ConfigDbSensorField, idx: number) => (
        <Input size="small" value={t}
          onChange={(e) => setS({ ...s, fields: s.fields.map((f, i) => i === idx ? { ...f, key: e.target.value } : f) })} />
      ) },
    { title: '值', dataIndex: 'value', width: 160,
      render: (t: string, _: ConfigDbSensorField, idx: number) => (
        <Input size="small" value={t}
          onChange={(e) => setS({ ...s, fields: s.fields.map((f, i) => i === idx ? { ...f, value: e.target.value } : f) })} />
      ) },
    { title: '备注', dataIndex: 'note',
      render: (t: string, _: ConfigDbSensorField, idx: number) => (
        <Input size="small" value={t}
          onChange={(e) => setS({ ...s, fields: s.fields.map((f, i) => i === idx ? { ...f, note: e.target.value } : f) })} />
      ) },
    { title: '', width: 50,
      render: (_: unknown, __: ConfigDbSensorField, idx: number) => (
        <Button type="link" size="small" danger icon={<DeleteOutlined />}
          onClick={() => setS({ ...s, fields: s.fields.filter((_r, i) => i !== idx) })} />
      ) },
  ]

  return (
    <Collapse
      size="small"
      defaultActiveKey={['3.1', '3.3', '3.3.3']}
      items={[
        {
          key: '3.1',
          label: '3.1 简介',
          children: (
            <Input.TextArea rows={3} value={sd.intro}
              placeholder="整体架构一句话描述，可 AI 兜底"
              onChange={(e) => patch({ intro: e.target.value })} />
          ),
        },
        {
          key: '3.2',
          label: '3.2 功能模块图（PlantUML）',
          children: (
            <>
              <Alert type="info" showIcon style={{ marginBottom: 8 }}
                message="模块图默认使用 DEFAULT_MODULE_DIAGRAM_PLANTUML（8 模块 + SIPL 框架分区）；留空导出时自动填回默认。" />
              <Input.TextArea rows={10} value={sd.module_diagram_plantuml}
                placeholder="@startuml ... @enduml  （留空走后端默认模板）"
                onChange={(e) => patch({ module_diagram_plantuml: e.target.value })} />
            </>
          ),
        },
        {
          key: '3.3',
          label: `3.3 接口（外部概念 / 内部概念 / 临时项 ${sd.external_interfaces.length}+${sd.internal_interfaces.length}）`,
          children: (
            <Space direction="vertical" style={{ width: '100%' }} size="middle">
              <Alert type="info" showIcon
                message="§3.3 本质是概念性章节"
                description="PreDev 参考：§3.3 只说明『外部 / 内部接口』的定义与边界；具体函数清单按模块归在 §4.X.2 下。此处 TextArea 为默认文案，可改；表格仅作为「不属于任何单模块的临时手工接口项」的兜底，日常维护请在 §4 完成。" />

              <Card size="small" title="3.3.1 外部接口 — 概念说明"
                extra={<Button size="small" onClick={() => patch({ external_iface_intro: DEFAULT_EXTERNAL_IFACE_INTRO })}>
                  回落到默认文案
                </Button>}>
                <Input.TextArea rows={7}
                  value={sd.external_iface_intro ?? ''}
                  placeholder={DEFAULT_EXTERNAL_IFACE_INTRO}
                  onChange={(e) => patch({ external_iface_intro: e.target.value })} />
              </Card>

              <Card size="small" title="3.3.2 内部接口 — 概念说明"
                extra={<Button size="small" onClick={() => patch({ internal_iface_intro: DEFAULT_INTERNAL_IFACE_INTRO })}>
                  回落到默认文案
                </Button>}>
                <Input.TextArea rows={5}
                  value={sd.internal_iface_intro ?? ''}
                  placeholder={DEFAULT_INTERNAL_IFACE_INTRO}
                  onChange={(e) => patch({ internal_iface_intro: e.target.value })} />
              </Card>

              <Collapse size="small" items={[{
                key: 'fallback-tables',
                label: `临时手工接口项（外部 ${sd.external_interfaces.length} / 内部 ${sd.internal_interfaces.length}）— 建议在 §4 维护`,
                children: (
                  <Space direction="vertical" style={{ width: '100%' }} size="small">
                    <Card size="small" title="3.3.1 临时外部接口项"
                      extra={<Button size="small" icon={<PlusOutlined />}
                        onClick={() => addIface(sd.external_interfaces, (v) => patch({ external_interfaces: v }), '外部接口')}>添加</Button>}>
                      <Table rowKey={(_, idx) => `ext-${idx}`} size="small" pagination={false}
                        dataSource={sd.external_interfaces}
                        columns={ifaceColumns(sd.external_interfaces, (v) => patch({ external_interfaces: v }))} />
                    </Card>
                    <Card size="small" title="3.3.2 临时内部接口项"
                      extra={<Button size="small" icon={<PlusOutlined />}
                        onClick={() => addIface(sd.internal_interfaces, (v) => patch({ internal_interfaces: v }), '内部接口')}>添加</Button>}>
                      <Table rowKey={(_, idx) => `int-${idx}`} size="small" pagination={false}
                        dataSource={sd.internal_interfaces}
                        columns={ifaceColumns(sd.internal_interfaces, (v) => patch({ internal_interfaces: v }))} />
                    </Card>
                  </Space>
                ),
              }]} />
            </Space>
          ),
        },
        {
          key: '3.3.3',
          label: '3.3.3 配置文件（query/database）',
          children: (
            <Space direction="vertical" style={{ width: '100%' }} size="middle">
              <Alert type="info" showIcon
                message="来源：工程 nvsipl/query/database/<project>/ 的 *_platform.json / *_module.json / sensor JSON / m24c04.json / cryptoConfig.json"
                description="规则解析为主、AI 兜底描述段与 3.3.3.1 关系图。目录从顶部『工程代码（与 SWE.3 共享）』面板扫出，手动可覆盖。" />

              {/* database_path：下拉候选 + 手动兜底（工程树在顶部 Collapse 面板上传） */}
              <Card size="small" title="database_path"
                extra={
                  <Space>
                    <Button size="small" icon={<ReloadOutlined />} loading={scanning}
                      onClick={refreshCandidates}>
                      重新扫描
                    </Button>
                    <Button size="small" type="link"
                      onClick={() => setManual((m) => !m)}>
                      {manualEffective ? '↩ 切回下拉' : '✍ 手动输入'}
                    </Button>
                  </Space>
                }>
                {!engReady && (
                  <Alert type="warning" showIcon style={{ marginBottom: 8 }}
                    message="工程代码尚未上传"
                    description="请到顶部『工程代码（与 SWE.3 共享）』面板上传工程，才能扫描 query/database 候选目录。也可以直接手动输入路径。" />
                )}
                {engReady && candidates.length === 0 && (
                  <Alert type="warning" showIcon style={{ marginBottom: 8 }}
                    message="没有扫到 query/database 候选目录"
                    description="判定规则：同目录包含 *_platform.json + *_module.json + cryptoConfig.json。请检查工程结构或切换到手动输入。" />
                )}
                {!manualEffective ? (
                  <Select<string> style={{ width: '100%' }} showSearch allowClear
                    placeholder="选择 engineering_src 下相对路径（如 nvsipl/query/database/predev_mixgroup）"
                    value={databasePath || undefined}
                    options={candidates.map((p) => ({ value: p, label: p }))}
                    onChange={(v) => patchConfig({ database_path: v || '' })} />
                ) : (
                  <Input placeholder="database_path（engineering_src 下相对路径，用 / 分隔）"
                    value={databasePath}
                    onChange={(e) => patchConfig({ database_path: e.target.value })} />
                )}
              </Card>
              <Input.TextArea rows={2} placeholder="总述段（手工或 AI 翻译 description）"
                value={sd.config_files.description}
                onChange={(e) => patchConfig({ description: e.target.value })} />
              <Input.TextArea rows={8} placeholder="3.3.3.1 关系图 PlantUML（AI 生成后用户可编辑）"
                value={sd.config_files.diagram_plantuml}
                onChange={(e) => patchConfig({ diagram_plantuml: e.target.value })} />

              {/* 后端解析状态 + 立即重解析 */}
              <Card size="small" title={
                <Space>
                  <span>后端解析（parse_config_db）</span>
                  {parsing && <Tag color="processing">解析中…</Tag>}
                  {!parsing && !parseError && databasePath && (
                    <Tag color={sd.config_files.platform || sd.config_files.modules.length > 0 ? 'success' : 'warning'}>
                      {sd.config_files.platform || sd.config_files.modules.length > 0 ? '已识别' : '未扫到 JSON'}
                    </Tag>
                  )}
                </Space>
              } extra={
                <Button size="small" icon={<ReloadOutlined />} loading={parsing}
                  disabled={!databasePath}
                  onClick={() => void doParse(databasePath)}>立即解析</Button>
              }>
                {parseError && (
                  <Alert type="error" showIcon message={parseError} style={{ marginBottom: 8 }} />
                )}
                <Collapse size="small" ghost items={[
                  {
                    key: 'preview-platform',
                    label: `平台（${sd.config_files.platform?.name || '—'}）`,
                    children: !sd.config_files.platform ? (
                      <div style={{ color: '#999', fontSize: 12 }}>未解析到 platformConfigs。</div>
                    ) : (
                      <Space direction="vertical" style={{ width: '100%' }} size="small">
                        <div><b>name:</b> {sd.config_files.platform.name || '—'}</div>
                        <div><b>description:</b> {sd.config_files.platform.description || '—'}</div>
                        <Table size="small" pagination={false}
                          rowKey={(_, idx) => `pb-${idx}`}
                          dataSource={sd.config_files.platform.device_blocks}
                          columns={[
                            { title: 'csi_port', dataIndex: 'csi_port', width: 100 },
                            { title: 'phy_mode', dataIndex: 'phy_mode', width: 80 },
                            { title: 'deserializer', dataIndex: 'deserializer', width: 180 },
                            { title: 'cameraModules', dataIndex: 'camera_modules',
                              render: (v: string[]) => (v || []).join(' / ') },
                          ]} />
                      </Space>
                    ),
                  },
                  {
                    key: 'preview-modules',
                    label: `cameraModules（${sd.config_files.modules.length}）`,
                    children: sd.config_files.modules.length === 0 ? (
                      <div style={{ color: '#999', fontSize: 12 }}>未解析到 cameraModules。</div>
                    ) : (
                      <Table size="small" pagination={false}
                        rowKey={(_, idx) => `md-${idx}`}
                        dataSource={sd.config_files.modules}
                        columns={[
                          { title: 'name', dataIndex: 'name', width: 260 },
                          { title: 'serializer', dataIndex: 'serializer', width: 140 },
                          { title: 'sensors', dataIndex: 'sensors',
                            render: (v: string[]) => (v || []).join(' / ') },
                          { title: 'eeproms', dataIndex: 'eeproms', width: 160,
                            render: (v: string[]) => (v || []).join(' / ') },
                        ]} />
                    ),
                  },
                  {
                    key: 'preview-eeproms',
                    label: `eeproms（${sd.config_files.eeproms.length}）`,
                    children: sd.config_files.eeproms.length === 0 ? (
                      <div style={{ color: '#999', fontSize: 12 }}>未解析到 eeproms。</div>
                    ) : (
                      <Table size="small" pagination={false}
                        rowKey={(_, idx) => `ep-${idx}`}
                        dataSource={sd.config_files.eeproms}
                        columns={[
                          { title: 'name', dataIndex: 'name', width: 180 },
                          { title: 'i2c_address', dataIndex: 'i2c_address', width: 120 },
                          { title: 'fields', dataIndex: 'fields',
                            render: (v: ConfigDbSensorField[]) => `${(v || []).length} 项` },
                        ]} />
                    ),
                  },
                  {
                    key: 'preview-crypto',
                    label: `crypto（${sd.config_files.crypto?.keys?.length ?? 0}）`,
                    children: !sd.config_files.crypto ? (
                      <div style={{ color: '#999', fontSize: 12 }}>未解析到 cryptoConfig（样本工程常缺此文件，正常）。</div>
                    ) : (
                      <Table size="small" pagination={false}
                        rowKey={(_, idx) => `ck-${idx}`}
                        dataSource={sd.config_files.crypto.keys}
                        columns={[
                          { title: 'link_id', dataIndex: 'link_id', width: 100 },
                          { title: 'key_purpose', dataIndex: 'key_purpose', width: 160 },
                          { title: 'key_slot', dataIndex: 'key_slot', width: 100 },
                          { title: 'note', dataIndex: 'note' },
                        ]} />
                    ),
                  },
                ]} />
              </Card>

              <Card size="small" title={`3.3.3.2 sensor 配置 (${sd.config_files.sensors.length})`}
                extra={
                  <Button size="small" icon={<PlusOutlined />}
                    onClick={() => patchConfig({
                      sensors: [...sd.config_files.sensors, { name: '', description: '', i2c_address: '', fields: [] }],
                    })}>添加 sensor</Button>
                }>
                {sd.config_files.sensors.length === 0 && (
                  <div style={{ color: '#999', fontSize: 12 }}>暂无 sensor；点击上方按钮新增，或由后端 parse_config_db 填入。</div>
                )}
                {sd.config_files.sensors.map((s, i) => (
                  <Card key={i} size="small" style={{ marginBottom: 8 }} type="inner"
                    title={
                      <Space>
                        <Tag color="geekblue">{s.name || `sensor #${i + 1}`}</Tag>
                        <Input size="small" placeholder="name" value={s.name} style={{ width: 160 }}
                          onChange={(e) => patchConfig({
                            sensors: sd.config_files.sensors.map((x, j) => j === i ? { ...x, name: e.target.value } : x),
                          })} />
                        <Input size="small" placeholder="i2c" value={s.i2c_address} style={{ width: 100 }}
                          onChange={(e) => patchConfig({
                            sensors: sd.config_files.sensors.map((x, j) => j === i ? { ...x, i2c_address: e.target.value } : x),
                          })} />
                      </Space>
                    }
                    extra={
                      <Space>
                        <Button size="small" icon={<PlusOutlined />}
                          onClick={() => patchConfig({
                            sensors: sd.config_files.sensors.map((x, j) => j === i
                              ? { ...x, fields: [...x.fields, { key: '', value: '', note: '' }] } : x),
                          })}>字段</Button>
                        <Button size="small" danger icon={<DeleteOutlined />}
                          onClick={() => patchConfig({ sensors: sd.config_files.sensors.filter((_, j) => j !== i) })} />
                      </Space>
                    }>
                    <Input.TextArea rows={1} placeholder="描述" value={s.description}
                      style={{ marginBottom: 8 }}
                      onChange={(e) => patchConfig({
                        sensors: sd.config_files.sensors.map((x, j) => j === i ? { ...x, description: e.target.value } : x),
                      })} />
                    <Table size="small" pagination={false}
                      rowKey={(_, idx) => `${i}-${idx}`}
                      dataSource={s.fields}
                      columns={sensorFieldColumns(s, (v) => patchConfig({
                        sensors: sd.config_files.sensors.map((x, j) => j === i ? v : x),
                      }))} />
                  </Card>
                ))}
              </Card>
            </Space>
          ),
        },
        {
          key: '3.4',
          label: `3.4 图（状态 ${sd.state_diagrams.length} / 时序 ${sd.sequence_diagrams.length}）`,
          children: (
            <Space direction="vertical" style={{ width: '100%' }} size="middle">
              <Card size="small" title="3.4.1 总状态迁移图"
                extra={<Button size="small" icon={<PlusOutlined />}
                  onClick={() => patch({
                    state_diagrams: [...sd.state_diagrams, { kind: '状态迁移', title: '', description: '', plantuml: '' }],
                  })}>添加</Button>}>
                <Table rowKey={(_, idx) => `st-${idx}`} size="small" pagination={false}
                  dataSource={sd.state_diagrams}
                  columns={scenarioColumns(sd.state_diagrams, (v) => patch({ state_diagrams: v }))} />
              </Card>
              <Card size="small" title="3.4.2 总时序图"
                extra={<Button size="small" icon={<PlusOutlined />}
                  onClick={() => patch({
                    sequence_diagrams: [...sd.sequence_diagrams, { kind: '时序', title: '', description: '', plantuml: '' }],
                  })}>添加</Button>}>
                <Table rowKey={(_, idx) => `sq-${idx}`} size="small" pagination={false}
                  dataSource={sd.sequence_diagrams}
                  columns={scenarioColumns(sd.sequence_diagrams, (v) => patch({ sequence_diagrams: v }))} />
              </Card>
            </Space>
          ),
        },
      ]}
    />
  )
}
