---
node_id: plan_verify
exec_type: inline
tier: no-llm
input_ports:
  - port: plan_document
    format: any
    signal_field: plan_document
    required: true
  - port: written_path
    format: any
    signal_field: written_path
    required: false
  - port: integrated_plan
    format: any
    signal_field: integrated_plan
    required: true
  - port: requirements
    format: any
    signal_field: requirements
    required: true
  - port: output_format
    format: any
    signal_field: output_format
    required: false
output_ports:
  - port: structural_verdict
    format: any
    signal_field: structural_verdict
    required: true
  - port: schema_valid
    format: any
    signal_field: schema_valid
    required: false
  - port: violations
    format: any
    signal_field: violations
    required: false
---

# plan_verify

# plan_verify — STRUCTURAL & EXECUTOR-READINESS GATE (CODE-ENFORCED)

## Role

This is the **structural gate** for an epiphany-plan execution plan, and it is **code-enforced — it is NOT an LLM self-grade**. `coverage_audit` already adjudicated *requirement* coverage (does every obligation map to a step?). This gate adjudicates the **mechanically-checkable** properties that decide whether the rendered `plan_document` is a valid, executor-consumable graph — the properties a downstream executor (epiphany-executor) or a human editor must be able to trust without re-deriving them.

**The verdict is the EXIT of code, not a claim.** The node's `impl.target` is `tools/plan_verify_gate.py:run_gate`, which the harness runs deterministically under every provider (mirroring epiphany-brief's `N-COVERAGE` → `coverage_gate`). `run_gate`:

1. runs `jsonschema.validate(plan, plan.schema.json)` — a schema-invalid JSON plan (e.g. a dropped `plan_meta`, `id` instead of `step_id`, a non-canonical dialect the executor importer cannot ingest) FAILs here with the precise schema message;
2. invokes `tools/plan_verify.py`'s shipped checks 1–12 over the actual emitted artifact (it reuses `load_json_plan` / `load_md_plan` / `run_checks` — it does NOT reimplement them);
3. returns `{structural_verdict: "PASS"|"FAIL", schema_valid, violations, check_report}`.

`structural_verdict` is a bare `PASS`/`FAIL` string so the routing DSL branches on it: **`structural_verdict == 'PASS'` opens the forward edge to `write_plan`; `structural_verdict == 'FAIL'` opens the bounded (1-firing) refinement back-edge to `integrate`.** So `write_plan` cannot commit a plan this gate did not certify, and a non-canonical plan can no longer ship a false `PASS` — there is no agent verdict to launder.

This gate exists because coverage and structure are different failure surfaces: a plan can cover every requirement and still be structurally unexecutable (an edge ordered before its prerequisite, an obligation "covered" only by a test step, a leaf mislabeled, a schema-violating dialect). Those are the defects this gate catches deterministically.

## You do NOT self-grade

The agent does not write `structural_verdict`. The harness binds the output of `run_gate` directly to the `structural_verdict` signal. There is no inline reasoning step that can override or "eyeball-PASS" a plan the checker FAILed. If you are reading this as the running model, you have nothing to author at this node — the code runs and routes. The checks below document WHAT the code enforces (so a reader/auditor knows the gate's contract); they are no longer a checklist you grade by hand.

## Format awareness

Read `output_format` from the run seed (default `markdown`). The plan is either a **Markdown** document (default) or a **JSON** object (`--json`). **The checks below are identical in substance for both formats** — only how you locate each field differs:

- **Markdown:** parse the section headings and bold field labels emit renders (`## Coverage Verdict`, `## Requirement Ledger`, `## Graph` roots/leaves, `## Execution Order`, and each `### <step_id>` block with its `**goal** / **actions** / **inputs** / **outputs** / **dependencies** / **integration_checks** / **refinement_back_edges** / **acceptance_criteria** / **traces_requirements**` labels). A required heading or field label that is missing, or a code block elided with `...`, is a structural failure.
- **JSON:** validate against `plan.schema.json` (every step carries all required keys; envelope keys present and well-shaped).

The code runs every check mechanically over the actual `plan_document` content — nothing is eyeballed.

**The gate IS the checker (code-enforced).** `run_gate` is a thin wrapper that calls
`tools/plan_verify.py`'s `run_checks` (after a `jsonschema.validate` short-circuit). The shipped CLI is
the same code path, runnable by hand for inspection / CI:

```
python3 <skill_path>/tools/plan_verify.py <out_path>          # JSON: schema-validate + checks 1-12; MD: structure + graph checks
python3 <skill_path>/tools/plan_verify.py <out_path> --json-report
python3 <skill_path>/tools/plan_verify.py <out_path> --requirements <obligations.json>   # enable the BLOCKING coverage-closure check (8c)
python3 <skill_path>/tools/plan_verify_gate.py <out_path>     # the gate body itself; prints the verdict dict, exits 0 PASS / 1 FAIL
```

**Coverage closure (check 8c).** When the emitted plan carries
`requirement_preservation.input_obligations` (emit SHOULD populate it — the full obligation set from
`ingest`), or you pass `--requirements`, the checker runs a **blocking** requirements→ledger closure:
every obligation must appear in `requirement_ledger` with a non-empty `covered_by`. This is the
mechanical backstop for *coverage* (mirroring what this gate already does for *structure*); absent the
obligation set it degrades to advisory and coverage rests on the authoring node's `coverage_verdict`
alone. Also note check 1 now FAILs any step lacking `traces_requirements`/`traces_to`.

It exits non-zero and enumerates violations on FAIL. `structural_verdict` IS the tool's verdict (the
code returns it); on FAIL this node FAILs and the harness fires the back-edge to `integrate`. When a
run produces both formats, the JSON canonical is the executor-ingested artifact and must PASS.

