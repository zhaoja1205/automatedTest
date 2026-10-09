/**
 * C++ 函数 → Mermaid 流程图 解析/构建器
 *
 * 由项目根目录的独立工具 cpp-flowchart-generator.html 移植而来，
 * 对齐 image728.png 的纵向流程图风格（起止/判断/处理/日志-返回节点）。
 *
 * 支持解析：函数入口、变量声明、函数调用、if/else 分支、早返回、日志、赋值、最终返回。
 */

/* ----------------- Lexer helpers ----------------- */
export function stripComments(s: string): string {
  let out = '', i = 0, n = s.length
  while (i < n) {
    if (s[i] === '/' && s[i + 1] === '*') {
      i += 2
      while (i < n && !(s[i] === '*' && s[i + 1] === '/')) i++
      i += 2
      out += ' '
      continue
    }
    if (s[i] === '/' && s[i + 1] === '/') {
      while (i < n && s[i] !== '\n') i++
      continue
    }
    if (s[i] === '"' || s[i] === "'") {
      const q = s[i]
      out += s[i++]
      while (i < n && s[i] !== q) {
        if (s[i] === '\\') out += s[i++]
        out += s[i++]
      }
      out += s[i++]
      continue
    }
    out += s[i++]
  }
  return out
}

// Find matching close bracket starting at openIdx (which points at the opener).
export function matchBracket(src: string, openIdx: number): number {
  const open = src[openIdx]
  const close = ({ '(': ')', '{': '}', '[': ']' } as Record<string, string>)[open]
  let depth = 0, i = openIdx, n = src.length
  for (; i < n; i++) {
    const c = src[i]
    if (c === '/' && src[i + 1] === '/') { while (i < n && src[i] !== '\n') i++; continue }
    if (c === '"' || c === "'") {
      const q = c; i++
      while (i < n && src[i] !== q) { if (src[i] === '\\') i++; i++ }
      continue
    }
    if (c === open) depth++
    else if (c === close) { depth--; if (depth === 0) return i }
  }
  return -1
}

export interface FuncInfo {
  signature: string
  body: string
}

