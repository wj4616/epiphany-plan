"""FIX N1 (plan side): operator-facing `--waiver facet=reason` baked into the plan
via tools/inject_waiver.py, honored by plan_verify check 12 through the SAME
waived_facets / per-facet waiver_reason path it already consults.

Proves: (a) --waiver makes the otherwise-blocking check 12 PASS for the waived facet;
(b) the audited reason is recorded where downstream can read it (harness_ledger +
plan_meta.waivers + the shared manifest); (c) the generic path is unchanged (INV-1);
(d) an unknown facet name is rejected (never silently accepted).
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.normpath(os.path.join(HERE, "..", "tools"))
sys.path.insert(0, TOOLS)
import plan_verify        # noqa: E402
import inject_waiver      # noqa: E402


def _step(sid, goal="implement thing", deps=None, **kw):
    s = {
        "step_id": sid, "goal": goal, "actions": ["build it"],
        "inputs": [], "outputs": [],
        "dependencies": deps or [],
        "integration_checks": [], "refinement_back_edges": [],
        "acceptance_criteria": ["works"], "traces_requirements": ["APU-001"],
    }
    s.update(kw)
    return s


def _harness_plan(steps, **extra):
    doc = {
        "plan_meta": {"target_profile": "harness-forge"},
        "roots": ["S0"], "leaves": [steps[-1]["step_id"]],
        "execution_order": [s["step_id"] for s in steps],
        "build_order": [s["step_id"] for s in steps],
        "steps": steps,
    }
    doc.update(extra)
    return doc


def _check12(R):
    return next((s for c, n, s in R if c == "12"), None)


def _verdict(doc):
    P = plan_verify.load_json_plan(doc)
    R, V = plan_verify.run_checks(P, "json", schema=None, doc=doc)
    return _check12(R), R, V


# --- the uncovered-facet plan: O has no covering step -> check 12 FAILS without a waiver
def _uncovered_o_plan():
    steps = [_step("S0", goal="facet:G", covers_facets=["W", "V", "M", "B", "E", "K"])]
    return _harness_plan(steps, harness_ledger={f: "full" for f in "GWVMBEOK"})


def test_blocking_without_waiver():
    """Baseline: O uncovered -> check 12 BLOCKS (the gate has teeth to waive)."""
    c12, R, V = _verdict(_uncovered_o_plan())
    assert c12 == "FAIL"
    assert any("O" in v for v in V)


def test_waiver_makes_check12_pass(tmp_path):
    """(a) inject_waiver O=reason -> check 12 PASSES for O; (b) reason recorded downstream."""
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(_uncovered_o_plan()))
    rc = inject_waiver.main([str(plan), "--waiver", "O=observability deferred to v2", "--in-place"])
    assert rc == 0
    doc = json.loads(plan.read_text())

    # (a) the gate now passes for the waived facet
    c12, R, V = _verdict(doc)
    assert c12 == "PASS", V
    assert not V
    assert any(c == "12w" for c, _, _ in R)  # advisory surfaces the audited waiver

    # (b) the reason is retrievable where downstream reads it
    assert doc["harness_ledger"]["O"]["status"] == "waived"
    assert doc["harness_ledger"]["O"]["waiver_reason"] == "observability deferred to v2"
    assert doc["waived_facets"] == ["O"]
    assert {"facet": "O", "reason": "observability deferred to v2"} in doc["plan_meta"]["waivers"]


def test_waiver_mirrored_into_manifest(tmp_path):
    """(b) the audited record also rides the shared solution-workspace manifest."""
    ws = str(tmp_path / "ws")
    os.makedirs(ws, exist_ok=True)
    # minimal manifest so record_waiver has something to merge into
    open(os.path.join(ws, "solution.json"), "w").write(json.dumps({"schema": "x", "stages": {}}))

    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(_uncovered_o_plan()))
    rc = inject_waiver.main([str(plan), "--waiver", "O=deferred", "--solution-dir", ws, "--in-place"])
    assert rc == 0
    man = json.loads(open(os.path.join(ws, "solution.json")).read())
    assert {"facet": "O", "reason": "deferred"} in man["waivers"]
    assert man["harness_ledger"]["O"]["status"] == "waived"


def test_generic_plan_unchanged(tmp_path):
    """(c) INV-1: a generic plan + --waiver is rejected (harness-forge only) and never mutated."""
    doc = {
        "plan_meta": {"target_profile": "generic"},
        "roots": ["S0"], "leaves": ["S0"],
        "execution_order": ["S0"], "build_order": ["S0"],
        "steps": [_step("S0")],
    }
    plan = tmp_path / "plan.json"
    original = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    plan.write_text(original)
    rc = inject_waiver.main([str(plan), "--waiver", "O=nope", "--in-place"])
    assert rc == 2  # harness-forge only — refused
    assert plan.read_text() == original  # byte-identical: not mutated


def test_no_waiver_is_noop(tmp_path):
    """(c) INV-1: a harness plan with NO --waiver is left byte-identical."""
    doc = _uncovered_o_plan()
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(doc))
    before = plan.read_text()
    rc = inject_waiver.main([str(plan), "--in-place"])
    assert rc == 0
    assert plan.read_text() == before


def test_unknown_facet_rejected(tmp_path):
    """(d) an unknown facet name is rejected with a nonzero exit, not silently accepted."""
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(_uncovered_o_plan()))
    rc = inject_waiver.main([str(plan), "--waiver", "ZZZ=nope", "--in-place"])
    assert rc == 2


def test_malformed_waiver_rejected(tmp_path):
    """(d) a malformed pair (no '=') is rejected."""
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(_uncovered_o_plan()))
    rc = inject_waiver.main([str(plan), "--waiver", "Onoreason", "--in-place"])
    assert rc == 2


def test_empty_reason_rejected(tmp_path):
    """(d) INV-6: a waiver must carry a non-empty reason."""
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(_uncovered_o_plan()))
    rc = inject_waiver.main([str(plan), "--waiver", "O=", "--in-place"])
    assert rc == 2
