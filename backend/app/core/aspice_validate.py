#!/usr/bin/env python3
"""Machine validation for SWE1 project JSON / generated documents.

Three modes:
  validate.py --project project.json
      -> check internal consistency of the JSON (ID coverage, naming, dates, enums)

  validate.py --project project.json --excel out.xlsx --docx out.docx
      -> additionally verify generated files round-trip to the same content

  validate.py --project project.json --excel out.xlsx --docx out.docx --report report.md
      -> write findings to a markdown report

Exit code: 0 = all pass, 1 = errors found (warnings do not fail the build).

Checks (all machine-checked, no eyeballing):
  V01 project/document fields present (name, doc_number, version, history)
  V02 inputs list non-empty; each name unique
  V03 Requirement A列(input) values ⊆ inputs names (exact string match)
  V04 or_id pattern <PROJ>_NNN, sequential without gaps (ignoring Deleted rows' N/A)
  V05 req_id pattern <OR>-RNNN and unique
  V06 every req_id's OR prefix == its or_id
  V07 flag values in {Original, Add, Deleted, Modified}
  V08 Deleted rows use the fixed boilerplate (F/G/H/I=N/A, J=NA, W=Guaranteed by other modules)
  V09 category/asil/priority value domains
  V10 SRS ch2/3 req_ids cover every non-Deleted req_id exactly >= once
  V11 SRS sections have non-empty desc_en + desc_cn (bilingual completeness)
  V12 risk req_id values exist in requirements
  V13 dates parseable; ra_deadline <= release_time when both set
  V14 Excel round-trip: rebuilt file re-extracts to identical requirements/risks/inputs/history
  V15 DOCX round-trip: all JSON req_ids appear in the doc; all SRS titles present as headings
"""
import argparse
import datetime
import json
import re
import sys
from collections import Counter

REQID_RE = re.compile(r"^([A-Za-z0-9]+)_(\d+)-R(\d+)$")
OR_RE = re.compile(r"^([A-Za-z0-9]+)_(\d+)$")
FLAGS = {"Original", "Add", "Deleted", "Modified"}
CATEGORIES_OK = {"Software Requirements"}
ASIL_OK = {"QM", "ASIL A", "ASIL B", "ASIL C", "ASIL D", "N/A"}
DATE_FIELDS = ("release_time", "ra_deadline", "actual_time")
# history keys stored only on the Word side; Excel round-trip can never carry them
WORD_ONLY_HISTORY_KEYS = ("status",)
# category column (L) allowed values, comma must be full-width ，
CATEGORIES_L_OK = {
    "Functional Requirements，Basic Functions",
    "Functional Requirements，Safety Requirements",
    "Functional Requirements，Cybersecurity Requirements",
    "Non-Functional Requirements",
    "Non-camera driver/tuning requirements",
}
# fields that must be exactly N/A on Deleted rows (per data_model.md)
DELETED_NA_FIELDS = ("or_id", "or_desc", "req_id", "sw_req_desc", "asil",
                     "correctness", "feasibility", "exception", "priority",
                     "release_time", "actual_time", "release_version", "owner",
                     "arch_doc")
DELETED_TESTCASE = "NA"


def flag_not_deleted(r):
    return r.get("flag") != "Deleted"


def wl_key_val(v):
    """Scalar string for worklist provenance keys: joins list values with newline
    (the Excel multi-value convention) so a Deleted row with `no: ["1","2"]` can
    match the worklist's multi-line orig_id. None → ''."""
    if v is None:
        return ""
    if isinstance(v, list):
        return "\n".join(str(x) if x is not None else "" for x in v)
    return str(v)


def norm_val(v):
    """Normalize a value for round-trip comparison: ''/None equivalent,
    single-element list equivalent to scalar, lists compared elementwise."""
    if isinstance(v, list):
        v = [norm_val(x) for x in v]
        if len(v) == 0:
            return None
        if len(v) == 1:
            return v[0]
        return tuple(v)
    if v is None or v == "":
        return None
    return v


