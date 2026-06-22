#!/usr/bin/env python3
"""Mechanical structural gate for epiphany-plan plan_documents (the `plan_verify` node, made
deterministic). Runs the BLOCKING checks 1-10 from modules/N-plan_verify.md over the ACTUAL emitted
artifact — JSON (schema-validated + graph checks) or Markdown (structure + graph checks) — instead of
the authoring agent eyeballing its own output.

    python3 tools/plan_verify.py <plan.json|plan.md> [--schema plan.schema.json] [--json-report]

Exit 0 = PASS (every blocking check holds). Exit 1 = FAIL (violations enumerated). Exit 2 = usage/error.

Build-order edge classes (constrain execution_order + acyclicity):
    implementation-prerequisite, ordering, concurrency-prerequisite
Non-build-order edge classes (do NOT constrain build order, NOT counted for acyclicity):
    runtime-data, feedback-input.
A genuine refinement link lives in `refinement_back_edges`, never in `dependencies`.

Soundness notes (hardened after adversarial audit):
- JSON is the canonical artifact; the Markdown path is parsed defensively and FAILs LOUD on any
  structure it cannot parse (missing `## Steps`, a step whose `**dependencies:**` value is non-empty
  but unparseable), rather than silently dropping content.
- `jsonschema` is optional: when absent, check 10 is SKIPPED (advisory), never a FALSE FAIL.
- check 7 (test-without-implementation) is a HEURISTIC and is ADVISORY-only (never blocks); it can
  produce false +/- on plausible prose and must not be trusted as a gate.
"""
from __future__ import annotations
import argparse, json, os, re, sys

try:
    import jsonschema as _jsonschema
except Exception:  # noqa
    _jsonschema = None

BUILD_ORDER_CLASSES = {"implementation-prerequisite", "ordering", "concurrency-prerequisite"}
VALID_EDGE_CLASSES = BUILD_ORDER_CLASSES | {"runtime-data", "feedback-input"}
VALID_KINDS = {"data", "ordering", "integration"}
STEP_REQUIRED = ["step_id", "goal", "actions", "inputs", "outputs", "dependencies",
                 "integration_checks", "refinement_back_edges", "acceptance_criteria"]
# id-token shape used to spot dangling references inside prose back-edges. Covers T12, S-1, A.1,
# S-a? (no digit -> not matched; reported as non-referential/advisory), T12b, phase-2, step_3.
ID_TOKEN = re.compile(r"\b[A-Za-z][A-Za-z]*[-_.]?\d{1,4}[a-z]?\b")
TEST_ONLY_RE = re.compile(r"\b(test|verify|verif|audit|checks?|validate|assert|ensure that)\b", re.I)
IMPL_RE = re.compile(r"\b(implement|build|creat|add|author|refactor|extend|wire|emit|"
                     r"produce|generat|render|install|port|fork|migrat|scaffold|"
                     r"replace|promote|de-commit|swap|register|hash|chain)\b", re.I)


def _nonempty(v):
    if v is None:
        return False
    if isinstance(v, str):
        return bool(v.strip())
    if isinstance(v, (list, dict)):
        return len(v) > 0
    return True


# ----------------------------------------------------------------------------- JSON parsing
def _dep_pairs(step):
    """Yield (target_step_id, edge_class) per dependency (typed dict or bare string). Defensive:
    a non-list `dependencies`, or a dep that is neither str nor dict, is reported by the caller."""
    deps = step.get("dependencies", [])
    if not isinstance(deps, list):
        return  # caller flags via _type_faults
    for d in deps:
        if isinstance(d, dict):
            yield d.get("on"), d.get("edge_class")
        elif isinstance(d, str):
            yield d, None
        # other types -> ignored here, flagged in _type_faults


