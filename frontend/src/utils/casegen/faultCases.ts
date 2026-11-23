/**
 * 故障测试用例生成。
 *
 * 针对 sensor 内部可注入的故障（如 IMX728 的 27 类故障），每条故障生成一条用例：
 * 起流 → 用故障注入脚本注入故障 → 观察驱动上报的 CDI 故障码 → 清除故障 → 退出。
 *
 * 故障注入脚本（fault_simulation_728_qnx.sh）的参数约定：
 *   ./fault_simulation_728_qnx.sh -i <I2C总线> -a <sensor地址> -n <故障号> [-c]
 * 其中 -c 表示清除故障。
 *
 * 用例的测试类型固定为「故障上报」：预期结果中出现 CDI 故障码，执行器的预期解析
 * 会据此识别为故障测试（输出中的 ERROR 属于预期行为，不按失败处理）。
 */
import type {
  FaultCaseTemplate,
  FaultCatalogItem,
  FaultTestOptions,
  FunctionalTestSelection,
  GeneratedCase,
  PlatformConfig,
  PlatformTopologyRow,
  SensorConfig,
} from '../../types/casegen'
import {
  DEFAULT_FUNCTIONAL_TEST_OPTIONS,
  TEST_TYPE_FAULT,
  findFaultCatalog,
} from '../../types/casegen'
import {
  buildCaseTemplateContext,
  buildMask,
  CASE_TEMPLATE_PLACEHOLDERS,
  platformMaskGroupCount,
  renderCaseTemplate,
  topologyRowKey,
  type CaseTemplateContext,
} from './functionalCases'

/**
 * 故障用例的步骤模板（支持占位符）。
 *
 * 脚本路径 / I2C 总线 / Sensor 地址 / 观察指令 / nito 目录默认直接写成实际值，
 * 用户可在模板中直接修改；也可改用 {script}、{i2c_bus}、{sensor_addr}、
 * {observe_command}、{nito_path} 等占位符。
 */
export const FAULT_CASE_STEPS_TEMPLATE = [
  '1、终端A输入命令：./nvsipl_camera -c {config} -m "{mask}" -R -1 -2 -s --nito ./nito/ -Z',
  '①、查看模组名称的方法：./nvsipl_camera -l',
  '②、"{config}"改为需要的模组名称',
  '③、-m 指定模组位置',
  '2、终端A输入gc {sensorid}选择要查看的模组',
  '3、终端B输入./fault_simulation_728_qnx.sh -i 9 -a 4c -n {fault_no} 注入故障',
  '4、终端A输入df指令查看相关的sensor故障情况',
  '5、终端B输入./fault_simulation_728_qnx.sh -i 9 -a 4c -n {fault_no} -c 清除故障',
  '6、终端A输入q退出应用',
].join('\n')

/** 故障用例的预期结果模板；清除步骤未被选中时去掉第 3 行 */
export const FAULT_CASE_EXPECTED_TEMPLATE = [
  '1、执行命令正常起流,',
  '2、故障注入后能检测到{error_code}故障',
  '3、清除故障后故障状态恢复，画面与帧率正常',
].join('\n')

/** 故障用例的前置条件模板 */
export const FAULT_CASE_PREREQUISITES_TEMPLATE = [
  '1、驱动文件放入目录：/usr/libnvidia/nvsipl_drv',
  '2、板子连接模组见附录1',
  '3、故障注入脚本已拷贝到板端当前目录：./fault_simulation_728_qnx.sh',
].join('\n')

/** 故障用例的描述模板 */
export const FAULT_CASE_DESCRIPTION_TEMPLATE = '{fault_name}故障验证'

/** 内置默认的故障用例模板（可被共享模板与按故障号覆盖的模板逐字段替换） */
export const DEFAULT_FAULT_CASE_TEMPLATE: FaultCaseTemplate = {
  description: FAULT_CASE_DESCRIPTION_TEMPLATE,
  prerequisites: FAULT_CASE_PREREQUISITES_TEMPLATE,
  steps: FAULT_CASE_STEPS_TEMPLATE,
  expected: FAULT_CASE_EXPECTED_TEMPLATE,
  priority: 'P1',
}

/**
 * 故障用例模板支持的占位符。
 *
 * 在功能测试的基础占位符（{config} / {mask} / {sensorid} 等）之上，
 * 增加故障注入脚本与当前故障项相关的占位符。
 */