def norm_row(d):
    """Normalize a dict row (requirement/risk) for comparison."""
    if not isinstance(d, dict):
        return d
    return {k: norm_val(v) for k, v in d.items()}


def norm_row_pair(x, y):
    """Normalize two rows onto a COMMON key set (union, missing keys read as
    None). The extractor always emits all 24 requirement keys while hand-written
    JSON may omit optional ones — key-set differences must not read as value
    differences (they produced self-contradictory empty diffs)."""
    if not (isinstance(x, dict) and isinstance(y, dict)):
        return x, y
    keys = set(x) | set(y)
    return ({k: norm_val(x.get(k)) for k in keys},
            {k: norm_val(y.get(k)) for k in keys})


def norm_history(rec):
    """Normalize a history record: drop Word-only keys (status is stored in the
    Word history table but not in the Excel document-record sheet)."""
    if not isinstance(rec, dict):
        return rec
    return {k: norm_val(v) for k, v in rec.items() if k not in WORD_ONLY_HISTORY_KEYS}


class Result:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.passed = []

    def err(self, code, msg):
        self.errors.append(f"[{code}] {msg}")

    def warn(self, code, msg):
        self.warnings.append(f"[{code}] {msg}")

    def ok(self, code, msg):
        self.passed.append(f"[{code}] {msg}")


def parse_date(v):
    if v in (None, "", "N/A", "NA", "TBD", "/"):
        return None
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(str(v).strip(), fmt)
        except ValueError:
            continue
    return False  # unparseable sentinel


