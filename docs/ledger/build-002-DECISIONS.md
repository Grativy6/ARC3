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

## D-002-0009 — Freeze the implemented mode and governor contracts

- Recorded: 2026-08-24T08:37:44Z.
- Status: accepted and implemented.
- Decision: retain `RESEARCH_UNBOUNDED` with its inherited tracing, automatic per-action
  checkpointing, and opaque-action learning defaults. Freeze `COMPETITION_BOUNDED` with allocator
  tracing off, automatic per-action checkpoint serialization off, compact in-memory trace capacity
  `512`, and sparse checkpoints every `16` actions.
- Competition governor: nine-hour `32,400s` ceiling, `6,000s` protected non-game reserve, dynamic
  allocation across `110` environments, maximum `240s` per game, minimum `5s` and one action
  protected for every future environment, exact legal-action filtering, explicit value and
  opportunity-cost receipts, and deterministic stop/fallback behavior.
- Interface decision: competition mode treats ACTION1=up, ACTION2=down, ACTION3=left,
  ACTION4=right, and ACTION7=undo as granted interface facts. ACTION5 and coordinate-dependent
  ACTION6 remain evidence-driven. Research mode's generic opaque-action mechanism is unchanged.
- Evidence: final synthetic profile
  `cfea7341ecd3617978451e0d6e8384d4f9d2cf4566fc72f6fdc55f3aaacad6bd`.
- Boundary: this establishes a tested mechanism, not gameplay recovery, generalization, or RHAE.

## D-002-0010 — Move one-shot consumption to scorecard-open intent

- Recorded: 2026-08-24T08:37:44Z.
- Status: accepted; prior mechanism superseded and preserved.
- Initial mechanism: the first durable version consumed authority immediately before the first
  environment `make`. That left the upstream `open_scorecard` interaction outside the one-shot
  seal.
- Decision: durable `scorecard.open_intent` immediately before the sole upstream scorecard open is
  the authority-consumption boundary. Each later environment `make` remains independently
  intent-counted.
- Consequence: a crash or failure after scorecard-open intent consumes the one run even when make
  interactions remain zero. A preflight failure before that marker does not consume authority.
- Verification: tests cover scorecard-open failure, marker-before-upstream ordering, rerun denial,
  make-after-scorecard ordering, interruption recovery, one scorecard, one make per environment,
  level resets only, no game resets, and no in-flight scorecard read.
- Boundary: Build 001's earlier holdout record remains unchanged.

## D-002-0011 — Accept local packaging evidence without claiming private parity

- Recorded: 2026-08-24T08:37:44Z.
- Status: accepted.
- Decision: classify the current package, generated notebook, structural Parquet file, and native
  Linux cold start as local `PACKAGING_PASS` evidence.
- Exact identities:
  - candidate `7b34c6c88f5ee88db823cd7d98409ddd06d0f9e4ebe8f5259bc7afe0104fd7f1`;
  - notebook `d3d7e51774c2c2e0f613f0a47b20359190af8d0f31a6b4ff5a0963fe9048e4f0`;
  - payload `726e595523a9b737a3b000b6d4d088a8e9289c1e6fd1da03297b79876311356f`;
  - local Parquet
    `f601196d5298e525e04c22185acb3668c3a9f74c6f371040164169fcc17279c9`.
- Integrity decision: package-only validation may pass while
  `full_competition_integrity_status` remains `NOT_EVALUATED_PUBLIC_IDENTIFIERS`. Do not coerce
  that deliberate authority boundary into a full competition PASS.
- Boundary: safe loopback framework/gateway fixtures, Python-level socket guards, and
  pinned-public Parquet structure do not prove exact Kaggle runtime, gateway, scorer, OS network
  containment, or upload acceptance.

## D-002-0012 — Stop the public run before consumption on missing exact surfaces

- Recorded: 2026-08-24T08:37:44Z.
- Status: accepted; `BLOCKED_EXTERNAL`.
- Decision: do not call the public holdout runner because the frozen production preflight cannot
  validate independently pinned ten-game static assets or exact external framework, gateway,
  scorer, and platform attestations.
- Receipt:
  `aa9906ca2612f9b9130ed19ac6dbe9b2138139613206bcd0f1891e13b6b77301`.
- Authority result: `0/1` runs started; zero scorecard intents, makes, resets, and actions.
- Claim result: all requested public performance fields remain `NOT_MEASURED`; no synthetic,
  fixture, or approximate output is promoted to official RHAE.
- Boundary: the authorization remains unconsumed; this decision does not grant a future run
  outside a later explicit owner instruction.

## D-002-0013 — Preserve source conflicts and apply explicit precedence

- Recorded: 2026-08-24T08:37:44Z.
- Status: accepted.
- Decision: use exact raw Git blobs for repository-file identity and the fresh anonymous raw
  Kaggle response
  `ca6253ca8e87ba6e4e5a435ee5f83bc27aaf62aa564860c1e31390349978de4f`
  for the runtime limit/configuration snapshot.
- Preserve, do not erase:
  - the two conflicting earlier Kaggle response hashes;
  - Windows checkout versus raw-Git line-ending hashes;
  - ARC-AGI 0.9.9's `1.15` score cap versus the Kaggle page's `1.0` cap;
  - public toolkit `0.9.9` versus staff-sample `0.9.6`;
  - starter guidance of five daily submissions versus current metadata of one daily and two
    scored submissions;
  - the Agents loop's inclusive counter versus ARC3's internal deterministic action cap;
  - ACTION7's documented undo meaning versus ARCEngine's generic simple-action type.
- Boundary: any local score remains source-bound and non-official even if later generated.

