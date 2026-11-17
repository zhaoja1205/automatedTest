"""SWE.3 推送 D 数据 → 推送 H 模块数据 的桥接层。

前端推送 D 扫出来的工程数据分散在：
  project.json: aspice.swe3.push_d.focus_functions[].focused_keys
  磁盘 scan_cache/<component_id>.json: 全量 files[].classes[].functions[]

推送 H 的生成器只认 `swe3.modules[].classes/functions/nv_original_functions`。
本模块把前者注入到后者，按用户选择的策略分流：

  focus_functions.focused_keys  → 函数列表（本工程改动/关注）
  其余 (非 SDK)                  → 原始 NV 函数列表（未动的接口）
  SDK                             → 直接忽略

类列表：按 class name 去重 merge（同名类来自 .cpp / .hpp 两个文件时合并成一条，
source_files 聚合）。
"""
from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 关注函数的"分流"策略 — 2026-11-10 后：focus + (diff ∧ diff可信)
# 移除 AI 产物作为独立入口信号：用户要求 L5 详情"仅显式关注的函数 + diff 命中改动"。
# AI 产物不再是分流依据（但依然在 _normalize_fn 透传到 L5 渲染）。
FUNCTION_SPLIT_STRATEGY = "focus_plus_trusted_diff"

# 复杂函数的 ai_flowchart 抑制阈值：body_lines 超过该值的函数在 docx 里不嵌入流程图
# （图太大、模糊）。由 bridge 在标准化时抹掉 ai_flowchart 字段，让生成器走"复杂函数"
# 占位路径。与 aspice_routes._AUTO_AUGMENT_FLOW_BODY_LIMIT 保持一致。
_FLOWCHART_BODY_LIMIT = 80


def _scan_cache_dir(project_root: Path) -> Path:
    return project_root / "swe3" / "scan_cache"


def _load_scan_cache(project_root: Path, component_id: str) -> Optional[dict]:
    """读取 scan_cache/<cid>.json；找不到返回 None。"""
    p = _scan_cache_dir(project_root) / f"{component_id}.json"
    if not p.exists():
        return None
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("读取 scan_cache 失败 %s: %s", p, e)
        return None


def _collect_focused_keys(push_d: dict) -> dict[str, set[str]]:
    """聚合 push_d.focus_functions，返回 {component_id: set(key)}。

    来源两路（并集）：
      - focused_keys           — 用户在前端表格里显式勾选的"关注"
        （前端 persistFocus 里 manual_additions 对应的 key 也会同步写进来，所以这里不重复读）
      - included_added_keys    — 用户勾了"仅看项目新增"并点"批量加入 L5 展开"后保存的 diff.added 函数 key
        （二级分流：让 L5 不吃全部 diff.added，而是吃用户确认过的那部分）
    """
    out: dict[str, set[str]] = {}
    for item in push_d.get("focus_functions") or []:
        cid = item.get("component_id") or ""
        if not cid:
            continue
        keys: set[str] = set()
        for src in ("focused_keys", "included_added_keys"):
            for k in item.get(src) or []:
                if k and isinstance(k, str):
                    keys.add(k.strip())
        out[cid] = out.setdefault(cid, set()) | keys
    return out


def _is_focused(fn_key: str, focused: set[str]) -> bool:
    """判断一个函数 key 是否在关注集合里。

    key 形如 'path::class::name::hash'。严格相等即可。
    """
    if not fn_key:
        return False
    return fn_key in focused


def _is_diff_focused(fn: dict) -> bool:
    """fn.diff_status in {'added', 'modified'}，用于把 git diff 的新增/改动也纳入关注。"""
    s = (fn.get("diff_status") or "").strip().lower()
    return s in {"added", "modified"}


