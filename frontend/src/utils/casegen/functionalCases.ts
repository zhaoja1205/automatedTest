/**
 * 功能测试与压力测试用例生成。
 *
 * 功能测试实现六类：
 * - raw图：只输出 RAW（-R），起流后输入 gc 触发出帧，验证能否正常出图
 * - YUV 图：按所选通道输出 YUV（未选中的通道用 -0/-1/-2 关闭），
 *   起流后输入 gc 触发出帧，验证出图
 * - ro 测试：起流后输入 gc 触发出帧，再输入 ro 读取 readout 信息
 * - al 测试：起流后输入 gc 触发出帧，再输入 al 读取有效像素信息
 * - 内参读取：通过 -e 参数读取模组内参（寄存器内容），并校验 CRC
 * - th 测试：起流后输入 gc 触发出帧，再输入 th 读取温度直方图；部分 sensor
 *   不支持该功能，仅对勾选的 sensor 型号生成
 *
 * 压力测试单独成组：每条用例可配置同时起流的相机组合与「反复起流 N 次」。
 * 后续新增类型时按同样结构扩展。
 */
import type {
  CustomCaseTemplate,
  FunctionalTestOptions,
  FunctionalTestSelection,
  GeneratedCase,
  PlatformConfig,
  PlatformTopologyRow,
  RawLightingOptions,
  SensorConfig,
  StabilityTestOptions,
  StressTestOptions,
} from '../../types/casegen'
import {
  DEFAULT_STABILITY_DURATION_MINUTES,
  DEFAULT_STRESS_REPEAT_COUNT,
  TEST_TYPE_AL,
  TEST_TYPE_CUSTOM,
  TEST_TYPE_INTRINSIC,
  TEST_TYPE_LIGHTING,
  TEST_TYPE_RO,
  TEST_TYPE_STABILITY,
  TEST_TYPE_STRESS,
  TEST_TYPE_TH,
  TEST_TYPE_YUV,
} from '../../types/casegen'
import { findSensorConfig } from './sensors'

const RAW_EXPECTED =
  '1、执行命令无报错，可生成.raw文件\n2、raw可正常查看，无异常'

const YUV_EXPECTED_LINE1 = '1、执行命令无报错，可生成.yuv文件'

const READOUT_EXPECTED_HEAD = '1、执行命令无报错，输入gc后帧率正常'

const RO_EXPECTED_LINE2 = '2、ro可正常读取readout信息，无异常'

const AL_EXPECTED_LINE2_FALLBACK = '2、al可正常读取有效像素信息（Vertical、horizontal），无异常'

const TH_EXPECTED_LINE2 = '2、th可正常读取温度直方图信息，无异常'

const INTRINSIC_EXPECTED =
  '1、执行命令无报错\n2、日志中打印出eeprom芯片内容\n3、CRC校验通过'

/** 带圈数字；①②… 开头的行会被执行器视为注释，不参与命令执行 */
const CIRCLED_NUMBERS = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩']

/**
 * 在命令步骤后追加参数备注。
 *
 * 命令本身为第 1 步，备注从 ① 开始编号，例如：
 *   1、输入命令：./nvsipl_camera ...
 *   ①、-m 指定模组位置
 */
function appendCommandNotes(commandStep: string, notes: string[]): string {
  const lines = [commandStep]
  notes.forEach((note, index) => {
    const symbol = CIRCLED_NUMBERS[index]
    if (symbol) lines.push(`${symbol}、${note}`)
  })
  return lines.join('\n')
}

/** nvsipl_camera 通用参数备注 */
const BASE_COMMAND_NOTES = ['-m 指定模组位置', '-c 指定平台配置']

/** 各类用例命令的附加参数备注 */
const RAW_COMMAND_NOTES = [
  ...BASE_COMMAND_NOTES,
  '-f 指定输出目录',
  '--skipFrames 跳过帧数',
  '--writeFrames 写帧数',
]
const YUV_COMMAND_NOTES = [
  ...BASE_COMMAND_NOTES,
  '--nito 指定NITO目录',
  '-f 指定输出目录',
]
const READOUT_COMMAND_NOTES = [...BASE_COMMAND_NOTES, '--nito 指定NITO目录']
const INTRINSIC_COMMAND_NOTES = [
  ...BASE_COMMAND_NOTES,
  '-e 读取EEPROM内参',
  '-r 4 运行4秒后自动退出',
]

/** 从 sensor 配置中取期望帧率（取第一个配置了 fps 的 virtual channel） */
function sensorFps(sensor?: SensorConfig): number | null {
  const channel = sensor?.virtual_channels.find((vc) => vc.fps !== null && vc.fps > 0)
  return channel?.fps ?? null
}

