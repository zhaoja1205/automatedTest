/**
 * SWE.2 架构设计步骤。
 *
 * 基于 SWE.1 需求项生成 SWE.1→SWE.2 映射表（每需求拆到组件行 -A###）。
 * 8 组件属性编辑（型号/I2C 地址/接口）；导出架构 docx + 映射表 xlsx。
 */
import { useState } from 'react'
import {
  Button, Space, Table, Card, Alert, message, Tag, Select, Input, Popconfirm,
} from 'antd'
import {
  RobotOutlined, ExportOutlined, DownloadOutlined, PlusOutlined, DeleteOutlined, ReloadOutlined,
} from '@ant-design/icons'
import { createDefaultAspice, useAspiceStore } from '../../stores/useAspiceStore'
import {
  generateSwe2, exportSwe2, downloadAspiceFile,
} from '../../api/aspiceApi'
import type { ArchMapping, AspiceComponent } from '../../types/aspice'

/** 8 组件 ID 选项（A001~A008） */
const COMPONENT_OPTIONS = [
  { id: 'A001', name: 'Serializer' },
  { id: 'A002', name: 'Deserializer' },
  { id: 'A003', name: 'EEPROM' },
  { id: 'A004', name: 'Camera Module' },
  { id: 'A005', name: 'nvsipl_camera' },
  { id: 'A006', name: 'nvsipl_multicast' },
  { id: 'A007', name: 'PMIC' },
  { id: 'A008', name: 'Camera Security' },
]

