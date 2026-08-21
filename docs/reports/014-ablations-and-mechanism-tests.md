# Stage 14 — Ablations and mechanism tests

- **Stage status:** PASS
- **Measured surface:** synthetic
- **Claim:** NO_GENERALIZATION_CLAIM
- **Measured commit:** `565712fe6fb1e62f704f40a7693d3d3fb1de3ada`
- **Primary evidence:** `docs/evidence/014-ablation-acceptance.json`
- **Preserved infrastructure failure:** `docs/evidence/014-ablation-infrastructure-failure.json`

## Result

The frozen A1–A10 protocol ran 154/154 equal-budget episodes from a clean detached worktree:
14 cases for FULL and each of ten one-feature removals, with 16 actions, two resets, a
120-second per-episode wall envelope, 2,048 search nodes, deterministic seeds, exact synthetic
scorers, immutable traces, and zero controller faults. The run used no network and no GPU.

FULL completed 8/14 cases in 150 actions. Removing world-model simulation (A4) reduced
completion to 1/14, and removing goal inference (A5) reduced it to 0/14. These are the two clear
positive integrated mechanism results on this suite. They are synthetic results, not evidence of
public- or hidden-game generalization.

## Paired comparison

| ID | Removed mechanism | Exposure | Completed | Actions | Effect relative to FULL | Classification |
|---|---|---|---:|---:|---|---|
| FULL | none | reference | 8/14 | 150 | — | reference |
| A1 | persistent game memory | partial proxy only | 8/14 | 150 | no score/action change; checkpoints removed | MECHANISM_NOT_OBSERVED |
| A2 | rejected-hypothesis retention | 43 contradictions | 8/14 | 150 | no score/action change; 80 fewer trace events | MECHANISM_NOT_OBSERVED |
| A3 | retrodiction gate | 156 receipts | 8/14 | 141 | ungated used 9 fewer actions | FULL_COMPONENT_REGRESSION |
| A4 | world-model simulation | 55 plan evaluations, 63 predictions | 1/14 | 211 | FULL +7 completions and +7 score | MECHANISM_OBSERVED |
| A5 | goal inference | 144 goal candidates | 0/14 | 224 | FULL +8 completions and +8 score | MECHANISM_OBSERVED |
| A6 | coordinate salience | 31 coordinate actions | 8/14 | 150 | no score/action change | MECHANISM_NOT_OBSERVED |
| A7 | planner recovery | 10 planned mismatches | 8/14 | 150 | no score/action change | MECHANISM_NOT_OBSERVED |
| A8 | object tracking | trace-only, not policy-coupled | 8/14 | 150 | no behavior change; 150 fewer events | MECHANISM_NOT_OBSERVED |
| A9 | information-gain term | no positive-information candidate | 8/14 | 150 | exposure absent | NOT_EXERCISED |
| A10 | trace summaries | runtime-only | 8/14 | 150 | identical score, actions, and event count | MECHANISM_NOT_OBSERVED |

Completion counts and action totals are raw sums over the same 14 cases. The action effect for
A3 is `ablated - FULL = -9` across eight equally completed pairs. Runtime values are retained in
the primary evidence but are descriptive because variants ran sequentially and checkpoint I/O
differs by design; Stage 16 owns controlled performance conclusions.

## Interpretation and competition preset

FULL remains the competition preset. A4 and A5 show clear benefit. A3 is not promoted despite
its nine-action advantage here: Stage 08 found the opposite mechanism result on four held-out
symbolic combinations, where retrodiction-gated selection completed 4/4 and the ungated
highest-rank alternative completed 0/4. The evidence is therefore context-dependent, and
removing the gate would weaken the accepted-rule boundary without a broader confirming result.

The other unchanged ablations do not justify broad removal. A1 exercises checkpoint persistence
but not cross-level learned-rule retrieval; A8 changes receipts without changing current symbolic
entities; A9 never reaches a positive information-disagreement case; and A10 is a runtime lookup
choice. A2, A6, and A7 were reached but showed no effect on this case set. Those negative and
unexercised results remain open burdens. Prior scoped mechanism evidence and required
trace/restart behavior are not erased by this integrated matrix.

## Representative traces

