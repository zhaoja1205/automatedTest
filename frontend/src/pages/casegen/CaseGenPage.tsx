/**
 * 生成测试用例 — 向导页面。
 *
 * 流程：基本信息 → 平台配置 → 功能测试配置 → 生成与预览 → 导出。
 */
import { useState } from 'react'
import { Button, Card, Divider, Form, Space, Steps, Typography, message } from 'antd'
import BasicInfoStep from '../../components/casegen/BasicInfoStep'
import FunctionalGenStep from '../../components/casegen/FunctionalGenStep'
import PlatformStep from '../../components/casegen/PlatformStep'
import CasePreviewStep from '../../components/casegen/CasePreviewStep'
import type { CaseGenBasicInfo, PlatformConfigParseResult, RawLightingOptions } from '../../types/casegen'
import { generateRawLightingCases } from '../../utils/casegen/functionalCases'

const { Title, Paragraph } = Typography

const STEPS = [
  { title: '基本信息', description: '项目与版本信息' },
  { title: '平台配置', description: '选择硬件拓扑' },
  { title: '功能测试', description: '点亮（生成 .raw）' },
  { title: '生成与预览', description: '查看生成的用例' },
  { title: '导出', description: '待实现' },
]

export default function CaseGenPage() {
  const [form] = Form.useForm<CaseGenBasicInfo>()
  const [current, setCurrent] = useState(0)
  const [platformData, setPlatformData] = useState<PlatformConfigParseResult | null>(null)
  const [selectedPlatform, setSelectedPlatform] = useState('')
  const [lightingOptions, setLightingOptions] = useState<RawLightingOptions>({
    image_path: './picture/',
    skip_frames: 10,
    write_frames: 1,
  })
  const [generatedCases, setGeneratedCases] = useState<ReturnType<typeof generateRawLightingCases>>([])

  const selectedPlatformConfig = platformData?.platform_configs.find(
    (c) => c.name === selectedPlatform,
  ) || null

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

  const handleGenerate = () => {
    if (!selectedPlatformConfig) {
      message.warning('请先选择平台配置')
      return
    }
    const cases = generateRawLightingCases(selectedPlatformConfig, lightingOptions)
    setGeneratedCases(cases)
    message.success(`已生成 ${cases.length} 条用例`)
  }

  return (
    <div>
      <Card style={{ marginBottom: 12 }}>
        <Title level={4} style={{ marginTop: 0, marginBottom: 8 }}>生成测试用例</Title>
        <Paragraph type="secondary" style={{ marginBottom: 0 }}>
          按向导分阶段完成用例生成：填写基本信息 → 选择平台配置 → 配置功能测试 → 预览生成的用例。
        </Paragraph>
      </Card>

      <Card>
        <Steps
          current={current}
          items={STEPS}
          onChange={(step) => {
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
        <FunctionalGenStep
          visible={current === 2}
          platform={selectedPlatformConfig}
          options={lightingOptions}
          onOptionsChange={setLightingOptions}
          onGenerate={handleGenerate}
        />
        <CasePreviewStep
          platformName={selectedPlatform}
          cases={generatedCases}
          onRegenerate={handleGenerate}
        />

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