export default function Swe2Step() {
  const store = useAspiceStore()
  const { projectId, setMappings, setComponents } = store
  const aspice = store.aspice || createDefaultAspice()
  const [generating, setGenerating] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exportFiles, setExportFiles] = useState<{ docx: string; xlsx: string } | null>(null)

  const mappings = aspice.swe2.mappings || []
  const components = aspice.swe2.components || []
  const swe1Reqs = aspice.swe1.requirements || []

  // 生成映射（规则 + AI）
  const handleGenerate = async (useAi: boolean) => {
    if (!projectId) { message.warning('项目未创建'); return }
    if (swe1Reqs.length === 0) {
      message.warning('请先在 SWE.1 中添加需求项')
      return
    }
    setGenerating(true)
    try {
      const res = await generateSwe2(projectId, useAi)
      const { source, count, mappings: mp, ai_error } = res.data
      setMappings(mp)
      if (source === 'ai') {
        message.success(`AI 生成 ${count} 条映射`)
      } else {
        message.info(`规则生成 ${count} 条映射（AI 未启用或失败）`)
      }
      if (ai_error) message.warning(ai_error)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '生成映射失败')
    } finally {
      setGenerating(false)
    }
  }

  // 导出
  const handleExport = async () => {
    if (!projectId) return
    if (mappings.length === 0) {
      message.warning('请先生成或添加映射')
      return
    }
    setExporting(true)
    try {
      const res = await exportSwe2(projectId)
      setExportFiles(res.data)
      message.success('导出成功')
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '导出失败')
    } finally {
      setExporting(false)
    }
  }

  const handleDownload = async (filename: string) => {
    if (!projectId) return
    try {
      const res = await downloadAspiceFile(projectId, filename)
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      message.error('下载失败')
    }
  }

  // 编辑映射行
  const updateMapping = (idx: number, field: keyof ArchMapping, value: any) => {
    const updated = [...mappings]
    updated[idx] = { ...updated[idx], [field]: value }
    // 若改了 swe1_id 或组件，重新派生 swe2_id
    if (field === 'swe1_id' || field === 'component_id') {
      const comp = COMPONENT_OPTIONS.find(c => c.id === updated[idx].component_id)
      if (comp) updated[idx].component = comp.name
      updated[idx].swe2_id = `${updated[idx].swe1_id}-${updated[idx].component_id}`
    }
    setMappings(updated)
  }
  const deleteMapping = (idx: number) => {
    setMappings(mappings.filter((_, i) => i !== idx))
  }
  const addMapping = () => {
    const firstReq = swe1Reqs[0]
    const swe1Id = firstReq?.req_id || ''
    const compId = 'A004'
    const comp = COMPONENT_OPTIONS.find(c => c.id === compId)!
    setMappings([...mappings, {
      swe1_id: swe1Id,
      swe2_id: `${swe1Id}-${compId}`,
      component_id: compId,
      component: comp.name,
      description: '',
      release_version: 'V1.0',
    }])
  }

  // 编辑组件属性
  const updateComponent = (idx: number, field: keyof AspiceComponent, value: string) => {
    const updated = [...components]
    updated[idx] = { ...updated[idx], [field]: value }
    setComponents(updated)
  }

  const mappingColumns = [
    { title: 'SWE.1 ID', dataIndex: 'swe1_id', key: 'swe1_id', width: 180,
      render: (t: string, _r: ArchMapping, idx: number) => (
        <Select size="small" value={t} style={{ width: 170 }}
          onChange={(v) => updateMapping(idx, 'swe1_id', v)}
          options={swe1Reqs.map(r => ({ value: r.req_id, label: r.req_id }))} />
      ) },
    { title: 'SWE.2 ID', dataIndex: 'swe2_id', key: 'swe2_id', width: 220,
      render: (t: string) => <Tag color="geekblue">{t}</Tag> },
    { title: '组件', dataIndex: 'component_id', key: 'component_id', width: 180,
      render: (t: string, _r: ArchMapping, idx: number) => (
        <Select size="small" value={t} style={{ width: 170 }}
          onChange={(v) => updateMapping(idx, 'component_id', v)}
          options={COMPONENT_OPTIONS.map(c => ({ value: c.id, label: `${c.id} ${c.name}` }))} />
      ) },
    { title: '描述', dataIndex: 'description', key: 'description',
      render: (t: string, _r: ArchMapping, idx: number) => (
        <Input size="small" value={t} onChange={(e) => updateMapping(idx, 'description', e.target.value)} />
      ) },
    { title: '发布版本', dataIndex: 'release_version', key: 'release_version', width: 100,
      render: (t: string, _r: ArchMapping, idx: number) => (
        <Input size="small" value={t} onChange={(e) => updateMapping(idx, 'release_version', e.target.value)} />
      ) },
    { title: '操作', key: 'actions', width: 60,
      render: (_: unknown, _r: ArchMapping, idx: number) => (
        <Popconfirm title="删除此映射？" onConfirm={() => deleteMapping(idx)}>
          <Button type="link" size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ) },
  ]

  return (
    <div style={{ maxWidth: 1200 }}>
      <Alert
        type="info" showIcon style={{ marginBottom: 16 }}
        message="SWE.2 软件架构设计"
        description="基于 SWE.1 需求项自动生成架构映射表（每需求拆到关联组件行，SWE.2 ID 自动派生：{SWE.1}-A###）。支持 AI 增强（调整组件归属 + 补接口描述）。"
      />

      {/* 映射表 */}
      <Card size="small" title={`SWE.1 → SWE.2 映射表 (${mappings.length})`} style={{ marginBottom: 16 }}
        extra={
          <Space>
            <Button size="small" icon={<PlusOutlined />} onClick={addMapping}>添加</Button>
            <Button size="small" icon={<ReloadOutlined />} loading={generating}
              onClick={() => handleGenerate(false)}>
              规则生成
            </Button>
            <Button size="small" type="primary" icon={<RobotOutlined />} loading={generating}
              onClick={() => handleGenerate(true)}>
              AI 生成映射
            </Button>
            <Button size="small" icon={<ExportOutlined />} loading={exporting} onClick={handleExport}>
              导出架构文档
            </Button>
          </Space>
        }>
        {swe1Reqs.length === 0 && (
          <Alert type="warning" showIcon style={{ marginBottom: 12 }}
            message="SWE.1 中暂无需求项，请先切换到 SWE.1 添加需求并保存" />
        )}
        <Table
          rowKey={(_, idx) => String(idx)}
          columns={mappingColumns}
          dataSource={mappings}
          pagination={mappings.length > 15 ? { pageSize: 15 } : false}
          size="small"
          scroll={{ x: 800 }}
        />
      </Card>

      {/* 导出文件 */}
      {exportFiles && (
        <Card size="small" title="导出文件" style={{ marginBottom: 16 }}>
          <Space>
            <Button icon={<DownloadOutlined />} onClick={() => handleDownload(exportFiles.docx)}>
              {exportFiles.docx}
            </Button>
            <Button icon={<DownloadOutlined />} onClick={() => handleDownload(exportFiles.xlsx)}>
              {exportFiles.xlsx}
            </Button>
          </Space>
        </Card>
      )}

      {/* 8 组件属性 */}
      <Card size="small" title={`组件属性 (${components.length})`} style={{ marginBottom: 16 }}>
        <Alert type="info" showIcon style={{ marginBottom: 12 }}
          message="8 组件固定架构（NVIDIA Drive-OS NvSIPL 框架）"
          description="A001 Serializer / A002 Deserializer / A003 EEPROM / A004 Camera Module / A005 nvsipl_camera / A006 nvsipl_multicast / A007 PMIC / A008 Camera Security"
        />
        <Table
          rowKey="id"
          dataSource={components}
          pagination={false}
          size="small"
          scroll={{ x: 600 }}
          columns={[
            { title: 'ID', dataIndex: 'id', key: 'id', width: 70,
              render: (t: string) => <Tag color="purple">{t}</Tag> },
            { title: '组件名', dataIndex: 'name', key: 'name', width: 150 },
            { title: '型号', dataIndex: 'model', key: 'model', width: 160,
              render: (t: string, _r: AspiceComponent, idx: number) => (
                <Input size="small" value={t} placeholder="如 MAX96717F"
                  onChange={(e) => updateComponent(idx, 'model', e.target.value)} />
              ) },
            { title: 'I2C 地址', dataIndex: 'i2c_addr', key: 'i2c_addr', width: 120,
              render: (t: string, _r: AspiceComponent, idx: number) => (
                <Input size="small" value={t} placeholder="如 0x40"
                  onChange={(e) => updateComponent(idx, 'i2c_addr', e.target.value)} />
              ) },
            { title: '接口说明', key: 'interface', render: () => <span style={{ color: '#999', fontSize: 12 }}>见架构文档</span> },
          ]}
        />
      </Card>
    </div>
  )
}
