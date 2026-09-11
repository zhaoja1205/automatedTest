/**
 * 步骤 3：用例编辑器。
 *
 * 功能用例 / 故障用例 两个 Tab，每个 Tab 下是可编辑的用例列表。
 * 支持添加、编辑（Modal）、删除、复制、上下移动操作。
 */
import { useState } from 'react'
import { Tabs, Table, Button, Space, Modal, Form, Input, Select, Popconfirm, Tag, message, Alert, Tooltip, Upload, Radio } from 'antd'
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  CopyOutlined,
  ArrowUpOutlined,
  ArrowDownOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  WarningOutlined,
  ImportOutlined,
} from '@ant-design/icons'
import { useCreatorStore } from '../../stores/useCreatorStore'
import type { DesignCase } from '../../types/creator'
import { sampleCase, validateCase } from '../../utils/caseRules'
import { importCreatorCases, getCreatorProject } from '../../api/creatorApi'

const { TextArea } = Input

// 测试类型选项
const TYPE_OPTIONS = ['基本功能', '边界值', '异常', '故障注入']
// 设计方法选项
const METHOD_OPTIONS = ['基于需求分析', '等价类划分', '边界值分析', '错误推测法']
// 优先级选项
const PRIORITY_OPTIONS = ['P0', 'P1', 'P2']

/** 空用例模板 */
const emptyCase = (): DesignCase => ({
  type: '基本功能',
  method: '基于需求分析',
  desc: '',
  pre: '',
  steps: '',
  expected: '',
  priority: 'P1',
  changelog: '',
})

interface CaseListEditorProps {
  cases: DesignCase[]
  onChange: (cases: DesignCase[]) => void
  category: 'functional' | 'fault'
}

