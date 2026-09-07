/**
 * 步骤 4：用例预览。
 *
 * 只读表格展示所有用例，按最终导出的列结构（ID/类型/方法/描述/前置/步骤/预期/优先级）。
 * 高亮占位符和默认值告警。
 */
import { Tabs, Table, Tag, Alert } from 'antd'
import { WarningOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { useCreatorStore } from '../../stores/useCreatorStore'
import type { DesignCase } from '../../types/creator'

function CasePreviewTable({ cases, startId = 1 }: { cases: DesignCase[]; startId?: number }) {
  const columns = [
    {
      title: 'ID',
      key: 'id',
      width: 60,
      render: (_: unknown, __: unknown, idx: number) => String(startId + idx).padStart(3, '0'),
    },
    { title: '测试类型', dataIndex: 'type', key: 'type', width: 100 },
    { title: '设计方法', dataIndex: 'method', key: 'method', width: 120 },
    {
      title: '用例描述',
      dataIndex: 'desc',
      key: 'desc',
      width: 200,
      render: (t: string) => renderWithPlaceholder(t),
    },
    {
      title: '前置条件',
      dataIndex: 'pre',
      key: 'pre',
      width: 250,
      render: (t: string) => renderWithPlaceholder(t),
    },
    {
      title: '测试步骤',
      dataIndex: 'steps',
      key: 'steps',
      width: 300,
      render: (t: string) => renderWithPlaceholder(t),
    },
    {
      title: '预期结果',
      dataIndex: 'expected',
      key: 'expected',
      width: 250,
      render: (t: string) => renderWithPlaceholder(t),
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      width: 80,
      render: (p: string) => {
        const colors: Record<string, string> = { P0: 'red', P1: 'orange', P2: 'blue' }
        return <Tag color={colors[p] || 'default'}>{p}</Tag>
      },
    },
  ]

  return (
    <Table
      rowKey={(_, idx) => String(idx)}
      columns={columns}
      dataSource={cases}
      pagination={cases.length > 30 ? { pageSize: 30 } : false}
      size="small"
      bordered
      scroll={{ x: 1360 }}
    />
  )
}

/** 高亮占位符文本 */
function renderWithPlaceholder(text: string) {
  if (!text) return <span style={{ color: '#ccc' }}>—</span>
  if (typeof text !== 'string') return text

  // 检测并高亮 <待补充:xxx>
  const parts = text.split(/(<待补充[^>]*>)/)
  if (parts.length === 1) {
    return <pre style={{ margin: 0, whiteSpace: 'pre-wrap', fontSize: 12, fontFamily: 'inherit' }}>{text}</pre>
  }

  return (
    <pre style={{ margin: 0, whiteSpace: 'pre-wrap', fontSize: 12, fontFamily: 'inherit' }}>
      {parts.map((part, i) =>
        part.startsWith('<待补充') ? (
          <Tag key={i} color="warning" style={{ fontSize: 11 }}>{part}</Tag>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </pre>
  )
}

export default function CasePreviewStep() {
  const { currentProject } = useCreatorStore()
  const funcCases = currentProject?.functional_cases || []
  const faultCases = currentProject?.fault_cases || []
  const defaults = currentProject?.defaults_used || []

  // 统计占位符
  const placeholders: string[] = []
  const allCases = [...funcCases, ...faultCases]
  for (const c of allCases) {
    for (const key of ['type', 'method', 'desc', 'pre', 'steps', 'expected', 'priority'] as const) {
      const val = c[key]
      if (typeof val === 'string') {
        const matches = val.match(/<待补充[^>]*>/g)
        if (matches) placeholders.push(...matches)
      }
    }
  }

  const totalCases = funcCases.length + faultCases.length

  return (
    <div>
      {/* 汇总信息 */}
      <div style={{ marginBottom: 16 }}>
        <strong>用例总览：</strong>
        功能 {funcCases.length} 条 + 故障 {faultCases.length} 条 = 共 {totalCases} 条
      </div>

      {placeholders.length > 0 && (
        <Alert
          type="warning"
          showIcon
          icon={<WarningOutlined />}
          message={`${placeholders.length} 处占位符待补充`}
          description={
            <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
              {[...new Set(placeholders)].slice(0, 8).map((p, i) => (
                <li key={i}><code>{p}</code></li>
              ))}
              {new Set(placeholders).size > 8 && <li>...还有更多</li>}
            </ul>
          }
          style={{ marginBottom: 12 }}
        />
      )}

      {defaults.length > 0 && (
        <Alert
          type="info"
          showIcon
          icon={<InfoCircleOutlined />}
          message={`${defaults.length} 项默认值请确认`}
          description={
            <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
              {defaults.map((d, i) => (
                <li key={i}>{d.field}: <strong>{d.default_value}</strong> <span style={{ color: '#888' }}>[{d.source}]</span></li>
              ))}
            </ul>
          }
          style={{ marginBottom: 12 }}
        />
      )}

      {/* 用例表格 */}
      <Tabs
        defaultActiveKey="functional"
        items={[
          {
            key: 'functional',
            label: `功能测试 (${funcCases.length})`,
            children: <CasePreviewTable cases={funcCases} startId={1} />,
          },
          {
            key: 'fault',
            label: `故障测试 (${faultCases.length})`,
            children: (
              <CasePreviewTable
                cases={faultCases}
                startId={currentProject?.meta?.fault_id_from_start ? 1 : funcCases.length + 1}
              />
            ),
          },
        ]}
      />
    </div>
  )
}
