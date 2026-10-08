/**
 * C++ 函数对 → PlantUML 时序图 解析/构建器
 *
 * 输入：两个 C++ 函数源码（A 与 B，B 可选），A 的调用链最终会调用到 B。
 * 输出：PlantUML sequence 图源码，带参与者（lifeline）、同步调用箭头、
 *       返回箭头（虚线）、自调用（self-loop）。
 *
 * 解析策略（纯正则 + 括号匹配，不走 AST）：
 *   1. 从函数签名提取"所在类"（`Class::Method` 的 `Class`）
 *   2. 扫描函数体，提取局部变量声明，建立 `varName → TypeName` 映射，
 *      用来把 `obj->method()` 的 lifeline 显示为类型名而不是裸变量名
 *   3. 线性扫描函数体，找所有顶层 `(` 开始的调用：
 *        obj->method(args)      → obj 的类型名作为 callee lifeline
 *        Class::method(args)    → Class 作为 callee lifeline
 *        method(args)           → 自调用（caller == callee）
 *   4. 若左侧有 `var = ...` 赋值则把 `var` 当返回值 label
 *
 * 已接受的漏识别（规则局限，记入模块注释）：
 *   - 嵌套在参数里的调用（`X(f())` 只识别 X，f 丢掉）—— 顶层调用能覆盖主干
 *   - 虚函数 / 多态真实接收者（纯文本看不到类层次）
 *   - 模板实例化、宏展开后的调用
 *   - 类型声明中的 `auto` 推导（看不到 RHS 的真实类型，lifeline 回退到变量名）
 *
 * 以上场景如果影响判读，用户可以切到「PlantUML 源码」tab 手工微调，或走后端
 * AI 兜底（后续迭代）。
 */

import { stripComments, matchBracket } from './cppFlowchart'

/* ----------------- Types ----------------- */
export interface SeqFuncInfo {
  /** `Class::Method` 的 Class 部分；自由函数时为空 */
  className: string
  /** 方法名（不含 Class 前缀） */
  funcName: string
  /** 完整签名字符串（返回类型 + Class::Method(params)） */
  signature: string
  /** 原始参数字符串（去掉外层括号） */
  params: string
  /** 函数体内容（去掉外层花括号；注释已剥离） */
  body: string
}

export interface CallEvent {
  /** 发起方 lifeline（通常是当前函数所在类） */
  caller: string
  /** 被调用方 lifeline（变量类型 / Class / 自身） */
  callee: string
  /** 显示在箭头上的方法名（不含 Class 前缀） */
  method: string
  /** 原样参数字符串（已折叠空白、截断过长） */
  args: string
  /** 返回值绑定的变量名；无赋值则 undefined */
  retVar?: string
  /** 自调用 flag（没有 `obj->` 或 `Class::` 前缀） */
  isSelf: boolean
  /** 原始调用文本（method + args 组合，调试用） */
  raw: string
}

