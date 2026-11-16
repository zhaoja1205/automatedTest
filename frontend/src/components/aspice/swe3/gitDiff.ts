/**
 * 推送 G 第二轮：Chrome File System Access API → LightningFS 镜像 → isomorphic-git diff。
 *
 * 为什么不直接实现 isomorphic-git 的 fs adapter 去直通 FileSystemDirectoryHandle：
 *   - isomorphic-git 的 fs 接口是同步/异步混合，而 FS Access API 全是异步 Promise
 *   - 做 adapter 需要 sync-promise 妥协，调试成本高
 *   - 我们只读 .git/ 一次、做一次 diff；镜像 .git（通常 50 MB~500 MB）到 IndexedDB 一次性成本可控
 *
 * 流程：
 *   1. pickDirectoryAndMirrorGit(): 让用户授权目录 → 把 .git/ 镜像到 LightningFS
 *   2. listBranches(): 列分支+tag，用于让用户选 baseline
 *   3. computeDiff(baseline): 跑 git.walk 产出 changed/added 文件清单
 *
 * 浏览器要求：Chromium 系（Chrome 86+ / Edge 86+）；Firefox/Safari 没 showDirectoryPicker。
 */
// isomorphic-git 读 pack 文件时要 globalThis.Buffer（Node.js API），浏览器没有。
// 必须在 import isomorphic-git 之前注入 polyfill —— import 顺序敏感。
import { Buffer } from 'buffer'
if (typeof (globalThis as any).Buffer === 'undefined') {
  ;(globalThis as any).Buffer = Buffer
}
import git from 'isomorphic-git'
import FS from '@isomorphic-git/lightning-fs'

const FS_NAME = 'swe3-git-fs'
const GIT_DIR = '/repo'

const fs = new FS(FS_NAME)
// isomorphic-git 要的 fs API：fs.promises.{readFile,writeFile,readdir,mkdir,stat,lstat,unlink,rmdir,readlink,symlink,chmod}
const gitFs = fs

interface MirrorProgress {
  current: number
  total: number
  path?: string
}

export interface GitBranch {
  name: string     // 短名，如 "main" / "v1.0.0"
  kind: 'branch' | 'tag' | 'remote'
  sha: string
}

export interface GitHunk {
  /** 1-indexed，HEAD（新版）里改动落在的起始行 */
  new_start: number
  /** HEAD 版里 hunk 跨越的行数；纯删除 hunk 为 0（上下文锚点行用 new_start 单行表示） */
  new_lines: number
}

export interface GitDiffResult {
  baselineCommit: string
  baselineBranch: string
  headCommit: string
  headBranch: string
  changedFiles: string[]
  addedFiles: string[]
  deletedFiles: string[]
  /** 推送 G 粒度升级：每个 changed_file 在 HEAD 版里的改动行区间
   *  用于后端 classify_functions 做 hunk × 函数 line_start/line_end 的交集判定，
   *  把"文件改一行 → 文件内所有函数都标 modified"的文件级粒度 bug 细到函数级。
   *  超大文件（超过 FILE_HUNK_LINE_LIMIT）不计算 hunks，走后端文件级回落。
   */
  fileHunks: Record<string, GitHunk[]>
}

// 文件级回落阈值：两侧都没超过就跑 Myers。阈值主要防止 git 里混进来的 minified
// JS / 自动生成的 register definition 之类 50 万行的怪物把浏览器 UI 卡死。
// 普通 C/C++ 驱动文件 1 万~3 万行用 Myers 都是毫秒级。
const FILE_HUNK_LINE_LIMIT = 100000
// Myers 算法的编辑距离 D 封顶：避免整文件重写时退化为 O(N²)。
// 距离超过这个就相当于"大半个文件都变了"，回落到后端文件级粒度（反正函数几乎都动了）。
const MYERS_MAX_EDITS = 20000

/** 把当前已镜像的 .git 清空（切项目时调）。 */
async function resetFs(): Promise<void> {
  // LightningFS 没有"整库清空"API，走 rimraf
  async function rm(p: string) {
    try {
      const stat = await gitFs.promises.lstat(p)
      if (stat.isDirectory()) {
        const entries = await gitFs.promises.readdir(p)
        for (const e of entries) await rm(`${p}/${e}`)
        await gitFs.promises.rmdir(p)
      } else {
        await gitFs.promises.unlink(p)
      }
    } catch { /* 已不存在 */ }
  }
  await rm(GIT_DIR)
  try { await gitFs.promises.mkdir(GIT_DIR) } catch { /* 已存在 */ }
}

