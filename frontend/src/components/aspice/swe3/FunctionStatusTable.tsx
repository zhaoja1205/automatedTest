/**
 * SWE.3 推送 G：函数状态面板（扁平化展示 scan_cache 里所有函数）。
 *
 * 功能：
 *   1. 按模块展示扫描到的所有函数，附 `diff_status` / `is_sdk` 彩色 Tag
 *   2. 用户可勾选"豁免 AI"列，决策 3 → `exempt_from_ai`
 *   3. AI 流程图状态列：pending / ok / failed（可重试） / exception
 *   4. 顶部 BaselineBanner：显示/编辑 baseline SHA + 改动文件清单（手工粘贴版）
 *   5. 全组件级 scanBusy/aiBusy 遮罩（决策 1：锁 UI，Toast 完成/失败）
 *
 * 不含：
 *   - isomorphic-git 自动 diff（下阶段加）
 *   - PlantUML 预览（走已有本地 PlantUML 服务）
 */
import { useEffect, useMemo, useState } from 'react'
import {
  Card, Table, Tag, Checkbox, Button, Space, message, Spin, Alert, Modal,
  Input, Typography, Tabs, Radio, Progress,
} from 'antd'
import {
  ReloadOutlined, WarningOutlined, CheckCircleOutlined,
  ClockCircleOutlined, StopOutlined, EditOutlined, ThunderboltOutlined,
  FilterOutlined, MinusCircleOutlined,
} from '@ant-design/icons'
import {
  getModuleScan, setFunctionExempt, markFunctionException,
  augmentOneWithRetry, getBaseline, putBaseline, reclassifyAll,
  putFocusFunctions,
} from '../../../api/aspiceApi'
import type { Swe3BaselineDiff } from '../../../api/aspiceApi'
import type { Swe3Module, Swe3ScannedFunction } from '../../../types/aspice'
import { useAspiceStore } from '../../../stores/useAspiceStore'
// EngineeringScanner 已上移到 Swe3Step 的 "工程代码上传" 面板统一入口，这里不再 import。

const { TextArea } = Input
const { Text, Paragraph } = Typography

interface Props {
  projectId: string
  modules: Swe3Module[]  // 从 push_d.swe3.modules，提供 component_id/name
}

interface FlatFn extends Swe3ScannedFunction {
  _componentId: string
  _className: string
  _file: string
}

/** 把一个模块的 scan 结果扁平为 FlatFn[]。 */
function flattenScan(componentId: string, scan: any): FlatFn[] {
  if (!scan?.files) return []
  const out: FlatFn[] = []
  for (const f of scan.files) {
    for (const cls of f.classes || []) {
      for (const fn of cls.functions || []) {
        out.push({
          ...fn,
          _componentId: componentId,
          _className: cls.name,
          _file: f.path,
        })
      }
    }
  }
  return out
}

function DiffStatusTag({ status }: { status?: string }) {
  if (!status) return <Tag color="default">未分类</Tag>
  const map: Record<string, { color: string; label: string }> = {
    added: { color: 'green', label: '新增' },
    modified: { color: 'orange', label: '改动' },
    unchanged: { color: 'default', label: '未改' },
    unchanged_sdk: { color: 'blue', label: 'SDK' },
  }
  const { color, label } = map[status] || { color: 'default', label: status }
  return <Tag color={color}>{label}</Tag>
}

