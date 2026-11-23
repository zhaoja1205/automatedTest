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
  /**
   * 是否启用该相机（默认 true）。
   *
   * 在「平台配置」步骤中逐台勾选；未启用的相机不会生成功能 / 压力 / 稳定性用例。
   */
  enabled?: boolean
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

/**
 * 自定义测试用例模板。
 *
 * 各文本字段支持 ``{config}``、``{mask}``、``{sensorid}`` 等占位符，
 * 生成时会按每台相机（或首个已启用相机）自动替换，占位符列表见
 * ``utils/casegen/functionalCases.ts`` 中的 ``CASE_TEMPLATE_PLACEHOLDERS``。
 */
export interface CustomCaseTemplate {
  /** 模板唯一标识（前端自动生成） */
  id: string
  /** 测试类型名称，默认「自定义测试」 */
  test_type: string
  /** 用例描述 */
  description: string
  /** 前置条件 */
  prerequisites: string
  /** 测试步骤（支持占位符） */
  steps: string
  /** 预期结果 */
  expected: string
  /** 优先级，例如 P1 */
  priority: string
  /**
   * 是否按相机生成。
   *
   * true（默认）：每台已启用相机各生成一条，占位符按该相机替换；
   * false：只生成一条，占位符按第一台已启用相机替换。
   */
  per_camera: boolean
  /** 是否参与本次用例生成（自定义标签页内的「参与本次生成」开关） */
  enabled: boolean
}

/** 内置功能测试预设标签的 key */
export const PRESET_CASE_KEYS = [
  'lighting',
  'yuv',
  'ro',
  'al',
  'intrinsic',
  'th',
  'dl_el',
] as const

export type PresetCaseKey = (typeof PRESET_CASE_KEYS)[number]

/**
 * 内置预设用例的可编辑字段。
 *
 * 未填写的字段使用默认模板；用户编辑任意字段后，该预设标签会保存一份完整
 * 的可编辑内容（`FunctionalTestOptions.preset_cases`），生成时与自定义用例
 * 一样按占位符替换。测试类型与预设 key 绑定，不可修改。
 */
export interface PresetCaseEdit {
  /** 用例描述 */
  description: string
  /** 前置条件 */
  prerequisites: string
  /** 测试步骤（支持占位符） */
  steps: string
  /** 预期结果 */
  expected: string
  /** 优先级，例如 P1 */
  priority: string
  /** 是否按相机生成 */
  per_camera: boolean
}

/** 内置预设用例的编辑内容，按预设 key 保存；未编辑的 key 使用默认模板 */
export type PresetCaseEdits = Partial<Record<PresetCaseKey, PresetCaseEdit>>

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
  /** 自定义测试用例模板（支持 {config} / {mask} / {sensorid} 等占位符） */
  custom_cases: CustomCaseTemplate[]
  /** 内置预设用例的编辑内容（未填写的预设使用默认模板） */
  preset_cases: PresetCaseEdits
  /**
   * 已关闭（隐藏）的内置预设标签。
   *
   * 关闭的预设不显示标签、不参与本次生成；其「参与本次生成」状态与编辑内容
   * 仍保留，点击标签栏的 + 可重新打开。为空时 + 直接新增自定义用例。
   */
  closed_presets: PresetCaseKey[]
}

export const DEFAULT_FUNCTIONAL_TEST_OPTIONS: FunctionalTestOptions = {
  ...DEFAULT_RAW_LIGHTING_OPTIONS,
  nito_path: './nito/',
  yuv_channels: [0],
  th_sensors: [],
  custom_cases: [],
  preset_cases: {},
  closed_presets: [],
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
  /** 内参读取测试（通过 -e 读取模组内参/寄存器并校验 CRC） */
  intrinsic: boolean
  /** th 温度直方图测试（仅对勾选的 sensor 型号生成） */
  th: boolean
  /** dl el 热插拔测试（输入 dl 关闭链路、输入 el 恢复链路，验证帧率降为 0 后恢复） */
  dl_el: boolean
  /** 压力测试（反复起流，组合与次数在压力测试步骤中配置） */
  stress: boolean
  /** 稳定性测试（长时间起流，组合与时长在稳定性测试步骤中配置） */
  stability: boolean
}

