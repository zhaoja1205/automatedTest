/**
 * 测试执行日志草稿箱。
 *
 * 为什么需要：下载结果 Excel 时，备注列的执行日志会被渲染成图片（或按工作区配置
 * 输出为文字）。图片形式的日志无法再复制 / 保存文本，清理会话或日志文件后也
 * 无法找回。本模块把每条用例的日志全文、执行状态与运行日志保存到浏览器
 * IndexedDB，重新上传用例文件后可一键恢复到对应用例。
 *
 * 日志全文体积很容易超过 localStorage 的 5MB 配额，因此以 IndexedDB 为主存储；
 * 首次加载时会把旧版本留在 localStorage 的草稿自动迁移过来。
 */
import { getCaseLog, getTerminalLogs } from '../api/axios'
import { useStore } from '../stores/useStore'
import type { LogEntry, TestCase } from '../types'
import { extractAiEvidence, extractLogText, parseRemark } from './remarkDisplay'
import {
  formatTerminalLog, terminalLogChars, toTerminalSections,
  type TerminalLogSection,
} from './terminalLogFormat'

/** 旧版草稿保存在 localStorage 的 key：仅用于首次迁移到 IndexedDB */
const LEGACY_DRAFTS_KEY = 'automatedTest.executionLogDrafts'
const AUTO_SAVE_KEY = 'automatedTest.executionLogDraftAutoSave'
/** 自动草稿最多保留的条数，控制草稿箱体积 */
const AUTO_DRAFT_LIMIT = 10
/** IndexedDB 数据库与草稿对象仓库名（独立数据库，避免和其它本地缓存混用） */
const DB_NAME = 'automatedTest.executionLogDrafts'
const DB_VERSION = 1
const DRAFT_STORE = 'drafts'
/** 开发阶段曾用过的数据库名 / 仓库名，首次加载时把其中的草稿迁移过来 */
const LEGACY_DB_NAME = 'automatedTest'
const LEGACY_DB_STORE = 'executionLogDrafts'
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

/** 内存缓存：IndexedDB 全量草稿的镜像，读取走同步接口 */
let draftCache: ExecutionDraft[] = []
let cacheHydrated = false
let hydrationPromise: Promise<void> | null = null
let dbPromise: Promise<IDBDatabase | null> | null = null

/** 首次打开数据库；不可用时返回 null，降级回 localStorage */
function openDraftDatabase(): Promise<IDBDatabase | null> {
  if (typeof indexedDB === 'undefined') return Promise.resolve(null)
  if (!dbPromise) {
    dbPromise = new Promise((resolve) => {
      let settled = false
      const finish = (db: IDBDatabase | null) => {
        if (settled) return
        settled = true
        resolve(db)
      }
      try {
        const request = indexedDB.open(DB_NAME, DB_VERSION)
        request.onupgradeneeded = () => {
          const db = request.result
          if (!db.objectStoreNames.contains(DRAFT_STORE)) {
            db.createObjectStore(DRAFT_STORE, { keyPath: 'id' })
          }
        }
        request.onsuccess = () => finish(request.result)
        request.onerror = () => finish(null)
        request.onblocked = () => finish(null)
      } catch {
        finish(null)
      }
    })
  }
  return dbPromise
}

/** 把 IndexedDB 记录 / 旧 localStorage 数据归一成完整草稿 */
function parseDraftList(parsed: unknown): ExecutionDraft[] {
  if (!Array.isArray(parsed)) return []
  return (parsed as ExecutionDraft[])
    .filter((d) => !!d && typeof d.id === 'string' && Array.isArray(d.cases))
    .map((d) => ({
      ...d,
      signature: typeof d.signature === 'string'
        ? d.signature
        : computeDraftSignature(d.cases.map(normalizeDraftCaseLog)),
      cases: d.cases.map(normalizeDraftCaseLog),
    }))
}

function sortDrafts(drafts: ExecutionDraft[]): ExecutionDraft[] {
  return drafts.slice().sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))
}

/** 合并两份草稿列表：同一 id 保留更新时间较新的版本 */
function mergeDraftLists(primary: ExecutionDraft[], extra: ExecutionDraft[]): ExecutionDraft[] {
  const byId = new Map(primary.map((d) => [d.id, d]))
  for (const draft of extra) {
    const existing = byId.get(draft.id)
    if (!existing || (draft.updatedAt || 0) > (existing.updatedAt || 0)) {
      byId.set(draft.id, draft)
    }
  }
  return sortDrafts([...byId.values()])
}