The authoritative evidence retains every raw episode row and its terminal trace hash. A FULL
success is `navigation-seed-101`, ending at
`sha256:44b0aab501640c74356f87935b98ccaad02e6f47cb3c96680b731ac8d00e182f`.
A FULL failure is `held-out-combinations-0000`, ending at
`sha256:fca5df1538abbe61ff6546d83534709928d95393cec301c1bbd6d9254ec3d4d1`.
For A4, `navigation-seed-101` changes from FULL success to ablation failure; the A4 trace ends at
`sha256:379024fead5c4ab2b0938b4999bbeb04777589935c40a6b62f6f35ad81dd2f67`.
A5 also fails that case, ending at
`sha256:9e1fe34180b65a778708f724c5881df4c24e548e3ecdf3e0af29e94eb5127e4b`.

## Reproduction and identities

The initial complete short-path run was a dirty-tree preacceptance result. The clean committed run
reproduced its exact semantic digest:

```text
preacceptance semantic digest: sha256:99f7ce35e86f9348ff0460345bb6921ee4fce7d641e8abcb470014ce29d1ad76
authoritative semantic digest:  sha256:99f7ce35e86f9348ff0460345bb6921ee4fce7d641e8abcb470014ce29d1ad76
case manifest:                 sha256:121264695566131342f3af9fbdefa0b3a0a2c812759467ef3863fcdbe339caa9
frozen protocol manifest:      sha256:b00c45337f451ecde9af097ce68c8eb60203a7516bff55d9ed7c40868700b369
authoritative artifact core:   sha256:ec86629685dad3b5693247d2514c3be89f38e79fc4cca2907a0d35ba09468045
authoritative evidence file:   sha256:56e7c23bea479cd64fb4433e369bda28177ca76e94e4ba18ee756dab3a8ab82c
```

The authoritative run began `2026-08-21T08:37:24.369230Z` and ended
`2026-08-21T08:44:34.738428Z`. Its source worktree was clean and detached at the measured commit.

## Preserved failure

The first run used the OneDrive-backed repository path for checkpoints and stopped after nine
FULL episode directories when an atomic `latest.json` replacement returned Windows error 5.
It exited 1 after 14.0 seconds before any ablation comparison existed. The exact exception,
command, partial counts, and the partial tree-manifest hash are preserved in the failure evidence.
Moving the generated runtime tree to `C:\a` resolved the infrastructure condition; the failed
attempt remains recorded rather than being relabeled as a mechanism failure or deleted.

## Verification

```text
Ruff check: PASS
Ruff format: 8 files already formatted
strict mypy: 6 source files clean
focused pytest: 48 passed in 54.56s
authoritative matrix: PASS, 154/154 episodes, 0 faults
protocol/case identity: PASS
preacceptance-to-clean semantic reproduction: PASS
production game-ID and hosted-network scan: PASS
```

## Commands

```text
.venv\Scripts\python.exe -m pytest -q --no-cov --basetemp C:\a\t14-final-6d985978a7 tests/unit/test_ablation_features.py tests/integration/test_ablation_runner.py tests/unit/test_controller_contract.py tests/integration/test_controller_end_to_end.py tests/replay/test_controller_checkpoint.py tests/competition/test_controller_offline_integrity.py tests/integrity/test_policy_scan.py
.venv\Scripts\python.exe -m ruff check scripts/measure_ablations.py src/arc3/ablations src/arc3/policy/controller.py src/arc3/policy/models.py tests/unit/test_ablation_features.py tests/integration/test_ablation_runner.py
.venv\Scripts\python.exe -m mypy --strict scripts/measure_ablations.py src/arc3/ablations src/arc3/policy/controller.py src/arc3/policy/models.py
$env:PYTHONPATH='C:\a\arc3-s14-auth-565712f\src'
C:\Users\cdpan\OneDrive\Documents\ARC3\.venv\Scripts\python.exe C:\a\arc3-s14-auth-565712f\scripts\measure_ablations.py --output C:\Users\cdpan\OneDrive\Documents\ARC3\docs\evidence\014-ablation-acceptance.json --work-root C:\a\arc3-s14-auth-data-565712f
```

## Preserved limits

- The suite is synthetic: eight deterministic navigation seeds and six predeclared procedural
  holdouts. It cannot establish official-public or hidden-game performance.
- FULL failed all six procedural holdouts; its eight completions came from the navigation set.
- A1 does not test learned cross-level rule retrieval in the integrated controller.
- A8 is trace-only in the current controller, and A9 was not exercised.
- Official RHAE remains unmeasured.
- These results do not establish PAL, AGI, consciousness, or a general theory of intelligence.