export const DEFAULT_FUNCTIONAL_TEST_SELECTION: FunctionalTestSelection = {
  lighting: true,
  yuv: true,
  ro: true,
  al: true,
  intrinsic: true,
  th: false,
  dl_el: true,
  stress: false,
  stability: false,
}

/** 测试类型名称 */
export const TEST_TYPE_LIGHTING = 'raw图'
export const TEST_TYPE_YUV = 'YUV图'
export const TEST_TYPE_RO = 'ro测试'
export const TEST_TYPE_AL = 'al测试'
export const TEST_TYPE_INTRINSIC = '内参测试'
export const TEST_TYPE_TH = 'th测试'
export const TEST_TYPE_DL_EL = 'dl el测试'
export const TEST_TYPE_CUSTOM = '自定义测试'
export const TEST_TYPE_STRESS = '压力测试'
export const TEST_TYPE_STABILITY = '稳定性测试'
/** 故障测试的测试类型名称；与测试用例文档「故障测试」Sheet 中已有用例保持一致 */
export const TEST_TYPE_FAULT = '故障上报'

/** 压力测试默认反复起流次数 */
export const DEFAULT_STRESS_REPEAT_COUNT = 10

/** 稳定性测试默认持续起流时长（分钟） */
export const DEFAULT_STABILITY_DURATION_MINUTES = 60

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

/**
 * 稳定性测试中的一条用例配置。
 *
 * 与压力测试相同的相机组合方式，但配置的是持续起流时长（分钟）。
 */
export interface StabilityCameraCombination {
  /** 组合唯一标识（用于用例 key 与表格 rowKey） */
  id: string
  /** 参与起流的相机（拓扑行 key 列表） */
  camera_keys: string[]
  /** 持续起流时长（分钟） */
  duration_minutes: number
}

/** 稳定性测试配置：每条用例的相机组合与起流时长均可单独配置 */
export interface StabilityTestOptions {
  combinations: StabilityCameraCombination[]
}

export const DEFAULT_STABILITY_TEST_OPTIONS: StabilityTestOptions = {
  combinations: [],
}

// ============================================================================
// 故障测试：注入 sensor 内部故障并清除
// ============================================================================

/**
 * 一条可注入的故障。
 *
 * ``no`` 对应故障注入脚本的 ``-n`` 参数，``error_code`` 为注入后驱动上报的
 * CDI 故障码（写入用例的预期结果，执行时预期解析会据此判定为故障测试）。
 */
export interface FaultCatalogItem {
  /** 故障号（脚本 -n 参数） */
  no: number
  /** 注入后应上报的 CDI 故障码 */
  error_code: string
}

/** 一个 sensor 型号对应的故障清单 */
export interface FaultCatalog {
  /** 清单标识，例如 IMX728 */
  key: string
  /** 清单显示名称 */
  label: string
  /** 故障注入脚本默认路径（板端执行） */
  script_path: string
  /** 清单内的全部故障 */
  items: FaultCatalogItem[]
}

