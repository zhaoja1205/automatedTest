/**
 * SWE.2 概述元数据编辑器（1.3 术语 / 1.4 参考文档 / 1.5 假设及依赖）。
 *
 * 推送 A 的新增 UI：对齐《PreDev_软件架构&概要设计书V1.0》第 1 章，
 * 用户可在导出 docx 前手动编辑这三张表 + 项目假设列表。
 *
 * 顶部"预置默认"按钮一键填入规则层预置内容（术语 10 条 / 假设 4 行 / 7 条项目假设）。
 */
import {
  Button, Space, Table, Card, Input, Popconfirm, Divider, Typography,
} from 'antd'
import { PlusOutlined, DeleteOutlined, ThunderboltOutlined } from '@ant-design/icons'
import type {
  Swe2Overview, TermItem, RefDocItem, AssumptionItem,
} from '../../../types/aspice'

const { TextArea } = Input
const { Text } = Typography

interface Props {
  overview: Swe2Overview
  onChange: (overview: Swe2Overview) => void
}

/** 规则层默认值（和后端 arch_sections.py 保持同步） */
const DEFAULT_TERMS: TermItem[] = [
  { term: 'SWE.1',  definition: '软件需求分析过程' },
  { term: 'SWE.2',  definition: '软件架构设计过程' },
  { term: 'SIPL',   definition: 'Sensor Input Processing Library，NVIDIA Drive-OS 相机输入处理库' },
  { term: 'PMIC',   definition: 'Power Management IC，电源管理芯片' },
  { term: 'EEPROM', definition: 'Electrically Erasable Programmable Read-Only Memory，电可擦可编程只读存储器' },
  { term: 'SerDes', definition: 'Serializer / Deserializer，串行器与解串器' },
  { term: 'ISP',    definition: 'Image Signal Processor，图像信号处理器' },
  { term: 'MIPI',   definition: 'Mobile Industry Processor Interface，移动产业处理器接口' },
  { term: 'I2C',    definition: 'Inter-Integrated Circuit，集成电路总线' },
  { term: 'ASIL',   definition: 'Automotive Safety Integrity Level，汽车安全完整性等级' },
]

const DEFAULT_ASSUMPTIONS: AssumptionItem[] = [
  { input: '文件资料', time: '项目开始时', description: '需要在项目开始时将开发所需资料提供给开发方（SOW/SRS/MRD/硬件原理图/模组规格等）。' },
  { input: '相机模组', time: '项目开始时', description: '项目所需调校型号的 Golden 相机模组各若干 pcs。' },
  { input: '开发板',   time: '项目开始前', description: 'camera 端口连接设计及物理地址与 NV 官方开发板一致；解串器连接和配置与 NV 官方开发板一致。' },
  { input: '工具链',   time: '开发阶段',   description: '评估开发工具可满足客户的验收要求。' },
]

const DEFAULT_PROJECT_ASSUMPTIONS = [
  '提供的模组参数均可达成规格书要求；',
  '基于 Nvidia 平台自带 ISP；',
  'Deserializer 和 Serializer 均采用 NVIDIA Orin 支持的参考设计；',
  '开发方在开发协议期内负责将职责范围内的开发内容适配到新版本的 NV Orin DriveOS；',
  '操作系统将提供稳定的运行环境，不会出现意外的故障或中断；',
  '硬件设备将满足软件的最低配置要求，能够正常运行软件；',
  '用户将按照规定的流程和操作方式使用软件，不会进行异常的操作；',
  '三方 FAE 支持，双方构建沟通渠道，不限于邮件和会议。',
]

