/**
 * 推送 G R2 方案 B：浏览器端选目录 → 分片直传工程树到后端。
 *
 * 替代"打 zip 上传"。用户本机零安装，走 File System Access API。
 *
 * 流程：
 *   1. showDirectoryPicker 选工程根
 *   2. 遍历目录，按扩展名白名单 + 目录黑名单过滤出要传的文件列表
 *   3. engineeringTreeStart 清空后端旧 engineering_src/
 *   4. 按 ≤ 10 MB / ≤ 50 文件打包，并发 3 路 POST
 *   5. engineeringTreeFinish 触发后端扫目录产 meta，返回 meta 回前端
 *   6. 任何环节失败 → engineeringTreeAbort 清半包
 *
 * 和 R2 自动 diff 完全互补：
 *   - 这个组件管"把源码送到后端供代码扫描/AI 用"
 *   - EngineeringScanner 管"浏览器本地算 git diff 送到后端打 diff_status"
 *   两者共用同一个 showDirectoryPicker 入口（用户只选一次目录就能完成两件事）。
 */

// 想要传的源码扩展名
const SOURCE_EXTS = new Set([
  '.h', '.hpp', '.hh', '.hxx',
  '.c', '.cpp', '.cc', '.cxx',
])
// 也捎上这些配置/文档文件（扫码不用但对比对版本有帮助）
const EXTRA_FILES = new Set([
  'CMakeLists.txt', 'Makefile', 'README', 'README.md',
])

// 和后端 _SKIP_SEGMENTS 对齐；浏览器端提前过滤能大幅减少文件数
const SKIP_DIRS = new Set([
  '.git', '.hg', '.svn',
  'build', 'out', 'dist', 'cmake-build-debug', 'cmake-build-release',
  'node_modules', 'third_party', 'third-party',
  '.vscode', '.idea', '.cache',
  // 常见的编译产物/运行产物
  'target', 'bin', 'obj',
])

export interface FileEntry {
  path: string   // 相对工程根的 posix 路径
  handle: any    // FileSystemFileHandle
  size: number
}

export interface TreeTraverseProgress {
  scanned: number
  found: number
  skipped: number
  currentDir?: string
}

export interface TreeUploadProgress {
  phase: 'traversing' | 'starting' | 'uploading' | 'finishing' | 'done' | 'aborted' | 'error'
  filesTotal: number
  filesSent: number
  bytesTotal: number
  bytesSent: number
  currentPath?: string
  message?: string
}

function isWantedFile(name: string): boolean {
  if (EXTRA_FILES.has(name)) return true
  const dot = name.lastIndexOf('.')
  if (dot < 0) return false
  return SOURCE_EXTS.has(name.slice(dot).toLowerCase())
}

/** 遍历目录 handle，按白名单收集文件。
 *  返回的 path 都是 posix 风格、相对工程根，不以 / 开头。 */
export async function traverseDirectory(
  rootHandle: any,
  onProgress: (p: TreeTraverseProgress) => void,
): Promise<FileEntry[]> {
  const result: FileEntry[] = []
  const stats = { scanned: 0, found: 0, skipped: 0 }

  async function visit(handle: any, prefix: string) {
    onProgress({ ...stats, currentDir: prefix || '/' })
    // @ts-ignore FileSystemDirectoryHandle.values()
    for await (const entry of handle.values()) {
      if (entry.kind === 'directory') {
        if (SKIP_DIRS.has(entry.name)) {
          stats.skipped++
          continue
        }
        await visit(entry, prefix ? `${prefix}/${entry.name}` : entry.name)
      } else if (entry.kind === 'file') {
        stats.scanned++
        if (!isWantedFile(entry.name)) continue
        try {
          const file: File = await entry.getFile()
          result.push({
            path: prefix ? `${prefix}/${entry.name}` : entry.name,
            handle: entry,
            size: file.size,
          })
          stats.found++
        } catch { /* 读失败，跳过 */ }
      }
    }
  }

  await visit(rootHandle, '')
  onProgress({ ...stats })
  return result
}

/** 让用户选目录。返回 rootHandle 和工作区名。 */
export async function pickWorkspace(): Promise<{ rootHandle: any; name: string }> {
  // @ts-ignore
  if (typeof window.showDirectoryPicker !== 'function') {
    throw new Error('当前浏览器不支持 File System Access API')
  }
  // @ts-ignore
  const handle: any = await window.showDirectoryPicker({ mode: 'read' })
  return { rootHandle: handle, name: handle.name || 'workspace' }
}

/** 按 posix 相对路径 ("a/b/c") 从 rootHandle 逐级 getDirectoryHandle 下钻。
 *  用于 git-repo 布局：选工作区根 + 输入子工程路径。
 *  任一段找不到就抛 Error 说明在哪断的。 */
export async function resolveSubHandle(rootHandle: any, relPath: string): Promise<any> {
  const parts = relPath.split('/').map((s) => s.trim()).filter((s) => s && s !== '.')
  if (parts.some((p) => p === '..')) throw new Error(`子工程路径不允许 ..: ${relPath}`)
  let cur = rootHandle
  const traversed: string[] = []
  for (const p of parts) {
    try {
      cur = await cur.getDirectoryHandle(p)
      traversed.push(p)
    } catch {
      throw new Error(`子工程路径不存在：到 "${traversed.join('/') || '(根)'}" 下找不到子目录 "${p}"`)
    }
  }
  return cur
}

/** 检测目录是否为 git-repo 工作区（根下有 .repo 目录）。 */
export async function detectRepoWorkspace(rootHandle: any): Promise<boolean> {
  try {
    await rootHandle.getDirectoryHandle('.repo')
    return true
  } catch { return false }
}

/**
 * 把 files 分成若干 batch，每 batch ≤ maxBytes 或 ≤ maxFiles。
 * 单文件超 maxBytes 的独占一 batch（后端会拒，但错误能被精确归因）。
 */
export function planBatches(
  files: FileEntry[],
  maxBytes = 10 * 1024 * 1024,   // 每批 10 MB
  maxFiles = 50,
): FileEntry[][] {
  const batches: FileEntry[][] = []
  let cur: FileEntry[] = []
  let curBytes = 0
  for (const f of files) {
    if (cur.length >= maxFiles || (cur.length > 0 && curBytes + f.size > maxBytes)) {
      batches.push(cur); cur = []; curBytes = 0
    }
    cur.push(f); curBytes += f.size
  }
  if (cur.length) batches.push(cur)
  return batches
}

/** 并发池：并行度 N，异常中止。 */
export async function runConcurrent<T>(
  items: T[], worker: (item: T, idx: number) => Promise<void>,
  concurrency: number,
): Promise<void> {
  let next = 0
  const workers: Promise<void>[] = []
  for (let i = 0; i < Math.min(concurrency, items.length); i++) {
    workers.push((async () => {
      while (next < items.length) {
        const idx = next++
        await worker(items[idx], idx)
      }
    })())
  }
  await Promise.all(workers)
}
