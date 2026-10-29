/**
 * 生成测试用例 — 向导页面。
 *
 * 流程：基本信息 → 平台配置 → Sensors 配置 → 功能测试配置 → 生成与预览 → 导出。
 * 支持自动保存和手动保存草稿。
 */
import { useState, useEffect, useCallback } from 'react'
import { Button, Card, Divider, Form, Space, Steps, Typography, message, Drawer } from 'antd'
import BasicInfoStep from '../../components/casegen/BasicInfoStep'
import FunctionalGenStep from '../../components/casegen/FunctionalGenStep'
import PlatformStep from '../../components/casegen/PlatformStep'
import SensorStep from '../../components/casegen/SensorStep'
import CasePreviewStep from '../../components/casegen/CasePreviewStep'
import DraftBox from '../../components/casegen/DraftBox'
import type {
  CaseGenBasicInfo,
  PlatformConfigParseResult,
  FunctionalTestOptions,
  FunctionalTestSelection,
  PlatformConfig,
  SensorConfigParseResult,
} from '../../types/casegen'
import {
  DEFAULT_FUNCTIONAL_TEST_OPTIONS,
  DEFAULT_FUNCTIONAL_TEST_SELECTION,
} from '../../types/casegen'
import { generateFunctionalCases } from '../../utils/casegen/functionalCases'
import { groupSensorsByFile } from '../../utils/casegen/sensors'
import { exportCases, downloadExportedFile } from '../../api/casegenApi'
import { autosaveCurrentState, loadAutoSave, clearAutoSave, saveGeneratedCases, clearGeneratedCases, type AutoSaveData } from '../../utils/casegen/storage'

const { Title, Paragraph } = Typography

const STEPS = [
  { title: '基本信息', description: '项目与版本信息' },
  { title: '平台配置', description: '选择硬件拓扑' },
  { title: 'Sensors 配置', description: '可选：读取 sensor 数据库' },
  { title: '功能测试', description: 'raw图 / YUV 图' },
  { title: '生成与预览', description: '查看生成的用例' },
  { title: '导出', description: '下载 Excel' },
]

/** 各步骤在 STEPS 中的下标，避免魔法数字 */
const STEP_INDEX = {
  basic: 0,
  platform: 1,
  sensors: 2,
  functional: 3,
  preview: 4,
  export: 5,
} as const