export const FAULT_CASE_PLACEHOLDERS: Array<{ key: string; label: string }> = [
  { key: 'fault_no', label: '故障号（脚本 -n 参数）' },
  { key: 'fault_name', label: '故障名称' },
  { key: 'error_code', label: '注入后上报的 CDI 故障码' },
  { key: 'script', label: '故障注入脚本路径' },
  { key: 'i2c_bus', label: 'I2C 总线号（-i）' },
  { key: 'sensor_addr', label: 'Sensor I2C 地址（-a）' },
  { key: 'observe_command', label: '观察故障用的指令（如 df）' },
  { key: 'requirement_id', label: '需求ID' },
  ...CASE_TEMPLATE_PLACEHOLDERS,
]

/** 去掉默认模板中的清除故障步骤 / 预期行（未勾选「清除故障」时使用） */
function withoutClearFault(text: string): string {
  return text
    .split('\n')
    .filter((line) => !line.includes('清除故障'))
    .join('\n')
}


/**
 * 合并内置默认模板、共享模板与指定故障号的覆盖模板。
 *
 * 返回原始模板内容（保留默认的清除故障步骤），供配置页编辑与预览使用。
 * 未填写的字段依次回退：故障号覆盖 → 共享模板 → 内置默认。
 */
export function faultCaseTemplateOf(
  options: FaultTestOptions,
  faultNo?: number,
): FaultCaseTemplate {
  const shared = options.case_template ?? {}
  const override =
    faultNo === undefined ? {} : (options.fault_templates?.[String(faultNo)] ?? {})
  return {
    description: override.description ?? shared.description ?? DEFAULT_FAULT_CASE_TEMPLATE.description,
    prerequisites:
      override.prerequisites ?? shared.prerequisites ?? DEFAULT_FAULT_CASE_TEMPLATE.prerequisites,
    steps: override.steps ?? shared.steps ?? DEFAULT_FAULT_CASE_TEMPLATE.steps,
    expected: override.expected ?? shared.expected ?? DEFAULT_FAULT_CASE_TEMPLATE.expected,
    priority: override.priority ?? shared.priority ?? DEFAULT_FAULT_CASE_TEMPLATE.priority,
  }
}

/**
 * 生成用例时实际使用的模板。
 *
 * 未自定义步骤 / 预期结果时，按「生成清除故障步骤」开关去掉默认模板中的
 * 清除故障步骤与对应预期行；用户自定义的内容保持原样。
 */
export function effectiveFaultCaseTemplate(
  options: FaultTestOptions,
  faultNo: number,
): FaultCaseTemplate {
  const template = faultCaseTemplateOf(options, faultNo)
  if (options.clear_fault) return template

  const shared = options.case_template ?? {}
  const override = options.fault_templates?.[String(faultNo)] ?? {}
  const hasCustomSteps = (override.steps ?? shared.steps) !== undefined
  const hasCustomExpected = (override.expected ?? shared.expected) !== undefined
  return {
    ...template,
    steps: hasCustomSteps ? template.steps : withoutClearFault(template.steps),
    expected: hasCustomExpected ? template.expected : withoutClearFault(template.expected),
  }
}

/** 模板是否有可生成的内容（至少填写描述 / 测试步骤 / 预期结果之一） */
export function isFaultCaseTemplateUsable(template: FaultCaseTemplate): boolean {
  return [template.description, template.steps, template.expected].some(
    (value) => (value || '').trim() !== '',
  )
}

/** 构造注入 / 清除故障的脚本命令 */
export function buildFaultScriptCommand(options: FaultTestOptions, faultNo: number, clear = false): string {
  const script = (options.script_path || '').trim() || './fault_simulation_728_qnx.sh'
  const bus = (options.i2c_bus || '').trim() || '0'
  const addr = (options.sensor_addr || '').trim() || '44'
  return `${script} -i ${bus} -a ${addr} -n ${faultNo}${clear ? ' -c' : ''}`
}

/** 构造故障测试的起流命令（与参考用例一致：-R -1 -2 -s --nito <目录> -Z） */
export function buildFaultStreamCommand(
  platformName: string,
  row: PlatformTopologyRow,
  nitoPath: string,
  groupCount = 4,
): string {
  const nito = (nitoPath || '').trim() || './nito/'
  return `./nvsipl_camera -c ${platformName} -m "${buildMask(row, groupCount)}" -R -1 -2 -s --nito ${nito} -Z`
}

/**
 * 按故障清单与当前配置构造占位符上下文。
 *
 * 在相机上下文（{config} / {mask} / {sensorid} 等）的基础上补充故障相关字段：
 * {fault_no} {fault_name} {error_code} {script} {i2c_bus} {sensor_addr}
 * {observe_command} {requirement_id}。
 */
export function buildFaultTemplateContext(
  platform: PlatformConfig,
  row: PlatformTopologyRow,
  options: FaultTestOptions,
  sensors?: SensorConfig[],
  groupCount = platformMaskGroupCount(platform),
): CaseTemplateContext {
  const base = buildCaseTemplateContext(
    platform,
    row,
    { ...DEFAULT_FUNCTIONAL_TEST_OPTIONS, nito_path: options.nito_path },
    sensors,
    groupCount,
  )
  const script = (options.script_path || '').trim() || './fault_simulation_728_qnx.sh'
  return {
    ...base,
    nito_path: (options.nito_path || '').trim() || './nito/',
    script,
    i2c_bus: (options.i2c_bus || '').trim() || '0',
    sensor_addr: (options.sensor_addr || '').trim() || '44',
    observe_command: (options.observe_command || '').trim() || 'df',
    requirement_id: (options.requirement_id || '').trim(),
  }
}

/** 构造某条故障的完整占位符上下文（相机信息 + 故障号 / 名称 / 故障码） */
export function buildFaultCaseContext(
  platform: PlatformConfig,
  row: PlatformTopologyRow,
  options: FaultTestOptions,
  item: FaultCatalogItem,
  sensors?: SensorConfig[],
  groupCount = platformMaskGroupCount(platform),
): CaseTemplateContext {
  return {
    ...buildFaultTemplateContext(platform, row, options, sensors, groupCount),
    fault_no: String(item.no),
    fault_name: item.name,
    error_code: item.error_code,
  }
}

/** 取本次参与生成的目标相机：优先使用配置里选中的相机，否则用第一台已启用相机 */
export function selectFaultCamera(
  platform: PlatformConfig,
  options: FaultTestOptions,
): { row: PlatformTopologyRow; index: number } | null {
  const rows: Array<{ row: PlatformTopologyRow; index: number }> = []
  platform.topology.forEach((row, index) => {
    if (row.enabled !== false) rows.push({ row, index })
  })
  if (rows.length === 0) return null
  const configured = rows.find(({ row, index }) => topologyRowKey(row, index) === options.camera_key)
  return configured ?? rows[0]
}

/** 本次将生成用例的故障项（按故障号升序，忽略清单中不存在的故障号） */
export function selectedFaultItems(options: FaultTestOptions): FaultCatalogItem[] {
  const catalog = findFaultCatalog(options.catalog)
  const selected = new Set(options.faults ?? [])
  return catalog.items
    .filter((item) => selected.has(item.no))
    .sort((a, b) => a.no - b.no)
}

interface GenerateFaultOptions {
  platform: PlatformConfig
  selection: FunctionalTestSelection
  options: FaultTestOptions
  sensors?: SensorConfig[]
}

/**
 * 按「勾选的故障」逐条生成故障测试用例。
 *
 * 故障注入针对整台板卡（同一 sensor 的 I2C 地址），因此不按相机逐台展开：
 * 每条故障生成一条用例，起流命令使用选中相机（默认第一台已启用相机）的掩码。
 */
export function generateFaultCases({
  platform,
  selection,
  options,
  sensors,
}: GenerateFaultOptions): GeneratedCase[] {
  if (!selection.fault) return []

  const target = selectFaultCamera(platform, options)
  if (!target) return []

  const items = selectedFaultItems(options)
  if (items.length === 0) return []

  const groupCount = platformMaskGroupCount(platform)

  return items.map((item) => {
    const template = effectiveFaultCaseTemplate(options, item.no)
    const faultContext = buildFaultCaseContext(
      platform,
      target.row,
      options,
      item,
      sensors,
      groupCount,
    )
    return {
      key: `fault-${item.no}`,
      group: target.row.group,
      link_index: target.row.link_index,
      module: target.row.module,
      sensor_id: target.row.sensor_id,
      test_type: TEST_TYPE_FAULT,
      description: renderCaseTemplate(template.description, faultContext),
      prerequisites: renderCaseTemplate(template.prerequisites, faultContext),
      steps: renderCaseTemplate(template.steps, faultContext),
      expected: renderCaseTemplate(template.expected, faultContext),
      priority: template.priority || 'P1',
      requirement_id: faultContext.requirement_id || undefined,
    }
  })
}
