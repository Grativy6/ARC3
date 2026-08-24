# ARC3 Build 001 Stage 02 — hot-path observability

- Stage status: **PASS**
- Evidence labels: **synthetic**, **local-public**
- Frozen measurement source: `8168168ea224add5b8e296ee892866d75f1ca0b7`
- Holdout: **SEALED_UNCONSUMED**

The opt-in profiler preserved every seeded synthetic decision and outcome across seven alternating
enabled/disabled pairs. Its median wall overhead was 4.62%, below the predeclared 15% ceiling. The
enabled trials attributed at least 99.75% of their measured profiler lifetime to named phases; the
small residue is explicitly `runtime_remainder`.

The bounded local-public profile then ran FULL/B4 for exactly eight actions on the same declared
development game used in Stage 01. It terminated normally in 38.3345 seconds, produced a verified
scorecard with zero completed levels, and sealed a replay-verified 30-artifact bundle. This is a
diagnostic run, not evidence of recovery or a performance win.

| exclusive phase | wall seconds | share of measured wall |
|---|---:|---:|
| action selection | 18.4078 | 48.06% |
| checkpointing | 6.4991 | 16.97% |
| startup | 4.1514 | 10.84% |
| goal inference | 3.5324 | 9.22% |
| trace serialization | 2.3425 | 6.12% |
| perception | 0.9813 | 2.56% |
| retrodiction | 0.9015 | 2.35% |
| planning | 0.4232 | 1.10% |

The steady-state boundary snapshots are especially discriminating. Excluding the first action and
initial startup, median action-to-action wall time was 4.3411 seconds. Action-selection cost stayed
near 2.6 seconds, while checkpointing grew from 0.3469 seconds at action 2 to 1.2397 seconds at
action 8. Retrodiction grew from 0.0502 to 0.1943 seconds across the same interval. Planning itself
was only about 1.1% of total wall, contradicting a planning-search explosion as the primary cause
on this run.

Repeated-computation accounting found 51 observed input identities: 38 repeated and 13 unique.
There were 16 real content-addressed blob-cache hits, one miss, and 34 uncached computation
opportunities. Forty classified inputs were unchanged. These counts do not prove that every repeat
is safely cacheable; Stage 03 must use one-at-a-time interventions before changing semantics.

The result supports a causal-diagnosis order, not a repair conclusion:

1. split the broad action-selection envelope and test allocator tracing as a global multiplier;
2. bypass checkpoint writes one factor at a time while comparing exact action signatures;
3. test growing retrodiction and repeated goal/perception work separately;
4. retain planning as a measured secondary cost unless later interventions contradict this run.

## Evidence integrity

- Stage receipt: `docs/evidence/001-02-hot-path-observability.json`
- Synthetic raw file: `sha256:0c2b4137b1627ef1670709fa4bab2f3af77aae619066eab6d49f40d47e33b6c3`
- Synthetic self-hash: `sha256:97a8f4c136700164e6e17636361a0a19a406edb14a72f9d4426b2703cea0d2b5`
- Local-public run receipt: `sha256:306906edc7225359a885a04df6ac303c71207f50ce68058ff3da5baa16707275`
- Evaluation manifest file: `sha256:5c2dd60a893c1ec4f31d35902026b601100eb77c5a5bf1bc285485d24f151060`
- Results JSONL: `sha256:1b8b4738f5851670a2b7692023a92c028f0f7aa04c1c0f0d69e339bc735a17cf`
- Trace manifest: `sha256:4649079cbe7df02e1325eab0653aa1950758cfa940fdc4e53d4c4a3bef91862a`
- Trace tail: `sha256:a6966fd9ab957cc27d6d7f5a0c71e68a0febda3f570398231e4a5e859d37481e`
- Stage 02 exposure ledger: `sha256:646ce90008f66bf54dfafd4ce7b80274c9b35cf819b0bafdb7cdf4e06325b676`

The Stage 02 ledger contains two development events, zero holdout events, and no locally acquired
holdout assets. The frozen Build 000 exposure ledger remains byte-identical. Full phase data,
per-boundary snapshots, CPU time, RSS, cache counts, commands, runtime identity, and resolved test
failures are preserved in the machine-readable receipt.
