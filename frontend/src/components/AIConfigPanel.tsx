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
  Typography, Divider, InputNumber, Tooltip, Spin, Radio,
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
    // —— 中智 ThunderSoft 网关模型（需配合 https://llm.thundersoft.com）——
    { value: 'ts-pri-auto', label: 'TS 自动路由 (推荐·均衡)' },
    { value: 'ts-gpt-55', label: 'TS GPT-5.5' },
    { value: 'ts-opus-46', label: 'TS Claude Opus 4.6 (最强)' },
    { value: 'ts-pri-glm', label: 'TS GLM (快速)' },
    { value: 'ts-pri-kimi', label: 'TS Kimi (中文优化)' },
    { value: 'ts-pri-deepseek', label: 'TS DeepSeek' },
    // —— Anthropic 原生模型（需官方 API Key + 留空 URL）——
    { value: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5 (Anthropic 直连)' },
    { value: 'claude-sonnet-4-20250514', label: 'Claude Sonnet 4 (Anthropic 直连)' },
    { value: 'claude-opus-4-20250514', label: 'Claude Opus 4 (Anthropic 直连)' },
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
          <span style={{ fontSize: 15, fontWeight: 600 }}>AI 智能辅助配置</span>
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
      style={{ maxWidth: 560 }}
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
        initialValues={config || {}}
      >
        {/* 总开关 */}
        <Form.Item
          name="ai_enabled"
          label={<Text strong style={{ fontSize: 14 }}>启用 AI 功能</Text>}
          valuePropName="checked"
        >
          <Switch
            checkedChildren="已启用"
            unCheckedChildren="已禁用"
            style={{ minWidth: 80 }}
          />
        </Form.Item>

        <Divider style={{ margin: '12px 0' }} />

        {/* Provider 选择 */}
        <Form.Item
          name="ai_provider"
          label="AI 服务商"
          rules={[{ required: true }]}
          style={{ maxWidth: 320 }}
        >
          <Select options={PROVIDER_OPTIONS} />
        </Form.Item>

        {/* API Key（Claude/OpenAI 需要，Ollama 不需要）*/}
        {currentProvider !== 'ollama' && (
          <Form.Item
            name="ai_api_key"
            label="API Key"
            style={{ maxWidth: 400 }}
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
        <Form.Item name="ai_model" label="模型" style={{ maxWidth: 320 }}>
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
            <Tooltip title="中智网关填 https://llm.thundersoft.com；Ollama 默认 http://localhost:11434；Anthropic/OpenAI 官方留空">
              自定义 API URL
            </Tooltip>
          }
          style={{ maxWidth: 400 }}
        >
          <Input
            placeholder={
              currentProvider === 'ollama'
                ? 'http://localhost:11434（默认）'
                : 'https://llm.thundersoft.com（中智网关）或留空用官方 API'
            }
          />
        </Form.Item>

        <Divider style={{ margin: '12px 0' }}>
          <Text type="secondary">功能开关</Text>
        </Divider>

        {/* AI 判定模式 */}
        <Form.Item
          name="ai_judge_mode"
          label={
            <Tooltip title="始终: 每个用例执行后 AI 根据 log 判定 Pass/Fail；仅不确定时: 规则引擎置信度低时才调 AI；关闭: 仅用规则引擎">
              AI 判定模式
            </Tooltip>
          }
        >
          <Radio.Group buttonStyle="solid" size="small">
            <Radio.Button value="always">始终 AI 判定</Radio.Button>
            <Radio.Button value="uncertain">仅不确定时</Radio.Button>
            <Radio.Button value="off">关闭</Radio.Button>
          </Radio.Group>
        </Form.Item>

        {/* AI 步骤智能识别 */}
        <Form.Item
          name="ai_auto_parse_steps"
          label={
            <Tooltip title="上传用例后自动调用 AI 识别测试步骤中的命令，提高未识别步骤的覆盖率">
              <Text strong style={{ fontSize: 14 }}>AI 识别测试步骤</Text>
            </Tooltip>
          }
          valuePropName="checked"
        >
          <Switch
            checkedChildren="开"
            unCheckedChildren="关"
            style={{ minWidth: 60 }}
          />
        </Form.Item>

        {/* 自动分析所有 Fail */}
        <Form.Item
          name="ai_auto_analyze"
          label={
            <Tooltip title="执行完成后自动分析所有 Fail 用例，生成失败原因摘要">
              <Text strong style={{ fontSize: 14 }}>自动分析所有 Fail 用例</Text>
            </Tooltip>
          }
          valuePropName="checked"
        >
          <Switch
            checkedChildren="开"
            unCheckedChildren="关"
            style={{ minWidth: 60 }}
          />
        </Form.Item>

        {/* 缓存 TTL */}
        <Form.Item name="ai_cache_ttl_hours" label="缓存有效期（小时）" style={{ maxWidth: 180 }}>
          <InputNumber min={1} max={168} style={{ width: 120 }} />
        </Form.Item>
      </Form>
    </Card>
  )
}
