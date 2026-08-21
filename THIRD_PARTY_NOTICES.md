# Third-party notices

Status: Build 000 Stage 17 inventory
Last verified: 2026-08-21

Christopher D. Pang is the author and steward of ARC3. Third-party works retain their own authorship, copyright, and license terms. This inventory records the exact Build 000 runtime, platform-input, and build-only identities; it does not grant a license for ARC3 itself.

The generated `runtime-requirements-linux-cp312.txt`, `runtime-wheels-linux-cp312.json`, and SPDX 2.3 SBOM bind every competition-runtime name and version below to one CPython 3.12 Linux x86_64 wheel SHA-256. The SBOM also records a version-keyed license-file or upstream-license identity for every runtime distribution.

## Competition runtime distributions

| License evidence | Exact locked distributions |
|---|---|
| MIT | `annotated-types==0.8.0`; `arc-agi==0.9.9`; `arcengine==0.9.3`; `blinker==1.9.0`; `charset-normalizer==3.5.1`; `fonttools==4.63.0`; `pydantic==2.13.4`; `pydantic-core==2.46.4`; `pyparsing==3.3.2`; `six==1.17.0`; `typing-inspection==0.4.4`; `urllib3==2.7.0` |
| BSD-3-Clause | `click==8.4.2`; `contourpy==1.3.3`; `cycler==0.12.1`; `flask==3.1.3`; `idna==3.19`; `itsdangerous==2.2.0`; `jinja2==3.1.6`; `kiwisolver==1.5.0`; `markupsafe==3.0.3`; `python-dotenv==1.2.3`; `werkzeug==3.1.8` |
| MPL-2.0 | `certifi==2026.7.22` |
| Apache-2.0 | `requests==2.34.2` |
| Apache-2.0 OR BSD-2-Clause | `packaging==26.3` |
| Apache-2.0 OR BSD-3-Clause | `python-dateutil==2.9.0.post0` |
| MIT-CMU | `pillow==12.3.0` |
| PSF-2.0 | `typing-extensions==4.16.0` |
| Composite distribution terms | `matplotlib==3.11.1` (`LICENSE` SHA-256 `822e8e528147569a41975592aee19c11992ab667ba50451cd929031d5fc74491` plus bundled notices); `numpy==2.5.2` (`BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0`, selected Linux-wheel `LICENSE.txt` SHA-256 `4860083caa0de2ac3292ca98bd074bd8f45d8b32624e37b1e70a240bff61e488`) |

The selected `fonttools==4.63.0` Linux wheel also carries bundled external OFL/BSD notices in `LICENSE.external` (20,022 bytes; SHA-256 `94a83aaee0729a0f302d34acc4acecbd9d58366f262429075fe557e4a54b2e69`). The generated SBOM records that notice alongside the primary FontTools `LICENSE` identity.

`colorama==0.4.6` remains in the cross-platform development lock as a Windows-only conditional dependency of Click; it is not in the Linux competition requirements or runtime SBOM closure.

## Platform-supplied runtime component

| Component | Identity and evidence | Treatment |
|---|---|---|
| ARC-AGI-3 Agents | `arcprize/ARC-AGI-3-Agents@4743e7d0aaae0ded0d98a89a7e282e63564cd58b`; MIT `LICENSE` Git blob `d8e1cd42ac40338c6c76a8a6ac18eea0eaf95fbe`; raw Git LF file SHA-256 `75c4276c506fd93082b38ad39f67ee97aa859574401ef978e701710c7a40af04` | Required external competition framework. It is supplied by the competition input, not bundled. The runtime launcher checks raw-LF pinned core-file hashes (permitting only their exact all-CRLF Windows checkout equivalents), bypasses upstream dotenv/template/telemetry initialization, and registers only ARC3's first-party agent. |

The platform's `arc_agi_3_wheels` directory is also an external competition input. ARC3 does not assume arbitrary contents: the notebook installs only the exact hash-locked Linux requirements with `--no-index --no-deps --require-hashes --only-binary=:all:`. The private Kaggle input and sidecar were not available for local reproduction; this remains an explicit package limitation.

## Build-only tools

