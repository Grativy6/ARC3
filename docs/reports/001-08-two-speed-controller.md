# Build 001 Stage 08 — Two-speed controller

Status: **FAILED_INFRASTRUCTURE**

Evidence labels: **synthetic**, **local-public**

Claim boundary: **no throughput, mechanism, or public-recovery claim**

## Result

The unique predeclared Stage 08 attempt stopped after its first of 20 cells. The process-isolated
worker ran frozen Build 000 FULL on the already exposed development identity `ar25-0c556536`, seed
7, for exactly eight submitted and eight returned actions with no reset. It then failed terminal
checkpoint validation with:

```text
RuntimeError: Stage 08 restored terminal controller snapshot changed
```

The same worker receipt marked all eight projected submitted-boundary chains invalid and reported
`receipt-integrity:action or cadence receipt chain is incomplete`. The parent therefore rejected
the worker projection with `EvaluationError: Stage 08 submitted boundary action chain is invalid`,
classified the cell as infrastructure failure, stopped the matrix, and returned exit 1. Nineteen
cells were never exposed or launched. Per the frozen exposure contract, the attempted cell will
not be rerun.

This leaves no paired timing sample: zero valid pairs, no median ratio, and no material-reduction
or non-regression result. Stage 08 therefore does not satisfy acceptance.

## Read-only root-cause audit

Both validation failures are harness false negatives; no controller defect was established.

First, the worker closed the controller before capturing its expected terminal snapshot. Frozen
Build 000 `close()` writes its last checkpoint immediately before changing the in-memory phase to
`CLOSED`; ordinary restore intentionally reconstructs the checkpointed `OBSERVED` phase and rejects
`CLOSED` as a restorable phase. The worker then compared that correct restored snapshot with the
post-close `CLOSED` snapshot. The phase alone therefore forced
`Stage 08 restored terminal controller snapshot changed`.

Second, all eight boundary chains failed a hash comparison that incorrectly treated two distinct
hash namespaces as identical. `GridFrame.digest` hashes a domain-separated binary grid encoding;
the immutable trace frame/blob hash covers canonical JSON bytes. For this cell the semantic digest
was `b0c134...` and the independently replay-verified trace hash was `dcb739...`. The audit checked
all eight boundaries: decision IDs, action payloads, selected/validated/submitted/consequence links,
event order, returned frames, following observations, semantic consequence digests, and trace
adjacency otherwise matched. Existing unit fixtures had assigned the same fake value to both hash
namespaces and mocked restore success, masking both integration defects.

This diagnosis explains the infrastructure classification but does not repair or reopen the unique
attempt. Generic regression repairs may protect later workflows; Stage 08 remains failed and will
not be rerun.

## Preserved bounded evidence

The raw worker trace independently replays: 241 events, 604,310 bytes, eight selected/validated/
submitted actions, eight returned consequences, one `run.completed`, manifest hash
`e30a9816e8b297dbccce500e3a83fe8563fd71e166e79f61032256adfd845490`, and tail hash
`336b8e461e8204ab610fd98e15515e057c01896a3c2a31807ae0d2f572050ce4`.
The worker measured 9.7909341 seconds wall, 9.125 seconds CPU, and 112,750,592 bytes peak RSS;
the parent measured 10.3751057 seconds around the process. No socket attempt was observed and the
source and development-asset identities remained stable.

The failed worker also preserved a local ScorecardManager receipt marked verified at score 0.0,
zero levels, `NOT_FINISHED`. Because terminal restore and receipt validation failed, the parent
correctly projected the typed score as unavailable. The raw scorecard is retained only as failed
worker evidence; it is not an accepted Stage 08 score or aggregate result.

## Exact execution identity

- Build 001 execution commit: `2e78c258cfbee8be62462f61ed08ad04c00a8934`
- Build 001 tree: `4145356c116944bbd7c0c412771de9179ba22efe`
- frozen Build 000 comparator: `90ecf7267d5bb23d751d6f7ce3e8aa75f2f1a130`
- Build 000 tree: `0cf6e00b2fcc399e7a99a62c20e91bb84d485f13`
- predeclaration SHA-256: `3342b6e2635c0606391c9aea02b2fec0cf4c5642a3d38b95768a1b77b4520878`
- matrix SHA-256: `ca507ee6e539e0544647aac792417b276806a848e656f2b7b4f1a368ba6b63a1`
- plan SHA-256: `b42326c4de76786982c07a18be2fcd73afe4583bdb11100e9cb6147b6c8e582c`
- Python 3.12.14; `arc-agi==0.9.9`; `arcengine==0.9.3`
- Windows 10.0.19045; AMD64 Family 23 Model 8; 12 logical CPUs

The exact launch was the frozen detached checkout with
`PYTHONPATH=C:/a/arc3-stage08-build001-2e78c25/src` and:

```text
C:/a/arc3-b001-28c7a00/Scripts/python.exe scripts/measure_two_speed_controller.py --execute
```

## Artifact receipts

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| raw attempt JSON | 74,659 | `7c39fa77de24bd1925d9dbd489d583118f96d4b7fe860678607f485506ad39d4` |
| exposure ledger | 511 | `be73b837805a66ed172b20573aa31c41fe6ba16ced4d471929b6018e22a5d52e` |
| raw worker result | 84,134 | `523f0a6fbc8b34d9ea739e17d507597a3f94d506ed8521b19335644c776e1465` |
| parent receipt | 12,480 | `b1e8028c949d7c7344c0aa820b6afd5f02a9d0026d3a48f2e57bebb12871a377` |
| trace chunk | 594,654 | `94b6e10df644e22963d82cfbfa990af36f6caf70ea14f601870d4bfab2b259ed` |
| recording | 118,540 | `27821d0cfda89948ccd552fb253648abdcce796ef35832a751a2c2b5d4581c16` |

The 45 surviving cell artifacts have canonical aggregate SHA-256
`810f1f6c5e6d06a06e5b9b061fb240879e0d97a1e2bf9f12cd66ad4bfe9aee22`.
The attempt artifact core hash is
`e3e078092318882f2c32887c6a223c0396938abba0ca7b30fdcde0eb5b15383f`.

Seal verification parsed and cross-checked the machine receipt, passed 16 focused secret/receipt
tests in 2.16 seconds, and produced a static competition-integrity receipt with zero findings and
passing policy, secret, source-identity, and supply-chain checks. Its file SHA-256 is
`df7b22783251afe252fdfb24a55f868f6700e563808268a5d1782a7d9f18e50b`. Two earlier scanner
invocations are retained as infrastructure evidence: one supplied `upstream.lock.json` instead of
the dependency lock; the next intentionally disabled metadata enrichment and therefore could not
claim a complete supply-chain pass. The corrected scan used `uv.lock` with installed metadata.

Primary machine receipt: `docs/evidence/001-08-two-speed-controller.json`.

## Boundary and continuation

The ten-game public holdout remains `SEALED_UNCONSUMED`: zero selected holdout game IDs, zero
holdout gameplay events, and no holdout manifest use as gameplay metadata. Stage 08's one exposure
is development-only and recorded before launch.

The infrastructure failure is preserved as a new open burden. It does not erase the preceding
synthetic implementation checks, and those checks do not convert this failed measurement into a
PASS. Workflow 001 continues with independent Stage 09 development-only work; no Stage 08 cell
will be retried in Build 001.
