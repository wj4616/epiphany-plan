"""Schema validation tests for epiphany-plan JSON output.

Verifies that:
1. Published schema variant (execution_order + steps + coverage_verdict) validates
2. Triad variant (build_order + gate_status + steps) validates
3. Real emitted plans validate without adaptation
4. Edge cases (missing optional fields, bare dependencies, object integration_checks) work
"""
import json
import pytest
from pathlib import Path
import jsonschema


@pytest.fixture
def schema():
    """Load the plan.schema.json"""
    schema_path = Path(__file__).parent.parent / "plan.schema.json"
    with open(schema_path) as f:
        return json.load(f)


@pytest.fixture
def minimal_published_variant():
    """Minimal valid plan in published-schema variant"""
    return {
        "plan_meta": {
            "plan_id": "test-plan-published",
            "schema": "epiphany-plan.plan_document.v1",
            "source_spec": "~/test.md"
        },
        "coverage_verdict": {
            "decision": "PASS"
        },
        "steps": [
            {
                "step_id": "S1",
                "goal": "Implement something",
                "actions": ["Do X"],
                "acceptance_criteria": ["X is done"]
            }
        ],
        "execution_order": ["S1"]
    }


@pytest.fixture
def minimal_triad_variant():
    """Minimal valid plan in triad variant (for executor)"""
    return {
        "plan_meta": {
            "plan_id": "test-plan-triad",
            "schema": "epiphany-plan.plan_document.v1",
            "source_spec": "~/test.md"
        },
        "gate_status": {
            "coverage_verdict": "PASS"
        },
        "steps": [
            {
                "step_id": "S1",
                "goal": "Implement something",
                "actions": ["Do X"],
                "acceptance_criteria": ["X is done"]
            }
        ],
        "build_order": ["S1"]
    }


@pytest.fixture
def rich_plan_with_typed_deps():
    """Plan with typed dependencies and edge_class"""
    return {
        "plan_meta": {
            "plan_id": "test-typed-deps",
            "schema": "epiphany-plan.plan_document.v1",
            "source_spec": "~/test.md",
            "title": "Test Plan with Typed Dependencies"
        },
        "coverage_verdict": {
            "decision": "PASS",
            "blocking": True
        },
        "steps": [
            {
                "step_id": "S1",
                "goal": "Setup",
                "actions": ["Initialize"],
                "acceptance_criteria": ["Ready"],
                "outputs": ["artifacts"]
            },
            {
                "step_id": "S2",
                "goal": "Build",
                "actions": ["Compile"],
                "acceptance_criteria": ["Success"],
                "dependencies": [
                    {
                        "on": "S1",
                        "kind": "data",
                        "edge_class": "runtime-data"
                    }
                ],
                "traces_requirements": ["REQ-001"]
            }
        ],
        "execution_order": ["S1", "S2"],
        "requirement_ledger": [
            {
                "obligation": "REQ-001",
                "covered_by": ["S2"]
            }
        ]
    }


@pytest.fixture
def plan_with_bare_deps():
    """Plan with bare string dependencies (legacy tolerant)"""
    return {
        "plan_meta": {
            "plan_id": "test-bare-deps",
            "schema": "epiphany-plan.plan_document.v1",
            "source_spec": "~/test.md"
        },
        "coverage_verdict": {
            "decision": "PASS"
        },
        "steps": [
            {
                "step_id": "S1",
                "goal": "Step 1",
                "actions": ["Action"],
                "acceptance_criteria": ["Done"]
            },
            {
                "step_id": "S2",
                "goal": "Step 2",
                "actions": ["Action"],
                "acceptance_criteria": ["Done"],
                "dependencies": ["S1"]  # Bare string, not typed object
            }
        ],
        "execution_order": ["S1", "S2"]
    }


