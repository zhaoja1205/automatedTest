/**
 * SSH 配置独立页面 — 从 Dashboard 弹窗提取为独立路由
 *
 * 支持把多套 SSH 配置保存在浏览器 localStorage 中（例如不同板端、
 * 直连/跳板环境），在下拉框中随时切换；切换后会同步到后端作为当前配置。
 */
import { useEffect, useRef, useState } from 'react'
import { isAxiosError } from 'axios'
import {
  Card, Form, Input, InputNumber, Radio, Button, Space, Alert, message,
  Select, Modal, Typography,
} from 'antd'
import {
  SyncOutlined, ApiOutlined, PlusOutlined, DeleteOutlined,
} from '@ant-design/icons'
import { useStore } from '../stores/useStore'
import { getSSHConfig, getSSHStatus, setSSHConfig as apiSetSSHConfig, testSSHConnection } from '../api/axios'
import {
  createSSHProfileId,
  EMPTY_SSH_CONFIG,
  isSSHConfigChanged,
  loadSSHProfiles,
  normalizeSSHConfig,
  saveSSHProfiles,
} from '../utils/sshConfigStorage'
import type { SSHConfigProfile } from '../utils/sshConfigStorage'
import type { SSHConfig, SSHLoginMode } from '../types'

const { Text } = Typography

/** 表单值：SSH 连接参数 + 配置名称（名称只存 localStorage，不提交后端） */
type SSHFormValues = SSHConfig & { name: string }

const getErrorMessage = (error: unknown, fallback: string) => {
  if (isAxiosError<{ detail?: string }>(error))
    return error.response?.data?.detail || error.message || fallback
  if (error instanceof Error) return error.message
  return fallback
}

/** 表单值 → 后端 SSHConfig（丢弃仅本地使用的配置名称） */
const toSSHConfig = (values: SSHFormValues): SSHConfig =>
  normalizeSSHConfig(values) ?? values

