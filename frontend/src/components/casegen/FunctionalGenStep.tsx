/**
 * 生成测试用例 — 第四步：功能测试生成配置。
 *
 * 支持六类功能测试，可分别勾选：
 * - raw图（生成 .raw）：每个相机一条用例
 * - YUV 图（生成 .yuv）：每个相机一条用例，可勾选 0/1/2 输出通道
 * - ro 读取：每个相机一条用例
 * - al 读取：每个相机一条用例
 * - 内参读取：每个相机一条用例（-e 读取寄存器内容并校验 CRC）
 * - th 温度直方图读取：仅对勾选的 sensor 型号生成（部分 sensor 不支持该功能）
 * 若已在「Sensors 配置」步骤添加 sensor 配置，会按 Sensor 名称匹配相机，
 * 并把 sensor 帧率写入用例预期结果。
 */
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Descriptions,
  Divider,
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
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import {
  buildCaseTemplateContext,
  buildIntrinsicCommand,
  buildLightingCommand,
  buildReadoutCommand,
  buildThCommand,
  buildYuvCommand,
  CASE_TEMPLATE_PLACEHOLDERS,
  isCustomCaseTemplateUsable,
  isThTestSensor,
  platformMaskGroupCount,
  renderCaseTemplate,
} from '../../utils/casegen/functionalCases'
import { findSensorConfig, formatSensorSummary } from '../../utils/casegen/sensors'
import {
  TEST_TYPE_AL,
  TEST_TYPE_CUSTOM,
  TEST_TYPE_INTRINSIC,
  TEST_TYPE_LIGHTING,
  TEST_TYPE_RO,
  TEST_TYPE_TH,
  TEST_TYPE_YUV,
  YUV_CHANNELS,
} from '../../types/casegen'
import type {
  CustomCaseTemplate,
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

/** 新建自定义用例模板时填写的默认内容，用于展示常用占位符的用法 */
const createDefaultCustomCase = (): CustomCaseTemplate => ({
  id: `custom-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
  test_type: TEST_TYPE_CUSTOM,
  description: '验证 group{group} linkindex{link_index}: {module} 的自定义测试情况',
  prerequisites: '1、模组 {module} 已正确连接\n2、板端已上电，驱动已加载',
  steps: [
    '1、输入命令：./nvsipl_camera -c {config} -m "{mask}" -R -0 -1 -2 -s -f {image_path} --skipFrames {skip_frames} --writeFrames {write_frames} -Z',
    '2、输入gc {sensorid}',
  ].join('\n'),
  expected: '1、执行命令无报错\n2、结果符合预期',
  priority: 'P1',
  per_camera: true,
})

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
  const enabledCameras = (platform?.topology ?? []).filter((row) => row.enabled !== false)
  const firstCamera = enabledCameras[0]
  const maskGroupCount = platformMaskGroupCount(platform)
  const lightingCommand =
    platform && firstCamera
      ? buildLightingCommand(platform.name, firstCamera, options, maskGroupCount)
      : ''
  const yuvCommand =
    platform && firstCamera
      ? buildYuvCommand(platform.name, firstCamera, options, maskGroupCount)
      : ''
  const readoutCommand =
    platform && firstCamera
      ? buildReadoutCommand(platform.name, firstCamera, options, maskGroupCount)
      : ''
  const thCommand =
    platform && firstCamera
      ? buildThCommand(platform.name, firstCamera, options, maskGroupCount)
      : ''
  const intrinsicCommand =
    platform && firstCamera
      ? buildIntrinsicCommand(platform.name, firstCamera, maskGroupCount)
      : ''
  const baseSelectedTypes =
    Number(selection.lighting) +
    Number(selection.yuv) +
    Number(selection.ro) +
    Number(selection.al) +
    Number(selection.intrinsic)
  const selectedTypes = baseSelectedTypes + Number(selection.th) + Number(selection.custom)
  // th 只对勾选的 sensor 型号生成，因此单独按拓扑统计
  const thCameraCount = platform
    ? enabledCameras.filter((row) => isThTestSensor(row.sensor, options)).length
    : 0
  // 自定义用例：按相机生成的模板 × 相机数 + 仅生成一条的模板数
  const customTemplates = options.custom_cases ?? []
  const usableCustomTemplates = customTemplates.filter(isCustomCaseTemplateUsable)
  const customPerCameraCount = usableCustomTemplates.filter(
    (template) => template.per_camera !== false,
  ).length
  const customGlobalCount = usableCustomTemplates.length - customPerCameraCount
  const customCaseCount = selection.custom
    ? enabledCameras.length * customPerCameraCount + customGlobalCount
    : 0
  const caseCount =
    enabledCameras.length * baseSelectedTypes +
    (selection.th ? thCameraCount : 0) +
    customCaseCount
  const platformSensors = platform
    ? Array.from(new Set(enabledCameras.map((row) => row.sensor).filter(Boolean)))
    : []
  const matchedSensors = platformSensors.map((name) => ({
    name,
    config: findSensorConfig(sensors, name),
  }))
  const matchedCount = matchedSensors.filter((item) => item.config).length
  // 自定义用例预览：用第一台已启用相机替换占位符
  const templatePreviewContext =
    platform && firstCamera
      ? buildCaseTemplateContext(platform, firstCamera, options, sensors, maskGroupCount)
      : null

  /** 更新自定义用例模板列表 */
  const setCustomTemplates = (next: CustomCaseTemplate[]) => {
    onOptionsChange({ ...options, custom_cases: next })
  }

  /** 新增一条模板，并自动勾选「自定义测试用例」 */
  const addCustomTemplate = () => {
    onOptionsChange({
      ...options,
      custom_cases: [...customTemplates, createDefaultCustomCase()],
    })
    if (!selection.custom) onSelectionChange({ ...selection, custom: true })
  }

  /** 修改单条模板字段 */
  const updateCustomTemplate = (id: string, patch: Partial<CustomCaseTemplate>) => {
    setCustomTemplates(
      customTemplates.map((template) =>
        template.id === id ? { ...template, ...patch } : template,
      ),
    )
  }

  /** 删除单条模板 */
  const removeCustomTemplate = (id: string) => {
    setCustomTemplates(customTemplates.filter((template) => template.id !== id))
  }

  /** 把占位符追加到测试步骤末尾 */
  const appendPlaceholder = (template: CustomCaseTemplate, placeholder: string) => {
    const current = template.steps || ''
    const separator = current && !current.endsWith('\n') ? '\n' : ''
    updateCustomTemplate(template.id, { steps: `${current}${separator}${placeholder}` })
  }

  return (
    <div style={{ display: visible ? undefined : 'none' }}>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="功能测试：raw图（生成 .raw）、YUV 图（生成 .yuv）、ro / al / 内参 / th 读取测试"
        description="每个相机为每种勾选的测试类型各生成一条用例；YUV 用例可勾选 0/1/2 输出通道，未勾选的通道会用 -0/-1/-2 关闭；ro / al / th 用例会在起流后输入 gc，再分别输入 ro、al 或 th；内参读取用例通过 -e 读取模组内参（寄存器内容）并校验 CRC；th（温度直方图）仅对勾选的 sensor 型号生成，因为部分 sensor 不支持该功能；命令中的 -m 掩码会按相机的 Group / linkIndex 自动生成。自定义测试用例支持在字段中书写 {config}、{mask}、{sensorid} 等占位符，生成时按每台相机的实际配置自动替换。"
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
            <Descriptions.Item label="相机数">{enabledCameras.length}（已启用）</Descriptions.Item>
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
                checked={selection.intrinsic}
                onChange={(e) =>
                  onSelectionChange({ ...selection, intrinsic: e.target.checked })
                }
              >
                {TEST_TYPE_INTRINSIC}
              </Checkbox>
              <Tag color="cyan">读取内参（CRC 校验）</Tag>
              <Checkbox
                checked={selection.th}
                onChange={(e) => onSelectionChange({ ...selection, th: e.target.checked })}
              >
                {TEST_TYPE_TH}
              </Checkbox>
              <Tag color="cyan">读取温度直方图</Tag>
              <Checkbox
                checked={selection.custom}
                onChange={(e) =>
                  onSelectionChange({ ...selection, custom: e.target.checked })
                }
              >
                自定义测试用例
              </Checkbox>
              <Tag color="orange">占位符自动替换</Tag>
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

            <Divider orientation="left" plain style={{ margin: '4px 0' }}>
              自定义测试用例
            </Divider>

            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Space wrap align="center">
                <Button icon={<PlusOutlined />} onClick={addCustomTemplate}>
                  添加自定义用例
                </Button>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  在描述 / 前置条件 / 测试步骤 / 预期结果中可使用
                  {` {config} {mask} {sensorid} `}
                  等占位符，生成时按相机自动替换；未识别的占位符会原样保留。
                </Text>
              </Space>

              {selection.custom && usableCustomTemplates.length === 0 && (
                <Text type="danger" style={{ fontSize: 12 }}>
                  请至少添加一条自定义用例，并在描述 / 测试步骤 / 预期结果中填写内容，否则不会生成自定义用例。
                </Text>
              )}

              {customTemplates.map((template, index) => (
                <Card
                  key={template.id}
                  size="small"
                  title={`自定义用例 ${index + 1}`}
                  extra={(
                    <Button
                      danger
                      type="text"
                      size="small"
                      icon={<DeleteOutlined />}
                      onClick={() => removeCustomTemplate(template.id)}
                    >
                      删除
                    </Button>
                  )}
                  style={{ background: '#fafafa' }}
                >
                  <Space direction="vertical" size={8} style={{ width: '100%' }}>
                    <Row gutter={12}>
                      <Col xs={24} md={8}>
                        <Text type="secondary">测试类型</Text>
                        <Input
                          value={template.test_type}
                          onChange={(e) =>
                            updateCustomTemplate(template.id, { test_type: e.target.value })
                          }
                          placeholder={TEST_TYPE_CUSTOM}
                        />
                      </Col>
                      <Col xs={12} md={4}>
                        <Text type="secondary">优先级</Text>
                        <Input
                          value={template.priority}
                          onChange={(e) =>
                            updateCustomTemplate(template.id, { priority: e.target.value })
                          }
                          placeholder="P1"
                        />
                      </Col>
                      <Col xs={24} md={12} style={{ display: 'flex', alignItems: 'flex-end' }}>
                        <Checkbox
                          checked={template.per_camera !== false}
                          onChange={(e) =>
                            updateCustomTemplate(template.id, { per_camera: e.target.checked })
                          }
                        >
                          每台已启用相机各生成一条（否则仅生成一条）
                        </Checkbox>
                      </Col>
                    </Row>

                    <div>
                      <Text type="secondary">用例描述</Text>
                      <Input.TextArea
                        autoSize={{ minRows: 2, maxRows: 4 }}
                        value={template.description}
                        onChange={(e) =>
                          updateCustomTemplate(template.id, { description: e.target.value })
                        }
                      />
                    </div>

                    <div>
                      <Text type="secondary">前置条件</Text>
                      <Input.TextArea
                        autoSize={{ minRows: 2, maxRows: 4 }}
                        value={template.prerequisites}
                        onChange={(e) =>
                          updateCustomTemplate(template.id, { prerequisites: e.target.value })
                        }
                      />
                    </div>

                    <div>
                      <Text type="secondary">测试步骤（支持占位符）</Text>
                      <Input.TextArea
                        autoSize={{ minRows: 4, maxRows: 12 }}
                        value={template.steps}
                        onChange={(e) =>
                          updateCustomTemplate(template.id, { steps: e.target.value })
                        }
                        style={{ fontFamily: 'monospace' }}
                      />
                      <div style={{ marginTop: 6 }}>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          点击占位符追加到测试步骤末尾：
                        </Text>
                        <div style={{ marginTop: 4 }}>
                          <Space wrap size={[4, 4]}>
                            {CASE_TEMPLATE_PLACEHOLDERS.map((item) => (
                              <Tooltip key={item.key} title={item.label}>
                                <Tag
                                  color="geekblue"
                                  style={{ cursor: 'pointer', marginInlineEnd: 0, fontSize: 12 }}
                                  onClick={() =>
                                    appendPlaceholder(template, `{${item.key}}`)
                                  }
                                >
                                  {`{${item.key}}`}
                                </Tag>
                              </Tooltip>
                            ))}
                          </Space>
                        </div>
                      </div>
                    </div>

                    <div>
                      <Text type="secondary">预期结果</Text>
                      <Input.TextArea
                        autoSize={{ minRows: 3, maxRows: 8 }}
                        value={template.expected}
                        onChange={(e) =>
                          updateCustomTemplate(template.id, { expected: e.target.value })
                        }
                      />
                    </div>

                    {templatePreviewContext && (
                      <div>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          测试步骤预览（{firstCamera?.group}: {firstCamera?.link_index}: {firstCamera?.module}）
                          {template.per_camera === false ? '，仅生成一条时按该相机替换' : ''}
                        </Text>
                        <pre style={codeStyle}>
                          {renderCaseTemplate(template.steps, templatePreviewContext)}
                        </pre>
                      </div>
                    )}
                  </Space>
                </Card>
              ))}
            </Space>

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

            {firstCamera && selection.intrinsic && (
              <div>
                <Text strong>
                  内参读取命令预览（{firstCamera.group}: {firstCamera.link_index}: {firstCamera.module}）
                </Text>
                <pre style={codeStyle}>{intrinsicCommand}</pre>
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
              <Button
                type="primary"
                disabled={
                  selectedTypes === 0 ||
                  (selection.custom && usableCustomTemplates.length === 0)
                }
                onClick={onGenerate}
              >
                生成用例
              </Button>
            </div>
          </Space>
        </>
      )}
    </div>
  )
}
