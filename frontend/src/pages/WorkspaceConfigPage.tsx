/**
 * 工作区配置独立页面
 */
import { useState, useEffect } from 'react'
import { isAxiosError } from 'axios'
import {
  Card, Form, Input, Row, Col, Checkbox, Collapse, Button, message,
  InputNumber, Radio,
} from 'antd'
import { SaveOutlined, FolderOpenOutlined } from '@ant-design/icons'
import { useStore } from '../stores/useStore'
import { getWorkspace, setWorkspace as apiSetWorkspace } from '../api/axios'
import {
  isWorkspaceConfigChanged,
  loadStoredWorkspace,
  mergeWorkspaceConfig,
  saveStoredWorkspace,
} from '../utils/workspaceStorage'
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
        // 浏览器本地保存的配置优先（新标签页/浏览器重启后恢复）
        const stored = loadStoredWorkspace()
        const merged = mergeWorkspaceConfig(res.data, stored)
        setWorkspace(merged)
        form.setFieldsValue(merged)
        // 同步到后端，确保执行时使用同一份配置
        if (stored && isWorkspaceConfigChanged(merged, res.data)) {
          try {
            await apiSetWorkspace(merged)
          } catch (syncErr) {
            if (!cancelled) {
              const msg = isAxiosError(syncErr)
                ? syncErr.response?.data?.detail || syncErr.message
                : '同步配置到后端失败'
              message.warning(`本地配置已恢复，但${msg}`)
            }
          }
        }
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
      saveStoredWorkspace(values)
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
        <Form.Item name="driver_path" label="驱动存放路径" style={{ marginBottom: 12 }}>
          <Input placeholder="板端驱动目录，如 /usr/lib/nvidia/nvsipl_drv（留空则不设置 LD_LIBRARY_PATH）" />
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
          {
            key: 'log',
            label: '日志备注配置',
            children: (
              <>
                <Form.Item name="log_remark_mode" initialValue="image" label="备注列日志格式" style={{ marginBottom: 12 }}>
                  <Radio.Group optionType="button" buttonStyle="solid">
                    <Radio.Button value="image">图片</Radio.Button>
                    <Radio.Button value="text">文字</Radio.Button>
                  </Radio.Group>
                </Form.Item>
                <Form.Item noStyle shouldUpdate={(prev, cur) => prev.log_remark_mode !== cur.log_remark_mode}>
                  {({ getFieldValue }) => getFieldValue('log_remark_mode') === 'image' ? (
                    <>
                      <Row gutter={12}>
                        <Col span={8}>
                          <Form.Item name="log_image_render_width" initialValue={400} label="渲染分辨率宽度 (px)" style={{ marginBottom: 8 }}>
                            <InputNumber min={200} max={1200} step={20} style={{ width: '100%' }} />
                          </Form.Item>
                        </Col>
                        <Col span={8}>
                          <Form.Item name="log_image_display_width" initialValue={320} label="Excel 显示宽度 (px)" style={{ marginBottom: 8 }}>
                            <InputNumber min={100} max={800} step={20} style={{ width: '100%' }} />
                          </Form.Item>
                        </Col>
                        <Col span={8}>
                          <Form.Item name="log_image_max_height" initialValue={520} label="图片最大高度 (px)" style={{ marginBottom: 8 }}>
                            <InputNumber min={120} max={1200} step={20} style={{ width: '100%' }} />
                          </Form.Item>
                        </Col>
                      </Row>
                      <Row gutter={12}>
                        <Col span={8}>
                          <Form.Item name="remark_image_padding" initialValue={12} label="备注图片留白 (px)" style={{ marginBottom: 8 }}>
                            <InputNumber min={0} max={60} step={2} style={{ width: '100%' }} />
                          </Form.Item>
                        </Col>
                        <Col span={8}>
                          <Form.Item name="remark_image_gap" initialValue={16} label="备注多图间距 (px)" style={{ marginBottom: 8 }}>
                            <InputNumber min={0} max={100} step={2} style={{ width: '100%' }} />
                          </Form.Item>
                        </Col>
                      </Row>
                      <div style={{ color: '#888', fontSize: 12, marginBottom: 8 }}>
                        先按「渲染分辨率宽度」生成图片，再缩放到「Excel 显示宽度」；超过最大高度的部分只保留命令、AI 证据和末尾结论。
                        备注列图片距单元格上/左/右/下各留「备注图片留白」，同一格内日志图与截图之间再留「备注多图间距」。
                      </div>
                    </>
                  ) : (
                    <div style={{ color: '#888', fontSize: 12, marginBottom: 8 }}>
                      备注列将直接写入日志文字，不生成图片。
                    </div>
                  )}
                </Form.Item>
              </>
            ),
          },
          {
            key: 'judge',
            label: 'AI 判定配置',
            children: (
              <>
                <Form.Item
                  name="judge_log_max_kb"
                  initialValue={0}
                  label="判定日志上限 (KB)"
                  style={{ marginBottom: 8 }}
                >
                  <InputNumber min={0} step={1} precision={0} style={{ width: '100%' }} />
                </Form.Item>
                <div style={{ color: '#888', fontSize: 12, marginBottom: 8 }}>
                  0 表示不限制；超过上限时从日志末尾截取（保留最近的输出）。
                </div>
              </>
            ),
          },
        ]} />
      </Form>
    </Card>
  )
}
