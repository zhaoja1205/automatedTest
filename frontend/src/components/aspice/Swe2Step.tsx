/**
 * SWE.2 架构设计步骤。
 *
 * 基于 SWE.1 需求项生成 SWE.1→SWE.2 映射表（每需求拆到组件行 -A###）。
 * 8 组件属性编辑（型号/I2C 地址/接口）；导出架构 docx + 映射表 xlsx。
 */
import { useState } from 'react'
import {
  Button, Space, Table, Card, Alert, message, Tag, Select, Input, Popconfirm, Upload, Collapse,
} from 'antd'
import {
  RobotOutlined, ExportOutlined, DownloadOutlined, PlusOutlined, DeleteOutlined, ReloadOutlined, ImportOutlined,
  FileTextOutlined, CloudUploadOutlined, AppstoreOutlined,
} from '@ant-design/icons'
import { createDefaultAspice, useAspiceStore } from '../../stores/useAspiceStore'
import {
  generateSwe2, exportSwe2, downloadAspiceFile, importSwe2,
} from '../../api/aspiceApi'
import type {
  ArchMapping, AspiceComponent, Swe2Overview,
  Swe2SoftwareDesign, Swe2Resources,
} from '../../types/aspice'
import OverviewEditor from './swe2/OverviewEditor'
import SoftwareDesignEditor from './swe2/SoftwareDesignEditor'
import ResourcesEditor from './swe2/ResourcesEditor'
import ModuleEditor from './swe2/ModuleEditor'
import EngineeringScanner from './swe3/EngineeringScanner'
import EngineeringUploadPanel from './swe3/EngineeringUploadPanel'

