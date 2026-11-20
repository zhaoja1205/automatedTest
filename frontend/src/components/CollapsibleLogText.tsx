import { Fragment, useState } from 'react'

const KEY_OUTPUT_MARKER = '命令关键输出:'
// 历史执行日志里每条日志的起始时间戳，用于在没有汇总行时判断关键输出块结束
const LOG_LINE_PREFIX_RE = /^\[\d{4}[-/]\d{1,2}[-/]\d{1,2]\s+\d{1,2}:\d{2}:\d{2}\]/
const KEY_OUTPUT_SUMMARY_RE =
  /^\s*\.\.\.\s*\(total\s+\d+\s+lines,\s*showing\s+\d+\s+key\s+lines\)/i

interface KeyOutputSplit {
  header: string
  body: string
}

/** 把「命令关键输出:」日志拆成标题与明细；非关键输出返回 null。 */
export function splitKeyOutput(message: string): KeyOutputSplit | null {
  const markerIndex = message.indexOf(KEY_OUTPUT_MARKER)
  if (markerIndex < 0) return null
  const header = message.slice(0, markerIndex + KEY_OUTPUT_MARKER.length).trimEnd()
  const body = message
    .slice(markerIndex + KEY_OUTPUT_MARKER.length)
    .replace(/^\r?\n/, '')
    .trimEnd()
  if (!body.trim()) return null
  return { header, body }
}

/** 单条日志文本：命令关键输出默认折叠，可点击展开 / 收起。 */
export function CollapsibleLogText({ message }: { message: string }) {
  const [expanded, setExpanded] = useState(false)
  const split = splitKeyOutput(message)
  if (!split) return <>{message}</>

  const lineCount = split.body.split(/\r?\n/).filter((line) => line.trim()).length
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', flexWrap: 'wrap', gap: 6 }}>
        <span style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{split.header}</span>
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
          style={{
            border: 'none',
            background: 'none',
            padding: 0,
            font: 'inherit',
            color: 'inherit',
            opacity: 0.8,
            cursor: 'pointer',
            textDecoration: 'underline',
          }}
        >
          {expanded ? '收起' : `展开（${lineCount} 行）`}
        </button>
      </div>
      {expanded && (
        <pre
          style={{
            margin: '4px 0 0',
            fontFamily: 'inherit',
            fontSize: 'inherit',
            lineHeight: 'inherit',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            opacity: 0.92,
          }}
        >
          {split.body}
        </pre>
      )}
    </div>
  )
}

type LogSegment =
  | { type: 'text'; text: string }
  | { type: 'block'; text: string }

/** 把整段执行日志按「命令关键输出:」拆成可折叠块。 */
export function splitKeyOutputBlocks(content: string): LogSegment[] {
  const lines = content.split(/\r?\n/)
  const segments: LogSegment[] = []
  let buffer: string[] = []
  const flush = () => {
    if (buffer.length > 0) {
      segments.push({ type: 'text', text: buffer.join('\n') })
      buffer = []
    }
  }

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]
    if (!line.includes(KEY_OUTPUT_MARKER)) {
      buffer.push(line)
      continue
    }

    flush()
    const blockLines = [line]
    let endIndex = index
    for (let nextIndex = index + 1; nextIndex < lines.length; nextIndex += 1) {
      const next = lines[nextIndex]
      if (KEY_OUTPUT_SUMMARY_RE.test(next)) {
        blockLines.push(next)
        endIndex = nextIndex
        break
      }
      // 没有汇总行的旧日志：遇到下一条带时间戳的日志即结束
      if (LOG_LINE_PREFIX_RE.test(next)) {
        endIndex = nextIndex - 1
        break
      }
      blockLines.push(next)
      endIndex = nextIndex
    }
    segments.push({ type: 'block', text: blockLines.join('\n') })
    index = endIndex
  }

  flush()
  return segments
}

/** 历史日志内容：关键输出块同样可折叠，其余文本原样展示。 */
export function CollapsibleRawLog({ content }: { content: string }) {
  const segments = splitKeyOutputBlocks(content)
  return (
    <>
      {segments.map((segment, index) =>
        segment.type === 'block' ? (
          <CollapsibleLogText key={index} message={segment.text} />
        ) : (
          <Fragment key={index}>{segment.text}</Fragment>
        ),
      )}
    </>
  )
}
