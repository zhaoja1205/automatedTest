/**
 * PlantUML 渲染后端选择器（本地内网 server / 线上 plantuml.com）
 *
 * 用在 FlowchartPage / SeqDiagPage / SeqDiagWorkspacePage / ClassDiagWorkspacePage
 * 这 4 个"要渲染 PlantUML 图"的页面工具栏里 —— 选择持久化到 localStorage
 * （key = `plantuml_backend`），切一次全站生效，不用每次手动在每个页面选。
 *
 * 行为：
 *  - 初次挂载时请求 `/api/plantuml/backend` 拿到：
 *      - env 默认 backend（如果用户没选过，就显示这个）
 *      - local 是否可用（部署机没配 PLANTUML_LOCAL_URL / 不在 allowlist 时为 false）
 *    拿到前用户选 local 也允许，直接让后端 400 把原因回显出来
 *  - 用户选择 → localStorage.setItem，onChange 通知父级（可选）
 *  - 选 local 但后端标记不可用 → Select 里 local 项置灰
 *
 * 为什么用 localStorage 而不是全局 store：
 *  - 作用面只跟渲染器挂钩，跟业务 store（Zustand 里的 ASPICE 项目态）无关
 *  - localStorage 跨页刷新也在，跟"渲染器偏好"的语义最贴
 *  - 避免给 cppFlowchart.ts（纯函数工具）加 Zustand 依赖
 */
import { useEffect, useState } from 'react'
import { Select, Tooltip, Tag } from 'antd'
import { CloudOutlined, HomeOutlined } from '@ant-design/icons'

/** 可取的渲染后端：`local` = 内网 server，`cloud` = plantuml.com */
export type PlantUmlBackend = 'local' | 'cloud'

/** localStorage key —— cppFlowchart.ts 的 getBackendChoice() 也用这个 key */
const STORAGE_KEY = 'plantuml_backend'

interface BackendInfo {
  backend: PlantUmlBackend
  local_available: boolean
  local_url_hint: string | null
  cloud_url_hint: string
}

/**
 * 读 localStorage 里用户选的后端。没选过 / 值非法 → null。
 * 用 `null` 而不是 'cloud' 表示"跟后端默认走"——UI 上也显示"默认"而不是写死 cloud。
 */
function readChoice(): PlantUmlBackend | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === 'local' || v === 'cloud') return v
  } catch { /* ignore */ }
  return null
}

function writeChoice(v: PlantUmlBackend | null): void {
  try {
    if (v === null) localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, v)
  } catch { /* ignore */ }
}

interface Props {
  /** 可选回调：用户切后端时触发，父页可以用来重新渲染当前图 */
  onChange?: (backend: PlantUmlBackend | null) => void
  /** 紧凑模式（工具栏宽度紧张时用） */
  size?: 'small' | 'middle'
}

export default function PlantUmlBackendSelect({ onChange, size = 'small' }: Props) {
  const [choice, setChoice] = useState<PlantUmlBackend | null>(readChoice())
  const [info, setInfo] = useState<BackendInfo | null>(null)

  useEffect(() => {
    // 页面加载时拉一次后端 info —— 本来可以缓存，但这接口返回 <100B，不值得
    let aborted = false
    fetch('/api/plantuml/backend')
      .then(r => r.ok ? r.json() : null)
      .then(j => { if (!aborted && j) setInfo(j as BackendInfo) })
      .catch(() => { /* 后端挂了 Select 还能用，只是失去 local_available 提示 */ })
    return () => { aborted = true }
  }, [])

  const handleChange = (v: PlantUmlBackend | '__default__') => {
    const next: PlantUmlBackend | null = v === '__default__' ? null : v
    setChoice(next)
    writeChoice(next)
    onChange?.(next)
  }

  // 展示用：选了什么就显示什么，没选就显示 info.backend（env 默认，灰色）
  const current: PlantUmlBackend | '__default__' = choice ?? '__default__'
  const defaultFromServer = info?.backend ?? 'cloud'
  const localAvailable = info?.local_available ?? true  // info 未加载完 → 乐观允许

  const tooltipTitle = (
    <div style={{ fontSize: 12, lineHeight: 1.6 }}>
      <div><b>PlantUML 渲染后端</b></div>
      <div>· <b>本地内网 server</b>：实测 median 0.2s，118× 快于线上</div>
      <div>· <b>plantuml.com</b>：公网，10.10.134.116 挂了时兜底</div>
      <div>· <b>默认</b>：跟后端 PLANTUML_BACKEND 环境变量走（当前 <Tag color="blue" style={{ margin: 0 }}>{defaultFromServer}</Tag>）</div>
      {info?.local_url_hint && <div style={{ color: '#94a3b8', marginTop: 4 }}>本地 URL：{info.local_url_hint}</div>}
      {!localAvailable && <div style={{ color: '#dc2626', marginTop: 4 }}>⚠ 后端未配置本地 server</div>}
    </div>
  )

  return (
    <Tooltip title={tooltipTitle} placement="bottom">
      <Select
        size={size}
        value={current}
        onChange={handleChange}
        style={{ minWidth: 150 }}
        options={[
          {
            value: '__default__',
            label: <span style={{ color: '#64748b' }}>默认（{defaultFromServer}）</span>,
          },
          {
            value: 'local',
            disabled: !localAvailable,
            label: (
              <span>
                <HomeOutlined style={{ marginRight: 6, color: localAvailable ? '#059669' : '#cbd5e1' }} />
                本地内网 server
              </span>
            ),
          },
          {
            value: 'cloud',
            label: (
              <span>
                <CloudOutlined style={{ marginRight: 6, color: '#0284c7' }} />
                plantuml.com
              </span>
            ),
          },
        ]}
      />
    </Tooltip>
  )
}
