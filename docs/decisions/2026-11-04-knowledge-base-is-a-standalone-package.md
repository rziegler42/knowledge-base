# The knowledge base is a standalone project with a thin workbench package

Status: Accepted by Robert Ziegler <25854477+rziegler42@users.noreply.github.com> on 2026-11-04

## Context

The knowledge base is a personal library of outside information that agents in workbench projects search. Its design is in
`docs/specs/knowledge-base.md` and the specs beside it. Two questions were open: whether it is built as a separate project that
the workbench installs as an external package, or inside the project-workbench repository, and whether the library can build out
on its own while the owner is away.

What bears on the choice:

- The workbench's spec `knowledge-tools.md` (status Current) names the knowledge base as the third of three knowledge modules and
  leaves its name and package open, so it does not require either route.
- The workbench installs packages from a local directory or a git URL: `--package <source>` on install, and `approve --source
  <url> [--ref]` to fetch and approve one. A local directory is used as it is, and the approval gate still applies to it.
- `module-boundary.md` keeps the installer to mechanism only and puts everything specific to one module in that module's own
  directory. The knowledge base brings a long-running engine (a library on disk, a crawler, a pipeline, its own tests and
  experiments), which is much larger than any module in the workbench's `packages/` today.
- Building the library unattended needs a program that runs on a schedule. An agent session cannot do that, because agents stop at
  the workbench's checkpoints. The engine therefore runs as its own program, and the small piece that lets a project agent search
  and read the library is the only part that is a workbench package. The engine is not free of the workbench, though: the design
  routes its model calls (cards, neutral descriptions, themes, judging) through the workbench's model bridges (`models.md`), so
  an unattended run depends on a scheduled program being able to call a bridge through `wb run`. That is not yet shown.
- The owner wanted to test the workbench's external-module path, and leans toward a standalone project.

## Decision

The knowledge base is a standalone project in its own repository (this one). It has two parts:

1. **The engine**, a standalone program that holds the library and does the work (loading books, the pipeline, search and, later,
   the crawler). Loading, conversion and keyword search do not depend on the workbench. Its model calls go through the
   workbench's model bridge, so the engine depends on the bridge for those stages.
2. **A thin workbench package**, kept in this repository and installed into projects with `--package` from a local directory. It
   declares what the workbench needs and offers a small set of commands to a project's agents (to begin with, search and read).

This decision is checked before anything is built on it by a **stub gate**: a throwaway package with one command that returns a
fixed answer, installed into a project with `--package` from a local directory. The gate must show that the package installs and
passes approval, that the command runs through `wb run`, and that the package can require `model-bridge` from a package inside the
workbench repository. A second part of the gate tests the unattended path the engine needs: a scheduled program, started with no
terminal and no agent session, calls the bridge through `wb run` for one short chat and one embedding, and the result comes back
usable. If the first part fails for a reason that cannot be fixed on this side, the first fallback applies. If the second part
fails, the second fallback applies.

**First fallback (package).** Only the thin package directory moves into `project-workbench/packages/`. The engine stays here, and
no other part of this decision changes.

**Second fallback (unattended model calls).** The stages that need a model run only when the owner starts them in a session where
a bridge can be called, and the engine's other work (loading, conversion, keyword search) still runs unattended. The engine does
not call the model server directly under this record. A direct route would need a new decision that supersedes or amends this
one, because it sends content to a model outside the workbench's permission model.

This record does not decide the package's name, the commands beyond search and read, how the unattended call is arranged if the
gate shows it can be made, or the build order. Those are separate.

## Alternatives considered

- **A module inside the project-workbench repository.** Rejected for now. It has the least installation friction and keeps the
  bridge in the same tree. But it puts a large engine, its specs and its experiments in the installer's repository, and joins the
  histories and review of two projects. It also gives up the owner's wish to test the external path. It remains the fallback for the
  thin package, which is cheap to move.
- **No workbench package: agents call the engine's command line directly.** Rejected. Project agents would then reach the library
  outside the workbench's permission model, approvals and the launcher, which is the opposite of the intent that the library's
  contents are data and reached through a governed command.
- **Decide later.** Rejected because the layout of the repository, the specs and the build order depend on it. The stub gate keeps
  the cost of being wrong low.

## Consequences

Good:

- The engine, its specs, its tests and its experiments stay together in one history, and are reviewed on their own terms.
- The unattended builder is an ordinary program, with no dependence on agent checkpoints, if the gate shows it can call a bridge
  without a terminal. If it cannot, only the model stages need the owner present.
- The workbench's external-package path gets a real test, as the owner wanted.
- The fallback is a directory move, so the decision is cheap to reverse.

Bad or unknown:

- Each change to the package needs a new approval and a new pin in every project that installs it, which adds friction compared
  with a package inside the workbench.
- Whether a package outside the workbench repository can require `model-bridge` from a package inside it is unverified.
- Whether a scheduled program with no terminal can call the model bridge through `wb run` is unverified. If it cannot, the engine
  may have to call the model server directly, which this record does not allow without a new decision.
