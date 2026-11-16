/**
 * SSH 配置独立页面 — 从 Dashboard 弹窗提取为独立路由
 *
 * 支持把多套 SSH 配置保存在浏览器 localStorage 中（例如不同板端、
 * 直连/跳板环境），在下拉框中随时切换；切换后会同步到后端作为当前配置。
 */
import { useState, useEffect } from 'react'
import { isAxiosError } from 'axios'
import {
  Card, Form, Input, InputNumber, Radio, Button, Space, Alert, message,
  Select, Modal, Typography,
} from 'antd'
import {
  SyncOutlined, SaveOutlined, ApiOutlined, PlusOutlined, DeleteOutlined,
} from '@ant-design/icons'
import { useStore } from '../stores/useStore'
import { getSSHConfig, getSSHStatus, setSSHConfig as apiSetSSHConfig, testSSHConnection } from '../api/axios'
import {
  createSSHProfileId,
  isSSHConfigChanged,
  loadSSHProfiles,
  saveSSHProfiles,
  suggestSSHProfileName,
} from '../utils/sshConfigStorage'
import type { SSHConfigProfile } from '../utils/sshConfigStorage'
import type { SSHConfig, SSHLoginMode } from '../types'

const { Text } = Typography

const getErrorMessage = (error: unknown, fallback: string) => {
  if (isAxiosError<{ detail?: string }>(error))
    return error.response?.data?.detail || error.message || fallback
  if (error instanceof Error) return error.message
  return fallback
}

