/**
 * SWE.3 推送 D — 单个关注函数的详情编辑器。
 *
 * 展示：函数声明（只读）、介绍（TextArea）、参数/返回值表、PlantUML TextArea。
 * "AI 生成" 按钮调后端 /swe3/ai/augment-one（需要 componentId）。
 */
import { useState } from 'react'
import { Card, Space, Tag, Input, Table, Button, message } from 'antd'
import { ThunderboltOutlined } from '@ant-design/icons'
import type { Swe3ScannedFunction } from '../../../types/aspice'
import { useAspiceStore } from '../../../stores/useAspiceStore'
import { augmentOneFunction } from '../../../api/aspiceApi'

interface Props {
  fn: Swe3ScannedFunction
  componentId: string
  onChange: (fn: Swe3ScannedFunction) => void
  designId?: string
}

export default function FunctionDetailEditor({ fn, componentId, onChange, designId }: Props) {
  const { projectId } = useAspiceStore()
  const [generating, setGenerating] = useState(false)

  const handleAiGen = async () => {
    if (!projectId) { message.warning('项目未创建'); return }
    setGenerating(true)
    try {
      const res = await augmentOneFunction(projectId, componentId, fn.key)
      onChange({
        ...fn,
        ai_intro: res.data.ai_intro,
        ai_flowchart: res.data.ai_flowchart,
        extracted_by: res.data.extracted_by as any,
      })
      message.success('已生成介绍与流程图')
    } catch (e: any) {
      message.error(e?.response?.data?.detail || 'AI 生成失败')
    } finally {
      setGenerating(false)
    }
  }

  const sourceTag = (() => {
    const map: Record<string, { color: string; text: string }> = {
      regex: { color: 'default', text: 'regex' },
      clang: { color: 'blue', text: 'clang' },
      ai: { color: 'purple', text: 'ai' },
      manual: { color: 'cyan', text: 'manual' },
    }
    const parts = String(fn.extracted_by).split('+')
    return parts.map((p) => {
      const m = map[p] || { color: 'default', text: p }
      return <Tag key={p} color={m.color}>{m.text}</Tag>
    })
  })()

  return (
    <Card size="small"
      title={
        <Space>
          <span style={{ fontFamily: 'monospace' }}>{fn.name}</span>
          {designId && <Tag color="geekblue">{designId}</Tag>}
          {fn.is_sdk && <Tag color="orange">SDK</Tag>}
          <Space size={2}>来源：{sourceTag}</Space>
        </Space>
      }
    >
      <div style={{ marginBottom: 8 }}>
        <div style={{ fontWeight: 500, marginBottom: 2 }}>函数声明（只读）</div>
        <div style={{ background: '#fafafa', padding: 8, fontFamily: 'monospace', fontSize: 12 }}>
          {fn.declaration || '<无>'}
        </div>
      </div>

      <div style={{ marginBottom: 8 }}>
        <div style={{ fontWeight: 500, marginBottom: 2 }}>函数介绍</div>
        <Input.TextArea rows={3}
          value={fn.ai_intro}
          onChange={(e) => onChange({ ...fn, ai_intro: e.target.value })}
          placeholder="可点下方 AI 生成，或直接编辑"
        />
      </div>

      <div style={{ marginBottom: 8 }}>
        <div style={{ fontWeight: 500, marginBottom: 2 }}>参数（{fn.parameters.length}）</div>
        <Table size="small" pagination={false}
          dataSource={fn.parameters}
          rowKey={(_, i) => String(i)}
          columns={[
            { title: '名称', dataIndex: 'name', width: 140 },
            { title: '类型', dataIndex: 'type', width: 180 },
            { title: '说明', dataIndex: 'desc' },
          ]}
        />
      </div>

      <div style={{ marginBottom: 8 }}>
        <div style={{ fontWeight: 500, marginBottom: 2 }}>返回值（{fn.returns.length}）</div>
        <Table size="small" pagination={false}
          dataSource={fn.returns}
          rowKey={(_, i) => String(i)}
          columns={[
            { title: '类型', dataIndex: 'type', width: 180 },
            { title: '说明', dataIndex: 'desc' },
          ]}
        />
      </div>

      <div style={{ marginBottom: 8 }}>
        <Space style={{ marginBottom: 4 }}>
          <span style={{ fontWeight: 500 }}>函数流程图（PlantUML 源码）</span>
          <Button size="small" type="primary" icon={<ThunderboltOutlined />}
            loading={generating} onClick={handleAiGen}>
            AI 生成介绍 + 流程图
          </Button>
          <Button size="small" onClick={() => onChange({ ...fn, ai_flowchart: '' })}>清空</Button>
        </Space>
        <Input.TextArea rows={8}
          style={{ fontFamily: 'monospace', fontSize: 12 }}
          value={fn.ai_flowchart}
          onChange={(e) => onChange({ ...fn, ai_flowchart: e.target.value })}
          placeholder="@startuml ... @enduml（留空则导出占位）"
        />
        <div style={{ color: '#999', fontSize: 12, marginTop: 4 }}>
          💡 推送 D 阶段只保存源码；可拷到 www.plantuml.com 预览后手动插图。
        </div>
      </div>
    </Card>
  )
}
