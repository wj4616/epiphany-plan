#!/usr/bin/env python3
"""inject_waiver — bake an operator-facing `--waiver facet=reason` into a plan doc.

FIX N1 (plan side). epiphany-plan is harness-driven (no session-init.sh); the
operator's `--waiver` flag is realized as this baked tool so `plan_verify` check 12
honors the waiver via the SAME `waived_facets` / per-facet `waiver_reason` path it
already consults — an operator never hand-edits the plan (APU-018: baked code, not
agent discretion).

Given the emitted plan JSON, each `--waiver facet=reason` pair:
  - is validated against the known harness facet set (unknown ⇒ clear error, exit 2;
    never silently accepted);
  - flips that facet's top-level `harness_ledger[facet]` to `status: waived` and
    records `waiver_reason` (the exact shape `_harness_ledger()` reads);
  - is added to the top-level `waived_facets` list (the explicit list check 12 reads);
  - is recorded in `plan_meta.waivers` (append-only audit, retrievable downstream);
  - and, when `--solution-dir` is given, is mirrored into the shared
    solution-workspace manifest via the resolver's `record_waiver()`.

HARNESS-FORGE ONLY + DEFAULT-OFF: a plan whose `plan_meta.target_profile` is not
`harness-forge`, or a run with no `--waiver`, is left byte-identical (INV-1).

Usage:
  inject_waiver.py <plan.json> --waiver G=reason [--waiver O=reason ...] \
      [--solution-dir <dir>] [--in-place | -o <out.json>]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from solution_workspace import ALL_FACETS, record_waiver, WorkspaceError  # noqa: E402


def parse_waivers(pairs: list[str]) -> dict[str, str]:
    """Parse + validate `facet=reason` pairs. Raises ValueError on a bad pair."""
    waivers: dict[str, str] = {}
    for raw in pairs:
        facet, sep, reason = raw.partition("=")
        facet = facet.strip()
        reason = reason.strip()
        if not sep or not facet:
            raise ValueError(f"invalid --waiver (expected facet=reason): {raw!r}")
        if facet not in ALL_FACETS:
            raise ValueError(
                f"unknown --waiver facet {facet!r}; expected one of {', '.join(ALL_FACETS)}")
        if not reason:
            raise ValueError(f"--waiver {facet} requires a non-empty reason (INV-6)")
        waivers[facet] = reason  # last-one-wins per facet
    return waivers


def _is_harness_forge(doc: dict) -> bool:
    pm = doc.get("plan_meta")
    if isinstance(pm, dict) and pm.get("target_profile") == "harness-forge":
        return True
    return doc.get("target_profile") == "harness-forge"


def apply_waivers(doc: dict, waivers: dict[str, str]) -> dict:
    """Bake waivers into a plan doc (in the shape plan_verify check 12 reads).

    No-op (returns doc unchanged) for a non-harness-forge plan or empty waivers
    so generic plans stay byte-identical (INV-1)."""
    if not waivers or not _is_harness_forge(doc):
        return doc
    ledger = dict(doc.get("harness_ledger") or {})
    for facet, reason in waivers.items():
        rec = ledger.get(facet)
        rec = dict(rec) if isinstance(rec, dict) else {
            "facet": facet, "source_stage": "waiver", "detail_ref": None}
        rec["status"] = "waived"
        rec["present"] = True
        rec["waiver_reason"] = reason
        ledger[facet] = rec
    doc["harness_ledger"] = ledger

    waived = list(doc.get("waived_facets") or [])
    for facet in waivers:
        if facet not in waived:
            waived.append(facet)
    doc["waived_facets"] = sorted(waived)

    pm = doc.get("plan_meta")
    if not isinstance(pm, dict):
        pm = {}
        doc["plan_meta"] = pm
    audit = list(pm.get("waivers") or [])
    for facet, reason in waivers.items():
        audit.append({"facet": facet, "reason": reason})
    pm["waivers"] = audit
    return doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan", help="emitted plan JSON")
    ap.add_argument("--waiver", action="append", default=[], metavar="FACET=REASON",
                    help="audited waiver of a harness facet (repeatable)")
    ap.add_argument("--solution-dir", default=None,
                    help="mirror the audited waiver into this solution-workspace manifest")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--in-place", action="store_true", help="rewrite the plan file")
    g.add_argument("-o", "--out", default=None, help="write the result here (default: stdout)")
    a = ap.parse_args(argv)

    if not os.path.isfile(a.plan):
        print(f"error: no such file: {a.plan}", file=sys.stderr)
        return 2
    try:
        doc = json.loads(open(a.plan, encoding="utf-8").read())
    except Exception as e:  # noqa: BLE001
        print(f"error: plan JSON does not parse: {e}", file=sys.stderr)
        return 2

    try:
        waivers = parse_waivers(a.waiver)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if waivers and not _is_harness_forge(doc):
        print("error: --waiver is harness-forge only; this plan is generic "
              "(plan_meta.target_profile != harness-forge)", file=sys.stderr)
        return 2

    # DEFAULT-OFF / INV-1: nothing to apply ⇒ leave the plan byte-identical. For
    # --in-place this means touching nothing; for stdout/-o it echoes the input verbatim.
    if not waivers:
        if a.in_place:
            return 0
        out_text = open(a.plan, encoding="utf-8").read()
        (open(a.out, "w", encoding="utf-8").write(out_text) if a.out
         else sys.stdout.write(out_text))
        return 0

    doc = apply_waivers(doc, waivers)

    # Mirror into the shared manifest (best-effort; the plan doc is authoritative for check 12).
    if waivers and a.solution_dir and os.path.isdir(a.solution_dir):
        for facet, reason in waivers.items():
            try:
                record_waiver(a.solution_dir, facet, reason)
            except WorkspaceError as e:
                print(f"[waiver-mirror skipped {facet}: {e}]", file=sys.stderr)

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