def validate_json(proj, res):
    pr, doc = proj.get("project", {}), proj.get("document", {})
    reqs = proj.get("requirements", [])
    inputs = proj.get("inputs", [])
    risks = proj.get("risks", [])

    # V01
    missing = [k for k in ("name",) if not pr.get(k)] + \
              [k for k in ("doc_number", "version") if not doc.get(k)]
    if missing:
        res.err("V01", f"missing project/document fields: {missing}")
    else:
        res.ok("V01", f"project={pr['name']}, doc={doc['doc_number']} {doc['version']}")

    # V02
    names = [i.get("name", "") if isinstance(i, dict) else str(i) for i in inputs]
    if not names or not any(n.strip() for n in names):
        res.err("V02", "inputs list is empty")
    else:
        dup = [n for n, c in Counter(names).items() if c > 1]
        if dup:
            res.err("V02", f"duplicate input names: {dup}")
        else:
            res.ok("V02", f"{len(names)} input documents")

    # V03
    bad_inputs = sorted({r.get("input", "") for r in reqs
                         if r.get("input") and r["input"] not in names})
    if bad_inputs:
        res.err("V03", f"requirement input values not in inputs list: {bad_inputs}")
    else:
        res.ok("V03", "requirement input column consistent with inputs sheet")

    # V04/V05/V06
    ors, req_ids, or_gaps = [], [], []
    seen_or = set()
    for idx, r in enumerate(reqs, start=3):
        oid, rid, flag = r.get("or_id"), r.get("req_id"), r.get("flag")
        if flag == "Deleted":
            continue
        if oid:
            m = OR_RE.match(str(oid))
            if not m:
                res.err("V04", f"row{idx}: or_id {oid!r} not <PROJ>_NNN")
            else:
                if oid not in seen_or:
                    seen_or.add(oid)
                    ors.append(int(m.group(2)))
        else:
            res.err("V04", f"row{idx}: missing or_id")
        if rid:
            m = REQID_RE.match(str(rid))
            if not m:
                res.err("V05", f"row{idx}: req_id {rid!r} not <OR>-RNNN")
            else:
                req_ids.append(str(rid))
                if oid and f"{m.group(1)}_{m.group(2)}" != str(oid):
                    res.err("V06", f"row{idx}: req_id {rid} prefix mismatch with or_id {oid}")
        else:
            res.err("V05", f"row{idx}: missing req_id")
    if ors:
        exp = list(range(1, max(ors) + 1))
        missing_or = sorted(set(exp) - set(ors))
        if missing_or:
            res.warn("V04", f"or_id sequence gaps: {missing_or}")
        else:
            res.ok("V04", f"or_id sequential 1..{max(ors)} ({len(seen_or)} ORs, {len(req_ids)} reqs)")
    dupreq = [r for r, c in Counter(req_ids).items() if c > 1]
    if dupreq:
        res.err("V05", f"duplicate req_id: {dupreq}")
    elif req_ids:
        res.ok("V05", f"{len(req_ids)} req_ids unique")

    # V07/V08
    deleted_bad = 0
    for idx, r in enumerate(reqs, start=3):
        if r.get("flag") not in FLAGS:
            res.err("V07", f"row{idx}: flag {r.get('flag')!r} not in {sorted(FLAGS)}")
        if r.get("flag") == "Deleted":
            for f in DELETED_NA_FIELDS:
                v = norm_val(r.get(f))
                if v is not None and str(v).strip() not in ("N/A", "NA"):
                    res.err("V08", f"row{idx}: Deleted row {f}={r.get(f)!r}, expected N/A")
                    deleted_bad += 1
            tcase = norm_val(r.get("test_case_id"))
            if tcase is not None and str(tcase).strip() != DELETED_TESTCASE:
                res.err("V08", f"row{idx}: Deleted row test_case_id={r.get('test_case_id')!r}, expected NA")
                deleted_bad += 1
            if str(r.get("memo", "")).strip() != "Guaranteed by other modules":
                res.err("V08", f"row{idx}: Deleted row memo={r.get('memo')!r}, expected 'Guaranteed by other modules'")
                deleted_bad += 1
    if not deleted_bad and not any(e.startswith("[V07]") for e in res.errors):
        res.ok("V07", "all flag values valid")
        res.ok("V08", "all Deleted rows use the fixed boilerplate")
    if not any(e.startswith("[V07]") for e in res.errors):
        res.ok("V07", "all flag values valid")

    # V09
    for idx, r in enumerate(reqs, start=3):
        if r.get("module") and r["module"] not in CATEGORIES_OK:
            res.warn("V09", f"row{idx}: module={r['module']!r} (expected 'Software Requirements' or project-specific')")
        cat = r.get("category")
        if cat and flag_not_deleted(r):
            if cat in CATEGORIES_L_OK:
                pass
            elif "," in str(cat):
                res.err("V09", f"row{idx}: category uses half-width comma: {cat!r} (must be full-width ，)")
            else:
                res.warn("V09", f"row{idx}: category={cat!r} not in the standard set")
        if r.get("asil") and r["asil"] not in ASIL_OK:
            res.err("V09", f"row{idx}: asil={r['asil']!r} not in {sorted(ASIL_OK)}")
        if r.get("priority") is not None and str(r["priority"]) not in ("1", "2", "3", "N/A", "None"):
            res.err("V09", f"row{idx}: priority={r['priority']!r} not 1-3")

    # V10/V11
    srs_reqids = []
    for ch in proj.get("srs", {}).get("chapters", []):
        for sec in ch.get("sections", []):
            srs_reqids.extend(sec.get("req_ids", []))
            if not sec.get("desc_en") or not sec.get("desc_cn"):
                res.warn("V11", f"SRS section '{sec.get('title_en','?')[:40]}': desc_en={len(sec.get('desc_en', []))} desc_cn={len(sec.get('desc_cn', []))} (bilingual incomplete)")
    missing_in_srs = sorted(set(req_ids) - set(srs_reqids))
    if missing_in_srs:
        res.err("V10", f"{len(missing_in_srs)} req_ids missing from SRS chapters 2/3: {missing_in_srs[:10]}{'...' if len(missing_in_srs)>10 else ''}")
    else:
        res.ok("V10", f"all {len(set(req_ids))} req_ids covered in SRS")
    phantom = sorted(set(srs_reqids) - set(req_ids) - {"N/A"})
    if phantom:
        res.err("V10", f"SRS references req_ids not in Excel: {phantom}")

    # V12
    all_ids_text = "\n".join(str(r.get("req_id", "")) for r in reqs)
    for i, rk in enumerate(risks, start=4):
        for rid in re.findall(r"[A-Za-z0-9]+_\d+-R\d+", str(rk.get("req_id", ""))):
            if rid not in req_ids:
                res.err("V12", f"risk row{i}: req_id {rid} not found in requirements")

    # V13
    for idx, r in enumerate(reqs, start=3):
        for f in DATE_FIELDS:
            d = parse_date(r.get(f))
            if d is False:
                res.warn("V13", f"row{idx}: {f}={r.get(f)!r} unparseable")
        ra, rel = parse_date(r.get("ra_deadline")), parse_date(r.get("release_time"))
        if isinstance(ra, datetime.datetime) and isinstance(rel, datetime.datetime) and ra > rel:
            res.warn("V13", f"row{idx}: ra_deadline {r['ra_deadline']} after release_time {r['release_time']}")

    # V16 — truncation sentinels must never reach project.json (advanced mode:
    # inventory cell caps / half-word cuts leaking into the formal deliverable)
    TRUNC_MARKS = ("…[+", " ⏎ ")
    n_trunc = 0
    def _scan_trunc(obj, path=""):
        nonlocal n_trunc
        if isinstance(obj, str):
            for m in TRUNC_MARKS:
                if m in obj:
                    res.err("V16", f"{path}: contains truncation sentinel {m!r} — "
                            "complete the text from the source document before assembly")
                    n_trunc += 1
        elif isinstance(obj, dict):
            for k, v in obj.items():
                _scan_trunc(v, f"{path}.{k}" if path else k)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                _scan_trunc(v, f"{path}[{i}]")
    _scan_trunc(proj)
    if n_trunc == 0:
        res.ok("V16", "no truncation sentinels (…[+N chars] / ⏎) in project.json")

    # V17 — template capacity (Input ≤10, Risk ≤4, history ≤11): build_excel
    # silently drops overflow; catch it at the JSON so the human decides
    n_in, n_risk, n_hist = len(inputs), len(risks), len(doc.get("history", []))
    if n_in > 10:
        res.err("V17", f"inputs {n_in} > template capacity 10 — excess silently dropped by build_excel")
    if n_risk > 4:
        res.err("V17", f"risks {n_risk} > template capacity 4 — excess silently dropped")
    if n_hist > 11:
        res.err("V17", f"history {n_hist} > template capacity 11 — excess silently dropped")
    if n_in <= 10 and n_risk <= 4 and n_hist <= 11:
        res.ok("V17", f"within template capacity (inputs {n_in}/10, risks {n_risk}/4, history {n_hist}/11)")


