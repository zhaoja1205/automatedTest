#!/usr/bin/env python3
"""Fill the SWE1 SRS Word template from a project JSON file.

Usage:
    python3 build_docx.py --project project.json --output "ProjectX_SRS.docx"

The template keeps the fixed skeleton (cover, history/review tables, chapter-1
headings, TOC field, headers/footers, template-control table). This script:
  1. substitutes {{PLACEHOLDER}} values in cover / chapter-1 / headers / tables
  2. regenerates chapters 2/3/4 body content from the JSON requirements

Chapter structure per requirement (matches Wukong source document):
  H2  <n>.<i> <Title EN> / <Title CN>
      Requirement Number需求编号：<ReqIDs>
  H3  <n>.<i>.1 Functional Description功能描述  (EN paragraphs, then CN paragraphs)
  H3  <n>.<i>.2 Operation description操作描述    (EN, then CN)
  H3  <n>.<i>.3 Security level安全等级           (EN sentence + CN sentence)
  H3  <n>.<i>.4 Analysis分析                     (EN, then CN)
"""
import argparse
import copy
import json
import sys
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

TEMPLATE = Path(__file__).resolve().parent / "aspice_templates" / "srs_template.docx"

# Body-level paragraph indices in the template
P_COVER_TITLE = 3
P_COVER_VERSION = 5
P_OVERVIEW_EN = 53
P_OVERVIEW_CN = 54

# Table indices in the template
T_HISTORY = 0
T_REVIEW = 1
T_DEPENDENCIES = 2
T_STANDARDS = 3
T_REFDOCS = 4
T_ENV = 5


def set_para_text(p, text):
    """Replace paragraph text keeping the first run's formatting."""
    runs = p.runs
    if not runs:
        if text:
            p.add_run(text)
        return
    runs[0].text = text
    for r in runs[1:]:
        r.text = ""


def fill_cell(cell, lines):
    """Write lines into a table cell: first line into the existing paragraph,
    extra lines as cloned paragraphs (keeps cell font)."""
    if not isinstance(lines, (list, tuple)):
        lines = [lines]
    lines = [str(l) if l is not None else "" for l in lines]
    base = cell.paragraphs[0]
    set_para_text(base, lines[0])
    for p in cell.paragraphs[1:]:
        p._p.getparent().remove(p._p)
    prev = base._p
    for line in lines[1:]:
        new_el = copy.deepcopy(base._p)
        np = Paragraph(new_el, cell)
        set_para_text(np, line)
        prev.addnext(new_el)
        prev = new_el


def unmerge_table(t):
    """Remove all vertical merges so every logical row owns its own cells.
    The template's dependency table merges rows 2-3 in columns 0-1; writing
    both rows would hit the same tc and silently overwrite row 2's data."""
    for tc in t._tbl.iter(qn('w:tc')):
        tcPr = tc.find(qn('w:tcPr'))
        if tcPr is not None:
            for vm in tcPr.findall(qn('w:vMerge')):
                tcPr.remove(vm)
    # re-create python-docx row/cell views (tc -> row mapping changed)


def fill_table_rows(t, rows, header=True):
    """Fill table rows with data; row 0 is header if header=True.
    Grows the table by deep-copying the last data row (keeps borders/fonts)."""
    unmerge_table(t)
    for i, rowdata in enumerate(rows):
        r = (1 if header else 0) + i
        while r >= len(t.rows):
            t._tbl.append(copy.deepcopy(t.rows[-1]._tr))  # clone last row XML (styles intact)
        vals = rowdata if isinstance(rowdata, (list, tuple)) else [rowdata]
        for c in range(min(len(t.columns), len(vals))):
            fill_cell(t.cell(r, c), vals[c])


def style_samples(doc):
    """One representative styled paragraph per style, to clone formatting from.
    Prefers paragraphs with text; falls back to any paragraph of that style
    (style lives in the paragraph's pPr, so an empty paragraph still clones
    correctly)."""
    samples = {}
    for p in doc.paragraphs:
        name = p.style.name
        if name not in samples:
            samples[name] = p
        elif not samples[name].text.strip() and p.text.strip():
            samples[name] = p
    return samples


def clone_paragraph_after(anchor_el, sample_p, text):
    """Deep-copy sample paragraph XML, set text, strip drawings/bookmarks, insert after anchor."""
    new_el = copy.deepcopy(sample_p._p)
    for tag in ('w:drawing', 'w:bookmarkStart', 'w:bookmarkEnd'):
        for el in new_el.findall('.//' + qn(tag)):
            el.getparent().remove(el)
    p = Paragraph(new_el, sample_p._parent)
    set_para_text(p, text)
    anchor_el.addnext(new_el)
    return new_el


