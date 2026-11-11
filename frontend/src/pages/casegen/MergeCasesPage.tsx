/**
 * 合并测试用例。
 *
 * 选择「主用例」与「来源用例」两个 case.xlsx 格式的表格，
 * 从来源表中勾选用例后追加到主用例对应的 Sheet，下载合并结果。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Empty,
  Input,
  Row,
  Segmented,
  Space,
  Table,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { UploadProps } from 'antd'
import {
  CheckOutlined,
  DownloadOutlined,
  FileExcelOutlined,
  InboxOutlined,
  MergeCellsOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { isAxiosError } from 'axios'

import { executeMerge, previewMerge } from '../../api/mergeApi'
import type {
  MergeCaseItem,
  MergeExecuteResponse,
  MergePreviewResponse,
} from '../../types/merge'

const { Title, Paragraph, Text } = Typography

function errorMessage(error: unknown, fallback: string): string {
  if (isAxiosError<{ detail?: string }>(error))
    return error.response?.data?.detail || error.message || fallback
  if (error instanceof Error) return error.message
  return fallback
}

export default function MergeCasesPage() {
  const [mainFile, setMainFile] = useState<File | null>(null)
  const [sourceFile, setSourceFile] = useState<File | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [preview, setPreview] = useState<MergePreviewResponse | null>(null)
  const [selectedKeys, setSelectedKeys] = useState<string[]>([])

  const [activeSheet, setActiveSheet] = useState<string>('all')
  const [keyword, setKeyword] = useState('')

  const [includeResults, setIncludeResults] = useState(false)
  const [skipDuplicates, setSkipDuplicates] = useState(true)
  const [outputFilename, setOutputFilename] = useState('')

  const [merging, setMerging] = useState(false)
  const [result, setResult] = useState<MergeExecuteResponse | null>(null)

  // 两个文件都就绪后自动解析来源用例
  useEffect(() => {
    if (!mainFile || !sourceFile) {
      setPreview(null)
      setSelectedKeys([])
      return
    }
    let cancelled = false
    setPreviewing(true)
    setResult(null)
    setSelectedKeys([])
    setActiveSheet('all')
    previewMerge(mainFile, sourceFile)
      .then((res) => {
        if (cancelled) return
        setPreview(res.data)
        message.success(`已解析来源用例 ${res.data.cases.length} 条`)
      })
      .catch((error) => {
        if (cancelled) return
        setPreview(null)
        message.error(errorMessage(error, '用例文件解析失败'))
      })
      .finally(() => {
        if (!cancelled) setPreviewing(false)
      })
    return () => {
      cancelled = true
    }
  }, [mainFile, sourceFile])

  const allCases = preview?.cases ?? []

  const filteredCases = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    return allCases.filter((item) => {
      if (activeSheet !== 'all' && item.source_sheet !== activeSheet) return false
      if (!kw) return true
      return [
        item.case_id,
        item.description,
        item.test_type,
        item.prerequisites,
        item.test_steps,
        item.expected_result,
        item.priority,
      ]
        .join(' ')
        .toLowerCase()
        .includes(kw)
    })
  }, [allCases, activeSheet, keyword])

  const sheetOptions = useMemo(
    () => [
      { label: `全部 (${allCases.length})`, value: 'all' },
      ...(preview?.source_sheets ?? [])
        .filter((sheet) => sheet.case_count > 0)
        .map((sheet) => ({
          label: `${sheet.name} (${sheet.case_count})`,
          value: sheet.name,
        })),
    ],
    [allCases.length, preview],
  )

  const selectVisible = useCallback(() => {
    setSelectedKeys((prev) => {
      const merged = new Set(prev)
      filteredCases.forEach((item) => merged.add(item.case_key))
      return Array.from(merged)
    })
  }, [filteredCases])

  const clearSelection = useCallback(() => setSelectedKeys([]), [])

  const handleMainUpload: UploadProps['beforeUpload'] = (file) => {
    setMainFile(file as File)
    return false
  }

  const handleSourceUpload: UploadProps['beforeUpload'] = (file) => {
    setSourceFile(file as File)
    return false
  }

  const handleMerge = useCallback(async () => {
    if (!preview) return
    if (selectedKeys.length === 0) {
      message.warning('请先勾选要加入主用例的来源用例')
      return
    }
    setMerging(true)
    setResult(null)
    try {
      const res = await executeMerge({
        token: preview.token,
        case_keys: selectedKeys,
        include_results: includeResults,
        skip_duplicates: skipDuplicates,
        output_filename: outputFilename.trim()
          ? `${outputFilename.trim().replace(/\.xlsx$/i, '')}.xlsx`
          : '',
      })
      setResult(res.data)
      message.success(res.data.message)
    } catch (error) {
      message.error(errorMessage(error, '合并失败'))
    } finally {
      setMerging(false)
    }
  }, [preview, selectedKeys, includeResults, skipDuplicates, outputFilename])

  const handleDownload = useCallback(() => {
    if (!result) return
    window.open(result.download_url, '_blank')
  }, [result])

  const columns: ColumnsType<MergeCaseItem> = [
    {
      title: '来源 Sheet',
      dataIndex: 'source_sheet',
      width: 120,
      render: (value: string, record) => (
        <Space direction="vertical" size={0}>
          <Tag color="blue">{value}</Tag>
          <Text type="secondary" style={{ fontSize: 11 }}>
            第 {record.row_number} 行
          </Text>
        </Space>
      ),
    },
    {
      title: '用例ID',
      dataIndex: 'case_id',
      width: 140,
      ellipsis: true,
    },
    {
      title: '测试类型',
      dataIndex: 'test_type',
      width: 110,
      ellipsis: true,
    },
    {
      title: '用例描述',
      dataIndex: 'description',
      width: 200,
      ellipsis: true,
    },
    {
      title: '前置条件',
      dataIndex: 'prerequisites',
      width: 180,
      ellipsis: true,
    },
    {
      title: '测试步骤',
      dataIndex: 'test_steps',
      width: 260,
      ellipsis: true,
    },
    {
      title: '预期结果',
      dataIndex: 'expected_result',
      width: 220,
      ellipsis: true,
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      width: 80,
    },
    {
      title: '合并到',
      dataIndex: 'target_sheet',
      width: 120,
      render: (value: string, record) => (
        <Tag color={record.target_sheet === record.source_sheet ? 'green' : 'orange'}>
          {value}
        </Tag>
      ),
    },
  ]

  return (
    <div>
      <Card bordered={false} style={{ marginBottom: 16 }}>
        <Title level={4} style={{ marginTop: 0, marginBottom: 4 }}>
          <MergeCellsOutlined /> 合并测试用例
        </Title>
        <Paragraph type="secondary" style={{ marginBottom: 0 }}>
          选择两个 case.xlsx 格式的用例表：内容会从「来源用例」中挑选并追加到「主用例」，
          主用例的封面、数据统计与 BugList 页保持不变。
        </Paragraph>
      </Card>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={24} md={12}>
          <Card title="① 主用例（合并目标）" size="small" bordered={false}>
            <Upload.Dragger
              accept=".xlsx,.xlsm"
              maxCount={1}
              showUploadList={false}
              beforeUpload={handleMainUpload}
            >
              <p className="ant-upload-drag-icon">
                <InboxOutlined />
              </p>
              <p className="ant-upload-text">点击或拖拽主用例 Excel 到此区域</p>
              <p className="ant-upload-hint">合并结果会以该文件的模板为准</p>
            </Upload.Dragger>
            <div style={{ marginTop: 8 }}>
              {mainFile ? (
                <Text>
                  <FileExcelOutlined /> {mainFile.name}
                </Text>
              ) : (
                <Text type="secondary">尚未选择主用例文件</Text>
              )}
            </div>
            {preview && (
              <div style={{ marginTop: 8 }}>
                <Text type="secondary">主用例现有 Sheet：</Text>
                <div style={{ marginTop: 4 }}>
                  <Space size={[4, 4]} wrap>
                    {preview.main_sheets.map((sheet) => (
                      <Tag key={sheet.name}>
                        {sheet.name}
                        <Text type="secondary" style={{ marginLeft: 4 }}>
                          {sheet.case_count} 条
                        </Text>
                      </Tag>
                    ))}
                  </Space>
                </div>
              </div>
            )}
          </Card>
        </Col>
        <Col xs={24} md={12}>
          <Card title="② 来源用例（挑选内容）" size="small" bordered={false}>
            <Upload.Dragger
              accept=".xlsx,.xlsm"
              maxCount={1}
              showUploadList={false}
              beforeUpload={handleSourceUpload}
            >
              <p className="ant-upload-drag-icon">
                <InboxOutlined />
              </p>
              <p className="ant-upload-text">点击或拖拽来源用例 Excel 到此区域</p>
              <p className="ant-upload-hint">只复制勾选的用例，可保留或忽略执行结果</p>
            </Upload.Dragger>
            <div style={{ marginTop: 8 }}>
              {sourceFile ? (
                <Text>
                  <FileExcelOutlined /> {sourceFile.name}
                </Text>
              ) : (
                <Text type="secondary">尚未选择来源用例文件</Text>
              )}
            </div>
            {preview && (
              <div style={{ marginTop: 8 }}>
                <Text type="secondary">来源 Sheet 与目标 Sheet：</Text>
                <div style={{ marginTop: 4 }}>
                  <Space size={[4, 4]} wrap>
                    {preview.source_sheets
                      .filter((sheet) => sheet.case_count > 0)
                      .map((sheet) => (
                        <Tag key={sheet.name} color="blue">
                          {sheet.name} → {sheet.target_sheet || '新建同名 Sheet'}
                          <Text type="secondary" style={{ marginLeft: 4 }}>
                            {sheet.case_count} 条
                          </Text>
                        </Tag>
                      ))}
                  </Space>
                </div>
              </div>
            )}
          </Card>
        </Col>
      </Row>

      {previewing && (
        <Card bordered={false}>
          <Space>
            <ReloadOutlined spin />
            <Text>正在解析用例文件…</Text>
          </Space>
        </Card>
      )}

      {preview && !previewing && (
        <Card
          bordered={false}
          title={
            <Space>
              <span>③ 选择要加入主用例的用例</span>
              <Tag color="green">已选 {selectedKeys.length} 条</Tag>
            </Space>
          }
          extra={
            <Space>
              <Button icon={<CheckOutlined />} onClick={selectVisible}>
                全选当前筛选
              </Button>
              <Button onClick={clearSelection} disabled={selectedKeys.length === 0}>
                清空选择
              </Button>
            </Space>
          }
        >
          <Space wrap style={{ marginBottom: 12 }}>
            <Segmented
              options={sheetOptions}
              value={activeSheet}
              onChange={(value) => setActiveSheet(String(value))}
            />
            <Input.Search
              allowClear
              placeholder="搜索用例ID / 描述 / 步骤 / 预期结果"
              style={{ width: 320 }}
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
            />
          </Space>

          <Table<MergeCaseItem>
            rowKey="case_key"
            size="small"
            bordered
            loading={previewing}
            columns={columns}
            dataSource={filteredCases}
            scroll={{ x: 1500 }}
            pagination={{ defaultPageSize: 20, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
            rowSelection={{
              selectedRowKeys: selectedKeys,
              preserveSelectedRowKeys: true,
              onChange: (keys) => setSelectedKeys(keys as string[]),
            }}
            locale={{
              emptyText: (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="没有匹配的用例"
                />
              ),
            }}
          />

          <Space wrap style={{ marginTop: 16 }}>
            <Checkbox
              checked={includeResults}
              onChange={(e) => setIncludeResults(e.target.checked)}
            >
              同时复制来源用例的执行结果（实际结果 / BUG / 备注等）
            </Checkbox>
            <Checkbox
              checked={skipDuplicates}
              onChange={(e) => setSkipDuplicates(e.target.checked)}
            >
              跳过主用例中已存在的相同用例ID
            </Checkbox>
            <Input
              placeholder="输出文件名（可留空自动生成）"
              style={{ width: 260 }}
              value={outputFilename}
              onChange={(e) => setOutputFilename(e.target.value)}
            />
            <Button
              type="primary"
              icon={<MergeCellsOutlined />}
              loading={merging}
              disabled={selectedKeys.length === 0}
              onClick={handleMerge}
            >
              合并所选用例（{selectedKeys.length} 条）
            </Button>
          </Space>
        </Card>
      )}

      {result && (
        <Card bordered={false} style={{ marginTop: 16 }}>
          <Alert
            type="success"
            showIcon
            message={result.message}
            description={
              <div>
                <div>
                  <Text type="secondary">各 Sheet 追加数量：</Text>
                  <Space size={[4, 4]} wrap style={{ marginLeft: 8 }}>
                    {Object.entries(result.sheet_counts).map(([sheet, count]) => (
                      <Tag key={sheet} color="blue">
                        {sheet} +{count}
                      </Tag>
                    ))}
                  </Space>
                </div>
                {result.skipped_duplicates.length > 0 && (
                  <div style={{ marginTop: 4 }}>
                    <Text type="warning">
                      跳过重复用例 {result.skipped_duplicates.length} 条：{result.skipped_duplicates.join('、')}
                    </Text>
                  </div>
                )}
                {result.warnings.map((warning) => (
                  <div key={warning} style={{ marginTop: 4 }}>
                    <Text type="warning">{warning}</Text>
                  </div>
                ))}
              </div>
            }
          />
          <Space style={{ marginTop: 12 }}>
            <Button
              type="primary"
              icon={<DownloadOutlined />}
              onClick={handleDownload}
            >
              下载合并文件
            </Button>
            <Text type="secondary">
              文件名：{result.filename}
            </Text>
          </Space>
        </Card>
      )}
    </div>
  )
}
