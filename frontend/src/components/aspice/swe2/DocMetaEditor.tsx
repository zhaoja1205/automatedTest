/**
 * SWE.2 文档元信息编辑器（封面版本号 / 公司名 / 修订人）。
 *
 * 落盘位置：aspice.swe2.doc_meta
 * 后端 arch_generator._build_swe2_context 优先读这里，留空则回落 project.meta。
 * 即 "SWE.2 文档层面的版本号"独立于"项目层面的 doc_version"，避免改 project.json 结构。
 */
import { Form, Input, Space, Tag } from 'antd'
import type { Swe2DocMeta } from '../../../types/aspice'

interface Props {
  value: Swe2DocMeta
  onChange: (next: Swe2DocMeta) => void
}

export default function DocMetaEditor({ value, onChange }: Props) {
  const patch = (p: Partial<Swe2DocMeta>) => onChange({ ...value, ...p })

  const filledCount =
    (value.version?.trim() ? 1 : 0)
    + (value.company?.trim() ? 1 : 0)
    + (value.modifier?.trim() ? 1 : 0)

  return (
    <Space direction="vertical" size={8} style={{ width: '100%' }}>
      <Space>
        <Tag color={filledCount ? 'green' : 'default'}>
          {filledCount ? `已覆盖 ${filledCount}/3` : '全走默认（project.meta）'}
        </Tag>
        <span style={{ color: '#888', fontSize: 12 }}>
          留空即用项目创建向导里的 doc_version / company / modifier。
        </span>
      </Space>
      <Form layout="vertical" size="small" style={{ maxWidth: 640 }}>
        <Form.Item label="文档版本号" help="封面「版本号：XXX」以及历史记录首行版本都用这个值。例如 V1.0 / V2.3。">
          <Input
            placeholder="V1.0"
            value={value.version || ''}
            onChange={(e) => patch({ version: e.target.value })}
            allowClear
          />
        </Form.Item>
        <Form.Item label="文档归属公司" help="封面落款。留空则用项目元信息里的公司名。">
          <Input
            placeholder="中科创达软件股份有限公司"
            value={value.company || ''}
            onChange={(e) => patch({ company: e.target.value })}
            allowClear
          />
        </Form.Item>
        <Form.Item label="修订人" help="历史记录首行的「修订人」字段兜底。">
          <Input
            placeholder=""
            value={value.modifier || ''}
            onChange={(e) => patch({ modifier: e.target.value })}
            allowClear
          />
        </Form.Item>
      </Form>
    </Space>
  )
}