def requirement_block(anchor_el, styles, num, sec, kind):
    """Append one requirement's 4-subsection block; returns last element."""
    title_en = sec.get("title_en") or sec.get("sw_req_desc", "")
    title_cn = sec.get("title_cn") or ""
    title = f"{title_en} / {title_cn}" if title_cn and title_cn != title_en else title_en
    anchor_el = clone_paragraph_after(anchor_el, styles["Heading 2"], f"{num} {title}")
    ids = [i for i in (sec.get("req_ids") or [sec.get("req_id", "")]) if i]
    anchor_el = clone_paragraph_after(anchor_el, styles["Body Text"],
                                      f"Requirement Number需求编号：{'、'.join(ids)}")
    sub1 = ("Requirement description需求描述" if kind == "nonfunctional"
            else "Functional Description功能描述")
    anchor_el = clone_paragraph_after(anchor_el, styles["Heading 3"], f"{num}.1 {sub1}")
    for line in sec.get("desc_en", []):
        anchor_el = clone_paragraph_after(anchor_el, styles["Body Text"], line)
    for line in sec.get("desc_cn", []):
        anchor_el = clone_paragraph_after(anchor_el, styles["Body Text"], line)
    anchor_el = clone_paragraph_after(anchor_el, styles["Heading 3"], f"{num}.2 Operation description操作描述")
    for line in sec.get("op_en", []):
        anchor_el = clone_paragraph_after(anchor_el, styles["Body Text"], line)
    for line in sec.get("op_cn", []):
        anchor_el = clone_paragraph_after(anchor_el, styles["Body Text"], line)
    anchor_el = clone_paragraph_after(anchor_el, styles["Heading 3"], f"{num}.3 Security level安全等级")
    asil = sec.get("asil") or "QM"
    anchor_el = clone_paragraph_after(anchor_el, styles["Body Text"],
                                      f"The security level of this module is determined to be {asil}.")
    anchor_el = clone_paragraph_after(anchor_el, styles["Body Text"],
                                      f"本模块的安全等级判定为 {asil}级。")
    anchor_el = clone_paragraph_after(anchor_el, styles["Heading 3"], f"{num}.4 Analysis分析")
    for line in sec.get("analysis_en", []):
        anchor_el = clone_paragraph_after(anchor_el, styles["Body Text"], line)
    for line in sec.get("analysis_cn", []):
        anchor_el = clone_paragraph_after(anchor_el, styles["Body Text"], line)
    return anchor_el


def build_chapters(doc, proj):
    """Regenerate requirement chapters (2/3/…) from JSON, plus the generic chapter."""
    styles = style_samples(doc)
    missing = [s for s in ("Heading 1", "Heading 2", "Heading 3", "Body Text", "Normal") if s not in styles]
    if missing:
        raise RuntimeError(f"template missing styled sample paragraphs: {missing}")

    # anchor: last empty paragraph before the "Template modification control" heading
    paras = doc.paragraphs
    idx_tail = next(i for i, p in enumerate(paras) if "Template modification control" in p.text)
    anchor_el = paras[idx_tail]._p.getprevious()
    if anchor_el is None:
        anchor_el = paras[idx_tail - 1]._p

    srs = proj.get("srs", {})
    chapters = srs.get("chapters", [])
    sec_no = 1  # chapter 1 = Project Scope; first requirement chapter is 2
    for ch in chapters:
        sec_no += 1
        # Heading 1 style is auto-numbered by Word (numPr in style) — no literal number
        h1_text = f"{ch.get('title_en', '')}{ch.get('title_cn', '')}"
        anchor_el = clone_paragraph_after(anchor_el, styles["Heading 1"], h1_text)
        for line in ch.get("intro_en", []):
            anchor_el = clone_paragraph_after(anchor_el, styles["Normal"], line)
        for line in ch.get("intro_cn", []):
            anchor_el = clone_paragraph_after(anchor_el, styles["Normal"], line)
        for j, sec in enumerate(ch.get("sections", []), start=1):
            anchor_el = requirement_block(anchor_el, styles, f"{sec_no}.{j}", sec,
                                          ch.get("kind", "functional"))

    ch4 = srs.get("chapter4")
    if ch4:
        ch4_no = len(chapters) + 2  # "Other requirements" follows the requirement chapters
        anchor_el = clone_paragraph_after(anchor_el, styles["Heading 1"],
                                          ch4.get("title", "Other requirements其他需求"))
        for j, sec in enumerate(ch4.get("sections", []), start=1):
            anchor_el = clone_paragraph_after(anchor_el, styles["Heading 2"],
                                              f"{ch4_no}.{j} {sec.get('title', '')}")
            st = styles.get(sec.get("body_style", "Body Text"), styles["Body Text"])
            for line in sec.get("body", []):
                anchor_el = clone_paragraph_after(anchor_el, st, line)


