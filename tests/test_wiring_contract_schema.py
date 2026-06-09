"""P2-1: optional wiring_contract in plan.schema.json (additive, back-compat)."""
import json
from pathlib import Path

import jsonschema
import pytest

SCHEMA = json.loads((Path(__file__).parent.parent / "plan.schema.json").read_text())

BASE_PLAN = {
    "plan_meta": {"plan_id": "p", "schema": "epiphany-plan/plan@1.1.0", "source_spec": "spec.md"},
    "steps": [{"step_id": "S1", "goal": "g", "actions": ["a"], "acceptance_criteria": ["ac"],
               "traces_requirements": ["R1"], "dependencies": []}],
}
ROW = {"id": "CAP-x", "requirement": "x wired", "mechanism": "tool_call",
       "sites": [{"tool": "t.x"}], "fired_marker": {"kind": "ledger_tool", "value": "t.x"},
       "smoke_input": "x"}


def test_plan_without_wiring_contract_still_validates():
    jsonschema.validate(BASE_PLAN, SCHEMA)          # back-compat: absent => valid as today


def test_plan_with_valid_wiring_contract_validates():
    jsonschema.validate({**BASE_PLAN, "wiring_contract": [ROW]}, SCHEMA)


def test_composite_marker_list_validates():
    row = {**ROW, "fired_marker": [{"kind": "driver_signal", "value": "split"},
                                   {"kind": "node_exec", "value": "join"}]}
    jsonschema.validate({**BASE_PLAN, "wiring_contract": [row]}, SCHEMA)


def test_invalid_mechanism_fails():
    bad = {**ROW, "mechanism": "telepathy"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**BASE_PLAN, "wiring_contract": [bad]}, SCHEMA)


def test_invalid_marker_kind_fails():
    bad = {**ROW, "fired_marker": {"kind": "node_body", "value": "x"}}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**BASE_PLAN, "wiring_contract": [bad]}, SCHEMA)


def test_missing_required_row_field_fails():
    bad = {k: v for k, v in ROW.items() if k != "mechanism"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**BASE_PLAN, "wiring_contract": [bad]}, SCHEMA)
