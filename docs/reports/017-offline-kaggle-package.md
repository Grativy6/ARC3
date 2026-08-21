# Stage 17 — Offline Kaggle package

- **Stage status:** PASS
- **Package status:** PACKAGING_PASS
- **Measured surface:** synthetic
- **Claim boundary:** NO_GENERALIZATION_CLAIM
- **Candidate source commit:** `e5f291912726e6139d1dda682707eada657cb5ce`
- **Candidate source tree:** `c25a4d98bb34f785e1b5ded79ed72a990359e114`
- **Primary evidence:** `docs/evidence/017-kaggle-package-acceptance.json`

## Result

A clean clone of the pushed implementation branch produced an offline, CPU-only Kaggle notebook
candidate twice. Both builds returned `PACKAGING_PASS`; all ten top-level package files and the
sandbox output were byte-identical. The candidate archive is 550,068 bytes with SHA-256
`sha256:06d688d0ceadc832147e3e2993dd8ba64523bad05ffa53004cf349ee861aceaa`.

The sandbox ran the production competition-rerun branch with internet disabled, performed a
hash-locked no-index dependency-install canary, imported ARC3 only from the extracted payload,
registered exactly one first-party agent, exercised `RESET` followed by `ACTION5`, and wrote a
valid one-row Parquet output. The loopback gateway observed five framework connections and zero
network attempts outside the allowed local boundary. No credentials were present and the package
secret scan passed with zero findings.

This is `synthetic` packaging evidence. The private Kaggle gateway, platform wheel inventory,
scorer, and exact platform-supplied framework tree were not available. No Kaggle authentication,
terms acceptance, upload, or official submission occurred, so this is not `Kaggle-public`,
`semi-private`, or `official-private` evidence.

## Candidate architecture

`agent/my_agent.py` remains a thin boundary around the first-party controller. Each decision
returns an immutable, instance-local action request; coordinate data is placed in a fresh request
model instead of mutating the shared upstream `GameAction.ACTION6` enum singleton. A deterministic
two-agent regression confirms that concurrent coordinate actions retain their own payloads.

The notebook validates the pinned Agents framework before loading ARC3. It pins the raw LF Git
bytes of `arcprize/ARC-AGI-3-Agents@4743e7d0aaae0ded0d98a89a7e282e63564cd58b`
and accepts only either those exact bytes or their reversible all-CRLF Windows checkout transform.
Mixed line endings, lone carriage returns, missing files, and content mutations fail closed. A
final audit caught and corrected the earlier Windows-only hashes before this candidate was built;
the superseded `e903c88` candidate remains preserved locally and is not acceptance evidence.

After framework validation, the launcher substitutes a sequential worker for the pinned Swarm's
thread constructor, then restores the original binding. This preserves game order and the single
scorecard open/close flow while bounding the process to one controller at a time. The choice is
based on Stage 16's measured 240-second/2-GiB per-game envelope: launching all 110 CPU-bound
controllers concurrently would violate the measured resource model, while a conservative
sequential estimate of about 3.55 hours fits the documented nine-hour envelope. The full 110-game
private workload was not available and was not represented as measured.

## Offline dependency seal

The generated runtime lock targets CPython 3.12 on Linux x86_64 with a glibc 2.28 compatibility
ladder. It contains 31 exact wheel filenames and hashes. The exact public-PyPI wheelhouse contains
31 files and 45,073,152 bytes; the verifier rejected extra, missing, or hash-mismatched wheels.
An offline `--no-index --no-deps --require-hashes` cross-target installation reproduced all 31
distributions under `C:\a\s17-install-compat-20260821a`.

The Windows notebook rehearsal could not load Linux wheels. It therefore exercised the production
install command with a deterministic pure-Python canary wheel and used already installed exact
runtime dependencies for execution. This limitation is explicit in the sandbox receipt; it does
not replace the separate Linux-wheel download, selection, hash, and offline-install evidence.

| Runtime artifact | Identity |
|---|---|
| Exact requirements | `sha256:d71522e36a1d39bd4bcc8c0a0d65d07886e7360658d1b4794add94de02ff2056` |
| Wheel manifest | `sha256:04a8774e252511d4b3e1c1f5ac7dab507f98ebb4e5a57c80a1415e50380df90e` |
| Exact wheelhouse | 31/31 files; 45,073,152 bytes; PASS |
| Cross-target offline install | 31/31 distributions; PASS |
| SBOM | `sha256:46a2c2ee81f787675f3c35856c1d5dba998cbde51514c071d2dfafa26b3616b5` |

## Deterministic artifacts

