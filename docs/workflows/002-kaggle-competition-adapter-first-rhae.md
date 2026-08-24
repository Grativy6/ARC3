# Workflow 002 — Kaggle competition adapter and first honest RHAE

**Status:** terminal `PARTIAL`; all achievable local stages completed, with frozen public and
official evaluation `BLOCKED_EXTERNAL`
**Implementation branch:** `build/002-kaggle-competition-adapter`
**Base:** exact merged `origin/main` at
`a1931c673b90923e1af78127229667544802a096`
**Owner, author, and steward:** Christopher D. Pang

This workflow adds a bounded Kaggle execution surface without deleting or weakening ARC3's
persistent research system. AI systems are development tools and assistants, not co-authors,
owners, or independent authorities.

## Frozen claim and authority boundaries

- Build 001 remains `PARTIAL`. Its ten-game public holdout record remains
  `SEALED_UNCONSUMED`; no Build 002 observation may revise that historical conclusion.
- For Build 002 only, the owner has authorized exactly one run over that ten-game public set,
  and only after every offline, source-identity, packaging, competition-mode, notebook, and
  structural-output preflight below passes.
- Authorization is not consumption. Until the one-shot runner durably records intent immediately
  before opening its first and only upstream scorecard, Build 002 records
  `AUTHORIZED_ONCE_NOT_YET_CONSUMED`.
- Once started, the run is consumed even if it fails, crashes, times out, or returns zero score.
  It must not be retried, resumed as a second run, or silently replaced.
- Any score from the public toolkit/local public games is `local-public`. It is not Kaggle-public,
  semi-private, official-private, or official RHAE unless the corresponding official evaluator
  actually returns it.
- Exact private Kaggle wheels, framework input, gateway, scorer, and accepted-terms execution are
  outside current authority. Their absence is `BLOCKED_EXTERNAL`, not a reason to manufacture a
  compatibility or scoring claim.
- No terms acceptance, Kaggle credential use, upload, submission, paid service, merge, release,
  DOI, external representation, or secret disclosure is authorized.

## Controlling sources

Current official ARC-AGI-3 documentation, `arcprize/ARC-AGI`,
`arcprize/ARC-AGI-3-Agents`, `arcprize/ARC-AGI-3-Kaggle-Starter`, ARCEngine, and the current
competition-specific Kaggle metadata control this workflow. Exact identities and unresolved
discrepancies are recorded in `docs/evidence/002-00-official-source-identities.json`.

When sources disagree:

1. competition-specific current Kaggle constraints control generic Kaggle limits;
2. executable pinned behavior controls local execution, with the conflict retained;
3. a returned official score controls only that official surface;
4. unresolved private-surface compatibility fails closed;
5. no source discrepancy may be erased after a later successful run.

The current competition metadata reports a nine-hour CPU/GPU limit. That narrower limit controls
the generic twelve-hour notebook ceiling. The competition governor must reserve safely below nine
hours; merely remaining below twelve hours is insufficient.

## Atomic stages

### Stage 00 — Repository, source, and authority preflight

Acceptance requires:

- all remotes fetched and pruned;
- Build 001 final commit `8a42e43c96ac1edada21725746cdedcee24e68f9` verified ancestral to the exact current merged
  `origin/main`;
- a clean Build 002 branch from that exact `origin/main`, without rewritten history;
- Build 000/001 evidence treated as immutable;
- official repositories, packages, relevant source files, and current competition metadata bound
  by exact commit/tree/blob/file or response hashes;
- every material source discrepancy and unavailable private surface recorded.

Terminal state: `PASS` on available public sources. The exact base, Build 001 ancestry, repository
pins, raw file identities, refreshed Kaggle metadata, project lock, and permanent source
discrepancies are sealed in Build 002 evidence. Exact private Kaggle surfaces remain separately
`BLOCKED_EXTERNAL`.

### Stage 01 — Execution-mode separation

