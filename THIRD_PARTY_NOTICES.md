# Third-party notices

Status: Build 000 inventory in progress
Last verified: 2026-08-21

Christopher D. Pang is the author and steward of ARC3. Third-party works retain their own authorship, copyright, and license terms. This file records inspected and runtime sources; it does not grant a license for ARC3 itself.

## Runtime dependencies pinned at Stage 00

| Component | Identity | License evidence | Use |
|---|---|---|---|
| ARC-AGI Toolkit | `arcprize/ARC-AGI@f12822c4d550121c35a275008d964afbbed47d2f`; PyPI `arc-agi==0.9.9` | MIT `LICENSE` blob `80216ed3bbd1749bf73b6ab13188db27178b4578` | Official local/API adapter dependency |
| ARC Engine | `arcprize/ARCEngine@b495c6acaf253c9681cd7b75c4299d352e9ce6f8`; PyPI `arcengine==0.9.3` | MIT; PyPI distribution metadata includes copyright ARC Prize Foundation | Official local game-engine dependency |

The complete transitive dependency resolution is recorded in `upstream.lock.json`. A generated dependency-license inventory will supplement this table before the release-candidate stage.

## Inspected development references

| Component | Identity | License evidence | Treatment |
|---|---|---|---|
| ARC-AGI-3 Agents | `arcprize/ARC-AGI-3-Agents@4743e7d0aaae0ded0d98a89a7e282e63564cd58b` | MIT `LICENSE` blob `d8e1cd42ac40338c6c76a8a6ac18eea0eaf95fbe` | Interface and examples inspected; hosted-model dependencies are excluded from the competition runtime |
| ARC-AGI-3 Kaggle Starter | `arcprize/ARC-AGI-3-Kaggle-Starter@eeb1535404f321d280a8f9194bbc1d7aca5f05fc` | `NOASSERTION`: no LICENSE/COPYING/NOTICE file and no GitHub-detected license at the pinned commit | Interface behavior inspected only; no source copied. ARC3 will implement an equivalent first-party wrapper pending owner license choice |
| ARC-AGI-3 documentation source | `arcprize/docs@a5dfc0b64c625fb4a19cf074af845ebe0bb88ff8` | `NOASSERTION`: no GitHub-detected repository license | Factual primary-source reference only; no documentation source copied |
| ARC-AGI-3 documentation | content identities in `upstream.lock.json` | Copyright remains with ARC Prize, Inc. and named source authors | Factual primary-source reference; short quotations only in reports where needed |

## Distribution boundary

There is intentionally no root `LICENSE` for ARC3. `docs/legal/LICENSE-DECISION.md` is an owner decision surface, not a license grant. Packaging must include applicable third-party notices without implying that first-party ARC3 code has already been licensed.
