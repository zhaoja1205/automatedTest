/**
 * SWE.2 §4 组件接口「从 SWE.3 scan 产物挑选 → 填外部/内部接口」picker。
 *
 * 数据链路：
 *   `push_d.module_code_sources[cid].path_patterns` (由内嵌 ModuleCard 维护)
 *     → `POST /swe3/modules/{cid}/scan` 产物
 *     → `GET  /swe3/modules/{cid}/scan` 读回
 *     → 这里把每个函数平摊成一行，让用户三态勾选 外/内/忽略
 *     → 「应用选择」把当前所选落到 `component.external_interfaces[]` / `internal_interfaces[]`
 *
 * 填充字段映射（与 InterfaceItem schema 对齐）：
 *   method      = fn.name
 *   source      = basename(file.path)              — 文件名（不带目录），给用户看是哪来的
 *   type        = '外部接口' | '内部接口'           — 前端 type 是"方向"字面量，不是 C 返回类型；
 *                                                    C 返回类型落到 description 开头方便 AI 续写
 *   params      = parameters[].{type} {name}, ...  — 单行参数串
 *   description = `[returns: <ret_type>]`          — AI 后续可覆盖，追加功能语义
 *   __from_scan__ = { file, fn_key, cid }          — 隐藏锚点，重复勾选会替换旧条目而非追加
 *
 * 过滤口径：
 *   默认「仅 diff.added + modified 且非 SDK」—— 和 SWE.3 L5「仅看项目新增」同口径；
 *   一键开关可切换到「全量」。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert, Button, Card, Input, Modal, Radio, Space, Table, Tag, Tooltip, Switch, message,
} from 'antd'
import { ReloadOutlined, CheckOutlined } from '@ant-design/icons'
import { useAspiceStore } from '../../../stores/useAspiceStore'
import { getModuleScan } from '../../../api/aspiceApi'
import type { AspiceComponent, InterfaceItem } from '../../../types/aspice'

/** 单行函数记录（picker 内部用）。 */
interface FnRow {
  key: string               // fn.key（{path}::{scope}::{name}::{sig_hash}）
  file: string              // 相对路径
  fileShort: string         // basename
  scope: string             // class 名（free 函数时 '__free__'）
  name: string              // 函数名
  returns: string           // 返回类型
  paramsStr: string         // 单行参数串，供 InterfaceItem.params
  paramsDisplay: string     // 展示用（含 name）
  diffStatus: string        // added/modified/unchanged/unchanged_sdk/deleted/''
  isSdk: boolean
}

type Decision = 'external' | 'internal' | 'ignore'

interface Props {
  component: AspiceComponent
  onChange: (v: AspiceComponent) => void
}

/** `added | modified` 且非 SDK —— 和 SWE.3 「仅看项目新增」同口径。 */
const DEFAULT_DIFF_HIT = new Set(['added', 'modified'])

/**
 * 扫描器用 `__free__` 作为「不属于任何类」的作用域哨兵（C 文件级 / 全局函数）。
 * 这个哨兵是 **key 的一部分**（`{path}::__free__::{name}::{sha1}`），
 * 不能改值，否则历史 scan_cache 的 fn_key 全部对不上。
 * 但界面上不应该把 `__free__` 露给用户 —— 统一显示成 "C 函数"。
 */
const SCOPE_FREE = '__free__'
const scopeLabel = (scope: string) => (scope === SCOPE_FREE ? 'C 函数' : scope)

/** 一键区间超过这么多行就先弹确认，避免一次把整份扫描全设成同类接口。 */
const BULK_CONFIRM_THRESHOLD = 50

const DECISION_LABEL: Record<'external' | 'internal' | 'ignore', string> = {
  external: '外部接口',
  internal: '内部接口',
  ignore: '忽略',
}
const DECISION_TAG_COLOR: Record<'external' | 'internal' | 'ignore', string> = {
  external: 'green',
  internal: 'geekblue',
  ignore: 'default',
}