def _type_faults(steps, doc):
    faults = []
    for s in steps:
        sid = s.get("step_id", "?")
        if "dependencies" in s and not isinstance(s["dependencies"], list):
            faults.append(f"{sid}.dependencies is {type(s['dependencies']).__name__}, expected array")
        else:
            for d in s.get("dependencies", []) or []:
                if not isinstance(d, (str, dict)):
                    faults.append(f"{sid}.dependencies has a {type(d).__name__} entry")
    for row in doc.get("requirement_ledger", []) or []:
        if isinstance(row, dict) and "covered_by" in row and not isinstance(row["covered_by"], list):
            faults.append(f"ledger '{str(row.get('obligation'))[:30]}'.covered_by is not an array")
    for k in ("execution_order", "build_order", "roots", "leaves"):
        if k in doc and not isinstance(doc[k], list):
            faults.append(f"{k} is {type(doc[k]).__name__}, expected array")
    return faults


def load_json_plan(doc):
    steps = [s for s in doc.get("steps", []) if isinstance(s, dict)]
    ids = [s.get("step_id") for s in steps]
    order = doc.get("execution_order") or doc.get("build_order") or []
    order = [x for x in order if isinstance(x, str)]  # tolerate prose build_order layers
    ledger = []
    for row in doc.get("requirement_ledger", []) or []:
        if isinstance(row, dict):
            cov = row.get("covered_by", [])
            cov = [c for c in cov if isinstance(c, str)] if isinstance(cov, list) else []
            ledger.append((str(row.get("obligation", "?")), cov))
    rp = doc.get("requirement_preservation")
    req_obl = rp.get("input_obligations") if isinstance(rp, dict) else None
    req_obl = [str(o) for o in req_obl] if isinstance(req_obl, list) else None
    return {
        "steps": steps, "ids": ids,
        "deps": {s.get("step_id"): list(_dep_pairs(s)) for s in steps},
        "back_edges": {s.get("step_id"): [b for b in (s.get("refinement_back_edges", []) or []) if isinstance(b, str)] for s in steps},
        "order": order,
        "roots": doc.get("roots") if isinstance(doc.get("roots"), list) else None,
        "leaves": doc.get("leaves") if isinstance(doc.get("leaves"), list) else None,
        "ledger": ledger,
        "coverage_pass": str((doc.get("coverage_verdict") or {}).get("decision", "")).upper() != "FAIL",
        "raw_steps": {s.get("step_id"): s for s in steps},
        "unparseable_deps": [],
        "type_faults": _type_faults(steps, doc),
        "no_steps_section": False,
        "req_obligations": req_obl,
        "target_profile": (doc.get("plan_meta") or {}).get("target_profile") if isinstance(doc.get("plan_meta"), dict) else None,
    }


# ----------------------------------------------------------------------------- Markdown parsing
STEP_HDR = re.compile(r"^###\s+([A-Za-z0-9._-]+)\b", re.M)
FENCE = re.compile(r"```.*?```", re.S)
FIELD_LABELS = ["goal", "actions", "inputs", "outputs", "dependencies",
                "integration_checks", "refinement_back_edges", "acceptance_criteria"]
DEP_LINE = re.compile(r"`([A-Za-z0-9._-]+)`\s*[—–-].*?edge_class:\s*([A-Za-z(][A-Za-z) -]*)", re.I)


def _label_section(block, label):
    """Return the text under **label:** up to the next bold field label (or end)."""
    m = re.search(r"\*\*\s*" + label + r"\s*:?\s*\*\*", block, re.I)
    if not m:
        return None
    rest = block[m.end():]
    nxt = re.search(r"\n-?\s*\*\*\s*[a-z_]+\s*:?\s*\*\*", rest, re.I)
    return rest[:nxt.start()] if nxt else rest