def _has_ai_artifact(fn: dict) -> bool:
    """AI 已为该函数生成过流程图/介绍 — 视为隐含关注。

    用户在前端"关注函数表"里对该函数手动点了"生成"，回写会落到 scan_cache 的
    ai_flowchart / ai_intro / flowchart_plantuml 字段。即使此 cid 在
    push_d.focus_functions 里缺失（例如老项目或前端只选了函数没触发 cid 条目），
    这个信号也要兜住，把函数拉进 functions[]，让 L5 章节能嵌入 PNG。
    """
    for k in ("ai_flowchart", "flowchart_plantuml", "ai_intro"):
        v = fn.get(k)
        if isinstance(v, str) and v.strip():
            return True
    return False


def _normalize_fn(fn: dict) -> dict:
    """把 scan_cache 里的函数对象标准化到生成器期望的字段名。

    生成器期望字段（参见 _build_function_subsection / _build_fn_detail_table）：
      name / declaration / intro / parameters / returns / design_id / flowchart_plantuml
    """
    # intro 优先级：ai_intro（AI 生成）> doc_comment（源码注释）> 空
    intro = (fn.get("ai_intro") or "").strip() or (fn.get("doc_comment") or "").strip()
    body_lines = int(fn.get("body_lines") or 0)
    out = {
        "key":          fn.get("key"),
        "name":         fn.get("name") or "",
        "declaration":  fn.get("declaration") or "",
        "parameters":   fn.get("parameters") or [],
        "returns":      fn.get("returns") or [],
        "intro":        intro,
        "diff_status":  fn.get("diff_status"),
        "is_sdk":       bool(fn.get("is_sdk")),
        "body_lines":   body_lines,
    }
    # 流程图：AI 生成结果（若 push_d 流程中回写到 scan_cache 的话）
    # 复杂函数（> _FLOWCHART_BODY_LIMIT 行）抑制 — 让生成器插"请手绘"占位
    complex_flag = body_lines > _FLOWCHART_BODY_LIMIT
    if complex_flag:
        out["is_complex"] = True
    elif fn.get("flowchart_plantuml"):
        out["flowchart_plantuml"] = fn["flowchart_plantuml"]
    elif fn.get("ai_flowchart"):
        out["ai_flowchart"] = fn["ai_flowchart"]
    return out


def _dedupe_funcs_by_name(funcs: list[dict]) -> list[dict]:
    """同名函数去重：按 name 保留第一个有 body/declaration 的版本。

    scan_cache 里同一个类会在 .cpp 和 .hpp 两个文件里各出现一次 — 合并成一条。
    """
    seen: dict[str, dict] = {}
    for f in funcs:
        nm = (f.get("name") or "").strip()
        if not nm:
            continue
        if nm not in seen:
            seen[nm] = f
        else:
            # 保留"更丰富"的那条：有 declaration > 无 declaration
            if not seen[nm].get("declaration") and f.get("declaration"):
                seen[nm] = f
    return list(seen.values())


def _merge_class(target: dict, src: dict, src_path: str) -> None:
    """把 src 类合并进 target（同名类）。source_files 聚合，functions 汇总。"""
    if src_path and src_path not in target.setdefault("source_files", []):
        target["source_files"].append(src_path)
    # 合并常量 / 变量（取并集，按 name 去重）
    for kind in ("constants", "variables"):
        tgt_list = target.setdefault(kind, [])
        existing_names = {(it.get("name") or "").strip() for it in tgt_list if isinstance(it, dict)}
        for it in src.get(kind) or []:
            nm = (it.get("name") or "").strip()
            if nm and nm not in existing_names:
                tgt_list.append(it)
                existing_names.add(nm)
    # 函数先按原样追加，稍后再去重
    target.setdefault("_raw_functions", []).extend(src.get("functions") or [])


