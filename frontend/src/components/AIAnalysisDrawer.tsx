/**
 * AI 失败分析抽屉组件。
 *
 * 功能：
 * - 单用例 AI 失败分析（展示根因分类、摘要、证据、建议）
 * - 分析结果缓存（同一用例不重复调用）
 * - 置信度可视化
 */
import { useState, useEffect, useCallback } from 'react'
import {
  Drawer, Button, Tag, Space, Alert, Spin, Typography,
  Progress, Descriptions, List, Divider, Card, Empty,
} from 'antd'
import {
  BugOutlined, ExperimentOutlined,
  EnvironmentOutlined, SyncOutlined, QuestionCircleOutlined,
  BulbOutlined, CheckCircleOutlined, ReloadOutlined,
} from '@ant-design/icons'
import { analyzeFailure } from '../api/axios'
import type { AIAnalysis, TestCase } from '../types'

const { Text, Title, Paragraph } = Typography

// 根因分类图标和颜色
const CATEGORY_MAP: Record<string, { label: string; icon: React.ReactNode; color: string }> = {
  environment: { label: '环境问题', icon: <EnvironmentOutlined />, color: 'blue' },
  defect:      { label: '软件缺陷', icon: <BugOutlined />, color: 'red' },
  test_issue:  { label: '用例问题', icon: <ExperimentOutlined />, color: 'orange' },
  flaky:       { label: '偶发失败', icon: <SyncOutlined />, color: 'purple' },
  mismatch:    { label: '预期偏差', icon: <QuestionCircleOutlined />, color: 'gold' },
}

interface Props {
  open: boolean
  onClose: () => void
  /** 当前正在分析的用例 */
  testCase: TestCase | null
  /** 缓存的分析结果（父组件管理） */
  cachedAnalysis?: AIAnalysis | null
  /** 分析完成回调（供父组件缓存结果） */
  onAnalysisDone?: (caseKey: string, analysis: AIAnalysis) => void
}

