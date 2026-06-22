"""Task A (S3 plan portion) — finalize_workspace tool.

The plan stage has no live code that calls `update_stage()` or writes the typed handoff-chain
fields; the chain fields presently in a plan's `plan_meta` were hand-authored by the producing run
(F1). This tool is the missing writer, invoked from `N-write_plan.md` (Task B). It mirrors the
spec's `record_waiver` tool->resolver pattern so the convention stays baked code, not prose
(INV-5 / APU-018).

Acceptance:
- harness plan: chain fields in plan_meta, stages.plan complete, priors preserved, ledger mirrored.
- generic plan: zero harness keys anywhere; manifest carries only the universal stage entry (INV-1).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.normpath(os.path.join(HERE, "..", "tools", "finalize_workspace.py"))
RESOLVER_DIR = os.path.normpath(os.path.join(HERE, "..", "tools"))
sys.path.insert(0, RESOLVER_DIR)
import solution_workspace as sw  # noqa: E402


def _mk_workspace(tmp_path, slug="t-finalize"):
    os.environ["EPIPHANY_SOLUTION_ROOT"] = str(tmp_path)
    ws = sw.resolve(slug=slug, date="2026-06-14")
    return ws


def _write_plan(path, *, harness=True, ledger=None):
    plan = {
        "plan_meta": {
            "plan_id": "pln-x", "schema": "epiphany-plan.plan_document.v1",
            "title": "T", "generated_by": "epiphany-plan v1.1.1",
        },
        "steps": [{"step_id": "S0", "goal": "g"}],
    }
    if harness:
        plan["plan_meta"]["target_profile"] = "harness-forge"
    if ledger is not None:
        plan["harness_ledger"] = ledger
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(plan, fh)
    return plan


def _run(plan_file, ws, extra=None):
    cmd = [sys.executable, TOOL, plan_file, "--solution-dir", ws, "--in-place"]
    if extra:
        cmd += extra
    return subprocess.run(cmd, capture_output=True, text=True)


def test_chain_fields_and_update_stage(tmp_path):
    ws = _mk_workspace(tmp_path)
    # a prior spec stage entry must survive (R-10)
    sw.update_stage(ws, "spec", {"status": "complete", "primary": "spec-final.md"})
    plan_file = os.path.join(sw.stage_subdir(ws, "plan"), "plan.json")
    _write_plan(plan_file, harness=True,
                ledger=sw.seed_ledger(["G", "W"], statuses={"G": "full", "W": "full"}))

    res = _run(plan_file, ws)
    assert res.returncode == 0, res.stderr

    doc = json.loads(open(plan_file, encoding="utf-8").read())
    pm = doc["plan_meta"]
    assert pm["solution_dir"] == os.path.abspath(ws)
    assert pm["stage"] == "plan"
    assert pm["prev_stage"] == "spec"
    assert pm["next_skill"] == "epiphany-executor"
    # never clobber other plan_meta keys
    assert pm["plan_id"] == "pln-x" and pm["title"] == "T"

    man = sw.read_manifest(ws)
    assert man["stages"]["plan"]["status"] == "complete"
    assert man["stages"]["spec"]["primary"] == "spec-final.md"   # prior preserved (R-10)
    # harness branch: ledger mirrored into the manifest
    assert "harness_ledger" in man and man["harness_ledger"]["G"]["status"] == "full"


def test_generic_no_ledger_key(tmp_path):
    """INV-1: a generic plan (no target_profile) writes NO harness_ledger key into solution.json
    and adds NO harness key to plan_meta. Only the universal stage entry + chain fields."""
    ws = _mk_workspace(tmp_path, slug="t-generic")
    plan_file = os.path.join(sw.stage_subdir(ws, "plan"), "plan.json")
    _write_plan(plan_file, harness=False)

    res = _run(plan_file, ws)
    assert res.returncode == 0, res.stderr

    man = sw.read_manifest(ws)
    assert "harness_ledger" not in man, "INV-1 violated: harness_ledger written for a generic plan"
    assert man["stages"]["plan"]["status"] == "complete"
    doc = json.loads(open(plan_file, encoding="utf-8").read())
    pm = doc["plan_meta"]
    # the universal chain fields are fine on any project; harness-only keys must be absent
    assert "harness_ledger" not in pm
    assert "target_profile" not in pm


def test_generic_even_with_ledger_present_writes_nothing_harness(tmp_path):
    """Belt-and-suspenders INV-1: even if a generic plan accidentally carries a harness_ledger blob,
    the tool must NOT mirror it (the harness branch is gated on target_profile == harness-forge)."""
    ws = _mk_workspace(tmp_path, slug="t-generic2")
    plan_file = os.path.join(sw.stage_subdir(ws, "plan"), "plan.json")
    _write_plan(plan_file, harness=False, ledger={"G": {"facet": "G", "status": "full"}})
    res = _run(plan_file, ws)
    assert res.returncode == 0, res.stderr
    man = sw.read_manifest(ws)
    assert "harness_ledger" not in man


def test_upstream_resolves_same_workspace(tmp_path):
    """R-8: a downstream stage given only the plan's chain fields (a handoff dict) resolves the
    SAME workspace path (round-trip)."""
    ws = _mk_workspace(tmp_path, slug="t-roundtrip")
    plan_file = os.path.join(sw.stage_subdir(ws, "plan"), "plan.json")
    _write_plan(plan_file, harness=True)
    _run(plan_file, ws)

    doc = json.loads(open(plan_file, encoding="utf-8").read())
    handoff = os.path.join(tmp_path, "handoff.json")
    with open(handoff, "w", encoding="utf-8") as fh:
        json.dump(doc["plan_meta"], fh)   # carries solution_dir
    again = sw.resolve(upstream=handoff)
    assert os.path.abspath(again) == os.path.abspath(ws)


def test_h_d1_fail_plan_marks_stage_blocked(tmp_path):
    """H-D1: an explicit FAIL plan_verify verdict must NOT mark the manifest stage `complete`."""
    ws = _mk_workspace(tmp_path, slug="t-hd1")
    plan_file = os.path.join(sw.stage_subdir(ws, "plan"), "plan.json")
    _write_plan(plan_file, harness=True)
    res = _run(plan_file, ws, extra=["--plan-status", "FAIL"])
    assert res.returncode == 0, res.stderr
    man = sw.read_manifest(ws)
    assert man["stages"]["plan"]["status"] == "blocked"

    # ... and an explicit PASS (or no status) still completes (happy path unchanged).
    res2 = _run(plan_file, ws, extra=["--plan-status", "PASS"])
    assert res2.returncode == 0, res2.stderr
    assert sw.read_manifest(ws)["stages"]["plan"]["status"] == "complete"


def test_h_f2_string_ledger_normalized_to_records(tmp_path):
    """H-F2: a {facet: 'full'} string-shaped ledger is coerced to canonical record dicts before
    update_ledger, so the durable manifest never stores a bare-string ledger."""
    ws = _mk_workspace(tmp_path, slug="t-hf2")
    plan_file = os.path.join(sw.stage_subdir(ws, "plan"), "plan.json")
    _write_plan(plan_file, harness=True, ledger={"G": "full", "W": "thin"})
    res = _run(plan_file, ws)
    assert res.returncode == 0, res.stderr
    man = sw.read_manifest(ws)
    led = man["harness_ledger"]
    assert isinstance(led["G"], dict) and led["G"]["status"] == "full" and led["G"]["present"] is True
    assert isinstance(led["W"], dict) and led["W"]["status"] == "thin"