/** 从 sensor 配置中取分辨率（取第一个配置了宽高的 virtual channel） */
function sensorResolutionSize(
  sensor?: SensorConfig,
): { width: number; height: number } | null {
  const channel = sensor?.virtual_channels.find(
    (vc) => vc.width !== null && vc.height !== null,
  )
  return channel ? { width: channel.width!, height: channel.height! } : null
}

/** 从 sensor 配置中取分辨率文本，如 1920x1536 */
function sensorResolution(sensor?: SensorConfig): string {
  const size = sensorResolutionSize(sensor)
  return size ? `${size.width}x${size.height}` : ''
}

/** 组装预期结果：有 sensor 帧率时追加「帧率稳定在 xx fps 左右」 */
function buildExpectedResult(base: string, sensor?: SensorConfig): string {
  const fps = sensorFps(sensor)
  if (fps === null) return base
  return `${base}\n3、帧率稳定在 ${fps}fps 左右`
}

/** 组装 YUV 图预期结果：yuv图后标注 sensor 分辨率，如 yuv图（1920x1536） */
function buildYuvExpected(sensor?: SensorConfig): string {
  const resolution = sensorResolution(sensor)
  const line2 = `2、yuv图${resolution ? `（${resolution}）` : ''}可正常查看，无异常`
  return buildExpectedResult(`${YUV_EXPECTED_LINE1}\n${line2}`, sensor)
}

/** 组装 ro 预期结果 */
function buildRoExpected(sensor?: SensorConfig): string {
  return buildExpectedResult(`${READOUT_EXPECTED_HEAD}\n${RO_EXPECTED_LINE2}`, sensor)
}

/** 组装 al 预期结果：标注 sensor 配置中的 Vertical（高）/ horizontal（宽） */
function buildAlExpected(sensor?: SensorConfig): string {
  const size = sensorResolutionSize(sensor)
  const line2 = size
    ? `2、al可正常读取有效像素信息（Vertical:${size.height}、horizontal:${size.width}），无异常`
    : AL_EXPECTED_LINE2_FALLBACK
  return buildExpectedResult(`${READOUT_EXPECTED_HEAD}\n${line2}`, sensor)
}

/** 组装 th 预期结果 */
function buildThExpected(sensor?: SensorConfig): string {
  return buildExpectedResult(`${READOUT_EXPECTED_HEAD}\n${TH_EXPECTED_LINE2}`, sensor)
}

/** 判断相机的 sensor 型号是否在「支持 th 测试」的勾选列表中（忽略大小写与首尾空格） */
export function isThTestSensor(
  sensorName: string,
  options: FunctionalTestOptions,
): boolean {
  const target = (sensorName || '').trim().toLowerCase()
  if (!target) return false
  return (options.th_sensors ?? []).some(
    (name) => (name || '').trim().toLowerCase() === target,
  )
}

/**
 * 组装前置条件：保持简短，只说明模组连接与板端上电状态。
 */
export function buildPrerequisites(row: PlatformTopologyRow): string {
  const moduleText = row.module ? `模组 ${row.module} 已正确连接` : '模组已正确连接'
  return `1、${moduleText}\n2、板端已上电，驱动已加载`
}

/** 返回平台配置中已启用的相机拓扑行；未勾选「启用」的相机不参与用例生成 */
export function enabledTopology(
  platform?: PlatformConfig | null,
): PlatformTopologyRow[] {
  return (platform?.topology ?? []).filter((row) => row.enabled !== false)
}

/**
 * 平台配置对应的 -m 掩码组数。
 *
 * 掩码组数与平台配置中的 ``enableMasks`` 一一对应：只有一组时（如
 * ``"enableMasks": ["0x1111"]``），命令只需一个掩码值（如 ``"0x0001"``），
 * 不能补成 ``"0x0001 0 0 0"``。
 */
export function platformMaskGroupCount(platform?: PlatformConfig | null): number {
  const maskCount = (platform?.enable_masks ?? []).filter(Boolean).length
  const groupCount = platform?.group_count ?? 0
  const count = maskCount || groupCount || 4
  return Math.max(1, Math.min(4, count))
}

/**
 * 把多台相机合并成同一个 -m 掩码。
 *
 * 同一个 Group 下的不同 linkIndex 会按位合并，例如 Group A 的 link0 + link1
 * → "0x0011"（单组平台）或 "0x0011 0 0 0"（四组平台）；不同 Group 则分别占用
 * 各自的掩码位。掩码组数由 ``groupCount`` 指定，与平台配置的 enableMasks 数量一致。
 */
