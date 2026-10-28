/**
 * 用例备注（Excel 备注列）格式解析 —— 仅用于前端展示。
 *
 * 约定格式：
 *   [AI判定] <状态> (置信度=<0~1 的小数>)
 *   判定依据: <判定理由>
 *   - <证据>
 *   --- 执行日志 ---
 *   <执行日志全文>
 *
 * 若备注不符合该格式（例如人工填写的旧备注、纯日志），
 * 实际结果栏原样展示备注内容。
 */

const AI_HEADER_RE =
  /^\[AI判定\]\s*(Pass|Fail|Review|NEED_REVIEW|BLOCK|NA|NT)\s*[（(]\s*置信度\s*[=＝]\s*([0-9]+(?:\.[0-9]+)?)\s*[）)]\s*$/i

const LOG_SEPARATOR_RE = /^-{3,}\s*执行日志\s*-{3,}$/

export interface ParsedRemark {
  /** 备注是否符合约定格式 */
  valid: boolean
  /** AI 判定状态（兼容 NEED_REVIEW） */
  aiStatus: string
  /** AI 置信度 */
  aiConfidence: number | null
  /** 备注中的 AI 判定区块（不含执行日志） */
  aiText: string
  /** 备注中的执行日志全文 */
  logText: string
}

const EMPTY_RESULT: ParsedRemark = {
  valid: false,
  aiStatus: '',
  aiConfidence: null,
  aiText: '',
  logText: '',
}

function splitLines(remark?: string): string[] {
  if (!remark) return []
  return remark.replace(/\r\n?/g, '\n').split('\n')
}

/** 提取备注中 `--- 执行日志 ---` 之后的内容 */
export function extractLogText(remark?: string): string {
  const lines = splitLines(remark)
  const separatorIndex = lines.findIndex((line) => LOG_SEPARATOR_RE.test(line.trim()))
  if (separatorIndex < 0) return ''
  return lines.slice(separatorIndex + 1).join('\n').trim()
}

/** 解析备注中的 AI 判定信息；格式不符合约定时 valid=false */
export function parseRemark(remark?: string): ParsedRemark {
  const lines = splitLines(remark)

  // 约定：第一个非空行必须是 AI 判定标题行
  const firstIndex = lines.findIndex((line) => line.trim() !== '')
  if (firstIndex < 0) return EMPTY_RESULT

  const header = lines[firstIndex].trim()
  const matched = header.match(AI_HEADER_RE)
  if (!matched) return EMPTY_RESULT

  const separatorIndex = lines.findIndex(
    (line, index) => index > firstIndex && LOG_SEPARATOR_RE.test(line.trim()),
  )
  const aiEnd = separatorIndex >= 0 ? separatorIndex : lines.length
  // 实际结果栏展示 AI 判定状态、判定依据与证据条目（形如 "- xxx"）
  const aiText = lines.slice(firstIndex, aiEnd).join('\n').trim()
  if (!aiText) return EMPTY_RESULT

  return {
    valid: true,
    aiStatus: matched[1],
    aiConfidence: Number(matched[2]),
    aiText,
    logText: separatorIndex >= 0 ? lines.slice(separatorIndex + 1).join('\n').trim() : '',
  }
}