/** 递归统计 handle 下 .git 内的文件数，用于进度条。 */
async function countFiles(dirHandle: any): Promise<number> {
  let n = 0
  // @ts-ignore FileSystemDirectoryHandle.values() 返回 async iterator
  for await (const entry of dirHandle.values()) {
    if (entry.kind === 'file') n++
    else if (entry.kind === 'directory') n += await countFiles(entry)
  }
  return n
}

/** 递归把 handle 下所有文件镜像到 LightningFS 下的 /repo/<relPath>。 */
async function mirrorDir(
  handle: any, destDir: string,
  onProgress: (p: MirrorProgress) => void, state: { done: number; total: number },
): Promise<void> {
  try { await gitFs.promises.mkdir(destDir) } catch { /* 已存在 */ }
  // @ts-ignore
  for await (const entry of handle.values()) {
    const sub = `${destDir}/${entry.name}`
    if (entry.kind === 'file') {
      const file: File = await entry.getFile()
      const buf = new Uint8Array(await file.arrayBuffer())
      await gitFs.promises.writeFile(sub, buf)
      state.done++
      onProgress({ current: state.done, total: state.total, path: sub })
    } else if (entry.kind === 'directory') {
      await mirrorDir(entry, sub, onProgress, state)
    }
  }
}

/** 让用户选目录，自动找到 .git 并镜像。返回工程根下 .git 的 relative structure。 */
export async function pickDirectoryAndMirrorGit(
  onProgress: (p: MirrorProgress) => void,
): Promise<{ workspaceName: string; totalFiles: number }> {
  // @ts-ignore showDirectoryPicker 实验 API，TS 定义不稳
  if (typeof window.showDirectoryPicker !== 'function') {
    throw new Error('当前浏览器不支持 File System Access API，请改用 Chrome/Edge')
  }
  // @ts-ignore
  const rootHandle: any = await window.showDirectoryPicker({ mode: 'read' })
  const r = await mirrorGitFromRoot(rootHandle, onProgress)
  return { workspaceName: rootHandle.name, ...r }
}

/** 已经有 rootHandle（外部拿的），在其中找 .git 并镜像。
 *  用于"选目录做多件事"的场景 —— 拿一次 handle，既传源码又算 diff。 */
export async function mirrorGitFromRoot(
  rootHandle: any,
  onProgress: (p: MirrorProgress) => void,
): Promise<{ totalFiles: number }> {
  // 找 .git 目录（必须是工程根）
  let gitHandle: any = null
  try {
    gitHandle = await rootHandle.getDirectoryHandle('.git')
  } catch {
    throw new Error('目录中没有 .git/（请选择 git 工程的根目录）')
  }

  await resetFs()

  // 先统计文件数做进度；.git 大多 1 万~10 万文件
  onProgress({ current: 0, total: 0, path: '正在清点 .git 目录…' })
  const total = await countFiles(gitHandle)
  onProgress({ current: 0, total })

  // 镜像 .git → /repo/.git
  const state = { done: 0, total }
  await mirrorDir(gitHandle, `${GIT_DIR}/.git`, onProgress, state)

  return { totalFiles: total }
}

/**
 * git-repo 布局镜像：从工作区根 (含 .repo/) 定位子工程真实 .git，再镜像。
 *
 * git-repo 的两层 symlink（Chrome FS API 都不跟随）：
 *   1. 工程根/.git          → .repo/projects/<rel>.git         （我们在 UI 让用户填相对路径跨过去）
 *   2. 上面那个 .git/objects → .repo/project-objects/<rel>.git/objects  （本函数额外镜像过去）
 *
 * 如果不处理第 2 层，镜像到的 .git/objects 会是空目录（只有 info/pack 空壳），
 * isomorphic-git 一 resolveRef 到 commit 就 "Could not find <sha>"。
 *
 * repoRootHandle: 用户选的工作区根（下面有 .repo/）
 * subProjectRelPath: 相对工作区根的子工程路径，如 "nvidia/Qnx_Standard_7.2.4.0/drive-qnx/samples/nvmedia"
 */
