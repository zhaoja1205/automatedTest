import { useState, useEffect, useCallback, useRef } from 'react'
import { isAxiosError } from 'axios'
import {
  Card, Row, Col, Upload, Button, Table, Tag, Progress, Statistic,
  Space, Typography, message, Alert, Radio, Checkbox, Tooltip, Dropdown, Popover,
  Badge, Drawer, Modal, Select,
} from 'antd'
import {
  UploadOutlined, PlayCircleOutlined, StopOutlined,
  DownloadOutlined, CheckOutlined, CloseOutlined,
  RobotOutlined, BulbOutlined, FileTextOutlined, CodeOutlined,
  ExperimentOutlined, LoadingOutlined, DownOutlined, QuestionCircleOutlined,
  PictureOutlined, BugOutlined, EditOutlined, SaveOutlined, ReloadOutlined,
  DesktopOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'
import { optionalCaseColumnKeys, useStore } from '../stores/useStore'
import { useWebSocket } from '../hooks/useWebSocket'
import AIAnalysisDrawer from '../components/AIAnalysisDrawer'
import AIReportModal from '../components/AIReportModal'
import CaseLogModal from '../components/CaseLogModal'
import CaseImagesModal from '../components/CaseImagesModal'
import { CollapsibleLogText } from '../components/CollapsibleLogText'
import CommandPreviewModal from '../components/CommandPreviewModal'
import TestStepRulesModal from '../components/TestStepRulesModal'
import TestCaseStepsEditModal from '../components/TestCaseStepsEditModal'
import TestStepsRewriteDiffModal from '../components/TestStepsRewriteDiffModal'
import CaseResultLogEditModal from '../components/CaseResultLogEditModal'
import ExecutionDraftBox from '../components/ExecutionDraftBox'
import {
  downloadResults,
  getCases,
  getBugList,
  getSSHConfig,
  getSSHStatus,
  getWorkspace,
  restoreCaseLogs,
  selectCases,
  sessionId,
  startExecution,
  uploadExcel,
  analyzeAllFailures,
  aiJudgeResult,
  aiRewriteSteps,
  exportTestCases,
  updateCaseSteps,
  updateCaseExpected,
  updateCaseResultLog,
  updateCaseManualEvidence,
  setWorkspace as apiSetWorkspace,
} from '../api/axios'
import type { ManualEvidencePayload } from '../api/axios'
import {
  isWorkspaceConfigChanged,
  loadStoredWorkspace,
  mergeWorkspaceConfig,
  saveStoredWorkspace,
} from '../utils/workspaceStorage'
import { extractAiEvidence, extractLogText, parseRemark } from '../utils/remarkDisplay'
import { formatWaitCountdown } from '../utils/countdown'
import { useWaitCountdown } from '../hooks/useWaitCountdown'
import { canShowCaseImages, isYuvCase } from '../utils/caseImages'
import {
  buildRestorePatch,
  findCaseForDraftItem,
  formatDraftTime,
  getAllExecutionDrafts,
  syncCaseEditToDrafts,
  type ExecutionDraft,
} from '../utils/executionDraft'
import { useCaseImageAvailability } from '../hooks/useCaseImageAvailability'
import type {
  TestCase, AIAnalysis, AIParsedStep, AIRewriteStepsResponse, BugListItem,
} from '../types'

const { Text } = Typography

/** 生成一次下载的进度标识，用于过滤 WebSocket 中的 download_progress 消息 */
const createDownloadToken = (): string => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

/** 从 Content-Disposition 解析下载文件名，解析失败时使用默认名 */
const getFilenameFromDisposition = (
  disposition: unknown,
  fallback: string,
): string => {
  if (typeof disposition !== 'string') return fallback
  const match = /filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i.exec(disposition)
  const raw = (match?.[1] || match?.[2] || '').trim()
  if (!raw) return fallback
  try {
    return decodeURIComponent(raw)
  } catch {
    return raw
  }
}

/** 状态统一按大写比较；空状态视为 NT */
const normalizeCaseStatus = (status?: string) => (status || 'NT').toUpperCase()

/** 状态筛选下拉的展示文案（与状态列标签保持一致） */
const STATUS_FILTER_LABELS: Record<string, string> = {
  NT: 'NT', PASS: 'Pass', FAIL: 'Fail', BLOCK: 'Block',
  REVIEW: '待确认', NA: 'NA', RUNNING: '执行中',
}

/** 状态筛选选项的展示顺序，未列出的状态追加在后面 */
const STATUS_FILTER_ORDER = ['NT', 'PASS', 'FAIL', 'BLOCK', 'REVIEW', 'NA', 'RUNNING']

/** 选择栏快捷选项：按执行状态批量选中当前表页的用例 */
const QUICK_SELECT_STATUSES = [
  { status: 'NT', label: 'NT' },
  { status: 'FAIL', label: 'Fail' },
  { status: 'PASS', label: 'Pass' },
  { status: 'REVIEW', label: 'Review' },
  { status: 'BLOCK', label: 'Block' },
  { status: 'NA', label: 'NA' },
]

/**
 * 表格筛选条件、页码与滚动位置存放在 sessionStorage，刷新页面后恢复。
 * key 带上 sessionId：与用例快照同生命周期，新标签页/新会话不会套用旧的视图状态。
 */
const DASHBOARD_VIEW_STORAGE_KEY = `automatedTest.dashboardView.${sessionId}`

interface DashboardViewState {
  currentPage: number
  typeFilter: string[]
  statusFilter: string[]
  statusFilterDraft: string[]
  /** 内容区（.page-content）的纵向滚动距离 */
  scrollTop: number
  /** 用例表格的横向滚动距离 */
  scrollLeft: number
}

const DEFAULT_DASHBOARD_VIEW_STATE: DashboardViewState = {
  currentPage: 1,
  typeFilter: [],
  statusFilter: [],
  statusFilterDraft: [],
  scrollTop: 0,
  scrollLeft: 0,
}

/** 读取滚动距离：只接受有限非负数 */
const parseScrollOffset = (value: unknown): number =>
  typeof value === 'number' && Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 0

/** 只接受字符串数组，过滤掉旧数据里的非法值 */
const parseStringList = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []

/** 读取上次的筛选条件与页码；无数据或损坏时回退到默认值 */
const loadDashboardViewState = (): DashboardViewState => {
  try {
    if (typeof sessionStorage === 'undefined') return { ...DEFAULT_DASHBOARD_VIEW_STATE }
    const raw = sessionStorage.getItem(DASHBOARD_VIEW_STORAGE_KEY)
    if (!raw) return { ...DEFAULT_DASHBOARD_VIEW_STATE }
    const parsed = JSON.parse(raw) as Partial<DashboardViewState>
    const currentPage =
      typeof parsed.currentPage === 'number' && Number.isFinite(parsed.currentPage)
        ? Math.max(1, Math.floor(parsed.currentPage))
        : 1
    return {
      currentPage,
      typeFilter: parseStringList(parsed.typeFilter),
      statusFilter: parseStringList(parsed.statusFilter),
      statusFilterDraft: parseStringList(parsed.statusFilterDraft),
      scrollTop: parseScrollOffset(parsed.scrollTop),
      scrollLeft: parseScrollOffset(parsed.scrollLeft),
    }
  } catch {
    return { ...DEFAULT_DASHBOARD_VIEW_STATE }
  }
}

/** 写回筛选条件、页码与滚动距离（隐私模式/存储已满等场景静默降级） */
const saveDashboardViewState = (state: DashboardViewState) => {
  try {
    if (typeof sessionStorage === 'undefined') return
    sessionStorage.setItem(DASHBOARD_VIEW_STORAGE_KEY, JSON.stringify(state))
  } catch {
    // 忽略存储失败，不影响页面使用
  }
}

/** 用例表格（含 BugList 页）的横向滚动容器 */
const isTableScrollContainer = (el: HTMLElement) =>
  el.classList.contains('ant-table-content') || el.classList.contains('ant-table-body')

/**
 * 按「表页 + 测试类型 + 状态」生成行快照。
 * 与点击「筛选」时的语义一致：之后执行导致用例状态变化也不会改变这份结果。
 */
const buildStatusFilterCaseKeys = (
  cases: TestCase[],
  typeFilter: string[],
  statusFilter: string[],
): Set<string> => {
  const typeFiltered = typeFilter.length === 0
    ? cases
    : cases.filter((c) => typeFilter.includes(c.test_type))
  return new Set(
    typeFiltered
      .filter((c) => statusFilter.includes(normalizeCaseStatus(c.status)))
      .map((c) => c.case_key),
  )
}

/** 「实际结果」单元格展示文本：优先 BUG 列，其次备注中的 AI 区块，最后原样备注 */
const getCaseResultText = (record: TestCase): string => {
  const parsed = parseRemark(record.remarks)
  const judgmentText = record.judgment?.trim() || ''
  if (judgmentText) {
    // BUG 列（judgment）按设计只保留状态与判定理由，不含证据行。
    // 重新判定后 judgment 会被写入并覆盖备注展示，这里把 AI 证据补回来，
    // 避免原来可见的「AI证据」行消失。
    const evidenceLines = record.ai_evidence?.length
      ? record.ai_evidence
      : extractAiEvidence(record.remarks)
    const missingEvidence = (evidenceLines || [])
      .map((line) => line.trim())
      .filter((line) => line && !judgmentText.includes(line))
    if (missingEvidence.length > 0) {
      return `${judgmentText}\nAI证据:\n${missingEvidence.map((line) => `- ${line}`).join('\n')}`
    }
    return judgmentText
  }
  return parsed.valid ? parsed.aiText : (record.remarks || 'NT')
}

export default function Dashboard() {
  const navigate = useNavigate()
  const store = useStore()
  const { visibleCaseColumnKeys: visibleColumnKeys, setVisibleCaseColumnKeys: setVisibleColumnKeys } = store
  const ws = useWebSocket()
  const [loading, setLoading] = useState(false)
  // 刷新后恢复的表筛选/页码/滚动位置（只在组件挂载时读取一次）
  const [initialViewState] = useState(loadDashboardViewState)
  // 最新的视图状态：滚动监听是异步回调，用 ref 读取避免闭包里的筛选/页码过期
  const viewStateRef = useRef<DashboardViewState>({ ...initialViewState })
  // 分页状态
  const [currentPage, setCurrentPage] = useState(initialViewState.currentPage)
  const pageSize = 20
  // AI 分析相关状态
  const [aiDrawerOpen, setAIDrawerOpen] = useState(false)
  const [aiDrawerCase, setAIDrawerCase] = useState<TestCase | null>(null)
  const [aiAnalysisCache, setAIAnalysisCache] = useState<Record<string, AIAnalysis>>({})
  const [aiBatchAnalyzing, setAIBatchAnalyzing] = useState(false)
  const [aiReportOpen, setAIReportOpen] = useState(false)
  // AI 步骤解析缓存
  const [aiParsedSteps, setAIParsedSteps] = useState<Record<string, AIParsedStep[]>>({})
  // 手动「重新判定」中的用例 key
  const [rejudgingCaseKey, setRejudgingCaseKey] = useState('')
  // AI 重写测试步骤：请求中的用例 key、待确认的 diff 数据、替换提交状态
  const [aiRewriteCase, setAIRewriteCase] = useState<string>('')
  const [stepRewrite, setStepRewrite] = useState<{
    caseKey: string
    caseId: string
    data: AIRewriteStepsResponse
  } | null>(null)
  const [applyingStepRewrite, setApplyingStepRewrite] = useState(false)
  // 执行日志弹窗
  const [logModalCase, setLogModalCase] = useState<TestCase | null>(null)
  // YUV 出图弹窗（查看板端下载回来的 PNG）
  const [imageModalCase, setImageModalCase] = useState<TestCase | null>(null)
  // 测试类型筛选（空数组表示显示全部类型）
  const [typeFilter, setTypeFilter] = useState<string[]>(initialViewState.typeFilter)
  // 执行状态筛选（已生效值；空数组表示显示全部状态）
  const [statusFilter, setStatusFilter] = useState<string[]>(initialViewState.statusFilter)
  // 状态下拉框中待应用的值：选择后不立即刷新表格，点击「筛选」才生效
  const [statusFilterDraft, setStatusFilterDraft] = useState<string[]>(initialViewState.statusFilterDraft)
  // 点击「筛选」时匹配到的用例快照；执行开始后用例状态变为 NT 时，
  // 仍是这些行留在表格里，直到下一次点击「筛选」才重新计算。
  const [statusFilterCaseKeys, setStatusFilterCaseKeys] = useState<Set<string> | null>(() => {
    if (initialViewState.statusFilter.length === 0) return null
    // 刷新后没有事件触发「筛选」，按恢复的筛选条件重建快照，表格才仍是筛选结果
    const sheetCasesForInit = store.currentSheet
      ? store.testCases.filter((c) => c.source_sheet === store.currentSheet)
      : store.testCases
    return buildStatusFilterCaseKeys(
      sheetCasesForInit,
      initialViewState.typeFilter,
      initialViewState.statusFilter,
    )
  })
  // 命令预览弹窗（为空表示关闭）
  const [previewCommandKeys, setPreviewCommandKeys] = useState<string[] | null>(null)
  // 测试步骤编写规则弹窗
  const [stepRulesOpen, setStepRulesOpen] = useState(false)
  // 测试步骤编辑弹窗
  const [stepEditCase, setStepEditCase] = useState<TestCase | null>(null)
  const [savingSteps, setSavingSteps] = useState(false)
  // 预期结果编辑弹窗
  const [expectedEditCase, setExpectedEditCase] = useState<TestCase | null>(null)
  const [savingExpected, setSavingExpected] = useState(false)
  // 实际结果 + 执行日志编辑弹窗
  const [resultLogEditCase, setResultLogEditCase] = useState<TestCase | null>(null)
  const [savingResultLog, setSavingResultLog] = useState(false)
  // 执行日志草稿箱
  const [draftBoxOpen, setDraftBoxOpen] = useState(false)
  const [draftCount, setDraftCount] = useState(() => getAllExecutionDrafts().length)
  const [pendingRestoreDraft, setPendingRestoreDraft] = useState<ExecutionDraft | null>(null)
  const [restoringLogs, setRestoringLogs] = useState(false)
  // 下载结果：可选只导出部分用例表
  const [downloadOpen, setDownloadOpen] = useState(false)
  const [downloadSheets, setDownloadSheets] = useState<string[]>([])
  const [downloadRegenerateStats, setDownloadRegenerateStats] = useState(true)
  // 只覆盖当前勾选的用例：其它用例行、工作表、统计页、BugList 全部保持原样
  const [downloadSelectedOnly, setDownloadSelectedOnly] = useState(false)
  const [downloadLoading, setDownloadLoading] = useState(false)
  // 本次下载的进度标识；只展示 token 匹配的进度消息（避免旧下载的迟到消息）
  const [downloadToken, setDownloadToken] = useState('')
  // 下载测试用例（只含定义信息）请求中
  const [exportingCases, setExportingCases] = useState(false)

  const handleAIAnalyze = useCallback((record: TestCase) => {
    setAIDrawerCase(record)
    setAIDrawerOpen(true)
  }, [])

  const handleAIRewriteStep = useCallback(async (record: TestCase) => {
    const caseKey = record.case_key || `${record.source_sheet}:${record.row_number}:${record.case_id}`
    if (aiRewriteCase) return
    if (!record.test_steps || !record.test_steps.trim()) {
      message.warning('该用例没有测试步骤，无法重写')
      return
    }
    setAIRewriteCase(caseKey)
    try {
      const res = await aiRewriteSteps({
        step_text: record.test_steps,
        context: record.description,
        case_id: caseKey,
        force_ai: true,
      })
      setStepRewrite({ caseKey, caseId: record.case_id, data: res.data })
    } catch (error: unknown) {
      const detail = isAxiosError(error)
        ? (error.response?.data as { detail?: string } | undefined)?.detail
        : undefined
      message.error(detail || 'AI 重写测试步骤失败')
    } finally {
      setAIRewriteCase('')
    }
  }, [aiRewriteCase])

  // 人工确认后，把 AI 重写版本写回用例并替换原步骤
  const handleApplyStepRewrite = useCallback(async () => {
    if (!stepRewrite) return
    if (stepRewrite.data.input_truncated) {
      message.error('原文过长，AI 只处理了部分内容，不能直接替换')
      return
    }
    setApplyingStepRewrite(true)
    try {
      await updateCaseSteps(stepRewrite.caseKey, stepRewrite.data.rewritten_steps)
      store.updateCaseFields(stepRewrite.caseKey, {
        test_steps: stepRewrite.data.rewritten_steps,
      })
      // 步骤已变化，旧的后台解析结果失效，避免命令预览/执行仍用旧命令
      setAIParsedSteps(prev => {
        if (!prev[stepRewrite.caseKey]) return prev
        const updated = { ...prev }
        delete updated[stepRewrite.caseKey]
        return updated
      })
      store.removeAIParsedCase(stepRewrite.caseKey)
      setStepRewrite(null)
      message.success('已替换为 AI 重写后的测试步骤')
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '替换测试步骤失败'))
    } finally {
      setApplyingStepRewrite(false)
    }
  }, [stepRewrite, store])

  const handleRejudge = useCallback(async (record: TestCase) => {
    const caseKey = record.case_key
      || `${record.source_sheet}:${record.row_number}:${record.case_id}`
    if (rejudgingCaseKey) return
    setRejudgingCaseKey(caseKey)
    try {
      const res = await aiJudgeResult(caseKey)
      const patch = res.data.case_patch
      if (patch) store.updateCaseFields(caseKey, patch)
      const status = res.data.judgment?.status || ''
      message.success(
        `重新判定完成：${status === 'NEED_REVIEW' ? '待人工确认' : status}`)
      if (res.data.excel_updated === false) {
        message.warning('页面判定已更新，但结果 Excel 写回失败')
      }
    } catch (error: unknown) {
      const detail = isAxiosError(error)
        ? (error.response?.data as { detail?: string } | undefined)?.detail
        : undefined
      message.error(detail || 'AI 重新判定失败')
    } finally {
      setRejudgingCaseKey('')
    }
  }, [rejudgingCaseKey, store])

  const handleAnalysisDone = useCallback((caseKey: string, analysis: AIAnalysis) => {
    setAIAnalysisCache(prev => ({ ...prev, [caseKey]: analysis }))
  }, [])

  const handleBatchAnalyze = useCallback(async () => {
    setAIBatchAnalyzing(true)
    try {
      const res = await analyzeAllFailures()
      const { analyses, total, analyzed } = res.data
      const newCache: Record<string, AIAnalysis> = { ...aiAnalysisCache }
      for (const a of analyses) {
        newCache[a.case_id] = a
      }
      setAIAnalysisCache(newCache)
      message.success(`AI 分析完成：${analyzed}/${total} 个失败用例已分析`)
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || '批量分析失败'
      message.error(detail)
    } finally {
      setAIBatchAnalyzing(false)
    }
  }, [aiAnalysisCache])

  const getErrorMessage = (error: unknown, fallback: string) => {
    if (isAxiosError<{ detail?: string }>(error))
      return error.response?.data?.detail || error.message || fallback
    if (error instanceof Error) return error.message
    return fallback
  }

  const handleSaveStepEdit = useCallback(async (next: string) => {
    if (!stepEditCase) return
    const caseKey = stepEditCase.case_key
      || `${stepEditCase.source_sheet}:${stepEditCase.row_number}:${stepEditCase.case_id}`
    setSavingSteps(true)
    try {
      await updateCaseSteps(caseKey, next)
      store.updateCaseFields(caseKey, { test_steps: next })
      // 步骤已变化，旧的 AI 解析结果失效
      setAIParsedSteps(prev => {
        if (!prev[caseKey]) return prev
        const updated = { ...prev }
        delete updated[caseKey]
        return updated
      })
      setStepEditCase(null)
      message.success('测试步骤已更新')
    } catch (error) {
      message.error(getErrorMessage(error, '保存测试步骤失败'))
    } finally {
      setSavingSteps(false)
    }
  }, [stepEditCase, store])

  const handleSaveExpectedEdit = useCallback(async (next: string) => {
    if (!expectedEditCase) return
    const caseKey = expectedEditCase.case_key
      || `${expectedEditCase.source_sheet}:${expectedEditCase.row_number}:${expectedEditCase.case_id}`
    setSavingExpected(true)
    try {
      await updateCaseExpected(caseKey, next)
      store.updateCaseFields(caseKey, { expected_result: next })
      setExpectedEditCase(null)
      message.success('预期结果已更新')
    } catch (error) {
      message.error(getErrorMessage(error, '保存预期结果失败'))
    } finally {
      setSavingExpected(false)
    }
  }, [expectedEditCase, store])

  const handleSaveResultLog = useCallback(async (resultText: string, logText: string) => {
    if (!resultLogEditCase) return
    const caseKey = resultLogEditCase.case_key
      || `${resultLogEditCase.source_sheet}:${resultLogEditCase.row_number}:${resultLogEditCase.case_id}`
    setSavingResultLog(true)
    try {
      const originalLog = extractLogText(resultLogEditCase.remarks)
      const logChanged = logText !== originalLog
      const res = await updateCaseResultLog(caseKey, resultText, logChanged ? logText : undefined)
      const updated = res.data.case
      store.updateCaseFields(caseKey, {
        judgment: updated.judgment ?? resultText,
        remarks: updated.remarks ?? resultLogEditCase.remarks,
        // 后端按编辑后的实际结果重新提取了证据行，同步后日志弹窗高亮随之更新
        ai_evidence: updated.ai_evidence ?? resultLogEditCase.ai_evidence,
        // 日志内容变化后后端会清空手动高亮，避免行号错位
        manual_evidence: updated.manual_evidence ?? resultLogEditCase.manual_evidence,
        manual_evidence_lines: updated.manual_evidence_lines
          ?? resultLogEditCase.manual_evidence_lines,
        manual_evidence_mode: updated.manual_evidence_mode
          ?? resultLogEditCase.manual_evidence_mode,
      })
      const latestCase: TestCase = { ...resultLogEditCase, ...updated }
      const synced = await syncCaseEditToDrafts(
        latestCase,
        useStore.getState().sourceFileName,
        { logChanged, logText },
      )
      setResultLogEditCase(null)
      message.success(
        synced > 0
          ? '实际结果与执行日志已更新，并已同步到草稿箱'
          : '实际结果与执行日志已更新',
      )
    } catch (error) {
      message.error(getErrorMessage(error, '保存实际结果与执行日志失败'))
    } finally {
      setSavingResultLog(false)
    }
  }, [resultLogEditCase, store])

  const handleSaveManualEvidence = useCallback(async (
    caseRecord: TestCase,
    payload: ManualEvidencePayload,
  ) => {
    const caseKey = caseRecord.case_key
      || `${caseRecord.source_sheet}:${caseRecord.row_number}:${caseRecord.case_id}`
    try {
      const res = await updateCaseManualEvidence(caseKey, payload)
      const updated = res.data.case
      const manual = updated.manual_evidence ?? payload.contents
      const lines = updated.manual_evidence_lines ?? payload.lines
      // 手动高亮只支持按行号选择，保存后统一使用 line 匹配方式
      const mode = 'line' as const
      store.updateCaseFields(caseKey, {
        manual_evidence: manual,
        manual_evidence_lines: lines,
        manual_evidence_mode: mode,
      })
      setLogModalCase((prev) => (
        prev
          ? {
              ...prev,
              ...updated,
              manual_evidence: manual,
              manual_evidence_lines: lines,
              manual_evidence_mode: mode,
            }
          : prev
      ))
      // 手动高亮同样属于用例状态，同步到当前工作簿的草稿
      await syncCaseEditToDrafts(
        {
          ...caseRecord,
          ...updated,
          manual_evidence: manual,
          manual_evidence_lines: lines,
          manual_evidence_mode: mode,
        },
        useStore.getState().sourceFileName,
      )
      const count = lines.length
      message.success(
        count > 0
          ? `已保存 ${count} 行手动高亮（按行号），将覆盖 AI 证据`
          : '已清除手动高亮，恢复使用 AI 证据',
      )
    } catch (error) {
      message.error(getErrorMessage(error, '保存手动高亮失败'))
      throw error
    }
  }, [store])

  useEffect(() => {
    loadConfigs()
  }, [])

  useEffect(() => {
    const handler = () => setDraftCount(getAllExecutionDrafts().length)
    // IndexedDB 异步预热可能早于监听注册，先同步一次当前缓存
    handler()
    window.addEventListener('execution-drafts-changed', handler)
    return () => window.removeEventListener('execution-drafts-changed', handler)
  }, [])

  // 筛选条件/页码变化时写回浏览器，刷新后恢复（切页签、重新上传时的重置也会被记录）
  useEffect(() => {
    viewStateRef.current = {
      ...viewStateRef.current,
      currentPage,
      typeFilter,
      statusFilter,
      statusFilterDraft,
    }
    saveDashboardViewState(viewStateRef.current)
  }, [currentPage, typeFilter, statusFilter, statusFilterDraft])

  // 记录并恢复滚动距离：内容区纵向（page-content）+ 用例表格横向
  useEffect(() => {
    const pageContent = document.querySelector<HTMLElement>('.page-content')
    if (!pageContent) return

    let scrollTimer: number | undefined

    const persistScroll = () => saveDashboardViewState(viewStateRef.current)

    // scroll 事件不冒泡但会走捕获阶段，统一在内容区上捕获，
    // 这样表格内部滚动（页面生命周期内重新挂载）也能被监听到
    const handleScroll = (event: Event) => {
      const target = event.target
      if (!(target instanceof HTMLElement)) return
      if (target === pageContent) {
        viewStateRef.current.scrollTop = target.scrollTop
      } else if (isTableScrollContainer(target)) {
        viewStateRef.current.scrollLeft = target.scrollLeft
      } else {
        return
      }
      // 滚动事件很频繁，节流写回，最后一次由 pagehide / 卸载时兜底保存
      window.clearTimeout(scrollTimer)
      scrollTimer = window.setTimeout(persistScroll, 200)
    }

    const flushScroll = () => {
      window.clearTimeout(scrollTimer)
      persistScroll()
    }

    pageContent.addEventListener('scroll', handleScroll, true)
    window.addEventListener('pagehide', flushScroll)

    // 等首屏布局完成（表格行高、固定列宽度确定）后再恢复，避免被最大滚动范围截断
    let innerRaf = 0
    const outerRaf = requestAnimationFrame(() => {
      innerRaf = requestAnimationFrame(() => {
        pageContent.scrollTop = viewStateRef.current.scrollTop
        const tableScroller = pageContent.querySelector<HTMLElement>(
          '.case-table .ant-table-body, .case-table .ant-table-content',
        )
        if (tableScroller && tableScroller.scrollWidth > tableScroller.clientWidth) {
          tableScroller.scrollLeft = viewStateRef.current.scrollLeft
        }
      })
    })

    return () => {
      cancelAnimationFrame(outerRaf)
      cancelAnimationFrame(innerRaf)
      pageContent.removeEventListener('scroll', handleScroll, true)
      window.removeEventListener('pagehide', flushScroll)
      flushScroll()
    }
  }, [])

  const loadConfigs = async () => {
    try {
      const [ssh, workspace] = await Promise.all([getSSHConfig(), getWorkspace()])
      const sshStatus = await getSSHStatus()
      store.setSSHConfig(ssh.data)
      store.setSSHStatus(sshStatus.data)
      // 浏览器本地保存的工作区配置优先，并同步到后端供执行使用
      const storedWorkspace = loadStoredWorkspace()
      const mergedWorkspace = mergeWorkspaceConfig(workspace.data, storedWorkspace)
      store.setWorkspace(mergedWorkspace)
      // 合并后的完整配置写回 localStorage，保证所有字段都已持久化
      saveStoredWorkspace(mergedWorkspace)
      if (storedWorkspace && isWorkspaceConfigChanged(mergedWorkspace, workspace.data)) {
        try {
          await apiSetWorkspace(mergedWorkspace)
        } catch (syncError) {
          console.warn('[Dashboard] 同步工作区配置到后端失败', syncError)
        }
      }
    } catch (error) {
      message.warning(getErrorMessage(error, '加载配置失败'))
    }
  }

  const uploadCases = async (file: File): Promise<boolean> => {
    setLoading(true)
    // 先清除旧的 AI 解析状态，避免上传后 WS 消息到达又被清空的时序问题
    setAIParsedSteps({})
    store.clearAIParsedCases()
    store.setAIParseProgress(null)
    try {
      const res = await uploadExcel(file)
      store.setSheets(res.data.sheets)
      // BugList统计 页与 Excel 中的同名工作表同步
      store.setBugList(res.data.bug_sheet || '', res.data.bug_list || [])
      store.setCurrentSheet(res.data.sheets[0] || res.data.bug_sheet || '')
      store.setSourceFileName(file.name)
      setTypeFilter([])
      setStatusFilter([])
      setStatusFilterDraft([])
      setStatusFilterCaseKeys(null)
      setCurrentPage(1)
      const cases = await getCases()
      store.setTestCases(cases.data)
      message.success(`已加载 ${res.data.case_count} 条用例`)
      return true
    } catch (error) {
      message.error(getErrorMessage(error, '上传失败'))
      return false
    } finally {
      setLoading(false)
    }
  }

  const handleUpload = async (file: File) => {
    await uploadCases(file)
    return false
  }

  const handleStart = async () => {
    try {
      const selectedKeys = store.testCases.filter((c) => c.selected).map((c) => c.case_key)
      await startExecution(selectedKeys)
      store.setIsRunning(true)
      store.clearLogs()
      // 新一轮执行：清掉上一轮的板端日志面板与用例信息
      store.clearBoardTerminal()
      store.setCurrentCaseInfo(null)
      store.resetSelectedCases()
      message.success(`执行已启动，已选择 ${selectedKeys.length} 条用例`)
    } catch (error) {
      message.error(getErrorMessage(error, '启动失败'))
    }
  }

  const handleStop = () => { ws.stopExecution() }

  /** 直接下载一份测试用例：只含用例定义，不含任何执行信息 */
  const handleExportTestCases = useCallback(async () => {
    if (exportingCases) return
    if (store.testCases.length === 0) {
      message.warning('请先上传测试用例文件')
      return
    }
    setExportingCases(true)
    try {
      // 取点击瞬间的最新本地用例，把界面当前展示的定义字段一并提交
      const localCases = useStore.getState().testCases
      const res = await exportTestCases(localCases.map((c) => ({
        case_key: c.case_key,
        case_id: c.case_id,
        test_type: c.test_type,
        requirement_id: c.requirement_id,
        design_method: c.design_method,
        description: c.description,
        prerequisites: c.prerequisites,
        test_steps: c.test_steps,
        expected_result: c.expected_result,
        priority: c.priority,
      })))
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = getFilenameFromDisposition(
        res.headers?.['content-disposition'],
        '测试用例.xlsx',
      )
      a.click()
      URL.revokeObjectURL(url)
      message.success('已开始下载不含执行信息的测试用例')
    } catch (error) {
      message.error(await getDownloadErrorMessage(error, '下载测试用例失败'))
    } finally {
      setExportingCases(false)
    }
  }, [store.testCases.length, exportingCases])

  /** blob 响应出错时，后端返回的 JSON detail 藏在 Blob 里，需要先解析 */
  const getDownloadErrorMessage = async (error: unknown, fallback: string) => {
    if (isAxiosError(error) && error.response?.data instanceof Blob) {
      try {
        const payload = JSON.parse(await error.response.data.text())
        if (payload?.detail) return String(payload.detail)
      } catch {
        // 非 JSON 响应，回退到通用错误信息
      }
    }
    return getErrorMessage(error, fallback)
  }

  const handleDownload = async (
    regenerateStats: boolean,
    sheets?: string[],
    caseKeys?: string[],
  ) => {
    const selectedOnly = !!caseKeys?.length
    // 重新生成统计页需要等 AI 汇总数据，耗时可能较长，先给出提示
    const loadingMsg = message.loading(
      selectedOnly
        ? `正在导出选中 ${caseKeys?.length ?? 0} 条用例的结果，请稍候...`
        : regenerateStats && !sheets?.length
          ? '正在重新生成数据统计页内容并导出，请稍候...'
          : '正在导出结果，请稍候...',
      0,
    )
    setDownloadLoading(true)
    const token = createDownloadToken()
    setDownloadToken(token)
    store.setDownloadProgress({
      token,
      current: 0,
      total: 1,
      case_id: '',
      phase: 'prepare',
      message: '正在准备导出',
    })
    try {
      const res = await downloadResults(regenerateStats, sheets, token, caseKeys)
      // 后端在下载时才生成 BugList，刷新页签显示本次下载报告中的登记结果
      try {
        const bugRes = await getBugList()
        store.setBugList(bugRes.data.bug_sheet || '', bugRes.data.bug_list || [])
      } catch {
        // BugList 刷新失败不影响已下载的结果文件
      }
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = selectedOnly
        ? `test_results_选中${caseKeys?.length ?? 0}条用例.xlsx`
        : sheets?.length
          ? `test_results_${sheets.map((name) => name.replace(/[\\/:*?"<>|]/g, '_')).join('_')}.xlsx`
          : 'test_results.xlsx'
      a.click()
      URL.revokeObjectURL(url)
      setDownloadOpen(false)
    } catch (error) {
      message.error(await getDownloadErrorMessage(error, '下载失败'))
    } finally {
      loadingMsg()
      setDownloadLoading(false)
      setDownloadToken('')
      store.setDownloadProgress(null)
    }
  }

  /** 打开下载弹窗：默认勾选全部用例表，保持原「下载整个工作簿」行为 */
  const openDownloadDialog = () => {
    setDownloadSheets(downloadSheetOptions)
    setDownloadRegenerateStats(true)
    setDownloadSelectedOnly(false)
    setDownloadOpen(true)
  }

  /**
   * 勾选「只覆盖选中的用例」时只传 case_keys，忽略用例表选择；
   * 否则只勾选部分用例表时仅更新这些表，全部勾选时沿用完整工作簿导出。
   */
  const handleDownloadFromDialog = () => {
    if (downloadSelectedOnly) {
      if (selectedCaseKeys.length === 0) {
        message.warning('请先在用例列表中勾选要下载的用例')
        return Promise.resolve()
      }
      return handleDownload(downloadRegenerateStats, undefined, selectedCaseKeys)
    }
    const sheets = downloadSheets.length === downloadSheetOptions.length
      ? undefined
      : downloadSheets
    return handleDownload(downloadRegenerateStats, sheets)
  }

  /** 把草稿中的日志文本、执行状态写回当前用例，并尽力同步到后端会话 */
  const applyDraftToCurrentCases = useCallback(async (draft: ExecutionDraft): Promise<boolean> => {
    const state = useStore.getState()
    const patches: Record<string, Partial<TestCase>> = {}
    // 后端会话按 case_key 匹配：导入的草稿可能没有 case_key，
    // 这里把前端已解析出的目标用例标识一并传给后端，避免重复 case_id 恢复错行
    const restoreItems: Parameters<typeof restoreCaseLogs>[0] = []
    let matched = 0
    for (const item of draft.cases) {
      const target = findCaseForDraftItem(state.testCases, item)
      if (!target) continue
      const caseKey = target.case_key
        || `${target.source_sheet}:${target.row_number}:${target.case_id}`
      patches[caseKey] = buildRestorePatch(item, target)
      restoreItems.push({
        case_key: caseKey,
        case_id: item.case_id,
        description: item.description || target.description,
        log_text: item.log_text,
        remarks: item.remarks,
        status: item.status,
        actual_result: item.actual_result,
        judgment: item.judgment,
        ai_evidence: item.ai_evidence,
        manual_evidence: item.manual_evidence,
        manual_evidence_lines: item.manual_evidence_lines,
        manual_evidence_mode: item.manual_evidence_mode,
        terminals: item.terminals.map((terminal) => ({
          label: terminal.label,
          content: terminal.content,
        })),
      })
      matched += 1
    }

    if (matched === 0) {
      message.warning('当前用例与草稿不匹配，请重新上传对应的测试用例文件后再恢复')
      return false
    }

    state.applyCasePatches(patches)
    if (draft.logs.length > 0) state.addLogs(draft.logs)
    state.addLog({
      level: 'info',
      message: `已从草稿「${draft.name}」恢复 ${matched} 条用例执行日志`,
      timestamp: Date.now(),
    })

    const missing = draft.cases.length - matched
    let backendNotice = ''
    try {
      const res = await restoreCaseLogs(restoreItems)
      if (res.data.applied < matched) {
        backendNotice = `后端会话仅匹配 ${res.data.applied} 条`
      }
    } catch (error) {
      backendNotice = `同步后端失败：${getErrorMessage(error, '请重新上传用例文件')}`
    }

    if (backendNotice) {
      message.warning(`已恢复 ${matched} 条用例日志${missing > 0 ? `（${missing} 条未匹配）` : ''}；${backendNotice}`)
    } else {
      message.success(`已恢复 ${matched} 条用例日志${missing > 0 ? `（${missing} 条未匹配）` : ''}`)
    }
    return true
  }, [])

  /** 打开恢复确认弹窗（提示重新上传用例文件） */
  const handleRestoreDraftRequest = (draft: ExecutionDraft) => {
    setPendingRestoreDraft(draft)
    setDraftBoxOpen(false)
  }

  /** 重新上传用例文件后恢复草稿日志 */
  const handleRestoreUpload = async (file: File) => {
    if (!pendingRestoreDraft) return false
    setRestoringLogs(true)
    try {
      const uploaded = await uploadCases(file)
      if (!uploaded) return false
      if (await applyDraftToCurrentCases(pendingRestoreDraft)) {
        setPendingRestoreDraft(null)
      }
    } finally {
      setRestoringLogs(false)
    }
    return false
  }

  /** 直接恢复到当前已匹配的用例（不重新上传） */
  const handleRestoreDirectly = async () => {
    if (!pendingRestoreDraft) return
    setRestoringLogs(true)
    try {
      if (await applyDraftToCurrentCases(pendingRestoreDraft)) {
        setPendingRestoreDraft(null)
      }
    } finally {
      setRestoringLogs(false)
    }
  }

  const pendingRestoreMatchCount = pendingRestoreDraft
    ? pendingRestoreDraft.cases.filter((item) => findCaseForDraftItem(store.testCases, item)).length
    : 0

  const handleConfirm = (result: boolean) => {
    if (store.confirmRequest) {
      ws.confirmResponse(store.confirmRequest.confirm_id, result)
    }
  }

  const handleCaseSelectedChange = async (record: TestCase, selected: boolean) => {
    const caseKey = record.case_key || `${record.source_sheet}:${record.row_number}:${record.case_id}`
    store.updateCaseSelected(caseKey, selected)
    try {
      await selectCases([record.case_id], selected)
    } catch (error) {
      store.updateCaseSelected(caseKey, !selected)
      message.error(getErrorMessage(error, '更新用例选择失败'))
    }
  }

  const handleSelectAll = async (selected: boolean) => {
    const currentCases = store.testCases.filter((c) => c.source_sheet === store.currentSheet)
    const caseKeys = currentCases.map((c) => c.case_key)
    store.updateCasesSelected(caseKeys, selected)
    try {
      await selectCases(currentCases.map((c) => c.case_id), selected)
    } catch (error) {
      store.updateCasesSelected(caseKeys, !selected)
      message.error(getErrorMessage(error, '批量更新用例选择失败'))
    }
  }

  /** 取消所有表页的已选用例（执行时下发的是全局已选用例，这里要清空全局选择） */
  const handleDeselectAllCases = async () => {
    const selectedCases = store.testCases.filter((c) => c.selected)
    if (selectedCases.length === 0) return
    const caseKeys = selectedCases.map((c) => c.case_key)
    const caseIds = Array.from(new Set(selectedCases.map((c) => c.case_id)))
    store.updateCasesSelected(caseKeys, false)
    try {
      await selectCases(caseIds, false)
    } catch (error) {
      store.updateCasesSelected(caseKeys, true)
      message.error(getErrorMessage(error, '取消选择失败'))
    }
  }

  const handleSheetChange = (sheet: string) => {
    store.setCurrentSheet(sheet)
    setTypeFilter([])
    setStatusFilter([])
    setStatusFilterDraft([])
    setStatusFilterCaseKeys(null)
    setCurrentPage(1)
  }

  const applyStatusFilter = () => {
    if (statusFilterDraft.length === 0) {
      setStatusFilterCaseKeys(null)
    } else {
      // 按点击时的状态生成行快照：之后执行导致状态变化（如 Fail → NT）
      // 也不会把行从当前筛选结果里移除，直到再次点击「筛选」。
      setStatusFilterCaseKeys(new Set(
        typeFilteredCases
          .filter((c) => statusFilterDraft.includes(normalizeCaseStatus(c.status)))
          .map((c) => c.case_key),
      ))
    }
    setStatusFilter(statusFilterDraft)
    setCurrentPage(1)
  }

  const sheetCases = store.currentSheet
    ? store.testCases.filter((c) => c.source_sheet === store.currentSheet)
    : store.testCases

  // 当前表页可选的测试类型（用于表头筛选下拉框）
  const availableTypes = Array.from(
    new Set(sheetCases.map((c) => c.test_type).filter(Boolean)),
  )

  const typeFilteredCases = typeFilter.length === 0
    ? sheetCases
    : sheetCases.filter((c) => typeFilter.includes(c.test_type))

  // 状态筛选选项：当前类型筛选结果中出现的状态（含已选中但暂时没有数据的值）
  const statusOptionCounts = typeFilteredCases.reduce<Record<string, number>>((acc, c) => {
    const status = normalizeCaseStatus(c.status)
    acc[status] = (acc[status] || 0) + 1
    return acc
  }, {})
  const availableStatuses = Array.from(new Set([
    ...Object.keys(statusOptionCounts),
    ...statusFilter,
    ...statusFilterDraft,
  ])).sort((a, b) => {
    const ia = STATUS_FILTER_ORDER.indexOf(a)
    const ib = STATUS_FILTER_ORDER.indexOf(b)
    if (ia === -1 && ib === -1) return a.localeCompare(b)
    if (ia === -1) return 1
    if (ib === -1) return -1
    return ia - ib
  })
  const statusFilterOptions = availableStatuses.map((status) => ({
    value: status,
    label: `${STATUS_FILTER_LABELS[status] || status}（${statusOptionCounts[status] || 0}）`,
  }))
  // 有待应用/已生效的状态筛选时「筛选」按钮可用；
  // 已生效时再次点击可让快照按最新状态重新计算。
  const statusFilterApplicable = statusFilterDraft.length > 0 || statusFilter.length > 0

  const filteredCases = statusFilterCaseKeys === null
    ? typeFilteredCases
    : typeFilteredCases.filter((c) => statusFilterCaseKeys.has(c.case_key))

  // 当前页用例（用于按页选中）
  const pageCases = filteredCases.slice((currentPage - 1) * pageSize, currentPage * pageSize)

  // 恢复的页码可能超出当前筛选后的总页数（数据/筛选条件已变化），收敛到最后一页
  useEffect(() => {
    const maxPage = Math.max(1, Math.ceil(filteredCases.length / pageSize))
    if (currentPage > maxPage) setCurrentPage(maxPage)
  }, [currentPage, filteredCases.length, pageSize])

  // 当前页 YUV 用例是否已生成 PNG（决定是否显示查看图片按钮，与 PASS/FAIL 无关）
  // 按 case_key 索引：同一 case_id 可能同时出现在功能/故障测试表
  const imageAvailability = useCaseImageAvailability(
    pageCases
      .filter((c) => isYuvCase(c.expected_result))
      .map((c) => ({
        case_key: c.case_key,
        case_id: c.case_id,
        source_sheet: c.source_sheet || '',
      })),
    pageCases.map((c) => `${c.case_key}:${c.status}`).join('|'),
  )

  const handleSelectPage = async (selected: boolean) => {
    const cases = pageCases
    const caseKeys = cases.map((c) => c.case_key)
    store.updateCasesSelected(caseKeys, selected)
    try {
      await selectCases(cases.map((c) => c.case_id), selected)
    } catch (error) {
      store.updateCasesSelected(caseKeys, !selected)
      message.error(getErrorMessage(error, '批量更新用例选择失败'))
    }
  }

  /** 按状态选中当前表页的所有用例 */
  const handleSelectByStatus = async (status: string, label: string) => {
    const targetCases = typeFilteredCases.filter(
      (c) => normalizeCaseStatus(c.status) === status,
    )
    if (targetCases.length === 0) {
      message.info(`当前表页没有 ${label} 用例`)
      return
    }
    const caseKeys = targetCases.map((c) => c.case_key)
    store.updateCasesSelected(caseKeys, true)
    try {
      await selectCases(targetCases.map((c) => c.case_id), true)
      message.success(`已选中 ${targetCases.length} 条 ${label} 用例`)
    } catch (error) {
      store.updateCasesSelected(caseKeys, false)
      message.error(getErrorMessage(error, '批量更新用例选择失败'))
    }
  }

  // 快捷选择按「类型筛选后」统计，避免再受状态筛选限制（否则无法选中其它状态）
  const statusCounts = typeFilteredCases.reduce<Record<string, number>>((acc, c) => {
    const status = normalizeCaseStatus(c.status)
    acc[status] = (acc[status] || 0) + 1
    return acc
  }, {})
  const statusQuickSelectItems = QUICK_SELECT_STATUSES
    .filter(({ status }) => (statusCounts[status] || 0) > 0)
    .map(({ status, label }) => ({
      key: `selectStatus:${status}`,
      label: `选中所有 ${label}（${statusCounts[status]}）`,
    }))

  // ===== 表格列定义 =====
  const columns: ColumnsType<TestCase> = [
    {
      title: (
        <Space size={0} align="center">
          <Checkbox
            checked={filteredCases.length > 0 && filteredCases.every((c) => c.selected)}
            indeterminate={filteredCases.some((c) => c.selected) && !filteredCases.every((c) => c.selected)}
            onChange={(e) => handleSelectAll(e.target.checked)}
          />
          <Dropdown menu={{
            items: [
              { key: 'selectPage', label: '选择本页' },
              { key: 'selectAll', label: '选择全部' },
              ...(statusQuickSelectItems.length > 0
                ? [
                    { type: 'divider' as const },
                    {
                      key: 'selectByStatus',
                      label: '按状态选择',
                      children: statusQuickSelectItems,
                    },
                  ]
                : []),
              { type: 'divider' as const },
              { key: 'deselectPage', label: '取消本页' },
              { key: 'deselectAll', label: '取消全部' },
            ],
            onClick: ({ key }) => {
              if (key === 'selectPage') void handleSelectPage(true)
              else if (key === 'selectAll') void handleSelectAll(true)
              else if (key === 'deselectPage') void handleSelectPage(false)
              else if (key === 'deselectAll') void handleSelectAll(false)
              else if (key.startsWith('selectStatus:')) {
                const status = key.slice('selectStatus:'.length)
                const label = QUICK_SELECT_STATUSES.find((s) => s.status === status)?.label || status
                void handleSelectByStatus(status, label)
              }
            },
          }} trigger={['click']}>
            <DownOutlined style={{ fontSize: 10, cursor: 'pointer', marginLeft: 2, color: '#999' }} />
          </Dropdown>
        </Space>
      ),
      key: 'selected',
      dataIndex: 'selected',
      width: 48,
      fixed: 'left',
      render: (_: boolean, record) => (
        <Checkbox
          checked={record.selected}
          onChange={(e) => handleCaseSelectedChange(record, e.target.checked)}
        />
      ),
    },
    {
      title: '#',
      key: 'index',
      width: 50,
      fixed: 'left',
      render: (_: unknown, __: TestCase, index: number) => (
        <span style={{ color: '#9ca3af' }}>{index + 1}</span>
      ),
    },
    { title: '用例编号', key: 'case_id', dataIndex: 'case_id', width: 130, fixed: 'left',
      render: (text: string, record: TestCase) => {
        const caseKey = record.case_key || `${record.source_sheet}:${record.row_number}:${record.case_id}`
        const isParsed = store.aiParsedCases.has(caseKey) || !!aiParsedSteps[caseKey]
        return (
          <Space size={4} align="start" className="case-cell-content">
            <span>{text}</span>
            {isParsed && (
              <Tooltip title="AI 步骤已解析">
                <RobotOutlined style={{ color: '#722ed1', fontSize: 12 }} />
              </Tooltip>
            )}
          </Space>
        )
      },
    },
    {
      title: '用例描述', key: 'description', dataIndex: 'description', width: 200,
      render: (text: string) => <div className="case-cell-scroll">{text || '-'}</div>,
    },
    {
      title: '测试类型', key: 'test_type', dataIndex: 'test_type', width: 120,
      filters: availableTypes.length > 0
        ? availableTypes.map((type) => ({ text: type, value: type }))
        : undefined,
      filterMultiple: true,
      filteredValue: typeFilter.length > 0 ? typeFilter : null,
      render: (value: string) => value || '-',
    },
    { title: '优先级', key: 'priority', dataIndex: 'priority', width: 80 },
    {
      title: '状态', key: 'status', dataIndex: 'status', width: 120,
      render: (s: string, record: TestCase) => {
        const colors: Record<string, string> = { Pass: 'green', Fail: 'red', NT: 'default', BLOCK: 'orange', NA: 'default', Running: 'processing', Review: 'blue' }
        const labels: Record<string, string> = { Review: '待确认' }
        const isAIJudged = record.actual_result?.includes('[AI判定]')
        const confMatch = record.actual_result?.match(/\[规则置信度=([\d.]+)\]/)
        const confidence = confMatch ? parseFloat(confMatch[1]) : null
        const caseKey = record.case_key || record.case_id
        const hasAnalysis = !!aiAnalysisCache[caseKey]
        return (
          <Space direction="vertical" size={2}>
            <Tag color={colors[s] || 'default'} style={{ fontSize: 14, padding: '2px 12px', lineHeight: '24px', borderRadius: 12, fontWeight: 600 }}>{labels[s] || s}</Tag>
            {isAIJudged && (
              <Tag color="purple" style={{ fontSize: 11, padding: '0 6px', lineHeight: '20px', borderRadius: 10 }}>
                <RobotOutlined style={{ marginRight: 2 }} />AI
              </Tag>
            )}
            {confidence !== null && !isAIJudged && (
              <Tooltip title={`规则引擎置信度: ${(confidence * 100).toFixed(0)}%`}>
                <Tag
                  color={confidence >= 0.8 ? 'green' : confidence >= 0.6 ? 'orange' : 'red'}
                  style={{ fontSize: 11, padding: '0 6px', lineHeight: '20px', borderRadius: 10 }}
                >
                  {(confidence * 100).toFixed(0)}%
                </Tag>
              </Tooltip>
            )}
            {hasAnalysis && (
              <Tag
                color="geekblue"
                style={{ fontSize: 11, padding: '0 6px', lineHeight: '20px', cursor: 'pointer', borderRadius: 10 }}
                onClick={() => handleAIAnalyze(record)}
              >
                <BulbOutlined style={{ marginRight: 2 }} />已分析
              </Tag>
            )}
          </Space>
        )
      },
    },
    { title: '前置条件', key: 'prerequisites', dataIndex: 'prerequisites', width: 200,
      render: (text: string) => (
        <div className="case-cell-scroll">
          <Tooltip placement="topLeft" title={text}><span>{text || '-'}</span></Tooltip>
        </div>
      ),
    },
    {
      title: (
        <Space size={2} align="center">
          <span>测试步骤</span>
          <Tooltip title="查看测试步骤编写规则">
            <Button
              type="text"
              size="small"
              icon={<QuestionCircleOutlined />}
              onClick={(e) => {
                e.stopPropagation()
                setStepRulesOpen(true)
              }}
              style={{ padding: '0 2px', fontSize: 12, color: '#2f54eb' }}
            />
          </Tooltip>
        </Space>
      ),
      key: 'test_steps',
      dataIndex: 'test_steps',
      width: 300,
      render: (text: string, record: TestCase) => {
        const caseKey = record.case_key || `${record.source_sheet}:${record.row_number}:${record.case_id}`
        const parsed = aiParsedSteps[caseKey]
        const isRewriting = aiRewriteCase === caseKey

        const confidenceColor = (c: number) => c >= 0.8 ? '#36b37e' : c >= 0.6 ? '#ff8b00' : '#de350b'

        const tooltipContent = (
          <div style={{ maxWidth: 450, maxHeight: 400, overflow: 'auto' }}>
            <div style={{ marginBottom: 8, whiteSpace: 'pre-wrap', fontSize: 12 }}>{text}</div>
            {parsed && parsed.length > 0 && (
              <>
                <div style={{ borderTop: '1px solid #444', paddingTop: 8, marginTop: 4 }}>
                  <strong>🤖 AI 解析命令：</strong>
                </div>
                {parsed.filter(s => s.kind !== 'skip').map((s, i) => (
                  <div key={i} style={{ fontSize: 12, margin: '4px 0', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{
                      display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
                      background: confidenceColor(s.confidence), flexShrink: 0,
                    }} />
                    <Tag color={s.kind === 'command' ? 'blue' : s.kind === 'nvsipl_input' ? 'purple' : 'default'}
                      style={{ fontSize: 11, lineHeight: '18px', margin: 0 }}>
                      {s.kind}
                    </Tag>
                    <code style={{ fontSize: 11, wordBreak: 'break-all' }}>{s.command}</code>
                  </div>
                ))}
              </>
            )}
          </div>
        )

        return (
          <Space size={4} align="start" className="case-cell-content">
            <div className="case-cell-scroll" style={{ flex: 1, minWidth: 0 }}>
              <Tooltip placement="topLeft" title={tooltipContent} overlayStyle={{ maxWidth: 500 }}>
                <span style={{ cursor: 'pointer' }}>{text}</span>
              </Tooltip>
            </div>
            {parsed && parsed.filter(s => s.kind !== 'skip').length > 0 && (
              <Tag color="purple" style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>
                <RobotOutlined /> {parsed.filter(s => s.kind !== 'skip').length}
              </Tag>
            )}
            {text && (
              <Tooltip title="查看将执行的命令">
                <Button
                  type="text"
                  size="small"
                  icon={<CodeOutlined />}
                  onClick={() => setPreviewCommandKeys([caseKey])}
                  style={{ fontSize: 12, padding: '0 2px', color: '#2f54eb' }}
                />
              </Tooltip>
            )}
            <Tooltip title="编辑测试步骤">
              <Button
                type="text"
                size="small"
                icon={<EditOutlined />}
                disabled={store.isRunning}
                onClick={() => setStepEditCase(record)}
                style={{ fontSize: 12, padding: '0 2px', color: '#2f54eb' }}
              />
            </Tooltip>
            {text && (
              <Tooltip title="AI 重写为程序可识别的测试步骤（会先展示差异，确认后替换）">
                <Button
                  type="text"
                  size="small"
                  icon={isRewriting ? <LoadingOutlined /> : <RobotOutlined />}
                  disabled={!!aiRewriteCase || store.isRunning}
                  onClick={() => handleAIRewriteStep(record)}
                  style={{ fontSize: 12, padding: '0 2px' }}
                />
              </Tooltip>
            )}
          </Space>
        )
      },
    },
    { title: '预期结果', key: 'expected_result', dataIndex: 'expected_result', width: 240,
      render: (text: string, record: TestCase) => (
        <Space size={4} align="start" className="case-cell-content">
          <div className="case-cell-scroll" style={{ flex: 1, minWidth: 0 }}>
            <Tooltip placement="topLeft" title={text}><span>{text}</span></Tooltip>
          </div>
          <Tooltip title="编辑预期结果">
            <Button
              type="text"
              size="small"
              icon={<EditOutlined />}
              disabled={store.isRunning}
              onClick={() => setExpectedEditCase(record)}
              style={{ fontSize: 12, padding: '0 2px', color: '#2f54eb' }}
            />
          </Tooltip>
        </Space>
      ),
    },
    { title: '实际结果', key: 'actual_result', dataIndex: 'actual_result', width: 300,
      render: (_text: string, record: TestCase) => {
        // 「BUG」列保存 AI 判定结果；兼容旧数据从备注中解析
        const parsedJudgment = record.judgment ? parseRemark(record.judgment) : null
        const parsed = parseRemark(record.remarks)
        const resultText = getCaseResultText(record)
        const aiStatus = ((parsedJudgment?.valid ? parsedJudgment.aiStatus : parsed.aiStatus) || '').toLowerCase()
        const color = !parsedJudgment?.valid && !parsed.valid ? undefined :
                      aiStatus === 'pass' ? '#36b37e' :
                      aiStatus === 'fail' ? '#de350b' :
                      aiStatus.includes('review') ? '#2f54eb' : undefined
        const logText = parsed.valid ? parsed.logText : extractLogText(record.remarks)
        const hasLog = !!(logText || record.log_file)

        return (
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 4 }}>
            <div className="case-cell-scroll" style={{ flex: 1, minWidth: 0 }}>
              <Tooltip
                placement="topLeft"
                overlayStyle={{ maxWidth: 600 }}
                title={
                  resultText ? (
                    <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all', maxWidth: 560, fontSize: 12 }}>
                      {resultText}
                    </pre>
                  ) : '暂无BUG'
                }
              >
                <span style={{ color, whiteSpace: 'pre-wrap' }}>{resultText}</span>
              </Tooltip>
            </div>
            <Tooltip title={hasLog ? '查看执行日志' : '暂无执行日志'}>
              <span style={{ display: 'inline-flex', flexShrink: 0 }}>
                <Button
                  type="text"
                  size="small"
                  icon={<FileTextOutlined />}
                  disabled={!hasLog}
                  onClick={() => setLogModalCase(record)}
                  style={{ padding: '0 2px', color: '#2f54eb' }}
                />
              </span>
            </Tooltip>
            <Tooltip title="编辑实际结果与执行日志">
              <span style={{ display: 'inline-flex', flexShrink: 0 }}>
                <Button
                  type="text"
                  size="small"
                  icon={<EditOutlined />}
                  disabled={store.isRunning}
                  onClick={() => setResultLogEditCase(record)}
                  style={{ padding: '0 2px', color: '#2f54eb' }}
                />
              </span>
            </Tooltip>
            {canShowCaseImages(record.expected_result, imageAvailability[record.case_key]) && (
              <Tooltip title="查看生成的 YUV 图（PNG）">
                <span style={{ display: 'inline-flex', flexShrink: 0 }}>
                  <Button
                    type="text"
                    size="small"
                    icon={<PictureOutlined />}
                    onClick={() => setImageModalCase(record)}
                    style={{ padding: '0 2px', color: '#2f54eb' }}
                  />
                </span>
              </Tooltip>
            )}
          </div>
        )
      },
    },
    {
      title: '操作', key: 'actions', width: 120, fixed: 'right' as const,
      render: (_: unknown, record: TestCase) => {
        const status = (record.status || '').toUpperCase()
        const canAnalyze = status === 'FAIL' || status === 'REVIEW'
        const hasResult = !!(
          record.actual_result?.trim() || record.log_file || record.judgment?.trim()
        )
        const canRejudge = hasResult
          && !['', 'NT', 'NA', 'RUNNING'].includes(status)
        const caseKey = record.case_key || record.case_id
        const rejudgeKey = record.case_key
          || `${record.source_sheet}:${record.row_number}:${record.case_id}`
        const hasCache = !!aiAnalysisCache[caseKey]
        if (!canAnalyze && !canRejudge) return null
        return (
          <Space direction="vertical" size={0}>
            {canAnalyze && (
              <Button
                type="link"
                size="small"
                icon={hasCache ? <BulbOutlined style={{ color: '#2f54eb' }} /> : <ExperimentOutlined />}
                onClick={() => handleAIAnalyze(record)}
              >
                {hasCache ? '查看' : 'AI分析'}
              </Button>
            )}
            {canRejudge && (
              <Button
                type="link"
                size="small"
                icon={<ReloadOutlined />}
                loading={rejudgingCaseKey === rejudgeKey}
                onClick={() => handleRejudge(record)}
              >
                重新判定
              </Button>
            )}
          </Space>
        )
      },
    },
  ]

  const optionalColumns = columns.filter(column => optionalCaseColumnKeys.includes(String(column.key)))
  const hasScrollableColumns = optionalColumns.some(column => !column.fixed && visibleColumnKeys.includes(String(column.key)))
  const visibleColumns = columns
    .filter(column => !optionalCaseColumnKeys.includes(String(column.key)) || visibleColumnKeys.includes(String(column.key)))
    .map(column => hasScrollableColumns ? column : { ...column, fixed: undefined })
  const visibleTableWidth = visibleColumns.reduce((total, column) => total + Number(column.width || 0), 0)

  // ===== 统计数据（统计全部用例，不随当前页签 / 类型筛选变化） =====
  const passCount = store.testCases.filter(c => c.status === 'Pass').length
  const failCount = store.testCases.filter(c => c.status === 'Fail').length
  const ntCount = store.testCases.filter(c => !c.status || c.status === 'NT').length
  const total = store.testCases.length
  const selectedCount = store.testCases.filter(c => c.selected).length
  const allSelectedCount = store.testCases.filter(c => c.selected).length
  /** 当前勾选用例的 case_key，用于「只覆盖选中的用例」下载 */
  const selectedCaseKeys = store.testCases
    .filter(c => c.selected)
    .map(c => c.case_key || `${c.source_sheet}:${c.row_number}:${c.case_id}`)
  // 通过率 = 通过数 / (通过 + 失败)，仅计算已判定的用例
  const judgedCount = passCount + failCount
  const rate = judgedCount > 0 ? Math.round((passCount / judgedCount) * 100) : 0
  // 是否有已执行的结果（非 NT 状态）；下载的是整个工作簿，不随当前页签变化
  const hasExecutedResults = store.testCases.some(c => c.status && c.status !== 'NT')
  // 可下载的用例表：优先用上传时后端返回的有序表名，旧快照回退到用例来源表
  const downloadSheetOptions = (
    store.sheets.length > 0
      ? store.sheets
      : Array.from(new Set(store.testCases.map(c => c.source_sheet).filter(Boolean)))
  ).filter((name) => name && name !== store.bugSheet)
  const allDownloadSheetsSelected =
    downloadSheetOptions.length > 0 && downloadSheets.length === downloadSheetOptions.length
  // 只展示本次下载的进度消息，避免上一次下载的迟到消息串到当前进度条
  const downloadProgress = downloadToken && store.downloadProgress?.token === downloadToken
    ? store.downloadProgress
    : null
  const downloadPercent = downloadProgress && downloadProgress.total > 0
    ? Math.min(100, Math.round((downloadProgress.current / downloadProgress.total) * 100))
    : 0
  // AI 已解析用例数
  const aiParsedCount = store.aiParsedCases.size
  // 等待倒计时：后端只给总时长，前端按截止时间本地每秒递减
  const waitRemaining = useWaitCountdown(store.progress)

  // ===== 页签：用例 Sheet + BugList统计 页（与 Excel 工作簿同步） =====
  const sheetTabs = store.bugSheet && !store.sheets.includes(store.bugSheet)
    ? [...store.sheets, store.bugSheet]
    : store.sheets
  const isBugListTab = !!store.bugSheet && store.currentSheet === store.bugSheet

  const severityColor = (value: string) => {
    const v = (value || '').toLowerCase()
    if (['致命', 'critical', 'blocker', 'fatal'].some((k) => v.includes(k))) return 'red'
    if (['严重', 'major', 'high'].some((k) => v.includes(k))) return 'volcano'
    if (['一般', 'normal', 'medium', 'moderate'].some((k) => v.includes(k))) return 'gold'
    if (['轻微', 'minor', 'low', 'trivial'].some((k) => v.includes(k))) return 'blue'
    return 'default'
  }
  const bugStatusColor = (value: string) => {
    const v = (value || '').toLowerCase()
    if (['fixed', 'closed', 'resolved', '已解决', '已修复'].some((k) => v.includes(k))) return 'green'
    if (['open', 'new', '待处理', '新建'].some((k) => v.includes(k))) return 'orange'
    if (['progress', '处理中', '修复中'].some((k) => v.includes(k))) return 'blue'
    if (['reject', '拒绝', '无效'].some((k) => v.includes(k))) return 'default'
    return 'purple'
  }

  // ===== BugList 表格列 =====
  const bugColumns: ColumnsType<BugListItem> = [
    { title: 'No.', key: 'no', dataIndex: 'no', width: 70 },
    { title: 'Bug ID', key: 'bug_id', dataIndex: 'bug_id', width: 130, render: (v: string) => v || '-' },
    { title: 'Module', key: 'module', dataIndex: 'module', width: 120, render: (v: string) => v || '-' },
    {
      title: 'Description', key: 'description', dataIndex: 'description', width: 320,
      render: (v: string) => (
        <Tooltip placement="topLeft" title={v}>
          <span>{v || '-'}</span>
        </Tooltip>
      ),
    },
    { title: 'Version', key: 'version', dataIndex: 'version', width: 120, render: (v: string) => v || '-' },
    {
      title: 'Severity', key: 'severity', dataIndex: 'severity', width: 110,
      render: (v: string) => (v ? <Tag color={severityColor(v)}>{v}</Tag> : '-'),
    },
    {
      title: 'Status', key: 'status', dataIndex: 'status', width: 110,
      render: (v: string) => (v ? <Tag color={bugStatusColor(v)}>{v}</Tag> : '-'),
    },
    { title: 'Tester', key: 'tester', dataIndex: 'tester', width: 110, render: (v: string) => v || '-' },
    { title: 'Date', key: 'date', dataIndex: 'date', width: 120, render: (v: string) => v || '-' },
    { title: 'Effective', key: 'effective', dataIndex: 'effective', width: 90, render: (v: string) => v || '-' },
    {
      title: 'Comment', key: 'comment', dataIndex: 'comment', width: 240,
      render: (v: string) => (
        <Tooltip placement="topLeft" title={v}>
          <span>{v || '-'}</span>
        </Tooltip>
      ),
    },
  ]

  return (
    <div>
      {/* ===== 工具栏 ===== */}
      <Card className="toolbar-card" style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
          <Space wrap size={8}>
            <Upload beforeUpload={handleUpload} showUploadList={false} accept=".xlsx,.xls">
              <Button icon={<UploadOutlined />} loading={loading}>上传用例</Button>
            </Upload>
            <Badge count={draftCount} size="small" offset={[-2, 2]}>
              <Tooltip title="保存执行日志文本；下载结果时日志会变成图片，可从草稿箱恢复">
                <Button icon={<SaveOutlined />} onClick={() => setDraftBoxOpen(true)}>
                  日志草稿箱
                </Button>
              </Tooltip>
            </Badge>
            <Badge dot={store.isRunning} status="processing" offset={[-2, 2]}>
              <Tooltip title="执行期间多终端并列实时显示板端日志，执行完成后可回看">
                <Button icon={<DesktopOutlined />} onClick={() => navigate('/logs/board')}>
                  板端日志
                </Button>
              </Tooltip>
            </Badge>
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              onClick={handleStart}
              disabled={store.isRunning || selectedCount === 0}
            >
              开始执行
            </Button>
            <Button
              danger
              icon={<StopOutlined />}
              onClick={handleStop}
              disabled={!store.isRunning}
            >
              停止
            </Button>
            <Tooltip title="预览选中用例将要下发到板端的命令">
              <Button
                icon={<CodeOutlined />}
                onClick={() => setPreviewCommandKeys(
                  store.testCases.filter((c) => c.selected).map((c) => c.case_key || c.case_id)
                )}
                disabled={allSelectedCount === 0}
              >
                查看执行命令
              </Button>
            </Tooltip>
            <Tooltip title="下载结果 Excel，备注列始终附带执行日志（按工作区配置输出为图片或文字）；可选择只覆盖当前勾选的用例，或只更新哪些用例表（其它内容保留原样），以及是否让 AI 重新生成「数据统计」页内容">
              <Button
                icon={<DownloadOutlined />}
                disabled={!hasExecutedResults}
                onClick={openDownloadDialog}
              >
                下载结果
              </Button>
            </Tooltip>
            <Tooltip title="下载一份测试用例 Excel：只包含测试步骤、预期结果等用例定义信息，不含执行状态、实际结果、BUG 判定、执行日志、测试人员/日期等执行信息；直接下载，不检查是否有修改">
              <Button
                icon={<DownloadOutlined />}
                loading={exportingCases}
                disabled={store.testCases.length === 0}
                onClick={handleExportTestCases}
              >
                下载测试用例
              </Button>
            </Tooltip>
          </Space>
          <Space wrap size={8}>
            <Tooltip title="AI 分析所有 Fail/Review 用例">
              <Button
                icon={aiBatchAnalyzing ? <LoadingOutlined /> : <ExperimentOutlined />}
                onClick={handleBatchAnalyze}
                loading={aiBatchAnalyzing}
                disabled={store.isRunning || !store.testCases.some(
                  (c: TestCase) => c.status?.toUpperCase() === 'FAIL' || c.status?.toUpperCase() === 'REVIEW'
                )}
              >
                AI 批量分析
              </Button>
            </Tooltip>
            <Button
              icon={<FileTextOutlined />}
              onClick={() => setAIReportOpen(true)}
              disabled={store.isRunning || store.testCases.length === 0}
            >
              AI 报告
            </Button>
          </Space>
        </div>
      </Card>

      {/* ===== 步骤解析进度 ===== */}
      {store.aiParseProgress && (
        <Card className="toolbar-card" style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <RobotOutlined style={{ fontSize: 18, color: store.aiParseProgress.status === 'done' ? '#36b37e' : '#722ed1' }} />
            <div style={{ flex: 1 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <Text strong style={{ fontSize: 13 }}>
                  {store.aiParseProgress.status === 'parsing' ? '步骤解析中...' :
                   store.aiParseProgress.status === 'interrupted' ? '步骤解析已中断' :
                   '步骤解析完成'}
                </Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {store.aiParseProgress.status === 'parsing'
                    ? `${store.aiParseProgress.current} / ${store.aiParseProgress.total}`
                    : `成功 ${store.aiParseProgress.success}，失败 ${store.aiParseProgress.failed}`
                  }
                </Text>
              </div>
              <Progress
                percent={store.aiParseProgress.total > 0
                  ? Math.round((store.aiParseProgress.current / store.aiParseProgress.total) * 100)
                  : 0}
                size="small"
                strokeColor={store.aiParseProgress.status === 'done' ? '#36b37e' :
                             store.aiParseProgress.status === 'interrupted' ? '#ff8b00' : '#722ed1'}
                showInfo={false}
              />
            </div>
            {store.aiParseProgress.status === 'parsing' && (
              <LoadingOutlined style={{ fontSize: 16, color: '#722ed1' }} />
            )}
            {store.aiParseProgress.status === 'done' && (
              <CheckOutlined style={{ fontSize: 16, color: '#36b37e' }} />
            )}
          </div>
        </Card>
      )}

      {/* ===== Sheet 页签（含与 Excel 同步的 BugList 页） ===== */}
      {store.sheets.length > 0 && (
        <Card className="toolbar-card" style={{ marginBottom: 12 }}>
          <Space wrap>
            <Text strong>页签：</Text>
            <Radio.Group value={store.currentSheet} onChange={(e) => handleSheetChange(e.target.value)}>
              {sheetTabs.map((sheet) => (
                <Radio.Button key={sheet} value={sheet}>
                  {sheet === store.bugSheet ? <><BugOutlined /> {sheet}</> : sheet}
                </Radio.Button>
              ))}
            </Radio.Group>
            <Text type="secondary">
              {isBugListTab
                ? `共 ${store.bugList.length} 条 Bug`
                : `已选 ${allSelectedCount} / ${store.testCases.length}`}
            </Text>
          </Space>
        </Card>
      )}

      {/* ===== 进度条 ===== */}
      {store.progress && (
        <Card className="toolbar-card" style={{ marginBottom: 12 }}>
          <Progress
            percent={Math.round((store.progress!.current / store.progress!.total) * 100)}
            format={() => (waitRemaining !== null
              ? `等待 ${formatWaitCountdown(waitRemaining)}`
              : `${store.progress!.current}/${store.progress!.total}`)}
            strokeColor="#2f54eb"
            status={store.progress!.message ? 'active' : 'normal'}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
            <Text style={{ flex: 1, minWidth: 0 }} ellipsis={{ tooltip: store.progress!.message }}>
              {store.progress!.message || '正在执行'}
            </Text>
            <Space size={12} style={{ flexShrink: 0 }}>
              <Text type="secondary">当前用例: {store.progress!.case_id}</Text>
              {store.isRunning && (
                <Button
                  type="link"
                  size="small"
                  onClick={() => navigate('/logs/board')}
                  style={{ padding: 0 }}
                >
                  板端实时日志 →
                </Button>
              )}
            </Space>
          </div>
        </Card>
      )}

      {/* ===== 人工确认 ===== */}
      {store.confirmRequest && (
        <Card style={{ marginBottom: 12, background: '#fefce8', border: '1px solid #fde68a' }}>
          <Alert
            message="需要人工确认"
            description={
              store.confirmRequest.step_desc.includes('\n') ? (
                <pre style={{
                  margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all',
                  maxHeight: 500, overflow: 'auto', fontSize: 12, lineHeight: 1.5,
                  background: '#fafafa', padding: 12, borderRadius: 4,
                }}>{store.confirmRequest.step_desc}</pre>
              ) : store.confirmRequest.step_desc
            }
            type="warning"
            showIcon
            action={
              <Space direction="vertical">
                <Button type="primary" icon={<CheckOutlined />} onClick={() => handleConfirm(true)}>确认 Pass</Button>
                <Button danger icon={<CloseOutlined />} onClick={() => handleConfirm(false)}>确认 Fail</Button>
              </Space>
            }
          />
        </Card>
      )}

      {/* ===== BugList 页（与 Excel 中的 BugList统计 页同步） ===== */}
      {isBugListTab && (
        <Card
          title={<Space size={6}><BugOutlined /><span>{store.bugSheet}</span></Space>}
          className="case-table"
          extra={<Text type="secondary">与 Excel 工作簿中的同名页同步</Text>}
        >
          <Table<BugListItem>
            columns={bugColumns}
            dataSource={store.bugList}
            rowKey={(record, index) => `${record.source_sheet}:${record.row_number}:${index}`}
            size="small"
            scroll={{ x: 1540 }}
            locale={{ emptyText: '暂无数据，下载结果报告时会自动登记失败用例' }}
            pagination={{
              current: currentPage,
              pageSize,
              showTotal: (total) => `共 ${total} 条 Bug`,
              showSizeChanger: false,
              onChange: (page) => setCurrentPage(page),
            }}
          />
        </Card>
      )}

      {!isBugListTab && (
        <>
      {/* ===== 统计卡片 ===== */}
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col flex="1"><Card className="stat-card"><Statistic title="总计" value={total} /></Card></Col>
        <Col flex="1"><Card className="stat-card"><Statistic title="已选" value={selectedCount} valueStyle={{ color: '#2f54eb' }} /></Card></Col>
        <Col flex="1"><Card className="stat-card"><Statistic title="通过" value={passCount} valueStyle={{ color: '#36b37e' }} /></Card></Col>
        <Col flex="1"><Card className="stat-card"><Statistic title="失败" value={failCount} valueStyle={{ color: '#de350b' }} /></Card></Col>
        <Col flex="1"><Card className="stat-card"><Statistic title="NT" value={ntCount} valueStyle={{ color: '#999' }} /></Card></Col>
        <Col flex="1"><Card className="stat-card"><Statistic title="通过率" value={rate} suffix="%" valueStyle={{ color: rate >= 80 ? '#36b37e' : rate >= 50 ? '#ff8b00' : '#de350b' }} /></Card></Col>
        {aiParsedCount > 0 && (
          <Col flex="1">
            <Card className="stat-card">
              <Statistic
                title={<><RobotOutlined style={{ marginRight: 4 }} />AI 已解析</>}
                value={aiParsedCount}
                valueStyle={{ color: '#722ed1' }}
              />
            </Card>
          </Col>
        )}
      </Row>

      {/* ===== 用例表格 ===== */}
      <Card
        title="测试用例"
        className="case-table"
        extra={
          <Space size={8}>
            <Select
              mode="multiple"
              allowClear
              size="small"
              placeholder="按状态筛选"
              value={statusFilterDraft}
              onChange={(values) => setStatusFilterDraft(values.map(String))}
              options={statusFilterOptions}
              maxTagCount="responsive"
              style={{ minWidth: 150, maxWidth: 280 }}
            />
            <Button
              size="small"
              disabled={!statusFilterApplicable}
              onClick={applyStatusFilter}
            >
              筛选
            </Button>
            {typeFilter.length > 0 && (
              <Tag
                color="blue"
                closable
                onClose={() => {
                  setTypeFilter([])
                  setCurrentPage(1)
                }}
              >
                测试类型：{typeFilter.join('、')}
              </Tag>
            )}
            <Popover
              trigger="click"
              placement="bottomRight"
              title="选择显示列"
              content={
                <Space direction="vertical" size={12}>
                  <Checkbox
                    checked={visibleColumnKeys.length === optionalCaseColumnKeys.length}
                    indeterminate={visibleColumnKeys.length > 0 && visibleColumnKeys.length < optionalCaseColumnKeys.length}
                    onChange={(e) => setVisibleColumnKeys(e.target.checked ? [...optionalCaseColumnKeys] : [])}
                  >
                    全选
                  </Checkbox>
                  <Checkbox.Group<string> value={visibleColumnKeys} onChange={setVisibleColumnKeys}>
                    <Space direction="vertical">
                      {optionalColumns.map(column => (
                        <Checkbox key={String(column.key)} value={String(column.key)}>
                          {typeof column.title === 'string'
                            ? column.title
                            : String(column.key) === 'test_steps' ? '测试步骤' : String(column.key)}
                        </Checkbox>
                      ))}
                    </Space>
                  </Checkbox.Group>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    选择框、序号和操作列始终显示
                  </Text>
                </Space>
              }
            >
              <Button size="small">显示列 <DownOutlined /></Button>
            </Popover>
          </Space>
        }
      >
        <Table
          columns={visibleColumns}
          dataSource={filteredCases}
          rowKey="case_key"
          scroll={hasScrollableColumns ? { x: visibleTableWidth } : undefined}
          size="small"
          onChange={(pagination, filters) => {
            const rawFilter = filters.test_type
            const nextTypeFilter = Array.isArray(rawFilter) ? rawFilter.map(String) : []
            const typeFilterChanged =
              nextTypeFilter.length !== typeFilter.length ||
              nextTypeFilter.some((type) => !typeFilter.includes(type))
            setTypeFilter(nextTypeFilter)
            // 切换筛选后回到第一页；仅翻页时保留当前筛选
            setCurrentPage(typeFilterChanged ? 1 : pagination.current ?? 1)
          }}
          pagination={{
            current: currentPage,
            pageSize,
            showTotal: (total) => `共 ${total} 条`,
            showSizeChanger: false,
          }}
        />
      </Card>
        </>
      )}

      {/* ===== 执行日志 ===== */}
      <Card
        title="执行日志"
        extra={<Button type="link" size="small" onClick={() => navigate('/logs')}>单独查看 →</Button>}
        style={{ marginTop: 12 }}
      >
        <div className="log-terminal">
          {store.logs.length === 0 && (
            <div style={{ color: '#6b7280', textAlign: 'center', padding: '20px 0' }}>暂无日志</div>
          )}
          {store.logs.map((log, i) => (
            <div
              key={i}
              className={log.level === 'error' ? 'log-error' : log.level === 'warning' ? 'log-warning' : 'log-info'}
            >
              [{new Date(log.timestamp).toLocaleTimeString()}] <CollapsibleLogText message={log.message} />
            </div>
          ))}
        </div>
      </Card>

      {/* ===== 底部固定操作条 ===== */}
      <div className="execution-action-bar">
        <Space size={4} wrap>
          <Text style={{ fontSize: 12 }}>当前已选</Text>
          <Text strong style={{ fontSize: 16, color: '#2f54eb', lineHeight: 1 }}>
            {allSelectedCount}
          </Text>
          <Text style={{ fontSize: 12 }}>条用例</Text>
          {store.isRunning && <Tag color="processing" style={{ marginInlineEnd: 0 }}>执行中</Tag>}
        </Space>
        <Space size={6} wrap>
          <Button
            size="small"
            type="primary"
            icon={<PlayCircleOutlined />}
            onClick={handleStart}
            disabled={store.isRunning || allSelectedCount === 0}
          >
            开始执行
          </Button>
          <Button
            size="small"
            danger
            icon={<StopOutlined />}
            onClick={handleStop}
            disabled={!store.isRunning}
          >
            结束执行
          </Button>
          <Button
            size="small"
            icon={<CloseOutlined />}
            onClick={() => void handleDeselectAllCases()}
            disabled={allSelectedCount === 0}
          >
            取消选择全部
          </Button>
        </Space>
      </div>

      {/* ===== AI 分析抽屉 ===== */}
      <AIAnalysisDrawer
        open={aiDrawerOpen}
        onClose={() => { setAIDrawerOpen(false); setAIDrawerCase(null) }}
        testCase={aiDrawerCase}
        cachedAnalysis={
          aiDrawerCase
            ? aiAnalysisCache[aiDrawerCase.case_key || aiDrawerCase.case_id] || null
            : null
        }
        onAnalysisDone={handleAnalysisDone}
      />

      {/* ===== AI 报告弹窗 ===== */}
      <AIReportModal
        open={aiReportOpen}
        onClose={() => setAIReportOpen(false)}
        hasCases={store.testCases.length > 0}
      />

      {/* ===== 执行日志弹窗 ===== */}
      <CaseLogModal
        open={!!logModalCase}
        title={logModalCase ? `执行日志 - ${logModalCase.case_id}` : undefined}
        log={logModalCase ? extractLogText(logModalCase.remarks) : ''}
        status={logModalCase ? parseRemark(logModalCase.judgment || logModalCase.remarks).aiStatus : ''}
        evidence={
          logModalCase
            ? (logModalCase.ai_evidence?.length
                ? logModalCase.ai_evidence
                : extractAiEvidence(logModalCase.judgment || logModalCase.remarks))
            : []
        }
        manualEvidence={logModalCase?.manual_evidence}
        manualEvidenceLines={logModalCase?.manual_evidence_lines}
        onManualEvidenceChange={logModalCase
          ? (payload) => handleSaveManualEvidence(logModalCase, payload)
          : undefined}
        path={logModalCase?.log_file}
        caseKey={logModalCase?.case_key}
        onEdit={logModalCase ? () => {
          const target = logModalCase
          setLogModalCase(null)
          setResultLogEditCase(target)
        } : undefined}
        onClose={() => setLogModalCase(null)}
      />

      {/* ===== YUV 出图弹窗 ===== */}
      <CaseImagesModal
        open={!!imageModalCase}
        caseId={imageModalCase?.case_id || null}
        sourceSheet={imageModalCase?.source_sheet || ''}
        onClose={() => setImageModalCase(null)}
      />

      {/* ===== 即将执行命令预览弹窗 ===== */}
      <CommandPreviewModal
        open={previewCommandKeys !== null}
        caseKeys={previewCommandKeys || []}
        onClose={() => setPreviewCommandKeys(null)}
      />

      {/* ===== 测试步骤编写规则弹窗 ===== */}
      <TestStepRulesModal
        open={stepRulesOpen}
        onClose={() => setStepRulesOpen(false)}
      />

      {/* ===== 测试步骤编辑弹窗 ===== */}
      <TestCaseStepsEditModal
        open={!!stepEditCase}
        title={stepEditCase ? `编辑测试步骤 - ${stepEditCase.case_id}` : undefined}
        value={stepEditCase?.test_steps || ''}
        loading={savingSteps}
        onCancel={() => setStepEditCase(null)}
        onSave={handleSaveStepEdit}
      />

      {/* ===== AI 重写测试步骤 diff 确认弹窗 ===== */}
      <TestStepsRewriteDiffModal
        open={!!stepRewrite}
        caseId={stepRewrite?.caseId}
        data={stepRewrite?.data || null}
        loading={applyingStepRewrite}
        onCancel={() => {
          if (applyingStepRewrite) return
          setStepRewrite(null)
        }}
        onApply={handleApplyStepRewrite}
      />

      {/* ===== 预期结果编辑弹窗 ===== */}
      <TestCaseStepsEditModal
        open={!!expectedEditCase}
        title={expectedEditCase ? `编辑预期结果 - ${expectedEditCase.case_id}` : undefined}
        hint="每行一条预期结果；可使用「执行命令无报错」「帧率稳定在 30fps 左右」等可判定的描述。"
        value={expectedEditCase?.expected_result || ''}
        placeholder={'例如：\n1、执行命令无报错，可生成.raw文件\n2、raw可正常查看，无异常\n3、帧率稳定在 30fps 左右'}
        loading={savingExpected}
        monospace={false}
        onCancel={() => setExpectedEditCase(null)}
        onSave={handleSaveExpectedEdit}
      />

      {/* ===== 实际结果与执行日志编辑弹窗 ===== */}
      <CaseResultLogEditModal
        open={!!resultLogEditCase}
        title={resultLogEditCase ? `编辑实际结果与执行日志 - ${resultLogEditCase.case_id}` : undefined}
        resultText={resultLogEditCase ? getCaseResultText(resultLogEditCase) : ''}
        logText={resultLogEditCase ? extractLogText(resultLogEditCase.remarks) : ''}
        loading={savingResultLog}
        onCancel={() => setResultLogEditCase(null)}
        onSave={handleSaveResultLog}
      />

      {/* ===== 下载结果：选择要导出的用例表 ===== */}
      <Modal
        open={downloadOpen}
        title="下载结果"
        okText="下载"
        cancelText="取消"
        confirmLoading={downloadLoading}
        okButtonProps={{
          disabled: downloadSelectedOnly
            ? selectedCaseKeys.length === 0
            : downloadSheets.length === 0,
        }}
        onOk={() => void handleDownloadFromDialog()}
        onCancel={() => {
          if (!downloadLoading) setDownloadOpen(false)
        }}
      >
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          {downloadLoading && (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                <Text>{downloadProgress?.message || '正在导出结果...'}</Text>
                {downloadProgress && downloadProgress.case_total ? (
                  <Text type="secondary">
                    用例 {Math.min(downloadProgress.case_current || 0, downloadProgress.case_total)}
                    /{downloadProgress.case_total}
                  </Text>
                ) : downloadPercent > 0 && (
                  <Text type="secondary">{downloadPercent}%</Text>
                )}
              </div>
              <Progress
                percent={downloadPercent}
                status={downloadProgress?.done ? 'success' : 'active'}
                showInfo={false}
                style={{ marginTop: 6 }}
              />
              {downloadProgress?.case_id && (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  当前用例：{downloadProgress.case_id}
                  {downloadProgress.case_total
                    ? `（共 ${downloadProgress.case_total} 条待处理）`
                    : ''}
                </Text>
              )}
            </div>
          )}
          <div>
            <Checkbox
              checked={downloadSelectedOnly}
              disabled={downloadLoading || selectedCount === 0}
              onChange={(e) => setDownloadSelectedOnly(e.target.checked)}
            >
              只覆盖选中的用例（当前勾选 {selectedCount} 条）
            </Checkbox>
            {selectedCount === 0 && (
              <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
                先在用例列表勾选用例后可启用
              </Text>
            )}
          </div>

          <div>
            <Space size={8} wrap>
              <Text strong>要更新结果的用例表</Text>
              <Button
                size="small"
                onClick={() => setDownloadSheets(downloadSheetOptions)}
                disabled={downloadLoading || downloadSelectedOnly}
              >
                全选
              </Button>
              <Button
                size="small"
                onClick={() => setDownloadSheets([])}
                disabled={downloadLoading || downloadSelectedOnly || downloadSheets.length === 0}
              >
                清空
              </Button>
              {downloadSheetOptions.includes(store.currentSheet) && (
                <Button
                  size="small"
                  onClick={() => setDownloadSheets([store.currentSheet])}
                  disabled={downloadLoading || downloadSelectedOnly}
                >
                  仅当前页签
                </Button>
              )}
            </Space>
            <div style={{ marginTop: 10 }}>
              <Checkbox.Group
                value={downloadSheets}
                disabled={downloadLoading || downloadSelectedOnly}
                onChange={(values) => setDownloadSheets(values.map(String))}
                options={downloadSheetOptions.map((name) => ({ label: name, value: name }))}
                style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
              />
            </div>
          </div>

          <Checkbox
            checked={allDownloadSheetsSelected && downloadRegenerateStats}
            disabled={downloadLoading || !allDownloadSheetsSelected || downloadSelectedOnly}
            onChange={(e) => setDownloadRegenerateStats(e.target.checked)}
          >
            重新生成「数据统计」页内容（AI 汇总，耗时较长）
          </Checkbox>

          {downloadSelectedOnly ? (
            <Alert
              type="info"
              showIcon
              message="只覆盖选中的用例"
              description="下载文件保留原工作簿的全部工作表与其它用例的原有内容，只把当前勾选用例的执行结果、日志图片与用例截图写入副本；「数据统计」页与 BugList 也不会更新。"
            />
          ) : allDownloadSheetsSelected ? (
            <Text type="secondary" style={{ fontSize: 12 }}>
              更新全部用例表，并在勾选时重新生成「数据统计」页；其它工作表保持工作簿原有内容。
            </Text>
          ) : (
            <Alert
              type="info"
              showIcon
              message="只修改勾选的用例表"
              description="下载文件保留原工作簿的全部工作表，只有勾选的用例表会写入本次执行结果、日志图片与用例截图；其它工作表与「数据统计」页保持原样，因此无需重新生成统计页。"
            />
          )}
        </Space>
      </Modal>

      {/* ===== 执行日志草稿箱 ===== */}
      <Drawer
        title="执行日志草稿箱"
        placement="right"
        width={680}
        open={draftBoxOpen}
        onClose={() => setDraftBoxOpen(false)}
      >
        <ExecutionDraftBox
          open={draftBoxOpen}
          cases={store.testCases}
          logs={store.logs}
          sourceFileName={store.sourceFileName}
          onRestore={handleRestoreDraftRequest}
          onDraftsChanged={setDraftCount}
        />
      </Drawer>

      {/* ===== 恢复日志草稿 ===== */}
      <Modal
        open={!!pendingRestoreDraft}
        title={pendingRestoreDraft ? `恢复日志草稿「${pendingRestoreDraft.name}」` : '恢复日志草稿'}
        onCancel={() => {
          if (!restoringLogs) setPendingRestoreDraft(null)
        }}
        footer={pendingRestoreDraft
          ? (
            <Space>
              <Button onClick={() => setPendingRestoreDraft(null)} disabled={restoringLogs}>取消</Button>
              <Button
                type="primary"
                icon={<ReloadOutlined />}
                loading={restoringLogs}
                disabled={pendingRestoreMatchCount === 0}
                onClick={() => void handleRestoreDirectly()}
              >
                直接恢复到当前用例（{pendingRestoreMatchCount} 条）
              </Button>
            </Space>
          )
          : null}
      >
        {pendingRestoreDraft && (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <Alert
              type="info"
              showIcon
              message="下载结果时执行日志会被渲染为图片，文本日志保存在草稿箱。恢复时请重新上传对应的测试用例文件，日志会写回用例并可再次随结果下载（文字模式保留文本）。"
            />
            <Space direction="vertical" size={4}>
              <Text>工作簿：{pendingRestoreDraft.workbookName || '-'}</Text>
              <Text>用例日志：{pendingRestoreDraft.cases.length} 条（当前可匹配 {pendingRestoreMatchCount} 条）</Text>
              <Text>运行日志：{pendingRestoreDraft.logs.length} 条</Text>
              <Text>保存时间：{formatDraftTime(pendingRestoreDraft.updatedAt)}</Text>
            </Space>
            <Upload
              accept=".xlsx,.xls"
              showUploadList={false}
              beforeUpload={(file) => { void handleRestoreUpload(file); return false }}
            >
              <Button type="primary" icon={<UploadOutlined />} loading={restoringLogs}>
                重新上传测试用例文件并恢复
              </Button>
            </Upload>
            <Text type="secondary" style={{ fontSize: 12 }}>
              若重新上传的用例文件与草稿中的用例编号一致，日志会同时写回后端会话；
              恢复后即可在「实际结果」栏查看日志，或在草稿箱中导出日志文本。
            </Text>
          </Space>
        )}
      </Modal>
    </div>
  )
}
