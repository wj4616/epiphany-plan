# epiphany-plan — AI-agent guide

> **Humans: see [`README.md`](README.md).** This file is the terse machine-facing guide.

Machine-facing operating guide for agents driving this skill. Read alongside [`SKILL.md`](SKILL.md)
(the skill card) and [`README.md`](README.md) (the full human reference). Schema:
[`plan.schema.json`](plan.schema.json). Pipeline contract:
`/home/myuser/docs/epiphany/harness-forge-pipeline-integration.md`.

## 1. TL;DR for agents

`epiphany-plan` is a 10-node native goatcs-harness graph (`graph.json`, IR
`epiphany-harness.ir.v1`, skill v1.1.0). You drive it on the harness. It turns a spec/brief into one
`plan_document` (Markdown default, or JSON validating `plan.schema.json`). Chain:

```
read_spec → ingest → decompose → {author_steps ∥ map_dependencies} → integrate
          → coverage_audit → emit → plan_verify → write_plan
```

Two **blocking** gates (`coverage_audit`, `plan_verify`), each with a **single** (`retry_cap: 1`)
refinement back-edge to `integrate`. The output feeds `epiphany-executor`. Default provider when an
agent drives is `inline`: mechanical nodes auto-advance, reasoning nodes exit 11 (PAUSED-INLINE) for
you to reason, then `submit --inline` + `run --resume`.

## 2. Invocation contract

### Step-wise (recommended for inline reasoning)

```bash
goatcs-harness init  /home/myuser/.claude/skills/epiphany-plan/graph.json \
    --session <SESSION> --seed <SEED.json>
goatcs-harness status   --session <SESSION>          # next node + state
goatcs-harness contract <node> --session <SESSION>   # the node's module-body contract
# reason over the contract, produce the node's declared output ports, then:
goatcs-harness submit  <node> --session <SESSION> --outputs <OUT.json>
```

`init`: `cli.py:80-84`. `submit`: `cli.py:104-113` (`--session` + `--outputs` only; **no** sandbox
flags). `submit` commits the node's outputs and the machine routes to the next node.

### One-shot (`run`)

```bash
echo '{"spec_path":"<ABS spec>","output_format":"markdown","out_path":"<ABS out>/plan.md"}' \
  | goatcs-harness run /home/myuser/.claude/skills/epiphany-plan/graph.json \
      --session <SESSION> --read-dir <ABS spec-dir> --out-dir <ABS out-dir>
```

`run`: `cli.py:250-282`. Seed via `--seed <file>` or stdin (`cli.py:254-255`). SAF-07 sandbox flags
(`--read-dir`/`--out-dir`/`--scratch-dir`/`--allow-network`) are **run-only**.

### Seed (entrypoint inputs)

| field | required | value |
|---|---|---|
| `spec_path` | yes | abs path the `read_spec` node reads (`SKILL.md:36`) |
| `output_format` | no | `markdown` (default) \| `json`; absent/empty → markdown (`SKILL.md:37`) |
| `out_path` | no | abs destination; default = alongside spec with format ext (`SKILL.md:38`) |

`--markdown`/`--json` are **skill-level conventions that set `output_format`** — the native run/init
verbs have no such flag. Set `output_format` in the seed JSON.

### Gate verdicts — what PASS / FAIL / refinement look like

- **PASS at `coverage_audit`** → routes forward to `emit` (E09, `graph.json:505-515`).
- **FAIL at `coverage_audit`** → fires E08 back-edge to `integrate` (`retry_cap: 1`,
  `graph.json:495-504`); `integrate` receives `coverage_verdict` as the work list, repairs the named
  uncovered/hollow obligations, re-emits → re-audited once.
- **PASS at `plan_verify`** → routes to `write_plan` (E11, `graph.json:527-537`) → sink.
- **FAIL at `plan_verify`** → fires E12 back-edge to `integrate` (`retry_cap: 1`,
  `graph.json:538-548`); `integrate` receives `structural_verdict`, repairs the named structural
  violations, re-emits → re-verified once.

A back-edge firing is **convergence, not a crash**. If a gate still FAILs after its single refinement
pass, surface the FAIL — the plan is genuinely not execution-ready (the skill abstains rather than ship
a broken plan; `SKILL.md:62-65`).

## 3. Decision rules

**Markdown vs JSON:**
- Human review / hand-editing / inline code examples → `markdown` (default, `N-emit.md:34`).
- Programmatic `epiphany-executor` consumption → `json` (validates `plan.schema.json`).
- Emitting JSON when `output_format` is absent/empty is a **wrong-default failure** (`N-emit.md:189`) —
  set `json` explicitly.