Implement explicit `RESEARCH_UNBOUNDED` and `COMPETITION_BOUNDED` modes. Acceptance requires the
research defaults and generic opaque-action mechanism to remain unchanged, while competition mode
is explicit, receipt-bound, deterministic, and rejected on incompatible environment modes.

### Stage 02 — Official agent adapter and granted interface semantics

Integrate the existing corpus and controller behind exact `MyAgent.is_done()` and
`MyAgent.choose_action()` entry points. In competition mode only, grant the documented meanings of
`ACTION1` through `ACTION4` and `ACTION7`; keep `ACTION5` and coordinate-dependent `ACTION6`
evidence-driven. Prove research mode still learns opaque action handles generically.

### Stage 03 — Global tournament governor and lifecycle

Implement a process-global governor with:

- a protected reserve below the controlling nine-hour competition limit;
- dynamic per-environment allocation from remaining runtime and environments;
- legal-action filtering;
- bounded deterministic fallback;
- action-value and opportunity-cost accounting;
- stable stop reasons and failure receipts;
- sequential lifecycle enforcement.

Acceptance also requires one scorecard, every supplied environment included, exactly one `make`
interaction per environment, level-only resets, no game resets, no illegal post-game action, and
deterministic behavior under a supplied seed.

### Stage 04 — Competition-only hot-path policy

In `COMPETITION_BOUNDED` only, disable allocator tracing and automatic per-action whole-state
checkpoint serialization. Retain compact in-memory trace, sparse recovery checkpoints,
deterministic replay, and failure receipts. This change is grounded only in Build 001's matched
performance evidence: allocator tracing off reduced wall time by 80.801 percent and automatic
checkpointing off reduced wall time by 17.538 percent while preserving exact actions and outcomes.
No research default changes.

### Stage 05 — Offline package and cold start

Build a self-contained candidate containing every required first-party module, dependency, model,
corpus asset, configuration, and applicable license notice. Verify at minimum:

- Python and official toolkit version compatibility;
- exact dependency and payload manifests;
- offline installation/import from the packaged wheelhouse or equivalent sealed payload;
- deterministic cold startup through the same entry point used by the notebook;
- runtime and peak-memory bounds;
- notebook/archive size;
- zero bundled credentials or secrets;
- zero evaluation-time internet requirement;
- complete source, configuration, package, and artifact hashes.

A host-site-packages injection, canned output, approximate framework fixture, or static import
scan alone cannot satisfy the cold-start gate.

### Stage 06 — Notebook and `submission.parquet` validation

Generate the Kaggle notebook from the frozen package, execute its local offline entry point, and
validate its generated `submission.parquet` structurally. Validate schema, columns, row identity,
types, uniqueness, completeness, readable Parquet encoding, deterministic regeneration, and
absence of credential/network requirements. No upload or submission is permitted.

Structural validity is not exact private scorer parity. Any unavailable private schema behavior
remains `BLOCKED_EXTERNAL`.

### Stage 07 — Frozen one-shot preflight

Freeze the exact source commit/tree, runtime configuration, dependency lock, package, notebook,
corpus, public partition, seeds, action/runtime/memory budgets, environment ordering, and output
roots. Re-run all source-identity, offline, packaging, competition-integrity, lifecycle, replay,
secret, and output-structure checks against that freeze.

The holdout gate is `OPEN_ONCE` only if every available predicate passes and every exact identity
matches the freeze. Any failure leaves the authorization unspent. The exact private surface may
remain separately `BLOCKED_EXTERNAL`, but no result may be labeled official.

### Stage 08 — Authorized ten-game public run

Execute the frozen public set exactly once. The consumption boundary is a durable intent marker
immediately before the first and only upstream scorecard open. Persist the launch receipt before
that boundary, and persist each environment `make` intent separately before its upstream call.
From the scorecard-open boundary onward, interruption is a consumed failed attempt, not authority
for a rerun; a pre-`make` failure still reports zero environment interactions.

