# epiphany-plan

## NAME

`epiphany-plan` — a native graph-of-agentic-thought skill ((derived at runtime)).

## INVOCATION

Run via the harness:
```
goatcs-harness run graph.json                 # Markdown plan (default)
goatcs-harness run graph.json --json          # JSON plan (plan.schema.json)
goatcs-harness run graph.json --markdown      # explicit Markdown (same as default)
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
- `out_path` (optional) — destination for the emitted plan; defaults to a file alongside the spec with the format's extension (`.md` for Markdown, `.json` for JSON). The plan document is **Markdown by default** (human-readable/editable) or, under `--json`, **JSON conforming to `plan.schema.json`** — the typed contract the downstream executor (epiphany-executor) consumes.

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

**Schema validation (v1.1.0+):** `plan.schema.json` has been reconciled to match actual emit output. It now accepts both the published-variant (execution_order + coverage_verdict) and triad-variant (build_order + gate_status) for downstream executor flexibility. Dependencies and integration_checks accept both typed and tolerant formats. Comprehensive test suite (42 tests) validates both JSON and Markdown structure, including the harness/forge integration (target_profile, harness-first ordering) and planning back-compat.

## EDGE CASES

- A missing required input is signaled, never invented. (`coverage_verdict`/`structural_verdict` on `integrate` are refinement-supplied and absent on the first pass — intentionally optional.)
- A node that cannot satisfy its contract abstains rather than emitting a placeholder.
- Out-of-envelope / contradictory input → the skill halts with a reason.

## DESIGN NOTES

Authored by forge from a brief. Topology `(derived at runtime)` chosen for the task's structure; the advantage floor for the class is enforced at design time.