export async function mirrorGitFromRepoLayout(
  repoRootHandle: any,
  subProjectRelPath: string,
  onProgress: (p: MirrorProgress) => void,
): Promise<{ totalFiles: number; realGitPath: string }> {
  // 定位 .repo/
  let repoDir: any = null
  try {
    repoDir = await repoRootHandle.getDirectoryHandle('.repo')
  } catch {
    throw new Error('工作区根下没有 .repo/（请选 git-repo 管理的 SDK 根目录）')
  }

  // 子工程路径
  const rel = subProjectRelPath.replace(/\\/g, '/').replace(/^\/+|\/+$/g, '')
  if (!rel) throw new Error('子工程路径为空')
  const parts = rel.split('/').filter((s) => s && s !== '.')
  if (parts.some((p) => p === '..')) throw new Error(`子工程路径不允许 ..: ${subProjectRelPath}`)

  // 通用：在 .repo/<topDir>/parts.../<leaf>.git 定位 handle
  async function locateProjectGit(topDir: string): Promise<any> {
    let top: any
    try { top = await repoDir.getDirectoryHandle(topDir) }
    catch { throw new Error(`.repo/ 下没有 ${topDir}/（不是标准 git-repo 布局）`) }

    let cur = top
    const traversed: string[] = []
    for (let i = 0; i < parts.length - 1; i++) {
      try {
        cur = await cur.getDirectoryHandle(parts[i])
        traversed.push(parts[i])
      } catch {
        throw new Error(
          `.repo/${topDir}/${traversed.join('/') || '(根)'} 下找不到 "${parts[i]}"（检查子工程路径是否正确）`,
        )
      }
    }
    const leaf = parts[parts.length - 1]
    try {
      return await cur.getDirectoryHandle(`${leaf}.git`)
    } catch {
      throw new Error(
        `.repo/${topDir}/${parts.slice(0, -1).join('/')}/${leaf}.git 不存在（repo 还没 sync？或子工程路径错？）`,
      )
    }
  }

  // 第 1 层：projects/.../leaf.git （HEAD/config/refs/packed-refs 等）
  const projectsGitHandle = await locateProjectGit('projects')
  // 第 2 层：project-objects/.../leaf.git/objects （真实 object pool）
  //   少数 repo 布局没有分 project-objects，此时降级成只镜像 projects 侧（可能仍能 work）
  let objectsHandle: any = null
  try {
    const projObjGitHandle = await locateProjectGit('project-objects')
    try {
      objectsHandle = await projObjGitHandle.getDirectoryHandle('objects')
    } catch {
      // 没 objects 子目录，继续走
    }
  } catch {
    // 没 project-objects 这个 top，继续走
  }

  const realGitPath = `.repo/projects/${parts.join('/')}.git`
    + (objectsHandle ? ` + .repo/project-objects/${parts.join('/')}.git/objects` : '')
  await resetFs()

  // 先镜像 projects 侧（结构骨架 + loose 侧 objects 占位目录）
  onProgress({ current: 0, total: 0, path: `正在清点 projects 侧…` })
  const totalProj = await countFiles(projectsGitHandle)

  let totalObj = 0
  if (objectsHandle) {
    onProgress({ current: 0, total: totalProj, path: `正在清点 project-objects/…/objects 侧…` })
    totalObj = await countFiles(objectsHandle)
  }
  const totalAll = totalProj + totalObj
  onProgress({ current: 0, total: totalAll })

  const state = { done: 0, total: totalAll }
  // 镜像 projects 侧 .git
  await mirrorDir(projectsGitHandle, `${GIT_DIR}/.git`, onProgress, state)

  if (objectsHandle) {
    // 删掉 projects 侧镜像过来的（空）objects 占位，用真实 objects 覆盖
    try {
      await rmRecursive(`${GIT_DIR}/.git/objects`)
    } catch { /* ignore */ }
    await mirrorDir(objectsHandle, `${GIT_DIR}/.git/objects`, onProgress, state)
  }

  return { totalFiles: totalAll, realGitPath }
}

// 递归删 LightningFS 下一个路径（兼容文件/目录）。
async function rmRecursive(p: string): Promise<void> {
  try {
    const stat = await gitFs.promises.lstat(p)
    if (stat.isDirectory()) {
      const entries = await gitFs.promises.readdir(p)
      for (const e of entries) await rmRecursive(`${p}/${e}`)
      await gitFs.promises.rmdir(p)
    } else {
      await gitFs.promises.unlink(p)
    }
  } catch { /* 已不存在 */ }
}

