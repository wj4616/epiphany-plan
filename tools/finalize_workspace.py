#!/usr/bin/env python3
"""finalize_workspace — the plan stage's manifest writer + typed handoff-chain emitter.

Task A (S3, plan portion). epiphany-plan is harness-driven (no session-init.sh) and, until now, had
no live code that calls `solution_workspace.update_stage()` or writes the typed chain fields — the
`plan_meta.solution_dir/stage/prev_stage/next_skill` keys in a real plan were hand-authored by the
producing run (F1). This baked tool is the missing writer, invoked from `N-write_plan.md` after the
plan document is committed (APU-018: baked code, not agent discretion). It mirrors the spec's
`record_waiver` tool->resolver pattern so the resolver stays single-source (INV-5).

Given the written plan JSON + a resolved `--solution-dir` workspace, it:
  - deep-merges the 4 typed chain fields into `plan_meta` (never clobbering other keys);
  - records a `stages.plan` entry into the workspace `solution.json` (atomic, idempotent,
    forward-compatible — priors preserved, R-10);
  - HARNESS-FORGE ONLY: when `plan_meta.target_profile == 'harness-forge'` AND the plan carries a
    `harness_ledger`, mirrors it into the manifest via `update_ledger()`.

GENERIC / DEFAULT-OFF (INV-1): a plan whose `plan_meta.target_profile` is not `harness-forge` gets
NO ledger write and NO harness key anywhere — only the universal stage entry + chain fields. The
chain fields themselves (solution_dir/stage/prev/next) are universal workspace provenance, written
for every project; the *harness* layer (ledger) is the only thing gated on the profile.

Usage:
  finalize_workspace.py <plan.json> --solution-dir <workspace> [--stage plan] [--in-place | -o out]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from solution_workspace import (  # noqa: E402
    handoff_chain_fields, seed_ledger, stage_subdir, update_ledger, update_stage, WorkspaceError,
)


def _normalize_ledger(ledger: dict) -> dict:
    """H-F2 — coerce a string-shaped ledger ({facet: 'full'|'thin'|...}) into the canonical
    record dicts that update_ledger / record_waiver assume. A ledger already in record shape
    (values are dicts) is returned untouched; a mixed/short shape is normalized via the resolver's
    existing seed_ledger so the durable manifest never stores a bare-string ledger."""
    if not isinstance(ledger, dict) or not ledger:
        return ledger
    if all(isinstance(v, dict) for v in ledger.values()):
        return ledger  # already canonical record dicts
    # treat string (or otherwise non-record) values as per-facet status overrides
    statuses = {k: v for k, v in ledger.items() if isinstance(v, str)}
    return seed_ledger(facets=list(ledger.keys()), statuses=statuses)


def _plan_gate_passes(doc: dict, plan_status: str | None) -> bool:
    """H-D1 — decide whether the manifest stage may be marked `complete`.

    The deterministic `plan_verify` gate already ran in the graph BEFORE write_plan calls this
    tool, so its verdict is an INPUT, not something to re-derive: an explicit `plan_status`
    (PASS/FAIL/PROCEED/OPEN/BLOCK) is authoritative. When it is absent we fall back to a structural
    signal the doc itself carries (`plan_meta.structural_verdict` / `structural_verdict`), and
    otherwise DEFAULT TO complete so a well-formed plan with no recorded verdict is never demoted
    (this is a manifest-hygiene guard, not a second gate). Only an explicit FAIL/BLOCK demotes."""
    status = plan_status
    if status is None:
        pm = doc.get("plan_meta") if isinstance(doc.get("plan_meta"), dict) else {}
        status = pm.get("structural_verdict") or doc.get("structural_verdict")
    if status is None:
        return True
    s = str(status).strip().upper()
    return s not in ("FAIL", "BLOCK", "BLOCKED", "OPEN")


def _is_harness_forge(doc: dict) -> bool:
    pm = doc.get("plan_meta")
    if isinstance(pm, dict) and pm.get("target_profile") == "harness-forge":
        return True
    return doc.get("target_profile") == "harness-forge"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def finalize(doc: dict, workspace: str, plan_basename: str, *, stage: str = "plan",
             plan_status: str | None = None) -> dict:
    """Apply the chain fields + manifest stage entry (+ ledger mirror for harness plans) and return
    the updated plan doc. Pure-ish: it writes the manifest as a side effect (the resolver owns the
    atomic write), and mutates+returns `doc` with the chain fields merged into plan_meta."""
    # 1. typed chain fields -> plan_meta (deep-merge the 4 keys only; preserve everything else).
    chain = handoff_chain_fields(workspace, stage, prev_stage="spec",
                                 next_skill="epiphany-executor")
    pm = doc.get("plan_meta")
    if not isinstance(pm, dict):
        pm = {}
        doc["plan_meta"] = pm
    pm.update(chain)   # only the 4 chain keys; never touches plan_id/title/etc.

    # 2. universal manifest stage entry (priors preserved by the resolver's deep-merge, R-10).
    #    H-D1: mark the stage `complete` ONLY when the plan gate PASSes; a FAIL plan is recorded
    #    `blocked` so the durable manifest never claims a non-executor-ingestible plan is done.
    passed = _plan_gate_passes(doc, plan_status)
    entry = {
        "status": "complete" if passed else "blocked",
        "dir": stage_subdir(workspace, stage),
        "primary": plan_basename,
        "completed_ts": _now_iso(),
    }
    update_stage(workspace, stage, entry)

    # 3. HARNESS branch only: mirror the travelling ledger into the manifest. Generic => skip
    #    entirely (INV-1: no harness_ledger key anywhere on a generic project).
    if _is_harness_forge(doc):
        ledger = doc.get("harness_ledger")
        if isinstance(ledger, dict) and ledger:
            update_ledger(workspace, _normalize_ledger(ledger))   # H-F2: canonical record shape
    return doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan", help="the written plan JSON")
    ap.add_argument("--solution-dir", required=True,
                    help="the resolved solution workspace (its solution.json is updated)")
    ap.add_argument("--stage", default="plan", help="stage name (default: plan)")
    ap.add_argument("--plan-status", default=None,
                    help="the plan_verify gate verdict (PASS/FAIL/...). H-D1: the manifest stage "
                         "is marked complete only on a non-FAIL verdict; default complete when "
                         "unset (the gate already ran upstream).")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--in-place", action="store_true", help="rewrite the plan file with chain fields")
    g.add_argument("-o", "--out", default=None, help="write the result here (default: stdout)")
    a = ap.parse_args(argv)

    if not os.path.isfile(a.plan):
        print(f"error: no such file: {a.plan}", file=sys.stderr)
        return 2
    # Markdown plans: operate on the JSON canonical only (Markdown parity is re-rendered downstream
    # by render_markdown.py). A .md path has no machine-mergeable plan_meta here, so we still update
    # the manifest from the resolver but cannot rewrite chain fields into a Markdown body — skip the
    # body rewrite, do the manifest. (F1: JSON is the canonical the executor ingests.)
    if a.plan.endswith(".md"):
        # best-effort manifest update with no doc rewrite; chain fields live in the JSON sibling.
        md_passed = _plan_gate_passes({}, a.plan_status)   # H-D1: honor an explicit FAIL verdict
        try:
            update_stage(a.solution_dir, a.stage, {
                "status": "complete" if md_passed else "blocked",
                "dir": stage_subdir(a.solution_dir, a.stage),
                "primary": os.path.basename(a.plan), "completed_ts": _now_iso()})
        except WorkspaceError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        return 0

    try:
        doc = json.loads(open(a.plan, encoding="utf-8").read())
    except Exception as e:  # noqa: BLE001
        print(f"error: plan JSON does not parse: {e}", file=sys.stderr)
        return 2

    try:
        doc = finalize(doc, a.solution_dir, os.path.basename(a.plan), stage=a.stage,
                       plan_status=a.plan_status)
    except WorkspaceError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    out_text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    if a.in_place:
        tmp = a.plan + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(out_text)
        os.replace(tmp, a.plan)
    elif a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(out_text)
    else:
        sys.stdout.write(out_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