function CaseListEditor({ cases, onChange, category }: CaseListEditorProps) {
  const [editingIndex, setEditingIndex] = useState<number>(-1)
  const [modalOpen, setModalOpen] = useState(false)
  const [form] = Form.useForm()

  // 打开编辑弹窗
  const openEditor = (c: DesignCase | null, index: number) => {
    const target = c ? { ...c } : emptyCase()
    setEditingIndex(index)
    form.setFieldsValue(target)
    setModalOpen(true)
  }

  // 保存用例
  const handleSave = () => {
    form.validateFields().then(values => {
      const updated = [...cases]
      if (editingIndex >= 0) {
        updated[editingIndex] = { ...updated[editingIndex], ...values }
      } else {
        updated.push({ ...emptyCase(), ...values })
      }
      onChange(updated)
      setModalOpen(false)
    })
  }

  // 删除用例
  const handleDelete = (index: number) => {
    const updated = cases.filter((_, i) => i !== index)
    onChange(updated)
  }

  // 复制用例
  const handleCopy = (index: number) => {
    const copy = { ...cases[index], id: undefined }
    const updated = [...cases]
    updated.splice(index + 1, 0, copy)
    onChange(updated)
    message.success('已复制')
  }

  // 上移
  const handleMoveUp = (index: number) => {
    if (index === 0) return
    const updated = [...cases]
    ;[updated[index - 1], updated[index]] = [updated[index], updated[index - 1]]
    onChange(updated)
  }

  // 下移
  const handleMoveDown = (index: number) => {
    if (index === cases.length - 1) return
    const updated = [...cases]
    ;[updated[index], updated[index + 1]] = [updated[index + 1], updated[index]]
    onChange(updated)
  }

  // 检测占位符
  const hasPlaceholder = (text: string) =>
    typeof text === 'string' && text.includes('<待补充')

  const showValidation = (record: DesignCase) => {
    const result = validateCase(record)
    Modal.info({
      title: '用例规范检查',
      content: (
        <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
          {result.messages.map((m, i) => <li key={i}>{m}</li>)}
        </ul>
      ),
    })
  }

  const columns = [
    {
      title: 'ID',
      key: 'id',
      width: 60,
      render: (_: unknown, __: unknown, idx: number) => (
        <span style={{ color: '#888' }}>{String(idx + 1).padStart(3, '0')}</span>
      ),
    },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 100,
    },
    {
      title: '描述',
      dataIndex: 'desc',
      key: 'desc',
      ellipsis: true,
      render: (text: string) => (
        <span>
          {hasPlaceholder(text) && <Tag color="warning" style={{ marginRight: 4 }}>待补充</Tag>}
          {text}
        </span>
      ),
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      width: 80,
      render: (p: string) => {
        const colors: Record<string, string> = { P0: 'red', P1: 'orange', P2: 'blue' }
        return <Tag color={colors[p] || 'default'}>{p}</Tag>
      },
    },
    {
      title: '规范',
      key: 'rules',
      width: 140,
      render: (_: unknown, record: DesignCase) => {
        const result = validateCase(record)
        if (result.level === 'ok') {
          return <Tag color="success" icon={<CheckCircleOutlined />}>可判定</Tag>
        }
        if (result.level === 'error') {
          return <Tag color="error" icon={<ExclamationCircleOutlined />} onClick={() => showValidation(record)} style={{ cursor: 'pointer' }}>需补充</Tag>
        }
        return <Tag color="warning" icon={<WarningOutlined />} onClick={() => showValidation(record)} style={{ cursor: 'pointer' }}>低置信度</Tag>
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 180,
      render: (_: unknown, record: DesignCase, idx: number) => (
        <Space size={4}>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEditor(record, idx)} />
          <Button type="link" size="small" icon={<CopyOutlined />} onClick={() => handleCopy(idx)} />
          <Button type="link" size="small" icon={<ArrowUpOutlined />} disabled={idx === 0} onClick={() => handleMoveUp(idx)} />
          <Button type="link" size="small" icon={<ArrowDownOutlined />} disabled={idx === cases.length - 1} onClick={() => handleMoveDown(idx)} />
          <Popconfirm title="删除此用例？" onConfirm={() => handleDelete(idx)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <>
      <Alert
        type="info"
        showIcon
        closable
        style={{ marginBottom: 12 }}
        message="规范要点：预期结果必须含可判定观测点"
        description="建议写入 .raw/.yuv 等产物后缀、30fps 等数值、无报错/无异常、正常起流，或用英文双引号包裹需匹配的关键字。否则执行引擎只能依赖退出码判定，置信度低。"
      />

      <div style={{ marginBottom: 12 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => openEditor(null, -1)}>
          添加{category === 'functional' ? '功能' : '故障'}用例
        </Button>
        <span style={{ marginLeft: 12, color: '#888' }}>共 {cases.length} 条</span>
      </div>

      <Table
        rowKey={(_, idx) => String(idx)}
        columns={columns}
        dataSource={cases}
        pagination={cases.length > 20 ? { pageSize: 20 } : false}
        size="small"
        bordered
      />

      {/* 用例编辑弹窗 */}
      <Modal
        title={editingIndex >= 0 ? `编辑用例 #${editingIndex + 1}` : '添加用例'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleSave}
        width={720}
        okText="确定"
      >
        <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ color: '#888' }}>字段提示会按执行侧解析规则校验。</span>
          <Button size="small" onClick={() => form.setFieldsValue(sampleCase())}>插入示例</Button>
        </div>
        <Form form={form} layout="vertical">
          <div style={{ display: 'flex', gap: 12 }}>
            <Form.Item label={<Tooltip title="基本功能或故障注入；故障类用例应选择「故障注入」">测试类型</Tooltip>} name="type" rules={[{ required: true }]} style={{ flex: 1 }}>
              <Select>
                {TYPE_OPTIONS.map(t => <Select.Option key={t} value={t}>{t}</Select.Option>)}
              </Select>
            </Form.Item>
            <Form.Item label={<Tooltip title="默认使用「基于需求分析」，与标准模板一致">设计方法</Tooltip>} name="method" rules={[{ required: true }]} style={{ flex: 1 }}>
              <Select>
                {METHOD_OPTIONS.map(m => <Select.Option key={m} value={m}>{m}</Select.Option>) }
              </Select>
            </Form.Item>
            <Form.Item label={<Tooltip title="起流/出图/帧率/故障注入建议 P1，其余可用 P2">优先级</Tooltip>} name="priority" rules={[{ required: true }]} style={{ width: 100 }}>
              <Select>
                {PRIORITY_OPTIONS.map(p => <Select.Option key={p} value={p}>{p}</Select.Option>)}
              </Select>
            </Form.Item>
          </div>
          <Form.Item label={<Tooltip title="一句话写清测试对象和目标，如：验证 IMX728 模组起流并正常出图">用例描述</Tooltip>} name="desc" rules={[{ required: true, message: '请输入用例描述' }]}>
            <TextArea rows={2} placeholder="一句话描述测试目标" />
          </Form.Item>
          <Form.Item label={<Tooltip title="写环境准备，如驱动文件路径、模组连接、SSH 登录板端">前置条件</Tooltip>} name="pre">
            <TextArea rows={4} placeholder="环境准备（如 SSH 连接板端、Camera 驱动已加载等）" />
          </Form.Item>
          <Form.Item label={<Tooltip title="必须包含编号和可执行命令，如：1、输入命令：./nvsipl_camera ...">测试步骤</Tooltip>} name="steps" rules={[{ required: true, message: '请输入测试步骤' }]}>
            <TextArea rows={6} placeholder="编号步骤 + 具体命令&#10;1. 在板端终端 A 执行 ...&#10;2. 等待 ...&#10;3. 确认 ..." />
          </Form.Item>
          <Form.Item label={<Tooltip title="必须含可判定观测点：.raw/.yuv、30fps、无报错、正常起流或引号关键字">预期结果</Tooltip>} name="expected" rules={[{ required: true, message: '请输入预期结果' }]}>
            <TextArea rows={4} placeholder="可观测判定标准&#10;如：终端打印帧率 30fps；.raw 文件生成且非空" />
          </Form.Item>
          <Form.Item label="版本变更记录" name="changelog">
            <Input placeholder="通常为空" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

export default function CaseEditorStep() {
  const { currentProject, setFunctionalCases, setFaultCases, setCurrentProject } = useCreatorStore()
  const [importing, setImporting] = useState(false)
  const [importModalOpen, setImportModalOpen] = useState(false)
  const [importMode, setImportMode] = useState<'overwrite' | 'append'>('overwrite')
  const [pendingFile, setPendingFile] = useState<File | null>(null)

  const functionalCases = currentProject?.functional_cases || []
  const faultCases = currentProject?.fault_cases || []

  const handleImportSelect = (file: File) => {
    setPendingFile(file)
    setImportModalOpen(true)
    return false // 拦截自动上传
  }

  const handleImportConfirm = async () => {
    if (!pendingFile || !currentProject) return
    setImporting(true)
    try {
      const res = await importCreatorCases(currentProject.project_id, pendingFile, importMode === 'overwrite')
      const { count, functional_count, fault_count, meta_extracted } = res.data
      // 重新拉取项目以同步用例与 meta
      const fresh = (await getCreatorProject(currentProject.project_id)).data
      setCurrentProject(fresh)
      const metaNote = Object.keys(meta_extracted).length
        ? `，已从命令提取 ${Object.entries(meta_extracted).map(([k, v]) => `${k}=${v}`).join('、')}`
        : ''
      message.success(`已导入 ${count} 条用例（功能 ${functional_count} / 故障 ${fault_count}）${metaNote}`)
      setImportModalOpen(false)
      setPendingFile(null)
    } catch (e: any) {
      const detail = e?.response?.data?.detail || e?.message || '导入失败'
      message.error(typeof detail === 'string' ? detail : '导入失败')
    } finally {
      setImporting(false)
    }
  }

  return (
    <div>
      <div style={{ marginBottom: 12, display: 'flex', gap: 8, alignItems: 'center' }}>
        <Upload
          accept=".xlsx,.xls"
          showUploadList={false}
          beforeUpload={handleImportSelect}
        >
          <Button icon={<ImportOutlined />} loading={importing}>
            从 Excel 回灌导入
          </Button>
        </Upload>
        <span style={{ color: '#999', fontSize: 12 }}>
          导入符合执行规范的 xlsx（如 PreDev 测试报告），按 sheet 分类为功能/故障用例
        </span>
      </div>

      <Tabs
        defaultActiveKey="functional"
        items={[
          {
            key: 'functional',
            label: `功能测试 (${functionalCases.length})`,
            children: (
              <CaseListEditor
                cases={functionalCases}
                onChange={setFunctionalCases}
                category="functional"
              />
            ),
          },
          {
            key: 'fault',
            label: `故障测试 (${faultCases.length})`,
            children: (
              <CaseListEditor
                cases={faultCases}
                onChange={setFaultCases}
                category="fault"
              />
            ),
          },
        ]}
      />

      <Modal
        title="回灌导入确认"
        open={importModalOpen}
        confirmLoading={importing}
        onCancel={() => { setImportModalOpen(false); setPendingFile(null) }}
        onOk={handleImportConfirm}
      >
        <p>已选择文件：{pendingFile?.name}</p>
        <Radio.Group value={importMode} onChange={(e) => setImportMode(e.target.value)}>
          <Space direction="vertical">
            <Radio value="overwrite">覆盖已有用例（推荐用于回灌模板）</Radio>
            <Radio value="append">追加到已有用例</Radio>
          </Space>
        </Radio.Group>
      </Modal>
    </div>
  )
}
