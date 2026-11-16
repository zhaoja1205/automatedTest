/**
 * SWE.3 第 4~10 章 模块详细设计编辑器。
 *
 * 顶部横向 Tabs 切换 9 个模块；每个模块下：
 *   - 元信息：组件 ID / slug / 展示名 / 章节标题
 *   - ★ 从关注函数自动生成：复用推送 D 的扫描结果 + 关注勾选，一键落盘为类/函数列表与类图
 *   - 类列表：添加/删除，行内编辑类名/路径/说明
 *   - 独立函数列表（不属于类的）：编辑设计 ID / 函数名 / 介绍 / 声明
 *   - 单元时序图：PlantUML TextArea
 *   - Camera Security（A008）专用：安全目标 + 流程设计
 * 完整编辑函数参数/返回值/流程图留给推送 D 的 InterfaceEditor。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Tabs, Table, Input, Button, Space, Popconfirm, Card, Tag, message,
  Modal, Checkbox, Alert, Radio,
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, ThunderboltOutlined, ApartmentOutlined,
  CheckCircleFilled, LoadingOutlined,
} from '@ant-design/icons'
import { useAspiceStore } from '../../../stores/useAspiceStore'
import { getModuleScan, augmentOneFunction, saveSwe3 } from '../../../api/aspiceApi'
import type {
  Swe3Module, Swe3Class, Swe3Function,
  Swe3ScannedFunction, Swe3MemberConstant, Swe3MemberVariable,
} from '../../../types/aspice'

interface Props {
  modules: Swe3Module[]
  onChange: (modules: Swe3Module[]) => void
  /** 推送 D：Camera Security 是否可见；关闭时隐藏 A008 Tab（数据保留） */
  hasCameraSecurity?: boolean
}

/** 把 'A001' 转为 '001'；无法解析时返回传入值。 */
function moduleSeq(componentId: string): string {
  const m = /A0*(\d+)/.exec(componentId || '')
  return m ? m[1].padStart(3, '0') : (componentId || '000')
}

function nextClassId(mod: Swe3Module): string {
  const seq = (mod.classes?.length || 0) + 1
  return `D${moduleSeq(mod.component_id)}-${mod.slug}-class-${String(seq).padStart(3, '0')}`
}

function nextFunctionId(mod: Swe3Module, inClass: Swe3Class | null): string {
  const base = inClass
    ? (inClass.functions?.length || 0)
    : (mod.functions?.length || 0)
  const seq = base + 1
  return `D${moduleSeq(mod.component_id)}-${mod.slug}-function-${String(seq).padStart(3, '0')}`
}

/**
 * 关注函数匹配：先按完整 key 命中（最精确），若 key 不在当前扫描结果里（可能
 * 来自 rescan 前的旧 sha），回退到 "{className}::{funcName}" 名字匹配 —
 * 这样用户换扫一次工程后仍能根据历史关注勾选把类/函数填出来。
 */
function makeFocusMatcher(
  focusedKeys: Set<string>,
  manualAdditions: Swe3ScannedFunction[],
): (fn: Swe3ScannedFunction, className: string) => boolean {
  // key 直接命中
  const byKey = focusedKeys
  // 从 key 回推类::名字；旧 key 大致为 `{file}::{class}::{name}::{sha}`
  const byName = new Set<string>()
  focusedKeys.forEach((k) => {
    const parts = k.split('::')
    // 至少 4 段才像完整 key；取倒数第二段作为函数名、倒数第三段作为类名
    if (parts.length >= 4) {
      const name = parts[parts.length - 2]
      const cls = parts[parts.length - 3]
      byName.add(`${cls}::${name}`)
    }
  })
  // 手工新增函数的名字也计入（它们的 key 带随机 sha，不会命中扫描结果）
  manualAdditions.forEach((fn) => byName.add(`__free__::${fn.name}`))
  return (fn, className) => byKey.has(fn.key) || byName.has(`${className}::${fn.name}`)
}

/**
 * 扫描结果里 `base` 的后端形态是 **字符串**（如 "NvMDeviceDriver"），
 * 多继承/含访问修饰时形如 "public A, protected B"。这里统一归一化成类名数组。
 * 同时兼容历史上可能存成数组的旧数据。
 */
function basesOf(base: unknown): string[] {
  const raw = Array.isArray(base) ? base : (typeof base === 'string' ? base.split(',') : [])
  return raw
    .map((b) => String(b).trim().replace(/^(public|protected|private|virtual)\s+/i, '').trim())
    .filter(Boolean)
}

/**
 * 从扫描结果 + 关注函数 key 集合，构造：
 *   - 按类分组的 Swe3Class[]（含该类下所有被关注的函数，即"详细展开函数"）
 *   - 独立函数 Swe3Function[]（原类为 __free__ 且被关注的函数）
 *   - NV 原始函数 Swe3Function[]（扫描到但 **未被** 关注的函数，作为原始实现登记）
 *   - 父类追溯：选项 `baseDepth` 控制把扫描到的直接父类/祖父类也拉入类列表（无函数、仅骨架）
 *
 * 复用扫描阶段提取的 declaration / parameters / returns / AI 介绍 / AI 流程图。
 * 序号在同一次生成内连续分配；覆盖写回时每次都从 1 开始。
 */
