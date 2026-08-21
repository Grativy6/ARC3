# ARC3 license decision — owner gate

Status: **NO LICENSE GRANTED**  
Owner: **Christopher D. Pang**  
Last updated: **2026-08-20**

This document is a decision surface, not a license grant. The absence of a root `LICENSE` file is intentional during workflow bootstrap.

## Why this remains open

ARC Prize eligibility requires the eventual competition method to be released under an eligible open-source license, but choosing a license determines what other people may copy, modify, redistribute, patent-license, or incorporate into other systems. Codex may research and prepare the options; only Christopher may select and grant the final license.

Stage 00 must re-check the current competition rules from primary sources before recommending an option. A stale eligibility list must not control the decision.

## Candidate code-license families to compare

| Candidate | General character | Questions to resolve before selection |
|---|---|---|
| MIT-0 | Very permissive; no attribution condition in the license text | Is it currently accepted/recommended by the competition? Is relinquishing the attribution condition desired? |
| MIT | Permissive with copyright/license notice preservation | Is ordinary attribution preservation preferable for ARC3 and third-party reuse? |
| Apache-2.0 | Permissive with an express patent license and notice requirements | Is the added patent language useful, and is the additional notice burden acceptable? |
| BSD-3-Clause | Permissive with notice preservation and non-endorsement clause | Is its wording preferable to MIT for downstream use? |

Do not use a Creative Commons content license as the default software license without a specific reason and current eligibility confirmation.

## Separate surfaces

The final decision may need to distinguish:

- first-party source code;
- documentation and research report;
- generated evaluation artifacts;
- model weights, if any;
- public-game recordings or other upstream-derived material;
- third-party dependencies and adapted starter code, which remain under their own licenses.

A first-party license cannot erase upstream obligations. `THIRD_PARTY_NOTICES.md` and the dependency inventory must remain accurate.

## Decision checklist for Christopher

Before granting a license, review:

1. current ARC Prize/Kaggle eligibility requirements;
2. the final source tree and any copied/adapted upstream material;
3. whether attribution preservation is wanted;
4. whether an express patent license is wanted;
5. whether documentation should use the same or a separate license;
6. whether the public repository contains anything intended to remain proprietary;
7. the exact copyright holder/year wording.

## Codex boundary

Codex may:

- verify current rules;
- produce a sourced comparison;
- inventory third-party licenses;
- prepare candidate `LICENSE` and `NOTICE` files under `docs/legal/candidates/`;
- test that packaging includes required notices.

Codex may not:

- place a final license at repository root;
- state that ARC3 is licensed under a candidate;
- submit the project as prize-eligible;
- infer consent from the public repository or this workflow.

## Resolution receipt

When Christopher explicitly chooses a license, append:

```text
Decision date:
Selected license:
Scope:
Owner instruction/source:
Implementing commit:
Competition-rule source and access date:
```

Then update `docs/ledger/DECISIONS.md`, resolve burden `B-20260820-004`, and add the exact root license files in a separate auditable commit.
