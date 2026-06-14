# epiphany-plan

## NAME

`epiphany-plan` — a native graph-of-agentic-thought skill ((derived at runtime)).

## INVOCATION

Run via the harness:
```
goatcs-harness run graph.json                 # Markdown plan (default)
goatcs-harness run graph.json --json          # JSON plan (plan.schema.json)
goatcs-harness run graph.json --markdown      # explicit Markdown (same as default)
goatcs-harness run graph.json --json --waiver O=reason   # audited harness-facet waiver (harness-forge only)
```
Provider-agnostic: the graph is identical across runtimes; only the live author/runtime provider differs (see RUNTIME CONVENTIONS).

**Output format.** The plan is emitted in **Markdown by default** — readable, hand-editable, with full code/command/config examples inline in fenced blocks. `--json` emits the machine-strict JSON contract (`plan.schema.json`) for programmatic executor consumption; `--markdown` selects the default explicitly. The flag sets the `output_format` seed signal (`markdown` | `json`); absent/empty → `markdown`. Both formats are lossless renderings of the same content contract.

## RUNTIME CONVENTIONS

This skill is **provider-agnostic** — one graph, any supported runtime. Runtime preflight — it runs under:
- `claude-cli`
- `codex`

The harness selects/falls back across these at run time; no per-agent variant is emitted (v2.0).

## ALGORITHM

Topology class: **(derived at runtime)**. The graph has 10 node(s) and 12 edge(s); execution follows the declared edges from the entrypoint to a clean sink. Each node reads its declared input ports and writes exactly its declared output ports.

Two blocking gates with bounded (1-firing) refinement back-edges to `integrate`: `coverage_audit` (requirement coverage) and `plan_verify` (structure + executor-readiness). Pipeline: `read_spec → ingest → decompose → {author_steps ∥ map_dependencies} → integrate → coverage_audit → emit → plan_verify → write_plan`.

## SEED CONTRACT (entrypoint inputs)

Provide these in the run seed / session state:
- `spec_path` (required) — path to the source spec/brief `read_spec` ingests.
- `output_format` (optional) — `markdown` (default) | `json`; set via the `--markdown`/`--json` flag. Absent/empty → `markdown`.
- `out_path` (optional) — destination for the emitted plan. **Resolver-routed default (additive):** when a `--solution-dir`/`--slug` or an upstream handoff is in the seed, the default lands in the shared solution-workspace `02-plan/` subdir (via `solution_workspace.stage_subdir(workspace, 'plan')`), `write_plan` finalizes the workspace through `tools/finalize_workspace.py` (records `stages.plan` in `solution.json`, writes the typed `solution_dir/stage/prev_stage/next_skill` chain fields into `plan_meta`, and — for a `harness-forge` plan — mirrors the `harness_ledger` into the manifest). When **no** workspace is seeded, the default is a file alongside the spec with the format's extension (`.md`/`.json`) and **no** resolver/manifest write happens — byte-identical to today (INV-1). The plan document is **Markdown by default** (human-readable/editable) or, under `--json`, **JSON conforming to `plan.schema.json`** — the typed contract the downstream executor (epiphany-executor) consumes.
- `waived_facets_pairs` (optional; **harness-forge only**) — repeatable `--waiver <facet>=<reason>` pairs. Each audited pair exempts an arrived `harness_ledger` facet from `plan_verify` check 12 (harness-ledger-facet-coverage) so an operator never hand-edits the plan (APU-018). `emit` bakes them into the canonical JSON via `tools/inject_waiver.py` (flips `harness_ledger[facet]` to `status: waived` + `waiver_reason`, adds `waived_facets`, appends `plan_meta.waivers`, and mirrors into the shared manifest via `record_waiver()`); check 12 then honors them through the `waived_facets` / `waiver_reason` path it already reads. An unknown facet is rejected. Absent/empty or `generic` ⇒ the plan is byte-identical (INV-1). Facets: `G W V M B E O K` + the 6 context-pack facets.

## NODE REGISTRY

| node | type | output ports |
|---|---|---|
| `read_spec` | inline | spec_text |
| `ingest` | inline | requirements, constraints, sections |
| `decompose` | inline | step_nodes |
| `author_steps` | inline | authored_steps |
| `map_dependencies` | inline | dependency_map (edges: kind + edge_class; execution_order) |
| `integrate` | inline | integrated_plan |
| `coverage_audit` | inline | coverage_verdict |
| `emit` | inline | plan_document (Markdown default; JSON via --json) |
| `plan_verify` | inline | structural_verdict |
| `write_plan` | inline | written_path |

## OUTPUT CONTRACT

The emitted `plan_document` is **Markdown by default** (sections: Coverage Verdict, Structural Verdict, Execution Notes, Requirement Ledger, Graph roots/leaves, Execution Order, and one `### <step_id>` block per step). Under `--json` it validates against `plan.schema.json` (shipped with the skill). In both formats, dependency edges carry `edge_class` ∈ {`implementation-prerequisite`, `runtime-data`, `ordering`} so an executor can distinguish build-order from data-flow, and every step carries `goal · actions · inputs · outputs · dependencies · integration_checks · refinement_back_edges · acceptance_criteria · traces_requirements` (or `traces_to`). `plan_verify` blocks `write_plan` until the plan is structurally complete, topologically consistent, acyclic (forward graph), correctly rooted/leafed, and free of test-without-implementation coverage — checked against whichever format was emitted.

**Schema validation (v1.1.0+):** `plan.schema.json` has been reconciled to match actual emit output. It now accepts both the published-variant (execution_order + coverage_verdict) and triad-variant (build_order + gate_status) for downstream executor flexibility. Dependencies and integration_checks accept both typed and tolerant formats. Comprehensive test suite (55 tests) validates both JSON and Markdown structure, including the harness/forge integration (target_profile, harness-first ordering), planning back-compat, and the `plan_verify`/`render_markdown` tools (dangling-back-edge + traceability soundness, the BLOCKING requirements→ledger coverage closure, and renderer round-trip fidelity).

## EDGE CASES

- A missing required input is signaled, never invented. (`coverage_verdict`/`structural_verdict` on `integrate` are refinement-supplied and absent on the first pass — intentionally optional.)
- A node that cannot satisfy its contract abstains rather than emitting a placeholder.
- Out-of-envelope / contradictory input → the skill halts with a reason.

## DESIGN NOTES

Authored by forge from a brief. Topology `(derived at runtime)` chosen for the task's structure; the advantage floor for the class is enforced at design time.
