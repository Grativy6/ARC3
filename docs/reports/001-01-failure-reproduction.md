# ARC3 Build 001 Stage 01 — local-public failure reproduction

- Stage status: **PASS**
- Evidence label: **local-public**
- Classification: **REPRODUCED_FAILURE**
- Frozen source: `75482a994c00123ddb3942663a2c521b710116c4`
- Holdout: **SEALED_UNCONSUMED**

The predeclared one-run development reproduction timed out after
`120.11965939996298` seconds and 21 environment actions, with zero completed levels. The matching
Build 000 run timed out after `120.110601900029` seconds and 19 actions, also with zero completed
levels. The wall-time difference was `0.009057499933987856` seconds and the action difference was
two, both inside the predeclared timing/action envelope. The Build 000 local-public pathology is
therefore reproduced on this bounded surface.

| measurement | Build 000 | Build 001 frozen reproduction |
|---|---:|---:|
| terminal status | timeout | timeout |
| wall seconds | 120.110601900029 | 120.11965939996298 |
| environment actions | 19 | 21 |
| completed levels | 0 | 0 |
| trace events | 759 | 617 |
| trace bytes | 1,679,940 | 1,545,054 |
| replay verified | yes | yes |

The reduced trace-event count is consistent with the later Build 000 production optimization that
batched component receipts; all five declared production-policy/runtime files match the final Stage
18 source byte-for-byte. Evaluation-only subset selection was added and tested before this run. It
is partition-bound, cannot select a holdout subset, and does not change policy behavior.

The generic evaluator labels an all-timeout evaluation `FAILED_INFRASTRUCTURE` and returns exit 1.
That aggregate status is preserved. It does not change the Stage 01 conclusion: the target of this
stage was the timeout pathology itself, and the sealed run receipt plus 56-artifact verifier prove
that pathology occurred. No scorecard was returned, so the recorded score is not an official RHAE.

## Evidence integrity

- Run receipt: `sha256:57a2686c51d87bedb80647c3fd820d34ec2ac09e3ba9dd853c7b12549d8aae34`
- Evaluation manifest file: `sha256:684cccf4731cf9e6163e51f121438fed4ba496bc9e6986ccb61aa4155b3592b4`
- Results JSONL: `sha256:a06e788f17800f1e7da7acf00fd32496ed4cb070d920398b8f356f1d56bb7ee2`
- Trace manifest: `sha256:2251e5061c981ba13fe2bd8378fd377bc76b71796e8321aca19e954322214770`
- Trace tail: `sha256:66def4f7b84d567031904c71d933c5a52b80c7f9b3f76d053a637bcf05e26e12`
- Exposure ledger: `sha256:25d86acbca2c4ab36945b602900f18b46ab7a6377e5a2b73c7053c202940fff8`
- Artifact verifier: **PASS**, 56 artifacts, one run, zero errors

The raw evidence is preserved at
`C:\a\arc3-b001\artifacts\stage01\evaluations\build001-stage01-ar25-seed7-full`.
Its two exposure events are both for the declared development run. There are zero holdout events
and zero locally acquired holdout assets.

One failed preflight is also preserved in the acceptance receipt: an incorrectly expanded expected
short SHA stopped before evaluator invocation or gameplay. The identity check was repaired by using
the exact `git rev-parse HEAD` value; it did not alter the frozen policy or consume another episode.

This one development-game result is local-public mechanism evidence only. It is not a public
holdout result, a benchmark claim, or evidence of hidden-game generalization.