/** 读取旧版 localStorage 草稿（迁移用） */
function readLegacyDrafts(): ExecutionDraft[] {
  try {
    if (typeof localStorage === 'undefined') return []
    const raw = localStorage.getItem(LEGACY_DRAFTS_KEY)
    if (!raw) return []
    return parseDraftList(JSON.parse(raw))
  } catch {
    return []
  }
}

function removeLegacyDrafts(): void {
  try {
    if (typeof localStorage !== 'undefined') localStorage.removeItem(LEGACY_DRAFTS_KEY)
  } catch {
    // 忽略存储异常
  }
}

function readDraftRecords(db: IDBDatabase): Promise<unknown> {
  return new Promise((resolve) => {
    try {
      const tx = db.transaction(DRAFT_STORE, 'readonly')
      const request = tx.objectStore(DRAFT_STORE).getAll()
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => resolve([])
      tx.onabort = () => resolve([])
    } catch {
      resolve([])
    }
  })
}

/** 在一个事务内写入 / 删除草稿记录（IndexedDB 版） */
function writeDraftRecords(
  db: IDBDatabase,
  put: ExecutionDraft[],
  remove: string[] = [],
): Promise<boolean> {
  return new Promise((resolve) => {
    let settled = false
    const finish = (ok: boolean) => {
      if (settled) return
      settled = true
      resolve(ok)
    }
    try {
      const tx = db.transaction(DRAFT_STORE, 'readwrite')
      tx.oncomplete = () => finish(true)
      tx.onerror = () => finish(false)
      tx.onabort = () => finish(false)
      const store = tx.objectStore(DRAFT_STORE)
      for (const draft of put) store.put(toStoredDraft(draft))
      for (const id of remove) store.delete(id)
    } catch {
      finish(false)
    }
  })
}

/** 读取开发阶段旧数据库中的草稿；数据库不存在时返回空列表 */
function readLegacyDbDrafts(): Promise<ExecutionDraft[]> {
  return new Promise((resolve) => {
    if (typeof indexedDB === 'undefined') {
      resolve([])
      return
    }
    // 旧库不存在时 open 会新建一个空库，读完顺手删掉，避免留下垃圾
    let createdEmptyDb = false
    try {
      const request = indexedDB.open(LEGACY_DB_NAME, 1)
      request.onupgradeneeded = () => {
        createdEmptyDb = true
        const db = request.result
        if (!db.objectStoreNames.contains(LEGACY_DB_STORE)) {
          db.createObjectStore(LEGACY_DB_STORE, { keyPath: 'id' })
        }
      }
      request.onerror = () => resolve([])
      request.onblocked = () => resolve([])
      request.onsuccess = () => {
        const db = request.result
        const closeWith = (value: ExecutionDraft[]) => {
          try { db.close() } catch { /* 忽略关闭异常 */ }
          if (createdEmptyDb) {
            try { indexedDB.deleteDatabase(LEGACY_DB_NAME) } catch { /* 忽略清理异常 */ }
          }
          resolve(value)
        }
        if (!db.objectStoreNames.contains(LEGACY_DB_STORE)) {
          closeWith([])
          return
        }
        try {
          const tx = db.transaction(LEGACY_DB_STORE, 'readonly')
          const records = tx.objectStore(LEGACY_DB_STORE).getAll()
          records.onsuccess = () => closeWith(parseDraftList(records.result))
          records.onerror = () => closeWith([])
          tx.onabort = () => closeWith([])
        } catch {
          closeWith([])
        }
      }
    } catch {
      resolve([])
    }
  })
}

/** 迁移成功后删除旧数据库（尽力而为，被其它标签页占用时下次再试） */
function deleteLegacyDbIfMigrated(): void {
  if (typeof indexedDB === 'undefined') return
  try { indexedDB.deleteDatabase(LEGACY_DB_NAME) } catch { /* 忽略清理异常 */ }
}

/** 没有 IndexedDB 时的降级：仍把整表写入 localStorage */
function writeLegacyDrafts(drafts: ExecutionDraft[]): boolean {
  try {
    if (typeof localStorage === 'undefined') return false
    localStorage.setItem(LEGACY_DRAFTS_KEY, JSON.stringify(drafts.map(toStoredDraft)))
    return true
  } catch {
    return false
  }
}