export default function AIAnalysisDrawer({
  open, onClose, testCase, cachedAnalysis, onAnalysisDone,
}: Props) {
  const [loading, setLoading] = useState(false)
  const [analysis, setAnalysis] = useState<AIAnalysis | null>(null)
  const [error, setError] = useState<string | null>(null)

  // 有缓存则直接使用
  useEffect(() => {
    if (cachedAnalysis) {
      setAnalysis(cachedAnalysis)
      setError(null)
    } else {
      setAnalysis(null)
    }
  }, [cachedAnalysis, testCase])

  const doAnalyze = useCallback(async () => {
    if (!testCase) return
    setLoading(true)
    setError(null)
    try {
      const caseKey = testCase.case_key || testCase.case_id
      const res = await analyzeFailure(caseKey)
      const result = res.data.analysis
      setAnalysis(result)
      // 回调供父组件缓存
      if (onAnalysisDone) {
        onAnalysisDone(caseKey, result)
      }
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || '分析失败'
      setError(detail)
    } finally {
      setLoading(false)
    }
  }, [testCase, onAnalysisDone])

  // 打开时如果没有缓存，自动触发分析
  useEffect(() => {
    if (open && testCase && !cachedAnalysis && !analysis && !loading) {
      doAnalyze()
    }
  }, [open, testCase, cachedAnalysis, analysis, loading, doAnalyze])

  const cat = analysis ? CATEGORY_MAP[analysis.root_cause_category] : null

  return (
    <Drawer
      title={
        <Space>
          <BulbOutlined />
          <span>AI 失败分析</span>
          {testCase && <Tag>{testCase.case_id}</Tag>}
        </Space>
      }
      open={open}
      onClose={onClose}
      width={520}
      extra={
        analysis && (
          <Button
            icon={<ReloadOutlined />}
            size="small"
            onClick={doAnalyze}
            loading={loading}
          >
            重新分析
          </Button>
        )
      }
    >
      {!testCase ? (
        <Empty description="未选择用例" />
      ) : loading ? (
        <div style={{ textAlign: 'center', padding: '60px 0' }}>
          <Spin size="large" tip="AI 正在分析失败原因..." />
        </div>
      ) : error ? (
        <div>
          <Alert type="error" message="分析失败" description={error} showIcon />
          <div style={{ textAlign: 'center', marginTop: 16 }}>
            <Button type="primary" onClick={doAnalyze}>重试</Button>
          </div>
        </div>
      ) : analysis ? (
        <div>
          {/* 根因分类 + 置信度 */}
          <Card size="small" style={{ marginBottom: 16 }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Space>
                <Tag
                  icon={cat?.icon}
                  color={cat?.color || 'default'}
                  style={{ fontSize: 14, padding: '4px 12px' }}
                >
                  {cat?.label || analysis.root_cause_category}
                </Tag>
                {analysis.is_likely_real_bug && (
                  <Tag color="red" icon={<BugOutlined />}>疑似真实缺陷</Tag>
                )}
                {analysis._from_cache && (
                  <Tag color="default" style={{ fontSize: 11 }}>缓存</Tag>
                )}
              </Space>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>置信度</Text>
                <Progress
                  percent={Math.round(analysis.confidence * 100)}
                  size="small"
                  strokeColor={
                    analysis.confidence >= 0.8 ? '#52c41a'
                    : analysis.confidence >= 0.6 ? '#faad14'
                    : '#ff4d4f'
                  }
                />
              </div>
            </Space>
          </Card>

          {/* 根因摘要 */}
          <Descriptions column={1} size="small" bordered style={{ marginBottom: 16 }}>
            <Descriptions.Item label="根因摘要">
              <Text strong>{analysis.root_cause_summary}</Text>
            </Descriptions.Item>
          </Descriptions>

          {/* 详细分析 */}
          <Title level={5}>详细分析</Title>
          <Paragraph style={{ whiteSpace: 'pre-wrap', fontSize: 13, background: '#f5f5f5', padding: 12, borderRadius: 6 }}>
            {analysis.explanation}
          </Paragraph>

          {/* 证据 */}
          {analysis.evidence && analysis.evidence.length > 0 && (
            <>
              <Divider style={{ margin: '12px 0' }} />
              <Title level={5}>
                <CheckCircleOutlined style={{ marginRight: 6 }} />
                关键证据
              </Title>
              <List
                size="small"
                bordered
                dataSource={analysis.evidence}
                renderItem={(item) => (
                  <List.Item>
                    <Text code style={{ fontSize: 12, wordBreak: 'break-all' }}>{item}</Text>
                  </List.Item>
                )}
              />
            </>
          )}

          {/* 修复建议 */}
          {analysis.suggestion && analysis.suggestion.length > 0 && (
            <>
              <Divider style={{ margin: '12px 0' }} />
              <Title level={5}>
                <BulbOutlined style={{ marginRight: 6 }} />
                修复建议
              </Title>
              <List
                size="small"
                dataSource={analysis.suggestion}
                renderItem={(item, idx) => (
                  <List.Item>
                    <Text>{idx + 1}. {item}</Text>
                  </List.Item>
                )}
              />
            </>
          )}

          {/* 元信息 */}
          {(analysis._model || analysis._tokens) && (
            <>
              <Divider style={{ margin: '12px 0' }} />
              <Space style={{ fontSize: 11 }}>
                {analysis._model && <Tag color="default">{analysis._model}</Tag>}
                {analysis._tokens && <Text type="secondary">{analysis._tokens} tokens</Text>}
              </Space>
            </>
          )}
        </div>
      ) : (
        <div style={{ textAlign: 'center', padding: '60px 0' }}>
          <Button type="primary" icon={<BulbOutlined />} onClick={doAnalyze}>
            开始 AI 分析
          </Button>
        </div>
      )}
    </Drawer>
  )
}
