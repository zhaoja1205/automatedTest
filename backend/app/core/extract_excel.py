#!/usr/bin/env python3
"""Extract a project JSON from an existing SWE1 Excel (+optional SRS Word doc).

Usage:
    python3 extract_excel.py --source "ProjectX_Detailed Software Requirements Table需求详细表.xlsx" \
                             [--srs "ProjectX_SRS.docx"] --output project.json

Reverse of build_excel.py: reads Cover / Document record / Input / Requirement /
Risk sheets (and SRS chapters if --srs given) and emits the project JSON
defined in references/data_model.md.
"""
import argparse
import datetime
import json
import re

import openpyxl
from docx import Document

REQ_COLUMNS = {
    "A": "input", "B": "chapter", "C": "no", "D": "content", "E": "flag",
    "F": "or_id", "G": "or_desc", "H": "req_id", "I": "sw_req_desc",
    "J": "test_case_id", "K": "module", "L": "category", "M": "asil",
    "N": "correctness", "O": "feasibility", "P": "exception", "Q": "priority",
    "R": "release_time", "S": "ra_deadline", "T": "actual_time",
    "U": "release_version", "V": "owner", "W": "memo", "X": "arch_doc",
}

CJK = re.compile(r"[一-鿿]")


def cell_value(v):
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.strftime("%Y-%m-%d")
    return v


def split_en_cn(text):
    """Split 'EN part / 中文部分' or 'EN部分中文' into (en, cn)."""
    if " / " in text:
        en, cn = text.split(" / ", 1)
        return en.strip(), cn.strip()
    m = re.search(r"[一-鿿]", text)
    if m:
        return text[:m.start()].strip(), text[m.start():].strip()
    return text.strip(), ""


def mostly_en(text):
    """True if the text reads as English. CJK ratio is decisive: even a short
    Chinese clause among long API names marks the sentence as Chinese."""
    cjk = len(CJK.findall(text))
    return cjk == 0 or cjk < max(2, len(text) // 40)


# ---------------------------------------------------------------- Excel side

def extract_excel(src):
    wb = openpyxl.load_workbook(src, data_only=True)
    proj = {"project": {}, "document": {}, "inputs": [],
            "requirements": [], "risks": [],
            "srs": {"chapters": [], "chapter4": None}}

    ws = wb["Cover 文件封面"]
    proj["document"]["doc_number"] = (ws["A3"].value or "").replace("文件编号：", "").strip()
    m = re.match(r"(.+?) Detailed Software Requirements Table", ws["A15"].value or "")
    proj["project"]["name"] = m.group(1).strip() if m else ""
    proj["document"]["version"] = (ws["A17"].value or "").replace("Version/版本：", "").strip()

    ws = wb["Document record文件修改控制"]
    hist = []
    for r in range(4, 15):
        ver = ws.cell(row=r, column=2).value
        if not ver:
            break
        hist.append({
            "version": ver,
            "description": cell_value(ws.cell(row=r, column=3).value),
            "date": cell_value(ws.cell(row=r, column=4).value),
            "author": cell_value(ws.cell(row=r, column=5).value),
            "reviewers": cell_value(ws.cell(row=r, column=6).value),
            "approver": cell_value(ws.cell(row=r, column=7).value),
        })
    proj["document"]["history"] = hist

    ws = wb["Input 输入"]
    proj["project"]["module_name"] = ws["C2"].value or ""
    for r in range(6, 16):
        name = ws.cell(row=r, column=3).value
        if name:
            proj["inputs"].append({"name": name})

    ws = wb["Requirement 需求"]
    for r in range(3, ws.max_row + 1):
        if not any(ws.cell(row=r, column=c).value for c in range(1, 25)):
            continue
        req = {}
        for col, field in REQ_COLUMNS.items():
            v = cell_value(ws[f"{col}{r}"].value)
            if field in ("no", "test_case_id") and isinstance(v, str) and "\n" in v:
                v = [line for line in v.split("\n") if line.strip()]
            req[field] = v
        proj["requirements"].append(req)

    ws = wb["Risk 风险"]
    for r in range(4, 8):
        if not ws.cell(row=r, column=2).value:
            continue
        proj["risks"].append({
            "req_id": cell_value(ws.cell(row=r, column=2).value),
            "function": cell_value(ws.cell(row=r, column=3).value),
            "risk": cell_value(ws.cell(row=r, column=4).value),
            "solution": cell_value(ws.cell(row=r, column=5).value),
            "owner": cell_value(ws.cell(row=r, column=6).value),
        })
    return proj


# ---------------------------------------------------------------- Word side

H2_RE = re.compile(r"^(\d+)\.(\d+)\s+(.*)$")
H3_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)\s+(.*)$")


