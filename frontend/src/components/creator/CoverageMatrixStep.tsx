/**
 * 步骤 2：覆盖矩阵编辑。
 *
 * 模组 × 功能 的交叉 Checkbox 表格。
 * 用户可动态增删模组（行）和功能（列）。
 */
import { useState } from 'react'
import { Table, Checkbox, Button, Input, Space, Popconfirm, Card, message, Alert, Modal, Switch } from 'antd'
import { PlusOutlined, DeleteOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useCreatorStore } from '../../stores/useCreatorStore'
import { generateCreatorCases, getCreatorProject, updateCreatorProject } from '../../api/creatorApi'

const DEFAULT_FEATURES = ['起流', '出图', '帧率', '帧同步', 'AE调节', '内参读取', 'metadata', '故障注入']

export default function CoverageMatrixStep() {
  const navigate = useNavigate()
  const store = useCreatorStore()
  const { currentProject, updateMatrix } = store
  const matrix = currentProject?.coverage_matrix || { modules: [], features: [], matrix: [] }

  const [newModule, setNewModule] = useState('')
  const [newFeature, setNewFeature] = useState('')
  const [generateModalOpen, setGenerateModalOpen] = useState(false)
  const [overwrite, setOverwrite] = useState(false)
  const [useAI, setUseAI] = useState(false)
  const [generating, setGenerating] = useState(false)

  // 添加模组（行）
  const addModule = () => {
    const name = newModule.trim()
    if (!name) { message.warning('请输入模组名称'); return }
    if (matrix.modules.includes(name)) { message.warning('模组已存在'); return }
    const newModules = [...matrix.modules, name]
    const newMatrixData = [...matrix.matrix, new Array(matrix.features.length).fill(false)]
    updateMatrix({ ...matrix, modules: newModules, matrix: newMatrixData })
    setNewModule('')
  }

  // 添加功能（列）
  const addFeature = () => {
    const name = newFeature.trim()
    if (!name) { message.warning('请输入功能名称'); return }
    if (matrix.features.includes(name)) { message.warning('功能已存在'); return }
    const newFeatures = [...matrix.features, name]
    const newMatrixData = matrix.matrix.map(row => [...row, false])
    updateMatrix({ ...matrix, features: newFeatures, matrix: newMatrixData })
    setNewFeature('')
  }

  // 删除模组
  const removeModule = (idx: number) => {
    const newModules = matrix.modules.filter((_, i) => i !== idx)
    const newMatrixData = matrix.matrix.filter((_, i) => i !== idx)
    updateMatrix({ ...matrix, modules: newModules, matrix: newMatrixData })
  }

  // 删除功能
  const removeFeature = (idx: number) => {
    const newFeatures = matrix.features.filter((_, i) => i !== idx)
    const newMatrixData = matrix.matrix.map(row => row.filter((_, i) => i !== idx))
    updateMatrix({ ...matrix, features: newFeatures, matrix: newMatrixData })
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
    const newMatrixData = matrix.modules.map(() => new Array(DEFAULT_FEATURES.length).fill(true))
    updateMatrix({ ...matrix, features: DEFAULT_FEATURES, matrix: newMatrixData })
  }

  // 按矩阵生成用例
  const handleGenerate = async () => {
    if (!currentProject) {
      message.warning('请先创建项目')
      return
    }
    setGenerating(true)
    try {
      // 先保存当前矩阵，避免后端读取到旧的 project.json
      await updateCreatorProject(currentProject.project_id, {
        coverage_matrix: matrix,
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

  // 构建 Table columns
  const columns = [
    {
      title: '模组',
      dataIndex: 'module',
      key: 'module',
      fixed: 'left' as const,
      width: 150,
      render: (name: string, _: unknown, idx: number) => (
        <Space>
          <strong>{name}</strong>
          <Popconfirm title="删除此模组？" onConfirm={() => removeModule(idx)}>
            <DeleteOutlined style={{ color: '#999', cursor: 'pointer', fontSize: 12 }} />
          </Popconfirm>
        </Space>
      ),
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
      <Card title="📊 覆盖矩阵" size="small" style={{ marginBottom: 16 }}>
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="勾选 = 该模组需要测试该功能"
          description="配置完成后可点击「按矩阵生成用例」，系统会生成符合执行侧 Excel/ExpectedResultParser 规范的用例骨架；预期结果会包含 .raw、30fps、无报错等可判定观测点。"
        />

        {/* 添加模组/功能 */}
        <Space style={{ marginBottom: 16 }} wrap>
          <Input
            placeholder="模组名称（如 IMX728）"
            value={newModule}
            onChange={(e) => setNewModule(e.target.value)}
            onPressEnter={addModule}
            style={{ width: 200 }}
          />
          <Button icon={<PlusOutlined />} onClick={addModule}>添加模组</Button>
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
              scroll={{ x: 150 + matrix.features.length * 100 }}
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
            请先添加模组和功能，再配置覆盖关系
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
