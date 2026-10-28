/**
 * 生成测试用例 — 第四步：用例预览。
 *
 * 展示按当前平台配置与生成参数得到的用例，后续可在此基础上增加编辑能力。
 */
import { Empty, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { GeneratedCase } from '../../types/casegen'

const { Text } = Typography

interface Props {
  visible: boolean
  platformName: string
  cases: GeneratedCase[]
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

export default function CasePreviewStep({ visible, platformName, cases }: Props) {
  return (
    <div style={{ display: visible ? undefined : 'none' }}>
      {cases.length === 0 ? (
        <Empty description="尚未生成用例，请返回上一步配置生成参数" style={{ padding: '32px 0' }} />
      ) : (
        <>
          <div style={{ marginBottom: 12 }}>
            <Text strong>{platformName}</Text>
            <Text type="secondary" style={{ marginLeft: 8 }}>
              共 {cases.length} 条功能测试用例（点亮）
            </Text>
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
