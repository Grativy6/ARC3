# Diagnosing and repairing an evidence-ledger ARC-AGI-3 controller under sealed public evaluation

**Publication draft — not submitted**

- **Author:** Christopher D. Pang
- **Project:** ARC3 Build 001
- **License:** MIT-0 for ARC3 first-party source
- **Measured evidence:** `synthetic`, `local-public`
**Unmeasured evidence:** `online-public`, `Kaggle-public`, `semi-private`, `official-private`

## Abstract

Interactive ARC tasks couple inference quality to environment-action efficiency: a probe can reveal
a mechanic, consume a scarce action, or irreversibly alter state. ARC3 represents each observation,
interpretation, candidate mechanic, accepted rule, world model, goal hypothesis, plan, action, and
returned consequence as distinct typed state linked to an immutable trace. Build 001 asked whether
generic throughput and equivariance repairs could recover from Build 000's measured public-game
failure without game identifiers or manually encoded solutions.

We reproduced the frozen local-public timeout, attributed 99.9783% of one representative prefix,
and used matched-action interventions to identify allocation tracing and checkpoint persistence as
material wall-time causes. Disabling allocation tracing reduced a 46.0703-second controlled prefix
to 8.8449 seconds; disabling checkpoints reduced it to 37.9904 seconds; both disabled required
6.7524 seconds. Generic palette correspondence then passed 256/256 paired procedural cases, and
opaque action calibration passed 128/128 paired cases plus 528/528 post-calibration inverse
requests. A subsequent 112-execution rule-change experiment failed its typed acceptance criteria:
action rotation passed 32/32, but traversability and stationary-noise gates each passed 0/32 despite
32/32 terminal wins, and checkpoint continuity passed only 4/8 pairs.

The decisive development and regression experiments ended at authenticated infrastructure
boundaries before agent performance could be measured. Their unique attempts were not rerun.
Consequently, the predeclared holdout gate was not earned, and the ten-game public holdout remained
sealed with zero loaded identities and zero gameplay actions. Available-surface packaging produced
deterministic offline candidates across local Windows and hosted Ubuntu/Windows runs, but exact
private competition surfaces were unavailable. Build 001 is therefore a partial, reproducible
failure-recovery study. It supports narrow claims about diagnosed bottlenecks and controlled
equivariance mechanisms, not local-public recovery, hidden-game generalization, RHAE, AGI, or a
general theory of intelligence.

## 1. Introduction

ARC-AGI-3 changes the operational problem from static transformation to sequential interaction.
An agent observes a grid-like state, chooses from a variable action space, receives a consequence,
and must update its beliefs and plan. The environment penalizes inefficient action use, while the
correct mechanics and goal are initially unknown. These properties motivate a policy that keeps
evidence, interpretations, hypotheses, and permissions to act separate.

ARC3 Build 000 implemented that separation and showed several controlled synthetic mechanisms. It
also failed on the measured local-public surface: the full policy timed out repeatedly at low
action counts and completed no level. It exhibited paired palette and action-remap failures. Build
001 was designed as a frozen failure-recovery program, not a fresh benchmark or a license to tune
against a public holdout.

The primary question was:

> Can generic throughput, palette-correspondence, action-calibration, rule-reopening, and
> two-speed-control repairs produce a valid measured improvement on a frozen local-public
> development protocol while preserving evidence integrity and a sealed holdout?

## 2. Evidence architecture

The controller explicitly separates:

```text
observation -> interpretation -> candidate hypothesis -> accepted rule
            -> executable world model -> goal hypothesis -> probe/plan
            -> action -> returned consequence -> trace update or reopening
```

Raw observations, actions, and consequences are immutable hash-linked receipts. Derived
summaries, correspondence indices, hypotheses, rules, goals, and plans are revisable. A successful
outcome cannot rewrite a prior hypothesis as having been known. Contradictions remain visible and
can retire or reopen accepted state. Each action receipt names the available observation, active
models and goals, selected probe/plan, concise alternatives, returned consequence, and resulting
belief revision.

Production code is offline and deterministic under a supplied seed. It contains no hosted-model
runtime dependency, public-game-ID solution table, or manually encoded public action sequence.
Static source/archive checks fail on known public identifiers and obvious game-specific tables.

## 3. Protocol and frozen boundaries

Build 001 began from canonical repository identity
`28c7a00732ce48e5c231211b01bc6eba7d0d71b4`. Upstream repositories, packages, documentation,
rules identities, source commits, configuration, seeds, action budgets, wall limits, and hardware
were pinned. Build 000 was used only through immutable historical artifacts and a detached
comparator checkout.

