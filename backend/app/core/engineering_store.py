"""SWE.3 推送 D — 工程代码上传 / 解压 / 查询。

- 存储布局：runtime/creator_projects/<id>/swe3/
    engineering_src/                  解压后的 zip 内容
    engineering_meta.json             解压后的概要（文件数/SDK数/样例）
    scan_cache/<component_id>.json    单模块扫描结果（code_scanner.py 落盘）

- 复用 zip_utils：stream_save（流式落盘）+ safe_extractall（跳 .git/build 等，防越界）
- SDK 识别：路径中出现 "nvsipl"/"nvmedia"/"drive-os"/"drive_os" 任一关键字即视为 SDK
"""
from __future__ import annotations

import json
import os
import shutil
import fnmatch
from datetime import datetime
from typing import Iterable, Optional

from app.core import zip_utils


# SDK 文件识别关键字（任一出现在路径段中就算 SDK）
_SDK_PATH_HINTS = ("nvsipl", "nvmedia", "drive-os", "drive_os", "nvscievent", "nvscibuf")

# 工程代码扫描时忽略的扩展名
_SOURCE_EXTS = {".h", ".hpp", ".hh", ".c", ".cpp", ".cc", ".cxx"}

# 浏览器直传工程树的硬限制（和 zip 保持一致）
MAX_TREE_BYTES = 300 * 1024 * 1024      # 累计落盘 300 MB 上限
MAX_TREE_FILES = 200_000                # 单工程文件数上限（防意外选到 /）
MAX_FILE_BYTES = 50 * 1024 * 1024       # 单文件 50 MB（.h/.cpp 不可能这么大，防异常）

# 和 zip_utils._SKIP_SEGMENTS 对齐：这些目录段落浏览器端应该已过滤，
# 但后端兜底再拒一次（纵深防御）。
_SKIP_SEGMENTS = frozenset({
    ".git", ".hg", ".svn",
    "build", "out", "dist", "cmake-build-debug",
    "node_modules", "third_party", "third-party",
    ".vscode", ".idea", ".cache",
})


class TreeUploadError(Exception):
    """浏览器端直传工程树失败。路由层捕获转 HTTP 400/413。"""


def swe3_dir(project_id: str) -> str:
    return os.path.join("runtime", "creator_projects", project_id, "swe3")


def engineering_root(project_id: str) -> str:
    return os.path.join(swe3_dir(project_id), "engineering_src")


def engineering_meta_path(project_id: str) -> str:
    return os.path.join(swe3_dir(project_id), "engineering_meta.json")


def scan_cache_dir(project_id: str) -> str:
    return os.path.join(swe3_dir(project_id), "scan_cache")


def scan_cache_path(project_id: str, component_id: str) -> str:
    # 组件 ID 仅允许字母数字，兜底过滤非法字符
    safe = "".join(ch for ch in component_id if ch.isalnum() or ch in "_-")
    return os.path.join(scan_cache_dir(project_id), f"{safe}.json")


def _is_sdk_path(rel_path: str) -> bool:
    """A 方案：git 工程内的文件一律视为本地代码。

    历史上这里按子串匹配 ("nvsipl", "nvmedia", "drive-os", ...) 判定 SDK，
    但 driveworks sample 风格的项目源码就位于 nvsipl/ 下，会被整个工程全量误判。
    真正的 NVIDIA SDK 装在系统路径（/usr/local/driveos 之类），不会被用户传上来。
    保留函数本身是为了兼容旧调用点；现在恒返回 False。
    """
    _ = rel_path  # noqa: F841 — 参数保留便于未来复用
    return False


def _walk_source_files(root: str) -> Iterable[str]:
    """遍历 root 下所有源码文件，产生相对 root 的路径（用 '/'）。"""
    for cur, _dirs, files in os.walk(root):
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext not in _SOURCE_EXTS:
                continue
            abs_path = os.path.join(cur, name)
            rel = os.path.relpath(abs_path, root).replace("\\", "/")
            yield rel


