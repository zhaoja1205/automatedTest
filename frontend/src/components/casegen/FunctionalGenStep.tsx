/**
 * 生成测试用例 — 第四步：功能测试生成配置。
 *
 * 全部功能测试用例以「浏览器标签页」的方式组织：
 * - 内置预设标签：raw图 / YUV图 / ro / al / 内参 / th，可切换，也可通过 ×
 *   关闭；关闭后不参与本次生成，点击 + 可从已关闭的预设中重新打开；
 * - 预设与自定义用例使用同一套可编辑字段（描述 / 前置条件 / 步骤 / 预期 /
 *   优先级 / 是否按相机生成），预设可一键恢复默认模板；
 * - 点击标签栏末尾的 + ：存在已关闭的预设时弹出选择列表，否则直接新增
 *   自定义用例标签；自定义标签可通过 × 关闭；
 * - 所有文本字段都支持 {config} / {mask} / {sensorid} 等占位符，
 *   生成时按相机属性自动替换。
 * 若已在「Sensors 配置」步骤添加 sensor 配置，会按 Sensor 名称匹配相机，
 * 并把 sensor 帧率写入用例预期结果。
 */
import { useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Checkbox,
  Col,
  Descriptions,
  Divider,
  Empty,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import {
  buildCaseTemplateContext,
  CASE_TEMPLATE_PLACEHOLDERS,
  isCustomCaseTemplateUsable,
  isThTestSensor,
  platformMaskGroupCount,
  presetCaseEditOf,
  renderCaseTemplate,
} from '../../utils/casegen/functionalCases'
import { findSensorConfig, formatSensorSummary } from '../../utils/casegen/sensors'
import {
  PRESET_CASE_KEYS,
  TEST_TYPE_AL,
  TEST_TYPE_CUSTOM,
  TEST_TYPE_DL_EL,
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
  PresetCaseEdit,
  PresetCaseKey,
  PlatformConfig,
  SensorConfig,
} from '../../types/casegen'

const { Text } = Typography

interface PresetTab {
  key: PresetCaseKey
  label: string
  tagText: string
  tagColor: string
  description: string
}

/** 内置预设标签：相当于自定义用例中的预置模板，点击标签切换配置 */
const PRESET_TABS: PresetTab[] = [
  {
    key: 'lighting',
    label: TEST_TYPE_LIGHTING,
    tagText: '生成 .raw',
    tagColor: 'blue',
    description: '命令使用 -R 输出 RAW 并关闭 ISP0/1/2，起流后输入 gc 触发出帧。',
  },
  {
    key: 'yuv',
    label: TEST_TYPE_YUV,
    tagText: '生成 .yuv',
    tagColor: 'purple',
    description: '按所选通道输出 YUV，未勾选的通道会用 -0/-1/-2 关闭，起流后输入 gc 触发出帧。',
  },
  {
    key: 'ro',
    label: TEST_TYPE_RO,
    tagText: '读取 readout',
    tagColor: 'cyan',
    description: '起流后输入 gc 触发出帧，再输入 ro 读取 readout 信息。',
  },
  {
    key: 'al',
    label: TEST_TYPE_AL,
    tagText: '读取有效像素',
    tagColor: 'cyan',
    description: '起流后输入 gc 触发出帧，再输入 al 读取有效像素信息。',
  },
  {
    key: 'intrinsic',
    label: TEST_TYPE_INTRINSIC,
    tagText: '读取内参（CRC 校验）',
    tagColor: 'magenta',
    description: '通过 -e 读取模组内参（寄存器内容）并校验 CRC，-r 4 表示运行 4 秒后自动退出。',
  },
  {
    key: 'th',
    label: TEST_TYPE_TH,
    tagText: '读取温度直方图',
    tagColor: 'green',
    description: '起流后输入 gc 触发出帧，再输入 th 读取温度直方图；仅对勾选的 sensor 型号生成。',
  },
  {
    key: 'dl_el',
    label: TEST_TYPE_DL_EL,
    tagText: 'dl el 热插拔验证',
    tagColor: 'volcano',
    description:
      '起流后输入 gc 触发出帧，再输入 dl 关闭链路、输入 el 恢复链路，验证帧率降为 0 后恢复。',
  },
]

const isPresetKey = (key: string): key is PresetCaseKey =>
  (PRESET_CASE_KEYS as readonly string[]).includes(key)

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

/** 标签页左上角的状态圆点：启用为绿色 / 自定义为橙色，禁用为灰色 */
const tabDotStyle = (
  enabled: boolean,
  activeColor = '#52c41a',
): React.CSSProperties => ({
  display: 'inline-block',
  width: 6,
  height: 6,
  borderRadius: 3,
  background: enabled ? activeColor : '#d9d9d9',
})

/** 新建自定义用例标签时填写的默认内容，用于展示常用占位符的用法 */
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
  enabled: true,
})