## D-002-0014 — Preserve Build 001's protected package-only verifier

- Recorded: 2026-08-24T08:37:44Z.
- Status: accepted.
- Decision: exclude only
  `tests/competition/test_run_build002_holdout.py` from Build 001's package-only subprocess test
  selection because that Build 002 test intentionally copies the protected public manifest.
- Reason: the Build 001 verifier must continue proving no semantic public-manifest access. Running
  a Build 002 preflight fixture inside that boundary changes the tested authority surface.
- Repair commit: `0385d238ab85477ce6f995f7182855a7b3473f5d`.
- Boundary: no scanner rule, protected path, Build 001 receipt, or Build 001 claim is weakened or
  reclassified.

## D-002-0015 — Close Build 002 as PARTIAL with an honest external stop

- Recorded: 2026-08-24T08:37:44Z.
- Status: accepted.
- Decision: final Build 002 status is `PARTIAL`, with local implementation/profile/package/cold
  start evidence passing and the exact competition/public-run surface `BLOCKED_EXTERNAL`.
- Measured public result: none.
- Official RHAE: none.
- Build 001: remains `PARTIAL`; its historical holdout status remains `SEALED_UNCONSUMED`.
- Human-gated actions still not performed: terms acceptance, Kaggle token use, upload, official
  submission, merge, release, DOI publication, spending, or external representation.

## D-002-0016 — Repair packaged startup without weakening ordinary CI

- Recorded: 2026-08-24T09:05:27Z.
- Status: accepted and implemented at
  `753b0e007222a973a2c8a6d7ce14a395135d3c5f`.
- Preserved regression: the Build 001 package-only workflow at source `0385d238` failed on both
  operating systems because the packaged startup probe constructed `MyAgent` before configuring
  its tournament governor. On Linux, that protected package-only selection also collected the
  exact pinned Agents integration test, whose POSIX subprocess behavior is outside that guard.
- Decision: conditionally configure the tournament governor in the packaged startup probe before
  constructing `MyAgent`. Exclude only
  `tests/integration/test_pinned_agents_framework.py` on POSIX from Build 001's protected
  package-only guard, with the boundary reason retained in code. Ordinary ARC3 CI continues to
  collect and execute the exact integration test.
- Evidence: local targeted selection `30 passed`; packaged startup passes; Build 002 package and
  cold-start workflow `32708504639` passed. The exact local argv and standalone transcript hash
  were not sealed.
- Boundary: this repairs a verification projection. It does not weaken Build 001's protected
  manifest policy, revise Build 001's `PARTIAL` result, exercise a public environment, or prove
  Kaggle parity.

## D-002-0017 — Supersede the terminal implementation freeze with exact 753b0e0 evidence

- Recorded: 2026-08-24T09:20:26Z.
- Status: accepted; earlier `0385d238` terminal artifacts remain preserved as superseded
  evidence.
- Frozen source:
  - commit `753b0e007222a973a2c8a6d7ce14a395135d3c5f`;
  - tree `d07e72716a1f918ed04a6892adb1e3f46259e345`.
- Decision: bind the current synthetic profile, package, native Linux cold start, and frozen
  preflight to that exact source identity. Do not reuse the earlier hashes as current evidence.
- Current hosted state: Build 002 workflow `32708504639` is green; exact-head ARC3 CI
  `32708504627` and Build 001 package-only CI `32708504623` were still pending at this evidence
  freeze and are not represented as passed.
- Terminal claim: Build 002 remains `PARTIAL`; exact public and official evaluation remains
  `BLOCKED_EXTERNAL`; authorized holdout consumption remains `0/1`; Build 001 remains unchanged
  `PARTIAL` and historically `SEALED_UNCONSUMED`.

## D-002-0018 — Retain replayable artifact paths and require a fresh preflight output

- Recorded: 2026-08-24T09:12:27Z.
- Status: accepted.
- Decision: bind the final launch-free request to the retained
  `artifacts/build002/final-753b0e0` package and flat retained Linux cold-start receipt. A preflight
  output directory is single-use evidence and must be fresh; never delete or overwrite an earlier
  stop merely to obtain a new conclusion.
- Preserved evidence: the temporary A/B-layout request and the corrected-path/non-fresh-output
  `FAILED_PREFLIGHT` receipt remain under the local failed-attempt artifact registry.
- Final receipt: producer SHA-256
  `bb37fa65c0bf470ba54b2e6b82c14c01cafc8045d9697b1ac82893b2a241b189`,
  request SHA-256
  `b842e2cee086ec2833bdd7c3453482f88c8a889b1e474ca992124e8a33033160`.
- Boundary: all attempts were launch-free and pre-consumption. This correction did not create a
  new holdout entitlement, run a game, or revise Build 001.

## D-002-0019 — Close Stage 10 on the frozen implementation tree

- Recorded: 2026-08-24T09:20:26Z.
- Status: accepted.
- Decision: mark Stage 10 `PASS` after ordinary Linux/Windows CI, Build 001 protected package-only
  CI, and Build 002 package/native cold-start CI all passed on the implementation tree
  `d07e72716a1f918ed04a6892adb1e3f46259e345`.
- Source-identity note: the pull-request workflow merge object `e3160891...` has that exact tree;
  package-only jobs explicitly checked out commit `753b0e0`.
- Documentation boundary: the final documentation commit reports the immutable implementation
  freeze but cannot embed its own later SHA or CI result. Verify that final head externally on the
  draft PR without creating a self-referential commit chain.
- Overall result remains `PARTIAL`: Stage 10 success cannot manufacture the missing exact external
  surface or an RHAE measurement.
