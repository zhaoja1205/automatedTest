/**
 * 生成测试用例 — 第一步：基本信息。
 *
 * 表单实例由父组件持有，保证切换步骤时已填内容不丢失。
 */
import { Col, Form, Input, Row, Select } from 'antd'
import type { FormInstance } from 'antd'
import { EMPTY_BASIC_INFO } from '../../types/casegen'
import type { CaseGenBasicInfo } from '../../types/casegen'

interface Props {
  form: FormInstance<CaseGenBasicInfo>
  visible: boolean
}

const OS_OPTIONS = ['QNX', 'Linux', 'Android', '其他'].map((value) => ({ value, label: value }))

export default function BasicInfoStep({ form, visible }: Props) {
  return (
    <div style={{ display: visible ? undefined : 'none' }}>
      <Form form={form} layout="vertical" requiredMark="optional" initialValues={EMPTY_BASIC_INFO}>
        <Row gutter={24}>
          <Col xs={24} md={12}>
            <Form.Item
              label="项目名称"
              name="project_name"
              rules={[{ required: true, message: '请输入项目名称' }]}
            >
              <Input placeholder="例如：PreDev Camera 驱动测试" maxLength={100} />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item label="被测对象 / 模块" name="target">
              <Input placeholder="例如：Camera 驱动、某功能模块" maxLength={100} />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item label="软件版本" name="software_version">
              <Input placeholder="例如：PreDev_Standard_7240.V2.006" maxLength={100} />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item label="测试版本" name="test_version">
              <Input placeholder="例如：V1.0" maxLength={100} />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item label="操作系统" name="os">
              <Select options={OS_OPTIONS} placeholder="请选择操作系统" allowClear />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item label="硬件平台 / 设备型号" name="device_model">
              <Input placeholder="例如：NVIDIA DRIVE Orin / IDC 开发板" maxLength={100} />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item label="测试负责人" name="owner">
              <Input placeholder="请输入姓名" maxLength={50} />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item label="测试周期" name="test_cycle">
              <Input placeholder="例如：2026/10/28 - 2026/11/05" maxLength={100} />
            </Form.Item>
          </Col>
          <Col xs={24}>
            <Form.Item label="备注" name="remark">
              <Input.TextArea rows={3} placeholder="其它需要说明的信息" maxLength={500} showCount />
            </Form.Item>
          </Col>
        </Row>
      </Form>
    </div>
  )
}
