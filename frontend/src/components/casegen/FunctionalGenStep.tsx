/**
 * 生成测试用例 — 第三步：功能测试生成配置。
 *
 * 当前仅实现「点亮（生成 .raw）」一种功能测试：
 * 按所选平台配置为每个相机生成一条用例。
 */
import {
  Alert,
  Checkbox,
  Col,
  Descriptions,
  Empty,
  Input,
  InputNumber,
  Row,
  Space,
  Tag,
  Typography,
} from 'antd'
import { buildLightingCommand } from '../../utils/casegen/functionalCases'
import type { PlatformConfig, RawLightingOptions } from '../../types/casegen'

const { Text } = Typography

interface Props {
  visible: boolean
  platform: PlatformConfig | null
  options: RawLightingOptions
  onOptionsChange: (options: RawLightingOptions) => void
}

const codeStyle: React.CSSProperties = {
  margin: '8px 0 0',
  padding: '10px 12px',
  background: '#f6f8fa',
  border: '1px solid #e5e7eb',
  borderRadius: 6,
  fontSize: 12,
  lineHeight: 1.6,
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-all',
}

export default function FunctionalGenStep({
  visible,
  platform,
  options,
  onOptionsChange,
}: Props) {
  const firstCamera = platform?.topology[0]
  const previewCommand =
    platform && firstCamera ? buildLightingCommand(platform.name, firstCamera, options) : ''

  return (
    <div style={{ display: visible ? undefined : 'none' }}>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="当前仅实现功能测试：点亮（生成 .raw）"
        description="每个相机生成一条点亮用例；命令中的 -m 掩码和 gc 参数会按相机的 Group / linkIndex / Sensor ID 自动生成。后续再扩展其它功能测试类型。"
      />

      {!platform ? (
        <Empty description="请先在「平台配置」步骤选择平台配置" style={{ padding: '32px 0' }} />
      ) : (
        <>
          <Descriptions size="small" column={3} bordered style={{ marginBottom: 16 }}>
            <Descriptions.Item label="平台配置">
              <Text code>{platform.name}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="Group 数">{platform.group_count}</Descriptions.Item>
            <Descriptions.Item label="相机数">{platform.module_count}</Descriptions.Item>
          </Descriptions>

          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Space>
              <Checkbox checked disabled>点亮</Checkbox>
              <Tag color="blue">生成 .raw</Tag>
              <Text type="secondary">将生成 {platform.module_count} 条用例</Text>
            </Space>

            <Row gutter={16}>
              <Col xs={24} md={12}>
                <Text type="secondary">-f 输出目录</Text>
                <Input
                  value={options.image_path}
                  onChange={(e) => onOptionsChange({ ...options, image_path: e.target.value })}
                  placeholder="./picture/"
                />
              </Col>
              <Col xs={12} md={6}>
                <Text type="secondary">--skipFrames</Text>
                <InputNumber
                  min={0}
                  precision={0}
                  style={{ width: '100%' }}
                  value={options.skip_frames}
                  onChange={(value) =>
                    onOptionsChange({ ...options, skip_frames: Number(value ?? 0) })
                  }
                />
              </Col>
              <Col xs={12} md={6}>
                <Text type="secondary">--writeFrames</Text>
                <InputNumber
                  min={0}
                  precision={0}
                  style={{ width: '100%' }}
                  value={options.write_frames}
                  onChange={(value) =>
                    onOptionsChange({ ...options, write_frames: Number(value ?? 0) })
                  }
                />
              </Col>
            </Row>

            {firstCamera && (
              <div>
                <Text strong>
                  命令预览（{firstCamera.group}: {firstCamera.link_index}: {firstCamera.module}）
                </Text>
                <pre style={codeStyle}>{previewCommand}</pre>
              </div>
            )}
          </Space>
        </>
      )}
    </div>
  )
}
