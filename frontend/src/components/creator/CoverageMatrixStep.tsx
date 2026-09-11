/**
 * 步骤 2：覆盖矩阵编辑。
 *
 * 模组 × 功能 的交叉 Checkbox 表格。
 * 用户通过硬件拓扑生成模组行，并动态增删功能（列）。
 */
import { useState } from 'react'
import { Table, Checkbox, Button, Input, Space, Popconfirm, Card, message, Alert, Modal, Switch, Select } from 'antd'
import { PlusOutlined, DeleteOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useCreatorStore } from '../../stores/useCreatorStore'
import { generateCreatorCases, getCreatorProject, updateCreatorProject } from '../../api/creatorApi'
import type { CoverageTopologyItem } from '../../types/creator'

const DEFAULT_FEATURES = ['起流', '出图', '帧率', '帧同步', 'AE调节', '内参读取', 'metadata', '故障注入']
const GROUP_OPTIONS = ['group-A', 'group-B', 'group-C', 'group-D', 'group-E']
const LINK_OPTIONS = ['Link A', 'Link B', 'Link C', 'Link D']

const EXAMPLE_TOPOLOGY: CoverageTopologyItem[] = [
  { group: 'group-A', decoder_model: 'MAX96712', i2c_bus: 'I2C7', power_addr: '0x28(7bit)', decoder_addr: '0x2D(7bit)', bypass_addr: '0x40(7bit)', camera: '前视远距FOV30', adr_name: '0x1a(7bit)', sensor_id: '3', link: 'Link D' },
  { group: 'group-A', decoder_model: 'MAX96712', i2c_bus: 'I2C7', power_addr: '0x28(7bit)', decoder_addr: '0x2D(7bit)', bypass_addr: '0x40(7bit)', camera: '前视广角FOV120', adr_name: '0x1b(7bit)', sensor_id: '2', link: 'Link C' },
  { group: 'group-A', decoder_model: 'MAX96712', i2c_bus: 'I2C7', power_addr: '0x28(7bit)', decoder_addr: '0x2D(7bit)', bypass_addr: '0x40(7bit)', camera: '后视远距FOV60', adr_name: '0x1c(7bit)', sensor_id: '0', link: 'Link A' },
  { group: 'group-C', decoder_model: 'max96724F', i2c_bus: 'I2C12', power_addr: '0x28(7bit)', decoder_addr: '0x27(7bit)', bypass_addr: '/', camera: 'LSCF_LVDS_左前', adr_name: '0x1d(7bit)', sensor_id: '11', link: 'Link D' },
  { group: 'group-C', decoder_model: 'max96724F', i2c_bus: 'I2C12', power_addr: '0x28(7bit)', decoder_addr: '0x27(7bit)', bypass_addr: '/', camera: 'LSCR_LVDS_左后', adr_name: '0x1e(7bit)', sensor_id: '10', link: 'Link C' },
  { group: 'group-C', decoder_model: 'max96724F', i2c_bus: 'I2C12', power_addr: '0x28(7bit)', decoder_addr: '0x27(7bit)', bypass_addr: '/', camera: 'RSCR_LVDS_右后', adr_name: '0x1f(7bit)', sensor_id: '8', link: 'Link A' },
  { group: 'group-C', decoder_model: 'max96724F', i2c_bus: 'I2C12', power_addr: '0x28(7bit)', decoder_addr: '0x27(7bit)', bypass_addr: '/', camera: 'RSCF_LVDS_右前', adr_name: '0x20(7bit)', sensor_id: '9', link: 'Link B' },
  { group: 'group-D', decoder_model: 'max96792A', i2c_bus: 'I2C1', power_addr: '/', decoder_addr: '0x4c(7bit)', bypass_addr: '0x40(7bit)', camera: 'RSVC_LVDS 右', adr_name: '0x21(7bit)', sensor_id: '15', link: 'Link A' },
  { group: 'group-D', decoder_model: 'max96792A', i2c_bus: 'I2C1', power_addr: '/', decoder_addr: '0x4c(7bit)', bypass_addr: '0x40(7bit)', camera: 'LSVC_LVDS 左', adr_name: '0x22(7bit)', sensor_id: '14', link: 'Link A' },
  { group: 'group-D', decoder_model: 'max96792A', i2c_bus: 'I2C1', power_addr: '/', decoder_addr: '0x4c(7bit)', bypass_addr: '0x40(7bit)', camera: 'FSVC_LVDS 前', adr_name: '0x23(7bit)', sensor_id: '12', link: 'Link A' },
  { group: 'group-D', decoder_model: 'max96792A', i2c_bus: 'I2C1', power_addr: '/', decoder_addr: '0x4c(7bit)', bypass_addr: '0x40(7bit)', camera: 'BSVC_LVDS 后', adr_name: '0x24(7bit)', sensor_id: '13', link: 'Link A' },
]