export default function CaseGenPage() {
  const [form] = Form.useForm<CaseGenBasicInfo>()
  const [current, setCurrent] = useState(0)
  const [platformData, setPlatformData] = useState<PlatformConfigParseResult | null>(null)
  const [selectedPlatform, setSelectedPlatform] = useState('')
  const [platformPath, setPlatformPath] = useState('')
  const [sensorData, setSensorData] = useState<SensorConfigParseResult | null>(null)
  const [sensorPaths, setSensorPaths] = useState<string[]>([])
  const [functionalOptions, setFunctionalOptions] = useState<FunctionalTestOptions>({
    ...DEFAULT_FUNCTIONAL_TEST_OPTIONS,
  })
  const [testSelection, setTestSelection] = useState<FunctionalTestSelection>({
    ...DEFAULT_FUNCTIONAL_TEST_SELECTION,
  })
  const [generatedCases, setGeneratedCases] = useState<ReturnType<typeof generateFunctionalCases>>([])
  const [exporting, setExporting] = useState(false)
  const [exportedFilename, setExportedFilename] = useState<string>('')
  const [showDraftBox, setShowDraftBox] = useState(false)

  /** 构建当前状态的快照，用于自动保存和草稿 */
  const buildStateSnapshot = useCallback((): AutoSaveData => {
    const basicInfo = form.getFieldsValue()
    const snapshot: AutoSaveData = {
      current,
      basicInfo: Object.fromEntries(
        Object.entries(basicInfo).map(([k, v]) => [k, String(v ?? '')])
      ),
      platformPath,
      fileName: platformData?.file_name || '',
      selectedPlatform,
      functionalOptions,
      testSelection,
      sensorPaths,
      sensorConfigs: sensorData?.sensors,
      generatedCasesCount: generatedCases.length,
      generatedCases: generatedCases.length > 0 ? [...generatedCases] : undefined,
      exportedFilename,
      timestamp: Date.now(),
    }
    if (platformData) {
      snapshot.platformConfigs = platformData.platform_configs
      snapshot.platformPath = platformData.path
    }
    return snapshot
  }, [current, form, platformPath, platformData, selectedPlatform, functionalOptions, testSelection, sensorData, sensorPaths, generatedCases, exportedFilename])

  /** 主动触发一次自动保存 */
  const doAutosave = useCallback(() => {
    autosaveCurrentState(buildStateSnapshot())
  }, [buildStateSnapshot])

  /** 从草稿/自动保存中恢复 sensor 配置 */
  const restoreSensors = useCallback((data: AutoSaveData) => {
    if (data.sensorConfigs && data.sensorConfigs.length > 0) {
      setSensorPaths(data.sensorPaths ?? [])
      setSensorData(groupSensorsByFile(data.sensorConfigs, data.sensorPaths ?? []))
    } else {
      setSensorPaths([])
      setSensorData(null)
    }
  }, [])

  /** 从草稿/自动保存中恢复功能测试参数（兼容旧草稿的 lightingOptions） */
  const restoreFunctionalOptions = useCallback((data: AutoSaveData) => {
    if (data.functionalOptions) {
      setFunctionalOptions({ ...DEFAULT_FUNCTIONAL_TEST_OPTIONS, ...data.functionalOptions })
    } else if (data.lightingOptions) {
      setFunctionalOptions({ ...DEFAULT_FUNCTIONAL_TEST_OPTIONS, ...data.lightingOptions })
    }
    if (data.testSelection) {
      // 旧草稿没有 roAl 字段，按未勾选处理，避免恢复后凭空多出用例
      setTestSelection({
        ...DEFAULT_FUNCTIONAL_TEST_SELECTION,
        ...data.testSelection,
        roAl: data.testSelection.roAl ?? false,
      })
    }
  }, [])

  // ── Mount: restore saved state from localStorage ──────────────────────
  useEffect(() => {
    const saved = loadAutoSave()
    if (saved) {
      setCurrent(saved.current || 0)
      form.setFieldsValue(saved.basicInfo || {})
      if (saved.selectedPlatform) {
        setSelectedPlatform(saved.selectedPlatform)
      }
      restoreFunctionalOptions(saved)
      restoreSensors(saved)
      if (saved.exportedFilename) {
        setExportedFilename(saved.exportedFilename)
      }
      // Restore platform config path so PlatformStep shows the saved path
      if (saved.platformPath) {
        setPlatformPath(saved.platformPath)
      }
      if (saved.generatedCasesCount && saved.platformConfigs) {
        const configs: PlatformConfig[] = saved.platformConfigs.map((c) => ({
          ...c,
          groups: c.groups || [],
          topology: c.topology || [],
        }))
        setPlatformData({
          path: saved.platformPath || '',
          file_name: saved.fileName || '',
          platform_configs: configs,
        })
      }
      // Restore generated cases from auto-save snapshot
      if (saved.generatedCases && saved.generatedCases.length > 0) {
        setGeneratedCases(saved.generatedCases)
      }
    }
  }, [form, restoreSensors, restoreFunctionalOptions])

  // ── Autosave at key moments ──────────────────────────────────────────
  // After restore completes (ensures restored state is re-saved with current timestamps)
  useEffect(() => {
    doAutosave()
  }, [doAutosave])

  // On every step change
  useEffect(() => {
    doAutosave()
  }, [current])

  const selectedPlatformConfig = platformData?.platform_configs.find(
    (c) => c.name === selectedPlatform,
  ) || null

  const handleNext = async () => {
    if (current === STEP_INDEX.basic) {
      try {
        await form.validateFields()
      } catch {
        return
      }
    }
    if (current === STEP_INDEX.platform && !selectedPlatform) {
      message.warning('请先读取配置文件并选择平台配置')
      return
    }
    if (current >= STEPS.length - 1) {
      return
    }
    setCurrent((v) => v + 1)
  }

  const handlePrev = () => {
    if (current > 0) setCurrent((v) => v - 1)
  }

  const handleGenerate = () => {
    if (!selectedPlatformConfig) {
      message.warning('请先选择平台配置')
      return
    }
    if (!testSelection.lighting && !testSelection.yuv && !testSelection.roAl) {
      message.warning('请至少勾选一种功能测试类型')
      return
    }
    const cases = generateFunctionalCases({
      platform: selectedPlatformConfig,
      selection: testSelection,
      options: functionalOptions,
      sensors: sensorData?.sensors,
    })
    setGeneratedCases(cases)
    saveGeneratedCases(cases)
    doAutosave()
    message.success(`已生成 ${cases.length} 条用例`)
  }

  const handleExport = async () => {
    if (generatedCases.length === 0) {
      message.warning('请先生成用例')
      return
    }
    setExporting(true)
    try {
      const basicInfo = form.getFieldsValue()
      const res = await exportCases({
        platform_name: selectedPlatform,
        basic_info: Object.fromEntries(
          Object.entries(basicInfo).map(([k, v]) => [k, String(v ?? '')])
        ),
        cases: generatedCases.map(c => Object.fromEntries(
          Object.entries(c).filter(([, v]) => v !== null && v !== undefined).map(([k, v]) => [k, String(v)])
        )),
      })
      setExportedFilename(res.data.filename)
      message.success(res.data.message)
      downloadExportedFile(res.data.download_url.split('/').pop()!)
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail || '导出失败，请稍后重试'
      message.error(detail)
    } finally {
      setExporting(false)
    }
  }

  const handleReset = () => {
    clearAutoSave()
    clearGeneratedCases()
    form.resetFields()
    setPlatformData(null)
    setSelectedPlatform('')
    setPlatformPath('')
    setSensorData(null)
    setSensorPaths([])
    setFunctionalOptions({ ...DEFAULT_FUNCTIONAL_TEST_OPTIONS })
    setTestSelection({ ...DEFAULT_FUNCTIONAL_TEST_SELECTION })
    setGeneratedCases([])
    setExportedFilename('')
    setCurrent(0)
    message.success('已清空所有数据')
  }

  // Restore a draft into the wizard
  const handleRestoreDraft = useCallback((data: AutoSaveData) => {
    setCurrent(data.current ?? 0)
    form.setFieldsValue(data.basicInfo ?? {})
    if (data.selectedPlatform) {
      setSelectedPlatform(data.selectedPlatform)
    }
    restoreFunctionalOptions(data)
    if (data.platformConfigs && data.platformConfigs.length > 0) {
      const configs: PlatformConfig[] = data.platformConfigs.map((c) => ({
        ...c,
        groups: c.groups || [],
        topology: c.topology || [],
      }))
      setPlatformData({
        path: data.platformPath || '',
        file_name: data.fileName || '',
        platform_configs: configs,
      })
      if (!configs.some((c) => c.name === data.selectedPlatform)) {
        setSelectedPlatform(configs[0]?.name || '')
      }
    }
    // Restore platform path for PlatformStep
    if (data.platformPath) {
      setPlatformPath(data.platformPath)
    }
    // Restore sensor configs
    restoreSensors(data)
    // Restore cached generated cases
    if (data.generatedCases && data.generatedCases.length > 0) {
      setGeneratedCases(data.generatedCases)
    }
    doAutosave()
    setShowDraftBox(false)
  }, [form, doAutosave, restoreSensors, restoreFunctionalOptions])

  // Prepare data for DraftBox
  const draftBoxData = buildStateSnapshot()

  return (
    <div>
      <Card style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <Title level={4} style={{ marginTop: 0, marginBottom: 8 }}>生成测试用例</Title>
            <Paragraph type="secondary" style={{ marginBottom: 0 }}>
              按向导分阶段完成用例生成：填写基本信息 → 选择平台配置 → （可选）添加 Sensor 配置 → 配置功能测试 → 预览生成的用例 → 导出 Excel。
            </Paragraph>
          </div>
          <Space>
            <Button onClick={() => setShowDraftBox(true)}>
              📋 草稿箱
            </Button>
            <Button danger onClick={handleReset}>
              清空
            </Button>
          </Space>
        </div>
      </Card>

      <Card>
        <Steps
          current={current}
          items={STEPS}
          onChange={(step) => {
            if (step < current) setCurrent(step)
          }}
        />
        <Divider />

        {/* Navigation toolbar */}
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
          <Button onClick={handlePrev} disabled={current === 0}>
            上一步
          </Button>
          <Space>
            <Button onClick={() => setShowDraftBox(true)}>
              💾 保存草稿
            </Button>
            {current === STEP_INDEX.export && (
              <Button
                type="primary"
                loading={exporting}
                disabled={generatedCases.length === 0}
                onClick={handleExport}
              >
                导出并下载 Excel
              </Button>
            )}
            <Button type="primary" onClick={() => void handleNext()}>
              {current === STEPS.length - 1 ? '完成' : '下一步'}
            </Button>
          </Space>
        </div>

        {current <= STEP_INDEX.sensors && (<>
          <BasicInfoStep form={form} visible={current === STEP_INDEX.basic} />
          <PlatformStep
            visible={current === STEP_INDEX.platform}
            data={platformData}
            selectedName={selectedPlatform}
            onData={setPlatformData}
            onSelect={setSelectedPlatform}
            onPathChange={setPlatformPath}
            defaultPath={platformPath}
          />
          <SensorStep
            visible={current === STEP_INDEX.sensors}
            data={sensorData}
            onData={setSensorData}
            onPathsChange={setSensorPaths}
            defaultPaths={sensorPaths}
          />
        </>)}
        {current >= STEP_INDEX.functional && (<>
          <FunctionalGenStep
            visible={current === STEP_INDEX.functional}
            platform={selectedPlatformConfig}
            options={functionalOptions}
            onOptionsChange={setFunctionalOptions}
            selection={testSelection}
            onSelectionChange={setTestSelection}
            onGenerate={handleGenerate}
            sensors={sensorData?.sensors}
          />
          <CasePreviewStep
            platformName={selectedPlatform}
            cases={generatedCases}
            onRegenerate={handleGenerate}
          />
        </>)}


      </Card>

      {/* 草稿箱抽屉 */}
      <Drawer
        title="草稿箱"
        placement="right"
        width={520}
        onClose={() => setShowDraftBox(false)}
        open={showDraftBox}
      >
        <DraftBox
          currentData={draftBoxData}
          onRestore={handleRestoreDraft}
          onSaveCallback={() => setShowDraftBox(false)}
        />
      </Drawer>
    </div>
  )
}
