/**
 * 生成测试用例 — 向导页面。
 *
 * 流程：基本信息 → 平台配置 → 测试范围 → 生成与预览 → 导出。
 * 当前已完成基本信息与平台配置，后续阶段为占位内容。
 */
import { useState } from 'react'
import { Button, Card, Divider, Form, Space, Steps, Typography, message } from 'antd'
import BasicInfoStep from '../../components/casegen/BasicInfoStep'
import PlatformStep from '../../components/casegen/PlatformStep'
import PlaceholderStep from '../../components/casegen/PlaceholderStep'
import type { CaseGenBasicInfo, PlatformConfigParseResult } from '../../types/casegen'

const { Title, Paragraph } = Typography

const STEPS = [
  { title: '基本信息', description: '项目与版本信息' },
  { title: '平台配置', description: '选择硬件拓扑' },
  { title: '测试范围', description: '待实现' },
  { title: '生成与预览', description: '待实现' },
  { title: '导出', description: '待实现' },
]

const PLACEHOLDERS = [
  null,
  null,
  { title: '测试范围', description: '后续在这里配置测试对象、功能覆盖范围与优先级等。' },
  { title: '生成与预览', description: '后续在这里生成、检查并编辑测试用例。' },
  { title: '导出', description: '后续在这里导出 Excel 用例文件。' },
]

export default function CaseGenPage() {
  const [form] = Form.useForm<CaseGenBasicInfo>()
  const [current, setCurrent] = useState(0)
  const [platformData, setPlatformData] = useState<PlatformConfigParseResult | null>(null)
  const [selectedPlatform, setSelectedPlatform] = useState('')

  const handleNext = async () => {
    if (current === 0) {
      try {
        await form.validateFields()
      } catch {
        return
      }
    }
    if (current === 1 && !selectedPlatform) {
      message.warning('请先读取配置文件并选择平台配置')
      return
    }
    if (current >= STEPS.length - 1) {
      message.info('导出阶段待实现')
      return
    }
    setCurrent((v) => v + 1)
  }

  const handlePrev = () => {
    if (current > 0) setCurrent((v) => v - 1)
  }

  const placeholder = PLACEHOLDERS[current]

  return (
    <div>
      <Card style={{ marginBottom: 12 }}>
        <Title level={4} style={{ marginTop: 0, marginBottom: 8 }}>生成测试用例</Title>
        <Paragraph type="secondary" style={{ marginBottom: 0 }}>
          按向导分阶段完成用例生成：填写基本信息 → 选择平台配置 → 配置测试范围 → 生成与预览 → 导出。
          当前已完成基本信息与平台配置（读取 nvsipl platform JSON 并选择硬件拓扑），后续阶段待实现。
        </Paragraph>
      </Card>

      <Card>
        <Steps
          current={current}
          items={STEPS}
          onChange={(step) => {
            // 只允许回退到已完成的步骤，避免跳过基本信息校验
            if (step < current) setCurrent(step)
          }}
        />
        <Divider />

        <BasicInfoStep form={form} visible={current === 0} />
        <PlatformStep
          visible={current === 1}
          data={platformData}
          selectedName={selectedPlatform}
          onData={setPlatformData}
          onSelect={setSelectedPlatform}
        />

        {current > 1 && placeholder && (
          <PlaceholderStep title={placeholder.title} description={placeholder.description} />
        )}

        <Divider style={{ marginBottom: 16 }} />
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <Button onClick={handlePrev} disabled={current === 0}>
            上一步
          </Button>
          <Space>
            <Button
              onClick={() => message.info('草稿保存待实现')}
            >
              保存草稿
            </Button>
            <Button type="primary" onClick={() => void handleNext()}>
              {current === STEPS.length - 1 ? '完成' : '下一步'}
            </Button>
          </Space>
        </div>
      </Card>
    </div>
  )
}