- The package is tested by the workbench's checks only after it is installed, so some breakage would show late.
- A git URL source needs the remote to hold commits, and pushing needs the owner's approval. A local directory source needs none.
- The workbench may change its package contract, and this project would have to follow.

## Evidence

- Source: the project-workbench repository, `git@github.com:rziegler42/project_workbench.git`, commit
  `23302cdfbf2a084beb2adfd2ce03d24594a6863e`, retrieved 2026-11-04. The three files below had no uncommitted changes at that
  commit (`git status` printed nothing for them). I read them earlier the same day, and their hashes were taken afterwards, so a
  change between the reading and the hashing is not excluded.

  | File in that repository | sha256 | What it was read for |
  |---|---|---|
  | `docs/specs/knowledge-tools.md` | `25260999dd416899c906cf0c554bbe1629f62dfb3fa350b0a2f037df734f480a` | Status Current; names the knowledge base as the third knowledge module, with name and package open |
  | `docs/specs/module-boundary.md` | `af4c1571667eecb9fd4a5f60bd0b83da2e17972541da8dfe16c00d1e776b571a` | The installer keeps mechanism only, and module-specific content lives in the module |
  | `workbench/sources.py` | `c9316af563bf210f5e01034315aeb738c3fe5e3465abcd9da85e0a19634c1f12` | Its module docstring: a local package directory is used as it is, and a URL or local repository must already be in the cache after `approve --source` |

  The conclusion is that an external package is supported by the installer's design, not that it works for this project.
- The stub gate has not been run. This repository has no commits at the time of writing, so there is no commit to cite.

## Note, 2026-11-04: stub gate results

Added at the owner's approval. The text above is unchanged. The line "The stub gate has not been run" in Evidence was true when
the record was accepted and is no longer current.

- **What was run.** A throwaway package `kbstub` with one module `kb-stub` was approved by the owner, then installed from a
  local directory with `--package` into a scratch project, alongside `workbench/claude`, `ask-ollama`, `groundwork`, `code-work`
  and `safe-git` from the workbench's own package. The module provides `kbstub:knowledge-search` and requires `model-bridge` and
  `text-embedding`. Its files had these sha256 values: `package.json` `21e4016f2c9eb7fffd09ae8d04828698afe084d0d5b823b55b3699cdef5db92c`,
  `kb-stub/module.json` `dc35201d6cfa5837bc617906d6b48502e2f4f3a12dc194816e7c8f1c8e8ee0ad`, `kb-stub/helper/kb-stub`
  `d1aee3755de85cae759e9c38b2175a5fc43a3b2f896feccc280359e5c8f8e085`. The stub is not kept in this repository.
- **Workbench version.** The project-workbench checkout was at commit `230fafaf38dd2f42920aac1388cfce3dc1a3ceb1` with
  uncommitted changes in its working tree, so the run is not tied to a clean commit. It differs from the commit cited above.
- **Part 1 result (package route): passed.** Install passed approval. `wb run kb-stub search anything` returned the fixed answer.
  `wb run --provides kbstub:knowledge-search kb-stub ping` made one short chat call and one embedding call (dimension 768) through
  the bridge, and both succeeded. The `requires` resolved to `workbench/ask-ollama`, a package inside the workbench repository.
- **Part 2 result (unattended path): passed in a stand-in, not shown for a real scheduled launch.** A script started the same
  ping with input from `/dev/null`, a minimal environment and a new session, and no terminal. It exited 0 in 1.4 seconds with
  both calls succeeding. It ran from an agent session on the owner's logged-in machine, so a launchd or cron start, or a start
  with no login session, was not tested. Script sha256 `45856b38a9cbe31c57c5c34a78bf400a628c6037764cd8b3db3a9a581628bafa`.
- **Conclusion.** Neither fallback is triggered by these results. The remaining unverified item is a real scheduled launch.
- **A consequence for the package.** A package outside the workbench cannot provide an unprefixed capability. Its capability
  names take the form `<package>:<name>`, so the real package's names are chosen with a prefix.

### Follow-up to the note above: launchd run

- **What was run.** The owner started the same script as a one-shot launchd job with `launchctl submit`, then removed the job with
  `launchctl remove`. The script's result file had been deleted beforehand, so the file read afterwards was written by that job.
- **Result: passed.** The job exited 0 in 1.5 seconds. The ping's chat call and embedding call (dimension 768) both succeeded
  through `wb run`, with no terminal (`had_tty` false). The job's output and error files were empty. The job no longer appears in
  `launchctl list`.
- **Limits.** A user-session launchd job still runs while the owner is logged in on the machine. A start with no login session
  (for example after a reboot before login), a cron start and a run while the model server is down were not tested. The bridge's
  retry and failure behaviour under those conditions is not shown.
- **Conclusion.** The second part of the gate is satisfied for a scheduled start in the owner's session. The unattended builder
  needs no fallback under this record, subject to the limits above.
