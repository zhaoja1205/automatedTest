/**
 * ASPICE 文档 — 项目列表页。
 *
 * 复用 creator 项目列表（共享同一项目实体），进入编辑走 ASPICE 向导。
 */
import { useEffect, useState } from 'react'
import { Table, Button, Space, Modal, Input, message, Popconfirm, Tag } from 'antd'
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  ApartmentOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import type { CaseProjectSummary } from '../../types/creator'
import {
  listAspiceProjects,
  createAspiceProject,
  deleteCreatorProject,
} from '../../api/aspiceApi'

export default function AspiceProjectsPage() {
  const navigate = useNavigate()
  const [projects, setProjects] = useState<CaseProjectSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [createModalOpen, setCreateModalOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [creating, setCreating] = useState(false)
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const [batchDeleting, setBatchDeleting] = useState(false)

  const fetchProjects = async () => {
    setLoading(true)
    try {
      const res = await listAspiceProjects()
      setProjects(res.data)
      setSelectedRowKeys((keys) => keys.filter((key) => res.data.some((p) => p.project_id === key)))
    } catch {
      message.error('加载项目列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchProjects() }, [])

  const handleCreate = async () => {
    if (!newName.trim()) {
      message.warning('请输入项目名称')
      return
    }
    setCreating(true)
    try {
      const res = await createAspiceProject(newName.trim())
      message.success('项目已创建')
      setCreateModalOpen(false)
      setNewName('')
      navigate(`/aspice/edit/${res.data.project_id}`)
    } catch {
      message.error('创建失败')
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteCreatorProject(id)
      message.success('已删除')
      setSelectedRowKeys((keys) => keys.filter((key) => key !== id))
      fetchProjects()
    } catch {
      message.error('删除失败')
    }
  }

  const handleBatchDelete = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要删除的项目')
      return
    }
    setBatchDeleting(true)
    try {
      await Promise.all(selectedRowKeys.map((id) => deleteCreatorProject(String(id))))
      message.success(`已删除 ${selectedRowKeys.length} 个项目`)
      setSelectedRowKeys([])
      fetchProjects()
    } catch {
      message.error('批量删除失败')
    } finally {
      setBatchDeleting(false)
    }
  }

  const columns = [
    { title: '项目名称', dataIndex: 'name', key: 'name' },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 180 },
    { title: '更新时间', dataIndex: 'updated_at', key: 'updated_at', width: 180 },
    {
      title: '功能用例',
      key: 'func',
      width: 100,
      render: (_: unknown, r: CaseProjectSummary) =>
        r.functional_count > 0 ? <Tag color="blue">{r.functional_count}</Tag> : <Tag>-</Tag>,
    },
    {
      title: '故障用例',
      key: 'fault',
      width: 100,
      render: (_: unknown, r: CaseProjectSummary) =>
        r.fault_count > 0 ? <Tag color="orange">{r.fault_count}</Tag> : <Tag>-</Tag>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      render: (_: unknown, r: CaseProjectSummary) => (
        <Space size={4}>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => navigate(`/aspice/edit/${r.project_id}`)}
          >
            ASPICE 编辑
          </Button>
          <Popconfirm title="删除此项目？" onConfirm={() => handleDelete(r.project_id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>
          <ApartmentOutlined style={{ marginRight: 8 }} />
          ASPICE 文档项目管理
        </h2>
        <Space>
          <Popconfirm
            title={`删除选中的 ${selectedRowKeys.length} 个项目？`}
            disabled={selectedRowKeys.length === 0}
            onConfirm={handleBatchDelete}
          >
            <Button
              danger
              icon={<DeleteOutlined />}
              disabled={selectedRowKeys.length === 0}
              loading={batchDeleting}
            >
              删除选中
            </Button>
          </Popconfirm>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModalOpen(true)}>
            新建项目
          </Button>
        </Space>
      </div>

      <Table
        rowKey="project_id"
        rowSelection={{
          selectedRowKeys,
          onChange: setSelectedRowKeys,
        }}
        columns={columns}
        dataSource={projects}
        loading={loading}
        pagination={false}
        size="small"
      />

      <Modal
        title="新建 ASPICE 项目"
        open={createModalOpen}
        confirmLoading={creating}
        onCancel={() => { setCreateModalOpen(false); setNewName('') }}
        onOk={handleCreate}
        okText="创建"
      >
        <p>此处创建的项目仅显示在「ASPICE 文档」入口，不会出现在「用例创建」项目列表。</p>
        <Input
          placeholder="项目名称（如 Pangu）"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onPressEnter={handleCreate}
        />
      </Modal>
    </div>
  )
}
