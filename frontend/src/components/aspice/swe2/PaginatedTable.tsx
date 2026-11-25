/**
 * 可搜索分页表格外壳（SWE.2 §4 / §3 接口表共用）。
 *
 * 作用：单模块接口 / 场景 / 类列表很多（几十上百行）时，编辑面板纵向不被拉长。
 *
 * 特性：
 * - Table 固定高度 scroll.y=360 + sticky 表头 → 列标题常驻顶部
 * - 顶部搜索框按调用方传入的 searchFields 实时过滤（toLowerCase + includes）
 * - 底部 antd 分页器（默认每页 10 行，可切 20 / 50 / 100）
 * - "添加" 按钮会自动清搜索词 + 跳到最后一页看新行
 *
 * 过滤安全：Table 行号在过滤后会变，但调用方 columns 的 render 回调通常按原始
 * 行 index 写回 state 数组。这里给每行 wrap 成 `{ ...r, __idx: originalIdx }`，
 * 并把 columns 的 render 包一层，把 record.__idx 当成真正的 idx 透回去，所以
 * 过滤 + 编辑不会错位。
 *
 * 不处理：虚拟滚动（上千行建议升级 antd Table 的 `virtual`，但本场景几十到
 * 几百行分页已够用）。
 */
import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Button, Card, Input, Space, Table, Tag } from 'antd'
import { PlusOutlined, SearchOutlined } from '@ant-design/icons'

export interface PaginatedTableProps<T extends object> {
  /** Card 标题，Tag 里会自动加上条数。 */
  title: string
  /** 原始数据数组（未过滤、未分页）。 */
  rows: T[]
  /** 已经绑定好当前 list/setList 的 columns。render 里用的 idx 应当是原始数组 idx。 */
  columns: any[]
  /** 新增一行。壳会在之后自动清搜索词 + 跳最后一页。 */
  onAdd: () => void
  /** rowKey 前缀，避免同页多张表 key 冲突。 */
  rowKeyPrefix: string
  /** 搜索字段白名单。toLowerCase + includes 逐字段匹配，命中任一字段即保留。 */
  searchFields: (keyof T)[]
  /** 右上角按钮槽（例如 "导入扫描" 按钮）。 */
  extraActions?: ReactNode
  /** 搜索框 placeholder；默认 "搜 method/source/说明"。 */
  searchPlaceholder?: string
  /** 空数据文案；默认 "暂无条目，点添加或上方导入扫描结果"。 */
  emptyText?: string
  /** 表内滚动高度，默认 360。 */
  tableHeight?: number
}

export default function PaginatedTable<T extends object>({
  title, rows, columns, onAdd, rowKeyPrefix, searchFields, extraActions,
  searchPlaceholder = '搜 method/source/说明',
  emptyText = '暂无条目，点"添加"或上方「导入扫描结果」',
  tableHeight = 360,
}: PaginatedTableProps<T>) {
  const [kw, setKw] = useState('')
  const [pageSize, setPageSize] = useState(10)
  const [page, setPage] = useState(1)

  // 过滤：原始 index 跟着一起带，保证 columns 里的 onChange 回调仍按真实位置写回原数组
  const indexed = useMemo(
    () => rows.map((r, originalIdx) => ({ r, originalIdx })),
    [rows],
  )
  const filtered = useMemo(() => {
    const q = kw.trim().toLowerCase()
    if (!q) return indexed
    return indexed.filter(({ r }) =>
      searchFields.some((f) => String((r as Record<string, unknown>)[f as string] ?? '')
        .toLowerCase().includes(q)),
    )
  }, [indexed, kw, searchFields])

  // 把原始 index 塞进 record，供包装后的 columns.render 读取
  const dataWithIdx = useMemo(
    () => filtered.map(({ r, originalIdx }) => ({ ...r, __idx: originalIdx })),
    [filtered],
  )

  // 把 columns 的 render 包一层：优先把 record.__idx 透给原 render 的 idx 参数
  const wrappedColumns = useMemo(() => columns.map((col) => {
    if (!col.render) return col
    const orig = col.render
    return {
      ...col,
      render: (v: unknown, record: Record<string, unknown>, _antdIdx: number) =>
        orig(v, record, record.__idx as number),
    }
  }), [columns])

  const total = filtered.length
  // 过滤 / 切 pageSize 后页码可能越界，自动回到第 1 页
  const safePage = (page - 1) * pageSize >= total ? 1 : page

  return (
    <Card size="small" title={
      <Space size="small">
        <span>{title}</span>
        <Tag>{rows.length}</Tag>
        {kw && <Tag color="blue">过滤 {filtered.length}/{rows.length}</Tag>}
      </Space>
    }
      extra={
        <Space size="small">
          <Input size="small" prefix={<SearchOutlined />} allowClear
            placeholder={searchPlaceholder} style={{ width: 200 }}
            value={kw} onChange={(e) => { setKw(e.target.value); setPage(1) }} />
          {extraActions}
          <Button size="small" icon={<PlusOutlined />}
            onClick={() => {
              onAdd()
              setKw('')
              setPage(Math.max(1, Math.ceil((rows.length + 1) / pageSize)))
            }}>添加</Button>
        </Space>
      }>
      <Table
        rowKey={(record) => `${rowKeyPrefix}-${(record as { __idx: number }).__idx}`}
        size="small"
        dataSource={dataWithIdx}
        columns={wrappedColumns}
        scroll={{ y: tableHeight }}
        sticky
        pagination={{
          current: safePage,
          pageSize,
          total,
          size: 'small',
          showSizeChanger: true,
          pageSizeOptions: [10, 20, 50, 100],
          showTotal: (t, range) => `${range[0]}-${range[1]} / ${t}`,
          onChange: (p, ps) => { setPage(p); setPageSize(ps) },
        }}
        locale={{ emptyText: kw ? `无匹配「${kw}」的行` : emptyText }}
      />
    </Card>
  )
}
