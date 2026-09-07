/**
 * 用例创建 — 项目列表页。
 *
 * 展示所有已保存项目，支持创建、编辑、删除、导出、下载操作。
 */
import { useEffect, useState } from 'react'
import { Table, Button, Space, Modal, Input, message, Tag, Popconfirm, Tooltip } from 'antd'
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  ExportOutlined,
  DownloadOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import type { CaseProjectSummary, ExportResult } from '../../types/creator'
import {
  listCreatorProjects,
  createCreatorProject,
  deleteCreatorProject,
  exportCreatorProject,
  downloadCreatorFile,
} from '../../api/creatorApi'

export default function CreatorProjectsPage() {
  const navigate = useNavigate()
  const [projects, setProjects] = useState<CaseProjectSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [createModalOpen, setCreateModalOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [creating, setCreating] = useState(false)
  const [exportingId, setExportingId] = useState<string | null>(null)
  const [exportResult, setExportResult] = useState<ExportResult | null>(null)
  const [exportModalOpen, setExportModalOpen] = useState(false)

  const fetchProjects = async () => {
    setLoading(true)
    try {
      const res = await listCreatorProjects()
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
      const res = await createCreatorProject(newName.trim())
      message.success('项目已创建')
      setCreateModalOpen(false)
      setNewName('')
      navigate(`/creator/edit/${res.data.project_id}`)
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
      fetchProjects()
    } catch {
      message.error('删除失败')
    }
  }

  const handleExport = async (id: string) => {
    setExportingId(id)
    try {
      const res = await exportCreatorProject(id)
      setExportResult(res.data)
      setExportModalOpen(true)
      message.success('导出完成')
    } catch {
      message.error('导出失败')
    } finally {
      setExportingId(null)
    }
  }

  const handleDownload = async (projectId: string, filename: string) => {
    try {
      const res = await downloadCreatorFile(projectId, filename)
      const blob = new Blob([res.data])
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      window.URL.revokeObjectURL(url)
    } catch {
      message.error('下载失败')
    }
  }

  const columns = [
    {
      title: '项目名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: CaseProjectSummary) => (
        <a onClick={() => navigate(`/creator/edit/${record.project_id}`)}>{name}</a>
      ),
    },
    {
      title: '功能用例',
      dataIndex: 'functional_count',
      key: 'functional_count',
      width: 100,
      align: 'center' as const,
    },
    {
      title: '故障用例',
      dataIndex: 'fault_count',
      key: 'fault_count',
      width: 100,
      align: 'center' as const,
    },
    {
      title: '状态',
      key: 'status',
      width: 120,
      render: (_: unknown, record: CaseProjectSummary) => {
        const total = record.functional_count + record.fault_count
        if (total === 0) return <Tag>空项目</Tag>
        if (record.has_placeholders) return <Tag icon={<WarningOutlined />} color="warning">有占位符</Tag>
        return <Tag color="success">就绪</Tag>
      },
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
      width: 240,
      render: (_: unknown, record: CaseProjectSummary) => (
        <Space size="small">
          <Tooltip title="编辑">
            <Button
              type="link"
              size="small"
              icon={<EditOutlined />}
              onClick={() => navigate(`/creator/edit/${record.project_id}`)}
            />
          </Tooltip>
          <Tooltip title="导出 xlsx">
            <Button
              type="link"
              size="small"
              icon={<ExportOutlined />}
              loading={exportingId === record.project_id}
              onClick={() => handleExport(record.project_id)}
            />
          </Tooltip>
          <Popconfirm title="确定删除此项目？" onConfirm={() => handleDelete(record.project_id)}>
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
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>用例创建项目</h2>
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
        locale={{ emptyText: '暂无项目，点击上方"新建项目"开始创建' }}
      />

      {/* 新建项目弹窗 */}
      <Modal
        title="新建用例创建项目"
        open={createModalOpen}
        onCancel={() => { setCreateModalOpen(false); setNewName('') }}
        onOk={handleCreate}
        confirmLoading={creating}
        okText="创建"
      >
        <Input
          placeholder="请输入项目名称，如：Zhiji Camera 驱动测试"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onPressEnter={handleCreate}
          autoFocus
        />
      </Modal>

      {/* 导出结果弹窗 */}
      <Modal
        title="导出结果"
        open={exportModalOpen}
        onCancel={() => setExportModalOpen(false)}
        footer={<Button onClick={() => setExportModalOpen(false)}>关闭</Button>}
        width={600}
      >
        {exportResult && (
          <div>
            <Space direction="vertical" style={{ width: '100%' }}>
              {exportResult.xlsx_internal && (
                <Button
                  icon={<DownloadOutlined />}
                  onClick={() => handleDownload(
                    projects.find(p => exportingId === p.project_id)?.project_id || '',
                    exportResult!.xlsx_internal!
                  )}
                >
                  下载内部版 xlsx
                </Button>
              )}
              {exportResult.xlsx_release && (
                <Button
                  icon={<DownloadOutlined />}
                  onClick={() => handleDownload(
                    projects.find(p => exportingId === p.project_id)?.project_id || '',
                    exportResult!.xlsx_release!
                  )}
                >
                  下载客户版 xlsx
                </Button>
              )}
              {exportResult.json_path && (
                <Button
                  icon={<DownloadOutlined />}
                  onClick={() => handleDownload(
                    projects.find(p => exportingId === p.project_id)?.project_id || '',
                    exportResult!.json_path!
                  )}
                >
                  下载 cases.json
                </Button>
              )}
            </Space>

            {exportResult.placeholders.length > 0 && (
              <div style={{ marginTop: 16, padding: 12, background: '#fffbe6', borderRadius: 4 }}>
                <strong>⚠️ {exportResult.placeholders.length} 处占位符待补充：</strong>
                <ul style={{ marginTop: 8, paddingLeft: 20 }}>
                  {exportResult.placeholders.slice(0, 10).map((p, i) => (
                    <li key={i}>
                      <code>{p.placeholder}</code>（{p.category} / {p.field}）
                    </li>
                  ))}
                  {exportResult.placeholders.length > 10 && (
                    <li>...还有 {exportResult.placeholders.length - 10} 处</li>
                  )}
                </ul>
              </div>
            )}

            {exportResult.defaults_used.length > 0 && (
              <div style={{ marginTop: 12, padding: 12, background: '#e6f7ff', borderRadius: 4 }}>
                <strong>ℹ️ {exportResult.defaults_used.length} 项默认值请确认：</strong>
                <ul style={{ marginTop: 8, paddingLeft: 20 }}>
                  {exportResult.defaults_used.map((d, i) => (
                    <li key={i}>
                      {d.field}: <strong>{d.default_value}</strong>
                      <span style={{ color: '#888' }}> [{d.source}]</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  )
}
