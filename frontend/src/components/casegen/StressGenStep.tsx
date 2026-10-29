/**
 * 生成测试用例 — 压力测试配置步骤。
 *
 * 每条用例可单独配置：
 * - 起流相机组合：选择一个或多个平台拓扑中的相机，生成命令时合并为同一个 -m 掩码
 * - 反复起流次数：步骤 2 的「反复起流 N 次」
 *
 * 起流命令固定为：
 * ./nvsipl_camera -c <平台> -m "<组合掩码>" -R -0 -1 -2 -s -Z
 */
import {
  Alert,
  Button,
  Checkbox,
  Col,
  Empty,
  InputNumber,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import {
  buildStressCommand,
  topologyRowKey,
} from '../../utils/casegen/functionalCases'
import {
  DEFAULT_STRESS_REPEAT_COUNT,
  TEST_TYPE_STRESS,
} from '../../types/casegen'
import type {
  FunctionalTestSelection,
  PlatformConfig,
  PlatformTopologyRow,
  StressCameraCombination,
  StressTestOptions,
} from '../../types/casegen'

const { Text } = Typography

interface Props {
  visible: boolean
  platform: PlatformConfig | null
  options: StressTestOptions
  onOptionsChange: (options: StressTestOptions) => void
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

/** 生成组合唯一 id（同时用于用例 key 与表格 rowKey） */
function newCombinationId(): string {
  return `combo-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function createCombination(
  cameraKeys: string[],
  repeatCount = DEFAULT_STRESS_REPEAT_COUNT,
): StressCameraCombination {
  return {
    id: newCombinationId(),
    camera_keys: cameraKeys,
    repeat_count: repeatCount,
  }
}

/** 相机选择项的展示文本：Group / linkIndex / 模组 / sensor */
function cameraLabel(row: PlatformTopologyRow, index: number): string {
  return (
    `Group ${row.group} / link ${row.link_index} · ${row.module || '-'}` +
    `${row.sensor ? ` · ${row.sensor}` : ''}（拓扑行 ${index + 1}）`
  )
}

export default function StressGenStep({
  visible,
  platform,
  options,
  onOptionsChange,
  selection,
  onSelectionChange,
  onGenerate,
}: Props) {
  const combinations = options.combinations ?? []
  const cameraOptions = (platform?.topology ?? []).map((row, index) => ({
    value: topologyRowKey(row, index),
    label: cameraLabel(row, index),
  }))
  const rowByKey = new Map<string, PlatformTopologyRow>()
  platform?.topology.forEach((row, index) => rowByKey.set(topologyRowKey(row, index), row))

  /** 能生成用例的组合：至少选择了一台相机 */
  const validCombinations = combinations.filter(
    (combination) => combination.camera_keys.length > 0,
  )
  const selectedCameraTotal = validCombinations.reduce(
    (total, combination) => total + combination.camera_keys.length,
    0,
  )

  const firstPreview = validCombinations[0]
  const previewRows = firstPreview
    ? firstPreview.camera_keys
        .map((key) => rowByKey.get(key))
        .filter((row): row is PlatformTopologyRow => Boolean(row))
    : []

  const updateCombination = (
    id: string,
    patch: Partial<StressCameraCombination>,
  ) => {
    onOptionsChange({
      ...options,
      combinations: combinations.map((combination) =>
        combination.id === id ? { ...combination, ...patch } : combination,
      ),
    })
  }

  const addCombination = () => {
    const firstKey = platform?.topology.length
      ? topologyRowKey(platform.topology[0], 0)
      : ''
    onOptionsChange({
      ...options,
      combinations: [...combinations, createCombination(firstKey ? [firstKey] : [])],
    })
  }

  /** 每个相机各生成一条用例（追加到现有配置） */
  const addOnePerCamera = () => {
    if (!platform) return
    const next = platform.topology.map((row, index) =>
      createCombination([topologyRowKey(row, index)]),
    )
    onOptionsChange({ ...options, combinations: [...combinations, ...next] })
  }

  /** 所有相机放在同一个组合中同时起流（追加到现有配置） */
  const addAllInOne = () => {
    if (!platform) return
    const allKeys = platform.topology.map((row, index) => topologyRowKey(row, index))
    onOptionsChange({
      ...options,
      combinations: [...combinations, createCombination(allKeys)],
    })
  }

  const removeCombination = (id: string) => {
    onOptionsChange({
      ...options,
      combinations: combinations.filter((combination) => combination.id !== id),
    })
  }

  const columns: ColumnsType<StressCameraCombination> = [
    {
      title: '#',
      key: 'index',
      width: 50,
      render: (_value, _record, index) => index + 1,
    },
    {
      title: '起流相机组合',
      dataIndex: 'camera_keys',
      key: 'camera_keys',
      render: (_value, record) => (
        <Select
          mode="multiple"
          allowClear
          style={{ width: '100%' }}
          placeholder="请选择参与同时起流的相机"
          value={record.camera_keys}
          onChange={(value) => updateCombination(record.id, { camera_keys: value })}
          options={cameraOptions}
          optionFilterProp="label"
          notFoundContent="平台拓扑中没有相机"
        />
      ),
    },
    {
      title: '反复起流次数',
      dataIndex: 'repeat_count',
      key: 'repeat_count',
      width: 150,
      render: (_value, record) => (
        <InputNumber
          min={1}
          max={10000}
          precision={0}
          style={{ width: '100%' }}
          value={record.repeat_count}
          onChange={(value) =>
            updateCombination(record.id, {
              repeat_count: Math.max(1, Math.floor(Number(value ?? DEFAULT_STRESS_REPEAT_COUNT))),
            })
          }
        />
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 80,
      render: (_value, record) => (
        <Button
          danger
          type="link"
          icon={<DeleteOutlined />}
          onClick={() => removeCombination(record.id)}
        >
          删除
        </Button>
      ),
    },
  ]

  return (
    <div style={{ display: visible ? undefined : 'none' }}>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="压力测试：反复起流"
        description='每条用例可单独配置同时起流的相机组合与反复起流次数。起流命令固定为 ./nvsipl_camera -c <平台> -m "<组合掩码>" -R -0 -1 -2 -s -Z，步骤 2 写为「反复起流N次」；系统会按轮次自动注入 gc、检测帧率并退出。'
      />

      {!platform ? (
        <Empty description="请先在「平台配置」步骤选择平台配置" style={{ padding: '32px 0' }} />
      ) : (
        <>
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Space wrap>
              <Checkbox
                checked={selection.stress}
                onChange={(event) =>
                  onSelectionChange({ ...selection, stress: event.target.checked })
                }
              >
                {TEST_TYPE_STRESS}
              </Checkbox>
              <Tag color="volcano">反复起流</Tag>
              <Text type="secondary">
                {!selection.stress
                  ? '未启用压力测试，不会生成压力测试用例'
                  : validCombinations.length === 0
                    ? '请至少添加一条包含相机的组合'
                    : `将生成 ${validCombinations.length} 条用例（共 ${selectedCameraTotal} 个相机配置）`}
              </Text>
            </Space>

            {selection.stress && (
              <>
                <Space wrap>
                  <Button icon={<PlusOutlined />} onClick={addCombination}>
                    添加相机组合
                  </Button>
                  <Tooltip title="为平台拓扑中的每个相机各追加一条单独起流的压力测试用例">
                    <Button onClick={addOnePerCamera}>每个相机各一条</Button>
                  </Tooltip>
                  <Tooltip title="把平台拓扑中的所有相机追加为同一个组合，验证多相机同时起流">
                    <Button onClick={addAllInOne}>全部相机一条组合</Button>
                  </Tooltip>
                </Space>

                {combinations.length === 0 ? (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description="尚未配置压力测试组合，点击「添加相机组合」开始配置"
                    style={{ padding: '16px 0' }}
                  />
                ) : (
                  <Table
                    size="small"
                    bordered
                    rowKey="id"
                    columns={columns}
                    dataSource={combinations}
                    pagination={false}
                  />
                )}

                {previewRows.length > 0 && (
                  <Row gutter={16}>
                    <Col span={24}>
                      <Text strong>
                        压测命令预览（组合 {firstPreview.id.slice(-6)}：
                        {firstPreview.repeat_count} 次）
                      </Text>
                      <pre style={codeStyle}>
                        {[
                          `1、输入命令：${buildStressCommand(platform.name, previewRows)}`,
                          `2、反复起流${firstPreview.repeat_count}次`,
                        ].join('\n')}
                      </pre>
                    </Col>
                  </Row>
                )}
              </>
            )}

            <div style={{ textAlign: 'right' }}>
              <Button
                type="primary"
                disabled={!selection.stress || validCombinations.length === 0}
                onClick={onGenerate}
              >
                生成用例
              </Button>
            </div>
          </Space>
        </>
      )}
    </div>
  )
}