export default function SSHConfigPage() {
  const setSSHConfig = useStore(s => s.setSSHConfig)
  const setSSHStatus = useStore(s => s.setSSHStatus)
  const sshStatus = useStore(s => s.sshStatus)
  const [form] = Form.useForm<SSHFormValues>()
  const [testingSSH, setTestingSSH] = useState(false)
  const currentMode = Form.useWatch('login_mode', form) || 'direct'

  // 浏览器本地配置集
  const [profiles, setProfiles] = useState<SSHConfigProfile[]>([])
  const [activeProfileId, setActiveProfileId] = useState<string | null>(null)
  const [switchingProfile, setSwitchingProfile] = useState(false)

  const activeProfile = activeProfileId
    ? profiles.find(p => p.id === activeProfileId) || null
    : null

  /** 更新本地配置集（同时写入 localStorage） */
  const persistProfiles = (nextProfiles: SSHConfigProfile[], nextActiveId: string | null) => {
    setProfiles(nextProfiles)
    setActiveProfileId(nextActiveId)
    saveSSHProfiles({ profiles: nextProfiles, activeId: nextActiveId })
  }

  // ---- 自动保存：表单改动防抖写回当前选中的本地配置 ----
  const autoSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  /** 程序化填充表单（载入/切换）期间不触发自动保存 */
  const suppressAutoSaveRef = useRef(false)
  /** 定时器里读取最新的配置集，避免闭包拿到旧数据 */
  const profilesRef = useRef<SSHConfigProfile[]>(profiles)
  useEffect(() => {
    profilesRef.current = profiles
  }, [profiles])

  useEffect(() => () => {
    if (autoSaveTimerRef.current) clearTimeout(autoSaveTimerRef.current)
  }, [])

  const cancelPendingAutoSave = () => {
    if (autoSaveTimerRef.current) {
      clearTimeout(autoSaveTimerRef.current)
      autoSaveTimerRef.current = null
    }
  }

  /** 填充表单但不触发自动保存（用于载入配置、切换配置等程序化赋值） */
  const setFormValues = (config: SSHConfig, name: string) => {
    cancelPendingAutoSave()
    suppressAutoSaveRef.current = true
    form.setFieldsValue({ ...(normalizeSSHConfig(config) ?? config), name })
    // 切换/载入后清掉上一份配置遗留的名称校验错误
    form.setFields([{ name: 'name', errors: [] }])
    // 等 setFieldsValue 的通知结束后再恢复；用宏任务避免把载入误判为用户编辑
    setTimeout(() => { suppressAutoSaveRef.current = false }, 0)
  }

  /** 用户改动任意字段后，防抖保存到当前选中的本地配置 */
  const handleFormValuesChange = () => {
    if (suppressAutoSaveRef.current) return
    const targetId = activeProfileId
    if (!targetId) return
    cancelPendingAutoSave()
    autoSaveTimerRef.current = setTimeout(() => {
      autoSaveTimerRef.current = null
      const raw = form.getFieldsValue(true) as SSHFormValues
      const values = normalizeSSHConfig(raw)
      if (!values) return
      const current = profilesRef.current
      const target = current.find(p => p.id === targetId)
      if (!target) return
      // 名称随表单一起保存；空名称或与他份重名时保留原名（字段校验会提示）
      const rawName = (raw.name ?? '').trim()
      const name = rawName && !current.some(p => p.id !== targetId && p.name === rawName)
        ? rawName
        : target.name
      if (!isSSHConfigChanged(target.config, values) && name === target.name) return
      persistProfiles(
        current.map(p => p.id === targetId
          ? { ...p, config: values, name, updatedAt: Date.now() }
          : p),
        targetId,
      )
    }, 600)
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
        setFormValues(initial, localActive?.name ?? '')
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
          setFormValues(localActive.config, localActive.name)
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

  /** 测试连接：成功后后端会将该配置作为当前执行配置（/ssh/test 内部同步） */
  const handleTest = async () => {
    let values: SSHConfig
    try {
      values = toSSHConfig(await form.validateFields())
    } catch {
      return // 字段错误由表单直接展示
    }
    try {
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
    setFormValues(profile.config, profile.name)
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
      cancelPendingAutoSave()
      persistProfiles(profiles, null)
      return
    }
    const profile = profiles.find(p => p.id === id)
    if (!profile) return

    // 有选中的本地配置时，检查最近一次自动保存之后是否还有改动（防抖窗口内）
    const currentValues = normalizeSSHConfig(form.getFieldsValue(true))
    const currentName = String(form.getFieldValue('name') ?? '').trim()
    const dirty = !!activeProfile && (
      (!!currentValues && isSSHConfigChanged(currentValues, activeProfile.config)) ||
      currentName !== activeProfile.name
    )
    if (dirty) {
      Modal.confirm({
        title: '当前配置有尚未保存的修改',
        content: '切换本地配置会覆盖当前表单内容，未保存的修改将丢失。',
        okText: '继续切换',
        cancelText: '取消',
        onOk: () => applyProfile(profile),
      })
      return
    }
    void applyProfile(profile)
  }

  /** 生成一个未被占用的默认配置名（如「配置 3」） */
  const nextProfileName = () => {
    let index = profiles.length + 1
    while (profiles.some(p => p.name === `配置 ${index}`)) index += 1
    return `配置 ${index}`
  }

  /** 新建一份空白本地配置：自动命名并选中，名称和连接参数都在表单里编辑 */
  const handleCreateProfile = () => {
    cancelPendingAutoSave()
    const profile: SSHConfigProfile = {
      id: createSSHProfileId(),
      name: nextProfileName(),
      config: { ...EMPTY_SSH_CONFIG },
      updatedAt: Date.now(),
    }
    persistProfiles([...profiles, profile], profile.id)
    setFormValues(profile.config, profile.name)
    message.success(`已新建本地配置「${profile.name}」，名称和连接参数均可在表单中修改`)
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
        cancelPendingAutoSave()
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
            <Button icon={<SyncOutlined />} loading={testingSSH} disabled={!activeProfile} onClick={handleTest}>测试连接</Button>
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
                notFoundContent="暂无本地配置，点「新建配置」创建一份"
              />
              <Button icon={<PlusOutlined />} onClick={handleCreateProfile}>新建配置</Button>
              <Button danger icon={<DeleteOutlined />} disabled={!activeProfile} onClick={handleDeleteProfile}>
                删除
              </Button>
            </Space.Compact>
            <Text type="secondary" style={{ fontSize: 12 }}>
              必须先新建或选中一份本地配置才能编辑表单；表单改动（含第一项配置名称）会自动保存到该配置
              （含密码，仅存于当前浏览器 localStorage）。点击「测试连接」会校验并把当前配置同步到后端，
              成功后的配置即用于实际测试执行。
            </Text>
          </Space>
        </div>

        {!activeProfile && (
          <Alert
            style={{ marginBottom: 16 }}
            type="info"
            showIcon
            message="未选中本地配置"
            description="请先点「新建配置」创建一份，或在下拉框中选择已有配置，之后才能编辑 SSH 连接参数。"
          />
        )}

        <Form
          form={form}
          layout="vertical"
          disabled={!activeProfile}
          initialValues={{ login_mode: 'direct', port: 22, timeout: 30, jump_port: 22 }}
          onValuesChange={handleFormValuesChange}
        >
          <Form.Item
            name="name"
            label="配置名称"
            rules={[
              { required: true, whitespace: true, message: '请输入配置名称' },
              {
                validator: (_, value: string) => {
                  const name = (value ?? '').trim()
                  if (!name) return Promise.resolve()
                  const duplicated = profiles.some(p =>
                    p.id !== activeProfileId && p.name === name)
                  return duplicated
                    ? Promise.reject(new Error('已存在同名配置，请换一个名称'))
                    : Promise.resolve()
                },
              },
            ]}
          >
            <Input maxLength={40} placeholder="例如：板端A / 跳板环境" />
          </Form.Item>

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
    </>
  )
}
