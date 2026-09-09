/**
 * 文件清理配置页面
 */
import { useState, useEffect, useCallback } from 'react'
import { isAxiosError } from 'axios'
import {
  Card, Form, InputNumber, Switch, Button, message, Space, Statistic,
  Row, Col, Popconfirm, Typography, Divider,
} from 'antd'
import {
  SaveOutlined, DeleteOutlined, ReloadOutlined,
  FileOutlined, DatabaseOutlined, FolderOutlined,
} from '@ant-design/icons'
import {
  getCleanupConfig, setCleanupConfig, getCleanupStats, runCleanupNow,
  type CleanupConfig,
} from '../api/axios'

const { Text } = Typography

export default function CleanupConfigPage() {
  const [form] = Form.useForm<CleanupConfig>()
  const [saving, setSaving] = useState(false)
  const [cleaning, setCleaning] = useState(false)
  const [stats, setStats] = useState<{
    total_files: number
    total_size_mb: number
    session_count: number
  } | null>(null)

  const loadData = useCallback(async () => {
    try {
      const [configRes, statsRes] = await Promise.all([
        getCleanupConfig(),
        getCleanupStats(),
      ])
      form.setFieldsValue(configRes.data)
      setStats({
        total_files: statsRes.data.total_files,
        total_size_mb: statsRes.data.total_size_mb,
        session_count: statsRes.data.session_count,
      })
    } catch (err) {
      const msg = isAxiosError(err)
        ? err.response?.data?.detail || err.message
        : '加载配置失败'
      void message.warning(msg)
    }
  }, [form])

  useEffect(() => {
    void loadData()
  }, [loadData])

  const handleSave = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      await setCleanupConfig(values)
      void message.success('清理配置已保存')
    } catch (err) {
      const msg = isAxiosError(err)
        ? err.response?.data?.detail || err.message
        : '保存失败'
      void message.error(msg)
    } finally {
      setSaving(false)
    }
  }

  const handleCleanNow = async () => {
    setCleaning(true)
    try {
      const res = await runCleanupNow()
      void message.success(res.data.message)
      // 刷新统计
      await loadData()
    } catch (err) {
      const msg = isAxiosError(err)
        ? err.response?.data?.detail || err.message
        : '清理失败'
      void message.error(msg)
    } finally {
      setCleaning(false)
    }
  }

  return (
    <Card
      title={
        <>
          <DeleteOutlined style={{ marginRight: 8 }} />
          文件清理配置
        </>
      }
      extra={
        <Button
          type="primary"
          icon={<SaveOutlined />}
          loading={saving}
          onClick={handleSave}
        >
          保存配置
        </Button>
      }
      style={{ maxWidth: 640 }}
    >
      {/* 存储统计 */}
      {stats && (
        <>
          <Row gutter={24} style={{ marginBottom: 16 }}>
            <Col span={8}>
              <Statistic
                title="上传文件数"
                value={stats.total_files}
                prefix={<FileOutlined />}
              />
            </Col>
            <Col span={8}>
              <Statistic
                title="占用空间"
                value={stats.total_size_mb}
                suffix="MB"
                prefix={<DatabaseOutlined />}
                precision={1}
              />
            </Col>
            <Col span={8}>
              <Statistic
                title="会话目录"
                value={stats.session_count}
                prefix={<FolderOutlined />}
              />
            </Col>
          </Row>
          <Divider style={{ margin: '12px 0' }} />
        </>
      )}

      <Form form={form} layout="vertical" size="small">
        <Form.Item
          name="enabled"
          label="自动清理"
          valuePropName="checked"
          style={{ marginBottom: 16 }}
        >
          <Switch checkedChildren="已启用" unCheckedChildren="已关闭" />
        </Form.Item>

        <Row gutter={16}>
          <Col span={12}>
            <Form.Item
              name="retention_days"
              label="文件保留天数"
              rules={[{ required: true, message: '请输入保留天数' }]}
              extra={<Text type="secondary">超过此天数的文件将被自动删除</Text>}
            >
              <InputNumber min={1} max={365} addonAfter="天" style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="check_interval_hours"
              label="检查间隔"
              rules={[{ required: true, message: '请输入检查间隔' }]}
              extra={<Text type="secondary">多久执行一次清理检查</Text>}
            >
              <InputNumber min={1} max={168} addonAfter="小时" style={{ width: '100%' }} />
            </Form.Item>
          </Col>
        </Row>
      </Form>

      <Divider style={{ margin: '12px 0' }} />

      <Space>
        <Popconfirm
          title="确定立即执行清理？"
          description="将删除超过保留天数的上传文件"
          okText="确定"
          cancelText="取消"
          onConfirm={handleCleanNow}
        >
          <Button
            icon={<DeleteOutlined />}
            danger
            loading={cleaning}
          >
            立即清理
          </Button>
        </Popconfirm>
        <Button
          icon={<ReloadOutlined />}
          onClick={() => void loadData()}
        >
          刷新统计
        </Button>
      </Space>
    </Card>
  )
}
