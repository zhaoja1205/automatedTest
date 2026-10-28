/**
 * 生成测试用例 — 后续阶段占位组件。
 *
 * 后续实现时用具体步骤组件替换即可，外层向导结构不用改。
 */
import { Empty, Typography } from 'antd'
import type { ReactNode } from 'react'

const { Text } = Typography

interface Props {
  title: string
  description: string
  children?: ReactNode
}

export default function PlaceholderStep({ title, description, children }: Props) {
  return (
    <div style={{ padding: '32px 0' }}>
      {children}
      <Empty
        description={
          <span>
            <Text strong>{title}</Text>
            <br />
            <Text type="secondary">{description}</Text>
          </span>
        }
      />
    </div>
  )
}
