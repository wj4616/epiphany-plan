"""P2-2: plan_verify C11 wiring-contract bijection (blocking, only when contract present)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
import plan_verify as pv

META = {"plan_id": "p", "schema": "s", "source_spec": "x"}
ROW = {"id": "CAP-a", "requirement": "r", "mechanism": "tool_call", "sites": [{"tool": "t"}],
       "fired_marker": {"kind": "ledger_tool", "value": "t"}, "smoke_input": "x"}


def _step(sid, **kw):
    s = {"step_id": sid, "goal": "g", "actions": ["a"], "acceptance_criteria": ["c"], "dependencies": []}
    s.update(kw)
    return s


def _run(doc):
    P = pv.load_json_plan(doc)
    R, V = pv.run_checks(P, "json", None, doc)
    return R, V


def _viol(V, code):
    return [v for v in V if v.startswith(f"[{code} ")]


def test_clean_bijection_passes():
    doc = {"plan_meta": META, "wiring_contract": [ROW],
           "steps": [_step("S1", obligation_class="capability-closure", target_subsystem="skill",
                           traces_requirements=["CAP-a"])]}
    _R, V = _run(doc)
    assert not _viol(V, "11") and not _viol(V, "11b")


def test_uncovered_row_fails():
    doc = {"plan_meta": META, "wiring_contract": [ROW, {**ROW, "id": "CAP-orphan"}],
           "steps": [_step("S1", traces_requirements=["CAP-a"])]}
    _R, V = _run(doc)
    assert _viol(V, "11")                       # CAP-orphan referenced by no step
    assert "CAP-orphan" in " ".join(V)


def test_skill_capability_step_without_row_fails():
    doc = {"plan_meta": META, "wiring_contract": [ROW],
           "steps": [_step("S1", obligation_class="capability-closure", target_subsystem="skill",
                           traces_requirements=["CAP-a"]),
                     _step("S2", obligation_class="capability-closure", target_subsystem="skill",
                           traces_requirements=["R-unrelated"])]}
    _R, V = _run(doc)
    assert _viol(V, "11b") and "S2" in " ".join(V)


def test_harness_primitive_step_exempt():
    # a capability-closure step on the HARNESS subsystem needs no row (wired by construction)
    doc = {"plan_meta": META, "wiring_contract": [ROW],
           "steps": [_step("S1", traces_requirements=["CAP-a"]),
                     _step("H1", obligation_class="capability-closure", target_subsystem="harness",
                           traces_requirements=["R-prim"])]}
    _R, V = _run(doc)
    assert not _viol(V, "11b")                  # harness primitive exempt


def test_no_contract_is_na_backcompat():
    # a plan with NO wiring_contract -> C11 does not run at all (byte-identical to today)
    doc = {"plan_meta": META, "steps": [_step("S1", traces_requirements=["R1"])]}
    R, V = _run(doc)
    assert not any(r[0] in ("11", "11b") for r in R)
    assert not _viol(V, "11") and not _viol(V, "11b")
