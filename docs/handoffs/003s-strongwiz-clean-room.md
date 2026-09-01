# Experiment 003s handoff — Strongwiz clean-room benchmark

Status: **FAILED_INFRASTRUCTURE — ONE-SHOT CLOSED, NO RERUN**

The frozen Codex-operated Strongwiz bridge opened its one authorized measured public-development
session and stopped before the first environment action. The PTY response transport truncated a
2,169-byte newline-terminated operator message, causing strict JSON rejection. An isolated dummy
`readline()` reproduction received 511 characters from a 2,170-byte line through the same tool path.

Authoritative game receipt:

- game: `ls20-9607627b`;
- final state: `NOT_FINISHED`;
- levels completed: 0 of 7;
- actions/resets: 0/0;
- measured wall time: 81.25 seconds;
- completion genuinely observed: no;
- run ID: `strongwiz-ls20-seed0-20260901T100522Z`;
- result internal hash:
  `sha256:3f25e959ef5f7d54fa486f6022f78311e80bcfc825ee1c551f4f5a182a4ec68c`;
- tracked result: `docs/results/003s-strongwiz-clean-room.md`;
- tracked machine receipt: `docs/evidence/strongwiz-clean-room-result.v0.1.json`.

No Hearthline repository/runtime, holdout, submission, credentials, terms acceptance, purchase,
merge, or second measured session was used. The branch must remain unmerged unless Christopher D.
Pang later authorizes a merge.

The next experiment requires a new predeclared protocol and a transport proven with valid responses
larger than 511 bytes. Do not revise or rerun this frozen result in place.
