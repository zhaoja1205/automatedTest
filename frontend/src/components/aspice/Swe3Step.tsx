/**
 * SWE.3 软件详细设计步骤。
 *
 * 承载 14 章骨架编辑：概述 / 术语 / 模块构成追溯 / 9 模块详细设计 /
 * 性能分析 / 函数设计评估 / 共通定义 / 系统集成。
 *
 * 推送 C：手动编辑 + 规则派生（已完成）
 * 推送 D UI 版本：新增顶部 Switch + 3 个新 Collapse（工程上传/路径配置/关注函数） + AI 批量补齐进度。
 *   —— 本阶段扫描/AI 全部走 mock，便于用户验证交互逻辑。真实后端接入在推送 D 第二阶段。
 */
import { useMemo, useState } from 'react'
import {
  Button, Space, Card, Alert, message, Tag, Collapse, Input, Switch, Progress, Modal,
} from 'antd'
import {
  ExportOutlined, DownloadOutlined, ThunderboltOutlined, ReloadOutlined,
  FileTextOutlined, AppstoreOutlined, ToolOutlined, DatabaseOutlined,
  CloudUploadOutlined, FolderOpenOutlined, AimOutlined, SafetyOutlined,
} from '@ant-design/icons'
import { useAspiceStore } from '../../stores/useAspiceStore'
import {
  generateSwe3, exportSwe3, downloadAspiceFile,
  augmentFocusFunctions, setCameraSecurity, getModuleScan,
} from '../../api/aspiceApi'
import ModuleCompositionEditor from './swe3/ModuleCompositionEditor'
import ModuleDesignEditor from './swe3/ModuleDesignEditor'
import CommonDefsEditor from './swe3/CommonDefsEditor'
import EngineeringUploadPanel from './swe3/EngineeringUploadPanel'
import EngineeringScanner from './swe3/EngineeringScanner'
import ModulePathConfigEditor from './swe3/ModulePathConfigEditor'
import FocusFunctionsPicker from './swe3/FocusFunctionsPicker'
import FunctionStatusTable from './swe3/FunctionStatusTable'

