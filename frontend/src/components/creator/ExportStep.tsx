/**
 * 步骤 5：导出。
 *
 * 调用后端 export API 生成 xlsx（内部版 + 客户版），提供下载链接。
 * 显示占位符/默认值汇总。
 */
import { useState } from 'react'
import { Button, Card, Space, Alert, message, Descriptions, Tag } from 'antd'
import {
  ExportOutlined,
  FileExcelOutlined,
  FileTextOutlined,
  CheckCircleOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { useCreatorStore } from '../../stores/useCreatorStore'
import { exportCreatorProject, downloadCreatorFile } from '../../api/creatorApi'
import type { ExportResult } from '../../types/creator'

export default function ExportStep() {
  const { currentProject, exporting, setExporting } = useCreatorStore()
  const [result, setResult] = useState<ExportResult | null>(null)

  const projectId = currentProject?.project_id
  const funcCount = currentProject?.functional_cases?.length || 0
  const faultCount = currentProject?.fault_cases?.length || 0

  const handleExport = async () => {
    if (!projectId) { message.error('项目未保存'); return }
    setExporting(true)
    try {
      const res = await exportCreatorProject(projectId)
      setResult(res.data)
      message.success('导出完成！')
    } catch (err: unknown) {
      message.error('导出失败')
    } finally {
      setExporting(false)
    }
  }

  const handleDownload = async (filename: string) => {
    if (!projectId) return
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

  return (
    <div>
      {/* 导出前摘要 */}
      <Card title="📦 导出用例" size="small" style={{ marginBottom: 16 }}>
        <Descriptions column={2} size="small">
          <Descriptions.Item label="项目">{currentProject?.name}</Descriptions.Item>
          <Descriptions.Item label="标题">{currentProject?.meta?.title}</Descriptions.Item>
          <Descriptions.Item label="功能用例">{funcCount} 条</Descriptions.Item>
          <Descriptions.Item label="故障用例">{faultCount} 条</Descriptions.Item>
          <Descriptions.Item label="测试版本">{currentProject?.meta?.test_version || '—'}</Descriptions.Item>
          <Descriptions.Item label="操作系统">{currentProject?.meta?.os || '—'}</Descriptions.Item>
        </Descriptions>

        <div style={{ marginTop: 16 }}>
          <Button
            type="primary"
            size="large"
            icon={<ExportOutlined />}
            loading={exporting}
            onClick={handleExport}
            disabled={funcCount + faultCount === 0}
          >
            {exporting ? '生成中...' : '生成 xlsx（内部版 + 客户版）'}
          </Button>
          {funcCount + faultCount === 0 && (
            <span style={{ marginLeft: 12, color: '#999' }}>请先在步骤 3 添加用例</span>
          )}
        </div>
      </Card>

      {/* 导出结果 */}
      {result && (
        <Card title="✅ 导出完成" size="small" style={{ marginBottom: 16 }}>
          <Space direction="vertical" style={{ width: '100%' }}>
            {result.xlsx_internal && (
              <Button
                icon={<FileExcelOutlined />}
                onClick={() => handleDownload(result.xlsx_internal!)}
                block
                style={{ textAlign: 'left' }}
              >
                📁 内部版 — {result.xlsx_internal}
                <Tag color="blue" style={{ marginLeft: 8 }}>含三态判定/正则/黑灰名单</Tag>
              </Button>
            )}
            {result.xlsx_release && (
              <Button
                icon={<FileExcelOutlined />}
                onClick={() => handleDownload(result.xlsx_release!)}
                block
                style={{ textAlign: 'left' }}
              >
                📁 客户版 — {result.xlsx_release}
                <Tag color="green" style={{ marginLeft: 8 }}>中性措辞/已过滤内部字眼</Tag>
              </Button>
            )}
            {result.json_path && (
              <Button
                icon={<FileTextOutlined />}
                onClick={() => handleDownload(result.json_path)}
                block
                style={{ textAlign: 'left' }}
              >
                📄 结构化数据 — {result.json_path}
              </Button>
            )}
          </Space>

          {/* 占位符告警 */}
          {result.placeholders.length > 0 && (
            <Alert
              type="warning"
              showIcon
              icon={<WarningOutlined />}
              message={`⚠️ ${result.placeholders.length} 处占位符待人工补充`}
              description={
                <ul style={{ margin: '4px 0 0', paddingLeft: 20, maxHeight: 200, overflow: 'auto' }}>
                  {result.placeholders.map((p, i) => (
                    <li key={i}>
                      <code>{p.placeholder}</code>
                      <span style={{ color: '#888' }}>（{p.category} #{p.case_id} / {p.field}）</span>
                    </li>
                  ))}
                </ul>
              }
              style={{ marginTop: 16 }}
            />
          )}

          {/* 默认值确认 */}
          {result.defaults_used.length > 0 && (
            <Alert
              type="info"
              showIcon
              message={`ℹ️ ${result.defaults_used.length} 项默认值请确认是否适用`}
              description={
                <ul style={{ margin: '4px 0 0', paddingLeft: 20, maxHeight: 200, overflow: 'auto' }}>
                  {result.defaults_used.map((d, i) => (
                    <li key={i}>
                      <strong>{d.field}</strong>: {d.default_value}
                      <span style={{ color: '#888' }}> [{d.source}]</span>
                      {d.note && <div style={{ color: '#666', fontSize: 12, marginLeft: 16 }}>💡 {d.note}</div>}
                    </li>
                  ))}
                </ul>
              }
              style={{ marginTop: 12 }}
            />
          )}

          {result.placeholders.length === 0 && result.defaults_used.length === 0 && (
            <Alert
              type="success"
              showIcon
              icon={<CheckCircleOutlined />}
              message="✓ 所有用例字段完整，无占位符，未引用默认值"
              style={{ marginTop: 16 }}
            />
          )}
        </Card>
      )}
    </div>
  )
}
