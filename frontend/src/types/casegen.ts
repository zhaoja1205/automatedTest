/**
 * 生成测试用例模块类型定义。
 */

/** 第一步：基本信息 */
export interface CaseGenBasicInfo {
  /** 项目名称 */
  project_name: string
  /** 被测对象 / 模块 */
  target: string
  /** 软件版本 */
  software_version: string
  /** 测试版本 */
  test_version: string
  /** 操作系统 */
  os: string
  /** 硬件平台 / 设备型号 */
  device_model: string
  /** 测试负责人 */
  owner: string
  /** 测试周期 */
  test_cycle: string
  /** 备注 */
  remark: string
}

export const EMPTY_BASIC_INFO: CaseGenBasicInfo = {
  project_name: '',
  target: '',
  software_version: '',
  test_version: '',
  os: '',
  device_model: '',
  owner: '',
  test_cycle: '',
  remark: '',
}

/** 平台配置中的单个 Camera 模组 */
export interface PlatformCamera {
  link_index: number
  module: string
  serializer: string
  serializer_i2c: string
  serializer_virtual_i2c: string
  sensor: string
  sensor_i2c: string
  sensor_id: number | null
  mask_bit: string
}

/** 一个 DeviceBlock（对应一个 Group） */
export interface PlatformGroup {
  group_index: number
  group: string
  enable_mask: string
  csi_port: string
  phy_mode: string
  deserializer: string
  simulator_mode: boolean
  passive_mode: boolean
  homogenous_modules: boolean
  group_init_prog: boolean
  cameras: PlatformCamera[]
}

/** 扁平化后的硬件拓扑行 */
export interface PlatformTopologyRow extends PlatformCamera {
  group: string
  group_index: number
  group_mask: string
  csi_port: string
  phy_mode: string
  deserializer: string
}

/** 单个平台配置 */
export interface PlatformConfig {
  name: string
  description: string
  enable_masks: string[]
  group_count: number
  module_count: number
  groups: PlatformGroup[]
  topology: PlatformTopologyRow[]
}

/** 平台配置文件解析结果 */
export interface PlatformConfigParseResult {
  path: string
  file_name: string
  platform_configs: PlatformConfig[]
}

/** 默认样例配置文件路径（可在页面中修改） */
export const DEFAULT_PLATFORM_CONFIG_PATH =
  '/home/tstj/project/nvidia/Qnx_Standard_7.2.4.0/drive-qnx/samples/nvmedia/nvsipl/query/database/predev_mixgroup/predev_mixgroup_platform.json'

/** Sensor 配置中的单个 virtual channel（对应 imx623.json 中 virtualChannels 的一项） */
export interface SensorVirtualChannel {
  /** 在 virtualChannels 数组中的下标 */
  index: number
  /** 色彩滤镜阵列，例如 rggb */
  cfa: string
  embedded_top_lines: number | null
  embedded_bottom_lines: number | null
  /** 输入格式，例如 raw12rj */
  input_format: string
  width: number | null
  height: number | null
  fps: number | null
  embedded_data_type_enabled: boolean
}

/** 单个 imageSensor 配置（对应 imx623.json 中 imageSensors 的一项） */
export interface SensorConfig {
  name: string
  description: string
  i2c_address: string
  virtual_channels: SensorVirtualChannel[]
  trigger_mode_enabled: boolean
  tpg_enabled: boolean
  use_cdi_v2_api: boolean
  /** 在来源文件 imageSensors 数组中的下标 */
  sensor_index: number
  /** 来源文件绝对路径 */
  source_path: string
  /** 来源文件名 */
  source_file: string
}

/** 一个 sensor 配置文件（可包含多个 imageSensor） */
export interface SensorConfigFile {
  path: string
  file_name: string
  sensors: SensorConfig[]
}

/** Sensor 配置文件读取结果 */
export interface SensorConfigParseResult {
  files: SensorConfigFile[]
  /** 所有文件中的 sensor 配置扁平化后的列表 */
  sensors: SensorConfig[]
}

/** 默认 sensor 配置样例文件路径（可在页面中修改） */
export const DEFAULT_SENSOR_CONFIG_PATH =
  '/home/tstj/project/nvidia/Qnx_Standard_7.2.4.0/drive-qnx/samples/nvmedia/nvsipl/query/database/predev_mixgroup/imx623.json'

