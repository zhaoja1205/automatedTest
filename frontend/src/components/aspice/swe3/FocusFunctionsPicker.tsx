/**
 * SWE.3 推送 D — 关注函数选择器。
 *
 * 按模块 Tabs 切分；每模块下按文件分组展示扫描到的类/函数。
 * 支持：复选 / 搜索 / "仅看已关注" 过滤 / 手工添加 / 同名函数联动勾选。
 * 勾选结果通过 putFocusFunctions 实时写回后端。
 */
import { useEffect, useMemo, useState } from 'react'
import {
  Tabs, Card, Input, Space, Checkbox, Tag, Collapse, Button, Modal, Form, message, Alert, Empty, Spin,
} from 'antd'
import { PlusOutlined, SearchOutlined } from '@ant-design/icons'
import { useAspiceStore } from '../../../stores/useAspiceStore'
import type {
  Swe3ScanIndex, Swe3ScannedFunction, Swe3FocusFunctions,
} from '../../../types/aspice'
import { getModuleScan, putFocusFunctions } from '../../../api/aspiceApi'

interface Props {
  modules: Array<{ component_id: string; name: string }>
}

export default function FocusFunctionsPicker({ modules }: Props) {
  const [active, setActive] = useState<string>(modules[0]?.component_id || '')
  const items = modules.map((mod) => ({
    key: mod.component_id,
    label: `${mod.component_id} ${mod.name}`,
    children: <ModulePicker key={mod.component_id} componentId={mod.component_id} />,
  }))
  return <Tabs size="small" activeKey={active} onChange={setActive} items={items} />
}

interface ModulePickerProps { componentId: string }