export default function Swe3Step() {
  const store = useAspiceStore()
  const { projectId, aspice, setSwe3Overview, setSwe3Composition,
    setSwe3Modules, setSwe3CommonDefs, setSwe3Performance, setSwe3FunctionEvaluation,
    setSwe3Integration, setSwe3HasCameraSecurity } = store
  const swe3 = aspice?.swe3
  const push_d = swe3?.push_d
  const [generating, setGenerating] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exportFiles, setExportFiles] = useState<{ docx: string; xlsx: string } | null>(null)
  const [aiProgress, setAiProgress] = useState<{ done: number; total: number; name: string } | null>(null)

  if (!swe3) {
    return <Alert type="warning" message="SWE.3 数据未初始化" />
  }

  const hasCameraSec = push_d?.has_camera_security ?? true

  // 关注函数汇总
  const allFocusedKeys = useMemo(() => {
    return (push_d?.focus_functions || []).flatMap((f) => f.focused_keys || [])
  }, [push_d?.focus_functions])

  // 过滤：若关闭 Camera Security，隐藏 A008 模块
  const visibleModules = useMemo(() => {
    if (hasCameraSec) return swe3.modules
    return swe3.modules.filter((m) => m.component_id !== 'A008')
  }, [swe3.modules, hasCameraSec])

  const handleGenerate = async () => {
    if (!projectId) { message.warning('项目未创建'); return }
    setGenerating(true)
    try {
      const res = await generateSwe3(projectId)
      message.success(`已派生：${res.data.composition_rows} 行构成，${res.data.modules} 个模块`)
      window.location.reload()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '派生失败')
    } finally {
      setGenerating(false)
    }
  }

  const handleExport = async () => {
    if (!projectId) return
    setExporting(true)
    try {
      const res = await exportSwe3(projectId)
      setExportFiles(res.data)
      message.success('详细设计导出成功')
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

  // AI 批量补齐
  const handleAiBatch = () => {
    if (allFocusedKeys.length === 0) {
      message.warning('请先在"关注函数选择"中勾选至少 1 个函数')
      return
    }
    if (!projectId) { message.warning('项目未创建'); return }
    Modal.confirm({
      title: `AI 批量补齐（${allFocusedKeys.length} 个关注函数）`,
      content: `将为每个关注函数调用 AI 生成"函数介绍"与"PlantUML 流程图"；完成后请点"刷新扫描数据"按钮或切换一次模块 Tab 以查看回填结果。`,
      okText: '开始',
      cancelText: '取消',
      onOk: async () => {
        setAiProgress({ done: 0, total: allFocusedKeys.length, name: '' })
        try {
          const res = await augmentFocusFunctions(projectId, (ev) => {
            setAiProgress({ done: ev.done, total: ev.total, name: ev.name })
          })
          // 完成后拉一遍所有已扫模块的最新 scan（含 AI 回填）回填 store
          const scanned = (push_d?.scan_indices || [])
            .map((s) => s.component_id)
          await Promise.all(scanned.map(async (cid) => {
            try {
              const r = await getModuleScan(projectId, cid)
              store.setSwe3ScanIndex(cid, r.data)
            } catch { /* ignore */ }
          }))
          message.success(`已补齐 ${res.augmented} 个函数`)
        } catch (e: any) {
          message.error(e?.message || 'AI 补齐失败')
        } finally {
          setTimeout(() => setAiProgress(null), 500)
        }
      },
    })
  }

  const handleToggleCameraSec = async (v: boolean) => {
    setSwe3HasCameraSecurity(v)   // 本地先改，UI 立刻响应
    if (!projectId) return
    try { await setCameraSecurity(projectId, v) }
    catch (e: any) {
      message.error(e?.response?.data?.detail || '保存 Camera Security 开关失败')
      setSwe3HasCameraSecurity(!v)   // 失败则回滚
    }
  }

  // 第 1 概述
  const updateOverviewField = (key: 'purpose' | 'charset' | 'getset_rule', value: string) => {
    setSwe3Overview({ ...swe3.overview, [key]: value })
  }

  return (
    <div style={{ maxWidth: 1280 }}>
      <Alert
        type="info" showIcon style={{ marginBottom: 16 }}
        message="SWE.3 软件详细设计（含推送 D UI 版本）"
        description="14 章骨架 + 工程代码集成：上传源码 zip → 配置模块代码目录 → 勾选关注函数 → AI 批量补齐介绍与流程图。设计 ID 命名规则：D{组件编号}-{组件名}-{class|function}-{3位序号}。"
      />

      {/* 顶部工具栏 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Space>
            <SafetyOutlined />
            <span>包含 Camera Security：</span>
            <Switch size="small" checked={hasCameraSec}
              onChange={handleToggleCameraSec}
              checkedChildren="是" unCheckedChildren="否" />
            {!hasCameraSec && <Tag color="orange">A008 模块与第 10 章将跳过</Tag>}
          </Space>
          <span style={{ borderLeft: '1px solid #eee', height: 20 }} />
          <Button icon={<ReloadOutlined />} loading={generating} onClick={handleGenerate}>
            规则派生（从 SWE.2）
          </Button>
          <Button icon={<ThunderboltOutlined />} onClick={handleAiBatch}
            disabled={allFocusedKeys.length === 0}>
            AI 批量补齐（{allFocusedKeys.length} 关注函数）
          </Button>
          <Button type="primary" icon={<ExportOutlined />} loading={exporting} onClick={handleExport}>
            导出详细设计文档
          </Button>
          <span style={{ borderLeft: '1px solid #eee', height: 20 }} />
          <Tag color="blue">模块：{visibleModules.length}</Tag>
          <Tag color="purple">
            扫描：{(push_d?.scan_indices || []).reduce((n, s) => n + (s.stats?.total_functions || 0), 0)} 函数
          </Tag>
          <Tag color="green">关注：{allFocusedKeys.length}</Tag>
        </Space>
      </Card>

      <Collapse
        size="small"
        defaultActiveKey={['engineering', 'paths', 'focus']}
        items={[
          /* ---------- 推送 D 新增三段 ---------- */
          {
            key: 'engineering',
            label: (
              <Space>
                <CloudUploadOutlined />
                <span>🗂 工程代码上传（推送 D）</span>
                {push_d?.engineering ? (
                  <Tag color="green">
                    已上传 {push_d.engineering.total_files} 文件
                  </Tag>
                ) : <Tag>未上传</Tag>}
              </Space>
            ),
            children: projectId ? (
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
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
          },
          {
            key: 'paths',
            label: (
              <Space>
                <FolderOpenOutlined />
                <span>📂 模块代码路径配置（推送 D）</span>
                <Tag color="blue">
                  {(push_d?.module_code_sources || []).filter((s) => s.path_patterns.length > 0).length} / {visibleModules.length} 已配置
                </Tag>
              </Space>
            ),
            children: push_d?.engineering ? (
              <ModulePathConfigEditor modules={visibleModules.map((m) => ({
                component_id: m.component_id, slug: m.slug, name: m.name,
              }))} />
            ) : (
              <Alert type="warning" showIcon message="请先在上方上传工程代码 zip" />
            ),
          },
          {
            key: 'focus',
            label: (
              <Space>
                <AimOutlined />
                <span>🎯 关注函数选择（推送 D）</span>
                <Tag color="green">共 {allFocusedKeys.length} 个</Tag>
              </Space>
            ),
            children: (push_d?.scan_indices || []).length > 0 ? (
              <FocusFunctionsPicker modules={visibleModules.map((m) => ({
                component_id: m.component_id, name: m.name,
              }))} />
            ) : (
              <Alert type="warning" showIcon
                message='请先在上方"路径配置"中为至少一个模块扫描源码' />
            ),
          },
          {
            key: 'func_status',
            label: (
              <Space>
                <SafetyOutlined />
                <span>📋 函数状态清单（推送 G）</span>
                <Tag color="blue">改动分类 · 豁免 · AI 重试</Tag>
                {allFocusedKeys.length === 0 && (push_d?.scan_indices || []).length > 0 && (
                  <Tag color="warning">⚠️ 未选关注函数</Tag>
                )}
              </Space>
            ),
            children: (push_d?.scan_indices || []).length > 0 ? (
              <FunctionStatusTable projectId={projectId || ''}
                modules={visibleModules} />
            ) : (
              <Alert type="info" showIcon
                message='请先在"路径配置"中扫描源码后，此处才能展示函数清单' />
            ),
          },
          /* ---------- 推送 C 已有五段 ---------- */
          {
            key: 'overview',
            label: (
              <Space>
                <FileTextOutlined />
                <span>第 1~2 章 概述 + 术语</span>
                <Tag color={swe3.overview.purpose ? 'green' : 'default'}>
                  {swe3.overview.purpose ? '已填充' : '待填充'}
                </Tag>
              </Space>
            ),
            children: (
              <Card size="small">
                <div style={{ marginBottom: 12 }}>
                  <div style={{ marginBottom: 4, fontWeight: 500 }}>1.1 目的</div>
                  <Input.TextArea rows={3} value={swe3.overview.purpose}
                    onChange={(e) => updateOverviewField('purpose', e.target.value)} />
                </div>
                <div style={{ marginBottom: 12 }}>
                  <div style={{ marginBottom: 4, fontWeight: 500 }}>1.4 字符集</div>
                  <Input.TextArea rows={2} value={swe3.overview.charset}
                    onChange={(e) => updateOverviewField('charset', e.target.value)} />
                </div>
                <div style={{ marginBottom: 12 }}>
                  <div style={{ marginBottom: 4, fontWeight: 500 }}>1.5 Set/Get 函数规则</div>
                  <Input.TextArea rows={3} value={swe3.overview.getset_rule}
                    onChange={(e) => updateOverviewField('getset_rule', e.target.value)} />
                </div>
                <Alert type="info" showIcon
                  message="范围表 / 参考文档 / 术语的详细编辑按推送 D 的章节树重构，目前仅展示默认值；导出 docx 使用默认内容。"
                />
              </Card>
            ),
          },
          {
            key: 'composition',
            label: (
              <Space>
                <AppstoreOutlined />
                <span>第 3 章 软件功能概述（SWE.1 → SWE.2 → 类 → SWE.3）</span>
                <Tag color={(swe3.composition.composition_rows?.length || 0) > 0 ? 'green' : 'default'}>
                  {swe3.composition.composition_rows?.length || 0} 行
                </Tag>
              </Space>
            ),
            children: <ModuleCompositionEditor
              composition={swe3.composition}
              onChange={setSwe3Composition} />,
          },
          {
            key: 'modules',
            label: (
              <Space>
                <ToolOutlined />
                <span>第 4~10 章 模块详细设计</span>
                <Tag color="blue">{visibleModules.length} 模块</Tag>
              </Space>
            ),
            children: <ModuleDesignEditor
              modules={swe3.modules}
              onChange={setSwe3Modules}
              hasCameraSecurity={hasCameraSec} />,
          },
          {
            key: 'common',
            label: (
              <Space>
                <DatabaseOutlined />
                <span>第 13 章 共通定义（常量/变量/枚举/结构体/配置）</span>
                <Tag color="purple">
                  {(swe3.common_defs.enums?.length || 0)} 枚举 /
                  {(swe3.common_defs.structures?.length || 0)} 结构体
                </Tag>
              </Space>
            ),
            children: <CommonDefsEditor
              commonDefs={swe3.common_defs}
              onChange={setSwe3CommonDefs} />,
          },
          {
            key: 'misc',
            label: (
              <Space>
                <ThunderboltOutlined />
                <span>第 11/12/14 章 性能 / 函数评估 / 系统集成</span>
              </Space>
            ),
            children: (
              <Card size="small">
                <div style={{ marginBottom: 12 }}>
                  <div style={{ marginBottom: 4, fontWeight: 500 }}>11 性能分析（每行一段）</div>
                  <Input.TextArea rows={4}
                    value={(swe3.performance.paragraphs || []).join('\n')}
                    onChange={(e) => setSwe3Performance({
                      paragraphs: e.target.value.split('\n').filter(Boolean),
                    })} />
                </div>
                <div style={{ marginBottom: 12 }}>
                  <div style={{ marginBottom: 4, fontWeight: 500 }}>12 函数设计评估（每行一段）</div>
                  <Input.TextArea rows={3}
                    value={(swe3.function_evaluation.paragraphs || []).join('\n')}
                    onChange={(e) => setSwe3FunctionEvaluation({
                      ...swe3.function_evaluation,
                      paragraphs: e.target.value.split('\n').filter(Boolean),
                    })} />
                  <div style={{ marginTop: 8, marginBottom: 4, fontWeight: 500 }}>
                    12.1 函数修改影响范围（每行一段）
                  </div>
                  <Input.TextArea rows={3}
                    value={(swe3.function_evaluation.impact_paragraphs || []).join('\n')}
                    onChange={(e) => setSwe3FunctionEvaluation({
                      ...swe3.function_evaluation,
                      impact_paragraphs: e.target.value.split('\n').filter(Boolean),
                    })} />
                </div>
                <div style={{ marginBottom: 12 }}>
                  <div style={{ marginBottom: 4, fontWeight: 500 }}>14 系统集成（每行一段）</div>
                  <Input.TextArea rows={4}
                    value={(swe3.integration.paragraphs || []).join('\n')}
                    onChange={(e) => setSwe3Integration({
                      paragraphs: e.target.value.split('\n').filter(Boolean),
                    })} />
                </div>
              </Card>
            ),
          },
        ]}
      />

      {exportFiles && (
        <Card size="small" title="导出文件" style={{ marginTop: 16 }}>
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

      {/* AI 批量补齐进度 */}
      {aiProgress && (
        <div style={{
          position: 'fixed', right: 24, bottom: 24, width: 320, zIndex: 1000,
          background: '#fff', boxShadow: '0 4px 20px rgba(0,0,0,0.15)',
          borderRadius: 8, padding: 16,
        }}>
          <div style={{ fontWeight: 500, marginBottom: 6 }}>
            <ThunderboltOutlined /> AI 补齐中…
          </div>
          <Progress percent={Math.round((aiProgress.done / aiProgress.total) * 100)}
            status="active" />
          <div style={{ color: '#666', fontSize: 12, marginTop: 4 }}>
            {aiProgress.done} / {aiProgress.total} — 当前：{aiProgress.name}
          </div>
        </div>
      )}
    </div>
  )
}
