/**
 * SWE.3 推送 D UI 版本 mock 数据。
 *
 * 本模块用于前端 UI 原型阶段，所有"扫描 / AI 补齐 / 上传"都走 setTimeout 返回假数据。
 * 后端联通时，替换 mock 函数为真实 axios 调用即可，组件代码不动。
 */
import type {
  Swe3EngineeringUpload,
  Swe3ScanIndex,
  Swe3ScannedFunction,
} from '../types/aspice'

/** 简单延时工具 */
export const delay = (ms: number) => new Promise((r) => setTimeout(r, ms))

/* ------------------- 工程信息 ------------------- */

export const MOCK_ENGINEERING_INFO: Swe3EngineeringUpload = {
  zip_name: 'nvsipl_pangu_src.zip',
  uploaded_at: '2026-10-12 10:30:00',
  include_root: 'include',
  code_roots: ['src'],
  total_files: 23,
  sdk_files: 8,
  custom_files: 15,
  file_tree_sample: [
    'include/serializer/MAX96717F.h',
    'include/serializer/MAX96717F_regs.h',
    'include/deserializer/MAX96712.h',
    'include/deserializer/MAX96712_regs.h',
    'include/eeprom/EEPROM.h',
    'include/camera_module/IMX728.h',
    'include/nvsipl_camera/NvSIPLCamera.h',
    'include/multicast/Multicast.h',
    'include/campwr/CamPwr.h',
    'src/serializer/MAX96717F.cpp',
    'src/deserializer/MAX96712.cpp',
    'src/eeprom/EEPROM.cpp',
    'src/camera_module/IMX728.cpp',
    'src/nvsipl_camera/NvSIPLCamera.cpp',
  ],
}

/* ------------------- 扫描结果：A001 Serializer ------------------- */

function fn(
  file: string,
  cls: string,
  name: string,
  decl: string,
  sdk = false,
): Swe3ScannedFunction {
  // 简单的 fake sha1
  const sha1 = Math.abs(
    [...name].reduce((a, c) => a * 31 + c.charCodeAt(0), 7),
  ).toString(16).padStart(8, '0').slice(0, 8)
  return {
    key: `${file}::${cls}::${name}::${sha1}`,
    name,
    declaration: decl,
    parameters: [],
    returns: [{ name: 'ret', type: 'SIPLStatus', desc: '函数返回状态' }],
    doc_comment: `/** @brief ${name} */`,
    body_lines: 20 + Math.floor(Math.random() * 40),
    extracted_by: 'regex',
    is_sdk: sdk,
    ai_intro: '',
    ai_flowchart: '',
  }
}

export const MOCK_SCAN_A001: Swe3ScanIndex = {
  component_id: 'A001',
  scanned_at: '2026-10-12 10:32:15',
  scanner_version: 'regex-1.0',
  files: [
    {
      path: 'include/serializer/MAX96717F.h',
      sha1: 'a1b2c3d4',
      is_sdk: false,
      classes: [
        {
          name: 'MAX96717FDeviceDriver',
          base: 'DeviceDriverBase',
          doc_comment: '/** @brief MAX96717F GMSL2 Serializer driver */',
          constants: [
            { seq: '1', name: 'MAX96717F_I2C_ADDR', type: 'uint8_t', value: '0x40', desc: '默认 I2C 地址' },
          ],
          variables: [
            { seq: '1', name: 'm_devParams', type: 'DeviceParams', desc: '设备参数' },
          ],
          functions: [
            fn('include/serializer/MAX96717F.h', 'MAX96717FDeviceDriver',
              'DriverCreate', 'SIPLStatus DriverCreate(DeviceParams &params);'),
            fn('include/serializer/MAX96717F.h', 'MAX96717FDeviceDriver',
              'InitializeDevice', 'SIPLStatus InitializeDevice();'),
            fn('include/serializer/MAX96717F.h', 'MAX96717FDeviceDriver',
              'StartStreaming', 'SIPLStatus StartStreaming();'),
            fn('include/serializer/MAX96717F.h', 'MAX96717FDeviceDriver',
              'StopStreaming', 'SIPLStatus StopStreaming();'),
            fn('include/serializer/MAX96717F.h', 'MAX96717FDeviceDriver',
              'DetectError', 'SIPLStatus DetectError();'),
          ],
        },
      ],
    },
    {
      path: 'src/serializer/MAX96717F.cpp',
      sha1: 'e5f6a7b8',
      is_sdk: false,
      classes: [
        {
          name: 'MAX96717FDeviceDriver',
          base: '',
          doc_comment: '',
          constants: [],
          variables: [],
          functions: [
            // 跨文件同名 — 用于演示联动勾选
            fn('src/serializer/MAX96717F.cpp', 'MAX96717FDeviceDriver',
              'DriverCreate', 'SIPLStatus MAX96717FDeviceDriver::DriverCreate(DeviceParams &params) { ... }'),
            fn('src/serializer/MAX96717F.cpp', 'MAX96717FDeviceDriver',
              'InitializeDevice', 'SIPLStatus MAX96717FDeviceDriver::InitializeDevice() { ... }'),
            fn('src/serializer/MAX96717F.cpp', 'MAX96717FDeviceDriver',
              'StartStreaming', 'SIPLStatus MAX96717FDeviceDriver::StartStreaming() { ... }'),
          ],
        },
        {
          name: '__free__',
          base: '',
          doc_comment: '',
          constants: [],
          variables: [],
          functions: [
            fn('src/serializer/MAX96717F.cpp', '__free__',
              'i2c_write_wrapper', 'static SIPLStatus i2c_write_wrapper(uint8_t reg, uint8_t val);'),
            fn('src/serializer/MAX96717F.cpp', '__free__',
              'i2c_read_wrapper', 'static SIPLStatus i2c_read_wrapper(uint8_t reg, uint8_t *val);'),
          ],
        },
      ],
    },
  ],
  stats: {
    total_files: 2,
    total_classes: 2,
    total_functions: 10,
    sdk_functions: 0,
    custom_functions: 10,
  },
}

