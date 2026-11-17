/**
 * 测试执行日志草稿箱。
 *
 * 为什么需要：下载结果 Excel 时，备注列的执行日志会被渲染成图片（或按工作区配置
 * 输出为文字）。图片形式的日志无法再复制 / 保存文本，清理会话或日志文件后也
 * 无法找回。本模块把每条用例的日志全文、执行状态与运行日志保存到浏览器
 * localStorage，重新上传用例文件后可一键恢复到对应用例。
 */
import { getCaseLog, getTerminalLogs } from '../api/axios'
import { useStore } from '../stores/useStore'
import type { LogEntry, TestCase } from '../types'
import { extractAiEvidence, extractLogText, parseRemark } from './remarkDisplay'
import {
  formatTerminalLog, terminalLogChars, toTerminalSections,
  type TerminalLogSection,
} from './terminalLogFormat'

const DRAFTS_KEY = 'automatedTest.executionLogDrafts'
const AUTO_SAVE_KEY = 'automatedTest.executionLogDraftAutoSave'
/** 自动草稿最多保留的条数，避免 localStorage 被占满 */
const AUTO_DRAFT_LIMIT = 10
/** 备注中执行日志段的分隔标记 */
export const LOG_SEPARATOR = '--- 执行日志 ---'

/** 草稿中单条用例的日志与执行结果 */
export interface ExecutionDraftCaseLog {
  case_key: string
  case_id: string
  description: string
  status: string
  actual_result: string
  judgment: string
  remarks: string
  /** 按终端分开的日志（与板端日志系统同一存储格式） */
  terminals: TerminalLogSection[]
  /** 纯日志文本（按终端分段后的统一格式，兼容旧草稿） */
  log_text: string
  log_file: string
  /** AI 判定时摘录的关键证据行 */
  ai_evidence: string[]
  /** 用户手动选择的高亮行内容快照（用于下载日志图片高亮） */
  manual_evidence: string[]
  /** 按行号选择的行标识（JSON [终端标签, 行号]） */
  manual_evidence_lines: string[]
  /** 手动高亮匹配方式 */
  manual_evidence_mode: 'line' | 'content'
}

/** 一次执行保存下来的日志草稿 */
export interface ExecutionDraft {
  id: string
  name: string
  /** 执行结束时自动保存的草稿 */
  auto: boolean
  createdAt: number
  updatedAt: number
  /** 保存时上传的用例文件名（仅用于展示） */
  workbookName: string
  case_count: number
  /** 执行期间控制台日志 */
  logs: LogEntry[]
  cases: ExecutionDraftCaseLog[]
  /** 用例日志指纹，用于避免重复自动保存 */
  signature: string
}

/** 用例唯一标识（与后端 case_key 规则一致） */
export function caseKeyOf(testCase: TestCase): string {
  return testCase.case_key
    || `${testCase.source_sheet}:${testCase.row_number}:${testCase.case_id}`
}

/** 把旧草稿（只有 log_text）补齐为按终端的结构化日志 */
function normalizeDraftCaseLog(item: ExecutionDraftCaseLog): ExecutionDraftCaseLog {
  const logText = (item.log_text || '').replace(/\r\n?/g, '\n').trim()
  const terminals = Array.isArray(item.terminals) && item.terminals.length
    ? item.terminals.filter((t) => t && (t.content || '').trim())
    : toTerminalSections(logText)
  return {
    ...item,
    terminals,
    // 统一按终端分段文本落盘，旧草稿的纯文本也在读取时完成迁移
    log_text: formatTerminalLog(terminals) || logText,
    ai_evidence: Array.isArray(item.ai_evidence) ? item.ai_evidence : [],
    manual_evidence: Array.isArray(item.manual_evidence) ? item.manual_evidence : [],
    manual_evidence_lines: Array.isArray(item.manual_evidence_lines)
      ? item.manual_evidence_lines
      : [],
    manual_evidence_mode: item.manual_evidence_mode === 'line' ? 'line' : 'content',
  }
}

/** 读取本机保存的所有日志草稿（按更新时间倒序） */
export function getAllExecutionDrafts(): ExecutionDraft[] {
  try {
    if (typeof localStorage === 'undefined') return []
    const raw = localStorage.getItem(DRAFTS_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return (parsed as ExecutionDraft[])
      .filter((d) => d && typeof d.id === 'string' && Array.isArray(d.cases))
      .map((d) => ({
        ...d,
        signature: typeof d.signature === 'string'
          ? d.signature
          : computeDraftSignature(d.cases.map(normalizeDraftCaseLog)),
        cases: d.cases.map(normalizeDraftCaseLog),
      }))
      .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))
  } catch {
    return []
  }
}

