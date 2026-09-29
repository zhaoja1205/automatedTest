"""
Zip 上传/解压小工具。

设计目标：
- **流式落盘**：`stream_save()` 边收边写，不把整包塞进内存
  （类图模块预期 20-200MB zip，走 `content = await file.read()` 会吃满进程内存）。
- **超尺寸早退**：`MAX_ZIP_BYTES` 硬顶，超了立刻抛，避免写半天再拒。
- **安全解压**：`safe_extractall()` 拦截绝对路径、`..` 穿越、符号链接。
  Python 3.12 起 zipfile 有 `filter="data"`，但这里显式检查更直白、也向下兼容。

被 `classdiag_routes.py` 调用；抽独立模块是为了给单测留缝。
"""
from __future__ import annotations

import os
import zipfile
from typing import BinaryIO

# 300 MB 硬顶：略高于用户声明的最大工程 200 MB，给压缩率不利的场景留头。
# 太大会撑爆磁盘，太小会误伤合法包。
MAX_ZIP_BYTES = 300 * 1024 * 1024

# 单次读写块大小。1 MB 对 fastapi UploadFile 是常见甜点，
# 小块调用次数多、大块占内存。
_CHUNK = 1 * 1024 * 1024

# 解压时**静默跳过**的路径段：这些目录 cpp_class_parser 也不扫（见 _SKIP_DIRS），
# 落盘毫无意义，且是 symlink / 权限位怪东西的主要来源
# （典型：`.git/` 里的 packed-refs symlink、submodule 场景下 `.git` 本身就是 symlink）。
# 只要路径**任一段**匹配到就整条 entry 跳过 —— 不当作安全违规抛异常。
# 与 cpp_class_parser._SKIP_DIRS 保持一致：改这里也要顺手改那边。
_SKIP_SEGMENTS = frozenset({
    ".git", ".hg", ".svn",
    "build", "out", "dist", "cmake-build-debug",
    "node_modules", "third_party", "third-party",
    ".vscode", ".idea", ".cache",
})


class UploadTooLarge(Exception):
    """上传超过 MAX_ZIP_BYTES 时抛。路由层捕获转 HTTP 413。"""


class UnsafeArchive(Exception):
    """zip 里出现绝对路径 / .. / 符号链接时抛。路由层捕获转 HTTP 400。"""


async def stream_save(upload_file, dest_path: str, max_bytes: int = MAX_ZIP_BYTES) -> int:
    """从 fastapi UploadFile 流式落到磁盘。返回落地字节数。

    UploadFile.file 是 SpooledTemporaryFile，但直接读它也一样走同步 IO；
    我们用 async 的 `.read(size)` 更贴合 fastapi 的事件循环模型，
    单次 1 MB 收 -> 写，超 max_bytes 立刻抛并删残留。
    """
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    total = 0
    try:
        with open(dest_path, "wb") as out:
            while True:
                chunk = await upload_file.read(_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise UploadTooLarge(
                        f"上传超过 {max_bytes // (1024*1024)} MB 上限"
                    )
                out.write(chunk)
    except Exception:
        # 落地失败/超尺寸：把已写的一部分清掉，避免留半个坏 zip
        if os.path.isfile(dest_path):
            try:
                os.remove(dest_path)
            except OSError:
                pass
        raise
    return total


def _should_skip(normalized_name: str) -> bool:
    """路径任一段落在 _SKIP_SEGMENTS 里就跳过（如 `.git/`, `foo/build/x.o`）。

    只识别目录段，不匹配文件名 —— 例如 `mybuild.h` 不会因为「build」被误伤。
    """
    for part in normalized_name.split("/"):
        if part in _SKIP_SEGMENTS:
            return True
    return False


def safe_extractall(zip_path: str, target_dir: str) -> int:
    """安全解压 zip 到 target_dir。返回**实际落盘**的条目数（跳过的不计）。

    对每个 entry 检查：
      1. 名字不能是绝对路径（`/foo`, `C:\\foo`）
      2. 名字不能含 `..`（防目录穿越）
      3. 解析后的目标路径必须落在 target_dir 内（做实际 realpath 对比，
         兜住组合式路径攻击如 `a/../../x`）
      4. 不允许符号链接条目（外部权限位 0xA0000000）
    任何一条不满足就整体拒绝。

    但：**先按 `_SKIP_SEGMENTS` 过滤路径**（.git / build / node_modules / ...）——
    这些目录 cpp_class_parser 也不扫，落盘无意义。跳过的 entry 不参与上述 4 项
    检查，也不会因为它们把整个上传拒掉（比如 zip 里恰好有 `.git/HEAD` 是 symlink，
    以前会整包报错「不安全」；现在静默跳过）。
    """
    os.makedirs(target_dir, exist_ok=True)
    target_abs = os.path.realpath(target_dir)

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            allowed: list[str] = []
            for name in zf.namelist():
                # 归一斜杠：zip 规范用 '/'，Windows 有些工具会塞 '\\'
                normalized = name.replace("\\", "/")

                # 先看是否属于「静默跳过」目录 —— 是的话完全不做后续安全检查
                if _should_skip(normalized):
                    continue

                if normalized.startswith("/") or (len(normalized) >= 2 and normalized[1] == ":"):
                    raise UnsafeArchive(f"zip 内含绝对路径: {name!r}")
                # `..` 单独段禁止；组合式攻击靠下面的 realpath 兜底
                parts = normalized.split("/")
                if any(p == ".." for p in parts):
                    raise UnsafeArchive(f"zip 内含 .. 路径穿越: {name!r}")

                info = zf.getinfo(name)
                # 符号链接：Unix mode 存在外部属性高位。type == 0xA (symlink)
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise UnsafeArchive(f"zip 内含符号链接: {name!r}")

                # realpath 对比兜底
                dest = os.path.realpath(os.path.join(target_dir, normalized))
                if not (dest == target_abs or dest.startswith(target_abs + os.sep)):
                    raise UnsafeArchive(f"zip 条目解析后越界: {name!r} -> {dest}")

                allowed.append(name)

            # 只解压 allowed 里的 entry，跳过的（.git 等）完全不落盘
            zf.extractall(target_dir, members=allowed)
            return len(allowed)
    except UnsafeArchive:
        # 检查阶段就抛的话 extractall 还没跑，target_dir 里没脏东西；这里不清理。
        raise
    except zipfile.BadZipFile as e:
        raise UnsafeArchive(f"不是合法 zip 文件: {e}") from e


def summarize_extract(target_dir: str) -> dict:
    """解压后返回一个精简摘要：文件数、顶层目录列表。给前端 UI 用。"""
    file_count = 0
    top_dirs: set[str] = set()
    for entry in os.scandir(target_dir):
        if entry.is_dir():
            top_dirs.add(entry.name)
        elif entry.is_file():
            file_count += 1
    # 深层文件也算
    for _, _, files in os.walk(target_dir):
        file_count += len(files)
    # os.walk 会把顶层文件也扫一遍，上面 scandir 已算过：修正
    file_count -= sum(1 for e in os.scandir(target_dir) if e.is_file())
    return {"file_count": file_count, "top_dirs": sorted(top_dirs)}