export function buildMaskForRows(
  rows: PlatformTopologyRow[],
  groupCount = 4,
): string {
  const count = Math.max(1, Math.min(4, Math.floor(groupCount) || 1))
  const masks = new Array<number>(count).fill(0)
  rows.forEach((row) => {
    if (
      row.group_index >= 0 &&
      row.group_index < masks.length &&
      row.link_index >= 0 &&
      row.link_index <= 3
    ) {
      masks[row.group_index] |= 1 << (row.link_index * 4)
    }
  })
  return masks
    .map((value) => (value === 0 ? '0' : `0x${value.toString(16).padStart(4, '0')}`))
    .join(' ')
}

/**
 * 按 Group / linkIndex 构造 -m 掩码。
 *
 * 单组平台 Group A + link 0 → "0x0001"；四组平台 Group C + link 2 →
 * "0 0 0x0100 0"。
 */
export function buildMask(row: PlatformTopologyRow, groupCount = 4): string {
  return buildMaskForRows([row], groupCount)
}

/** 拓扑行 key：用于在压力测试配置中稳定引用平台拓扑中的某台相机 */
export function topologyRowKey(row: PlatformTopologyRow, index: number): string {
  return `${row.group_index}-${row.link_index}-${index}`
}

/** 公共尾部参数：跳帧数、写帧数与关闭认证 */
function tailArgs(options: RawLightingOptions): string {
  const skipFrames = Math.max(0, Math.floor(options.skip_frames))
  const writeFrames = Math.max(0, Math.floor(options.write_frames))
  return `--skipFrames ${skipFrames} --writeFrames ${writeFrames} -Z`
}

/** 构造单条 raw图 用例的 nvsipl_camera 命令（-R 输出 RAW，禁用 ISP0/1/2） */
export function buildLightingCommand(
  platformName: string,
  row: PlatformTopologyRow,
  options: RawLightingOptions,
  groupCount = 4,
): string {
  return (
    `./nvsipl_camera -c ${platformName} -m "${buildMask(row, groupCount)}" ` +
    `-R -0 -1 -2 -s -f ${options.image_path} ${tailArgs(options)}`
  )
}

/** 构造 YUV 通道参数：未选中的通道以 -0/-1/-2 关闭，例如只启用通道 0 → "-1 -2" */
export function buildYuvChannelArgs(channels: number[] | undefined): string {
  const enabled = channels ?? [0]
  return [0, 1, 2]
    .filter((channel) => !enabled.includes(channel))
    .map((channel) => `-${channel}`)
    .join(' ')
}

/** 构造单条 YUV 出图用例的 nvsipl_camera 命令（按所选通道启停 ISP，并指定 NITO） */
export function buildYuvCommand(
  platformName: string,
  row: PlatformTopologyRow,
  options: FunctionalTestOptions,
  groupCount = 4,
): string {
  const channelArgs = buildYuvChannelArgs(options.yuv_channels)
  return (
    `./nvsipl_camera -c ${platformName} -m "${buildMask(row, groupCount)}" ` +
    `${channelArgs ? `${channelArgs} ` : ''}-s --nito ${options.nito_path} ` +
    `-f ${options.image_path} ${tailArgs(options)}`
  )
}

/** 构造单条 ro / al 用例的 nvsipl_camera 命令（-R 输出 RAW，启用 ISP0 并指定 NITO） */
export function buildReadoutCommand(
  platformName: string,
  row: PlatformTopologyRow,
  options: FunctionalTestOptions,
  groupCount = 4,
): string {
  return (
    `./nvsipl_camera -c ${platformName} -m "${buildMask(row, groupCount)}" ` +
    `-R -1 -2 -s -Z --nito ${options.nito_path}`
  )
}

/** 构造 th 用例命令：起流方式与 ro / al 相同（-R 输出 RAW，启用 ISP0 并指定 NITO） */
export function buildThCommand(
  platformName: string,
  row: PlatformTopologyRow,
  options: FunctionalTestOptions,
  groupCount = 4,
): string {
  return buildReadoutCommand(platformName, row, options, groupCount)
}

/**
 * 构造内参读取用例的 nvsipl_camera 命令。
 *
 * -e 使能模组内参（EEPROM）读取，读取结果与 CRC 校验结果打印到日志；
 * -r 4 表示运行 4 秒后自动退出，避免进程阻塞等待手动 q。
 * 无需落盘、无需 NITO，因此不带 -f / --nito / --skipFrames / --writeFrames。
 */
