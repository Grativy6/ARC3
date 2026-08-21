# ARC3 trace-ledger contract

Status: **controlling data contract for Build 000**  
Schema family: **ARC3 Trace v0.1**  
Owner: **Christopher D. Pang**

## 1. Purpose

ARC3 needs memory that is useful for action selection without silently rewriting history. The trace ledger therefore separates immutable receipts from derived interpretations.

The ledger must answer:

- What was actually observed?
- What action was actually sent?
- What alternatives and hypotheses were active at that moment?
- What consequence arrived?
- Which prediction succeeded or failed?
- What was changed in the world model afterward?
- Can the run be replayed and audited from the recorded evidence?

The ledger is not a transcript of hidden chain-of-thought. Store concise, structured decision summaries and machine-readable hypothesis state.

## 2. Invariants

1. **Append-only raw trace** — accepted raw events are never mutated in place.
2. **Hash-linked order** — each raw event commits to the previous event hash.
3. **Source honesty** — observations, metadata, model inferences, and evaluator scores have distinct event types.
4. **No retrospective promotion** — later success cannot turn an earlier candidate into prior knowledge.
5. **No silent deletion** — rejected hypotheses and unexplained residuals remain addressable.
6. **Derived-view replaceability** — summaries, indices, embeddings, and reports may be rebuilt from source events.
7. **Scoped confidence** — support in one level/game does not automatically become generic support.
8. **Replayability** — a recording plus configuration and code identity is sufficient to reproduce policy updates offline where upstream determinism permits.
9. **Bounded disclosure** — secrets and unnecessary user/environment data are never written.
10. **Versioned migration** — schema changes produce migration receipts rather than rewriting old files.

## 3. Storage surfaces

Use three layers.

### 3.1 Raw event journal

Default format: newline-delimited canonical JSON (`.jsonl`).

Properties:

- one event per line;
- UTF-8;
- deterministic key ordering before hashing;
- no NaN/Infinity;
- append + flush policy configurable;
- optional chunk rotation by size or episode;
- optional compression only after the chunk is sealed;
- every sealed chunk receives a manifest entry and SHA-256.

### 3.2 Derived index

Use an in-memory index and optionally SQLite/Parquet for analysis. The index may contain:

- event offsets;
- frame-hash lookup;
- hypothesis lineage;
- action-effect statistics;
- object tracks;
- state-graph edges;
- summary ranges.

The index is disposable and rebuildable.

### 3.3 Checkpoint

A checkpoint is a versioned snapshot of current derived state plus the exact raw trace position it depends on. It is not a replacement for raw events.

## 4. Common event envelope

Every raw event should serialize an envelope equivalent to:

```json
{
  "schema": "arc3.trace.event.v0.1",
  "event_id": "01J...",
  "run_id": "...",
  "episode_id": "...",
  "game_id": "ls20-version-or-redacted",
  "level_index": 1,
  "step_index": 0,
  "event_type": "observation.received",
  "occurred_at": "2026-08-21T00:00:00Z",
  "recorded_at": "2026-08-21T00:00:00Z",
  "source": {
    "kind": "arc_agi_toolkit",
    "version": "0.9.9"
  },
  "scope": "episode",
  "payload": {},
  "code_identity": {
    "git_commit": "...",
    "config_hash": "..."
  },
  "previous_event_hash": "sha256:...",
  "event_hash": "sha256:..."
}
```

Required envelope rules:

- `event_id` is globally unique and sortable when practical.
- `occurred_at` is the source/environment time when available; `recorded_at` is local journal time.
- `step_index` advances only for attempted environment actions and their consequences; internal events can share a step.
- `game_id` may be retained for evaluation bookkeeping but production policy code may not branch on it.
- `event_hash` is computed over the canonical event excluding the `event_hash` field itself.

## 5. Core event types

### 5.1 Run lifecycle

- `run.started`
- `run.resumed`
- `run.completed`
- `run.aborted`
- `run.environment_fault`
- `run.checkpoint_written`
- `run.checkpoint_restored`
- `run.checkpoint_rejected`

### 5.2 Observation events

- `observation.received`
- `observation.normalized`
- `observation.delta_measured`
- `observation.metadata_changed`
- `observation.parse_failed`

`observation.received` should preserve or reference the exact upstream frame payload. Large frames may be content-addressed in a blob store, but the event must include the blob hash and dimensions.

