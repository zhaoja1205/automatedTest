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

/** 点亮用例生成参数 */
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

/** 生成出的测试用例 */
export interface GeneratedCase {
  key: string
  group: string
  link_index: number
  module: string
  sensor_id: number | null
  /** 测试类型，例如：点亮 */
  test_type: string
  description: string
  prerequisites: string
  steps: string
  expected: string
  priority: string
}