/** 持久化一次草稿变更；IndexedDB 只改变更的记录，失败时返回 false */
async function persistDraftChange(
  mutation: { put?: ExecutionDraft[]; remove?: string[] },
  fallbackList: ExecutionDraft[],
): Promise<boolean> {
  const db = await openDraftDatabase()
  if (!db) return writeLegacyDrafts(fallbackList)
  return writeDraftRecords(db, mutation.put || [], mutation.remove || [])
}

/** 首次加载：读取 IndexedDB，并迁移旧数据库 / 旧 localStorage 中的草稿 */
async function hydrateDraftCache(): Promise<void> {
  try {
    const db = await openDraftDatabase()
    if (db) {
      let stored = parseDraftList(await readDraftRecords(db))
      // 开发阶段旧数据库（automatedTest / executionLogDrafts）中的草稿
      const legacyDbDrafts = await readLegacyDbDrafts()
      const legacyLocalDrafts = readLegacyDrafts()
      const legacyById = new Map<string, ExecutionDraft>()
      for (const draft of [...legacyDbDrafts, ...legacyLocalDrafts]) {
        const existing = legacyById.get(draft.id)
        if (!existing || (draft.updatedAt || 0) > (existing.updatedAt || 0)) {
          legacyById.set(draft.id, draft)
        }
      }
      const legacy = [...legacyById.values()]
      if (legacy.length > 0) {
        const storedById = new Map(stored.map((d) => [d.id, d]))
        const imported = legacy.filter((d) => {
          const existing = storedById.get(d.id)
          return !existing || (d.updatedAt || 0) > (existing.updatedAt || 0)
        })
        if (imported.length === 0) {
          // 当前库已包含这些草稿：可以直接清理旧数据
          removeLegacyDrafts()
          deleteLegacyDbIfMigrated()
        } else if (await writeDraftRecords(db, imported)) {
          stored = mergeDraftLists(stored, imported)
          removeLegacyDrafts()
          deleteLegacyDbIfMigrated()
        } else {
          // 迁移失败时先放进内存，避免草稿在界面上消失
          stored = mergeDraftLists(stored, imported)
        }
      }
      draftCache = sortDrafts(stored)
    } else {
      // 没有 IndexedDB：直接使用旧 localStorage 草稿（并保留 key 作为降级存储）
      draftCache = sortDrafts(readLegacyDrafts())
    }
  } catch {
    draftCache = sortDrafts(readLegacyDrafts())
  } finally {
    cacheHydrated = true
    // 缓存就绪后通知页面刷新（Dashboard 徽标 / 草稿箱列表）
    notifyDraftsChanged()
  }
}

/** 等缓存从 IndexedDB 加载完成（写入前必须保证基线一致） */
async function ensureDraftsReady(): Promise<void> {
  if (cacheHydrated) return
  if (!hydrationPromise) {
    hydrationPromise = hydrateDraftCache().finally(() => {
      hydrationPromise = null
    })
  }
  await hydrationPromise
}

/** 串行执行草稿写操作，避免并发保存时读到的缓存互相覆盖 */
let draftMutationQueue: Promise<unknown> = Promise.resolve()

function enqueueDraftMutation<T>(task: () => Promise<T>): Promise<T> {
  const run = draftMutationQueue.then(task, task)
  draftMutationQueue = run.then(() => undefined, () => undefined)
  return run
}

// 页面加载即预热缓存，避免首次打开草稿箱时列表为空
if (typeof indexedDB !== 'undefined' || typeof localStorage !== 'undefined') {
  void ensureDraftsReady()
}

/**
 * 读取本机保存的所有日志草稿（按更新时间倒序）。
 *
 * 返回的是内存缓存的快照；缓存由 IndexedDB 异步预热，页面通过
 * ``execution-drafts-changed`` 事件能拿到就绪后的完整列表。
 */
export function getAllExecutionDrafts(): ExecutionDraft[] {
  return draftCache.map((d) => ({ ...d }))
}

/** 落盘前去掉可由 terminals 还原的重复文本，避免存储体积翻倍 */
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
export function saveExecutionDraft(draft: ExecutionDraft): Promise<boolean> {
  return enqueueDraftMutation(() => saveDraftInternal(draft))
}

