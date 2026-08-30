# Wise Scientist local playground

This directory is the disposable scratch area for the Wise Scientist clean-room experiment. The
repository containing it is the outer project boundary.

## Conditional authority

Reading this file or repository does not authorize modification. A system may build, run, or write
only when an active owner instruction explicitly directs it to perform that work in this checkout.
A system with read-only authority must remain read-only.

## Boundary for an authorized builder

First resolve the repository root with `git rev-parse --show-toplevel`. For the requested checkout,
the expected root is:

```text
C:\Users\cdpan\OneDrive\Documents\ARC3-Wise-Scientist
```

Treat that resolved root as the complete writable playground:

1. Do not create, edit, move, or delete project or task-generated files outside it.
2. Do not enumerate, inspect, copy from, or modify sibling ARC3 repositories or worktrees.
3. Do not fetch, inspect, or import Build 003, its pull request, implementation, ledgers, reports,
   traces, recordings, checkpoints, replays, or learned game-specific state.
4. Keep the environment and generated state local. Use repository-local locations such as `.venv/`,
   `.cache/`, `.uv-cache/`, `.pytest_cache/`, `.arc3/`, `artifacts/`, `recordings/`, and this
   `playground/` directory.
5. Put arbitrary temporary files under `playground/tmp/`. Redirect tools that normally write to a
   user or system temporary directory when that is feasible.
6. Installed operating-system tools and explicitly authorized public services may be read or
   executed, but they must not be used to retrieve prior ARC3 experiment state or to place
   task-generated project state outside this repository.
7. If a necessary operation would cross this boundary, stop before crossing it and report the exact
   requirement to the owner.

Normal source, test, documentation, and evidence changes may be made elsewhere inside this
repository when the active task authorizes them. This directory is for scratch state; it is not a
restriction that all committed source code must live here.

## Clean-room identity

```text
experiment branch: experiment/003w-wise-scientist-clean-room
comparison base:   bea1eac99cb0f1b351526b1dc487d132ba1d40ef
relationship:      sibling of Build 003, not a descendant of Build 003
```

Preserve that relationship until the Wise Scientist run and its final receipt are frozen. Compare
against Little Scientist only afterward, from a separate evaluation context.