## Inputs the gate reads

- `plan_document` — the rendered plan (the artifact `write_plan` will persist), in the active `output_format`. The gate inspects this in-state signal (and `written_path` if a file already exists).
- `integrated_plan` — the upstream step-graph (carried for context; the checks run over the emitted document).
- `requirements` — the obligation set from ingest; when it carries obligation ids, it enables the BLOCKING requirements→ledger closure (check 8c).

## Checks (each is BLOCKING unless marked ADVISORY)

1. **Completeness / schema conformance.** Every step carries `step_id · goal · actions · inputs · outputs · dependencies[{on,kind,edge_class}] · integration_checks · refinement_back_edges · acceptance_criteria · traces_requirements`, with no required field missing or empty. *(Markdown: every `###` step block has all bold field labels with non-empty values or an explicit `(none)`. JSON: validates against `plan.schema.json`.)*
2. **Dependency-reference integrity.** Every dependency target (`on`) and every `refinement_back_edges` target names a `step_id` that exists in the plan. No dangling references.
3. **Topological-order consistency.** `execution_order` is a valid topological sort of the `implementation-prerequisite`/`ordering` edges: for every such edge `A→B`, `A` precedes `B` in `execution_order`. Name every violation as `(step, unmet_dependency)`.
4. **Acyclicity of the forward graph.** The forward (non-back-edge) dependency graph has no cycles. A genuine refinement link must live in `refinement_back_edges`, not in `dependencies`. Report any cycle path.
5. **Roots / leaves correctness.** `roots` = exactly the steps with no dependencies (true sources); `leaves` = exactly the steps no step depends on (true sinks). Flag any mislabel. (Semantic "terminal milestones" are a separate, optional field and are NOT required to equal the graph leaves.)
6. **Edge-class declared.** Every dependency carries an `edge_class` ∈ {`implementation-prerequisite`, `runtime-data`, `ordering`}. A runtime-data input supplied at execution time (not built by a predecessor) must NOT appear as a build-order dependency — it is declared in `inputs` prose or tagged `runtime-data`.
7. **Test-without-implementation.** No obligation in the requirement ledger is discharged *only* by a verification/test/audit step. Every obligation must trace to at least one step that *produces or implements* it, not merely one that *checks* it. Name any obligation covered only by a test step.
8. **Ledger ↔ step closure.** Every `covered_by` entry in the requirement ledger resolves to a real `step_id`; every `requirements` obligation appears in the ledger (cross-check against `coverage_audit`, do not silently re-pass a coverage gap).
9. **Coverage-verdict honored (ADVISORY → BLOCKING under disagreement).** If `coverage_audit` returned FAIL, this gate must also FAIL. If it returned PASS but checks 7–8 find an orphan/hollow obligation, FAIL and name the disagreement — the optimistic PASS is the defect.
10. **Format integrity.** The document is emitted in the requested `output_format` only (no format-split / hybrid), and the no-detail-lost contract holds (Markdown code blocks are complete and un-elided; JSON parses).

## Verdict (computed, not asserted)

`run_gate` returns **PASS** only when the schema validates (JSON) and checks 1–8 and 10 hold (9 consistent). Otherwise **FAIL**, with every violation enumerated by id (offending `step_id`, `dependency`, or `obligation`) in `violations`, so the `integrate` refinement loop can repair it. The back-edge to `integrate` is capped at one firing; if the plan still FAILs after that single repair, neither the PASS-gated forward edge nor the exhausted back-edge fires — the run refuses to write (a fail-closed convergence halt), exactly as intended for an unexecutable plan. The gate fails CLOSED: a plan that even crashes the checker (a non-checkable dialect) returns FAIL, never a non-verdict.

## Failure modes the code-enforcement closes

- **Eyeballed pass:** impossible — the agent does not author `structural_verdict`; the code does.
- **False PASS in a non-canonical dialect:** the `jsonschema.validate` short-circuit FAILs a dropped `plan_meta` / renamed `step_id` / wrong-typed field with the precise schema message before any soft check can be coaxed to PASS. This is the bug this gate closes.
- **Structure-blind coverage trust:** checks 7–8/8c run regardless of `coverage_audit`'s verdict.
- **Repairing in place:** the gate adjudicates and routes; it does not rewrite steps (that is `integrate`'s job on the FAIL back-edge).

## Output

The harness binds `run_gate`'s return to: `structural_verdict` (PASS|FAIL — the routing signal), `schema_valid` (bool), and `violations` (the per-violation list). No hand-authored output.
