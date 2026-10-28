/**
 * 功能测试 — 点亮（生成 .raw）用例生成。
 *
 * 当前仅实现「点亮」一种功能测试，后续新增类型时按同样结构扩展。
 */
import type {
  GeneratedCase,
  PlatformConfig,
  PlatformTopologyRow,
  RawLightingOptions,
} from '../../types/casegen'

const EXPECTED_RESULT =
  '1、执行命令无报错，可生成.raw文件\n2、raw可正常查看，无异常'

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

/** 构造单条点亮用例的 nvsipl_camera 命令 */
export function buildLightingCommand(
  platformName: string,
  row: PlatformTopologyRow,
  options: RawLightingOptions,
): string {
  const skipFrames = Math.max(0, Math.floor(options.skip_frames))
  const writeFrames = Math.max(0, Math.floor(options.write_frames))
  return (
    `./nvsipl_camera -c ${platformName} -m "${buildMask(row)}" ` +
    `-R -0 -1 -2 -s -f ${options.image_path} ` +
    `--skipFrames ${skipFrames} --writeFrames ${writeFrames} -Z`
  )
}

/** 为平台配置中的每个相机生成一条点亮用例 */
export function generateRawLightingCases(
  platform: PlatformConfig,
  options: RawLightingOptions,
): GeneratedCase[] {
  return platform.topology.map((row, index) => {
    const sensorId = row.sensor_id ?? row.link_index
    return {
      key: `${row.group_index}-${row.link_index}-${index}`,
      group: row.group,
      link_index: row.link_index,
      module: row.module,
      sensor_id: row.sensor_id,
      test_type: '点亮',
      description: `验证${row.group}: ${row.link_index}: ${row.module} 的点亮情况`,
      prerequisites: '',
      steps:
        `1、输入命令：${buildLightingCommand(platform.name, row, options)}\n` +
        `2、起流后输入gc ${sensorId}`,
      expected: EXPECTED_RESULT,
      priority: 'P1',
    }
  })
}
