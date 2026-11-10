/**
 * 测试步骤编辑弹窗。
 *
 * 用于在用例预览 / 用例列表里就地修改「测试步骤」文本，保存后写回当前用例。
 */
import { useEffect, useState } from 'react'
import { Input, Modal, Typography } from 'antd'

interface Props {
  open: boolean
  title?: string
  /** 当前测试步骤文本 */
  value: string
  /** 保存中状态（例如后端接口请求中） */
  loading?: boolean
  onCancel: () => void
  onSave: (next: string) => void | Promise<void>
}

export default function TestCaseStepsEditModal({
  open,
  title = '编辑测试步骤',
  value,
  loading = false,
  onCancel,
  onSave,
}: Props) {
  const [text, setText] = useState(value)

  // 每次打开时同步为当前用例的步骤，避免残留上一条用例的内容
  useEffect(() => {
    if (open) setText(value)
  }, [open, value])

  return (
    <Modal
      open={open}
      title={title}
      width={760}
      okText="保存"
      cancelText="取消"
      confirmLoading={loading}
      onOk={() => onSave(text)}
      onCancel={onCancel}
      destroyOnClose
    >
      <Typography.Paragraph type="secondary" style={{ marginBottom: 8, fontSize: 12 }}>
        每行一个步骤；交互命令写「输入 gc 0」「输入 al」等。系统只执行步骤中显式写出的 gc。
      </Typography.Paragraph>
      <Input.TextArea
        value={text}
        onChange={(event) => setText(event.target.value)}
        autoSize={{ minRows: 10, maxRows: 22 }}
        style={{ fontFamily: 'monospace', fontSize: 13 }}
        placeholder={'例如：\n1、输入命令：./nvsipl_camera ...\n2、输入gc 0\n3、输入 al'}
      />
    </Modal>
  )
}