def load_md_plan(text):
    no_steps = False
    sm = re.search(r"\n##\s+Steps\s*\n", text)
    if not sm:
        # required anchor absent -> do not whole-doc-scan (phantom steps); FAIL loud.
        return {"steps": [], "ids": [], "deps": {}, "back_edges": {}, "order": [],
                "roots": None, "leaves": None, "ledger": [], "coverage_pass": True,
                "raw_blocks": {}, "unparseable_deps": [], "type_faults": [], "no_steps_section": True,
                "req_obligations": None, "target_profile": None}
    tail = text[sm.end():]
    endm = re.search(r"\n##\s+", tail)          # end ONLY at the next top-level section (NOT at ---)
    steps_region = tail[:endm.start()] if endm else tail
    fenced = FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), steps_region)  # blank out code fences

    hdrs = list(STEP_HDR.finditer(fenced))
    steps, deps, back_edges, raw_blocks, unparseable = [], {}, {}, {}, []
    for i, m in enumerate(hdrs):
        sid = m.group(1)
        start = m.end()
        end = hdrs[i + 1].start() if i + 1 < len(hdrs) else len(fenced)
        block = fenced[start:end]
        steps.append(sid)
        raw_blocks[sid] = block
        dsec = _label_section(block, "dependencies")
        dpairs = []
        if dsec is not None:
            for dl in DEP_LINE.finditer(dsec):
                dpairs.append((dl.group(1), dl.group(2).strip().lower()))
            # non-empty deps that we could not parse -> LOUD fault, never a silent drop
            if not dpairs and "(none)" not in dsec.lower() and re.search(r"`[A-Za-z0-9._-]+`", dsec):
                unparseable.append(sid)
        deps[sid] = dpairs
        besec = _label_section(block, "refinement_back_edges") or ""
        back_edges[sid] = [ln.strip(" -`") for ln in besec.splitlines() if ln.strip(" -`")]
    order = []
    mo = re.search(r"##\s*Execution Order\s*(.+?)(?:\n##\s|\Z)", text, re.S | re.I)
    if mo:
        order = re.findall(r"\d+\.\s*([A-Za-z0-9._-]+)", mo.group(1))

    def _grab(label):
        m = re.search(r"\*\*" + label + r":\*\*\s*([^\n]+)", text, re.I)
        if not m:
            return None
        toks = [t.strip(" `") for t in re.split(r"[,\s]+", m.group(1)) if t.strip(" `")]
        return [t for t in toks if re.fullmatch(r"[A-Za-z0-9._-]+", t) and t.lower() != "(none)"]
    roots, leaves = _grab("roots"), _grab("leaves")

    ledger = []
    lm = re.search(r"##\s*Requirement Ledger\s*(.+?)(?:\n##\s|\Z)", text, re.S | re.I)
    if lm:
        for row in lm.group(1).splitlines():
            row = row.strip()
            if not row.startswith("|") or "---" in row or "covered_by" in row.lower():
                continue
            cells = [c.strip() for c in re.split(r"(?<!\\)\|", row.strip("|"))]  # respect \| escapes
            if len(cells) >= 2:
                cov = [c for c in re.findall(r"[A-Za-z0-9._-]+", cells[1]) if c.lower() != "none"]
                ledger.append((cells[0].replace("\\|", "|"), cov))
    cov_fail = bool(re.search(r"\*\*?\s*decision\s*\*?\*?\s*:?\s*\**\s*FAIL", text, re.I))
    return {
        "steps": steps, "ids": steps, "deps": deps, "back_edges": back_edges, "order": order,
        "roots": roots, "leaves": leaves, "ledger": ledger, "coverage_pass": not cov_fail,
        "raw_blocks": raw_blocks, "unparseable_deps": unparseable, "type_faults": [],
        "no_steps_section": no_steps, "req_obligations": None, "target_profile": None,
    }