def validate_worklist(proj, wl_path, res):
    """V18 (进阶模式): project.json must match worklist.confirmed.json — the human
    confirmation gate's artifact. Catches the AI assembling from its own draft or
    editing requirements after confirmation."""
    try:
        with open(wl_path, encoding="utf-8") as f:
            wl = json.load(f)
    except Exception as e:
        res.err("V18", f"cannot read {wl_path}: {e} — Step A3 (human confirmation) not evidenced")
        return
    reqs = proj.get("requirements", [])
    by_rid = {str(r.get("req_id")): r for r in reqs if r.get("req_id")}
    wl_in = [w for w in wl if str(w.get("scope", "")).lower() not in ("out", "deleted")]
    # 1) every confirmed in-scope row must be present in project.json
    missing = [w.get("req_id") for w in wl_in if str(w.get("req_id")) not in by_rid]
    if missing:
        res.err("V18", f"{len(missing)} confirmed in-scope req_id(s) absent from project.json "
                f"(post-confirmation edits?): {missing[:8]}")
    # 2) or_id / flag(scope) / asil must agree row-by-row
    mismatch = []
    for w in wl_in:
        r = by_rid.get(str(w.get("req_id")))
        if not r:
            continue
        if str(w.get("or_id", "")) and str(r.get("or_id", "")) != str(w["or_id"]):
            mismatch.append(f"{w['req_id']} or_id {r.get('or_id')}≠{w['or_id']}")
        if r.get("flag") not in ("Original", "Add", "Modified"):
            # confirmed in-scope row must not be Deleted (or bogus) downstream
            mismatch.append(f"{w['req_id']} flag {r.get('flag')} but confirmed scope=in")
        if w.get("asil") and str(r.get("asil", "")) != str(w["asil"]):
            mismatch.append(f"{w['req_id']} asil {r.get('asil')}≠{w['asil']}")
    if mismatch:
        res.err("V18", f"{len(mismatch)} field mismatch(es) vs confirmed worklist: {mismatch[:8]}")
    # 3) extra rows in project.json not in confirmed worklist (either flag)
    wl_all_rids = {str(w.get("req_id")) for w in wl if w.get("req_id")}
    extra = [r.get("req_id") for r in reqs
             if r.get("req_id") and r.get("flag") != "Deleted"
             and str(r["req_id"]) not in wl_all_rids]
    if extra:
        res.err("V18", f"{len(extra)} req_id(s) in project.json not in confirmed worklist "
                f"(assembled from draft?): {extra[:8]}")
    # 4) Deleted rows can't be told apart by req_id (all N/A) — compare by
    #    (input, chapter, no) provenance instead, so a dropped Deleted row is caught
    from collections import Counter
    wl_out_keys = Counter((wl_key_val(w.get("source")), wl_key_val(w.get("chapter")),
                           wl_key_val(w.get("orig_id"))) for w in wl
                          if str(w.get("scope", "")).lower() in ("out", "deleted"))
    pj_del_keys = Counter((wl_key_val(r.get("input")), wl_key_val(r.get("chapter")),
                           wl_key_val(r.get("no"))) for r in reqs
                          if r.get("flag") == "Deleted")
    if wl_out_keys != pj_del_keys:
        gone = wl_out_keys - pj_del_keys
        added = pj_del_keys - wl_out_keys
        res.err("V18", f"Deleted-row provenance mismatch vs confirmed worklist: "
                f"missing {list(gone)[:4]} / extra {list(added)[:4]}")
    if not any(e.startswith("[V18]") for e in res.errors):
        res.ok("V18", f"project.json matches confirmed worklist "
                f"({len(wl)} confirmed rows, {len(wl_in)} in-scope)")


