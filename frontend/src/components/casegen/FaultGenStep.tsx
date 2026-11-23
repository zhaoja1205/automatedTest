/**
 * 生成测试用例 — 故障测试配置步骤。
 *
 * 针对 sensor 内部可注入的故障（IMX728 共 27 类），按勾选的故障逐条生成用例：
 * 起流 → 终端B 执行故障注入脚本注入故障 → 终端A 观察上报的 CDI 故障码
 * → 终端B 清除故障 → 退出。
 *
 * 故障注入命令固定为：
 *   ./fault_simulation_728_qnx.sh -i <I2C总线> -a <sensor地址> -n <故障号> [-c]
 */
import { useState } from 'react'
import {
  Alert,
  Button,
  Checkbox,
  Col,
  Divider,
  Empty,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  FAULT_CATALOGS,
  TEST_TYPE_FAULT,
  findFaultCatalog,
} from '../../types/casegen'
import type {
  FaultCaseTemplate,
  FaultCaseTemplatePatch,
  FaultCatalogItem,
  FaultTestOptions,
  FunctionalTestSelection,
  PlatformConfig,
} from '../../types/casegen'
import {
  buildFaultCaseContext,
  effectiveFaultCaseTemplate,
  FAULT_CASE_PLACEHOLDERS,
  faultCaseTemplateOf,
  isFaultCaseTemplateUsable,
  generateFaultCases,
  selectedFaultItems,
  selectFaultCamera,
} from '../../utils/casegen/faultCases'
import {
  renderCaseTemplate,
  type CaseTemplateContext,
} from '../../utils/casegen/functionalCases'

const { Text } = Typography

interface Props {
  visible: boolean
  platform: PlatformConfig | null
  options: FaultTestOptions
  onOptionsChange: (options: FaultTestOptions) => void
  selection: FunctionalTestSelection
  onSelectionChange: (selection: FunctionalTestSelection) => void
  onGenerate: () => void
}

const codeStyle: React.CSSProperties = {
  margin: '8px 0 0',
  padding: '10px 12px',
  background: '#f6f8fa',
  border: '1px solid #e5e7eb',
  borderRadius: 6,
  fontSize: 12,
  lineHeight: 1.6,
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-all',
}

/** 在测试步骤末尾追加占位符 */
const appendPlaceholderText = (steps: string, placeholder: string): string => {
  const current = steps || ''
  const separator = current && !current.endsWith('\n') ? '\n' : ''
  return `${current}${separator}${placeholder}`
}

