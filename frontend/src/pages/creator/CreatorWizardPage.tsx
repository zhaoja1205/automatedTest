/**
 * 用例创建 — 向导页面。
 *
 * 5 步向导：项目信息 → 覆盖矩阵 → 用例编辑 → 预览 → 导出。
 * 支持新建（/creator/new）和编辑（/creator/edit/:projectId）。
 */
import { useEffect, useState, useCallback } from 'react'
import { Steps, Button, Space, message, Spin, Modal } from 'antd'
import { useParams, useNavigate } from 'react-router-dom'
import { useCreatorStore } from '../../stores/useCreatorStore'
import { getCreatorProject, updateCreatorProject, createCreatorProject } from '../../api/creatorApi'
import ProjectInfoStep from '../../components/creator/ProjectInfoStep'
import CoverageMatrixStep from '../../components/creator/CoverageMatrixStep'
import CaseEditorStep from '../../components/creator/CaseEditorStep'
import CasePreviewStep from '../../components/creator/CasePreviewStep'
import ExportStep from '../../components/creator/ExportStep'

const STEPS = [
  { title: '项目信息' },
  { title: '覆盖矩阵' },
  { title: '用例编辑' },
  { title: '预览确认' },
  { title: '导出' },
]

export default function CreatorWizardPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const store = useCreatorStore()
  const [loading, setLoading] = useState(false)

  // 加载项目（编辑模式）或初始化空项目（新建模式）
  useEffect(() => {
    if (projectId) {
      loadProject(projectId)
    } else {
      store.reset()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  const loadProject = async (id: string) => {
    setLoading(true)
    try {
      const res = await getCreatorProject(id)
      store.setCurrentProject(res.data)
    } catch {
      message.error('加载项目失败')
      navigate('/creator/projects')
    } finally {
      setLoading(false)
    }
  }

  // 保存当前项目到后端
  const saveProject = useCallback(async () => {
    const project = store.currentProject
    if (!project) return

    try {
      await updateCreatorProject(project.project_id, {
        name: project.name,
        meta: project.meta,
        coverage_matrix: project.coverage_matrix,
        functional_cases: project.functional_cases,
        fault_cases: project.fault_cases,
        defaults_used: project.defaults_used,
        current_step: store.currentStep,
      })
      store.markClean()
    } catch {
      message.error('保存失败')
    }
  }, [store])

  // 新建模式：第一步完成时创建项目
  const ensureProject = async (): Promise<boolean> => {
    if (store.currentProject) return true
    try {
      const name = `新建项目_${new Date().toLocaleDateString('zh-CN')}`
      const res = await createCreatorProject(name)
      store.setCurrentProject(res.data)
      // 切换 URL 到编辑模式（不重载）
      window.history.replaceState(null, '', `/creator/edit/${res.data.project_id}`)
      return true
    } catch {
      message.error('创建项目失败')
      return false
    }
  }

  // 下一步
  const handleNext = async () => {
    // 新建模式在第一步之后需创建项目
    if (!store.currentProject) {
      const ok = await ensureProject()
      if (!ok) return
    }
    if (store.isDirty) await saveProject()
    store.setCurrentStep(Math.min(store.currentStep + 1, STEPS.length - 1))
  }

  // 上一步
  const handlePrev = async () => {
    if (store.isDirty) await saveProject()
    store.setCurrentStep(Math.max(store.currentStep - 1, 0))
  }

  // 离开时提示保存
  const handleBack = () => {
    if (store.isDirty) {
      Modal.confirm({
        title: '有未保存的修改',
        content: '离开前是否保存当前修改？',
        okText: '保存并离开',
        cancelText: '不保存',
        onOk: async () => {
          await saveProject()
          navigate('/creator/projects')
        },
        onCancel: () => navigate('/creator/projects'),
      })
    } else {
      navigate('/creator/projects')
    }
  }

  const renderStep = () => {
    switch (store.currentStep) {
      case 0: return <ProjectInfoStep />
      case 1: return <CoverageMatrixStep />
      case 2: return <CaseEditorStep />
      case 3: return <CasePreviewStep />
      case 4: return <ExportStep />
      default: return null
    }
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '60vh' }}>
        <Spin size="large" tip="加载项目..." />
      </div>
    )
  }

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2 style={{ margin: 0 }}>
          {projectId ? (store.currentProject?.name || '编辑项目') : '新建用例项目'}
        </h2>
        <Button onClick={handleBack}>返回列表</Button>
      </div>

      <Steps
        current={store.currentStep}
        items={STEPS}
        style={{ marginBottom: 32 }}
        onChange={(step) => {
          // 允许点击已完成/当前步骤跳转
          if (step <= store.currentStep) {
            store.setCurrentStep(step)
          }
        }}
      />

      <div style={{ minHeight: 400 }}>
        {renderStep()}
      </div>

      <div style={{ marginTop: 24, display: 'flex', justifyContent: 'space-between' }}>
        <Space>
          {store.currentStep > 0 && (
            <Button onClick={handlePrev}>上一步</Button>
          )}
        </Space>
        <Space>
          {store.currentProject && (
            <Button onClick={saveProject} disabled={!store.isDirty}>
              保存
            </Button>
          )}
          {store.currentStep < STEPS.length - 1 && (
            <Button type="primary" onClick={handleNext}>
              下一步
            </Button>
          )}
        </Space>
      </div>
    </div>
  )
}