function buildClassesFromFocus(
  mod: Swe3Module,
  focusedKeys: Set<string>,
  scanFiles: Array<{
    path: string
    classes: Array<{
      name: string
      base: string | string[]
      doc_comment: string
      constants: Swe3MemberConstant[]
      variables: Swe3MemberVariable[]
      functions: Swe3ScannedFunction[]
    }>
  }>,
  manualAdditions: Swe3ScannedFunction[],
  opts: { baseDepth: 0 | 1 | 2 } = { baseDepth: 0 },
): { classes: Swe3Class[]; functions: Swe3Function[]; nv_original_functions: Swe3Function[] } {
  const seq3 = moduleSeq(mod.component_id)
  const slug = mod.slug || mod.component_id
  const isFocused = makeFocusMatcher(focusedKeys, manualAdditions)

  // --- 一遍扫描：收集 className → 聚合槽（跨文件合并同类） ---
  type ClassAgg = {
    paths: Set<string>
    description: string
    base: Set<string>
    constants: Swe3MemberConstant[]
    variables: Swe3MemberVariable[]
    focused: Swe3ScannedFunction[]      // 被关注 → 详细展开
    unfocused: Swe3ScannedFunction[]    // 未关注 → NV 原始
  }
  const classMap = new Map<string, ClassAgg>()
  const freeFocused: Swe3ScannedFunction[] = []
  const freeUnfocused: Swe3ScannedFunction[] = []

  for (const f of scanFiles) {
    for (const c of (f.classes || [])) {
      if (c.name === '__free__') {
        ;(c.functions || []).forEach((fn) => {
          if (isFocused(fn, '__free__')) freeFocused.push(fn)
          else freeUnfocused.push(fn)
        })
        continue
      }
      const slot = classMap.get(c.name) || {
        paths: new Set<string>(),
        description: c.doc_comment || '',
        base: new Set<string>(),
        constants: [] as Swe3MemberConstant[],
        variables: [] as Swe3MemberVariable[],
        focused: [] as Swe3ScannedFunction[],
        unfocused: [] as Swe3ScannedFunction[],
      }
      slot.paths.add(f.path)
      if (!slot.description && c.doc_comment) slot.description = c.doc_comment
      basesOf(c.base).forEach((b) => slot.base.add(b))
      ;(c.constants || []).forEach((cst) => {
        if (!slot.constants.some((x) => x.name === cst.name)) slot.constants.push(cst)
      })
      ;(c.variables || []).forEach((v) => {
        if (!slot.variables.some((x) => x.name === v.name)) slot.variables.push(v)
      })
      ;(c.functions || []).forEach((fn) => {
        if (isFocused(fn, c.name)) slot.focused.push(fn)
        else slot.unfocused.push(fn)
      })
      classMap.set(c.name, slot)
    }
  }

  // 手工新增 → 独立函数（它们的 key 带随机 sha，不会出现在 scanFiles 里，这里直接登记）
  for (const fn of manualAdditions) {
    freeFocused.push(fn)
  }

  // --- 选出 "命中类"：有关注函数的类 + 可选的 1~2 层父类 ---
  const hitClassNames = new Set<string>()
  classMap.forEach((slot, name) => {
    if (slot.focused.length > 0) hitClassNames.add(name)
  })
  const emittedClassNames = new Set(hitClassNames)
  if (opts.baseDepth >= 1) {
    hitClassNames.forEach((name) => {
      const slot = classMap.get(name)
      slot?.base.forEach((b) => { if (classMap.has(b)) emittedClassNames.add(b) })
    })
  }
  if (opts.baseDepth >= 2) {
    // 对第一层父类再抽一层
    Array.from(emittedClassNames).forEach((name) => {
      if (hitClassNames.has(name)) return
      const slot = classMap.get(name)
      slot?.base.forEach((b) => { if (classMap.has(b)) emittedClassNames.add(b) })
    })
  }

  const toSweFunction = (
    fn: Swe3ScannedFunction, seq: number, className?: string,
  ): Swe3Function => ({
    design_id: `D${seq3}-${slug}-function-${String(seq).padStart(3, '0')}`,
    name: className ? `${className}::${fn.name}` : fn.name,
    declaration: fn.declaration || '',
    intro: fn.ai_intro || fn.doc_comment || '',
    parameters: fn.parameters || [],
    returns: fn.returns || [],
    flowchart_plantuml: fn.ai_flowchart || '',
    // 携带扫描 key，便于单条 AI 补齐介绍/流程图（手工新增函数以 __manual__ 开头，不走 AI）
    source_key: fn.key && !fn.key.startsWith('__manual__') ? fn.key : undefined,
  })

  // --- 生成类列表 ---
  const classes: Swe3Class[] = []
  let classSeq = 0
  const emittedSorted = Array.from(emittedClassNames).sort((a, b) => a.localeCompare(b))
  emittedSorted.forEach((className) => {
    const slot = classMap.get(className)!
    classSeq += 1
    const fns = [...slot.focused]
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((fn, i) => toSweFunction(fn, i + 1))
    const isBaseOnly = !hitClassNames.has(className)
    classes.push({
      design_id: `D${seq3}-${slug}-class-${String(classSeq).padStart(3, '0')}`,
      class_name: className,
      description: slot.description || (isBaseOnly
        ? `${className}（父类追溯，无详细函数展开）`
        : ''),
      path: Array.from(slot.paths).sort().join(' / '),
      constants: slot.constants,
      variables: slot.variables,
      functions: fns,            // 父类条目 functions=[]
    })
  })

  // --- 独立函数（__free__ 中的关注函数 + 手工） ---
  let funcSeq = 0
  const functions = [...freeFocused]
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((fn) => {
      funcSeq += 1
      return toSweFunction(fn, funcSeq)
    })

  // --- NV 原始函数：所有未被关注的扫描函数（命中类 + __free__ + 父类） ---
  // 父类的所有函数都算作原始（因为用户没显式关注）。
  const nvRaw: Array<{ className: string; fn: Swe3ScannedFunction }> = []
  emittedSorted.forEach((className) => {
    const slot = classMap.get(className)!
    const isBaseOnly = !hitClassNames.has(className)
    const pool = isBaseOnly
      ? [...slot.focused, ...slot.unfocused]  // 父类里即便 "被关注" 也作为原始罗列（关注语义只对命中类生效）
      : slot.unfocused
    pool.forEach((fn) => nvRaw.push({ className, fn }))
  })
  freeUnfocused.forEach((fn) => nvRaw.push({ className: '', fn }))

  let nvSeq = 0
  const nv_original_functions = nvRaw
    .sort((a, b) => (a.className + '::' + a.fn.name).localeCompare(b.className + '::' + b.fn.name))
    .map(({ className, fn }) => {
      nvSeq += 1
      return toSweFunction(fn, nvSeq, className || undefined)
    })

  return { classes, functions, nv_original_functions }
}


