/**
 * SWE.2 §5 资源消耗 面板（Phase 4 Group 5）。
 *
 * - memory_summary / cpu_summary：两段总述文本（5.1 / 5.2 开头说明）
 * - items[]：KPI 行（category=内存/CPU/延迟 ...；item/target/measured/method/note）
 *
 * 不新建 AI 按钮；资源数据来源以人工 + 实测为主。
 */
import { useMemo } from 'react'
import { Button, Card, Input, Space, Table, Tag } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import type { Swe2Resources, Swe2ResourceKpi } from '../../../types/aspice'

const DEFAULT: Swe2Resources = {
  memory_summary: '',
  cpu_summary: '',
  kpi_adjustment: '',
  items: [],
}

// V4.0 参考模板里给的 KPI 原目标 + 2023/10/20 客户变更段落示例，
// 用户点"填充示例"直接复用这段，省得逐行敲。
const KPI_ADJUSTMENT_SAMPLE =
  '资源消耗原目标：\n' +
  'KPI1：Steady state RAM usage < 1MB\n' +
  'KPI2：NAND Flash usage < 1MB\n' +
  'KPI3：CPU usage < 5%\n' +
  'KPI4：Defect number per KLOC <20\n' +
  'KPI5：Keep running and cant suddenly shut down\n' +
  'KPI6：CAN access I2C devices relate to the camera nums\n' +
  '\n' +
  '2023/10/20 经过跟客户沟通，按照实际情况验收，修改如下：\n' +
  'KPI1：Steady state RAM usage 无内存泄漏\n' +
  'KPI2：NAND Flash usage 核查 so 库占用空间\n' +
  'KPI3：CPU usage 核查驱动部分对应的 CPU 使用率\n' +
  'KPI4：Defect number per KLOC <20\n' +
  'KPI5：Keep running and cant suddenly shut down\n' +
  'KPI6：CAN access I2C devices relate to the camera nums\n' +
  'KPI7：8 颗模组(4x728 +4x623) 启动时间 2.7s，4x623 1.6s，1x623 0.9s\n' +
  'KPI8：相机启停 10000 次无异常报错\n' +
  '\n' +
  '详细细节可参考沟通记录《XX 项目 Deviation List and Quotation》。'

interface Props {
  value?: Swe2Resources
  onChange: (v: Swe2Resources) => void
}

export default function ResourcesEditor({ value, onChange }: Props) {
  const r = useMemo<Swe2Resources>(() => ({ ...DEFAULT, ...(value || {}) }), [value])
  const patch = (p: Partial<Swe2Resources>) => onChange({ ...r, ...p })
  const setItems = (items: Swe2ResourceKpi[]) => patch({ items })

  const columns = [
    { title: '类别', dataIndex: 'category', width: 90,
      render: (t: string, _: Swe2ResourceKpi, idx: number) => (
        <Input size="small" value={t} placeholder="内存/CPU/延迟"
          onChange={(e) => setItems(r.items.map((x, i) => i === idx ? { ...x, category: e.target.value } : x))} />
      ) },
    { title: '条目', dataIndex: 'item', width: 160,
      render: (t: string, _: Swe2ResourceKpi, idx: number) => (
        <Input size="small" value={t}
          onChange={(e) => setItems(r.items.map((x, i) => i === idx ? { ...x, item: e.target.value } : x))} />
      ) },
    { title: '目标', dataIndex: 'target', width: 120,
      render: (t: string, _: Swe2ResourceKpi, idx: number) => (
        <Input size="small" value={t}
          onChange={(e) => setItems(r.items.map((x, i) => i === idx ? { ...x, target: e.target.value } : x))} />
      ) },
    { title: '实测', dataIndex: 'measured', width: 120,
      render: (t: string, _: Swe2ResourceKpi, idx: number) => (
        <Input size="small" value={t}
          onChange={(e) => setItems(r.items.map((x, i) => i === idx ? { ...x, measured: e.target.value } : x))} />
      ) },
    { title: '测法', dataIndex: 'method',
      render: (t: string, _: Swe2ResourceKpi, idx: number) => (
        <Input size="small" value={t}
          onChange={(e) => setItems(r.items.map((x, i) => i === idx ? { ...x, method: e.target.value } : x))} />
      ) },
    { title: '备注', dataIndex: 'note',
      render: (t: string, _: Swe2ResourceKpi, idx: number) => (
        <Input size="small" value={t}
          onChange={(e) => setItems(r.items.map((x, i) => i === idx ? { ...x, note: e.target.value } : x))} />
      ) },
    { title: '', width: 50,
      render: (_: unknown, __: Swe2ResourceKpi, idx: number) => (
        <Button type="link" size="small" danger icon={<DeleteOutlined />}
          onClick={() => setItems(r.items.filter((_x, i) => i !== idx))} />
      ) },
  ]

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="middle">
      <Card size="small"
        title={<Space><Tag color="volcano">5. §</Tag><span>KPI 原目标 & 客户变更记录（可选）</span></Space>}
        extra={
          <Button size="small"
            onClick={() => patch({ kpi_adjustment: KPI_ADJUSTMENT_SAMPLE })}>
            填充 V4.0 示例
          </Button>
        }>
        <Input.TextArea rows={6} value={r.kpi_adjustment}
          placeholder={
            '留空则整段不渲染。V4.0 Pangu 样本里这块是 KPI1-8 原目标 + ' +
            '"2023/10/20 经过跟客户沟通 按照实际情况验收 修改如下 ..." 的客户变更记录。' +
            '想保留这段就手填或点"填充 V4.0 示例"。'
          }
          onChange={(e) => patch({ kpi_adjustment: e.target.value })} />
      </Card>
      <Card size="small" title={<Space><Tag color="purple">5.1</Tag><span>内存</span></Space>}>
        <Input.TextArea rows={2} value={r.memory_summary}
          placeholder="内存消耗总述段（如：'峰值 X MB，常态 Y MB，测量方法 ...'）"
          onChange={(e) => patch({ memory_summary: e.target.value })} />
      </Card>
      <Card size="small" title={<Space><Tag color="purple">5.2</Tag><span>CPU</span></Space>}>
        <Input.TextArea rows={2} value={r.cpu_summary}
          placeholder="CPU 占用总述段"
          onChange={(e) => patch({ cpu_summary: e.target.value })} />
      </Card>
      <Card size="small" title={`KPI 明细 (${r.items.length})`}
        extra={
          <Button size="small" icon={<PlusOutlined />}
            onClick={() => setItems([...r.items, {
              category: '', item: '', target: '', measured: '', method: '', note: '',
            }])}>添加</Button>
        }>
        <Table size="small" pagination={false}
          rowKey={(_, idx) => String(idx)}
          dataSource={r.items}
          columns={columns} />
      </Card>
    </Space>
  )
}
