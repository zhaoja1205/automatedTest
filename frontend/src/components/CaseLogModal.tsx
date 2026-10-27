/**
 * 单条用例执行日志弹窗。
 *
 * 优先展示备注中 `--- 执行日志 ---` 之后的日志内容（上传结果表时可直接看到）；
 * 备注中没有日志时，回退到后端 /logs/content 读取日志文件全文。
 */
import { useEffect, useState } from 'react'
import { Alert, Modal, Spin, Typography } from 'antd'
import { getCaseLog } from '../api/axios'

interface Props {
  open: boolean
  title?: string
  log?: string
  path?: string
  runId?: string
  caseKey?: string
  onClose: () => void
}

export default function CaseLogModal({ open, title, log, path, runId, caseKey, onClose }: Props) {
  const [loading, setLoading] = useState(false)
  const [content, setContent] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return

    const localLog = log && log.trim() ? log : ''
    if (localLog) {
      setLoading(false)
      setError('')
      setContent(localLog)
      return
    }

    let cancelled = false
    setLoading(true)
    setContent('')
    setError('')
    getCaseLog({ path, run_id: runId, case_key: caseKey })
      .then((res) => {
        if (!cancelled) setContent(res.data.content || '')
      })
      .catch((err: unknown) => {
        if (cancelled) return
        const detail =
          (err as { response?: { data?: { detail?: string } }; message?: string })
            ?.response?.data?.detail
          || (err as Error)?.message
          || '读取日志失败'
        setError(detail)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, log, path, runId, caseKey])

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={920}
      title={title || '执行日志'}
      styles={{ body: { paddingTop: 12 } }}
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: '32px 0' }}>
          <Spin tip="加载日志..." />
        </div>
      ) : error ? (
        <Alert type="error" message={error} showIcon />
      ) : content.trim() ? (
        <>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {path || `${runId ? `运行 ${runId} / ` : ''}${caseKey || ''}`}
          </Typography.Text>
          <pre
            style={{
              margin: '8px 0 0',
              maxHeight: '65vh',
              overflow: 'auto',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-all',
              background: '#0b1020',
              color: '#d6deeb',
              padding: 12,
              borderRadius: 6,
              fontSize: 12,
              lineHeight: 1.6,
            }}
          >
            {content}
          </pre>
        </>
      ) : (
        <Alert type="info" message="该用例暂无执行日志" showIcon />
      )}
    </Modal>
  )
}