def validate_roundtrip(proj, excel_path, docx_path, res):
    """Re-extract generated files and compare against the source JSON."""
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from extract_excel import extract_excel as ex

    if excel_path:
        got = ex(excel_path)
        for key in ("inputs", "requirements", "risks"):
            a = [norm_row(x) for x in proj.get(key, [])]
            b = [norm_row(x) for x in got.get(key, [])]
            # pairwise compare on the union key set: JSON may omit optional
            # keys the extractor always emits; only VALUE differences count
            diff_found = False
            for i in range(max(len(a), len(b))):
                x = a[i] if i < len(a) else None
                y = b[i] if i < len(b) else None
                if (x is None) != (y is None):
                    res.err("V14", f"excel round-trip {key} length {len(a)} vs {len(b)} "
                            f"(extra {'source' if x is not None else 'extracted'} row at [{i}])")
                    diff_found = True
                    break
                nx, ny = norm_row_pair(x, y)
                if nx != ny:
                    diff = {k: (nx.get(k), ny.get(k)) for k in set(nx) | set(ny)
                            if nx.get(k) != ny.get(k)}
                    res.err("V14", f"excel round-trip {key}[{i}] differs: {list(diff.items())[:3]}")
                    diff_found = True
                    break
            if not diff_found:
                res.ok("V14", f"excel round-trip {key} identical ({len(a)} rows)")
        a_hist = [norm_history(x) for x in proj.get("document", {}).get("history", [])]
        b_hist = [norm_history(x) for x in got.get("document", {}).get("history", [])]
        if a_hist != b_hist:
            res.err("V14", "excel round-trip document history differs")
        else:
            res.ok("V14", "excel round-trip history identical")

    if docx_path:
        from docx import Document
        doc = Document(docx_path)
        text = "\n".join(p.text for p in doc.paragraphs)
        # every non-Deleted req_id must appear
        for r in proj.get("requirements", []):
            rid = r.get("req_id")
            if r.get("flag") != "Deleted" and rid and rid not in text:
                res.err("V15", f"req_id {rid} not found in generated DOCX")
        # every SRS section title must appear as a heading
        for ch in proj.get("srs", {}).get("chapters", []):
            for sec in ch.get("sections", []):
                if sec.get("title_en") and sec["title_en"] not in text:
                    res.err("V15", f"SRS title missing in DOCX: {sec['title_en'][:50]}")
        if not any(e.startswith("[V15]") for e in res.errors):
            res.ok("V15", "all req_ids and section titles present in DOCX")