- **Both formats from one run:** never hand-author the pair. Emit JSON as canonical, then render
  Markdown from it deterministically and verify both (`N-emit.md:40-53,183`):
  ```bash
  python3 tools/render_markdown.py <plan.json> -o <plan.md>   # parity-safe; cannot drift
  python3 tools/plan_verify.py <plan.json> && python3 tools/plan_verify.py <plan.md>
  ```

**`coverage_audit` will FAIL when** (fix in `integrate` on the back-edge):
- any obligation maps to **0** steps → add the implementing step.
- an obligation's only step is a **test/audit** step → add a step that *builds* it (`N-coverage_audit.md:40,54`).
- a mapping is **hollow** (step doesn't actually discharge the obligation) → make actions/acceptance
  materially discharge it, with a utilization citation (`:37,41`).
- a cross-step obligation has **no integration check** anchored to a back-edge → install one (`:42`).
- a whole obligation **class** was never enumerated at ingest → surface it as uncovered (`:38,55`).
- (harness-forge only) a forge-self step could run **ahead of** the primitive it consumes → add an
  ordering edge (`implementation-prerequisite`/`concurrency-prerequisite`) (`:74-83`).

**`plan_verify` will FAIL when** (fix in `integrate`):
- a step is missing a required field, or a `(none)` is dropped (check 1).
- a dependency `on` / `refinement_back_edges` target names a non-existent step (check 2).
- `execution_order` violates an implementation-prerequisite/ordering edge (check 3).
- the forward graph has a cycle in `dependencies` (a refinement link belongs in
  `refinement_back_edges`, not `dependencies`) (check 4).
- `roots`/`leaves` mislabeled vs the actual edge set (check 5).
- a dependency lacks `edge_class`, or runtime-data masquerades as a build-order dep (check 6).
- an obligation is discharged only by a test step (check 7) / a ledger entry dangles (check 8).
- format-split or detail loss (check 10).
(`N-plan_verify.md:65-74`.)

## 4. Operating invariants for agents

When you author/repair at any reasoning node, hold these (they are gate predicates, not style):
- **No orphan coverage** — every requirement/constraint/section → ≥1 *building* step with a utilization
  citation (`N-coverage_audit.md:37,39`).
- **No hollow coverage** — a step credited with an obligation must materially discharge it in its
  actions/acceptance (`:41`).
- **No test-only coverage** — every obligation traces to a step that *produces/implements* it, not only
  one that *checks* it (`:40,54`; `N-plan_verify.md:71`).
- **Acceptance must name a gate where the spec defines one** — acceptance criteria may carry a
  `gate: <name>` prefix (`N-author_steps.md:59-64`); harness-forge capability/gate obligations require
  it (`N-coverage_audit.md:67-72`).
- **No synthesized predicates / no fabrication** — never invent a requirement, step, edge, gap, or
  profile to unlock behavior; mark absences as absences, indeterminate links as `unresolved`, and
  abstain when uncertain (INV-1) (`N-ingest.md:56-57`; `N-decompose.md:43`;
  `N-map_dependencies.md:48`).
- **Single owner of edges** — `map_dependencies` owns the dependency graph; `integrate` binds it; `emit`
  carries it verbatim. Do **not** re-derive or hand-edit edges downstream, and never drop `edge_class`
  (`N-map_dependencies.md:22`; `N-integrate.md:35`; `N-emit.md:192`).
- **Lossless render** — `emit`/`write_plan` carry every field through; `(none)`/`[]` for empty, never
  dropped; fenced code blocks intact, never `...`-elided (`N-emit.md:66,151`; `N-write_plan.md:47`).
- **Roots/leaves computed, not asserted** — from the actual edge set (`N-emit.md:60`;
  `N-plan_verify.md:69`).

## 5. Common agent mistakes

- **Passing sandbox flags to `submit`/`init`.** `--read-dir`/`--out-dir`/`--scratch-dir`/
  `--allow-network` exist **only** on `run` (`cli.py:271-282`). `submit` takes `--session` + `--outputs`.
- **`--out-dir` overlapping the read/session/graph root.** The run refuses before any node fires
  (`cli.py:534-540`). Keep the output root disjoint.
- **Forgetting `--read-dir` for the spec.** `read_spec` is an `fs.read_text` tool node and fail-closes
  under SAF-07 without a read root covering the spec dir (`graph.json:40-48`; `cli.py:277-279`).
- **Treating a refinement back-edge as a failure.** E08/E12 firing is the designed repair loop, not an
  error. Repair the *named* defects in `integrate` and re-emit (once).
- **Emitting JSON by default.** Default is Markdown; emit JSON only when `output_format: json`
  (`N-emit.md:189`).
- **Re-deriving/hand-editing dependency edges at `integrate`/`emit`.** Consume `dependency_map`
  verbatim; record discrepancies, prefer the map (`N-integrate.md:35`; `N-emit.md:192`).
- **`exec_type: inline` ≠ `--provider inline`.** Every node is `exec_type: inline` (in-context, not a
  spawned subgraph); that is unrelated to the `--provider inline` *run mode*. Don't conflate them.

## 6. Machine-readable quick reference

### Nodes + ports (`graph.json`)

| node | type/tier | inputs | outputs |
|---|---|---|---|
| read_spec | io / no-llm | spec_path? | spec_text |
| ingest | llm / medium | spec_text | requirements, constraints, sections, target_profile? |
| decompose | llm / medium | requirements | step_nodes |
| author_steps | llm / medium | step_nodes | authored_steps |
| map_dependencies | llm / medium | step_nodes | dependency_map |
| integrate | llm / medium (AND-join) | authored_steps, dependency_map, coverage_verdict?, structural_verdict? | integrated_plan |
| coverage_audit | llm / medium (GATE) | requirements, integrated_plan | coverage_verdict |
| emit | llm / medium | integrated_plan, coverage_verdict, output_format?, target_profile? | plan_document |
| plan_verify | llm / medium (GATE) | plan_document, integrated_plan, requirements, output_format? | structural_verdict |
| write_plan | io / no-llm | plan_document, out_path?, output_format? | written_path |

`?` = `required: false`. `coverage_verdict`/`structural_verdict` on `integrate` are refinement-supplied
(absent on first pass).

### Edges (`graph.json:416-549`)

| id | src → dst | kind | notes |
|---|---|---|---|
| E01 | read_spec → ingest | required | |
| E02 | ingest → decompose | required | |
| E03 | decompose → author_steps | required | split_from decompose |
| E04 | decompose → map_dependencies | required | split_from decompose |
| E05 | author_steps → integrate | required | and_join_group decompose |
| E06 | map_dependencies → integrate | required | and_join_group decompose |
| E07 | integrate → coverage_audit | required | |
| E08 | coverage_audit → integrate | back-edge | retry_cap 1 |
| E09 | coverage_audit → emit | required | (PASS path) |
| E10 | emit → plan_verify | required | |
| E11 | plan_verify → write_plan | required | (PASS path → sink) |
| E12 | plan_verify → integrate | back-edge | retry_cap 1 |

Entrypoint: `read_spec`. Sink: `write_plan`.

### Schema fields (`plan.schema.json`)

- Top-level required: `plan_meta`, `steps`. `additionalProperties: true` (tolerant).
- `plan_meta` required: `plan_id`, `schema`, `source_spec`. Optional incl.
  `target_profile` (enum `generic|harness-forge`), `harness_forge` (open object), `execution_notes`,
  `consumers`, `phasing`, `global_invariants`.
- Step required: `step_id`, `goal` (minLen 1), `actions` (minItems 1), `acceptance_criteria`
  (minItems 1). Optional: `phase`, `inputs`, `outputs`, `dependencies`, `integration_checks`
  (array **or** `{id,assert,status}` object), `refinement_back_edges`, `traces_to`/`traces_requirements`.
- `dependencies` entry: typed `{on, kind∈data|ordering|integration, edge_class}` **or** bare step-id
  string (tolerant).
- Variants: published (`execution_order` + `coverage_verdict`) **or** triad (`build_order` +
  `gate_status`).

### `edge_class` enum (`plan.schema.json:226-227`)

`implementation-prerequisite` (build X before Y) · `runtime-data` (X runtime-output feeds Y at exec) ·
`ordering` (follow, no data) · `concurrency-prerequisite` (X done before parallel/fan-out region Y) ·
`feedback-input` (X feeds a feedback/refinement loop Y). Unknown values rejected.

### Gate checks

- `coverage_audit`: orphan / hollow / test-without-impl / granularity-loss / integration-blind /
  fabricated / ingest-bounded-blindness; utilization citation required; doubt → FAIL
  (`N-coverage_audit.md`).
- `plan_verify`: (1) completeness/schema (2) dep-ref integrity (3) topo-order (4) acyclicity
  (5) roots/leaves (6) edge-class declared (7) test-without-impl (8) ledger↔step closure
  (9) coverage-verdict honored (10) format integrity; PASS iff 1–8,10 hold & 9 consistent; doubt → FAIL
  (`N-plan_verify.md:65-78`). The gate runs a **shipped mechanical checker** whose verdict is BINDING —
  `structural_verdict` MUST agree with it (`N-plan_verify.md:46-54`):
  ```bash
  python3 tools/plan_verify.py <out_path>               # JSON: schema + checks 1-10; MD: structure + graph
  python3 tools/plan_verify.py <out_path> --json-report # exit 0=PASS, 1=FAIL(+violations), 2=usage
  ```
  Run it on whichever format(s) were emitted; if it FAILs, the node FAILs and fires E12.

## 7. Self-verification checklist (before you let `write_plan` commit)

- [ ] Every requirement/constraint/section → ≥1 *building* step with a citation (no orphan/test-only).
- [ ] Every step has step_id/goal/actions/acceptance_criteria; empties rendered `(none)`/`[]`.
- [ ] Every dependency carries `{on, kind, edge_class}`; `on` targets exist; no dangling back-edge ref.
- [ ] `execution_order` respects every implementation-prerequisite/ordering edge; forward graph acyclic.
- [ ] `roots`/`leaves` computed from the actual edge set.
- [ ] `output_format` honored (one format only, no detail lost, code blocks intact).
- [ ] `coverage_verdict` and `structural_verdict` both PASS (or the FAIL is surfaced, not hidden).
- [ ] If `target_profile == harness-forge`: conventions auto-activated, harness-first ordering present,
      `plan_meta.target_profile` + `plan_meta.harness_forge` written. If `generic`: neither key written.

## 8. Integration for agents

**Detect once at `ingest`** (`N-ingest.md:45-58`): scan `spec_text` for a `harness_forge_context`
fenced-yaml block (typically in a §17 Handoff Bundle) or for the detection signals in
`harness-forge-pipeline-integration.md §1`. Set `target_profile: harness-forge` on an explicit
declaration **or** ≥2 independent signals; else `generic`. When uncertain → `generic` and abstain
(INV-1). Prefer an upstream-declared profile over re-detection.

**Parse the §17 pack**: when declared, adopt it verbatim and carry the whole pack
(`capability_gaps`, `harness_primitives`, `grammar_cells`, `correctness_basis`, `machine_advantage`,
`harness_first`, `invariants`, `provider_hint`, `self_modifying`) as the value of `target_profile`
(`N-ingest.md:49-52`). When synthesized from ≥2 signals, build the pack only from what the spec states.

**Auto-activate conventions** (only under `harness-forge`; closes the hand-tagging gap,
`N-ingest.md:82-90`):
- tag capability-gap requirements `obligation_class: capability-closure`; named-gate requirements
  `gate-passing`.
- register the pack's `harness_primitives` as ordinary **harness-first** obligations (primitive must
  land+tested before the forge step that exploits it) and `grammar_cells` as coverage obligations.
