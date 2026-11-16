/**
 * 推送 G R2：浏览器端"选一次目录，做两件事"。
 *
 * ## 两条数据流
 *
 * A. 源码直传 → 后端 engineering_src/（代码扫描/AI 用）
 *    - 走 showDirectoryPicker 遍历工程目录
 *    - 过滤出源码文件（.h/.c/.cpp/CMakeLists 等）
 *    - 分片 POST 到 /swe3/engineering/tree/chunk
 *    - 用户本机零安装，替代 zip 上传
 *
 * B. git 自动 diff → 后端 baseline_diff（打 diff_status 用）
 *    - 把 .git/ 镜像到 LightningFS
 *    - 让用户选 baseline 分支
 *    - 跑 isomorphic-git walk 产出文件级 diff
 *    - PUT 到 /swe3/baseline + 触发 reclassify
 *
 * 两件事共用同一个 showDirectoryPicker —— 用户只授权一次就能都做。
 *
 * ## 浏览器要求
 *
 * Chrome 86+ / Edge 86+，且必须 secure context（https:// 或 http://localhost）。
 * 其他情况整个面板展示降级提示，让用户用上方的 zip 上传 + 手动 Modal。
 */
import { useState } from 'react'
import {
  Card, Button, Space, Alert, Progress, Select, message, Typography, Tag, List,
  Steps, Divider, Input,
} from 'antd'
import {
  FolderOpenOutlined, BranchesOutlined, ThunderboltOutlined, CheckOutlined,
  CloudUploadOutlined,
} from '@ant-design/icons'
import {
  mirrorGitFromRoot, mirrorGitFromRepoLayout, listBranches, computeDiff,
  type GitBranch, type GitDiffResult,
} from './gitDiff'
import {
  pickWorkspace, traverseDirectory, planBatches, runConcurrent,
  detectRepoWorkspace, resolveSubHandle,
  type FileEntry,
} from './treeUpload'
import {
  putBaseline, reclassifyAll,
  engineeringTreeStart, engineeringTreeChunk, engineeringTreeFinish, engineeringTreeAbort,
} from '../../../api/aspiceApi'
import { useAspiceStore } from '../../../stores/useAspiceStore'

const { Text, Paragraph } = Typography

interface Props {
  projectId: string
  onDone: () => void   // 成功后让父组件 loadAll()
}

export function isFileSystemAccessSupported(): boolean {
  // @ts-ignore
  return typeof window !== 'undefined' && typeof window.showDirectoryPicker === 'function'
}