The result must include every environment, including zero/failure rows for environments that
receive only bounded fallback. Capture total local-toolkit RHAE, completed games and levels,
per-game/per-level scores, agent actions and human baselines, wall time, peak memory, budget
allocation, reserve, stop reasons, failures by required taxonomy, and exact hashes.

### Stage 09 — Result seal and failure analysis

Independently verify the complete scorecard/trace/artifact graph. Classify each failure as exactly
one primary category among perception, goal inference, rule learning, planning, execution,
platform, or budget exhaustion, while retaining any secondary evidence. Preserve failed attempts
and superseded evidence. Do not turn local-public output into an official claim.

### Stage 10 — Final verification and handoff

Run repository tests, Ruff, formatting, strict mypy, replay/property checks, lifecycle and package
checks, offline cold start, secret and competition-integrity scans, artifact/hash verification,
Git integrity, and clean-clone validation. Commit and push the Build 002 branch, open or update a
draft PR, and prepare the final report and owner handoff. Do not merge or submit.

## Terminal stage disposition

| Stage | Status | Terminal evidence |
|---|---|---|
| 00 | `PASS` | exact base, ancestry, public source pins, metadata, and locks |
| 01 | `PASS` | research and bounded competition modes separated |
| 02 | `PASS` | official agent surface and granted-action boundary implemented |
| 03 | `PASS` | governor and lifecycle locally verified |
| 04 | `PASS` | competition hot-path policy verified; research defaults retained |
| 05 | `PASS` | clean package and native Linux exact-requirement cold start passed |
| 06 | `PASS` | notebook and pinned-public Parquet structure passed |
| 07 | `BLOCKED_EXTERNAL` | frozen preflight stopped before arming |
| 08 | `BLOCKED_EXTERNAL` | authorized run not started; `0/1` consumed |
| 09 | `PASS` | pre-consumption blocked disposition sealed; no result promoted |
| 10 | `PASS` | exact-head checks, pushed branch, draft PR, report, and handoff complete |

Build 002 closes as `PARTIAL`. `BLOCKED_EXTERNAL` is the honest terminal result for the unavailable
public/official evaluation surfaces. Build 001 remains immutable `PARTIAL`.

## Persistent-run protocol

After each atomic task:

1. run the smallest relevant verification;
2. append the exact invocation and result to `docs/ledger/build-002-VALIDATION.md`;
3. update `docs/ledger/build-002-run-state.json` atomically;
4. append material decisions to `docs/ledger/build-002-DECISIONS.md`;
5. append unresolved failures, source conflicts, and superseded evidence to
   `docs/ledger/build-002-OPEN-BURDENS.md`;
6. commit a coherent checkpoint and push when credentials/network permit.

No unresolved burden is deleted. A later repair marks it resolved and points to the repair while
retaining the original observation.

## Completion states

Each stage ends as `PASS`, `PARTIAL`, `BLOCKED_EXTERNAL`, `FAILED_MECHANISM`, or
`FAILED_INFRASTRUCTURE`. `PENDING` and `IN_PROGRESS` are run-state markers, not terminal evidence
claims.

Build 002 is complete only after all achievable stages are terminal, the implementation and exact
adapter are pushed, the draft PR is current, the one-shot run is sealed or honestly blocked, the
notebook and `submission.parquet` validate locally, and the handoff separates measured results,
open burdens, and owner-only actions.

## Terminal freeze addendum — 753b0e0

Recorded 2026-08-24T09:20:26Z. This append-only addendum supersedes the current-artifact identity
in the earlier terminal table without deleting the `0385d238` evidence or its failures.

- Frozen implementation: commit `753b0e007222a973a2c8a6d7ce14a395135d3c5f`, tree
  `d07e72716a1f918ed04a6892adb1e3f46259e345`.
- Synthetic profile: file
  `ed2d4c336017551cb4b99e3fc2bc71eedf66b87683811d0d4a00056e0f84fb15`, producer receipt
  `3f03b17ed639a6e7c6762254a1cba9fdfabb45aaa6ac42f9eb72e7f7b0048714`,
  `39.6246924s` wall, `321,466,368`-byte peak RSS, and
  `3.3508976999946753s` maximum production controller cycle.
