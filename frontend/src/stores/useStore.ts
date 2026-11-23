import { create } from 'zustand'
import { sessionId } from '../api/axios'
import type {
  BugListItem,
  CaseStartInfo,
  ConfirmRequest,
  DownloadProgress,
  ExecutionProgress,
  LogEntry,
  SSHConfig,
  SSHStatus,
  TestCase,
  WorkspaceConfig,
} from '../types'

export const optionalCaseColumnKeys = [
  'case_id', 'description', 'test_type', 'priority', 'status',
  'prerequisites', 'test_steps', 'expected_result', 'actual_result',
]

/** 表格显示列配置的 localStorage key */
const VISIBLE_COLUMNS_STORAGE_KEY = 'automatedTest.visibleCaseColumnKeys'

/** 从浏览器读取显示列配置，无效或不存在时回退为全部显示 */
const loadVisibleColumnKeys = (): string[] => {
  const all = [...optionalCaseColumnKeys]
  try {
    if (typeof localStorage === 'undefined') return all
    const raw = localStorage.getItem(VISIBLE_COLUMNS_STORAGE_KEY)
    if (!raw) return all
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return all
    // 过滤掉已删除/非法的列名，避免旧配置导致表格列异常
    return parsed.filter(
      (key): key is string => typeof key === 'string' && optionalCaseColumnKeys.includes(key),
    )
  } catch {
    return all
  }
}

/** 保存显示列配置到浏览器（失败不影响页面使用） */
const saveVisibleColumnKeys = (keys: string[]) => {
  try {
    if (typeof localStorage === 'undefined') return
    localStorage.setItem(VISIBLE_COLUMNS_STORAGE_KEY, JSON.stringify(keys))
  } catch {
    // 隐私模式/存储已满等场景下静默降级
  }
}

/**
 * 用例快照按 session 分开存储，避免多个标签页互相覆盖。
 * 使用 sessionStorage：刷新页面不丢失，关闭标签页即清除，
 * 测试用例内容不落到 localStorage。
 */
const CASES_STORAGE_KEY = `automatedTest.cases.${sessionId}`

interface CasesSnapshot {
  testCases: TestCase[]
  sheets: string[]
  currentSheet: string
  bugSheet: string
  bugList: BugListItem[]
  /** 当前上传的用例文件名（用于日志草稿箱展示） */
  sourceFileName?: string
}

