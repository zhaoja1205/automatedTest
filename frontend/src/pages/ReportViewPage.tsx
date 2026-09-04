import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Card, Button, Space, Tag, Spin, message, Typography } from 'antd'
import {
  ArrowLeftOutlined,
  PrinterOutlined,
  FileExcelOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import { getReport, exportReport } from '../api/historyApi'
import type { TestReport } from '../types/history'

export default function ReportViewPage() {
  const { reportId } = useParams<{ reportId: string }>()
  const navigate = useNavigate()
  const [report, setReport] = useState<TestReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    const fetchReport = async () => {
      if (!reportId) return
      try {
        setLoading(true)
        setError(false)
        const res = await getReport(reportId)
        setReport(res.data)
      } catch {
        setError(true)
        message.error('加载报告失败')
      } finally {
        setLoading(false)
      }
    }
    fetchReport()
  }, [reportId])

  const handleExport = async (format: 'xlsx' | 'html') => {
    try {
      const res = await exportReport(reportId!, format)
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `${report?.title || 'report'}.${format}`
      a.click()
      URL.revokeObjectURL(url)
      message.success('导出成功')
    } catch {
      message.error('导出失败')
    }
  }

  const handlePrint = () => {
    window.print()
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '60vh' }}>
        <Spin size="large" tip="加载报告中..." />
      </div>
    )
  }

  if (error || !report) {
    return (
      <Card>
        <div style={{ textAlign: 'center', padding: 48 }}>
          <Typography.Text type="secondary">报告未找到或加载失败</Typography.Text>
          <div style={{ marginTop: 16 }}>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/records/reports')}>
              返回列表
            </Button>
          </div>
        </div>
      </Card>
    )
  }

  return (
    <>
      <style>{`
        @media print {
          .app-header, .app-sider, .ant-layout-sider, .toolbar-card { display: none !important; }
          .page-content { padding: 0 !important; margin: 0 !important; }
          .report-content { max-height: none !important; overflow: visible !important; }
        }
      `}</style>

      <div className="page-content" style={{ padding: 16 }}>
        {/* Top toolbar */}
        <Card className="toolbar-card" bodyStyle={{ padding: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Space>
              <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/records/reports')}>
                返回列表
              </Button>
              <Tag color={report.report_type === 'ai' ? 'purple' : 'blue'}>
                {report.report_type === 'ai' ? 'AI 报告' : '摘要报告'}
              </Tag>
            </Space>
            <Space>
              <Button icon={<FileExcelOutlined />} onClick={() => handleExport('xlsx')}>
                导出 Excel
              </Button>
              <Button icon={<FileTextOutlined />} onClick={() => handleExport('html')}>
                导出 HTML
              </Button>
              <Button icon={<PrinterOutlined />} onClick={handlePrint}>
                打印
              </Button>
            </Space>
          </div>
        </Card>

        {/* Report content area */}
        <Card style={{ marginTop: 12 }}>
          {report.format === 'html' ? (
            <div
              className="report-content"
              dangerouslySetInnerHTML={{ __html: report.content || '' }}
              style={{ maxHeight: 'calc(100vh - 280px)', overflow: 'auto' }}
            />
          ) : (
            <pre
              style={{
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
                fontFamily: 'monospace',
                fontSize: 13,
                lineHeight: 1.6,
                background: '#f8f9fa',
                padding: 16,
                borderRadius: 4,
                maxHeight: 'calc(100vh - 280px)',
                overflow: 'auto',
              }}
            >
              {report.content}
            </pre>
          )}
        </Card>

        {/* Report metadata footer */}
        <div
          style={{
            marginTop: 12,
            padding: '8px 16px',
            fontSize: 12,
            color: '#8c8c8c',
            display: 'flex',
            gap: 24,
            flexWrap: 'wrap',
          }}
        >
          <span>报告 ID: {report.report_id}</span>
          <span>生成时间: {report.created_at ? new Date(report.created_at).toLocaleString('zh-CN') : '-'}</span>
          <span>测试人: {report.tester_name || '-'}</span>
          <span>版本: {report.test_version || '-'}</span>
        </div>
      </div>
    </>
  )
}