export function buildIntrinsicCommand(
  platformName: string,
  row: PlatformTopologyRow,
  groupCount = 4,
): string {
  return `./nvsipl_camera -c ${platformName} -m "${buildMask(row, groupCount)}" -R -0 -1 -2 -e -r 4`
}

interface GenerateOptions {
  platform: PlatformConfig
  selection: FunctionalTestSelection
  options: FunctionalTestOptions
  sensors?: SensorConfig[]
}

/** 为平台配置中的每个相机，按所选测试类型各生成一条用例 */
export function generateFunctionalCases({
  platform,
  selection,
  options,
  sensors,
}: GenerateOptions): GeneratedCase[] {
  const cases: GeneratedCase[] = []
  const groupCount = platformMaskGroupCount(platform)

  platform.topology.forEach((row, index) => {
    // 未启用的相机不生成任何功能测试用例（保留原始下标，避免影响用例 key）
    if (row.enabled === false) return
    const sensorConfig = findSensorConfig(sensors, row.sensor)
    const cameraKey = `${row.group_index}-${row.link_index}-${index}`

    if (selection.lighting) {
      const sensorId = row.sensor_id ?? row.link_index
      cases.push({
        key: `lighting-${cameraKey}`,
        group: row.group,
        link_index: row.link_index,
        module: row.module,
        sensor_id: row.sensor_id,
        test_type: TEST_TYPE_LIGHTING,
        description: `验证 group${row.group} linkindex${row.link_index}: ${row.module} 的 raw 图生成情况`,
        prerequisites: buildPrerequisites(row),
        steps: [
          appendCommandNotes(
            `1、输入命令：${buildLightingCommand(platform.name, row, options, groupCount)}`,
            RAW_COMMAND_NOTES,
          ),
          `2、输入gc ${sensorId}`,
        ].join('\n'),
        expected: buildExpectedResult(RAW_EXPECTED, sensorConfig),
        priority: 'P1',
      })
    }

    if (selection.yuv) {
      const sensorId = row.sensor_id ?? row.link_index
      const channels = options.yuv_channels ?? [0]
      const channelText = channels.length > 0
        ? channels.map((channel) => `ISP${channel}`).join('、')
        : '未选择通道'
      cases.push({
        key: `yuv-${cameraKey}`,
        group: row.group,
        link_index: row.link_index,
        module: row.module,
        sensor_id: row.sensor_id,
        test_type: TEST_TYPE_YUV,
        description: `验证 group${row.group} linkindex${row.link_index}: ${row.module} 的 YUV（${channelText}）出图情况`,
        prerequisites: buildPrerequisites(row),
        steps: [
          appendCommandNotes(
            `1、输入命令：${buildYuvCommand(platform.name, row, options, groupCount)}`,
            YUV_COMMAND_NOTES,
          ),
          `2、输入gc ${sensorId}`,
        ].join('\n'),
        expected: buildYuvExpected(sensorConfig),
        priority: 'P1',
      })
    }

    if (selection.ro) {
      const sensorId = row.sensor_id ?? row.link_index
      cases.push({
        key: `ro-${cameraKey}`,
        group: row.group,
        link_index: row.link_index,
        module: row.module,
        sensor_id: row.sensor_id,
        test_type: TEST_TYPE_RO,
        description: `验证 group${row.group} linkindex${row.link_index}: ${row.module} 的 ro 读取情况`,
        prerequisites: buildPrerequisites(row),
        steps: [
          appendCommandNotes(
            `1、输入命令：${buildReadoutCommand(platform.name, row, options, groupCount)}`,
            READOUT_COMMAND_NOTES,
          ),
          `2、输入gc ${sensorId}`,
          '3、输入 ro',
        ].join('\n'),
        expected: buildRoExpected(sensorConfig),
        priority: 'P1',
      })
    }

    if (selection.al) {
      const sensorId = row.sensor_id ?? row.link_index
      cases.push({
        key: `al-${cameraKey}`,
        group: row.group,
        link_index: row.link_index,
        module: row.module,
        sensor_id: row.sensor_id,
        test_type: TEST_TYPE_AL,
        description: `验证 group${row.group} linkindex${row.link_index}: ${row.module} 的 al 读取情况`,
        prerequisites: buildPrerequisites(row),
        steps: [
          appendCommandNotes(
            `1、输入命令：${buildReadoutCommand(platform.name, row, options, groupCount)}`,
            READOUT_COMMAND_NOTES,
          ),
          `2、输入gc ${sensorId}`,
          '3、输入 al',
        ].join('\n'),
        expected: buildAlExpected(sensorConfig),
        priority: 'P1',
      })
    }

    // 内参读取：-e 读取模组内参（寄存器内容）并校验 CRC
    if (selection.intrinsic) {
      cases.push({
        key: `intrinsic-${cameraKey}`,
        group: row.group,
        link_index: row.link_index,
        module: row.module,
        sensor_id: row.sensor_id,
        test_type: TEST_TYPE_INTRINSIC,
        description: `验证 group${row.group} linkindex${row.link_index}: ${row.module} 的内参读取情况`,
        prerequisites: buildPrerequisites(row),
        steps: appendCommandNotes(
          `1、输入命令：${buildIntrinsicCommand(platform.name, row, groupCount)}`,
          INTRINSIC_COMMAND_NOTES,
        ),
        expected: INTRINSIC_EXPECTED,
        priority: 'P1',
      })
    }

    // th 仅对勾选了「支持 th」的 sensor 型号生成，避免为不支持该功能的 sensor 生成用例
    if (selection.th && isThTestSensor(row.sensor, options)) {
      const sensorId = row.sensor_id ?? row.link_index
      cases.push({
        key: `th-${cameraKey}`,
        group: row.group,
        link_index: row.link_index,
        module: row.module,
        sensor_id: row.sensor_id,
        test_type: TEST_TYPE_TH,
        description: `验证 group${row.group} linkindex${row.link_index}: ${row.module} 的 th（温度直方图）读取情况`,
        prerequisites: buildPrerequisites(row),
        steps: [
          appendCommandNotes(
            `1、输入命令：${buildThCommand(platform.name, row, options, groupCount)}`,
            READOUT_COMMAND_NOTES,
          ),
          `2、输入gc ${sensorId}`,
          '3、输入 th',
        ].join('\n'),
        expected: buildThExpected(sensorConfig),
        priority: 'P1',
      })
    }
  })

  // 自定义测试用例：按模板生成，占位符按相机属性自动替换
  cases.push(...buildCustomCases(platform, selection, options, sensors))

  return cases
}