# ----------------------------------------------------------------------------- checks
def run_checks(P, fmt, schema=None, doc=None):
    V = []
    R = []
    ids = set(P["ids"])

    def chk(cid, name, ok, detail="", advisory=False):
        if advisory:
            R.append((cid, name, "PASS" if ok else "ADVISORY"))
            return
        R.append((cid, name, "PASS" if ok else "FAIL"))
        if not ok:
            V.append(f"[{cid} {name}] {detail}")

    if P.get("no_steps_section"):
        chk("0", "markdown-structure", False, "no `## Steps` section found — cannot locate step blocks")
        return R, V

    # 10 schema / format integrity
    if fmt == "json":
        if _jsonschema is None:
            R.append(("10", "schema-validate", "SKIP(jsonschema unavailable)"))
        elif schema is not None:
            try:
                _jsonschema.validate(doc, schema)
                chk("10", "schema/format-integrity", True)
            except Exception as e:  # noqa
                chk("10", "schema/format-integrity", False, f"schema invalid: {str(e)[:200]}")
        else:
            R.append(("10", "schema-validate", "SKIP(no schema file)"))
        for tf in P["type_faults"]:
            chk("10t", "type-integrity", False, tf)
    else:
        chk("10", "format-integrity", bool(P["steps"]), "no step blocks parsed")

    # 1 completeness
    if fmt == "json":
        miss = []
        for s in P["steps"]:
            for f in STEP_REQUIRED:
                v = s.get(f)
                if f in ("step_id", "goal", "actions", "acceptance_criteria") and not _nonempty(v):
                    miss.append(f"{s.get('step_id','?')}:{f}")
                elif v is None:
                    miss.append(f"{s.get('step_id','?')}:{f}")
            # traceability is mandated by N-emit.md + the spec OUTPUT CONTRACT (every step carries
            # traces_requirements / traces_to). The schema stays tolerant; the gate enforces it here.
            if not (_nonempty(s.get("traces_requirements")) or _nonempty(s.get("traces_to"))):
                miss.append(f"{s.get('step_id','?')}:traces_requirements")
        chk("1", "completeness", not miss, "missing/empty: " + ", ".join(miss[:12]))
    else:
        miss = []
        for sid, block in P["raw_blocks"].items():
            for lbl in FIELD_LABELS:
                if not re.search(r"\*\*\s*" + lbl + r"\s*:?\s*\*\*", block, re.I):
                    miss.append(f"{sid}:{lbl}")
            # actions + acceptance must have a real item (not empty / not (none))
            for lbl in ("actions", "acceptance_criteria"):
                sec = _label_section(block, lbl) or ""
                items = [ln for ln in sec.splitlines() if re.match(r"\s*(\d+\.|[-*])\s+\S", ln)]
                real = [ln for ln in items if "(none)" not in ln.lower() and "(missing" not in ln.lower()]
                if not real:
                    miss.append(f"{sid}:{lbl}(empty)")
            # traceability (either label) must be present and non-(none) — mandated by N-emit.md.
            trsec = _label_section(block, "traces_requirements")
            if trsec is None:
                trsec = _label_section(block, "traces_to")
            trval = (trsec or "").strip()
            if not trval or trval.lower().startswith("(none)"):
                miss.append(f"{sid}:traces_requirements(empty)")
        chk("1", "completeness", not miss, "missing/empty: " + ", ".join(miss[:12]))

    # 2 dependency-reference integrity (HARD)
    bad = [f"{sid}->{on}" for sid, dl in P["deps"].items() for on, _ in dl if on not in ids]
    for sid in P.get("unparseable_deps", []):
        bad.append(f"{sid}:unparseable `dependencies` block (non-empty but no edge parsed)")
    chk("2", "dep-reference-integrity", not bad, "; ".join(bad[:12]))

    # 2b back-edge references. refinement_back_edges are PROSE that should NAME the dependents to
    # re-verify. Free prose legitimately mentions non-id tokens (milestone labels "M1b"/"M3",
    # "task-27"), so we only flag a token as DANGLING when it shares the *signature* of the plan's
    # real step ids (digit-runs normalised) yet resolves to no real id — e.g. ids {T00..T12} have
    # signature `T#`, so `T77` is dangling but `M1b`/`M3`/`task-27` are not. An entry that names NO
    # real step id at all is reported ADVISORY (possibly-decorative), never a hard fail.
    def _sig(tok):
        return re.sub(r"\d+", "#", tok)
    id_sigs = {_sig(i) for i in ids if isinstance(i, str)}
    be_bad, be_decor = [], []
    for sid, be in P["back_edges"].items():
        for entry in be:
            if not isinstance(entry, str):
                continue
            e = entry.strip()
            if e.lower() in ("", "(none)", "none"):
                continue
            # 1) exact whole-entry id reference — the JSON case and renderer-MD case, where
            #    refinement_back_edges entries are exact step_ids. (Was missed before: the
            #    token-scan split `S-M0-2` into `M0`, so neither a valid ref nor a dangling
            #    `S-M0-99` matched — defeating this BLOCKING check for hyphenated id schemes.)
            if e in ids:
                continue
            # 2) whole entry has the signature of a real step id but resolves to none -> DANGLING
            #    (e.g. ids look like `S-M#-#` and the entry is `S-M0-99`).
            if _sig(e) in id_sigs:
                be_bad.append(f"{sid} back-edge ->{e}")
                continue
            # 3) prose fallback: scan id-like tokens embedded in free text.
            toks = set(ID_TOKEN.findall(e))
            present = [t for t in toks if t in ids]
            dangling = [t for t in toks if t not in ids and _sig(t) in id_sigs]
            if dangling:
                be_bad.append(f"{sid} back-edge ->{','.join(sorted(set(dangling)))}")
            elif not present:
                be_decor.append(sid)
    chk("2b", "back-edge-references", not be_bad, "dangling back-edge ids: " + "; ".join(be_bad[:12]))
    if be_decor:
        R.append(("2b*", "back-edge-non-referential(advisory)", "ADVISORY"))

    # 3 topological-order consistency (build-order edges only)
    order = P["order"]
    if order:
        pos = {s: i for i, s in enumerate(order)}
        viol = []
        for sid, dl in P["deps"].items():
            for on, ec in dl:
                build = (ec in BUILD_ORDER_CLASSES) or (fmt == "json" and ec is None)
                if build and on in pos and sid in pos and pos[on] >= pos[sid]:
                    viol.append(f"({sid} after-or-equal prereq {on})")
        miss = [s for s in P["ids"] if s not in pos]
        # coerce to str: a step missing `step_id` (non-canonical dialect) yields a None id here;
        # it is a real FAIL (check 1 also flags it), and must not crash the join.
        chk("3", "topo-order-consistency", not viol and not miss,
            ("order: " + ", ".join(viol[:8])) + ("; not in order: " + ", ".join(str(s) for s in miss[:8]) if miss else ""))
    else:
        chk("3", "topo-order-consistency", False, "no execution_order/build_order found")

    # 4 acyclicity of the BUILD-ORDER forward graph (exclude runtime-data/feedback-input)
    adj = {s: [] for s in P["ids"]}
    for sid, dl in P["deps"].items():
        for on, ec in dl:
            build = (ec in BUILD_ORDER_CLASSES) or (fmt == "json" and ec is None)
            if build and on in adj:
                adj[on].append(sid)
    color, cyc = {s: 0 for s in P["ids"]}, []
    sys.setrecursionlimit(max(1000, len(P["ids"]) * 10 + 100))  # guard for large plans (cap ~1000 steps)

    def dfs(u, stack):
        color[u] = 1
        for v in adj[u]:
            if color[v] == 1:
                cyc.append(" -> ".join(stack + [u, v]))
            elif color[v] == 0:
                dfs(v, stack + [u])
        color[u] = 2
    for s in P["ids"]:
        if color[s] == 0:
            dfs(s, [])
    chk("4", "acyclicity(build-order)", not cyc, "cycles: " + "; ".join(cyc[:5]))

    # 5 roots/leaves correctness (literal: a step with ANY dependency is not a root;
    #   a step that ANY step depends on - any edge kind - is not a leaf).
    has_dep = {s for s, dl in P["deps"].items() if dl}
    depended_on = {on for dl in P["deps"].values() for on, _ in dl}
    comp_roots = sorted(s for s in P["ids"] if s not in has_dep)
    comp_leaves = sorted(s for s in P["ids"] if s not in depended_on)
    if P["roots"] is not None:
        chk("5a", "roots-correct", sorted(P["roots"]) == comp_roots,
            f"declared {sorted(P['roots'])} != computed {comp_roots}")
    else:
        chk("5a", "roots-present", False, "no roots declared")
    if P["leaves"] is not None:
        chk("5b", "leaves-correct", sorted(P["leaves"]) == comp_leaves,
            f"declared {sorted(P['leaves'])} != computed {comp_leaves}")
    else:
        chk("5b", "leaves-present", False, "no leaves declared")

    # 6 edge-class declared (typed deps must carry a VALID edge_class)
    bad_ec = []
    if fmt == "json":
        for s in P["steps"]:
            for d in s.get("dependencies", []) or []:
                if isinstance(d, dict):
                    ec = d.get("edge_class")
                    if ec is None:
                        bad_ec.append(f"{s.get('step_id')}->{d.get('on')} (missing edge_class)")
                    elif ec not in VALID_EDGE_CLASSES:
                        bad_ec.append(f"{s.get('step_id')}->{d.get('on')} edge_class={ec}")
    else:
        for sid, dl in P["deps"].items():
            for on, ec in dl:
                if ec not in VALID_EDGE_CLASSES:
                    bad_ec.append(f"{sid}->{on} edge_class={ec or '(missing)'}")
    chk("6", "edge-class-declared", not bad_ec, "; ".join(bad_ec[:12]))

    # 8 ledger<->step closure (covered_by must resolve to real steps; non-empty)
    bad_led = []
    for ob, cov in P["ledger"]:
        if not cov:
            bad_led.append(f"'{ob[:40]}' covered_by empty/unresolved")
        for c in cov:
            if c not in ids:
                bad_led.append(f"'{ob[:30]}'->{c} (not a step)")
    chk("8", "ledger-step-closure", not bad_led, "; ".join(bad_led[:12]))

    # 8c requirements -> ledger closure. BLOCKING when the obligation set is available (emit populates
    # plan_meta-adjacent `requirement_preservation.input_obligations`, or pass --requirements). This
    # gives coverage a mechanical backstop equal to the structural checks instead of trusting the
    # authoring LLM's self-certified coverage_verdict.
    req_obl = P.get("req_obligations")
    if req_obl:
        ledger_obls = {ob for ob, _ in P["ledger"]}
        uncovered = [o for o in req_obl if o not in ledger_obls]
        chk("8c", "requirements-ledger-closure", not uncovered,
            "obligations absent from the requirement ledger: " + ", ".join(uncovered[:12]))
    else:
        R.append(("8c", "requirements-ledger-closure NOT verified "
                  "(no requirement_preservation.input_obligations / --requirements)", "ADVISORY"))

    # harness-forge: the coverage_audit harness-first ordering check needs per-step obligation_class /
    # target_subsystem tags (N-emit.md). Surface (advisory) whether they were carried so an inert
    # harness-first check is visible rather than silently skipped.
    if P.get("target_profile") == "harness-forge":
        tagged = any((s.get("obligation_class") or s.get("target_subsystem")) for s in P.get("steps", []))
        R.append(("hf", "harness-forge tags " + ("PRESENT (harness-first mechanically traceable)"
                  if tagged else "ABSENT (harness-first NOT mechanically checkable — assert in prose)"),
                  "ADVISORY"))

    # 7 test-without-implementation — HEURISTIC, ADVISORY ONLY (never blocks; runs both formats)
    tw = []
    for ob, cov in P["ledger"]:
        texts = []
        for c in cov:
            if fmt == "json" and c in P["raw_steps"]:
                s = P["raw_steps"][c]
                texts.append(" ".join([str(s.get("goal", ""))] + [str(a) for a in s.get("actions", []) or []]))
            elif fmt == "md" and c in P.get("raw_blocks", {}):
                texts.append(P["raw_blocks"][c])
        if texts and all(TEST_ONLY_RE.search(t) and not IMPL_RE.search(t) for t in texts):
            tw.append(f"'{ob[:40]}' covered only by apparent test/verify step(s) {cov}")
    chk("7", "test-without-implementation(heuristic)", not tw, "; ".join(tw[:8]), advisory=True)

    # 9 coverage honored
    chk("9", "coverage-verdict-honored", P["coverage_pass"],
        "coverage_verdict.decision=FAIL but plan emitted as ready")

    # 11 wiring-contract bijection (additive; BLOCKING only when a wiring_contract is present).
    # The integration DoD carried from the spec (wiring-check Phase 2 §5): every contract row maps
    # to a capability step, and every SKILL capability-closure step maps to a row. Absent contract
    # => N/A (back-compat: ordinary plans are byte-identical). Harness primitives (target_subsystem
    # == harness) are EXEMPT from the reverse direction (gotcha #4: they are wired by construction).
    wc = (doc or {}).get("wiring_contract") if fmt == "json" else None
    if wc:
        row_ids = [r.get("id") for r in wc if isinstance(r, dict) and r.get("id")]

        def _refs(step):
            toks = set()
            for k in ("traces_requirements", "traces_to", "wiring_row", "wiring_rows", "wiring_contract_id"):
                v = step.get(k)
                if isinstance(v, str):
                    toks.add(v)
                elif isinstance(v, list):
                    toks |= {str(x) for x in v}
            return toks

        steps = P.get("steps", [])
        referenced = set()
        for s in steps:
            referenced |= _refs(s)
        uncovered_rows = [rid for rid in row_ids if rid not in referenced]
        chk("11", "wiring-bijection(row->step)", not uncovered_rows,
            "wiring_contract rows referenced by no step (a declared capability with no plan step): "
            + ", ".join(uncovered_rows[:12]))

        rowset = set(row_ids)
        unbound = []
        for s in steps:
            if (str(s.get("obligation_class", "")) == "capability-closure"
                    and str(s.get("target_subsystem", "")).lower() == "skill"):
                if not (_refs(s) & rowset):
                    unbound.append(s.get("step_id", "?"))
        chk("11b", "wiring-bijection(skill-step->row)", not unbound,
            "skill capability-closure steps with no wiring_contract row: " + ", ".join(unbound[:12]))

    # 12 harness-ledger facet coverage (S7 / WC-9 / APU-011). BLOCKING, harness-forge only.
    # Every harness_ledger facet that is not waived must be covered by >=1 build step. A facet is
    # "covered" when a step names it via covers_facets / facets, OR (fallback) any step's prose
    # explicitly mentions the facet. Waived facets (status==waived or in a `waived_facets` set) are
    # exempt — the waiver is the audited reason it has no covering step (INV-6). Absent a
    # harness_ledger this check is N/A, so generic and non-harness plans are byte-identical (INV-1).
    if fmt == "json":
        ledger, waived = _harness_ledger(doc, P)
        if ledger:
            covered = _facets_covered_by_steps(P["steps"], P.get("raw_steps", {}))
            uncovered = [f for f, status in ledger.items()
                         if status != "waived" and f not in waived and f not in covered]
            chk("12", "harness-ledger-facet-coverage", not uncovered,
                "harness facets with no covering build step (add a step or --waiver): "
                + ", ".join(sorted(uncovered)[:14]))
            if waived:
                R.append(("12w", "waived facets (audited, exempt from coverage): "
                          + ", ".join(sorted(waived)), "ADVISORY"))

    return R, V


