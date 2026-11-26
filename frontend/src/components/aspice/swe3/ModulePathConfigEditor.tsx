/**
 * SWE.3 推送 D — 模块代码路径配置编辑器。
 *
 * 一模块一卡片：glob 规则列表（含排除）、命中预览、"自动推测"、"扫描"按钮。
 * UI 版本：匹配预览和扫描都走 mock。真实版本接后端 API 即可。
 */
import { useEffect, useState, useMemo } from 'react'
import { Card, Input, Button, Space, Tag, Tabs, Tooltip, Popover, message, Switch } from 'antd'
import { PlusOutlined, DeleteOutlined, ThunderboltOutlined, ScanOutlined } from '@ant-design/icons'
import { useAspiceStore } from '../../../stores/useAspiceStore'
import type { Swe3ModuleCodeSource, Swe3PathPattern } from '../../../types/aspice'
import { guessPathPatterns } from '../../../mocks/swe3MockData'
import { previewMatch, scanModule, putPathConfig } from '../../../api/aspiceApi'

interface Props {
  /** 全部模块（取自 swe3.modules，用于显示 Tabs） */
  modules: Array<{ component_id: string; slug: string; name: string }>
}

export default function ModulePathConfigEditor({ modules }: Props) {
  const { projectId, aspice, setSwe3ModuleCodeSource, setSwe3ScanIndex } = useAspiceStore()
  const push_d = aspice?.swe3?.push_d
  const [active, setActive] = useState<string>(modules[0]?.component_id || '')

  if (!modules.length) {
    return <Tag>先确认模块列表</Tag>
  }

  const items = modules.map((mod) => {
    const src = push_d?.module_code_sources.find((m) => m.component_id === mod.component_id)
    const scanned = push_d?.scan_indices.find((m) => m.component_id === mod.component_id)
    const badge = scanned ? <Tag color="green">已扫 {scanned.stats.total_functions} 函数</Tag> : null
    return {
      key: mod.component_id,
      label: (
        <Space size={4}>
          <span>{mod.component_id} {mod.name}</span>
          {badge}
        </Space>
      ),
      children: (
        <ModuleCard
          key={mod.component_id}
          mod={mod}
          src={src}
          projectId={projectId}
          onSrcChange={(ns) => setSwe3ModuleCodeSource(mod.component_id, ns)}
          onScanned={(idx) => setSwe3ScanIndex(mod.component_id, idx)}
        />
      ),
    }
  })

  return (
    <Tabs
      tabPosition="left"
      size="small"
      activeKey={active}
      onChange={setActive}
      items={items}
      style={{ minHeight: 320 }}
    />
  )
}

export interface ModuleCardProps {
  mod: { component_id: string; slug: string; name: string }
  src?: Swe3ModuleCodeSource
  projectId: string | null
  onSrcChange: (src: Swe3ModuleCodeSource) => void
  onScanned: (idx: any) => void
}

/**
 * 单模块路径配置卡片 —— 现在被 SWE.2 §4 ModuleEditor 和 SWE.3 Step 共享。
 * 内部仅依赖 props 和全局 store 的 projectId，路径写入两边实时同步（底层都是
 * `push_d.module_code_sources` 一份），扫描产物都落 `scan_cache/<cid>.json`。
 */
