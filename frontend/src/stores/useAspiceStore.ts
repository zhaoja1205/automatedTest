/**
 * ASPICE 文档模块 Zustand Store。
 *
 * 独立于主 useStore，管理 ASPICE 向导的状态。
 * 与 creator 模块共享同一项目实体，但此 store 只管 aspice 数据段。
 */
import { create } from 'zustand'
import type {
  AspiceData,
  Requirement,
  ArchMapping,
  AspiceComponent,
  AspiceTopology,
  KpiItem,
  Swe2Overview,
  Swe2Integration,
  Swe2SoftwareDesign,
  Swe2Resources,
  Swe3Data,
  Swe3Overview,
  Swe3Composition,
  Swe3Module,
  Swe3Performance,
  Swe3FunctionEvaluation,
  Swe3CommonDefs,
  Swe3Integration,
  TermItem,
  Swe3PushDData,
  Swe3EngineeringUpload,
  Swe3ModuleCodeSource,
  Swe3ScanIndex,
  Swe3FocusFunctions,
} from '../types/aspice'

const defaultPushD = (): Swe3PushDData => ({
  has_camera_security: true,
  engineering: undefined,
  module_code_sources: [],
  scan_indices: [],
  focus_functions: [],
})

const defaultSwe3 = (): Swe3Data => ({
  project_code: '',
  overview: { purpose: '', scope_rows: [], ref_docs: [], charset: '', getset_rule: '' },
  terms: [],
  composition: { function_overview: '', composition_rows: [] },
  modules: [],
  performance: { paragraphs: [] },
  function_evaluation: { paragraphs: [], impact_paragraphs: [], boundary_analysis: [] },
  common_defs: { constants: [], variables: [], enums: [], structures: [], config_files: [] },
  integration: { paragraphs: [] },
  current_step: 0,
  push_d: defaultPushD(),
})

export const createDefaultAspice = (): AspiceData => ({
  project_code: '',
  swe1: { requirements: [], topology: [], kpi: [], risks: [], current_step: 0 },
  swe2: { mappings: [], components: [], current_step: 0 },
  swe3: defaultSwe3(),
})

interface AspiceState {
  /** 当前编辑的项目 ID */
  projectId: string | null
  /** 项目名称 */
  projectName: string
  /** ASPICE 数据段 */
  aspice: AspiceData | null
  /** 是否有未保存的修改 */
  isDirty: boolean
  /** 当前阶段（swe1 / swe2 / swe3） */
  currentPhase: 'swe1' | 'swe2' | 'swe3'

  // --- setters ---
  setProject: (projectId: string, projectName: string, aspice: AspiceData) => void
  setAspice: (aspice: AspiceData) => void
  setProjectCode: (code: string) => void
  setRequirements: (reqs: Requirement[]) => void
  setTopology: (t: AspiceTopology[]) => void
  setKpi: (k: KpiItem[]) => void
  setMappings: (m: ArchMapping[]) => void
  setComponents: (c: AspiceComponent[]) => void
  setOverview: (overview: Swe2Overview) => void
  setIntegration: (integration: Swe2Integration) => void
  // Phase 4 Group 2 新增：§3 软件设计 / §5 资源 / §6 备选架构
  setSwe2SoftwareDesign: (sd: Swe2SoftwareDesign) => void
  setSwe2Resources: (r: Swe2Resources) => void
  setSwe2AlternativeArch: (text: string) => void
  // SWE.3 setters（推送 C 新增）
  setSwe3: (swe3: Swe3Data) => void
  setSwe3Overview: (overview: Swe3Overview) => void
  setSwe3Terms: (terms: TermItem[]) => void
  setSwe3Composition: (composition: Swe3Composition) => void
  setSwe3Modules: (modules: Swe3Module[]) => void
  setSwe3Performance: (performance: Swe3Performance) => void
  setSwe3FunctionEvaluation: (fe: Swe3FunctionEvaluation) => void
  setSwe3CommonDefs: (cd: Swe3CommonDefs) => void
  setSwe3Integration: (integration: Swe3Integration) => void
  // SWE.3 推送 D setters（UI 版本）
  setSwe3HasCameraSecurity: (on: boolean) => void
  setSwe3Engineering: (engineering: Swe3EngineeringUpload | undefined) => void
  setSwe3ModuleCodeSource: (componentId: string, src: Swe3ModuleCodeSource) => void
  setSwe3ScanIndex: (componentId: string, idx: Swe3ScanIndex) => void
  setSwe3FocusFunctions: (componentId: string, focus: Swe3FocusFunctions) => void
  setCurrentPhase: (phase: 'swe1' | 'swe2' | 'swe3') => void
  markDirty: () => void
  markClean: () => void
  reset: () => void
}

