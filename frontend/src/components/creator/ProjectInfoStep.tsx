/**
 * 步骤 1：A1~A5 分批问答式项目信息。
 *
 * 按创建用例 skill 的问答顺序收集：A1 文档元信息、A2 被测对象维度、
 * A3 公共前置条件、A4 分类与优先级、A5 输出要求。
 */
import { Form, Input, Select, Switch, Card, Button, Space, Alert } from 'antd'
import { PlusOutlined, MinusCircleOutlined } from '@ant-design/icons'
import { useCreatorStore } from '../../stores/useCreatorStore'
import type { ProjectMeta } from '../../types/creator'
import { useEffect } from 'react'

const { TextArea } = Input

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
      style={{ maxWidth: 1040 }}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="按 A1→A5 分批收集创建用例信息"
        description="每一批先补齐关键信息，再进入下一批。命令、路径、IP、阈值、帧率等项目特定信息不会自动编造；缺失时生成用例会保留 <待补充:xxx> 占位符，导出后继续按占位符清单补齐。"
      />

      {/* A1 文档信息 */}
      <Card title="A1 文档元信息（封面 / 修改控制）" size="small" style={{ marginBottom: 16 }}>
        <Alert
          type="success"
          showIcon
          style={{ marginBottom: 16 }}
          message="本批用于填表头，缺失会导致封面和修改控制页为空"
          description="示例：项目名称 Zhiji，文件编号 ThunderSoft-SVB-11-ZY07，文档版本 V3.0，参考资料 需求规格说明书 V1.1。"
        />
        <Form.Item label="项目名称 / 标题" name="title" extra="用于命名标题和导出文件，例如 Zhiji。">
          <Input placeholder="如 Zhiji" />
        </Form.Item>
        <div style={{ display: 'flex', gap: 16 }}>
          <Form.Item label="文件编号" name="file_number" style={{ flex: 1 }} extra="封面右上角编号。">
            <Input placeholder="ThunderSoft-SVB-11-ZY07" />
          </Form.Item>
          <Form.Item label="文档版本" name="doc_version" style={{ flex: 1 }} extra="修改控制页版本。">
            <Input placeholder="V3.0" />
          </Form.Item>
        </div>
        <Form.Item label="测试对象" name="test_object" extra="标识被测范围，例如 Camera 驱动 / Camera Driver。">
          <Input placeholder="Camera驱动/Camera Driver" />
        </Form.Item>
        <div style={{ display: 'flex', gap: 16 }}>
          <Form.Item label="软件版本" name="software_version" style={{ flex: 1 }}>
            <Input placeholder="DriveOS 6.5.2.1" />
          </Form.Item>
          <Form.Item label="测试版本" name="test_version" style={{ flex: 1 }}>
            <Input placeholder="IM_Qnx_Safety_6521_V01.004" />
          </Form.Item>
        </div>
        <div style={{ display: 'flex', gap: 16 }}>
          <Form.Item label="操作系统" name="os" style={{ flex: 1 }}>
            <Select>
              <Select.Option value="QNX">QNX</Select.Option>
              <Select.Option value="Linux">Linux</Select.Option>
              <Select.Option value="Android">Android</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item label="设备型号 / 客户开发板" name="dev_board" style={{ flex: 2 }}>
            <Input placeholder="Nvidia 客户开发板" />
          </Form.Item>
        </div>
        <div style={{ display: 'flex', gap: 16 }}>
          <Form.Item label="设备型号" name="equipment_model" style={{ flex: 1 }}>
            <Input placeholder="Orin X" />
          </Form.Item>
          <Form.Item label="测试周期" name="test_cycle" style={{ flex: 1 }}>
            <Input placeholder="2026/6/11-2026/6/11" />
          </Form.Item>
        </div>
        <div style={{ display: 'flex', gap: 16 }}>
          <Form.Item label="修改日期" name="revision_date" style={{ flex: 1 }}>
            <Input placeholder="2026-01-01" />
          </Form.Item>
          <Form.Item label="修改者" name="modifier" style={{ flex: 1 }}>
            <Input placeholder="刘国龙" />
          </Form.Item>
          <Form.Item label="评审人" name="reviewer" style={{ flex: 1 }}>
            <Input placeholder="胡玉廷等" />
          </Form.Item>
          <Form.Item label="批准人" name="approver" style={{ flex: 1 }}>
            <Input placeholder="胡玉廷" />
          </Form.Item>
        </div>
        <Form.Item label="修改内容" name="change_content">
          <Input placeholder="针对 IM_Qnx_Safety_6521_V01.004 进行测试用例设计" />
        </Form.Item>
        <Form.Item label="公司" name="company">
          <Input />
        </Form.Item>
      </Card>

      {/* 参考资料 */}
      <Card title="A1 参考资料（溯源）" size="small" style={{ marginBottom: 16 }}>
        <Form.List name="references">
          {(fields, { add, remove }) => (
            <>
              {fields.map(({ key, name, ...restField }) => (
                <Space key={key} style={{ display: 'flex', marginBottom: 8 }} align="baseline">
                  <Form.Item {...restField} name={[name, 'name']} style={{ flex: 2, marginBottom: 0 }}>
                    <Input placeholder="文档名称，如 需求规格说明书" />
                  </Form.Item>
                  <Form.Item {...restField} name={[name, 'version']} style={{ width: 100, marginBottom: 0 }}>
                    <Input placeholder="V1.1" />
                  </Form.Item>
                  <Form.Item {...restField} name={[name, 'summary']} style={{ flex: 2, marginBottom: 0 }}>
                    <Input placeholder="用途/摘要" />
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

      {/* A2 被测对象维度 */}
      <Card title="A2 被测对象维度（覆盖度根信息）" size="small" style={{ marginBottom: 16 }}>
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="这一批决定覆盖矩阵、命令步骤和预期判定"
          description="硬件拓扑和每模组支持功能在下一步填写；这里补齐命令、路径、帧率、跳板机、故障变体等会直接影响生成用例。"
        />
        <Form.Item label="被测组件清单（驱动 / 程序 / 库）" name="tested_components" extra="逐个列全，前置条件会引用，不能只写“等”。">
          <TextArea rows={3} placeholder={`libnvsipl_qry_Zhiji_mixgroup.so
nvsipl_camera`} />
        </Form.Item>
        <div style={{ display: 'flex', gap: 16 }}>
          <Form.Item label="配置名（-c 的值）" name="cam_config" style={{ flex: 1 }} extra="不知道时保留为空，生成用例会写 <待补充:-c配置名>。">
            <Input placeholder="IM_IMX623_IMX728_X1G_D" />
          </Form.Item>
          <Form.Item label="起流可执行程序（必问）" name="stream_program" style={{ flex: 1 }} extra="Excel 只体现一个程序名，强杀和结束确认也用它。">
            <Select allowClear placeholder="请选择">
              <Select.Option value="nvsipl_camera">nvsipl_camera（单路）</Select.Option>
              <Select.Option value="nvsipl_multicast">nvsipl_multicast（多播/环视）</Select.Option>
            </Select>
          </Form.Item>
        </div>
        <Form.Item label="每个模组输出帧率（必问，不默认 30）" name="fps_by_module" extra="一行一个：模组型号=帧率。生成器只按精确模组名匹配；缺失则输出 <待补充:帧率>。">
          <TextArea rows={3} placeholder={`IMX728=30fps
IMX623=30fps
OX03F10=60fps`} />
        </Form.Item>
        <div style={{ display: 'flex', gap: 16 }}>
          <Form.Item label="调试目录路径" name="debug_dir" style={{ flex: 1 }}>
            <Input placeholder="/opt/cfg/lgl/new1" />
          </Form.Item>
          <Form.Item label="板端 IP" name="board_ip" style={{ flex: 1 }}>
            <Input placeholder="172.31.254.38" />
          </Form.Item>
          <Form.Item label="板端密码" name="board_password" style={{ flex: 1 }}>
            <Input.Password placeholder="root / <密码>" />
          </Form.Item>
        </div>
        <Form.Item label="命令参数及含义" name="command_args" extra="用于生成 G 列步骤说明。">
          <TextArea rows={3} placeholder={'-m 四段 mask 对应 Group；-e 读内参；-f 输出路径；-R RAW'} />
        </Form.Item>
        <Form.Item label="每个功能点的判定标准" name="feature_criteria" extra="用于生成 H 列预期结果，建议包含 .raw、fps、故障位、关键字等可判定观测点。">
          <TextArea rows={3} placeholder={'出图：生成 .raw；帧率：30fps；故障：SAFETY_CAM_SENSOR_STREAMING_ERROR 置 1'} />
        </Form.Item>
      </Card>

      <Card title="A2 跳板机 / 传输 / 执行模式" size="small" style={{ marginBottom: 16 }}>
        <Form.Item label="本地到板端是否需要跳板机" name="jump_host_enabled" valuePropName="checked">
          <Switch checkedChildren="需要" unCheckedChildren="直连" />
        </Form.Item>
        <div style={{ display: 'flex', gap: 16 }}>
          <Form.Item label="跳板机 IP" name="jump_host_ip" style={{ flex: 1 }}>
            <Input placeholder="172.31.1.100" />
          </Form.Item>
          <Form.Item label="跳板机用户名" name="jump_host_user" style={{ flex: 1 }}>
            <Input placeholder="user" />
          </Form.Item>
          <Form.Item label="跳板机密码" name="jump_host_password" style={{ flex: 1 }}>
            <Input.Password placeholder="<密码>" />
          </Form.Item>
        </div>
        <div style={{ display: 'flex', gap: 16 }}>
          <Form.Item label="跳板机中转目录" name="jump_host_transfer_dir" style={{ flex: 1 }}>
            <Input placeholder="/home/user/transfer/" />
          </Form.Item>
          <Form.Item label="跳板机能直接 ssh 到板端" name="jump_host_can_ssh" valuePropName="checked" style={{ flex: 1 }}>
            <Switch checkedChildren="能" unCheckedChildren="不能" />
          </Form.Item>
          <Form.Item label="执行模式" name="execution_mode" style={{ flex: 1 }}>
            <Select placeholder="请选择">
              <Select.Option value="自动化">自动化（M列放 log 文本+截图）</Select.Option>
              <Select.Option value="人工">人工（M列放截图）</Select.Option>
              <Select.Option value="混合">混合</Select.Option>
            </Select>
          </Form.Item>
        </div>
        <div style={{ display: 'flex', gap: 16 }}>
          <Form.Item label="scp 源路径（本地驱动/工具目录）" name="scp_source_path" style={{ flex: 1 }}>
            <Input placeholder="本地驱动/工具目录" />
          </Form.Item>
          <Form.Item label="scp 目标路径（板端调试目录）" name="scp_target_path" style={{ flex: 1 }}>
            <Input placeholder="/opt/cfg/lgl/new1" />
          </Form.Item>
        </div>
        <div style={{ display: 'flex', gap: 16 }}>
          <Form.Item label="起流成功判定标志" name="stream_success_signal" style={{ flex: 1 }} extra="默认建议：出现帧率打印或 streaming。">
            <Input placeholder={'"streaming started" / 帧率打印出现'} />
          </Form.Item>
          <Form.Item label="功能用例等待超时(s)" name="functional_timeout" style={{ flex: 1 }}>
            <Input placeholder="15" />
          </Form.Item>
          <Form.Item label="故障用例等待超时(s)" name="fault_timeout" style={{ flex: 1 }}>
            <Input placeholder="30" />
          </Form.Item>
        </div>
      </Card>

      <Card title="A2 特殊测试 / 故障变体" size="small" style={{ marginBottom: 16 }}>
        <Form.Item label="特殊测试与可靠性范围" name="special_tests" extra="逐项说明做/不做及模组或 Group；未明确不做的项目建议主动确认。">
          <TextArea rows={5} placeholder={`热插拔：做，GroupA/GroupC，--autorecovery
快启：不做
bypass：做，GroupD LinkA，--camRecCfg 1
丢帧：做，10万帧丢帧<2
稳定性：做，10min/1h/4h`} />
        </Form.Item>
        <div style={{ display: 'flex', gap: 16 }}>
          <Form.Item label="故障展开方式" name="fault_expand_mode" style={{ flex: 1 }}>
            <Select placeholder="请选择">
              <Select.Option value="全量展开">全量展开</Select.Option>
              <Select.Option value="按优先级">按优先级</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item label="故障子项来源" name="fault_source" style={{ flex: 1 }}>
            <Select placeholder="请选择">
              <Select.Option value="储备库">储备库</Select.Option>
              <Select.Option value="参考用例">用户提供参考用例</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item label="故障上报/查询方式" name="fault_report_mode" style={{ flex: 1 }}>
            <Select placeholder="请选择">
              <Select.Option value="ex8查询">A：ex8 主动查询</Select.Option>
              <Select.Option value="主动上报">B：驱动主动上报</Select.Option>
              <Select.Option value="f_df查询">C：f/df 主动查询</Select.Option>
            </Select>
          </Form.Item>
        </div>
        <div style={{ display: 'flex', gap: 16 }}>
          <Form.Item label="需要 syslog 打印验证" name="fault_syslog" valuePropName="checked" style={{ flex: 1 }}>
            <Switch checkedChildren="需要" unCheckedChildren="不需要" />
          </Form.Item>
          <Form.Item label="需要验证故障位清零" name="fault_clear_check" valuePropName="checked" style={{ flex: 1 }}>
            <Switch checkedChildren="需要" unCheckedChildren="不需要" />
          </Form.Item>
          <Form.Item label="故障用例 ID 从 001 重新编号" name="fault_id_from_start" valuePropName="checked" style={{ flex: 1 }}>
            <Switch />
          </Form.Item>
        </div>
      </Card>

      {/* A3/A4/A5 */}
      <Card title="A3 公共前置条件" size="small" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 16 }}>
          <Form.Item label="驱动 .so 部署目录" name="driver_deploy_dir" style={{ flex: 1 }}>
            <Input placeholder="/usr/lib/nvidia/nvsipl_drv/ 和 /usr/lib/" />
          </Form.Item>
          <Form.Item label="测试工具及路径" name="test_tool_path" style={{ flex: 1 }}>
            <Input placeholder="调试目录下的 nvsipl_camera" />
          </Form.Item>
        </div>
        <Form.Item label="异常处理约定" name="exception_handling" extra="进程名按 A2 的起流程序选择。">
          <Input placeholder="slay nvsipl_camera" />
        </Form.Item>
      </Card>

      <Card title="A4 分类与优先级规则" size="small" style={{ marginBottom: 16 }}>
        <Form.Item label="测试类型取值范围（C列）" name="test_type_scope">
          <Input placeholder="基本功能 / IMX728 故障项测试 / 异常 / 边界值" />
        </Form.Item>
        <Form.Item label="设计方法取值规则（D列）" name="method_rule">
          <TextArea rows={2} placeholder="功能点=基于需求分析；边界=边界值分析；负向=错误推测法；故障不用错误推测" />
        </Form.Item>
        <Form.Item label="优先级规则（I列）" name="priority_rule">
          <TextArea rows={2} placeholder="多模组并发=P0；单模组基本/故障=P1；压力稳定=P2" />
        </Form.Item>
        <Form.Item label="ID 编号规则（B列）" name="id_rule">
          <Input placeholder="功能 001.. 连续；故障接续或按子类分段" />
        </Form.Item>
      </Card>

      <Card title="A5 输出要求 / 选填增强" size="small" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 16 }}>
          <Form.Item label="生成范围" name="generation_scope" style={{ flex: 1 }}>
            <Select placeholder="请选择">
              <Select.Option value="仅功能">仅功能</Select.Option>
              <Select.Option value="功能+故障">功能+故障</Select.Option>
              <Select.Option value="含附录">含附录</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item label="输出格式" name="output_format" style={{ flex: 1 }}>
            <Select placeholder="请选择">
              <Select.Option value="先草稿">先出 Markdown 草稿确认</Select.Option>
              <Select.Option value="直接xlsx">直接 .xlsx</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item label="截图保存列" name="screenshot_column" style={{ flex: 1 }}>
            <Input placeholder="M列" />
          </Form.Item>
        </div>
        <Form.Item label="领域公式 / 阈值 / 已知约束 / 不在范围场景" name="optional_notes">
          <TextArea rows={4} placeholder="帧同步公式、exp/gain 标定阈值、已知不测场景、板端拓扑图文件路径、是否有最新测试报告等" />
        </Form.Item>
      </Card>
    </Form>
  )
}
