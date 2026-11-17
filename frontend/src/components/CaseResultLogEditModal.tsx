/**
 * 用例「实际结果 + 执行日志」编辑弹窗。
 *
 * 执行测试页表格的实际结果单元格展示判定文本，日志通过弹窗查看；
 * 这里同时提供两个文本框，保存后分别写回 BUG 列文本与执行日志
 * （日志同时更新聚合日志文件和按终端落盘的日志文件）。
 */
import { useEffect, useState } from 'react'
import { Input, Modal, Typography } from 'antd'

interface Props {
  open: boolean
  title?: string
  /** 实际结果（表格中展示的判定文本） */
  resultText: string
  /** 执行日志文本 */
  logText: string
  /** 保存中状态 */
  loading?: boolean
  onCancel: () => void
  onSave: (resultText: string, logText: string) => void | Promise<void>
}

export default function CaseResultLogEditModal({
  open,
  title = '编辑实际结果与执行日志',
  resultText,
  logText,
  loading = false,
  onCancel,
  onSave,
}: Props) {
  const [result, setResult] = useState(resultText)
  const [log, setLog] = useState(logText)

  // 每次打开时同步为当前用例内容，避免残留上一条用例的文本
  useEffect(() => {
    if (open) {
      setResult(resultText)
      setLog(logText)
    }
  }, [open, resultText, logText])

  return (
    <Modal
      open={open}
      title={title}
      width={960}
      okText="保存"
      cancelText="取消"
      confirmLoading={loading}
      onOk={() => onSave(result, log)}
      onCancel={onCancel}
      destroyOnClose
    >
      <Typography.Paragraph type="secondary" style={{ marginBottom: 12, fontSize: 12 }}>
        实际结果会写入用例的 BUG 列；执行日志会写回备注与日志文件（若日志含
        「===== 终端 =====」分段，会同步更新各终端日志）。
      </Typography.Paragraph>
      <Typography.Text strong style={{ fontSize: 13 }}>实际结果</Typography.Text>
      <Input.TextArea
        value={result}
        onChange={(event) => setResult(event.target.value)}
        autoSize={{ minRows: 6, maxRows: 14 }}
        style={{ margin: '6px 0 14px', fontSize: 13 }}
        placeholder="填写实际结果 / 判定说明"
      />
      <Typography.Text strong style={{ fontSize: 13 }}>执行日志</Typography.Text>
      <Input.TextArea
        value={log}
        onChange={(event) => setLog(event.target.value)}
        autoSize={{ minRows: 10, maxRows: 22 }}
        style={{ marginTop: 6, fontFamily: 'monospace', fontSize: 12 }}
        placeholder="粘贴或修改执行日志文本"
      />
    </Modal>
  )
}
