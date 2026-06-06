"""Regression tests for tools/plan_verify.py and tools/render_markdown.py.

Covers the 2026-06-06 audit fixes (F1-F7):
- F1: dangling refinement_back_edge to a hyphenated id (`S-M0-99`) FAILs check 2b; a valid exact-id
      back-edge does NOT raise the spurious 2b* advisory.
- F2: a step with no traces_requirements/traces_to FAILs check 1 (JSON + Markdown).
- F3: BLOCKING requirements->ledger closure (8c) from requirement_preservation.input_obligations and
      from --requirements.
- F4: harness-forge plans surface the harness-first tag advisory.
- F6: render_markdown carries audit_log + requirement_preservation through to the Markdown.
- F7: a large linear plan does not blow the recursion limit.
These tools had zero test coverage before this file.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
PLAN_VERIFY = ROOT / "tools" / "plan_verify.py"
RENDER_MD = ROOT / "tools" / "render_markdown.py"


def run_verify(path, *extra):
    r = subprocess.run([sys.executable, str(PLAN_VERIFY), str(path), *extra],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def render(path, *extra):
    r = subprocess.run([sys.executable, str(RENDER_MD), str(path), *extra],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def step(sid, deps=None, back=None, traces=("R-1",), **over):
    s = {
        "step_id": sid, "goal": f"goal {sid}", "actions": [f"build {sid}"],
        "inputs": [], "outputs": [f"{sid}-out"],
        "dependencies": deps or [], "integration_checks": [f"ic {sid}"],
        "refinement_back_edges": back or [], "acceptance_criteria": [f"ac {sid}"],
        "traces_requirements": list(traces),
    }
    s.update(over)
    return s


def base_plan(steps, **over):
    ids = [s["step_id"] for s in steps]
    depended = {d["on"] for s in steps for d in s["dependencies"]}
    has_dep = {s["step_id"] for s in steps if s["dependencies"]}
    d = {
        "plan_meta": {"plan_id": "t", "schema": "epiphany-plan.plan_document.v1", "source_spec": "~/x.md"},
        "coverage_verdict": {"decision": "PASS", "blocking": True},
        "roots": sorted(i for i in ids if i not in has_dep),
        "leaves": sorted(i for i in ids if i not in depended),
        "execution_order": ids,
        "requirement_ledger": [{"obligation": "R-1", "covered_by": ids[:1]}],
        "steps": steps,
    }
    d.update(over)
    return d


def write(tmp, doc, name="plan.json"):
    p = tmp / name
    p.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return p


# ---------------------------------------------------------------- F1 dangling back-edge
def test_f1_dangling_hyphenated_backedge_fails(tmp_path):
    steps = [step("S-M0-1", back=["S-M0-99"]),  # S-M0-99 does not exist
             step("S-M0-2", deps=[{"on": "S-M0-1", "kind": "data", "edge_class": "implementation-prerequisite"}])]
    code, out = run_verify(write(tmp_path, base_plan(steps)))
    assert code == 1, out
    assert "2b" in out and ("S-M0-99" in out)


def test_f1_valid_exact_id_backedge_no_spurious_advisory(tmp_path):
    steps = [step("S-M0-1", back=["S-M0-2"]),
             step("S-M0-2", deps=[{"on": "S-M0-1", "kind": "data", "edge_class": "implementation-prerequisite"}])]
    code, out = run_verify(write(tmp_path, base_plan(steps)))
    assert code == 0, out
    # the old tokenizer raised "2b*" non-referential on every hyphenated id; it must be gone now.
    assert "2b*" not in out


# ---------------------------------------------------------------- F2 traces enforced
def test_f2_missing_traces_fails_json(tmp_path):
    s = step("A1")
    s.pop("traces_requirements")
    code, out = run_verify(write(tmp_path, base_plan([s])))
    assert code == 1, out
    assert "traces" in out.lower()


def test_f2_traces_to_alias_passes(tmp_path):
    s = step("A1", traces=())
    s["traces_to"] = ["R-1"]  # the alias satisfies the requirement
    code, out = run_verify(write(tmp_path, base_plan([s])))
    assert code == 0, out


def test_f2_missing_traces_fails_markdown(tmp_path):
    # render a plan, then strip the traces line, and confirm the md path FAILs.
    p = write(tmp_path, base_plan([step("A1")]))
    code, _ = render(p, "-o", str(tmp_path / "plan.md"))
    assert code == 0
    md = (tmp_path / "plan.md").read_text()
    md2 = "\n".join(l for l in md.splitlines() if "traces_requirements" not in l)
    (tmp_path / "plan2.md").write_text(md2)
    code, out = run_verify(tmp_path / "plan2.md")
    assert code == 1, out
    assert "traces" in out.lower()


# ---------------------------------------------------------------- F3 coverage closure
def test_f3_input_obligations_closure_fails_when_uncovered(tmp_path):
    doc = base_plan([step("A1")])
    doc["requirement_preservation"] = {"input_obligations": ["R-1", "R-2"]}  # R-2 not in ledger
    code, out = run_verify(write(tmp_path, doc))
    assert code == 1, out
    assert "8c" in out and "R-2" in out


def test_f3_input_obligations_closure_passes_when_complete(tmp_path):
    doc = base_plan([step("A1")])
    doc["requirement_preservation"] = {"input_obligations": ["R-1"]}
    code, out = run_verify(write(tmp_path, doc))
    assert code == 0, out
    assert "8c" in out


def test_f3_requirements_arg_enables_closure(tmp_path):
    doc = base_plan([step("A1")])
    p = write(tmp_path, doc)
    req = tmp_path / "obl.json"
    req.write_text(json.dumps(["R-1", "R-2"]))  # R-2 uncovered
    code, out = run_verify(p, "--requirements", str(req))
    assert code == 1, out
    assert "8c" in out


# ---------------------------------------------------------------- F4 harness-forge advisory
def test_f4_harness_forge_tags_advisory(tmp_path):
    doc = base_plan([step("A1")])
    doc["plan_meta"]["target_profile"] = "harness-forge"
    code, out = run_verify(write(tmp_path, doc))
    assert code == 0, out
    assert "harness-forge tags" in out
    assert "ABSENT" in out  # no obligation_class/target_subsystem tags carried


def test_f4_harness_forge_tags_present(tmp_path):
    s = step("A1", obligation_class="capability-closure", target_subsystem="compiler")
    doc = base_plan([s])
    doc["plan_meta"]["target_profile"] = "harness-forge"
    code, out = run_verify(write(tmp_path, doc))
    assert code == 0, out
    assert "PRESENT" in out


# ---------------------------------------------------------------- F6 renderer carries metadata
def test_f6_render_carries_audit_log_and_obligations(tmp_path):
    doc = base_plan([step("A1")])
    doc["requirement_preservation"] = {"input_obligations": ["R-1"]}
    doc["audit_log"] = [{"id": "AUD-1", "severity": "HIGH", "class": "orphan",
                         "finding": "x dangled", "fix": "wired x->y"}]
    p = write(tmp_path, doc)
    code, _ = render(p, "-o", str(tmp_path / "plan.md"))
    assert code == 0
    md = (tmp_path / "plan.md").read_text()
    assert "## Audit Log" in md and "AUD-1" in md and "wired x->y" in md
    assert "## Input Obligations" in md and "R-1" in md
    # and the rendered md still passes the gate
    code, out = run_verify(tmp_path / "plan.md")
    assert code == 0, out


# ---------------------------------------------------------------- F7 large plan / recursion
def test_f7_large_linear_plan_no_recursion_error(tmp_path):
    steps = [step("S-0", traces=("R-1",))]
    for i in range(1, 300):
        steps.append(step(f"S-{i}",
                          deps=[{"on": f"S-{i-1}", "kind": "ordering", "edge_class": "implementation-prerequisite"}]))
    doc = base_plan(steps)
    doc["requirement_ledger"] = [{"obligation": "R-1", "covered_by": ["S-0"]}]
    code, out = run_verify(write(tmp_path, doc))
    assert code == 0, out[-800:]


# ---------------------------------------------------------------- baseline: a good plan passes
def test_baseline_good_plan_passes(tmp_path):
    steps = [step("S-A"),
             step("S-B", deps=[{"on": "S-A", "kind": "data", "edge_class": "implementation-prerequisite"}],
                  back=["S-A"])]
    code, out = run_verify(write(tmp_path, base_plan(steps)))
    assert code == 0, out
