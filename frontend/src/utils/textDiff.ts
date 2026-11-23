/**
 * 轻量行级 diff 工具，用于 AI 重写测试步骤后的前后对比。
 *
 * 输出两种 GitHub 风格的视图数据：
 * - 并排（split）：左侧原文删除行、右侧改写后新增行，带行号；
 * - 统一（unified）：`@@` 分块 + `-` / `+` 行，带新旧行号。
 *
 * 步骤文本通常只有几十行，使用 LCS 动态规划即可，不引入额外依赖。
 */

export type DiffOpType = 'equal' | 'delete' | 'insert'

export interface DiffOp {
  type: DiffOpType
  text: string
}

export interface SplitDiffCell {
  type: 'equal' | 'delete' | 'insert' | 'empty'
  lineNumber: number | null
  text: string
}

export interface SplitDiffRow {
  left: SplitDiffCell
  right: SplitDiffCell
}

export interface UnifiedDiffLine {
  type: 'equal' | 'delete' | 'insert' | 'hunk'
  text: string
  oldLine: number | null
  newLine: number | null
}

export interface DiffStats {
  additions: number
  deletions: number
}

const EMPTY_CELL: SplitDiffCell = { type: 'empty', lineNumber: null, text: '' }

/** 按行切分；统一换行符并去掉末尾换行产生的空行 */
export function splitLines(text: string): string[] {
  if (!text) return []
  const normalized = text.replace(/\r\n?/g, '\n')
  const lines = normalized.split('\n')
  if (lines.length > 0 && lines[lines.length - 1] === '') lines.pop()
  return lines
}

/** LCS 行级 diff；超长文本退化为“全部删除 + 全部新增”避免内存膨胀 */
export function computeLineOps(oldText: string, newText: string): DiffOp[] {
  const a = splitLines(oldText)
  const b = splitLines(newText)
  const n = a.length
  const m = b.length

  if (n === 0) return b.map((text) => ({ type: 'insert' as const, text }))
  if (m === 0) return a.map((text) => ({ type: 'delete' as const, text }))

  // 4M 格子以内使用 LCS，步骤文本远小于该规模
  if (n * m > 4_000_000) {
    return [
      ...a.map((text) => ({ type: 'delete' as const, text })),
      ...b.map((text) => ({ type: 'insert' as const, text })),
    ]
  }

  const dp: Int32Array[] = new Array(n + 1)
  for (let i = 0; i <= n; i += 1) dp[i] = new Int32Array(m + 1)
  for (let i = n - 1; i >= 0; i -= 1) {
    const row = dp[i]
    const next = dp[i + 1]
    for (let j = m - 1; j >= 0; j -= 1) {
      row[j] = a[i] === b[j] ? next[j + 1] + 1 : Math.max(next[j], row[j + 1])
    }
  }

  const ops: DiffOp[] = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      ops.push({ type: 'equal', text: a[i] })
      i += 1
      j += 1
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      ops.push({ type: 'delete', text: a[i] })
      i += 1
    } else {
      ops.push({ type: 'insert', text: b[j] })
      j += 1
    }
  }
  while (i < n) {
    ops.push({ type: 'delete', text: a[i] })
    i += 1
  }
  while (j < m) {
    ops.push({ type: 'insert', text: b[j] })
    j += 1
  }
  return ops
}

export function computeDiffStats(ops: DiffOp[]): DiffStats {
  let additions = 0
  let deletions = 0
  for (const op of ops) {
    if (op.type === 'insert') additions += 1
    else if (op.type === 'delete') deletions += 1
  }
  return { additions, deletions }
}

/** 构造并排视图：连续的新增/删除块按行对齐，方便逐行比对 */
export function buildSplitRows(oldText: string, newText: string): SplitDiffRow[] {
  const ops = computeLineOps(oldText, newText)
  const rows: SplitDiffRow[] = []
  let oldLine = 1
  let newLine = 1
  let index = 0

  while (index < ops.length) {
    const op = ops[index]
    if (op.type === 'equal') {
      rows.push({
        left: { type: 'equal', lineNumber: oldLine, text: op.text },
        right: { type: 'equal', lineNumber: newLine, text: op.text },
      })
      oldLine += 1
      newLine += 1
      index += 1
      continue
    }

    // 收集连续的变更块
    const deletes: DiffOp[] = []
    const inserts: DiffOp[] = []
    while (index < ops.length && ops[index].type !== 'equal') {
      const changed = ops[index]
      if (changed.type === 'delete') deletes.push(changed)
      else inserts.push(changed)
      index += 1
    }

    const count = Math.max(deletes.length, inserts.length)
    for (let k = 0; k < count; k += 1) {
      const del = deletes[k]
      const ins = inserts[k]
      rows.push({
        left: del
          ? { type: 'delete', lineNumber: oldLine + k, text: del.text }
          : EMPTY_CELL,
        right: ins
          ? { type: 'insert', lineNumber: newLine + k, text: ins.text }
          : EMPTY_CELL,
      })
    }
    oldLine += deletes.length
    newLine += inserts.length
  }

  return rows
}

/** 构造 GitHub 统一视图（带 @@ 分块与 3 行上下文） */
export function buildUnifiedRows(
  oldText: string,
  newText: string,
  context = 3,
): UnifiedDiffLine[] {
  const ops = computeLineOps(oldText, newText)

  // 预计算每行的旧/新行号
  const annotated: UnifiedDiffLine[] = []
  let oldLine = 1
  let newLine = 1
  for (const op of ops) {
    if (op.type === 'equal') {
      annotated.push({ type: 'equal', text: op.text, oldLine, newLine })
      oldLine += 1
      newLine += 1
    } else if (op.type === 'delete') {
      annotated.push({ type: 'delete', text: op.text, oldLine, newLine: null })
      oldLine += 1
    } else {
      annotated.push({ type: 'insert', text: op.text, oldLine: null, newLine })
      newLine += 1
    }
  }

  const changedIndexes = annotated
    .map((line, index) => (line.type === 'equal' ? -1 : index))
    .filter((index) => index >= 0)
  if (changedIndexes.length === 0) return []

  // 合并上下文范围相互重叠的分块
  const ranges: Array<{ start: number; end: number }> = []
  for (const index of changedIndexes) {
    const start = Math.max(0, index - context)
    const end = Math.min(annotated.length, index + context + 1)
    const last = ranges[ranges.length - 1]
    if (last && start <= last.end) last.end = Math.max(last.end, end)
    else ranges.push({ start, end })
  }

  const result: UnifiedDiffLine[] = []
  for (const range of ranges) {
    const slice = annotated.slice(range.start, range.end)
    const oldStart = slice.find((line) => line.oldLine !== null)?.oldLine ?? 0
    const newStart = slice.find((line) => line.newLine !== null)?.newLine ?? 0
    const oldCount = slice.filter((line) => line.type !== 'insert').length
    const newCount = slice.filter((line) => line.type !== 'delete').length
    result.push({
      type: 'hunk',
      text: `@@ -${oldStart},${oldCount} +${newStart},${newCount} @@`,
      oldLine: null,
      newLine: null,
    })
    result.push(...slice)
  }
  return result
}