/* ----------------- Extract function signature + body ----------------- */
export function extractSeqFunction(src: string): SeqFuncInfo | null {
  const s = stripComments(src).trim()
  // 复用 cppFlowchart 里的匹配模式；允许模板、const、ref、ptr
  const m = s.match(
    /([A-Za-z_][\w:<>,\s\*&~]*?)\s+([A-Za-z_][\w]*(?:::[A-Za-z_][\w]*)*)\s*\(([^;{}]*?)\)\s*(?:const)?\s*\{/,
  )
  if (!m || m.index === undefined) return null
  const headerEnd = m.index + m[0].length
  const openBrace = m.index + m[0].lastIndexOf('{')
  const close = matchBracket(s, openBrace)
  if (close < 0) return null

  const fullName = m[2].trim()
  const lastColon = fullName.lastIndexOf('::')
  const className = lastColon >= 0 ? fullName.slice(0, lastColon) : ''
  const funcName = lastColon >= 0 ? fullName.slice(lastColon + 2) : fullName
  const params = m[3].trim()

  return {
    className,
    funcName,
    signature: (m[1].trim() + ' ' + fullName + '(' + params + ')').replace(/\s+/g, ' '),
    params,
    body: s.slice(headerEnd, close),
  }
}

/* ----------------- Local variable type resolution ----------------- */
/**
 * 扫描函数体，建立 `varName → TypeName` 映射。
 *
 * 覆盖以下常见声明形态（都是函数体顶层扫描，不进嵌套作用域）：
 *   Type var;
 *   Type var = ...;
 *   Type *var = ...;
 *   Type &var = ...;
 *   Type var(args);
 *   Type var{args};
 *   const Type *var = ...;
 *   std::shared_ptr<T> var = ...;  → 类型取 `T`，更贴近调用方真实类型
 *   auto var = make_xxx<T>(...);   → 类型取 `T`
 *
 * 返回的类型字符串尽量裁掉 `std::`、`shared_ptr<>`、`unique_ptr<>` 等包装层，
 * 让 lifeline 名称更接近业务类名。
 */
export function extractVarTypes(body: string, params: string = ''): Map<string, string> {
  const types = new Map<string, string>()

  // 1) 函数形参也要进 map：`Foo *handle, const Bar &cfg`
  //    形参按逗号切分（不进括号/尖括号深度），逐个取"最后一个标识符"作为 var，
  //    其前面的部分作为 type 片段
  if (params.trim()) {
    const parts = splitTopLevelCommas(params)
    for (const p of parts) {
      const trimmed = p.trim().replace(/\s*=.*$/, '') // 去默认值
      // 末尾标识符即形参名
      const paramM = trimmed.match(/([A-Za-z_][\w]*)\s*(?:\[\s*\d*\s*\])?\s*$/)
      if (!paramM) continue
      const varName = paramM[1]
      const typeStr = trimmed.slice(0, paramM.index).trim()
      const typeName = extractCoreTypeName(typeStr)
      if (typeName && !types.has(varName)) types.set(varName, typeName)
    }
  }

  // 2) 函数体内局部声明。匹配必须锚定到"语句开头"（上一字符是 ; { } 或 BOF），
  //    否则会误伤 `obj->GetFoo()` 这种链式访问（把 `->GetFoo` 当成"类型 GetFoo
  //    变量 r"而弹进 map）
  //    类型与变量之间要求 `\s+` 或 `*`/`&` 分隔，否则 `LOG_ERR(` 会被切成
  //    "类型 LOG + 变量 _ERR"（regex 回溯会把标识符从中间断开）
  //    `(?<=^|[;{}])\s*` 的 lookbehind 固定长度，所有现代 JS 引擎支持
  const declRe =
    /(?<=^|[;{}])\s*((?:const\s+|volatile\s+|static\s+|mutable\s+)*[A-Z][\w]*(?:::[A-Z][\w]*)*(?:\s*<[^;{}=]*>)?)(?:\s+(?:const\s+)?\**\s*&?\s*|\s*\*+\s*(?:const\s+)?|\s*&\s*)([a-z_][\w]*)\s*(?:=|;|\(|\{|\[)/g
  let m: RegExpExecArray | null
  while ((m = declRe.exec(body)) !== null) {
    const typeName = extractCoreTypeName(m[1])
    const varName = m[2]
    // 关键字过滤：避免 `return foo;` 被当成 `return` 类型声明
    if (['return', 'if', 'for', 'while', 'switch', 'else', 'case'].includes(varName)) continue
    if (!types.has(varName) && typeName) types.set(varName, typeName)
  }

  return types
}

/** 从类型片段里剥一层 `shared_ptr<T>` / `unique_ptr<T>` / `std::` 命名空间 */
function extractCoreTypeName(raw: string): string {
  let t = raw.trim()
  // 剥 const / volatile / static 等修饰
  t = t.replace(/\b(const|volatile|static|mutable|inline|constexpr)\s+/g, '')
  // shared_ptr<T> / unique_ptr<T> / weak_ptr<T> → T
  const smartPtr = t.match(/^(?:std::)?(?:shared_ptr|unique_ptr|weak_ptr)\s*<\s*([A-Za-z_][\w:]*)/)
  if (smartPtr) return smartPtr[1].replace(/^std::/, '')
  // 去 std:: 前缀
  t = t.replace(/^std::/, '')
  // 取第一个标识符（含 ::）
  const idM = t.match(/^([A-Za-z_][\w]*(?:::[A-Za-z_][\w]*)*)/)
  return idM ? idM[1] : ''
}

/** 按顶层逗号切分，忽略括号/尖括号/花括号内部 */
function splitTopLevelCommas(s: string): string[] {
  const out: string[] = []
  let depth = 0, buf = ''
  for (let i = 0; i < s.length; i++) {
    const c = s[i]
    if (c === '(' || c === '[' || c === '{' || c === '<') depth++
    else if (c === ')' || c === ']' || c === '}' || c === '>') depth--
    if (c === ',' && depth === 0) { out.push(buf); buf = ''; continue }
    buf += c
  }
  if (buf.trim()) out.push(buf)
  return out
}

/* ----------------- Call extraction ----------------- */
/** C++ 关键字 / 运算符 / cast 等伪调用（出现 `(` 但不是函数调用）黑名单 */
const NON_CALL_IDENTS = new Set([
  'if', 'for', 'while', 'switch', 'return', 'sizeof', 'typeid', 'alignof', 'decltype',
  'static_cast', 'dynamic_cast', 'const_cast', 'reinterpret_cast',
  'new', 'delete', 'throw', 'catch', 'typeof',
  'and', 'or', 'not', 'xor',  // C++ 关键字替代
])

/**
 * 扫描函数体，顺序提取所有顶层调用。
 *
 * 顶层 = 不在另一个调用的参数列表内部。嵌套调用（`X(f())` 里的 `f`）本版本
 * 不单独展开，否则会和 `X` 的箭头互相穿插，可读性反而变差。
 *
 * @param body 函数体文本（已 stripComments）
 * @param currentClass 当前函数所在类名；用来给自调用和 `obj->` 回填 lifeline
 * @param varTypes `varName → TypeName` 映射（从 extractVarTypes 来）
 */
export function extractCalls(
  body: string,
  currentClass: string,
  varTypes: Map<string, string>,
): CallEvent[] {
  const calls: CallEvent[] = []
  const s = body
  const n = s.length
  let i = 0
  const self = currentClass || 'Self'

  while (i < n) {
    const c = s[i]
    // 字符串：直接跳过
    if (c === '"' || c === "'") {
      const q = c
      i++
      while (i < n && s[i] !== q) { if (s[i] === '\\') i++; i++ }
      i++
      continue
    }
    // 行注释（兜底，stripComments 已处理，但宏里偶尔有残留）
    if (c === '/' && s[i + 1] === '/') { while (i < n && s[i] !== '\n') i++; continue }

    if (c !== '(') { i++; continue }

    const close = matchBracket(s, i)
    if (close < 0) break

    // 从 `(` 往前读方法名（允许 `::` 连接）
    let p = i - 1
    while (p >= 0 && /\s/.test(s[p])) p--
    const nameEnd = p + 1
    while (p >= 0 && /[\w:]/.test(s[p])) p--
    const methodName = s.slice(p + 1, nameEnd)

    // 不像函数调用：空名、纯数字、关键字 → 跳过
    if (
      !methodName ||
      !/^[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*$/.test(methodName) ||
      NON_CALL_IDENTS.has(methodName)
    ) {
      i = close + 1
      continue
    }

    // 看方法名前面是什么决定调用形式
    let q = p
    while (q >= 0 && /\s/.test(s[q])) q--

    let caller = self
    let callee = self
    let method = methodName
    let isSelf = false

    if (q >= 1 && s[q] === '>' && s[q - 1] === '-') {
      // obj->method(args) 或 ptr->foo->bar(args)
      // 取紧挨着的 obj 作为变量名（简化：不处理链式访问）
      let r = q - 2
      while (r >= 0 && /\s/.test(s[r])) r--
      const varEnd = r + 1
      while (r >= 0 && /[\w\]]/.test(s[r])) {
        // 处理 arr[i]->method：遇到 `]` 要跳回配对的 `[`
        if (s[r] === ']') {
          // 找左 `[`
          let depth = 1
          r--
          while (r >= 0 && depth > 0) {
            if (s[r] === ']') depth++
            else if (s[r] === '[') depth--
            r--
          }
        } else {
          r--
        }
      }
      const varName = s.slice(r + 1, varEnd).replace(/\[.*?\]/g, '').trim()
      const resolved = varTypes.get(varName)
      callee = resolved || varName || 'Obj'
      method = methodName
    } else if (q >= 1 && s[q] === ':' && s[q - 1] === ':') {
      // 不太可能走到：methodName 里的 :: 已经被 `[\w:]` 吃进去了
      // 保留兜底
      const lastColon = methodName.lastIndexOf('::')
      callee = methodName.slice(0, lastColon)
      method = methodName.slice(lastColon + 2)
    } else if (methodName.includes('::')) {
      // Class::method(args)
      const lastColon = methodName.lastIndexOf('::')
      callee = methodName.slice(0, lastColon)
      method = methodName.slice(lastColon + 2)
    } else if (q >= 0 && s[q] === '.') {
      // obj.method(args)
      let r = q - 1
      while (r >= 0 && /\s/.test(s[r])) r--
      const varEnd = r + 1
      while (r >= 0 && /[\w]/.test(s[r])) r--
      const varName = s.slice(r + 1, varEnd)
      const resolved = varTypes.get(varName)
      callee = resolved || varName || 'Obj'
      method = methodName
    } else {
      // method(args) —— 自调用
      isSelf = true
      callee = self
      method = methodName
    }

    // 返回值绑定：往前扫到上一条语句分隔符，看前缀是否 `var =`
    let stmtStart = p + 1
    while (stmtStart > 0 && !';{}'.includes(s[stmtStart - 1])) stmtStart--
    const stmtPrefix = s.slice(stmtStart, p + 1).trim()
    let retVar: string | undefined
    // 两种形态：`Type var =`（声明+赋值）/ `var =`（纯赋值）
    const assignM = stmtPrefix.match(/([A-Za-z_][\w]*)\s*=\s*$/)
    if (assignM) retVar = assignM[1]

    const args = foldWhitespace(s.slice(i + 1, close))
    calls.push({
      caller,
      callee,
      method,
      args,
      retVar,
      isSelf,
      raw: methodName + '(' + args + ')',
    })

    i = close + 1
  }

  return calls
}

function foldWhitespace(s: string): string {
  return s.replace(/\s+/g, ' ').trim()
}

/* ----------------- PlantUML sequence emit ----------------- */
/**
 * PlantUML sequence 文本转义：
 *   - 双引号 → 全角，不然 label 会提前闭合
 *   - 冒号 → `：`（全角），不然 `A -> B: foo:bar()` 的第二个冒号会把 bar 当新 label
 *   - 换行折叠
 *   - 过长截断（经验值：plantuml.com 对 message label 超过 ~300 字直接 400）
 */
function seqLabel(s: string): string {
  let out = String(s)
    .replace(/"/g, '＂')
    .replace(/\r?\n/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  const MAX = 180
  if (out.length > MAX) out = out.slice(0, MAX) + ' …⟨截断⟩'
  return out
}

/** 把 lifeline 名字清理成合法 PlantUML alias（只允许字母数字下划线） */
function aliasOf(name: string): string {
  return name.replace(/[^A-Za-z0-9_]/g, '_').replace(/^(\d)/, '_$1') || 'X'
}

export interface SeqBuildOptions {
  /** 外部"调用方"actor 名字（默认「调用方」） */
  callerName?: string
  /** 是否显示 autonumber */
  autonumber?: boolean
  /** 是否把每条调用后的返回箭头都画出来；复杂图可以关掉降噪 */
  showReturns?: boolean
}

export interface SeqBuildResult {
  uml: string
  /** 参与者数量（含外部调用方） */
  participants: number
  /** 调用边数量 */
  calls: number
}

/**
 * 从一个（或两个）函数构建 PlantUML sequence 图。
 *
 * - 只传 A：画 外部 → A.className → A 中各调用点 → 返回
 * - A + B：如果 A 中有一条调用的 method 名正好等于 B.funcName，
 *   则在那条调用之后"展开 B 的内部调用"（嵌套在 B.className lifeline 下），
 *   直观展示 A→...→B 的调用链
 */
export function buildSeqUml(
  funcA: SeqFuncInfo,
  funcB: SeqFuncInfo | null,
  opts: SeqBuildOptions = {},
): SeqBuildResult {
  const { callerName = '调用方', autonumber = true, showReturns = true } = opts

  const aClass = funcA.className || 'FuncA'
  const varsA = extractVarTypes(funcA.body, funcA.params)
  const callsA = extractCalls(funcA.body, aClass, varsA)

  // 若 B 可用，预计算其内部调用，以便命中点上展开
  let bClass = ''
  let callsB: CallEvent[] = []
  if (funcB) {
    bClass = funcB.className || 'FuncB'
    const varsB = extractVarTypes(funcB.body, funcB.params)
    callsB = extractCalls(funcB.body, bClass, varsB)
  }

  // 汇总所有 lifeline，保持首次出现顺序
  const seen = new Set<string>()
  const lifelines: string[] = []
  const addLifeline = (name: string) => {
    if (!name) return
    if (seen.has(name)) return
    seen.add(name)
    lifelines.push(name)
  }
  addLifeline(aClass)
  for (const c of callsA) addLifeline(c.callee)
  if (bClass) addLifeline(bClass)
  for (const c of callsB) addLifeline(c.callee)

  const lines: string[] = []
  lines.push('@startuml')
  lines.push('skinparam defaultFontName "PingFang SC, Microsoft YaHei, Segoe UI"')
  lines.push('skinparam defaultFontSize 12')
  lines.push('skinparam sequenceArrowThickness 1.2')
  lines.push('skinparam sequenceParticipant underline')
  lines.push('skinparam sequence {')
  lines.push('  ParticipantBackgroundColor #F1F5F9')
  lines.push('  ParticipantBorderColor #475569')
  lines.push('  ActorBackgroundColor #E0F2FE')
  lines.push('  ActorBorderColor #0284C7')
  lines.push('  LifeLineBorderColor #94A3B8')
  lines.push('  ArrowColor #334155')
  lines.push('}')
  if (autonumber) lines.push('autonumber')

  // 参与者声明：外部 actor 的 alias 固定用 ASCII `Caller`，不然非 ASCII
  // 名字（"调用方"）在 aliasOf 里会被清成 `___`
  const callerAlias = 'Caller'
  lines.push(`actor "${seqLabel(callerName)}" as ${callerAlias}`)
  for (const name of lifelines) {
    lines.push(`participant "${seqLabel(name)}" as ${aliasOf(name)}`)
  }

  // 外部 → A：第一条箭头的 label 只保留形参名，不带类型，更贴近 sequence 图
  // 的"消息传参"语义（UML 消息边不是函数签名）
  const aAlias = aliasOf(aClass)
  const aArgNames = splitTopLevelCommas(funcA.params)
    .map(p => {
      const t = p.trim().replace(/\s*=.*$/, '')
      const nm = t.match(/([A-Za-z_][\w]*)\s*(?:\[\s*\d*\s*\])?\s*$/)
      return nm ? nm[1] : t
    })
    .filter(Boolean)
    .join(', ')
  const aMsg = `${funcA.funcName}(${seqLabel(aArgNames)})`
  lines.push(`${callerAlias} -> ${aAlias}: ${aMsg}`)
  lines.push(`activate ${aAlias}`)

  let callEdges = 0

  for (const c of callsA) {
    const dstAlias = aliasOf(c.callee)
    const msg = `${c.method}(${seqLabel(c.args)})`
    if (c.isSelf) {
      // self-loop
      lines.push(`${aAlias} -> ${aAlias}: ${msg}`)
    } else {
      lines.push(`${aAlias} -> ${dstAlias}: ${msg}`)
      lines.push(`activate ${dstAlias}`)
    }
    callEdges++

    // 若该调用正好是 B（通过方法名匹配），展开 B 的内部调用。
    // 自调用也要展开：A 自调用 B 是最常见情形（同一个类里的两个方法）
    if (funcB && c.method === funcB.funcName) {
      const bAlias = aliasOf(bClass)
      // B 的 lifeline：若 A 中调用是 self-call，B 当作 A 的类（dstAlias===aAlias）；
      // 若 A 通过对象/类名调用 B，用 dstAlias；再若 user 给的 B 类名和实际
      // callee lifeline 不一致（例如虚函数、typedef），加 note 兜底
      const expandOn = c.isSelf ? aAlias : dstAlias
      if (!c.isSelf && expandOn !== bAlias) {
        lines.push(`note over ${expandOn}, ${bAlias}: 以下展开自 ${bClass}::${funcB.funcName}`)
      }
      for (const cb of callsB) {
        const innerAlias = aliasOf(cb.callee)
        const innerMsg = `${cb.method}(${seqLabel(cb.args)})`
        if (cb.isSelf) {
          lines.push(`${expandOn} -> ${expandOn}: ${innerMsg}`)
        } else {
          lines.push(`${expandOn} -> ${innerAlias}: ${innerMsg}`)
          if (showReturns) {
            const retLabel = cb.retVar ? seqLabel(cb.retVar) : 'return'
            lines.push(`${innerAlias} --> ${expandOn}: ${retLabel}`)
          }
        }
        callEdges++
      }
    }

    if (showReturns && !c.isSelf) {
      const retLabel = c.retVar ? seqLabel(c.retVar) : 'return'
      lines.push(`${dstAlias} --> ${aAlias}: ${retLabel}`)
      lines.push(`deactivate ${dstAlias}`)
    }
  }

  // A → 外部返回
  lines.push(`${aAlias} --> ${callerAlias}: return`)
  lines.push(`deactivate ${aAlias}`)
  lines.push('@enduml')

  return {
    uml: lines.join('\n'),
    participants: lifelines.length + 1,
    calls: callEdges,
  }
}

/* ----------------- Example input（载入示例按钮用） ----------------- */
export const SEQ_EXAMPLE_A = `SIPLStatus CSiplCamera::InitCustomInterfaces(uint32_t uSensorId) {
    SIPLStatus status = NVSIPL_STATUS_OK;
    IInterfaceProvider *provider = GetModuleInterfaceProvider(uSensorId);
    if (provider == nullptr) {
        LOG_ERR("GetModuleInterfaceProvider failed");
        return NVSIPL_STATUS_ERROR;
    }
    Interface *customInterface = provider->GetInterface(IMX_CUSTOM_UUID);
    if (customInterface == nullptr) {
        return NVSIPL_STATUS_NOT_SUPPORTED;
    }
    status = GetIMX728_CustomInterface(uSensorId, customInterface);
    return status;
}`

export const SEQ_EXAMPLE_B = `SIPLStatus CSiplCamera::GetIMX728_CustomInterface(uint32_t uSensorId, Interface *customInterface) {
    CNvMMAX96712_96717F_IMX728 *driver = GetDriver(uSensorId);
    SIPLStatus status = driver->ShowReadOutTime();
    status = driver->ShowActionLine();
    return status;
}`