def build_module_data_from_scan(
    component_id: str,
    scan_cache: dict,
    focused: set[str],
    split_policy: str = "auto_all",
) -> dict:
    """根据 scan_cache 和关注函数集合，构造一个 module 数据对象。

    返回字段：
      id / name / classes[] / functions[] / nv_original_functions[]

    classes[]: 去重合并后的类（含 member_constants / member_variables）
    functions[]: 关注的函数 + diff_status 命中的函数（本工程改动）
    nv_original_functions[]: 其余非 SDK 函数（未动的原始接口）

    split_policy（见 arch_sections.MODULE_SPLIT_POLICY）：
      - auto_all      A 组：trusted diff 下 added ∨ modified 都自动进 L5
      - modified_only B/C 组：trusted diff 下只有 modified 自动进 L5；
                      added 需用户在 FocusFunctionsPicker 勾选（落到 focused ∪ included_added_keys）
      - manual        人工维护章节；本函数不对 manual 做特殊处理（manual 章节走另外路径）

    任何 policy 下，diff.trustworthy=False 都退化成"只 focused_keys/included_added_keys"
    （防 baseline 退化导致 docx 全模块膨胀）。
    """
    # diff_status 是否可信：classify_functions 退化到全标 modified 时置 False，
    # 这里就不能让 diff_status=modified 独自触发入 functions[]，否则一次扫描会把全部
    # 非 SDK 函数都塞进 L5，docx 膨胀且大多为空流程图（见 2026-11-09 A001 182 fn 场景）。
    diff_stats = (scan_cache.get("stats") or {}).get("diff") or {}
    diff_trustworthy = diff_stats.get("trustworthy", True)

    classes_by_name: dict[str, dict] = {}
    file_level_funcs: list[dict] = []  # __free__ 类下的函数，视作文件级/C 函数

    for f in scan_cache.get("files") or []:
        path = f.get("path") or ""
        for c in f.get("classes") or []:
            cname = (c.get("name") or "").strip()
            if not cname:
                continue
            if cname == "__free__":
                # 游离函数（C 函数 / 全局函数）不进"类"，单独收集
                file_level_funcs.extend(c.get("functions") or [])
                continue
            tgt = classes_by_name.get(cname)
            if tgt is None:
                tgt = {
                    "class_name":        f"Class {cname}" if not cname.lower().startswith("class") else cname,
                    "name":              cname,
                    "description":       (c.get("doc_comment") or "").strip(),
                    "source_files":      [],
                    "member_constants":  [],
                    "member_variables":  [],
                    "_raw_functions":    [],
                }
                classes_by_name[cname] = tgt
            _merge_class(tgt, c, path)

    # 分流：遍历所有候选函数（类里的 + 文件级的），按 focused/diff 分到两组
    all_focus: list[dict] = []
    all_nv:    list[dict] = []

    def _should_focus(fn: dict, key: str) -> bool:
        """按模块 split_policy 决定一个函数是否进 L5。

        2026-11-13 规则 v8（R4 需求 #2）：
          - 显式关注（focused_keys / included_added_keys 合集 = focused 入参）→ 永远进
          - manual 策略：**只**认 focused，diff_status 一律不自动吃
            （Deserializer / nvsipl_camera / nvsipl_multicast 走这条，
            避免 NV 底仓海量函数全被 modified 噪声拖进 L5）
          - diff 可信时：auto_all 允许 added ∨ modified；modified_only 只允许 modified
          - diff 不可信（如 baseline==head 退化）→ 两种 policy 都退化成只 focused

        2026-11-10 已移除 AI 产物作为独立入口：ai_intro / ai_flowchart 不再把函数拉进
        L5，仅透传给生成器做渲染（见 _normalize_fn）。
        """
        if _is_focused(key, focused):
            return True
        if split_policy == "manual":
            return False
        if not diff_trustworthy:
            return False
        s = (fn.get("diff_status") or "").strip().lower()
        if s == "modified":
            return True
        if s == "added" and split_policy == "auto_all":
            return True
        return False

    def classify(fn: dict) -> None:
        if fn.get("is_sdk"):
            return  # SDK 全部跳过
        key = fn.get("key") or ""
        if _should_focus(fn, key):
            all_focus.append(_normalize_fn(fn))
        else:
            all_nv.append(_normalize_fn(fn))

    # 类里的函数
    for cname, tgt in classes_by_name.items():
        class_focus: list[dict] = []
        for fn in tgt.pop("_raw_functions", []):
            if fn.get("is_sdk"):
                continue
            key = fn.get("key") or ""
            norm = _normalize_fn(fn)
            if _should_focus(fn, key):
                class_focus.append(norm)
                all_focus.append(norm)
            else:
                all_nv.append(norm)
        # 把关注的函数挂到类里（供 _list_functions 聚合，渲染 L5 详情）
        tgt["functions"] = _dedupe_funcs_by_name(class_focus)
        # member_constants/variables 字段名 → 生成器期望的 constants/variables 同义字段都兼容

    # 文件级函数
    for fn in file_level_funcs:
        classify(fn)

    # 排序：按 name 稳定
    classes_list = sorted(classes_by_name.values(), key=lambda c: c.get("name", ""))
    all_focus = _dedupe_funcs_by_name(all_focus)
    all_nv = _dedupe_funcs_by_name(all_nv)

    return {
        "id":                      component_id,
        "name":                    _component_name(component_id, scan_cache),
        "classes":                 classes_list,
        "functions":               all_focus,
        "nv_original_functions":   all_nv,
    }