function AIStatusCell(props: {
  fn: FlatFn
  onRetry: (fn: FlatFn) => void
  onMarkException: (fn: FlatFn) => void
  aiBusy: boolean
}) {
  const { fn, onRetry, onMarkException, aiBusy } = props
  const status = fn.ai_status || (fn.ai_flowchart ? 'ok' : 'pending')
  if (fn.exempt_from_ai) {
    return (
      <Space size={4}>
        <Tag icon={<StopOutlined />} color="purple">已豁免</Tag>
        <Text type="secondary" style={{ fontSize: 12 }}>由人工补</Text>
      </Space>
    )
  }
  if (fn.is_sdk && (fn.diff_status === 'unchanged_sdk' || fn.diff_status === 'unchanged')) {
    return <Tag color="blue">SDK·不画</Tag>
  }
  if (status === 'ok') {
    return <Tag icon={<CheckCircleOutlined />} color="success">OK</Tag>
  }
  if (status === 'failed') {
    return (
      <Space size={4}>
        <Tag icon={<WarningOutlined />} color="warning">失败 x{fn.ai_retry_count || 0}</Tag>
        <Button size="small" type="link" disabled={aiBusy}
          icon={<ReloadOutlined />} onClick={() => onRetry(fn)}>重试</Button>
        <Button size="small" type="link" danger disabled={aiBusy}
          onClick={() => onMarkException(fn)}>标异常</Button>
      </Space>
    )
  }
  if (status === 'exception') {
    return (
      <Space size={4}>
        <Tag icon={<StopOutlined />} color="red">异常</Tag>
        <Button size="small" type="link" disabled={aiBusy}
          icon={<ReloadOutlined />} onClick={() => onRetry(fn)}>重试</Button>
      </Space>
    )
  }
  return (
    <Space size={4}>
      <Tag icon={<ClockCircleOutlined />} color="default">待生成</Tag>
      <Button size="small" type="link" disabled={aiBusy}
        onClick={() => onRetry(fn)}>生成</Button>
    </Space>
  )
}

/** Baseline 手动编辑弹窗（降级方案，等前端 isomorphic-git 接入后替换）。 */
function BaselineModal(props: {
  open: boolean
  value: Swe3BaselineDiff | null
  onCancel: () => void
  onOk: (diff: Swe3BaselineDiff) => void
}) {
  const { open, value, onCancel, onOk } = props
  const [commit, setCommit] = useState('')
  const [changedRaw, setChangedRaw] = useState('')
  const [addedRaw, setAddedRaw] = useState('')
  useEffect(() => {
    if (open) {
      setCommit(value?.baseline_commit || '')
      setChangedRaw((value?.changed_files || []).join('\n'))
      setAddedRaw((value?.added_files || []).join('\n'))
    }
  }, [open, value])

  const splitLines = (s: string) =>
    s.split('\n').map((x) => x.trim()).filter(Boolean)

  return (
    <Modal open={open} title="设置 baseline（人工模式）" width={720}
      onCancel={onCancel}
      onOk={() => onOk({
        baseline_commit: commit.trim(),
        changed_files: splitLines(changedRaw),
        added_files: splitLines(addedRaw),
      })}>
      <Alert type="info" showIcon style={{ marginBottom: 12 }}
        message="此为降级方案：把 git diff baseline..HEAD 的输出手工粘进来。后续会接入 isomorphic-git 自动完成。" />
      <Paragraph>
        <Text strong>baseline commit（SHA 或 ref）：</Text>
      </Paragraph>
      <Input value={commit} onChange={(e) => setCommit(e.target.value)}
        placeholder="如：v1.0.0 / abc1234" style={{ marginBottom: 12 }} />
      <Paragraph>
        <Text strong>已改动文件列表（相对工程根，一行一个）：</Text>
      </Paragraph>
      <TextArea rows={6} value={changedRaw}
        onChange={(e) => setChangedRaw(e.target.value)}
        placeholder="src/foo.cpp&#10;include/bar.h" style={{ marginBottom: 12 }} />
      <Paragraph>
        <Text strong>新增文件列表（相对工程根，一行一个）：</Text>
      </Paragraph>
      <TextArea rows={4} value={addedRaw}
        onChange={(e) => setAddedRaw(e.target.value)}
        placeholder="src/new_driver.cpp" />
    </Modal>
  )
}

