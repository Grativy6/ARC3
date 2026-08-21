# ARC3 Build 000 — Methods, results, and limitations

- **Build status:** PARTIAL
- **Branch:** `build/000-arc3-end-to-end`
- **Measured surfaces:** synthetic; local-public
- **Unmeasured surfaces:** online-public; Kaggle-public; semi-private; official-private
- **Claim boundary:** NO_GENERALIZATION_CLAIM

## Abstract

Build 000 implements a typed, offline ARC-AGI-3 agent around an immutable action/consequence
ledger, revisable perception and hypothesis state, executable world models, goal hypotheses,
bounded planning, recovery, checkpoint/resume, and scoped persistent memory. It also provides
deterministic synthetic and local-public evaluation, replay/tamper checks, process isolation,
ablations, runtime profiling, competition-integrity scans, and a deterministic offline Kaggle
package candidate.

The strongest controlled mechanism result is `synthetic`: on the Stage 12 integrated suite, the
full controller completed 32/32 episodes in 190 actions while deterministic cycle exploration
completed 4/32 in 463 actions under equal 16-action budgets. A broader Stage 14 suite retained
8/14 completions in 150 actions; removing world-model simulation reduced this to 1/14, and
removing goal inference reduced it to 0/14. These results do not transfer to the measured public
surface: the frozen full policy timed out in all 30 Stage 15 smoke/development runs, completed zero
levels, and returned no official scorecard. B0 random produced the sole nonzero scored result,
completing one development level. Stage 16
repaired the measured synthetic runtime envelope but failed four palette/action-remap robustness
cases. Build 000 is therefore a reproducible research system and packaging candidate, not evidence
of hidden-game generalization.

## Benchmark problem

ARC-AGI-3 presents interactive grid environments through observations and a constrained action
interface. The policy must acquire action semantics, infer mechanics and goals, and act with few
environment interactions. Unlike a static input/output task, an action changes the environment
and can consume a scarce opportunity; internal search is cheap relative to an inefficient probe.

Build 000 targets the official Python 3.12 interface pinned in `upstream.lock.json`. For
`local-public` measurements, ARC3 uses pinned executable behavior from `arc-agi==0.9.9`,
`arcengine==0.9.3`, and the named local `ScorecardManager`. Kaggle/private behavior remains
authoritative on those surfaces; documented discrepancies are preserved in `upstream.lock.json`.
The production candidate is offline, CPU-default, contains no hosted inference client, and is
statically checked for public game identifiers and obvious solution tables.

## Architecture

The controller preserves the following explicit progression:

```text
observation
  -> interpretation
  -> candidate hypothesis
  -> accepted rule
  -> executable world model
  -> goal hypothesis
  -> probe or plan
  -> action
  -> returned consequence
  -> confirmation, narrowing, contradiction, or reopening
```

Raw observations, submitted actions, and returned consequences are immutable hash-linked receipts.
Derived summaries, indices, hypotheses, models, goals, and plans are separately represented and
may be contradicted, retired, or reopened. A checkpoint binds its source trace and typed live
state. A pending submitted action restores only into an await-consequence phase; it is never
silently resubmitted.

Each action receipt can be traced to the pre-action observation, active mechanics/world models,
active goal hypotheses, selected probe or plan, concise alternatives, returned consequence, and
resulting belief revision. The integrated policy executes one environment action at a time and
validates the consequence before continuing a plan.

## Trace/world-model hypothesis

The engineering hypothesis was that explicit provenance, alternative preservation, retrodiction,
and reopening could improve action-efficient inference and make failures diagnosable. The
synthetic experiments support narrower components of that hypothesis:

- semantic probe selection reduced median identification cost on 101 controlled cases;
- full-history retrodiction rejected locally attractive rules that contradicted preserved history;
- explicit goal evidence displaced novelty-only behavior in delayed/proxy fixtures;
- bounded planning plus consequence validation recovered from model mismatch;
- source-linked scoped memory reduced repeated semantic probes in one cross-level fixture.

Those are bounded mechanism observations within one implementation lineage. They are not
independent confirmation of PAL, not a proof that PAL is correct, and not evidence that a formal
ledger alone creates intelligence. Conceptual provenance—not ARC3 execution authority—is PAL
v2.2's Spine, Mathematical Atlas, Ledger, Tests, and Compatibility Note. This single
implementation lineage is not independent corroboration and does not amend PAL canon.

## Implementation

The first-party implementation is organized by responsibility:

| Area | First-party surface |
|---|---|
| Official boundary | `src/arc3/adapters`, thin `agent/my_agent.py` |
| Immutable evidence | `src/arc3/trace` |
| Observation and correspondence | `src/arc3/perception` |
| Typed alternatives and reopening | `src/arc3/hypotheses` |
| Probe selection | `src/arc3/exploration` |
| Executable rules and retrodiction | `src/arc3/world_model` |
| Goal evidence | `src/arc3/goals` |
| Bounded search and recovery | `src/arc3/planning` |
| Scoped reuse and restart | `src/arc3/memory` |
| Integrated policy | `src/arc3/policy` |
| Procedural environments | `src/arc3/lab` |
| Evaluation and ablation | `src/arc3/evaluation`, `src/arc3/ablations` |
| Runtime profiling and integrity | `src/arc3/profiling`, `src/arc3/integrity` |
| Offline candidate | `src/arc3/packaging`, `scripts/prepare_kaggle_submission.py` |

