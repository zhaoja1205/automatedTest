/**
 * 步骤 1：项目元信息表单。
 *
 * 收集问卷 A1（文档信息）、A2（测试对象信息）、A3（共用前置条件）的内容。
 */
import { Form, Input, Select, Switch, Card, Button, Space } from 'antd'
import { PlusOutlined, MinusCircleOutlined } from '@ant-design/icons'
import { useCreatorStore } from '../../stores/useCreatorStore'
import type { ProjectMeta } from '../../types/creator'
import { useEffect } from 'react'

export default function ProjectInfoStep() {
  const { currentProject, updateMeta } = useCreatorStore()
  const [form] = Form.useForm()
  const meta = currentProject?.meta

  useEffect(() => {
    if (meta) {
      form.setFieldsValue(meta)
    }
  }, [meta, form])

  const handleValuesChange = (_changed: Partial<ProjectMeta>, allValues: ProjectMeta) => {
    updateMeta(allValues)
  }

  return (
    <Form
      form={form}
      layout="vertical"
      initialValues={meta}
      onValuesChange={handleValuesChange}
      style={{ maxWidth: 800 }}
    >
      {/* A1 文档信息 */}
      <Card title="📋 文档信息" size="small" style={{ marginBottom: 16 }}>
        <Form.Item label="文件编号" name="file_number">
          <Input placeholder="如 ThunderSoft-SVB-11-ZY07" />
        </Form.Item>
        <Form.Item label="项目标题" name="title">
          <Input placeholder="如 Zhiji" />
        </Form.Item>
        <div style={{ display: 'flex', gap: 16 }}>
          <Form.Item label="文档版本" name="doc_version" style={{ flex: 1 }}>
            <Input placeholder="V1.0" />
          </Form.Item>
          <Form.Item label="公司" name="company" style={{ flex: 2 }}>
            <Input />
          </Form.Item>
        </div>
        <Form.Item label="修改内容" name="change_content">
          <Input placeholder="如：针对 IM_Qnx_Safety_6521_V01.001 进行测试用例设计" />
        </Form.Item>
        <div style={{ display: 'flex', gap: 16 }}>
          <Form.Item label="修改日期" name="revision_date" style={{ flex: 1 }}>
            <Input placeholder="2026-01-01" />
          </Form.Item>
          <Form.Item label="修改者" name="modifier" style={{ flex: 1 }}>
            <Input />
          </Form.Item>
        </div>
        <div style={{ display: 'flex', gap: 16 }}>
          <Form.Item label="评审人" name="reviewer" style={{ flex: 1 }}>
            <Input />
          </Form.Item>
          <Form.Item label="批准人" name="approver" style={{ flex: 1 }}>
            <Input />
          </Form.Item>
        </div>
      </Card>

      {/* A2 测试对象信息 */}
      <Card title="🔧 测试对象信息" size="small" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 16 }}>
          <Form.Item label="操作系统" name="os" style={{ flex: 1 }}>
            <Select>
              <Select.Option value="QNX">QNX</Select.Option>
              <Select.Option value="Linux">Linux</Select.Option>
              <Select.Option value="Android">Android</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item label="设备型号" name="equipment_model" style={{ flex: 1 }}>
            <Input placeholder="如 Orin X" />
          </Form.Item>
        </div>
        <Form.Item label="客户开发板" name="dev_board">
          <Input placeholder="如 Nvidia 客户开发板" />
        </Form.Item>
        <Form.Item label="测试对象" name="test_object">
          <Input placeholder="Camera驱动/Camera Driver" />
        </Form.Item>
        <div style={{ display: 'flex', gap: 16 }}>
          <Form.Item label="软件版本" name="software_version" style={{ flex: 1 }}>
            <Input placeholder="如 Nvidia DriveOS 6.5.2.1" />
          </Form.Item>
          <Form.Item label="测试版本" name="test_version" style={{ flex: 1 }}>
            <Input placeholder="如 IM_Qnx_Safety_6521_V01.001" />
          </Form.Item>
        </div>
        <Form.Item label="测试周期" name="test_cycle">
          <Input placeholder="如 2026/5/14-2026/5/28" />
        </Form.Item>
        <Form.Item label="故障用例 ID 从 001 重新编号" name="fault_id_from_start" valuePropName="checked">
          <Switch />
        </Form.Item>
      </Card>

      {/* 参考资料 */}
      <Card title="📚 参考资料" size="small" style={{ marginBottom: 16 }}>
        <Form.List name="references">
          {(fields, { add, remove }) => (
            <>
              {fields.map(({ key, name, ...restField }) => (
                <Space key={key} style={{ display: 'flex', marginBottom: 8 }} align="baseline">
                  <Form.Item {...restField} name={[name, 'name']} style={{ flex: 2, marginBottom: 0 }}>
                    <Input placeholder="文档名称" />
                  </Form.Item>
                  <Form.Item {...restField} name={[name, 'version']} style={{ width: 100, marginBottom: 0 }}>
                    <Input placeholder="版本" />
                  </Form.Item>
                  <Form.Item {...restField} name={[name, 'summary']} style={{ flex: 2, marginBottom: 0 }}>
                    <Input placeholder="摘要" />
                  </Form.Item>
                  <MinusCircleOutlined onClick={() => remove(name)} style={{ color: '#999' }} />
                </Space>
              ))}
              <Button type="dashed" onClick={() => add({ name: '', version: 'V1.0', summary: '' })} block icon={<PlusOutlined />}>
                添加参考资料
              </Button>
            </>
          )}
        </Form.List>
      </Card>
    </Form>
  )
}