/** 根据选中的类名集合生成简易 PlantUML 类图：类成员 + 公有函数签名；继承用 extends 边。 */
function buildClassDiagramPlantUml(
  moduleName: string,
  selectedClassNames: string[],
  scanFiles: Array<{
    classes: Array<{
      name: string
      base: string | string[]
      functions: Swe3ScannedFunction[]
      constants: Swe3MemberConstant[]
      variables: Swe3MemberVariable[]
    }>
  }>,
  focusedKeys: Set<string>,
): string {
  const picked = new Set(selectedClassNames)
  // 跨文件合并同类
  type Agg = {
    name: string
    bases: Set<string>
    fns: Swe3ScannedFunction[]
    vars: Swe3MemberVariable[]
  }
  const agg = new Map<string, Agg>()
  for (const f of scanFiles) {
    for (const c of (f.classes || [])) {
      if (!picked.has(c.name)) continue
      const slot = agg.get(c.name) || { name: c.name, bases: new Set<string>(), fns: [], vars: [] }
      basesOf(c.base).forEach((b) => slot.bases.add(b))
      ;(c.functions || []).forEach((fn) => {
        // 优先列已关注的；若该类没有关注函数则列前 8 个作为示意
        if (focusedKeys.size === 0 || focusedKeys.has(fn.key)) slot.fns.push(fn)
      })
      ;(c.variables || []).forEach((v) => slot.vars.push(v))
      agg.set(c.name, slot)
    }
  }
  const lines: string[] = ['@startuml', `title ${moduleName} 类图`, 'skinparam classAttributeIconSize 0']
  for (const [, a] of agg) {
    lines.push(`class ${a.name} {`)
    a.vars.slice(0, 8).forEach((v) => lines.push(`  - ${v.name}: ${v.type || 'void'}`))
    const fns = a.fns.length > 0 ? a.fns.slice(0, 12) : []
    fns.forEach((fn) => {
      const params = (fn.parameters || []).map((p) => `${p.name}: ${p.type || 'void'}`).join(', ')
      lines.push(`  + ${fn.name}(${params})`)
    })
    lines.push('}')
  }
  // 继承边：仅在双方都在图中时才画
  for (const [, a] of agg) {
    a.bases.forEach((b) => {
      if (agg.has(b)) lines.push(`${b} <|-- ${a.name}`)
    })
  }
  lines.push('@enduml')
  return lines.join('\n')
}


