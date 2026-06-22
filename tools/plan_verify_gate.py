#!/usr/bin/env python3
"""Code-enforced structural gate for the `plan_verify` node (the deterministic teeth).

This is the `impl.target` of the `plan_verify` graph node. It mirrors epiphany-brief's
`coverage_gate`: the gate's verdict is the EXIT of real validation code (jsonschema +
`plan_verify.py`'s shipped checks 1-12), NOT an LLM self-grade. The verdict drives routing —
a FAIL fires the bounded back-edge to `integrate` (repair); only a PASS opens the forward edge
to `write_plan`. So a plan in a non-canonical dialect the executor cannot ingest (e.g. a
schema-invalid JSON, `id` instead of `step_id`, a dropped `plan_meta`) can no longer ship a
false `structural_verdict: PASS`.

The node reads the rendered `plan_document` (the in-state signal emit produced; written to disk
by `write_plan` only AFTER this gate passes) plus the `output_format` and optional
`requirements` obligation set, and returns:

    {structural_verdict: "PASS"|"FAIL", schema_valid: bool, violations: [...], check_report: [...]}

`structural_verdict` is a bare PASS/FAIL string so the edge DSL (`structural_verdict == 'PASS'`)
branches cleanly. The detail (per-check results + violation list) rides alongside for the
`integrate` repair node and the run ledger.
"""
from __future__ import annotations

import json
import os
import sys

# Reuse plan_verify.py's parsers + checks verbatim — do NOT reimplement the validation.
# Dual-context import: as `tools.plan_verify_gate` (the harness impl.target path — package-relative)
# OR as a bare script (`python3 tools/plan_verify_gate.py` — add this dir to sys.path).
try:
    from . import plan_verify as _pv  # type: ignore  # noqa
except ImportError:  # pragma: no cover - script-mode fallback
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import plan_verify as _pv  # type: ignore  # noqa


def _load_schema():
    spath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plan.schema.json")
    if os.path.exists(spath):
        try:
            return json.load(open(spath, encoding="utf-8"))
        except (ValueError, OSError):
            return None
    return None


def _obligations_from(requirements):
    """Best-effort pull of an obligation-id list from the `requirements` signal so check 8c
    (requirements -> ledger closure) runs BLOCKING when the obligation set is known. Accepts a
    list of ids, a list of obligation dicts (`id`/`obligation_id`/`obligation`), or a dict
    carrying `requirement_preservation.input_obligations` / `input_obligations`."""
    if not requirements:
        return None
    obls = requirements
    if isinstance(requirements, dict):
        rp = requirements.get("requirement_preservation")
        obls = (rp.get("input_obligations") if isinstance(rp, dict) else None) \
            or requirements.get("input_obligations") \
            or requirements.get("obligations")
    if not isinstance(obls, list):
        return None
    out = []
    for o in obls:
        if isinstance(o, str):
            out.append(o)
        elif isinstance(o, dict):
            oid = o.get("id") or o.get("obligation_id") or o.get("obligation")
            if oid:
                out.append(str(oid))
    return out or None