def _harness_ledger(doc, P):
    """Extract (facet->status, waived_set) from a plan doc, harness-forge only.

    The ledger may live at top-level `harness_ledger`, or under
    `plan_meta.harness_forge.harness_ledger`. Each value is either a status
    string or a record dict with a `status`/`waiver_reason`. Returns ({}, set())
    for generic plans so check 12 is a no-op (INV-1)."""
    if P.get("target_profile") != "harness-forge":
        return {}, set()
    raw = doc.get("harness_ledger")
    if raw is None:
        hf = (doc.get("plan_meta") or {}).get("harness_forge") or {}
        raw = hf.get("harness_ledger")
    if not isinstance(raw, dict):
        return {}, set()
    ledger, waived = {}, set()
    for facet, rec in raw.items():
        if isinstance(rec, dict):
            status = str(rec.get("status", "")).lower()
            if rec.get("waiver_reason") or status == "waived":
                waived.add(facet)
            ledger[facet] = status or "missing"
        else:
            ledger[facet] = str(rec).lower()
            if str(rec).lower() == "waived":
                waived.add(facet)
    # explicit waived list, if the planner chose to carry one
    for f in (doc.get("waived_facets") or []):
        if isinstance(f, str):
            waived.add(f)
    return ledger, waived


def _facets_covered_by_steps(steps, raw_steps):
    """The set of harness facets covered by >=1 step. A step covers a facet via an
    explicit `covers_facets`/`facets` list, or by naming the facet token in its
    goal/actions prose (e.g. 'facet:G' or 'Graph Architecture (G)')."""
    covered = set()
    for s in steps:
        for key in ("covers_facets", "facets"):
            v = s.get(key)
            if isinstance(v, str):
                covered.add(v)
            elif isinstance(v, list):
                covered |= {str(x) for x in v}
        prose = " ".join([str(s.get("goal", ""))]
                         + [str(a) for a in (s.get("actions") or [])])
        for tok in re.findall(r"facet[:=]\s*([A-Za-z_]+)", prose):
            covered.add(tok)
    return covered