export default function FaultGenStep({
  visible,
  platform,
  options,
  onOptionsChange,
  selection,
  onSelectionChange,
  onGenerate,
}: Props) {
  /** 正在单独编辑模板的故障号；为空表示未打开弹窗 */
  const [editingFaultNo, setEditingFaultNo] = useState<number | null>(null)
  const catalog = findFaultCatalog(options.catalog)
  const items = selectedFaultItems(options)
  const targetCamera = platform ? selectFaultCamera(platform, options) : null
  const previewFault = items[0]
  /** 用例模板预览 / 编辑时替换占位符使用的上下文（按首条选中故障） */
  const previewContext: CaseTemplateContext | null =
    platform && targetCamera && previewFault
      ? buildFaultCaseContext(platform, targetCamera.row, options, previewFault)
      : null
  const sharedTemplate = faultCaseTemplateOf(options)
  const editingFault =
    editingFaultNo === null
      ? undefined
      : catalog.items.find((item) => item.no === editingFaultNo)
  const editingTemplate =
    editingFault ? faultCaseTemplateOf(options, editingFault.no) : null
  const editingContext: CaseTemplateContext | null =
    platform && targetCamera && editingFault
      ? buildFaultCaseContext(platform, targetCamera.row, options, editingFault)
      : null
  const unusableTemplateCount = items.filter(
    (item) => !isFaultCaseTemplateUsable(effectiveFaultCaseTemplate(options, item.no)),
  ).length
  /** 切换故障清单：脚本路径与故障勾选回到该清单的默认值 */
  const changeCatalog = (key: string) => {
    const next = findFaultCatalog(key)
    onOptionsChange({
      ...options,
      catalog: next.key,
      script_path: next.script_path,
      faults: next.items.map((item) => item.no),
    })
  }

  const setFaults = (faults: number[]) => onOptionsChange({ ...options, faults })

  /** 修改所有故障共用的模板字段（只保存用户改动的字段，其余继续回退默认值） */
  const updateSharedTemplate = (patch: FaultCaseTemplatePatch) => {
    onOptionsChange({
      ...options,
      case_template: { ...(options.case_template ?? {}), ...patch },
    })
  }

  /** 恢复默认模板：清空共享模板，按故障号覆盖的模板不受影响 */
  const resetSharedTemplate = () => {
    const next = { ...options }
    delete next.case_template
    onOptionsChange(next)
  }

  /** 修改某条故障单独覆盖的模板字段 */
  const updateFaultTemplate = (faultNo: number, patch: FaultCaseTemplatePatch) => {
    const key = String(faultNo)
    const current = options.fault_templates?.[key] ?? {}
    onOptionsChange({
      ...options,
      fault_templates: {
        ...(options.fault_templates ?? {}),
        [key]: { ...current, ...patch },
      },
    })
  }

  /** 清除某条故障的单独覆盖，重新跟随共享模板 */
  const resetFaultTemplate = (faultNo: number) => {
    const next = { ...options }
    const overrides = { ...(options.fault_templates ?? {}) }
    delete overrides[String(faultNo)]
    if (Object.keys(overrides).length === 0) {
      delete next.fault_templates
    } else {
      next.fault_templates = overrides
    }
    onOptionsChange(next)
  }

  /** 共享 / 单条故障共用的模板编辑表单（文本字段均支持占位符） */
  const renderTemplateFields = (
    template: FaultCaseTemplate,
    onChange: (patch: FaultCaseTemplatePatch) => void,
    context: CaseTemplateContext | null,
    previewLabel: string,
  ) => (
    <Space direction="vertical" size={10} style={{ width: '100%' }}>
      <Row gutter={12}>
        <Col xs={24} md={18}>
          <Text type="secondary">用例描述</Text>
          <Input
            value={template.description}
            onChange={(event) => onChange({ description: event.target.value })}
            placeholder="{fault_name}故障验证"
          />
        </Col>
        <Col xs={24} md={6}>
          <Text type="secondary">优先级</Text>
          <Input
            value={template.priority}
            onChange={(event) => onChange({ priority: event.target.value })}
            placeholder="P1"
          />
        </Col>
      </Row>

      <div>
        <Text type="secondary">前置条件</Text>
        <Input.TextArea
          autoSize={{ minRows: 2, maxRows: 5 }}
          value={template.prerequisites}
          onChange={(event) => onChange({ prerequisites: event.target.value })}
        />
      </div>

      <div>
        <Text type="secondary">测试步骤（支持占位符）</Text>
        <Input.TextArea
          autoSize={{ minRows: 5, maxRows: 16 }}
          value={template.steps}
          onChange={(event) => onChange({ steps: event.target.value })}
          style={{ fontFamily: 'monospace' }}
        />
        <div style={{ marginTop: 6 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            点击占位符追加到测试步骤末尾：
          </Text>
          <div style={{ marginTop: 4 }}>
            <Space wrap size={[4, 4]}>
              {FAULT_CASE_PLACEHOLDERS.map((item) => (
                <Tooltip key={item.key} title={item.label}>
                  <Tag
                    color="geekblue"
                    style={{ cursor: 'pointer', marginInlineEnd: 0, fontSize: 12 }}
                    onClick={() =>
                      onChange({
                        steps: appendPlaceholderText(template.steps, `{${item.key}}`),
                      })
                    }
                  >
                    {`{${item.key}}`}
                  </Tag>
                </Tooltip>
              ))}
            </Space>
          </div>
        </div>
      </div>

      <div>
        <Text type="secondary">预期结果（支持占位符）</Text>
        <Input.TextArea
          autoSize={{ minRows: 3, maxRows: 8 }}
          value={template.expected}
          onChange={(event) => onChange({ expected: event.target.value })}
        />
        <Text type="secondary" style={{ fontSize: 12 }}>
          建议保留「故障注入」「{'{error_code}'}」等描述，执行器会据此将用例识别为故障测试。
        </Text>
      </div>

      {context && (
        <Row gutter={16}>
          <Col xs={24} lg={12}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              测试步骤预览（{previewLabel}）
            </Text>
            <pre style={codeStyle}>{renderCaseTemplate(template.steps, context)}</pre>
          </Col>
          <Col xs={24} lg={12}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              预期结果预览（{previewLabel}）
            </Text>
            <pre style={codeStyle}>{renderCaseTemplate(template.expected, context)}</pre>
          </Col>
        </Row>
      )}
    </Space>
  )

  const columns: ColumnsType<FaultCatalogItem> = [
    { title: '故障号', dataIndex: 'no', key: 'no', width: 80 },
    { title: '故障名称', dataIndex: 'name', key: 'name' },
    {
      title: 'CDI 故障码',
      dataIndex: 'error_code',
      key: 'error_code',
      render: (value: string) => <Tag color="volcano">{value}</Tag>,
    },
    {
      title: '模板',
      key: 'template',
      width: 120,
      render: (_value, item: FaultCatalogItem) => {
        const customized = Boolean(options.fault_templates?.[String(item.no)])
        return (
          <Space size={4}>
            <Button type="link" size="small" onClick={() => setEditingFaultNo(item.no)}>
              编辑
            </Button>
            {customized && <Tag color="orange">已自定义</Tag>}
          </Space>
        )
      },
    },
  ]

  /** 首条用例预览（与正式生成走同一套逻辑） */
  const previewCase =
    platform && selection.fault && items.length > 0
      ? generateFaultCases({ platform, selection, options })[0]
      : undefined

  return (
    <div style={{ display: visible ? undefined : 'none' }}>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="故障测试：注入 sensor 内部故障并清除"
        description="按勾选的故障逐条生成用例：终端A 起流并观察，终端B 执行故障注入脚本注入故障，终端A 查看上报的 CDI 故障码，再在终端B 清除故障。默认注入命令为 ./fault_simulation_728_qnx.sh -i 9 -a 4c -n <故障号> [-c]，脚本路径、总线、地址、观察指令等可直接在下方用例模板中编辑。"
      />

      {!platform ? (
        <Empty description="请先在「平台配置」步骤选择平台配置" style={{ padding: '32px 0' }} />
      ) : (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Space wrap>
            <Checkbox
              checked={selection.fault}
              onChange={(event) =>
                onSelectionChange({ ...selection, fault: event.target.checked })
              }
            >
              {TEST_TYPE_FAULT}
            </Checkbox>
            <Tag color="volcano">故障注入</Tag>
            <Text type="secondary">
              {!selection.fault
                ? '未启用故障测试，不会生成故障测试用例'
                : items.length === 0
                  ? '请至少勾选一条故障'
                  : `将生成 ${items.length} 条用例（清单 ${catalog.label}）`}
            </Text>
          </Space>

          <div style={{ maxWidth: 320 }}>
            <Text strong>故障清单</Text>
            <Select
              style={{ width: '100%', marginTop: 4 }}
              value={options.catalog}
              onChange={changeCatalog}
              options={FAULT_CATALOGS.map((item) => ({ value: item.key, label: item.label }))}
            />
          </div>

          <Divider orientation="left" style={{ margin: '4px 0' }}>
            用例模板（支持占位符）
          </Divider>
          <Space wrap align="center">
            <Text type="secondary" style={{ fontSize: 12 }}>
              所有故障共用这套模板，生成时按每条故障替换 {'{fault_no}'} / {'{fault_name}'} /
              {' '}{'{error_code}'} 等占位符；点击故障表格中的「编辑」可为单条故障单独调整。
              脚本 / I2C 总线 / Sensor 地址 / 观察指令 / nito 目录等参数直接在模板中书写，
              也可以使用占位符按默认参数替换；需要其它值时直接改成实际内容即可。
              未自定义测试步骤 / 预期结果时，关闭「生成『清除故障』步骤」会自动去掉默认模板中的清除步骤。
            </Text>
            {options.case_template && (
              <Button size="small" onClick={resetSharedTemplate}>
                恢复默认模板
              </Button>
            )}
          </Space>
          {renderTemplateFields(
            sharedTemplate,
            updateSharedTemplate,
            previewContext,
            previewFault ? `第 ${previewFault.no} 号故障` : '尚无可预览的故障',
          )}
          {selection.fault && unusableTemplateCount > 0 && (
            <Text type="danger" style={{ fontSize: 12 }}>
              有 {unusableTemplateCount} 条故障的模板描述 / 测试步骤 / 预期结果均为空，
              生成后对应单元格会为空，请补充模板内容。
            </Text>
          )}

          {selection.fault && (
            <>
              <Space wrap>
                <Button onClick={() => setFaults(catalog.items.map((item) => item.no))}>
                  全选
                </Button>
                <Button onClick={() => setFaults([])}>清空</Button>
                <Checkbox
                  checked={options.clear_fault}
                  onChange={(event) =>
                    onOptionsChange({ ...options, clear_fault: event.target.checked })
                  }
                >
                  生成「清除故障」步骤
                </Checkbox>
                <Text type="secondary">共 {items.length} / {catalog.items.length} 条</Text>
              </Space>

              <Table
                size="small"
                bordered
                rowKey="no"
                columns={columns}
                dataSource={catalog.items}
                pagination={false}
                scroll={{ y: 320 }}
                rowSelection={{
                  selectedRowKeys: options.faults,
                  onChange: (keys) => setFaults(keys.map((key) => Number(key))),
                }}
              />

              {previewCase && (
                <Row gutter={16}>
                  <Col span={24}>
                    <Text strong>
                      用例预览（{items[0]?.no} 号 · {items[0]?.name}）
                    </Text>
                    <pre style={codeStyle}>{previewCase.steps}</pre>
                  </Col>
                </Row>
              )}
            </>
          )}

          <div style={{ textAlign: 'right' }}>
            <Button
              type="primary"
              disabled={!selection.fault || items.length === 0}
              onClick={onGenerate}
            >
              生成用例
            </Button>
          </div>
        </Space>
      )}

      <Modal
        open={editingFault !== undefined}
        title={
          editingFault
            ? `编辑故障 ${editingFault.no} · ${editingFault.name} 的用例模板`
            : '编辑故障用例模板'
        }
        width={960}
        destroyOnClose
        onCancel={() => setEditingFaultNo(null)}
        footer={
          <Space>
            {editingFault && options.fault_templates?.[String(editingFault.no)] && (
              <Button onClick={() => resetFaultTemplate(editingFault.no)}>
                恢复共享模板
              </Button>
            )}
            <Button type="primary" onClick={() => setEditingFaultNo(null)}>
              完成
            </Button>
          </Space>
        }
      >
        {editingFault && editingTemplate && (
          <Space direction="vertical" size={10} style={{ width: '100%' }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              这里修改的字段只对 {editingFault.no} 号故障生效，并优先于上方共享模板。
              占位符中的故障号 / 名称 / CDI 故障码会自动取当前故障。
            </Text>
            {renderTemplateFields(
              editingTemplate,
              (patch) => updateFaultTemplate(editingFault.no, patch),
              editingContext,
              `第 ${editingFault.no} 号故障`,
            )}
          </Space>
        )}
      </Modal>
    </div>
  )
}