export function ModuleCard({ mod, src, projectId, onSrcChange, onScanned }: ModuleCardProps) {
  const patterns: Swe3PathPattern[] = src?.path_patterns || []
  const [preview, setPreview] = useState<string[]>([])
  const [scanning, setScanning] = useState(false)

  // 实时命中预览
  const includePatterns = useMemo(
    () => patterns.filter((p) => !p.exclude).map((p) => p.pattern).filter(Boolean),
    [patterns],
  )
  const excludePatterns = useMemo(
    () => patterns.filter((p) => p.exclude).map((p) => p.pattern).filter(Boolean),
    [patterns],
  )
  useEffect(() => {
    if (!projectId || includePatterns.length === 0) {
      setPreview([])
      return
    }
    let cancelled = false
    const h = setTimeout(async () => {
      try {
        const res = await previewMatch(projectId, includePatterns, excludePatterns)
        if (!cancelled) setPreview(res.data.sample)
      } catch { /* 工程未上传时后端返回空列表，静默 */ }
    }, 300)
    return () => { cancelled = true; clearTimeout(h) }
  }, [projectId, JSON.stringify(includePatterns), JSON.stringify(excludePatterns)])

  /** 本地写入 + 后端持久化（patterns 修改时就立刻 PUT）。 */
  const persist = async (nextPatterns: Swe3PathPattern[]) => {
    const next: Swe3ModuleCodeSource = {
      component_id: mod.component_id,
      path_patterns: nextPatterns,
      last_scanned_at: src?.last_scanned_at,
      scan_hit_count: src?.scan_hit_count,
    }
    onSrcChange(next)
    if (projectId) {
      try { await putPathConfig(projectId, mod.component_id, nextPatterns) }
      catch (e: any) { message.error(e?.response?.data?.detail || '保存规则失败') }
    }
  }

  const updatePattern = (idx: number, patch: Partial<Swe3PathPattern>) => {
    const next = [...patterns]
    next[idx] = { ...next[idx], ...patch }
    persist(next)
  }
  const addPattern = () => persist([...patterns, { pattern: '', exclude: false }])
  const delPattern = (idx: number) => persist(patterns.filter((_, i) => i !== idx))
  const handleAutoGuess = () => {
    const guessed = guessPathPatterns(mod.slug).map((p) => ({ pattern: p, exclude: false }))
    persist([...patterns, ...guessed])
    message.success('已追加 2 条推测规则')
  }
  const handleScan = async () => {
    if (!projectId) return
    if (!includePatterns.length) {
      message.warning('请先添加至少 1 条包含规则')
      return
    }
    setScanning(true)
    try {
      const res = await scanModule(projectId, mod.component_id)
      const idx = res.data
      onScanned({
        component_id: mod.component_id,
        scanned_at: idx.scanned_at,
        scanner_version: idx.scanner_version,
        files: idx.files || [],
        stats: idx.stats,
      })
      onSrcChange({
        component_id: mod.component_id,
        path_patterns: patterns,
        last_scanned_at: idx.scanned_at,
        scan_hit_count: idx.stats.total_files,
      })
      message.success(`扫描完成：${idx.stats.total_classes} 类 / ${idx.stats.total_functions} 函数`)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || e?.message || '扫描失败')
    } finally {
      setScanning(false)
    }
  }

  return (
    <Card size="small"
      title={`${mod.component_id} ${mod.name}`}
      extra={
        <Space>
          <Button size="small" icon={<ThunderboltOutlined />} onClick={handleAutoGuess}>
            自动推测
          </Button>
          <Button size="small" type="primary" icon={<ScanOutlined />}
            loading={scanning} onClick={handleScan}>
            扫描本模块
          </Button>
        </Space>
      }>
      <div style={{ marginBottom: 8 }}>
        <Space>
          <span style={{ fontWeight: 500 }}>路径规则（glob）</span>
          <Button size="small" icon={<PlusOutlined />} onClick={addPattern}>添加规则</Button>
          <Tooltip title={
            <div style={{ fontSize: 12, lineHeight: 1.6 }}>
              支持任选以下写法，均自动递归扫描子目录：<br />
              1. <b>目录相对路径</b>：如 <code>nvsipl/devblk/devices/MAX96717FSerializerDriver</code><br />
              2. <b>裸目录名</b>：如 <code>src</code>（匹配工程下任意层级的 src 子树）<br />
              3. <b>fnmatch 通配</b>：如 <code>**/MAX*.cpp</code>、<code>include/**</code><br />
              首尾斜杠会自动忽略；路径分隔符统一用 '/'。
            </div>
          }>
            <Tag style={{ cursor: 'help' }}>写法说明 ?</Tag>
          </Tooltip>
        </Space>
      </div>
      {patterns.length === 0 ? (
        <Tag>尚未配置任何规则，请点"自动推测"或"添加规则"</Tag>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {patterns.map((p, idx) => (
            <Space key={idx}>
              <Switch size="small"
                checkedChildren="排除" unCheckedChildren="包含"
                checked={!!p.exclude}
                onChange={(v) => updatePattern(idx, { exclude: v })} />
              <Input size="small" style={{ width: 320 }}
                value={p.pattern}
                placeholder="目录路径，如 nvsipl/devblk/devices/MAX96717FSerializerDriver"
                onChange={(e) => updatePattern(idx, { pattern: e.target.value })} />
              <Button size="small" danger type="link"
                icon={<DeleteOutlined />} onClick={() => delPattern(idx)} />
            </Space>
          ))}
        </div>
      )}
      <div style={{ marginTop: 12 }}>
        <Space>
          <span style={{ fontWeight: 500 }}>命中预览：</span>
          {preview.length > 0 ? (
            <Popover content={
              <div style={{ maxWidth: 400 }}>
                {preview.map((f) => <div key={f} style={{ fontFamily: 'monospace', fontSize: 12 }}>📄 {f}</div>)}
              </div>
            }>
              <Tag color="blue" style={{ cursor: 'pointer' }}>命中 {preview.length} 个文件 ▼</Tag>
            </Popover>
          ) : includePatterns.length === 0 ? (
            <Tag>尚无包含规则</Tag>
          ) : (
            <Tooltip title="规则未匹配任何文件">
              <Tag color="red">命中 0</Tag>
            </Tooltip>
          )}
          {src?.last_scanned_at && (
            <Tag color="purple">上次扫描：{src.last_scanned_at}</Tag>
          )}
        </Space>
      </div>
    </Card>
  )
}