/* ----------------- Extract function ----------------- */
export function extractFunction(src: string): FuncInfo | null {
  const s = stripComments(src)
  const m = s.match(/([A-Za-z_][\w:<>,\s\*&~]*?)\s+([A-Za-z_][\w]*(?:::[A-Za-z_][\w]*)*)\s*\(([^;{}]*?)\)\s*(?:const)?\s*\{/)
  if (!m || m.index === undefined) return null
  const headerEnd = m.index + m[0].length
  const close = matchBracket(s, m.index + m[0].lastIndexOf('{'))
  if (close < 0) return null
  return {
    signature: (m[1].trim() + ' ' + m[2].trim() + '(' + m[3].trim() + ')').replace(/\s+/g, ' '),
    body: s.slice(headerEnd, close),
  }
}

/* ----------------- Recursive parser ----------------- */
export type FlowNode =
  | { type: 'stmt'; text: string }
  | { type: 'decl'; text: string }
  | { type: 'log'; text: string }
  | { type: 'return'; text: string }
  | { type: 'if'; cond: string; then: FlowNode[]; else: FlowNode[] }

function skipWs(src: string, i: number): number {
  while (i < src.length && /\s/.test(src[i])) i++
  return i
}

function readUntilSemi(src: string, p: number): { text: string; end: number } {
  let i = p, n = src.length, pd = 0, bd = 0, inStr: string | null = null, buf = ''
  for (; i < n; i++) {
    const c = src[i]
    if (inStr) { buf += c; if (c === inStr && src[i - 1] !== '\\') inStr = null; continue }
    if (c === '"' || c === "'") { inStr = c; buf += c; continue }
    if (c === '(' || c === '[') pd++
    else if (c === ')' || c === ']') pd--
    // 花括号也算深度：聚合初始化 `T arr[] = { {…}, {…} };` 里的 `;` 必须落在
    // 最外层。不然会在数组末尾之前误 return，甚至把 subobject 内容当整条 activity
    else if (c === '{') bd++
    else if (c === '}') bd--
    if (c === ';' && pd === 0 && bd === 0) return { text: buf, end: i + 1 }
    buf += c
  }
  return { text: buf, end: i }
}

function readCond(src: string, p: number): { cond: string; end: number } {
  const close = matchBracket(src, p)
  if (close < 0) return { cond: '', end: p }
  return { cond: src.slice(p + 1, close).trim(), end: close + 1 }
}

function classify(t: string): FlowNode | null {
  t = t.trim().replace(/;$/, '')
  if (!t) return null
  if (/^return\b/.test(t)) return { type: 'return', text: t }
  if (/\b(SIPL_LOG|LOG_ERR|LOG_DBG|LOG_INFO|printf|fprintf|SIPL_LOG_ERR_STR(_INT)?)\b/.test(t)) return { type: 'log', text: t }
  if (/^(static\s+)?(const\s+)?(inline\s+)?[A-Za-z_][\w:<>*\s&]*?\s+\*?\s*[A-Za-z_]\w*\s*(\=|\[)/.test(t) && !/^if\b|^for\b|^while\b|^switch\b/.test(t))
    return { type: 'decl', text: t }
  return { type: 'stmt', text: t }
}

function readSubBlock(src: string, p: number): { nodes: FlowNode[]; end: number } {
  let i = skipWs(src, p)
  if (src[i] === '{') {
    const close = matchBracket(src, i)
    const inner = src.slice(i + 1, close)
    return { nodes: parseBody(inner), end: close + 1 }
  }
  const r = readUntilSemi(src, i)
  const st = r.text.trim().replace(/;$/, '')
  return { nodes: st ? [classify(st)].filter(Boolean) as FlowNode[] : [], end: r.end }
}

export function parseBody(src: string): FlowNode[] {
  const out: FlowNode[] = []
  let i = 0, n = src.length
  while (i < n) {
    i = skipWs(src, i)
    if (i >= n) break
    if (src[i] === '{') {
      const close = matchBracket(src, i)
      out.push(...parseBody(src.slice(i + 1, close)))
      i = close + 1
      continue
    }
    const kwMatch = src.slice(i).match(/^(if|else if|for|while|switch)\b/)
    if (kwMatch) {
      const kw = kwMatch[1]
      if (kw === 'if' || kw === 'else if') {
        const condStart = src.indexOf('(', i)
        const condRes = readCond(src, condStart)
        let j = skipWs(src, condRes.end)
        const thenBlock = readSubBlock(src, j)
        let k = skipWs(src, thenBlock.end)
        let elseNodes: FlowNode[] = []
        if (src.slice(k).match(/^else\b/)) {
          k = skipWs(src, k + 4)
          if (src.slice(k).match(/^if\b/)) {
            const ec = src.indexOf('(', k)
            const ecR = readCond(src, ec)
            const ebStart = skipWs(src, ecR.end)
            const eb = readSubBlock(src, ebStart)
            elseNodes = [{ type: 'if', cond: ecR.cond, then: eb.nodes, else: [] }]
            k = eb.end
          } else {
            const eb = readSubBlock(src, k)
            elseNodes = eb.nodes
            k = eb.end
          }
        }
        out.push({ type: 'if', cond: (kw === 'else if' ? 'else if ' : '') + condRes.cond, then: thenBlock.nodes, else: elseNodes })
        i = k
        continue
      }
      const condStart = src.indexOf('(', i)
      const condRes = readCond(src, condStart)
      let j = skipWs(src, condRes.end)
      const block = readSubBlock(src, j)
      out.push({ type: 'stmt', text: kw + ' (' + condRes.cond + ')' })
      out.push(...block.nodes)
      i = block.end
      continue
    }
    if (src.slice(i).match(/^else\b/)) {
      i = skipWs(src, i + 4)
      const eb = readSubBlock(src, i)
      out.push(...eb.nodes)
      i = eb.end
      continue
    }
    const r = readUntilSemi(src, i)
    const st = r.text.trim().replace(/;$/, '')
    if (st) {
      const c = classify(st)
      if (c) out.push(c)
    }
    i = r.end
  }
  return out
}

/* ----------------- Build Mermaid ----------------- */
const LOG_RE = /\b(SIPL_LOG|LOG_ERR|LOG_DBG|LOG_INFO|printf|fprintf|SIPL_LOG_ERR_STR(_INT)?)\b/
const DECL_RE = /^(static\s+)?(const\s+)?(inline\s+)?[A-Za-z_][\w:<>*\s&]*?\s+\*?\s*[A-Za-z_]\w*\s*(\=|\[)/

let idc = 0
interface MNode { id: string; type: string; label: string }
interface MEdge { from: string; to: string; label: string }
let nodes: MNode[] = []
let edges: MEdge[] = []

function nid(): string { return 'n' + (idc++) }
// Mermaid v10 节点标签清理：把破坏语法的字符替换成视觉相近的 Unicode 全角字符，
// Mermaid 直接作为纯文本渲染，肉眼几乎无差异。
function esc(s: string): string {
  return String(s)
    .replace(/"/g, '＂')  // 全角引号
    .replace(/\(/g, '❨')  // U+2768
    .replace(/\)/g, '❩')  // U+2769
    .replace(/\[/g, '⟦')  // U+27E6
    .replace(/\]/g, '⟧')  // U+27E7
    .replace(/\{/g, '❴')  // U+2774
    .replace(/\}/g, '❵')  // U+2775
    .replace(/\|/g, '❘')  // U+2758
    .replace(/&/g, '＆')  // 全角
    .replace(/</g, '＜')  // 全角
    .replace(/>/g, '＞')  // 全角
    .replace(/#/g, '＃')  // 全角
    .replace(/`/g, '＇')
    .replace(/\s+/g, ' ')
    .trim()
}
// 不再截断标签，让 Mermaid 自适应节点宽度显示完整文本
function label(s: string): string { return esc(s) }
function addNode(type: string, label: string): string { const id = nid(); nodes.push({ id, type, label }); return id }
function edge(a: string, b: string, label = ''): void { edges.push({ from: a, to: b, label }) }

function stmtNode(text: string): string {
  if (LOG_RE.test(text)) return addNode('log', label(text.replace(/;$/, '')))
  if (DECL_RE.test(text) && !/^if\b|^for\b|^while\b/.test(text)) return addNode('decl', label(text.replace(/;$/, '')))
  return addNode('process', label(text.replace(/;$/, '')))
}

interface PlanItem {
  node: FlowNode
  kind: 'if' | 'return' | 'log' | 'decl' | 'stmt'
  entryId: string
  cont?: string
  thenPlan?: PlanItem[]
  elsePlan?: PlanItem[] | null
  thenHead?: string
  elseHead?: string | null
}

function allocList(list: FlowNode[]): PlanItem[] {
  const plan: PlanItem[] = []
  for (const node of list) {
    if (node.type === 'if') {
      const decId = addNode('decision', label(node.cond))
      plan.push({ node, kind: 'if', entryId: decId })
    } else if (node.type === 'return') {
      const id = addNode('log', 'return ' + label(node.text.replace(/^return\s*/, '')))
      plan.push({ node, kind: 'return', entryId: id })
    } else if (node.type === 'log') {
      const id = addNode('log', label(node.text.replace(/;$/, '')))
      plan.push({ node, kind: 'log', entryId: id })
    } else if (node.type === 'decl') {
      const id = addNode('decl', label(node.text.replace(/;$/, '')))
      plan.push({ node, kind: 'decl', entryId: id })
    } else {
      const id = stmtNode((node as { text: string }).text)
      plan.push({ node, kind: 'stmt', entryId: id })
    }
  }
  return plan
}

function finalizeList(plan: PlanItem[], contId: string): void {
  for (let i = 0; i < plan.length; i++) {
    const p = plan[i]
    p.cont = (i + 1 < plan.length) ? plan[i + 1].entryId : contId
    if (p.kind === 'if') {
      const node = p.node as Extract<FlowNode, { type: 'if' }>
      p.thenPlan = allocList(node.then || [])
      finalizeList(p.thenPlan, p.cont)
      p.elsePlan = (node.else && node.else.length) ? allocList(node.else) : null
      if (p.elsePlan) finalizeList(p.elsePlan, p.cont)
      p.thenHead = p.thenPlan.length ? p.thenPlan[0].entryId : p.cont
      p.elseHead = p.elsePlan && p.elsePlan.length ? p.elsePlan[0].entryId : null
    }
  }
}

function chainPlan(plan: PlanItem[], entryId: string): string | null {
  let prev: string | null = entryId
  for (const p of plan) {
    if (p.kind === 'if') {
      // 若 prev 与当前决策节点相同（分支头即是自己），跳过自环
      if (prev !== null && prev !== p.entryId) edge(prev, p.entryId, '')
      if (p.thenPlan && p.thenPlan.length) {
        edge(p.entryId, p.thenHead!, 'Yes')
        const thenTail = chainPlan(p.thenPlan, p.thenHead!)
        if (thenTail !== null && thenTail !== p.cont!) edge(thenTail, p.cont!, '')
      } else {
        edge(p.entryId, p.cont!, 'Yes')
      }
      if (p.elsePlan && p.elsePlan.length) {
        edge(p.entryId, p.elseHead!, 'No')
        const elseTail = chainPlan(p.elsePlan, p.elseHead!)
        if (elseTail !== null && elseTail !== p.cont!) edge(elseTail, p.cont!, '')
      } else {
        edge(p.entryId, p.cont!, 'No')
      }
      prev = null
    } else if (p.kind === 'return') {
      if (prev !== null && prev !== p.entryId) edge(prev, p.entryId, '')
      edge(p.entryId, 'END', '')
      prev = null
    } else {
      if (prev !== null && prev !== p.entryId) edge(prev, p.entryId, '')
      prev = p.entryId
    }
  }
  return prev
}

export interface BuildResult {
  md: string
  count: number
}

/**
 * 生成 Mermaid 源码。固定纵向 TD 布局：
 * 需要重新排布时由前端 SVG 节点拖拽实现，不再在这里做多方向/多列切分。
 */
export function buildMermaid(func: FuncInfo): BuildResult {
  idc = 0
  nodes = []
  edges = []
  // 起始节点第一行"开始 · 函数签名"（Mermaid 纯文本模式下无换行，直接一行显示）
  const sigLabel = '开始 · ' + label(func.signature)
  const startId = addNode('start', sigLabel)
  nodes.push({ id: 'END', type: 'end', label: '结束' })

  const body = parseBody(func.body)
  const rootPlan = allocList(body)
  finalizeList(rootPlan, 'END')
  const rootTail = chainPlan(rootPlan, startId)
  if (rootTail !== null) edge(rootTail, 'END', '')

  const seen = new Set<string>()
  edges = edges.filter(e => {
    const k = e.from + '|' + e.to + '|' + (e.label || '')
    if (seen.has(k)) return false
    seen.add(k)
    return true
  })

  let md = 'flowchart TD\n'
  for (const nd of nodes) {
    // 用双引号包裹标签内容以避免 Mermaid 解析器把标签中的字符当作语法
    if (nd.type === 'start') md += `  ${nd.id}(["${nd.label}"]):::startNode\n`
    else if (nd.type === 'end') md += `  ${nd.id}(["${nd.label}"]):::endNode\n`
    else if (nd.type === 'decision') md += `  ${nd.id}{"${nd.label}"}:::decNode\n`
    else if (nd.type === 'log') md += `  ${nd.id}["${nd.label}"]:::logNode\n`
    else if (nd.type === 'decl') md += `  ${nd.id}["${nd.label}"]:::declNode\n`
    else md += `  ${nd.id}["${nd.label}"]:::procNode\n`
  }
  for (const e of edges) {
    if (e.label) md += `  ${e.from} -- ${e.label} --> ${e.to}\n`
    else md += `  ${e.from} --> ${e.to}\n`
  }
  md += `  classDef startNode fill:#e0f2fe,stroke:#0284c7,stroke-width:1.5px,color:#0c4a6e;\n`
  md += `  classDef endNode fill:#fee2e2,stroke:#dc2626,stroke-width:1.5px,color:#991b1b;\n`
  md += `  classDef decNode fill:#fef3c7,stroke:#d97706,stroke-width:1.5px,color:#92400e;\n`
  md += `  classDef procNode fill:#f1f5f9,stroke:#64748b,stroke-width:1px,color:#1f2937;\n`
  md += `  classDef declNode fill:#ecfdf5,stroke:#059669,stroke-width:1px,color:#064e3b;\n`
  md += `  classDef logNode fill:#fff7ed,stroke:#ea580c,stroke-width:1px,color:#9a3412;\n`
  return { md, count: nodes.length }
}

/* ----------------- Build PlantUML ----------------- */

/**
 * 输出 PlantUML activity beta 语法（`:...;`、`if () then (yes) ... else (no) ... endif`）
 * 而不是老 activity（`(*) --> "..."`）—— beta 语法对 if/else、多分支、条件标签
 * 支持更好，plantuml.com 渲染出来的箭头、菱形也更贴近工业流程图。
 *
 * 每个节点前缀成不同的图形/颜色：
 *   :xxx;   矩形处理块（默认灰蓝色）
 *   :log/return;   带颜色高亮
 *   if / then / else / endif —— 判断菱形
 */

/** PlantUML 标签清理：转义反斜杠 / 换成全角引号和括号 / 折叠空白
 *
 * PlantUML activity beta 里 `{` `}` `[` `]` `|` 都有特殊含义（分组、注释、
 * partition），activity 文本原样出现会让解析器报错并返回空 SVG。全角替换是
 * 视觉最接近的无损兜底方案 —— 显示上仍是括号，不影响可读性。
 *
 * 长度硬截断：单个 activity 文本超过 ~300 字符时 plantuml.com 会直接
 * 400（内部 Graphviz label 长度限制），实际例子是聚合初始化列表
 * `T arr[] = { {…}, {…}, … };` 展开到 3000+ 字符。截到 240 保底。 */
function plantLabel(s: string): string {
  let out = String(s)
    .replace(/\\/g, '\\\\')
    .replace(/"/g, '＂')
    .replace(/\{/g, '❴')  // U+2774
    .replace(/\}/g, '❵')  // U+2775
    .replace(/\[/g, '⟦')  // U+27E6
    .replace(/\]/g, '⟧')  // U+27E7
    .replace(/\|/g, '❘')  // U+2758
    .replace(/\r?\n/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  const MAX = 240
  if (out.length > MAX) out = out.slice(0, MAX) + ' …⟨截断⟩'
  return out
}

/**
 * 递归把 FlowNode[] 输出为 PlantUML activity beta 片段。
 *
 * 颜色使用新语法 `:label; <<#RRGGBB>>` —— 老写法 `#RRGGBB:label;`
 * 在新版 PlantUML 会打 deprecation 警告（"This syntax is deprecated
 * and the color is ignored"）并直接忽略颜色，图上会飘一堆黄色横条。
 */
function plantEmit(list: FlowNode[], out: string[], indent = '', colored = true): void {
  for (const n of list) {
    if (n.type === 'return') {
      // 早返回：用 stop 结束当前流；配色用红（colored 模式）
      out.push(colored
        ? `${indent}:${plantLabel(n.text)}; <<#FFE4E6>>`
        : `${indent}:${plantLabel(n.text)};`)
      out.push(`${indent}stop`)
      continue
    }
    if (n.type === 'log') {
      out.push(colored
        ? `${indent}:${plantLabel(n.text)}; <<#FFEDD5>>`
        : `${indent}:${plantLabel(n.text)};`)
      continue
    }
    if (n.type === 'decl') {
      out.push(colored
        ? `${indent}:${plantLabel(n.text)}; <<#DCFCE7>>`
        : `${indent}:${plantLabel(n.text)};`)
      continue
    }
    if (n.type === 'stmt') {
      out.push(`${indent}:${plantLabel(n.text)};`)
      continue
    }
    if (n.type === 'if') {
      // if 分支：cond 里可能已经带 "else if "，PlantUML 不需要这个前缀
      const cond = plantLabel(n.cond.replace(/^else if\s+/, ''))
      out.push(`${indent}if (${cond}) then (yes)`)
      plantEmit(n.then, out, indent + '  ', colored)
      if (n.else.length > 0) {
        out.push(`${indent}else (no)`)
        plantEmit(n.else, out, indent + '  ', colored)
      } else {
        // 保留 else 分支以便渲染时形成对称菱形（走空路径直连汇合点）
        out.push(`${indent}else (no)`)
      }
      out.push(`${indent}endif`)
      continue
    }
  }
}

export interface PlantResult {
  /** 完整 PlantUML 源码（@startuml … @enduml） */
  uml: string
  /** 节点/语句条数（用于状态栏显示） */
  count: number
}

export function buildPlantUML(func: FuncInfo, colored = true): PlantResult {
  const body = parseBody(func.body)
  const lines: string[] = []
  lines.push('@startuml')
  // 一些让流程图更好看的皮肤配置
  lines.push('skinparam defaultFontName "PingFang SC, Microsoft YaHei, Segoe UI"')
  lines.push('skinparam defaultFontSize 12')
  lines.push('skinparam activity {')
  if (colored) {
    lines.push('  BackgroundColor #F1F5F9')
    lines.push('  BorderColor #64748B')
    lines.push('  FontColor #1F2937')
    lines.push('  DiamondBackgroundColor #FEF3C7')
    lines.push('  DiamondBorderColor #D97706')
    lines.push('  DiamondFontColor #92400E')
    lines.push('  StartColor #0284C7')
    lines.push('  EndColor #DC2626')
    lines.push('  ArrowColor #475569')
  } else {
    lines.push('  BackgroundColor #FFFFFF')
    lines.push('  BorderColor #444444')
    lines.push('  FontColor #000000')
    lines.push('  DiamondBackgroundColor #FFFFFF')
    lines.push('  DiamondBorderColor #444444')
    lines.push('  DiamondFontColor #000000')
    lines.push('  StartColor #000000')
    lines.push('  EndColor #000000')
    lines.push('  ArrowColor #444444')
  }
  lines.push('}')
  lines.push('start')
  // 首节点：函数签名（新语法：`:label; <<#color>>`，无色模式去掉颜色注解）
  lines.push(colored
    ? `:开始 · ${plantLabel(func.signature)}; <<#E0F2FE>>`
    : `:开始 · ${plantLabel(func.signature)};`)
  let count = 2
  const before = lines.length
  plantEmit(body, lines, '', colored)
  for (let i = before; i < lines.length; i++) {
    const t = lines[i].trim()
    if (t.startsWith(':') || t.startsWith('if ')) count++
  }
  lines.push(colored ? `:结束; <<#FEE2E2>>` : `:结束;`)
  lines.push('stop')
  lines.push('@enduml')
  return { uml: lines.join('\n'), count }
}

/**
 * 把 PlantUML 源码编码成 URL。策略：
 *
 *   1) 首选 deflate + PlantUML-base64（长度只有 hex 的 ~25%）
 *   2) 兜底 hex（`~h<hex>`）—— 不依赖 deflate、无中间过程
 *
 * URL 目标由 `directPlantUmlHost()` 决定：
 *   - 默认走**后端代理** `/api/plantuml/render`——浏览器直连 plantuml.com
 *     经常挂在 TLS/DNS/GFW（用户看到 `Failed to fetch`），后端代理绕开
 *   - 兜底可在浏览器控制台设 `window.__DIRECT_PLANTUML__ = true` 强制直连
 *     用于调试后端代理本身的问题
 *
 * 不用 GET `~1` deflate 前缀 —— 官方文档虽然写了但服务器实际支持有起伏，
 * "无前缀 + PlantUML-base64" 是最稳的姿势。
 */
import { deflateRaw } from 'pako'

/** PlantUML 特殊 base64 字符表：位序 0..63 = 0-9A-Za-z-_ */
const PU_ALPHABET = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_'

/** 每 3 字节 → 4 字符（和标准 base64 顺序相同，只是字符表不同） */
function encodePlantUmlBase64(bytes: Uint8Array): string {
  let out = ''
  const n = bytes.length
  for (let i = 0; i < n; i += 3) {
    const b1 = bytes[i]
    const b2 = i + 1 < n ? bytes[i + 1] : 0
    const b3 = i + 2 < n ? bytes[i + 2] : 0
    out += PU_ALPHABET[(b1 >> 2) & 0x3f]
    out += PU_ALPHABET[((b1 << 4) | (b2 >> 4)) & 0x3f]
    out += PU_ALPHABET[((b2 << 2) | (b3 >> 6)) & 0x3f]
    out += PU_ALPHABET[b3 & 0x3f]
  }
  return out
}

/** 判断是否强制直连 plantuml.com（调试后端代理时用） */
function useDirect(): boolean {
  try {
    return Boolean((window as unknown as { __DIRECT_PLANTUML__?: boolean }).__DIRECT_PLANTUML__)
  } catch {
    return false
  }
}

export function plantUmlToUrl(uml: string, format: 'svg' | 'png' = 'svg'): string {
  const bytes = new TextEncoder().encode(uml)
  // level 9 = 最高压缩率；PlantUML 期望的是"裸 deflate"（raw，无 zlib 头），
  // 所以用 deflateRaw 而不是 deflate。
  const compressed = deflateRaw(bytes, { level: 9 })
  const encoded = encodePlantUmlBase64(compressed)
  if (useDirect()) return `https://www.plantuml.com/plantuml/${format}/${encoded}`
  // 后端代理端点：GET /api/plantuml/render?fmt=svg&encoded=<...>
  // 后端拼成 https://www.plantuml.com/plantuml/<fmt>/<encoded> 再转发
  return `/api/plantuml/render?fmt=${format}&encoded=${encodeURIComponent(encoded)}`
}

/**
 * hex 编码兜底方案（保留 export 名以兼容旧调用）。URL 较长，
 * 但不依赖 deflate、无中间过程，服务端一定能解。当 deflate 版拉不动时用。
 *
 * 同样走后端代理；hex 格式在 URL 里加 `~h` 前缀，后端透传给 plantuml.com。
 */
export function plantUmlToHexUrl(uml: string, format: 'svg' | 'png' = 'svg'): string {
  const bytes = new TextEncoder().encode(uml)
  let hex = ''
  for (const b of bytes) hex += b.toString(16).padStart(2, '0')
  if (useDirect()) return `https://www.plantuml.com/plantuml/${format}/~h${hex}`
  return `/api/plantuml/render?fmt=${format}&encoded=${encodeURIComponent('~h' + hex)}`
}

export const EXAMPLE_CPP = `SIPLStatus CNvMMAX96724_96717F_IMX623::GetMax96717FErrorInfo(
    ErrorStatus *buffer, const std::size_t bufferSize, std::size_t &size) {
    SIPLStatus status = NVSIPL_STATUS_OK;
    NvMediaStatus mediaStatus = NVMEDIA_STATUS_OK;
    uint8_t err_byte[3] = {0};
    CNvMSerializer *const serializer = GetUpSerializer();
    mediaStatus = MAX96717FReadErrorStatus(serializer->GetCDIDeviceHandle(), sizeof(err_byte), err_byte);
    if (mediaStatus != NVMEDIA_STATUS_OK) {
        SIPL_LOG_ERR_STR_INT("MAX96717F: ReadErrorStatus failed with NvMedia error", static_cast<int32_t>(mediaStatus));
        status = ConvertNvMediaStatus(mediaStatus);
        return status;
    }
    if (((err_byte[0] & 0x20U) == 0U) && ((err_byte[0] & 0x80U) != 0U)) {
        buffer->globalFailureType[buffer->count] = CDI_MAX96717_LBIST_ERR;
        buffer->predevFailureType[buffer->count] = SERIALIZER_ERROR;
        if (buffer->count < MAX_GLOBAL_ERROR_NUM - 1U) { buffer->count++; }
        SIPL_LOG_ERR_STR("CDI_MAX96717_LBIST_ERR");
    }
    if (((err_byte[0] & 0x40U) == 0U) && ((err_byte[0] & 0x80U) != 0U)) {
        buffer->globalFailureType[buffer->count] = CDI_MAX96717_MBIST_ERR;
        buffer->predevFailureType[buffer->count] = SERIALIZER_ERROR;
        if (buffer->count < MAX_GLOBAL_ERROR_NUM - 1U) { buffer->count++; }
        SIPL_LOG_ERR_STR("CDI_MAX96717_MBIST_ERR");
    }
    if ((err_byte[1] & 0x20U) != 0U || (err_byte[2] & 0x01U) != 0U) {
        buffer->globalFailureType[buffer->count] = CDI_MAX96717_MEMORY_OVERFLOW;
        buffer->predevFailureType[buffer->count] = GMSL_LINK_ERROR;
        if (buffer->count < MAX_GLOBAL_ERROR_NUM - 1U) { buffer->count++; }
        SIPL_LOG_ERR_STR("CDI_MAX96717_MEMORY_OVERFLOW");
    }
    if ((err_byte[1] & 0x80U) == 0U) {
        buffer->globalFailureType[buffer->count] = CDI_MAX96717_PCLK_UNLOCK;
        buffer->predevFailureType[buffer->count] = GMSL_LINK_ERROR;
        if (buffer->count < MAX_GLOBAL_ERROR_NUM - 1U) { buffer->count++; }
        SIPL_LOG_ERR_STR("CDI_MAX96717_PCLK_UNLOCK");
    }
    return status;
}`
