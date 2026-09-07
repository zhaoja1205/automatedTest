/**
 * 用例创建模块 Zustand Store。
 *
 * 独立于主 useStore，管理用例创建向导的状态。
 */
import { create } from 'zustand'
import type {
  CaseProject,
  DesignCase,
  CoverageMatrix,
  ProjectMeta,
  DefaultUsed,
} from '../types/creator'

interface CreatorState {
  /** 当前编辑的项目 */
  currentProject: CaseProject | null
  /** 是否有未保存的修改 */
  isDirty: boolean
  /** 当前向导步骤 (0~4) */
  currentStep: number
  /** 导出中 */
  exporting: boolean

  // --- setters ---
  setCurrentProject: (project: CaseProject | null) => void
  setCurrentStep: (step: number) => void
  updateMeta: (meta: Partial<ProjectMeta>) => void
  updateMatrix: (matrix: CoverageMatrix) => void
  setFunctionalCases: (cases: DesignCase[]) => void
  setFaultCases: (cases: DesignCase[]) => void
  setDefaultsUsed: (defaults: DefaultUsed[]) => void
  markDirty: () => void
  markClean: () => void
  setExporting: (v: boolean) => void
  reset: () => void
}

export const useCreatorStore = create<CreatorState>((set) => ({
  currentProject: null,
  isDirty: false,
  currentStep: 0,
  exporting: false,

  setCurrentProject: (project) =>
    set({
      currentProject: project,
      currentStep: project?.current_step ?? 0,
      isDirty: false,
    }),

  setCurrentStep: (step) =>
    set((state) => ({
      currentStep: step,
      currentProject: state.currentProject
        ? { ...state.currentProject, current_step: step }
        : null,
      isDirty: true,
    })),

  updateMeta: (partial) =>
    set((state) => {
      if (!state.currentProject) return state
      return {
        currentProject: {
          ...state.currentProject,
          meta: { ...state.currentProject.meta, ...partial },
        },
        isDirty: true,
      }
    }),

  updateMatrix: (matrix) =>
    set((state) => {
      if (!state.currentProject) return state
      return {
        currentProject: { ...state.currentProject, coverage_matrix: matrix },
        isDirty: true,
      }
    }),

  setFunctionalCases: (cases) =>
    set((state) => {
      if (!state.currentProject) return state
      return {
        currentProject: { ...state.currentProject, functional_cases: cases },
        isDirty: true,
      }
    }),

  setFaultCases: (cases) =>
    set((state) => {
      if (!state.currentProject) return state
      return {
        currentProject: { ...state.currentProject, fault_cases: cases },
        isDirty: true,
      }
    }),

  setDefaultsUsed: (defaults) =>
    set((state) => {
      if (!state.currentProject) return state
      return {
        currentProject: { ...state.currentProject, defaults_used: defaults },
        isDirty: true,
      }
    }),

  markDirty: () => set({ isDirty: true }),
  markClean: () => set({ isDirty: false }),
  setExporting: (v) => set({ exporting: v }),
  reset: () => set({ currentProject: null, isDirty: false, currentStep: 0, exporting: false }),
}))