def fill_front_matter(doc, proj):
    pr = proj["project"]
    pj = proj.get("document", {})

    set_para_text(doc.paragraphs[P_COVER_TITLE],
                  f"{pr['name']} Project Software Requirements Specification项目软件需求说明书")
    set_para_text(doc.paragraphs[P_COVER_VERSION], f"Version：{pj.get('version', 'V1.0')}")

    set_para_text(doc.paragraphs[P_OVERVIEW_EN], pr.get("overview_en", ""))
    set_para_text(doc.paragraphs[P_OVERVIEW_CN], pr.get("overview_cn", ""))

    hist = [[rec.get("date", ""), rec.get("version", ""), rec.get("author", ""),
             rec.get("status", ""), rec.get("description", "")]
            for rec in pj.get("history", [])]
    fill_table_rows(doc.tables[T_HISTORY], hist)

    rev = [[rec.get("version", ""), rec.get("date", ""), rec.get("reviewers", ""),
            rec.get("approver", "/"), rec.get("comments", "/")]
           for rec in pj.get("reviews", [])]
    fill_table_rows(doc.tables[T_REVIEW], rev)

    deps = [[d.get("item", ""), d.get("time", ""), d.get("description", "")]
            for d in pr.get("dependencies", [])]
    fill_table_rows(doc.tables[T_DEPENDENCIES], deps)

    # assumptions: EN/CN paragraph pairs after the "Project assumption项目假设：" label.
    # Match the CONTIGUOUS bilingual label — the 1.2 heading contains the EN and
    # CN words in separate positions ("...Project assumptions and ... 项目假设..."),
    # so only the joined form "Project assumption项目假设" is unambiguous.
    paras = doc.paragraphs
    idx = next(i for i, p in enumerate(paras)
               if "Project assumption项目假设" in p.text)
    sample = paras[idx]
    el = paras[idx]._p
    for pair in pr.get("assumptions", []):
        en, cn = pair if isinstance(pair, (list, tuple)) else (pair, "")
        if en:
            el = clone_paragraph_after(el, sample, en)
        if cn:
            el = clone_paragraph_after(el, sample, cn)

    std = [[i + 1, s] for i, s in enumerate(pr.get("standards", []))]
    fill_table_rows(doc.tables[T_STANDARDS], std)

    refs = [[i + 1, r if isinstance(r, str) else r.get("name", "")]
            for i, r in enumerate(pr.get("reference_docs", []))]
    fill_table_rows(doc.tables[T_REFDOCS], refs)

    env = pr.get("environment", [])
    t = doc.tables[T_ENV]
    for i, row in enumerate(env):
        if i >= len(t.rows):
            print(f"[WARN] env table overflow: {len(env)} rows > {len(t.rows)}, extras dropped", file=sys.stderr)
            break
        fill_cell(t.cell(i, 0), row.get("label", ""))
        fill_cell(t.cell(i, 1), row.get("value", ""))

    loc_lines = pr.get("sensor_location", [])
    if loc_lines:
        paras = doc.paragraphs
        idx = next(i for i, p in enumerate(paras) if p.text.strip().startswith("1.5"))
        el = paras[idx]._p
        for line in loc_lines:
            el = clone_paragraph_after(el, paras[P_OVERVIEW_CN], line)

    header_text = (f"{pr['name']} Project Software Requirements Specification项目软件需求说明书"
                   f"                                             "
                   f"{pj.get('doc_number_word') or pj.get('doc_number', '')}")
    for sec in doc.sections:
        for p in sec.header.paragraphs:
            if "{{PROJECT}}" in p.text:
                set_para_text(p, header_text)


def precheck(proj):
    """Fail fast with a readable message instead of a KeyError traceback."""
    pr, pj = proj.get("project"), proj.get("document")
    problems = []
    if not isinstance(pr, dict) or not pr.get("name"):
        problems.append("project.name is required")
    if not isinstance(pj, dict) or not pj.get("doc_number"):
        problems.append("document.doc_number is required (Word header falls back to it)")
    if problems:
        raise SystemExit("ERROR: invalid project JSON:\n  - " + "\n  - ".join(problems))


def build(project: dict, output: str, template: str = None) -> str:
    """Build SRS Word doc from a project dict (in-memory), for programmatic use."""
    precheck(project)
    tpl = template or str(TEMPLATE)
    doc = Document(tpl)
    fill_front_matter(doc, project)
    build_chapters(doc, project)
    doc.save(output)
    return output


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--template", default=str(TEMPLATE))
    args = ap.parse_args()

    with open(args.project, encoding="utf-8") as f:
        proj = json.load(f)
    build(proj, args.output, args.template)
    print(f"OK: {args.output}")


if __name__ == "__main__":
    main()
