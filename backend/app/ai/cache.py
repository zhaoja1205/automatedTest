"""
AI 结果缓存。

基于文件系统的简单缓存，避免同一用例 + 同一错误重复调用 LLM。
缓存键 = hash(case_id + error_signature)，TTL 默认 24 小时。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Optional


class AICache:
    """文件级 AI 结果缓存。"""

    def __init__(self, cache_dir: str = "runtime/ai_cache", ttl_hours: int = 24):
        self.cache_dir = cache_dir
        self.ttl_seconds = ttl_hours * 3600
        os.makedirs(cache_dir, exist_ok=True)

    def _make_key(self, *parts: str) -> str:
        raw = "|".join(str(p) for p in parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _path(self, key: str) -> str:
        return os.path.join(self.cache_dir, f"{key}.json")

    def get(self, *key_parts: str) -> Optional[dict]:
        """从缓存获取结果，过期返回 None。"""
        key = self._make_key(*key_parts)
        path = self._path(key)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                entry = json.load(f)
            if time.time() - entry.get("_ts", 0) > self.ttl_seconds:
                os.remove(path)
                return None
            data = dict(entry)
            data.pop("_ts", None)
            return data
        except (json.JSONDecodeError, OSError):
            return None

    def set(self, *key_parts: str, value: dict):
        """写入缓存。"""
        key = self._make_key(*key_parts)
        path = self._path(key)
        entry = {**value, "_ts": time.time()}
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(entry, f, ensure_ascii=False, indent=2)
        except OSError:
            pass  # 缓存写入失败不影响主流程

    def invalidate(self, *key_parts: str):
        """删除指定缓存。"""
        key = self._make_key(*key_parts)
        path = self._path(key)
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    def clear(self):
        """清空全部缓存。"""
        if not os.path.isdir(self.cache_dir):
            return
        for fname in os.listdir(self.cache_dir):
            if fname.endswith(".json"):
                try:
                    os.remove(os.path.join(self.cache_dir, fname))
                except OSError:
                    pass

    def cleanup_expired(self):
        """清理过期缓存条目。"""
        if not os.path.isdir(self.cache_dir):
            return
        now = time.time()
        for fname in os.listdir(self.cache_dir):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(self.cache_dir, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    entry = json.load(f)
                if now - entry.get("_ts", 0) > self.ttl_seconds:
                    os.remove(path)
            except (json.JSONDecodeError, OSError):
                pass
