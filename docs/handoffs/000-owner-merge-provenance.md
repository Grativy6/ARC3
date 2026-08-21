# Build 000 — owner merge provenance

Status: **OWNER ACTION RECORDED**  
Recorded: 2026-08-21  
Repository: `Grativy6/ARC3`

## What happened

Build 000's autonomous handoff ended with PR #3 intentionally left draft and unmerged because merging remained a human gate.

After reviewing the Build 000 result, **Christopher D. Pang explicitly chose to merge PR #3** so Build 000 would become the canonical `main` base for the next build. The merge was therefore an owner action performed after the autonomous run stopped at its authority boundary; it was **not** an autonomous Codex merge and was **not** a violation of the Build 000 execution contract.

## Exact Git identities

- Build 000 branch: `build/000-arc3-end-to-end`
- Build 000 final branch tip: `ee4938b4fdba8bcea9fa3660d32d7b9597644896`
- Build 000 PR: #3 — `https://github.com/Grativy6/ARC3/pull/3`
- Owner merge time recorded by GitHub: `2026-08-21T14:34:05Z`
- Resulting merge commit on `main`: `cf321c3e0e1aa782076491ee84015d24d0fe28ce`

## Interpretation rule

Any Build 000 artifact saying that PR #3 "must remain draft and unmerged until Christopher D. Pang decides otherwise" describes the state **before the owner decision**. It is not evidence that the later merge was unauthorized.

For Build 001 and later work, treat `cf321c3e0e1aa782076491ee84015d24d0fe28ce` as the owner-approved canonical Build 000 merge base unless a later owner action supersedes it.

Christopher D. Pang remains author and steward. AI systems acted as development tools and assistants; they did not make the merge decision.