def validate_project(proj: dict, excel_path: str = None, docx_path: str = None,
                     worklist_path: str = None) -> dict:
    """Validate a project dict in-memory, for programmatic use.

    Returns {"errors": [...], "warnings": [...], "passed": [...], "report": str}.
    """
    res = Result()
    validate_json(proj, res)
    if worklist_path:
        validate_worklist(proj, worklist_path, res)
    if excel_path or docx_path:
        validate_roundtrip(proj, excel_path, docx_path, res)

    lines = [f"# SWE1 Validation Report — {proj.get('project', {}).get('name', '')}",
             f"_generated: {datetime.datetime.now().isoformat(timespec='seconds')}_", ""]
    if res.errors:
        lines.append(f"## ✗ ERRORS ({len(res.errors)})")
        lines += [f"- {e}" for e in res.errors]
    if res.warnings:
        lines.append(f"## ⚠ WARNINGS ({len(res.warnings)})")
        lines += [f"- {w}" for w in res.warnings]
    lines.append(f"## ✓ PASSED ({len(res.passed)})")
    lines += [f"- {p}" for p in res.passed]
    report = "\n".join(lines)

    return {"errors": res.errors, "warnings": res.warnings,
            "passed": res.passed, "report": report,
            "has_errors": len(res.errors) > 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--excel")
    ap.add_argument("--docx")
    ap.add_argument("--worklist", help="worklist.confirmed.json — V18 cross-check (进阶模式)")
    ap.add_argument("--report")
    args = ap.parse_args()

    with open(args.project, encoding="utf-8") as f:
        proj = json.load(f)

    res = Result()
    validate_json(proj, res)
    if args.worklist:
        validate_worklist(proj, args.worklist, res)
    if args.excel or args.docx:
        validate_roundtrip(proj, args.excel, args.docx, res)

    lines = [f"# SWE1 Validation Report — {proj.get('project', {}).get('name', '')}",
             f"_generated: {datetime.datetime.now().isoformat(timespec='seconds')}_", ""]
    if res.errors:
        lines.append(f"## ✗ ERRORS ({len(res.errors)})")
        lines += [f"- {e}" for e in res.errors]
    if res.warnings:
        lines.append(f"## ⚠ WARNINGS ({len(res.warnings)})")
        lines += [f"- {w}" for w in res.warnings]
    lines.append(f"## ✓ PASSED ({len(res.passed)})")
    lines += [f"- {p}" for p in res.passed]
    report = "\n".join(lines)

    print(report)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(report + "\n")
        print(f"\nreport saved: {args.report}", file=sys.stderr)
    sys.exit(1 if res.errors else 0)


if __name__ == "__main__":
    main()
