# Stage 12 — Full ARC3 controller integration

- **Stage status:** PASS
- **Measured surfaces:** synthetic; local-public
- **Mechanism result:** MECHANISM_OBSERVED on the declared synthetic surface
- **Measured controller commit:** `3fee19d9f82210ba5010af94feac170164a30f3c`
- **Primary evidence:** `docs/evidence/012-controller-acceptance.json`

## Result

One typed controller now owns the observation-to-action path used by the synthetic adapter and
the thin official/Kaggle wrapper. The wrapper constructs `ARC3Controller`; it does not carry a
second policy. The deterministic presets are `baseline`, `trace`, `world-model`, `full`, and
`competition`. The optional proposal boundary is local and disabled by default. Production
policy contains no hosted-model dependency, public-game identifier, or embedded action table.

The callback path validates and normalizes the raw observation, appends its immutable receipt,
derives measurements, revises hypotheses, retrodicts models, revises goal candidates, creates
probe/plan alternatives, validates one action, records its prediction and submission, consumes
the returned consequence on the next callback, and checkpoints the resulting state. Every
environment action retains a complete pre-action and post-action receipt chain. Derived state is
reconstructable and reopenable; raw receipts are not rewritten.

## Equal-budget synthetic measurement

The final fresh-process run used seeds 0–31 and a 16-action budget per episode:

| Policy | Completed | Completion rate | Total actions | Mean actions/episode |
|---|---:|---:|---:|---:|
| full controller | 32/32 | 1.000 | 190 | 5.9375 |
| deterministic cycle | 4/32 | 0.125 | 463 | 14.46875 |

This is a measured +28-completion difference on `synthetic-grid-v1`. The full controller wrote
4,819 trace events covering 190 submissions, 190 returned consequences, and 190 complete action
chains. All 32 checkpoint artifacts were present, all 32 restores verified, no restore duplicated
an event, and no controller fault occurred. The run took 47.058359 seconds. Its canonical evidence
core is `sha256:ba315a58cab567540cade4f1d08bc20e9d1d36830edabff56efe5929dd47d51d`.

The competition preset separately completed the same synthetic mechanism in seven actions with
network disabled, a verified checkpoint restore, seven complete receipt chains, zero duplicate
events, and zero faults. This shows the offline execution boundary; it is not competition score
evidence.

## Official boundary smoke

An earlier Stage 12 preacceptance run used the pinned official local environment on the already
exposed development game `ls20-9607627b`, seed 7, for eight actions. It produced 524 immutable
events, eight submissions, eight consequences, zero controller faults, zero completed levels,
and official score **0.0**. The trace hash is
`sha256:059400b915f01926b172810eb9a9ce86526fd00b8cec44a8e8612a7cfa57ab1f`.
That run names commit `d1c06cd4e512ab83093d291ae4f990bbcc039ced`; later corrective changes were
validated through fresh-process synthetic and pinned official-shaped wrapper tests, not by
replaying this public environment. It is retained as bounded adapter evidence only.

The pinned `FrameData` wrapper test covers the official toolkit's default `RESET`-shaped
`action_input` ambiguity and confirms that normalization happens only at the wrapper boundary.
Direct adapters retain strict returned-action mismatch checking. Online official API execution
remains `BLOCKED_EXTERNAL` because no credentials were available; no credential was required for
the local, synthetic, or packaging work.

## Deterministic restart and fault handling

Checkpoints restore exact controller phase, RNG, action/reset counters, pending plan and
prediction, explored coordinates, typed hypotheses, world models, goals, and memory. A submitted
action is never resubmitted after restoration; the adapter must reconcile its consequence. A
returned-action mismatch first preserves the actual consequence and raw observation, accounts
for the action actually taken, then faults the controller. `FAULTED` cannot select another action.

Level-scoped goals and hypotheses retire and reseed with source evidence on level transitions.
Receipt-derived identities prevent collisions when a level index is revisited, and a decreasing
level index is recorded as metadata change rather than falsely claiming level completion.

## Verification

```text
focused pytest without coverage: 21 passed in 22.96s
Ruff check / format: PASS
strict mypy over 8 Stage 12 source files: PASS
fresh-process controller and wrapper imports: PASS
public-ID / hosted-network / duplicated-wrapper-policy scans: 0 matches
```

Preacceptance failures are preserved in the evidence JSON. They include two fresh-process
initialization defects, one signed-seed defect, two test-audit defects, Windows temporary-path
failures, and two post-checkpoint level-transition defects. All named mechanism defects were
corrected and covered by the final focused suite; the infrastructure failures were avoided with
a short unique basetemp rather than relabeled as product success.

## Commands

```text
.venv\Scripts\python.exe -m pytest -q --no-cov --basetemp C:\a\<unique> tests/unit/test_controller_contract.py tests/integration/test_controller_end_to_end.py tests/replay/test_controller_checkpoint.py tests/competition/test_controller_offline_integrity.py
.venv\Scripts\python.exe -m ruff check --no-cache agent/my_agent.py scripts/measure_controller.py src/arc3/goals/registry.py src/arc3/policy tests/unit/test_controller_contract.py tests/integration/test_controller_end_to_end.py tests/replay/test_controller_checkpoint.py tests/competition/test_controller_offline_integrity.py
.venv\Scripts\python.exe -m ruff format --check --no-cache agent/my_agent.py scripts/measure_controller.py src/arc3/goals/registry.py src/arc3/policy tests/unit/test_controller_contract.py tests/integration/test_controller_end_to_end.py tests/replay/test_controller_checkpoint.py tests/competition/test_controller_offline_integrity.py
.venv\Scripts\python.exe -m mypy --strict --cache-dir C:\a\<unique> agent/my_agent.py scripts/measure_controller.py src/arc3/goals/registry.py src/arc3/policy
.venv\Scripts\python.exe scripts/measure_controller.py --output artifacts/stage12/controller-measurement-final.json
```

## Preserved limits

- The measured improvement is synthetic and does not establish public or hidden-game
  generalization.
- The official local smoke scored exactly zero, used an exposed development game, and preceded
  the final Stage 12 corrective checkpoint.
- The cycle baseline is intentionally uninstrumented; integrated trace cost remains a Stage 16
  profiling burden.
- Online official API behavior remains unmeasured without credentials.
- These results do not prove PAL, AGI, consciousness, or a general theory of intelligence.