// ============================================================================
// 自定义测试用例：模板占位符替换
// ============================================================================

/**
 * 自定义用例模板支持的占位符。
 *
 * 模板中写 ``{config}``、``{mask}``、``{sensorid}`` 等，生成时会替换为当前
 * 相机的实际取值；占位符不区分大小写，未识别的占位符会原样保留。
 */
export const CASE_TEMPLATE_PLACEHOLDERS: Array<{ key: string; label: string }> = [
  { key: 'config', label: '平台配置名（-c 参数）' },
  { key: 'mask', label: '当前相机的 -m 掩码' },
  { key: 'sensorid', label: 'Sensor ID（gc 使用的编号）' },
  { key: 'group', label: 'Group 字母（A/B/C…）' },
  { key: 'group_index', label: 'Group 下标（从 0 开始）' },
  { key: 'group_mask', label: 'Group 使能掩码' },
  { key: 'link_index', label: 'linkIndex' },
  { key: 'module', label: '模组型号' },
  { key: 'sensor', label: 'Sensor 型号' },
  { key: 'sensor_i2c', label: 'Sensor I2C 地址' },
  { key: 'serializer', label: 'Serializer 型号' },
  { key: 'serializer_i2c', label: 'Serializer I2C 地址' },
  { key: 'csi_port', label: 'CSI Port' },
  { key: 'phy_mode', label: 'PHY 模式' },
  { key: 'deserializer', label: '解串器型号' },
  { key: 'mask_bit', label: '掩码位（如 0x1）' },
  { key: 'resolution', label: 'sensor 分辨率（如 1920x1536）' },
  { key: 'width', label: 'sensor 宽度' },
  { key: 'height', label: 'sensor 高度' },
  { key: 'fps', label: 'sensor 帧率' },
  { key: 'image_path', label: '-f 输出目录' },
  { key: 'nito_path', label: '--nito 目录' },
  { key: 'skip_frames', label: '--skipFrames' },
  { key: 'write_frames', label: '--writeFrames' },
  { key: 'yuv_channels', label: '启用的 YUV 通道（如 0,1）' },
  { key: 'yuv_channel_args', label: '关闭 YUV 通道的参数（如 -1 -2）' },
]

/** 占位符替换上下文，key 为小写占位符名 */
export type CaseTemplateContext = Record<string, string>

/** 占位符匹配规则：{name}，名称由字母、数字、下划线组成 */
const TEMPLATE_PLACEHOLDER_PATTERN = /\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g

