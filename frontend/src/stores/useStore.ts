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
  updateCaseStatus: (caseKey: string, status: string) => void
  updateCaseSelected: (caseKey: string, selected: boolean) => void
  setAllCaseSelected: (selected: boolean) => void
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
  updateCaseStatus: (caseKey, status) =>
    set((state) => ({
      testCases: state.testCases.map((c) =>
        resolveCaseKey(c) === caseKey ? { ...c, status } : c
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
}))