/** 落盘前去掉可由 terminals 还原的重复文本，避免 localStorage 体积翻倍 */
function toStoredDraft(draft: ExecutionDraft): ExecutionDraft {
  return {
    ...draft,
    cases: draft.cases.map((item) => ({
      ...item,
      log_text: item.terminals?.length ? '' : item.log_text,
    })),
  }
}

/** 保存草稿（存在则更新、不存在则插入）；返回是否写入成功 */
export function saveExecutionDraft(draft: ExecutionDraft): boolean {
  try {
    if (typeof localStorage === 'undefined') return false
    const now = Date.now()
    const drafts = getAllExecutionDrafts()
    const index = drafts.findIndex((d) => d.id === draft.id)
    if (index >= 0) {
      drafts[index] = { ...draft, updatedAt: now }
    } else {
      drafts.unshift({ ...draft, createdAt: draft.createdAt || now, updatedAt: now })
    }
    // 自动草稿只保留最近的若干条；手动草稿不自动清理
    const autos = drafts
      .filter((d) => d.auto)
      .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))
    const expired = new Set(autos.slice(AUTO_DRAFT_LIMIT).map((d) => d.id))
    const kept = drafts.filter((d) => !expired.has(d.id))
    try {
      localStorage.setItem(DRAFTS_KEY, JSON.stringify(kept.map(toStoredDraft)))
      return true
    } catch {
      // 存储空间不足：仅保留手动草稿与当前草稿后重试
      const reduced = kept.filter((d) => !d.auto || d.id === draft.id)
      localStorage.setItem(DRAFTS_KEY, JSON.stringify(reduced.map(toStoredDraft)))
      return reduced.some((d) => d.id === draft.id)
    }
  } catch {
    return false
  }
}

/** 删除草稿 */
export function deleteExecutionDraft(id: string): boolean {
  try {
    const drafts = getAllExecutionDrafts().filter((d) => d.id !== id)
    localStorage.setItem(DRAFTS_KEY, JSON.stringify(drafts.map(toStoredDraft)))
    notifyDraftsChanged()
    return true
  } catch {
    return false
  }
}

/** 重命名草稿 */
export function renameExecutionDraft(id: string, name: string): boolean {
  try {
    const trimmed = name.trim()
    if (!trimmed) return false
    const drafts = getAllExecutionDrafts().map((d) =>
      d.id === id ? { ...d, name: trimmed, updatedAt: Date.now() } : d,
    )
    localStorage.setItem(DRAFTS_KEY, JSON.stringify(drafts.map(toStoredDraft)))
    notifyDraftsChanged()
    return true
  } catch {
    return false
  }
}

/** 执行结束/停止时是否自动保存日志草稿（默认开启） */
export function isExecutionDraftAutoSaveEnabled(): boolean {
  try {
    if (typeof localStorage === 'undefined') return true
    const raw = localStorage.getItem(AUTO_SAVE_KEY)
    return raw === null ? true : raw === '1'
  } catch {
    return true
  }
}

export function setExecutionDraftAutoSaveEnabled(enabled: boolean): void {
  try {
    localStorage.setItem(AUTO_SAVE_KEY, enabled ? '1' : '0')
  } catch {
    // 忽略存储异常
  }
}

/** 通知页面刷新草稿数量（自动保存后同步徽标） */
function notifyDraftsChanged(): void {
  try {
    window.dispatchEvent(new Event('execution-drafts-changed'))
  } catch {
    // 非浏览器环境忽略
  }
}