- the forge's `machine_advantage` obligations become `gate-passing`.
- steps may carry `target_subsystem`; acceptance may carry `gate: <name>` (`N-author_steps.md:59-64`).
- Register **only** what the pack/spec states — no invented gaps/primitives/cells (INV-1).

**Harness-first ordering** (`coverage_audit`, `N-coverage_audit.md:74-83`): for each forge-self step
consuming a primitive built by a capability-closure step, **FAIL** coverage unless an ordering
dependency (`implementation-prerequisite` or `concurrency-prerequisite`) sequences the primitive before
the forge step. Generic plans skip this check.

**Emit `plan_meta.harness_forge`** (`emit`, `N-emit.md:56`): write `plan_meta.target_profile:
harness-forge` and `plan_meta.harness_forge: <pack>` (only the keys the pack carries). For
`generic`/absent, write **neither** key — byte-identical to the default. `epiphany-executor`'s
`ingest_plan` reads these into `plan_metadata`; its `census.py` has consumer entries for
`target_subsystem`/`obligation_class` so tagged plans don't trip the INV-2 unconsumed-field BLOCK
(`harness-forge-pipeline-integration.md:109-120`).

**Back-compat (non-negotiable, test-pinned):** generic path byte-identical; detection never gates;
unknown profile/edge_class rejected (`tests/test_planning_backcompat.py`).

## 9. Pointers

- `SKILL.md` — skill card (invocation, node registry, output contract).
- `README.md` — full human reference (schema tables, gates, examples, gotchas).
- `graph.json` — the authoritative 10-node / 12-edge native IR.
- `plan.schema.json` — the emitted plan_document contract (executor binds to this).
- `modules/N-*.md` — per-node module-body contracts.
- `tools/plan_verify.py` — the binding mechanical structural gate (`plan_verify` runs it).
- `tools/render_markdown.py` — deterministic JSON→Markdown parity renderer (for emitting both formats).
- `/home/myuser/docs/epiphany/harness-forge-pipeline-integration.md` — the spec→plan→executor contract.
- Siblings: `/home/myuser/.claude/skills/epiphany-spec/` (upstream),
  `/home/myuser/.claude/skills/epiphany-executor/` (downstream).
