/**
 * 类图分析模块类型定义。
 *
 * 对齐后端 `classdiag_routes.py` / `classdiag_store.py` 的 project.json 结构。
 */

export interface IncludeItem {
  name: string
  path: string
  uploaded_at: string
  zip_name?: string
  summary?: { entry_count?: number; file_count?: number; top_dirs?: string[] }
}

export interface LastQuery {
  class_name: string
  resolved_qualified_name?: string
  options: ClassDiagOptions
  depth?: number
  matched_headers: string[]
  clang_status: 'unavailable' | 'ok' | 'partial' | 'error'
  clang_diagnostics: string[]
  uml: string
  stage: 'regex' | 'clang'
  next_stage: 'clang' | null
}

export interface ClassDiagProject {
  project_id: string
  name: string
  created_at: string
  updated_at: string
  source_dir: string
  source_zip_name: string
  source_summary: {
    entry_count?: number
    file_count?: number
    top_dirs?: string[]
  }
  include_dirs: IncludeItem[]
  last_query: LastQuery | null
}

export interface ClassDiagProjectSummary {
  project_id: string
  name: string
  created_at: string
  updated_at: string
  has_source: boolean
  include_count: number
  last_class: string
}

export interface ClassDiagOptions {
  show_private: boolean
  show_protected: boolean
  show_static: boolean
}

export interface GenerateRequest {
  class_name: string
  stage?: 'regex' | 'clang' | 'auto'
  options?: Partial<ClassDiagOptions>
  /** 向上追踪的继承层数，默认 2，后端 clamp 到 1..10 */
  depth?: number
}

export interface MultiMatchCandidate {
  qualified_name: string
  file: string
  line: number
  kind: string
}

export interface MultiMatchError {
  detail: string
  matches: MultiMatchCandidate[]
}

export type GenerateResult = LastQuery
