/**
 * 用例生成模块的 localStorage 持久化工具。
 */
import type {
  FunctionalTestOptions,
  FunctionalTestSelection,
  GeneratedCase,
  SensorConfig,
} from '../../types/casegen'

const STORAGE_KEYS = {
  AUTO_SAVE: 'casegen.autosave',
  DRAFTS: 'casegen.drafts',
} as const

// ── 自动保存（当前编辑状态）──────────────────────────────

export interface AutoSaveData {
  current: number
  basicInfo: Record<string, string>
  platformPath: string
  fileName: string
  selectedPlatform: string
  /** 功能测试参数（raw图 + YUV + ro / al / th 读取） */
  functionalOptions?: FunctionalTestOptions
  /** 勾选的功能测试类型 */
  testSelection?: FunctionalTestSelection
  /** @deprecated 旧版仅含 raw图参数的草稿，读取时作为功能测试参数回退 */
  lightingOptions?: {
    image_path: string
    skip_frames: number
    write_frames: number
  }
  /** 已添加的 sensor 配置文件路径 */
  sensorPaths?: string[]
  /** 已读取的 sensor 配置（扁平化） */
  sensorConfigs?: SensorConfig[]
  generatedCasesCount: number
  exportedFilename: string
  generatedCases?: GeneratedCase[]
  platformConfigs?: Array<{
    name: string
    description: string
    enable_masks: string[]
    group_count: number
    module_count: number
    groups: any[]
    topology: any[]
  }>
  timestamp: number
}

let autoSaveTimer: ReturnType<typeof setTimeout> | null = null

/** 防抖保存自动状态 */
export function autosaveCurrentState(data: AutoSaveData): void {
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
  autoSaveTimer = setTimeout(() => {
    try {
      localStorage.setItem(STORAGE_KEYS.AUTO_SAVE, JSON.stringify(data))
    } catch { /* 忽略存储异常 */ }
  }, 500)
}

/** 读取自动保存的状态 */
export function loadAutoSave(): AutoSaveData | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.AUTO_SAVE)
    if (!raw) return null
    return JSON.parse(raw) as AutoSaveData
  } catch {
    return null
  }
}

/** 清除自动保存状态 */
export function clearAutoSave(): void {
  try {
    localStorage.removeItem(STORAGE_KEYS.AUTO_SAVE)
  } catch { /* ignore */ }
}

// ── 草稿箱（手动保存）───────────────────────────────────

export interface DraftItem {
  id: string
  name: string
  createdAt: number
  updatedAt: number
  data: AutoSaveData
}

/** 获取所有草稿 */
export function getAllDrafts(): DraftItem[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.DRAFTS)
    if (!raw) return []
    return JSON.parse(raw) as DraftItem[]
  } catch {
    return []
  }
}

/** 保存新草稿或更新已有草稿 */
export function saveDraft(draft: DraftItem): DraftItem {
  const drafts = getAllDrafts()
  const idx = drafts.findIndex((d) => d.id === draft.id)
  if (idx >= 0) {
    drafts[idx] = { ...draft, updatedAt: Date.now() }
  } else {
    drafts.push({ ...draft, createdAt: Date.now(), updatedAt: Date.now() })
  }
  try {
    localStorage.setItem(STORAGE_KEYS.DRAFTS, JSON.stringify(drafts))
  } catch { /* ignore */ }
  return drafts[idx >= 0 ? idx : drafts.length - 1]
}

/** 删除草稿 */
export function deleteDraft(id: string): boolean {
  const drafts = getAllDrafts().filter((d) => d.id !== id)
  try {
    localStorage.setItem(STORAGE_KEYS.DRAFTS, JSON.stringify(drafts))
    return true
  } catch {
    return false
  }
}

/** 格式化时间 */
export function formatDate(ts: number): string {
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
// ── 生成用例缓存（独立于自动保存，避免每次 autosave 都序列化大量用例）────────────

const GENERATED_CASES_KEY = 'casegen.generated_cases' as const

/** 保存生成的用例列表 */
export function saveGeneratedCases(cases: AutoSaveData['generatedCases']): void {
  try {
    localStorage.setItem(GENERATED_CASES_KEY, JSON.stringify(cases))
  } catch { /* ignore */ }
}

/** 读取保存的用例列表 */
export function loadGeneratedCases(): AutoSaveData['generatedCases'] {
  try {
    const raw = localStorage.getItem(GENERATED_CASES_KEY)
    if (!raw) return undefined
    return JSON.parse(raw) as AutoSaveData['generatedCases']
  } catch {
    return undefined
  }
}

/** 清除保存的用例列表 */
export function clearGeneratedCases(): void {
  try {
    localStorage.removeItem(GENERATED_CASES_KEY)
  } catch { /* ignore */ }
}