def _detect_roots(target_dir: str) -> tuple[Optional[str], list[str]]:
    """探测 include_root / code_roots。

    include_root：首个名字含 "include" 的顶层目录
    code_roots：剩余的顶层目录（排除 include_root）
    """
    include_root: Optional[str] = None
    code_roots: list[str] = []
    try:
        entries = sorted(e for e in os.listdir(target_dir)
                         if os.path.isdir(os.path.join(target_dir, e)))
    except FileNotFoundError:
        return None, []
    for name in entries:
        low = name.lower()
        if include_root is None and "include" in low:
            include_root = name
        else:
            code_roots.append(name)
    return include_root, code_roots


def build_meta(zip_name: str, target_dir: str) -> dict:
    """扫描 target_dir，生成 engineering_meta。"""
    files = list(_walk_source_files(target_dir))
    sdk_files = sum(1 for p in files if _is_sdk_path(p))
    sample = sorted(files)[:50]
    include_root, code_roots = _detect_roots(target_dir)
    return {
        "zip_name": zip_name,
        "uploaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "include_root": include_root,
        "code_roots": code_roots,
        "total_files": len(files),
        "sdk_files": sdk_files,
        "custom_files": len(files) - sdk_files,
        "file_tree_sample": sample,
    }


async def receive_upload(project_id: str, upload_file, *, append: bool = False) -> dict:
    """接收 UploadFile → 流式落盘 → 解压 → 产生 meta。

    - append=False（默认）：先清空 engineering_src/ 再解压，meta 中 zip_name 覆盖
    - append=True：保留原有内容追加解压（同路径覆盖），meta 中 zip_name 记录全部 zip 列表

    返回最新 engineering_meta。
    上传过程中任何异常都已把残留 zip 清理，但解压阶段若失败，engineering_src/ 可能
    已部分落盘；这里兜底把它也清掉，避免下次 glob 匹配到半包。
    """
    sdir = swe3_dir(project_id)
    os.makedirs(sdir, exist_ok=True)

    tmp_zip = os.path.join(sdir, f"__upload_{datetime.now().timestamp():.0f}.zip")
    try:
        await zip_utils.stream_save(upload_file, tmp_zip)
    finally:
        # upload_file.close() 由 fastapi 托管；此处只处理我们这端的临时文件
        pass

    target = engineering_root(project_id)
    prev_meta = read_meta(project_id) if append else None
    if not append:
        # 覆盖模式：清旧目录
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
    os.makedirs(target, exist_ok=True)

    try:
        zip_utils.safe_extractall(tmp_zip, target)
    except Exception:
        # 覆盖模式失败时清半包；追加模式失败时保留原状不动
        if not append:
            shutil.rmtree(target, ignore_errors=True)
        raise
    finally:
        if os.path.isfile(tmp_zip):
            try:
                os.remove(tmp_zip)
            except OSError:
                pass

    zip_name = getattr(upload_file, "filename", None) or "upload.zip"
    meta = build_meta(zip_name, target)
    if append and prev_meta:
        # 保留此前上传的 zip 文件名列表
        prev_names = prev_meta.get("zip_name") or ""
        if isinstance(prev_names, str):
            names = [n.strip() for n in prev_names.split("+") if n.strip()]
        else:
            names = list(prev_names)
        if zip_name not in names:
            names.append(zip_name)
        meta["zip_name"] = " + ".join(names)
    with open(engineering_meta_path(project_id), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta


def read_meta(project_id: str) -> Optional[dict]:
    """读取已有 engineering_meta，无则 None。"""
    mp = engineering_meta_path(project_id)
    if not os.path.isfile(mp):
        return None
    try:
        with open(mp, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def clear_engineering(project_id: str) -> None:
    """清空工程代码（含 engineering_src / meta / scan_cache 全部）。"""
    target = engineering_root(project_id)
    if os.path.isdir(target):
        shutil.rmtree(target, ignore_errors=True)
    mp = engineering_meta_path(project_id)
    if os.path.isfile(mp):
        try:
            os.remove(mp)
        except OSError:
            pass
    sdir = scan_cache_dir(project_id)
    if os.path.isdir(sdir):
        shutil.rmtree(sdir, ignore_errors=True)


def match_files(project_id: str, patterns: list[dict]) -> list[str]:
    """按 glob 规则在 engineering_src 下匹配源码文件。

    patterns: [{ "pattern": "include/foo/**", "exclude": False }, ...]

    支持的写法（任选其一）：
      1) 纯目录名      "src"                        → 匹配工程下任意位置名为 src 的目录子树
      2) 相对子树路径   "nvsipl/devblk/devices/XXX"  → 匹配该相对路径下的所有源文件
      3) 带尾斜杠      "nvsipl/.../XXX/"            → 等价 2（自动剥尾斜杠）
      4) 显式子树通配   "nvsipl/.../XXX/**"          → 等价 2
      5) fnmatch 风格   "**/MAX*.cpp"                → 走标准 fnmatch
    返回命中的相对路径列表（去重排序）。

    **虚根前缀自动剥离**（2026-11-10 加）：
    用户在前端选目录时，根目录名（如 "nvsipl"）会被前端拼进 glob（变成
    "nvsipl/devblk/..."），但后端 engineering_src/ 下第一层其实就是 devblk/。
    为了不逼用户手动改每条规则，我们在匹配时：若 glob 第一段不在工程树的第一
    层目录集合里（但第二段在），自动剥掉第一段再匹配。
    """
    target = engineering_root(project_id)
    if not os.path.isdir(target):
        return []
    all_files = list(_walk_source_files(target))
    includes = [p["pattern"] for p in patterns if not p.get("exclude")]
    excludes = [p["pattern"] for p in patterns if p.get("exclude")]

    # 计算工程树第一层目录名（用于虚根剥离判定）
    try:
        top_dirs = {e for e in os.listdir(target)
                    if os.path.isdir(os.path.join(target, e))}
    except OSError:
        top_dirs = set()

    def _strip_virtual_root(g: str) -> str:
        """若 glob 第一段不是实际顶层目录，但第二段是，则剥掉第一段。"""
        if "/" not in g:
            return g
        head, rest = g.split("/", 1)
        if head in top_dirs:
            return g  # 第一段匹配真实顶层，保持
        if "/" in rest:
            next_head = rest.split("/", 1)[0]
        else:
            next_head = rest
        if next_head in top_dirs:
            return rest  # 剥掉虚根前缀
        return g

    def _normalize(glob: str) -> str:
        """去掉首尾空白与尾斜杠；统一分隔符为 '/'。"""
        g = glob.strip().replace("\\", "/").strip("/")
        # 把 'xxx/**' 的尾 '**' 剥掉，便于与"纯目录"统一处理
        if g.endswith("/**"):
            g = g[:-3]
        return g

    def _has_wildcard(glob: str) -> bool:
        return any(ch in glob for ch in ("*", "?", "["))

    def _match(path: str, glob: str) -> bool:
        g = _normalize(glob)
        if not g:
            return False
        g = _strip_virtual_root(g)
        # 分支 A：无通配符 → 作为"目录子树"处理
        if not _has_wildcard(g):
            # A1：裸目录名（不含 '/'）→ 匹配任意层级下该名字的目录子树
            if "/" not in g:
                parts = path.split("/")
                return g in parts[:-1]   # [:-1] 排除最后的文件名本身
            # A2：相对子树路径 → path 以 g+'/' 开头
            return path.startswith(g + "/") or path == g
        # 分支 B：含通配符 → 走 fnmatch；对 '**' 做补偿替换以近似"任意层级"
        g2 = g.replace("**/", "*/").replace("/**", "/*")
        if fnmatch.fnmatch(path, g2):
            return True
        # 补偿：fnmatch 对多级 '*' 不自然，尝试把 '*' 当作任意层级做一次宽松匹配
        return fnmatch.fnmatch(path, g2.replace("*", "**")) if False else False

    hit: list[str] = []
    for p in all_files:
        if not any(_match(p, g) for g in includes):
            continue
        if any(_match(p, g) for g in excludes):
            continue
        hit.append(p)
    return sorted(set(hit))


def read_scan_cache(project_id: str, component_id: str) -> Optional[dict]:
    sp = scan_cache_path(project_id, component_id)
    if not os.path.isfile(sp):
        return None
    try:
        with open(sp, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def write_scan_cache(project_id: str, component_id: str, data: dict) -> None:
    os.makedirs(scan_cache_dir(project_id), exist_ok=True)
    with open(scan_cache_path(project_id, component_id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def file_is_sdk(rel_path: str) -> bool:
    """供 code_scanner 调用：判断某文件是否属于 SDK（通过路径关键字）。"""
    return _is_sdk_path(rel_path)


# ---- 推送 G：baseline diff ----

def baseline_diff_path(project_id: str) -> str:
    """存储前端 isomorphic-git 预计算的 baseline..HEAD 差异清单。"""
    return os.path.join(swe3_dir(project_id), "baseline_diff.json")


def write_baseline_diff(project_id: str, diff: dict) -> None:
    """落盘 baseline_commit + changed_files + added/modified_functions（可选）。

    结构：
    ```
    {
      "baseline_commit": "abc1234",
      "baseline_branch": "main",
      "head_commit": "def5678",
      "pinned_at": "2026-11-05 ...",
      "changed_files": ["src/foo.cpp", ...],   # 相对工程根
      "added_files":   [...],                   # 新增文件（diff_status=added）
      "deleted_files": [...],                   # 已删除（本次不参与扫描）
      "file_hunks": {                           # 推送 G 粒度升级（2026-11-11）
        "src/foo.cpp": [{"new_start": 120, "new_lines": 5}, ...]
      }
    }
    ```
    函数级 diff 规则（见 code_scanner.classify_functions）：
      - 文件在 added_files → 文件内所有函数标 added
      - 文件在 changed_files 且 file_hunks 该 path 有条目 → 只有函数 [line_start, line_end]
        与任一 hunk 区间相交的函数标 modified，其余标 unchanged（细粒度）
      - 文件在 changed_files 但 file_hunks 未覆盖 → 回落文件级，全部标 modified（向后兼容）
    """
    os.makedirs(swe3_dir(project_id), exist_ok=True)
    with open(baseline_diff_path(project_id), "w", encoding="utf-8") as f:
        json.dump(diff, f, ensure_ascii=False, indent=2)


def read_baseline_diff(project_id: str) -> Optional[dict]:
    bp = baseline_diff_path(project_id)
    if not os.path.isfile(bp):
        return None
    try:
        with open(bp, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def clear_baseline_diff(project_id: str) -> None:
    bp = baseline_diff_path(project_id)
    if os.path.isfile(bp):
        try:
            os.remove(bp)
        except OSError:
            pass


# ---- 推送 G R2：浏览器端直传工程树（绕开 zip 打包） ----
#
# 流程：
#   1. tree_start(project_id)        — 清空旧 engineering_src/，返回 new state
#   2. tree_write_files(..., files)  — 一批文件 (rel_path -> bytes) 落到 engineering_src/
#      —— 可调多次，每次累计，期间强制检查总大小/文件数不超上限
#   3. tree_finish(project_id, name) — 扫目录产 meta，name 是工作区名作为"zip_name"替代
#
# 安全策略：每个 rel_path 都做：
#   (a) 不能是绝对路径（含 Windows C:\）
#   (b) 规范化后不能有 ".." 段
#   (c) 规范化后不能有 _SKIP_SEGMENTS（.git / build / ...）—— 浏览器端兜底
#   (d) realpath 后必须落在 engineering_src/ 内（防 symlink 骗局）

def _validate_rel_path(rel_path: str) -> str:
    """返回规范化后的相对路径；若不安全则抛 TreeUploadError。"""
    if not rel_path:
        raise TreeUploadError("路径为空")
    # 统一斜杠
    norm = rel_path.replace("\\", "/").strip()
    # 去掉前导 "./"
    while norm.startswith("./"):
        norm = norm[2:]
    # 绝对路径（含 Windows 盘符）—— 直接拒，不做静默吸收
    if norm.startswith("/"):
        raise TreeUploadError(f"拒绝绝对路径：{rel_path}")
    if len(norm) >= 2 and norm[1] == ":":
        raise TreeUploadError(f"拒绝 Windows 绝对路径：{rel_path}")
    # posix 规范化
    parts = [p for p in norm.split("/") if p and p != "."]
    if any(p == ".." for p in parts):
        raise TreeUploadError(f"拒绝路径穿越：{rel_path}")
    for p in parts:
        if p in _SKIP_SEGMENTS:
            raise TreeUploadError(f"路径包含应忽略的目录段 {p}：{rel_path}")
    if not parts:
        raise TreeUploadError(f"路径空：{rel_path}")
    return "/".join(parts)


def tree_start(project_id: str) -> None:
    """清空旧工程目录（含 scan_cache），准备接收新一轮直传。"""
    clear_engineering(project_id)
    sdir = swe3_dir(project_id)
    os.makedirs(sdir, exist_ok=True)
    os.makedirs(engineering_root(project_id), exist_ok=True)


def _tree_current_stats(project_id: str) -> tuple[int, int]:
    """(current_files, current_bytes) — 用于跨 chunk 累计限额。"""
    target = engineering_root(project_id)
    total_files = 0
    total_bytes = 0
    for root, _, names in os.walk(target):
        for n in names:
            total_files += 1
            try:
                total_bytes += os.path.getsize(os.path.join(root, n))
            except OSError:
                pass
    return total_files, total_bytes


def tree_write_files(project_id: str, files: list[tuple[str, bytes]]) -> dict:
    """落盘一批文件到 engineering_src/<rel_path>。

    files: [(rel_path, data_bytes), ...]
    返回 {"written": N, "total_files": ..., "total_bytes": ...} — 便于前端显示进度
    超限时抛 TreeUploadError（HTTP 413）。
    """
    target = engineering_root(project_id)
    target_real = os.path.realpath(target)
    cur_files, cur_bytes = _tree_current_stats(project_id)

    written = 0
    for rel, data in files:
        safe_rel = _validate_rel_path(rel)
        # 单文件大小
        if len(data) > MAX_FILE_BYTES:
            raise TreeUploadError(
                f"文件 {rel} 超过单文件上限 {MAX_FILE_BYTES // 1024 // 1024} MB"
            )
        # 累计限额
        if cur_files + 1 > MAX_TREE_FILES:
            raise TreeUploadError(f"工程文件数超 {MAX_TREE_FILES}（防误选大目录）")
        if cur_bytes + len(data) > MAX_TREE_BYTES:
            raise TreeUploadError(
                f"工程累计大小超 {MAX_TREE_BYTES // 1024 // 1024} MB"
            )

        dest = os.path.join(target, safe_rel)
        # realpath 防 symlink 骗局
        dest_dir_real = os.path.realpath(os.path.dirname(dest))
        if not (dest_dir_real == target_real or dest_dir_real.startswith(target_real + os.sep)):
            raise TreeUploadError(f"目标路径逃逸：{rel}")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)
        cur_files += 1
        cur_bytes += len(data)
        written += 1

    return {"written": written, "total_files": cur_files, "total_bytes": cur_bytes}


def tree_finish(project_id: str, workspace_name: str) -> dict:
    """直传结束，扫目录产 meta。workspace_name 替代 zip_name 字段。"""
    target = engineering_root(project_id)
    if not os.path.isdir(target) or not os.listdir(target):
        raise TreeUploadError("工程目录为空，未落盘任何文件")
    display_name = (workspace_name or "unnamed").strip() or "unnamed"
    # meta 结构和 zip 上传完全一致，前端 EngineeringUploadPanel 能直接复用
    meta = build_meta(f"[dir] {display_name}", target)
    with open(engineering_meta_path(project_id), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta
