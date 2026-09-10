/**
 * 用例规范校验规则。
 *
 * 镜像后端 ExpectedResultParser 的判定要素，在前端给出实时反馈。
 * 后端 parser 是权威实现；本文件是其在前端的等价摘要，用于提示而非判定。
 *
 * ExpectedResultParser 可识别的判定要素：
 *   - 产物后缀 .raw/.yuv/.png/.jpg/.jpeg/.log/.txt/.csv → file_check
 *   - 数值 NNfps / NN帧 → 帧率检查（±20% 容差）
 *   - 无报错/无异常/无错误 → exit_code 检查
 *   - 正常起流/正常启动/正常输出 → 注入 streaming/started/initialized
 *   - 引号包裹的字符串 → 精确关键字
 *   - 十六进制 0xNN（跟在「值为/返回/等于/为」后）→ 关键字
 *
 * 空提取 → 引擎只能依赖退出码判定，置信度上限 0.7。
 */
import type { DesignCase } from '../types/creator'

export type CaseValidationLevel = 'ok' | 'warn' | 'error'

export interface CaseValidation {
  level: CaseValidationLevel
  messages: string[]
}

/** 文件后缀正则（与 expected_parser.py:172-176 对齐） */
const FILE_SUFFIX_RE = /\.(raw|yuv|png|jpg|jpeg|log|txt|csv)/i
/** 帧率数值正则（与 expected_parser.py:140-143 对齐） */
const FPS_RE = /(\d+)\s*(?:fps|FPS|帧)/i
/** 帧率稳定性表述（与 expected_parser.py:161-163 对齐） */
const FPS_STABLE_RE = /帧率不变|帧率稳定|保证帧率|帧率正常|fps稳定|fps不变|正常出帧|稳定出帧/i
/** 无报错表述（与 expected_parser.py:211-212 对齐） */
const NO_ERROR_RE = /无报错|无异常|无错误|不报错|no error|without error|no exception/i
/** 正常起流表述（与 expected_parser.py:246 对齐） */
const STREAM_OK_RE = /正常起流|正常启动|正常输出/i
/** 引号包裹的字符串（与 expected_parser.py:107 对齐） */
const QUOTED_RE = /"([^"]+)"/
/** 步骤中的命令标志（判断步骤是否含可执行命令） */
const CMD_RE = /(\.\/|sudo|nvsipl|i2c|python|\.sh|export|cd\s)/i
/** 步骤数字编号 */
const STEP_NUM_RE = /^\s*\d+、/

/** 占位符标记（与 creator_store._collect_placeholders 对齐） */
const PLACEHOLDER_RE = /<待补充[^>]*>/

/**
 * 校验单条用例是否符合执行引擎可判定的规范。
 */
export function validateCase(c: DesignCase): CaseValidation {
  const messages: string[] = []
  let level: CaseValidationLevel = 'ok'

  // 描述为空 → error
  if (!c.desc || !c.desc.trim()) {
    level = 'error'
    messages.push('用例描述为空')
  }

  // 预期结果为空 / 仅占位符 → error
  const expected = c.expected || ''
  if (!expected.trim()) {
    level = 'error'
    messages.push('预期结果为空')
  } else if (PLACEHOLDER_RE.test(expected)) {
    level = 'error'
    messages.push('预期结果含 <待补充> 占位符，引擎无法判定')
  } else {
    // 预期结果必须含可判定观测点
    const hasFile = FILE_SUFFIX_RE.test(expected)
    const hasFps = FPS_RE.test(expected)
    const hasFpsStable = FPS_STABLE_RE.test(expected)
    const hasNoError = NO_ERROR_RE.test(expected)
    const hasStreamOk = STREAM_OK_RE.test(expected)
    const hasQuoted = QUOTED_RE.test(expected)

    if (!hasFile && !hasFps && !hasFpsStable && !hasNoError && !hasStreamOk && !hasQuoted) {
      if (level !== 'error') level = 'warn'
      messages.push('预期结果缺少可判定观测点（文件后缀/帧率数值/无报错/正常起流/引号关键字），引擎将只能依赖退出码判定，置信度低')
    }
  }

  // 步骤校验
  const steps = c.steps || ''
  if (!steps.trim()) {
    if (level !== 'error') level = 'warn'
    messages.push('测试步骤为空')
  } else {
    if (!CMD_RE.test(steps)) {
      if (level !== 'error') level = 'warn'
      messages.push('测试步骤未检测到可执行命令（./nvsipl / sudo / i2c 等）')
    }
    if (!STEP_NUM_RE.test(steps)) {
      if (level !== 'error') level = 'warn'
      messages.push('测试步骤缺少数字编号（如 1、2、）')
    }
  }

  if (messages.length === 0) {
    return { level: 'ok', messages: ['可判定'] }
  }
  return { level, messages }
}

/**
 * 批量校验，返回通过率摘要。
 */
export function summarizeValidation(cases: DesignCase[]): {
  ok: number
  warn: number
  error: number
} {
  let ok = 0, warn = 0, error = 0
  for (const c of cases) {
    const v = validateCase(c)
    if (v.level === 'ok') ok++
    else if (v.level === 'warn') warn++
    else error++
  }
  return { ok, warn, error }
}

/**
 * 插入示例：返回一条符合规范的黄金示例用例（起流+出图）。
 */
export function sampleCase(): DesignCase {
  return {
    type: '基本功能',
    method: '基于需求分析',
    desc: '验证 IMX728 模组起流并正常出图（RAW/YUV 落盘）',
    pre: (
      '1、驱动文件放入目录：/usr/lib/nvidia/nvsipl_drv\n' +
      '2、板子连接模组，确认模组在位\n' +
      '3、SSH 登录板端'
    ),
    steps: (
      '1、输入命令：./nvsipl_camera -c MIXGROUP_PREDEV_30FPS_MAX96724_CPHY_x4 -m "0x1 0 0 0" -R -0 -1 -2 -s -f ./picture/ --skipFrames 10 --writeFrames 1\n' +
      '①、查看模组名称的方法：./nvsipl_camera -l\n' +
      '②、-m 指定模组位置，-f 指定图片存放目录'
    ),
    expected: (
      '1、执行命令无报错，可生成.raw文件\n' +
      '2、raw 可正常查看，图像无花屏、无黑屏'
    ),
    priority: 'P1',
    changelog: '',
  }
}
