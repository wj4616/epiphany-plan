"""Markdown structure tests for epiphany-plan outputs.

Verifies that:
1. Markdown plans have required sections and headings
2. Steps are properly formatted with required metadata
3. Coverage and structural verdicts are present in Markdown
4. Integration checks and acceptance criteria are parseable
"""
import re
from pathlib import Path


def parse_markdown_headings(content: str) -> dict:
    """Extract heading structure from Markdown content"""
    headings = {}
    lines = content.split('\n')
    current_h1 = None
    current_h2 = None

    for line in lines:
        if line.startswith('# ') and not line.startswith('# #'):
            current_h1 = line[2:].strip()
            headings[current_h1] = {}
            current_h2 = None
        elif line.startswith('## ') and not line.startswith('## #'):
            current_h2 = line[3:].strip()
            if current_h1:
                headings[current_h1][current_h2] = []
        elif current_h2 and current_h1:
            headings[current_h1][current_h2].append(line)

    return headings


class TestMarkdownStructure:
    """Tests for Markdown plan structure"""

    @staticmethod
    def sample_markdown_plan() -> str:
        """Sample valid Markdown plan"""
        return """# PLAN: Test Implementation Plan

## Overview
This is a test plan for validating structure.

## Coverage Verdict
- **decision:** PASS
- **rationale:** All requirements covered
- **blocking:** true

## Structural Verdict
- **decision:** PASS
- **checks:** (structure valid)

## Requirement Ledger
- REQ-001 → covered by S1, S2
- REQ-002 → covered by S3

## Roots (DAG sources)
- S1

## Leaves (DAG sinks)
- S3

## Execution Order
1. S1 (Phase A)
2. S2 (Phase B)
3. S3 (Phase C)

---

## Step S1: Setup

**Phase:** A
**Goal:** Initialize infrastructure

**Actions:**
- Create directories
- Load configuration

**Inputs:**
- Base configuration file

**Outputs:**
- Initialized workspace
- Configuration state

**Dependencies:**
- (none)

**Integration Checks:**
- Verify directories exist

**Refinement Back-edges:**
- S2 (if inputs change)

**Acceptance Criteria:**
- Workspace ready
- Configuration loaded

**Traces to:** REQ-001

---

## Step S2: Build

**Phase:** B
**Goal:** Implement features

**Actions:**
- Write code
- Compile

**Inputs:**
- S1 workspace
- Requirements document

**Outputs:**
- Built artifacts
- Feature set

**Dependencies:**
- S1 (data: implementation-prerequisite)

**Integration Checks:**
- Prior step completed
- Dependencies satisfied

**Refinement Back-edges:**
- S3 (if code changes)

**Acceptance Criteria:**
- Code compiles
- Features working

**Traces to:** REQ-001, REQ-002

---

## Step S3: Test & Release

**Phase:** C
**Goal:** Validate and release

**Actions:**
- Run test suite
- Package artifacts

**Inputs:**
- S2 artifacts

**Outputs:**
- Test results
- Release package

**Dependencies:**
- S2 (ordering)

**Integration Checks:**
- Outputs available

**Acceptance Criteria:**
- Tests pass
- Package ready

**Traces to:** REQ-002
"""

    def test_markdown_has_title(self):
        """Plan should have a # PLAN: title"""
        content = self.sample_markdown_plan()
        assert '# PLAN:' in content or content.startswith('# ')
        assert re.search(r'# PLAN?:', content), "Plan should have a title"

    def test_markdown_has_coverage_verdict_section(self):
        """Plan should have Coverage Verdict section"""
        content = self.sample_markdown_plan()
        assert re.search(r'## .*Coverage.*Verdict', content), \
            "Plan should have 'Coverage Verdict' section"

    def test_markdown_has_structural_verdict_section(self):
        """Plan should have Structural Verdict section"""
        content = self.sample_markdown_plan()
        assert re.search(r'## .*Structural.*Verdict', content), \
            "Plan should have 'Structural Verdict' section"

    def test_markdown_has_requirement_ledger(self):
        """Plan should have Requirement Ledger section"""
        content = self.sample_markdown_plan()
        assert re.search(r'## .*Requirement.*Ledger', content), \
            "Plan should have 'Requirement Ledger' section"

    def test_markdown_has_dag_sections(self):
        """Plan should have DAG structure sections (roots, leaves, order)"""
        content = self.sample_markdown_plan()
        assert re.search(r'## .*Roots', content) or re.search(r'DAG source', content), \
            "Should document DAG roots"
        assert re.search(r'## .*Leaves', content) or re.search(r'DAG sink', content), \
            "Should document DAG leaves"
        assert re.search(r'## .*Execution.*Order', content) or re.search(r'execution order', content, re.IGNORECASE), \
            "Should document execution order"

    def test_steps_have_required_fields(self):
        """Each step should have required fields (phase, goal, actions, acceptance_criteria)"""
        content = self.sample_markdown_plan()
        # Find all step sections (## Step <id>: ...)
        steps = re.findall(r'## Step (\S+):(.*?)(?=## Step |\Z)', content, re.DOTALL)
        assert len(steps) > 0, "Plan should have at least one step"

        for step_id, step_content in steps:
            assert '**Phase:**' in step_content, f"Step {step_id} missing Phase"
            assert '**Goal:**' in step_content, f"Step {step_id} missing Goal"
            assert '**Actions:**' in step_content, f"Step {step_id} missing Actions"
            assert '**Acceptance Criteria:**' in step_content, f"Step {step_id} missing Acceptance Criteria"

    def test_steps_have_metadata_fields(self):
        """Each step should have metadata fields (inputs, outputs, dependencies, traces)"""
        content = self.sample_markdown_plan()
        steps = re.findall(r'## Step (\S+):(.*?)(?=## Step |\Z)', content, re.DOTALL)

        for step_id, step_content in steps:
            assert '**Inputs:**' in step_content or '**inputs:**' in step_content.lower(), \
                f"Step {step_id} missing Inputs section"
            assert '**Outputs:**' in step_content or '**outputs:**' in step_content.lower(), \
                f"Step {step_id} missing Outputs section"
            assert '**Dependencies:**' in step_content or '**dependencies:**' in step_content.lower(), \
                f"Step {step_id} missing Dependencies"
            assert '**Traces' in step_content or 'traces' in step_content.lower(), \
                f"Step {step_id} missing requirement traces"

    def test_coverage_verdict_has_decision(self):
        """Coverage verdict should have decision field"""
        content = self.sample_markdown_plan()
        assert re.search(r'\*\*decision:\*\*\s*(PASS|FAIL)', content, re.IGNORECASE), \
            "Coverage verdict should specify PASS or FAIL"

    def test_coverage_verdict_has_rationale(self):
        """Coverage verdict should have rationale"""
        content = self.sample_markdown_plan()
        assert re.search(r'rationale:', content, re.IGNORECASE), \
            "Coverage verdict should have rationale"

    def test_acceptance_criteria_are_lists(self):
        """Acceptance criteria should be formatted as a list"""
        content = self.sample_markdown_plan()
        steps = re.findall(r'## Step (\S+):(.*?)(?=## Step |\Z)', content, re.DOTALL)

        for step_id, step_content in steps:
            # Extract acceptance criteria section
            ac_match = re.search(r'\*\*Acceptance Criteria:\*\*(.*?)(?=\*\*|##)', step_content, re.DOTALL)
            if ac_match:
                ac_section = ac_match.group(1)
                # Should have bullet points or numbered list
                assert re.search(r'[-*•]\s+\S', ac_section) or re.search(r'\d+\.\s+\S', ac_section), \
                    f"Step {step_id} acceptance criteria should be a list"

    def test_integration_checks_documented(self):
        """Integration checks should be documented"""
        content = self.sample_markdown_plan()
        steps = re.findall(r'## Step (\S+):(.*?)(?=## Step |\Z)', content, re.DOTALL)

        for step_id, step_content in steps:
            # Most steps should have integration checks
            if 'S2' in step_id or 'S3' in step_id:  # Dependent steps especially
                assert 'Integration Check' in step_content, \
                    f"Step {step_id} (depends on others) should have integration checks"