@pytest.fixture
def plan_with_object_integration_checks():
    """Plan with integration_checks as object (real emit format)"""
    return {
        "plan_meta": {
            "plan_id": "test-object-checks",
            "schema": "epiphany-plan.plan_document.v1",
            "source_spec": "~/test.md"
        },
        "coverage_verdict": {
            "decision": "PASS"
        },
        "steps": [
            {
                "step_id": "S1",
                "goal": "Build",
                "actions": ["Compile"],
                "acceptance_criteria": ["Success"],
                "integration_checks": {
                    "id": "IC-001",
                    "assert": "prior step output present",
                    "status": "PASS"
                }
            }
        ],
        "execution_order": ["S1"]
    }


@pytest.fixture
def plan_with_plan_level_gates():
    """Plan with plan-level gate_status, blocking_defects, structural_faults"""
    return {
        "plan_meta": {
            "plan_id": "test-gates",
            "schema": "epiphany-plan.plan_document.v1",
            "source_spec": "~/test.md"
        },
        "gate_status": {
            "coverage_verdict": "PASS",
            "structural_verdict": "PASS"
        },
        "blocking_defects": [],
        "structural_faults": [],
        "coverage_verdict": {
            "decision": "PASS"
        },
        "steps": [
            {
                "step_id": "S1",
                "goal": "Step",
                "actions": ["Do it"],
                "acceptance_criteria": ["Done"]
            }
        ],
        "build_order": ["S1"]
    }


class TestPublishedVariant:
    """Tests for published-schema variant (execution_order + steps + coverage_verdict)"""

    def test_minimal_plan_validates(self, schema, minimal_published_variant):
        """Minimal published variant should validate"""
        jsonschema.validate(minimal_published_variant, schema)

    def test_rich_typed_deps_validates(self, schema, rich_plan_with_typed_deps):
        """Plan with fully typed dependencies should validate"""
        jsonschema.validate(rich_plan_with_typed_deps, schema)

    def test_plan_with_bare_deps_validates(self, schema, plan_with_bare_deps):
        """Plan with bare string dependencies should validate (tolerant)"""
        jsonschema.validate(plan_with_bare_deps, schema)

    def test_plan_with_all_optional_fields(self, schema, minimal_published_variant):
        """Plan with all optional meta fields should validate"""
        plan = minimal_published_variant.copy()
        plan["plan_meta"]["title"] = "Full Plan"
        plan["plan_meta"]["dual_mode"] = True
        plan["plan_meta"]["consumers"] = ["executor"]
        plan["plan_meta"]["global_invariants"] = ["INV-1"]
        plan["plan_meta"]["execution_notes"] = ["Note 1"]
        plan["structural_verdict"] = {"decision": "PASS"}
        plan["audit_log"] = [
            {
                "id": "AUD-1",
                "severity": "MEDIUM",
                "class": "test",
                "finding": "Test finding",
                "fix": "Fixed"
            }
        ]
        plan["requirement_ledger"] = [
            {"obligation": "REQ-1", "covered_by": ["S1"]}
        ]
        jsonschema.validate(plan, schema)


class TestTriadVariant:
    """Tests for triad variant (build_order + gate_status + steps)"""

    def test_minimal_triad_validates(self, schema, minimal_triad_variant):
        """Minimal triad variant should validate"""
        jsonschema.validate(minimal_triad_variant, schema)

    def test_triad_with_full_gates(self, schema, plan_with_plan_level_gates):
        """Triad with complete gate_status, blocking_defects, structural_faults"""
        jsonschema.validate(plan_with_plan_level_gates, schema)


