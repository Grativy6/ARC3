# ARC3 Build 001 decisions

Append-only record for material Build 001 engineering and evidence decisions. Christopher D. Pang
is the author and steward; AI systems prepare implementation evidence and are not co-authors or
independent authorities.

## D-001-0001 — Base Build 001 on the exact current main

- Recorded: 2026-08-21T15:41:02Z
- Status: accepted
- Decision: Create `build/001-local-public-recovery` from exact current `main`
  `28c7a00732ce48e5c231211b01bc6eba7d0d71b4` and perform no implementation work on `main`.
- Evidence: Git identity and merge ancestry in the Stage 00 receipt/report.
- Boundary: the current main merge was an owner-created PR #4 merge before this run; Codex did not
  merge it and will not merge the Build 001 PR.

## D-001-0002 — Apply the explicit MIT-0 owner decision

- Recorded: 2026-08-21T15:41:02Z
- Status: accepted
- Decision: Install the candidate MIT-0 text as the operative root `LICENSE` for ARC3 first-party
  source and update active first-party metadata while retaining candidate and Build 000 provenance.
- Authority: active owner instruction states, “I approve MIT-0 for ARC3 first-party source.”
- Boundary: third-party licenses remain unchanged; this does not accept terms, submit, merge, or
  publish a release.

## D-001-0003 — Retain frozen executable pins while recording organizer-page drift

- Recorded: 2026-08-22T03:08:38Z
- Status: accepted
- Decision: Keep Build 000's pinned `arc-agi==0.9.9`, `arcengine==0.9.3`, repository commits, and
  static documentation hashes because the Stage 00 refresh found those executable and static
  identities unchanged. Record, but do not silently adopt, drift in both dynamic organizer pages:
  ARC-AGI-3 `06ba7dde…` → `00de5129…` and general 2026 `59061f61…` → `f0bc5b1f…`.
- Evidence: Stage 00 source-identity receipt.
- Reopening condition: a later measured compatibility failure or upstream identity change.

## D-001-0004 — Keep the ten-game public holdout sealed

- Recorded: 2026-08-21T15:41:02Z
- Status: accepted
- Decision: Read only manifest/exposure metadata until the Stage 11 gate is earned; do not acquire,
  open, inspect, or run a holdout game episode.
- Evidence: manifest hash, 330-event exposure-ledger hash, zero holdout events, and zero local
  holdout asset directories in the Stage 00 receipt.
