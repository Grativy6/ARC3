# Stage 02 — Official SDK and baseline loop

- **Stage status:** PASS
- **Measured surfaces:** synthetic; local-public
- **Measured at:** 2026-08-21
- **Pinned toolkit:** `arc-agi==0.9.9`, `arcengine==0.9.3`
- **Repository base during measurement:** `e91a1bb50e67fe3ad6b1636345a120613eb640e3` with the Stage 02 files uncommitted and individually content-hashed
- **Primary evidence:** `docs/evidence/002-baseline-scorecards.json`
- **Public partition manifest:** `docs/evaluation/public-game-partitions.v0.1.json`

## Result

The complete first-party discovery → observation → policy → validated action → returned
consequence → scorecard path now runs through both a deterministic synthetic adapter and the
pinned official SDK. SDK objects do not cross the adapter boundary. Frames are explicitly
deep-copied because the pinned SDK's private `frame` attribute is omitted by Pydantic
serialization.

The strongest measured Stage 02 score is deliberately modest:

- **synthetic:** random-valid baseline, seeds `0,1,2,3`, 100-action budget, mean score `0.5`
  (2/4 completed; per-run actions `12,100,100,83`);
- **local-public:** deterministic cycle, `ls20-9607627b`, seed 7, 20-action budget,
  official local score `0.0`, 0 levels completed, 20 actions, 0 resets, state
  `NOT_FINISHED`.

The synthetic result proves only deterministic plumbing on a small first-party environment. It
is not evidence of public-game performance or hidden-game generalization. The public baseline
is exactly zero and is not relabeled.

## Adapter contract

The adapter exposes immutable first-party descriptors, frames, observations, action requests,
and credential-free score summaries. It:

- lazily verifies exact installed SDK versions;
- uses constructor-provided `observation_space` rather than issuing an unnecessary second reset;
- explicitly extracts and copies every raw frame;
- validates the current advertised action set before calling upstream;
- requires exact integer `ACTION6` coordinates in `0..63` and forbids coordinate data for all
  other actions;
- permits only `RESET` after `GAME_OVER` and stops at `WIN`;
- normalizes unknown SDK states/actions as typed errors rather than guessing;
- suppresses the SDK's credential-adjacent loggers and sanitizes upstream exception text;
- rejects an inherited `OPERATION_MODE` that conflicts with the first-party mode;
- permits competition adapter construction only for an explicit loopback endpoint;
- never requires a hosted inference service.

The production policy paths contain no known public game ID and no game-specific solution
table. The public game name appears only in the partition/evidence/report surfaces and in the
explicit development command.

## Deterministic baselines

- **random-valid:** seed-local PRNG, restricted to advertised non-reset actions;
- **cycle:** fixed vocabulary order while skipping unavailable actions;
- **coordinate sweep:** fixed coarse `ACTION6` lattice, only when the action is advertised.

The bounded runner counts environment actions separately from resets, records before/after
frame identities and states for each submission, and passes only a typed `baseline` rationale
category plus a concise summary. It does not record hidden chain-of-thought.

CLI receipts are available through:

```text
arc3 games list --mode synthetic --seed 7
arc3 games list --mode local --environments-dir <cache>
arc3 play --mode local --agent cycle --game <resolved-id> --seed 7 --max-actions 20
arc3 evaluate --agent random --partition smoke --seeds 0,1,2,3 --max-actions 100
```

## Executable upstream probes

The pinned SDK was probed before implementation and then exercised through the new adapter.
Material observations retained as engineering evidence:

- anonymous discovery returned 25 current public descriptors;
- explicit `OFFLINE` construction made no session and could use one cached environment;
- `NORMAL`, `ONLINE`, and SDK `COMPETITION` may acquire anonymous credentials and perform
  network calls; SDK competition mode is not an offline guarantee;
- inherited `OPERATION_MODE=competition` can override an explicit offline constructor argument;
- upstream action models accept missing/extra/coerced coordinate values in cases ARC3 rejects;
- upstream accepts an action absent from `available_actions`;
- `GAME_OVER` may retain a stale action list and accept a non-reset no-op;
- `make()` automatically resets and may return `None` or a wrapper with no initial observation;
- upstream local JSONL recordings are neither hash-linked nor sealed;
- the anonymous-key path can log the key at INFO if a caller does not inject a logger.

These are compatibility observations, not accusations and not benchmark results. ARC3 tests the
stricter first-party behavior instead of silently inheriting the permissive paths.

## Verification

```text
Ruff check / format (Stage 02 paths): PASS
strict mypy (7 Stage 02 source files): PASS
focused pytest with coverage: 27 passed in 1.40s
official adapter cached local smoke: PASS
production public-ID scan: 0 matches
hosted-inference import/call scan: 0 functional matches
JSON evidence/partition validation: PASS
```

The 27 tests include SDK model normalization and frame deep-copy, unknown IDs, strict action
membership and coordinates, backend-not-called failures, terminal lifecycle, discovery copying
and sorting, environment-mode override rejection before construction, offline no-network
construction, sentinel credential suppression, sanitized errors, deterministic random/cycle/
sweep policies, reset/action budgets, synthetic scorecards, and CLI repeatability.

### Remote CI integration fault

Initial Stage 02 Actions runs `32451110070` and `32451112828` passed sync, Ruff, formatting,
and strict mypy on both operating systems, then failed the full test suite: the Stage 01 doctor
test still asserted that `arc3 evaluate` was a reserved future command after Stage 02 had
implemented it. The test was corrected to exercise the still-reserved `arc3 compare` command.
This is preserved as an integration-test maintenance failure; the correcting CI receipt is
recorded in Actions runs `32451273583` and `32451275935`, where both Ubuntu and Windows jobs
passed.

## Public partition integrity

The 25 discovered names were partitioned by a committed salt and full SHA-256 ordering: three
smoke, eleven original development, and eleven original holdout games. `ls20` had already been
opened for the SDK contract probe before the manifest existed; its original hash assignment was
public holdout, so the manifest visibly overrides it to development. The resulting counts are
3 smoke, 12 development, and 10 public holdout. This prevents later treatment of an exposed
game as unseen. Discovery metadata alone is not gameplay exposure for the remaining games.

## Preserved limits

- The local public environment source executed inside the official toolkit but was not opened or
  semantically inspected; the policy never read it, and developer tooling only computed its
  content hash.
- The Stage 02 CLI did not yet emit exact start/end timestamps, so those fields are `null` with an
  explanation in the evidence file. Stage 03/13 event and evaluation envelopes close that gap.
- Anonymous public access works today; authenticated online/Kaggle/private surfaces remain
  external and unmeasured.
- A score of zero is expected for a generic cycle and provides no evidence against the later
  mechanisms by itself.