class TestTolerantAdaptation:
    """Tests for tolerant handling of both formats"""

    def test_object_integration_checks_validates(self, schema, plan_with_object_integration_checks):
        """integration_checks as object should validate (real emit format)"""
        jsonschema.validate(plan_with_object_integration_checks, schema)

    def test_traces_to_field_validates(self, schema):
        """traces_to field should be accepted as alternative to traces_requirements"""
        plan = {
            "plan_meta": {
                "plan_id": "test-traces",
                "schema": "epiphany-plan.plan_document.v1",
                "source_spec": "~/test.md"
            },
            "coverage_verdict": {"decision": "PASS"},
            "steps": [
                {
                    "step_id": "S1",
                    "goal": "Implement",
                    "actions": ["Do"],
                    "acceptance_criteria": ["Done"],
                    "traces_to": ["REQ-001", "REQ-002"]  # Using traces_to instead
                }
            ],
            "execution_order": ["S1"]
        }
        jsonschema.validate(plan, schema)

    def test_array_integration_checks_validates(self, schema):
        """integration_checks as array of strings should validate"""
        plan = {
            "plan_meta": {
                "plan_id": "test-array-checks",
                "schema": "epiphany-plan.plan_document.v1",
                "source_spec": "~/test.md"
            },
            "coverage_verdict": {"decision": "PASS"},
            "steps": [
                {
                    "step_id": "S1",
                    "goal": "Build",
                    "actions": ["Do"],
                    "acceptance_criteria": ["Done"],
                    "integration_checks": ["Check 1", "Check 2"]  # Array format
                }
            ],
            "execution_order": ["S1"]
        }
        jsonschema.validate(plan, schema)