def run_gate(plan_path=None, plan_document=None, output_format=None, requirements=None,
             requirements_path=None):
    """Run the deterministic structural gate over the emitted plan.

    Exactly one source of the plan body is required: a `plan_path` on disk OR the rendered
    `plan_document` string/object held in node state. Returns a verdict dict (never raises on a
    plan defect — a defect is a FAIL verdict that the graph routes to `integrate`; it only raises
    when it has no plan to inspect at all, which is a wiring error, not a plan defect).
    """
    # ---- materialise the plan text + detect format ------------------------------------------
    text = None
    if plan_path and os.path.exists(str(plan_path)):
        text = open(str(plan_path), encoding="utf-8").read()
        fmt = "json" if str(plan_path).endswith(".json") or text.lstrip().startswith("{") else "md"
    elif plan_document is not None:
        if isinstance(plan_document, (dict, list)):
            text = json.dumps(plan_document)
            fmt = "json"
        else:
            text = str(plan_document)
            fmt = "json" if text.lstrip().startswith("{") else "md"
    else:
        raise RuntimeError("plan_verify gate: no plan to inspect (neither plan_path nor "
                           "plan_document provided) — wiring error, not a plan defect.")

    # An explicit output_format overrides the sniffed one when it is meaningful.
    of = str(output_format or "").strip().lower()
    if of in ("json", "markdown", "md"):
        fmt = "json" if of == "json" else ("md" if fmt != "json" or of != "json" else "json")
        # keep it simple: trust an explicit format only to disambiguate, never to force json on md text
        if of == "json" and not text.lstrip().startswith("{"):
            fmt = "md"
        elif of in ("markdown", "md"):
            fmt = "md"

    # ---- parse + run the shipped checks (schema-validate + 1..12) ---------------------------
    schema = None
    doc = None
    if fmt == "json":
        try:
            doc = json.loads(text)
        except Exception as ex:  # noqa
            return {"structural_verdict": "FAIL", "schema_valid": False,
                    "violations": [f"[10 format-integrity] JSON does not parse: {ex}"],
                    "check_report": [{"id": "10", "name": "format-integrity", "status": "FAIL"}]}
        P = _pv.load_json_plan(doc)
        schema = _load_schema()
        # Schema short-circuit: a JSON plan that violates plan.schema.json is, by definition, in a
        # dialect the executor importer cannot ingest (e.g. dropped `plan_meta`, `id` instead of
        # `step_id`). Return that as the verdict with a precise message FIRST — both so the FAIL
        # names the real defect (not a downstream checker-error), and so the malformed doc never
        # reaches the graph-algorithm checks that legitimately assume canonical ids.
        if _pv._jsonschema is not None and schema is not None:
            try:
                _pv._jsonschema.validate(doc, schema)
            except Exception as ex:  # noqa  (jsonschema.ValidationError + friends)
                msg = str(getattr(ex, "message", ex))
                return {"structural_verdict": "FAIL", "schema_valid": False,
                        "violations": [f"[10 schema/format-integrity] plan.schema.json invalid: "
                                       f"{msg[:240]}"],
                        "check_report": [{"id": "10", "name": "schema/format-integrity",
                                          "status": "FAIL"}],
                        "format": fmt}
    else:
        P = _pv.load_md_plan(text)

    # obligation set -> BLOCKING check 8c when available
    req_obl = _obligations_from(requirements)
    if not req_obl and requirements_path and os.path.exists(str(requirements_path)):
        try:
            rq = json.load(open(str(requirements_path), encoding="utf-8"))
            req_obl = _obligations_from(rq) or _obligations_from({"input_obligations": rq})
        except Exception:  # noqa
            req_obl = None
    if req_obl:
        P["req_obligations"] = req_obl

    try:
        results, violations = _pv.run_checks(P, fmt, schema=schema, doc=doc)
    except Exception as ex:  # noqa  — fail CLOSED: a plan that crashes the checker is not
        # executor-ingestible. Never let an exception escape into a non-verdict the router can't
        # branch on (that would re-open the false-PASS hole from the other side).
        return {"structural_verdict": "FAIL", "schema_valid": False,
                "violations": [f"[checker-error] structural checks raised "
                               f"{type(ex).__name__}: {ex} (plan is not in a checkable dialect)"],
                "check_report": [{"id": "0", "name": "checker-error", "status": "FAIL"}],
                "format": fmt}
    passed = not violations
    schema_valid = True
    if fmt == "json":
        # schema_valid reflects check 10 specifically (None/SKIP when jsonschema is unavailable).
        for cid, _name, status in results:
            if cid == "10":
                schema_valid = status == "PASS"
                break

    return {
        "structural_verdict": "PASS" if passed else "FAIL",
        "schema_valid": schema_valid,
        "violations": violations,
        "check_report": [{"id": c, "name": n, "status": s} for c, n, s in results],
        "format": fmt,
    }


if __name__ == "__main__":  # pragma: no cover - manual smoke
    import sys
    rep = run_gate(plan_path=sys.argv[1] if len(sys.argv) > 1 else None,
                   requirements_path=sys.argv[2] if len(sys.argv) > 2 else None)
    print(json.dumps(rep, indent=2))
    sys.exit(0 if rep["structural_verdict"] == "PASS" else 1)