The project pins CPython 3.12.14, uv 0.12.5, the complete dependency graph, official repository
commits, public documentation identities, the public partition manifest, evaluation
configurations, seeds, budgets, and package inputs. The final package serializes competition
controllers to bound resource use and constructs fresh action payloads rather than mutating shared
upstream enum members.

## Evaluation protocol

Results are separated by their exact evidence surface:

- `synthetic`: first-party procedural or controlled environments;
- `local-public`: official public game assets executed locally with the pinned scorer;
- `online-public`, `Kaggle-public`, `semi-private`, and `official-private`: not measured.

Stage 15 development and smoke partitions were frozen before Stage 15 evaluation, but
`ls20-9607627b` had already been opened and was permanently reassigned from would-be holdout to
development. The remaining ten-game one-shot public holdout was gated on a passing sealed
development result and remains unconsumed because the gate failed. The Stage 13–18 harness uses
process-isolated evaluation workers, preserves terminal failures and timeouts, binds
code/config/runtime identity, and seals complete artifact sets. Reproduction compares semantic
projections where timestamps, wall duration, and host paths are legitimately nondeterministic.

The production preset and public baselines use equal declared action/reset/wall budgets within a
comparison. No public game identifier or manually encoded action sequence is permitted in
production policy. Static source/archive scans, package sandboxing, trace replay, and deliberate
tamper tests check for obvious violations of those boundaries. No game source was read during
public evaluation to infer solutions.

Official RHAE remains unmeasured/null for these local runs; completion, environment-action counts,
and local scorecard values are reported separately and are not RHAE.

## Measured results

| Stage | Surface | Result | Interpretation |
|---|---|---|---|
| 06 | synthetic | 630/630 oracle-solvable procedural episodes across 15 rule families | Environment laboratory coverage, not agent performance |
| 07 | synthetic | 101 semantic cases; median selected-probe cost 1 action vs random 4 and cycle 3 | MECHANISM_OBSERVED for the controlled identification task |
| 08 | synthetic | 4/4 retrodiction-gated predicted completions vs 0/4 highest-rank without the gate | MECHANISM_OBSERVED on supplied symbolic states/plans |
| 09 | synthetic | goal-aware selection after supplied strong-progress evidence: 64/64 vs novelty-only 0/64 under equal five-action budgets | MECHANISM_OBSERVED on delayed/proxy fixtures |
| 10 | synthetic | planning 24/24 in 174 actions vs cycle 0/24 in 576; recovery 24/24 vs 0/24 | MECHANISM_OBSERVED on held-out symbolic tasks |
| 11 | synthetic | source-linked memory required 1 validation probe vs 3 without memory in one supplied-signature cross-level fixture | MECHANISM_OBSERVED on the controlled reuse fixture |
| 12 | synthetic | full 32/32 in 190 actions vs cycle 4/32 in 463 | Strongest integrated controlled result |
| 13 | synthetic | full 2/2 in 8 actions; cycle/trace 1/2 in 19; random/novelty 0/2 in 32 | Process-isolated pinned baseline milestone |
| 14 | synthetic | full 8/14 in 150 actions across 14 paired fixtures | Broader but still first-party synthetic evidence |
| 15 | local-public | FULL 0 levels and no official scorecard across 30/30 timeouts; B0 random produced the sole nonzero scored result and completed 1 development level | MECHANISM_NOT_OBSERVED; public holdout remains sealed |
| 16 | synthetic | 80 actions in 116.26474110002164 s; peak RSS 175,210,496 bytes; 9/9 runtime checks | Runtime envelope PASS; robustness stage FAILED_MECHANISM |
| 17 | synthetic | two byte-identical 11-artifact offline package builds; sandbox and schema PASS | PACKAGING_PASS, not a Kaggle or private result |
| 18 | synthetic | release infrastructure: 423 tests, 13 replay/tamper tests, exact Stage 13 reproduction, and byte-identical package builds | PASS for release infrastructure |
| 18 | local-public | FULL 0/6 successful runs, six timeouts, and zero levels | Stage 18 overall FAILED_MECHANISM; partial artifacts verify |

Primary compact receipts are under `docs/evidence/`; the corresponding methods and command
receipts are under `docs/reports/`. No score in this table is an online, Kaggle, semi-private, or
official-private score.

## Ablations

Stage 14 ran FULL and A1–A10 under paired seeds and equal budgets. The complete matrix contains
154/154 terminal episodes with zero controller faults.

