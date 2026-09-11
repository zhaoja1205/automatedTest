"""
ASPICE ID 编号规则 — 四级 ID 派生。

依据 Pangu_ASPICE ID编号规则V1.0：
  OR:      {项目代号}_{序号}              如 Pangu_001
  SWE.1:   {OR}-R{序号}                   如 Pangu_001-R001
  SWE.2:   {SWE.1}-A{序号}                如 Pangu_001-R001-A001
  SWE.3:   {SWE.2}-D{序号}                如 Pangu_001-R001-A001-D001
  SWE.4:   {SWE.3模块ID}-F{函数序号}.{用例序号}
  SWE.5:   {分类}_{序号}（表里对应 SWE.2 的 A-ID）
  SWE.6:   {分类}_{序号}（表里对应 SWE.1 的 R-ID）

项目代号大小写不限，原样使用（不转换大小写）。
序号统一 3 位零填充。
"""


def derive_or(project_code: str, seq: int) -> str:
    """OR ID：项目代号 + 序号。"""
    return f"{project_code}_{seq:03d}"


def derive_req(or_id: str, r_seq: int) -> str:
    """SWE.1 需求 ID：OR + -R + 序号。"""
    return f"{or_id}-R{r_seq:03d}"


def derive_arch(req_id: str, a_seq: int) -> str:
    """SWE.2 架构 ID：SWE.1 + -A + 序号。"""
    return f"{req_id}-A{a_seq:03d}"


def derive_detail(arch_id: str, d_seq: int) -> str:
    """SWE.3 详设 ID：SWE.2 + -D + 序号。"""
    return f"{arch_id}-D{d_seq:03d}"


def derive_unit_test(detail_module_id: str, func_seq: int, case_seq: int) -> str:
    """SWE.4 单元测试 ID：SWE.3 模块 ID + -F + 函数序号 + .用例序号。"""
    return f"{detail_module_id}-F{func_seq:02d}.{case_seq:02d}"


def parse_or_id(or_id: str) -> tuple[str, int]:
    """解析 OR ID 为 (项目代号, 序号)。如 Pangu_001 → ('Pangu', 1)。"""
    idx = or_id.rfind("_")
    if idx < 0:
        return or_id, 0
    code = or_id[:idx]
    seq = int(or_id[idx + 1:])
    return code, seq


def parse_req_id(req_id: str) -> tuple[str, int]:
    """解析 SWE.1 需求 ID 为 (OR ID, R 序号)。如 Pangu_001-R001 → ('Pangu_001', 1)。"""
    idx = req_id.rfind("-R")
    if idx < 0:
        return req_id, 0
    or_id = req_id[:idx]
    r_seq = int(req_id[idx + 2:])
    return or_id, r_seq


def parse_arch_id(arch_id: str) -> tuple[str, int]:
    """解析 SWE.2 架构 ID 为 (SWE.1 ID, A 序号)。如 Pangu_001-R001-A001 → ('Pangu_001-R001', 1)。"""
    idx = arch_id.rfind("-A")
    if idx < 0:
        return arch_id, 0
    req_id = arch_id[:idx]
    a_seq = int(arch_id[idx + 2:])
    return req_id, a_seq


def next_or_seq(existing: list[dict]) -> int:
    """根据已有需求项列表计算下一个 OR 序号（从 1 起）。"""
    max_seq = 0
    for item in existing:
        or_id = item.get("or_id", "")
        _, seq = parse_or_id(or_id)
        if seq > max_seq:
            max_seq = seq
    return max_seq + 1


def next_req_seq(existing: list[dict]) -> int:
    """根据已有需求项列表计算下一个 R 序号。"""
    max_seq = 0
    for item in existing:
        req_id = item.get("req_id", "")
        _, seq = parse_req_id(req_id)
        if seq > max_seq:
            max_seq = seq
    return max_seq + 1


def next_arch_seq(existing: list[dict], req_id: str) -> int:
    """对同一 req_id，计算下一个 A 序号。"""
    max_seq = 0
    for item in existing:
        if item.get("swe1_id") != req_id:
            continue
        arch_id = item.get("swe2_id", "")
        _, seq = parse_arch_id(arch_id)
        if seq > max_seq:
            max_seq = seq
    return max_seq + 1