async function saveDraftInternal(draft: ExecutionDraft): Promise<boolean> {
  try {
    await ensureDraftsReady()
    const now = Date.now()
    const existing = draftCache.find((d) => d.id === draft.id)
    const saved: ExecutionDraft = {
      ...draft,
      createdAt: existing?.createdAt ?? draft.createdAt ?? now,
      updatedAt: now,
    }
    let next = sortDrafts([saved, ...draftCache.filter((d) => d.id !== draft.id)])
    // 自动草稿只保留最近的若干条；手动草稿不自动清理
    const expired = next
      .filter((d) => d.auto)
      .slice(AUTO_DRAFT_LIMIT)
      .map((d) => d.id)
    next = next.filter((d) => !expired.includes(d.id))
    const ok = await persistDraftChange({ put: [saved], remove: expired }, next)
    if (!ok) return false
    draftCache = next
    notifyDraftsChanged()
    return true
  } catch {
    return false
  }
}

/** 删除草稿 */
export function deleteExecutionDraft(id: string): Promise<boolean> {
  return enqueueDraftMutation(() => deleteDraftInternal(id))
}

async function deleteDraftInternal(id: string): Promise<boolean> {
  try {
    await ensureDraftsReady()
    const next = draftCache.filter((d) => d.id !== id)
    const ok = await persistDraftChange({ remove: [id] }, next)
    if (!ok) return false
    draftCache = next
    notifyDraftsChanged()
    return true
  } catch {
    return false
  }
}

/** 重命名草稿 */
export function renameExecutionDraft(id: string, name: string): Promise<boolean> {
  return enqueueDraftMutation(() => renameDraftInternal(id, name))
}

