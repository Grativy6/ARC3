# ARC3 retirement verification seal

Status: **OWNER-AUTHORIZED PRE-ARCHIVE VERIFICATION**

Owner: **Christopher D. Pang**  
Verification date: **2026-09-02**

This record binds ARC3's public retirement transition to its preserved history and documents the repository controls observed before archival. It is a provenance receipt, not a safety certification, recall mechanism, or claim that earlier public copies can no longer be used.

## Commit and tree boundary

| Record | Identifier |
|---|---|
| Final active `main` commit before retirement | `16ecb87c04b8a4db214db12d13d8d1d672d5a254` |
| Final active tree | `790f4cab54cd9b65b59adf331dc583506f13fa0c` |
| Published retirement-transition preview commit | `933f977df6d068cb3ac611dff6fd09054bcd5541` |
| Retirement-transition tree | `402ec46923a57cb086aaf0d41de3735d40073d1d` |

The transition tree removes the active source, agent, scripts, tests, package metadata, environment/bootstrap configuration, and GitHub Actions workflows from the default branch. It retains historical reports and receipts with nonoperative archive warnings.

## File and digest verification

The transition was verified with the following results:

- 413 tracked paths containing active code or execution support were removed from the retirement-transition tree.
- 189 tracked paths remained in that transition tree.
- Zero tracked paths in that tree used these common runnable or packaged-artifact suffixes: `.py`, `.sh`, `.ps1`, `.ipynb`, `.whl`, `.zip`, `.tar`, `.gz`, `.7z`, `.exe`, `.dll`, `.so`, or `.jar`.
- `git diff --check` passed.
- `git fsck --strict` found no integrity error in a committed object.
- The public-ref and Actions artifact-and-cache manifests parse as valid JSON.
- A current-tree scan found no common private-key or access-token pattern. This bounded scan is not proof that no sensitive information exists in the full history or in every retained artifact.

| Preserved record | SHA-256 |
|---|---|
| Historical MIT-0 text | `7f433e520d07d56ad14d92e9da9f580771479c30a2bfccc8024eed308f21bbe8` |
| Retirement root license notice | `d0f7ae88809eef8231192c958c815b6a9164da3bc9cf623921338ac15ab0678e` |
| Pre-retirement public-ref manifest | `19590e13008e7f2acdee751028f8b12d00dff69013bea0c0df9c36dd003ceab0` |
| Pre-retirement Actions artifact-and-cache manifest | `53c7710147be85893fccf0a3b793620d3b911b3c802a85eed22ac5b615888ba5` |

## GitHub control verification

Before archival, the following repository settings and public surfaces were checked on 2026-09-02:

- Repository-level GitHub Actions execution was disabled. Four historical workflow registrations still appeared as `active` through the workflow API; there were zero queued or in-progress runs and 851 completed runs.
- Artifact and log retention for newly created objects was reduced to one day. GitHub states that retention changes are not retroactive.
- Issues, Projects, Wiki, and Discussions were disabled.
- Pull request #9 was closed without merge.
- At the authenticated point-in-time inspection, GitHub showed no repository webhooks, deploy keys, environments, Actions secrets, or Actions variables.
- No GitHub Pages site, release, tag, deployment, or visible package was present.
- Existing public branch heads and Git history remained visible as recorded in [pre-retirement-public-refs.json](pre-retirement-public-refs.json).
- The ChatGPT Codex Connector remained installed to complete the owner-authorized retirement publication and archival. It is a residual trusted integration, and its presence is not execution authority granted by this repository.

Archival is the remaining planned repository-state control after this seal is merged. GitHub archival makes the repository read-only, but an authorized owner can later unarchive it. A public archive remains visible and may remain cloneable or forkable.

## Residual Actions storage

At `2026-09-02T04:17:20.341378571Z`, GitHub still reported:

- 456 unexpired workflow artifacts totaling 5,126,957,453 bytes;
- SHA-256 digest metadata for all 456 artifacts;
- expiry dates from `2026-09-06T04:48:01Z` through `2026-09-14T20:51:12Z`; and
- two setup caches totaling 174,265 bytes.

Those objects were **not represented as deleted**. Their exact non-secret metadata is preserved in [pre-retirement-actions-storage.json](pre-retirement-actions-storage.json). This inventory covers API-reported artifacts and caches; it is not an exhaustive inventory of every workflow run or log surface. Artifacts may remain downloadable to people with repository read access until expiry or deletion. While Actions remains disabled, repository workflows cannot start new GitHub Actions runs; this does not erase prior artifacts or prevent execution from a fork, copy, or other environment. The one-day retention setting applies only to newly created objects.

## License and safety limit

This transition does not revoke or narrow MIT-0 rights already granted for historical snapshots. It reserves rights only in first-party retirement material and later additions unless a file expressly states otherwise. Third-party material retains its own terms.

Removing active code and workflow definitions from the default branch, disabling repository-level Actions execution, adding explicit safety boundaries, and archiving the repository remove first-party execution surfaces from the default branch and reduce accidental activation through the official repository. They cannot prevent a determined person from retrieving or using an earlier public copy. No repository state, license, receipt, benchmark result, or public availability creates consent, ethical approval, deployment authority, or authority to act for Christopher D. Pang or Branchline Systems.

See [RETIREMENT-LICENSE-DECISION.md](RETIREMENT-LICENSE-DECISION.md), [../../SAFETY.md](../../SAFETY.md), and [../../STATUS.md](../../STATUS.md).
