"""Task B (S2/S3, plan portion) — N-write_plan.md must instruct the runtime to resolve the plan's
02-plan/ default via the resolver AND finalize the workspace manifest after the write, with an
EXPLICIT generic-path skip clause (INV-1). These are grep-level contract tests in the existing
module-structure-test style: the convention must be BAKED CODE referenced from the node contract,
not inline prose (APU-018 / R-2).
"""
from __future__ import annotations

import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE = os.path.normpath(os.path.join(HERE, "..", "modules", "N-write_plan.md"))
SKILL = os.path.normpath(os.path.join(HERE, "..", "SKILL.md"))


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_contract_mentions_finalize():
    text = _read(MODULE)
    assert "finalize_workspace.py" in text, \
        "N-write_plan.md must invoke tools/finalize_workspace.py after the write (Task B)"
    # the default out_path is resolver-routed (02-plan via the resolver / stage_subdir), not an
    # inline path string built in the node body (R-2).
    assert re.search(r"stage_subdir|02-plan", text), \
        "N-write_plan.md must route the default out_path through the resolver (stage_subdir/02-plan)"
    assert "solution_workspace" in text or "resolver" in text.lower()


def test_generic_skip_clause_present():
    """INV-1 guard: the finalize instruction must carry an explicit generic-path skip — the tool
    runs ONLY when a --solution-dir / target_profile workspace is present; absent => unchanged."""
    text = _read(MODULE)
    # a skip clause: 'generic' near 'skip'/'no-op'/'unchanged'/'only when'
    lowered = text.lower()
    assert "generic" in lowered, "missing generic-path mention (INV-1)"
    assert any(k in lowered for k in ("skip", "no-op", "noop", "unchanged", "only when", "absent")), \
        "missing an explicit generic skip clause (INV-1)"


def test_skill_documents_resolver_routed_default():
    text = _read(SKILL)
    assert "finalize_workspace" in text or "02-plan" in text, \
        "SKILL.md must document the resolver-routed 02-plan default + finalize step"
    assert "--solution-dir" in text