Evidence labels were fixed as `synthetic`, `local-public`, `online-public`, `Kaggle-public`,
`semi-private`, and `official-private`. A result could not migrate between labels. Local scores
were not official RHAE. The ten-game public holdout could open only if five predicates were all
true: Stage 09 PASS, Stage 10 PASS, no unresolved competition-integrity failure, unchanged
production source, and exact sealed holdout identity. The gate could not be weakened after results.

The owner authorized MIT-0 for first-party source. Legal-term acceptance, paid compute, official
submission, PR merge, release publication, credentials, and external communication remained human
gates and were not performed.

## 4. Failure reproduction and causal profiling

The Stage 01 matched local-public run reproduced the failure:

| Controller | Wall seconds | Actions | Levels | Local score |
|---|---:|---:|---:|---:|
| Build 001 FULL | 120.11965939996298 | 21 | 0 | 0.0 |
| frozen Build 000 FULL | 120.110601900029 | 19 | 0 | 0.0 |

Stage 02 instrumentation covered 99.9783% of one eight-action local-public prefix. Action
selection accounted for 48.06% of measured wall, checkpoint work 16.97%, startup 10.84%, goal
work 9.22%, trace work 6.12%, retrodiction 2.35%, and planning 1.10%. The instrumentation itself
added a 4.62% median overhead on a controlled synthetic calibration.

Stage 03 used interventions that preserved the exact action and outcome sequence. Relative to the
46.070333300042-second control, disabling allocation tracing used 8.84490280004684 seconds
(-80.80%), disabling checkpoint persistence used 37.9903721000301 seconds (-17.54%), and disabling
both used 6.7524 seconds. This is causal timing evidence for the measured prefix. It is not evidence
that a production repair improves completion or action efficiency.

## 5. Generic equivariance repairs

### 5.1 Palette correspondence

The palette mechanism represents roles and correspondences without treating literal color
identity as a stable mechanic. Under the predeclared synthetic matrix it passed 256/256 paired
bijections, 16/16 checkpoint/resume pairs, 64/64 joint equivalence controls, 64/64 one-sided
distinguishability controls, and both frozen historical regressions. Across 324 executions it
recorded zero controller faults. The historical unpermuted workload increased from eight to ten
actions, so the result demonstrates bounded equivariance, not free invariance.

### 5.2 Opaque action calibration

The action mechanism distinguishes stable effect facets from opaque external handles, calibrates
the mapping from observed consequences, and uses inverse requests only after evidence supports the
mapping. It passed 128/128 procedural pairs, 528/528 post-calibration inverse requests, 64/64
causal controls, 16/16 restart pairs, and both historical action-remap regressions. The historical
unpermuted workload increased from eight to twelve actions, preserving an explicit calibration-cost
burden.

## 6. Failed rule-change mechanism

Stage 06 predeclared 112 controlled executions across action rotation, traversability change,
stationary noise, and checkpoint continuity. All executions completed without controller faults or
invalid requests, and all trace/prefix checks passed. Yet the typed result was
`FAILED_MECHANISM`:

- action rotation: 32/32 accepted;
- traversability: 0/32 accepted despite 32/32 terminal wins;
- stationary noise: 0/32 accepted despite 32/32 terminal wins, 32/32 noise resolutions, and zero
  false-positive reopenings;
- checkpoint continuity: 4/8 paired comparisons.

This distinction matters. A terminal win is an outcome; it is not retroactive proof that the agent
formed the correct typed rule, preserved the right causal support, or reopened for the declared
reason. The experiment falsified the full predeclared mechanism while retaining a narrower action-
rotation success.

## 7. Retrodiction and two-speed control

Build 001 implemented event-triggered retrodiction caches bound to immutable evidence and a
two-speed controller with typed triggers for deeper deliberation. Partial Stage 07 receipts showed
that FULL, EVENT_TRIGGERED, and CACHED modes rejected eight false histories while RECENT_WINDOW_8
accepted all eight false histories. However, the 280-cell attempt failed before aggregate and
microbenchmark completion. Stage 08 likewise ended after one of twenty cells, leaving zero valid
timing pairs. Neither attempt can support a winner, a throughput claim, or a public-recovery claim.

The failures were preserved. Generic serialization, timing, source-binding, process-supervision,
and validator repairs were added for future work without resuming either unique experiment.

## 8. Decisive evaluation and holdout gate

