/**
 * SSH 配置独立页面 — 从 Dashboard 弹窗提取为独立路由
 */
import { useState, useEffect, useCallback } from 'react'
import { isAxiosError } from 'axios'
import {
  Card, Form, Input, InputNumber, Radio, Button, Space, Alert, message,
} from 'antd'
import { SyncOutlined, SaveOutlined, ApiOutlined } from '@ant-design/icons'
import { useStore } from '../stores/useStore'
import { getSSHConfig, getSSHStatus, setSSHConfig, testSSHConnection } from '../api/axios'
import type { SSHConfig, SSHLoginMode } from '../types'

export default function SSHConfigPage() {
  const store = useStore()
  const [form] = Form.useForm<SSHConfig>()
  const [testingSSH, setTestingSSH] = useState(false)
  const [saving, setSaving] = useState(false)
  const currentMode = Form.useWatch('login_mode', form) || 'direct'

  const getErrorMessage = (error: unknown, fallback: string) => {
    if (isAxiosError<{ detail?: string }>(error))
      return error.response?.data?.detail || error.message || fallback
    if (error instanceof Error) return error.message
    return fallback
  }

  const loadConfig = useCallback(async () => {
    try {
      const [ssh, status] = await Promise.all([getSSHConfig(), getSSHStatus()])
      store.setSSHConfig(ssh.data)
      store.setSSHStatus(status.data)
      form.setFieldsValue(ssh.data)
    } catch (err) {
      message.warning(getErrorMessage(err, '加载 SSH 配置失败'))
    }
  }, [form, store])

  useEffect(() => { loadConfig() }, [loadConfig])

  const handleSave = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      await setSSHConfig(values)
      store.setSSHConfig(values)
      store.setSSHStatus({
        connected: false, tested: false, mode: values.login_mode,
        message: 'SSH 配置已更新，请点击"测试连接"确认',
      })
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
      store.setSSHConfig(values)
      store.setSSHStatus(res.data)
      message.success(res.data.message)
    } catch (err) {
      store.setSSHStatus({
        connected: false, tested: true, mode: form.getFieldValue('login_mode') || 'direct',
        message: getErrorMessage(err, 'SSH 连接测试失败'),
      })
      message.error(getErrorMessage(err, 'SSH 连接测试失败'))
    } finally {
      setTestingSSH(false)
    }
  }

  const sshModeText: Record<SSHLoginMode, string> = { direct: '直连板端', jump: '通过跳板机' }
  const statusType = store.sshStatus?.connected ? 'success' : store.sshStatus?.tested ? 'error' : 'info'
  const statusText = store.sshStatus
    ? `${sshModeText[store.sshStatus.mode]}｜${store.sshStatus.message}`
    : 'SSH 未配置'

  return (
    <Card
      title={<><ApiOutlined style={{ marginRight: 8 }} />SSH 连接配置</>}
      extra={
        <Space>
          <Button icon={<SyncOutlined />} loading={testingSSH} onClick={handleTest}>测试连接</Button>
          <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>保存配置</Button>
        </Space>
      }
      style={{ maxWidth: 640 }}
    >
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
  )
}
