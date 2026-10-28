/**
 * Sensor 配置相关的展示与匹配工具。
 *
 * sensor 配置文件（如 imx623.json）中的 name 与平台配置里相机的 sensor 名称
 * 对应，两者匹配后即可在后续步骤中展示、拼装用例文案。
 */
import type {
  SensorConfig,
  SensorConfigFile,
  SensorConfigParseResult,
  SensorVirtualChannel,
} from '../../types/casegen'

/** 布尔值转为中文开关状态 */
const onOff = (value: boolean) => (value ? '开' : '关')

/** 格式化单个 virtual channel，例如：VC0 1920x1536@30fps raw12rj rggb */
export function formatVirtualChannel(channel: SensorVirtualChannel): string {
  const resolution =
    channel.width !== null && channel.height !== null
      ? `${channel.width}x${channel.height}`
      : ''
  const fps = channel.fps !== null ? `${channel.fps}fps` : ''
  const frameRate = [resolution, fps].filter(Boolean).join('@')
  const embedded =
    channel.embedded_top_lines !== null || channel.embedded_bottom_lines !== null
      ? `(embedded ${channel.embedded_top_lines ?? 0}/${channel.embedded_bottom_lines ?? 0})`
      : ''

  return [
    `VC${channel.index}`,
    frameRate,
    channel.input_format,
    channel.cfa,
    embedded,
    channel.embedded_data_type_enabled ? 'embeddedDataType' : '',
  ]
    .filter(Boolean)
    .join(' ')
}

/** 格式化一个 sensor 配置的摘要，用于用例前置条件与列表展示 */
export function formatSensorSummary(sensor: SensorConfig): string {
  const channels = sensor.virtual_channels.map(formatVirtualChannel).join('; ')
  return [
    sensor.name,
    sensor.i2c_address ? `I2C ${sensor.i2c_address}` : '',
    channels,
    `TriggerMode ${onOff(sensor.trigger_mode_enabled)}`,
    `TPG ${onOff(sensor.tpg_enabled)}`,
    sensor.use_cdi_v2_api ? 'CDI v2' : '',
  ]
    .filter(Boolean)
    .join(' · ')
}

/** 按 sensor 名称查找配置（忽略大小写与首尾空格） */
export function findSensorConfig(
  sensors: SensorConfig[] | null | undefined,
  name: string,
): SensorConfig | undefined {
  const target = (name || '').trim().toLowerCase()
  if (!target) return undefined
  return sensors?.find((sensor) => sensor.name.trim().toLowerCase() === target)
}

/**
 * 把扁平的 sensor 列表按来源文件重新分组，用于从草稿/自动保存中恢复。
 *
 * paths 为还原后的文件路径顺序，缺省时按 sensor 的 source_path 聚组。
 */
export function groupSensorsByFile(
  sensors: SensorConfig[],
  paths: string[] = [],
): SensorConfigParseResult {
  const order = paths.length > 0 ? [...paths] : []
  const map = new Map<string, SensorConfigFile>()

  for (const sensor of sensors) {
    const key = sensor.source_path || sensor.source_file || 'unknown'
    let file = map.get(key)
    if (!file) {
      file = {
        path: sensor.source_path || '',
        file_name: sensor.source_file || '',
        sensors: [],
      }
      map.set(key, file)
    }
    if (!file.sensors.some((s) => s.source_path === sensor.source_path && s.sensor_index === sensor.sensor_index)) {
      file.sensors.push(sensor)
    }
  }

  const files = Array.from(map.entries())
    .sort(([keyA], [keyB]) => {
      const indexA = order.indexOf(keyA)
      const indexB = order.indexOf(keyB)
      if (indexA === -1 && indexB === -1) return 0
      if (indexA === -1) return 1
      if (indexB === -1) return -1
      return indexA - indexB
    })
    .map(([, file]) => file)

  return { files, sensors: files.flatMap((file) => file.sensors) }
}