/** 从浏览器读取当前标签页的用例快照 */
const loadCasesSnapshot = (): CasesSnapshot | null => {
  try {
    if (typeof sessionStorage === 'undefined') return null
    const raw = sessionStorage.getItem(CASES_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<CasesSnapshot>
    if (!Array.isArray(parsed.testCases)) return null
    return {
      testCases: parsed.testCases,
      sheets: Array.isArray(parsed.sheets) ? parsed.sheets : [],
      currentSheet: typeof parsed.currentSheet === 'string' ? parsed.currentSheet : '',
      bugSheet: typeof parsed.bugSheet === 'string' ? parsed.bugSheet : '',
      bugList: Array.isArray(parsed.bugList) ? parsed.bugList : [],
      sourceFileName: typeof parsed.sourceFileName === 'string' ? parsed.sourceFileName : '',
    }
  } catch {
    return null
  }
}

/** 保存用例快照到浏览器（超出配额时静默放弃，不影响页面使用） */
const saveCasesSnapshot = (snapshot: CasesSnapshot) => {
  try {
    if (typeof sessionStorage === 'undefined') return
    const raw = JSON.stringify(snapshot)
    // sessionStorage 配额通常约 5MB（UTF-16 计约 2.5M 字符），留出余量
    if (raw.length > 2_000_000) {
      console.warn('[useStore] 用例数据过大，跳过本地持久化')
      return
    }
    sessionStorage.setItem(CASES_STORAGE_KEY, raw)
  } catch {
    // 隐私模式/存储已满等场景下静默降级
  }
}

const resolveCaseKey = (testCase: TestCase) =>
  testCase.case_key || `${testCase.source_sheet}:${testCase.row_number}:${testCase.case_id}`

/** AI 步骤解析进度 */
export interface AIParseProgress {
  current: number
  total: number
  status: 'parsing' | 'done' | 'interrupted'
  message: string
  success: number
  failed: number
}

// =========================================================================
// 多终端实时板端日志
// =========================================================================

/** 单个终端实时缓冲的最大字符数（超出只保留尾部，避免内存无限增长） */
const BOARD_TERMINAL_MAX_CHARS = 200_000

/** 当前/最近一个用例的多终端实时日志 */
export interface BoardTerminalState {
  caseId: string
  caseKey: string
  /** 终端标签展示顺序 */
  order: string[]
  /** 终端标签 → 已累计的板端输出文本 */
  texts: Record<string, string>
  updatedAt: number
}

export const createEmptyBoardTerminal = (): BoardTerminalState => ({
  caseId: '',
  caseKey: '',
  order: [],
  texts: {},
  updatedAt: 0,
})

/** 把输出追加到某个终端，返回新的状态（超出上限时保留尾部） */
const appendTerminalText = (
  base: BoardTerminalState,
  terminal: string,
  chunk: string,
  patch: { caseId?: string; caseKey?: string },
): BoardTerminalState => {
  const order = base.order.includes(terminal)
    ? base.order
    : [...base.order, terminal]
  let text = (base.texts[terminal] || '') + chunk
  if (text.length > BOARD_TERMINAL_MAX_CHARS) {
    text = text.slice(-BOARD_TERMINAL_MAX_CHARS)
  }
  return {
    caseId: base.caseId || patch.caseId || '',
    caseKey: base.caseKey || patch.caseKey || '',
    order,
    texts: { ...base.texts, [terminal]: text },
    updatedAt: Date.now(),
  }
}

interface AppState {
  testCases: TestCase[]
  /** 当前上传的用例文件名 */
  sourceFileName: string
  visibleCaseColumnKeys: string[]
  sheets: string[]
  currentSheet: string
  /** Excel 中的 BugList统计 页签名称（为空表示工作簿没有该页） */
  bugSheet: string
  /** BugList统计 页数据，与上传的 Excel 同步 */
  bugList: BugListItem[]
  logs: LogEntry[]
  progress: ExecutionProgress | null
  isRunning: boolean
  isConnected: boolean
  confirmRequest: ConfirmRequest | null
  sshConfig: SSHConfig | null
  sshStatus: SSHStatus | null
  workspace: WorkspaceConfig | null
  // AI 步骤解析
  aiParseProgress: AIParseProgress | null
  aiParsedCases: Set<string>
  /** 下载结果的导出进度（token 区分本次下载） */
  downloadProgress: DownloadProgress | null
  // 多终端实时板端日志
  boardTerminal: BoardTerminalState
  currentCaseInfo: CaseStartInfo | null

  setCurrentCaseInfo: (info: CaseStartInfo | null) => void
  /** 新用例开始：重置各终端面板（保留执行器给出的终端列表） */
  startBoardTerminal: (payload: {
    caseId: string
    caseKey: string
    terminals: string[]
  }) => void
  /** 追加某个终端的实时输出（WS terminal_log） */
  appendTerminalLog: (payload: {
    caseId: string
    caseKey: string
    terminal: string
    chunk: string
  }) => void
  /** 用服务端快照初始化（页面中途打开/断线重连） */
  loadBoardTerminalSnapshot: (payload: {
    caseId: string
    caseKey: string
    terminals: Array<{ label: string; text: string }>
  }) => void
  clearBoardTerminal: () => void

  setTestCases: (cases: TestCase[]) => void
  setSourceFileName: (name: string) => void
  setVisibleCaseColumnKeys: (keys: string[]) => void
  setSheets: (sheets: string[]) => void
  setCurrentSheet: (sheet: string) => void
  setBugList: (bugSheet: string, bugList: BugListItem[]) => void
  addLog: (log: LogEntry) => void
  addLogs: (logs: LogEntry[]) => void
  clearLogs: () => void
  setProgress: (p: ExecutionProgress | null) => void
  setIsRunning: (v: boolean) => void
  setIsConnected: (v: boolean) => void
  setConfirmRequest: (c: ConfirmRequest | null) => void
  setSSHConfig: (c: SSHConfig) => void
  setSSHStatus: (s: SSHStatus) => void
  setWorkspace: (w: WorkspaceConfig) => void
  updateCaseStatus: (caseKey: string, status: string, actualResult?: string, logFile?: string, remarks?: string) => void
  /** 更新用例的任意字段（例如就地编辑 test_steps） */
  updateCaseFields: (caseKey: string, patch: Partial<TestCase>) => void
  /** 批量更新多条用例（按 case_key 索引），用于恢复日志草稿 */
  applyCasePatches: (patches: Record<string, Partial<TestCase>>) => void
  updateCaseSelected: (caseKey: string, selected: boolean) => void
  /**
   * 批量更新多条用例的选中状态。
   *
   * 逐条调用 updateCaseSelected 会触发 N 次全量渲染 + N 次 sessionStorage 序列化，
   * 200 条用例全选时明显卡顿；这里合并为一次 set 和一次持久化。
   */
  updateCasesSelected: (caseKeys: string[], selected: boolean) => void
  setAllCaseSelected: (selected: boolean) => void
  resetSelectedCases: () => void
  // AI 步骤解析
  setAIParseProgress: (p: AIParseProgress | null) => void
  addAIParsedCase: (caseKey: string) => void
  removeAIParsedCase: (caseKey: string) => void
  clearAIParsedCases: () => void
  setDownloadProgress: (p: DownloadProgress | null) => void
}

const casesSnapshot = loadCasesSnapshot()

/** 将当前用例/表页状态写回浏览器（仅在用例相关状态变更时调用） */
const persistCases = () => {
  const state = useStore.getState()
  saveCasesSnapshot({
    testCases: state.testCases,
    sheets: state.sheets,
    currentSheet: state.currentSheet,
    bugSheet: state.bugSheet,
    bugList: state.bugList,
    sourceFileName: state.sourceFileName,
  })
}

export const useStore = create<AppState>((set) => ({
  testCases: casesSnapshot?.testCases ?? [],
  sourceFileName: casesSnapshot?.sourceFileName ?? '',
  visibleCaseColumnKeys: loadVisibleColumnKeys(),
  sheets: casesSnapshot?.sheets ?? [],
  currentSheet: casesSnapshot?.currentSheet ?? '',
  bugSheet: casesSnapshot?.bugSheet ?? '',
  bugList: casesSnapshot?.bugList ?? [],
  logs: [],
  progress: null,
  isRunning: false,
  isConnected: false,
  confirmRequest: null,
  sshConfig: null,
  sshStatus: null,
  workspace: null,
  aiParseProgress: null,
  aiParsedCases: new Set<string>(),
  downloadProgress: null,
  boardTerminal: createEmptyBoardTerminal(),
  currentCaseInfo: null,

  setCurrentCaseInfo: (info) => set({ currentCaseInfo: info }),
  startBoardTerminal: ({ caseId, caseKey, terminals }) => {
    const order = [...(terminals || [])]
    set({
      boardTerminal: {
        caseId,
        caseKey,
        order,
        texts: Object.fromEntries(order.map((label) => [label, ''])),
        updatedAt: Date.now(),
      },
    })
  },
  appendTerminalLog: ({ caseId, caseKey, terminal, chunk }) => {
    set((state) => {
      const base = state.boardTerminal
      const sameCase =
        !base.caseKey || base.caseKey === caseKey || (!caseKey && base.caseId === caseId)
      const next = sameCase
        ? base
        : {
            caseId,
            caseKey,
            order: [],
            texts: {},
            updatedAt: Date.now(),
          }
      return { boardTerminal: appendTerminalText(next, terminal, chunk, { caseId, caseKey }) }
    })
  },
  loadBoardTerminalSnapshot: ({ caseId, caseKey, terminals }) => {
    set((state) => {
      // 已有同一用例且已有内容时，不覆盖（避免快照晚到冲掉实时数据）
      const base = state.boardTerminal
      const hasContent =
        base.caseKey === caseKey && Object.values(base.texts).some((t) => t.length > 0)
      if (hasContent) return {}
      const order = terminals.map((t) => t.label)
      return {
        boardTerminal: {
          caseId,
          caseKey,
          order,
          texts: Object.fromEntries(terminals.map((t) => [t.label, t.text || ''])),
          updatedAt: Date.now(),
        },
      }
    })
  },
  clearBoardTerminal: () => set({ boardTerminal: createEmptyBoardTerminal() }),

  setTestCases: (cases) => {
    set({
      testCases: cases.map((c) => ({
        ...c,
        case_key: resolveCaseKey(c),
      })),
    })
    persistCases()
  },
  setSourceFileName: (name) => {
    set({ sourceFileName: name })
    persistCases()
  },
  setVisibleCaseColumnKeys: (keys) => {
    set({ visibleCaseColumnKeys: keys })
    saveVisibleColumnKeys(keys)
  },
  setSheets: (sheets) => {
    set({ sheets })
    persistCases()
  },
  setCurrentSheet: (sheet) => {
    set({ currentSheet: sheet })
    persistCases()
  },
  setBugList: (bugSheet, bugList) => {
    set({ bugSheet, bugList })
    persistCases()
  },
  addLog: (log) => set((state) => ({ logs: [...state.logs, log] })),
  addLogs: (logs) => set((state) => ({ logs: [...state.logs, ...logs] })),
  clearLogs: () => set({ logs: [] }),
  setProgress: (p) => set({ progress: p }),
  setIsRunning: (v) => set({ isRunning: v }),
  setIsConnected: (v) => set({ isConnected: v }),
  setConfirmRequest: (c) => set({ confirmRequest: c }),
  setSSHConfig: (c) => set({ sshConfig: c }),
  setSSHStatus: (s) => set({ sshStatus: s }),
  setWorkspace: (w) => set({ workspace: w }),
  updateCaseStatus: (caseKey, status, actualResult?, logFile?, remarks?) => {
    set((state) => ({
      testCases: state.testCases.map((c) =>
        resolveCaseKey(c) === caseKey
          ? {
              ...c,
              status,
              ...(actualResult !== undefined ? { actual_result: actualResult } : {}),
              ...(logFile ? { log_file: logFile } : {}),
              ...(remarks !== undefined ? { remarks } : {}),
            }
          : c
      ),
    }))
    persistCases()
  },
  updateCaseFields: (caseKey, patch) => {
    set((state) => ({
      testCases: state.testCases.map((c) =>
        resolveCaseKey(c) === caseKey ? { ...c, ...patch } : c
      ),
    }))
    persistCases()
  },
  applyCasePatches: (patches) => {
    set((state) => ({
      testCases: state.testCases.map((c) => {
        const patch = patches[resolveCaseKey(c)]
        return patch ? { ...c, ...patch } : c
      }),
    }))
    persistCases()
  },
  updateCaseSelected: (caseKey, selected) => {
    set((state) => ({
      testCases: state.testCases.map((c) =>
        resolveCaseKey(c) === caseKey ? { ...c, selected } : c
      ),
    }))
    persistCases()
  },
  updateCasesSelected: (caseKeys, selected) => {
    if (caseKeys.length === 0) return
    const keySet = new Set(caseKeys)
    set((state) => ({
      testCases: state.testCases.map((c) =>
        keySet.has(resolveCaseKey(c)) ? { ...c, selected } : c
      ),
    }))
    persistCases()
  },
  setAllCaseSelected: (selected) => {
    set((state) => ({
      testCases: state.testCases.map((c) => ({ ...c, selected })),
    }))
    persistCases()
  },
  resetSelectedCases: () => {
    set((state) => ({
      testCases: state.testCases.map((c) =>
        c.selected
          ? {
              ...c,
              status: 'NT',
              actual_result: '',
              log_file: '',
              remarks: '',
              // 「BUG」列的 AI 判定与证据也要清空：日志草稿恢复的旧结论
              // 不清掉的话，新一轮执行后实际结果仍显示上一次的 Pass / 置信度
              judgment: '',
              ai_judged: false,
              ai_status: '',
              ai_confidence: 0,
              ai_reason: '',
              ai_evidence: [],
              bug_description: '',
              bug_severity: '',
            }
          : c
      ),
    }))
    persistCases()
  },
  // AI 步骤解析
  setAIParseProgress: (p) => set({ aiParseProgress: p }),
  addAIParsedCase: (caseKey) =>
    set((state) => {
      const next = new Set(state.aiParsedCases)
      next.add(caseKey)
      return { aiParsedCases: next }
    }),
  removeAIParsedCase: (caseKey) =>
    set((state) => {
      if (!state.aiParsedCases.has(caseKey)) return state
      const next = new Set(state.aiParsedCases)
      next.delete(caseKey)
      return { aiParsedCases: next }
    }),
  clearAIParsedCases: () => set({ aiParsedCases: new Set<string>() }),
  setDownloadProgress: (p) => set({ downloadProgress: p }),
}))