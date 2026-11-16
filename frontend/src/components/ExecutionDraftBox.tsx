/**
 * 执行日志草稿箱。
 *
 * 保存每条用例的执行日志全文、执行状态与运行日志，避免下载结果时
 * 日志被渲染成图片后丢失文本。恢复时把日志写回重新上传的用例。
 */
import { useCallback, useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import {
  Button, Collapse, Empty, Input, List, Modal, Popconfirm, Space, Switch,
  Tabs, Tag, Typography, message,
} from 'antd'
import {
  CopyOutlined, DeleteOutlined, DownloadOutlined, EditOutlined,
  EyeOutlined, FileTextOutlined, ReloadOutlined, SaveOutlined,
} from '@ant-design/icons'
import type { LogEntry, TestCase } from '../types'
import {
  buildDraftPlainText, collectExecutionDraft, copyTextToClipboard,
  deleteExecutionDraft, downloadTextFile, formatDraftTime, getAllExecutionDrafts,
  isExecutionDraftAutoSaveEnabled, renameExecutionDraft, saveExecutionDraft,
  setExecutionDraftAutoSaveEnabled, type ExecutionDraft,
} from '../utils/executionDraft'
import { terminalLogChars, toTerminalSections } from '../utils/terminalLogFormat'

const { Text } = Typography

interface Props {
  open: boolean
  cases: TestCase[]
  logs: LogEntry[]
  sourceFileName?: string
  onRestore: (draft: ExecutionDraft) => void
  onDraftsChanged?: (count: number) => void
}

const preStyle: CSSProperties = {
  margin: 0,
  maxHeight: '45vh',
  overflow: 'auto',
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-all',
  background: '#0b1020',
  color: '#d6deeb',
  padding: 12,
  borderRadius: 6,
  fontSize: 12,
  lineHeight: 1.6,
  fontFamily: "Consolas, 'Courier New', monospace",
}

function draftLogChars(draft: ExecutionDraft): number {
  return draft.cases.reduce(
    (total, item) => total + terminalLogChars(
      item.terminals?.length ? item.terminals : toTerminalSections(item.log_text),
    ),
    0,
  )
}

function draftTerminalCount(draft: ExecutionDraft): number {
  return draft.cases.reduce((total, item) => {
    const terminals = item.terminals?.length
      ? item.terminals
      : toTerminalSections(item.log_text)
    return total + terminals.length
  }, 0)
}

function draftFileName(draft: ExecutionDraft): string {
  const safe = draft.name.replace(/[\\/:*?"<>|]/g, '_')
  return `执行日志_${safe}.txt`
}

export default function ExecutionDraftBox({
  open,
  cases,
  logs,
  sourceFileName,
  onRestore,
  onDraftsChanged,
}: Props) {
  const [drafts, setDrafts] = useState<ExecutionDraft[]>([])
  const [saving, setSaving] = useState(false)
  const [autoSave, setAutoSave] = useState(isExecutionDraftAutoSaveEnabled())
  const [viewingDraft, setViewingDraft] = useState<ExecutionDraft | null>(null)
  const [renameTarget, setRenameTarget] = useState<{ id: string; name: string } | null>(null)

  const refreshDrafts = useCallback(() => {
    const list = getAllExecutionDrafts()
    setDrafts(list)
    onDraftsChanged?.(list.length)
  }, [onDraftsChanged])

  useEffect(() => {
    if (open) refreshDrafts()
  }, [open, refreshDrafts])

  useEffect(() => {
    const handler = () => refreshDrafts()
    window.addEventListener('execution-drafts-changed', handler)
    return () => window.removeEventListener('execution-drafts-changed', handler)
  }, [refreshDrafts])

  const handleSave = async () => {
    setSaving(true)
    try {
      const draft = await collectExecutionDraft({
        cases,
        logs,
        workbookName: sourceFileName,
      })
      if (!draft) {
        message.warning('暂无可保存的执行日志（用例尚未产生日志）')
        return
      }
      if (!saveExecutionDraft(draft)) {
        message.error('保存草稿失败：浏览器本地存储空间不足，请先删除旧草稿')
        return
      }
      refreshDrafts()
      message.success(`已保存草稿「${draft.name}」，包含 ${draft.case_count} 条用例日志`)
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = (id: string) => {
    if (deleteExecutionDraft(id)) {
      refreshDrafts()
      message.success('已删除草稿')
    } else {
      message.error('删除草稿失败')
    }
  }

  const handleRename = () => {
    if (!renameTarget) return
    if (!renameTarget.name.trim()) {
      message.warning('草稿名称不能为空')
      return
    }
    if (renameExecutionDraft(renameTarget.id, renameTarget.name)) {
      refreshDrafts()
      message.success('已重命名草稿')
      setRenameTarget(null)
    } else {
      message.error('重命名草稿失败')
    }
  }

  const handleCopy = async (draft: ExecutionDraft) => {
    const text = buildDraftPlainText(draft)
    if (await copyTextToClipboard(text)) {
      message.success('日志文本已复制到剪贴板')
    } else {
      message.error('复制失败，请改用「导出」按钮保存文本')
    }
  }

  const handleExport = (draft: ExecutionDraft) => {
    downloadTextFile(draftFileName(draft), buildDraftPlainText(draft))
    message.success('已导出日志文本')
  }

  const handleAutoSaveChange = (checked: boolean) => {
    setAutoSave(checked)
    setExecutionDraftAutoSaveEnabled(checked)
    message.success(checked ? '已开启执行结束自动保存日志草稿' : '已关闭执行结束自动保存')
  }

  const viewingItems = viewingDraft
    ? [
        ...viewingDraft.cases.map((item, index) => {
          const terminals = item.terminals?.length
            ? item.terminals
            : toTerminalSections(item.log_text)
          const chars = terminalLogChars(terminals)
          return {
            key: `case-${index}`,
            label: (
              <Space size={6} wrap>
                <Text strong>{item.case_id || `用例 ${index + 1}`}</Text>
                {item.status && <Tag color={item.status.toLowerCase() === 'pass' ? 'green' : item.status.toLowerCase() === 'fail' ? 'red' : 'default'}>{item.status}</Tag>}
                {item.description && <Text type="secondary" style={{ fontSize: 12 }}>{item.description}</Text>}
                {terminals.length > 1 && (
                  <Text type="secondary" style={{ fontSize: 12 }}>{terminals.length} 个终端</Text>
                )}
                <Text type="secondary" style={{ fontSize: 12 }}>{chars} 字符</Text>
              </Space>
            ),
            children: terminals.length > 0
              ? (
                <Tabs
                  size="small"
                  items={terminals.map((terminal, terminalIndex) => ({
                    key: `terminal-${terminalIndex}`,
                    label: terminal.label || '聚合日志',
                    children: <pre style={preStyle}>{terminal.content || '（无日志文本）'}</pre>,
                  }))}
                />
              )
              : <pre style={preStyle}>（无日志文本）</pre>,
          }
        }),
        ...(viewingDraft.logs.length > 0
          ? [{
              key: 'run-logs',
              label: <Text>运行日志（{viewingDraft.logs.length} 条）</Text>,
              children: (
                <pre style={preStyle}>
                  {viewingDraft.logs
                    .map((log) => `[${new Date(log.timestamp).toLocaleString()}] [${log.level}] ${log.message}`)
                    .join('\n')}
                </pre>
              ),
            }]
          : []),
      ]
    : []

  return (
    <div>
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
          <Button
            type="primary"
            icon={<SaveOutlined />}
            loading={saving}
            onClick={() => void handleSave()}
          >
            保存当前执行日志
          </Button>
          <Space size={8}>
            <Switch size="small" checked={autoSave} onChange={handleAutoSaveChange} />
            <Text type="secondary" style={{ fontSize: 12 }}>执行结束自动保存</Text>
            <Button size="small" icon={<ReloadOutlined />} onClick={refreshDrafts}>刷新</Button>
          </Space>
        </div>

        <Text type="secondary" style={{ fontSize: 12 }}>
          下载结果时日志会被渲染为图片，文本日志按终端分别保存在这里。恢复时请先重新上传用例文件，
          再把日志写回对应用例；当前工作簿：{sourceFileName || '未上传'}
        </Text>

        {drafts.length === 0 ? (
          <Empty description="暂无日志草稿" />
        ) : (
          <List
            size="small"
            dataSource={drafts}
            renderItem={(item) => (
              <List.Item
                key={item.id}
                style={{ padding: '10px 12px', background: '#fafafa', borderRadius: 6, border: '1px solid #eee' }}
                actions={[
                  <Button
                    key="restore"
                    type="primary"
                    size="small"
                    icon={<ReloadOutlined />}
                    onClick={() => onRestore(item)}
                  >
                    恢复
                  </Button>,
                  <Button key="view" size="small" icon={<EyeOutlined />} onClick={() => setViewingDraft(item)}>
                    查看
                  </Button>,
                  <Button key="export" size="small" icon={<DownloadOutlined />} onClick={() => handleExport(item)}>
                    导出
                  </Button>,
                  <Button
                    key="rename"
                    size="small"
                    icon={<EditOutlined />}
                    onClick={() => setRenameTarget({ id: item.id, name: item.name })}
                  >
                    重命名
                  </Button>,
                  <Popconfirm
                    key="delete"
                    title="确定删除这个日志草稿吗？"
                    description="删除后无法恢复。"
                    okText="删除"
                    cancelText="取消"
                    onConfirm={() => handleDelete(item.id)}
                  >
                    <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
                  </Popconfirm>,
                ]}
              >
                <List.Item.Meta
                  title={(
                    <Space size={6} wrap>
                      <Text strong>{item.name}</Text>
                      <Tag color={item.auto ? 'blue' : 'green'}>{item.auto ? '自动' : '手动'}</Tag>
                      <Text type="secondary" style={{ fontSize: 12 }}>{formatDraftTime(item.updatedAt)}</Text>
                    </Space>
                  )}
                  description={(
                    <Space size={12} wrap>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        <FileTextOutlined /> {item.cases.length} 条用例日志
                        {draftTerminalCount(item) > item.cases.length
                          ? ` · ${draftTerminalCount(item)} 个终端日志`
                          : ''}
                        {item.logs.length > 0 ? ` · ${item.logs.length} 条运行日志` : ''}
                        {draftLogChars(item) > 0 ? ` · ${(draftLogChars(item) / 1024).toFixed(1)} KB` : ''}
                      </Text>
                      {item.workbookName && (
                        <Text type="secondary" style={{ fontSize: 12 }}>工作簿：{item.workbookName}</Text>
                      )}
                    </Space>
                  )}
                />
              </List.Item>
            )}
          />
        )}
      </Space>

      {/* 查看日志全文 */}
      <Modal
        open={!!viewingDraft}
        title={viewingDraft ? `草稿日志 - ${viewingDraft.name}` : '草稿日志'}
        onCancel={() => setViewingDraft(null)}
        width={960}
        footer={viewingDraft
          ? (
            <Space>
              <Button onClick={() => setViewingDraft(null)}>关闭</Button>
              <Button icon={<CopyOutlined />} onClick={() => void handleCopy(viewingDraft)}>复制全部</Button>
              <Button type="primary" icon={<DownloadOutlined />} onClick={() => handleExport(viewingDraft)}>导出 txt</Button>
            </Space>
          )
          : null}
      >
        {viewingDraft && (
          <Space direction="vertical" style={{ width: '100%' }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              工作簿：{viewingDraft.workbookName || '-'} · 保存时间：{formatDraftTime(viewingDraft.updatedAt)}
            </Text>
            {viewingItems.length > 0
              ? <Collapse items={viewingItems} size="small" defaultActiveKey={['case-0']} />
              : <Empty description="草稿中没有日志" />}
          </Space>
        )}
      </Modal>

      {/* 重命名 */}
      <Modal
        title="重命名日志草稿"
        open={!!renameTarget}
        onOk={handleRename}
        onCancel={() => setRenameTarget(null)}
        okText="确定"
        cancelText="取消"
      >
        <Input
          value={renameTarget?.name || ''}
          onChange={(e) => setRenameTarget((prev) => prev ? { ...prev, name: e.target.value } : prev)}
          onPressEnter={handleRename}
          placeholder="输入草稿名称"
        />
      </Modal>
    </div>
  )
}