def extract_srs(src, proj):
    """Extract requirement chapters (four-subsection structure) and the generic
    tail chapter from an existing SRS docx.

    Single collection pass, structural classification afterwards:
      - every H1 after the first becomes a raw chapter (first H1 = Project
        Scope front matter, skipped);
      - a section is a REQUIREMENT section iff it contains x.y.z H3
        subsections; chapters containing any such section are requirement
        chapters, the remaining chapters merge into the generic chapter4;
      - chapter kind: first requirement chapter = functional, the rest
        nonfunctional (matches the ch2/ch3 convention).

    Positional hardcoding ("chapter 2/3 vs chapter 4") is deliberately NOT
    used — it breaks for projects with 1 or 3 requirement chapters."""
    doc = Document(src)
    chapters = []        # [{"title", "intro_en", "intro_cn", "sections": [...]}]
    cur_ch = None
    cur_sec = None
    cur_sub = None       # "h2body"|"desc"|"op"|"asil"|"analysis"|None

    for p in doc.paragraphs:
        text = p.text.strip()
        if not text:
            continue
        style = p.style.name

        # sentinel: the template-control table's heading ends the document body;
        # beyond it there is only fixed boilerplate that must not be extracted
        if "Template modification control" in text:
            break

        if style == "Heading 1":
            cur_ch = {"title": re.sub(r"^\d+\s*", "", text),
                      "intro_en": [], "intro_cn": [], "sections": []}
            chapters.append(cur_ch)
            cur_sec, cur_sub = None, None
            continue
        if cur_ch is None:          # cover / TOC / history tables before chapter 1
            continue

        if style == "Heading 2":
            m = H2_RE.match(text)
            if not m:
                cur_sec, cur_sub = None, None
                continue
            en, cn = split_en_cn(m.group(3).strip())
            # has_h3 is decided later (first H3 under this section flips it);
            # body/req_ids both filled — assembly picks by has_h3
            cur_sec = {"title": m.group(3).strip(), "title_en": en, "title_cn": cn,
                       "req_ids": [], "desc_en": [], "desc_cn": [],
                       "op_en": [], "op_cn": [], "asil": None,
                       "analysis_en": [], "analysis_cn": [],
                       "body": [], "has_h3": False}
            cur_ch["sections"].append(cur_sec)
            cur_sub = "h2body"
            continue

        if style == "Heading 3":
            m = H3_RE.match(text)
            if m and cur_sec is not None:
                cur_sec["has_h3"] = True
                cur_sub = {1: "desc", 2: "op", 3: "asil", 4: "analysis"}.get(int(m.group(3)))
                # the .1 subsection wording IS the chapter's kind:
                # "Requirement description需求描述" => nonfunctional, else functional
                if int(m.group(3)) == 1 and "Requirement description" in text:
                    cur_sec["nonfunctional_style"] = True
            continue

        # ---- body paragraphs ----
        if cur_sec is None:
            (cur_ch["intro_cn"] if CJK.search(text) and not mostly_en(text)
             else cur_ch["intro_en"]).append(text)
        elif cur_sub == "h2body":
            # directly under H2: "Requirement Number需求编号：..." for req
            # sections, plain content for generic sections
            ids = re.findall(r"[A-Za-z]+_\d+-R\d+", text)
            if ids:
                cur_sec["req_ids"].extend(ids)
            cur_sec["body"].append(text)
        elif cur_sub == "desc":
            (cur_sec["desc_cn"] if CJK.search(text) and not mostly_en(text)
             else cur_sec["desc_en"]).append(text)
        elif cur_sub == "op":
            (cur_sec["op_cn"] if CJK.search(text) and not mostly_en(text)
             else cur_sec["op_en"]).append(text)
        elif cur_sub == "asil":
            if not cur_sec["asil"]:
                m2 = re.search(r"QM|ASIL\s*[A-D]", text)
                if m2:
                    cur_sec["asil"] = m2.group(0)
        elif cur_sub == "analysis":
            (cur_sec["analysis_cn"] if CJK.search(text) and not mostly_en(text)
             else cur_sec["analysis_en"]).append(text)

    # ---- classification & assembly ----
    body_chapters = chapters[1:]           # chapters[0] = Project Scope, skipped
    req_chapters = [ch for ch in body_chapters
                    if any(sec["has_h3"] for sec in ch["sections"])]
    generic_chapters = [ch for ch in body_chapters
                        if not any(sec["has_h3"] for sec in ch["sections"])]

    out = []
    for i, ch in enumerate(req_chapters):
        en, cn = split_en_cn(ch["title"])
        kind = ("nonfunctional"
                if any(sec.get("nonfunctional_style") for sec in ch["sections"])
                else "functional")
        out.append({"title_en": en, "title_cn": cn,
                    "kind": kind,
                    "intro_en": ch["intro_en"], "intro_cn": ch["intro_cn"],
                    "sections": ch["sections"]})
    proj["srs"]["chapters"] = out

    if generic_chapters:
        ch4 = {"title": generic_chapters[0]["title"], "sections": []}
        for ch in generic_chapters:
            for sec in ch["sections"]:
                ch4["sections"].append({"title": sec["title"],
                                        "body": sec["body"]})
        proj["srs"]["chapter4"] = ch4
    else:
        proj["srs"]["chapter4"] = None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="existing requirements-table xlsx")
    ap.add_argument("--srs", help="existing SRS docx (optional)")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    proj = extract_excel(args.source)
    if args.srs:
        extract_srs(args.srs, proj)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(proj, f, ensure_ascii=False, indent=2)
    print(f"OK: {args.output}")
    print(f"    requirements: {len(proj['requirements'])}, inputs: {len(proj['inputs'])}, "
          f"risks: {len(proj['risks'])}, srs chapters: {len(proj['srs']['chapters'])}, "
          f"ch4 sections: {len(proj['srs']['chapter4']['sections']) if proj['srs']['chapter4'] else 0}")


if __name__ == "__main__":
    main()
