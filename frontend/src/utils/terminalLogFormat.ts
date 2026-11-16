/**
 * 按终端日志的统一文本格式。
 *
 * 与板端日志系统保持一致：执行器按终端落盘，备注列 / 日志草稿箱也使用
 * 同样的分段标题，便于三处互相转换：
 *
 *   ===== 终端A =====
 *   <终端A 输出>
 *
 *   ===== 终端B =====
 *   <终端B 输出>
 */
export interface TerminalLogSection {
  /** 终端标签（旧聚合日志为空字符串） */
  label: string
  content: string
}

// 终端分段标题必须严格为「恰好 5 个等号 + 非空标签 + 恰好 5 个等号」，
// 标签内不允许再出现 `=`，避免把日志中的 `====================` 分隔线
// 误识别成终端标题。
const HEADER_RE = /^=====\s*([^=]+?)\s*=====$/
/** 与终端标题格式相同、但属于系统分区的标题，不能当作终端 */
const NON_TERMINAL_TITLES = ['完整执行日志', '板端系统日志']

// ANSI / OSC 控制序列（颜色、光标、括号粘贴模式等）。bash 在提示符处会输出
// ESC[?2004h / ESC[?2004l，文本日志里 ESC 不可见，只剩 `[?2004l`，需统一剔除。
const ANSI_RE = /\x1B\][^\x07\x1B]*(?:\x07|\x1B\\)|\x1B\[[0-9;?]*[ -/]*[@-~]|\x1B[()][A-Za-z0-9]/g
const CONTROL_RE = /[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g

/** 剔除终端控制序列与不可见控制字符（保留换行与制表符） */
export function stripTerminalControl(text?: string | null): string {
  return (text || '')
    .replace(ANSI_RE, '')
    // 兼容早期日志：ESC 已被其它环节丢掉，只剩括号粘贴模式标记
    .replace(/\[\?2004[hl]/g, '')
    .replace(CONTROL_RE, '')
}

function matchTerminalHeader(line: string): string {
  const matched = line.trim().match(HEADER_RE)
  if (!matched) return ''
  const label = matched[1].trim()
  if (!label || NON_TERMINAL_TITLES.some((title) => label.startsWith(title))) {
    return ''
  }
  return label
}

function normalizeText(text?: string | null): string {
  // 先剔除 ESC[?2004l 等终端控制序列，再做换行归一
  return stripTerminalControl(text).replace(/\r\n?/g, '\n')
}

/** 从统一文本格式中拆出各终端日志；没有终端标题时返回空数组 */
export function parseTerminalLog(text?: string | null): TerminalLogSection[] {
  const lines = normalizeText(text).split('\n')
  const sections: TerminalLogSection[] = []
  let label = ''
  let current: string[] = []

  const flush = () => {
    if (!label) return
    const content = current.join('\n').replace(/^\n+|\n+$/g, '')
    if (content.trim()) sections.push({ label, content })
  }

  for (const line of lines) {
    const labelCandidate = matchTerminalHeader(line)
    if (labelCandidate) {
      flush()
      label = labelCandidate
      current = []
    } else if (label) {
      current.push(line)
    }
  }
  flush()
  return sections
}

/** 把各终端日志拼成统一文本格式；空日志会被跳过 */
export function formatTerminalLog(sections: TerminalLogSection[]): string {
  return (sections || [])
    .map((section) => {
      const label = (section.label || '').trim()
      let content = normalizeText(section.content)
      if (label) {
        const header = `===== ${label} =====`
        if (content.trimStart().startsWith(header)) {
          content = content.trimStart().slice(header.length)
        }
        content = content.replace(/^\n+|\n+$/g, '')
        return content ? `${header}\n${content}` : ''
      }
      return content.replace(/^\n+|\n+$/g, '')
    })
    .filter(Boolean)
    .join('\n\n')
}

/**
 * 把任意日志文本归一为终端分段：
 * 已有分段标题时按标题拆分，否则整体视为一段聚合日志（label 为空）。
 */
export function toTerminalSections(text?: string | null): TerminalLogSection[] {
  const raw = normalizeText(text).trim()
  if (!raw) return []
  const parsed = parseTerminalLog(raw)
  if (parsed.length > 0) return parsed
  return [{ label: '', content: raw }]
}

/** 终端日志总字符数 */
export function terminalLogChars(sections: TerminalLogSection[]): number {
  return (sections || []).reduce((total, item) => total + (item.content || '').length, 0)
}