/** 列当前镜像仓库的分支 + tags（给选 baseline 用）。 */
export async function listBranches(): Promise<GitBranch[]> {
  const out: GitBranch[] = []
  try {
    const branches = await git.listBranches({ fs: gitFs, dir: GIT_DIR })
    for (const name of branches) {
      try {
        const sha = await git.resolveRef({ fs: gitFs, dir: GIT_DIR, ref: name })
        out.push({ name, kind: 'branch', sha })
      } catch { /* 跳过解析失败的 */ }
    }
  } catch { /* 无分支 */ }
  try {
    const tags = await git.listTags({ fs: gitFs, dir: GIT_DIR })
    for (const name of tags) {
      try {
        const sha = await git.resolveRef({ fs: gitFs, dir: GIT_DIR, ref: name })
        out.push({ name, kind: 'tag', sha })
      } catch { /* 跳过 */ }
    }
  } catch { /* 无 tag */ }
  try {
    const remotes = await git.listBranches({ fs: gitFs, dir: GIT_DIR, remote: 'origin' })
    for (const name of remotes) {
      try {
        const sha = await git.resolveRef({
          fs: gitFs, dir: GIT_DIR, ref: `refs/remotes/origin/${name}`,
        })
        out.push({ name: `origin/${name}`, kind: 'remote', sha })
      } catch { /* 跳过 */ }
    }
  } catch { /* 无 remote */ }
  return out
}

/** 返回当前 HEAD 的 SHA + 分支名（detached 时 branch 空）。 */
export async function getHead(): Promise<{ sha: string; branch: string }> {
  const sha = await git.resolveRef({ fs: gitFs, dir: GIT_DIR, ref: 'HEAD' })
  let branch = ''
  try {
    branch = (await git.currentBranch({ fs: gitFs, dir: GIT_DIR, fullname: false })) || ''
  } catch { /* detached */ }
  return { sha, branch }
}

/**
 * 跑 baseline..HEAD 文件级 diff。
 *
 * isomorphic-git 的 walk 接口给我们 (filepath, [treeA, treeB]) 的回调，
 * 我们按 oid 比对判定 added / modified / deleted。
 */
/**
 * 把 ref 字符串解析成 commit SHA。
 *   - 全 hex 且长度 7~40 的字符串：当 raw sha 处理，用 expandOid 补全（支持短 sha）
 *   - 其他：当分支/tag 名走 resolveRef
 * raw sha 的好处：用户可以在 git log 里拷一个任意 commit 作 baseline。
 */
async function resolveToCommitSha(ref: string): Promise<string> {
  const trimmed = ref.trim()
  const isHex = /^[0-9a-fA-F]{7,40}$/.test(trimmed)
  if (isHex) {
    try {
      // expandOid 对完整 40 位 sha 也能 identity 返回；对 7+ 位短 sha 补全
      const full = await git.expandOid({ fs: gitFs, dir: GIT_DIR, oid: trimmed.toLowerCase() })
      return full
    } catch (e: any) {
      throw new Error(`commit "${trimmed}" 在镜像仓库中找不到：${e?.message || e}`)
    }
  }
  return git.resolveRef({ fs: gitFs, dir: GIT_DIR, ref: trimmed })
}

/** 行级 Myers O(ND) 差分 → hunks（HEAD 版行号 1-indexed）。
 *
 *  为什么不是 LCS：11621 × 13465 行的 cdi_max96724.c 用 LCS 需要 ~625MB Uint32Array，
 *  浏览器直接爆。Myers 的编辑距离 D 对相似文件通常只有几百，时间 O((N+M)*D)、
 *  空间 O(D²) 存 trace，万行文件也就几 MB 内存、百毫秒级。
 *
 *  算法骨架（Myers 1986 §4b）：
 *    - 第 1 步前向搜索：V[k] 记录 k 对角线上能走到的最远 x；每轮 D 保留 V 快照
 *    - 第 2 步回溯：从 (N,M) 反推 trace，一路还原正向的 edit script
 *    - 第 3 步发射：把 edit script 扫一遍，合并相邻新增行、独立发射纯删除锚点
 *
 *  返回：
 *    GitHunk[]（含 []，表示内容一致） — hunks
 *    null                           — 文件太大 / 距离太远，回落后端文件级
 */