export default function CoverageMatrixStep() {
  const navigate = useNavigate()
  const store = useCreatorStore()
  const { currentProject, updateMatrix } = store
  const matrix = currentProject?.coverage_matrix || { modules: [], features: [], matrix: [], topology: [] }
  const topology = matrix.topology || []

  const [newFeature, setNewFeature] = useState('')
  const [generateModalOpen, setGenerateModalOpen] = useState(false)
  const [overwrite, setOverwrite] = useState(false)
  const [useAI, setUseAI] = useState(false)
  const [generating, setGenerating] = useState(false)

  const topologyModules = (items: CoverageTopologyItem[]) => Array.from(new Set(
    items.map(t => t.camera?.trim()).filter((name): name is string => Boolean(name))
  ))

  const rebuildMatrixByTopology = (items: CoverageTopologyItem[], features = matrix.features, oldModules = matrix.modules, oldMatrix = matrix.matrix) => {
    const modules = topologyModules(items)
    const newMatrixData = modules.map((module) => {
      const oldIdx = oldModules.indexOf(module)
      return features.map((_, colIdx) => oldIdx >= 0 ? (oldMatrix[oldIdx]?.[colIdx] ?? true) : true)
    })
    return { modules, matrix: newMatrixData }
  }

  // 添加功能（列）
  const addFeature = () => {
    const name = newFeature.trim()
    if (!name) { message.warning('请输入功能名称'); return }
    if (matrix.features.includes(name)) { message.warning('功能已存在'); return }
    const newFeatures = [...matrix.features, name]
    const synced = rebuildMatrixByTopology(topology, newFeatures)
    updateMatrix({ ...matrix, features: newFeatures, modules: synced.modules, matrix: synced.matrix })
    setNewFeature('')
  }

  // 删除功能
  const removeFeature = (idx: number) => {
    const newFeatures = matrix.features.filter((_, i) => i !== idx)
    const synced = rebuildMatrixByTopology(topology, newFeatures)
    updateMatrix({ ...matrix, features: newFeatures, modules: synced.modules, matrix: synced.matrix })
  }

  // 切换 Checkbox
  const toggleCell = (row: number, col: number) => {
    const newMatrixData = matrix.matrix.map((r, ri) =>
      ri === row ? r.map((c, ci) => ci === col ? !c : c) : [...r]
    )
    updateMatrix({ ...matrix, matrix: newMatrixData })
  }

  // 一键使用默认功能列表
  const useDefaults = () => {
    if (matrix.features.length > 0) {
      message.info('已有功能列表，请手动添加')
      return
    }
    const synced = rebuildMatrixByTopology(topology, DEFAULT_FEATURES)
    updateMatrix({ ...matrix, features: DEFAULT_FEATURES, modules: synced.modules, matrix: synced.matrix })
  }

  // 添加硬件拓扑行
  const addTopologyRow = () => {
    const next: CoverageTopologyItem = {
      group: 'group-A',
      decoder_model: '',
      i2c_bus: '',
      power_addr: '',
      decoder_addr: '',
      bypass_addr: '',
      camera: '',
      adr_name: '',
      sensor_id: '',
      link: 'Link A',
      mask_bit: '0x1',
    }
    const nextTopology = [...topology, next]
    const synced = rebuildMatrixByTopology(nextTopology)
    updateMatrix({ ...matrix, topology: nextTopology, modules: synced.modules, matrix: synced.matrix })
  }

  const updateTopologyRow = (idx: number, patch: Partial<CoverageTopologyItem>) => {
    const next = topology.map((row, i) => i === idx ? { ...row, ...patch } : row)
    const synced = rebuildMatrixByTopology(next)
    updateMatrix({ ...matrix, topology: next, modules: synced.modules, matrix: synced.matrix })
  }

  const removeTopologyRow = (idx: number) => {
    const next = topology.filter((_, i) => i !== idx)
    const synced = rebuildMatrixByTopology(next)
    updateMatrix({ ...matrix, topology: next, modules: synced.modules, matrix: synced.matrix })
  }

  const useTopologyExample = () => {
    const synced = rebuildMatrixByTopology(EXAMPLE_TOPOLOGY)
    updateMatrix({ ...matrix, topology: EXAMPLE_TOPOLOGY, modules: synced.modules, matrix: synced.matrix })
    message.success(`已填入示例拓扑，并同步 ${synced.modules.length} 个模组到覆盖矩阵`)
  }

  // 将拓扑中的模组型号同步为覆盖矩阵行
  const syncModulesFromTopology = () => {
    const synced = rebuildMatrixByTopology(topology)
    if (synced.modules.length === 0) {
      message.warning('请先填写拓扑表中的模组型号')
      return
    }
    updateMatrix({ ...matrix, modules: synced.modules, matrix: synced.matrix })
    message.success(`已同步 ${synced.modules.length} 个模组到覆盖矩阵`)
  }

  // 按矩阵生成用例
  const handleGenerate = async () => {
    if (!currentProject) {
      message.warning('请先创建项目')
      return
    }
    setGenerating(true)
    try {
      // 生成前强制按拓扑刷新矩阵行，避免 mask 拓扑与覆盖矩阵脱节
      const synced = rebuildMatrixByTopology(topology)
      const syncedMatrix = { ...matrix, modules: synced.modules, matrix: synced.matrix }

      // 先保存当前矩阵，避免后端读取到旧的 project.json
      await updateCreatorProject(currentProject.project_id, {
        coverage_matrix: syncedMatrix,
        meta: currentProject.meta,
        functional_cases: currentProject.functional_cases,
        fault_cases: currentProject.fault_cases,
        defaults_used: currentProject.defaults_used,
        current_step: 1,
      })

      const res = await generateCreatorCases(currentProject.project_id, {
        overwrite,
        use_ai: useAI,
        category: null,
      })
      const data = res.data
      const refreshed = await getCreatorProject(currentProject.project_id)
      store.setCurrentProject({ ...refreshed.data, current_step: 2 })
      setGenerateModalOpen(false)

      const sourceText = data.source === 'ai' ? 'AI 增强' : '规则模板'
      if (data.ai_error) {
        message.warning(`已降级为规则模板生成 ${data.count} 条用例：${data.ai_error}`)
      } else {
        message.success(`已通过${sourceText}生成 ${data.count} 条用例`)
      }
    } catch (err) {
      console.error(err)
      message.error('生成用例失败')
    } finally {
      setGenerating(false)
    }
  }

  const topologyColumns = [
    {
      title: 'GROUP',
      dataIndex: 'group',
      key: 'group',
      width: 120,
      render: (value: string, _: unknown, idx: number) => (
        <Select value={value} style={{ width: 110 }} onChange={(v) => updateTopologyRow(idx, { group: v })}>
          {GROUP_OPTIONS.map(g => <Select.Option key={g} value={g}>{g}</Select.Option>)}
        </Select>
      ),
    },
    {
      title: '模组型号',
      dataIndex: 'camera',
      key: 'camera',
      width: 180,
      render: (value: string, _: unknown, idx: number) => (
        <Input value={value} placeholder="FOV30 / IMX728" onChange={(e) => updateTopologyRow(idx, { camera: e.target.value })} />
      ),
    },
    {
      title: '解串器型号',
      dataIndex: 'decoder_model',
      key: 'decoder_model',
      width: 130,
      render: (value: string, _: unknown, idx: number) => (
        <Input value={value} placeholder="MAX96712" onChange={(e) => updateTopologyRow(idx, { decoder_model: e.target.value })} />
      ),
    },
    {
      title: 'I2C总线',
      dataIndex: 'i2c_bus',
      key: 'i2c_bus',
      width: 110,
      render: (value: string, _: unknown, idx: number) => (
        <Input value={value} placeholder="I2C7" onChange={(e) => updateTopologyRow(idx, { i2c_bus: e.target.value })} />
      ),
    },
    {
      title: '电源芯片地址',
      dataIndex: 'power_addr',
      key: 'power_addr',
      width: 130,
      render: (value: string, _: unknown, idx: number) => (
        <Input value={value} placeholder="0x28(7bit)" onChange={(e) => updateTopologyRow(idx, { power_addr: e.target.value })} />
      ),
    },
    {
      title: '解串器地址',
      dataIndex: 'decoder_addr',
      key: 'decoder_addr',
      width: 120,
      render: (value: string, _: unknown, idx: number) => (
        <Input value={value} placeholder="0x2D(7bit)" onChange={(e) => updateTopologyRow(idx, { decoder_addr: e.target.value })} />
      ),
    },
    {
      title: '加串器地址',
      dataIndex: 'bypass_addr',
      key: 'bypass_addr',
      width: 140,
      render: (value: string, _: unknown, idx: number) => (
        <Input value={value} placeholder="0x40(7bit)" onChange={(e) => updateTopologyRow(idx, { bypass_addr: e.target.value })} />
      ),
    },
    {
      title: 'sensor地址(I2C)',
      dataIndex: 'adr_name',
      key: 'adr_name',
      width: 190,
      render: (value: string, _: unknown, idx: number) => (
        <Input value={value} placeholder="0x1a(7bit)" onChange={(e) => updateTopologyRow(idx, { adr_name: e.target.value })} />
      ),
    },
    {
      title: 'sensor-id',
      dataIndex: 'sensor_id',
      key: 'sensor_id',
      width: 100,
      render: (value: string, _: unknown, idx: number) => (
        <Input value={value} placeholder="3" onChange={(e) => updateTopologyRow(idx, { sensor_id: e.target.value })} />
      ),
    },
    {
      title: 'LINK',
      dataIndex: 'link',
      key: 'link',
      width: 110,
      render: (value: string, _: unknown, idx: number) => (
        <Select value={value} style={{ width: 100 }} onChange={(v) => updateTopologyRow(idx, { link: v })}>
          {LINK_OPTIONS.map(l => <Select.Option key={l} value={l}>{l}</Select.Option>)}
        </Select>
      ),
    },
    {
      title: 'mask位',
      dataIndex: 'mask_bit',
      key: 'mask_bit',
      width: 120,
      render: (value: string, _: unknown, idx: number) => (
        <Select value={value || ''} style={{ width: 110 }} onChange={(v) => updateTopologyRow(idx, { mask_bit: v })}>
          <Select.Option value="0x1">0x1</Select.Option>
          <Select.Option value="0x10">0x10</Select.Option>
          <Select.Option value="0x100">0x100</Select.Option>
          <Select.Option value="0x1000">0x1000</Select.Option>
        </Select>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 70,
      render: (_: unknown, __: unknown, idx: number) => (
        <Popconfirm title="删除此拓扑行？" onConfirm={() => removeTopologyRow(idx)}>
          <Button type="link" size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ),
    },
  ]

  // 构建 Table columns
  const columns = [
    {
      title: '模组型号（来自拓扑）',
      dataIndex: 'module',
      key: 'module',
      fixed: 'left' as const,
      width: 190,
      render: (name: string) => <strong>{name}</strong>,
    },
    ...matrix.features.map((feat, colIdx) => ({
      title: (
        <Space size={4}>
          <span>{feat}</span>
          <Popconfirm title="删除此功能列？" onConfirm={() => removeFeature(colIdx)}>
            <DeleteOutlined style={{ color: '#999', cursor: 'pointer', fontSize: 10 }} />
          </Popconfirm>
        </Space>
      ),
      key: `feat-${colIdx}`,
      width: 100,
      align: 'center' as const,
      render: (_: unknown, __: unknown, rowIdx: number) => (
        <Checkbox
          checked={matrix.matrix[rowIdx]?.[colIdx] ?? false}
          onChange={() => toggleCell(rowIdx, colIdx)}
        />
      ),
    })),
  ]

  const dataSource = matrix.modules.map((mod, idx) => ({ key: idx, module: mod }))

  // 统计
  const totalChecked = matrix.matrix.flat().filter(Boolean).length
  const totalCells = matrix.modules.length * matrix.features.length

  return (
    <div>
      <Card title="🔌 硬件拓扑 / Mask 对应关系" size="small" style={{ marginBottom: 16 }}>
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="用于精确计算 -m 四段 mask"
          description={'先按项目实际填写 Group、模组型号、Link、sensor I2C地址、sensor-id、I2C 总线等；覆盖矩阵的模组行会自动来自这里的「模组型号」。生成用例时会按同一模组型号聚合所在的 Group/Link，例如可生成 -m "0x1111 0 0x1111 0x1111" 这类组合。'}
        />
        <Space style={{ marginBottom: 12 }} wrap>
          <Button icon={<PlusOutlined />} onClick={addTopologyRow}>添加拓扑行</Button>
          <Button onClick={useTopologyExample}>填入示例拓扑</Button>
          <Button type="dashed" onClick={syncModulesFromTopology}>从拓扑同步模组到矩阵</Button>
          <span style={{ color: '#888' }}>共 {topology.length} 条 Link 映射</span>
        </Space>
        <Table
          rowKey={(_, idx) => String(idx)}
          columns={topologyColumns}
          dataSource={topology}
          pagination={false}
          bordered
          size="small"
          scroll={{ x: 1600 }}
          locale={{ emptyText: '可手动添加，或点击「填入示例拓扑」后按项目修改' }}
        />
      </Card>

      <Card title="📊 覆盖矩阵" size="small" style={{ marginBottom: 16 }}>
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="勾选 = 该模组需要测试该功能"
          description="配置完成后可点击「按矩阵生成用例」，系统会生成符合执行侧 Excel/ExpectedResultParser 规范的用例骨架；预期结果会包含 .raw、30fps、无报错等可判定观测点。"
        />

        {/* 添加功能，模组行由上方硬件拓扑自动生成 */}
        <Space style={{ marginBottom: 16 }} wrap>
          <span style={{ color: '#888' }}>模组行来自上方拓扑表的「模组型号」</span>
          <div style={{ width: 1, height: 24, background: '#ddd' }} />
          <Input
            placeholder="功能名称（如 起流）"
            value={newFeature}
            onChange={(e) => setNewFeature(e.target.value)}
            onPressEnter={addFeature}
            style={{ width: 200 }}
          />
          <Button icon={<PlusOutlined />} onClick={addFeature}>添加功能</Button>
          {matrix.features.length === 0 && (
            <Button type="dashed" onClick={useDefaults}>使用默认功能列表</Button>
          )}
        </Space>

        {/* 矩阵表 */}
        {matrix.modules.length > 0 && matrix.features.length > 0 ? (
          <>
            <Table
              columns={columns}
              dataSource={dataSource}
              pagination={false}
              bordered
              size="small"
              scroll={{ x: 190 + matrix.features.length * 100 }}
            />
            <div style={{ marginTop: 8, color: '#888' }}>
              覆盖率：{totalChecked} / {totalCells}（{totalCells > 0 ? Math.round(totalChecked / totalCells * 100) : 0}%）
            </div>
            <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid #f0f0f0' }}>
              <Space>
                <Button
                  type="primary"
                  icon={<ThunderboltOutlined />}
                  disabled={totalChecked === 0}
                  onClick={() => setGenerateModalOpen(true)}
                >
                  按矩阵生成用例
                </Button>
                <span style={{ color: '#888' }}>
                  将从 {matrix.modules.length} 个模组 × {matrix.features.length} 个功能中生成 {totalChecked} 条用例
                </span>
              </Space>
            </div>
          </>
        ) : (
          <div style={{ padding: 32, textAlign: 'center', color: '#999' }}>
            请先在上方拓扑表填写模组型号，并添加功能后再配置覆盖关系
          </div>
        )}
      </Card>

      <Modal
        title="按覆盖矩阵生成用例"
        open={generateModalOpen}
        onOk={handleGenerate}
        onCancel={() => setGenerateModalOpen(false)}
        confirmLoading={generating}
        okText="开始生成"
        cancelText="取消"
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Alert
            type="info"
            showIcon
            message={`将生成 ${totalChecked} 条用例`}
            description={`来源：${matrix.modules.length} 个模组 × ${matrix.features.length} 个功能。生成后会自动跳转到「用例编辑」步骤。`}
          />

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <strong>覆盖已有用例</strong>
              <div style={{ color: '#888', fontSize: 12 }}>
                关闭时为追加生成；开启时会替换当前功能/故障用例列表
              </div>
            </div>
            <Switch checked={overwrite} onChange={setOverwrite} />
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <strong>启用 AI 增强</strong>
              <div style={{ color: '#888', fontSize: 12 }}>
                默认关闭；启用后会先尝试 AI 生成，失败自动降级为规则模板。
                <a onClick={() => navigate('/config/ai')}> 去配置 AI</a>
              </div>
            </div>
            <Switch checked={useAI} onChange={setUseAI} />
          </div>
        </Space>
      </Modal>
    </div>
  )
}
