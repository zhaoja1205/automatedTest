/**
 * 生成测试用例 — 故障测试配置步骤。
 *
 * 交互与功能测试一致：顶部为标签栏，每个标签对应一个故障来源 / 故障清单
 * （当前为 IMX728），点击标签切换配置；标签内可启用、编辑用例模板并勾选故障。
 * 生成用例的测试类型由标签配置决定（目前均为「故障上报」），未来新增其它
 * 故障时在 `FAULT_TEST_TABS` 中追加即可，页面会自动出现新标签。
 *
 * 故障注入默认命令：
 *   ./fault_simulation_728_qnx.sh -i 9 -a 4c -n <故障号> [-c]
 * 脚本路径、总线、地址、观察指令等参数直接在模板中编辑。
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
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  FAULT_TEST_TABS,
  findFaultTestTab,
} from '../../types/casegen'
import type {
  FaultCaseTemplate,
  FaultCaseTemplatePatch,
  FaultCatalogItem,
  FaultTestOptions,
  FaultTestTabConfig,
  FaultTestTabOptions,
  PlatformConfig,
} from '../../types/casegen'
import {
  buildFaultCaseContext,
  effectiveFaultCaseTemplate,
  enabledFaultTabs,
  FAULT_CASE_PLACEHOLDERS,
  faultCaseTemplateOf,
  faultTabOptionsOf,
  isFaultCaseTemplateUsable,
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

/** 标签页左上角的状态圆点：启用为绿色，禁用为灰色 */
const tabDotStyle = (enabled: boolean): React.CSSProperties => ({
  display: 'inline-block',
  width: 6,
  height: 6,
  borderRadius: 3,
  background: enabled ? '#52c41a' : '#d9d9d9',
})