export default function FunctionStatusTable({ projectId, modules }: Props) {
  const [scansByModule, setScansByModule] = useState<Record<string, any>>({})
  const [loading, setLoading] = useState(false)
  const [aiBusy, setAiBusy] = useState(false)
  const [activeCid, setActiveCid] = useState<string>('')
  const [baseline, setBaseline] = useState<Swe3BaselineDiff | null>(null)
  const [baselineModalOpen, setBaselineModalOpen] = useState(false)
  // B 方案联动：'focus' = 只看关注函数（默认，推送 G 的正式视角）；'all' = 全扫描结果（排错/复查）
  const [viewMode, setViewMode] = useState<'focus' | 'all'>('focus')
  // 从 store 读/写关注函数清单（按 component_id 查到 focused_keys 集合）
  const focusFunctions = useAspiceStore((s) => s.aspice?.swe3?.push_d?.focus_functions || [])
  const setSwe3FocusFunctions = useAspiceStore((s) => s.setSwe3FocusFunctions)

  // 1B：表格多选，用于批量取消关注
  const [selectedKeys, setSelectedKeys] = useState<string[]>([])
  // 2C 实时过滤：文件路径 include/exclude 子串（当前模块本地过滤，不改后端规则）
  const [pathInclude, setPathInclude] = useState('')
  const [pathExclude, setPathExclude] = useState('')
  // 3A 批量生成流程图进度
  const [batchBusy, setBatchBusy] = useState(false)
  const [batchProgress, setBatchProgress] = useState<{ done: number; total: number; ok: number; fail: number } | null>(null)

  const moduleList = useMemo(() => modules.filter((m) => m.component_id), [modules])

  useEffect(() => {
    if (moduleList.length && !activeCid) {
      setActiveCid(moduleList[0].component_id)
    }
  }, [moduleList, activeCid])

  const loadAll = async () => {
    setLoading(true)
    try {
      const res: Record<string, any> = {}
      await Promise.all(moduleList.map(async (m) => {
        try {
          const r = await getModuleScan(projectId, m.component_id)
          res[m.component_id] = r.data
        } catch { /* 未扫描 */ }
      }))
      setScansByModule(res)
      try {
        const bl = await getBaseline(projectId)
        setBaseline(bl.data && bl.data.baseline_commit ? bl.data : null)
      } catch { /* 无 */ }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (projectId && moduleList.length) loadAll()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, moduleList.length])

  const activeScan = scansByModule[activeCid]
  // 当前模块所有函数（扁平化）
  const allFns = useMemo(
    () => flattenScan(activeCid, activeScan), [activeCid, activeScan])
  // 当前模块的"关注函数"key 集合
  const focusKeys = useMemo(() => {
    const entry = focusFunctions.find((f) => f.component_id === activeCid)
    return new Set((entry?.focused_keys) || [])
  }, [focusFunctions, activeCid])
  // B 方案：'focus' 模式下只保留关注函数；'all' 保留全部
  // 2C 实时过滤：再叠加文件路径 include/exclude 子串过滤（切模块或改 viewMode 不丢）
  const flatFns = useMemo(() => {
    let out = viewMode === 'focus' ? allFns.filter((f) => focusKeys.has(f.key)) : allFns
    const inc = pathInclude.trim().toLowerCase()
    const exc = pathExclude.trim().toLowerCase()
    if (inc) {
      // 逗号/空格分隔的多关键字：任意一个命中即通过（OR）
      const tokens = inc.split(/[,\s]+/).filter(Boolean)
      if (tokens.length) out = out.filter((f) => tokens.some((t) => f._file.toLowerCase().includes(t)))
    }
    if (exc) {
      const tokens = exc.split(/[,\s]+/).filter(Boolean)
      if (tokens.length) out = out.filter((f) => !tokens.some((t) => f._file.toLowerCase().includes(t)))
    }
    return out
  }, [allFns, focusKeys, viewMode, pathInclude, pathExclude])

  const handleToggleExempt = async (fn: FlatFn, exempt: boolean) => {
    try {
      await setFunctionExempt(projectId, fn._componentId, fn.key, exempt)
      // 本地刷新
      setScansByModule((prev) => {
        const scan = prev[fn._componentId]
        if (!scan) return prev
        for (const file of scan.files || []) {
          for (const cls of file.classes || []) {
            for (const f of cls.functions || []) {
              if (f.key === fn.key) f.exempt_from_ai = exempt
            }
          }
        }
        return { ...prev, [fn._componentId]: { ...scan } }
      })
      message.success(exempt ? '已标记豁免 AI' : '已取消豁免')
    } catch (e: any) {
      message.error('操作失败：' + (e.message || e))
    }
  }

  const handleRetry = async (fn: FlatFn) => {
    setAiBusy(true)
    try {
      message.loading({ content: `正在为 ${fn.name} 生成流程图…`, key: 'ai', duration: 0 })
      const r = await augmentOneWithRetry(projectId, fn._componentId, fn.key, 3)
      const status = r.data.ai_status
      setScansByModule((prev) => {
        const scan = prev[fn._componentId]
        if (!scan) return prev
        for (const file of scan.files || []) {
          for (const cls of file.classes || []) {
            for (const f of cls.functions || []) {
              if (f.key === fn.key) {
                f.ai_status = status
                f.ai_retry_count = r.data.ai_retry_count
                f.ai_last_error = r.data.ai_last_error
                f.ai_flowchart = r.data.ai_flowchart
                // 后端 augment-one-retry 现在同步生成 ai_intro，顺手回灌
                if (r.data.ai_intro) f.ai_intro = r.data.ai_intro
              }
            }
          }
        }
        return { ...prev, [fn._componentId]: { ...scan } }
      })
      if (status === 'ok') {
        message.success({ content: `✓ ${fn.name} 流程图已生成`, key: 'ai' })
      } else {
        message.warning({
          content: `${fn.name} 生成失败（${r.data.ai_last_error || '未知'}），可继续重试或标异常`,
          key: 'ai', duration: 6,
        })
      }
    } catch (e: any) {
      message.error({
        content: '调用失败：' + (e?.response?.data?.detail || e.message || e),
        key: 'ai', duration: 8,
      })
    } finally {
      setAiBusy(false)
    }
  }

  const handleMarkException = async (fn: FlatFn) => {
    // R4：标异常前让用户填一个短注释（可空），会写入 docx 占位文案，便于 reviewer 找回场景
    Modal.confirm({
      title: `标记「${fn.name}」为异常`,
      content: (
        <div>
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            message="标异常后，批量生成将跳过此函数，导出 docx 时流程图位置会显示该注释，交人工补充"
          />
          <Text type="secondary">可选：补充一句话说明为什么标异常（空则只显示通用提示）</Text>
          <Input.TextArea
            id="aspice-exception-note-input"
            rows={3}
            placeholder="如：此函数依赖硬件状态机，流程图需人工按硬件时序手绘"
            style={{ marginTop: 8 }}
          />
        </div>
      ),
      okText: '标为异常',
      cancelText: '取消',
      onOk: async () => {
        const el = document.getElementById('aspice-exception-note-input') as HTMLTextAreaElement | null
        const note = (el?.value || '').trim()
        try {
          await markFunctionException(projectId, fn._componentId, fn.key, true, note)
          setScansByModule((prev) => {
            const scan = prev[fn._componentId]
            if (!scan) return prev
            for (const file of scan.files || []) {
              for (const cls of file.classes || []) {
                for (const f of cls.functions || []) {
                  if (f.key === fn.key) {
                    f.ai_status = 'exception'
                    if (note) f.ai_exception_note = note
                  }
                }
              }
            }
            return { ...prev, [fn._componentId]: { ...scan } }
          })
          message.success('已标记为异常，由人工处理')
        } catch (e: any) {
          message.error('标记失败：' + (e.message || e))
        }
      },
    })
  }

  const handleSaveBaseline = async (diff: Swe3BaselineDiff) => {
    setLoading(true)
    try {
      await putBaseline(projectId, diff)
      await reclassifyAll(projectId)
      setBaseline(diff)
      setBaselineModalOpen(false)
      message.success('baseline 已更新，所有模块函数已重新分类')
      await loadAll()
    } catch (e: any) {
      message.error('保存失败：' + (e.message || e))
    } finally {
      setLoading(false)
    }
  }

  /** 1B：批量取消当前模块的关注（selectedKeys → focused_keys 差集） */
  const handleBatchUnfocus = async () => {
    if (!activeCid || selectedKeys.length === 0) return
    const entry = focusFunctions.find((f) => f.component_id === activeCid)
    if (!entry) {
      message.info('当前模块尚未设置关注函数')
      return
    }
    const nextKeys = (entry.focused_keys || []).filter((k) => !selectedKeys.includes(k))
    const removedCount = (entry.focused_keys || []).length - nextKeys.length
    if (removedCount === 0) {
      message.info('勾选的函数本来就不在关注清单里')
      return
    }
    try {
      const res = await putFocusFunctions(projectId, activeCid, {
        focused_keys: nextKeys,
        manual_additions: entry.manual_additions,
      })
      setSwe3FocusFunctions(activeCid, res.data)
      setSelectedKeys([])
      message.success(`已取消关注 ${removedCount} 个函数（剩余 ${nextKeys.length}）`)
    } catch (e: any) {
      message.error('取消关注失败：' + (e?.response?.data?.detail || e.message || e))
    }
  }

  /**
   * 3A：批量为当前模块的"关注 ∩ 改动（added/modified）"函数生成流程图。
   * 串行跑，失败继续，exempt / SDK·不画 / 已 OK / 已标 exception 跳过。
   * exception 是用户显式选择"交人工处理"的状态，自动流程不再骚扰；
   * 如需重跑，用户在该函数行上单点"重试"按钮。
   */
  const handleBatchGenerate = async () => {
    const targets = allFns.filter((fn) => {
      if (!focusKeys.has(fn.key)) return false
      if (fn.exempt_from_ai) return false
      // SDK·不画 场景跳过（未改 + is_sdk）
      if (fn.is_sdk && (fn.diff_status === 'unchanged_sdk' || fn.diff_status === 'unchanged')) return false
      // 只跑改动/新增
      if (fn.diff_status !== 'added' && fn.diff_status !== 'modified') return false
      // 已经 OK 的跳过（重试走单条按钮）；已标 exception 的也跳过（用户决定交人工）
      const status = fn.ai_status || (fn.ai_flowchart ? 'ok' : 'pending')
      if (status === 'ok') return false
      if (status === 'exception') return false
      return true
    })
    if (targets.length === 0) {
      message.info('当前模块暂无「关注 ∩ 改动 ∩ 未生成」函数')
      return
    }
    Modal.confirm({
      title: `一键生成当前模块所有改动函数流程图`,
      content: `将对 ${targets.length} 个函数串行调 AI。过程中请勿关闭页面。失败的会标记并继续，完成后可对失败的单独重试或标异常。`,
      okText: `开始生成 (${targets.length})`,
      cancelText: '取消',
      onOk: async () => {
        setBatchBusy(true)
        setAiBusy(true)
        setBatchProgress({ done: 0, total: targets.length, ok: 0, fail: 0 })
        let ok = 0
        let fail = 0
        for (let i = 0; i < targets.length; i++) {
          const fn = targets[i]
          try {
            message.loading({
              content: `(${i + 1}/${targets.length}) 正在生成 ${fn.name}…`,
              key: 'batch-ai', duration: 0,
            })
            const r = await augmentOneWithRetry(projectId, fn._componentId, fn.key, 3)
            const status = r.data.ai_status
            setScansByModule((prev) => {
              const scan = prev[fn._componentId]
              if (!scan) return prev
              for (const file of scan.files || []) {
                for (const cls of file.classes || []) {
                  for (const f of cls.functions || []) {
                    if (f.key === fn.key) {
                      f.ai_status = status
                      f.ai_retry_count = r.data.ai_retry_count
                      f.ai_last_error = r.data.ai_last_error
                      f.ai_flowchart = r.data.ai_flowchart
                      // 后端 augment-one-retry 现在同步生成 ai_intro，顺手回灌
                      if (r.data.ai_intro) f.ai_intro = r.data.ai_intro
                    }
                  }
                }
              }
              return { ...prev, [fn._componentId]: { ...scan } }
            })
            if (status === 'ok') ok++
            else fail++
          } catch (e: any) {
            // 打到 console 方便诊断 404/500 这种模块没扫等场景
            console.warn(`[batch ai] ${fn.name} 调用失败:`,
                         e?.response?.data?.detail || e.message || e)
            fail++
          }
          setBatchProgress({ done: i + 1, total: targets.length, ok, fail })
        }
        message.success({
          content: `✓ 批量完成：成功 ${ok} / 失败 ${fail}。失败的可在表格里单条重试或标异常。`,
          key: 'batch-ai', duration: 8,
        })
        setBatchBusy(false)
        setAiBusy(false)
      },
    })
  }

  // 统计
  const stats = useMemo(() => {
    const s = { added: 0, modified: 0, unchanged: 0, unchanged_sdk: 0,
                ai_ok: 0, ai_failed: 0, ai_exception: 0, exempt: 0 }
    for (const fn of flatFns) {
      const ds = fn.diff_status || 'modified'
      // @ts-ignore
      s[ds] = (s[ds] || 0) + 1
      if (fn.exempt_from_ai) s.exempt++
      else if (fn.ai_status === 'ok' || fn.ai_flowchart) s.ai_ok++
      else if (fn.ai_status === 'failed') s.ai_failed++
      else if (fn.ai_status === 'exception') s.ai_exception++
    }
    return s
  }, [flatFns])

  // B 方案的核心交叉统计：关注函数 ∩ 改动。即使当前在 'all' 模式也计算全模块的，
  // 让用户能看到"真正要走 AI 流程图的有多少个"。
  const focusDiffStats = useMemo(() => {
    const s = { focus_total: 0, focus_changed: 0, focus_added: 0, focus_unchanged: 0, focus_sdk: 0 }
    for (const fn of allFns) {
      if (!focusKeys.has(fn.key)) continue
      s.focus_total++
      const ds = fn.diff_status
      if (ds === 'added') s.focus_added++
      else if (ds === 'modified') s.focus_changed++
      else if (ds === 'unchanged_sdk') s.focus_sdk++
      else s.focus_unchanged++
    }
    return s
  }, [allFns, focusKeys])

  // 3A：待批量生成的目标数（关注 ∩ 改动 ∩ 未 OK ∩ 未异常 ∩ 未豁免 ∩ 非 SDK·不画）
  const batchTargetCount = useMemo(() => {
    let n = 0
    for (const fn of allFns) {
      if (!focusKeys.has(fn.key)) continue
      if (fn.exempt_from_ai) continue
      if (fn.is_sdk && (fn.diff_status === 'unchanged_sdk' || fn.diff_status === 'unchanged')) continue
      if (fn.diff_status !== 'added' && fn.diff_status !== 'modified') continue
      const s = fn.ai_status || (fn.ai_flowchart ? 'ok' : 'pending')
      if (s === 'ok') continue
      if (s === 'exception') continue
      n++
    }
    return n
  }, [allFns, focusKeys])

  const columns = [
    {
      title: '文件', dataIndex: '_file', width: 220,
      render: (t: string) => <Text style={{ fontSize: 12 }} code>{t}</Text>,
    },
    { title: '类', dataIndex: '_className', width: 120 },
    {
      title: '函数名', dataIndex: 'name', width: 160,
      render: (t: string, fn: FlatFn) => (
        <Space direction="vertical" size={0}>
          <Text strong>{t}</Text>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {fn.body_lines || 0} 行
          </Text>
        </Space>
      ),
    },
    {
      title: '改动', dataIndex: 'diff_status', width: 90,
      render: (s: string, fn: FlatFn) => fn.is_sdk
        ? <Tag color="blue">SDK</Tag>
        : <DiffStatusTag status={s} />,
    },
    {
      title: '豁免 AI', dataIndex: 'exempt_from_ai', width: 80,
      render: (v: boolean, fn: FlatFn) => (
        <Checkbox checked={!!v} disabled={aiBusy || (fn.is_sdk && fn.diff_status !== 'modified')}
          onChange={(e) => handleToggleExempt(fn, e.target.checked)} />
      ),
    },
    {
      title: 'AI 流程图', width: 220,
      render: (_: any, fn: FlatFn) => (
        <AIStatusCell fn={fn} onRetry={handleRetry}
          onMarkException={handleMarkException} aiBusy={aiBusy} />
      ),
    },
  ]

  if (!moduleList.length) {
    return <Alert type="info" message="暂无模块，请先在 SWE.3 组件编辑中创建模块。" />
  }

  return (
    <Spin spinning={loading} tip="加载扫描结果…">
      {aiBusy && (
        <Alert type="warning" showIcon style={{ marginBottom: 12 }}
          message="AI 正在生成，请勿关闭页面"
          description="重试中。完成后此条消息会消失，并弹出成功/失败 Toast。" />
      )}

      <Card
        size="small" title="Baseline 与改动分类" style={{ marginBottom: 12 }}
        extra={<Space>
          <Button icon={<EditOutlined />} onClick={() => setBaselineModalOpen(true)}>
            {baseline ? '手动编辑 baseline' : '手动设置 baseline'}
          </Button>
          <Button
            icon={<ReloadOutlined />}
            loading={loading}
            onClick={async () => {
              // 先让后端按当前规则重跑 is_sdk + diff 分类，再 loadAll 拉回最新 scan
              // 这个按钮同时也解决老 scan cache 里 is_sdk 字段过时的问题（比如 SDK 规则改了）
              try {
                await reclassifyAll(projectId)
                message.success({ content: '已按当前规则重新分类', key: 're' })
              } catch (e: any) {
                message.error({ content: '重新分类失败：' + (e.message || e), key: 're' })
              }
              await loadAll()
            }}
          >
            重新分类 + 刷新
          </Button>
        </Space>}
      >
        {baseline ? (
          <Space direction="vertical" size={4} style={{ width: '100%' }}>
            <Text>
              <Text strong>基线 commit：</Text>
              <Text code>{baseline.baseline_commit}</Text>
              {baseline.baseline_branch && <Text type="secondary"> @ {baseline.baseline_branch}</Text>}
            </Text>
            <Text type="secondary">
              改动 {baseline.changed_files?.length || 0} 文件 /
              新增 {baseline.added_files?.length || 0} 文件
            </Text>
          </Space>
        ) : (
          <Alert type="info" showIcon
            message="尚未设置 baseline：当前所有非 SDK 函数被保守标记为「改动」" />
        )}
      </Card>

      {/* 推送 G 第二轮的 EngineeringScanner 已上移到"工程代码上传"面板，这里不再重复渲染 */}

      <Tabs
        activeKey={activeCid}
        onChange={(k) => { setActiveCid(k); setSelectedKeys([]) }}
        items={moduleList.map((m) => {
          const scan = scansByModule[m.component_id]
          const count = scan?.stats?.total_functions ?? 0
          return {
            key: m.component_id,
            label: `${m.component_id} ${m.name} (${count})`,
          }
        })}
      />

      {/* B 方案联动条：关注函数 ∩ diff 四态的交叉视图 + 过滤模式切换 */}
      <Alert
        type={focusDiffStats.focus_total === 0 ? 'warning' : 'success'}
        showIcon
        style={{ marginBottom: 8 }}
        message={
          <Space wrap size={[12, 4]}>
            <Text strong>模块 {activeCid} 关注函数：</Text>
            <Tag color="purple">共 {focusDiffStats.focus_total} 关注</Tag>
            <Text type="secondary">其中：</Text>
            <Tag color="green">🆕 新增 {focusDiffStats.focus_added}</Tag>
            <Tag color="orange">✏️ 改动 {focusDiffStats.focus_changed}</Tag>
            <Tag color="default">未改 {focusDiffStats.focus_unchanged}</Tag>
            <Tag color="blue">SDK {focusDiffStats.focus_sdk}</Tag>
            <Text type="secondary" style={{ marginLeft: 8 }}>
              → 需走 AI 流程图：
              <Text strong style={{ color: '#fa8c16' }}>
                {' '}{focusDiffStats.focus_added + focusDiffStats.focus_changed}
              </Text> 个
            </Text>
          </Space>
        }
        description={focusDiffStats.focus_total === 0
          ? `该模块尚未在"关注函数选择"中勾选任何函数。推送 G 只对"关注函数 ∩ 改动"跑 AI 流程图——请先去上方勾选对外 API。`
          : undefined}
      />
      <Space style={{ marginBottom: 8 }}>
        <Text type="secondary">显示范围：</Text>
        <Radio.Group
          value={viewMode}
          onChange={(e) => setViewMode(e.target.value)}
          size="small"
          optionType="button"
          buttonStyle="solid"
        >
          <Radio.Button value="focus">
            🎯 只看关注函数（{focusKeys.size}）
          </Radio.Button>
          <Radio.Button value="all">
            🔍 全部扫描结果（{allFns.length}）
          </Radio.Button>
        </Radio.Group>
      </Space>

      <Alert type="info" showIcon style={{ marginBottom: 8 }}
        message={
          <Space wrap size={[12, 4]}>
            <Text>当前视图 <Text strong>{flatFns.length}</Text> 函数：</Text>
            <Tag color="green">新增 {stats.added}</Tag>
            <Tag color="orange">改动 {stats.modified}</Tag>
            <Tag color="default">未改 {stats.unchanged}</Tag>
            <Tag color="blue">SDK {stats.unchanged_sdk}</Tag>
            <Text type="secondary">·</Text>
            <Tag color="success">AI ✓ {stats.ai_ok}</Tag>
            <Tag color="warning">AI ✗ {stats.ai_failed}</Tag>
            <Tag color="error">异常 {stats.ai_exception}</Tag>
            <Tag color="purple">豁免 {stats.exempt}</Tag>
          </Space>
        }
      />

      {/* 3A：批量生成 + 1B：批量取消关注 工具栏 */}
      <Space wrap style={{ marginBottom: 8 }}>
        <Button
          type="primary"
          icon={<ThunderboltOutlined />}
          loading={batchBusy}
          disabled={aiBusy && !batchBusy}
          onClick={handleBatchGenerate}
        >
          🚀 一键生成当前模块所有改动函数流程图（{batchTargetCount}）
        </Button>
        <Button
          icon={<MinusCircleOutlined />}
          disabled={selectedKeys.length === 0 || batchBusy}
          onClick={handleBatchUnfocus}
        >
          批量取消关注（已选 {selectedKeys.length}）
        </Button>
        {batchProgress && (
          <Space size={8}>
            <Text type="secondary">批量进度：</Text>
            <Progress
              type="line"
              percent={Math.round((batchProgress.done / batchProgress.total) * 100)}
              size="small"
              style={{ width: 180 }}
            />
            <Tag color="success">OK {batchProgress.ok}</Tag>
            <Tag color="warning">失败 {batchProgress.fail}</Tag>
            <Text type="secondary">
              {batchProgress.done}/{batchProgress.total}
            </Text>
          </Space>
        )}
      </Space>

      {/* 2C 实时过滤：文件路径 include/exclude（本模块本地，纯 UI 过滤） */}
      <Space wrap style={{ marginBottom: 8 }}>
        <FilterOutlined style={{ color: '#888' }} />
        <Text type="secondary" style={{ fontSize: 12 }}>本地文件过滤：</Text>
        <Input
          size="small"
          allowClear
          style={{ width: 240 }}
          placeholder="包含关键字（逗号/空格分多个，OR）"
          value={pathInclude}
          onChange={(e) => setPathInclude(e.target.value)}
        />
        <Input
          size="small"
          allowClear
          style={{ width: 240 }}
          placeholder="排除关键字（逗号/空格分多个，OR）"
          value={pathExclude}
          onChange={(e) => setPathExclude(e.target.value)}
        />
        {(pathInclude || pathExclude) && (
          <Tag color="processing">本地过滤生效</Tag>
        )}
        <Text type="secondary" style={{ fontSize: 11 }}>
          若要永久排除某些目录，去上方"模块代码路径配置"加一条「排除」规则
        </Text>
      </Space>

      <Table
        rowKey="key"
        size="small"
        dataSource={flatFns}
        columns={columns as any}
        rowSelection={{
          selectedRowKeys: selectedKeys,
          onChange: (keys) => setSelectedKeys(keys as string[]),
          // 只允许多选关注函数（在 focus 模式）；all 模式也允许选，用于加/移关注
          getCheckboxProps: () => ({ disabled: batchBusy }),
        }}
        pagination={{ pageSize: 20, showSizeChanger: true }}
        locale={{ emptyText: `模块 ${activeCid} 尚未扫描或无函数` }}
      />

      <BaselineModal open={baselineModalOpen} value={baseline}
        onCancel={() => setBaselineModalOpen(false)}
        onOk={handleSaveBaseline} />
    </Spin>
  )
}