| Variant | Change | Completions | Actions | Finding |
|---|---|---:|---:|---|
| FULL | competition preset | 8/14 | 150 | retained reference |
| A4 | no world-model simulation | 1/14 | 211 | seven lost completions; observed benefit |
| A5 | no goal inference | 0/14 | 224 | eight lost completions; observed benefit |
| A3 | retrodiction gate disabled | 8/14 | 141 | conflicting evidence: same completion, nine fewer actions |

A3 was not promoted: Stage 08 showed the opposite controlled mechanism result, and removing the
gate weakens the accepted-rule boundary. Null effects for the remaining switches were not treated
as proof that trace, checkpoint, recovery, or integrity machinery is unnecessary; several are
trace-only, restart-only, runtime-only, proxy-limited, or unexercised on this matrix.

## Representative failures

1. **Public transfer failure.** The full policy timed out in all 30 Stage 15 public smoke and
   development runs and completed no level. It again timed out in all six Stage 18 smoke runs.
   Packaging, release-infrastructure success, and synthetic runtime repair do not revise either
   negative result.
2. **Palette and action remapping.** Four Stage 16 paired cases remained operational but changed
   from base score 1.0 to 0.0. These are `FAILED_MECHANISM`, not infrastructure failures.
3. **Rule-change coverage gap.** One rule-change seed terminated before the intervention and is
   `NOT_EXERCISED`.
4. **Retrodiction conflict.** Disabling the retrodiction gate used nine fewer actions in Stage 14
   while failing the earlier Stage 08 mechanism test. The conflict remains open.
5. **Infrastructure failures preserved.** OneDrive temp permissions, Windows path limits,
   cross-platform line endings, shallow CI history, and an inherited Git ignore scope each caused
   failed runs before narrow repairs. Their receipts are not treated as policy evidence.

## Limitations and no-generalization boundary

- The public evidence is negative and small relative to hidden evaluation.
- The public holdout is deliberately unconsumed; there is no holdout result.
- The private Kaggle wheel inventory, platform framework input, gateway, scorer, and complete
  110-game workload were unavailable locally.
- The sequential 110-game runtime is estimated from a measured single-controller envelope, not
  measured end to end.
- Local schema validation is pinned-public; the private gateway remains authoritative.
- Static scans reduce obvious game-specific leakage risk but cannot prove absence of every
  possible shortcut.
- Hash seals are tamper-evident identities, not signatures or proof of trusted execution.
- There is no trained model, hosted inference dependency, online learning claim, or GPU benefit
  claim in Build 000.
- No official submission, hidden evaluation, release, license grant, or merge was performed.

Build 000 does not prove ARC hidden-game generalization, AGI, consciousness, PAL, or a general
theory of intelligence. Observation, interpretation, ontology, authority, and ethical consequence
remain distinct claim layers.

## Future experiments

Prioritized next experiments are:

1. predeclare and test generic palette/action equivariance on procedural paired suites;
2. profile why the current public full controller reaches 120-second timeouts at low action counts;
3. create two guaranteed-exposure rule-change cases and verify contradiction/reopening after the
   intervention;
4. rerun a new frozen public development milestone only after a generic policy change, preserving
   the existing negative result;
5. consume the public holdout only after a future predeclared milestone produces a passing sealed
   development result;
6. after owner legal/credential gates, run a no-submit rehearsal against exact platform inputs and
   preserve complete wall/RSS/gateway receipts;
7. compare bounded concurrency against the current sequential package only on the exact platform
   workload and resource envelope.

## Upstream attribution and source identity

Build 000 uses or inspects the following pinned upstream sources:

- `arcprize/ARC-AGI@f12822c4d550121c35a275008d964afbbed47d2f`;
- `arcprize/ARCEngine@b495c6acaf253c9681cd7b75c4299d352e9ce6f8`;
- `arcprize/ARC-AGI-3-Agents@4743e7d0aaae0ded0d98a89a7e282e63564cd58b`;
- `arcprize/ARC-AGI-3-Kaggle-Starter@eeb1535404f321d280a8f9194bbc1d7aca5f05fc`;
- `arcprize/docs@a5dfc0b64c625fb4a19cf074af845ebe0bb88ff8`;
- `arc-agi==0.9.9` and its exact Python 3.12 lock closure.

Exact identities, documentation hashes, dependency pins, and license observations are in
`upstream.lock.json`, `docs/reports/000-source-identity.md`, `THIRD_PARTY_NOTICES.md`, and
`docs/evidence/019-dependency-license-inventory.json`. The pinned Kaggle Starter had no detected
source license, so its behavior was inspected but its source was not copied. The Agents framework
remains an external platform-supplied component checked by exact raw-LF identities with a narrow
reversible CRLF allowance.

## Authorship and authority

Christopher D. Pang is the project author and steward. AI systems were used as engineering tools
and assistants, not as co-authors, owners, or independent authorities. Reports and receipts are
bounded evidence; they do not grant legal authority, accept competition terms, submit an entry,
or amend any external framework canon.
