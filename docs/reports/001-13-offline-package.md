# Build 001 Stage 13 — Offline package and clean-clone verification

## Result

**Status:** `BLOCKED_EXTERNAL`

**Evidence label:** `synthetic`

**Claim:** `DETERMINISTIC_OFFLINE_PACKAGE_OBSERVED_ON_AVAILABLE_SURFACES`

Build 001 produced a deterministic 788,070-byte final offline package candidate from clean source
`9f25e13b4672ff0ea87544ba20c5677f194cf291`. All eight A/B builds across four final hosted
Ubuntu/Windows jobs are byte-identical at SHA-256
`sha256:02326a145d510c017dc04ffd79a61cfe8c46771cbc9e74b7c8f29a9b75756d21`.
The only unavailable required surface is the exact private Kaggle wheel/framework/gateway/scorer
environment. This stage therefore remains `BLOCKED_EXTERNAL`, not PASS.

No public game, holdout game, official submission, terms acceptance, upload, or private evaluation
was attempted.

## Source and lock identity

- final package source commit: `9f25e13b4672ff0ea87544ba20c5677f194cf291`;
- final package source tree: `d7fc05c9dff0f63cc97e7b752e1fe59ff7583900`;
- accepted local clean-clone source: `d9c19558fb76b9c5111221a8e7c78d4def5dee51`,
  tree `ba0cdbc178d41e7b528240c042a3a61cdb1b329b`;
- production policy: `d6d4bac1e33c9837856c08abcee61bcb14afd34e`, tree
  `dd8e82e4b34337a208110929e3f5f8079d1e0a18`;
- production source hash:
  `sha256:8f0de1a9c2c88761951ba2bcd69f2612bedfa0cc4226f44f1ed272b54b9023a8`;
- `uv.lock`: `sha256:3bf42dcbe45720f71b7433584f56a5d5982ec1c687c341ad2626222fa5de285b`;
- `upstream.lock.json`:
  `sha256:67e1d937e213bbcc25783784d04c4fa349b85dc09b94855256916ca6b96e808a`;
- operative MIT-0 `LICENSE`:
  `sha256:7f433e520d07d56ad14d92e9da9f580771479c30a2bfccc8024eed308f21bbe8`;
- `THIRD_PARTY_NOTICES.md`:
  `sha256:dd3b46094c40b5bf2a0b13892382e05ebaa1e8006f341f94f1279a87ffdbf70a`.

## Preserved failed long-root attempt

The first Stage 13 long-root run at accepted local source `d9c19558…` used avoidably long external
output/transient paths. It preserved a
`FAILED_MECHANISM` receipt after 696 tests passed, two skipped, and three failed with Windows
path-length `FileNotFoundError`. The two package builds still matched the eventual accepted
candidate hash, but the test and guard-validation checks did not pass, so that attempt was not
promoted.

- receipt:
  `C:/a/arc3-b001-final-output-d9c1955/release-verification-receipt.json`;
- receipt file SHA-256:
  `sha256:cd8aed1cb97cdac6bfd7f27b1a3852724e09ca71a5740360b40e55dcc931e4e3`;
- curated evidence file SHA-256:
  `sha256:100f86379f867d14cb330d28c25f32436fb5243863e22b78da89275e65c95732`.

The bounded retry changed only the external root lengths, not source, lock, profile, package
builder, or package bytes. The failed receipt remains preserved.

## Accepted local clean-clone result

The short-root run at `C:/a/o13d9` completed 20/21 checks. Exactly
`private-kaggle-surfaces` is `BLOCKED_EXTERNAL`; there are no mechanism or infrastructure
failures. The package-safe suite passed 699 tests with two platform skips. Independent validation
confirmed the verifier's no-newline canonical self-hash contract, every one of the 46 sealed file
hashes, and byte equality of the A/B archives.

| Measurement | A | B |
|---|---:|---:|
| package wall seconds | 16.563186600105837 | 16.239603399997577 |
| package peak RSS bytes | 166,326,272 | 151,076,864 |
| archive bytes | 788,071 | 788,071 |
| archive SHA-256 | `0bd55b93…a095bd` | `0bd55b93…a095bd` |

