import { create } from 'zustand'
import { sessionId } from '../api/axios'
import type {
  ConfirmRequest,
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
  'remarks',
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

/** 用例快照按 session 分开存储，避免多个标签页互相覆盖 */
const CASES_STORAGE_KEY = `automatedTest.cases.${sessionId}`

interface CasesSnapshot {
  testCases: TestCase[]
  sheets: string[]
  currentSheet: string
}

/** 从浏览器读取当前标签页的用例快照 */
const loadCasesSnapshot = (): CasesSnapshot | null => {
  try {
    if (typeof localStorage === 'undefined') return null
    const raw = localStorage.getItem(CASES_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<CasesSnapshot>
    if (!Array.isArray(parsed.testCases)) return null
    return {
      testCases: parsed.testCases,
      sheets: Array.isArray(parsed.sheets) ? parsed.sheets : [],
      currentSheet: typeof parsed.currentSheet === 'string' ? parsed.currentSheet : '',
    }
  } catch {
    return null
  }
}

/** 保存用例快照到浏览器（超出配额时静默放弃，不影响页面使用） */
const saveCasesSnapshot = (snapshot: CasesSnapshot) => {
  try {
    if (typeof localStorage === 'undefined') return
    const raw = JSON.stringify(snapshot)
    // localStorage 配额通常约 5MB（UTF-16 计约 2.5M 字符），留出余量
    if (raw.length > 2_000_000) {
      console.warn('[useStore] 用例数据过大，跳过本地持久化')
      return
    }
    localStorage.setItem(CASES_STORAGE_KEY, raw)
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

interface AppState {
  testCases: TestCase[]
  visibleCaseColumnKeys: string[]
  sheets: string[]
  currentSheet: string
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

  setTestCases: (cases: TestCase[]) => void
  setVisibleCaseColumnKeys: (keys: string[]) => void
  setSheets: (sheets: string[]) => void
  setCurrentSheet: (sheet: string) => void
  addLog: (log: LogEntry) => void
  clearLogs: () => void
  setProgress: (p: ExecutionProgress | null) => void
  setIsRunning: (v: boolean) => void
  setIsConnected: (v: boolean) => void
  setConfirmRequest: (c: ConfirmRequest | null) => void
  setSSHConfig: (c: SSHConfig) => void
  setSSHStatus: (s: SSHStatus) => void
  setWorkspace: (w: WorkspaceConfig) => void
  updateCaseStatus: (caseKey: string, status: string, actualResult?: string, logFile?: string) => void
  updateCaseSelected: (caseKey: string, selected: boolean) => void
  setAllCaseSelected: (selected: boolean) => void
  resetSelectedCases: () => void
  // AI 步骤解析
  setAIParseProgress: (p: AIParseProgress | null) => void
  addAIParsedCase: (caseKey: string) => void
  clearAIParsedCases: () => void
}

const casesSnapshot = loadCasesSnapshot()

/** 将当前用例/表页状态写回浏览器（仅在用例相关状态变更时调用） */
const persistCases = () => {
  const state = useStore.getState()
  saveCasesSnapshot({
    testCases: state.testCases,
    sheets: state.sheets,
    currentSheet: state.currentSheet,
  })
}

export const useStore = create<AppState>((set) => ({
  testCases: casesSnapshot?.testCases ?? [],
  visibleCaseColumnKeys: loadVisibleColumnKeys(),
  sheets: casesSnapshot?.sheets ?? [],
  currentSheet: casesSnapshot?.currentSheet ?? '',
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

  setTestCases: (cases) => {
    set({
      testCases: cases.map((c) => ({
        ...c,
        case_key: resolveCaseKey(c),
      })),
    })
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
  addLog: (log) => set((state) => ({ logs: [...state.logs, log] })),
  clearLogs: () => set({ logs: [] }),
  setProgress: (p) => set({ progress: p }),
  setIsRunning: (v) => set({ isRunning: v }),
  setIsConnected: (v) => set({ isConnected: v }),
  setConfirmRequest: (c) => set({ confirmRequest: c }),
  setSSHConfig: (c) => set({ sshConfig: c }),
  setSSHStatus: (s) => set({ sshStatus: s }),
  setWorkspace: (w) => set({ workspace: w }),
  updateCaseStatus: (caseKey, status, actualResult?, logFile?) => {
    set((state) => ({
      testCases: state.testCases.map((c) =>
        resolveCaseKey(c) === caseKey
          ? {
              ...c,
              status,
              ...(actualResult !== undefined ? { actual_result: actualResult } : {}),
              ...(logFile ? { log_file: logFile } : {}),
            }
          : c
      ),
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
  setAllCaseSelected: (selected) => {
    set((state) => ({
      testCases: state.testCases.map((c) => ({ ...c, selected })),
    }))
    persistCases()
  },
  resetSelectedCases: () => {
    set((state) => ({
      testCases: state.testCases.map((c) =>
        c.selected ? { ...c, status: 'NT', actual_result: '' } : c
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
  clearAIParsedCases: () => set({ aiParsedCases: new Set<string>() }),
}))