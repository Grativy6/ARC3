# Build 001 Stage 00 — preflight, identity, and owner gates

Status: **PASS**

Evidence label: **synthetic** (engineering/source-identity acceptance only)

Completed: `2026-08-22T03:11:34Z`

## Result

Build 001 is based on exact current `main`
`28c7a00732ce48e5c231211b01bc6eba7d0d71b4` (tree
`4586299448e9b1b585a0878674ed5f9afa60c384`) on
`build/001-local-public-recovery`. The active and remote `main` identities remained equal after
fetch. No implementation work occurred on `main`.

The owner explicitly authorized MIT-0 for ARC3 first-party source. Root `LICENSE` is operative,
has SHA-256 `7f433e520d07d56ad14d92e9da9f580771479c30a2bfccc8024eed308f21bbe8`,
and exactly equals the candidate body after excluding its nonoperative boundary text. Package
metadata, the SBOM, candidate validation, integrity inventory, notices, and tests now fail closed
on that exact identity. Third-party licenses were not changed.

The ten-game public holdout remains sealed and unconsumed. Only manifest and exposure metadata
were read: the exposure ledger still has 330 events, zero holdout events, and no local holdout asset
directory. No holdout episode, observation, recording, or source was opened.

## Build 000 and owner provenance

- Build 000 PR #3 was merged by the non-bot owner account `Grativy6` at
  `2026-08-21T14:34:05Z`; merge commit `cf321c3e0e1aa782076491ee84015d24d0fe28ce`.
- Workflow PR #4 was likewise an owner action before this run; merge commit
  `28c7a00732ce48e5c231211b01bc6eba7d0d71b4`.
- Codex did not perform either merge and will not merge the Build 001 draft PR.
- At the exact base before active license metadata changed, all 48 Build 000 artifact-path hashes
  and all 22 referenced commit objects validated. All 25 checked evidence/identity JSON files
  parsed, and the public partition assignment recomputed 25/25.
- Build 000 reports, evidence JSON, research report, handoff, and `docs/ledger/run-state.json`
  remain unchanged. Active root metadata evolves in Build 001; frozen content remains recoverable
  from the Build 000 seal `ee4938b4fdba8bcea9fa3660d32d7b9597644896`.

## Source refresh and drift

Five upstream repository heads, `arc-agi==0.9.9`, `arcengine==0.9.3`, and all eight static ARC docs
remained byte-identical to `upstream.lock.json`. Two dynamic organizer pages did drift, stably across
three fetches each:

| Surface | Frozen SHA-256 | Current SHA-256 | Bytes |
|---|---|---|---:|
| ARC-AGI-3 competition page | `06ba7dde82da5b9d8bd370646727f036ce3a7bba62e2d2af3c3ffa53952eeaf2` | `00de512939d11d2aafe824800efdedb8c0331d7a63c6e9be85a4b7a8aa85db36` | 44,439 |
| ARC Prize 2026 general page | `59061f6142b7a59bedfba9227cb15d22068566d94437f7ce800a37b10fdbcd33` | `f0bc5b1f363038912c1440462603d61efb3f470366139a993b9cddaa1311a874` | 47,176 |

The executable/static pins were retained. The dynamic-body difference is an open burden; it was
not silently interpreted as an executable upgrade or as legal acceptance.

## Machine identity

- Windows 10 Home `10.0.19045`, x86-64;
- AMD Ryzen 5 2600, 6 physical/12 logical cores;
- 17,124,503,552 bytes visible RAM;
- NVIDIA GeForce GTX 1660, 6,144 MiB, driver 560.94 (CPU remains selected);
- CPython 3.12.14 project runtime; uv 0.12.5; Git 2.54.0.windows.1;
- Windows system clock in America/New_York; the Windows Time service was stopped, recorded as an
  infrastructure limitation rather than a synchronized-clock claim;
- public network reachable; ARC/Kaggle credentials absent; no `.env`; no terms accepted.

## Verification and preserved failures

The narrow current checks passed: uv lock (61 records), Ruff lint/format (29 files), mypy strict
(19 source files), focused pytest (35/35), offline sdist/wheel build, integrity/secret scan (zero
findings), `git fsck`, `git diff --check`, and holdout nonconsumption.

Three environment attempts failed before the isolated path was established: OneDrive denied
replacement of the workspace distribution metadata, the first short-path sync hit Windows cloud
hardlink error 396, and the first pytest run hit an ACL-denied default temp root (10 tests passed,
23 setup errors). The exact retry used `C:\a\arc3-b001-28c7a00`, uv copy mode, and an explicit
`--basetemp`; it passed. These are preserved as resolved infrastructure failures, not relabeled as
mechanism success or failure.

## Acceptance mapping

- exact branch/base: **PASS**;
- owner merge provenance: **PASS**;
- Build 000 historical evidence unchanged: **PASS**;
- independent Build 001 ledgers: **PASS**;
- owner-authorized license state: **PASS**;
- holdout sealed/unconsumed: **PASS**;
- source and machine identities: **PASS**, with dynamic-page drift recorded;
- secret and Git integrity checks: **PASS**.

Compact machine-readable evidence is
`docs/evidence/001-00-preflight-acceptance.json`.

No gameplay, completion, score, RHAE, hidden-game generalization, AGI, PAL, or consciousness claim
is made by this stage.
