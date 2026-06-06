#!/usr/bin/env python3
"""Deterministic Markdown renderer for an epiphany-plan plan_document JSON.

Parity guarantee: when a run must produce BOTH formats (human review + executor), the JSON is the
CANONICAL artifact and the Markdown is rendered FROM it with this tool — so the two cannot drift.
The emitted Markdown follows modules/N-emit.md's structure and is engineered so that a defect visible
in the JSON (a hollow step, a dropped edge, a missing executor field) is ALSO visible in the Markdown
(round-trip-faithful), and so plan_verify.py's md path reaches the same verdict as the json path.

    python3 tools/render_markdown.py <plan.json> [-o plan.md]   # default: stdout

Hardened after adversarial audit:
- bare-string dependencies render as a PARSEABLE default build edge (kind: ordering · edge_class:
  ordering) so the edge survives the md graph checks instead of vanishing as `(unspecified)`.
- empty `actions`/`acceptance_criteria` render an explicit `(none)` marker (plan_verify md check-1
  flags it) — a naked step cannot be laundered into a clean md.
- `plan_meta.target_profile`/`harness_forge` are emitted unconditionally (executor pack survives).
- table cells + field values are escaped (`|`, newlines) so content cannot corrupt structure.
- executor-handshake envelope fields (blocking_defects/structural_faults/build_order/...) get sections.
"""
from __future__ import annotations
import argparse, json, sys


def _list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _inline(s):
    """Sanitise a value for inline Markdown: collapse newlines, neutralise a leading `### ` (so an
    embedded heading cannot mint a phantom step block)."""
    s = "" if s is None else str(s)
    s = s.replace("\r", " ").replace("\n", " ").strip()
    s = s.lstrip("#").lstrip() if s.lstrip().startswith("#") else s
    return s


def _cell(s):
    """Escape a value for a Markdown table cell."""
    return _inline(s).replace("|", "\\|")


def _fmt_dep(d):
    if isinstance(d, str):
        # bare-string dep has no kind/edge_class; render a PARSEABLE default build edge so the
        # dependency survives plan_verify's md graph checks (rather than vanishing). The class is a
        # neutral build-order default; normalise the canonical JSON to typed deps to preserve exactness.
        return f"  - `{_inline(d)}` — kind: ordering · edge_class: ordering"
    on = _inline(d.get("on", "?"))
    kind = _inline(d.get("kind", "ordering")) or "ordering"
    ec = _inline(d.get("edge_class", "ordering")) or "ordering"
    return f"  - `{on}` — kind: {kind} · edge_class: {ec}"


def _fmt_ic(c):
    if isinstance(c, str):
        return f"  - {_inline(c)}"
    bits = []
    if c.get("id"):
        bits.append(f"`{_inline(c['id'])}`")
    bits.append(_inline(c.get("assert", "")))
    if c.get("status"):
        bits.append(f"[status: {_inline(c['status'])}]")
    return "  - " + " ".join(b for b in bits if b)