# ----------------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description="Mechanical structural gate for epiphany-plan plans.")
    ap.add_argument("plan")
    ap.add_argument("--schema", default=None)
    ap.add_argument("--requirements", default=None,
                    help="path to a JSON array of obligation ids (or a coverage doc with "
                         "requirement_preservation.input_obligations) — enables the BLOCKING "
                         "requirements->ledger closure check (8c) for plans that don't embed it.")
    ap.add_argument("--json-report", action="store_true")
    a = ap.parse_args(argv)

    if not os.path.exists(a.plan):
        print(f"error: no such file: {a.plan}", file=sys.stderr)
        return 2
    text = open(a.plan, encoding="utf-8").read()
    fmt = "json" if a.plan.endswith(".json") or text.lstrip().startswith("{") else "md"

    schema, doc = None, None
    if fmt == "json":
        try:
            doc = json.loads(text)
        except Exception as e:  # noqa
            print(f"FAIL [10 format-integrity] JSON does not parse: {e}", file=sys.stderr)
            return 1
        P = load_json_plan(doc)
        spath = a.schema or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plan.schema.json")
        if os.path.exists(spath):
            schema = json.load(open(spath))
    else:
        P = load_md_plan(text)

    if a.requirements and os.path.exists(a.requirements):
        try:
            rq = json.load(open(a.requirements, encoding="utf-8"))
            if isinstance(rq, dict):
                rq = (rq.get("requirement_preservation") or {}).get("input_obligations") or rq.get("input_obligations")
            if isinstance(rq, list):
                P["req_obligations"] = [str(o) for o in rq]
        except Exception as e:  # noqa
            print(f"warning: could not read --requirements {a.requirements}: {e}", file=sys.stderr)

    results, violations = run_checks(P, fmt, schema=schema, doc=doc)
    passed = not violations

    if a.json_report:
        print(json.dumps({"format": fmt, "verdict": "PASS" if passed else "FAIL",
                          "checks": [{"id": c, "name": n, "status": s} for c, n, s in results],
                          "violations": violations}, indent=2))
    else:
        print(f"# plan_verify ({fmt}) — {a.plan}")
        for cid, name, status in results:
            print(f"  [{status}] {cid} {name}")
        npass = sum(1 for _, _, s in results if s == "PASS")
        print(f"\nVERDICT: {'PASS' if passed else 'FAIL'} ({npass}/{len(results)} checks)")
        for v in violations:
            print("  VIOLATION " + v)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
