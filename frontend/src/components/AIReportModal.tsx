/**
 * AI 报告生成弹窗组件。
 *
 * 功能：
 * - 调用后端 AI 生成测试报告（Markdown 格式）
 * - 报告预览（Markdown 渲染）
 * - 高亮关键发现
 * - 一键复制报告内容
 */
import { useState, useCallback } from 'react'
import {
  Modal, Button, Space, Alert, Spin, Typography, Tag, Divider,
  message, List, Empty,
} from 'antd'
import {
  FileTextOutlined, CopyOutlined, ReloadOutlined,
  WarningOutlined, CheckCircleOutlined, InfoCircleOutlined,
} from '@ant-design/icons'
import { generateReport } from '../api/axios'
import type { AIReport } from '../types'

const { Text, Title, Paragraph } = Typography

interface Props {
  open: boolean
  onClose: () => void
  hasCases: boolean
}

const HIGHLIGHT_ICONS: Record<string, React.ReactNode> = {
  warning: <WarningOutlined style={{ color: '#faad14' }} />,
  success: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
  info: <InfoCircleOutlined style={{ color: '#1677ff' }} />,
  error: <WarningOutlined style={{ color: '#ff4d4f' }} />,
}

export default function AIReportModal({ open, onClose, hasCases }: Props) {
  const [loading, setLoading] = useState(false)
  const [report, setReport] = useState<AIReport | null>(null)
  const [error, setError] = useState<string | null>(null)

  const doGenerate = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await generateReport('markdown')
      setReport(res.data)
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || '报告生成失败'
      setError(detail)
    } finally {
      setLoading(false)
    }
  }, [])

  const handleCopy = async () => {
    if (!report?.report) return
    try {
      await navigator.clipboard.writeText(report.report)
      message.success('报告已复制到剪贴板')
    } catch {
      message.error('复制失败，请手动选择复制')
    }
  }

  const handleClose = () => {
    onClose()
  }

  return (
    <Modal
      title={
        <Space>
          <FileTextOutlined />
          <span>AI 测试报告</span>
        </Space>
      }
      open={open}
      onCancel={handleClose}
      width={780}
      footer={
        report ? (
          <Space>
            <Button icon={<CopyOutlined />} onClick={handleCopy}>
              复制报告
            </Button>
            <Button icon={<ReloadOutlined />} onClick={doGenerate} loading={loading}>
              重新生成
            </Button>
            <Button type="primary" onClick={handleClose}>
              关闭
            </Button>
          </Space>
        ) : null
      }
      destroyOnClose
    >
      {!hasCases ? (
        <Empty description="没有用例数据，请先上传 Excel 并执行测试" />
      ) : loading ? (
        <div style={{ textAlign: 'center', padding: '60px 0' }}>
          <Spin size="large" tip="AI 正在生成测试报告..." />
          <div style={{ marginTop: 16 }}>
            <Text type="secondary">这可能需要 10-30 秒，取决于用例数量</Text>
          </div>
        </div>
      ) : error ? (
        <div>
          <Alert type="error" message="报告生成失败" description={error} showIcon />
          <div style={{ textAlign: 'center', marginTop: 16 }}>
            <Button type="primary" onClick={doGenerate}>重试</Button>
          </div>
        </div>
      ) : report ? (
        <div>
          {/* 关键发现高亮 */}
          {report.highlights && report.highlights.length > 0 && (
            <>
              <Title level={5}>关键发现</Title>
              <List
                size="small"
                dataSource={report.highlights}
                renderItem={(item) => (
                  <List.Item>
                    <Space>
                      {HIGHLIGHT_ICONS[item.type] || <InfoCircleOutlined />}
                      <Text>{item.msg}</Text>
                    </Space>
                  </List.Item>
                )}
                style={{ marginBottom: 16 }}
              />
              <Divider style={{ margin: '8px 0 16px' }} />
            </>
          )}

          {/* Markdown 报告内容 */}
          <div
            style={{
              background: '#fafafa',
              border: '1px solid #f0f0f0',
              borderRadius: 8,
              padding: '16px 20px',
              maxHeight: 500,
              overflow: 'auto',
              whiteSpace: 'pre-wrap',
              fontFamily: 'monospace',
              fontSize: 13,
              lineHeight: 1.6,
            }}
          >
            {report.report}
          </div>

          {/* 元信息 */}
          {(report._model || report._tokens) && (
            <div style={{ marginTop: 12 }}>
              <Space style={{ fontSize: 11 }}>
                {report._model && <Tag color="default">{report._model}</Tag>}
                {report._tokens && <Text type="secondary">{report._tokens} tokens</Text>}
              </Space>
            </div>
          )}
        </div>
      ) : (
        <div style={{ textAlign: 'center', padding: '60px 0' }}>
          <Paragraph type="secondary" style={{ marginBottom: 24 }}>
            基于当前测试执行结果，AI 将自动生成结构化测试报告，包括：
            执行概况、失败分析、关键发现和改进建议。
          </Paragraph>
          <Button
            type="primary"
            size="large"
            icon={<FileTextOutlined />}
            onClick={doGenerate}
          >
            生成报告
          </Button>
        </div>
      )}
    </Modal>
  )
}
