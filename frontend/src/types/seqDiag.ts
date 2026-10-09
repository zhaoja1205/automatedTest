/**
 * 函数时序图模块类型定义。
 *
 * 对齐后端 `seqdiag_routes.py` / `seqdiag_store.py` 的 project.json 结构。
 */

export interface IncludeItem {
  name: string
  path: string
  uploaded_at: string
  zip_name?: string
  summary?: { entry_count?: number; file_count?: number; top_dirs?: string[] }
}

export interface SeqLastQuery {
  func_a_name: string
  func_b_name?: string
  resolved_func_a?: string
  resolved_func_b?: string
  matched_files: string[]
  uml: string
}

export interface SeqDiagProject {
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
  last_query: SeqLastQuery | null
}

export interface SeqDiagProjectSummary {
  project_id: string
  name: string
  created_at: string
  updated_at: string
  has_source: boolean
  include_count: number
  last_func: string
}

export interface SeqGenerateRequest {
  func_a_name: string
  func_b_name?: string
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

export type SeqGenerateResult = SeqLastQuery
