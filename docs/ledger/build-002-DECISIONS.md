# ARC3 Build 002 decisions

Append-only record for material Build 002 engineering, source, evaluation, and authority decisions.
Christopher D. Pang is the author and steward; AI systems prepare implementation evidence and are
not co-authors or independent authorities.

## D-002-0001 — Base Build 002 on the exact merged origin/main

- Recorded: 2026-08-24T03:26:38Z
- Status: accepted.
- Decision: create `build/002-kaggle-competition-adapter` from fetched `origin/main`
  `a1931c673b90923e1af78127229667544802a096`, tree
  `7ddc02a03908e43caeda31edaf09bea9bd426cfd`, and do no implementation work on `main`.
- Evidence: `git merge-base --is-ancestor` passed for Build 001 final commit
  `8a42e43c96ac1edada21725746cdedcee24e68f9`; the merge commit's second parent is that exact
  Build 001 tip.
- Boundary: no history rewrite, prior-evidence alteration, merge, release, or official submission.

## D-002-0002 — Preserve Build 001 as PARTIAL and open a separate one-run authority

- Recorded: 2026-08-24T03:26:38Z
- Status: accepted from the active owner instruction; not yet consumed.
- Decision: retain Build 001's final `PARTIAL`, `HOLDOUT_NOT_EARNED`, and
  `SEALED_UNCONSUMED` records exactly as historical evidence. For Build 002 only, authorize one
  run over the same ten-game public set after all frozen preflights pass.
- Current Build 002 state: `AUTHORIZED_ONCE_NOT_YET_CONSUMED`; runs started `0/1`.
- Consumption rule: durable intent immediately before the first and only upstream scorecard open
  consumes the run. Each later environment `make` intent is counted separately. Crash, timeout,
  platform failure, or zero score after scorecard-open intent does not restore authority, even if
  no environment `make` was reached.
- Boundary: later Build 002 evidence cannot revise or retrospectively earn any Build 001 claim.

## D-002-0003 — Add a bounded competition mode without replacing research mode

- Recorded: 2026-08-24T03:26:38Z
- Status: implementation in progress.
- Decision: retain the persistent research controller under `RESEARCH_UNBOUNDED` with its existing
  tracing, per-action checkpoints, and generic opaque-action learning defaults. Add an explicit
  `COMPETITION_BOUNDED` policy with bounded global runtime, compact trace, sparse recovery
  checkpoints, deterministic replay, and failure receipts.
- Evidence basis: Build 001 Stage 03 measured an 80.801 percent wall-time reduction with allocator
  tracing off and a 17.538 percent reduction with automatic checkpointing off under exact matched
  actions and outcomes.
- Boundary: those measurements justify competition-only hot-path controls; they do not establish
  gameplay recovery or authorize changing research defaults.

## D-002-0004 — Use documented fixed semantics only at the competition adapter boundary

- Recorded: 2026-08-24T03:26:38Z
- Status: implementation in progress.
- Decision: in `COMPETITION_BOUNDED` only, treat official documentation's ACTION1=up,
  ACTION2=down, ACTION3=left, ACTION4=right, and ACTION7=undo as granted interface information.
  Keep ACTION5 and coordinate-dependent ACTION6 evidence-driven. Preserve generic opaque-action
  calibration in `RESEARCH_UNBOUNDED`.
- Source: `arcprize/docs` commit `a5dfc0b64c625fb4a19cf074af845ebe0bb88ff8`,
  `actions.mdx` blob `2ebe7dc536e07aabf4f52727e6012ca0df485c30`, file SHA-256
  `a0125637f035b1f4e5f445ec939d0cce848e1b95b310fe1afb34b14421667662`.
- Boundary: documentation grants an input interface; it does not grant game-specific solutions,
  ACTION5 meanings, ACTION6 active coordinates, or permission to hard-code public game IDs.

## D-002-0005 — Let the competition-specific nine-hour limit control

- Recorded: 2026-08-24T03:26:38Z
- Status: accepted pending frozen runtime verification.
- Decision: use the live competition metadata's 540-minute CPU/GPU limit as the controlling
  ceiling instead of the generic twelve-hour notebook ceiling. Configure the global governor with
  a 6,000-second reserve inside that nine-hour envelope.
- Evidence: anonymous Kaggle CompetitionService response observed at
  `2026-08-24T03:10:13.3556365Z`, response SHA-256
  `de323841ab53bc7f0378a632a3176566111c8a4060009e7952b826661896e09e`.
- Reopening condition: a newer official competition-specific source changes the limit before the
  frozen one-shot preflight. Any change requires a new exact identity and fresh preflight; it does
  not silently mutate a frozen run.

## D-002-0006 — Fail closed across scoring and package-version discrepancies

- Recorded: 2026-08-24T03:26:38Z
- Status: accepted.
- Decision: identify the local public result by its exact toolkit scorer and never label it
  official Kaggle RHAE. Preserve the conflict between ARC-AGI 0.9.9's 1.15 per-level cap and the
  current Kaggle data-page formula's 1.0 cap. Preserve the current public toolkit version 0.9.9
  versus the latest observed staff-sample 0.9.6 divergence.
- Boundary: exact private wheel, framework input, gateway, scorer, and Parquet-schema behavior
  remain `BLOCKED_EXTERNAL` until an owner-authorized official surface returns evidence.

## D-002-0007 — Require package and notebook gates before public consumption

- Recorded: 2026-08-24T03:26:38Z
- Status: accepted; gates pending.
- Decision: the one-shot run cannot begin until exact source/lock identity, competition lifecycle,
  offline cold start, complete payload/license inventory, deterministic startup, notebook build
  and execution, structural `submission.parquet` validation, secret scan, and no-network
  competition entry point all pass against one frozen configuration.
- Boundary: a host environment import, canned Parquet file, approximate fixture, or static scan
  cannot substitute for the required execution. A preflight failure leaves the one-run authority
  unconsumed.

## D-002-0008 — Preserve every environment with bounded fallback

- Recorded: 2026-08-24T03:26:38Z
- Status: implementation in progress.
- Decision: use a process-global tournament governor to allocate time/actions dynamically, enforce
  legal actions, account for value and opportunity cost, stop deterministically, and reserve a
  bounded fallback path for every supplied environment. Every environment must appear in the one
  scorecard even when its measured result is zero or a failure.
- Boundary: graceful inclusion does not permit multiple `make` interactions, game reset, illegal
  actions, a second scorecard, omitted environments, or a manufactured successful row.