def render(doc) -> str:
    pm = doc.get("plan_meta", {})
    L = []
    title = pm.get("title") or pm.get("plan_id") or "Execution Plan"
    L.append(f"# {_inline(title)}")
    L.append("")
    consumers = ", ".join(_inline(c) for c in _list(pm.get("consumers"))) or "epiphany-executor, agent-reading-directly"
    L.append(f"> **plan_id:** {_inline(pm.get('plan_id','?'))} · **schema:** {_inline(pm.get('schema','epiphany-plan.plan_document.v1'))} "
             f"· **source_spec:** {_inline(pm.get('source_spec','?'))} · "
             f"**dual_mode:** {str(pm.get('dual_mode', True)).lower()} · **consumers:** {consumers}")
    meta2 = []
    if pm.get("generated_by"):
        meta2.append(f"**generated_by:** {_inline(pm['generated_by'])}")
    # target_profile UNCONDITIONAL (executor reads it to select the harness-forge accommodation)
    meta2.append(f"**target_profile:** {_inline(pm.get('target_profile', 'generic'))}")
    L.append("> " + " · ".join(meta2))
    L.append("")

    # harness/forge executor context-pack — must survive the round-trip (N-emit.md mandate)
    hf = pm.get("harness_forge")
    if hf:
        L.append("## Harness/Forge Context")
        if isinstance(hf, dict):
            for k, v in hf.items():
                if isinstance(v, list):
                    L.append(f"- **{k}:** " + "; ".join(_inline(x) for x in v))
                elif isinstance(v, dict):
                    L.append(f"- **{k}:** " + "; ".join(f"{kk}={_inline(vv)}" for kk, vv in v.items()))
                else:
                    L.append(f"- **{k}:** {_inline(v)}")
        else:
            L.append(f"- {_inline(hf)}")
        L.append("")

    cv = doc.get("coverage_verdict", {})
    dec = cv.get("decision")
    L += ["## Coverage Verdict",
          f"- **decision:** {_inline(dec) if dec else 'MISSING (no decision in source)'}",
          f"- **blocking:** {str(cv.get('blocking', True)).lower()}",
          f"- **rationale:** {_inline(cv.get('rationale','(none)'))}", ""]

    sv = doc.get("structural_verdict")
    L.append("## Structural Verdict")
    if isinstance(sv, dict):
        L.append(f"- **decision:** {_inline(sv.get('decision','?'))}")
        for c in _list(sv.get("checks")):
            L.append(f"  - {_inline(c)}")
    else:
        L.append("_(added by plan_verify; pending on first emit)_")
    L.append("")

    # executor-handshake envelope fields — emit so they survive (parity with N-emit.md "always emit")
    if "blocking_defects" in doc or "structural_faults" in doc:
        L.append("## Gate Status (executor handshake)")
        L.append(f"- **blocking_defects:** " + (", ".join(_inline(x) for x in _list(doc.get('blocking_defects'))) or "[] (none — execution-ready)"))
        L.append(f"- **structural_faults:** " + (", ".join(_inline(x) for x in _list(doc.get('structural_faults'))) or "[] (none)"))
        bo = [s for s in _list(doc.get("build_order")) if isinstance(s, str)]
        L.append(f"- **build_order:** " + (", ".join(bo) or "(see Execution Order)"))
        L.append("")

    gi = _list(pm.get("global_invariants"))
    if gi:
        L.append("## Global Invariants")
        for g in gi:
            L.append(f"- {_inline(g)}")
        L.append("")

    L.append("## Execution Notes")
    for n in _list(pm.get("execution_notes")) or ["(none)"]:
        L.append(f"- {_inline(n)}")
    oa = _list((doc.get("coverage_verdict") or {}).get("open_assumptions"))
    for n in oa:
        L.append(f"- (assumption) {_inline(n)}")
    L.append("")

    L.append("## Requirement Ledger")
    L.append("| obligation | covered_by |")
    L.append("|---|---|")
    for row in doc.get("requirement_ledger", []) or []:
        if isinstance(row, dict):
            cb = ", ".join(_cell(c) for c in _list(row.get("covered_by")))
            L.append(f"| {_cell(row.get('obligation','?'))} | {cb} |")
    L.append("")

    L += ["## Graph",
          f"- **roots:** {', '.join(_inline(x) for x in _list(doc.get('roots'))) or '(none)'}",
          f"- **leaves:** {', '.join(_inline(x) for x in _list(doc.get('leaves'))) or '(none)'}",
          f"- **terminal_milestones:** {', '.join(_inline(x) for x in _list(doc.get('terminal_milestones'))) or '(none)'}"]
    if doc.get("graph_notes"):
        L.append(f"- **graph_notes:** {_inline(doc['graph_notes'])}")
    L.append("")

    L.append("## Execution Order")
    order = doc.get("execution_order") or doc.get("build_order") or []
    order = [s for s in order if isinstance(s, str)]
    for i, s in enumerate(order, 1):
        L.append(f"{i}. {_inline(s)}")
    L.append("")

    L.append("## Steps")
    L.append("")
    for s in doc.get("steps", []):
        if not isinstance(s, dict):
            continue
        goal = s.get("goal", "")
        one_line = _inline(goal).split(". ")[0][:90]
        L.append(f"### {_inline(s.get('step_id','?'))} — {one_line}")
        if s.get("phase"):
            L.append(f"- **phase:** {_inline(s['phase'])}")
        L.append(f"- **goal:** {_inline(goal) or '(MISSING)'}")
        L.append("- **actions:**")
        acts = _list(s.get("actions"))
        if acts:
            for j, a in enumerate(acts, 1):
                L.append(f"  {j}. {_inline(a)}")
        else:
            L.append("  - (none)")            # surfaced so md check-1 flags the empty required field
        L.append(f"- **inputs:** {', '.join(_inline(x) for x in _list(s.get('inputs'))) or '(none)'}")
        L.append(f"- **outputs:** {', '.join(_inline(x) for x in _list(s.get('outputs'))) or '(none)'}")
        L.append("- **dependencies:**")
        deps = _list(s.get("dependencies"))
        if deps:
            for d in deps:
                L.append(_fmt_dep(d))
        else:
            L.append("  - (none)")
        L.append("- **integration_checks:**")
        ics = s.get("integration_checks")
        ics = ics if isinstance(ics, list) else ([ics] if ics else [])
        if ics:
            for c in ics:
                L.append(_fmt_ic(c))
        else:
            L.append("  - (none)")
        L.append("- **refinement_back_edges:**")
        for b in _list(s.get("refinement_back_edges")) or ["(none)"]:
            L.append(f"  - {_inline(b)}")
        L.append("- **acceptance_criteria:**")
        acc = _list(s.get("acceptance_criteria"))
        if acc:
            for c in acc:
                L.append(f"  - {_inline(c)}")
        else:
            L.append("  - (none)")            # surfaced so md check-1 flags the empty required field
        traces = _list(s.get("traces_requirements")) or _list(s.get("traces_to"))
        L.append(f"- **traces_requirements:** {', '.join(_inline(t) for t in traces) or '(none)'}")
        L.append("")

    if doc.get("out_of_scope"):
        L.append("## Out of Scope")
        for o in _list(doc["out_of_scope"]):
            L.append(f"- {_inline(o)}")
        L.append("")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Render an epiphany-plan plan JSON to Markdown (parity-safe).")
    ap.add_argument("plan_json")
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args(argv)
    doc = json.load(open(a.plan_json, encoding="utf-8"))
    md = render(doc)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(md + "\n")
        print(f"wrote {a.out} ({len(md)} bytes)")
    else:
        sys.stdout.write(md + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
