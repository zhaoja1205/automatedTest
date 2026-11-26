/**
 * SWE.1 R1 - 列映射模板管理（跨项目复用）
 *
 * 只允许改名字 / 描述 / 删除；mapping 本身通过 IngestWizard "保存为模板"覆盖。
 */
import { useEffect, useState } from 'react'
import { List, Button, Input, Space, Tag, Popconfirm, message, Empty, Tooltip } from 'antd'
import { ReloadOutlined, DeleteOutlined, EditOutlined, CheckOutlined } from '@ant-design/icons'
import {
  listMappingTemplates, updateMappingTemplate, deleteMappingTemplate,
} from '../../../api/aspiceApi'
import type { Swe1MappingTemplate } from '../../../types/aspice'

export default function TemplatesPanel() {
  const [tpls, setTpls] = useState<Swe1MappingTemplate[]>([])
  const [loading, setLoading] = useState(false)
  const [editId, setEditId] = useState<string>('')
  const [editName, setEditName] = useState<string>('')

  const refresh = async () => {
    setLoading(true)
    try {
      const res = await listMappingTemplates()
      setTpls(res.data.templates || [])
    } catch (e) {
      // 空就是空
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() }, [])

  const handleSaveName = async (id: string) => {
    try {
      await updateMappingTemplate(id, { name: editName })
      message.success('已更新')
      setEditId('')
      refresh()
    } catch (e) {
      message.error('更新失败')
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteMappingTemplate(id)
      message.success('已删除')
      refresh()
    } catch (e) {
      message.error('删除失败')
    }
  }

  return (
    <div>
      <Space style={{ marginBottom: 8, width: '100%', justifyContent: 'space-between' }}>
        <span style={{ color: '#666' }}>
          模板保存后，再次导入同样列头的需求表会自动套用，省掉 A3 列映射步骤
        </span>
        <Space>
          <Tag>{tpls.length} 个模板</Tag>
          <Button size="small" icon={<ReloadOutlined />} onClick={refresh} loading={loading} />
        </Space>
      </Space>

      {tpls.length === 0 ? (
        <Empty description="还没有列映射模板 — 在回灌向导里勾选'保存为模板'即可" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <List
          size="small"
          dataSource={tpls}
          renderItem={(t) => (
            <List.Item
              actions={[
                editId === t.template_id ? (
                  <Button
                    key="save"
                    size="small"
                    type="link"
                    icon={<CheckOutlined />}
                    onClick={() => handleSaveName(t.template_id)}
                  >保存</Button>
                ) : (
                  <Button
                    key="edit"
                    size="small"
                    type="link"
                    icon={<EditOutlined />}
                    onClick={() => { setEditId(t.template_id); setEditName(t.name) }}
                  >改名</Button>
                ),
                <Popconfirm
                  key="del"
                  title="删除此模板？"
                  description="不影响已入库需求"
                  onConfirm={() => handleDelete(t.template_id)}
                >
                  <Button size="small" type="link" danger icon={<DeleteOutlined />}>删除</Button>
                </Popconfirm>,
              ]}
            >
              <List.Item.Meta
                title={
                  editId === t.template_id ? (
                    <Input
                      size="small"
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      onPressEnter={() => handleSaveName(t.template_id)}
                      style={{ maxWidth: 300 }}
                    />
                  ) : (
                    <Space>
                      <span style={{ fontWeight: 500 }}>{t.name}</span>
                      <Tag color="cyan">{t.mappings.length} 列</Tag>
                      <Tooltip title={t.header_fingerprint}>
                        <Tag style={{ fontFamily: 'monospace', fontSize: 11 }}>
                          fp: {t.header_fingerprint.slice(0, 8)}
                        </Tag>
                      </Tooltip>
                    </Space>
                  )
                }
                description={
                  <span style={{ fontSize: 12, color: '#999' }}>
                    创建于 {t.created_at.slice(0, 16).replace('T', ' ')} ·{' '}
                    列头: {t.headers.filter(Boolean).slice(0, 5).join(' / ')}
                    {t.headers.filter(Boolean).length > 5 && ' ...'}
                  </span>
                }
              />
            </List.Item>
          )}
        />
      )}
    </div>
  )
}
