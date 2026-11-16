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

// 日志/打印宏白名单：来源 drive-linux/samples/nvmedia/nvsipl/devblk/common/utils/sipl_error.h
// + C 标准 printf。严格全词匹配 —— `MyLogWrapper` / `printf_safe` / `std::printf` 不会误伤。
// 命中这些的语句会被丢弃，不画进流程图（日志是副作用、不是业务逻辑）。
const _LOG_MACROS: readonly string[] = [
  'LOG_DBG', 'LOG_DEBUG', 'LOG_INFO', 'LOG_MSG',
  'SIPL_LOG_2STR', 'SIPL_LOG_2STR_INT', 'SIPL_LOG_3STR', 'SIPL_LOG_3STR_UINT',
  'SIPL_LOG_ERR_2STR', 'SIPL_LOG_ERR_2STR_INT', 'SIPL_LOG_ERR_3STR',
  'SIPL_LOG_ERR_STR', 'SIPL_LOG_ERR_STR_2DOUBLE', 'SIPL_LOG_ERR_STR_2FLOAT',
  'SIPL_LOG_ERR_STR_2HEX', 'SIPL_LOG_ERR_STR_2INT', 'SIPL_LOG_ERR_STR_2SLONG',
  'SIPL_LOG_ERR_STR_2UINT', 'SIPL_LOG_ERR_STR_2ULONG',
  'SIPL_LOG_ERR_STR_DOUBLE', 'SIPL_LOG_ERR_STR_FLOAT',
  'SIPL_LOG_ERR_STR_HEX_2ULONG', 'SIPL_LOG_ERR_STR_HEX_3ULONG',
  'SIPL_LOG_ERR_STR_HEX_AND_UINT', 'SIPL_LOG_ERR_STR_HEX_UINT',
  'SIPL_LOG_ERR_STR_INT', 'SIPL_LOG_ERR_STR_SLONG', 'SIPL_LOG_ERR_STR_UINT',
  'SIPL_LOG_ERR_STR_UINT_AND_HEX', 'SIPL_LOG_ERR_STR_ULONG',
  'SIPL_LOG_INFO_2STR', 'SIPL_LOG_INFO_2STR_UINT', 'SIPL_LOG_INFO_3STR_UINT',
  'SIPL_LOG_INFO_STR', 'SIPL_LOG_INFO_STR_2HEX', 'SIPL_LOG_INFO_STR_2UINT',
  'SIPL_LOG_INFO_STR_3UINT', 'SIPL_LOG_INFO_STR_FLOAT',
  'SIPL_LOG_INFO_STR_HEX_UINT', 'SIPL_LOG_INFO_STR_INT',
  'SIPL_LOG_INFO_STR_UINT', 'SIPL_LOG_INFO_STR_ULONG',
  'SIPL_LOG_LINE', 'SIPL_LOG_STR',
  'SIPL_LOG_STR_2DOUBLE', 'SIPL_LOG_STR_2FLOAT', 'SIPL_LOG_STR_2HEX',
  'SIPL_LOG_STR_2INT', 'SIPL_LOG_STR_2SLONG', 'SIPL_LOG_STR_2UINT',
  'SIPL_LOG_STR_2ULONG', 'SIPL_LOG_STR_3UINT',
  'SIPL_LOG_STR_DOUBLE', 'SIPL_LOG_STR_FLOAT',
  'SIPL_LOG_STR_HEX_2ULONG', 'SIPL_LOG_STR_HEX_3ULONG',
  'SIPL_LOG_STR_HEX_AND_UINT', 'SIPL_LOG_STR_HEX_UINT',
  'SIPL_LOG_STR_INT', 'SIPL_LOG_STR_SLONG', 'SIPL_LOG_STR_UINT',
  'SIPL_LOG_STR_UINT_AND_HEX', 'SIPL_LOG_STR_UINT_FLOAT', 'SIPL_LOG_STR_ULONG',
  'SIPL_LOG_WARN_2STR', 'SIPL_LOG_WARN_STR', 'SIPL_LOG_WARN_STR_UINT',
  'printf',
]
// 行首必须紧跟 `(`：`printf(...)` 命中、`std::printf(...)` 不命中（因为前面有 `::`）
const LOG_MACRO_RE = new RegExp(
  '^\\s*(?:' + [..._LOG_MACROS].sort((a, b) => b.length - a.length).join('|') + ')\\s*\\(',
)

