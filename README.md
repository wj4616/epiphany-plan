# epiphany-plan

> **AI agents: see [`AGENTS.md`](AGENTS.md).** This file is the human reference.

**One-line.** A 10-node harness-native graph that turns a finalized spec/brief into an executable
`plan_document` — a coverage-audited, structurally-verified, dependency-classified step DAG that
[epiphany-executor](#10-integration) runs step by step.

**Version.** Skill `1.1.0` (`graph.json:5`, `manifest.json`). Plan-document schema id
`epiphany-plan.plan_document.v1` (`plan.schema.json` title/`plan_meta.schema`). Graph IR
`epiphany-harness.ir.v1` (`graph.json:2`).

> Dual-audience reference (human + AI agent). Every claim is grounded in a shipped file; see
> [§11 Verification appendix](#11-verification-appendix). The companion machine guide is
> [`AGENTS.md`](AGENTS.md).

---

## 1. What it is

`epiphany-plan` is the **middle stage of the spec → plan → execute pipeline**. It is a *native*
goatcs-harness skill: a declarative `graph.json` (10 nodes, 12 edges) plus one module-body contract
per node under `modules/N-*.md`. The harness runtime walks the declared edges; each node reads its
declared input ports and writes exactly its declared output ports. There is no bespoke Python driver —
`bootstrap.py` only proves the package is harness-loadable (`bootstrap.py:1-26`).

The skill ingests a specification/brief (e.g. the output of `epiphany-spec`, or any detailed brief),
fans every requirement out into atomic step-nodes, classifies the dependency edges between them,
integrates them into one mutually-consistent plan, runs **two blocking gates** (requirement coverage,
then structure + executor-readiness), and emits a single `plan_document` — **Markdown by default**, or
strict **JSON** (`plan.schema.json`) under `--json` — that `write_plan` persists to disk.

It is a *planner*, not an *implementer*: it never writes the code/artifacts the plan describes. It only
produces the plan that `epiphany-executor` (or a human, or any agent) then carries out.

## 2. When to use / not use

**Use it when:**
- You have a finalized spec or a detailed brief and need an executable, step-by-step plan with
  provable requirement coverage and a clean dependency DAG.
- You want a plan an executor can consume mechanically (`--json` → `plan.schema.json`) *or* a human can
  read and hand-edit (Markdown default).
- The work targets the goatcs/epiphany-harness + forge system and you want the harness/forge context
  threaded through to the executor (the `harness-forge` profile — [§10](#10-integration)).

**Do not use it when:**
- You only have a raw idea or rough requirements — run `epiphany-spec` first to produce the spec this
  skill ingests.
- You want the plan *executed* — that is `epiphany-executor`.
- You want prose/brainstorming rather than a structured step DAG.

## 3. How to run it

`epiphany-plan` is a harness graph, not a CLI binary. You drive it through `goatcs-harness`. Two
styles:

### A. One-shot drive (`run`)

```bash
# Markdown plan (default). The seed carries spec_path, output_format, out_path.
echo '{"spec_path": "/abs/path/to/spec-final.md", "output_format": "markdown",
       "out_path": "/abs/path/out/plan.md"}' \
  | goatcs-harness run /home/myuser/.claude/skills/epiphany-plan/graph.json \
      --session /abs/path/sessions/plan-run \
      --read-dir /abs/path/to/spec-dir \
      --out-dir  /abs/path/out

# JSON plan (plan.schema.json): set output_format=json and an out_path ending in .json.
echo '{"spec_path": "/abs/path/to/spec-final.md", "output_format": "json",
       "out_path": "/abs/path/out/plan.json"}' \
  | goatcs-harness run /home/myuser/.claude/skills/epiphany-plan/graph.json \
      --session /abs/path/sessions/plan-run \
      --read-dir /abs/path/to/spec-dir --out-dir /abs/path/out
```

The seed is supplied as a `--seed <file.json>` or piped on stdin (`cli.py:254-255`). Under an
in-session agent provider (the default `inline`), the run auto-advances mechanical nodes and exits 11
(PAUSED-INLINE) at each reasoning node; the agent reasons, `submit --inline`s, and `run --resume`s
(`cli.py:256-263`).

### B. Step-wise drive (`init` → reason → `submit`)

```bash
goatcs-harness init  /home/myuser/.claude/skills/epiphany-plan/graph.json \
    --session /abs/path/sessions/plan-run --seed /abs/path/seed.json
goatcs-harness status   --session /abs/path/sessions/plan-run     # next node + state
goatcs-harness contract <node> --session /abs/path/sessions/plan-run
# reason over the node's module-body contract, then:
goatcs-harness submit  <node> --session /abs/path/sessions/plan-run \
    --outputs /abs/path/node-outputs.json
```

`init` creates the session from the graph (`cli.py:80-84`); `submit` commits a node's declared
outputs and the machine routes to the next node (`cli.py:104-113`). `submit` takes `--session` and
`--outputs` — it does **not** take the sandbox flags (those are `run`-only; see §9).

### The `--markdown` / `--json` flag vs the seed

In skill-level usage (`SKILL.md:9-17`) the format is described as `--markdown` / `--json`. Mechanically
these set the **`output_format` seed signal** (`markdown` | `json`); the native `run`/`init` verbs have
no `--json`/`--markdown` argument — you set `output_format` in the seed JSON. Absent/empty →
`markdown` (`SKILL.md:17,37`; `N-emit.md:32-37`). Both formats are lossless renderings of the same
content contract.

**Need both formats from one run?** Don't hand-author them — that is how a twin drifts. Emit the JSON
as the canonical artifact, then render the Markdown deterministically from it with the shipped renderer,
and verify both (`N-emit.md:40-53,183`):

```bash
python3 tools/render_markdown.py <plan.json> -o <plan.md>   # parity-safe JSON -> Markdown
python3 tools/plan_verify.py <plan.json>                    # both must PASS
python3 tools/plan_verify.py <plan.md>
```

### Seed fields (entrypoint inputs)

| seed field | required | meaning |
|---|---|---|
| `spec_path` | **required** | path the `read_spec` node reads the source spec/brief from (`SKILL.md:36`; `N-read_spec.md`). |
| `output_format` | optional | `markdown` (default) \| `json`; set by the `--markdown`/`--json` flag (`SKILL.md:37`). Absent/empty → `markdown`. |
| `out_path` | optional | destination for the emitted plan; defaults to a file alongside the spec with the format's extension (`.md` / `.json`) (`SKILL.md:38`; `N-write_plan.md:36`). |

### Sandbox flag gotchas (SAF-07)

`--read-dir`, `--out-dir`, `--scratch-dir`, `--allow-network` are **harness `run` flags**, not skill
seed fields (`cli.py:271-282`). They gate the SAF-07 filesystem/network sandbox:
- `read_spec` is an `fs.read_text` tool node — the spec's directory must be inside an allowed root, so
  pass `--read-dir <spec-dir>` (`cli.py:277-279`, `graph.json:40-48`).
- `write_plan` is an `fs.write_text` tool node — its `out_path` must be inside the `--out-dir` root
  (`cli.py:280-282`, `graph.json:404-413`).
- **`--out-dir` must not overlap the session/graph/read roots** or the run refuses before any node
  fires (`cli.py:280-282,534-540`). This is the #1 real-world friction (see §9).

## 4. Concepts & architecture

### The 10 nodes

| node | type / tier | role | output port(s) |
|---|---|---|---|
| `read_spec` | io / no-llm | IO extractor — surface the source spec/brief verbatim. | `spec_text` |
| `ingest` | llm / model-medium | ANALYZER — extract `requirements`, `constraints`, `sections`; detect `target_profile`. | `requirements`, `constraints`, `sections`, `target_profile` |
| `decompose` | llm / model-medium | ANALYZER — fan requirements out into atomic, executable `step_nodes`. | `step_nodes` |
| `author_steps` | llm / model-medium | ANALYZER — author each step at full schema (goal/actions/inputs/outputs/integration-checks/acceptance). | `authored_steps` |
| `map_dependencies` | llm / model-medium | ANALYZER — **sole owner of the dependency graph**; classify each edge `kind` + `edge_class`; emit `execution_order`. | `dependency_map` |
| `integrate` | llm / model-medium | ANALYZER — bind the map's edges onto the steps, install integration checks + refinement back-edges; AND-join. | `integrated_plan` |
| `coverage_audit` | llm / model-medium | **GATE** — does every obligation map to a building (not just testing) step? | `coverage_verdict` |
| `emit` | llm / model-medium | ANALYZER — render the integrated plan to one `plan_document` (Markdown default / JSON). | `plan_document` |
| `plan_verify` | llm / model-medium | **GATE** — structural + executor-readiness checks over the rendered document. | `structural_verdict` |
| `write_plan` | io / no-llm | IO — persist the document byte-for-byte and return `written_path`. | `written_path` |

(`graph.json:8-414`; `SKILL.md:42-53`.)

### The DAG, the fan-out, the AND-join, the two back-edges

```
read_spec → ingest → decompose ─┬─→ author_steps ─────┐
                                └─→ map_dependencies ──┤ (AND-join @ integrate)
                                                       ▼
   ┌──── back-edge E08 (retry_cap 1) ────  coverage_audit ◄── integrate
   │                                            │
integrate ◄─── back-edge E12 (retry_cap 1) ─┐   ├──→ emit → plan_verify ─→ write_plan (sink)
   ▲                                         │                   │
   └─────────────── E12 ─────────────────────┴───────────────────┘
```

Canonical chain (`SKILL.md:31`):
`read_spec → ingest → decompose → {author_steps ∥ map_dependencies} → integrate → coverage_audit → emit → plan_verify → write_plan`.

- **Fan-out (E03/E04).** `decompose` splits to `author_steps` and `map_dependencies` in parallel
  (`split_from: "decompose"`, `graph.json:448,459`).
- **AND-join (E05/E06).** `integrate` fires only after **both** branches arrive
  (`and_join_group: "decompose"`, `join_policy: "AND"`, `aggregation_policy: "concat"`;
  `graph.json:228-229,469,480`).
- **Refinement back-edge E08** — `coverage_audit → integrate`, `kind: back-edge`, `retry_cap: 1`
  (`graph.json:495-504`). Fires on a coverage FAIL; `integrate` repairs the named uncovered/hollow
  obligations and re-emits — once.
- **Refinement back-edge E12** — `plan_verify → integrate`, `kind: back-edge`, `retry_cap: 1`
  (`graph.json:538-548`). Fires on a structural FAIL; `integrate` repairs the named structural
  violations — once.
- **Entrypoint** `read_spec`; **sink** `write_plan` (`graph.json:550-552`).

Each back-edge fires **at most once** (`retry_cap: 1`). On a refinement pass, `integrate` receives the
otherwise-absent `coverage_verdict` / `structural_verdict` inputs (declared `required: false`,
`graph.json:206-215`) as the work list and spends the single pass on exactly those defects
(`N-integrate.md:37`).

### Determinism

`non-deterministic` (`graph.json:6`; `provenance.json` `determinism: non-deterministic`). 8 of 10
nodes are `model-medium` LLM reasoners; only `read_spec` and `write_plan` are `no-llm` IO. The skill is
provider-agnostic — one graph, any supported runtime (`claude-cli`, `codex`, or `inline`);
no per-agent variant is emitted (`SKILL.md:19-25`).

### Directory layout

```
epiphany-plan/
  SKILL.md              # skill card: invocation, node registry, output contract
  graph.json            # the 10-node / 12-edge native IR (the source of truth)
  graph.schema.json     # native-IR schema the graph validates against
  plan.schema.json      # the emitted plan_document contract (executor consumes this)
  bootstrap.py          # harness-loadable shim (build(session_dir, seed))
  install.sh            # copy-install to a dest dir
  manifest.json         # file manifest + version
  provenance.json       # forge provenance (brief/design sha, topology GoT-full)
  coverage_map.json     # per-node verify/fidelity coverage (orphans: [])
  RATIONALE.md          # forge faithfulness note
  modules/              # one N-<node>.md module-body contract per node
    N-read_spec.md  N-ingest.md  N-decompose.md  N-author_steps.md
    N-map_dependencies.md  N-integrate.md  N-coverage_audit.md
    N-emit.md  N-plan_verify.md  N-write_plan.md
  tools/                # shipped helper scripts the reasoning nodes invoke
    plan_verify.py      # the mechanical structural gate plan_verify runs (binding verdict)
    render_markdown.py  # deterministic JSON→Markdown parity renderer (for emitting BOTH formats)
  tests/                # 55 tests (json schema + markdown structure + planning back-compat + plan_verify/render_markdown tools)
```

Worked example plans (real `epiphany-plan` Markdown output) live in
`/home/myuser/projects/epiphany-plan/` — e.g. `forge-v2-build-plan.md`,
`goatcs-v3-build-execution-plan.md`, `gotscs-v1-build-execution-plan.md`.

## 5. The plan_document schema — full field reference

The emitted artifact validates against `plan.schema.json` (when `--json`). Markdown renders the *same*
content contract. Top-level required keys: `plan_meta`, `steps` (`plan.schema.json:6`). The schema is
**tolerant** (`additionalProperties: true`) and accepts two variants: the **published variant**
(`execution_order` + `coverage_verdict`) and the **triad variant** (`build_order` + `gate_status`) for
downstream-executor flexibility (`SKILL.md:59`; tests `minimal_published_variant` /
`minimal_triad_variant`).

### `plan_meta` (`plan.schema.json:9-52`)

| field | type | required | meaning |
|---|---|---|---|
| `plan_id` | string | yes | unique id for this plan |
| `schema` | string | yes | schema version, e.g. `epiphany-plan.plan_document.v1` |
| `source_spec` | string | yes | path/reference to the source spec |
| `title` | string | no | human-readable plan title |
| `dual_mode` | boolean | no | renderable in both Markdown and JSON |
| `consumers` | string[] | no | downstream skill/executor names |
| `generated_by` | string | no | skill version + mode that generated the plan |
| `source_spec_version` | string | no | version of the source spec |
| `baseline` | string | no | prior version/baseline this plan builds on |
| `phasing` | object | no | high-level phase breakdown / milestones |
| `global_invariants` | string[] | no | architectural invariants across all steps |
| `execution_notes` | string[] | no | operator notes (semantics, deps, integration checks) |
| `target_profile` | enum `generic`\|`harness-forge` | no | additive, default `generic` (§10) |
| `harness_forge` | object | no | the forwarded harness/forge context-pack (only when `harness-forge`) |

### Step fields (`plan.schema.json:187-273`)

Per-step required keys: `step_id`, `goal`, `actions`, `acceptance_criteria` (`plan.schema.json:192`).

| field | type | required | meaning |
|---|---|---|---|
| `step_id` | string | yes | unique step id within the plan |
| `phase` | string | no | phase id (A, B, C, …) for phased execution |
| `goal` | string (minLen 1) | yes | the single outcome, in the brief's own language |
| `actions` | string[] (minItems 1) | yes | concrete, ordered, agent-executable operations |
| `inputs` | string[] | no | inputs consumed from prior steps / external sources |
| `outputs` | string[] | no | artifacts produced for downstream steps |
| `dependencies` | array | no | typed edges (objects) **or** bare step-id strings (tolerant) — see below |
| `integration_checks` | array **or** object | no | cross-step assertions over prior outputs (`{id, assert, status}` object form allowed) |
| `refinement_back_edges` | string[] | no | named dependents to re-verify if this step changes |
| `acceptance_criteria` | string[] (minItems 1) | yes | testable gate; executor must not mark done until all pass |
| `traces_to` | string[] | no | requirement ids this step traces to (Markdown output) |
| `traces_requirements` | string[] | no | requirement ids (alias of `traces_to`) |

A typed `dependencies` entry is `{on, kind, edge_class}` (`plan.schema.json:220-231`):
- `on` — the `step_id` this step depends on (required).
- `kind` — `data` | `ordering` | `integration` (required) (`plan.schema.json:224`).
- `edge_class` — see enum below.

### `edge_class` enum (`plan.schema.json:226-227`)

| value | meaning |
|---|---|
| `implementation-prerequisite` | build X before Y (build-order constraint). |
| `runtime-data` | X's *runtime output* feeds Y at execution time — **not** a build-order constraint. |
| `ordering` | Y must follow X; no data passes. |
| `concurrency-prerequisite` | X must complete before a parallel/fan-out region Y may fire. |
| `feedback-input` | X's output feeds a feedback/refinement loop Y. |

The first three are the original/core set; `concurrency-prerequisite` and `feedback-input` are the two
additive (generic, non-domain) values introduced for the harness-forge profile but valid on any plan
(`test_planning_backcompat.py::test_new_generic_edge_classes_validate`). An unknown `edge_class` is
still rejected — the enum is widened, not opened (`test_bogus_edge_class_still_rejected`).

### Envelope fields (top-level, `plan.schema.json:53-186`)

| field | shape | meaning |
|---|---|---|
| `coverage_verdict` | `{decision PASS\|FAIL, blocking, rationale, audit_revision, open_assumptions}` | requirement-coverage gate result (published variant). |
| `structural_verdict` | `{decision PASS\|FAIL, checks[], blocking}` | `plan_verify`'s structural gate result; present once the gate has run. |
| `gate_status` | `{coverage_verdict, structural_verdict}` | aggregated gate status (triad variant). |
| `requirement_ledger` | array of `{obligation, covered_by[≥1]}` | obligation → discharging step ids. |
| `roots` | string[] | true DAG sources (no dependencies). |
| `leaves` | string[] | true DAG sinks (no dependents). |
| `terminal_milestones` | string[] | optional semantic release tail; **not** required to equal `leaves`. |
| `execution_order` | string[] | topological sort over implementation-prerequisite/ordering edges. |
| `build_order` | string[] | alias of `execution_order` (triad variant). |
| `blocking_defects` / `structural_faults` | string[] | plan-level defects/faults that block execution. |
| `out_of_scope` | string[] | explicit non-goals/exclusions. |
| `audit_log` | array of `{id, severity, class, finding, fix}` | audit trail of issues found/resolved. |
| `graph_notes` / `refinement_back_edges` / `requirement_preservation` | (see schema) | narrative + plan-level back-edges + preservation metadata. |

## 6. (Schema continued) — Markdown rendering

Markdown is the **default** because plans are read, reviewed, and hand-edited by humans, and because
full code/command/config examples live inline in fenced blocks without escaping (`N-emit.md:34,90-152`).
The renderer emits literal section headings and bold field labels so the document is reliably
parseable: `## Coverage Verdict`, `## Structural Verdict`, `## Execution Notes`, `## Requirement
Ledger`, `## Graph` (roots/leaves/terminal_milestones), `## Execution Order`, then one `### <step_id>`
block per step carrying `**goal** / **actions** / **inputs** / **outputs** / **dependencies** /
**integration_checks** / **refinement_back_edges** / **acceptance_criteria** / **traces_requirements**`
(`N-emit.md:90-152`). Empty values render as `(none)`, never dropped (`N-emit.md:66`).

## 7. The two gates

Both gates are **blocking** and each owns one refinement back-edge to `integrate` (`retry_cap: 1`).

### `coverage_audit` — requirement coverage (`N-coverage_audit.md`)

Adjudicates whether the integrated plan accounts for **every** requirement, constraint, and section
extracted at `ingest`. Asserts (refuses to PASS if any hold):
- **Orphaned obligation** — any requirement/constraint/section maps to zero steps (`N-coverage_audit.md:39,48`).
- **Hollow mapping** — a step credited with an obligation it doesn't actually discharge (`:41,49`).
- **Test-without-implementation** — an obligation whose only mapped step *checks* it with no step that
  *builds/produces* it (`:40,54`).
- **Granularity loss** — obligations collapsed so coverage only *looks* complete (`:50`).
- **Integration-blind coverage** — a cross-step obligation "covered" by a step with no integration
  check / back-edge anchor (`:42,51`).
- **Fabricated coverage** — a sparse-input gap papered over with invented content (`:43,52`).
- **Ingest-bounded blindness** — a whole *class* of obligation never enumerated at ingest, so its
  absence looked like completeness (`:38,55`).
Coverage requires a per-obligation **utilization citation** — no citation, no credit (`:37,53`). When
in doubt → FAIL (`:57`). On FAIL it names every uncovered/hollow obligation so the `integrate` loop can
act (`:65`). Optional convention: `obligation_class: capability-closure` / `gate-passing` sharpen the
trace (`:67-72`); and when `target_profile == harness-forge` it additionally enforces **harness-first
ordering** — a forge-self step must not run ahead of the primitive it consumes (`:74-83`).

### `plan_verify` — structure + executor-readiness (`N-plan_verify.md`)

Adjudicates the **mechanically-checkable** properties a downstream executor/human must trust without
re-deriving. Checks (BLOCKING unless ADVISORY), run over the actual `plan_document` content:
1. **Completeness / schema conformance** — every step carries all required fields, non-empty or
   explicit `(none)` (Markdown) / validates `plan.schema.json` (JSON) (`N-plan_verify.md:65`).
2. **Dependency-reference integrity** — every `on` and `refinement_back_edges` target names a real
   `step_id`; no dangling references (`:66`).
3. **Topological-order consistency** — `execution_order` is a valid sort of the
   implementation-prerequisite/ordering edges (`:67`).
4. **Acyclicity of the forward graph** — no cycles among forward (non-back-edge) dependencies (`:68`).
5. **Roots / leaves correctness** — `roots` = exactly the no-dependency steps; `leaves` = exactly the
   no-dependent steps (`:69`).
6. **Edge-class declared** — every dependency carries an `edge_class`; runtime-data must not masquerade
   as a build-order dep (`:70`).
7. **Test-without-implementation** — no ledger obligation discharged *only* by a test/audit step (`:71`).
8. **Ledger ↔ step closure** — every `covered_by` resolves to a real step; every obligation appears in
   the ledger (`:72`).
9. **Coverage-verdict honored** (ADVISORY → BLOCKING under disagreement) — if `coverage_audit` FAILed,
   this gate must FAIL too; an optimistic PASS hiding an orphan is the defect (`:73`).
10. **Format integrity** — emitted in the requested `output_format` only; no detail lost (`:74`).
PASS only when 1–8 and 10 hold (and 9 is consistent); else FAIL with every violation enumerated by id,
firing the single back-edge to `integrate` (`:78`). When in doubt → FAIL.

The gate is not purely judgment: it runs a **shipped mechanical checker** and treats its verdict as
binding (`N-plan_verify.md:46-54`):

```bash
python3 tools/plan_verify.py <out_path>               # JSON: schema-validate + checks 1–10; MD: structure + graph checks
python3 tools/plan_verify.py <out_path> --json-report
```

`plan_verify.py` exits `0` = PASS, `1` = FAIL (violations enumerated), `2` = usage/error
(`tools/plan_verify.py:7-9`). The node's `structural_verdict` must agree with it; if the tool FAILs,
the node FAILs and fires E12. Run it on whichever format(s) were emitted (both, when a run produced
both).

## 8. Examples

### 8a. JSON plan (`--json`, validates `plan.schema.json`)

```json
{
  "plan_meta": {
    "plan_id": "test-typed-deps",
    "schema": "epiphany-plan.plan_document.v1",
    "source_spec": "~/test.md",
    "title": "Test Plan with Typed Dependencies"
  },
  "coverage_verdict": { "decision": "PASS", "blocking": true },
  "steps": [
    { "step_id": "S1", "goal": "Setup", "actions": ["Initialize"],
      "acceptance_criteria": ["Ready"], "outputs": ["artifacts"] },
    { "step_id": "S2", "goal": "Build", "actions": ["Compile"],
      "acceptance_criteria": ["Success"],
      "dependencies": [ { "on": "S1", "kind": "data", "edge_class": "runtime-data" } ],
      "traces_requirements": ["REQ-001"] }
  ],
  "execution_order": ["S1", "S2"],
  "requirement_ledger": [ { "obligation": "REQ-001", "covered_by": ["S2"] } ]
}
```

(From `tests/test_json_schema_validation.py` fixture `rich_plan_with_typed_deps` — a validated
example.)

### 8b. Markdown plan excerpt (default)

```markdown
# <Plan Title>

> **plan_id:** P-001 · **schema:** epiphany-plan.plan_document.v1 (markdown) · **source_spec:** ~/spec.md · **dual_mode:** true · **consumers:** inline-executor-skill, agent-reading-directly

## Coverage Verdict
- **decision:** PASS
- **blocking:** true
- **rationale:** every obligation maps to a building step with a utilization citation

## Structural Verdict
- **decision:** PASS
- **checks:** (1–8,10 hold; 9 consistent)

## Requirement Ledger
| obligation | covered_by |
|---|---|
| APU-001 | S-a, S-b |

## Graph
- **roots:** S-a
- **leaves:** S-z
- **terminal_milestones:** (none)

## Execution Order
1. S-a
2. S-b

## Steps

### S-b — compile the module
- **goal:** produce the built module artifact
- **actions:**
  1. run the build
- **inputs:** S-a artifacts
- **outputs:** module.bin
- **dependencies:**
  - `S-a` — kind: data · edge_class: runtime-data
- **integration_checks:**
  - assert S-a's artifacts present + well-formed before build
- **refinement_back_edges:**
  - S-z re-verified if this step changes
- **acceptance_criteria:**
  - build exits 0; module.bin present
- **traces_requirements:** APU-001
```

(Structure per `N-emit.md:90-152`.)

## 9. Failure modes & gotchas

- **`--out-dir` overlap (the #1 friction).** `write_plan`'s `out_path` must sit under `--out-dir`, and
  `--out-dir` must **not** overlap the session dir, the graph dir, or any `--read-dir` root, or the run
  refuses *before any node fires* (`cli.py:534-540`). Keep the output root disjoint from the
  spec/session roots.
- **`read_spec` fails closed without `--read-dir`.** It's an `fs.read_text` tool node; absent a
  read root covering the spec's directory, SAF-07 fail-closes (`cli.py:271-279`; `graph.json:40-48`).
- **Refinement back-edge ≠ failure.** A gate FAIL firing E08/E12 to `integrate` is the **designed**
  repair loop, not a crash. `integrate` repairs the named defects and re-emits once. Treat a back-edge
  firing as normal convergence behavior.
- **One-shot caps.** Each back-edge has `retry_cap: 1` (`graph.json:501,545`). If a gate still FAILs
  after its single refinement pass, the plan is genuinely not ready — the FAIL verdict is the correct,
  useful signal (the skill abstains rather than ship a broken plan; `SKILL.md:62-65`).
- **Markdown is the default.** Emitting JSON when `output_format` is absent/empty is a defined failure
  mode (`N-emit.md:189`). Set `output_format: json` explicitly for the executor path.
- **No edge re-derivation.** `map_dependencies` is the sole owner of the dependency graph; `integrate`
  binds it and `emit` carries it verbatim. Hand-editing edges at render time (or dropping `edge_class`)
  is a rejected failure mode (`N-emit.md:192`; `N-map_dependencies.md:22`).
- **A node that can't satisfy its contract abstains** rather than emitting a placeholder; missing
  inputs are signaled, never invented (`SKILL.md:62-65`).

## 10. Integration

`epiphany-plan` is the **middle stage** of the
`epiphany-spec → epiphany-plan → epiphany-executor` pipeline.

- **Consumes** the upstream spec — typically the `epiphany-spec` output, whose §17 Handoff Bundle may
  carry a `harness_forge_context` pack (`N-ingest.md:45-58`).
- **Emits** `plan_meta` (incl. `schema`, `source_spec`, `consumers`) that `epiphany-executor` reads to
  run the plan step by step. The schema docstring is explicit: "the typed contract for the artifact
  epiphany-plan emits and epiphany-executor consumes … Both planner and executor bind to this one file"
  (`plan.schema.json:4`).

### The harness/forge `target_profile` contract

Per `~/docs/epiphany/harness-forge-pipeline-integration.md`, the pipeline threads ONE optional,
additive, **default-off** capability end-to-end. When the spec/plan/execute task targets the
goatcs/epiphany-harness + forge system:

1. **Detect once at `ingest`** (`N-ingest.md:45-58`). `target_profile ∈ {generic (default),
   harness-forge}`. Set `harness-forge` only on an explicit declaration *or* ≥2 independent signals
   (artifact/vocabulary/command signals — pipeline-integration §1). When uncertain → `generic` and
   abstain (INV-1: never fabricate the profile to unlock behavior). It only *enriches*; it never gates.
2. **Parse the §17 pack.** `ingest` parses the structured `harness_forge_context` block (or a
   `--handoff` seed) and carries the whole pack forward as the value of `target_profile`
   (`N-ingest.md:49-52`).
3. **Auto-activate conventions** (closes the hand-tagging gap, `N-ingest.md:82-90`): tag capability-gap
   requirements `obligation_class: capability-closure`, named-gate requirements `gate-passing`, register
   the pack's `harness_primitives` (each a **harness-first** obligation) and `grammar_cells` (coverage
   obligations); steps may carry a `target_subsystem` tag; acceptance criteria may name a verification
   gate (`gate: <name>`, `N-author_steps.md:59-64`).
4. **Harness-first ordering enforced** at `coverage_audit` when `target_profile == harness-forge`: a
   forge-self step must be sequenced *after* the primitive it consumes via an ordering edge
   (`implementation-prerequisite` or `concurrency-prerequisite`), else coverage FAILs
   (`N-coverage_audit.md:74-83`).
5. **Emit the pack** at `emit`: write `plan_meta.target_profile: harness-forge` and
   `plan_meta.harness_forge: <pack>` (capability_gaps, harness_primitives, grammar_cells,
   correctness_basis, machine_advantage, harness_first, invariants, provider_hint, self_modifying —
   only the keys the pack carries) so `epiphany-executor` consumes it (`N-emit.md:56`). For
   `generic`/absent, write **neither** key — `plan_meta` is byte-identical to the prior default
   (additive, default-off).

**Back-compat is non-negotiable and test-pinned.** A generic plan is byte-identical to the pre-existing
path; detection never gates; an unknown `target_profile`/`edge_class` is rejected
(`tests/test_planning_backcompat.py`, 42-test suite). The contract's implementation is marked DONE +
re-audited CONVERGED (`harness-forge-pipeline-integration.md:138-186`).

### Cross-links

- Upstream: `epiphany-spec` (`/home/myuser/.claude/skills/epiphany-spec/`).
- Downstream: `epiphany-executor` (`/home/myuser/.claude/skills/epiphany-executor/`).
- Pipeline contract: `/home/myuser/docs/epiphany/harness-forge-pipeline-integration.md`.
- Plan-document contract: `plan.schema.json`.

## 11. Verification appendix

Every load-bearing claim → its source.

| claim | source |
|---|---|
| Skill version 1.1.0 | `graph.json:5`; `manifest.json` |
| Plan-document schema id `epiphany-plan.plan_document.v1` | `plan.schema.json` title; `N-emit.md:97` |
| Graph IR `epiphany-harness.ir.v1` | `graph.json:2` |
| 10 nodes, 12 edges | `graph.json:7-415` (nodes), `graph.json:416-549` (edges); `SKILL.md:29` |
| Canonical chain | `SKILL.md:31` |
| Fan-out E03/E04 `split_from: decompose` | `graph.json:448,459` |
| AND-join `join_policy: AND` @ integrate | `graph.json:228-229,469,480` |
| Back-edge E08 coverage_audit→integrate retry_cap 1 | `graph.json:495-504` |
| Back-edge E12 plan_verify→integrate retry_cap 1 | `graph.json:538-548` |
| Entrypoint read_spec / sink write_plan | `graph.json:550-552` |
| read_spec = fs.read_text tool node | `graph.json:40-48` |
| write_plan = fs.write_text tool node | `graph.json:404-413` |
| `run` subcommand + seed via stdin/--seed | `cli.py:250-255` |
| `init`/`submit` subcommands | `cli.py:80-84,104-113` |
| SAF-07 flags `--read-dir/--out-dir/--scratch-dir/--allow-network` are run-only | `cli.py:271-282` |
| `--out-dir` must not overlap session/graph/read roots | `cli.py:280-282,534-540` |
| `output_format` default markdown | `SKILL.md:17,37`; `N-emit.md:32-37` |
| Two blocking gates with bounded refinement | `SKILL.md:31`; `N-coverage_audit.md:27`; `N-plan_verify.md:30` |
| edge_class enum (5 values) | `plan.schema.json:226-227` |
| Step required keys step_id/goal/actions/acceptance_criteria | `plan.schema.json:192` |
| target_profile detect @ ingest | `N-ingest.md:45-58`; `harness-forge-pipeline-integration.md:48` |
| harness-first ordering @ coverage_audit | `N-coverage_audit.md:74-83` |
| plan_meta.target_profile/harness_forge @ emit | `N-emit.md:56`; `plan.schema.json:41-49` |
| Pipeline contract status DONE/CONVERGED | `harness-forge-pipeline-integration.md:138-186` |
| 42-test suite | `tests/` (pytest collected 42) |
| determinism non-deterministic | `graph.json` `determinism_class`; `provenance.json` |
| shipped `tools/plan_verify.py` binding gate | `tools/plan_verify.py:7-9`; `N-plan_verify.md:46-54` |
| shipped `tools/render_markdown.py` parity renderer | `tools/render_markdown.py`; `N-emit.md:40-53` |
| example plans on disk | `/home/myuser/projects/epiphany-plan/*.md` |

### UNVERIFIED / caveats
- **Test count:** `SKILL.md:59` and the live `tests/` suite both report **42** (json schema +
  markdown structure + planning back-compat). Verified via `pytest --collect-only` (42 collected).
- The `--markdown`/`--json` *flags* in `SKILL.md` are skill-level conventions; the native harness
  `run`/`init` verbs expose **no** such argument — format is set via the `output_format` seed signal.
  `SKILL.md` example lines `goatcs-harness run graph.json --json` should be read as "set
  `output_format: json` in the seed", not a literal CLI flag. (Verified against `cli.py` — no `--json`
  on the run/init parsers.)
- **`exec_type: inline` vs harness "inline provider":** every node is `exec_type: inline` (in-context,
  not a spawned subgraph; `graph.json`). This is distinct from the `--provider inline` run mode. The
  README keeps them separate; both labels are accurate in their own scope.
