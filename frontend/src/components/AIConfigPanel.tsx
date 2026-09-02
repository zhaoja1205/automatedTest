/**
 * AI 配置面板组件。
 *
 * 功能：
 * - AI 总开关、Provider 选择（Claude/OpenAI/Ollama）
 * - API Key 输入（显示掩码，编辑时替换）
 * - 模型选择、自定义 URL
 * - 连接测试
 * - AI 判定和分析的子开关
 */
import { useState, useEffect, useCallback } from 'react'
import { isAxiosError } from 'axios'
import {
  Card, Form, Input, Select, Switch, Button, Space, Alert,
  Typography, Divider, InputNumber, Tooltip, Spin,
} from 'antd'
import {
  RobotOutlined, ApiOutlined, ThunderboltOutlined,
  CheckCircleOutlined, CloseCircleOutlined,
} from '@ant-design/icons'
import { getAIConfig, setAIConfig, testAIConnection } from '../api/axios'
import type { AIConfig } from '../types'

const { Text } = Typography

const PROVIDER_OPTIONS = [
  { value: 'claude', label: 'Claude (Anthropic)' },
  { value: 'openai', label: 'OpenAI / 兼容 API' },
  { value: 'ollama', label: 'Ollama (本地模型)' },
]

const MODEL_PRESETS: Record<string, { value: string; label: string }[]> = {
  claude: [
    { value: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5 (推荐·快速)' },
    { value: 'claude-sonnet-4-20250514', label: 'Claude Sonnet 4' },
    { value: 'claude-opus-4-20250514', label: 'Claude Opus 4 (最强)' },
  ],
  openai: [
    { value: 'gpt-4o-mini', label: 'GPT-4o Mini (推荐·快速)' },
    { value: 'gpt-4o', label: 'GPT-4o' },
    { value: 'gpt-4-turbo', label: 'GPT-4 Turbo' },
  ],
  ollama: [
    { value: 'qwen2.5:7b', label: 'Qwen2.5 7B (推荐)' },
    { value: 'llama3.1:8b', label: 'Llama 3.1 8B' },
    { value: 'mistral:7b', label: 'Mistral 7B' },
  ],
}

export default function AIConfigPanel() {
  const [form] = Form.useForm<AIConfig>()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null)
  const [config, setConfig] = useState<AIConfig | null>(null)
  const [error, setError] = useState<string | null>(null)

  const currentProvider = Form.useWatch('ai_provider', form) || 'claude'

  const getErrorMessage = (err: unknown, fallback: string) => {
    if (isAxiosError<{ detail?: string }>(err)) {
      return err.response?.data?.detail || err.message || fallback
    }
    if (err instanceof Error) return err.message
    return fallback
  }

  const loadConfig = useCallback(async () => {
    setLoading(true)
    try {
      const res = await getAIConfig()
      setConfig(res.data)
      form.setFieldsValue(res.data)
      setError(null)
    } catch (err) {
      setError(getErrorMessage(err, '加载 AI 配置失败'))
    } finally {
      setLoading(false)
    }
  }, [form])

  useEffect(() => {
    loadConfig()
  }, [loadConfig])

  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      setTestResult(null)
      await setAIConfig(values)
      await loadConfig()
    } catch (err) {
      setError(getErrorMessage(err, '保存 AI 配置失败'))
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    // 先保存再测试
    try {
      const values = await form.validateFields()
      setTesting(true)
      setTestResult(null)
      await setAIConfig(values)
      const res = await testAIConnection()
      setTestResult(res.data)
    } catch (err) {
      setTestResult({ ok: false, message: getErrorMessage(err, '连接测试失败') })
    } finally {
      setTesting(false)
    }
  }

  if (loading) {
    return (
      <Card>
        <Spin tip="加载 AI 配置..." />
      </Card>
    )
  }

  return (
    <Card
      title={
        <Space>
          <RobotOutlined />
          <span>AI 智能辅助配置</span>
        </Space>
      }
      extra={
        <Space>
          <Button
            icon={<ApiOutlined spin={testing} />}
            onClick={handleTest}
            loading={testing}
          >
            测试连接
          </Button>
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            onClick={handleSave}
            loading={saving}
          >
            保存配置
          </Button>
        </Space>
      }
    >
      {error && (
        <Alert
          type="error"
          message={error}
          closable
          onClose={() => setError(null)}
          style={{ marginBottom: 16 }}
        />
      )}

      {testResult && (
        <Alert
          type={testResult.ok ? 'success' : 'error'}
          message={testResult.ok ? 'AI 连接成功' : 'AI 连接失败'}
          description={testResult.message}
          icon={testResult.ok ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
          showIcon
          closable
          onClose={() => setTestResult(null)}
          style={{ marginBottom: 16 }}
        />
      )}

      <Form
        form={form}
        layout="vertical"
        size="small"
        initialValues={config || {}}
      >
        {/* 总开关 */}
        <Form.Item
          name="ai_enabled"
          label={<Text strong>启用 AI 功能</Text>}
          valuePropName="checked"
        >
          <Switch
            checkedChildren="已启用"
            unCheckedChildren="已禁用"
          />
        </Form.Item>

        <Divider style={{ margin: '12px 0' }} />

        {/* Provider 选择 */}
        <Form.Item
          name="ai_provider"
          label="AI 服务商"
          rules={[{ required: true }]}
        >
          <Select options={PROVIDER_OPTIONS} />
        </Form.Item>

        {/* API Key（Claude/OpenAI 需要，Ollama 不需要）*/}
        {currentProvider !== 'ollama' && (
          <Form.Item
            name="ai_api_key"
            label="API Key"
            extra={
              config?.ai_api_key_masked
                ? <Text type="secondary">当前: {config.ai_api_key_masked}（留空保留原密钥）</Text>
                : <Text type="secondary">尚未配置 API Key</Text>
            }
          >
            <Input.Password placeholder="输入新的 API Key（留空保留已有）" />
          </Form.Item>
        )}

        {/* 模型选择 */}
        <Form.Item name="ai_model" label="模型">
          <Select
            options={MODEL_PRESETS[currentProvider] || []}
            showSearch
            allowClear
            placeholder="选择或输入自定义模型名称"
          />
        </Form.Item>

        {/* 自定义 URL（主要给 Ollama 和代理用）*/}
        <Form.Item
          name="ai_base_url"
          label={
            <Tooltip title="Ollama 默认 http://localhost:11434，Claude/OpenAI 留空使用官方 API">
              自定义 API URL
            </Tooltip>
          }
        >
          <Input
            placeholder={
              currentProvider === 'ollama'
                ? 'http://localhost:11434（默认）'
                : '留空使用官方 API 地址'
            }
          />
        </Form.Item>

        <Divider style={{ margin: '12px 0' }}>
          <Text type="secondary">功能开关</Text>
        </Divider>

        {/* AI 判定不确定时 fallback */}
        <Form.Item
          name="ai_judge_uncertain"
          label={
            <Tooltip title="当规则引擎置信度 < 0.8 时，调用 AI 做语义级 Pass/Fail 判定">
              规则不确定时调用 AI 判定
            </Tooltip>
          }
          valuePropName="checked"
        >
          <Switch
            checkedChildren="开"
            unCheckedChildren="关"
          />
        </Form.Item>

        {/* 自动分析所有 Fail */}
        <Form.Item
          name="ai_auto_analyze"
          label={
            <Tooltip title="执行完成后自动分析所有 Fail 用例，生成失败原因摘要">
              自动分析所有 Fail 用例
            </Tooltip>
          }
          valuePropName="checked"
        >
          <Switch
            checkedChildren="开"
            unCheckedChildren="关"
          />
        </Form.Item>

        {/* 缓存 TTL */}
        <Form.Item name="ai_cache_ttl_hours" label="缓存有效期（小时）">
          <InputNumber min={1} max={168} style={{ width: 120 }} />
        </Form.Item>
      </Form>
    </Card>
  )
}
