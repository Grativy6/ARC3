# Build 001 Stage 14 — Final verification and publication seal

## Result

**Stage status:** `PASS`

**Overall build status:** `BUILD 001: PARTIAL`

**Evidence label:** `synthetic`

**Claim:** `FINAL_REPRODUCIBILITY_AND_PUBLICATION_SURFACES_VERIFIED`

The final report, publication draft, review packet, owner handoff, result tables, figure, evidence
index, and verification receipt are complete. This stage verifies reproducibility and reporting;
it does not create a gameplay result or revise any failed mechanism.

## Frozen source identity

- canonical `main`: `28c7a00732ce48e5c231211b01bc6eba7d0d71b4`, tree
  `4586299448e9b1b585a0878674ed5f9afa60c384`;
- production policy: `d6d4bac1e33c9837856c08abcee61bcb14afd34e`, tree
  `dd8e82e4b34337a208110929e3f5f8079d1e0a18`;
- package/code/test freeze: `9f25e13b4672ff0ea87544ba20c5677f194cf291`, tree
  `d7fc05c9dff0f63cc97e7b752e1fe59ff7583900`;
- Stage 13 checkpoint: `6e6899693acc35c1b48012ed7f82cdd6eaffdc52`, tree
  `9348aaba717e1e11a3deb4c2660d43048f69d327`.

The diff after `9f25e13…` changes no `agent/`, `src/`, `scripts/`, `tests/`, workflow, package,
lock, license, notice, or upstream-lock file. The final descendant is limited to `README.md` and
`docs/**`. A commit cannot embed its own SHA without changing it; the final pushed tip and draft-PR
head are therefore checked externally after the documentation commit.

## Independent clean clone

The detached clone at `C:/a/arc3-b001-stage14-9f25e13` is clean at the exact package/code/test
freeze. Its isolated environment uses CPython 3.12.14 and uv 0.12.5. CPU execution was used on the
Windows 10 AMD64 host.

| Check | Exact result |
|---|---|
| offline frozen sync | 61 locked packages checked in 176 ms |
| offline lock check | 61 packages resolved in 2 ms |
| Ruff lint | PASS |
| Ruff format | 313 files already formatted |
| strict mypy | 179 source files, no issues |
| full pytest | 1,322 passed, 17 platform skips, 80% total coverage, 2,077.70 s |
| replay/property pytest | 45 passed, 34.03 s |
| runtime doctor | all required checks PASS; optional `agents` framework absent |

Coverage emitted nonfatal warnings for removed transient package-startup source paths. Pytest and
the reported 80% total coverage completed successfully. An initial bare `uv lock` invocation
failed because `uv` was absent from `PATH`; the public pinned `uv==0.12.5` tool was installed in an
isolated external environment and the exact-path retry passed. Both command outcomes are preserved
in the machine receipt.

## Hosted cross-platform verification

At exact source `9f25e13…`, ordinary CI passed lint, formatting, strict typing, full tests, and
doctor for push run `32636996144` and draft-PR run `32636997705`:

| Event/platform | Job | Tests | Coverage | Pytest seconds |
|---|---:|---:|---:|---:|
| push / Ubuntu | 97188148681 | 1,329 passed; 10 skipped | 80% | 1,024.61 |
| push / Windows | 97188148803 | 1,323 passed; 16 skipped | 80% | 1,836.93 |
| draft PR / Ubuntu | 97188153034 | 1,329 passed; 10 skipped | 80% | 1,047.62 |
| draft PR / Windows | 97188153231 | 1,323 passed; 16 skipped | 80% | 1,573.22 |

Package runs `32636996137` and `32636997645` also passed on Ubuntu and Windows. GitHub's Node 20
forced-to-24 deprecation annotation is preserved as upstream workflow maintenance; it did not fail
a required step.

## Package and integrity

All eight exact-source hosted A/B candidates are byte-identical at 788,070 bytes and SHA-256
`02326a145d510c017dc04ffd79a61cfe8c46771cbc9e74b7c8f29a9b75756d21`. The complete 48-file
Windows-hosted receipt root is
`C:/a/arc3-b001/artifacts/stage13/final-package-9f25e13-exact`, 4,263,775 bytes, with file-record
manifest SHA-256 `2aca4b7e6f1430b33444459470850b05947fedef2c0bfed34d0eb07a69d03295`.
The canonical release-receipt validator returns the expected `BLOCKED_EXTERNAL` terminal: 20
available checks pass, and only `private-kaggle-surfaces` is unavailable.

The package and production static scans report zero secrets, known public-game IDs, obvious
game-specific solution tables, and hosted-model runtime dependencies. Git integrity passes with
only unreferenced dangling objects. MIT-0 owner authorization and third-party notices remain
intact. Python audit hooks and static scans are explicitly not complete OS/native containment or
trusted execution.

## Reporting and evidence validation

- required JSON documents parse;
- all three CSV tables parse with their declared rows and columns;
- the SVG stage figure parses as XML and was rendered for visual inspection;
- relative Markdown links resolve;
- referenced source/evidence commit objects exist;
- recorded Stage 00–13 acceptance paths and SHA-256 values verify;
- the final machine index binds Stage 00–14 dispositions and publication artifacts;
- no unsupported positive recovery, reopening, holdout, RHAE, private, AGI, consciousness, PAL,
  or general-theory claim appears.

## Holdout and human gates

The ten-game public holdout remains `SEALED_UNCONSUMED`: no identities were loaded, no manifest was
parsed, no adapter was loaded, no gameplay was opened, and zero environment actions occurred.
No terms were accepted; no official submission, merge, release, DOI, paid compute, owner
communication, credential transfer, or secret disclosure occurred.

Stage 14 PASS means the achievable verification/reporting work is complete. Build 001 remains
`PARTIAL`, Stage 06 remains `FAILED_MECHANISM`, Stages 07–10 retain their exact infrastructure
failures, and Stage 13 remains `BLOCKED_EXTERNAL`.