export default function ModuleDesignEditor({ modules, onChange, hasCameraSecurity = true }: Props) {
  const visibleModules = hasCameraSecurity
    ? modules
    : modules.filter((m) => m.component_id !== 'A008')
  const [activeKey, setActiveKey] = useState<string>(visibleModules[0]?.component_id || '')
  const { projectId, markClean } = useAspiceStore()

  // ---- R4.8 细粒度 debounce 自动保存 ----
  // 背景：顶部 "保存" 按钮调的 PUT /aspice/projects/{id} 后端 Pydantic 只收
  // project_code/swe1/swe2，swe3 整段会被丢弃。要让 ModuleEditor 的编辑真正落盘，
  // 这里对 modules 做 debounce 直接推到 /aspice/projects/{id}/swe3。
  //   - 顶层保存按钮改动放在 AspiceWizardPage 里（并行走 saveSwe3）
  //   - 这里做"动一下、半秒无动作就推"的即时体验，不等用户点按钮
  // 第一次 load 不要推：用 initRef 跳过首个 effect。
  const [saveState, setSaveState] = useState<'idle' | 'pending' | 'saving' | 'saved' | 'error'>('idle')
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const latestModulesRef = useRef(modules)
  const initRef = useRef(true)
  const savedAtRef = useRef<number | null>(null)
  const inflightRef = useRef(false)
  latestModulesRef.current = modules

  const flushSave = async () => {
    if (!projectId) return
    if (inflightRef.current) {
      // 已有请求在飞 → 下面结束后还会读 latestModulesRef，不用再触发一次
      return
    }
    inflightRef.current = true
    setSaveState('saving')
    try {
      await saveSwe3(projectId, { modules: latestModulesRef.current })
      // 可能保存期间用户又改了 → 再保一次最新快照
      inflightRef.current = false
      if (latestModulesRef.current !== modules) {
        void flushSave()
        return
      }
      savedAtRef.current = Date.now()
      setSaveState('saved')
      markClean()
    } catch (e: any) {
      inflightRef.current = false
      setSaveState('error')
      message.error(e?.response?.data?.detail || '模块数据自动保存失败')
    }
  }

  useEffect(() => {
    if (initRef.current) {
      initRef.current = false
      return
    }
    if (!projectId) return
    setSaveState('pending')
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    saveTimerRef.current = setTimeout(() => { void flushSave() }, 600)
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modules])

  // 离开页面前兜底刷一次（React 的 cleanup 不会跑 async，用 beforeunload 也只能
  // 发同步 XHR；这里退而求其次：如果还有 pending timer，直接立即 flush）
  useEffect(() => {
    return () => {
      if (saveTimerRef.current) {
        clearTimeout(saveTimerRef.current)
        if (projectId && !inflightRef.current) {
          // 组件卸载时同步触发一次 save
          void saveSwe3(projectId, { modules: latestModulesRef.current }).catch(() => {})
        }
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  if (!visibleModules.length) {
    return <Card size="small"><Tag>模块列表为空，请先点"规则派生"初始化 9 模块骨架</Tag></Card>
  }

  const updateModule = (componentId: string, patch: Partial<Swe3Module>) => {
    const updated = modules.map((m) => m.component_id === componentId ? { ...m, ...patch } : m)
    onChange(updated)
  }

  const saveStatusTag = (() => {
    switch (saveState) {
      case 'pending':
        return <Tag color="orange" icon={<LoadingOutlined />}>有改动，待保存</Tag>
      case 'saving':
        return <Tag color="blue" icon={<LoadingOutlined />}>正在保存…</Tag>
      case 'saved':
        return <Tag color="green" icon={<CheckCircleFilled />}>已自动保存</Tag>
      case 'error':
        return <Tag color="red">自动保存失败</Tag>
      default:
        return null
    }
  })()

  const items = visibleModules.map((mod) => ({
    key: mod.component_id,
    label: `${mod.component_id} ${mod.name}`,
    children: (
      <ModulePanel
        module={mod}
        onChange={(patch) => updateModule(mod.component_id, patch)}
      />
    ),
  }))

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 6, minHeight: 24 }}>
        {saveStatusTag}
      </div>
      <Tabs
        tabPosition="left"
        activeKey={activeKey}
        onChange={setActiveKey}
        items={items}
        style={{ minHeight: 480 }}
      />
    </div>
  )
}

interface ModulePanelProps {
  module: Swe3Module
  onChange: (patch: Partial<Swe3Module>) => void
}

function ModulePanel({ module: mod, onChange }: ModulePanelProps) {
  const classes = mod.classes || []
  const functions = mod.functions || []

  // ---- 推送 D：从扫描结果 + 关注函数生成类/函数列表 ----
  const { projectId, aspice, setSwe3ScanIndex } = useAspiceStore()
  const push_d = aspice?.swe3?.push_d
  const scanIdx = useMemo(() => {
    return (push_d?.scan_indices || []).find((s) => s.component_id === mod.component_id)
  }, [push_d?.scan_indices, mod.component_id])
  const scanFiles = scanIdx?.files || []

  // 懒加载：若 scanIdx 存在 stats 但 files 为空（刷新后 project.json 只恢复轻量索引），
  // 回头端 getModuleScan 拉完整扫描数据回填 store。
  useEffect(() => {
    if (!projectId) return
    if (!scanIdx) return
    if (scanIdx.files && scanIdx.files.length > 0) return
    if (scanIdx.stats?.total_files === 0) return
    let cancelled = false
    getModuleScan(projectId, mod.component_id)
      .then((res) => { if (!cancelled) setSwe3ScanIndex(mod.component_id, res.data) })
      .catch(() => { /* 后端若未扫则 404，静默 */ })
    return () => { cancelled = true }
  }, [projectId, mod.component_id, scanIdx?.scanned_at, scanIdx?.files?.length])

  const focus = useMemo(() => {
    return (push_d?.focus_functions || []).find((f) => f.component_id === mod.component_id)
      || { component_id: mod.component_id, focused_keys: [] as string[], manual_additions: [] as Swe3ScannedFunction[] }
  }, [push_d?.focus_functions, mod.component_id])
  const focusedSet = useMemo(() => new Set(focus.focused_keys || []), [focus.focused_keys])

  /** 跨文件聚合后，可供用户勾选用于类图的类名集合（排除 __free__） */
  const availableClassNames = useMemo(() => {
    const set = new Set<string>()
    ;(scanIdx?.files || []).forEach((f) => (f.classes || []).forEach((c) => {
      if (c.name && c.name !== '__free__') set.add(c.name)
    }))
    return Array.from(set).sort()
  }, [scanIdx])

  /** 默认勾选：有关注函数命中的类 */
  const defaultDiagramClasses = useMemo(() => {
    const set = new Set<string>()
    ;(scanIdx?.files || []).forEach((f) => (f.classes || []).forEach((c) => {
      if (c.name === '__free__') return
      if ((c.functions || []).some((fn) => focusedSet.has(fn.key))) set.add(c.name)
    }))
    return Array.from(set)
  }, [scanIdx, focusedSet])

  const [diagramModalOpen, setDiagramModalOpen] = useState(false)
  const [diagramPicked, setDiagramPicked] = useState<string[]>([])
  /** 父类追溯层数：0=不追溯；1=含直接父类；2=含祖父类 */
  const [baseDepth, setBaseDepth] = useState<0 | 1 | 2>(1)

  const handleGenerateFromFocus = () => {
    if (focusedSet.size === 0 && (focus.manual_additions || []).length === 0) {
      message.warning('该模块尚未勾选任何关注函数，请先在"关注函数选择"中勾选')
      return
    }
    if (scanFiles.length === 0) {
      message.error('该模块扫描结果未加载到前端（可能需要先切到"关注函数选择"面板触发扫描数据懒加载），稍后重试')
      return
    }
    const { classes: newClasses, functions: newFunctions, nv_original_functions: nvFns }
      = buildClassesFromFocus(mod, focusedSet, scanFiles, focus.manual_additions || [], { baseDepth })
    if (newClasses.length === 0 && newFunctions.length === 0) {
      message.warning(
        `关注函数未在当前扫描结果中命中（可能是重新扫描后 sha 变了）。`
        + `已尝试按 "类名::函数名" 回退匹配但仍无结果，请回到"关注函数选择"面板重新勾选。`,
      )
      return
    }
    onChange({
      classes: newClasses,
      functions: newFunctions,
      nv_original_functions: nvFns,
    })
    message.success(
      `已生成 ${newClasses.length} 个类（含 ${baseDepth} 层父类追溯）`
      + ` / ${newFunctions.length} 个独立函数 / ${nvFns.length} 个 NV 原始函数`,
    )
  }

  const openDiagramPicker = () => {
    if (availableClassNames.length === 0) {
      message.warning('该模块尚未扫描到任何类；请先在"关注函数选择"中确认已扫描')
      return
    }
    setDiagramPicked(defaultDiagramClasses.length > 0 ? defaultDiagramClasses : availableClassNames.slice(0, 5))
    setDiagramModalOpen(true)
  }

  const handleGenerateDiagram = () => {
    if (diagramPicked.length === 0) {
      message.warning('请至少勾选一个类')
      return
    }
    const uml = buildClassDiagramPlantUml(mod.name || mod.slug, diagramPicked, scanFiles, focusedSet)
    onChange({ class_diagram_plantuml: uml })
    setDiagramModalOpen(false)
    message.success(`已生成含 ${diagramPicked.length} 个类的类图`)
  }

  const addClass = () => {
    onChange({
      classes: [...classes, {
        design_id: nextClassId(mod),
        class_name: '',
        description: '',
        path: '',
        constants: [], variables: [], functions: [],
      }],
    })
  }

  const updateClass = (idx: number, field: keyof Swe3Class, value: any) => {
    const updated = [...classes]
    updated[idx] = { ...updated[idx], [field]: value }
    onChange({ classes: updated })
  }

  const deleteClass = (idx: number) => onChange({ classes: classes.filter((_, i) => i !== idx) })

  const addFunction = (inClass: Swe3Class | null, inClassIdx: number) => {
    const newFunc: Swe3Function = {
      design_id: nextFunctionId(mod, inClass),
      name: '', declaration: '', intro: '',
      parameters: [], returns: [], flowchart_plantuml: '',
    }
    if (inClass) {
      const updated = [...classes]
      updated[inClassIdx] = {
        ...updated[inClassIdx],
        functions: [...(updated[inClassIdx].functions || []), newFunc],
      }
      onChange({ classes: updated })
    } else {
      onChange({ functions: [...functions, newFunc] })
    }
  }

  const updateIndependentFunction = (idx: number, field: keyof Swe3Function, value: any) => {
    const updated = [...functions]
    updated[idx] = { ...updated[idx], [field]: value }
    onChange({ functions: updated })
  }

  const deleteIndependentFunction = (idx: number) =>
    onChange({ functions: functions.filter((_, i) => i !== idx) })

  const updateInClassFunction = (
    cIdx: number, fIdx: number, field: keyof Swe3Function, value: any,
  ) => {
    const updated = [...classes]
    const fs = [...(updated[cIdx].functions || [])]
    fs[fIdx] = { ...fs[fIdx], [field]: value }
    updated[cIdx] = { ...updated[cIdx], functions: fs }
    onChange({ classes: updated })
  }

  /**
   * 单条 AI 补齐函数介绍（和流程图），复用后端 /swe3/ai/augment-one 端点。
   * 要求：
   * - projectId 存在；
   * - 函数带 `source_key`（从关注函数自动生成时携带；手工新增/规则派生的无 key，禁用）。
   * aiBusy 保存正在生成的 design_id，用于按钮 loading。
   */
  const [aiBusy, setAiBusy] = useState<Set<string>>(new Set())
  const [aiBatchBusy, setAiBatchBusy] = useState(false)

  // R4.5 需求 #3：类列表默认全部展开成员函数。
  // 为什么用受控：defaultExpandAllRows 只在首次渲染生效；点"一键填充"后 classes
  // 由空变成有，仍需保持默认全展开，所以每次 classes 变化都同步 expandedKeys。
  // 用户手动折叠行后，effect 又会把它拉回展开 —— 这正是需求（"不显示函数就是 bug"）。
  const [expandedClassKeys, setExpandedClassKeys] = useState<readonly string[]>([])
  useEffect(() => {
    const keys = classes.filter((c) => (c.functions?.length || 0) > 0).map((c) => c.design_id)
    setExpandedClassKeys(keys)
    // 依赖拼接后的 design_id 列表，避免 classes 引用变化但内容未动时无谓 setState
  }, [classes.map((c) => `${c.design_id}:${(c.functions || []).length}`).join('|')])

  // R4.5 需求 #2：类列表左侧 Checkbox + 批量删除按钮。
  // 场景：nvsipl_camera / multicast 扫描出 36+ 类，用户只想留其中几个，逐行删太慢。
  // 删除语义：直接从 mod.classes 删行；类下未勾选的函数已经按 bridge 策略归到
  // nv_original_functions，和整个类一起消失。
  const [selectedClassKeys, setSelectedClassKeys] = useState<React.Key[]>([])
  const deleteSelectedClasses = () => {
    if (selectedClassKeys.length === 0) return
    const kept = classes.filter((c) => !selectedClassKeys.includes(c.design_id))
    onChange({ classes: kept })
    setSelectedClassKeys([])
  }

  /** 收集本模块里"介绍为空且有扫描 key"的函数（含类成员 + 独立函数），用于批量补齐。 */
  const collectEmptyIntroFuncs = (): Array<{
    kind: 'class' | 'free'
    cIdx?: number
    fIdx: number
    fn: Swe3Function
  }> => {
    const out: Array<{ kind: 'class' | 'free'; cIdx?: number; fIdx: number; fn: Swe3Function }> = []
    classes.forEach((c, cIdx) => {
      ;(c.functions || []).forEach((fn, fIdx) => {
        if (!fn.intro && fn.source_key) out.push({ kind: 'class', cIdx, fIdx, fn })
      })
    })
    functions.forEach((fn, fIdx) => {
      if (!fn.intro && fn.source_key) out.push({ kind: 'free', fIdx, fn })
    })
    return out
  }

  /**
   * 批量调 /augment-one 补齐本模块所有缺介绍的函数；一次只开 1 个并发，避免打爆后端。
   * 产生的回填直接写回 store（类/独立两条路径），不等整体结束。
   */
  const handleAiBatchModuleIntro = async () => {
    if (!projectId) { message.warning('项目未创建'); return }
    const todo = collectEmptyIntroFuncs()
    if (todo.length === 0) { message.info('没有需要补齐的函数'); return }
    setAiBatchBusy(true)
    let ok = 0, fail = 0
    for (const item of todo) {
      try {
        const res = await augmentOneFunction(projectId, mod.component_id, item.fn.source_key!)
        if (item.kind === 'class' && item.cIdx !== undefined) {
          updateInClassFunction(item.cIdx, item.fIdx, 'intro', res.data.ai_intro)
        } else {
          updateIndependentFunction(item.fIdx, 'intro', res.data.ai_intro)
        }
        ok += 1
      } catch { fail += 1 }
    }
    setAiBatchBusy(false)
    if (fail === 0) message.success(`AI 已补齐 ${ok} 个函数介绍`)
    else message.warning(`AI 补齐完成：成功 ${ok}，失败 ${fail}`)
  }

  const aiGenIntroForFunction = async (
    fn: Swe3Function,
    writeBack: (patch: Partial<Swe3Function>) => void,
    opts: { includeFlowchart?: boolean } = {},
  ) => {
    if (!projectId) { message.warning('项目未创建'); return }
    if (!fn.source_key) {
      message.warning('该函数没有扫描 key（手工新增或规则派生），请到"关注函数选择"重新勾选再生成，或手动填写介绍'); return
    }
    const designId = fn.design_id
    setAiBusy((prev) => new Set(prev).add(designId))
    try {
      const res = await augmentOneFunction(projectId, mod.component_id, fn.source_key)
      const patch: Partial<Swe3Function> = { intro: res.data.ai_intro }
      if (opts.includeFlowchart && res.data.ai_flowchart) {
        patch.flowchart_plantuml = res.data.ai_flowchart
      }
      writeBack(patch)
      message.success(opts.includeFlowchart ? 'AI 已生成介绍 + 流程图' : 'AI 已生成函数介绍')
    } catch (e: any) {
      message.error(e?.response?.data?.detail || 'AI 生成失败')
    } finally {
      setAiBusy((prev) => {
        const next = new Set(prev); next.delete(designId); return next
      })
    }
  }

  const deleteInClassFunction = (cIdx: number, fIdx: number) => {
    const updated = [...classes]
    updated[cIdx] = {
      ...updated[cIdx],
      functions: (updated[cIdx].functions || []).filter((_, i) => i !== fIdx),
    }
    onChange({ classes: updated })
  }

  const classColumns = [
    { title: '设计 ID', dataIndex: 'design_id', key: 'design_id', width: 220,
      render: (v: string) => <Tag color="geekblue">{v}</Tag> },
    { title: '类名', dataIndex: 'class_name', key: 'class_name', width: 180,
      render: (v: string, _r: Swe3Class, idx: number) =>
        <Input size="small" value={v} onChange={(e) => updateClass(idx, 'class_name', e.target.value)} /> },
    { title: '路径', dataIndex: 'path', key: 'path', width: 240,
      render: (v: string, _r: Swe3Class, idx: number) =>
        <Input size="small" value={v} onChange={(e) => updateClass(idx, 'path', e.target.value)} /> },
    { title: '说明', dataIndex: 'description', key: 'description',
      render: (v: string, _r: Swe3Class, idx: number) =>
        <Input size="small" value={v} onChange={(e) => updateClass(idx, 'description', e.target.value)} /> },
    { title: '函数数', key: 'func_count', width: 70,
      render: (_: any, r: Swe3Class) => <Tag>{r.functions?.length || 0}</Tag> },
    { title: '操作', key: 'actions', width: 60,
      render: (_: any, _r: Swe3Class, idx: number) =>
        <Popconfirm title="删除此类（含其所有函数）？" onConfirm={() => deleteClass(idx)}>
          <Button type="link" size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm> },
  ]

  return (
    <div>
      {/* 元信息 */}
      <Card size="small" title="模块元信息" style={{ marginBottom: 12 }}>
        <Space wrap size="middle">
          <Tag color="purple">组件 ID：{mod.component_id}</Tag>
          <span>Slug：<Input size="small" style={{ width: 160 }}
            value={mod.slug} onChange={(e) => onChange({ slug: e.target.value })} /></span>
          <span>展示名：<Input size="small" style={{ width: 180 }}
            value={mod.name} onChange={(e) => onChange({ name: e.target.value })} /></span>
          <span>章节标题：<Input size="small" style={{ width: 280 }}
            value={mod.title} onChange={(e) => onChange({ title: e.target.value })} /></span>
        </Space>
      </Card>

      {/* ★ 一键：从关注函数生成 类列表 + 独立函数列表 + NV 原始函数 */}
      <Card
        size="small"
        title={<Space><ThunderboltOutlined /><span>从关注函数自动生成</span></Space>}
        style={{ marginBottom: 12 }}
        extra={
          <Space wrap>
            <Tag color="green">已关注 {focusedSet.size}</Tag>
            <Tag color="blue">扫到类 {availableClassNames.length}</Tag>
            <Tag color={scanFiles.length > 0 ? 'cyan' : 'red'}>
              扫描文件 {scanFiles.length}
            </Tag>
            <span style={{ fontSize: 12, color: '#666' }}>父类追溯：</span>
            <Radio.Group size="small" value={baseDepth}
              onChange={(e) => setBaseDepth(e.target.value)}>
              <Radio.Button value={0}>不追溯</Radio.Button>
              <Radio.Button value={1}>直接父类</Radio.Button>
              <Radio.Button value={2}>祖父两层</Radio.Button>
            </Radio.Group>
            <Button size="small" type="primary" icon={<ThunderboltOutlined />}
              disabled={focusedSet.size === 0 && (focus.manual_additions || []).length === 0}
              onClick={handleGenerateFromFocus}>
              一键填充类/函数列表
            </Button>
            <Button size="small" icon={<ThunderboltOutlined />}
              loading={aiBatchBusy}
              disabled={!collectEmptyIntroFuncs().length}
              onClick={handleAiBatchModuleIntro}
              title="为本模块所有缺介绍且有扫描 key 的函数批量调 AI 生成介绍">
              AI 批量补介绍（{collectEmptyIntroFuncs().length}）
            </Button>
          </Space>
        }
      >
        {scanFiles.length === 0 ? (
          <Alert type="warning" showIcon
            message="该模块的扫描数据尚未加载到前端"
            description='正在后台拉取…若长时间无响应，请回到"关注函数选择"面板触发扫描数据加载后再回来。' />
        ) : focusedSet.size === 0 && (focus.manual_additions || []).length === 0 ? (
          <Alert type="info" showIcon
            message="该模块尚未勾选关注函数"
            description='请先在上方"关注函数选择（推送 D）"面板勾选函数，然后回到此处点"一键填充"。手工新增的函数也会同时并入独立函数列表。' />
        ) : (
          <Alert type="success" showIcon
            message={`当前关注 ${focusedSet.size} 个函数 + 手工 ${(focus.manual_additions || []).length} 个，可直接填充`}
            description={
              <>
                <div>• 类列表：按扫描时提取的类归属聚合；同类同名函数合并为一行；
                  <b>父类追溯</b>按右上角选项把 1~2 层直接父类/祖父类也加入列表（无详细函数展开）。</div>
                <div>• 详细函数（类下 / 独立）：从 <b>已勾选</b>的关注函数生成，复用 AI 介绍 / 流程图 / 参数签名。</div>
                <div>• NV 原始函数：扫描到但<b>未勾选</b>的函数全部登记，用于详设文档的"原始函数列表"章节。</div>
                <div>• 若重新扫描过工程，函数 sha 可能变化，会自动按 <code>类名::函数名</code> 回退匹配。</div>
                <div style={{ color: '#d46b08' }}>⚠ 覆盖写入会清掉手工新增的类/函数，请谨慎。</div>
              </>
            } />
        )}
      </Card>

      {/* 类图 PlantUML：用户可勾选参与类图的类，自动生成 UML */}
      <Card size="small"
        title={<Space><ApartmentOutlined /><span>类图 PlantUML（留空则导出占位）</span></Space>}
        style={{ marginBottom: 12 }}
        extra={
          <Button size="small" icon={<ApartmentOutlined />}
            disabled={availableClassNames.length === 0}
            onClick={openDiagramPicker}>
            从扫描到的类生成类图
          </Button>
        }>
        <Input.TextArea rows={6} value={mod.class_diagram_plantuml}
          onChange={(e) => onChange({ class_diagram_plantuml: e.target.value })}
          placeholder="@startuml ... @enduml" />
      </Card>

      {/* 类图：类挑选 Modal */}
      <Modal title="选择参与类图的类"
        open={diagramModalOpen}
        width={520}
        onCancel={() => setDiagramModalOpen(false)}
        onOk={handleGenerateDiagram}
        okText="生成类图">
        <Alert type="info" showIcon style={{ marginBottom: 8 }}
          message={`扫描到 ${availableClassNames.length} 个类；默认勾选为已有关注函数的类`} />
        <Checkbox.Group
          value={diagramPicked}
          onChange={(vs) => setDiagramPicked(vs as string[])}
          style={{ display: 'flex', flexDirection: 'column', maxHeight: 320, overflow: 'auto' }}>
          {availableClassNames.map((name) => (
            <Checkbox key={name} value={name} style={{ marginLeft: 0, padding: '2px 0' }}>
              <span style={{ fontFamily: 'monospace' }}>{name}</span>
              {defaultDiagramClasses.includes(name) && <Tag color="green" style={{ marginLeft: 8 }}>关注</Tag>}
            </Checkbox>
          ))}
        </Checkbox.Group>
        <div style={{ marginTop: 8 }}>
          <Space size="small">
            <Button size="small" onClick={() => setDiagramPicked(availableClassNames)}>全选</Button>
            <Button size="small" onClick={() => setDiagramPicked(defaultDiagramClasses)}>仅关注命中</Button>
            <Button size="small" onClick={() => setDiagramPicked([])}>清空</Button>
          </Space>
        </div>
      </Modal>

      {/* 类列表 */}
      <Card size="small"
        title={`类列表 (${classes.length})`}
        style={{ marginBottom: 12 }}
        extra={
          <Space>
            {selectedClassKeys.length > 0 && (
              <Popconfirm
                title={`确认删除选中的 ${selectedClassKeys.length} 个类？`}
                description="类下未勾选的函数会一并消失（原本就只登记到 NV 原始表）"
                onConfirm={deleteSelectedClasses}
              >
                <Button size="small" danger icon={<DeleteOutlined />}>
                  删除所选（{selectedClassKeys.length}）
                </Button>
              </Popconfirm>
            )}
            <Button size="small" icon={<PlusOutlined />} onClick={addClass}>添加类</Button>
          </Space>
        }>
        <Table
          rowKey="design_id"
          columns={classColumns}
          dataSource={classes}
          size="small"
          pagination={false}
          rowSelection={{
            selectedRowKeys: selectedClassKeys,
            onChange: (keys) => setSelectedClassKeys(keys),
            // 表头全选复选框
            columnWidth: 40,
          }}
          expandable={{
            // R4.5 需求 #3：受控展开，effect 把所有非空类拉到展开状态
            expandedRowKeys: expandedClassKeys as string[],
            onExpandedRowsChange: (keys) => setExpandedClassKeys(keys as string[]),
            // 行里没有函数时（父类追溯条目 / 空壳类）就不显示展开按钮，避免误以为能展开
            rowExpandable: (cls) => (cls.functions?.length || 0) > 0,
            expandedRowRender: (cls, cIdx) => (
              <ClassFunctionsTable
                cls={cls}
                onAddFunc={() => addFunction(cls, cIdx)}
                onUpdateFunc={(fIdx, field, val) => updateInClassFunction(cIdx, fIdx, field, val)}
                onDeleteFunc={(fIdx) => deleteInClassFunction(cIdx, fIdx)}
                aiBusy={aiBusy}
                onAiGenIntro={(fIdx, fn) => aiGenIntroForFunction(fn,
                  (patch) => updateInClassFunction(cIdx, fIdx, 'intro', patch.intro ?? fn.intro))}
              />
            ),
          }}
        />
      </Card>

      {/* 独立函数列表 */}
      <Card size="small"
        title={`独立函数列表 (${functions.length})`}
        style={{ marginBottom: 12 }}
        extra={<Button size="small" icon={<PlusOutlined />}
          onClick={() => addFunction(null, -1)}>添加函数</Button>}>
        {functions.length === 0 ? (
          <Tag>无（所有函数挂在类下）</Tag>
        ) : (
          <Table
            rowKey="design_id"
            size="small"
            pagination={false}
            dataSource={functions}
            columns={[
              { title: '设计 ID', dataIndex: 'design_id', width: 220,
                render: (v: string) => <Tag color="geekblue">{v}</Tag> },
              { title: '函数名', dataIndex: 'name', width: 180,
                render: (v: string, _r: Swe3Function, idx: number) =>
                  <Input size="small" value={v}
                    onChange={(e) => updateIndependentFunction(idx, 'name', e.target.value)} /> },
              { title: '介绍', dataIndex: 'intro',
                render: (v: string, r: Swe3Function, idx: number) => (
                  <Space.Compact style={{ display: 'flex', width: '100%' }}>
                    <Input size="small" value={v}
                      onChange={(e) => updateIndependentFunction(idx, 'intro', e.target.value)} />
                    <Button size="small" icon={<ThunderboltOutlined />}
                      loading={aiBusy.has(r.design_id)}
                      disabled={!r.source_key}
                      title={r.source_key ? 'AI 生成函数介绍（基于源码）' : '无扫描 key，无法 AI 生成'}
                      onClick={() => aiGenIntroForFunction(r,
                        (patch) => updateIndependentFunction(idx, 'intro', patch.intro ?? v))} />
                  </Space.Compact>
                ) },
              { title: '声明', dataIndex: 'declaration',
                render: (v: string, _r: Swe3Function, idx: number) =>
                  <Input size="small" value={v}
                    onChange={(e) => updateIndependentFunction(idx, 'declaration', e.target.value)} /> },
              { title: '操作', key: 'actions', width: 60,
                render: (_: any, _r: Swe3Function, idx: number) =>
                  <Popconfirm title="删除？" onConfirm={() => deleteIndependentFunction(idx)}>
                    <Button type="link" size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm> },
            ]}
          />
        )}
      </Card>

      {/* NV 原始函数列表 — 用于详设文档"原始函数列表"章节；来自未勾选的扫描函数 */}
      <Card size="small"
        title={`NV 原始函数列表 (${(mod.nv_original_functions || []).length})`}
        style={{ marginBottom: 12 }}
        extra={
          <Space>
            <Tag color="orange">仅登记未勾选函数，不展开详细设计</Tag>
            <Popconfirm title="清空 NV 原始函数列表？" onConfirm={() => onChange({ nv_original_functions: [] })}>
              <Button size="small" danger icon={<DeleteOutlined />}>清空</Button>
            </Popconfirm>
          </Space>
        }>
        {(mod.nv_original_functions || []).length === 0 ? (
          <Tag>无（请点上方"一键填充"自动生成）</Tag>
        ) : (
          <Table
            rowKey="design_id"
            size="small"
            pagination={{ pageSize: 20, size: 'small' }}
            dataSource={mod.nv_original_functions}
            columns={[
              { title: '设计 ID', dataIndex: 'design_id', width: 220,
                render: (v: string) => <Tag color="orange">{v}</Tag> },
              { title: '函数名', dataIndex: 'name', width: 260,
                render: (v: string) => <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{v}</span> },
              { title: '声明', dataIndex: 'declaration',
                render: (v: string) => (
                  <span style={{ fontFamily: 'monospace', fontSize: 12, color: '#555' }}>
                    {v || <Tag>-</Tag>}
                  </span>
                ) },
              { title: '操作', key: 'actions', width: 60,
                render: (_: any, _r: Swe3Function, idx: number) => (
                  <Popconfirm title="删除此行？" onConfirm={() => {
                    const next = [...(mod.nv_original_functions || [])].filter((_, i) => i !== idx)
                    onChange({ nv_original_functions: next })
                  }}>
                    <Button type="link" size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                ) },
            ]}
          />
        )}
      </Card>

      {/* 单元时序图 PlantUML */}
      <Card size="small" title="单元时序图 PlantUML" style={{ marginBottom: 12 }}>
        <Input.TextArea rows={3} value={mod.sequence_plantuml}
          onChange={(e) => onChange({ sequence_plantuml: e.target.value })}
          placeholder="@startuml ... @enduml" />
      </Card>

      {/* A008 Camera Security 专用 */}
      {mod.component_id === 'A008' && (
        <Card size="small" title="Camera Security 功能安全目标 + 流程设计" style={{ marginBottom: 12 }}>
          {!mod.security_goals && (
            <Button size="small" style={{ marginBottom: 8 }} onClick={() => {
              onChange({
                security_goals: { authentication: '', data_protection: '', key_management: '' },
                flow_design: { detailed_plan: '', implementation: '', flowchart_plantuml: '' },
              })
              message.success('已初始化')
            }}>初始化安全目标字段</Button>
          )}
          {mod.security_goals && (
            <>
              <div style={{ marginBottom: 8 }}>
                <div style={{ fontWeight: 500 }}>身份验证</div>
                <Input.TextArea rows={2} value={mod.security_goals.authentication}
                  onChange={(e) => onChange({
                    security_goals: { ...mod.security_goals!, authentication: e.target.value },
                  })} />
              </div>
              <div style={{ marginBottom: 8 }}>
                <div style={{ fontWeight: 500 }}>数据保护</div>
                <Input.TextArea rows={2} value={mod.security_goals.data_protection}
                  onChange={(e) => onChange({
                    security_goals: { ...mod.security_goals!, data_protection: e.target.value },
                  })} />
              </div>
              <div style={{ marginBottom: 8 }}>
                <div style={{ fontWeight: 500 }}>密钥管理</div>
                <Input.TextArea rows={2} value={mod.security_goals.key_management}
                  onChange={(e) => onChange({
                    security_goals: { ...mod.security_goals!, key_management: e.target.value },
                  })} />
              </div>
            </>
          )}
        </Card>
      )}
    </div>
  )
}

function ClassFunctionsTable({
  cls, onAddFunc, onUpdateFunc, onDeleteFunc, aiBusy, onAiGenIntro,
}: {
  cls: Swe3Class
  onAddFunc: () => void
  onUpdateFunc: (fIdx: number, field: keyof Swe3Function, value: any) => void
  onDeleteFunc: (fIdx: number) => void
  aiBusy: Set<string>
  onAiGenIntro: (fIdx: number, fn: Swe3Function) => void
}) {
  const funcs = cls.functions || []
  return (
    <div style={{ background: '#fafafa', padding: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
        <strong>类 {cls.class_name} 的函数列表（{funcs.length}）</strong>
        <Button size="small" icon={<PlusOutlined />} onClick={onAddFunc}>添加函数</Button>
      </div>
      {funcs.length === 0 ? (
        <Tag>无</Tag>
      ) : (
        <Table
          rowKey="design_id"
          size="small"
          pagination={false}
          dataSource={funcs}
          columns={[
            { title: '设计 ID', dataIndex: 'design_id', width: 220,
              render: (v: string) => <Tag color="geekblue">{v}</Tag> },
            { title: '函数名', dataIndex: 'name', width: 180,
              render: (v: string, _r: Swe3Function, idx: number) =>
                <Input size="small" value={v}
                  onChange={(e) => onUpdateFunc(idx, 'name', e.target.value)} /> },
            { title: '介绍', dataIndex: 'intro',
              render: (v: string, r: Swe3Function, idx: number) => (
                <Space.Compact style={{ display: 'flex', width: '100%' }}>
                  <Input size="small" value={v}
                    onChange={(e) => onUpdateFunc(idx, 'intro', e.target.value)} />
                  <Button size="small" icon={<ThunderboltOutlined />}
                    loading={aiBusy.has(r.design_id)}
                    disabled={!r.source_key}
                    title={r.source_key ? 'AI 生成函数介绍（基于源码）' : '无扫描 key，无法 AI 生成'}
                    onClick={() => onAiGenIntro(idx, r)} />
                </Space.Compact>
              ) },
            { title: '声明', dataIndex: 'declaration',
              render: (v: string, _r: Swe3Function, idx: number) =>
                <Input size="small" value={v}
                  onChange={(e) => onUpdateFunc(idx, 'declaration', e.target.value)} /> },
            { title: '操作', key: 'actions', width: 60,
              render: (_: any, _r: Swe3Function, idx: number) =>
                <Popconfirm title="删除？" onConfirm={() => onDeleteFunc(idx)}>
                  <Button type="link" size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm> },
          ]}
        />
      )}
    </div>
  )
}