class TestRoundTripValidation:
    """Tests for converting between formats"""

    def test_json_to_markdown_preserves_structure(self):
        """Converting JSON to Markdown should preserve all required structure"""
        # This is a template test — actual conversion would be done by emit
        # but we can verify the format is compatible
        json_plan = {
            "plan_meta": {
                "plan_id": "roundtrip-test",
                "schema": "epiphany-plan.plan_document.v1",
                "source_spec": "~/test.md",
                "title": "Roundtrip Test Plan"
            },
            "coverage_verdict": {
                "decision": "PASS",
                "rationale": "Test coverage complete"
            },
            "steps": [
                {
                    "step_id": "S1",
                    "goal": "Setup",
                    "actions": ["Initialize"],
                    "acceptance_criteria": ["Ready"],
                    "traces_requirements": ["REQ-1"]
                }
            ],
            "execution_order": ["S1"]
        }

        # Verify JSON has all the fields that Markdown would need
        assert json_plan["plan_meta"]["plan_id"], "Need plan_id for Markdown title"
        assert json_plan["coverage_verdict"]["decision"], "Need coverage decision"
        assert json_plan["steps"], "Need steps for Markdown"
        for step in json_plan["steps"]:
            assert step["step_id"], "Need step_id"
            assert step["goal"], "Need goal"
            assert step["actions"], "Need actions"
            assert step["acceptance_criteria"], "Need acceptance criteria"

    def test_markdown_to_json_extractable(self):
        """Markdown plan should be parseable back to JSON structure"""
        content = TestMarkdownStructure.sample_markdown_plan()

        # Extract key elements
        title_match = re.search(r'# PLAN:\s*(.*)', content)
        assert title_match, "Should extract plan title"

        coverage_match = re.search(r'\*\*decision:\*\*\s*(PASS|FAIL)', content, re.IGNORECASE)
        assert coverage_match, "Should extract coverage verdict"

        steps = re.findall(r'## Step (\S+):', content)
        assert len(steps) > 0, "Should extract step IDs"

        # Verify step details are extractable
        for step_id in steps:
            step_pattern = rf'## Step {re.escape(step_id)}:(.*?)(?=## Step |\Z)'
            step_content = re.search(step_pattern, content, re.DOTALL)
            assert step_content, f"Should extract step {step_id}"

            goal_match = re.search(r'\*\*Goal:\*\*(.*?)(?=\n|\*\*)', step_content.group(1))
            assert goal_match, f"Step {step_id} should have goal"
