# Strongwiz operator bridge v0.1

This bridge measures a Codex-operated Strongwiz process on one frozen ARC-AGI-3 public
development game. It is neither Hearthline nor an autonomous Kaggle agent.

## Identity and acquisition

Strongwiz is fetched only from `Grativy6/strongwiz` commit
`6944642da7f4f3e6428a597587038c3b365074a5`. A clean clone can acquire and verify the exact source,
tree, license, and deterministic Git archive without opening an ARC environment:

```powershell
.venv\Scripts\python.exe -m scripts.acquire_strongwiz_source
```

The acquired source and archive remain under ignored `playground/` paths. CI repeats the
acquisition and both upstream and bridge tests. No game source is inspected.

## Decision boundary

The official ARC adapter owns the only measured environment session. The JSONL operator receives
only the returned frame cells and digests, environment state, completed-level counters, remaining
declared budgets, legal action aperture, retained hypothesis references, last concise assessment,
and the current Strongwiz cadence selection. It never receives the SDK session or game source.

The exposure ledger reserves acquisition and measured-play intent with an exclusive create lock,
so concurrent processes cannot both pass the one-shot check. The measured runner enforces the
frozen wall-clock, peak-RSS, and evidence-byte ceilings before action authorization, immediately
after every environment return, around policy closure, and before writing the final result. The
operator read is deadline-bound and invokes the resource watchdog while waiting. Official measured
recordings are isolated beneath the counted per-run evidence root; measured exposure-ledger growth
is counted from its pre-intent baseline. The evidence allowance reserves space for the final result
and completion receipt.

For every proposed action, the bridge uses pinned Strongwiz machinery to bind:

- an observation, governing WIN goal, scoped next-decision goal, and meaningful distinction;
- optional versioned hypotheses plus a falsifiable prediction;
- the external model-driver limitation, normalized domain adapter, and single writer identities;
- the exact router and two-speed cadence policies;
- the owner-supplied public-play grant and exact PEA/PECAN lab-policy decision;
- the proposal, legal action, returned official consequence, prediction checks, residual, and
  smallest implicated reopening rule;
- a serial append-only SQLite receipt chain and 80-action/8-reset checkpoint seals.

The full Strongwiz `ReasoningSession`, `GrantRegistry`, `ExecutionCoordinator`, `FactStore`,
`MechanicLedger`, and `GoalGraph` are not used in this bridge. The result therefore measures this
declared Strongwiz contract/routing/cadence/lab/ledger slice, not every subsystem in the repository.

## Operator response

Each request is self-describing and includes the response vocabulary. The operator returns exactly
one JSON object with this shape (arrays are JSON arrays and ranks are exact integers):

```json
{
  "schema": "arc3.strongwiz-operator-response.v0.1",
  "request_sha256": "sha256:<copied from request>",
  "sequence": 0,
  "action": {"name": "ACTION1", "coordinate": null},
  "distinction": {
    "statement": "decision-relevant uncertainty",
    "candidate_resolutions": ["candidate A", "candidate B"],
    "competing_predictions": ["prediction A", "prediction B"],
    "decision_effects": ["progress"],
    "decision_that_could_change": "the next action or plan",
    "relevance_summary": "how resolving this serves authoritative WIN",
    "smallest_discriminating_test": "one smallest useful action",
    "reopening_condition": "later evidence that would reopen this distinction"
  },
  "prediction": {
    "expected_consequences": ["concise expected result"],
    "falsified_by": ["concise contrary result"],
    "alternatives": ["another live account"],
    "expected_frame_change": true,
    "expected_state": null,
    "expected_level_delta": 0
  },
  "hypotheses": [],
  "evidence_refs": [],
  "trace_refs": [],
  "residual_refs": [],
  "concise_rationale": "why this is the next bounded action",
  "reversible": true,
  "expected_progress_rank": 1,
  "information_gain_rank": 1,
  "risk_rank": 0
}
```

`ACTION6` alone requires `{"x": <int>, "y": <int>}`. While the returned state is `GAME_OVER` or
`NOT_PLAYED`, the aperture contains `RESET` only when the runtime itself exposes it; otherwise it
is empty. The bridge never synthesizes an action. A returned `WIN` is terminal and authoritative.
Hidden chain-of-thought fields are rejected and never stored.

## Claim ceiling

The environment process is local and uses a Python socket-entry-point denial guard after the one
anonymous, networked official `NORMAL` acquisition. The Codex operator remains hosted outside that
process. Its exact model/runtime artifact is not exposed to or hash-bound by this repository, so
this is a community-style, self-reported `local-public` result—not an autonomous offline agent,
Kaggle result, hidden-game result, or official leaderboard score.