/** 按相机与功能测试参数构建占位符上下文 */
export function buildCaseTemplateContext(
  platform: PlatformConfig,
  row: PlatformTopologyRow,
  options: FunctionalTestOptions,
  sensors?: SensorConfig[],
  groupCount = platformMaskGroupCount(platform),
): CaseTemplateContext {
  const sensorConfig = findSensorConfig(sensors, row.sensor)
  const size = sensorResolutionSize(sensorConfig)
  const fps = sensorFps(sensorConfig)
  const sensorId = row.sensor_id ?? row.link_index
  const channels = options.yuv_channels ?? [0]

  return {
    config: platform.name,
    platform: platform.name,
    mask: buildMask(row, groupCount),
    group: row.group,
    group_index: String(row.group_index),
    group_mask: row.group_mask || '',
    link: String(row.link_index),
    link_index: String(row.link_index),
    module: row.module || '',
    sensor: row.sensor || '',
    sensorid: String(sensorId),
    sensor_id: String(sensorId),
    sensor_i2c: row.sensor_i2c || '',
    serializer: row.serializer || '',
    serializer_i2c: row.serializer_i2c || '',
    serializer_virtual_i2c: row.serializer_virtual_i2c || '',
    csi_port: row.csi_port || '',
    phy: row.phy_mode || '',
    phy_mode: row.phy_mode || '',
    deserializer: row.deserializer || '',
    mask_bit: row.mask_bit || '',
    resolution: size ? `${size.width}x${size.height}` : '',
    width: size ? String(size.width) : '',
    height: size ? String(size.height) : '',
    fps: fps === null ? '' : String(fps),
    image_path: options.image_path || '',
    nito_path: options.nito_path || '',
    nito: options.nito_path || '',
    skip_frames: String(Math.max(0, Math.floor(options.skip_frames ?? 0))),
    write_frames: String(Math.max(0, Math.floor(options.write_frames ?? 0))),
    yuv_channels: channels.join(','),
    yuv_channel_args: buildYuvChannelArgs(channels),
  }
}

/** 替换模板文本中的占位符；未知占位符保持原样，便于用户发现拼写错误 */
export function renderCaseTemplate(
  text: string,
  context: CaseTemplateContext,
): string {
  return (text || '').replace(TEMPLATE_PLACEHOLDER_PATTERN, (match, name: string) => {
    const value = context[name.toLowerCase()]
    return value === undefined ? match : value
  })
}

/** 模板是否有可生成的内容（至少填写描述 / 测试步骤 / 预期结果之一） */
export function isCustomCaseTemplateUsable(template: CustomCaseTemplate): boolean {
  return [template.description, template.steps, template.expected]
    .some((text) => (text || '').trim().length > 0)
}

/** 根据自定义模板，按相机生成用例（选择项 custom 未勾选时返回空数组） */
function buildCustomCases(
  platform: PlatformConfig,
  selection: FunctionalTestSelection,
  options: FunctionalTestOptions,
  sensors?: SensorConfig[],
): GeneratedCase[] {
  if (!selection.custom) return []

  const templates = (options.custom_cases ?? []).filter(isCustomCaseTemplateUsable)
  if (templates.length === 0) return []

  const groupCount = platformMaskGroupCount(platform)
  const cases: GeneratedCase[] = []

  const pushCase = (
    template: CustomCaseTemplate,
    templateIndex: number,
    row: PlatformTopologyRow,
    rowIndex: number,
    global: boolean,
  ) => {
    const context = buildCaseTemplateContext(platform, row, options, sensors, groupCount)
    const testType = (template.test_type || '').trim() || TEST_TYPE_CUSTOM
    cases.push({
      key: global
        ? `custom-${templateIndex}-global`
        : `custom-${templateIndex}-${row.group_index}-${row.link_index}-${rowIndex}`,
      group: row.group,
      link_index: row.link_index,
      module: row.module,
      sensor_id: row.sensor_id,
      test_type: testType,
      description: renderCaseTemplate(template.description, context),
      prerequisites: renderCaseTemplate(template.prerequisites, context),
      steps: renderCaseTemplate(template.steps, context),
      expected: renderCaseTemplate(template.expected, context),
      priority: (template.priority || '').trim() || 'P1',
    })
  }

  const enabledRows: Array<{ row: PlatformTopologyRow; index: number }> = []
  platform.topology.forEach((row, index) => {
    if (row.enabled !== false) enabledRows.push({ row, index })
  })

  templates.forEach((template, templateIndex) => {
    if (template.per_camera === false) {
      const first = enabledRows[0]
      if (first) pushCase(template, templateIndex, first.row, first.index, true)
      return
    }
    enabledRows.forEach(({ row, index }) => {
      pushCase(template, templateIndex, row, index, false)
    })
  })

  return cases
}

