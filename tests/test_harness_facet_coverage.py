"""S7 / WC-9 / APU-011: epiphany-plan plan_verify NEW blocking check —
every harness_ledger facet covered by >=1 step (harness-forge only); --waiver exempt.
Generic plans are byte-identical (check 12 is N/A).
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.normpath(os.path.join(HERE, "..", "tools"))
sys.path.insert(0, TOOLS)
import plan_verify  # noqa: E402


def _base_plan(steps, **extra):
    doc = {
        "plan_meta": {"target_profile": "harness-forge"},
        "roots": ["S0"], "leaves": [steps[-1]["step_id"]],
        "execution_order": [s["step_id"] for s in steps],
        "build_order": [s["step_id"] for s in steps],
        "steps": steps,
    }
    doc.update(extra)
    return doc


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


def _verdict(doc):
    P = plan_verify.load_json_plan(doc)
    R, V = plan_verify.run_checks(P, "json", schema=None, doc=doc)
    return ("PASS" if not V else "FAIL", R, V)


def _check12(R):
    return next((s for c, n, s in R if c == "12"), None)


def test_harness_facet_uncovered_fails():
    steps = [_step("S0", goal="facet:G graph architecture")]
    doc = _base_plan(steps, harness_ledger={"G": "full", "W": "full"})
    verdict, R, V = _verdict(doc)
    assert _check12(R) == "FAIL"
    assert any("W" in v for v in V)  # W is the uncovered facet


def test_harness_all_facets_covered_passes_check12():
    steps = [
        _step("S0", goal="facet:G facet:W graph + wiring"),
        _step("S1", goal="facet:V acceptance", deps=[{"on": "S0", "edge_class": "ordering"}],
              covers_facets=["M", "B", "E", "O", "K"]),
    ]
    doc = _base_plan(steps, harness_ledger={f: "full" for f in ["G", "W", "V", "M", "B", "E", "O", "K"]})
    verdict, R, V = _verdict(doc)
    assert _check12(R) == "PASS"


def test_waived_facet_exempt_from_coverage():
    steps = [_step("S0", goal="facet:G", covers_facets=["W", "V", "M", "B", "E", "K"])]
    # O has no covering step but is waived -> check 12 must still PASS
    doc = _base_plan(steps, harness_ledger={
        "G": "full", "W": "full", "V": "full", "M": "full", "B": "full",
        "E": "full", "K": "full",
        "O": {"status": "waived", "waiver_reason": "observability deferred to v2"},
    })
    verdict, R, V = _verdict(doc)
    assert _check12(R) == "PASS"
    assert any(c == "12w" for c, _, _ in R)


def test_generic_plan_unaffected_no_check12():
    """INV-1: a generic plan (no target_profile harness-forge / no ledger) never runs check 12."""
    steps = [_step("S0")]
    doc = {
        "plan_meta": {"target_profile": "generic"},
        "roots": ["S0"], "leaves": ["S0"],
        "execution_order": ["S0"], "build_order": ["S0"], "steps": steps,
    }
    verdict, R, V = _verdict(doc)
    assert _check12(R) is None  # check 12 absent entirely for generic


def test_harness_plan_without_ledger_is_noop():
    """A harness plan that carries no harness_ledger yet still skips check 12 (nothing to verify)."""
    steps = [_step("S0")]
    doc = _base_plan(steps)
    verdict, R, V = _verdict(doc)
    assert _check12(R) is None
