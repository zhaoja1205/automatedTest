/**
 * AI 重写测试步骤的差异确认弹窗。
 *
 * 左/右展示原始步骤与 AI 改写后的步骤（GitHub 风格 split diff），
 * 也可切换为统一视图。用户确认后才替换用例的测试步骤。
 */
import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { Alert, Modal, Radio, Space, Tag, Typography } from 'antd'
import { SwapOutlined } from '@ant-design/icons'
import type { AIRewriteStepsResponse } from '../types'
import {
  buildSplitRows,
  buildUnifiedRows,
  computeDiffStats,
  computeLineOps,
} from '../utils/textDiff'

const { Text } = Typography

interface Props {
  open: boolean
  caseId?: string
  data: AIRewriteStepsResponse | null
  /** 替换请求提交中 */
  loading?: boolean
  onCancel: () => void
  onApply: () => void
}

type ViewMode = 'split' | 'unified'

const GUTTER_WIDTH = 48

const splitCellStyle = (
  type: 'equal' | 'delete' | 'insert' | 'empty',
  side: 'left' | 'right',
): CSSProperties => {
  const bg =
    type === 'delete' ? '#ffebe9'
      : type === 'insert' ? '#e6ffec'
        : type === 'empty' ? '#f6f8fa'
          : '#ffffff'
  return {
    background: bg,
    padding: '2px 8px',
    borderLeft: side === 'right' ? '1px solid #d0d7de' : undefined,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-all',
    fontSize: 12.5,
    lineHeight: 1.65,
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
  }
}

const splitGutterStyle = (
  type: 'equal' | 'delete' | 'insert' | 'empty',
  side: 'left' | 'right',
): CSSProperties => {
  const bg =
    type === 'delete' ? '#ffd7d5'
      : type === 'insert' ? '#ccffd8'
        : type === 'empty' ? '#f6f8fa'
          : '#f6f8fa'
  return {
    background: bg,
    color: '#6e7781',
    textAlign: 'right',
    padding: '2px 6px',
    fontSize: 11,
    lineHeight: 1.65,
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
    userSelect: 'none',
    borderLeft: side === 'right' ? '1px solid #d0d7de' : undefined,
  }
}

function renderLineText(text: string) {
  return text.length > 0 ? text : ' '
}

