# 版本管理规范

## 版本号格式

```
X.Y.Z
│ │ └── 修订号 (Patch): Bug 修复，+1
│ └──── 次版本号 (Minor): 新增需求/功能发布，+1
└────── 主版本号 (Major): 架构升级/里程碑版本
```

## 版本号规则

| 变更类型 | 版本号变化 | 示例 |
|---|---|---|
| 修复 Bug | Z + 1 | 1.0.0 → 1.0.1 → 1.0.2 |
| 新增功能/需求 | Y + 1, Z 归零 | 1.0.2 → 1.1.0 |
| 架构升级 (AI 引入等) | X + 1, Y.Z 归零 | 1.x.x → 2.0.0 |

## 版本演进（实际）

```
V1.0.0  初始发布（规则引擎版）                  — 2026-08-13
V1.1.0  新增: PTY 交互式 nvsipl 执行            — 2026-08-17
V1.2.0  新增: 跳板机模式 + 配置持久化            — 2026-08-23
V2.0.0  新增: Web UI 前端 + 文件推送             — 2026-08-28
V2.1.0  新增: 摄像头旋转配置                     — 2026-08-30
V2.2.0  新增: 多拍照命名 + 持久化 Shell          — 2026-08-31
──── Phase 2: AI 辅助判定版 ────
  AI Service 框架 + Provider 抽象
  AI 结果判定（三种模式）
  AI 失败分析（根因/证据/建议）
  AI 报告生成
  中智网关适配
V3.0.0  架构升级: 多会话隔离                     — 2026-09-01
V3.1.0  新增: 故障测试交错执行                   — 2026-09-02
V3.2.0  改进: 前端 UI 重构（Jira 风格）          — 2026-09-01
V3.3.0  新增: 执行历史 + 报告管理                — 2026-09-02
──── Phase 3: 全智能版 ────
V3.4.0  修复: 跳板机 SSH sshpass 回退 + 轮询修复 — 2026-09-05
V3.5.0  新增: AI 步骤智能识别 + 自动解析开关     — 2026-09-07
```

## 分支策略

### 实际使用的分支

```
master (主分支 — V1 规则引擎基线 + hotfix)
  │
  ├── phase2-dev (V2 开发分支 — AI 辅助判定版)
  │     ├─ AI Service + Provider 抽象
  │     ├─ AI 判定/分析/报告
  │     ├─ 前端 UI 重构
  │     └─ cherry-pick hotfix 从 phase3-dev
  │
  └── phase3-dev (V3 开发分支 — 全智能版)
        ├─ 基于 phase2-dev 创建
        ├─ 多会话隔离 + 故障交错执行
        ├─ AI 步骤智能识别
        └─ 当前主开发分支
```

### 分支间同步

- `phase3-dev` 是当前主开发分支，所有新功能在此开发
- 通用修复（SSH、轮询等）通过 `git cherry-pick` 同步到 `phase2-dev`
- `master` 保持 V1 稳定基线，接收关键 hotfix
- 开发完成后：`phase3-dev` → 合并回 `master`，打 tag

## Git 操作规范

### Commit 前缀

| 前缀 | 用途 | 版本影响 |
|---|---|---|
| `fix:` | Bug 修复 | patch +1 |
| `feat:` | 新功能/需求 | minor +1 |
| `perf:` | 性能优化 | patch +1 |
| `docs:` | 文档更新 | 不影响版本 |
| `refactor:` | 重构（不影响功能） | 不影响版本 |
| `style:` | 代码格式 | 不影响版本 |
| `chore:` | 构建/配置/依赖 | 不影响版本 |

### 日常工作流

```bash
# 在 phase3-dev 上开发
git checkout phase3-dev

# 修复 Bug
git add -A
git commit -m "fix: 修复XXX问题"

# 新增功能
git add -A
git commit -m "feat: 新增XXX功能"

# 同步修复到 phase2-dev
git checkout phase2-dev
git cherry-pick <commit-hash>
git checkout phase3-dev
```

### 版本发布工作流

```bash
# Phase 3 开发完成，合并回 master
git checkout master
git merge phase3-dev --no-ff -m "V3.5.0 - AI 全智能版"
git tag -a v3.5.0 -m "V3.5.0 - AI 全智能版"
git push origin master --tags
```

### 推送到 GitHub

```bash
# 推送所有分支
git push origin master
git push origin phase2-dev
git push origin phase3-dev

# 推送所有 tag
git push origin --tags
```

### 查看版本历史

```bash
git log --oneline --graph --all --decorate
git tag -l                    # 列出所有版本标签
git show v1.0.0              # 查看某版本详情
git diff v1.0.0..v3.5.0     # 对比两个版本差异
```
