/**
 * SWE.2 §7 系统集成 编辑面板（Phase C）。
 *
 * - §7.1 集成顺序：一段自由文本（textarea）
 * - §7.2.1-7.2.6 六原则：每条一个 title（固定）+ description（textarea）
 *
 * 和后端 `arch_sections.DEFAULT_INTEGRATION_ORDER` / `DEFAULT_INTEGRATION_PRINCIPLES`
 * 保持一致：留空 → 导出时 generator 走默认值（见 arch_generator._build_swe2_context
 * 的 `integration_src.get("order") or arch_sections.DEFAULT_INTEGRATION_ORDER`）。
 * 这里 placeholder 展示默认文案提示用户可以直接套用。
 *
 * 不处理：原则的 key 和 title 是固定 6 条，和模板里的 7.2.1-7.2.6 一一对应；
 * 不允许增删 —— 加/删一条就会导致 principles_by_key 查不到 → 模板里对应描述段空白。
 * 若未来真的要加/删，须同步改模板 build 脚本的 principle_keys / principle_titles。
 */
import { Alert, Card, Collapse, Input, Space, Tag } from 'antd'
import { FileTextOutlined } from '@ant-design/icons'
import type { Swe2Integration, IntegrationPrinciple } from '../../../types/aspice'

/** 和后端 `arch_sections.DEFAULT_INTEGRATION_ORDER` 对齐；仅用于 placeholder 提示。 */
const DEFAULT_ORDER =
  '集成顺序：Deserializer → Serializer → Sensor。'
  + 'MAX20087、EEPROM、PMIC 注册到框架中。'
  + '按从底层外设到上层应用的顺序逐步集成，每一步均完成功能点验证后再推进。'

/** 和后端 `arch_sections.DEFAULT_INTEGRATION_PRINCIPLES` 的 6 条对齐。
 *  key / title 不能改，否则模板 {{ integration.principles_by_key.<key>.description }} 查不到。
 */
const PRINCIPLE_SKELETON: Omit<IntegrationPrinciple, 'description'>[] = [
  { key: 'usability',   title: '易用性原则' },
  { key: 'security',    title: '安全性原则' },
  { key: 'integrity',   title: '业务完整性原则' },
  { key: 'normalize',   title: '业务规范化原则' },
  { key: 'scalability', title: '可扩展性原则' },
  { key: 'openness',    title: '开放性原则' },
]

/** key → 默认描述文案，仅作 placeholder；留空交由后端走 default。 */
const DEFAULT_DESC: Record<string, string> = {
  usability:   '集成后的系统应保持接口简洁、调用方式一致，上层应用无需感知底层硬件差异。',
  security:    '集成过程中严格区分特权与非特权操作，关键配置（SerDes/Sensor/PMIC）须经校验后生效。',
  integrity:   '任一模块集成不得破坏已集成模块的功能完整性，提交前需回归已有通过项。',
  normalize:   '遵循 NvSIPL 既有接口规范，新增接口须按统一命名/参数风格对齐。',
  scalability: '保留足够扩展位（新 sensor/新 ser/des 型号接入点），避免硬编码特定型号。',
  openness:    '对三方工具链（NV FAE/模组厂）保留可调试、可观测接入点，便于后续迭代。',
}

export interface IntegrationEditorProps {
  value?: Swe2Integration
  onChange: (v: Swe2Integration) => void
}

export default function IntegrationEditor({ value, onChange }: IntegrationEditorProps) {
  // 规范化：确保 principles 永远是 6 条、顺序和 key 固定。
  // 用户历史数据可能少/多/乱序，统一按 skeleton 对齐，取用户填的 description，没有就用空字符串。
  const existingByKey = new Map(
    (value?.principles ?? []).map((p) => [p.key, p.description ?? '']),
  )
  const principles: IntegrationPrinciple[] = PRINCIPLE_SKELETON.map(({ key, title }) => ({
    key,
    title,
    description: existingByKey.get(key) ?? '',
  }))
  const order = value?.order ?? ''

  const patchOrder = (next: string) => onChange({ order: next, principles })
  const patchPrinciple = (idx: number, desc: string) => {
    const copy = principles.slice()
    copy[idx] = { ...copy[idx], description: desc }
    onChange({ order, principles: copy })
  }

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="middle">
      <Alert type="info" showIcon
        message="留空交后端 default"
        description="任一字段留空，后端在导出 docx 时会自动回落到 PreDev 默认文案；想自定义就直接覆盖。" />

      <Card size="small" title={
        <Space>
          <FileTextOutlined />
          <span>§7.1 各模块的集成顺序</span>
          <Tag color={order ? 'green' : 'default'}>{order ? '已覆盖' : '走默认'}</Tag>
        </Space>
      }>
        <Input.TextArea rows={4} value={order}
          placeholder={DEFAULT_ORDER}
          onChange={(e) => patchOrder(e.target.value)} />
      </Card>

      <Card size="small" title={
        <Space>
          <FileTextOutlined />
          <span>§7.2 集成注意事项（六原则）</span>
        </Space>
      }>
        <Collapse size="small" items={principles.map((p, idx) => ({
          key: p.key,
          label: (
            <Space>
              <span>{`7.2.${idx + 1} ${p.title}`}</span>
              <Tag color={p.description ? 'green' : 'default'}>
                {p.description ? '已覆盖' : '走默认'}
              </Tag>
            </Space>
          ),
          children: (
            <Input.TextArea rows={3} value={p.description}
              placeholder={DEFAULT_DESC[p.key] ?? ''}
              onChange={(e) => patchPrinciple(idx, e.target.value)} />
          ),
        }))} />
      </Card>
    </Space>
  )
}