| Component | Identity and evidence | Use |
|---|---|---|
| PyArrow | `pyarrow==21.0.0`; selected CPython 3.12 Linux x86_64 wheel SHA-256 `b7ae0bbdc8c6674259b25bef5d2a1d6af5d39d7200c819cf99e07f7dfef1c51e`; Apache-2.0; `LICENSE.txt` SHA-256 `82f5f9b0e6592da7f79022fc930add132a76c56727d29813f94058157a2b2d11`; `NOTICE.txt` SHA-256 `c946470d6b024c77feebdfb686bf92a828402c0ffc27c769bca7d8bef08e1db7` | Deterministic local Parquet creation and validation only; absent from competition runtime requirements. |
| Hatchling | `hatchling==1.32.0`; MIT; wheel SHA-256 `0e17c9c3b9aa7c625acc8d0f5b622f107d5049af9ecf5ada4de1aada5be7cdbc`; `LICENSE.txt` SHA-256 `7f143a8127ad4873862d70854b5bd2abd0085aa73e64fd2b08704a3b9f5c07fc` | Exact PEP 517 build backend. |
| Hatchling dependency: PathSpec | `pathspec==1.1.1`; MPL-2.0; wheel SHA-256 `a00ce642f577bf7f473932318056212bc4f8bfdf53128c78bbd5af0b9b20b189`; `LICENSE` SHA-256 `fab3dd6bdab226f1c08630b1dd917e11fcb4ec5e1e020e2c16f83a0a13863e85` | Exact build-backend dependency; absent from the competition runtime. |
| Hatchling dependency: Pluggy | `pluggy==1.6.0`; MIT; wheel SHA-256 `e920276dd6813095e9377c0bc5566d94c932c33b27a3e3945d8389c374dd4746`; `LICENSE` SHA-256 `d6b65e6c213a5d0b577911d34d6e5949b9f59d76c238c5071a2f3fc16cfb2606` | Exact build-backend dependency; absent from the competition runtime. |
| Hatchling dependency: TOML Kit | `tomlkit==0.15.1`; MIT; wheel SHA-256 `177a05aece5a8ca5266fd3c448abb47b8d352f09d477d3ca8332db4d89b24304`; `LICENSE` SHA-256 `f2f9b460ba719da6626add264d3782f275a4ff7aab677beda08b330911e23adb` | Exact build-backend dependency; absent from the competition runtime. |
| Hatchling dependency: Trove Classifiers | `trove-classifiers==2026.6.1.19`; Apache-2.0; wheel SHA-256 `ab4c4ec93cc4a4e7815fa759906e05e6bb3f2fbd92ea0f897288c6a43efd15b3`; `LICENSE` SHA-256 `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4` | Exact build-backend dependency; absent from the competition runtime. |
| Shared Hatchling dependency: Packaging | `packaging==26.3`; Apache-2.0 OR BSD-2-Clause; exact wheel and license evidence are in the competition runtime inventory | Used by both the build backend and runtime closure; represented once as a package in the SBOM with both relationship roles. |
| uv | `uv==0.12.5`; Apache-2.0 OR MIT; `LICENSE-APACHE` SHA-256 `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4`; `LICENSE-MIT` SHA-256 `860e3d7a86b84e6a7012c7a635fc64df475cebc6cce34dfeb73a5982ec58176c` | Exact repository environment/lock tool, enforced by `tool.uv.required-version`; not included in the candidate runtime. |

## Inspected sources not distributed

| Component | Identity | License evidence and treatment |
|---|---|---|
| ARC-AGI-3 Kaggle Starter | `arcprize/ARC-AGI-3-Kaggle-Starter@eeb1535404f321d280a8f9194bbc1d7aca5f05fc` | `NOASSERTION`: no LICENSE/COPYING/NOTICE file or GitHub-detected license at the pinned commit. Interface behavior was inspected; no starter source is copied. ARC3 uses an independently written wrapper. |
| ARC-AGI-3 documentation | `arcprize/docs@a5dfc0b64c625fb4a19cf074af845ebe0bb88ff8` and content hashes in `upstream.lock.json` | Factual primary-source reference only; no documentation source copied. |

## First-party distribution boundary

There is intentionally no root `LICENSE` for ARC3. First-party `arc3` remains `NOASSERTION` in the SBOM until Christopher D. Pang makes the owner-only license decision. Any candidate text under `docs/legal/` is a review surface, not a license grant.
