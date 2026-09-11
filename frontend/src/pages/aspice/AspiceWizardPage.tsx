/**
 * ASPICE 文档 — 向导页面。
 *
 * 用 Tabs 切 SWE.1 需求分析 / SWE.2 架构设计两个阶段。
 * 支持 /aspice/new（新建）和 /aspice/edit/:projectId（编辑）。
 */
import { useEffect, useState, useCallback, useRef } from 'react'
import { Tabs, Button, Space, message, Spin } from 'antd'
import { useParams, useNavigate } from 'react-router-dom'
import { createDefaultAspice, useAspiceStore } from '../../stores/useAspiceStore'
import api from '../../api/axios'
import {
  getAspiceProject,
  saveAspiceProject,
  createAspiceProject,
} from '../../api/aspiceApi'
import Swe1Step from '../../components/aspice/Swe1Step'
import Swe2Step from '../../components/aspice/Swe2Step'

export default function AspiceWizardPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const store = useAspiceStore()
  const [loading, setLoading] = useState(false)
  const creatingProjectRef = useRef(false)

  useEffect(() => {
    if (projectId) {
      loadProject(projectId)
    } else {
      store.reset()
      // 新建模式：自动创建项目
      ensureProject()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  const ensureProject = async () => {
    if (creatingProjectRef.current) return
    creatingProjectRef.current = true
    try {
      const name = `新建ASPICE项目_${new Date().toLocaleDateString('zh-CN')}`
      const res = await createAspiceProject(name)
      store.setProject(res.data.project_id, res.data.name, createDefaultAspice())
      navigate(`/aspice/edit/${res.data.project_id}`, { replace: true })
    } catch {
      message.error('创建项目失败')
      navigate('/aspice/projects')
    } finally {
      creatingProjectRef.current = false
    }
  }

  const loadProject = async (id: string) => {
    const current = useAspiceStore.getState()
    // 从「项目管理」返回同一项目时，优先保留前端未保存的解析/编辑结果，避免被后端旧数据覆盖。
    if (current.projectId === id && current.aspice) return

    setLoading(true)
    try {
      // 先拉 creator 项目拿名称
      const projRes = await api.get(`/creator/projects/${id}`)
      const aspiceRes = await getAspiceProject(id)
      store.setProject(id, projRes.data.name, {
        ...createDefaultAspice(),
        ...aspiceRes.data,
        swe1: { ...createDefaultAspice().swe1, ...aspiceRes.data.swe1 },
        swe2: { ...createDefaultAspice().swe2, ...aspiceRes.data.swe2 },
      })
    } catch {
      message.error('加载项目失败')
      navigate('/aspice/projects')
    } finally {
      setLoading(false)
    }
  }

  const saveCurrent = useCallback(async () => {
    if (!store.projectId || !store.aspice) return
    try {
      await saveAspiceProject(store.projectId, store.aspice)
      store.markClean()
    } catch {
      message.error('保存失败')
    }
  }, [store])

  if (!store.aspice) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '60vh' }}>
        <Spin size="large" tip="初始化 ASPICE 项目..." />
      </div>
    )
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
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>
          {store.projectName || 'ASPICE 文档'} — ID 链路：{store.aspice?.project_code || '未设代号'}_001 → -R001 → -A001
        </h2>
        <Space>
          <Button onClick={() => navigate('/aspice/projects')}>返回列表</Button>
          <Button onClick={saveCurrent} disabled={!store.isDirty}>保存</Button>
        </Space>
      </div>

      <Tabs
        activeKey={store.currentPhase}
        onChange={(key) => {
          if (store.isDirty) saveCurrent()
          store.setCurrentPhase(key as 'swe1' | 'swe2')
        }}
        items={[
          {
            key: 'swe1',
            label: `SWE.1 需求分析 (${store.aspice?.swe1?.requirements?.length || 0})`,
            children: <Swe1Step />,
          },
          {
            key: 'swe2',
            label: `SWE.2 架构设计 (${store.aspice?.swe2?.mappings?.length || 0})`,
            children: <Swe2Step />,
          },
        ]}
      />
    </div>
  )
}
