/**
 * 生成测试用例 — 第三步：Sensor 配置（可选）。
 *
 * 从 sensor 数据库文件（如 predev_mixgroup/imx623.json）读取 imageSensors，
 * 支持添加 0 个或多个配置文件；读取结果在后续功能测试步骤中用于补充用例信息。
 */
import { useState, useEffect } from 'react'
import { isAxiosError } from 'axios'
import {
  Alert,
  Button,
  Descriptions,
  Empty,
  Input,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { DeleteOutlined } from '@ant-design/icons'
import { parseSensorConfig } from '../../api/casegenApi'
import { DEFAULT_SENSOR_CONFIG_PATH } from '../../types/casegen'
import type {
  SensorConfig,
  SensorConfigFile,
  SensorConfigParseResult,
  SensorVirtualChannel,
} from '../../types/casegen'
import { formatVirtualChannel } from '../../utils/casegen/sensors'

const { Text } = Typography

interface Props {
  visible: boolean
  data: SensorConfigParseResult | null
  onData: (data: SensorConfigParseResult | null) => void
  /** 已添加的文件路径列表变化时通知父组件（用于自动保存/草稿） */
  onPathsChange?: (paths: string[]) => void
  /** 从父组件恢复的文件路径列表（草稿恢复） */
  defaultPaths?: string[]
}

const getErrorMessage = (error: unknown, fallback: string) => {
  if (isAxiosError<{ detail?: string }>(error)) {
    return error.response?.data?.detail || error.message || fallback
  }
  if (error instanceof Error) return error.message
  return fallback
}

/** 合并文件列表：同一路径以新读取结果覆盖，保持原有顺序 */
function mergeFiles(current: SensorConfigFile[], incoming: SensorConfigFile[]): SensorConfigFile[] {
  const map = new Map(current.map((file) => [file.path, file]))
  incoming.forEach((file) => map.set(file.path, file))
  return Array.from(map.values())
}

function buildResult(files: SensorConfigFile[]): SensorConfigParseResult | null {
  if (files.length === 0) return null
  return { files, sensors: files.flatMap((file) => file.sensors) }
}

const VC_COLUMNS: ColumnsType<SensorVirtualChannel> = [
  { title: 'VC', dataIndex: 'index', key: 'index', width: 60, render: (v: number) => `VC${v}` },
  {
    title: '分辨率', key: 'resolution', width: 120,
    render: (_v, row) =>
      row.width !== null && row.height !== null ? `${row.width} x ${row.height}` : '-',
  },
  { title: 'FPS', dataIndex: 'fps', key: 'fps', width: 70, render: (v: number | null) => v ?? '-' },
  { title: 'CFA', dataIndex: 'cfa', key: 'cfa', width: 80, render: (v: string) => v || '-' },
  { title: '输入格式', dataIndex: 'input_format', key: 'input_format', width: 100, render: (v: string) => v || '-' },
  {
    title: 'Embedded 行数 (Top/Bottom)', key: 'embedded', width: 180,
    render: (_v, row) =>
      row.embedded_top_lines === null && row.embedded_bottom_lines === null
        ? '-'
        : `${row.embedded_top_lines ?? 0} / ${row.embedded_bottom_lines ?? 0}`,
  },
  {
    title: 'Embedded Data Type', dataIndex: 'embedded_data_type_enabled', key: 'embedded_data_type_enabled', width: 130,
    render: (v: boolean) => (v ? <Tag color="green">开</Tag> : <Tag>关</Tag>),
  },
]

const SENSOR_COLUMNS: ColumnsType<SensorConfig> = [
  {
    title: 'Sensor', dataIndex: 'name', key: 'name', width: 130,
    render: (v: string) => <Text strong>{v || '-'}</Text>,
  },
  { title: '描述', dataIndex: 'description', key: 'description', width: 220, render: (v: string) => v || '-' },
  { title: 'I2C 地址', dataIndex: 'i2c_address', key: 'i2c_address', width: 100, render: (v: string) => v || '-' },
  {
    title: '虚拟通道', key: 'virtual_channels', width: 190,
    render: (_v, row) => (
      <Space size={4} wrap>
        {row.virtual_channels.length === 0 ? '-' : row.virtual_channels.map((channel) => (
          <Tag key={channel.index} color="blue">{formatVirtualChannel(channel)}</Tag>
        ))}
      </Space>
    ),
  },
  {
    title: 'Trigger 模式', dataIndex: 'trigger_mode_enabled', key: 'trigger_mode_enabled', width: 100,
    render: (v: boolean) => (v ? <Tag color="green">开</Tag> : <Tag>关</Tag>),
  },
  {
    title: 'TPG', dataIndex: 'tpg_enabled', key: 'tpg_enabled', width: 80,
    render: (v: boolean) => (v ? <Tag color="orange">开</Tag> : <Tag>关</Tag>),
  },
  {
    title: 'CDI v2', dataIndex: 'use_cdi_v2_api', key: 'use_cdi_v2_api', width: 80,
    render: (v: boolean) => (v ? <Tag color="green">是</Tag> : <Tag>否</Tag>),
  },
  { title: '来源文件', dataIndex: 'source_file', key: 'source_file', width: 130, render: (v: string) => v || '-' },
]

export default function SensorStep({ visible, data, onData, onPathsChange, defaultPaths }: Props) {
  const [path, setPath] = useState(
    () => defaultPaths?.[defaultPaths.length - 1] || DEFAULT_SENSOR_CONFIG_PATH,
  )
  const [loading, setLoading] = useState(false)

  // 草稿恢复后把输入框同步到最近添加的文件路径
  const defaultPathKey = (defaultPaths ?? []).join('|')
  useEffect(() => {
    if (!defaultPathKey) return
    const paths = defaultPathKey.split('|')
    setPath(paths[paths.length - 1])
  }, [defaultPathKey])

  const files = data?.files ?? []
  const sensors = data?.sensors ?? []

  const handleAdd = async () => {
    const target = path.trim()
    if (!target) {
      message.warning('请输入 sensor 配置文件路径')
      return
    }
    setLoading(true)
    try {
      const res = await parseSensorConfig([target])
      const merged = mergeFiles(files, res.data.files)
      onData(buildResult(merged))
      onPathsChange?.(merged.map((file) => file.path))
      const count = res.data.files.reduce((sum, file) => sum + file.sensors.length, 0)
      message.success(`已读取 ${count} 个 sensor 配置`)
    } catch (error) {
      message.error(getErrorMessage(error, '读取 sensor 配置文件失败'))
    } finally {
      setLoading(false)
    }
  }

  const handleRemove = (target: string) => {
    const remaining = files.filter((file) => file.path !== target)
    onData(buildResult(remaining))
    onPathsChange?.(remaining.map((file) => file.path))
    message.success('已移除该 sensor 配置文件')
  }

  const handleClear = () => {
    onData(null)
    onPathsChange?.([])
    message.success('已清空 sensor 配置')
  }

  return (
    <div style={{ display: visible ? undefined : 'none' }}>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="Sensor 配置（可选，可添加 0 个或多个）"
        description="读取 sensor 数据库文件（如 imx623.json）中的 imageSensors。配置会按 Sensor 名称与平台拓扑中的相机匹配，匹配到的帧率等参数会写入后续生成的用例（预期结果）。"
      />

      <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
        <Input
          value={path}
          onChange={(e) => setPath(e.target.value)}
          placeholder="sensor 配置文件绝对路径，例如 .../predev_mixgroup/imx623.json"
          onPressEnter={() => void handleAdd()}
        />
        <Button type="primary" loading={loading} onClick={() => void handleAdd()}>
          读取并添加
        </Button>
      </Space.Compact>

      <Space wrap align="center" style={{ marginBottom: 12 }}>
        <Text type="secondary">已添加 {files.length} 个文件 / {sensors.length} 个 sensor 配置</Text>
        {files.map((file) => (
          <Tag
            key={file.path}
            color="geekblue"
            closable
            onClose={(e) => {
              e.preventDefault()
              handleRemove(file.path)
            }}
          >
            {file.file_name} ({file.sensors.length})
          </Tag>
        ))}
        {files.length > 0 && (
          <Tooltip title="移除所有已添加的 sensor 配置">
            <Button size="small" danger icon={<DeleteOutlined />} onClick={handleClear}>
              清空
            </Button>
          </Tooltip>
        )}
      </Space>

      {files.length === 0 ? (
        <Empty description="尚未添加 sensor 配置（此步骤可不配置）" style={{ padding: '32px 0' }} />
      ) : (
        <>
          <Table
            size="small"
            rowKey={(row) => `${row.source_path}-${row.sensor_index}`}
            columns={SENSOR_COLUMNS}
            dataSource={sensors}
            pagination={false}
            scroll={{ x: 1200 }}
            expandable={{
              expandedRowRender: (row) => (
                <>
                  <Descriptions size="small" column={2} style={{ marginBottom: 8 }}>
                    <Descriptions.Item label="来源文件">{row.source_file}</Descriptions.Item>
                    <Descriptions.Item label="来源路径">
                      <Text code style={{ fontSize: 12 }}>{row.source_path}</Text>
                    </Descriptions.Item>
                  </Descriptions>
                  <Table
                    size="small"
                    rowKey={(channel) => channel.index}
                    columns={VC_COLUMNS}
                    dataSource={row.virtual_channels}
                    pagination={false}
                    locale={{ emptyText: '该 sensor 未配置 virtualChannels' }}
                  />
                </>
              ),
            }}
          />
        </>
      )}
    </div>
  )
}