/* ------------------- 扫描结果：A002 Deserializer ------------------- */

export const MOCK_SCAN_A002: Swe3ScanIndex = {
  component_id: 'A002',
  scanned_at: '2026-10-12 10:33:50',
  scanner_version: 'regex-1.0',
  files: [
    {
      path: 'include/deserializer/MAX96712.h',
      sha1: 'f1a2b3c4',
      is_sdk: false,
      classes: [
        {
          name: 'MAX96712DeviceDriver',
          base: 'DeviceDriverBase',
          doc_comment: '/** @brief MAX96712 GMSL2 Deserializer */',
          constants: [],
          variables: [],
          functions: [
            fn('include/deserializer/MAX96712.h', 'MAX96712DeviceDriver',
              'DriverCreate', 'SIPLStatus DriverCreate(DeviceParams &params);'),
            fn('include/deserializer/MAX96712.h', 'MAX96712DeviceDriver',
              'InitializeDevice', 'SIPLStatus InitializeDevice();'),
            fn('include/deserializer/MAX96712.h', 'MAX96712DeviceDriver',
              'LinkControl', 'SIPLStatus LinkControl(uint32_t linkMask);'),
            // SDK 函数（标 is_sdk=true，用于演示"原始 NV 函数"分区）
            {
              ...fn('include/deserializer/MAX96712.h', 'MAX96712DeviceDriver',
                'NvSetFrameSyncMode', 'SIPLStatus NvSetFrameSyncMode(FrameSyncMode mode);', true),
            },
            {
              ...fn('include/deserializer/MAX96712.h', 'MAX96712DeviceDriver',
                'NvGetDeviceStatus', 'SIPLStatus NvGetDeviceStatus(DeviceStatus &st);', true),
            },
          ],
        },
      ],
    },
  ],
  stats: {
    total_files: 1,
    total_classes: 1,
    total_functions: 5,
    sdk_functions: 2,
    custom_functions: 3,
  },
}

/* ------------------- 组件 → scan 映射 ------------------- */

const MOCK_SCAN_MAP: Record<string, Swe3ScanIndex> = {
  A001: MOCK_SCAN_A001,
  A002: MOCK_SCAN_A002,
}

/* ------------------- 推测路径规则 ------------------- */

/** 给定模块 slug，产出 2 条推测规则：裸目录名 + 带 src/ 前缀的子树路径 */
export function guessPathPatterns(slug: string): string[] {
  const low = slug.toLowerCase().replace(/\s+/g, '_')
  return [low, `src/${low}`]
}

/* ------------------- 异步 mock 函数 ------------------- */

/** 模拟上传 zip —— 直接返回工程元信息 */
export async function mockUploadEngineering(_file: File): Promise<Swe3EngineeringUpload> {
  await delay(500)
  return { ...MOCK_ENGINEERING_INFO, zip_name: _file.name || MOCK_ENGINEERING_INFO.zip_name }
}

/** 模拟按 glob 命中预览 */
export async function mockPreviewMatch(patterns: string[]): Promise<string[]> {
  await delay(250)
  const all = MOCK_ENGINEERING_INFO.file_tree_sample
  if (!patterns.length) return []
  // 简单：抽取 glob 中去 ** 的中间段作为关键字
  const keys = patterns.map((p) => p.replace(/\*\*/g, '').replace(/\*/g, '')
    .split('/').filter(Boolean))
  return all.filter((f) => keys.some((segs) => segs.every((seg) => f.includes(seg))))
}

/** 模拟扫描 */
export async function mockScanModule(componentId: string): Promise<Swe3ScanIndex> {
  await delay(1500)
  const cached = MOCK_SCAN_MAP[componentId]
  if (cached) return cached
  // 其他模块返回空扫描结果 — 让 UI 能展示"空"状态
  return {
    component_id: componentId,
    scanned_at: new Date().toISOString().slice(0, 19).replace('T', ' '),
    scanner_version: 'regex-1.0',
    files: [],
    stats: { total_files: 0, total_classes: 0, total_functions: 0, sdk_functions: 0, custom_functions: 0 },
  }
}

/** 模拟 AI 批量补齐（流式回调一个一个来） */
export async function mockAiAugment(
  funcKeys: string[],
  onProgress?: (done: number, total: number, name: string) => void,
): Promise<Array<{ key: string; intro: string; flowchart: string }>> {
  const out: Array<{ key: string; intro: string; flowchart: string }> = []
  for (let i = 0; i < funcKeys.length; i++) {
    const key = funcKeys[i]
    const name = key.split('::')[2] || key
    await delay(800)
    out.push({
      key,
      intro: `[AI mock] 该函数 ${name} 负责对应模块的核心逻辑，参数经校验后调用底层驱动完成寄存器配置或状态查询。`,
      flowchart: `@startuml
start
:参数校验;
if (参数合法?) then (yes)
  :执行主逻辑;
  :返回 OK;
else (no)
  :记录日志;
  :返回错误码;
endif
stop
@enduml`,
    })
    onProgress?.(i + 1, funcKeys.length, name)
  }
  return out
}