export default function FaultGenStep({
  visible,
  platform,
  options,
  onOptionsChange,
  onGenerate,
}: Props) {
  /** 当前选中的故障标签页 */
  const [activeTabKey, setActiveTabKey] = useState(
    FAULT_TEST_TABS[0]?.key ?? '',
  )
  /** 正在单独编辑模板的标签页与故障号；为空表示未打开弹窗 */
  const [editing, setEditing] = useState<{ tabKey: string; faultNo: number } | null>(
    null,
  )

  const targetCamera = platform ? selectFaultCamera(platform, options) : null
  const enabledTabs = enabledFaultTabs(options)
  const totalSelected = enabledTabs.reduce(
    (total, tab) => total + selectedFaultItems(options, tab).length,
    0,
  )

  /** 修改某个标签页的配置 */
  const updateTab = (
    tab: FaultTestTabConfig,
    patch: Partial<FaultTestTabOptions>,
  ) => {
    const current = faultTabOptionsOf(options, tab)
    onOptionsChange({
      ...options,
      tabs: {
        ...options.tabs,
        [tab.key]: { ...current, ...patch },
      },
    })
  }

  const setFaults = (tab: FaultTestTabConfig, faults: number[]) =>
    updateTab(tab, { faults })

  /** 修改标签页内所有故障共用的模板字段（只保存改动字段，其余继续回退默认值） */
  const updateSharedTemplate = (
    tab: FaultTestTabConfig,
    patch: FaultCaseTemplatePatch,
  ) => {
    const current = faultTabOptionsOf(options, tab)
    updateTab(tab, {
      case_template: { ...(current.case_template ?? {}), ...patch },
    })
  }

  /** 恢复标签页的默认模板 */
  const resetSharedTemplate = (tab: FaultTestTabConfig) =>
    updateTab(tab, { case_template: undefined })

  /** 修改某条故障单独覆盖的模板字段 */
  const updateFaultTemplate = (
    tab: FaultTestTabConfig,
    faultNo: number,
    patch: FaultCaseTemplatePatch,
  ) => {
    const key = String(faultNo)
    const current = faultTabOptionsOf(options, tab)
    const overrides = current.fault_templates ?? {}
    updateTab(tab, {
      fault_templates: {
        ...overrides,
        [key]: { ...(overrides[key] ?? {}), ...patch },
      },
    })
  }

  /** 清除某条故障的单独覆盖，重新跟随标签页共享模板 */
  const resetFaultTemplate = (tab: FaultTestTabConfig, faultNo: number) => {
    const overrides = {
      ...(faultTabOptionsOf(options, tab).fault_templates ?? {}),
    }
    delete overrides[String(faultNo)]
    updateTab(tab, {
      fault_templates:
        Object.keys(overrides).length > 0 ? overrides : undefined,
    })
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
            placeholder="第{fault_no}号故障验证"
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

  /** 单个标签页的故障表格列（「编辑」用于单独调整该故障的模板） */
  const columnsFor = (tab: FaultTestTabConfig): ColumnsType<FaultCatalogItem> => [
    { title: '故障号', dataIndex: 'no', key: 'no', width: 80 },
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
        const customized = Boolean(
          faultTabOptionsOf(options, tab).fault_templates?.[String(item.no)],
        )
        return (
          <Space size={4}>
            <Button
              type="link"
              size="small"
              onClick={() =>
                setEditing({ tabKey: tab.key, faultNo: item.no })
              }
            >
              编辑
            </Button>
            {customized && <Tag color="orange">已自定义</Tag>}
          </Space>
        )
      },
    },
  ]

  /** 标签页内容：启用开关、测试类型、模板编辑与故障勾选 */
  const renderTabPanel = (tab: FaultTestTabConfig) => {
    const tabOptions = faultTabOptionsOf(options, tab)
    const items = selectedFaultItems(options, tab)
    const sharedTemplate = faultCaseTemplateOf(options, tab.key)
    const previewFault = items[0]
    const previewContext: CaseTemplateContext | null =
      platform && targetCamera && previewFault
        ? buildFaultCaseContext(platform, targetCamera.row, options, previewFault)
        : null
    const unusableCount = tabOptions.enabled
      ? items.filter(
          (item) =>
            !isFaultCaseTemplateUsable(
              effectiveFaultCaseTemplate(options, tab.key, item.no),
            ),
        ).length
      : 0

    return (
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Space wrap align="center">
          <Checkbox
            checked={tabOptions.enabled}
            onChange={(event) =>
              updateTab(tab, { enabled: event.target.checked })
            }
          >
            参与本次生成
          </Checkbox>
          <Text type="secondary">测试类型：</Text>
          <Tag color="volcano">{tab.test_type}</Tag>
          <Text type="secondary">
            {tabOptions.enabled
              ? items.length === 0
                ? '请至少勾选一条故障'
                : `将生成 ${items.length} 条用例（清单 ${tab.catalog.label}）`
              : '未启用，不会生成该标签页的用例'}
          </Text>
        </Space>

        <Divider orientation="left" style={{ margin: '4px 0' }}>
          用例模板（支持占位符）
        </Divider>
        <Space wrap align="center">
          <Text type="secondary" style={{ fontSize: 12 }}>
            该标签页的所有故障共用这套模板，生成时按每条故障替换 {'{fault_no}'} /
            {' '}{'{error_code}'} 等占位符；点击故障表格中的
            「编辑」可单条调整。脚本 / 总线 / 地址 / 观察指令等参数直接在模板中书写。
            未自定义测试步骤 / 预期结果时，关闭「生成『清除故障』步骤」会自动去掉
            默认模板中的清除步骤。
          </Text>
          {tabOptions.case_template && (
            <Button size="small" onClick={() => resetSharedTemplate(tab)}>
              恢复默认模板
            </Button>
          )}
        </Space>
        {renderTemplateFields(
          sharedTemplate,
          (patch) => updateSharedTemplate(tab, patch),
          previewContext,
          previewFault ? `第 ${previewFault.no} 号故障` : '尚无可预览的故障',
        )}

        {tabOptions.enabled && unusableCount > 0 && (
          <Text type="danger" style={{ fontSize: 12 }}>
            有 {unusableCount} 条故障的模板描述 / 测试步骤 / 预期结果均为空，
            生成后对应单元格会为空，请补充模板内容。
          </Text>
        )}

        <Space wrap>
          <Button
            onClick={() => setFaults(tab, tab.catalog.items.map((item) => item.no))}
          >
            全选
          </Button>
          <Button onClick={() => setFaults(tab, [])}>清空</Button>
          <Text type="secondary">
            共 {items.length} / {tab.catalog.items.length} 条
          </Text>
        </Space>

        <Table
          size="small"
          bordered
          rowKey="no"
          columns={columnsFor(tab)}
          dataSource={tab.catalog.items}
          pagination={false}
          scroll={{ y: 320 }}
          rowSelection={{
            selectedRowKeys: tabOptions.faults,
            onChange: (keys) => setFaults(tab, keys.map((key) => Number(key))),
          }}
        />
      </Space>
    )
  }

  const tabItems = FAULT_TEST_TABS.map((tab) => ({
    key: tab.key,
    label: (
      <Space size={6}>
        <span style={tabDotStyle(faultTabOptionsOf(options, tab).enabled)} />
        <span>{tab.label}</span>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {tab.test_type}
        </Text>
      </Space>
    ),
    children: renderTabPanel(tab),
  }))

  const editingTab = editing ? findFaultTestTab(editing.tabKey) : undefined
  const editingFault = editing
    ? editingTab?.catalog.items.find((item) => item.no === editing.faultNo)
    : undefined
  const editingTemplate =
    editingTab && editingFault
      ? faultCaseTemplateOf(options, editingTab.key, editingFault.no)
      : null
  const editingContext: CaseTemplateContext | null =
    platform && targetCamera && editingFault
      ? buildFaultCaseContext(platform, targetCamera.row, options, editingFault)
      : null

  return (
    <div style={{ display: visible ? undefined : 'none' }}>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="故障测试：注入 sensor 内部故障并清除（点击标签切换故障类型）"
        description="每个标签页对应一类故障来源，点击标签切换配置；标签内可启用、编辑用例模板并勾选故障。默认注入命令为 ./fault_simulation_728_qnx.sh -i 9 -a 4c -n <故障号> [-c]，脚本路径、总线、地址、观察指令等可直接在用例模板中编辑。当前所有标签的测试类型均为「故障上报」，未来新增其它故障时会自动出现新的标签页。"
      />

      {!platform ? (
        <Empty description="请先在「平台配置」步骤选择平台配置" style={{ padding: '32px 0' }} />
      ) : (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Space wrap align="center" style={{ width: '100%', justifyContent: 'space-between' }}>
            <Space wrap align="center">
              <Checkbox
                checked={options.clear_fault}
                onChange={(event) =>
                  onOptionsChange({ ...options, clear_fault: event.target.checked })
                }
              >
                生成「清除故障」步骤
              </Checkbox>
              <Text type="secondary">
                已启用 {enabledTabs.length} 个标签页，共 {totalSelected} 条故障
              </Text>
            </Space>
            <Button
              type="primary"
              disabled={enabledTabs.length === 0 || totalSelected === 0}
              onClick={onGenerate}
            >
              生成用例
            </Button>
          </Space>

          <Tabs
            type="card"
            activeKey={activeTabKey}
            onChange={setActiveTabKey}
            items={tabItems}
          />
        </Space>
      )}

      <Modal
        open={editing !== null && editingFault !== undefined}
        title={
          editingTab && editingFault
            ? `编辑 ${editingTab.label} · 故障 ${editingFault.no} 的用例模板`
            : '编辑故障用例模板'
        }
        width={960}
        destroyOnClose
        onCancel={() => setEditing(null)}
        footer={
          <Space>
            {editingTab && editing && editingFault &&
              faultTabOptionsOf(options, editingTab).fault_templates?.[
                String(editingFault.no)
              ] && (
                <Button
                  onClick={() =>
                    resetFaultTemplate(editingTab, editingFault.no)
                  }
                >
                  恢复共享模板
                </Button>
              )}
            <Button type="primary" onClick={() => setEditing(null)}>
              完成
            </Button>
          </Space>
        }
      >
        {editingTab && editingFault && editingTemplate && (
          <Space direction="vertical" size={10} style={{ width: '100%' }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              这里修改的字段只对 {editingTab.label} 的 {editingFault.no} 号故障生效，
              并优先于该标签页的共享模板。占位符中的故障号 / 名称 / CDI 故障码会自动取当前故障。
            </Text>
            {renderTemplateFields(
              editingTemplate,
              (patch) =>
                updateFaultTemplate(editingTab, editingFault.no, patch),
              editingContext,
              `第 ${editingFault.no} 号故障`,
            )}
          </Space>
        )}
      </Modal>
    </div>
  )
}
