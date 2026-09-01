# Strongwiz clean-room ARC-AGI-3 protocol v0.1

Status: **FROZEN — NO ENVIRONMENT SESSION OPENED AND NO FRAME OR ACTION CONSUMED**

Experiment class: **community-style `local-public`, Codex-operated Strongwiz**

Claim ceiling: **no autonomous-agent, Kaggle, hidden-game, or official score claim**

## Frozen aperture

- Outer checkout: `C:\Users\cdpan\OneDrive\Documents\ARC3-Strongwiz` at setup commit
  `c01b37e961bf7396df8e6556200ab59743c850c5` before experiment implementation.
- Comparison base: `bea1eac99cb0f1b351526b1dc487d132ba1d40ef`.
- Strongwiz source: `Grativy6/strongwiz@6944642da7f4f3e6428a597587038c3b365074a5`,
  tree `f9097631fa5c6fb1dcce7756baaa290d76d22d92`, acquired only under this checkout.
- Exact source and license receipt:
  `docs/evidence/strongwiz-clean-room-source-pin.v0.1.json`.
- Official executable inputs remain `arc-agi==0.9.9` and `arcengine==0.9.3`; the three
  inherited official repository pins were reverified unchanged on 2026-09-01.
- Excluded: sibling checkouts, local user memory, Hearthline, Build 003/003w, Model Scientist,
  Wise Scientist, Little Scientist, prior solutions/replays/traces, human/public replays, ARC game
  source, and environment internals.

## Target and holdout boundary

The first run targets `ls20-9607627b`, which the frozen Build 000 partition manifest already marks
as **development** after its pre-manifest SDK exposure. It is therefore not claimed as a project
holdout. This context-isolated operator has not consumed a gameplay trace or game-specific rule for
it. The inherited ten-game `public-holdout` partition remains sealed and must not be acquired,
opened, inventoried semantically, or acted in during this experiment.

If `ls20-9607627b` cannot be acquired or executed through the pinned official public interface,
the run stops `BLOCKED_EXTERNAL` or `FAILED_INFRASTRUCTURE`; it does not substitute a holdout game.

## Policy and execution identity

Codex supplies one proposal at a time through a dedicated Strongwiz operator broker. The model
decision source is labeled `external-hosted-codex-operator`; it is not an offline autonomous model.
The ARC asset may be acquired through the pinned official public `NORMAL` path. Acquisition may
open and close one uninspected setup session if the official SDK requires it to materialize the
local asset. No setup-session frame, metadata, or gameplay consequence may reach the operator or
be reused as play evidence. After acquisition, exactly one measured play session is opened and
stepped locally with networking disabled. The receipt must distinguish:

- `policy_network_mode = external-hosted-codex-operator`;
- `environment_acquisition_network_mode = official-public-normal`;
- `environment_runtime_network_mode = offline-local`.

Strongwiz must bind the exact model-driver, domain-adapter, router, cadence, grant, lab decision,
proposal, action, executor, returned observation, and outcome. A single executor is the only code
path allowed to call the official session's `step` method.

## Runtime evidence and action rules

The operator may consume only runtime-returned frames, `state`, `levels_completed`, `win_levels`,
and `available_actions`. It may select only an exposed action, one at a time. `ACTION6` requires an
exact in-range coordinate. Each action receipt records a concise distinction, falsifiable
prediction, alternatives at summary level, selection, returned consequence, prediction match or
residual, and reopening/update; hidden chain-of-thought is neither requested nor stored.

`GameState.WIN` is the sole completion authority. `GAME_OVER` is failure; while it is current, the
only permitted next command is exposed `RESET`. A successful action does not rewrite its prediction
as prior knowledge.

## Frozen budgets and stopping rule

- non-RESET environment actions: **80-action measurement/checkpoint cadence**, with a declared
  safety ceiling of **4096**;
- RESET actions: **8-reset measurement/checkpoint cadence**, with a declared safety ceiling of
  **64**;
- measured-run wall time: declared safety ceiling of **9 hours**;
- coordinate candidates in any one operator decision: at most **24**;
- environment/runtime memory ceiling: **2048 MiB**;
- retained Strongwiz plus bridge evidence: at most **256 MiB**;
- action stopping: authoritative `WIN`; a stricter hard action boundary or unrecoverable terminal
  returned by the official environment; a declared safety ceiling; unrecoverable receipt or
  source-identity failure; unavailable official asset; or an unknown-effect executor failure.

Crossing an 80-action or 8-reset checkpoint is not a stopping condition. If no authoritative or
safety boundary has been reached, the same measured session continues one action at a time toward
all-level `WIN`. `GAME_OVER` is likewise not a terminal stop while an exposed `RESET` remains valid;
it is recorded as failure and followed only by `RESET`.

The inherited 240-second competition per-game wall envelope and 10-second autonomous decision
ceiling are recorded but are not expected to hold for a hosted, tool-mediated Codex operator. Wall
time is measured and reported rather than relabeled as competition-compatible.

## Current public-rules reconciliation

This is a deliberately narrow single-game development diagnostic, supported by the official local
starter's `make play-local GAME=ls20` path. It is not the official 110-game evaluation, a public
25-game suite result, a Kaggle submission, or a score directly comparable to either leaderboard.

The ARC-AGI-3 Technical Report describes an evaluator action budget of five times the human-baseline
median action count **per level**. The operator will not receive, derive, query, or inspect those
human baselines during play. After the measured session closes, the report may record that scoring
rule and any authoritative scorecard fields returned by the pinned runtime. The official Agents
repository's LLM template sets `MAX_ACTIONS = 80`, but that is a template/controller setting, not a
documented universal per-game terminal rule. The current public-runtime audit therefore does not
justify turning 80 into this experiment's stop. Any stricter hard boundary actually returned by the
pinned environment remains authoritative.

Primary public sources (accessed 2026-09-01):

- ARC-AGI-3 Technical Report:
  <https://arcprize.org/media/ARC_AGI_3_Technical_Report.pdf>
- official pinned Agents template:
  <https://github.com/arcprize/ARC-AGI-3-Agents/blob/4743e7d0aaae0ded0d98a89a7e282e63564cd58b/agents/templates/llm_agents.py>
- official pinned local starter:
  <https://github.com/arcprize/ARC-AGI-3-Kaggle-Starter/tree/eeb1535404f321d280a8f9194bbc1d7aca5f05fc>

## Predeclared result

- `PASS`: the single pinned official local measured session returns `GameState.WIN` before an
  authoritative or declared safety boundary and all Strongwiz/bridge ledgers verify.
- `PARTIAL`: no `WIN`, but the run has valid bounded action/consequence receipts and an authoritative
  terminal, official hard-budget, or declared safety-stop result.
- `FAILED_INFRASTRUCTURE`: a reproducible local bridge/tooling failure prevents a valid run.
- `BLOCKED_EXTERNAL`: the exact public asset or official interface cannot be obtained without a new
  credential, legal acceptance, paid service, or source-boundary crossing.

Completion, levels, environment actions, resets, wall time, and the pinned local scorecard are
reported separately. Official RHAE remains null unless an authoritative returned scorecard names
it explicitly.