async function renameDraftInternal(id: string, name: string): Promise<boolean> {
  try {
    const trimmed = name.trim()
    if (!trimmed) return false
    await ensureDraftsReady()
    const updated = draftCache.map((d) =>
      d.id === id ? { ...d, name: trimmed, updatedAt: Date.now() } : d,
    )
    const target = updated.find((d) => d.id === id)
    if (!target) return false
    const next = sortDrafts(updated)
    const ok = await persistDraftChange({ put: [target] }, next)
    if (!ok) return false
    draftCache = next
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
 * 执行结束/停止时自动保存日志草稿（不拉取日志文件）。
 * 指纹与已有草稿相同则跳过，避免同一次执行重复保存。
 */
export function autoSaveCurrentExecution(): Promise<ExecutionDraft | null> {
  return enqueueDraftMutation(() => autoSaveCurrentExecutionInternal())
}

async function autoSaveCurrentExecutionInternal(): Promise<ExecutionDraft | null> {
  try {
    if (!isExecutionDraftAutoSaveEnabled()) return null
    await ensureDraftsReady()
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
    if (!(await saveDraftInternal(draft))) return null
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
): Promise<number> {
  return enqueueDraftMutation(() => syncCaseEditToDraftsInternal(record, workbookName, options))
}

async function syncCaseEditToDraftsInternal(
  record: TestCase,
  workbookName: string,
  options: SyncCaseEditOptions,
): Promise<number> {
  try {
    await ensureDraftsReady()
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

    // 用新数组替换单条用例，避免直接改动缓存里的原草稿
    const cases = draft.cases.map((caseLog, i) => (i === index ? item : caseLog))
    const updatedDraft: ExecutionDraft = {
      ...draft,
      cases,
      signature: computeDraftSignature(cases),
      case_count: cases.length,
    }
    if (!(await saveDraftInternal(updatedDraft))) return 0
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

/** 解析导出文本中的「保存时间」 */
function parseDraftTimestamp(value: string): number {
  const match = /(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})/.exec(value)
  if (!match) return 0
  const date = new Date(
    Number(match[1]), Number(match[2]) - 1, Number(match[3]),
    Number(match[4]), Number(match[5]),
  )
  return Number.isNaN(date.getTime()) ? 0 : date.getTime()
}

/**
 * 解析草稿箱导出的纯文本，还原成可以再次保存 / 恢复的草稿。
 *
 * 导出格式见 ``buildDraftPlainText``：头部是草稿名、工作簿与保存时间，
 * 每条用例以 ``===== 用例ID [状态] =====`` 开始，日志按 ``----- 终端 -----``
 * 分段，最后是运行日志。用例的其它字段（实际结果 / AI 判定等）不在导出文本中，
 * 恢复时按空值处理；用例按 case_id 匹配。
 */
export function parseDraftPlainText(text: string, fallbackName = ''): ExecutionDraft | null {
  const normalized = (text || '').replace(/^﻿/, '').replace(/\r\n?/g, '\n')
  if (!normalized.trim()) return null

  let name = ''
  let workbookName = ''
  let savedAt = 0
  let inRunLogs = false
  const cases: ExecutionDraftCaseLog[] = []
  const logs: LogEntry[] = []

  interface ParsedCase {
    case_id: string
    status: string
    description: string
    terminals: TerminalLogSection[]
  }
  let current: ParsedCase | null = null
  let currentTerminal: TerminalLogSection | null = null

  const flushCase = () => {
    if (!current) return
    const terminals = current.terminals
      .map((terminal) => ({
        label: terminal.label,
        content: terminal.content.replace(/\n+$/, ''),
      }))
      .filter((terminal) => terminal.content.trim())
    if (terminals.length > 0) {
      cases.push({
        case_key: '',
        case_id: current.case_id,
        description: current.description,
        status: current.status,
        actual_result: '',
        judgment: '',
        remarks: '',
        terminals,
        log_text: formatTerminalLog(terminals),
        log_file: '',
        ai_evidence: [],
        manual_evidence: [],
        manual_evidence_lines: [],
        manual_evidence_mode: 'content',
      })
    }
    current = null
    currentTerminal = null
  }

  for (const line of normalized.split('\n')) {
    const trimmed = line.trimEnd()

    // 运行日志段（位于所有用例之后）
    if (/^=====\s+运行日志\s+=====$/.test(trimmed)) {
      flushCase()
      inRunLogs = true
      continue
    }
    if (inRunLogs) {
      const match = /^\[(.+?)\]\s+\[([^\]]+)\]\s+(.*)$/.exec(trimmed)
      if (match) {
        const level = match[2] === 'warning' || match[2] === 'error' ? match[2] : 'info'
        const timestamp = Date.parse(match[1])
        logs.push({
          level,
          message: match[3],
          timestamp: Number.isNaN(timestamp) ? 0 : timestamp,
        })
      } else if (trimmed.trim()) {
        logs.push({ level: 'info', message: trimmed, timestamp: 0 })
      }
      continue
    }

    // 用例头：===== 用例ID [状态] =====
    if (trimmed.startsWith('===== ') && trimmed.endsWith(' =====')) {
      flushCase()
      const inner = trimmed.slice(6, trimmed.length - 6).trim()
      let caseId = inner
      let status = ''
      const statusIndex = inner.lastIndexOf(' [')
      if (statusIndex > 0 && inner.endsWith(']')) {
        caseId = inner.slice(0, statusIndex).trim()
        status = inner.slice(statusIndex + 2, -1).trim()
      }
      current = { case_id: caseId, status, description: '', terminals: [] }
      continue
    }

    if (!current) {
      if (trimmed.startsWith('执行日志草稿：')) {
        name = trimmed.slice('执行日志草稿：'.length).trim()
      } else if (trimmed.startsWith('工作簿：')) {
        const value = trimmed.slice('工作簿：'.length).trim()
        workbookName = value === '-' ? '' : value
      } else if (trimmed.startsWith('保存时间：')) {
        savedAt = parseDraftTimestamp(trimmed.slice('保存时间：'.length))
      }
      // 「用例日志：N 条」及其它头部行无需解析
      continue
    }

    // 终端头：----- 终端名 -----
    if (trimmed.startsWith('----- ') && trimmed.endsWith(' -----')) {
      const label = trimmed.slice(6, trimmed.length - 6).trim() || '聚合日志'
      currentTerminal = { label, content: '' }
      current.terminals.push(currentTerminal)
      continue
    }

    if (!currentTerminal) {
      if (trimmed.startsWith('用例描述：')) {
        current.description = trimmed.slice('用例描述：'.length).trim()
      }
      // 「（无日志文本）」和空行忽略
      continue
    }

    // 终端正文：保留原始换行，导出时的尾部空行在 flushCase 中裁掉
    currentTerminal.content += (currentTerminal.content ? '\n' : '') + line
  }
  flushCase()

  if (cases.length === 0) return null

  const now = Date.now()
  const updatedAt = savedAt || now
  return {
    id: `import_${now}_${Math.random().toString(16).slice(2, 8)}`,
    name: name
      || `导入草稿 - ${fallbackName || '未命名'} - ${formatDraftTime(now)}`,
    auto: false,
    createdAt: updatedAt,
    updatedAt,
    workbookName,
    case_count: cases.length,
    // 运行日志的时间戳是本地化文本，解析失败时用草稿保存时间兜底
    logs: logs.map((log) => log.timestamp ? log : { ...log, timestamp: updatedAt }),
    cases,
    signature: computeDraftSignature(cases),
  }
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
