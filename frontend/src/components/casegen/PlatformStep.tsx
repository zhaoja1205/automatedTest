/**
 * 生成测试用例 — 第二步：读取平台配置并选择硬件拓扑。
 *
 * 读取 predev_mixgroup_platform.json，解析全部 platformConfigs；
 * 用户选择其中一个配置后，展示由 deviceBlocks 推导出的 Group / Link / 模组拓扑。
 */
import { useState } from 'react'
import { isAxiosError } from 'axios'
import {
  Alert,
  Button,
  Descriptions,
  Empty,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { parsePlatformConfig } from '../../api/casegenApi'
import { DEFAULT_PLATFORM_CONFIG_PATH } from '../../types/casegen'
import type { PlatformConfigParseResult, PlatformTopologyRow } from '../../types/casegen'

const { Text } = Typography

interface Props {
  visible: boolean
  data: PlatformConfigParseResult | null
  selectedName: string
  onData: (data: PlatformConfigParseResult) => void
  onSelect: (name: string) => void
}

const getErrorMessage = (error: unknown, fallback: string) => {
  if (isAxiosError<{ detail?: string }>(error)) {
    return error.response?.data?.detail || error.message || fallback
  }
  if (error instanceof Error) return error.message
  return fallback
}

const TOPOLOGY_COLUMNS: ColumnsType<PlatformTopologyRow> = [
  { title: 'GROUP', dataIndex: 'group', key: 'group', width: 90, render: (g: string) => `Group ${g}` },
  { title: 'linkIndex', dataIndex: 'link_index', key: 'link_index', width: 90 },
  { title: '模组型号', dataIndex: 'module', key: 'module', width: 190 },
  { title: 'Sensor', dataIndex: 'sensor', key: 'sensor', width: 110 },
  { title: 'Sensor I2C', dataIndex: 'sensor_i2c', key: 'sensor_i2c', width: 110, render: (v: string) => v || '-' },
  {
    title: 'Sensor ID', dataIndex: 'sensor_id', key: 'sensor_id', width: 90,
    render: (v: number | null) => (v === null || v === undefined ? '-' : v),
  },
  { title: 'Serializer', dataIndex: 'serializer', key: 'serializer', width: 100, render: (v: string) => v || '-' },
  { title: 'Serializer I2C', dataIndex: 'serializer_i2c', key: 'serializer_i2c', width: 120, render: (v: string) => v || '-' },
  { title: 'CSI Port', dataIndex: 'csi_port', key: 'csi_port', width: 90 },
  { title: 'PHY', dataIndex: 'phy_mode', key: 'phy_mode', width: 70 },
  { title: '解串器', dataIndex: 'deserializer', key: 'deserializer', width: 170 },
  {
    title: '掩码位', dataIndex: 'mask_bit', key: 'mask_bit', width: 90,
    render: (v: string) => (v ? <Tag color="blue">{v}</Tag> : '-'),
  },
]

export default function PlatformStep({ visible, data, selectedName, onData, onSelect }: Props) {
  const [path, setPath] = useState(DEFAULT_PLATFORM_CONFIG_PATH)
  const [loading, setLoading] = useState(false)

  const selected = data?.platform_configs.find((c) => c.name === selectedName) || null

  const handleLoad = async () => {
    if (!path.trim()) {
      message.warning('请输入配置文件路径')
      return
    }
    setLoading(true)
    try {
      const res = await parsePlatformConfig(path.trim())
      const configs = res.data.platform_configs
      onData(res.data)
      const keep = configs.some((c) => c.name === selectedName)
      if (!keep && configs.length > 0) onSelect(configs[0].name)
      message.success(`已读取 ${configs.length} 个平台配置`)
    } catch (error) {
      message.error(getErrorMessage(error, '读取配置文件失败'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ display: visible ? undefined : 'none' }}>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="读取平台配置文件"
        description="读取 predev_mixgroup_platform.json 后，选择其中一个平台配置作为本项目的硬件拓扑。"
      />

      <Space.Compact style={{ width: '100%', marginBottom: 16 }}>
        <Input
          value={path}
          onChange={(e) => setPath(e.target.value)}
          placeholder="平台配置文件绝对路径"
          onPressEnter={() => void handleLoad()}
        />
        <Button type="primary" loading={loading} onClick={() => void handleLoad()}>
          读取配置
        </Button>
      </Space.Compact>

      {!data ? (
        <Empty description="尚未读取配置文件" style={{ padding: '32px 0' }} />
      ) : (
        <>
          <Space wrap align="center" style={{ marginBottom: 12 }}>
            <Text strong>平台配置</Text>
            <Select
              value={selectedName || undefined}
              onChange={onSelect}
              placeholder="请选择平台配置"
              style={{ minWidth: 420 }}
              showSearch
              optionFilterProp="label"
              options={data.platform_configs.map((config) => ({
                value: config.name,
                label: config.name,
              }))}
            />
            <Text type="secondary">{data.file_name}</Text>
          </Space>

          {selected ? (
            <>
              <Descriptions size="small" column={1} bordered style={{ marginBottom: 16 }}>
                <Descriptions.Item label="名称">
                  <Text code>{selected.name}</Text>
                </Descriptions.Item>
                <Descriptions.Item label="描述">{selected.description || '-'}</Descriptions.Item>
                <Descriptions.Item label="Group 掩码">
                  <Space wrap size={4}>
                    {selected.enable_masks.map((mask, index) => (
                      <Tag key={`${mask}-${index}`}>
                        Group {String.fromCharCode(65 + index)}: {mask}
                      </Tag>
                    ))}
                  </Space>
                </Descriptions.Item>
                <Descriptions.Item label="规模">
                  {selected.group_count} 个 Group / {selected.module_count} 个模组
                </Descriptions.Item>
              </Descriptions>

              <Table
                size="small"
                rowKey={(row) => `${row.group_index}-${row.link_index}`}
                columns={TOPOLOGY_COLUMNS}
                dataSource={selected.topology}
                pagination={false}
                scroll={{ x: 1400 }}
              />
            </>
          ) : (
            <Empty description="请选择一个平台配置" />
          )}
        </>
      )}
    </div>
  )
}