export default function OverviewEditor({ overview, onChange }: Props) {
  const terms = overview.terms || []
  const refDocs = overview.ref_docs || []
  const assumptions = overview.assumptions || []
  const projAssump = overview.project_assumptions || []

  const update = (patch: Partial<Swe2Overview>) => onChange({ ...overview, ...patch })

  // 预置默认
  const applyDefaults = () => {
    update({
      terms: terms.length ? terms : [...DEFAULT_TERMS],
      assumptions: assumptions.length ? assumptions : [...DEFAULT_ASSUMPTIONS],
      project_assumptions: projAssump.length ? projAssump : [...DEFAULT_PROJECT_ASSUMPTIONS],
    })
  }

  // 术语
  const addTerm = () => update({ terms: [...terms, { term: '', definition: '' }] })
  const delTerm = (i: number) => update({ terms: terms.filter((_, idx) => idx !== i) })
  const setTerm = (i: number, field: keyof TermItem, val: string) => {
    const next = [...terms]
    next[i] = { ...next[i], [field]: val }
    update({ terms: next })
  }

  // 参考文档
  const addRef = () => update({ ref_docs: [...refDocs, { no: String(refDocs.length + 1), name: '', version: '', note: '' }] })
  const delRef = (i: number) => update({ ref_docs: refDocs.filter((_, idx) => idx !== i) })
  const setRef = (i: number, field: keyof RefDocItem, val: string) => {
    const next = [...refDocs]
    next[i] = { ...next[i], [field]: val }
    update({ ref_docs: next })
  }

  // 假设
  const addAssump = () => update({ assumptions: [...assumptions, { input: '', time: '', description: '' }] })
  const delAssump = (i: number) => update({ assumptions: assumptions.filter((_, idx) => idx !== i) })
  const setAssump = (i: number, field: keyof AssumptionItem, val: string) => {
    const next = [...assumptions]
    next[i] = { ...next[i], [field]: val }
    update({ assumptions: next })
  }

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="middle">
      <Space>
        <Button size="small" type="primary" icon={<ThunderboltOutlined />} onClick={applyDefaults}>
          预置默认值
        </Button>
        <Text type="secondary" style={{ fontSize: 12 }}>
          预置内容基于 PreDev 参考文档；已有数据不会被覆盖
        </Text>
      </Space>

      {/* 1.1 目的 / 1.2 范围 */}
      <Card size="small" title="1.1 目的 / 1.2 范围">
        <Space direction="vertical" style={{ width: '100%' }}>
          <TextArea
            placeholder="1.1 目的（留空则导出时按项目代号自动填默认句）"
            rows={2}
            value={overview.purpose}
            onChange={(e) => update({ purpose: e.target.value })}
          />
          <TextArea
            placeholder="1.2 范围（留空则导出时填入标准描述）"
            rows={3}
            value={overview.scope}
            onChange={(e) => update({ scope: e.target.value })}
          />
        </Space>
      </Card>

      {/* 1.3 术语 */}
      <Card
        size="small"
        title={`1.3 术语定义 (${terms.length})`}
        extra={<Button size="small" icon={<PlusOutlined />} onClick={addTerm}>添加</Button>}
      >
        <Table
          size="small"
          rowKey={(_, idx) => String(idx)}
          dataSource={terms}
          pagination={terms.length > 15 ? { pageSize: 15 } : false}
          columns={[
            { title: '缩写和术语', dataIndex: 'term', width: 160,
              render: (v: string, _r: TermItem, i: number) => (
                <Input size="small" value={v} onChange={(e) => setTerm(i, 'term', e.target.value)} />
              ) },
            { title: '定义', dataIndex: 'definition',
              render: (v: string, _r: TermItem, i: number) => (
                <Input size="small" value={v} onChange={(e) => setTerm(i, 'definition', e.target.value)} />
              ) },
            { title: '', width: 50,
              render: (_: unknown, _r: TermItem, i: number) => (
                <Popconfirm title="删除？" onConfirm={() => delTerm(i)}>
                  <Button type="link" size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              ) },
          ]}
        />
      </Card>

      {/* 1.4 参考文档 */}
      <Card
        size="small"
        title={`1.4 参考文档 (${refDocs.length})`}
        extra={<Button size="small" icon={<PlusOutlined />} onClick={addRef}>添加</Button>}
      >
        <Table
          size="small"
          rowKey={(_, idx) => String(idx)}
          dataSource={refDocs}
          pagination={refDocs.length > 15 ? { pageSize: 15 } : false}
          columns={[
            { title: 'NO', dataIndex: 'no', width: 60,
              render: (v: string, _r: RefDocItem, i: number) => (
                <Input size="small" value={v} onChange={(e) => setRef(i, 'no', e.target.value)} />
              ) },
            { title: '参考文献名称', dataIndex: 'name',
              render: (v: string, _r: RefDocItem, i: number) => (
                <Input size="small" value={v} onChange={(e) => setRef(i, 'name', e.target.value)} />
              ) },
            { title: '文件版本', dataIndex: 'version', width: 100,
              render: (v: string, _r: RefDocItem, i: number) => (
                <Input size="small" value={v} onChange={(e) => setRef(i, 'version', e.target.value)} />
              ) },
            { title: '说明', dataIndex: 'note', width: 200,
              render: (v: string, _r: RefDocItem, i: number) => (
                <Input size="small" value={v} onChange={(e) => setRef(i, 'note', e.target.value)} />
              ) },
            { title: '', width: 50,
              render: (_: unknown, _r: RefDocItem, i: number) => (
                <Popconfirm title="删除？" onConfirm={() => delRef(i)}>
                  <Button type="link" size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              ) },
          ]}
        />
      </Card>

      {/* 1.5 假设及依赖 */}
      <Card size="small" title={`1.5 假设及依赖 — 关键依赖 (${assumptions.length})`}
        extra={<Button size="small" icon={<PlusOutlined />} onClick={addAssump}>添加</Button>}
      >
        <Table
          size="small"
          rowKey={(_, idx) => String(idx)}
          dataSource={assumptions}
          pagination={false}
          columns={[
            { title: '输入项', dataIndex: 'input', width: 120,
              render: (v: string, _r: AssumptionItem, i: number) => (
                <Input size="small" value={v} onChange={(e) => setAssump(i, 'input', e.target.value)} />
              ) },
            { title: '输入时间', dataIndex: 'time', width: 120,
              render: (v: string, _r: AssumptionItem, i: number) => (
                <Input size="small" value={v} onChange={(e) => setAssump(i, 'time', e.target.value)} />
              ) },
            { title: '描述', dataIndex: 'description',
              render: (v: string, _r: AssumptionItem, i: number) => (
                <Input size="small" value={v} onChange={(e) => setAssump(i, 'description', e.target.value)} />
              ) },
            { title: '', width: 50,
              render: (_: unknown, _r: AssumptionItem, i: number) => (
                <Popconfirm title="删除？" onConfirm={() => delAssump(i)}>
                  <Button type="link" size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              ) },
          ]}
        />
        <Divider style={{ margin: '12px 0 8px' }}>项目假设（每行一条）</Divider>
        <TextArea
          rows={6}
          value={projAssump.join('\n')}
          placeholder="每行一条项目假设，导出 docx 时以项目符号渲染"
          onChange={(e) => update({
            project_assumptions: e.target.value.split('\n').map(s => s.trim()).filter(Boolean),
          })}
        />
      </Card>
    </Space>
  )
}