export const useAspiceStore = create<AspiceState>((set) => ({
  projectId: null,
  projectName: '',
  aspice: null,
  isDirty: false,
  currentPhase: 'swe1',

  setProject: (projectId, projectName, aspice) =>
    set({ projectId, projectName, aspice, isDirty: false }),

  setAspice: (aspice) => set({ aspice, isDirty: true }),

  setProjectCode: (code) =>
    set((s) => ({
      aspice: s.aspice ? { ...s.aspice, project_code: code } : null,
      isDirty: true,
    })),

  setRequirements: (reqs) =>
    set((s) => ({
      aspice: s.aspice
        ? { ...s.aspice, swe1: { ...s.aspice.swe1, requirements: reqs } }
        : null,
      isDirty: true,
    })),

  setTopology: (t) =>
    set((s) => ({
      aspice: s.aspice
        ? { ...s.aspice, swe1: { ...s.aspice.swe1, topology: t } }
        : null,
      isDirty: true,
    })),

  setKpi: (k) =>
    set((s) => ({
      aspice: s.aspice
        ? { ...s.aspice, swe1: { ...s.aspice.swe1, kpi: k } }
        : null,
      isDirty: true,
    })),

  setMappings: (m) =>
    set((s) => ({
      aspice: s.aspice
        ? { ...s.aspice, swe2: { ...s.aspice.swe2, mappings: m } }
        : null,
      isDirty: true,
    })),

  setComponents: (c) =>
    set((s) => ({
      aspice: s.aspice
        ? { ...s.aspice, swe2: { ...s.aspice.swe2, components: c } }
        : null,
      isDirty: true,
    })),

  setOverview: (overview) =>
    set((s) => ({
      aspice: s.aspice
        ? { ...s.aspice, swe2: { ...s.aspice.swe2, overview } }
        : null,
      isDirty: true,
    })),

  setIntegration: (integration) =>
    set((s) => ({
      aspice: s.aspice
        ? { ...s.aspice, swe2: { ...s.aspice.swe2, integration } }
        : null,
      isDirty: true,
    })),

  // --- Phase 4 Group 2 新增 ---
  setSwe2SoftwareDesign: (sd) =>
    set((s) => ({
      aspice: s.aspice
        ? { ...s.aspice, swe2: { ...s.aspice.swe2, software_design: sd } }
        : null,
      isDirty: true,
    })),

  setSwe2Resources: (r) =>
    set((s) => ({
      aspice: s.aspice
        ? { ...s.aspice, swe2: { ...s.aspice.swe2, resources: r } }
        : null,
      isDirty: true,
    })),

  setSwe2AlternativeArch: (text) =>
    set((s) => ({
      aspice: s.aspice
        ? { ...s.aspice, swe2: { ...s.aspice.swe2, alternative_arch: text } }
        : null,
      isDirty: true,
    })),

  // --- SWE.3 setters（推送 C 新增） ---
  setSwe3: (swe3) =>
    set((s) => ({
      aspice: s.aspice ? { ...s.aspice, swe3 } : null,
      isDirty: true,
    })),

  setSwe3Overview: (overview) =>
    set((s) => ({
      aspice: s.aspice
        ? { ...s.aspice, swe3: { ...(s.aspice.swe3 || defaultSwe3()), overview } }
        : null,
      isDirty: true,
    })),

  setSwe3Terms: (terms) =>
    set((s) => ({
      aspice: s.aspice
        ? { ...s.aspice, swe3: { ...(s.aspice.swe3 || defaultSwe3()), terms } }
        : null,
      isDirty: true,
    })),

  setSwe3Composition: (composition) =>
    set((s) => ({
      aspice: s.aspice
        ? { ...s.aspice, swe3: { ...(s.aspice.swe3 || defaultSwe3()), composition } }
        : null,
      isDirty: true,
    })),

  setSwe3Modules: (modules) =>
    set((s) => ({
      aspice: s.aspice
        ? { ...s.aspice, swe3: { ...(s.aspice.swe3 || defaultSwe3()), modules } }
        : null,
      isDirty: true,
    })),

  setSwe3Performance: (performance) =>
    set((s) => ({
      aspice: s.aspice
        ? { ...s.aspice, swe3: { ...(s.aspice.swe3 || defaultSwe3()), performance } }
        : null,
      isDirty: true,
    })),

  setSwe3FunctionEvaluation: (function_evaluation) =>
    set((s) => ({
      aspice: s.aspice
        ? { ...s.aspice, swe3: { ...(s.aspice.swe3 || defaultSwe3()), function_evaluation } }
        : null,
      isDirty: true,
    })),

  setSwe3CommonDefs: (common_defs) =>
    set((s) => ({
      aspice: s.aspice
        ? { ...s.aspice, swe3: { ...(s.aspice.swe3 || defaultSwe3()), common_defs } }
        : null,
      isDirty: true,
    })),

  setSwe3Integration: (integration) =>
    set((s) => ({
      aspice: s.aspice
        ? { ...s.aspice, swe3: { ...(s.aspice.swe3 || defaultSwe3()), integration } }
        : null,
      isDirty: true,
    })),

  // --- SWE.3 推送 D setters（UI 版本） ---
  setSwe3HasCameraSecurity: (on) =>
    set((s) => {
      if (!s.aspice) return {}
      const swe3 = s.aspice.swe3 || defaultSwe3()
      const push_d = { ...(swe3.push_d || defaultPushD()), has_camera_security: on }
      return {
        aspice: { ...s.aspice, swe3: { ...swe3, push_d } },
        isDirty: true,
      }
    }),

  setSwe3Engineering: (engineering) =>
    set((s) => {
      if (!s.aspice) return {}
      const swe3 = s.aspice.swe3 || defaultSwe3()
      const push_d = { ...(swe3.push_d || defaultPushD()), engineering }
      return {
        aspice: { ...s.aspice, swe3: { ...swe3, push_d } },
        isDirty: true,
      }
    }),

  setSwe3ModuleCodeSource: (componentId, src) =>
    set((s) => {
      if (!s.aspice) return {}
      const swe3 = s.aspice.swe3 || defaultSwe3()
      const base = swe3.push_d || defaultPushD()
      const arr = base.module_code_sources.filter((m) => m.component_id !== componentId)
      arr.push(src)
      return {
        aspice: { ...s.aspice, swe3: { ...swe3, push_d: { ...base, module_code_sources: arr } } },
        isDirty: true,
      }
    }),

  setSwe3ScanIndex: (componentId, idx) =>
    set((s) => {
      if (!s.aspice) return {}
      const swe3 = s.aspice.swe3 || defaultSwe3()
      const base = swe3.push_d || defaultPushD()
      const arr = base.scan_indices.filter((m) => m.component_id !== componentId)
      arr.push(idx)
      return {
        aspice: { ...s.aspice, swe3: { ...swe3, push_d: { ...base, scan_indices: arr } } },
        isDirty: true,
      }
    }),

  setSwe3FocusFunctions: (componentId, focus) =>
    set((s) => {
      if (!s.aspice) return {}
      const swe3 = s.aspice.swe3 || defaultSwe3()
      const base = swe3.push_d || defaultPushD()
      const arr = base.focus_functions.filter((m) => m.component_id !== componentId)
      arr.push(focus)
      return {
        aspice: { ...s.aspice, swe3: { ...swe3, push_d: { ...base, focus_functions: arr } } },
        isDirty: true,
      }
    }),

  setCurrentPhase: (phase) => set({ currentPhase: phase }),
  markDirty: () => set({ isDirty: true }),
  markClean: () => set({ isDirty: false }),
  reset: () =>
    set({
      projectId: null,
      projectName: '',
      aspice: null,
      isDirty: false,
      currentPhase: 'swe1',
    }),
}))
