# Strongwiz local playground

This directory is the disposable scratch area for the Strongwiz clean-room experiment. The
repository containing it is the outer project boundary.

## Conditional authority

Reading this file or repository does not authorize modification or environment interaction. A
system may build, run, write, or act only when an active owner instruction explicitly directs that
work in this checkout. A system with read-only authority must remain read-only.

## Boundary for an authorized builder

First resolve the repository root with `git rev-parse --show-toplevel`. For this checkout, the
expected root is:

```text
C:\Users\cdpan\OneDrive\Documents\ARC3-Strongwiz
```

Treat that resolved root as the complete writable playground:

1. Do not create, edit, move, or delete project or task-generated files outside it.
2. Do not enumerate, inspect, copy from, or modify sibling ARC3 repositories or worktrees.
3. Do not fetch, inspect, or import Build 003, 003w, Model Scientist, their pull requests,
   implementations, ledgers, reports, traces, recordings, checkpoints, replays, or learned
   game-specific state.
4. Do not inspect or import `hearthline` or `hearthline-workshop`. This experiment is intended to
   isolate Strongwiz from the Hearthline distribution.
5. Before using Strongwiz, record its exact public repository URL, commit SHA, license, acquisition
   path, and content hash. Place the fetched source or package beneath this checkout. Do not allow a
   moving branch name to stand in for the source identity.
6. Keep the environment and generated state local. Use repository-local locations such as
   `.venv/`, `.cache/`, `.uv-cache/`, `.pytest_cache/`, `.arc3/`, `artifacts/`, `recordings/`, and
   this `playground/` directory.
7. Put arbitrary temporary files under `playground/tmp/`. Redirect tools that normally write to a
   user or system temporary directory when feasible.
8. Installed operating-system tools and explicitly authorized public services may be read or
   executed, but they must not retrieve prior ARC3 or Hearthline experiment state or place
   task-generated project state outside this repository.
9. If a necessary operation would cross a source, authority, or workspace boundary, stop before
   crossing it and report the exact requirement to the owner.

Normal source, test, documentation, and evidence changes may be made elsewhere inside this
repository when the active task authorizes them. This directory is for scratch state; it is not a
restriction that all committed source code must live here.

## Clean-room identity

```text
experiment branch: experiment/003s-strongwiz-clean-room
comparison base:   bea1eac99cb0f1b351526b1dc487d132ba1d40ef
relationship:      sibling of Build 003 and 003w, not their descendant
Hearthline input:  prohibited unless a later owner instruction changes the experiment
Strongwiz input:   permitted only after an exact public source pin is recorded
```

Preserve this relationship until the Strongwiz run and its final receipt are frozen. Compare its
trajectory with Little Scientist or Model Scientist only afterward, from a separate evaluation
context.