/** 返回 null = 支持；否则是"为什么不支持"的中文说明。 */
function diagnoseFSSupport(): string | null {
  if (typeof window === 'undefined') return '非浏览器环境'
  // @ts-ignore
  if (typeof window.showDirectoryPicker !== 'function') {
    const ua = navigator.userAgent
    const isChromium = /Chrome|Edg|OPR/.test(ua) && !/Firefox/.test(ua)
    if (!isChromium) {
      return `当前浏览器（${ua.split(' ').slice(-2).join(' ')}）不支持 File System Access API。请换 Chrome 86+ / Edge 86+。`
    }
    if (!window.isSecureContext) {
      return `Chromium 浏览器探测到了，但当前页面不是 secure context（${window.location.protocol}//${window.location.host}）。`
        + ` showDirectoryPicker 要求 HTTPS 或 localhost/127.0.0.1。`
        + ` 临时方案：Vite 启动时加 VITE_HTTPS=1（自签证书），`
        + ` 或在 chrome://flags/#unsafely-treat-insecure-origin-as-secure 把 ${window.location.origin} 加白名单。`
    }
    return 'Chromium + secure context 都齐了，但 showDirectoryPicker 仍不存在；可能是浏览器扩展拦截或企业策略禁用。'
  }
  return null
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export default function EngineeringScanner({ projectId, onDone }: Props) {
  // 更新 store 的 push_d.engineering，让上方 Collapse 面板立刻从"请先上传"切到正常内容
  const setSwe3Engineering = useAspiceStore((s) => s.setSwe3Engineering)
  // 共用的 workspace handle 和名字
  // rootHandle: 用户点"选目录"拿到的最顶层 handle（可能是单工程根，也可能是 git-repo 工作区根）
  // effectiveHandle: 实际做遍历/git 的 handle；非 repo 布局下 = rootHandle；repo 布局下 = resolveSubHandle(root, subPath)
  const [rootHandle, setRootHandle] = useState<any>(null)
  const [effectiveHandle, setEffectiveHandle] = useState<any>(null)
  const [workspaceName, setWorkspaceName] = useState<string>('')

  // git-repo 布局状态
  const [isRepoWorkspace, setIsRepoWorkspace] = useState<boolean>(false)
  const [subProjectPath, setSubProjectPath] = useState<string>('')
  const [subProjectConfirmed, setSubProjectConfirmed] = useState<boolean>(false)

  // 【独立的 git 根】用户如果第 1 步选错了层级（没包含 .repo/），
  // 可以在"分析 git"面板里单独再选一次目录；源码上传不受影响。
  const [gitRootHandle, setGitRootHandle] = useState<any>(null)
  const [gitRootName, setGitRootName] = useState<string>('')
  const [gitRootIsRepo, setGitRootIsRepo] = useState<boolean>(false)
  const [gitSubPath, setGitSubPath] = useState<string>('')  // repo 布局下的子工程路径，可与上面 subProjectPath 相同

  // === A. 源码直传状态 ===
  const [traversing, setTraversing] = useState(false)
  const [traverseStats, setTraverseStats] = useState<{ scanned: number; found: number; skipped: number; dir?: string } | null>(null)
  const [fileList, setFileList] = useState<FileEntry[]>([])
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<{ sent: number; total: number; bytes: number; totalBytes: number; path?: string } | null>(null)
  const [uploadDone, setUploadDone] = useState(false)

  // === B. git diff 状态 ===
  const [mirrorProgress, setMirrorProgress] = useState<{ cur: number; total: number; path: string } | null>(null)
  const [mirroring, setMirroring] = useState(false)
  const [mirrored, setMirrored] = useState(false)
  const [branches, setBranches] = useState<GitBranch[]>([])
  const [baselineRef, setBaselineRef] = useState<string>('')
  const [loadingBranches, setLoadingBranches] = useState(false)
  const [diffing, setDiffing] = useState(false)
  const [diffResult, setDiffResult] = useState<GitDiffResult | null>(null)
  const [publishing, setPublishing] = useState(false)

  const resetAll = () => {
    setFileList([])
    setUploadDone(false)
    setUploadProgress(null)
    setTraverseStats(null)
    setMirrored(false)
    setMirrorProgress(null)
    setBranches([])
    setBaselineRef('')
    setDiffResult(null)
    setEffectiveHandle(null)
    setIsRepoWorkspace(false)
    setSubProjectPath('')
    setSubProjectConfirmed(false)
  }

  // 公用：对 effectiveHandle 遍历源码
  const traverseEffective = async (handle: any) => {
    setTraversing(true)
    setTraverseStats({ scanned: 0, found: 0, skipped: 0, dir: '' })
    try {
      const files = await traverseDirectory(handle, (p) => {
        setTraverseStats({
          scanned: p.scanned, found: p.found, skipped: p.skipped, dir: p.currentDir,
        })
      })
      setFileList(files)
      message.success(`扫描完成：发现 ${files.length} 个源码文件`)
    } finally {
      setTraversing(false)
    }
  }

  // === 步骤 1：选目录（一次性） ===
  const handlePick = async () => {
    resetAll()
    try {
      const { rootHandle: h, name } = await pickWorkspace()
      setRootHandle(h)
      setWorkspaceName(name)

      // 检测是不是 git-repo 工作区（根下有 .repo/）
      const isRepo = await detectRepoWorkspace(h)
      if (isRepo) {
        setIsRepoWorkspace(true)
        message.info('检测到 git-repo 工作区（有 .repo/），请在下方填子工程相对路径')
        // 不立刻遍历，等用户填 subProjectPath 并确认
      } else {
        setIsRepoWorkspace(false)
        setEffectiveHandle(h)
        setSubProjectConfirmed(true) // 单工程直接就位
        await traverseEffective(h)
      }
    } catch (e: any) {
      if (e?.name === 'AbortError') {
        message.info('已取消目录选择')
      } else {
        message.error('选择失败：' + (e?.message || e))
      }
    }
  }

  // repo 布局：用户填完 subProjectPath 后点"确认子工程"
  const handleConfirmSubProject = async () => {
    if (!rootHandle) return
    const rel = subProjectPath.trim()
    if (!rel) { message.warning('请填子工程相对路径'); return }
    try {
      const sub = await resolveSubHandle(rootHandle, rel)
      setEffectiveHandle(sub)
      setSubProjectConfirmed(true)
      setWorkspaceName(`${rootHandle.name} / ${rel}`)
      await traverseEffective(sub)
    } catch (e: any) {
      message.error(String(e?.message || e))
      setEffectiveHandle(null)
      setSubProjectConfirmed(false)
    }
  }

  // === 步骤 2a：上传源码树 ===
  const handleUploadSource = async () => {
    if (!projectId || !fileList.length) return
    setUploading(true)
    setUploadDone(false)
    const totalBytes = fileList.reduce((s, f) => s + f.size, 0)
    setUploadProgress({ sent: 0, total: fileList.length, bytes: 0, totalBytes })
    try {
      await engineeringTreeStart(projectId)
      const batches = planBatches(fileList)
      let sentFiles = 0
      let sentBytes = 0
      await runConcurrent(batches, async (batch) => {
        // 并行读取 batch 中的 File
        const payload = await Promise.all(batch.map(async (f) => ({
          data: await f.handle.getFile() as Blob,
          path: f.path,
        })))
        await engineeringTreeChunk(projectId, payload)
        sentFiles += batch.length
        sentBytes += batch.reduce((s, f) => s + f.size, 0)
        setUploadProgress({
          sent: sentFiles, total: fileList.length,
          bytes: sentBytes, totalBytes,
          path: batch[batch.length - 1]?.path,
        })
      }, 3)
      const finishRes = await engineeringTreeFinish(projectId, workspaceName)
      // 关键：把 engineering meta 同步到 store，否则下方 Collapse 还认为"没传过"
      setSwe3Engineering(finishRes.data)
      setUploadDone(true)
      message.success(`源码直传完成：${fileList.length} 文件 ${fmtBytes(totalBytes)}`)
      onDone()
    } catch (e: any) {
      message.error('上传失败：' + (e?.response?.data?.detail || e?.message || e))
      try { await engineeringTreeAbort(projectId) } catch { /* ignore */ }
    } finally {
      setUploading(false)
    }
  }

  // === 独立为 git 选根（当第一次选的目录不含 .repo/ 时用） ===
  const handlePickGitRoot = async () => {
    try {
      const { rootHandle: h, name } = await pickWorkspace()
      setGitRootHandle(h)
      setGitRootName(name)
      // 探测
      const isRepo = await detectRepoWorkspace(h)
      setGitRootIsRepo(isRepo)

      // 额外探：也看看有没有裸 .git（表明用户选对了单工程根）
      let hasBareGit = false
      try { await h.getDirectoryHandle('.git'); hasBareGit = true } catch { /* 无 .git */ }

      if (isRepo) {
        // 若用户在上面已经填过子工程路径，默认复用
        if (subProjectPath && !gitSubPath) setGitSubPath(subProjectPath)
        message.success(`✓ 检测到 .repo/，是 git-repo 工作区根（${name}）`)
      } else if (hasBareGit) {
        setGitSubPath('')
        message.success(`✓ 检测到 .git/，直接读 ${name}/.git`)
      } else {
        // 两个都没找到 —— 这是用户选错层级了
        message.warning(`⚠️ "${name}" 里既没有 .git/ 也没有 .repo/，可能选错层级了`)
      }
      // 清掉之前的 git 阶段状态（但保留源码上传成果）
      setMirrored(false)
      setBranches([])
      setBaselineRef('')
      setDiffResult(null)
    } catch (e: any) {
      if (e?.name === 'AbortError') {
        message.info('已取消目录选择')
      } else {
        message.error('选择失败：' + (e?.message || e))
      }
    }
  }

  // === 步骤 2b：镜像 .git 并列分支 ===
  const handleMirrorGit = async () => {
    // 优先用独立选的 git 根；否则回落到源码那次选的 rootHandle
    const useIndependentGitRoot = !!gitRootHandle
    const usingHandle = useIndependentGitRoot ? gitRootHandle : rootHandle
    const usingIsRepo = useIndependentGitRoot ? gitRootIsRepo : isRepoWorkspace
    const usingSub = useIndependentGitRoot ? gitSubPath.trim() : subProjectPath.trim()

    if (!usingHandle) {
      message.warning('请先选目录（上方"选择工程目录"或下方"为 git 单独选根"）')
      return
    }

    setMirroring(true)
    setMirrored(false)
    setBranches([])
    setBaselineRef('')
    setDiffResult(null)
    setMirrorProgress({ cur: 0, total: 0, path: '开始镜像 .git…' })
    try {
      let totalFiles = 0
      let realGitPath: string | undefined
      if (usingIsRepo) {
        if (!usingSub) throw new Error('git-repo 布局：请填子工程相对路径')
        const r = await mirrorGitFromRepoLayout(usingHandle, usingSub, (p) => {
          setMirrorProgress({ cur: p.current, total: p.total, path: p.path || '' })
        })
        totalFiles = r.totalFiles
        realGitPath = r.realGitPath
      } else {
        const r = await mirrorGitFromRoot(usingHandle, (p) => {
          setMirrorProgress({ cur: p.current, total: p.total, path: p.path || '' })
        })
        totalFiles = r.totalFiles
      }
      setMirrored(true)
      message.success(`.git 镜像完成：${totalFiles} 文件` + (realGitPath ? `（${realGitPath}）` : ''))
      setLoadingBranches(true)
      try {
        const list = await listBranches()
        setBranches(list)
        const prefer = list.find((b) => b.kind === 'branch' && /^(main|master)$/.test(b.name))
          || list.find((b) => b.kind === 'tag')
          || list[0]
        if (prefer) setBaselineRef(prefer.name)
      } finally {
        setLoadingBranches(false)
      }
    } catch (e: any) {
      message.error('镜像失败：' + (e?.message || e))
    } finally {
      setMirroring(false)
    }
  }

  const handleDiff = async () => {
    if (!baselineRef) { message.warning('请先选 baseline'); return }
    setDiffing(true)
    try {
      const r = await computeDiff(baselineRef)
      setDiffResult(r)
      message.success(
        `diff 完成：新增 ${r.addedFiles.length} / 改动 ${r.changedFiles.length} / 删除 ${r.deletedFiles.length}`,
      )
    } catch (e: any) {
      message.error('diff 失败：' + (e?.message || e))
    } finally {
      setDiffing(false)
    }
  }

  const handlePublish = async () => {
    if (!diffResult) return
    setPublishing(true)
    try {
      await putBaseline(projectId, {
        baseline_commit: diffResult.baselineCommit,
        baseline_branch: diffResult.baselineBranch,
        head_commit: diffResult.headCommit,
        head_branch: diffResult.headBranch,
        changed_files: diffResult.changedFiles,
        added_files: diffResult.addedFiles,
        file_hunks: diffResult.fileHunks,   // 推送 G 粒度升级：函数级 diff 的关键输入
      })
      await reclassifyAll(projectId)
      message.success('baseline 已发布，所有模块函数已重新分类')
      onDone()
    } catch (e: any) {
      message.error('发布失败：' + (e?.message || e))
    } finally {
      setPublishing(false)
    }
  }

  // ===== 不支持 FS API 时的降级提示 =====
  if (!isFileSystemAccessSupported()) {
    const reason = diagnoseFSSupport()
    return (
      <Card size="small" title={<Space><ThunderboltOutlined />自动化工程接入</Space>}>
        <Alert type="warning" showIcon
          message="当前环境无法使用 File System Access API"
          description={
            <div>
              <Paragraph style={{ marginBottom: 8 }}>{reason}</Paragraph>
              <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                请用上方「上传工程 zip」+「手动设置 baseline」作为降级方案。
              </Paragraph>
            </div>
          } />
      </Card>
    )
  }

  const currentStep = !rootHandle ? 0
    : !uploadDone ? 1
    : !mirrored ? 2
    : !diffResult ? 3
    : 4

  return (
    <Card size="small"
      title={<Space><ThunderboltOutlined />自动化工程接入（选一次目录完成源码直传 + git diff）</Space>}
    >
      <Paragraph type="secondary" style={{ marginBottom: 12 }}>
        用户本机零安装：只需 Chrome 86+ / Edge 86+。选目录后，浏览器内完成源码过滤、.git 分析，
        <Text strong>源码不打 zip、不走 SSH</Text>，直接分片 POST 到后端。
      </Paragraph>

      <Steps size="small" current={currentStep} style={{ marginBottom: 16 }}
        items={[
          { title: '选目录' },
          { title: '源码直传' },
          { title: '镜像 .git' },
          { title: '选 baseline / diff' },
          { title: '完成' },
        ]}
      />

      {!projectId && (
        <Alert type="warning" showIcon style={{ marginBottom: 12 }}
          message="projectId 为空：按钮已禁用。请先创建或打开项目。" />
      )}

      {/* ===== 步骤 1：选目录 ===== */}
      <div style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }} size={8}>
          <Space wrap>
            <Button icon={<FolderOpenOutlined />} type="primary"
              disabled={!projectId || traversing || uploading || mirroring}
              loading={traversing && !isRepoWorkspace}
              onClick={handlePick}>
              1. 选择工程目录（含 .git 或 .repo/）
            </Button>
            {workspaceName && (
              <Tag icon={<CheckOutlined />} color="green">
                已选：{workspaceName}
              </Tag>
            )}
            {traverseStats && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                扫描 {traverseStats.scanned} / 收 {traverseStats.found} / 忽略 {traverseStats.skipped}
                {traverseStats.dir && ` — ${traverseStats.dir.slice(-50)}`}
              </Text>
            )}
          </Space>

          {/* git-repo 布局：子工程相对路径输入 */}
          {isRepoWorkspace && !subProjectConfirmed && (
            <Alert
              type="info" showIcon
              message="检测到 git-repo 工作区（根下有 .repo/）"
              description={
                <Space direction="vertical" size={6} style={{ width: '100%' }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    git-repo 工程的 <code>.git</code> 是 symlink 指向 <code>.repo/projects/*.git</code>，
                    Chrome 不跟随 symlink。请填要 diff 的子工程相对路径（相对你刚才选的根）：
                  </Text>
                  <Space.Compact style={{ width: '100%' }}>
                    <Input
                      placeholder="例如：nvidia/Qnx_Standard_7.2.4.0/drive-qnx/samples/nvmedia"
                      value={subProjectPath}
                      onChange={(e) => setSubProjectPath(e.target.value)}
                      onPressEnter={handleConfirmSubProject}
                    />
                    <Button type="primary" loading={traversing} onClick={handleConfirmSubProject}>
                      确认子工程
                    </Button>
                  </Space.Compact>
                </Space>
              }
            />
          )}
          {isRepoWorkspace && subProjectConfirmed && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              📂 子工程：<Text code>{subProjectPath.trim()}</Text>
              &nbsp;（.git 将从 <Text code>.repo/projects/{subProjectPath.trim()}.git</Text> 读取）
            </Text>
          )}
        </Space>
      </div>

      {effectiveHandle && subProjectConfirmed && !traversing && (
        <>
          <Divider style={{ margin: '12px 0' }} />

          {/* ===== 步骤 2a：源码直传 ===== */}
          <div style={{ marginBottom: 16 }}>
            <Space direction="vertical" style={{ width: '100%' }} size={8}>
              <Space wrap>
                <CloudUploadOutlined />
                <Text strong>2. 上传源码到后端（{fileList.length} 文件
                  {fmtBytes(fileList.reduce((s, f) => s + f.size, 0))}）：</Text>
              </Space>
              <Space>
                <Button icon={<CloudUploadOutlined />} type={uploadDone ? 'default' : 'primary'}
                  loading={uploading} disabled={!fileList.length || uploading}
                  onClick={handleUploadSource}>
                  {uploadDone ? '重新上传' : '开始上传'}
                </Button>
                {uploadDone && <Tag icon={<CheckOutlined />} color="green">上传完成</Tag>}
              </Space>
              {uploadProgress && (
                <div>
                  <Progress
                    percent={uploadProgress.total > 0
                      ? Math.round(uploadProgress.sent / uploadProgress.total * 100)
                      : 0}
                    size="small"
                    status={uploadDone ? 'success' : uploading ? 'active' : 'normal'} />
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {uploadProgress.sent} / {uploadProgress.total} 文件
                    &nbsp;·&nbsp;
                    {fmtBytes(uploadProgress.bytes)} / {fmtBytes(uploadProgress.totalBytes)}
                    {uploadProgress.path && ` — ${uploadProgress.path.slice(-50)}`}
                  </Text>
                </div>
              )}
            </Space>
          </div>

          <Divider style={{ margin: '12px 0' }} />

          {/* ===== 步骤 2b：镜像 .git ===== */}
          <div style={{ marginBottom: 16 }}>
            <Space direction="vertical" style={{ width: '100%' }} size={8}>
              <Space wrap>
                <BranchesOutlined />
                <Text strong>3. 分析 git（可选，若做"改动函数四态分类"必需）：</Text>
              </Space>

              {/* 当前 git 根状态提示 */}
              {gitRootHandle && !gitRootIsRepo && !mirrored && (
                <Alert
                  type="warning" showIcon
                  message={`git 根（独立）：${gitRootName}（无 .repo/，将按普通 git 工程读 ${gitRootName}/.git）`}
                  description={
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      💡 如果该目录的 <code>.git</code> 其实是 symlink（git-repo 布局），镜像会失败。
                      点"为 git 单独选根（重选）"换成含 <code>.repo/</code> 的根目录。
                    </Text>
                  }
                />
              )}
              {gitRootHandle && gitRootIsRepo && (
                <Alert
                  type="success" showIcon
                  message={`git 根（独立）：${gitRootName}（✓ 检测到 .repo/，走 git-repo 布局）`}
                />
              )}
              {!gitRootHandle && (
                <Alert
                  type="info" showIcon
                  message={
                    isRepoWorkspace && subProjectConfirmed
                      ? `复用上方工作区：${rootHandle?.name}（含 .repo/，子工程 ${subProjectPath}）`
                      : rootHandle
                        ? `复用上方目录：${rootHandle.name}（将直接读 ${rootHandle.name}/.git）`
                        : '尚未选任何目录'
                  }
                  description={
                    !isRepoWorkspace && rootHandle && (
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        💡 如果 <code>{rootHandle.name}</code> 里的 <code>.git</code> 是 symlink（git-repo 布局），
                        上方会直接读失败。此时点下方"为 git 单独选根"重选到含 <code>.repo/</code> 的工作区根，
                        源码上传不会丢。
                      </Text>
                    )
                  }
                />
              )}
              <Space wrap>
                <Button icon={<FolderOpenOutlined />} onClick={handlePickGitRoot} disabled={mirroring}>
                  为 git 单独选根{gitRootHandle ? '（重选）' : ''}
                </Button>
              </Space>

              {/* 若 git 根是 repo 布局，再提供一个子工程输入框 */}
              {gitRootHandle && gitRootIsRepo && (
                <Space.Compact style={{ width: '100%' }}>
                  <Input
                    placeholder="子工程相对路径（例如：nvidia/Qnx_Standard_7.2.4.0/drive-qnx/samples/nvmedia）"
                    value={gitSubPath}
                    onChange={(e) => setGitSubPath(e.target.value)}
                    disabled={mirroring}
                  />
                </Space.Compact>
              )}

              <Space>
                <Button icon={<BranchesOutlined />} loading={mirroring} type="primary"
                  disabled={
                    mirroring ||
                    (!gitRootHandle && !rootHandle) ||
                    // 若要走 repo 分支，必须有 sub 路径
                    (gitRootHandle ? (gitRootIsRepo && !gitSubPath.trim()) :
                      (isRepoWorkspace && !subProjectConfirmed))
                  }
                  onClick={handleMirrorGit}>
                  {mirrored ? '重新镜像 .git' : '镜像 .git 并列分支'}
                </Button>
                {mirrored && <Tag icon={<CheckOutlined />} color="green">.git 镜像完成</Tag>}
              </Space>
              {mirrorProgress && mirroring && (
                <div>
                  <Progress
                    percent={mirrorProgress.total > 0
                      ? Math.round(mirrorProgress.cur / mirrorProgress.total * 100)
                      : 0}
                    size="small" status="active" />
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {mirrorProgress.cur} / {mirrorProgress.total}
                    {mirrorProgress.path && ` — ${mirrorProgress.path.slice(-60)}`}
                  </Text>
                </div>
              )}
            </Space>
          </div>

          {/* ===== 步骤 3：选 baseline + diff ===== */}
          {mirrored && (
            <div style={{ marginBottom: 16 }}>
              <Space direction="vertical" style={{ width: '100%' }} size={8}>
                <Text strong>4. 选 baseline 并算 diff：</Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  可从分支/tag 下拉选，也可直接贴一个 commit sha（≥7 位，支持短 sha）。
                  diff = baseline..HEAD，即从 baseline 到当前 HEAD 之间的文件改动。
                </Text>
                <Select
                  style={{ width: '100%' }} showSearch placeholder="选择分支 / tag / remote"
                  loading={loadingBranches}
                  value={baselineRef || undefined}
                  onChange={setBaselineRef}
                  options={branches.map((b) => ({
                    value: b.name,
                    label: (
                      <Space>
                        <Tag color={b.kind === 'branch' ? 'blue' : b.kind === 'tag' ? 'green' : 'default'}>
                          {b.kind}
                        </Tag>
                        <Text>{b.name}</Text>
                        <Text type="secondary" style={{ fontSize: 11 }} code>
                          {b.sha.slice(0, 7)}
                        </Text>
                      </Space>
                    ),
                  }))}
                />
                <Input
                  placeholder="或直接粘贴 commit sha（如 36546b3 或完整 40 位）"
                  value={baselineRef}
                  onChange={(e) => setBaselineRef(e.target.value)}
                  allowClear
                />
                <Button icon={<ThunderboltOutlined />} loading={diffing}
                  disabled={!baselineRef} onClick={handleDiff}>
                  运行 diff (baseline..HEAD)
                </Button>
              </Space>
            </div>
          )}

          {diffResult && (
            <Card size="small" title="Diff 结果预览" style={{ marginBottom: 12 }}
              extra={
                <Button type="primary" icon={<CheckOutlined />} loading={publishing}
                  onClick={handlePublish}>
                  5. 发布 baseline + 重新分类
                </Button>
              }
            >
              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                <Text>
                  <Text strong>Baseline：</Text>
                  <Text code>{diffResult.baselineBranch}</Text>
                  <Text type="secondary"> ({diffResult.baselineCommit.slice(0, 10)})</Text>
                </Text>
                <Text>
                  <Text strong>HEAD：</Text>
                  <Text code>{diffResult.headBranch || '(detached)'}</Text>
                  <Text type="secondary"> ({diffResult.headCommit.slice(0, 10)})</Text>
                </Text>
                <Space wrap>
                  <Tag color="green">新增 {diffResult.addedFiles.length}</Tag>
                  <Tag color="orange">改动 {diffResult.changedFiles.length}</Tag>
                  <Tag color="red">删除 {diffResult.deletedFiles.length}</Tag>
                </Space>
                {(diffResult.addedFiles.length + diffResult.changedFiles.length) > 0 && (
                  <List
                    size="small" bordered
                    style={{ maxHeight: 200, overflowY: 'auto', marginTop: 8 }}
                    dataSource={[
                      ...diffResult.addedFiles.map((f) => ({ kind: 'added', path: f })),
                      ...diffResult.changedFiles.map((f) => ({ kind: 'modified', path: f })),
                    ]}
                    renderItem={(item: any) => (
                      <List.Item style={{ padding: '4px 8px' }}>
                        <Tag color={item.kind === 'added' ? 'green' : 'orange'}
                          style={{ minWidth: 60, textAlign: 'center' }}>
                          {item.kind === 'added' ? '新增' : '改动'}
                        </Tag>
                        <Text style={{ fontSize: 12 }} code>{item.path}</Text>
                      </List.Item>
                    )}
                  />
                )}
              </Space>
            </Card>
          )}
        </>
      )}
    </Card>
  )
}