/** IMX728 故障清单：与 fault_simulation_728_qnx.sh 中的故障号一一对应 */
export const IMX728_FAULT_CATALOG: FaultCatalog = {
  key: 'IMX728',
  label: 'IMX728',
  script_path: './fault_simulation_728_qnx.sh',
  items: [
    { no: 1, error_code: 'CDI_SENSOR_CLK_ABNORMAL_ERR' },
    { no: 2, error_code: 'CDI_SENSOR_SEQUENCE_ABNORMAL_ERR' },
    { no: 3, error_code: 'CDI_SENSOR_SYNC_ABNORMAL_ERR' },
    { no: 4, error_code: 'CDI_SENSOR_TEMPERATURE_ABNORMAL_ERR' },
    { no: 5, error_code: 'CDI_SENSOR_SRAM_ABNORMAL_ERR' },
    { no: 6, error_code: 'CDI_SENSOR_OTP_ABNORMAL_ERR' },
    { no: 7, error_code: 'CDI_SENSOR_ROM_ABNORMAL_ERR' },
    { no: 8, error_code: 'CDI_SENSOR_ABIST_ABNORMAL_ERR' },
    { no: 9, error_code: 'CDI_SENSOR_DATAPATH_TEST_ERR' },
    { no: 10, error_code: 'CDI_SENSOR_REGISTER_ABNORMAL_ERR' },
    { no: 11, error_code: 'CDI_SENSOR_INTERNAL_BUS_ERR' },
    { no: 12, error_code: 'CDI_SENSOR_ROWCOLUMN_ID_CHECK_ERR' },
    { no: 13, error_code: 'CDI_SENSOR_VOLTAGE_CHECK_ERR' },
    { no: 14, error_code: 'CDI_SENSOR_DUAL_LOCKSTEP_ERR' },
    { no: 15, error_code: 'CDI_SENSOR_WATCHDOG_TIMER_ERR' },
    { no: 16, error_code: 'CDI_SENSOR_DMAC_ABNORMAL_ERR' },
    { no: 17, error_code: 'CDI_SENSOR_POWER_SWITCH_ERR' },
    { no: 18, error_code: 'CDI_SENSOR_CCC_PEELING_CHECK_ERR' },
    { no: 19, error_code: 'CDI_SENSOR_CONTROL_FLOW_ERR' },
    { no: 20, error_code: 'CDI_SENSOR_MEMORY_PROTECTION_ERR' },
    { no: 21, error_code: 'CDI_SENSOR_LBIST_ABNORMAL_ERR' },
    { no: 22, error_code: 'CDI_SENSOR_MBIST_ABNORMAL_ERR' },
    { no: 23, error_code: 'CDI_SENSOR_COMMUNICATION_CRC_ERR' },
    { no: 24, error_code: 'CDI_SENSOR_APPLICATION_LOCK_ERR' },
    { no: 25, error_code: 'CDI_SENSOR_DATA_RANGE_CHECK_ERR' },
    { no: 26, error_code: 'CDI_SENSOR_FSYNC_ABNORMAL_ERR' },
    { no: 27, error_code: 'CDI_SENSOR_FLASH_CHECK_ERR' },
  ],
}

/** 已支持的故障清单（新增 sensor 型号时在此追加） */
export const FAULT_CATALOGS: FaultCatalog[] = [IMX728_FAULT_CATALOG]

/** 按清单标识取故障清单，未知标识回退到第一份清单 */
export function findFaultCatalog(key?: string): FaultCatalog {
  return FAULT_CATALOGS.find((catalog) => catalog.key === key) ?? FAULT_CATALOGS[0]
}

/**
 * 运行时的故障测试标签页：用户创建的标签配置 + 解析后的故障单。
 *
 * 标签页由用户在页面上通过「+」创建，数量不限；每个标签页可自定义名称，
 * 并在标签内部选择使用哪一份故障单（见 ``FAULT_CATALOGS``）。未来新增
 * 其它故障单时只需在 ``FAULT_CATALOGS`` 中追加，标签内的下拉即可选择。
 */
export interface FaultTabInstance {
  /** 标签页标识（同时作为配置 key） */
  key: string
  /** 标签页配置（名称、故障单、勾选故障等） */
  options: FaultTestTabOptions
  /** 标签页当前使用的故障单 */
  catalog: FaultCatalog
}

/**
 * 故障测试用例的可编辑模板。
 *
 * 各文本字段支持占位符，生成时按每条故障与所选相机替换：
 *
 * - 故障相关：``{fault_no}``、``{error_code}``、``{script}``、
 *   ``{i2c_bus}``、``{sensor_addr}``、``{observe_command}``、``{requirement_id}``
 * - 相机相关：``{config}``、``{mask}``、``{sensorid}``、``{module}``、
 *   ``{nito_path}`` 等（见 ``CASE_TEMPLATE_PLACEHOLDERS``）
 */
