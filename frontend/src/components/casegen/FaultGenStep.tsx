/**
 * 生成测试用例 — 故障测试配置步骤。
 *
 * 顶部为标签栏，标签由用户通过「+」创建，数量不限：每个标签页有可自定义的
 * 名称，并在标签内部选择使用哪一份故障单（当前为 IMX728），标签内可启用、
 * 编辑用例模板并勾选故障。未来新增其它故障单时在 `FAULT_CATALOGS` 中追加，
 * 标签内的故障单下拉即可直接选择。
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
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  FAULT_CATALOGS,
  TEST_TYPE_FAULT,
  defaultFaultTabOptions,
  findFaultCatalog,
} from '../../types/casegen'
import type {
  FaultCaseTemplate,
  FaultCaseTemplatePatch,
  FaultCatalogItem,
  FaultTabInstance,
  FaultTestOptions,
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
  faultTabsOf,
  isFaultCaseTemplateUsable,
  nextFaultTabKey,
  selectedFaultItems,
  selectFaultCamera,
  uniqueFaultTabLabel,
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
  const [activeTabKey, setActiveTabKey] = useState(() =>
    Object.keys(options.tabs ?? {})[0] ?? '',
  )
  /** 正在单独编辑模板的标签页与故障号；为空表示未打开弹窗 */
  const [editing, setEditing] = useState<{ tabKey: string; faultNo: number } | null>(
    null,
  )

  const tabs = faultTabsOf(options)
  // 标签页可能被删除或在刷新后恢复，选中 key 失效时回退到第一个标签
  const activeKey = tabs.some((tab) => tab.key === activeTabKey)
    ? activeTabKey
    : tabs[0]?.key ?? ''

  const targetCamera = platform ? selectFaultCamera(platform, options) : null
  const enabledTabs = enabledFaultTabs(options)
  const totalSelected = enabledTabs.reduce(
    (total, tab) => total + selectedFaultItems(options, tab).length,
    0,
  )

  /** 修改某个标签页的配置 */
  const updateTab = (tabKey: string, patch: Partial<FaultTestTabOptions>) => {
    const current = faultTabOptionsOf(options, tabKey)
    onOptionsChange({
      ...options,
      tabs: {
        ...options.tabs,
        [tabKey]: { ...current, ...patch },
      },
    })
  }

  /** 新建标签页：默认使用第一份故障单，名称自动去重 */
  const addTab = () => {
    const catalog = FAULT_CATALOGS[0]
    const key = nextFaultTabKey(options)
    const label = uniqueFaultTabLabel(catalog.label, options)
    onOptionsChange({
      ...options,
      tabs: {
        ...options.tabs,
        [key]: { ...defaultFaultTabOptions(catalog), label },
      },
    })
    setActiveTabKey(key)
  }

  /** 删除标签页；仅当删除的是当前标签时让选中标签回退到第一个 */
  const removeTab = (tabKey: string) => {
    const nextTabs = { ...options.tabs }
    delete nextTabs[tabKey]
    onOptionsChange({ ...options, tabs: nextTabs })
    if (editing?.tabKey === tabKey) setEditing(null)
    if (activeKey === tabKey) setActiveTabKey('')
  }

  const setFaults = (tabKey: string, faults: number[]) =>
    updateTab(tabKey, { faults })

  /**
   * 切换标签页使用的故障单。
   *
   * 勾选状态保留新故障单中仍存在的故障号；若一条都不存在则默认全选。
   * 标签名称仍为旧故障单默认名称时，同步替换为新故障单名称（已自定义的名称保持不动）。
   */
  const changeCatalog = (tab: FaultTabInstance, catalogKey: string) => {
    const catalog = findFaultCatalog(catalogKey)
    if (catalog.key === tab.catalog.key) return
    const kept = tab.options.faults.filter((no) =>
      catalog.items.some((item) => item.no === no),
    )
    const label =
      tab.options.label === tab.catalog.label
        ? uniqueFaultTabLabel(catalog.label, options, tab.key)
        : tab.options.label
    updateTab(tab.key, {
      catalog: catalog.key,
      faults: kept.length > 0 ? kept : catalog.items.map((item) => item.no),
      label,
    })
    // 单条故障模板按故障号覆盖，切换故障单后弹窗内容已失去意义
    setEditing(null)
  }

  /** 修改标签页内所有故障共用的模板字段（只保存改动字段，其余继续回退默认值） */
  const updateSharedTemplate = (
    tabKey: string,
    patch: FaultCaseTemplatePatch,
  ) => {
    const current = faultTabOptionsOf(options, tabKey)
    updateTab(tabKey, {
      case_template: { ...(current.case_template ?? {}), ...patch },
    })
  }

  /** 恢复标签页的默认模板 */
  const resetSharedTemplate = (tabKey: string) =>
    updateTab(tabKey, { case_template: undefined })

  /** 修改某条故障单独覆盖的模板字段 */
  const updateFaultTemplate = (
    tabKey: string,
    faultNo: number,
    patch: FaultCaseTemplatePatch,
  ) => {
    const key = String(faultNo)
    const current = faultTabOptionsOf(options, tabKey)
    const overrides = current.fault_templates ?? {}
    updateTab(tabKey, {
      fault_templates: {
        ...overrides,
        [key]: { ...(overrides[key] ?? {}), ...patch },
      },
    })
  }

  /** 清除某条故障的单独覆盖，重新跟随标签页共享模板 */
  const resetFaultTemplate = (tabKey: string, faultNo: number) => {
    const overrides = {
      ...(faultTabOptionsOf(options, tabKey).fault_templates ?? {}),
    }
    delete overrides[String(faultNo)]
    updateTab(tabKey, {
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
  const columnsFor = (tab: FaultTabInstance): ColumnsType<FaultCatalogItem> => [
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
          tab.options.fault_templates?.[String(item.no)],
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

  /** 标签页内容：名称、故障单、启用开关、模板编辑与故障勾选 */
  const renderTabPanel = (tab: FaultTabInstance) => {
    const tabOptions = tab.options
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
        <Row gutter={16}>
          <Col xs={24} md={10}>
            <Text type="secondary">标签名称（可自定义）</Text>
            <Input
              value={tabOptions.label}
              maxLength={40}
              placeholder="例如 IMX728 故障上报"
              onChange={(event) =>
                updateTab(tab.key, { label: event.target.value })
              }
            />
          </Col>
          <Col xs={24} md={10}>
            <Text type="secondary">故障单</Text>
            <Select
              value={tabOptions.catalog}
              style={{ width: '100%' }}
              options={FAULT_CATALOGS.map((catalog) => ({
                value: catalog.key,
                label: `${catalog.label}（${catalog.items.length} 条故障）`,
              }))}
              onChange={(catalogKey) => changeCatalog(tab, catalogKey)}
            />
          </Col>
          <Col xs={24} md={4}>
            <Text type="secondary">测试类型</Text>
            <div>
              <Tag color="volcano" style={{ marginTop: 4 }}>
                {TEST_TYPE_FAULT}
              </Tag>
            </div>
          </Col>
        </Row>

        <Space wrap align="center">
          <Checkbox
            checked={tabOptions.enabled}
            onChange={(event) =>
              updateTab(tab.key, { enabled: event.target.checked })
            }
          >
            参与本次生成
          </Checkbox>
          <Text type="secondary">
            {tabOptions.enabled
              ? items.length === 0
                ? '请至少勾选一条故障'
                : `将生成 ${items.length} 条用例（故障单 ${tab.catalog.label}）`
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
            <Button size="small" onClick={() => resetSharedTemplate(tab.key)}>
              恢复默认模板
            </Button>
          )}
        </Space>
        {renderTemplateFields(
          sharedTemplate,
          (patch) => updateSharedTemplate(tab.key, patch),
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
            onClick={() =>
              setFaults(tab.key, tab.catalog.items.map((item) => item.no))
            }
          >
            全选
          </Button>
          <Button onClick={() => setFaults(tab.key, [])}>清空</Button>
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
            onChange: (keys) =>
              setFaults(tab.key, keys.map((key) => Number(key))),
          }}
        />
      </Space>
    )
  }

  const tabItems = tabs.map((tab) => ({
    key: tab.key,
    label: (
      <Space size={6}>
        <span style={tabDotStyle(tab.options.enabled)} />
        <span>{tab.options.label || '未命名标签'}</span>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {tab.catalog.label}
        </Text>
      </Space>
    ),
    children: renderTabPanel(tab),
  }))

  const editingTab = editing
    ? tabs.find((tab) => tab.key === editing.tabKey)
    : undefined
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
        message="故障测试：注入 sensor 内部故障并清除（点击标签切换故障单）"
        description="点击标签栏右侧的「+」新建标签页，标签名称可自定义；每个标签内可选择要使用的故障单（当前支持 IMX728），并可启用、编辑用例模板、勾选故障。默认注入命令为 ./fault_simulation_728_qnx.sh -i 9 -a 4c -n <故障号> [-c]，脚本路径、总线、地址、观察指令等可直接在用例模板中编辑。未来新增其它故障单时，在故障单下拉中即可直接选择。"
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
            type="editable-card"
            activeKey={activeKey}
            onChange={setActiveTabKey}
            items={tabItems}
            onEdit={(targetKey, action) => {
              if (action === 'add') addTab()
              else removeTab(String(targetKey))
            }}
          />
          {tabs.length === 0 && (
            <Empty
              description="还没有故障标签页，点击右上角「+」新建"
              style={{ padding: '32px 0' }}
            />
          )}
        </Space>
      )}

      <Modal
        open={editing !== null && editingFault !== undefined}
        title={
          editingTab && editingFault
            ? `编辑 ${editingTab.options.label} · 故障 ${editingFault.no} 的用例模板`
            : '编辑故障用例模板'
        }
        width={960}
        destroyOnClose
        onCancel={() => setEditing(null)}
        footer={
          <Space>
            {editingTab && editing && editingFault &&
              editingTab.options.fault_templates?.[String(editingFault.no)] && (
                <Button
                  onClick={() =>
                    resetFaultTemplate(editingTab.key, editingFault.no)
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
              这里修改的字段只对 {editingTab.options.label} 的 {editingFault.no} 号故障生效，
              并优先于该标签页的共享模板。占位符中的故障号 / 名称 / CDI 故障码会自动取当前故障。
            </Text>
            {renderTemplateFields(
              editingTemplate,
              (patch) =>
                updateFaultTemplate(editingTab.key, editingFault.no, patch),
              editingContext,
              `第 ${editingFault.no} 号故障`,
            )}
          </Space>
        )}
      </Modal>
    </div>
  )
}
