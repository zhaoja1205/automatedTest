/**
 * 文件推送独立页面
 */
import { useState } from 'react'
import { isAxiosError } from 'axios'
import {
  Card, Input, Radio, Upload, Button, Space, Typography, Checkbox, message,
} from 'antd'
import { UploadOutlined, CloudUploadOutlined } from '@ant-design/icons'
import api, { pushFileToBoard, pushLocalToBoard } from '../api/axios'

const { Text } = Typography

export default function FilePushPage() {
  const [pushMode, setPushMode] = useState<'file' | 'local'>('local')
  const [pushFile, setPushFile] = useState<File | null>(null)
  const [pushLocalPath, setPushLocalPath] = useState('')
  const [pushRemotePath, setPushRemotePath] = useState('')
  const [pushSoPath, setPushSoPath] = useState('')
  const [pushBoardType, setPushBoardType] = useState<'linux' | 'qnx'>('linux')
  const [pushCopyEnabled, setPushCopyEnabled] = useState(false)
  const [pushing, setPushing] = useState(false)

  const handlePush = async () => {
    if (!pushRemotePath) { message.warning('请填写板端目标路径'); return }
    if (pushMode === 'file' && !pushFile) { message.warning('请选择要上传的文件'); return }
    if (pushMode === 'local' && !pushLocalPath) { message.warning('请填写 PC 本地路径'); return }
    if (pushCopyEnabled && !pushSoPath) { message.warning('请填写运行 so 路径'); return }

    setPushing(true)
    try {
      if (pushMode === 'file' && pushFile) {
        const res = await pushFileToBoard(pushFile, pushRemotePath)
        message.success(res.data.message)
      } else {
        const res = await pushLocalToBoard(pushLocalPath, pushRemotePath)
        message.success(res.data.message)
      }
      if (pushCopyEnabled && pushSoPath) {
        const copyRes = await api.post<{ message: string }>('/files/copy-to-so', {
          source_path: pushRemotePath, so_path: pushSoPath, board_type: pushBoardType,
        })
        message.success(copyRes.data.message)
      }
      setPushFile(null)
      setPushLocalPath('')
      setPushRemotePath('')
    } catch (err) {
      const msg = isAxiosError(err) ? err.response?.data?.detail || err.message : '文件推送失败'
      message.error(msg)
    } finally {
      setPushing(false)
    }
  }

  return (
    <Card
      title={<><CloudUploadOutlined style={{ marginRight: 8 }} />推送文件到板端</>}
      extra={<Button type="primary" loading={pushing} onClick={handlePush}>推送</Button>}
      style={{ maxWidth: 640 }}
    >
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <div>
          <Text strong>推送方式：</Text>
          <Radio.Group value={pushMode} onChange={(e) => setPushMode(e.target.value)} style={{ marginLeft: 8 }}>
            <Radio value="local">PC 本地路径（支持目录）</Radio>
            <Radio value="file">浏览器选择文件</Radio>
          </Radio.Group>
        </div>

        {pushMode === 'local' ? (
          <div>
            <Text strong>PC 本地路径（文件或目录）：</Text>
            <Input
              placeholder="如 /media/tstj/2t/so_files/ 或 /home/user/test.so"
              value={pushLocalPath}
              onChange={(e) => setPushLocalPath(e.target.value)}
              style={{ marginTop: 4 }}
            />
          </div>
        ) : (
          <div>
            <Text strong>选择本地文件：</Text>
            <Upload
              beforeUpload={(file) => { setPushFile(file); return false }}
              maxCount={1}
              onRemove={() => setPushFile(null)}
              fileList={pushFile ? [{ uid: '-1', name: pushFile.name, status: 'done' as const }] : []}
            >
              <Button icon={<UploadOutlined />}>选择文件</Button>
            </Upload>
          </div>
        )}

        <div>
          <Text strong>板端目标路径（中转目录）：</Text>
          <Input
            placeholder="如 /home/nvidia/tmp_so/ 或 /storage/zja/drv/"
            value={pushRemotePath}
            onChange={(e) => setPushRemotePath(e.target.value)}
            style={{ marginTop: 4 }}
          />
        </div>

        <div>
          <Checkbox checked={pushCopyEnabled} onChange={(e) => setPushCopyEnabled(e.target.checked)}>
            <Text strong>推送后复制到运行 so 路径</Text>
          </Checkbox>
        </div>

        {pushCopyEnabled && (
          <>
            <div>
              <Text strong>板端系统类型：</Text>
              <Radio.Group value={pushBoardType} onChange={(e) => setPushBoardType(e.target.value)} style={{ marginLeft: 8 }}>
                <Radio value="linux">Linux（sudo cp）</Radio>
                <Radio value="qnx">QNX（cp）</Radio>
              </Radio.Group>
            </div>
            <div>
              <Text strong>运行 so 路径：</Text>
              <Input
                placeholder={pushBoardType === 'linux' ? '如 /usr/lib/nvsipl_drv/' : '如 /lib/firmware/'}
                value={pushSoPath}
                onChange={(e) => setPushSoPath(e.target.value)}
                style={{ marginTop: 4 }}
              />
            </div>
          </>
        )}
      </Space>
    </Card>
  )
}
