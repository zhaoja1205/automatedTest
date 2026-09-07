import { create } from 'zustand'
import type {
  ConfirmRequest,
  ExecutionProgress,
  LogEntry,
  SSHConfig,
  SSHStatus,
  TestCase,
  WorkspaceConfig,
} from '../types'

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
  updateCaseStatus: (caseKey: string, status: string, actualResult?: string) => void
  updateCaseSelected: (caseKey: string, selected: boolean) => void
  setAllCaseSelected: (selected: boolean) => void
  resetSelectedCases: () => void
  // AI 步骤解析
  setAIParseProgress: (p: AIParseProgress | null) => void
  addAIParsedCase: (caseKey: string) => void
  clearAIParsedCases: () => void
}

export const useStore = create<AppState>((set) => ({
  testCases: [],
  sheets: [],
  currentSheet: '',
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

  setTestCases: (cases) => set({
    testCases: cases.map((c) => ({
      ...c,
      case_key: resolveCaseKey(c),
    })),
  }),
  setSheets: (sheets) => set({ sheets }),
  setCurrentSheet: (sheet) => set({ currentSheet: sheet }),
  addLog: (log) => set((state) => ({ logs: [...state.logs, log] })),
  clearLogs: () => set({ logs: [] }),
  setProgress: (p) => set({ progress: p }),
  setIsRunning: (v) => set({ isRunning: v }),
  setIsConnected: (v) => set({ isConnected: v }),
  setConfirmRequest: (c) => set({ confirmRequest: c }),
  setSSHConfig: (c) => set({ sshConfig: c }),
  setSSHStatus: (s) => set({ sshStatus: s }),
  setWorkspace: (w) => set({ workspace: w }),
  updateCaseStatus: (caseKey, status, actualResult?) =>
    set((state) => ({
      testCases: state.testCases.map((c) =>
        resolveCaseKey(c) === caseKey
          ? { ...c, status, ...(actualResult !== undefined ? { actual_result: actualResult } : {}) }
          : c
      ),
    })),
  updateCaseSelected: (caseKey, selected) =>
    set((state) => ({
      testCases: state.testCases.map((c) =>
        resolveCaseKey(c) === caseKey ? { ...c, selected } : c
      ),
    })),
  setAllCaseSelected: (selected) =>
    set((state) => ({
      testCases: state.testCases.map((c) => ({ ...c, selected })),
    })),
  resetSelectedCases: () =>
    set((state) => ({
      testCases: state.testCases.map((c) =>
        c.selected ? { ...c, status: 'NT', actual_result: '' } : c
      ),
    })),
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