/** 格式化草稿时间 */
export function formatDraftTime(ts: number): string {
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 备注中执行日志段之前的原有内容（保留 AI 判定 / 人工备注） */
export function stripLogSection(remark: string | undefined): string {
  const text = remark || ''
  const index = text.indexOf(LOG_SEPARATOR)
  return index < 0 ? text : text.slice(0, index)
}

/** 把日志文本合并进备注（保留原有的 AI 判定 / 人工备注段） */
export function mergeLogIntoRemark(remark: string | undefined, logText: string): string {
  const log = (logText || '').replace(/\r\n?/g, '\n').trim()
  if (!log) return remark || ''
  const base = stripLogSection(remark).trim()
  return base ? `${base}\n${LOG_SEPARATOR}\n${log}` : `${LOG_SEPARATOR}\n${log}`
}

/** 把按终端分段的日志合并进备注（与板端日志系统同一文本格式） */
export function mergeTerminalLogIntoRemark(
  remark: string | undefined,
  terminals: TerminalLogSection[],
): string {
  const log = formatTerminalLog(terminals)
  return log ? mergeLogIntoRemark(remark, log) : (remark || '')
}

function buildDraftCaseLog(record: TestCase, logText: string): ExecutionDraftCaseLog {
  const terminals = toTerminalSections(logText)
  const normalizedLog = formatTerminalLog(terminals)
  // WS 实时结果只带合并备注（AI 判定 + 日志），没有 judgment 字段时从备注中提取
  const parsedRemark = parseRemark(record.remarks)
  const aiText = record.judgment?.trim()
    || (parsedRemark.valid ? parsedRemark.aiText : '')
  const evidence = record.ai_evidence?.length
    ? [...record.ai_evidence]
    : extractAiEvidence(record.remarks)
  return {
    case_key: caseKeyOf(record),
    case_id: record.case_id || '',
    description: record.description || '',
    status: record.status || '',
    actual_result: record.actual_result || '',
    judgment: aiText,
    // 已提取出日志时不再重复保存完整备注，避免草稿体积翻倍
    remarks: normalizedLog ? '' : (record.remarks || ''),
    terminals,
    log_text: normalizedLog,
    log_file: record.log_file || '',
    ai_evidence: evidence,
    manual_evidence: [...(record.manual_evidence || [])],
    manual_evidence_lines: [...(record.manual_evidence_lines || [])],
    manual_evidence_mode: record.manual_evidence_mode === 'line' ? 'line' : 'content',
  }
}

/** 用例日志指纹（用于自动保存去重） */
export function computeDraftSignature(caseLogs: ExecutionDraftCaseLog[]): string {
  return caseLogs
    .map((c) => [
      c.case_key,
      c.case_id,
      c.status,
      terminalLogChars(c.terminals),
      formatTerminalLog(c.terminals).slice(0, 50),
      formatTerminalLog(c.terminals).slice(-50),
    ].join('|'))
    .join('\u0001')
}

/**
 * 收集用例日志：优先从备注解析；备注里没有但存在日志文件时，优先读取
 * 板端日志系统按终端落盘的日志（``/logs/terminals``），再回退聚合日志。
 * 日志文件可能已被清理，单条失败不影响其它用例。
 */
async function collectCaseLogs(cases: TestCase[]): Promise<ExecutionDraftCaseLog[]> {
  const items = cases.map((record) => ({
    record,
    item: buildDraftCaseLog(record, extractLogText(record.remarks)),
  }))
  const pending = items.filter(({ item }) => !item.log_text && item.log_file)

  let cursor = 0
  const worker = async () => {
    while (cursor < pending.length) {
      const { item } = pending[cursor]
      cursor += 1
      // 板端日志系统：每个终端独立落盘，优先读取并保持终端分段
      try {
        const res = await getTerminalLogs({
          path: item.log_file, case_key: item.case_key,
        })
        const panes = (res.data.terminals || []).filter(
          (pane) => pane.label && (pane.content || '').trim(),
        )
        if (panes.length > 0) {
          item.terminals = panes.map((pane) => ({
            label: pane.label,
            content: pane.content,
          }))
          item.log_text = formatTerminalLog(item.terminals)
          continue
        }
      } catch {
        // 旧记录没有终端级日志：继续回退聚合日志
      }
      try {
        const res = await getCaseLog({ path: item.log_file, case_key: item.case_key })
        const content = (res.data.content || '').replace(/\r\n?/g, '\n').trim()
        if (!content) continue
        // 聚合日志通常已带 ``===== 终端 =====`` 分段，拆回各终端；
        // 没有分段时保留为一段聚合日志
        item.terminals = toTerminalSections(content)
        item.log_text = formatTerminalLog(item.terminals)
      } catch {
        // 日志文件不存在 / 已清理时跳过
      }
    }
  }
  // 限制并发，避免一次性打出大量请求
  await Promise.all(
    Array.from({ length: Math.min(4, pending.length) }, () => worker()),
  )
  return items.map(({ item }) => item).filter((item) => item.log_text)
}

export interface CollectDraftOptions {
  cases: TestCase[]
  logs: LogEntry[]
  workbookName?: string
  name?: string
  auto?: boolean
}

/** 从当前用例与控制台日志生成草稿；没有任何用例日志时返回 null */
export async function collectExecutionDraft(
  options: CollectDraftOptions,
): Promise<ExecutionDraft | null> {
  const caseLogs = await collectCaseLogs(options.cases)
  if (caseLogs.length === 0) return null
  const now = Date.now()
  return {
    id: `draft_${now}_${Math.random().toString(16).slice(2, 8)}`,
    name: options.name?.trim()
      || `${options.auto ? '自动草稿' : '日志草稿'} - ${options.workbookName || '未命名'} - ${formatDraftTime(now)}`,
    auto: !!options.auto,
    createdAt: now,
    updatedAt: now,
    workbookName: options.workbookName || '',
    case_count: caseLogs.length,
    logs: options.logs.map((log) => ({ ...log })),
    cases: caseLogs,
    signature: computeDraftSignature(caseLogs),
  }
}

/**
 * 执行结束/停止时自动保存日志草稿（同步、不拉取日志文件）。
 * 指纹与已有草稿相同则跳过，避免同一次执行重复保存。
 */
export function autoSaveCurrentExecution(): ExecutionDraft | null {
  try {
    if (!isExecutionDraftAutoSaveEnabled()) return null
    const state = useStore.getState()
    const caseLogs = state.testCases
      .map((record) => buildDraftCaseLog(record, extractLogText(record.remarks)))
      .filter((item) => item.log_text)
    if (caseLogs.length === 0) return null

    const signature = computeDraftSignature(caseLogs)
    if (getAllExecutionDrafts().some((d) => d.signature === signature)) return null

    const now = Date.now()
    const draft: ExecutionDraft = {
      id: `auto_${now}_${Math.random().toString(16).slice(2, 8)}`,
      name: `自动草稿 - ${state.sourceFileName || '未命名'} - ${formatDraftTime(now)}`,
      auto: true,
      createdAt: now,
      updatedAt: now,
      workbookName: state.sourceFileName || '',
      case_count: caseLogs.length,
      logs: state.logs.map((log) => ({ ...log })),
      cases: caseLogs,
      signature,
    }
    if (!saveExecutionDraft(draft)) return null
    notifyDraftsChanged()
    return draft
  } catch {
    return null
  }
}

export interface SyncCaseEditOptions {
  /** 本次编辑是否修改了执行日志 */
  logChanged?: boolean
  /** 修改后的执行日志文本 */
  logText?: string
}

/**
 * 把单条用例的最新编辑同步到草稿箱中「当前工作簿最近一次保存」的草稿。
 *
 * 编辑实际结果 / 执行日志只会更新浏览器用例快照，草稿箱不会自动变化；
 * 这里在保存成功后把同一条用例的判定、证据与日志写回最近的草稿，
 * 避免恢复草稿时仍是编辑前的内容。没有对应草稿时不做任何事。
 */
export function syncCaseEditToDrafts(
  record: TestCase,
  workbookName = '',
  options: SyncCaseEditOptions = {},
): number {
  try {
    if (typeof localStorage === 'undefined') return 0
    const key = caseKeyOf(record)
    const hasCase = (draft: ExecutionDraft) =>
      draft.cases.some((item) => item.case_key === key)

    const drafts = getAllExecutionDrafts()
    let draft: ExecutionDraft | undefined
    if (workbookName) {
      draft = drafts.find((d) => d.workbookName === workbookName && hasCase(d))
        || drafts.find((d) => !d.workbookName && hasCase(d))
    } else {
      draft = drafts.find(hasCase)
    }
    if (!draft) return 0

    const index = draft.cases.findIndex((item) => item.case_key === key)
    if (index < 0) return 0
    const existing = draft.cases[index]

    // 日志未修改时沿用草稿里已有的终端分段，避免把草稿日志清空
    const preservedLog = existing.log_text
      || formatTerminalLog(
        existing.terminals?.length
          ? existing.terminals
          : toTerminalSections(existing.log_text),
      )

    let item: ExecutionDraftCaseLog
    if (options.logChanged) {
      // 日志可能被改成空文本，按编辑后的内容重建终端分段
      const editedLog = (options.logText || '')
        .replace(/\r\n?/g, '\n')
        .trim()
      item = buildDraftCaseLog(record, editedLog)
    } else if (preservedLog) {
      item = buildDraftCaseLog(record, preservedLog)
    } else {
      item = {
        ...existing,
        case_id: record.case_id || existing.case_id,
        description: record.description || existing.description,
        status: record.status || '',
        actual_result: record.actual_result || '',
        judgment: record.judgment?.trim() || '',
        ai_evidence: [...(record.ai_evidence || [])],
        manual_evidence: [...(record.manual_evidence || [])],
        manual_evidence_lines: [...(record.manual_evidence_lines || [])],
        manual_evidence_mode: record.manual_evidence_mode === 'line' ? 'line' : 'content',
        log_file: record.log_file || existing.log_file,
        terminals: [],
        log_text: '',
      }
    }

    draft.cases[index] = item
    draft.signature = computeDraftSignature(draft.cases)
    draft.case_count = draft.cases.length
    if (!saveExecutionDraft(draft)) return 0
    notifyDraftsChanged()
    return 1
  } catch {
    return 0
  }
}

/** 按 case_key 优先、case_id 唯一时回退的规则，在用例列表中查找草稿对应的用例 */
export function findCaseForDraftItem(
  cases: TestCase[],
  item: ExecutionDraftCaseLog,
): TestCase | undefined {
  if (item.case_key) {
    const byKey = cases.find((c) => caseKeyOf(c) === item.case_key)
    if (byKey) return byKey
  }
  if (!item.case_id) return undefined
  const matches = cases.filter((c) => c.case_id === item.case_id)
  if (matches.length === 1) return matches[0]
  if (matches.length > 1 && item.case_key) {
    // case_key 形如 `Sheet:行号:用例ID`，表名本身可能含冒号，取末尾两段
    const parts = item.case_key.split(':')
    const sheet = parts.slice(0, Math.max(0, parts.length - 2)).join(':')
    const target = matches.find((c) => c.source_sheet === sheet)
    if (target) return target
  }
  return undefined
}

/** 生成恢复到用例上的字段补丁（日志写入备注，同时带回执行状态与 AI 判定） */
export function buildRestorePatch(
  item: ExecutionDraftCaseLog,
  current: TestCase,
): Partial<TestCase> {
  const patch: Partial<TestCase> = {}
  const terminals = item.terminals?.length
    ? item.terminals
    : toTerminalSections(item.log_text)
  if (terminals.length > 0) {
    // 与板端日志系统一致：备注中的日志按 ``===== 终端 =====`` 分段存储
    patch.remarks = mergeTerminalLogIntoRemark(current.remarks, terminals)
  } else if (item.remarks) {
    patch.remarks = item.remarks
  }
  if (item.status) patch.status = item.status
  if (item.actual_result) patch.actual_result = item.actual_result
  if (item.judgment) patch.judgment = item.judgment
  if (item.ai_evidence.length > 0) patch.ai_evidence = [...item.ai_evidence]
  // 手动高亮行属于草稿状态；空数组表示恢复使用 AI 证据
  patch.manual_evidence = [...(item.manual_evidence || [])]
  patch.manual_evidence_lines = [...(item.manual_evidence_lines || [])]
  patch.manual_evidence_mode = item.manual_evidence_mode === 'line' ? 'line' : 'content'
  return patch
}

/** 把草稿内容拼成可导出的纯文本（按终端分开的用例日志 + 运行日志） */
export function buildDraftPlainText(draft: ExecutionDraft): string {
  const lines: string[] = [
    `执行日志草稿：${draft.name}`,
    `工作簿：${draft.workbookName || '-'}`,
    `保存时间：${formatDraftTime(draft.updatedAt)}`,
    `用例日志：${draft.cases.length} 条`,
    '',
  ]
  for (const item of draft.cases) {
    lines.push(`===== ${item.case_id}${item.status ? ` [${item.status}]` : ''} =====`)
    if (item.description) lines.push(`用例描述：${item.description}`)
    const terminals = item.terminals?.length
      ? item.terminals
      : toTerminalSections(item.log_text)
    if (terminals.length > 0) {
      for (const terminal of terminals) {
        lines.push(`----- ${terminal.label || '聚合日志'} -----`)
        lines.push(terminal.content || '（无日志文本）')
      }
    } else {
      lines.push('（无日志文本）')
    }
    lines.push('')
  }
  if (draft.logs.length > 0) {
    lines.push('===== 运行日志 =====')
    for (const log of draft.logs) {
      lines.push(`[${new Date(log.timestamp).toLocaleString()}] [${log.level}] ${log.message}`)
    }
  }
  return lines.join('\n')
}

/** 触发浏览器下载文本文件 */
export function downloadTextFile(filename: string, content: string): void {
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

/** 复制文本到剪贴板（HTTP 非安全上下文下退化为隐藏 textarea） */
export async function copyTextToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(textarea)
    return ok
  } catch {
    return false
  }
}
