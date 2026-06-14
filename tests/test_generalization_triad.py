"""S10 generalization triad for epiphany-plan (WC-13 / APU-013,014,017,019 / R-1,R-12).

  1. byte-identity (generic): finalize_workspace on a GENERIC plan writes NO harness_ledger key into
     solution.json and adds NO harness key to plan_meta.
  2. harness-activation: on a HARNESS plan the ledger is mirrored into solution.json.
  3. cross-stage-trace (per-skill slice): the plan RECEIVES the upstream chain (resolves the same
     workspace from the spec handoff) and FORWARDS the chain fields into plan_meta for the executor.

R-12 resolver drift: covered by the existing test_solution_workspace_in_sync (re-asserted present).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.normpath(os.path.join(HERE, "..", "tools", "finalize_workspace.py"))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "tools")))
import solution_workspace as sw  # noqa: E402


def _ws(tmp_path, slug):
    os.environ["EPIPHANY_SOLUTION_ROOT"] = str(tmp_path)
    return sw.resolve(slug=slug, date="2026-06-14")


def _plan(ws, *, harness, ledger=None):
    pm = {"plan_id": "p", "title": "T"}
    if harness:
        pm["target_profile"] = "harness-forge"
    plan = {"plan_meta": pm, "steps": [{"step_id": "S0", "goal": "g"}]}
    if ledger:
        plan["harness_ledger"] = ledger
    return plan


def _run(plan_file, ws):
    return subprocess.run([sys.executable, TOOL, plan_file, "--solution-dir", ws, "--in-place"],
                          capture_output=True, text=True)


def _write(ws, plan):
    f = os.path.join(sw.stage_subdir(ws, "plan"), "plan.json")
    with open(f, "w", encoding="utf-8") as fh:
        json.dump(plan, fh)
    return f


class TestByteIdentityGeneric:
    def test_generic_finalize_no_harness_key(self, tmp_path):
        ws = _ws(tmp_path, "t-gen")
        f = _write(ws, _plan(ws, harness=False))
        assert _run(f, ws).returncode == 0
        man = sw.read_manifest(ws)
        assert "harness_ledger" not in man
        doc = json.load(open(f))
        assert "harness_ledger" not in doc["plan_meta"]
        assert "target_profile" not in doc["plan_meta"]


class TestHarnessActivation:
    def test_harness_finalize_mirrors_ledger(self, tmp_path):
        ws = _ws(tmp_path, "t-act")
        ledger = sw.seed_ledger(["G"], statuses={"G": "full"})
        f = _write(ws, _plan(ws, harness=True, ledger=ledger))
        assert _run(f, ws).returncode == 0
        man = sw.read_manifest(ws)
        assert man["harness_ledger"]["G"]["status"] == "full"


class TestCrossStageTrace:
    def test_plan_receives_chain_and_forwards_to_executor(self, tmp_path):
        ws = _ws(tmp_path, "t-trace")
        # simulate the upstream spec handoff carrying the chain
        sw.update_stage(ws, "spec", {"status": "complete", "primary": "spec-final.md"})
        spec_handoff = os.path.join(sw.stage_subdir(ws, "spec"), "handoff.json")
        with open(spec_handoff, "w", encoding="utf-8") as fh:
            json.dump({"solution_dir": os.path.abspath(ws), "stage": "spec",
                       "next_skill": "epiphany-plan"}, fh)
        # the plan resolves the SAME workspace from the spec handoff (receives)
        again = sw.resolve(upstream=spec_handoff)
        assert os.path.abspath(again) == os.path.abspath(ws)
        # and forwards the chain fields to the executor (next_skill)
        f = _write(ws, _plan(ws, harness=True))
        assert _run(f, ws).returncode == 0
        doc = json.load(open(f))
        assert doc["plan_meta"]["next_skill"] == "epiphany-executor"
        assert doc["plan_meta"]["prev_stage"] == "spec"
        assert doc["plan_meta"]["solution_dir"] == os.path.abspath(ws)


def test_resolver_sync_check_exists():
    assert os.path.isfile(os.path.join(HERE, "test_solution_workspace_in_sync.py"))
