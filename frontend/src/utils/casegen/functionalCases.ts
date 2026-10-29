/**
 * 功能测试与压力测试用例生成。
 *
 * 功能测试实现五类：
 * - raw图：只输出 RAW（-R），验证相机能否正常出图
 * - YUV 图：按所选通道输出 YUV（未选中的通道用 -0/-1/-2 关闭），验证出图
 * - ro 测试：起流后输入 gc 触发出帧，再输入 ro 读取 readout 信息
 * - al 测试：起流后输入 gc 触发出帧，再输入 al 读取有效像素信息
 * - th 测试：起流后输入 gc 触发出帧，再输入 th 读取温度直方图；部分 sensor
 *   不支持该功能，仅对勾选的 sensor 型号生成
 *
 * 压力测试单独成组：每条用例可配置同时起流的相机组合与「反复起流 N 次」。
 * 后续新增类型时按同样结构扩展。
 */
import type {
  FunctionalTestOptions,
  FunctionalTestSelection,
  GeneratedCase,
  PlatformConfig,
  PlatformTopologyRow,
  RawLightingOptions,
  SensorConfig,
  StressTestOptions,
} from '../../types/casegen'
import {
  DEFAULT_STRESS_REPEAT_COUNT,
  TEST_TYPE_AL,
  TEST_TYPE_LIGHTING,
  TEST_TYPE_RO,
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
 * 组装前置条件：简要描述该相机在硬件上如何连接。
 *
 * 例：
 * 1、模组 PANGU_IMX728V3_30F 接 Group A（linkIndex 0，解串器 MAX96724，csi-cd，cphy）
 * 2、I2C：串行器 0x40，Sensor 0x44（ID 0）
 */
export function buildPrerequisites(row: PlatformTopologyRow): string {
  const lines: string[] = [
    `1、模组 ${row.module || '-'} 接 Group ${row.group}（linkIndex ${row.link_index}，` +
      `解串器 ${row.deserializer || '-'}，${row.csi_port || '-'}，${row.phy_mode || '-'}）`,
  ]

  const i2cParts = [
    row.serializer_i2c ? `串行器 ${row.serializer_i2c}` : '',
    row.sensor_i2c
      ? `Sensor ${row.sensor_i2c}` +
        `${row.sensor_id !== null && row.sensor_id !== undefined ? `（ID ${row.sensor_id}）` : ''}`
      : '',
  ].filter(Boolean)
  if (i2cParts.length > 0) {
    lines.push(`2、I2C：${i2cParts.join('，')}`)
  }

  return lines.join('\n')
}

/**
 * 把多台相机合并成同一个 -m 掩码。
 *
 * 同一个 Group 下的不同 linkIndex 会按位合并，例如 Group A 的 link0 + link1
 * → "0x0011 0 0 0"；不同 Group 则分别占用各自的掩码位。
 */
export function buildMaskForRows(rows: PlatformTopologyRow[]): string {
  const masks = [0, 0, 0, 0]
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

/** 按 Group / linkIndex 构造 -m 掩码，例如 Group C + link 2 → "0 0 0x0100 0" */
export function buildMask(row: PlatformTopologyRow): string {
  return buildMaskForRows([row])
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
): string {
  return (
    `./nvsipl_camera -c ${platformName} -m "${buildMask(row)}" ` +
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
): string {
  const channelArgs = buildYuvChannelArgs(options.yuv_channels)
  return (
    `./nvsipl_camera -c ${platformName} -m "${buildMask(row)}" ` +
    `${channelArgs ? `${channelArgs} ` : ''}-s --nito ${options.nito_path} ` +
    `-f ${options.image_path} ${tailArgs(options)}`
  )
}

/** 构造单条 ro / al 用例的 nvsipl_camera 命令（-R 输出 RAW，启用 ISP0 并指定 NITO） */
export function buildReadoutCommand(
  platformName: string,
  row: PlatformTopologyRow,
  options: FunctionalTestOptions,
): string {
  return (
    `./nvsipl_camera -c ${platformName} -m "${buildMask(row)}" ` +
    `-R -1 -2 -s -Z --nito ${options.nito_path}`
  )
}

/** 构造 th 用例命令：起流方式与 ro / al 相同（-R 输出 RAW，启用 ISP0 并指定 NITO） */
export function buildThCommand(
  platformName: string,
  row: PlatformTopologyRow,
  options: FunctionalTestOptions,
): string {
  return buildReadoutCommand(platformName, row, options)
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

  platform.topology.forEach((row, index) => {
    const sensorConfig = findSensorConfig(sensors, row.sensor)
    const cameraKey = `${row.group_index}-${row.link_index}-${index}`

    if (selection.lighting) {
      cases.push({
        key: `lighting-${cameraKey}`,
        group: row.group,
        link_index: row.link_index,
        module: row.module,
        sensor_id: row.sensor_id,
        test_type: TEST_TYPE_LIGHTING,
        description: `验证 group${row.group} linkindex${row.link_index}: ${row.module} 的 raw 图生成情况`,
        prerequisites: buildPrerequisites(row),
        steps: `1、输入命令：${buildLightingCommand(platform.name, row, options)}`,
        expected: buildExpectedResult(RAW_EXPECTED, sensorConfig),
        priority: 'P1',
      })
    }

    if (selection.yuv) {
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
        steps: `1、输入命令：${buildYuvCommand(platform.name, row, options)}`,
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
          `1、输入命令：${buildReadoutCommand(platform.name, row, options)}`,
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
          `1、输入命令：${buildReadoutCommand(platform.name, row, options)}`,
          `2、输入gc ${sensorId}`,
          '3、输入 al',
        ].join('\n'),
        expected: buildAlExpected(sensorConfig),
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
          `1、输入命令：${buildThCommand(platform.name, row, options)}`,
          `2、输入gc ${sensorId}`,
          '3、输入 th',
        ].join('\n'),
        expected: buildThExpected(sensorConfig),
        priority: 'P1',
      })
    }
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
 * -f / --skipFrames / --writeFrames，命令与下面示例保持一致：
 * ./nvsipl_camera -c <平台> -m "0 0x0001 0 0" -R -0 -1 -2 -s -Z
 */
export function buildStressCommand(
  platformName: string,
  rows: PlatformTopologyRow[],
): string {
  return `./nvsipl_camera -c ${platformName} -m "${buildMaskForRows(rows)}" -R -0 -1 -2 -s -Z`
}

/**
 * 组装压力测试前置条件：列出组合内每台相机的硬件连接与 I2C 信息。
 * 多台相机时逐台编号，I2C 信息合并为一行。
 */
export function buildStressPrerequisites(rows: PlatformTopologyRow[]): string {
  const lines = rows.map(
    (row, index) =>
      `${index + 1}、模组 ${row.module || '-'} 接 Group ${row.group}（linkIndex ${row.link_index}，` +
      `解串器 ${row.deserializer || '-'}，${row.csi_port || '-'}，${row.phy_mode || '-'}）`,
  )

  const i2cParts: string[] = []
  rows.forEach((row) => {
    const tag = `Group ${row.group} link ${row.link_index}`
    if (row.serializer_i2c) i2cParts.push(`串行器 ${row.serializer_i2c}（${tag}）`)
    if (row.sensor_i2c) {
      const sensorId =
        row.sensor_id !== null && row.sensor_id !== undefined ? `（ID ${row.sensor_id}）` : ''
      i2cParts.push(`Sensor ${row.sensor_i2c}${sensorId}（${tag}）`)
    }
  })
  if (i2cParts.length > 0) {
    lines.push(`${lines.length + 1}、I2C：${i2cParts.join('；')}`)
  }

  return lines.join('\n')
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
    rowByKey.set(topologyRowKey(row, index), row)
  })

  const cases: GeneratedCase[] = []
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
    const cameraText = rows
      .map((row) => `${row.group} linkindex${row.link_index}: ${row.module || '-'}`)
      .join('；')

    cases.push({
      key: `stress-${combination.id}`,
      group: rows.map((row) => row.group).join('+'),
      link_index: rows[0].link_index,
      module: rows.map((row) => row.module || '-').join('+'),
      sensor_id: rows.length === 1 ? rows[0].sensor_id : null,
      test_type: TEST_TYPE_STRESS,
      description: `验证相机组合（${cameraText}）反复起流 ${repeatCount} 次的稳定性`,
      prerequisites: buildStressPrerequisites(rows),
      steps: [
        `1、输入命令：${buildStressCommand(platform.name, rows)}`,
        `2、反复起流${repeatCount}次`,
      ].join('\n'),
      expected: buildStressExpected(rows, repeatCount, sensors),
      priority: 'P1',
    })
  })

  return cases
}