export default function SSHConfigPage() {
  const setSSHConfig = useStore(s => s.setSSHConfig)
  const setSSHStatus = useStore(s => s.setSSHStatus)
  const sshConfig = useStore(s => s.sshConfig)
  const sshStatus = useStore(s => s.sshStatus)
  const [form] = Form.useForm<SSHConfig>()
  const [testingSSH, setTestingSSH] = useState(false)
  const [saving, setSaving] = useState(false)
  const currentMode = Form.useWatch('login_mode', form) || 'direct'

  // 浏览器本地配置集
  const [profiles, setProfiles] = useState<SSHConfigProfile[]>([])
  const [activeProfileId, setActiveProfileId] = useState<string | null>(null)
  const [switchingProfile, setSwitchingProfile] = useState(false)
  const [profileModalOpen, setProfileModalOpen] = useState(false)
  const [profileName, setProfileName] = useState('')
  const [profileSaving, setProfileSaving] = useState(false)

  const activeProfile = activeProfileId
    ? profiles.find(p => p.id === activeProfileId) || null
    : null

  /** 更新本地配置集（同时写入 localStorage） */
  const persistProfiles = (nextProfiles: SSHConfigProfile[], nextActiveId: string | null) => {
    setProfiles(nextProfiles)
    setActiveProfileId(nextActiveId)
    saveSSHProfiles({ profiles: nextProfiles, activeId: nextActiveId })
  }

  useEffect(() => {
    let cancelled = false
    const stored = loadSSHProfiles()
    setProfiles(stored.profiles)
    setActiveProfileId(stored.activeId)
    const localActive = stored.profiles.find(p => p.id === stored.activeId) || null

    ;(async () => {
      try {
        const [ssh, status] = await Promise.all([getSSHConfig(), getSSHStatus()])
        if (cancelled) return
        // 已选中的本地配置优先（新标签页/浏览器重启后恢复），并同步到后端
        const initial = localActive?.config ?? ssh.data
        form.setFieldsValue(initial)
        setSSHConfig(initial)
        if (localActive) {
          setSSHStatus({
            connected: false,
            tested: false,
            mode: initial.login_mode,
            message: `已载入本地配置「${localActive.name}」，请点击"测试连接"确认`,
          })
          if (isSSHConfigChanged(localActive.config, ssh.data)) {
            try {
              await apiSetSSHConfig(localActive.config)
            } catch (syncErr) {
              if (!cancelled) {
                setSSHStatus({
                  connected: false,
                  tested: false,
                  mode: initial.login_mode,
                  message: `本地配置「${localActive.name}」已载入，但同步到后端失败`,
                })
                message.warning(`本地配置已载入，但${getErrorMessage(syncErr, '同步到后端失败')}`)
              }
            }
          }
        } else {
          setSSHStatus(status.data)
        }
      } catch (err) {
        if (cancelled) return
        if (localActive) {
          form.setFieldsValue(localActive.config)
          setSSHConfig(localActive.config)
          setSSHStatus({
            connected: false,
            tested: false,
            mode: localActive.config.login_mode,
            message: `后端配置加载失败，已使用本地配置「${localActive.name}」`,
          })
          message.warning(getErrorMessage(err, '后端 SSH 配置加载失败，已使用浏览器本地配置'))
        } else {
          message.warning(getErrorMessage(err, '加载 SSH 配置失败'))
        }
      }
    })()
    return () => { cancelled = true }
  }, [form, setSSHConfig, setSSHStatus])

  const handleSave = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      await apiSetSSHConfig(values)
      setSSHConfig(values)
      setSSHStatus({
        connected: false, tested: false, mode: values.login_mode,
        message: 'SSH 配置已更新，请点击"测试连接"确认',
      })
      // 有选中的本地配置时，同步更新该份快照
      if (activeProfile) {
        const nextProfiles = profiles.map(p => p.id === activeProfile.id
          ? { ...p, config: values, updatedAt: Date.now() }
          : p)
        persistProfiles(nextProfiles, activeProfile.id)
      }
      message.success('SSH 配置已保存')
    } catch (err) {
      message.error(getErrorMessage(err, '保存失败'))
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    try {
      const values = await form.validateFields()
      setTestingSSH(true)
      const res = await testSSHConnection(values)
      setSSHConfig(values)
      setSSHStatus(res.data)
      message.success(res.data.message)
    } catch (err) {
      setSSHStatus({
        connected: false, tested: true, mode: form.getFieldValue('login_mode') || 'direct',
        message: getErrorMessage(err, 'SSH 连接测试失败'),
      })
      message.error(getErrorMessage(err, 'SSH 连接测试失败'))
    } finally {
      setTestingSSH(false)
    }
  }

  /** 把选中的本地配置载入表单，并同步到后端作为当前配置 */
  const applyProfile = async (profile: SSHConfigProfile) => {
    setSwitchingProfile(true)
    form.setFieldsValue(profile.config)
    persistProfiles(profiles, profile.id)
    try {
      await apiSetSSHConfig(profile.config)
      setSSHConfig(profile.config)
      setSSHStatus({
        connected: false, tested: false, mode: profile.config.login_mode,
        message: `已切换到本地配置「${profile.name}」，请点击"测试连接"确认`,
      })
      message.success(`已切换到本地配置「${profile.name}」`)
    } catch (err) {
      setSSHConfig(profile.config)
      setSSHStatus({
        connected: false, tested: false, mode: profile.config.login_mode,
        message: `本地配置「${profile.name}」已载入，但同步到后端失败`,
      })
      message.warning(`已载入本地配置「${profile.name}」，但${getErrorMessage(err, '同步到后端失败')}`)
    } finally {
      setSwitchingProfile(false)
    }
  }

  const handleSelectProfile = (id?: string) => {
    if (switchingProfile) return
    if (!id) {
      persistProfiles(profiles, null)
      return
    }
    const profile = profiles.find(p => p.id === id)
    if (!profile) return

    const currentValues = form.getFieldsValue() as SSHConfig
    const savedValues = activeProfile?.config ?? sshConfig
    if (savedValues && isSSHConfigChanged(currentValues, savedValues)) {
      Modal.confirm({
        title: '当前配置有未保存的修改',
        content: '切换本地配置会覆盖当前表单内容，未保存的修改将丢失。',
        okText: '继续切换',
        cancelText: '取消',
        onOk: () => applyProfile(profile),
      })
      return
    }
    void applyProfile(profile)
  }

  /** 保存当前表单到本地配置（已有选中配置时覆盖它） */
  const handleSaveLocal = async () => {
    let values: SSHConfig
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    if (activeProfile) {
      const nextProfiles = profiles.map(p => p.id === activeProfile.id
        ? { ...p, config: values, updatedAt: Date.now() }
        : p)
      persistProfiles(nextProfiles, activeProfile.id)
      message.success(`已更新本地配置「${activeProfile.name}」`)
      return
    }
    setProfileName(suggestSSHProfileName(values, profiles.length))
    setProfileModalOpen(true)
  }

  /** 另存为一份新的本地配置 */
  const handleSaveAs = async () => {
    let values: SSHConfig
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    setProfileName(activeProfile
      ? `${activeProfile.name} 副本`
      : suggestSSHProfileName(values, profiles.length))
    setProfileModalOpen(true)
  }

  const handleProfileModalOk = async () => {
    if (profileSaving) return
    const name = profileName.trim()
    if (!name) {
      message.warning('请输入配置名称')
      return
    }
    if (profiles.some(p => p.name === name)) {
      message.warning('已存在同名配置，请换一个名称')
      return
    }
    setProfileSaving(true)
    try {
      const values = await form.validateFields()
      const profile: SSHConfigProfile = {
        id: createSSHProfileId(),
        name,
        config: values,
        updatedAt: Date.now(),
      }
      persistProfiles([...profiles, profile], profile.id)
      setProfileModalOpen(false)
      setProfileName('')
      message.success(`已保存本地配置「${name}」`)
    } catch {
      // 表单校验失败时保持弹窗，字段错误会显示在表单中
    } finally {
      setProfileSaving(false)
    }
  }

  const handleDeleteProfile = () => {
    if (!activeProfile) return
    const target = activeProfile
    Modal.confirm({
      title: `删除本地配置「${target.name}」？`,
      content: '只删除浏览器 localStorage 中的这份配置，不会清除后端当前配置。',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => {
        const nextProfiles = profiles.filter(p => p.id !== target.id)
        persistProfiles(nextProfiles, null)
        message.success(`已删除本地配置「${target.name}」`)
      },
    })
  }

  const sshModeText: Record<SSHLoginMode, string> = { direct: '直连板端', jump: '通过跳板机' }
  const statusType = sshStatus?.connected ? 'success' : sshStatus?.tested ? 'error' : 'info'
  const statusText = sshStatus
    ? `${sshModeText[sshStatus.mode]}｜${sshStatus.message}`
    : 'SSH 未配置'

  const profileOptions = profiles.map((p) => {
    const endpoint = [p.config.username, p.config.host].filter(Boolean).join('@') || '未填写主机'
    return { value: p.id, label: `${p.name}（${endpoint}）` }
  })

  return (
    <>
      <Card
        title={<><ApiOutlined style={{ marginRight: 8 }} />SSH 连接配置</>}
        extra={
          <Space>
            <Button icon={<SyncOutlined />} loading={testingSSH} onClick={handleTest}>测试连接</Button>
            <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>保存配置</Button>
          </Space>
        }
        style={{ maxWidth: 720 }}
      >
        <div
          style={{
            marginBottom: 16,
            padding: '10px 12px',
            background: '#fafafa',
            border: '1px solid #f0f0f0',
            borderRadius: 6,
          }}
        >
          <Space direction="vertical" size={6} style={{ display: 'flex' }}>
            <div>
              <Text strong>浏览器本地配置</Text>
              <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                保存多套 SSH 连接配置，选中后立即切换
              </Text>
            </div>
            <Space.Compact block>
              <Select
                allowClear
                showSearch
                optionFilterProp="label"
                style={{ flex: 1 }}
                value={activeProfileId || undefined}
                placeholder="选择本地配置"
                options={profileOptions}
                loading={switchingProfile}
                onChange={handleSelectProfile}
                notFoundContent="暂无本地配置，保存后可在此切换"
              />
              <Button icon={<SaveOutlined />} onClick={handleSaveLocal}>保存到本地</Button>
              <Button icon={<PlusOutlined />} onClick={handleSaveAs}>另存为</Button>
              <Button danger icon={<DeleteOutlined />} disabled={!activeProfile} onClick={handleDeleteProfile}>
                删除
              </Button>
            </Space.Compact>
            <Text type="secondary" style={{ fontSize: 12 }}>
              本地配置（含密码）只保存在当前浏览器的 localStorage；点击「保存配置」才会同步到后端用于测试执行。
            </Text>
          </Space>
        </div>

        <Form form={form} layout="vertical" initialValues={{ login_mode: 'direct', port: 22, timeout: 30, jump_port: 22 }}>
          <Form.Item name="login_mode" label="登录方式">
            <Radio.Group>
              <Radio value="direct">直接登录板端</Radio>
              <Radio value="jump">通过跳板机登录板端</Radio>
            </Radio.Group>
          </Form.Item>

          {currentMode === 'jump' && (
            <Alert
              style={{ marginBottom: 16 }} type="info" showIcon
              message="当前为跳板机模式"
              description="系统将先登录跳板机，再通过跳板机连接目标板端。"
            />
          )}

          <Form.Item name="host" label="目标板端主机" rules={[{ required: true }]}>
            <Input placeholder="例如：192.168.1.10" />
          </Form.Item>
          <Form.Item name="port" label="目标板端端口">
            <InputNumber min={1} max={65535} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="username" label="目标板端用户名" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="password" label="目标板端密码">
            <Input.Password />
          </Form.Item>
          <Form.Item name="target_password" label="板端 sudo/二次认证密码">
            <Input.Password />
          </Form.Item>

          {currentMode === 'jump' && (
            <>
              <Form.Item name="jump_host" label="跳板机主机" rules={[{ required: true }]}>
                <Input />
              </Form.Item>
              <Form.Item name="jump_port" label="跳板机端口">
                <InputNumber min={1} max={65535} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item name="jump_username" label="跳板机用户名" rules={[{ required: true }]}>
                <Input />
              </Form.Item>
              <Form.Item name="jump_password" label="跳板机密码">
                <Input.Password />
              </Form.Item>
            </>
          )}

          <Form.Item name="timeout" label="超时(秒)">
            <InputNumber min={1} max={300} style={{ width: '100%' }} />
          </Form.Item>
        </Form>

        <Alert style={{ marginTop: 8 }} type={statusType} showIcon message="SSH 登录状态" description={statusText} />
      </Card>

      <Modal
        open={profileModalOpen}
        title="保存为本地配置"
        okText="保存"
        cancelText="取消"
        confirmLoading={profileSaving}
        onOk={handleProfileModalOk}
        onCancel={() => {
          if (profileSaving) return
          setProfileModalOpen(false)
          setProfileName('')
        }}
      >
        <div style={{ marginBottom: 6, fontSize: 13 }}>配置名称</div>
        <Input
          value={profileName}
          onChange={(e) => setProfileName(e.target.value)}
          placeholder="例如：板端A / 跳板环境"
          maxLength={40}
          autoFocus
          onPressEnter={() => void handleProfileModalOk()}
        />
        <Text type="secondary" style={{ display: 'block', marginTop: 8, fontSize: 12 }}>
          保存后当前表单内容会存入浏览器 localStorage，并作为选中的本地配置。
        </Text>
      </Modal>
    </>
  )
}