The two clean-source builds under `C:\a\s17-candidate-e5f2919-a` and
`C:\a\s17-candidate-e5f2919-b` were byte-identical:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `arc3-kaggle-candidate.zip` | 550,068 | `sha256:06d688d0ceadc832147e3e2993dd8ba64523bad05ffa53004cf349ee861aceaa` |
| `arc3-first-party.zip` | 257,140 | `sha256:ebcb5ae0137c8e76209287b0ac9b2a4b8db821cf00f836d8e7d82cac919b9227` |
| `arc3-submission.ipynb` | 356,603 | `sha256:c4637cea1037755f056bf6dc0e1ac7006348570f2b93b1afab966bd118bb7f0d` |
| `kernel-metadata.json` | 410 | `sha256:c80c48d07a611119f58e33ee24e25821623a6218494ac03cad1c1eb4ad77d4b7` |
| `package-manifest.json` | 22,037 | `sha256:f4ff228e38ba0a161aeacfea4b4ba2f731bb7993e5c3c120e2ffb81671925730` |
| `runtime-requirements-linux-cp312.txt` | 3,128 | `sha256:d71522e36a1d39bd4bcc8c0a0d65d07886e7360658d1b4794add94de02ff2056` |
| `runtime-wheels-linux-cp312.json` | 11,955 | `sha256:04a8774e252511d4b3e1c1f5ac7dab507f98ebb4e5a57c80a1415e50380df90e` |
| `sbom.spdx.json` | 102,333 | `sha256:46a2c2ee81f787675f3c35856c1d5dba998cbde51514c071d2dfafa26b3616b5` |
| `submission-schema.v0.1.json` | 931 | `sha256:2966db762a4c328ee8854cb7ba6b78194bd2fab6cca278f8411ffaab6780bd56` |
| `build-receipt.json` | 3,679 | `sha256:7a737fad6faef335aaff6847c7baac864e43d4809a177e3b30d2f4994f6f1835` |
| `offline-sandbox/submission.parquet` | 856 | `sha256:f601196d5298e525e04c22185acb3668c3a9f74c6f371040164169fcc17279c9` |

The build receipt's canonical self-hash is
`sha256:691e04ac25f404b968bdef9a9fbd45f1968e433d27c9ac33291c7947f9f7e845`.
Independent archive validation found eight candidate members and 93 payload members. The manifest
binds the clean source commit, every payload file, the seven review artifacts embedded in the
candidate, the secret scan, all pinned upstreams, and the public submission-schema source.

## Output validation

The sandbox output contains one row with columns `row_id`, `game_id`, `end_of_game`, and `score`.
It validates as Parquet with `pyarrow==21.0.0` against the schema extracted from the pinned public
starter commit `eeb1535404f321d280a8f9194bbc1d7aca5f05fc`. The validation status is PASS at
level `pinned-public-schema`. The private competition gateway remains authoritative; the public
starter provides the example schema but no standalone private scorer or validator.

## Verification

- clean clone and frozen offline dependency sync: PASS; 61 packages;
- Ruff lint and format checks on the source-identity repair: PASS;
- strict mypy on the repaired launcher: PASS;
- complete `tests/competition` suite: 31 passed in 49.11 seconds;
- focused package determinism: PASS;
- genuine raw-LF pinned framework validation: PASS;
- exact all-CRLF checkout validation: PASS;
- mixed endings, lone carriage return, and mutation rejection: PASS;
- exact wheelhouse verification: PASS, 31/31;
- cross-target offline wheel installation: PASS, 31 distributions;
- candidate A/B byte comparison: PASS, 11/11 artifacts;
- package secret scan: PASS, zero findings;
- static public-game ID and hosted-client checks: PASS;
- sandbox network boundary: PASS, zero non-loopback attempts;
- official submission performed: false.

## Reproduction commands

```text
git clone --branch build/000-arc3-end-to-end --single-branch https://github.com/Grativy6/ARC3.git C:\a\arc3-s17-e5f2919
git -C C:\a\arc3-s17-e5f2919 rev-parse HEAD
python -m uv sync --directory C:\a\arc3-s17-e5f2919 --frozen --all-extras --dev --python 3.12.14 --offline --link-mode copy
C:\a\arc3-s17-e5f2919\.venv\Scripts\python.exe C:\a\arc3-s17-e5f2919\scripts\prepare_kaggle_submission.py --output C:\a\s17-candidate-e5f2919-a --owner-username OWNER_USERNAME --sandbox-timeout 180
C:\a\arc3-s17-e5f2919\.venv\Scripts\python.exe C:\a\arc3-s17-e5f2919\scripts\prepare_kaggle_submission.py --output C:\a\s17-candidate-e5f2919-b --owner-username OWNER_USERNAME --sandbox-timeout 180
```

## Boundaries carried forward

- The private Kaggle wheel inventory, Agents input tree, gateway sidecar, and scorer were not
  available and remain `BLOCKED_EXTERNAL` for exact platform validation.
- The complete 110-game sequential workload was not run; only the bounded three-game scheduler
  fixture and the Stage 16 single-controller resource profile were measured.
- The submission schema is pinned-public evidence; private gateway validation remains
  authoritative.
- The optimized policy was not rerun on the public development partition. Stage 15's negative
  `local-public` result and sealed holdout remain unchanged.
- Palette and action-remap robustness remain failed mechanisms.
- No official competition submission, public score, hidden-game result, release, license grant,
  or merge was performed.
- Nothing in this stage proves hidden-game generalization, PAL, AGI, consciousness, or a general
  theory of intelligence.

Christopher D. Pang remains the project author and steward. AI systems were used as engineering
tools and assistants, not as co-authors, owners, or independent authorities.