# ---- 模块短名映射（扫 scan_cache 顶层的 component_id，fallback 到项目 project.json）----

def _component_name(cid: str, scan_cache: dict) -> str:
    # scan_cache 没明确 name，按 path 第一段推测
    for f in scan_cache.get("files") or []:
        path = f.get("path") or ""
        if "serializer" in path.lower():
            return "Serializer"
        if "deserializer" in path.lower():
            return "Deserializer"
        if "eeprom" in path.lower():
            return "EEPROM"
        if "cameramodule" in path.lower():
            return "CameraModule"
        if "camerasecurity" in path.lower():
            return "CameraSecurity"
        if "nvsipl_multicast" in path.lower() or "multicast" in path.lower():
            return "nvsipl_multicast"
        if "nvsipl_camera" in path.lower():
            return "nvsipl_camera"
        if "pmic" in path.lower():
            return "PMIC"
        if "campwr" in path.lower() or "pwr" in path.lower():
            return "Campwr"
    return cid


def enrich_modules_from_push_d(
    project: dict,
    project_root: Path,
) -> dict:
    """把 push_d 的扫描数据注入 project.aspice.swe3.modules，返回新的 project（浅拷贝）。

    - 对每个在 push_d 里有扫描结果的 component_id，覆盖/新增一个 module 数据
    - 原来 modules 里已有的字段（name 等）优先保留
    - 返回的 project 可直接传给 export_swe3
    """
    aspice = project.get("aspice") or {}
    swe3 = aspice.get("swe3") or {}
    push_d = swe3.get("push_d") or {}
    if not push_d:
        return project  # 没有推送 D 数据，不做事

    focused_by_cid = _collect_focused_keys(push_d)

    # 收集所有 component_id：focus + module_code_sources + scan_indices 并集
    cids: set[str] = set(focused_by_cid.keys())
    for item in push_d.get("module_code_sources") or []:
        cid = item.get("component_id")
        if cid:
            cids.add(cid)
    for item in push_d.get("scan_indices") or []:
        cid = item.get("component_id")
        if cid:
            cids.add(cid)

    from app.core.arch_sections import split_policy_for_module

    enriched: dict[str, dict] = {}
    for cid in cids:
        sc = _load_scan_cache(project_root, cid)
        if not sc:
            continue
        focused = focused_by_cid.get(cid, set())
        # 按 cid + scan 推断的 name 决定分流策略（arch_sections.MODULE_SPLIT_POLICY）
        inferred_name = _component_name(cid, sc)
        policy = split_policy_for_module(cid, inferred_name)
        md = build_module_data_from_scan(cid, sc, focused, split_policy=policy)
        # 记一份 policy，供下面 merge 时判断是否要保留用户在 ModuleEditor 的编辑
        md["__split_policy__"] = policy
        enriched[cid] = md
        logger.info(
            "SWE.3 bridge 注入模块 %s (%s, policy=%s): %d 类 / %d 关注函数 / %d 原始 NV",
            cid, inferred_name, policy,
            len(md["classes"]), len(md["functions"]), len(md["nv_original_functions"]),
        )

    if not enriched:
        return project

    # 深拷贝 project 避免副作用
    new_project = copy.deepcopy(project)
    new_swe3 = new_project.setdefault("aspice", {}).setdefault("swe3", {})
    old_modules = new_swe3.get("modules") or []

    # 建立 id → old_module 索引；没有 id 的按 name 关键字匹配
    merged: list[dict] = []
    used_cids: set[str] = set()

    def _match_cid(old_m: dict) -> Optional[str]:
        # 1) 显式 id/component_id
        for k in ("id", "component_id"):
            v = (old_m.get(k) or "").strip()
            if v in enriched:
                return v
        # 2) name 关键字匹配
        name = (old_m.get("name") or "").lower().replace(" ", "")
        for cid, md in enriched.items():
            md_name = (md.get("name") or "").lower().replace(" ", "")
            if md_name and (md_name in name or name in md_name):
                return cid
        return None

    for old_m in old_modules:
        cid = _match_cid(old_m)
        if cid and cid not in used_cids:
            new_m = copy.deepcopy(old_m)
            injected = enriched[cid]
            new_m["id"] = cid
            # 覆盖扫描型字段；保留老的 name/description 等
            if not new_m.get("name"):
                new_m["name"] = injected["name"]
            # R4.7 需求：manual 策略下 bridge 不覆盖 mod.classes / mod.functions
            # —— 四个人工模块（Deserializer / nvsipl_camera / nvsipl_multicast /
            # CameraSecurity）的类列表和函数列表完全由用户在 ModuleEditor 里手编。
            # 这样 ModuleEditor 显示「类列表(0)」时，docx 导出里也不会突然蹦出
            # 45 个从 scan_cache 重生的空壳 Class XX 章节。
            # nv_original_functions 仍然按 scan 注入（用户抱怨的 4.3.2 原始NV列表章节
            # 是从 scan 直接取的，这才是合理的「原始 SDK 函数」来源）。
            policy = injected.get("__split_policy__") or ""
            if policy == "manual":
                # 若用户老数据里压根没有 classes / functions 字段，给个空数组，
                # 避免下游 arch_generator_swe3_v3 读 .get("classes") 时拿到 None 崩
                new_m.setdefault("classes", [])
                new_m.setdefault("functions", [])
            else:
                new_m["classes"] = injected["classes"]
                new_m["functions"] = injected["functions"]
            new_m["nv_original_functions"] = injected["nv_original_functions"]
            merged.append(new_m)
            used_cids.add(cid)
        else:
            merged.append(old_m)

    # 剩余未匹配的 cid 作为新模块追加
    for cid, md in enriched.items():
        if cid not in used_cids:
            # manual 策略下同样不要把扫描来的 classes / functions 直接塞进文档，
            # 让用户去 ModuleEditor 里手编（见上面 R4.7 说明）。
            if (md.get("__split_policy__") or "") == "manual":
                md = copy.deepcopy(md)
                md["classes"] = []
                md["functions"] = []
            merged.append(md)

    # 清理 __split_policy__ 内部标记，不要把它写进 project.json
    for m in merged:
        if isinstance(m, dict) and "__split_policy__" in m:
            m.pop("__split_policy__", None)

    new_swe3["modules"] = merged
    return new_project