- Package: candidate
  `adcd92352f55a0109c0898fe14b531e8780f02dc9b68489af449c1b8b8c16d9a`
  (`838,438` bytes), notebook
  `adbb75d09806da104a5d3bfbe41e55d809ec2bb91514aafa6176c2469f30c81e`
  (`548,193` bytes), payload
  `726e595523a9b737a3b000b6d4d088a8e9289c1e6fd1da03297b79876311356f`, manifest
  `29f5b430ff3be418bd8c4922939aa9134f823864983abf320601e1a46ca89388`, and SBOM
  `e1d4836e974f22cf8821ddc46909edc1bce0ed2146a9ad4116550d11a130d0ed`.
- Package receipts: serialized build
  `be23ee24c614229b2f940c112fb916f12b63cbdc700c8bcafc1569024d008bc5`, build producer
  `8afaf2f16cf9f4a7c7825718b14427b5afdcb239d877523d22e70f617ed46358`, serialized integrity
  `9287f22b9a6d63cd8dd3540661f28b2115e9935488d24c38aeb58767c7ad1b3b`, and integrity producer
  `42aa847bc4443f100be9163b9bb9746ed30dc1e5d79692d20d7d1cfbc43da588`.
- Native Linux cold start: workflow `32708504639` passed; receipt file
  `d04dcef55e36a9ee32a6f4153d89efc6b61560962b9931b031a70632a4ff4ecc`,
  `12.728529202s` wall, `132,288,512`-byte peak memory, and zero public interactions.
- Frozen preflight: serialized source artifact
  `15d748c6954705cabdfc37d0f993ec3e5d352558fb0741d7bd7cbd472e24e82e`, producer receipt
  `bb37fa65c0bf470ba54b2e6b82c14c01cafc8045d9697b1ac82893b2a241b189`, request
  `b842e2cee086ec2833bdd7c3453482f88c8a889b1e474ca992124e8a33033160`, and hashed error
  `ba7ce61033f638929402dad230d898e52fb6ddbdf1471b4951fe49c525e8bd86`.
  It stopped before arming, scorecard open, make, reset, or action; authority remains `0/1`.
- Preserved second `0385d238` regression: packaged `MyAgent` startup lacked tournament
  configuration on both operating systems, and the Linux protected package-only selector also
  collected the exact POSIX Agents integration. Commit `753b0e0` repairs the startup and excludes
  only that integration from the protected guard; ordinary CI retains it. Local targeted result:
  `30 passed`; package startup passes. The exact local invocation and standalone transcript hash
  were not sealed.
- Hosted state at this freeze: Build 002 workflow `32708504639` is `PASS`; ARC3 CI
  `32708504627` and Build 001 package-only CI `32708504623` are `PENDING`. Therefore the earlier
  Stage 10 `PASS` row is superseded for the exact `753b0e0` head by `IN_PROGRESS` until both final
  hosted conclusions are bound. Pending is not green.

### Terminal hosted conclusion

Recorded 2026-08-24T09:20:26Z: ARC3 CI `32708504627` and Build 001 package-only CI
`32708504623` both completed `PASS`; Build 002 package/cold-start CI `32708504639` was already
`PASS`. The PR merge object `e3160891...` has the exact implementation tree `d07e7271...`.
Stage 10 is therefore terminal `PASS` at the implementation freeze. The overall Build 002 status
remains `PARTIAL`, with Stages 07 and 08 `BLOCKED_EXTERNAL`, no public result, and holdout authority
unconsumed at `0/1`.

Build 002 remains `PARTIAL`; the exact public/official surface remains `BLOCKED_EXTERNAL`; no RHAE
or public gameplay metric was measured. Build 001 remains unchanged `PARTIAL` and historically
`SEALED_UNCONSUMED`.
