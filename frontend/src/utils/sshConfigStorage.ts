/**
 * SSH 配置的浏览器本地配置集。
 *
 * 后端只保存「当前生效」的一份 SSH 配置；这里在 localStorage 中额外保存
 * 多套命名配置（例如不同板端、直连/跳板环境），页面可在其中随时切换。
 */
import type { SSHConfig } from '../types'

/** 本地 SSH 配置集的 localStorage key（同一浏览器所有标签页共享） */
export const SSH_CONFIG_PROFILES_KEY = 'automatedTest.sshConfigProfiles'

export interface SSHConfigProfile {
  id: string
  name: string
  config: SSHConfig
  /** 最近一次保存/更新时间（毫秒） */
  updatedAt: number
}

export interface StoredSSHProfiles {
  profiles: SSHConfigProfile[]
  /** 当前选中的本地配置；为 null 表示未选择 */
  activeId: string | null
}

const EMPTY_STATE: StoredSSHProfiles = { profiles: [], activeId: null }

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function asString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

function asNumber(value: unknown, fallback: number): number {
  const num = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(num) ? num : fallback
}

/** 新建本地配置时的默认值：直连模式 + 默认端口/超时，其余为空 */
export const EMPTY_SSH_CONFIG: SSHConfig = {
  login_mode: 'direct',
  host: '',
  port: 22,
  username: '',
  password: '',
  target_password: '',
  timeout: 30,
  jump_host: '',
  jump_port: 22,
  jump_username: '',
  jump_password: '',
}

/** 把外部数据归一成完整的 SSHConfig，避免旧数据/脏数据导致表单异常 */
export function normalizeSSHConfig(value: unknown): SSHConfig | null {
  if (!isRecord(value)) return null
  return {
    login_mode: value.login_mode === 'jump' ? 'jump' : 'direct',
    host: asString(value.host),
    port: asNumber(value.port, 22),
    username: asString(value.username),
    password: asString(value.password),
    target_password: asString(value.target_password),
    timeout: asNumber(value.timeout, 30),
    jump_host: asString(value.jump_host),
    jump_port: asNumber(value.jump_port, 22),
    jump_username: asString(value.jump_username),
    jump_password: asString(value.jump_password),
  }
}

/** 读取 localStorage 中的本地 SSH 配置集，无效时返回空集合 */
export function loadSSHProfiles(): StoredSSHProfiles {
  try {
    if (typeof localStorage === 'undefined') return { ...EMPTY_STATE }
    const raw = localStorage.getItem(SSH_CONFIG_PROFILES_KEY)
    if (!raw) return { ...EMPTY_STATE }
    const parsed: unknown = JSON.parse(raw)
    if (!isRecord(parsed)) return { ...EMPTY_STATE }

    const rawProfiles = Array.isArray(parsed.profiles) ? parsed.profiles : []
    const ids = new Set<string>()
    const profiles: SSHConfigProfile[] = []
    rawProfiles.forEach((item, index) => {
      if (!isRecord(item)) return
      const config = normalizeSSHConfig(item.config)
      if (!config) return
      const name = asString(item.name).trim() || `配置 ${index + 1}`
      let id = asString(item.id).trim()
      if (!id || ids.has(id)) id = createSSHProfileId()
      ids.add(id)
      profiles.push({
        id,
        name,
        config,
        updatedAt: asNumber(item.updatedAt, 0),
      })
    })

    const activeId = asString(parsed.activeId).trim()
    const activeExists = profiles.some(p => p.id === activeId)
    return { profiles, activeId: activeExists ? activeId : null }
  } catch {
    return { ...EMPTY_STATE }
  }
}

/** 保存本地 SSH 配置集到 localStorage（隐私模式/存储已满时静默降级） */
export function saveSSHProfiles(state: StoredSSHProfiles): void {
  try {
    if (typeof localStorage === 'undefined') return
    localStorage.setItem(SSH_CONFIG_PROFILES_KEY, JSON.stringify(state))
  } catch {
    // 忽略写入失败，页面仍可正常使用
  }
}

/** 生成本地配置 id（优先使用 crypto.randomUUID） */
export function createSSHProfileId(): string {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID()
    }
  } catch {
    // 回退到时间戳 + 随机数
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

/** 判断两份 SSH 配置是否有差异（用于决定是否同步到后端） */
export function isSSHConfigChanged(a: SSHConfig, b: SSHConfig): boolean {
  return JSON.stringify(a) !== JSON.stringify(b)
}