class TestEdgeCases:
    """Tests for edge cases and error conditions"""

    def test_missing_plan_meta_fails(self, schema, minimal_published_variant):
        """Plan without plan_meta should fail"""
        plan = minimal_published_variant.copy()
        del plan["plan_meta"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(plan, schema)

    def test_missing_steps_fails(self, schema, minimal_published_variant):
        """Plan without steps should fail"""
        plan = minimal_published_variant.copy()
        del plan["steps"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(plan, schema)

    def test_missing_both_coverage_and_gate_status_ok_with_tolerant_schema(self, schema):
        """Plan without coverage_verdict or gate_status is allowed (schema is tolerant)"""
        # The triad variant may omit coverage_verdict if gate_status is present
        # The published variant may omit gate_status if coverage_verdict is present
        # Both are optional to support both formats
        plan = {
            "plan_meta": {
                "plan_id": "test",
                "schema": "epiphany-plan.plan_document.v1",
                "source_spec": "~/test.md"
            },
            "steps": [
                {
                    "step_id": "S1",
                    "goal": "Do",
                    "actions": ["Do"],
                    "acceptance_criteria": ["Done"]
                }
            ],
            "execution_order": ["S1"]
        }
        # Should validate — minimal but valid plan
        jsonschema.validate(plan, schema)

    def test_empty_steps_fails(self, schema):
        """Plan with empty steps array should fail"""
        plan = {
            "plan_meta": {
                "plan_id": "test",
                "schema": "epiphany-plan.plan_document.v1",
                "source_spec": "~/test.md"
            },
            "coverage_verdict": {"decision": "PASS"},
            "steps": [],  # Empty
            "execution_order": []
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(plan, schema)

    def test_step_missing_required_fields_fails(self, schema):
        """Step without required fields (goal, actions, acceptance_criteria) should fail"""
        plan = {
            "plan_meta": {
                "plan_id": "test",
                "schema": "epiphany-plan.plan_document.v1",
                "source_spec": "~/test.md"
            },
            "coverage_verdict": {"decision": "PASS"},
            "steps": [
                {
                    "step_id": "S1"
                    # Missing: goal, actions, acceptance_criteria
                }
            ],
            "execution_order": ["S1"]
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(plan, schema)

    def test_step_with_empty_acceptance_criteria_fails(self, schema):
        """Step with empty acceptance_criteria should fail"""
        plan = {
            "plan_meta": {
                "plan_id": "test",
                "schema": "epiphany-plan.plan_document.v1",
                "source_spec": "~/test.md"
            },
            "coverage_verdict": {"decision": "PASS"},
            "steps": [
                {
                    "step_id": "S1",
                    "goal": "Do something",
                    "actions": ["Action"],
                    "acceptance_criteria": []  # Empty
                }
            ],
            "execution_order": ["S1"]
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(plan, schema)

    def test_invalid_coverage_verdict_decision_fails(self, schema):
        """Invalid coverage_verdict decision should fail"""
        plan = {
            "plan_meta": {
                "plan_id": "test",
                "schema": "epiphany-plan.plan_document.v1",
                "source_spec": "~/test.md"
            },
            "coverage_verdict": {"decision": "UNKNOWN"},  # Invalid
            "steps": [
                {
                    "step_id": "S1",
                    "goal": "Do",
                    "actions": ["Do"],
                    "acceptance_criteria": ["Done"]
                }
            ],
            "execution_order": ["S1"]
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(plan, schema)

    def test_invalid_edge_class_fails(self, schema):
        """Invalid edge_class should fail"""
        plan = {
            "plan_meta": {
                "plan_id": "test",
                "schema": "epiphany-plan.plan_document.v1",
                "source_spec": "~/test.md"
            },
            "coverage_verdict": {"decision": "PASS"},
            "steps": [
                {
                    "step_id": "S1",
                    "goal": "Do",
                    "actions": ["Do"],
                    "acceptance_criteria": ["Done"]
                },
                {
                    "step_id": "S2",
                    "goal": "Do",
                    "actions": ["Do"],
                    "acceptance_criteria": ["Done"],
                    "dependencies": [
                        {
                            "on": "S1",
                            "kind": "data",
                            "edge_class": "INVALID"  # Invalid
                        }
                    ]
                }
            ],
            "execution_order": ["S1", "S2"]
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(plan, schema)


class TestRealWorldExamples:
    """Tests with real-world plan structures"""

    def test_gotscs_v5_plan_structure(self, schema):
        """Test structure matching actual GOTSCS v5 plans"""
        plan = {
            "plan_meta": {
                "plan_id": "gotscs-v5-test",
                "schema": "epiphany-plan.plan_document.v1",
                "source_spec": "~/docs/solution/spec.md",
                "title": "GOTSCS v5 — Code-Artifact Builder",
                "consumers": ["inline-executor"],
                "global_invariants": ["APU-008 additive-only"],
                "execution_notes": ["Dependencies denote implementation order, not runtime flow"]
            },
            "coverage_verdict": {
                "decision": "PASS",
                "rationale": "Every requirement maps to >=1 step",
                "blocking": True,
                "audit_revision": "v2"
            },
            "gate_status": {
                "coverage_verdict": "PASS",
                "structural_verdict": "PASS"
            },
            "requirement_preservation": {
                "input_obligations": ["REQ-001", "REQ-002"]
            },
            "requirement_ledger": [
                {"obligation": "REQ-001", "covered_by": ["S1", "S2"]},
                {"obligation": "REQ-002", "covered_by": ["S3"]}
            ],
            "roots": ["S1"],
            "leaves": ["S3"],
            "execution_order": ["S1", "S2", "S3"],
            "steps": [
                {
                    "step_id": "S1",
                    "phase": "A",
                    "goal": "Phase A setup",
                    "actions": ["Setup infrastructure"],
                    "outputs": ["artifacts"],
                    "dependencies": [],
                    "acceptance_criteria": ["Setup complete"]
                },
                {
                    "step_id": "S2",
                    "phase": "B",
                    "goal": "Phase B implementation",
                    "actions": ["Implement features"],
                    "inputs": ["S1 artifacts"],
                    "outputs": ["feature-set"],
                    "dependencies": [
                        {"on": "S1", "kind": "data", "edge_class": "implementation-prerequisite"}
                    ],
                    "integration_checks": ["Prior output exists"],
                    "acceptance_criteria": ["Features working"]
                },
                {
                    "step_id": "S3",
                    "phase": "C",
                    "goal": "Testing and release",
                    "actions": ["Run tests", "Package"],
                    "dependencies": ["S2"],  # Bare string (tolerant)
                    "acceptance_criteria": ["Tests pass", "Package ready"]
                }
            ]
        }
        jsonschema.validate(plan, schema)
