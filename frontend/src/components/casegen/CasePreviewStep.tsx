/**
 * 生成测试用例 — 第四步：用例预览。
 *
 * 展示按当前平台配置与生成参数得到的用例。
 */
import { Button, Empty, Space, Table, Tag, Tooltip, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { CopyOutlined } from '@ant-design/icons'
import type { GeneratedCase } from '../../types/casegen'

interface Props {
  platformName: string
  cases: GeneratedCase[]
  onRegenerate: () => void
}

const multiLineStyle: React.CSSProperties = {
  margin: 0,
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
  fontSize: 12,
  lineHeight: 1.6,
}

const COLUMNS: ColumnsType<GeneratedCase> = [
  { title: '#', key: 'index', width: 50, render: (_v, _r, index) => index + 1 },
  { title: '用例描述', dataIndex: 'description', key: 'description', width: 300 },
  {
    title: '测试类型', dataIndex: 'test_type', key: 'test_type', width: 90,
    render: (value: string) => <Tag color="blue">{value}</Tag>,
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

export default function CasePreviewStep({ platformName, cases, onRegenerate }: Props) {
  const handleCopyAll = () => {
    if (cases.length === 0) return
    const text = cases
      .map((c, i) => {
        return [
          `${i + 1}. ${c.description}`,
          `   测试类型：${c.test_type}`,
          `   步骤：${c.steps.replace(/\n/g, '\\n')}`,
          `   预期：${c.expected.replace(/\n/g, '\\n')}`,
        ].join('\n')
      })
      .join('\n\n')
    navigator.clipboard.writeText(text).then(
      () => message.success('已复制到剪贴板'),
      () => message.error('复制失败'),
    )
  }

  return (
    <div>
      {cases.length === 0 ? (
        <Empty description="尚未生成用例，请在上一步点击「生成用例」" style={{ padding: '32px 0' }} />
      ) : (
        <>
          <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <strong>{platformName}</strong>
              <span style={{ marginLeft: 8, color: '#666' }}>
                共 {cases.length} 条功能测试用例（点亮）
              </span>
            </div>
            <Space>
              <Tooltip title="重新生成用例">
                <Button onClick={onRegenerate}>重新生成</Button>
              </Tooltip>
              <Tooltip title="复制所有用例文本">
                <Button icon={<CopyOutlined />} onClick={handleCopyAll}>复制</Button>
              </Tooltip>
            </Space>
          </div>
          <Table
            size="small"
            bordered
            rowKey="key"
            columns={COLUMNS}
            dataSource={cases}
            pagination={false}
            scroll={{ x: 1400 }}
          />
        </>
      )}
    </div>
  )
}
