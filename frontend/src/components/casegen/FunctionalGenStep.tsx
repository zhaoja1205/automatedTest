/**
 * 生成测试用例 — 第四步：功能测试生成配置。
 *
 * 支持五类功能测试，可分别勾选：
 * - raw图（生成 .raw）：每个相机一条用例
 * - YUV 图（生成 .yuv）：每个相机一条用例，可勾选 0/1/2 输出通道
 * - ro 读取：每个相机一条用例
 * - al 读取：每个相机一条用例
 * - th 温度直方图读取：仅对勾选的 sensor 型号生成（部分 sensor 不支持该功能）
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
  Select,
  Space,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import {
  buildLightingCommand,
  buildReadoutCommand,
  buildThCommand,
  buildYuvCommand,
  isThTestSensor,
} from '../../utils/casegen/functionalCases'
import { findSensorConfig, formatSensorSummary } from '../../utils/casegen/sensors'
import {
  TEST_TYPE_AL,
  TEST_TYPE_LIGHTING,
  TEST_TYPE_RO,
  TEST_TYPE_TH,
  TEST_TYPE_YUV,
  YUV_CHANNELS,
} from '../../types/casegen'
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
  const readoutCommand =
    platform && firstCamera ? buildReadoutCommand(platform.name, firstCamera, options) : ''
  const thCommand =
    platform && firstCamera ? buildThCommand(platform.name, firstCamera, options) : ''
  const baseSelectedTypes =
    Number(selection.lighting) +
    Number(selection.yuv) +
    Number(selection.ro) +
    Number(selection.al)
  const selectedTypes = baseSelectedTypes + Number(selection.th)
  // th 只对勾选的 sensor 型号生成，因此单独按拓扑统计
  const thCameraCount = platform
    ? platform.topology.filter((row) => isThTestSensor(row.sensor, options)).length
    : 0
  const caseCount =
    (platform?.module_count ?? 0) * baseSelectedTypes + (selection.th ? thCameraCount : 0)
  const platformSensors = platform
    ? Array.from(new Set(platform.topology.map((row) => row.sensor).filter(Boolean)))
    : []
  const matchedSensors = platformSensors.map((name) => ({
    name,
    config: findSensorConfig(sensors, name),
  }))
  const matchedCount = matchedSensors.filter((item) => item.config).length

  return (
    <div style={{ display: visible ? undefined : 'none' }}>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="功能测试：raw图（生成 .raw）、YUV 图（生成 .yuv）、ro / al / th 读取测试"
        description="每个相机为每种勾选的测试类型各生成一条用例；YUV 用例可勾选 0/1/2 输出通道，未勾选的通道会用 -0/-1/-2 关闭；ro / al / th 用例会在起流后输入 gc，再分别输入 ro、al 或 th；th（温度直方图）仅对勾选的 sensor 型号生成，因为部分 sensor 不支持该功能；命令中的 -m 掩码会按相机的 Group / linkIndex 自动生成。"
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
              <Checkbox
                checked={selection.ro}
                onChange={(e) => onSelectionChange({ ...selection, ro: e.target.checked })}
              >
                {TEST_TYPE_RO}
              </Checkbox>
              <Tag color="cyan">读取 readout</Tag>
              <Checkbox
                checked={selection.al}
                onChange={(e) => onSelectionChange({ ...selection, al: e.target.checked })}
              >
                {TEST_TYPE_AL}
              </Checkbox>
              <Tag color="cyan">读取有效像素</Tag>
              <Checkbox
                checked={selection.th}
                onChange={(e) => onSelectionChange({ ...selection, th: e.target.checked })}
              >
                {TEST_TYPE_TH}
              </Checkbox>
              <Tag color="cyan">读取温度直方图</Tag>
              <Text type="secondary">
                {selectedTypes === 0
                  ? '请至少勾选一种测试类型'
                  : `将生成 ${caseCount} 条用例`}
              </Text>
            </Space>

            {selection.th && (
              <Row gutter={16}>
                <Col xs={24} md={16}>
                  <Text type="secondary">支持 th（温度直方图）测试的 sensor 型号</Text>
                  <Select
                    mode="multiple"
                    allowClear
                    style={{ width: '100%', marginTop: 4 }}
                    placeholder="请选择支持 th 测试的 sensor 型号"
                    value={options.th_sensors ?? []}
                    onChange={(value) => onOptionsChange({ ...options, th_sensors: value })}
                    options={platformSensors.map((name) => ({
                      value: name,
                      label: findSensorConfig(sensors, name)
                        ? `${name}（已配置）`
                        : `${name}（未配置）`,
                    }))}
                    notFoundContent="平台拓扑中没有相机 sensor 型号"
                  />
                  <div style={{ marginTop: 4 }}>
                    {platformSensors.length === 0 ? (
                      <Text type="danger" style={{ fontSize: 12 }}>
                        平台拓扑中没有可识别的 sensor 型号，无法生成 th 用例
                      </Text>
                    ) : (options.th_sensors ?? []).length === 0 ? (
                      <Text type="danger" style={{ fontSize: 12 }}>
                        请至少选择一个支持 th 的 sensor 型号，否则不会生成 th 用例
                      </Text>
                    ) : (
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        已选 {options.th_sensors?.length ?? 0} 种型号：{thCameraCount} 个相机将生成 th 用例；
                        不在列表中的 sensor 不会生成 th 用例
                      </Text>
                    )}
                  </div>
                </Col>
              </Row>
            )}

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
              {(selection.yuv || selection.ro || selection.al || selection.th) && (
                <Col xs={24} md={12} style={{ marginTop: 8 }}>
                  <Text type="secondary">--nito NITO 目录（YUV 图 / ro / al / th）</Text>
                  <Input
                    value={options.nito_path}
                    onChange={(e) => onOptionsChange({ ...options, nito_path: e.target.value })}
                    placeholder="./nito/"
                  />
                </Col>
              )}
              {selection.yuv && (
                <Col xs={24} md={12} style={{ marginTop: 8 }}>
                  <Text type="secondary">YUV 输出通道（未勾选的通道用 -0/-1/-2 关闭）</Text>
                  <div style={{ marginTop: 4 }}>
                    <Space size={8}>
                      {YUV_CHANNELS.map((channel) => {
                        const channels = options.yuv_channels ?? [0]
                        return (
                          <Checkbox
                            key={channel}
                            checked={channels.includes(channel)}
                            onChange={(e) => {
                              const next = e.target.checked
                                ? [...channels, channel].sort((a, b) => a - b)
                                : channels.filter((item) => item !== channel)
                              onOptionsChange({ ...options, yuv_channels: next })
                            }}
                          >
                            通道 {channel}
                          </Checkbox>
                        )
                      })}
                    </Space>
                  </div>
                  {(options.yuv_channels ?? [0]).length === 0 && (
                    <Text type="danger" style={{ display: 'block', fontSize: 12 }}>
                      请至少选择一个通道，否则所有 ISP 通道都会被关闭
                    </Text>
                  )}
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

            {firstCamera && (selection.ro || selection.al) && (
              <div>
                <Text strong>
                  ro / al 命令预览（{firstCamera.group}: {firstCamera.link_index}: {firstCamera.module}）
                </Text>
                <pre style={codeStyle}>{readoutCommand}</pre>
              </div>
            )}

            {firstCamera && selection.th && (
              <div>
                <Text strong>
                  th 命令预览（{firstCamera.group}: {firstCamera.link_index}: {firstCamera.module}）
                </Text>
                <pre style={codeStyle}>{thCommand}</pre>
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
