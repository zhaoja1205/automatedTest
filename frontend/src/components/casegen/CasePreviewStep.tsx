/**
 * 生成测试用例 — 用例预览步骤。
 *
 * 展示按当前平台配置与生成参数得到的用例，并支持按测试类型筛选预览。
 */
import { useEffect, useMemo, useState } from 'react'
import { Button, Empty, Select, Space, Table, Tag, Tooltip, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { CopyOutlined } from '@ant-design/icons'
import type { GeneratedCase } from '../../types/casegen'

interface Props {
  platformName: string
  cases: GeneratedCase[]
  onRegenerate: () => void
  /** 用例为空时的提示文案（功能测试 / 压力测试页面分别定制） */
  emptyDescription?: string
}

const multiLineStyle: React.CSSProperties = {
  margin: 0,
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
  fontSize: 12,
  lineHeight: 1.6,
}

/** 各测试类型的标签颜色 */
const TYPE_COLORS: Record<string, string> = {
  'raw图': 'blue',
  'YUV图': 'purple',
  'ro测试': 'cyan',
  'al测试': 'geekblue',
  'th测试': 'green',
  '压力测试': 'volcano',
  '稳定性测试': 'gold',
}

/** 按测试类型统计用例数（保持用例中首次出现的顺序） */
function countTypes(cases: GeneratedCase[]): Map<string, number> {
  const counts = new Map<string, number>()
  cases.forEach((item) => counts.set(item.test_type, (counts.get(item.test_type) ?? 0) + 1))
  return counts
}

/** 统计各测试类型的用例数，例如「raw图 8 · YUV图 8」 */
function countByType(cases: GeneratedCase[]): string {
  return Array.from(countTypes(cases).entries())
    .map(([type, count]) => `${type} ${count}`)
    .join(' · ')
}

const COLUMNS: ColumnsType<GeneratedCase> = [
  { title: '#', key: 'index', width: 50, render: (_v, _r, index) => index + 1 },
  { title: '用例描述', dataIndex: 'description', key: 'description', width: 300 },
  {
    title: '测试类型', dataIndex: 'test_type', key: 'test_type', width: 90,
    render: (value: string) => <Tag color={TYPE_COLORS[value] ?? 'blue'}>{value}</Tag>,
  },
  {
    title: '前置条件', dataIndex: 'prerequisites', key: 'prerequisites', width: 320,
    render: (value: string) => <pre style={multiLineStyle}>{value || '-'}</pre>,
  },
  {
    title: '测试步骤', dataIndex: 'steps', key: 'steps', width: 560,
    render: (value: string) => <pre style={multiLineStyle}>{value}</pre>,
  },
  {
    title: '预期结果', dataIndex: 'expected', key: 'expected', width: 260,
    render: (value: string) => <pre style={multiLineStyle}>{value}</pre>,
  },
  { title: '优先级', dataIndex: 'priority', key: 'priority', width: 80 },
]

export default function CasePreviewStep({
  platformName,
  cases,
  onRegenerate,
  emptyDescription = '尚未生成用例，请点击「生成用例」',
}: Props) {
  /** 当前选中的测试类型；为空表示不筛选（展示全部） */
  const [typeFilter, setTypeFilter] = useState<string[]>([])

  const typeCounts = useMemo(() => countTypes(cases), [cases])
  const typeOptions = useMemo(
    () =>
      Array.from(typeCounts.entries()).map(([type, count]) => ({
        value: type,
        label: `${type}（${count}）`,
      })),
    [typeCounts],
  )

  // 重新生成后若原筛选类型已不存在，自动丢弃无效筛选项
  useEffect(() => {
    setTypeFilter((previous) => {
      const valid = previous.filter((type) => typeCounts.has(type))
      return valid.length === previous.length ? previous : valid
    })
  }, [typeCounts])

  const filteredCases = useMemo(() => {
    if (typeFilter.length === 0) return cases
    return cases.filter((item) => typeFilter.includes(item.test_type))
  }, [cases, typeFilter])

  const handleCopyAll = () => {
    if (filteredCases.length === 0) return
    const text = filteredCases
      .map((c, i) => {
        return [
          `${i + 1}. ${c.description}`,
          `   测试类型：${c.test_type}`,
          `   前置条件：${c.prerequisites.replace(/\n/g, '\\n')}`,
          `   步骤：${c.steps.replace(/\n/g, '\\n')}`,
          `   预期：${c.expected.replace(/\n/g, '\\n')}`,
        ].join('\n')
      })
      .join('\n\n')
    navigator.clipboard.writeText(text).then(
      () => message.success(`已复制 ${filteredCases.length} 条用例到剪贴板`),
      () => message.error('复制失败'),
    )
  }

  return (
    <div>
      {cases.length === 0 ? (
        <Empty description={emptyDescription} style={{ padding: '32px 0' }} />
      ) : (
        <>
          <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
            <div>
              <strong>{platformName}</strong>
              <span style={{ marginLeft: 8, color: '#666' }}>
                共 {cases.length} 条测试用例（{countByType(cases)}）
              </span>
              {typeFilter.length > 0 && (
                <span style={{ marginLeft: 8, color: '#1677ff' }}>
                  当前筛选 {filteredCases.length} 条
                </span>
              )}
            </div>
            <Space wrap>
              <Select
                mode="multiple"
                allowClear
                size="small"
                style={{ minWidth: 200, maxWidth: 340 }}
                placeholder="按测试类型筛选"
                value={typeFilter}
                onChange={setTypeFilter}
                options={typeOptions}
                maxTagCount="responsive"
              />
              <Tooltip title="重新生成用例">
                <Button onClick={onRegenerate}>重新生成</Button>
              </Tooltip>
              <Tooltip
                title={
                  typeFilter.length > 0
                    ? '复制当前筛选的用例文本'
                    : '复制所有用例文本'
                }
              >
                <Button icon={<CopyOutlined />} onClick={handleCopyAll}>复制</Button>
              </Tooltip>
            </Space>
          </div>
          {filteredCases.length === 0 ? (
            <Empty description="当前筛选条件下没有用例" style={{ padding: '24px 0' }} />
          ) : (
            <Table
              size="small"
              bordered
              rowKey="key"
              columns={COLUMNS}
              dataSource={filteredCases}
              pagination={false}
              scroll={{ x: 1700 }}
            />
          )}
        </>
      )}
    </div>
  )
}
