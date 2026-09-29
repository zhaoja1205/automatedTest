/**
 * 类图分析 — 项目列表页。
 *
 * 每个项目是一次「工程 zip + include zips + 查询记录」的持久化容器。
 * 从表格进工作区页做上传+生成。
 */
import { useEffect, useState } from 'react'
import { Table, Button, Space, Modal, Input, message, Tag, Popconfirm, Tooltip } from 'antd'
import {
  PlusOutlined,
  DeleteOutlined,
  EditOutlined,
  FolderOpenOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import type { ClassDiagProjectSummary } from '../../types/classDiag'
import {
  listClassDiagProjects,
  createClassDiagProject,
  deleteClassDiagProject,
} from '../../api/classDiagApi'

export default function ClassDiagProjectsPage() {
  const navigate = useNavigate()
  const [projects, setProjects] = useState<ClassDiagProjectSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [createModalOpen, setCreateModalOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [creating, setCreating] = useState(false)

  const fetchProjects = async () => {
    setLoading(true)
    try {
      const res = await listClassDiagProjects()
      setProjects(res.data)
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
      const res = await createClassDiagProject(newName.trim())
      message.success('项目已创建')
      setCreateModalOpen(false)
      setNewName('')
      navigate(`/classdiag/workspace/${res.data.project_id}`)
    } catch {
      message.error('创建失败')
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteClassDiagProject(id)
      message.success('已删除')
      fetchProjects()
    } catch {
      message.error('删除失败')
    }
  }

  const columns = [
    {
      title: '项目名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: ClassDiagProjectSummary) => (
        <a onClick={() => navigate(`/classdiag/workspace/${record.project_id}`)}>{name}</a>
      ),
    },
    {
      title: '源码',
      key: 'source',
      width: 100,
      align: 'center' as const,
      render: (_: unknown, record: ClassDiagProjectSummary) =>
        record.has_source
          ? <Tag color="success">已上传</Tag>
          : <Tag>未上传</Tag>,
    },
    {
      title: 'Include 包',
      dataIndex: 'include_count',
      key: 'include_count',
      width: 110,
      align: 'center' as const,
      render: (n: number) => n > 0 ? <Tag color="blue">{n}</Tag> : <Tag>0</Tag>,
    },
    {
      title: '上次查询',
      dataIndex: 'last_class',
      key: 'last_class',
      render: (v: string) => v || <span style={{ color: '#bbb' }}>—</span>,
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 180,
    },
    {
      title: '操作',
      key: 'actions',
      width: 180,
      render: (_: unknown, record: ClassDiagProjectSummary) => (
        <Space size="small">
          <Tooltip title="打开">
            <Button
              type="link"
              size="small"
              icon={<EditOutlined />}
              onClick={() => navigate(`/classdiag/workspace/${record.project_id}`)}
            />
          </Tooltip>
          <Popconfirm title="确定删除此项目？会同时删除源码解压目录。"
                       onConfirm={() => handleDelete(record.project_id)}>
            <Tooltip title="删除">
              <Button type="link" size="small" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between',
                    alignItems: 'center', marginBottom: 16 }}>
        <div>
          <h2 style={{ margin: 0 }}>
            <FolderOpenOutlined style={{ marginRight: 8 }} />
            类图分析项目
          </h2>
          <p style={{ margin: '6px 0 0', color: '#888' }}>
            上传 C++ 工程 zip 和 include 依赖包，输入类的全限定名，生成 UML 类图。
          </p>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModalOpen(true)}>
          新建项目
        </Button>
      </div>

      <Table
        rowKey="project_id"
        columns={columns}
        dataSource={projects}
        loading={loading}
        pagination={false}
        locale={{ emptyText: '暂无项目，点击右上角"新建项目"开始' }}
      />

      <Modal
        title="新建类图分析项目"
        open={createModalOpen}
        onCancel={() => { setCreateModalOpen(false); setNewName('') }}
        onOk={handleCreate}
        confirmLoading={creating}
        okText="创建"
      >
        <Input
          placeholder="请输入项目名称，如：SIPL 驱动 UML"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onPressEnter={handleCreate}
          autoFocus
        />
      </Modal>
    </div>
  )
}