Stage 09 froze 96 matched local-public cells. Its non-playing authority preflight passed all 14
predicates. On the single authorized launch, a Windows virtual-environment launcher PID differed
from the actual interpreter PID. Exact worker identity therefore failed closed before environment
open: one development identity was exposed, zero gameplay actions occurred, and 95 cells remained
unstarted. This is `FAILED_INFRASTRUCTURE`, not evidence about the controller's recovery mechanism.

Stage 10's one authorized launch failed when the first suite omitted a required frozen-commit
argument. One of nine suites completed its infrastructure terminal; eight remained unstarted. No
Build 001 baseline, ablation, resource, or robustness comparison exists.

Because Stage 09 and Stage 10 were not PASS, all five Stage 11 holdout predicates were false. The
gate returned `HOLDOUT_NOT_EARNED`. Stage 12 recorded no adapter load, no manifest parse, no loaded
holdout identity, and zero environment action. The public holdout remains sealed and cannot be
reopened in Build 001.

## 9. Offline packaging

The accepted clean local verifier at `d9c19558…` completed 20 available checks and stopped only at
the exact private-platform boundary. Two builds produced byte-identical 788,071-byte candidate
archives at SHA-256 `0bd55b93…a095bd`; startup passed in 1.605782 seconds at 67,846,144-byte peak
RSS with zero Python-audited network or process-launch attempts. The package-safe suite passed 699
tests with two platform skips. Four hosted Ubuntu/Windows jobs reproduced that local-source
identity.

The final code/test/package freeze `9f25e13…` retained the same 100-member runtime payload
projection. Because source identity is embedded in the archive, its outer identity changed: all
eight A/B candidates across four final hosted Ubuntu/Windows jobs are byte-identical at 788,070
bytes and SHA-256 `02326a14…56d21`. Exact-source ordinary CI also passed on Ubuntu and Windows for
both push and draft-PR events. Secret scans found zero findings.

These receipts are bounded. Python audit hooks are not OS filesystem/network/native containment,
sampled RSS is not a hard limit, static import reachability cannot prove every dynamic/native path,
and public gateway-shaped fixtures cannot establish private scorer compatibility. Exact private
wheels, framework input, gateway, and scorer remained unavailable. No upload or submission was
performed.

## 10. Results and claim status

| Claim | Status | Evidence label |
|---|---|---|
| `THROUGHPUT_BOTTLENECK_IDENTIFIED` | observed for matched prefix | local-public |
| `PALETTE_EQUIVARIANCE_OBSERVED` | observed on paired controlled suite | synthetic |
| `ACTION_EQUIVARIANCE_OBSERVED` | observed on paired controlled suite | synthetic |
| `RULE_CHANGE_REOPENING_OBSERVED` | not supported; full stage failed | synthetic |
| `LOCAL_PUBLIC_RECOVERY_OBSERVED` | not measured | local-public |
| `HOLDOUT_GATE_EARNED` | false | synthetic gate evidence |
| `HOLDOUT_NOT_EARNED` | mechanically observed | synthetic gate evidence |
| `PUBLIC_HOLDOUT_RESULT_OBSERVED` | no result exists | — |

Overall status is `BUILD 001: PARTIAL`.

## 11. Threats to validity

1. Controlled procedural matrices are first-party synthetic evidence from one implementation
   lineage, not independent corroboration or hidden-game evidence.
2. The local-public sample is small and negative; the decisive recovery matrix did not reach
   gameplay.
3. Timing interventions isolate causes for matched prefixes but are not a production-performance
   trial.
4. Palette and action mechanisms carry measured action-cost regressions.
5. Unique Stage 07–10 attempts are incomplete and cannot be rerun without violating the frozen
   protocol.
6. Exact private platform behavior and full competition runtime remain unmeasured.
7. Static and Python-level integrity controls do not prove complete trusted execution or native
   containment.

## 12. Reproducibility and artifact availability

The implementation branch, draft PR, exact source commits, dependency lock, upstream lock,
predeclarations, run receipts, acceptance artifacts, failure receipts, decision ledger, burden
ledger, machine-readable result table, package receipts, and final evidence index are preserved in
the ARC3 repository. External raw artifacts are identified by absolute measured-machine paths and
SHA-256 hashes; concise tracked receipts prevent claims from depending solely on those paths.

The public holdout contents are intentionally absent from this paper. Reproduction must not open or
enumerate that holdout unless a future separately predeclared gate is legitimately earned.

## 13. Authorship and acknowledgments

Christopher D. Pang is the project author and steward. AI systems were used as development tools
and assistants for implementation, verification, and drafting. They are not co-authors, owners, or
independent authorities. This report does not claim that ARC3 validates PAL, proves AGI or
consciousness, or establishes a general theory of intelligence.
