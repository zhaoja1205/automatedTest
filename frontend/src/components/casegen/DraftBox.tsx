/**
 * 草稿箱组件 - 管理手动保存的草稿
 */
import { useState } from 'react'
import { Button, Empty, List, Modal, Space, Typography, Input, message } from 'antd'
import { DeleteOutlined, EditOutlined, SaveOutlined, ReloadOutlined } from '@ant-design/icons'
import type { DraftItem, AutoSaveData } from '../../utils/casegen/storage'
import { getAllDrafts, saveDraft, deleteDraft, formatDate } from '../../utils/casegen/storage'

const { Text, Title } = Typography

interface Props {
  currentData: AutoSaveData
  onRestore: (data: AutoSaveData) => void
  onSaveCallback?: () => void
}

export default function DraftBox({ currentData, onRestore, onSaveCallback }: Props) {
  const [drafts, setDrafts] = useState<DraftItem[]>(getAllDrafts())
  const [saving, setSaving] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)
  const [renameModal, setRenameModal] = useState<{ id: string; name: string } | null>(null)

  const refreshDrafts = () => {
    setDrafts(getAllDrafts())
  }

  const handleSaveDraft = async () => {
    setSaving(true)
    try {
      const draft: DraftItem = {
        id: Date.now().toString(),
        name: `草稿_${drafts.length + 1}`,
        createdAt: Date.now(),
        updatedAt: Date.now(),
        data: currentData,
      }

      saveDraft(draft)
      refreshDrafts()
      message.success('草稿已保存')
      onSaveCallback?.()
    } catch {
      message.error('保存草稿失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteDraft = (id: string) => {
    if (deleteDraft(id)) {
      refreshDrafts()
      message.success('已删除草稿')
    }
    setDeleteConfirm(null)
  }

  const handleRenameDraft = (id: string, newName: string) => {
    const updated = drafts.map((d) =>
      d.id === id ? { ...d, name: newName, updatedAt: Date.now() } : d
    )
    updated.forEach((d) => saveDraft(d))
    refreshDrafts()
    setRenameModal(null)
    message.success('已重命名')
  }

  const handleRestoreDraft = (item: DraftItem) => {
    onRestore(item.data)
    message.success(`已恢复草稿"${item.name}"`)
  }

  return (
    <div>
      <Space direction="vertical" style={{ width: '100%' }} size="large">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Title level={5} style={{ margin: 0 }}>
            手动保存的草稿
          </Title>
          <Button
            type="primary"
            icon={<SaveOutlined />}
            onClick={handleSaveDraft}
            loading={saving}
          >
            保存当前状态
          </Button>
        </div>

        {drafts.length === 0 ? (
          <Empty description="暂无草稿" />
        ) : (
          <List
            size="small"
            dataSource={drafts}
            locale={{ emptyText: '' }}
            renderItem={(item) => (
              <List.Item
                style={{
                  padding: '8px 12px',
                  background: '#fafafa',
                  borderRadius: 6,
                  border: '1px solid #eee',
                }}
              >
                <List.Item.Meta
                  title={
                    <Space>
                      <Text strong>{item.name}</Text>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {formatDate(item.updatedAt)}
                      </Text>
                    </Space>
                  }
                  description={`步骤 ${Math.min(item.data.current, 5) + 1}/6 · ${item.data.generatedCasesCount || 0} 条用例${item.data.sensorConfigs?.length ? ` · ${item.data.sensorConfigs.length} 个 sensor 配置` : ''}`}
                />

                <Space style={{ float: 'right' }}>
                  <Button
                    size="small"
                    type="primary"
                    icon={<ReloadOutlined />}
                    onClick={() => handleRestoreDraft(item)}
                  >
                    恢复
                  </Button>
                  <Button
                    size="small"
                    icon={<EditOutlined />}
                    onClick={() => setRenameModal({ id: item.id, name: item.name })}
                  >
                    重命名
                  </Button>
                  <Button
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => setDeleteConfirm(item.id)}
                  >
                    删除
                  </Button>
                </Space>
              </List.Item>
            )}
          />
        )}
      </Space>

      {/* 删除确认弹窗 */}
      <Modal
        title="确认删除"
        open={!!deleteConfirm}
        onOk={() => deleteConfirm && handleDeleteDraft(deleteConfirm)}
        onCancel={() => setDeleteConfirm(null)}
        okText="删除"
        cancelText="取消"
      >
        <p>确定要删除这个草稿吗？此操作不可恢复。</p>
      </Modal>

      {/* 重命名弹窗 */}
      {renameModal && (
        <Modal
          title="重命名草稿"
          open={true}
          onOk={() => renameModal.name.trim() && handleRenameDraft(renameModal.id, renameModal.name.trim())}
          onCancel={() => setRenameModal(null)}
          okText="确定"
          cancelText="取消"
        >
          <Input
            value={renameModal.name}
            onChange={(e) => setRenameModal({ ...renameModal, name: e.target.value })}
            onPressEnter={() => renameModal.name.trim() && handleRenameDraft(renameModal.id, renameModal.name.trim())}
          />
        </Modal>
      )}
    </div>
  )
}
