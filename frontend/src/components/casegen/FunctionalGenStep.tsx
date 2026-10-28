/**
 * 生成测试用例 — 第四步：功能测试生成配置。
 *
 * 支持两类功能测试，可分别勾选：
 * - raw图（生成 .raw）：每个相机一条用例
 * - YUV 图（生成 .yuv）：每个相机一条用例
 * 若已在「Sensors 配置」步骤添加 sensor 配置，会按 Sensor 名称匹配相机，
 * 并把 sensor 帧率写入用例预期结果。
 */
import {
  Alert,
  Button,
  Checkbox,
  Col,
  Descriptions,
  Empty,
  Input,
  InputNumber,
  Row,
  Space,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import { buildLightingCommand, buildYuvCommand } from '../../utils/casegen/functionalCases'
import { findSensorConfig, formatSensorSummary } from '../../utils/casegen/sensors'
import { TEST_TYPE_LIGHTING, TEST_TYPE_YUV } from '../../types/casegen'
import type {
  FunctionalTestOptions,
  FunctionalTestSelection,
  PlatformConfig,
  SensorConfig,
} from '../../types/casegen'

const { Text } = Typography

interface Props {
  visible: boolean
  platform: PlatformConfig | null
  options: FunctionalTestOptions
  onOptionsChange: (options: FunctionalTestOptions) => void
  selection: FunctionalTestSelection
  onSelectionChange: (selection: FunctionalTestSelection) => void
  onGenerate: () => void
  /** 已添加的 sensor 配置（可为空） */
  sensors?: SensorConfig[]
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
  selection,
  onSelectionChange,
  onGenerate,
  sensors,
}: Props) {
  const firstCamera = platform?.topology[0]
  const lightingCommand =
    platform && firstCamera ? buildLightingCommand(platform.name, firstCamera, options) : ''
  const yuvCommand =
    platform && firstCamera ? buildYuvCommand(platform.name, firstCamera, options) : ''
  const selectedTypes = Number(selection.lighting) + Number(selection.yuv)
  const caseCount = (platform?.module_count ?? 0) * selectedTypes
  const matchedSensors = platform
    ? Array.from(new Set(platform.topology.map((row) => row.sensor).filter(Boolean))).map((name) => ({
        name,
        config: findSensorConfig(sensors, name),
      }))
    : []
  const matchedCount = matchedSensors.filter((item) => item.config).length

  return (
    <div style={{ display: visible ? undefined : 'none' }}>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="功能测试：raw图（生成 .raw）与 YUV 图（生成 .yuv）"
        description="每个相机为每种勾选的测试类型各生成一条用例；命令中的 -m 掩码和 gc 参数会按相机的 Group / linkIndex / Sensor ID 自动生成。"
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
            <Descriptions.Item label="Sensor 配置" span={3}>
              {matchedSensors.length === 0 ? (
                <Text type="secondary">平台中没有相机</Text>
              ) : (
                <Space wrap size={4}>
                  {matchedSensors.map((item) =>
                    item.config ? (
                      <Tooltip key={item.name} title={formatSensorSummary(item.config)}>
                        <Tag color="green">{item.name} 已配置</Tag>
                      </Tooltip>
                    ) : (
                      <Tag key={item.name}>{item.name} 未配置</Tag>
                    ),
                  )}
                </Space>
              )}
              <div style={{ marginTop: 4 }}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {sensors && sensors.length > 0
                    ? `已匹配 ${matchedCount}/${matchedSensors.length} 种 sensor，匹配到的 sensor 帧率会写入用例预期结果。`
                    : '未添加 sensor 配置（可在「Sensors 配置」步骤添加），预期结果中将不包含帧率要求。'}
                </Text>
              </div>
            </Descriptions.Item>
          </Descriptions>

          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Space wrap>
              <Checkbox
                checked={selection.lighting}
                onChange={(e) =>
                  onSelectionChange({ ...selection, lighting: e.target.checked })
                }
              >
                {TEST_TYPE_LIGHTING}
              </Checkbox>
              <Tag color="blue">生成 .raw</Tag>
              <Checkbox
                checked={selection.yuv}
                onChange={(e) => onSelectionChange({ ...selection, yuv: e.target.checked })}
              >
                {TEST_TYPE_YUV}
              </Checkbox>
              <Tag color="purple">生成 .yuv</Tag>
              <Text type="secondary">
                {selectedTypes === 0
                  ? '请至少勾选一种测试类型'
                  : `将生成 ${caseCount} 条用例`}
              </Text>
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
              {selection.yuv && (
                <Col xs={24} md={12} style={{ marginTop: 8 }}>
                  <Text type="secondary">--nito NITO 目录（YUV 图）</Text>
                  <Input
                    value={options.nito_path}
                    onChange={(e) => onOptionsChange({ ...options, nito_path: e.target.value })}
                    placeholder="./nito/"
                  />
                </Col>
              )}
            </Row>

            {firstCamera && selection.lighting && (
              <div>
                <Text strong>
                  raw图命令预览（{firstCamera.group}: {firstCamera.link_index}: {firstCamera.module}）
                </Text>
                <pre style={codeStyle}>{lightingCommand}</pre>
              </div>
            )}

            {firstCamera && selection.yuv && (
              <div>
                <Text strong>
                  YUV 图命令预览（{firstCamera.group}: {firstCamera.link_index}: {firstCamera.module}）
                </Text>
                <pre style={codeStyle}>{yuvCommand}</pre>
              </div>
            )}

            <div style={{ textAlign: 'right' }}>
              <Button type="primary" disabled={selectedTypes === 0} onClick={onGenerate}>
                生成用例
              </Button>
            </div>
          </Space>
        </>
      )}
    </div>
  )
}