export interface FaultCaseTemplate {
  /** 用例描述，默认「第{fault_no}号故障验证」 */
  description: string
  /** 前置条件 */
  prerequisites: string
  /** 测试步骤（支持占位符） */
  steps: string
  /** 预期结果（支持占位符） */
  expected: string
  /** 优先级，例如 P1 */
  priority: string
}

/** 可部分填写的模板；未填写的字段回退到上级模板或内置默认模板 */
export type FaultCaseTemplatePatch = Partial<FaultCaseTemplate>

/** 单个故障测试标签页的配置 */
export interface FaultTestTabOptions {
  /** 标签页显示名称，可由用户自定义 */
  label: string
  /** 该标签页使用的故障单标识（``FAULT_CATALOGS`` 中的 key） */
  catalog: string
  /** 是否参与本次生成（标签页内的「参与本次生成」开关） */
  enabled: boolean
  /** 勾选要生成用例的故障号 */
  faults: number[]
  /** 该标签页所有故障共用的用例模板；未填写字段使用内置默认模板 */
  case_template?: FaultCaseTemplatePatch
  /** 该标签页内按故障号单独覆盖的模板字段 */
  fault_templates?: Record<string, FaultCaseTemplatePatch>
}

/** 故障测试配置 */
export interface FaultTestOptions {
  /** 是否生成「清除故障」步骤（所有标签页共用） */
  clear_fault: boolean
  /** 各故障测试标签页的配置，key 为标签页标识（如 IMX728 / tab-1） */
  tabs: Record<string, FaultTestTabOptions>
  /** 故障注入脚本路径（作为 {script} 占位符的默认值） */
  script_path: string
  /** -i I2C 总线号（作为 {i2c_bus} 占位符的默认值） */
  i2c_bus: string
  /** -a sensor 的 I2C 地址（作为 {sensor_addr} 占位符的默认值） */
  sensor_addr: string
  /** 参与用例的相机（拓扑行 key）；为空时取第一台已启用的相机 */
  camera_key: string
  /** 起流命令中 --nito 指定的目录（作为 {nito_path} 占位符的默认值） */
  nito_path: string
  /** 注入故障后在终端A观察故障用的指令（作为 {observe_command} 占位符的默认值） */
  observe_command: string
  /** 需求ID（写入 Excel「需求ID」列，可留空） */
  requirement_id: string
  /** @deprecated 旧版单清单配置，仅用于兼容旧草稿 */
  catalog?: string
  /** @deprecated 旧版勾选的故障号，仅用于兼容旧草稿 */
  faults?: number[]
  /** @deprecated 旧版共享模板，仅用于兼容旧草稿 */
  case_template?: FaultCaseTemplatePatch
  /** @deprecated 旧版按故障号覆盖的模板，仅用于兼容旧草稿 */
  fault_templates?: Record<string, FaultCaseTemplatePatch>
}

/** 生成故障标签页的默认配置：名称取故障单名称，全部故障勾选，但不参与本次生成 */
export function defaultFaultTabOptions(catalog: FaultCatalog): FaultTestTabOptions {
  return {
    label: catalog.label,
    catalog: catalog.key,
    enabled: false,
    faults: catalog.items.map((item) => item.no),
  }
}

export const DEFAULT_FAULT_TEST_OPTIONS: FaultTestOptions = {
  clear_fault: true,
  tabs: {
    [IMX728_FAULT_CATALOG.key]: defaultFaultTabOptions(IMX728_FAULT_CATALOG),
  },
  script_path: IMX728_FAULT_CATALOG.script_path,
  i2c_bus: '9',
  sensor_addr: '4c',
  camera_key: '',
  nito_path: './nito/',
  observe_command: 'df',
  requirement_id: 'PREDEV_024-R001',
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
  /** 需求ID（写入 Excel「需求ID」列，故障测试用例会带上） */
  requirement_id?: string
  /** 导出目标 Sheet（故障测试用例显式标记为「故障测试」） */
  sheet_name?: string
}