export default function TestStepsRewriteDiffModal({
  open,
  caseId,
  data,
  loading = false,
  onCancel,
  onApply,
}: Props) {
  const [viewMode, setViewMode] = useState<ViewMode>('split')

  useEffect(() => {
    if (open) setViewMode('split')
  }, [open])

  const ops = useMemo(
    () => (data ? computeLineOps(data.original_steps, data.rewritten_steps) : []),
    [data],
  )
  const stats = useMemo(() => computeDiffStats(ops), [ops])
  const splitRows = useMemo(
    () => (data ? buildSplitRows(data.original_steps, data.rewritten_steps) : []),
    [data],
  )
  const unifiedRows = useMemo(
    () => (data ? buildUnifiedRows(data.original_steps, data.rewritten_steps) : []),
    [data],
  )

  const unaffected = data ? stats.additions === 0 && stats.deletions === 0 : true
  const truncated = !!data?.input_truncated
  const canApply = !unaffected && !truncated
  const unrecognized = data?.validation?.unrecognized_steps || []

  const header = (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: `${GUTTER_WIDTH}px minmax(0, 1fr) ${GUTTER_WIDTH}px minmax(0, 1fr)`,
        position: 'sticky',
        top: 0,
        zIndex: 2,
        borderBottom: '1px solid #d0d7de',
        background: '#f6f8fa',
        fontWeight: 600,
        fontSize: 12,
        color: '#57606a',
      }}
    >
      <div />
      <div style={{ padding: '4px 8px' }}>原始测试步骤</div>
      <div style={{ borderLeft: '1px solid #d0d7de' }} />
      <div style={{ padding: '4px 8px' }}>AI 重写后（程序可识别写法）</div>
    </div>
  )

  return (
    <Modal
      open={open}
      width={1180}
      title={`AI 重写测试步骤${caseId ? ` - ${caseId}` : ''}`}
      okText="替换测试步骤"
      cancelText="保留原步骤"
      okButtonProps={{ disabled: !canApply, icon: <SwapOutlined /> }}
      confirmLoading={loading}
      onOk={onApply}
      onCancel={onCancel}
      destroyOnClose
      styles={{ body: { paddingTop: 12 } }}
    >
      {data && (
        <Space direction="vertical" size={10} style={{ display: 'flex' }}>
          {truncated && (
            <Alert
              type="error"
              showIcon
              message="原文过长，已禁止直接替换"
              description="AI 只读取了原文的前 8000 个字符，直接替换可能丢失后续步骤。请拆分用例或手动调整后再替换。"
            />
          )}

          {data.summary && (
            <Alert
              type="info"
              showIcon
              message="AI 改写说明"
              description={data.summary}
            />
          )}

          {unaffected ? (
            <Alert
              type="success"
              showIcon
              message="AI 判断原文已经符合规范，没有产生修改"
              description="可以保留当前测试步骤，无需替换。"
            />
          ) : (
            <Space size={8} wrap>
              <Tag color="green">+{stats.additions} 行新增</Tag>
              <Tag color="red">-{stats.deletions} 行删除</Tag>
              {data.original_validation && data.validation && (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  规则识别：原文 {data.original_validation.executable_steps} 条可执行
                  {' → '}
                  重写后 {data.validation.executable_steps} 条可执行
                </Text>
              )}
            </Space>
          )}

          {unrecognized.length > 0 && (
            <Alert
              type="warning"
              showIcon
              message={`重写后仍有 ${unrecognized.length} 条步骤无法被规则识别`}
              description={
                <div style={{ fontSize: 12 }}>
                  {unrecognized.slice(0, 3).map((item, index) => (
                    <div key={index} style={{ marginTop: 2 }}>• {item}</div>
                  ))}
                  {unrecognized.length > 3 && <div style={{ marginTop: 2 }}>……</div>}
                  <div style={{ marginTop: 4 }}>可取消替换后手动调整，或改用「执行命令：」显式写法。</div>
                </div>
              }
            />
          )}

          {(data.changes?.length ?? 0) > 0 && (
            <div style={{ fontSize: 12, color: '#57606a', lineHeight: 1.8 }}>
              <Text strong style={{ fontSize: 12 }}>主要改写点：</Text>
              {data.changes.map((item, index) => (
                <span key={index}>
                  {index > 0 ? '；' : ' '}
                  {item}
                </span>
              ))}
            </div>
          )}

          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 12,
              padding: '4px 2px',
            }}
          >
            <Radio.Group
              size="small"
              value={viewMode}
              onChange={(event) => setViewMode(event.target.value as ViewMode)}
              options={[
                { label: '并排对比', value: 'split' },
                { label: '统一视图', value: 'unified' },
              ]}
              optionType="button"
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              删除行显示为红色，新增行显示为绿色，确认无误后点击「替换测试步骤」
            </Text>
          </div>

          <div
            style={{
              border: '1px solid #d0d7de',
              borderRadius: 6,
              overflow: 'auto',
              maxHeight: '52vh',
              background: '#ffffff',
            }}
          >
            {viewMode === 'split' ? (
              <div>
                {header}
                {splitRows.map((row, index) => (
                  <div
                    key={index}
                    style={{
                      display: 'grid',
                      gridTemplateColumns: `${GUTTER_WIDTH}px minmax(0, 1fr) ${GUTTER_WIDTH}px minmax(0, 1fr)`,
                    }}
                  >
                    <div style={splitGutterStyle(row.left.type, 'left')}>
                      {row.left.lineNumber ?? ''}
                    </div>
                    <div style={splitCellStyle(row.left.type, 'left')}>
                      {row.left.type === 'empty' ? '' : renderLineText(row.left.text)}
                    </div>
                    <div style={splitGutterStyle(row.right.type, 'right')}>
                      {row.right.lineNumber ?? ''}
                    </div>
                    <div style={splitCellStyle(row.right.type, 'right')}>
                      {row.right.type === 'empty' ? '' : renderLineText(row.right.text)}
                    </div>
                  </div>
                ))}
              </div>
            ) : unifiedRows.length === 0 ? (
              <div style={{ padding: '24px 12px', textAlign: 'center', color: '#6e7781', fontSize: 12 }}>
                原文与重写结果没有差异
              </div>
            ) : (
              <div>
                {unifiedRows.map((line, index) => {
                  if (line.type === 'hunk') {
                    return (
                      <div
                        key={index}
                        style={{
                          background: '#f6f8fa',
                          color: '#57606a',
                          fontSize: 11.5,
                          padding: '2px 8px',
                          borderTop: index > 0 ? '1px solid #d0d7de' : undefined,
                          fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
                        }}
                      >
                        {line.text}
                      </div>
                    )
                  }
                  const bg = line.type === 'delete' ? '#ffebe9' : line.type === 'insert' ? '#e6ffec' : '#ffffff'
                  const sign = line.type === 'delete' ? '-' : line.type === 'insert' ? '+' : ' '
                  return (
                    <div
                      key={index}
                      style={{
                        display: 'grid',
                        gridTemplateColumns: `${GUTTER_WIDTH}px ${GUTTER_WIDTH}px 18px minmax(0, 1fr)`,
                        background: bg,
                      }}
                    >
                      <div
                        style={{
                          color: '#6e7781', textAlign: 'right', padding: '2px 6px',
                          fontSize: 11, lineHeight: 1.65, background: '#f6f8fa',
                        }}
                      >
                        {line.oldLine ?? ''}
                      </div>
                      <div
                        style={{
                          color: '#6e7781', textAlign: 'right', padding: '2px 6px',
                          fontSize: 11, lineHeight: 1.65, background: '#f6f8fa',
                          borderLeft: '1px solid #d0d7de',
                        }}
                      >
                        {line.newLine ?? ''}
                      </div>
                      <div
                        style={{
                          color: line.type === 'delete' ? '#cf222e' : line.type === 'insert' ? '#1a7f37' : '#6e7781',
                          textAlign: 'center', fontSize: 12, lineHeight: 1.65,
                        }}
                      >
                        {sign}
                      </div>
                      <div
                        style={{
                          padding: '2px 8px', whiteSpace: 'pre-wrap', wordBreak: 'break-all',
                          fontSize: 12.5, lineHeight: 1.65,
                          fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
                        }}
                      >
                        {renderLineText(line.text)}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </Space>
      )}
    </Modal>
  )
}
