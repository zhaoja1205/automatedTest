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
} from '../types/aspice'

interface AspiceState {
  /** 当前编辑的项目 ID */
  projectId: string | null
  /** 项目名称 */
  projectName: string
  /** ASPICE 数据段 */
  aspice: AspiceData | null
  /** 是否有未保存的修改 */
  isDirty: boolean
  /** 当前阶段（swe1 / swe2） */
  currentPhase: 'swe1' | 'swe2'

  // --- setters ---
  setProject: (projectId: string, projectName: string, aspice: AspiceData) => void
  setAspice: (aspice: AspiceData) => void
  setProjectCode: (code: string) => void
  setRequirements: (reqs: Requirement[]) => void
  setTopology: (t: AspiceTopology[]) => void
  setKpi: (k: KpiItem[]) => void
  setMappings: (m: ArchMapping[]) => void
  setComponents: (c: AspiceComponent[]) => void
  setCurrentPhase: (phase: 'swe1' | 'swe2') => void
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
