# Build 003 Stage 01 — existing-system audit and frozen baseline

Status: **PASS**, with one inherited reproducible `FAILED_INFRASTRUCTURE` test preserved.

Build 003 starts from merged `main` commit `bea1eac99cb0f1b351526b1dc487d132ba1d40ef`. Build 002 head `5448c53f3b7e08f606cf292e6068f3f9c9db16d4` is ancestral, and its tree is identical to merged `main`. The frozen baseline opened no game, took no environment action, and consumed no holdout.

## Reuse map

Build 003 extends the existing observation normalization and perception, bounded memory, world-model and hypothesis machinery, exploration, controller/governor, immutable trace and replay, official adapter, `MyAgent` lifecycle, and offline package pipeline. It does not introduce another budget authority or a parallel competition lifecycle. The new work is limited to structured action effects, layer relevance, versioned mechanics, residual-directed probes, and cross-level reuse.

## Frozen checks

- Lock consistency, Ruff lint, Ruff formatting, and strict mypy passed.
- The full suite recorded 1,463 passed, 21 skipped, and two initial failures in 2,437 seconds.
- One repository-integrity failure was a concurrent-write race caused by ignored analysis artifacts being produced during the bounded scan; it passed once those writes stopped.
- One Windows launcher-topology regression remains reproducible. Its runtime receipt passes every predicate except `direct_process_probe_exact`: the ordinary virtual-environment launcher reports the unversioned uv-managed base executable lexically, while the direct-base probe reports its versioned resolved path. This is preserved as inherited `FAILED_INFRASTRUCTURE`, not converted into a Build 003 code failure or a passing suite.
- Peak memory was not sampled during the already-running baseline and is explicitly `NOT_MEASURED`; no retrospective value is invented.

The machine-readable receipt is `docs/evidence/003-01-build-002-frozen-baseline.json`.
