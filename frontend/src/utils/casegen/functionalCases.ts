/**
 * 功能测试用例生成。
 *
 * 当前实现三类功能测试：
 * - raw图：只输出 RAW（-R），验证相机能否正常出图
 * - YUV 图：输出 ISP0 的 YUV（启用 ISP0，禁用 ISP1/ISP2），验证出图
 * - ro/al 测试：起流后输入 gc 触发出帧，再输入 ro / al 读取 readout 与有效像素信息
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
} from '../../types/casegen'
import { TEST_TYPE_LIGHTING, TEST_TYPE_RO_AL, TEST_TYPE_YUV } from '../../types/casegen'
import { findSensorConfig } from './sensors'

const RAW_EXPECTED =
  '1、执行命令无报错，可生成.raw文件\n2、raw可正常查看，无异常'

const YUV_EXPECTED_LINE1 = '1、执行命令无报错，可生成.yuv文件'

const RO_AL_EXPECTED_HEAD =
  '1、执行命令无报错，输入gc后帧率正常\n' +
  '2、ro可正常读取readout信息，无异常'

const RO_AL_EXPECTED_AL_FALLBACK = '3、al可正常读取有效像素信息（Vertical、horizontal），无异常'

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

/** 组装 ro/al 预期结果：al 后标注 sensor 配置中的 Vertical（高）/ horizontal（宽） */
function buildRoAlExpected(sensor?: SensorConfig): string {
  const size = sensorResolutionSize(sensor)
  const line3 = size
    ? `3、al可正常读取有效像素信息（Vertical:${size.height}、horizontal:${size.width}），无异常`
    : RO_AL_EXPECTED_AL_FALLBACK
  return `${RO_AL_EXPECTED_HEAD}\n${line3}`
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

/** linkIndex → 该 Group 掩码中的半字节，如 link 2 → 0x0100 */
function maskNibble(linkIndex: number): string {
  if (linkIndex < 0 || linkIndex > 3) return '0'
  return `0x${(1 << (linkIndex * 4)).toString(16).padStart(4, '0')}`
}

/** 按 Group / linkIndex 构造 -m 掩码，例如 Group C + link 2 → "0 0 0x0100 0" */
export function buildMask(row: PlatformTopologyRow): string {
  const masks = ['0', '0', '0', '0']
  if (row.group_index >= 0 && row.group_index < masks.length) {
    masks[row.group_index] = maskNibble(row.link_index)
  }
  return masks.join(' ')
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

/** 构造单条 YUV 出图用例的 nvsipl_camera 命令（启用 ISP0，禁用 ISP1/2，并指定 NITO） */
export function buildYuvCommand(
  platformName: string,
  row: PlatformTopologyRow,
  options: FunctionalTestOptions,
): string {
  return (
    `./nvsipl_camera -c ${platformName} -m "${buildMask(row)}" ` +
    `-1 -2 -s --nito ${options.nito_path} -f ${options.image_path} ${tailArgs(options)}`
  )
}

/** 构造单条 ro/al 用例的 nvsipl_camera 命令（-R 输出 RAW，启用 ISP0 并指定 NITO） */
export function buildRoAlCommand(
  platformName: string,
  row: PlatformTopologyRow,
  options: FunctionalTestOptions,
): string {
  return (
    `./nvsipl_camera -c ${platformName} -m "${buildMask(row)}" ` +
    `-R -1 -2 -s -Z --nito ${options.nito_path}`
  )
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
      cases.push({
        key: `yuv-${cameraKey}`,
        group: row.group,
        link_index: row.link_index,
        module: row.module,
        sensor_id: row.sensor_id,
        test_type: TEST_TYPE_YUV,
        description: `验证 group${row.group} linkindex${row.link_index}: ${row.module} 的 YUV 出图情况`,
        prerequisites: buildPrerequisites(row),
        steps: `1、输入命令：${buildYuvCommand(platform.name, row, options)}`,
        expected: buildYuvExpected(sensorConfig),
        priority: 'P1',
      })
    }

    if (selection.roAl) {
      const sensorId = row.sensor_id ?? row.link_index
      cases.push({
        key: `ro-al-${cameraKey}`,
        group: row.group,
        link_index: row.link_index,
        module: row.module,
        sensor_id: row.sensor_id,
        test_type: TEST_TYPE_RO_AL,
        description: `验证 group${row.group} linkindex${row.link_index}: ${row.module} 的 ro/al 读取情况`,
        prerequisites: buildPrerequisites(row),
        steps: [
          `1、输入命令：${buildRoAlCommand(platform.name, row, options)}`,
          `2、输入gc ${sensorId}`,
          '3、输入 ro',
          '4、输入 al',
        ].join('\n'),
        expected: buildRoAlExpected(sensorConfig),
        priority: 'P1',
      })
    }
  })

  return cases
}
