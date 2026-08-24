# Third-party notices

Status: Build 001 Stage 00 license transition; Build 000 lock inventory preserved
Last verified: 2026-08-21

Christopher D. Pang is the author and steward of ARC3. Third-party works retain their own authorship, copyright, and license terms. This inventory records the exact Build 000 runtime, platform-input, and build-only identities; it does not grant a license for ARC3 itself.

ARC3 first-party source is licensed under MIT-0 by the operative root `LICENSE`, following the
owner's explicit 2026-08-21 approval. That first-party grant does not replace, relax, or
misrepresent any third-party terms below.

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

## Complete repository lock reconciliation

The Stage 19 audit binds `uv.lock` at
`sha256:3bf42dcbe45720f71b7433584f56a5d5982ec1c687c341ad2626222fa5de285b`.
It contains 61 package records: one first-party `arc3` record and 60 third-party records. The
Stage 17 SPDX file covers 37 locked third-party distributions, and the development-lock table
below covers the remaining 23, including the previously noted platform-conditional Colorama
record. Thus every third-party locked record has a declared or concluded treatment. The Build 000
machine-readable reconciliation remains preserved at
`docs/evidence/019-dependency-license-inventory.json`; its historical first-party
`OWNER_DECISION_REQUIRED` status was resolved by the later Build 001 owner instruction and root
MIT-0 license.

Hashes below are SHA-256 identities of exact installed `.dist-info` license or notice evidence in
the frozen Python 3.12 environment. “Composite” means the primary license and bundled terms must
travel together. Colorama and Nodeenv declare generic BSD metadata; the BSD-3-Clause conclusion
comes from their exact embedded three-clause text.

| Development-lock distribution | Concluded treatment | Exact evidence SHA-256 |
|---|---|---|
| `cfgv==3.5.0` | MIT | `01fc3f8031a672b3f5d7d8ac262e432f3ea812809f5697d6bc5b270bf6446561` |
| `colorama==0.4.6` | BSD-3-Clause | `cac35c02686e5d04a5a7140bfb3b36e73aed496656e891102e428886d7930318` |
| `coverage==7.15.4` | Apache-2.0 | LICENSE `eb3d7b5485466acbd81f2b496f595ab637d2792e268206b27d99e793bdb67549`; NOTICE `445e6e7876ff25ff16254af9ba7cb38939b108bad08034ab7742334473ad0e34` |
| `distlib==0.4.3` | PSF-2.0 | `808e10c8a6ab8deb149ff9b3fb19f447a808094606d712a9ca57fead3552599d` |
| `filelock==3.32.3` | MIT | `608c89d5060ae9921adccf3236695bc654a9946e12323ef6c021dfa04e294d48` |
| `hypothesis==6.165.10` | MPL-2.0 | `ac89037bac63550644dce8cf32c6765e5fab9dc1a1ce94b89f8a805f341a6750` |
| `identify==2.6.19` | MIT | `edbc2ad3b7084fac873e1b1b450fd370d914eb97f7f31263b4ff65f47dc10c43` |
| `iniconfig==2.3.0` | MIT | `3409fa91f7ace557894632676656e32264fe5ef7581535725dc9a23774551bd4` |
| `librt==0.15.0` | MIT with bundled terms retained | `81b7ac7e5dc9410dd4aa4c8f8c5884b43cb821137904dc247b381132389b6aa8` |
| `mypy==1.20.2` | Composite: MIT primary plus embedded PSF and typeshed Apache/MIT terms | primary `1cdee80ea9363fbe69582df40fa64e1853d7647fb4978c2b376f5854d88142be`; typeshed `13c71e0962836d8850762bda0f6234ff213034871fa66b6c42962549d73517a4` |
| `mypy-extensions==1.1.0` | MIT | `a50450da1d53cd777b80ced77c58ff96abe0ccd879706bd142c3ec20e245f0b4` |
| `nodeenv==1.10.0` | BSD-3-Clause | `606faf42d48b54d539dae99db6fecd48544535587e27275b319a3f36113cb6fa` |
| `platformdirs==4.11.3` | MIT | `29e0fd62e929850e86eb28c3fdccf0cefdf4fa94879011cffb3d0d4bed6d4db6` |
| `pre-commit==4.6.2` | MIT | `ea2ca27cba7cc35822d95a46d59bcd3cc88e196592e6390d1949a359ffc990e8` |
| `pygments==2.21.0` | BSD-2-Clause | `a9d66f1d526df02e29dce73436d34e56e8632f46c275bbdffc70569e882f9f17` |
| `pytest==8.4.2` | MIT | `ca836a5f9ecca3b2f350230faa20a48fb8b145653b5568d784862df864706b9b` |
| `pytest-cov==6.3.0` | MIT | `835586ae156766a24e3c103fbc55d9af6b1a16df57ca932c97482a2737fd83d5` |
| `python-discovery==1.5.2` | MIT | `90e25e1faf2a4aaea8d95ee8e7f5738b052a1acc0c9c58068101f931a86bd588` |
| `pyyaml==6.0.3` | MIT | `8d3928f9dc4490fd635707cb88eb26bd764102a7282954307d3e5167a577e8a4` |
| `ruff==0.16.4` | Composite: MIT primary plus bundled third-party notices | `2597d854122b77ddc71971564ca2350a37608575ce324adc5650a2b2051c8f18` |
| `sortedcontainers==2.4.0` | Apache-2.0 | `1db7cae7fce6452e2e608e401a0f953e0133e4c2d75db69fb8ae851d2086f5b6` |
| `types-requests==2.33.0.20260712` | Apache-2.0 | `295f8538c94ae5c3043301cf7cff1c852dab6a786a8ddee471e061b40d5ecabe` |
| `virtualenv==21.7.4` | MIT | `5c15919378c5b2aaab7b19cea70d8cdc75f76879e32454e4c0399f8b71d171e9` |

No locked third-party distribution was unknown or absent from the synchronized audit environment.
The installed metadata for `arc-agi==0.9.9` and `arcengine==0.9.3` declares MIT but embeds no
license file, so the existing upstream Git/sdist identities remain the controlling evidence.

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

The root `LICENSE` grants MIT-0 for ARC3 first-party source. Current ARC3 package metadata and
SBOMs declare `MIT-0`. The original file under `docs/legal/candidates/` remains a nonoperative
historical review surface; it is not the operative license. Third-party and platform-supplied
components remain under the independent terms recorded above.
