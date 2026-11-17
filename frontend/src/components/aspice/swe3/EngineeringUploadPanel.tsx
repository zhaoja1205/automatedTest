/**
 * SWE.3 推送 D — 工程代码上传面板。
 *
 * 拖入 .zip → POST /aspice/projects/{id}/swe3/engineering/upload
 * 清空工程 → DELETE /aspice/projects/{id}/swe3/engineering
 *
 * 支持两种上传模式：
 * - 首次上传：覆盖解压
 * - 追加 zip：在已有 engineering_src/ 基础上追加解压（例如先传 include zip，再传源码 zip）
 */
import { useState } from 'react'
import { Upload, Card, Button, Space, Tag, Popconfirm, message, Descriptions, Empty, Tooltip } from 'antd'
import { InboxOutlined, DeleteOutlined, FileZipOutlined, PlusOutlined } from '@ant-design/icons'
import type { UploadProps } from 'antd'
import { useAspiceStore } from '../../../stores/useAspiceStore'
import { uploadEngineering, clearEngineering } from '../../../api/aspiceApi'

const { Dragger } = Upload

export default function EngineeringUploadPanel() {
  const { projectId, aspice, setSwe3Engineering } = useAspiceStore()
  const engineering = aspice?.swe3?.push_d?.engineering
  const [uploading, setUploading] = useState(false)

  const doUpload = async (file: File, append: boolean) => {
    if (!projectId) { message.warning('项目未创建'); return }
    setUploading(true)
    try {
      const res = await uploadEngineering(projectId, file, append)
      setSwe3Engineering(res.data)
      message.success(
        `${append ? '追加' : '上传'}完成：已解析 ${res.data.total_files} 个文件`
        + `（SDK ${res.data.sdk_files} / 项目 ${res.data.custom_files}）`,
      )
    } catch (e: any) {
      message.error(e?.response?.data?.detail || e?.message || '上传失败')
    } finally {
      setUploading(false)
    }
  }

  const uploadProps: UploadProps = {
    accept: '.zip',
    multiple: false,
    showUploadList: false,
    beforeUpload: async (file) => {
      await doUpload(file as File, false)
      return false  // 阻止 antd 默认上传
    },
  }

  const appendProps: UploadProps = {
    accept: '.zip',
    multiple: false,
    showUploadList: false,
    beforeUpload: async (file) => {
      await doUpload(file as File, true)
      return false
    },
  }

  const handleClear = async () => {
    if (!projectId) return
    try {
      await clearEngineering(projectId)
      setSwe3Engineering(undefined)
      message.info('已清空工程')
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '清空失败')
    }
  }

  if (!engineering) {
    return (
      <Card size="small">
        <Dragger {...uploadProps} disabled={uploading} style={{ padding: 20 }}>
          <p className="ant-upload-drag-icon">
            <InboxOutlined style={{ fontSize: 42 }} />
          </p>
          <p className="ant-upload-text">点击或拖拽 工程源码 .zip 到此处</p>
          <p className="ant-upload-hint">
            要求包含 <Tag>include/</Tag> 头文件根目录 + 工程代码目录（如 <Tag>src/</Tag>）
            <br />
            若 include 与源码分成多个 zip 包，可先上传任意一个，然后用右上角"追加 zip"把其余的加进来。
          </p>
        </Dragger>
        {uploading && <div style={{ textAlign: 'center', marginTop: 8 }}>解析中…</div>}
      </Card>
    )
  }

  return (
    <Card
      size="small"
      title={<Space><FileZipOutlined /><span>{engineering.zip_name}</span></Space>}
      extra={
        <Space>
          <Tooltip title="在已有工程上追加解压一个 zip（同路径会覆盖）">
            <Upload {...appendProps} disabled={uploading}>
              <Button size="small" icon={<PlusOutlined />} loading={uploading}>
                追加 zip
              </Button>
            </Upload>
          </Tooltip>
          <Popconfirm title="清空工程？所有扫描结果与关注函数一并清除" onConfirm={handleClear}>
            <Button size="small" danger icon={<DeleteOutlined />}>清空工程</Button>
          </Popconfirm>
        </Space>
      }
    >
      <Descriptions size="small" column={3} bordered>
        <Descriptions.Item label="上传时间">{engineering.uploaded_at}</Descriptions.Item>
        <Descriptions.Item label="include 根">{engineering.include_root}</Descriptions.Item>
        <Descriptions.Item label="代码根">
          {engineering.code_roots.join(' / ')}
        </Descriptions.Item>
        <Descriptions.Item label="总文件">
          <Tag color="blue">{engineering.total_files}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="SDK 文件">
          <Tag>{engineering.sdk_files}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="项目新增">
          <Tag color="green">{engineering.custom_files}</Tag>
        </Descriptions.Item>
      </Descriptions>
      <div style={{ marginTop: 12 }}>
        <div style={{ fontWeight: 500, marginBottom: 4 }}>文件抽样预览：</div>
        {engineering.file_tree_sample.length === 0 ? <Empty /> : (
          <div style={{
            maxHeight: 140, overflow: 'auto', background: '#fafafa',
            padding: 8, fontFamily: 'monospace', fontSize: 12,
          }}>
            {engineering.file_tree_sample.map((f) => <div key={f}>📄 {f}</div>)}
          </div>
        )}
      </div>
    </Card>
  )
}
