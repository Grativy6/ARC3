# Stage 01 — Repository foundation

- **Stage status:** PASS
- **Evidence label:** synthetic
- **Measured at:** 2026-08-21T05:17:15Z
- **Implementation branch:** `build/000-arc3-end-to-end`
- **Starting checkpoint:** `52c4406`
- **Host:** Windows 10.0.19045, x86-64
- **Runtime:** uv 0.12.5 (`210d1f678`), CPython 3.12.14

## Result

ARC3 now has a reproducible Python 3.12 project, a locked dependency graph, a typed
offline-first core, a safe structured logger, a cross-platform doctor, an independently
implemented `agent/my_agent.py` compatibility surface, and Linux/Windows CI configuration.
The official Kaggle starter remains a pinned interface reference only: no starter source was
copied because its pinned repository has no detected source license. This implements decision
D-20260821-006 without making or implying a license grant.

The four execution modes are explicit: `synthetic`, `local`, `online`, and `competition`.
Competition mode rejects network-enabled configuration at every tested entry point. Config
identity and component seeds use canonical SHA-256 derivation rather than process-dependent
Python hashing or wall-clock state. The compatibility policy is deterministic under seed,
filters to advertised actions, and has no game-identity branch.

## Durable surfaces

- `pyproject.toml` and `uv.lock` pin the build and exact transitive resolution.
- `.python-version` pins CPython 3.12.14.
- `src/arc3/config.py`, `types.py`, and `errors.py` establish typed boundaries.
- `src/arc3/logging.py` emits JSON and recursively redacts credential-bearing keys and values.
- `src/arc3/doctor.py` performs local diagnostics without probing the network.
- `scripts/bootstrap.ps1` and `scripts/bootstrap.sh` are location-independent smoke entrypoints.
- `.github/workflows/ci.yml` defines locked Linux and Windows checks with read-only contents
  permission.
- `.gitignore` excludes credentials, local environments, recordings, artifacts, generated
  notebooks, caches, and profiling output.
- The test skeleton contains unit, property, integration, replay, and competition surfaces.

## Measured verification

The following commands ran from the repository root. No credential value was printed or
stored.

```text
python -m uv sync --all-extras --dev
Resolved 57 packages
Checked 57 packages
PASS

python -m uv run ruff check .
All checks passed

python -m uv run ruff format --check .
PASS

python -m uv run mypy src agent scripts
Success: no issues found

python -m uv run pytest -q
49 passed in 2.41s
branch coverage: 77% for the Stage 01 source set

python -m uv run arc3 doctor
ARC3 doctor: PASS
Python 3.12: PASS
configuration: PASS
network policy: PASS
official arc-agi toolkit: FOUND
official arcengine models: FOUND
official Agents framework: OPTIONAL / not installed

./scripts/bootstrap.ps1 -Check
PASS
49 tests passed
doctor PASS
```

The PowerShell bootstrap was exercised on the measured Windows host. Bash syntax was parsed
successfully during scaffold validation; execution on Linux remains delegated to the pushed CI
job and later clean-clone verification.

### Remote CI fault and correction

The first pushed CI runs `32450125300` and `32450125762` passed on Ubuntu and failed on
Windows at `ruff format --check`: Git's Windows checkout converted tracked LF files to CRLF,
and Ruff correctly reported 16 files as requiring normalization. This was an infrastructure
configuration failure, not relabeled as a product pass. `.gitattributes` now fixes text files to
LF across checkouts. Correcting runs `32450257835` and `32450260123` then passed all Ubuntu
and Windows jobs (two push/PR trigger surfaces).

## Test coverage of the contract

The 49 focused tests cover:

- strict coordinate and action construction;
- exact result/stage labels;
- deterministic config serialization, hash identity, and seed derivation;
- rejection of unknown configuration and networked competition mode;
- recursive redaction, including explicit sentinel secrets and structured exception fields;
- doctor output, dependency absence, and no-network behavior;
- installed module/CLI availability;
- pinned bootstrap and CI contracts;
- Linux/Windows CI matrix presence and locked installation commands.

## Artifact identities

- `uv.lock`: `sha256:c2c8fac365e0e93dd7743c8797f0d2b00a64183b4f7063546c17cabd3fd08a6a`
- Stage report: recorded in `docs/ledger/run-state.json` after final content is sealed.

## Limits and next work

This stage establishes an engineering substrate, not an ARC benchmark result. No public or
private completion claim is made. Remote GitHub Actions and an actual fresh-clone build are
still separately verified in Stages 01/18, and the thin compatibility policy is replaced by the
integrated controller in Stage 12. Stage 02 next proves the official observation/action path and
records even a zero-score baseline honestly.