function classify(t: string): FlowNode | null {
  t = t.trim().replace(/;$/, '')
  if (!t) return null
  if (/^return\b/.test(t)) return { type: 'return', text: t }
  if (LOG_MACRO_RE.test(t)) return { type: 'log', text: t }
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

/**
 * 从位置 k 起消化 `else [if (cond) { ... }]  [else ...]?` —— 把整条
 * `else if … else if … else` 链吃到当前 if 的 else 分支里，形成嵌套
 * `{type:'if', then, else: [{type:'if', then, else: [...]} ] }` 结构。
 *
 * 如果不递归，`else if (B)` 被当独立 if 处理 → 外层 if (A) 为真时流程
 * 会继续走 if (B) 判断，违反 C/C++ `if/else if` 互斥语义（issue: 代码
 * 分析页流程图里 if 条件满足后仍走 else if）。
 */
function readElseChain(src: string, k: number): { nodes: FlowNode[]; end: number } {
  if (!src.slice(k).match(/^else\b/)) return { nodes: [], end: k }
  k = skipWs(src, k + 4)
  // `else if (cond) { ... }` —— 读完后继续递归拉链
  if (src.slice(k).match(/^if\b/)) {
    const ec = src.indexOf('(', k)
    const ecR = readCond(src, ec)
    const ebStart = skipWs(src, ecR.end)
    const eb = readSubBlock(src, ebStart)
    const next = readElseChain(src, skipWs(src, eb.end))
    return {
      nodes: [{ type: 'if', cond: ecR.cond, then: eb.nodes, else: next.nodes }],
      end: next.end,
    }
  }
  // 普通 `else { ... }` —— 链到此结束
  const eb = readSubBlock(src, k)
  return { nodes: eb.nodes, end: eb.end }
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
        const k = skipWs(src, thenBlock.end)
        // 整条 else-if-else 链一次性消化，保持嵌套结构，避免后续 else if
        // 被 kwMatch 误当作独立顶层 if
        const chain = readElseChain(src, k)
        out.push({ type: 'if', cond: (kw === 'else if' ? 'else if ' : '') + condRes.cond, then: thenBlock.nodes, else: chain.nodes })
        i = chain.end
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
// 复用 classify 用的严格白名单正则，不要再在这里维护第二份规则
const LOG_RE = LOG_MACRO_RE
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

function stmtNode(text: string): string | null {
  // 日志整条丢弃（返回 null 让上层跳过）—— 跟后端 _emit 的行为保持一致
  if (LOG_RE.test(text)) return null
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
      // 日志节点整条丢弃，不画进 Mermaid 流程图（跟 PlantUML / 后端口径一致）
      continue
    } else if (node.type === 'decl') {
      const id = addNode('decl', label(node.text.replace(/;$/, '')))
      plan.push({ node, kind: 'decl', entryId: id })
    } else {
      const id = stmtNode((node as { text: string }).text)
      if (id === null) continue   // stmtNode 命中 LOG_RE 兜底时也跳过
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
 * `< > %` 也是坑（creole 标签 `<color:red>`、`<b>`、`%newline()` 等）：
 * C++ 里 `static_cast<T>`、`a >> 2`、`printf("%lld")` 直接 400。同样全角替换。
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
    .replace(/</g, '＜')  // U+FF1C 防 creole 标签 `<color>` / 模板实参 `<T>`
    .replace(/>/g, '＞')  // U+FF1E 配套；`>>` 顺带被转成 `＞＞`
    .replace(/%/g, '％')  // U+FF05 防 creole 转义 `%newline()` 等
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
      // 日志节点整条丢弃 —— 与后端 _emit 口径一致，日志是副作用、不画流程图
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
      const cond = plantLabel(n.cond.replace(/^else if\s+/, ''))
      const thenNodes = n.then || []
      const elseNodes = n.else || []
      // detach 分支改写：如果 then 整支以 return 结尾，画 then 时用 `detach` 让错误
      // 分支从主流程脱出，而不是流回 endif 汇合点；主流程的 endif 下面直接继续画下
      // 一条语句，无视觉汇合。效果：错误早返回占纵向空间 -14%，布局一眼就看出"正常
      // 主干 vs 异常分支"的意图。只有 then 命中时用 detach；else 命中时保持原样让
      // PlantUML 自己收口（已有的 stop 够用）。
      const thenJumpsOut = thenNodes.length > 0 && thenNodes[thenNodes.length - 1].type === 'return'
      out.push(`${indent}if (${cond}) then (yes)`)
      if (thenJumpsOut) {
        // 画 then 的前 N-1 条
        for (let i = 0; i < thenNodes.length - 1; i++) {
          plantEmit([thenNodes[i]], out, indent + '  ', colored)
        }
        // 最后一条 return 手写成 label + detach，而不是 label + stop
        const last = thenNodes[thenNodes.length - 1] as Extract<FlowNode, { type: 'return' }>
        out.push(colored
          ? `${indent}  :${plantLabel(last.text)}; <<#FFE4E6>>`
          : `${indent}  :${plantLabel(last.text)};`)
        out.push(`${indent}  detach`)
      } else {
        plantEmit(thenNodes, out, indent + '  ', colored)
      }
      if (elseNodes.length > 0) {
        out.push(`${indent}else (no)`)
        plantEmit(elseNodes, out, indent + '  ', colored)
      } else {
        // 空 else 也要 push `else (no)` —— 这行是给 no 分支的箭头打文字标签用；
        // 配合 skinparam ConditionEndStyle hline，空 else 收口在水平线不画菱形。
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
  // 分支汇合点改画水平线而不是菱形；PlantUML activity beta 默认 `endif` 后画一个
  // merge diamond（空菱形），空 else 分支时视觉上就是一个"无内容的菱形"（用户反馈
  // "分支走完后一个菱形空图形"）。hline 让汇合点变成一条水平线，分支语义不变。
  lines.push('skinparam ConditionEndStyle hline')
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
  // 直接 stop 结束 —— PlantUML 自身会画终止圆圈。再加 `:结束;` 节点会
  // 多出一个方框（用户反馈"最后总有一个单独的结束框图"的来源）。
  // 若最后一个顶层节点是 return，plantEmit 已经吐了 stop，不再追加
  // （避免 stop\nstop 画两个重叠终止圆圈）。
  const lastIsReturn = body.length > 0 && body[body.length - 1].type === 'return'
  if (!lastIsReturn) {
    lines.push('stop')
  }
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

/**
 * 读用户在前端 UI 里选的渲染后端（本地内网 server vs 线上 plantuml.com）。
 * 用 localStorage 持久化 —— 用户切一次就全站生效（4 个流程图/时序/类图页面共用）。
 *
 * 值：`"local"` / `"cloud"` / 其他（含 null）= 跟后端 env 默认走。
 */
function getBackendChoice(): 'local' | 'cloud' | null {
  try {
    const v = localStorage.getItem('plantuml_backend')
    if (v === 'local' || v === 'cloud') return v
  } catch {
    // 无痕/localStorage 被禁 —— 忽略，走后端默认
  }
  return null
}

/** 把 backend 选择拼到后端代理 URL 上。空选择 → 不加 query，后端用 env 默认。 */
function proxyUrl(format: 'svg' | 'png', encoded: string): string {
  const back = getBackendChoice()
  const suffix = back ? `&backend=${back}` : ''
  return `/api/plantuml/render?fmt=${format}&encoded=${encodeURIComponent(encoded)}${suffix}`
}

export function plantUmlToUrl(uml: string, format: 'svg' | 'png' = 'svg'): string {
  const bytes = new TextEncoder().encode(uml)
  // level 9 = 最高压缩率；PlantUML 期望的是"裸 deflate"（raw，无 zlib 头），
  // 所以用 deflateRaw 而不是 deflate。
  const compressed = deflateRaw(bytes, { level: 9 })
  const encoded = encodePlantUmlBase64(compressed)
  if (useDirect()) return `https://www.plantuml.com/plantuml/${format}/${encoded}`
  // 后端代理端点：GET /api/plantuml/render?fmt=svg&encoded=<...>[&backend=local|cloud]
  return proxyUrl(format, encoded)
}

/**
 * hex 编码兜底方案（保留 export 名以兼容旧调用）。URL 较长，
 * 但不依赖 deflate、无中间过程，服务端一定能解。当 deflate 版拉不动时用。
 *
 * 同样走后端代理；hex 格式在 URL 里加 `~h` 前缀，后端透传给上游。
 */
export function plantUmlToHexUrl(uml: string, format: 'svg' | 'png' = 'svg'): string {
  const bytes = new TextEncoder().encode(uml)
  let hex = ''
  for (const b of bytes) hex += b.toString(16).padStart(2, '0')
  if (useDirect()) return `https://www.plantuml.com/plantuml/${format}/~h${hex}`
  return proxyUrl(format, '~h' + hex)
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
