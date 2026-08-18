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

## 示例版本演进

```
V1.0.0  初始发布（规则引擎版）
V1.0.1  修复: Unicode 弯引号匹配
V1.0.2  修复: PTY channel 超时处理
V1.1.0  新增: 执行前自动清理残留进程
V1.1.1  修复: 清理逻辑对跳板机模式的兼容
V1.2.0  新增: DEBUG 日志开关配置
V1.3.0  新增: 用例批量选择优化
...
V2.0.0  AI 辅助判定版（重大升级）
V2.0.1  修复: AI 分析超时处理
V2.1.0  新增: AI 报告导出 PDF
...
V3.0.0  全智能版（重大升级）
```

## 分支策略

```
master (主分支)
  │
  ├── 日常 bugfix 和小需求直接在 master 提交
  │   commit: "fix: ..."   → patch +1
  │   commit: "feat: ..."  → minor +1
  │
  ├── dev/v2.0.0 (V2 开发分支，独立开发不影响主分支)
  │   │── AI 结果判定
  │   │── AI 失败分析
  │   │── AI 报告生成
  │   └── 开发完成后合并回 master，打 v2.0.0 tag
  │
  └── dev/v3.0.0 (V3 开发分支，远期)
      └── AI 步骤解析 / 全智能
```

## Git 操作规范

### Commit 前缀

| 前缀 | 用途 | 版本影响 |
|---|---|---|
| `fix:` | Bug 修复 | patch +1 |
| `feat:` | 新功能/需求 | minor +1 |
| `docs:` | 文档更新 | 不影响版本 |
| `refactor:` | 重构（不影响功能） | 不影响版本 |
| `style:` | 代码格式 | 不影响版本 |
| `chore:` | 构建/配置/依赖 | 不影响版本 |

### 日常工作流

```bash
# 修复 Bug
git add -A
git commit -m "fix: 修复XXX问题"
# 更新 VERSION 文件: 1.0.0 → 1.0.1
git tag -a v1.0.1 -m "fix: 修复XXX问题"

# 新增功能
git add -A
git commit -m "feat: 新增XXX功能"
# 更新 VERSION 文件: 1.0.1 → 1.1.0
git tag -a v1.1.0 -m "feat: 新增XXX功能"
```

### V2 开发工作流

```bash
# 切到 V2 分支开发
git checkout dev/v2.0.0

# 开发 AI 功能...
git commit -m "feat: AI 失败分析服务"
git commit -m "feat: AI 结果判定级联逻辑"
git commit -m "feat: 前端 AI 分析卡片"

# V2 开发完成，合并回 master
git checkout master
git merge dev/v2.0.0 --no-ff -m "V2.0.0 - AI 辅助判定版"
# 更新 VERSION: 2.0.0
git tag -a v2.0.0 -m "V2.0.0 - AI 辅助判定版"
```

### 查看版本历史

```bash
git log --oneline --graph --all --decorate
git tag -l                    # 列出所有版本标签
git show v1.0.0              # 查看某版本详情
git diff v1.0.0..v1.1.0     # 对比两个版本差异
```