function computeFileHunks(oldText: string, newText: string): GitHunk[] | null {
  const a = oldText.split('\n')
  const b = newText.split('\n')
  const N = a.length
  const M = b.length
  if (N > FILE_HUNK_LINE_LIMIT || M > FILE_HUNK_LINE_LIMIT) return null
  if (N === 0 && M === 0) return []
  if (N === 0) return [{ new_start: 1, new_lines: M }]
  if (M === 0) return [{ new_start: 1, new_lines: 0 }]

  // ---- 第 1 步：前向 Myers，记录每一轮 D 的 V 快照 ----
  const MAX = N + M
  if (MAX > MYERS_MAX_EDITS * 4) return null
  const offset = MAX
  const vSize = 2 * MAX + 1
  const V = new Int32Array(vSize)
  const trace: Int32Array[] = []
  let foundD = -1
  outer: for (let D = 0; D <= Math.min(MAX, MYERS_MAX_EDITS); D++) {
    // 本轮开始前先把 V 存一份（存"轮次 D 开始时"的 V 更适合回溯）
    const snap = new Int32Array(V)
    trace.push(snap)
    for (let k = -D; k <= D; k += 2) {
      let x: number
      if (k === -D || (k !== D && V[k - 1 + offset] < V[k + 1 + offset])) {
        x = V[k + 1 + offset]       // 向下（insert）
      } else {
        x = V[k - 1 + offset] + 1   // 向右（delete）
      }
      let y = x - k
      while (x < N && y < M && a[x] === b[y]) { x++; y++ }
      V[k + offset] = x
      if (x >= N && y >= M) { foundD = D; break outer }
    }
  }
  if (foundD < 0) return null

  // ---- 第 2 步：反向回溯，产出正向的 edit ops ----
  // ops：按正向顺序，每条是 {t: 'd'|'i', newLine1: number}
  //   d: delete a[prevX] — 它在 baseline 里的位置被"跳过"，锚到 HEAD 版行 prevY+1
  //   i: insert b[prevY] — 它是 HEAD 版第 prevY+1 行
  const opsRev: Array<{ t: 'd' | 'i'; nl: number }> = []
  let x = N, y = M
  for (let D = foundD; D > 0; D--) {
    const vPrev = trace[D]         // 轮次 D 开始时的 V（即轮次 D-1 结束时的 V）
    const k = x - y
    let prevK: number
    if (k === -D || (k !== D && vPrev[k - 1 + offset] < vPrev[k + 1 + offset])) {
      prevK = k + 1                // 本步是 insert（向下）
    } else {
      prevK = k - 1                // 本步是 delete（向右）
    }
    const prevX = vPrev[prevK + offset]
    const prevY = prevX - prevK
    // 回滑 snake（无 edit 段）
    while (x > prevX && y > prevY && a[x - 1] === b[y - 1]) { x--; y-- }
    if (D > 0 && (x !== prevX || y !== prevY)) {
      if (prevK === k - 1) {
        // delete a[prevX]；在 HEAD 里锚到 prevY+1 行（1-indexed）
        opsRev.push({ t: 'd', nl: prevY + 1 })
      } else {
        // insert b[prevY]；HEAD 版第 prevY+1 行
        opsRev.push({ t: 'i', nl: prevY + 1 })
      }
    }
    x = prevX; y = prevY
  }

  // ---- 第 3 步：正向扫 edit ops → 聚合 hunks ----
  const ops = opsRev.reverse()
  const hunks: GitHunk[] = []
  let runStart = -1, runEnd = -1
  const flush = () => {
    if (runStart > 0) {
      hunks.push({ new_start: runStart, new_lines: runEnd - runStart + 1 })
      runStart = -1; runEnd = -1
    }
  }
  // pendingDel：连续的 delete 聚合。规则：
  //   - 若紧接着来个 insert → 合并成一个 "modify" run（锚点行就是 insert 的首行）
  //   - 若紧接着又是 delete 在同 anchor → 已被同 anchor 吸收，不再发
  //   - 若过渡到完全不同位置 → 作为独立纯删除 hunk 发射
  let pendingDelAnchor = -1
  // 锚点行号须钳在 [1, M] — 文件末尾删除的 anchor 会算到 M+1，没意义；
  // 钳到 M 可以让 classify_functions 的交集判定命中文件末尾的函数（更符合直觉）
  const clampAnchor = (nl: number) => Math.min(Math.max(1, nl), Math.max(1, M))
  const emitDelAnchor = (nl: number) => {
    const anchor = clampAnchor(nl)
    // 若恰好能贴到当前 run 两端，吸入 run（不独立发）
    if (runStart > 0 && anchor >= runStart - 1 && anchor <= runEnd + 1) return
    flush()
    hunks.push({ new_start: anchor, new_lines: 0 })
  }
  for (let i = 0; i < ops.length; i++) {
    const op = ops[i]
    if (op.t === 'd') {
      if (pendingDelAnchor === op.nl) continue  // 连续同锚点 delete，合并一次
      // flush 掉可能挂着的前一个 anchor
      if (pendingDelAnchor > 0) { emitDelAnchor(pendingDelAnchor); pendingDelAnchor = -1 }
      pendingDelAnchor = op.nl
    } else {
      // insert：若有挂起 delete 且 anchor == 当前 insert 行 → 吸入 run（变成替换/modify）
      const nl = op.nl
      if (pendingDelAnchor === nl) pendingDelAnchor = -1
      else if (pendingDelAnchor > 0) { emitDelAnchor(pendingDelAnchor); pendingDelAnchor = -1 }
      // 把 nl 加进 run
      if (runStart < 0) { runStart = nl; runEnd = nl }
      else if (nl === runEnd + 1) runEnd = nl
      else if (nl === runStart - 1) runStart = nl
      else { flush(); runStart = nl; runEnd = nl }
    }
  }
  if (pendingDelAnchor > 0) emitDelAnchor(pendingDelAnchor)
  flush()
  // 按 new_start 排序以保证发射顺序稳定
  hunks.sort((p, q) => p.new_start - q.new_start)
  return hunks
}