// ============================================================================
// 压力测试：反复起流
// ============================================================================

/**
 * 构造压力测试起流命令。
 *
 * 与功能测试不同，压力测试只关注反复起流本身，不落盘文件，因此不带
 * -f / --skipFrames / --writeFrames。掩码组数与平台配置 enableMasks 数量一致，
 * 例如四组平台：./nvsipl_camera -c <平台> -m "0 0x0001 0 0" -R -0 -1 -2 -s -Z
 */
export function buildStressCommand(
  platformName: string,
  rows: PlatformTopologyRow[],
  groupCount = 4,
): string {
  return `./nvsipl_camera -c ${platformName} -m "${buildMaskForRows(rows, groupCount)}" -R -0 -1 -2 -s -Z`
}

/**
 * 组装压力测试前置条件：与功能测试保持一致，保持简短。
 * 只有一台相机时保留模组名称；多台相机时统一描述为组合内模组已连接。
 */
export function buildStressPrerequisites(rows: PlatformTopologyRow[]): string {
  const modules = Array.from(
    new Set(rows.map((row) => row.module).filter(Boolean)),
  )
  const moduleText =
    modules.length === 1 ? `模组 ${modules[0]} 已正确连接` : '组合内模组均已正确连接'
  return `1、${moduleText}\n2、板端已上电，驱动已加载`
}

/** 取组合内各相机在 sensor 配置中声明的帧率（去重） */
function combinationSensorFps(
  rows: PlatformTopologyRow[],
  sensors?: SensorConfig[],
): number[] {
  const fpsSet = new Set<number>()
  rows.forEach((row) => {
    const fps = sensorFps(findSensorConfig(sensors, row.sensor))
    if (fps !== null) fpsSet.add(fps)
  })
  return Array.from(fpsSet)
}

/** 组装压力测试预期结果：每次均可正常起流，反复 N 次帧率稳定 */
function buildStressExpected(
  rows: PlatformTopologyRow[],
  repeatCount: number,
  sensors?: SensorConfig[],
): string {
  const fpsList = combinationSensorFps(rows, sensors)
  let line2 = `2、反复起流${repeatCount}次均能正常出帧，帧率稳定`
  if (fpsList.length === 1) {
    line2 = `2、反复起流${repeatCount}次均能正常出帧，帧率稳定在 ${fpsList[0]}fps 左右`
  } else if (fpsList.length > 1) {
    line2 =
      `2、反复起流${repeatCount}次均能正常出帧，各相机帧率符合配置` +
      `（${fpsList.join('/')}fps）`
  }
  return `1、每次执行起流命令均无报错，可正常起流\n${line2}\n3、全程无异常退出`
}

interface GenerateStressOptions {
  platform: PlatformConfig
  selection: FunctionalTestSelection
  options: StressTestOptions
  sensors?: SensorConfig[]
}

/** 按配置的每条「相机组合 + 起流次数」生成一条压力测试用例 */
export function generateStressCases({
  platform,
  selection,
  options,
  sensors,
}: GenerateStressOptions): GeneratedCase[] {
  if (!selection.stress) return []

  const rowByKey = new Map<string, PlatformTopologyRow>()
  platform.topology.forEach((row, index) => {
    // 未启用的相机不参与测试组合（保留原始下标，保证草稿中的组合 key 仍可解析）
    if (row.enabled === false) return
    rowByKey.set(topologyRowKey(row, index), row)
  })

  const cases: GeneratedCase[] = []
  const groupCount = platformMaskGroupCount(platform)
  ;(options.combinations ?? []).forEach((combination) => {
    const cameraKeys = Array.from(new Set(combination.camera_keys ?? []))
    const rows = cameraKeys
      .map((key) => rowByKey.get(key))
      .filter((row): row is PlatformTopologyRow => Boolean(row))
    if (rows.length === 0) return

    const repeatCount = Math.max(
      1,
      Math.floor(combination.repeat_count || DEFAULT_STRESS_REPEAT_COUNT),
    )
    const mask = buildMaskForRows(rows, groupCount)
    const sensorId = rows[0].sensor_id ?? rows[0].link_index

    cases.push({
      key: `stress-${combination.id}`,
      group: rows.map((row) => row.group).join('+'),
      link_index: rows[0].link_index,
      module: rows.map((row) => row.module || '-').join('+'),
      sensor_id: rows.length === 1 ? rows[0].sensor_id : null,
      test_type: TEST_TYPE_STRESS,
      description: `验证相机组合掩码 "${mask}" 反复起流 ${repeatCount} 次的稳定性`,
      prerequisites: buildStressPrerequisites(rows),
      steps: [
        appendCommandNotes(
          `1、输入命令：${buildStressCommand(platform.name, rows, groupCount)}`,
          BASE_COMMAND_NOTES,
        ),
        `2、输入gc ${sensorId}`,
        `3、反复起流${repeatCount}次`,
      ].join('\n'),
      expected: buildStressExpected(rows, repeatCount, sensors),
      priority: 'P1',
    })
  })

  return cases
}