function ModulePicker({ componentId }: ModulePickerProps) {
  const { projectId, aspice, setSwe3FocusFunctions, setSwe3ScanIndex } = useAspiceStore()
  const push_d = aspice?.swe3?.push_d
  const scan: Swe3ScanIndex | undefined = push_d?.scan_indices.find((s) => s.component_id === componentId)
  const existing: Swe3FocusFunctions = push_d?.focus_functions.find((f) => f.component_id === componentId)
    || { component_id: componentId, focused_keys: [], manual_additions: [], included_added_keys: [] }

  const [query, setQuery] = useState('')
  const [onlyFocused, setOnlyFocused] = useState(false)
  const [onlyCustom, setOnlyCustom] = useState(false)
  const [manualOpen, setManualOpen] = useState(false)
  const [manualForm] = Form.useForm()
  const [loadingScan, setLoadingScan] = useState(false)
  // R4 需求 #3：大模块（nvsipl_camera 2300+ 函数）默认只渲染前 50 个文件，
  // 加 "显示全部" 开关。否则 Collapse 把 154 个 panel 一次性 render + 默认全展开
  // → 几千个 checkbox 卡死浏览器。
  const [showAll, setShowAll] = useState(false)
  const FILE_CAP = 50

  // 懒加载：如果 scan 有 stats 但没 files（刷新后从后端 project.json 恢复的轻量索引），
  // 调一次 getModuleScan 把完整扫描数据取回来。
  useEffect(() => {
    if (!projectId) return
    if (!scan) return               // 完全没有扫描结果 → 走下面 Alert 分支
    if (scan.files && scan.files.length > 0) return  // 已有完整数据
    if (scan.stats?.total_files === 0) return        // 空扫描，不必请求
    let cancelled = false
    setLoadingScan(true)
    getModuleScan(projectId, componentId)
      .then((res) => {
        if (cancelled) return
        setSwe3ScanIndex(componentId, res.data)
      })
      .catch(() => { /* 后端若未扫则 404，静默，上面 Alert 已覆盖 */ })
      .finally(() => { if (!cancelled) setLoadingScan(false) })
    return () => { cancelled = true }
  }, [projectId, componentId, scan?.scanned_at, scan?.files?.length])

  const persistFocus = (next: Swe3FocusFunctions) => {
    setSwe3FocusFunctions(componentId, next)
    if (projectId) {
      putFocusFunctions(projectId, componentId, {
        focused_keys: next.focused_keys,
        manual_additions: next.manual_additions,
        included_added_keys: next.included_added_keys || [],
      }).catch((e: any) => {
        message.error(e?.response?.data?.detail || '保存关注函数失败')
      })
    }
  }

  // 索引：同类同名函数 — 跨文件联动用
  // key = `${className}::${funcName}` → 所有具体 key 列表
  const sameNameIndex = useMemo(() => {
    const map: Record<string, string[]> = {}
    const files = scan?.files || []
    files.forEach((f) => {
      ;(f.classes || []).forEach((c) => {
        ;(c.functions || []).forEach((fn) => {
          const idx = `${c.name}::${fn.name}`
          if (!map[idx]) map[idx] = []
          map[idx].push(fn.key)
        })
      })
    })
    return map
  }, [scan])

  const focusedSet = useMemo(() => new Set(existing.focused_keys), [existing.focused_keys])

  const toggle = (fn: Swe3ScannedFunction, checked: boolean) => {
    // 找出所有同名同类的 key
    const siblings = sameNameIndex[`${fn.key.split('::')[1]}::${fn.name}`] || [fn.key]
    const next = new Set(focusedSet)
    if (checked) siblings.forEach((k) => next.add(k))
    else siblings.forEach((k) => next.delete(k))
    persistFocus({
      ...existing,
      focused_keys: Array.from(next),
    })
  }

  const addManual = () => {
    manualForm.validateFields().then((v) => {
      const key = `__manual__::__free__::${v.name}::${Math.random().toString(16).slice(2, 10)}`
      const fn: Swe3ScannedFunction = {
        key, name: v.name, declaration: v.declaration || '',
        parameters: [], returns: [], doc_comment: '', body_lines: 0,
        extracted_by: 'manual', is_sdk: false, ai_intro: '', ai_flowchart: '',
      }
      persistFocus({
        ...existing,
        manual_additions: [...existing.manual_additions, fn],
        focused_keys: [...existing.focused_keys, key],
      })
      manualForm.resetFields()
      setManualOpen(false)
      message.success('已添加手工关注函数')
    })
  }

  if (!scan) {
    return (
      <Card size="small">
        <Alert type="info" showIcon
          message="本模块尚未扫描"
          description={`请先在上方"模块代码路径配置"中配置 ${componentId} 的 glob 规则并点"扫描本模块"。`}
        />
      </Card>
    )
  }

  if (!scan.files || scan.files.length === 0) {
    if (loadingScan) {
      return (
        <Card size="small">
          <div style={{ textAlign: 'center', padding: 24 }}>
            <Spin tip="加载扫描结果…" />
          </div>
        </Card>
      )
    }
    return (
      <Card size="small">
        <Empty description="扫描结果为空（可能规则未匹配到源文件）" />
      </Card>
    )
  }

  // 过滤匹配
  const match = (fn: Swe3ScannedFunction) => {
    if (onlyFocused && !focusedSet.has(fn.key)) return false
    if (onlyCustom && fn.is_sdk) return false
    if (query && !fn.name.toLowerCase().includes(query.toLowerCase())) return false
    return true
  }

  const stats = {
    focused: existing.focused_keys.length,
    total: scan.stats?.total_functions || 0,
  }

  return (
    <Card size="small">
      <Space wrap style={{ marginBottom: 10 }}>
        <Input size="small" style={{ width: 200 }}
          prefix={<SearchOutlined />} placeholder="按函数名搜索"
          value={query} onChange={(e) => setQuery(e.target.value)} />
        <Checkbox checked={onlyFocused} onChange={(e) => setOnlyFocused(e.target.checked)}>
          仅看已关注
        </Checkbox>
        <Checkbox checked={onlyCustom} onChange={(e) => setOnlyCustom(e.target.checked)}>
          仅看项目新增（排除 SDK）
        </Checkbox>
        <Button size="small" icon={<PlusOutlined />} onClick={() => setManualOpen(true)}>
          手工添加未扫到函数
        </Button>
        <Button size="small" type="dashed"
          disabled={!onlyCustom}
          title={onlyCustom
            ? '把当前视图里项目新增（diff.added 且非 SDK）的函数批量加入关注，导出 docx 时进入 L5 详细展开'
            : '先勾上"仅看项目新增（排除 SDK）"再使用'}
          onClick={() => {
            const addedKeys: string[] = []
            ;(scan.files || []).forEach((f) => {
              if (f.is_sdk) return
              ;(f.classes || []).forEach((c) => {
                ;(c.functions || []).forEach((fn: any) => {
                  if (fn.is_sdk) return
                  const st = (fn.diff_status || '').toLowerCase()
                  if (st === 'added') addedKeys.push(fn.key)
                })
              })
            })
            if (addedKeys.length === 0) {
              message.info('本模块当前扫描结果里没有 diff.added 的函数')
              return
            }
            const prev = new Set(existing.included_added_keys || [])
            addedKeys.forEach((k) => prev.add(k))
            persistFocus({ ...existing, included_added_keys: Array.from(prev) })
            message.success(`已把 ${addedKeys.length} 个项目新增函数加入 L5 详细展开清单`)
          }}
        >
          📌 批量加入 L5 展开
        </Button>
        <Tag color="blue">已关注 {stats.focused} / 共 {stats.total}</Tag>
        {(existing.included_added_keys?.length || 0) > 0 && (
          <Tag color="purple">L5 新增入口 {existing.included_added_keys!.length}</Tag>
        )}
        {(scan.files?.length || 0) > FILE_CAP && (
          <Checkbox checked={showAll} onChange={(e) => setShowAll(e.target.checked)}>
            显示全部文件（{scan.files!.length} 个，默认只展示前 {FILE_CAP} 以保证性能）
          </Checkbox>
        )}
      </Space>

      {(() => {
        const allFiles = scan.files || []
        const visibleFiles = showAll ? allFiles : allFiles.slice(0, FILE_CAP)
        const hiddenCount = allFiles.length - visibleFiles.length
        return (
          <>
      {hiddenCount > 0 && (
        <Alert type="warning" showIcon style={{ marginBottom: 8 }}
          message={`当前仅显示前 ${FILE_CAP} 个文件；还有 ${hiddenCount} 个未展示，勾上上方"显示全部文件"查看完整列表（大模块加载较慢）。`}
        />
      )}
      <Collapse size="small"
        items={visibleFiles.map((f) => ({
          key: f.path,
          label: (
            <Space>
              <span>📄 {f.path}</span>
              <Tag>{(f.classes || []).reduce((n, c) => n + (c.functions?.length || 0), 0)} 函数</Tag>
              {f.is_sdk && <Tag color="orange">SDK</Tag>}
            </Space>
          ),
          children: (
            <div>
              {(f.classes || []).map((c) => {
                const fns = c.functions || []
                const visibleFns = fns.filter(match)
                if (visibleFns.length === 0) return null
                return (
                  <div key={c.name} style={{ marginBottom: 8 }}>
                    <div style={{ marginBottom: 4 }}>
                      <Space>
                        {c.name === '__free__' ? (
                          <Tag color="gold">⚡ 自由函数</Tag>
                        ) : (
                          <Tag color="geekblue">📦 Class {c.name}</Tag>
                        )}
                        <Tag>{fns.length}</Tag>
                      </Space>
                    </div>
                    <div style={{ paddingLeft: 20 }}>
                      {visibleFns.map((fn) => {
                        const checked = focusedSet.has(fn.key)
                        const idx = `${c.name}::${fn.name}`
                        const linkedCount = (sameNameIndex[idx] || []).length
                        // 判定 "被联动" 状态：当前文件未直接勾选，但同名其他文件已勾
                        const linkedChecked = checked && linkedCount > 1
                        return (
                          <div key={fn.key} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '2px 0' }}>
                            <Checkbox checked={checked}
                              onChange={(e) => toggle(fn, e.target.checked)}>
                              <span style={{ fontFamily: 'monospace', fontSize: 13 }}>{fn.name}</span>
                            </Checkbox>
                            {fn.is_sdk && <Tag color="orange">SDK</Tag>}
                            {!fn.is_sdk && fn.diff_status === 'added' && (
                              <Tag color="green" title="本工程新增；B/C 组模块需要勾选才会进 L5 详细展开">🆕 新增</Tag>
                            )}
                            {!fn.is_sdk && fn.diff_status === 'modified' && (
                              <Tag color="blue" title="本工程改动；自动进 L5 详细展开">✏ 改动</Tag>
                            )}
                            {linkedChecked && linkedCount > 1 && (
                              <Tag color="purple">联动 {linkedCount} 处</Tag>
                            )}
                            <span style={{ color: '#999', fontSize: 11 }}>{fn.body_lines} 行</span>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )
              })}
            </div>
          ),
        }))}
      />
          </>
        )
      })()}

      {existing.manual_additions.length > 0 && (
        <Card size="small" title="手工添加的函数" style={{ marginTop: 12 }}>
          {existing.manual_additions.map((fn) => (
            <div key={fn.key}>
              <Tag color="cyan">manual</Tag>
              <span style={{ fontFamily: 'monospace' }}>{fn.name}</span> — {fn.declaration}
            </div>
          ))}
        </Card>
      )}

      <Modal title="手工添加关注函数" open={manualOpen}
        onCancel={() => setManualOpen(false)} onOk={addManual}>
        <Form form={manualForm} layout="vertical">
          <Form.Item name="name" label="函数名" rules={[{ required: true }]}>
            <Input placeholder="MyFunction" />
          </Form.Item>
          <Form.Item name="declaration" label="函数声明（可选）">
            <Input.TextArea rows={2} placeholder="void MyFunction(int x);" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}