/** §6 备选架构默认文案（和后端 DEFAULT_ALTERNATIVE_ARCH 保持一致）。 */
const DEFAULT_ALTERNATIVE_ARCH = '暂不涉及，目前仅在 NV 框架上实现。'

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
  const {
    projectId, setMappings, setComponents, setOverview,
    setSwe2SoftwareDesign, setSwe2Resources, setSwe2AlternativeArch,
  } = store
  const aspice = store.aspice || createDefaultAspice()
  const [generating, setGenerating] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)
  const [exportFiles, setExportFiles] = useState<{ docx: string; xlsx: string } | null>(null)

  const mappings = aspice.swe2.mappings || []
  const components = aspice.swe2.components || []
  const swe1Reqs = aspice.swe1.requirements || []
  // 推送 A：概述元数据（1.3 术语 / 1.4 参考文档 / 1.5 假设及依赖）
  const overview: Swe2Overview = aspice.swe2.overview || {
    purpose: '', scope: '', terms: [], ref_docs: [], assumptions: [], project_assumptions: [],
  }
  const overviewCount =
    (overview.terms?.length || 0) +
    (overview.ref_docs?.length || 0) +
    (overview.assumptions?.length || 0) +
    (overview.project_assumptions?.length || 0)

  // Phase 4 Group 2 新增字段
  const softwareDesign: Swe2SoftwareDesign | undefined = aspice.swe2.software_design
  const sdCount =
    (softwareDesign?.external_interfaces?.length || 0) +
    (softwareDesign?.internal_interfaces?.length || 0) +
    (softwareDesign?.config_files?.sensors?.length || 0) +
    (softwareDesign?.state_diagrams?.length || 0) +
    (softwareDesign?.sequence_diagrams?.length || 0)
  const resources: Swe2Resources | undefined = aspice.swe2.resources
  const resourcesCount = resources?.items?.length || 0
  const alternativeArch: string = aspice.swe2.alternative_arch ?? ''

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
  // 注：不再以 mappings 是否为空为前置拦截 —— §2 需求映射只是 SWE.2 的
  // 其中一章，§3 软件设计 / §4 模块设计 / §5 资源 / §6 备选架构 / §7 集成
  // 都可能是用户本次只想导的内容；后端生成器对空 mappings 已经容错，
  // 导出的 docx 对应章节就是空白表格 + 默认提示段，不会炸。
  const handleExport = async () => {
    if (!projectId) return
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

  const handleImport = async (file: File) => {
    if (!projectId) {
      message.warning('项目未创建')
      return
    }
    setImporting(true)
    try {
      const res = await importSwe2(projectId, file)
      setMappings(res.data.mappings)
      setComponents(res.data.components)
      message.success(`回灌完成：${res.data.count} 条映射，${res.data.component_count} 个组件属性`)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || 'SWE.2 回灌失败')
    } finally {
      setImporting(false)
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

      {/* 工程代码（与 SWE.3 共享）—— §3.3.3 config database 扫描、§4 组件接口推导都要吃这棵树 */}
      <Collapse
        size="small"
        style={{ marginBottom: 16 }}
        items={[{
          key: 'engineering',
          label: (
            <Space>
              <CloudUploadOutlined />
              <span>工程代码（与 SWE.3 共享 engineering_src/）</span>
              <Tag color="blue">§3.3.3 / §4 共用</Tag>
            </Space>
          ),
          children: projectId ? (
            <Space direction="vertical" size={16} style={{ width: '100%' }}>
              <Alert type="info" showIcon
                message="与 SWE.3 共享同一棵工程树"
                description="优先使用浏览器直接选目录（含 .git 用来做基线 diff）；无 .git 或旧浏览器时走退路 zip 上传。此目录同时供 §3.3.3 config database 扫描 和 §4 组件接口/场景生成。" />
              <EngineeringScanner projectId={projectId} onDone={() => { /* 由 store 自动刷新 */ }} />
              <Collapse size="small" items={[{
                key: 'zip-fallback',
                label: '🗜 退路方式：直接上传 .zip（旧浏览器 / 无 .git 时）',
                children: <EngineeringUploadPanel />,
              }]} />
            </Space>
          ) : (
            <Alert type="info" message="项目加载中…" />
          ),
        }]}
      />

      {/* 推送 A：概述元数据折叠区 */}
      <Collapse
        size="small"
        style={{ marginBottom: 16 }}
        items={[{
          key: 'overview',
          label: (
            <Space>
              <FileTextOutlined />
              <span>概述元数据（1.3 术语 / 1.4 参考文档 / 1.5 假设及依赖）</span>
              <Tag color={overviewCount ? 'green' : 'default'}>
                {overviewCount ? `已填 ${overviewCount} 项` : '未填充'}
              </Tag>
            </Space>
          ),
          children: (
            <OverviewEditor overview={overview} onChange={setOverview} />
          ),
        }]}
      />

      {/* 映射表 */}
      <Card size="small" title={`SWE.1 → SWE.2 映射表 (${mappings.length})`} style={{ marginBottom: 16 }}
        extra={
          <Space>
            <Upload
              accept=".xlsx,.xls,.docx"
              showUploadList={false}
              beforeUpload={(file) => {
                handleImport(file)
                return false
              }}
            >
              <Button size="small" icon={<ImportOutlined />} loading={importing}>
                导入回灌
              </Button>
            </Upload>
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

      {/* §3 → §4 → §5 → §6 按 PreDev 文档顺序排版 */}
      <Collapse
        size="small"
        style={{ marginBottom: 16 }}
        items={[
          {
            key: 'software_design',
            label: (
              <Space>
                <FileTextOutlined />
                <span>§3 软件设计（3.1 简介 / 3.2 模块图 / 3.3.1-3 接口+配置 / 3.4 图）</span>
                <Tag color={sdCount ? 'green' : 'default'}>
                  {sdCount ? `已填 ${sdCount} 项` : '未填充'}
                </Tag>
              </Space>
            ),
            children: (
              <SoftwareDesignEditor
                value={softwareDesign}
                onChange={setSwe2SoftwareDesign}
              />
            ),
          },
          {
            key: 'components',
            label: (
              <Space>
                <AppstoreOutlined />
                <span>§4 组件详细设计（8 模块，每模块一面板）</span>
                <Tag color="purple">{components.length} 模块</Tag>
              </Space>
            ),
            children: (
              <>
                <Alert type="info" showIcon style={{ marginBottom: 12 }}
                  message="8 组件固定架构（NVIDIA Drive-OS NvSIPL 框架，PreDev 口径）"
                  description="A001 Serializer / A002 Deserializer / A003 EEPROM / A004 Camera Module / A005 nvsipl_camera / A006 nvsipl_multicast / A007 PMIC / A008 Camera Security（manual_only）。工程代码请在顶部『工程代码（与 SWE.3 共享）』面板上传。"
                />
                <Collapse size="small" accordion
                  items={components.map((comp, idx) => {
                    const contentCount =
                      (comp.external_interfaces?.length || 0) +
                      (comp.internal_interfaces?.length || 0) +
                      (comp.scenarios?.length || 0) +
                      (comp.classes?.length || 0) +
                      (comp.function_desc_segments?.length || 0) +
                      ((comp.function_desc || '').trim() ? 1 : 0)
                    return {
                      key: comp.id,
                      label: (
                        <Space wrap>
                          <Tag color="purple">{comp.id}</Tag>
                          <span style={{ fontWeight: 500 }}>{comp.name}</span>
                          {comp.id === 'A008' && <Tag color="orange">manual_only</Tag>}
                          <span style={{ color: '#999', fontSize: 12 }}>
                            型号 <Input size="small" value={comp.model || ''} style={{ width: 160 }}
                              placeholder="如 MAX96717F"
                              onClick={(e) => e.stopPropagation()}
                              onChange={(e) => updateComponent(idx, 'model', e.target.value)} />
                            &nbsp;&nbsp;I2C <Input size="small" value={comp.i2c_addr || ''} style={{ width: 90 }}
                              placeholder="0x40"
                              onClick={(e) => e.stopPropagation()}
                              onChange={(e) => updateComponent(idx, 'i2c_addr', e.target.value)} />
                          </span>
                          <Tag color={contentCount ? 'green' : 'default'}>
                            {contentCount ? `已填 ${contentCount} 项` : '未填充'}
                          </Tag>
                        </Space>
                      ),
                      children: (
                        <ModuleEditor
                          component={comp}
                          reqIds={mappings.map((m) => m.swe2_id)}
                          onChange={(v) => {
                            const next = [...components]
                            next[idx] = v
                            setComponents(next)
                          }}
                        />
                      ),
                    }
                  })} />
              </>
            ),
          },
          {
            key: 'resources',
            label: (
              <Space>
                <FileTextOutlined />
                <span>§5 资源消耗（5.1 内存 / 5.2 CPU）</span>
                <Tag color={resourcesCount ? 'green' : 'default'}>
                  {resourcesCount ? `${resourcesCount} 条 KPI` : '未填充'}
                </Tag>
              </Space>
            ),
            children: (
              <ResourcesEditor
                value={resources}
                onChange={setSwe2Resources}
              />
            ),
          },
          {
            key: 'alternative_arch',
            label: (
              <Space>
                <FileTextOutlined />
                <span>§6 备选架构</span>
                <Tag color={alternativeArch && alternativeArch !== DEFAULT_ALTERNATIVE_ARCH ? 'green' : 'default'}>
                  {alternativeArch ? '已填写' : '走默认'}
                </Tag>
              </Space>
            ),
            children: (
              <>
                <Alert type="info" showIcon style={{ marginBottom: 8 }}
                  message="PreDev 默认文案"
                  description={DEFAULT_ALTERNATIVE_ARCH} />
                <Input.TextArea rows={3} value={alternativeArch}
                  placeholder={DEFAULT_ALTERNATIVE_ARCH}
                  onChange={(e) => setSwe2AlternativeArch(e.target.value)} />
              </>
            ),
          },
        ]}
      />

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
    </div>
  )
}