// ============================================================================
// 稳定性测试：长时间起流
// ============================================================================

/**
 * 构造稳定性测试起流命令。
 * 与样例保持一致，只指定平台配置与相机组合掩码，不带其他功能参数。
 */
export function buildStabilityCommand(
  platformName: string,
  rows: PlatformTopologyRow[],
  groupCount = 4,
): string {
  return `./nvsipl_camera -c ${platformName} -m "${buildMaskForRows(rows, groupCount)}"`
}

/** 稳定性测试前置条件：与压力测试保持一致，保持简短 */
export function buildStabilityPrerequisites(rows: PlatformTopologyRow[]): string {
  return buildStressPrerequisites(rows)
}

/** 组装稳定性测试预期结果：持续起流期间无报错、无异常退出 */
function buildStabilityExpected(
  rows: PlatformTopologyRow[],
  durationMinutes: number,
  sensors?: SensorConfig[],
): string {
  const fpsList = combinationSensorFps(rows, sensors)
  const lines = [
    '1、起流命令执行无报错，可正常起流',
    `2、持续起流${durationMinutes}分钟期间无报错，画面正常、无异常退出`,
  ]
  if (fpsList.length === 1) {
    lines.push(`3、帧率稳定在 ${fpsList[0]}fps 左右`)
  } else if (fpsList.length > 1) {
    lines.push(`3、各相机帧率符合配置（${fpsList.join('/')}fps）`)
  }
  return lines.join('\n')
}

interface GenerateStabilityOptions {
  platform: PlatformConfig
  selection: FunctionalTestSelection
  options: StabilityTestOptions
  sensors?: SensorConfig[]
}

/** 按配置的每条「相机组合 + 起流时长」生成一条稳定性测试用例 */
export function generateStabilityCases({
  platform,
  selection,
  options,
  sensors,
}: GenerateStabilityOptions): GeneratedCase[] {
  if (!selection.stability) return []

  const rowByKey = new Map<string, PlatformTopologyRow>()
  platform.topology.forEach((row, index) => {
    // 未启用的相机不参与测试组合（保留原始下标，保证草稿中的组合 key 仍可解析）
    if (row.enabled === false) return
    rowByKey.set(topologyRowKey(row, index), row)
  })

  const cases: GeneratedCase[] = []
  const groupCount = platformMaskGroupCount(platform)
  ;(options.combinations ?? []).forEach((combination) => {
    const cameraKeys = Array.from(new Set(combination.camera_keys ?? []))
    const rows = cameraKeys
      .map((key) => rowByKey.get(key))
      .filter((row): row is PlatformTopologyRow => Boolean(row))
    if (rows.length === 0) return

    const durationMinutes = Math.max(
      1,
      Math.round(combination.duration_minutes || DEFAULT_STABILITY_DURATION_MINUTES),
    )
    const mask = buildMaskForRows(rows, groupCount)
    const sensorId = rows[0].sensor_id ?? rows[0].link_index

    cases.push({
      key: `stability-${combination.id}`,
      group: rows.map((row) => row.group).join('+'),
      link_index: rows[0].link_index,
      module: rows.map((row) => row.module || '-').join('+'),
      sensor_id: rows.length === 1 ? rows[0].sensor_id : null,
      test_type: TEST_TYPE_STABILITY,
      description: `验证相机组合掩码 "${mask}" 持续起流 ${durationMinutes} 分钟的稳定性`,
      prerequisites: buildStabilityPrerequisites(rows),
      steps: [
        appendCommandNotes(
          `1、输入命令：${buildStabilityCommand(platform.name, rows, groupCount)}`,
          BASE_COMMAND_NOTES,
        ),
        `2、输入gc ${sensorId}`,
        `3、验证${durationMinutes}分钟起流是否报错`,
      ].join('\n'),
      expected: buildStabilityExpected(rows, durationMinutes, sensors),
      priority: 'P1',
    })
  })

  return cases
}
