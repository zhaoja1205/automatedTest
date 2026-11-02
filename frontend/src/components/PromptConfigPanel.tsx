/**
 * AI 系统提示词配置面板（独立页面）。
 *
 * 默认提示词直接填入编辑框；用户修改后按功能保存为自定义提示词，
 * 与内置默认一致的内容不会写入配置，避免无意义地复制默认文本。
 */
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { isAxiosError } from 'axios'
import {
  Alert, Button, Card, Divider, Input, Popconfirm, Select, Space, Spin,
  Tabs, Tag, Typography, message,
} from 'antd'
import {
  EditOutlined, ReloadOutlined, SaveOutlined, SettingOutlined, SwapOutlined,
} from '@ant-design/icons'
import {
  activateAIProfile, getAIConfig, listAIProfiles, listAISystemPrompts,
  setAISystemPrompts,
} from '../api/axios'
import type { AIProfileSummary, AISystemPromptFeature } from '../types'

const { Text } = Typography

export default function PromptConfigPanel() {
  const navigate = useNavigate()
  const [features, setFeatures] = useState<AISystemPromptFeature[]>([])
  const [promptValues, setPromptValues] = useState<Record<string, string>>({})
  const [profiles, setProfiles] = useState<AIProfileSummary[]>([])
  const [activeProfileId, setActiveProfileId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [switching, setSwitching] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const getErrorMessage = (err: unknown, fallback: string) => {
    if (isAxiosError<{ detail?: string }>(err)) {
      return err.response?.data?.detail || err.message || fallback
    }
    if (err instanceof Error) return err.message
    return fallback
  }

  const loadData = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const [configRes, promptsRes, profilesRes] = await Promise.all([
        getAIConfig(),
        listAISystemPrompts(),
        listAIProfiles(),
      ])
      const promptFeatures = promptsRes.data.prompts
      const config = configRes.data

      // 输入框始终显示“实际生效”的提示词：有自定义值用自定义，否则用默认值
      const effective: Record<string, string> = {}
      for (const feature of promptFeatures) {
        const custom = config.ai_system_prompts?.[feature.key]
        effective[feature.key] = custom && custom.trim()
          ? custom
          : feature.default_prompt
      }

      setFeatures(promptFeatures)
      setPromptValues(effective)
      setProfiles(profilesRes.data.profiles)
      setActiveProfileId(profilesRes.data.active_id)
      setError(null)
    } catch (err) {
      setError(getErrorMessage(err, '加载提示词配置失败'))
    } finally {
      if (!silent) setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadData()
  }, [loadData])

  const updateValue = (key: string, value: string) => {
    setPromptValues((prev) => ({ ...prev, [key]: value }))
  }

  const isModified = (feature: AISystemPromptFeature) =>
    (promptValues[feature.key] ?? feature.default_prompt).trim()
      !== feature.default_prompt.trim()

  const modifiedCount = features.filter(isModified).length

  /** 输入框被清空时自动恢复默认文本，保证默认提示词始终可见。 */
  const handleBlur = (feature: AISystemPromptFeature) => {
    if (!(promptValues[feature.key] || '').trim()) {
      updateValue(feature.key, feature.default_prompt)
    }
  }

  const resetOne = (feature: AISystemPromptFeature) => {
    updateValue(feature.key, feature.default_prompt)
  }

  const resetAll = () => {
    const defaults: Record<string, string> = {}
    for (const feature of features) {
      defaults[feature.key] = feature.default_prompt
    }
    setPromptValues(defaults)
    message.success('已恢复全部默认提示词，点击「保存提示词」后生效')
  }

  const handleSave = async () => {
    if (!activeProfileId) {
      message.warning('请先在 AI 配置方案中新增并激活一套方案')
      return
    }
    setSaving(true)
    setError(null)
    try {
      // 只有与默认值不同的内容才写为自定义提示词
      const custom: Record<string, string> = {}
      for (const feature of features) {
        const value = (promptValues[feature.key] ?? feature.default_prompt).trim()
        if (value && value !== feature.default_prompt.trim()) {
          custom[feature.key] = value
        }
      }
      await setAISystemPrompts(custom)
      await loadData(true)
      message.success('提示词配置已保存')
    } catch (err) {
      setError(getErrorMessage(err, '保存提示词配置失败'))
    } finally {
      setSaving(false)
    }
  }

  const handleSwitchProfile = async (id: string) => {
    if (!id || id === activeProfileId) return
    setSwitching(true)
    setError(null)
    try {
      await activateAIProfile(id)
      await loadData(true)
      message.success('已切换配置方案')
    } catch (err) {
      setError(getErrorMessage(err, '切换配置方案失败'))
    } finally {
      setSwitching(false)
    }
  }

  if (loading) {
    return (
      <Card>
        <Spin tip="加载提示词配置..." />
      </Card>
    )
  }

  return (
    <Card
      title={
        <Space>
          <EditOutlined />
          <span style={{ fontSize: 15, fontWeight: 600 }}>提示词配置</span>
        </Space>
      }
      extra={
        <Space>
          <Popconfirm
            title="恢复所有功能的默认提示词？"
            description="输入框将全部恢复为内置默认文本，保存后生效。"
            okText="恢复"
            cancelText="取消"
            onConfirm={resetAll}
            disabled={!activeProfileId || modifiedCount === 0}
          >
            <Button
              icon={<ReloadOutlined />}
              disabled={!activeProfileId || modifiedCount === 0}
            >
              全部恢复默认
            </Button>
          </Popconfirm>
          <Button
            type="primary"
            icon={<SaveOutlined />}
            loading={saving}
            onClick={handleSave}
            disabled={!activeProfileId}
          >
            保存提示词
          </Button>
        </Space>
      }
      style={{ maxWidth: 980 }}
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

      <div
        style={{
          marginBottom: 14,
          padding: '12px 14px',
          background: 'rgba(22, 119, 255, 0.04)',
          border: '1px solid rgba(22, 119, 255, 0.15)',
          borderRadius: 8,
        }}
      >
        <Space wrap>
          <Space size={6}>
            <SwapOutlined style={{ color: '#1677ff' }} />
            <Text strong style={{ fontSize: 14 }}>当前配置方案</Text>
          </Space>
          <Select
            style={{ minWidth: 240 }}
            placeholder={profiles.length ? '选择已保存的方案' : '暂无已保存的方案'}
            value={activeProfileId ?? undefined}
            onChange={handleSwitchProfile}
            options={profiles.map((p) => ({
              value: p.id,
              label: `${p.name}（${p.ai_model || p.ai_protocol}）`,
            }))}
            disabled={switching}
            loading={switching}
            allowClear={false}
          />
          <Button
            icon={<SettingOutlined />}
            onClick={() => navigate('/config/ai')}
          >
            管理方案
          </Button>
        </Space>
        <div style={{ marginTop: 6 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            提示词随当前方案保存；切换方案后会载入该方案对应的提示词。
          </Text>
        </div>
      </div>

      {!activeProfileId && (
        <Alert
          type="info"
          showIcon
          message="请先创建 AI 配置方案"
          description="提示词需要保存到某套 AI 配置方案中。请先前往「AI 配置方案」新增方案。"
          style={{ marginBottom: 16 }}
        />
      )}

      <div style={{ marginBottom: 8 }}>
        <Text strong>共 {features.length} 个 AI 功能</Text>
        {modifiedCount > 0 ? (
          <Text type="secondary" style={{ marginLeft: 8 }}>
            已修改 {modifiedCount} 项，保存后作为自定义提示词生效
          </Text>
        ) : (
          <Text type="secondary" style={{ marginLeft: 8 }}>
            当前输入框显示内置默认提示词，可直接编辑
          </Text>
        )}
      </div>

      <Divider style={{ margin: '10px 0' }} />

      <Tabs
        tabPosition="left"
        items={features.map((feature) => {
          const value = promptValues[feature.key] ?? feature.default_prompt
          const modified = isModified(feature)
          return {
            key: feature.key,
            label: (
              <Space size={6}>
                <span>{feature.name}</span>
                {modified && (
                  <span
                    style={{
                      display: 'inline-block',
                      width: 6,
                      height: 6,
                      borderRadius: '50%',
                      background: '#1677ff',
                    }}
                  />
                )}
              </Space>
            ),
            children: (
              <div style={{ minHeight: 360 }}>
                <Space align="center" wrap>
                  <Text strong style={{ fontSize: 15 }}>{feature.name}</Text>
                  {modified
                    ? <Tag color="blue">已修改</Tag>
                    : <Tag>默认提示词</Tag>}
                </Space>
                <div style={{ margin: '4px 0 10px' }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {feature.description}
                  </Text>
                </div>
                <Input.TextArea
                  value={value}
                  onChange={(e) => updateValue(feature.key, e.target.value)}
                  onBlur={() => handleBlur(feature)}
                  disabled={!activeProfileId}
                  autoSize={{ minRows: 14, maxRows: 24 }}
                  style={{
                    fontSize: 13,
                    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
                  }}
                />
                <div
                  style={{
                    marginTop: 8,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 10,
                    flexWrap: 'wrap',
                  }}
                >
                  <Button
                    size="small"
                    icon={<ReloadOutlined />}
                    onClick={() => resetOne(feature)}
                    disabled={!activeProfileId || !modified}
                  >
                    恢复默认
                  </Button>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {value.length} 字符
                  </Text>
                  {modified && (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      与默认提示词不同，保存后作为自定义提示词生效
                    </Text>
                  )}
                </div>
              </div>
            ),
          }
        })}
      />
    </Card>
  )
}