/** 把 fn.parameters 捏回去：`InterfaceItem.params` 存"类型 名字, ..."；展示再多带下类型。 */
function paramsToString(parameters: Array<{ name: string; type: string }>): {
  stored: string; display: string
} {
  if (!parameters || !parameters.length) return { stored: '', display: '()' }
  const parts = parameters.map((p) => {
    const t = (p.type || '').trim()
    const n = (p.name || '').trim()
    return t && n ? `${t} ${n}` : (t || n)
  }).filter(Boolean)
  return {
    stored: parts.join(', '),
    display: `(${parts.join(', ')})`,
  }
}

/** basename —— 工程里统一正斜杠。 */
function basename(path: string): string {
  const i = path.lastIndexOf('/')
  return i >= 0 ? path.substring(i + 1) : path
}

export default function InterfacePickerFromScan({ component, onChange }: Props) {
  const { projectId } = useAspiceStore()
  const cid = component.id

  const [loading, setLoading] = useState(false)
  const [scan, setScan] = useState<any>(null)
  const [notFound, setNotFound] = useState(false)
  const [onlyDiff, setOnlyDiff] = useState(true)
  const [onlyNonSdk, setOnlyNonSdk] = useState(true)
  const [search, setSearch] = useState('')
  // 本地勾选表：key → Decision；初值用已存在于 external/internal 的 __from_scan__ 条目回滤
  const [decisions, setDecisions] = useState<Record<string, Decision>>({})

  // 读 scan
  const refreshScan = useCallback(async () => {
    if (!projectId) return
    setLoading(true); setNotFound(false)
    try {
      const res = await getModuleScan(projectId, cid)
      setScan(res.data)
    } catch (e: any) {
      if (e?.response?.status === 404) {
        setNotFound(true)
        setScan(null)
      } else {
        message.error(e?.response?.data?.detail || '读取扫描结果失败')
      }
    } finally {
      setLoading(false)
    }
  }, [projectId, cid])

  useEffect(() => { void refreshScan() }, [refreshScan])

  // scan.files[].classes[].functions[] → 扁平行
  const rows: FnRow[] = useMemo(() => {
    if (!scan?.files) return []
    const out: FnRow[] = []
    for (const f of scan.files) {
      const isSdkFile = !!f.is_sdk
      for (const cls of (f.classes || [])) {
        for (const fn of (cls.functions || [])) {
          const retType = (fn.returns?.[0]?.type || '').trim()
          const pp = paramsToString(fn.parameters || [])
          out.push({
            key: fn.key,
            file: f.path,
            fileShort: basename(f.path),
            scope: cls.name || '__free__',
            name: fn.name,
            returns: retType,
            paramsStr: pp.stored,
            paramsDisplay: pp.display,
            diffStatus: (fn.diff_status || '').toLowerCase(),
            isSdk: !!fn.is_sdk || isSdkFile,
          })
        }
      }
    }
    return out
  }, [scan])

  // 过滤 —— 默认 diff.added + modified & 非 SDK
  const filteredRows = useMemo(() => {
    const s = search.trim().toLowerCase()
    return rows.filter((r) => {
      if (onlyDiff && !DEFAULT_DIFF_HIT.has(r.diffStatus)) return false
      if (onlyNonSdk && r.isSdk) return false
      if (s && !r.name.toLowerCase().includes(s) && !r.fileShort.toLowerCase().includes(s)) return false
      return true
    })
  }, [rows, onlyDiff, onlyNonSdk, search])

  // 初值：把 component 里已有的「来源于扫描」条目回滤到 decisions
  useEffect(() => {
    const initial: Record<string, Decision> = {}
    const absorb = (list: InterfaceItem[] | undefined, kind: Decision) => {
      for (const it of (list || [])) {
        const anchor = (it as any).__from_scan__
        if (anchor?.cid === cid && anchor?.fn_key) {
          initial[anchor.fn_key] = kind
        }
      }
    }
    absorb(component.external_interfaces, 'external')
    absorb(component.internal_interfaces, 'internal')
    setDecisions(initial)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cid])

  const setDecision = (key: string, d: Decision) => {
    setDecisions((prev) => {
      if (d === 'ignore') {
        if (!(key in prev)) return prev
        const { [key]: _drop, ...rest } = prev
        return rest
      }
      return { ...prev, [key]: d }
    })
  }

  /** 一键区间：可见行批量设决策。行数大时先弹确认，防止误把整份扫描全设成同类接口。 */
  const applyToVisible = (d: Decision) => {
    const n = filteredRows.length
    if (n === 0) {
      message.info('当前没有可操作的可见行')
      return
    }
    const doApply = () => {
      setDecisions((prev) => {
        const next = { ...prev }
        for (const r of filteredRows) {
          if (d === 'ignore') delete next[r.key]
          else next[r.key] = d
        }
        return next
      })
    }
    // 超过 50 行视为「批量」，量化告知用户影响面（A004 这类模块全量扫描可上千条）
    if (n > BULK_CONFIRM_THRESHOLD) {
      Modal.confirm({
        title: `批量设置 ${n} 条函数` ,
        content: (
          <div style={{ fontSize: 13 }}>
            将把当前可见的 <b>{n}</b> 条函数全部设为
            <Tag color={DECISION_TAG_COLOR[d]} style={{ marginLeft: 6 }}>
              {DECISION_LABEL[d]}
            </Tag>
            <div style={{ marginTop: 8, color: '#888' }}>
              应用到接口表后，§4 接口表会新增 {d === 'ignore' ? 0 : n} 行。
              如果只想挑选一部分，请先缩窄过滤条件（如只勾「仅看 added/modified」或使用搜索框）。
            </div>
          </div>
        ),
        okText: '确认设置',
        cancelText: '取消',
        onOk: doApply,
      })
      return
    }
    doApply()
  }

  // 应用：把当前 decisions 落到 component 的两个接口列表
  const handleApply = () => {
    // 原列表里，非扫描来源的手填条目保留；扫描来源但本次未勾选的清掉；本次勾选的（或已勾选的）
    // 按 decision 落到对应列表；已存在同 fn_key 的替换，不新增重复。
    const keepManual = (list: InterfaceItem[] | undefined): InterfaceItem[] =>
      (list || []).filter((it) => {
        const a = (it as any).__from_scan__
        return !(a?.cid === cid && a?.fn_key)
      })

    const extManual = keepManual(component.external_interfaces)
    const intManual = keepManual(component.internal_interfaces)

    // rows 是全量（含被当前过滤隐藏的），但 decisions 只记用户 explicit 选择 ⇒ 遍历 decisions
    // 索引表：key → FnRow（全量扫描中找）
    const rowByKey = new Map<string, FnRow>()
    for (const r of rows) rowByKey.set(r.key, r)

    const extFromScan: InterfaceItem[] = []
    const intFromScan: InterfaceItem[] = []
    for (const [key, d] of Object.entries(decisions)) {
      const r = rowByKey.get(key)
      if (!r) continue  // 旧 scan 的条目这轮没扫到 → 丢弃（防止陈旧条目堆积）
      const item: InterfaceItem = {
        source: r.fileShort,
        method: r.name,
        type: d === 'external' ? '外部接口' : '内部接口',
        params: r.paramsStr,
        description: r.returns ? `[returns: ${r.returns}]` : '',
      }
      ;(item as any).__from_scan__ = { cid, fn_key: key, file: r.file }
      if (d === 'external') extFromScan.push(item)
      else if (d === 'internal') intFromScan.push(item)
    }

    onChange({
      ...component,
      external_interfaces: [...extManual, ...extFromScan],
      internal_interfaces: [...intManual, ...intFromScan],
    })
    message.success(`已应用：外部 ${extFromScan.length} 条 / 内部 ${intFromScan.length} 条`)
  }

  // 勾选计数
  const picked = Object.values(decisions)
  const extCount = picked.filter((d) => d === 'external').length
  const intCount = picked.filter((d) => d === 'internal').length

  const columns = [
    {
      title: '文件 :: 函数', key: 'fn', width: 320,
      render: (_: unknown, r: FnRow) => (
        <Tooltip title={r.file}>
          <div style={{ fontFamily: 'monospace', fontSize: 12 }}>
            <span style={{ color: '#999' }}>{r.fileShort}</span>
            <span style={{ color: '#ccc' }}>::</span>
            <span style={{ color: '#888' }}>{scopeLabel(r.scope)}</span>
            <span style={{ color: '#ccc' }}>::</span>
            <b>{r.name}</b>
          </div>
          <div style={{ fontFamily: 'monospace', fontSize: 11, color: '#888' }}>
            {r.returns || 'void'} {r.paramsDisplay}
          </div>
        </Tooltip>
      ),
    },
    {
      title: 'diff', dataIndex: 'diffStatus', width: 90,
      render: (t: string, r: FnRow) => {
        if (r.isSdk) return <Tag color="default">SDK</Tag>
        if (t === 'added') return <Tag color="green">added</Tag>
        if (t === 'modified') return <Tag color="orange">modified</Tag>
        if (t === 'deleted') return <Tag color="red">deleted</Tag>
        if (t) return <Tag>{t}</Tag>
        return <Tag color="default">-</Tag>
      },
    },
    {
      title: '归属', key: 'decision', width: 240,
      render: (_: unknown, r: FnRow) => {
        const d = decisions[r.key] || 'ignore'
        return (
          <Radio.Group size="small" value={d}
            onChange={(e) => setDecision(r.key, e.target.value)}>
            <Radio.Button value="external">外部</Radio.Button>
            <Radio.Button value="internal">内部</Radio.Button>
            <Radio.Button value="ignore">忽略</Radio.Button>
          </Radio.Group>
        )
      },
    },
  ]

  return (
    <Card size="small" title={
      <Space>
        <span>从扫描结果挑选接口</span>
        <Tag color="green">已选外部 {extCount}</Tag>
        <Tag color="geekblue">已选内部 {intCount}</Tag>
      </Space>
    } extra={
      <Space>
        <Button size="small" icon={<ReloadOutlined />} loading={loading}
          onClick={refreshScan}>重新读取</Button>
        <Button size="small" type="primary" icon={<CheckOutlined />}
          onClick={handleApply}>应用到接口表</Button>
      </Space>
    }>
      {notFound && (
        <Alert type="info" showIcon style={{ marginBottom: 8 }}
          message="该模块尚未扫描"
          description="请在上方「代码路径配置」卡片里添加 glob 规则并点「扫描本模块」，这里会读取同一份 scan_cache。" />
      )}

      <Space style={{ marginBottom: 8 }} wrap>
        <Space size={4}>
          <span style={{ fontSize: 12 }}>仅看 added/modified</span>
          <Switch size="small" checked={onlyDiff}
            onChange={setOnlyDiff} />
        </Space>
        <Space size={4}>
          <span style={{ fontSize: 12 }}>排除 SDK 函数</span>
          <Switch size="small" checked={onlyNonSdk}
            onChange={setOnlyNonSdk} />
        </Space>
        <Input.Search size="small" allowClear placeholder="按函数名/文件名搜"
          value={search} onChange={(e) => setSearch(e.target.value)}
          style={{ width: 220 }} />
        <Button size="small" onClick={() => applyToVisible('external')}>
          当前过滤 → 全标外部
        </Button>
        <Button size="small" onClick={() => applyToVisible('internal')}>
          当前过滤 → 全标内部
        </Button>
        <Button size="small" danger onClick={() => applyToVisible('ignore')}>
          清空当前过滤
        </Button>
      </Space>

      <Table<FnRow>
        rowKey="key" size="small"
        columns={columns}
        dataSource={filteredRows}
        pagination={filteredRows.length > 20 ? { pageSize: 20, size: 'small' } : false}
        locale={{ emptyText: notFound ? '未扫描' : '没有符合过滤条件的函数' }}
      />
    </Card>
  )
}