### 5.3 Perception events

- `perception.component_detected`
- `perception.components_detected` (bounded batch of one observation's component measurements)
- `perception.object_correspondence_proposed`
- `perception.object_correspondence_rejected`
- `perception.salience_computed`

Perception events are interpretations and must reference source observation event IDs.

### 5.4 Hypothesis events

- `hypothesis.created`
- `hypothesis.supported`
- `hypothesis.contradicted`
- `hypothesis.narrowed`
- `hypothesis.rejected`
- `hypothesis.reopened`
- `hypothesis.superseded`
- `hypothesis.scope_changed`

Each event references a stable `hypothesis_id` and the evidence events that caused the change.

### 5.5 Retrodiction and simulation

- `model.retrodiction_started`
- `model.retrodiction_completed`
- `model.rule_promoted`
- `model.rule_demoted`
- `simulation.plan_evaluated`
- `simulation.prediction_emitted`

### 5.6 Goal events

- `goal.candidate_created`
- `goal.supported`
- `goal.contradicted`
- `goal.selected_for_planning`
- `goal.reopened`
- `goal.retired`

### 5.7 Action events

- `action.candidates_generated`
- `action.selected`
- `action.validated`
- `action.submitted`
- `action.rejected_by_environment`
- `action.fallback_used`

`action.selected` payload should include:

- selected action and coordinate data;
- candidate utilities;
- selected probe/plan ID;
- active hypothesis IDs;
- predicted outcome IDs;
- concise rationale category such as `discriminate_models`, `follow_plan`, `mandatory_reset`, or `fault_fallback`.

Do not store unrestricted hidden reasoning text.

### 5.8 Consequence events

- `consequence.received`
- `consequence.matched_prediction`
- `consequence.mismatched_prediction`
- `consequence.progress_detected`
- `consequence.level_completed`
- `consequence.game_over`

### 5.9 Evaluation events

- `evaluation.started`
- `evaluation.game_result`
- `evaluation.scorecard_received`
- `evaluation.completed`
- `evaluation.result_invalidated`

The payload must label the result surface:

- `synthetic`
- `local-public`
- `online-public`
- `Kaggle-public`
- `semi-private`
- `official-private`

## 6. Observation receipt

Minimum normalized observation payload:

```json
{
  "frame_count": 1,
  "frames": [
    {
      "blob_hash": "sha256:...",
      "width": 64,
      "height": 64,
      "palette": [0, 1, 3],
      "frame_hash": "sha256:..."
    }
  ],
  "game_state": "NOT_FINISHED",
  "score": null,
  "available_actions": ["ACTION1", "ACTION2", "ACTION5"],
  "upstream_metadata": {}
}
```

Preserve unknown upstream fields under a namespaced object instead of discarding them.

## 7. Delta receipt

Minimum delta payload:

```json
{
  "before_frame_hash": "sha256:...",
  "after_frame_hash": "sha256:...",
  "changed_cell_count": 4,
  "changed_bbox": [10, 12, 11, 13],
  "cell_changes": [
    {"x": 10, "y": 12, "before": 2, "after": 0},
    {"x": 11, "y": 12, "before": 0, "after": 2}
  ],
  "component_changes": [],
  "metadata_changes": {},
  "apparent_noop": false
}
```

If the full cell list is too large, store a content-addressed delta blob plus summary metrics.

## 8. Hypothesis record

The current derived hypothesis record should have a serializable shape equivalent to:

```json
{
  "hypothesis_id": "H-ACTION1-MOVE-UP-001",
  "hypothesis_type": "action_semantics",
  "scope": "game",
  "statement": {
    "action": "ACTION1",
    "effect": "translate_controllable_object",
    "dx": 0,
    "dy": -1,
    "conditions": []
  },
  "status": "active",
  "weight": 0.72,
  "created_event_id": "...",
  "support_event_ids": ["..."],
  "contradiction_event_ids": ["..."],
  "parent_ids": [],
  "superseded_by": null,
  "predictions": [],
  "last_tested_step": 8
}
```

Weights are ranking aids, not proof. Use calibrated probabilities only when calibration has been measured.

## 9. Prediction and consequence matching

Before submitting an action, emit one or more prediction records:

```json
{
  "prediction_id": "P-...",
  "action_decision_id": "A-...",
  "world_model_id": "WM-...",
  "predicted_delta": {
    "kind": "translation",
    "object_id": "O-...",
    "dx": 1,
    "dy": 0
  },
  "probability_or_weight": 0.61,
  "alternative_rank": 1
}
```

After the consequence, match predictions using declared tolerances and emit the result. A mismatch should identify residuals rather than merely return false.

## 10. Reopening

Reopening never deletes history. It creates a new event that references:

- the hypothesis/model/goal being reopened;
- the contradiction or unexplained residual;
- the prior status;
- the new status;
- which downstream plans became invalid;
- whether scope was narrowed;
- any newly generated alternatives.

Example:

```json
{
  "event_type": "hypothesis.reopened",
  "payload": {
    "hypothesis_id": "H-...",
    "caused_by_event_ids": ["E-..."],
    "previous_status": "active",
    "new_status": "candidate",
    "invalidated_plan_ids": ["PLAN-..."],
    "residual": "ACTION1 moved a different component under contact condition"
  }
}
```

## 11. Summary contract

A summary must contain:

- summary schema/version;
- source event start/end IDs;
- source chunk hashes;
- generated-at timestamp;
- generator code commit/config hash;
- claims with supporting and contradicting event IDs;
- unresolved residuals;
- retrieval tags.

A summary that cannot cite its source range is invalid.

## 12. Checkpoint contract

Checkpoint envelope:

```json
{
  "schema": "arc3.checkpoint.v0.1",
  "run_id": "...",
  "episode_id": "...",
  "trace_tail_event_id": "...",
  "trace_tail_hash": "sha256:...",
  "git_commit": "...",
  "config_hash": "sha256:...",
  "rng_state": {},
  "state": {
    "hypothesis_registry": {},
    "world_model_ensemble": {},
    "goal_registry": {},
    "state_graph": {},
    "current_plan": null,
    "memory_indices": {}
  },
  "checkpoint_hash": "sha256:..."
}
```

Restore only when schema, trace tail, code/config compatibility policy, and checkpoint hash validate. Otherwise emit `run.checkpoint_rejected` and start a new derived state while preserving the incompatible file.

## 13. Chunk sealing and manifests

When a raw journal chunk closes:

1. flush and fsync where supported;
2. calculate byte length, event count, first/last event IDs, first/last hashes, SHA-256;
3. append an entry to the run manifest;
4. optionally compress the sealed chunk;
5. verify decompression/hash before deleting the uncompressed copy;
6. never modify a sealed chunk.

## 14. Migration

Schema migrations are programs with tests.

A migration must:

- leave source files untouched;
- produce a destination journal/index;
- record source and destination hashes;
- list semantic changes;
- preserve unknown fields where possible;
- emit a migration manifest;
- pass replay equivalence checks for unaffected semantics.

## 15. Privacy and competition hygiene

- Do not write credentials or environment variables to trace payloads.
- Redact API headers and local absolute paths in committed reports.
- Raw online recordings remain local/ignored unless intentionally curated and checked.
- Do not commit hidden/private evaluation frames.
- Public recordings included as fixtures must be labeled and license-compatible.

## 16. Required tests

### Unit

- canonical JSON stability;
- event hash generation;
- previous-hash linkage;
- schema validation;
- frame/delta blob hashing;
- summary source references;
- checkpoint validation.

### Property

- mutation of any sealed event changes the chain/manifest verification result;
- arbitrary valid events round-trip without semantic loss;
- derived index rebuild is deterministic;
- rejected hypotheses remain queryable;
- migration preserves source hashes.

### Integration

- complete synthetic episode can be journaled, sealed, replayed, summarized, checkpointed, restored, and continued;
- prediction mismatch reopens dependent plan/model state;
- interrupted append recovers to last valid event without accepting a partial line;
- competition mode writes locally without attempting network access.

### Performance

- event append overhead remains small relative to environment step time;
- frame blobs are deduplicated by hash;
- retrieval stays within the configured decision-time budget;
- memory use remains bounded across long episodes.

## 17. Acceptance condition

The trace layer passes when an independent test can:

1. alter one historical event and detect the alteration;
2. rebuild all derived indices from raw chunks;
3. reproduce the controller's concise action-decision inputs for a recorded step;
4. show what evidence supported and contradicted each active rule;
5. resume after an artificial interruption;
6. preserve unresolved residuals through summary and checkpoint cycles.
