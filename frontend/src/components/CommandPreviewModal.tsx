/**
 * 远端命令预览弹窗。
 *
 * 展示用例执行时真正会下发到板端的命令（含工作区路径覆盖、gc 注入、cd 前缀），
 * 以及不会自动执行的步骤（人工操作、待确认、未识别等）。
 */
import { useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Collapse,
  Empty,
  Modal,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { CopyOutlined } from '@ant-design/icons'
import { previewCaseCommands } from '../api/axios'
import type { CommandPreviewCase, CommandPreviewStep } from '../types'

interface Props {
  open: boolean
  caseKeys: string[]
  onClose: () => void
}

const KIND_META: Record<string, { label: string; color: string }> = {
  command: { label: 'Shell 命令', color: 'blue' },
  wait: { label: '等待', color: 'green' },
  enter_dir: { label: '进入目录', color: 'cyan' },
  cd: { label: '切换目录', color: 'cyan' },
  nvsipl_input: { label: 'nvsipl 输入', color: 'purple' },
  manual: { label: '人工操作', color: 'orange' },
  confirm: { label: '人工确认', color: 'gold' },
  repeat: { label: '重复', color: 'geekblue' },
  repeat_stream: { label: '反复起流', color: 'geekblue' },
  skip: { label: '跳过', color: 'default' },
}

const ACTION_LABEL: Record<string, string> = {
  execute: '执行',
  change_dir: '切换目录',
  input: '发送输入',
  manual: '人工操作',
  confirm: '人工确认',
  repeat: '重复',
  skip: '跳过',
  wait: '等待',
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    // 非 HTTPS / 非 localhost 环境下 clipboard API 不可用，回退到 execCommand
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
  }
  message.success('已复制到剪贴板')
}

function CaseCommands({ data }: { data: CommandPreviewCase }) {
  const columns: ColumnsType<CommandPreviewStep> = [
    {
      title: '#',
      key: 'index',
      width: 50,
      render: (_: unknown, record) => (
        <span style={{ color: '#9ca3af' }}>{record.index}</span>
      ),
    },
    {
      title: '类型',
      key: 'kind',
      width: 110,
      render: (_: unknown, record) => {
        const meta = KIND_META[record.kind] || { label: record.kind, color: 'default' }
        return (
          <Space direction="vertical" size={2}>
            <Tag color={meta.color} style={{ margin: 0 }}>{meta.label}</Tag>
            <Tag style={{ margin: 0, fontSize: 11 }}>{ACTION_LABEL[record.action] || record.action}</Tag>
          </Space>
        )
      },
    },
    {
      title: '实际下发命令',
      key: 'command',
      render: (_: unknown, record) =>
        record.command ? (
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 4 }}>
            <pre
              style={{
                margin: 0,
                flex: 1,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
                fontSize: 12,
                lineHeight: 1.5,
                background: '#f6f8fa',
                border: '1px solid #e5e7eb',
                borderRadius: 4,
                padding: '6px 8px',
              }}
            >
              {record.command}
            </pre>
            <Button
              type="text"
              size="small"
              icon={<CopyOutlined />}
              onClick={() => copyText(record.command)}
              style={{ padding: '0 2px', flexShrink: 0 }}
            />
          </div>
        ) : (
          <Typography.Text type="secondary">-</Typography.Text>
        ),
    },
    {
      title: '说明',
      key: 'notes',
      render: (_: unknown, record) => (
        <div style={{ fontSize: 12, lineHeight: 1.6 }}>
          <div style={{ color: '#6b7280' }}>{record.description || '-'}</div>
          {record.notes.map((note, i) => (
            <div key={i} style={{ color: '#fa8c16', marginTop: 2 }}>• {note}</div>
          ))}
        </div>
      ),
    },
    {
      title: '终端',
      key: 'terminal',
      width: 90,
      render: (_: unknown, record) => record.terminal || '-',
    },
  ]

  const copyAll = () => {
    const lines: string[] = []
    if (data.prerequisites_enabled) {
      data.prerequisites.forEach((p) => {
        lines.push(p.manual_confirm ? `MANUAL_CONFIRM ${p.command}` : p.command)
      })
    }
    data.steps.filter((s) => s.action === 'execute').forEach((s) => lines.push(s.command))
    if (lines.length === 0) {
      message.info('没有可复制的命令')
      return
    }
    void copyText(lines.join('\n'))
  }

  if (data.error) {
    return <Alert type="error" showIcon message={data.error} />
  }

  return (
    <div>
      <Space wrap size={8} style={{ marginBottom: 8 }}>
        <Tag color="blue">{data.mode_label || data.mode}</Tag>
        {data.ai_cache_used && <Tag color="purple">已应用 AI 解析结果</Tag>}
        {data.na && <Tag>NA</Tag>}
        <Button size="small" icon={<CopyOutlined />} onClick={copyAll}>
          复制全部命令
        </Button>
      </Space>

      {data.na && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 8 }}
          message={`该用例判定为 NA，不会执行：${data.na_reason}`}
        />
      )}

      {data.unrecognized_count > 0 && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 8 }}
          message={`有 ${data.unrecognized_count} 个步骤未识别为命令，执行时会被跳过`}
          description={data.ai_cache_used ? '' : '如已启用 AI，可先在用例列表点击「AI 解析步骤」补充后再预览。'}
        />
      )}

      {!data.na && (
        <>
          <Typography.Text strong style={{ fontSize: 13 }}>
            前置条件
            {!data.prerequisites_enabled && (
              <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 6 }}>
                （工作区已关闭，不会执行）
              </Typography.Text>
            )}
          </Typography.Text>
          {data.prerequisites.length === 0 ? (
            <div style={{ color: '#9ca3af', fontSize: 12, margin: '4px 0 12px' }}>无</div>
          ) : (
            <div
              style={{
                margin: '4px 0 12px',
                padding: '6px 8px',
                background: '#fafafa',
                border: '1px solid #eee',
                borderRadius: 4,
                opacity: data.prerequisites_enabled ? 1 : 0.55,
              }}
            >
              {data.prerequisites.map((p, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, margin: '2px 0' }}>
                  {p.manual_confirm ? (
                    <Tag color="gold" style={{ margin: 0, fontSize: 11 }}>人工确认</Tag>
                  ) : (
                    <Tag style={{ margin: 0, fontSize: 11 }}>Shell</Tag>
                  )}
                  <code style={{ fontSize: 12, wordBreak: 'break-all' }}>{p.command}</code>
                </div>
              ))}
            </div>
          )}

          <Typography.Text strong style={{ fontSize: 13 }}>测试步骤</Typography.Text>
          <Table
            style={{ marginTop: 4 }}
            size="small"
            rowKey="index"
            columns={columns}
            dataSource={data.steps}
            pagination={false}
            scroll={{ x: 900 }}
            locale={{ emptyText: <Empty description="没有解析出可执行步骤" /> }}
          />
        </>
      )}

      {data.notes.length > 0 && (
        <div style={{ marginTop: 10, fontSize: 12, color: '#6b7280', lineHeight: 1.7 }}>
          {data.notes.map((note, i) => (
            <div key={i}>• {note}</div>
          ))}
        </div>
      )}

      <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
        以上为实际下发到板端的命令；sudo 密码不会显示，执行时自动注入。
      </Typography.Text>
    </div>
  )
}