/** raw图用例生成参数 */
export interface RawLightingOptions {
  /** -f 输出目录 */
  image_path: string
  /** --skipFrames */
  skip_frames: number
  /** --writeFrames */
  write_frames: number
}

export const DEFAULT_RAW_LIGHTING_OPTIONS: RawLightingOptions = {
  image_path: './picture/',
  skip_frames: 10,
  write_frames: 1,
}

/** YUV 可输出的 ISP 通道 */
export const YUV_CHANNELS = [0, 1, 2] as const
export type YuvChannel = (typeof YUV_CHANNELS)[number]

/** 功能测试参数：raw图（.raw）与 YUV 图（.yuv）共用输出参数，YUV 额外需要 NITO 目录与输出通道 */
export interface FunctionalTestOptions extends RawLightingOptions {
  /** --nito NITO 文件目录（生成 YUV 图时使用） */
  nito_path: string
  /** 启用的 YUV 输出通道（0/1/2），未选中的通道会用 -0/-1/-2 关闭 */
  yuv_channels: YuvChannel[]
  /**
   * 支持 th（温度直方图）测试的 sensor 型号。
   *
   * 部分 sensor 不支持 th 功能，因此需要手动勾选；只有平台拓扑中 sensor
   * 名称与列表中某一项匹配的相机才会生成 th 用例。
   */
  th_sensors: string[]
}

export const DEFAULT_FUNCTIONAL_TEST_OPTIONS: FunctionalTestOptions = {
  ...DEFAULT_RAW_LIGHTING_OPTIONS,
  nito_path: './nito/',
  yuv_channels: [0],
  th_sensors: [],
}

/** 选择要生成哪几类测试用例 */
export interface FunctionalTestSelection {
  /** raw图（生成 .raw） */
  lighting: boolean
  /** YUV 图（生成 .yuv） */
  yuv: boolean
  /** ro 读取测试（起流后读取 readout 信息） */
  ro: boolean
  /** al 读取测试（起流后读取有效像素信息） */
  al: boolean
  /** th 温度直方图测试（仅对勾选的 sensor 型号生成） */
  th: boolean
  /** 压力测试（反复起流，组合与次数在压力测试步骤中配置） */
  stress: boolean
}

export const DEFAULT_FUNCTIONAL_TEST_SELECTION: FunctionalTestSelection = {
  lighting: true,
  yuv: true,
  ro: true,
  al: true,
  th: false,
  stress: false,
}

/** 测试类型名称 */
export const TEST_TYPE_LIGHTING = 'raw图'
export const TEST_TYPE_YUV = 'YUV图'
export const TEST_TYPE_RO = 'ro测试'
export const TEST_TYPE_AL = 'al测试'
export const TEST_TYPE_TH = 'th测试'
export const TEST_TYPE_STRESS = '压力测试'

/** 压力测试默认反复起流次数 */
export const DEFAULT_STRESS_REPEAT_COUNT = 10

/**
 * 压力测试中的一条用例配置。
 *
 * camera_keys 使用拓扑行 key（`<group_index>-<link_index>-<拓扑行号>`），
 * 一个组合里的相机同时起流，生成命令时会把各相机的 Group / linkIndex
 * 合并成同一个 -m 掩码。
 */
export interface StressCameraCombination {
  /** 组合唯一标识（用于用例 key 与表格 rowKey） */
  id: string
  /** 参与起流的相机（拓扑行 key 列表） */
  camera_keys: string[]
  /** 反复起流次数 */
  repeat_count: number
}

/** 压力测试配置：每条用例的相机组合与起流次数均可单独配置 */
export interface StressTestOptions {
  combinations: StressCameraCombination[]
}

export const DEFAULT_STRESS_TEST_OPTIONS: StressTestOptions = {
  combinations: [],
}

/** 生成出的测试用例 */
export interface GeneratedCase {
  key: string
  group: string
  link_index: number
  module: string
  sensor_id: number | null
  /** 测试类型，例如：raw图 */
  test_type: string
  description: string
  prerequisites: string
  steps: string
  expected: string
  priority: string
}