Startup passed in 1.6057818999979645 seconds, including a 1.4579975999658927-second import, at
67,846,144-byte peak RSS. The audit hook recorded zero network attempts and zero process-launch
attempts. The package contains 31 locked Linux CPython 3.12 wheels. Its 46-file sealed evidence set
contains 4,182,060 bytes at
`sha256:cbc2532eca8119d8fc04f6327b1b66a428c723260b5c8657b060d381988c4834`, with zero secret
findings.

The canonical receipt is
`C:/a/o13d9/release-verification-receipt.json`, file SHA-256
`sha256:c2feeee04fbf0a82291a0c7ba335a1bfe041a6bffbefed4db73d51901c9ec234`, self-hash
`sha256:6bab4c521b1202198aa96ea81b8c3f24ee78f6d12e8c58b5793da7b48cd312d9`.
Its curated evidence file is
`sha256:2ddf1af211f973ac71c1eb5e13d97d03c2fd2b664a319611945e0ffa0c780d06`.

## Hosted cross-platform result

Package runs `32634680498` (push) and `32634682445` (draft PR) both first succeeded at literal
local-source commit `d9c19558…`; all four Ubuntu/Windows sealed maps validated and every A/B
candidate matched the accepted local bytes. The downloaded audit root is
`C:/a/hpa-d9-3263468`.

The final code/test freeze `9f25e13b4672ff0ea87544ba20c5677f194cf291` differs from that local
source only in `.github/workflows/ci.yml` and
`tests/release/test_package_only_path_guard.py`. Its 100-member runtime payload projection is
unchanged, but the outer candidate embeds the exact source commit and therefore has a new archive
identity. Final package runs `32636996137` (push) and `32636997645` (draft PR) both succeeded on
Ubuntu and Windows. All four authenticated receipts reached only the declared
`private-kaggle-surfaces` boundary; all eight A/B candidates match at 788,070 bytes and
`sha256:02326a145d510c017dc04ffd79a61cfe8c46771cbc9e74b7c8f29a9b75756d21`.
Their build receipts match at file SHA-256
`sha256:6651eabef173547b8ffa52bdd8bebc46549e197dcb3424c766689202f16087a8`.
The final downloaded audit root is `C:/a/hpa-9f-3263699`.

The exact 48-file Windows-hosted candidate and receipt set are preserved at
`C:/a/arc3-b001/artifacts/stage13/final-package-9f25e13-exact`. Its independent file-record
manifest is `sha256:2aca4b7e6f1430b33444459470850b05947fedef2c0bfed34d0eb07a69d03295`, and the canonical
release-receipt verifier returned the expected `BLOCKED_EXTERNAL` terminal. The candidate SHA-256 is
`sha256:02326a145d510c017dc04ffd79a61cfe8c46771cbc9e74b7c8f29a9b75756d21`; the build receipt,
package manifest, verification evidence, and verification receipt file SHA-256 values are,
respectively, `6651eabe…87a8`, `d6766e06…f933`, `98ddfedc…2390`, and `5657f2b3…c6e0`.

The independent `9f25e13…` clean clone passed offline sync/lock, lint, formatting, strict typing,
and doctor. Exact-source ordinary CI also passed on both push and draft-PR events: Ubuntu reported
1,329 passed/10 skipped at 80% total coverage in 1,024.61 and 1,047.62 seconds; Windows reported
1,323 passed/16 skipped at 80% in 1,836.93 and 1,573.22 seconds. Full local and hosted verification
results are sealed in Stage 14.

## Boundary and burden

This evidence proves deterministic offline package construction and local/hosted behavior on the
available public dependency/runtime surfaces. Python audit guards are not an OS filesystem or
native-extension sandbox, sampled RSS is not a hard memory limit, and private Kaggle compatibility
is not locally knowable. Those limits remain explicit in the burden ledger. No package result is a
game score or evidence of hidden-game generalization.
