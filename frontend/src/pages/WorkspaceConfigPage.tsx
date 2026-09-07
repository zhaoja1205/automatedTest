/**
 * 工作区配置独立页面
 */
import { useState, useEffect } from 'react'
import { isAxiosError } from 'axios'
import {
  Card, Form, Input, Row, Col, Checkbox, Collapse, Button, message,
} from 'antd'
import { SaveOutlined, FolderOpenOutlined } from '@ant-design/icons'
import { useStore } from '../stores/useStore'
import { getWorkspace, setWorkspace as apiSetWorkspace } from '../api/axios'
import type { WorkspaceConfig } from '../types'

export default function WorkspaceConfigPage() {
  const setWorkspace = useStore(s => s.setWorkspace)
  const [form] = Form.useForm<WorkspaceConfig>()
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await getWorkspace()
        if (cancelled) return
        setWorkspace(res.data)
        form.setFieldsValue(res.data)
      } catch (err) {
        if (!cancelled) {
          const msg = isAxiosError(err) ? err.response?.data?.detail || err.message : '加载配置失败'
          message.warning(msg)
        }
      }
    })()
    return () => { cancelled = true }
  }, [form, setWorkspace])

  const handleSave = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      await apiSetWorkspace(values)
      setWorkspace(values)
      message.success('工作区配置已保存')
    } catch (err) {
      const msg = isAxiosError(err) ? err.response?.data?.detail || err.message : '保存失败'
      message.error(msg)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card
      title={<><FolderOpenOutlined style={{ marginRight: 8 }} />工作区配置</>}
      extra={<Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>保存配置</Button>}
      style={{ maxWidth: 640 }}
    >
      <Form form={form} layout="vertical" size="small">
        <Row gutter={16}>
          <Col span={12}><Form.Item name="tester_name" label="测试人员"><Input /></Form.Item></Col>
          <Col span={12}><Form.Item name="test_version" label="测试版本"><Input /></Form.Item></Col>
        </Row>
        <Form.Item name="default_remote_path" label="远程工作路径" style={{ marginBottom: 12 }}>
          <Input placeholder="板端测试命令的工作目录" />
        </Form.Item>
        <Form.Item name="run_prerequisites" valuePropName="checked" style={{ marginBottom: 8 }}>
          <Checkbox>执行前置条件</Checkbox>
        </Form.Item>

        <Collapse size="small" style={{ marginTop: 8 }} items={[
          {
            key: 'paths',
            label: '路径覆盖配置',
            children: (
              <>
                <Form.Item name="nito_override_enabled" valuePropName="checked" style={{ marginBottom: 4 }}>
                  <Checkbox>启用 Nito 路径覆盖</Checkbox>
                </Form.Item>
                <Form.Item noStyle shouldUpdate={(prev, cur) => prev.nito_override_enabled !== cur.nito_override_enabled}>
                  {({ getFieldValue }) => getFieldValue('nito_override_enabled') ? (
                    <Form.Item name="nito_override_path" style={{ marginBottom: 8 }}>
                      <Input placeholder="板端 nito 路径，如 /app/basetech/nito" />
                    </Form.Item>
                  ) : null}
                </Form.Item>
                <Form.Item name="image_storage_enabled" valuePropName="checked" style={{ marginBottom: 4 }}>
                  <Checkbox>启用 Image 存储路径（-f 参数替换）</Checkbox>
                </Form.Item>
                <Form.Item noStyle shouldUpdate={(prev, cur) => prev.image_storage_enabled !== cur.image_storage_enabled}>
                  {({ getFieldValue }) => getFieldValue('image_storage_enabled') ? (
                    <Form.Item name="image_storage_path" style={{ marginBottom: 8 }}>
                      <Input placeholder="板端图像存储目录，如 /storage/zja/picture/" />
                    </Form.Item>
                  ) : null}
                </Form.Item>
                <Form.Item name="cam_rotate_cfg_enabled" valuePropName="checked" style={{ marginBottom: 4 }}>
                  <Checkbox>启用 Camera 翻转配置</Checkbox>
                </Form.Item>
                <Form.Item noStyle shouldUpdate={(prev, cur) => prev.cam_rotate_cfg_enabled !== cur.cam_rotate_cfg_enabled}>
                  {({ getFieldValue }) => getFieldValue('cam_rotate_cfg_enabled') ? (
                    <Form.Item name="cam_rotate_cfg_path" style={{ marginBottom: 8 }}>
                      <Input placeholder="板端翻转配置文件路径" />
                    </Form.Item>
                  ) : null}
                </Form.Item>
              </>
            ),
          },
          {
            key: 'download',
            label: '拍图下载配置',
            children: (
              <>
                <Form.Item name="image_download_enabled" valuePropName="checked" style={{ marginBottom: 4 }}>
                  <Checkbox>执行后下载图片到 PC（并清理板端）</Checkbox>
                </Form.Item>
                <Form.Item noStyle shouldUpdate={(prev, cur) => prev.image_download_enabled !== cur.image_download_enabled}>
                  {({ getFieldValue }) => getFieldValue('image_download_enabled') ? (
                    <Form.Item name="image_download_path" style={{ marginBottom: 8 }}>
                      <Input placeholder="PC 本地保存路径" />
                    </Form.Item>
                  ) : null}
                </Form.Item>
              </>
            ),
          },
        ]} />
      </Form>
    </Card>
  )
}