export default function CommandPreviewModal({ open, caseKeys, onClose }: Props) {
  const [loading, setLoading] = useState(false)
  const [cases, setCases] = useState<CommandPreviewCase[]>([])
  const [error, setError] = useState('')

  const keySignature = caseKeys.join(',')

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    setError('')
    setCases([])
    previewCaseCommands(caseKeys)
      .then((res) => {
        if (!cancelled) setCases(res.data.cases || [])
      })
      .catch((err: unknown) => {
        if (cancelled) return
        const detail =
          (err as { response?: { data?: { detail?: string } }; message?: string })
            ?.response?.data?.detail
          || (err as Error)?.message
          || '命令预览失败'
        setError(detail)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // caseKeys 以签名作为依赖，避免数组引用变化触发重复请求
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, keySignature])

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={1100}
      title={`即将执行的命令${cases.length > 1 ? `（${cases.length} 条用例）` : ''}`}
      styles={{ body: { paddingTop: 12, maxHeight: '75vh', overflow: 'auto' } }}
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: '40px 0' }}>
          <Spin tip="解析命令..." />
        </div>
      ) : error ? (
        <Alert type="error" showIcon message={error} />
      ) : cases.length === 0 ? (
        <Empty description="没有可预览的用例" />
      ) : cases.length === 1 ? (
        <CaseCommands data={cases[0]} />
      ) : (
        <Collapse
          defaultActiveKey={[cases[0].case_key || cases[0].case_id]}
          items={cases.map((c) => ({
            key: c.case_key || c.case_id,
            label: (
              <Space size={8}>
                <span style={{ fontWeight: 600 }}>{c.case_id}</span>
                <span style={{ color: '#6b7280', fontSize: 12 }}>{c.description}</span>
                {c.na && <Tag>NA</Tag>}
              </Space>
            ),
            children: <CaseCommands data={c} />,
          }))}
        />
      )}
    </Modal>
  )
}