async function readBlobText(sha: string, filepath: string): Promise<string | null> {
  try {
    const { blob } = await git.readBlob({ fs: gitFs, dir: GIT_DIR, oid: sha, filepath })
    // blob 是 Uint8Array；用 TextDecoder，二进制文件会解出乱码但长度估计还能用——
    // 这里我们先不显式检测 binary，由上层按扩展名过滤（C/H/CPP 都是文本）
    return new TextDecoder('utf-8', { fatal: false }).decode(blob)
  } catch {
    return null
  }
}

export async function computeDiff(baselineRef: string): Promise<GitDiffResult> {
  const { TREE } = git
  const baselineSha = await resolveToCommitSha(baselineRef)
  const head = await getHead()

  const changedFiles: string[] = []
  const addedFiles: string[] = []
  const deletedFiles: string[] = []

  await git.walk({
    fs: gitFs, dir: GIT_DIR,
    trees: [TREE({ ref: baselineSha }), TREE({ ref: head.sha })],
    map: async (filepath: string, entries: any[] | null) => {
      if (!entries) return
      const [A, B] = entries
      if (filepath === '.' || !filepath) return
      // 跳目录
      const aType = A ? await A.type() : null
      const bType = B ? await B.type() : null
      if (aType === 'tree' || bType === 'tree') return
      const aOid = A ? await A.oid() : null
      const bOid = B ? await B.oid() : null
      if (!aOid && bOid) addedFiles.push(filepath)
      else if (aOid && !bOid) deletedFiles.push(filepath)
      else if (aOid && bOid && aOid !== bOid) changedFiles.push(filepath)
    },
  })

  // 为每个 changed_file 计算 hunks（只对文本扩展名做；其余交后端文件级回落）
  const TEXT_EXT = /\.(c|h|cpp|cc|cxx|hpp|hh|hxx|py|js|ts|tsx|jsx|java|go|rs)$/i
  const fileHunks: Record<string, GitHunk[]> = {}
  for (const path of changedFiles) {
    if (!TEXT_EXT.test(path)) continue
    const [oldText, newText] = await Promise.all([
      readBlobText(baselineSha, path),
      readBlobText(head.sha, path),
    ])
    if (oldText === null || newText === null) continue
    const hunks = computeFileHunks(oldText, newText)
    // null = 文件太大，不提交 hunks → 后端文件级回落
    // []   = 内容一致（CRLF 等噪音），提交空数组让后端把文件内所有函数标 unchanged
    if (hunks !== null) fileHunks[path] = hunks
  }

  return {
    baselineCommit: baselineSha,
    baselineBranch: baselineRef,
    headCommit: head.sha,
    headBranch: head.branch,
    changedFiles,
    addedFiles,
    deletedFiles,
    fileHunks,
  }
}
