"""
配置持久化。

当前阶段使用 JSON 文件保存 SSH / Workspace 配置，
避免服务重启后配置完全丢失。
"""
from __future__ import annotations

import json
import os
from typing import Type, TypeVar

from pydantic import BaseModel


T = TypeVar("T", bound=BaseModel)


class ConfigStore:
    def __init__(self, base_dir: str = "runtime"):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def _path(self, name: str) -> str:
        return os.path.join(self.base_dir, f"{name}.json")

    def load(self, name: str, model_cls: Type[T], default: T) -> T:
        path = self._path(name)
        if not os.path.exists(path):
            return default

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return model_cls(**data)
        except Exception:
            return default

    def save(self, name: str, model: BaseModel):
        path = self._path(name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(model.model_dump(), f, ensure_ascii=False, indent=2)
