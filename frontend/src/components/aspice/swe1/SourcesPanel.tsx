/**
 * SWE.1 R1 - 需求源文件管理面板
 *
 * 职责：
 *   - 列出已上传的源文件（swe1.sources[]）
 *   - 上传新文件 → 直接触发 IngestWizard
 *   - 删除源文件（物理 + 记录）
 *   - 对已上传的文件"重新回灌" → 触发 IngestWizard
 *
 * 不负责解析和入库 - 那是 IngestWizard 的事。
 */
import { useEffect, useState } from 'react'
import {
  Button, List, Space, Tag, Upload, message, Popconfirm, Tooltip, Empty,
} from 'antd'
import {
  CloudUploadOutlined, DeleteOutlined, ReloadOutlined, FileExcelOutlined,
  FileWordOutlined, ImportOutlined,
} from '@ant-design/icons'
import type { UploadProps } from 'antd'
import {
  listSwe1Sources, uploadSwe1Source, deleteSwe1Source,
} from '../../../api/aspiceApi'
import type { Swe1SourceFile, Swe1SourceType } from '../../../types/aspice'

interface Props {
  projectId: string
  onOpenWizard: (fileId: string) => void   // 父组件开 IngestWizard
}

const SOURCE_TYPE_TAG: Record<Swe1SourceType, { color: string; text: string }> = {
  engineer_processed: { color: 'green', text: '已处理需求表' },
  customer_raw: { color: 'orange', text: '客户原始文档' },
  manual: { color: 'blue', text: '手工新增' },
  ai_suggested: { color: 'purple', text: 'AI 候选' },
  legacy: { color: 'default', text: '历史遗留' },
}

export default function SourcesPanel({ projectId, onOpenWizard }: Props) {
  const [sources, setSources] = useState<Swe1SourceFile[]>([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)

  const refresh = async () => {
    if (!projectId) return
    setLoading(true)
    try {
      const res = await listSwe1Sources(projectId)
      setSources(res.data.sources || [])
    } catch (e) {
      // 新项目没数据不算错
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  const handleDelete = async (fileId: string) => {
    try {
      await deleteSwe1Source(projectId, fileId)
      message.success('已删除')
      refresh()
    } catch (e) {
      message.error('删除失败')
    }
  }

  const uploadProps: UploadProps = {
    name: 'file',
    accept: '.xlsx,.xls,.docx',
    showUploadList: false,
    customRequest: async ({ file, onSuccess, onError }) => {
      if (!projectId) {
        message.warning('请先选择项目')
        return
      }
      setUploading(true)
      try {
        const res = await uploadSwe1Source(projectId, file as File, 'engineer_processed')
        message.success(`上传成功：${res.data.source.original_name}`)
        if (res.data.duplicate_of) {
          message.warning(`注意：文件内容与已有源 (${res.data.duplicate_of.slice(0, 8)}...) 相同`)
        }
        onSuccess?.(res.data)
        await refresh()
        // 自动开向导
        onOpenWizard(res.data.source.file_id)
      } catch (e: any) {
        const msg = e?.response?.data?.detail || e?.message || '上传失败'
        message.error(msg)
        onError?.(e)
      } finally {
        setUploading(false)
      }
    },
  }

  const fileIcon = (name: string) => {
    const lower = name.toLowerCase()
    if (lower.endsWith('.docx')) return <FileWordOutlined style={{ color: '#2b5797' }} />
    return <FileExcelOutlined style={{ color: '#217346' }} />
  }

  return (
    <div>
      <Space style={{ marginBottom: 12, width: '100%', justifyContent: 'space-between' }}>
        <Space>
          <Upload {...uploadProps}>
            <Button
              type="primary"
              icon={<CloudUploadOutlined />}
              loading={uploading}
            >
              上传需求表
            </Button>
          </Upload>
          <Tooltip title="刷新列表">
            <Button icon={<ReloadOutlined />} onClick={refresh} loading={loading} />
          </Tooltip>
        </Space>
        <Tag>{sources.length} 个源文件</Tag>
      </Space>

      {sources.length === 0 ? (
        <Empty
          description="还没有上传需求源文件 — 支持 .xlsx / .xls / .docx"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          style={{ padding: '24px 0' }}
        />
      ) : (
        <List
          size="small"
          dataSource={sources}
          renderItem={(s) => {
            const tagInfo = SOURCE_TYPE_TAG[s.source_type] || SOURCE_TYPE_TAG.manual
            return (
              <List.Item
                actions={[
                  <Button
                    key="ingest"
                    type="link"
                    size="small"
                    icon={<ImportOutlined />}
                    onClick={() => onOpenWizard(s.file_id)}
                  >
                    回灌
                  </Button>,
                  <Popconfirm
                    key="del"
                    title="删除源文件？"
                    description="仅删文件记录，已入库的需求不受影响。"
                    onConfirm={() => handleDelete(s.file_id)}
                  >
                    <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                      删除
                    </Button>
                  </Popconfirm>,
                ]}
              >
                <List.Item.Meta
                  avatar={fileIcon(s.original_name)}
                  title={
                    <Space wrap size={4}>
                      <span style={{ fontWeight: 500 }}>{s.original_name}</span>
                      <Tag color={tagInfo.color}>{tagInfo.text}</Tag>
                      {s.mapping_template_id && (
                        <Tag color="cyan">已套模板</Tag>
                      )}
                    </Space>
                  }
                  description={
                    <span style={{ fontSize: 12, color: '#999' }}>
                      {(s.size_bytes / 1024).toFixed(1)} KB · {s.sheet_count} sheet ·{' '}
                      {s.row_count} 行 · 上传于 {s.uploaded_at.slice(0, 16).replace('T', ' ')}
                    </span>
                  }
                />
              </List.Item>
            )
          }}
        />
      )}
    </div>
  )
}
