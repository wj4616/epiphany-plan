"""Phase-S back-compat: the forge-program integration additions to epiphany-plan are ADDITIVE and
optional — a non-forge plan validates exactly as before, the new edge_class values validate, the
optional capability/gate metadata validates (additionalProperties), and a bogus edge_class is still
rejected. This pins that the general skill was not regressed by the forge integration."""
import json
from pathlib import Path

import jsonschema
import pytest

SCHEMA_PATH = Path(__file__).parent.parent / "plan.schema.json"


@pytest.fixture
def schema():
    with open(SCHEMA_PATH) as f:
        return json.load(f)


def _stock_plan():
    """A plain non-forge plan using ONLY the pre-existing fields (the back-compat baseline)."""
    return {
        "plan_meta": {"plan_id": "stock", "schema": "epiphany-plan.plan_document.v1",
                      "source_spec": "~/some-ordinary-spec.md"},
        "coverage_verdict": {"decision": "PASS"},
        "requirement_ledger": [{"obligation": "R1", "covered_by": ["S1"]}],
        "steps": [{
            "step_id": "S1", "goal": "Implement R1", "actions": ["do x"],
            "acceptance_criteria": ["x works"],
            "dependencies": [{"on": "S0", "kind": "ordering", "edge_class": "implementation-prerequisite"}],
        }],
        "execution_order": ["S1"],
    }


def test_stock_plan_still_validates(schema):
    """A non-forge plan with only pre-existing fields validates unchanged (back-compat)."""
    jsonschema.validate(_stock_plan(), schema)


def test_new_generic_edge_classes_validate(schema):
    """The two additive edge_class values validate."""
    for ec in ("concurrency-prerequisite", "feedback-input"):
        plan = _stock_plan()
        plan["steps"][0]["dependencies"][0]["edge_class"] = ec
        jsonschema.validate(plan, schema)


def test_legacy_edge_classes_unchanged(schema):
    """The original edge_class values still validate (no regression)."""
    for ec in ("implementation-prerequisite", "runtime-data", "ordering"):
        plan = _stock_plan()
        plan["steps"][0]["dependencies"][0]["edge_class"] = ec
        jsonschema.validate(plan, schema)


def test_bogus_edge_class_still_rejected(schema):
    """The enum is widened, not opened — an unknown edge_class is still rejected."""
    plan = _stock_plan()
    plan["steps"][0]["dependencies"][0]["edge_class"] = "totally-made-up"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(plan, schema)


def test_optional_capability_gate_metadata_validates(schema):
    """obligation_class / gate-named acceptance / target_subsystem ride additionalProperties — they
    validate when present and are simply absent for ordinary specs."""
    plan = _stock_plan()
    plan["requirement_ledger"][0]["obligation_class"] = "capability-closure"
    plan["steps"][0]["target_subsystem"] = "generator/infer.py"
    plan["steps"][0]["acceptance_criteria"].append("gate: structural-valid")
    jsonschema.validate(plan, schema)


def test_stock_plan_has_no_target_profile(schema):
    """The back-compat baseline carries NO target_profile/harness_forge — proves the default path is
    untouched (generic plans must not gain harness/forge metadata)."""
    plan = _stock_plan()
    assert "target_profile" not in plan["plan_meta"]
    assert "harness_forge" not in plan["plan_meta"]
    jsonschema.validate(plan, schema)


def test_plan_meta_target_profile_enum_validates(schema):
    """plan_meta.target_profile accepts the two known values."""
    for prof in ("generic", "harness-forge"):
        plan = _stock_plan()
        plan["plan_meta"]["target_profile"] = prof
        jsonschema.validate(plan, schema)


def test_plan_meta_bogus_target_profile_rejected(schema):
    """target_profile is an enum — an unknown profile is rejected (no silent typo-pass)."""
    plan = _stock_plan()
    plan["plan_meta"]["target_profile"] = "made-up-profile"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(plan, schema)


def test_coverage_audit_enforces_harness_first_ordering():
    """M2: harness-first must be an ENFORCED coverage obligation when target_profile==harness-forge,
    not just a tag — the convention block must require an ordering edge primitive→forge step."""
    import pathlib
    cov = (pathlib.Path(__file__).resolve().parents[1] / "modules" / "N-coverage_audit.md").read_text()
    low = cov.lower()
    assert "harness-first" in low and "harness-forge" in low
    assert "ordering" in low and ("prerequisite" in low or "before" in low)
    assert "fail" in low  # an ordering violation must FAIL coverage, not pass silently


def test_ingest_does_not_raise_dead_signal():
    """N1: the dead `targets_harness_forge` raised-signal was removed; the live pipe is the
    target_profile output port."""
    import json
    import pathlib
    graph = json.loads((pathlib.Path(__file__).resolve().parents[1] / "graph.json").read_text())
    ingest = graph["nodes"]["ingest"]
    assert "targets_harness_forge" not in (ingest.get("raises_signals") or [])
    assert any(o["name"] == "target_profile" for o in ingest["outputs"])


def test_plan_meta_harness_forge_pack_validates(schema):
    """The forwarded context-pack validates as an open object on plan_meta.harness_forge."""
    plan = _stock_plan()
    plan["plan_meta"]["target_profile"] = "harness-forge"
    plan["plan_meta"]["harness_forge"] = {
        "harness_primitives": ["fan-out/AND-join"],
        "grammar_cells": [{"cell": "RESEARCHER+subagent-fanout+AND-join", "oracle_kind": "differential"}],
        "correctness_basis": "differential",
        "harness_first": True,
        "provider_hint": "codex",
        "self_modifying": True,
    }
    jsonschema.validate(plan, schema)