/** 在测试步骤末尾追加占位符 */
const appendPlaceholderText = (steps: string, placeholder: string): string => {
  const current = steps || ''
  const separator = current && !current.endsWith('\n') ? '\n' : ''
  return `${current}${separator}${placeholder}`
}

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
  /** 当前激活的标签页，默认选中 raw图预设 */
  const [activeCaseTab, setActiveCaseTab] = useState<string>('lighting')
  /** 点击 + 时若存在已关闭的预设，弹出选择框 */
  const [presetPickerOpen, setPresetPickerOpen] = useState(false)

  const enabledCameras = (platform?.topology ?? []).filter((row) => row.enabled !== false)
  const firstCamera = enabledCameras[0]
  const maskGroupCount = platformMaskGroupCount(platform)

  // 已关闭的预设标签：不显示、不参与生成；+ 可重新打开
  const closedPresets = options.closed_presets ?? []
  const visiblePresetTabs = PRESET_TABS.filter(
    (preset) => !closedPresets.includes(preset.key),
  )
  const closedPresetTabs = PRESET_TABS.filter((preset) =>
    closedPresets.includes(preset.key),
  )

  /** 取内置预设的有效可编辑内容（用户编辑优先，否则使用默认模板） */
  const effectivePresetEdit = (key: PresetCaseKey): PresetCaseEdit => ({
    ...presetCaseEditOf(key),
    ...(options.preset_cases?.[key] ?? {}),
  })

  // th 只对勾选的 sensor 型号生成，因此单独按拓扑统计
  const thCameraCount = platform && firstCamera
    ? enabledCameras.filter((row) => isThTestSensor(row.sensor, options)).length
    : 0

  // 预设用例条数：仅统计未关闭且已启用的类型，并按 per_camera 设置与生成逻辑保持一致
  const presetCaseCount = PRESET_CASE_KEYS.reduce((total, key) => {
    if (!selection[key] || closedPresets.includes(key)) return total
    const perCamera = effectivePresetEdit(key).per_camera !== false
    if (key === 'th') {
      if (perCamera) return total + thCameraCount
      return total + (thCameraCount > 0 ? 1 : 0)
    }
    if (perCamera) return total + enabledCameras.length
    return total + (enabledCameras.length > 0 ? 1 : 0)
  }, 0)

  const enabledPresetTypes = PRESET_CASE_KEYS.filter(
    (key) => selection[key] && !closedPresets.includes(key),
  ).length

  // 自定义用例：仅统计「参与本次生成」且内容有效的模板
  const customTemplates = options.custom_cases ?? []
  const usableCustomTemplates = customTemplates.filter(
    (template) => template.enabled !== false && isCustomCaseTemplateUsable(template),
  )
  const selectedTypes =
    enabledPresetTypes + (usableCustomTemplates.length > 0 ? 1 : 0)
  const customPerCameraCount = usableCustomTemplates.filter(
    (template) => template.per_camera !== false,
  ).length
  const customGlobalCount = usableCustomTemplates.length - customPerCameraCount
  const caseCount =
    presetCaseCount +
    enabledCameras.length * customPerCameraCount +
    (enabledCameras.length > 0 ? customGlobalCount : 0)

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

  // 关闭预设 / 删除自定义标签 / 恢复草稿后，若当前标签不可见则切到第一个可见标签
  const visibleTabKeys = [
    ...visiblePresetTabs.map((preset) => preset.key as string),
    ...customTemplates.map((template) => template.id),
  ]
  const visibleTabKeySignature = visibleTabKeys.join('|')
  useEffect(() => {
    if (visibleTabKeys.length === 0) {
      if (activeCaseTab !== '') setActiveCaseTab('')
      return
    }
    if (!visibleTabKeys.includes(activeCaseTab)) {
      setActiveCaseTab(visibleTabKeys[0])
    }
  }, [activeCaseTab, visibleTabKeySignature])

  /** 更新自定义用例模板列表 */
  const setCustomTemplates = (next: CustomCaseTemplate[]) => {
    onOptionsChange({ ...options, custom_cases: next })
  }

  /** 新增一条自定义用例标签，并切换到该标签 */
  const addCustomTemplate = () => {
    const template = createDefaultCustomCase()
    setCustomTemplates([...customTemplates, template])
    setActiveCaseTab(template.id)
  }

  /** 修改单条自定义模板字段 */
  const updateCustomTemplate = (id: string, patch: Partial<CustomCaseTemplate>) => {
    setCustomTemplates(
      customTemplates.map((template) =>
        template.id === id ? { ...template, ...patch } : template,
      ),
    )
  }

  /** 删除单条自定义模板（浏览器式标签的 × / 关闭操作） */
  const removeCustomTemplate = (id: string) => {
    setCustomTemplates(customTemplates.filter((template) => template.id !== id))
  }

  /** 关闭内置预设标签：仅隐藏，不修改启用状态与编辑内容 */
  const closePresetTab = (key: PresetCaseKey) => {
    if (closedPresets.includes(key)) return
    onOptionsChange({ ...options, closed_presets: [...closedPresets, key] })
  }

  /** 重新打开内置预设标签，并切换到该标签 */
  const reopenPresetTab = (key: PresetCaseKey) => {
    onOptionsChange({
      ...options,
      closed_presets: closedPresets.filter((item) => item !== key),
    })
    setActiveCaseTab(key)
    setPresetPickerOpen(false)
  }

  /** 点击标签栏 +：存在已关闭预设时弹出选择框，否则直接新增自定义用例 */
  const handleAddTab = () => {
    if (closedPresets.length === 0) {
      addCustomTemplate()
      return
    }
    setPresetPickerOpen(true)
  }

  /** 修改内置预设字段；首次修改时保存一份完整可编辑内容 */
  const updatePresetTemplate = (
    key: PresetCaseKey,
    patch: Partial<PresetCaseEdit>,
  ) => {
    const current = effectivePresetEdit(key)
    onOptionsChange({
      ...options,
      preset_cases: {
        ...options.preset_cases,
        [key]: { ...current, ...patch },
      },
    })
  }

  /** 恢复内置预设的默认模板 */
  const resetPresetTemplate = (key: PresetCaseKey) => {
    const next = { ...options.preset_cases }
    delete next[key]
    onOptionsChange({ ...options, preset_cases: next })
  }

  /** 标签栏的 + 新增 / × 关闭 */
  const handleTabEdit = (
    targetKey: React.MouseEvent | React.KeyboardEvent | string,
    action: 'add' | 'remove',
  ) => {
    if (action === 'add') {
      handleAddTab()
      return
    }
    if (typeof targetKey !== 'string') return
    if (isPresetKey(targetKey)) {
      closePresetTab(targetKey)
    } else {
      removeCustomTemplate(targetKey)
    }
  }

  /** 标签页标题：状态圆点 + 名称，禁用时置灰 */
  const presetTabLabel = (preset: PresetTab) => (
    <Space size={6}>
      <span style={tabDotStyle(selection[preset.key])} />
      <span style={{ color: selection[preset.key] ? undefined : 'rgba(0, 0, 0, 0.45)' }}>
        {preset.label}
      </span>
    </Space>
  )

  const customTabLabel = (template: CustomCaseTemplate, index: number) => (
    <Space size={6}>
      <span style={tabDotStyle(template.enabled !== false, '#fa8c16')} />
      <span
        style={{
          color: template.enabled !== false ? undefined : 'rgba(0, 0, 0, 0.45)',
        }}
      >
        {template.test_type?.trim() || `自定义用例 ${index + 1}`}
      </span>
    </Space>
  )

  /**
   * 预设与自定义用例共用的可编辑字段。
   *
   * testTypeField 用于自定义用例插入「测试类型」输入框；预设的测试类型固定，
   * 不传该字段。
   */
  const renderEditableCaseFields = (
    fields: PresetCaseEdit,
    onChange: (patch: Partial<PresetCaseEdit>) => void,
    testTypeField?: React.ReactNode,
  ) => (
    <Space direction="vertical" size={10} style={{ width: '100%' }}>
      <Row gutter={12}>
        {testTypeField && (
          <Col xs={24} md={8}>
            {testTypeField}
          </Col>
        )}
        <Col xs={12} md={testTypeField ? 4 : 6}>
          <Text type="secondary">优先级</Text>
          <Input
            value={fields.priority}
            onChange={(e) => onChange({ priority: e.target.value })}
            placeholder="P1"
          />
        </Col>
        <Col
          xs={24}
          md={testTypeField ? 12 : 18}
          style={{ display: 'flex', alignItems: 'flex-end' }}
        >
          <Checkbox
            checked={fields.per_camera !== false}
            onChange={(e) => onChange({ per_camera: e.target.checked })}
          >
            每台已启用相机各生成一条（否则仅生成一条）
          </Checkbox>
        </Col>
      </Row>

      <div>
        <Text type="secondary">用例描述</Text>
        <Input.TextArea
          autoSize={{ minRows: 2, maxRows: 4 }}
          value={fields.description}
          onChange={(e) => onChange({ description: e.target.value })}
        />
      </div>

      <div>
        <Text type="secondary">前置条件</Text>
        <Input.TextArea
          autoSize={{ minRows: 2, maxRows: 4 }}
          value={fields.prerequisites}
          onChange={(e) => onChange({ prerequisites: e.target.value })}
        />
      </div>

      <div>
        <Text type="secondary">测试步骤（支持占位符）</Text>
        <Input.TextArea
          autoSize={{ minRows: 4, maxRows: 12 }}
          value={fields.steps}
          onChange={(e) => onChange({ steps: e.target.value })}
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
                      onChange({
                        steps: appendPlaceholderText(fields.steps, `{${item.key}}`),
                      })
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
          value={fields.expected}
          onChange={(e) => onChange({ expected: e.target.value })}
        />
      </div>

      {templatePreviewContext && (
        <div>
          <Text type="secondary" style={{ fontSize: 12 }}>
            测试步骤预览（{firstCamera?.group}: {firstCamera?.link_index}: {firstCamera?.module}）
            {fields.per_camera === false ? '，仅生成一条时按该相机替换' : ''}
          </Text>
          <pre style={codeStyle}>
            {renderCaseTemplate(fields.steps, templatePreviewContext)}
          </pre>
        </div>
      )}
    </Space>
  )

  /** 预设标签面板：与自定义用例使用同一套可编辑字段 */
  const renderPresetPanel = (key: PresetCaseKey) => {
    const preset = PRESET_TABS.find((item) => item.key === key)!
    const fields = effectivePresetEdit(key)
    const edited = Boolean(options.preset_cases?.[key])
    return (
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Space wrap align="center">
          <Checkbox
            checked={selection[key]}
            onChange={(e) =>
              onSelectionChange({ ...selection, [key]: e.target.checked })
            }
          >
            参与本次生成
          </Checkbox>
          <Text type="secondary">测试类型：</Text>
          <Tag color={preset.tagColor}>{preset.label}</Tag>
          <Tag color={preset.tagColor}>{preset.tagText}</Tag>
          {edited && (
            <Button size="small" onClick={() => resetPresetTemplate(key)}>
              恢复默认
            </Button>
          )}
        </Space>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {preset.description}
        </Text>

        {key === 'yuv' && (
          <div>
            <Text type="secondary">YUV 输出通道（未勾选的通道用 -0/-1/-2 关闭）</Text>
            <div style={{ marginTop: 4 }}>
              <Space size={8} wrap>
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
          </div>
        )}

        {key === 'th' && (
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

        {renderEditableCaseFields(fields, (patch) => updatePresetTemplate(key, patch))}
      </Space>
    )
  }

  /** 自定义用例标签面板：与预设共用同一套可编辑字段 */
  const renderCustomPanel = (template: CustomCaseTemplate) => (
    <Space direction="vertical" size={10} style={{ width: '100%' }}>
      <Space wrap align="center">
        <Checkbox
          checked={template.enabled !== false}
          onChange={(e) =>
            updateCustomTemplate(template.id, { enabled: e.target.checked })
          }
        >
          参与本次生成
        </Checkbox>
        <Text type="secondary" style={{ fontSize: 12 }}>
          在描述 / 前置条件 / 测试步骤 / 预期结果中可使用
          {` {config} {mask} {sensorid} `}
          等占位符，生成时按相机自动替换；点击标签上的 × 可移除该用例。
        </Text>
      </Space>

      {template.enabled !== false && !isCustomCaseTemplateUsable(template) && (
        <Text type="danger" style={{ fontSize: 12 }}>
          请填写描述 / 测试步骤 / 预期结果之一，否则该标签不会生成用例。
        </Text>
      )}

      {renderEditableCaseFields(
        template,
        (patch) => updateCustomTemplate(template.id, patch),
        (
          <>
            <Text type="secondary">测试类型</Text>
            <Input
              value={template.test_type}
              onChange={(e) =>
                updateCustomTemplate(template.id, { test_type: e.target.value })
              }
              placeholder={TEST_TYPE_CUSTOM}
            />
          </>
        ),
      )}
    </Space>
  )

  /** 标签页列表：内置预设（未关闭的）+ 自定义用例，均可通过 × 关闭 */
  const caseTabItems = [
    ...visiblePresetTabs.map((preset) => ({
      key: preset.key,
      label: presetTabLabel(preset),
      closable: true,
      children: renderPresetPanel(preset.key),
    })),
    ...customTemplates.map((template, index) => ({
      key: template.id,
      label: customTabLabel(template, index),
      closable: true,
      children: renderCustomPanel(template),
    })),
  ]

  return (
    <div style={{ display: visible ? undefined : 'none' }}>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="功能测试：标签页切换测试类型，+ 新增自定义用例或重新打开已关闭的预设"
        description="内置预设（raw图 / YUV图 / ro / al / 内参 / th / dl el）与自定义用例统一以标签页组织，均可直接编辑描述 / 前置条件 / 测试步骤 / 预期结果，预设可一键恢复默认模板。点击 × 可关闭任意标签；关闭的预设不参与本次生成，点击标签栏末尾的 + 时，若存在已关闭的预设会弹出选择列表，没有任何已关闭预设时直接新增自定义用例。文本支持 {config}、{mask}、{sensorid} 等占位符，生成时按相机自动替换。"
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
            <div>
              <Text strong>公共参数</Text>
              <Row gutter={16} style={{ marginTop: 6 }}>
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
                <Col xs={24} md={12}>
                  <Text type="secondary">--nito NITO 目录（YUV 图 / ro / al / th / 自定义用例）</Text>
                  <Input
                    value={options.nito_path}
                    onChange={(e) => onOptionsChange({ ...options, nito_path: e.target.value })}
                    placeholder="./nito/"
                  />
                </Col>
              </Row>
            </div>

            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>
                点击标签切换测试类型；预设与自定义用例的字段均可编辑，任意标签都可通过 × 关闭。关闭的预设不参与本次生成，+ 会优先列出已关闭的预设供重新打开；没有任何已关闭预设时直接新增自定义用例。
              </Text>
            </div>

            <Tabs
              type="editable-card"
              activeKey={activeCaseTab}
              onChange={setActiveCaseTab}
              onEdit={handleTabEdit}
              items={caseTabItems}
              hideAdd={false}
              style={{ width: '100%' }}
            />

            <Modal
              title="重新打开预设标签"
              open={presetPickerOpen}
              onCancel={() => setPresetPickerOpen(false)}
              footer={null}
              width={440}
            >
              <Text type="secondary" style={{ fontSize: 12 }}>
                关闭的预设不参与本次生成；重新打开后会恢复原有的启用状态与编辑内容。
              </Text>
              <Space direction="vertical" size={8} style={{ width: '100%', marginTop: 12 }}>
                {closedPresetTabs.map((preset) => (
                  <Button
                    key={preset.key}
                    block
                    onClick={() => reopenPresetTab(preset.key)}
                    style={{
                      height: 'auto',
                      padding: '8px 12px',
                      display: 'flex',
                      justifyContent: 'flex-start',
                    }}
                  >
                    <Space size={8} wrap>
                      <span style={tabDotStyle(selection[preset.key])} />
                      <Tag color={preset.tagColor} style={{ marginInlineEnd: 0 }}>
                        {preset.label}
                      </Tag>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {preset.tagText}
                      </Text>
                      {selection[preset.key] && <Tag color="green">已启用</Tag>}
                    </Space>
                  </Button>
                ))}
              </Space>
              <Divider style={{ margin: '12px 0' }} />
              <Button
                block
                onClick={() => {
                  setPresetPickerOpen(false)
                  addCustomTemplate()
                }}
              >
                + 新增自定义用例
              </Button>
            </Modal>

            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                gap: 12,
              }}
            >
              <Text type="secondary">
                {selectedTypes === 0
                  ? '请至少启用一种测试类型或填写一条自定义用例'
                  : `将生成 ${caseCount} 条用例`}
              </Text>
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
