# Close the small gaps found before the agent of the unattended crawl is installed

Status: Proposed
Created: 2026-11-17
Candidate: none (corrections that follow from findings: the last security review of the assembled crawl, `2026-11-16-run-the-steps-of-the-unattended-crawl`, and the first supervised run)
Specs: docs/specs/population.md

## Goal

The first supervised run of the unattended crawl went well (two books filed, judged in and carded, nothing refused, the log and the queue compared the same). Four small gaps are known before the agent that starts a run every 15 minutes is installed. They are one plan, because **every change to the engine's code changes the fingerprint of the approved crawl plan, so each change costs the owner a new approval**: made together, they cost one.

1. **The agent cannot find `wb`.** The text of the launchd agent (`crawl-schedule-text`) sets no environment, so launchd gives the run its default `PATH` (`/usr/bin:/bin:/usr/sbin:/sbin`), and the engine's model calls (`models._launcher`, `shutil.which("wb")`) fail with "the workbench launcher (wb) was not found", which looks like a model that is down. On the owner's machine `wb` is outside that path.
2. **The text the owner reads before approving a plan is stale.** `crawl-approve` says "or the model server down N minutes"; the breaker's limit is now counted for each model entry (`2026-11-17-see-when-a-model-of-the-unattended-crawl-is-down`).
3. **The index folder is not checked.** The run lock (`crawl.lock`) and the stop file (`crawl.stop`) live in the index root, and the files are checked but their folder is not: unlinking the lock while a run holds it lets a second run start, and the stop file can be removed, by another account with write access to that folder.
4. **A redirect can use another site's day.** A hop of a redirect to a site other than the first is charged to that site's unit of the day (`crawlstate.charge_hop`). A hostile candidate with three hops to one site takes that site's whole `per_domain_per_day` for the day, so its real candidates are skipped; a site that answers 403 to those hops gets refusals counted too, and three of them stop it for the day. It is a loss of availability only.

When this plan is done: the text of the agent sets a `PATH` that holds the folder of `wb`; the plan summary says the model entry; a run is refused when the index folder is not the owner's or can be written by others; and a redirect cannot take a unit of another site's day that a real candidate would have used.

## Scope

**Changed:** `engine/kb/crawlschedule.py`, `engine/kb/__main__.py` (the argument of `crawl-schedule-text`), `engine/kb/crawlapprove.py` (one sentence), `engine/kb/crawlguard.py` and `engine/kb/crawlrun.py` (the check of the index folder, and its line in the dry run), `engine/kb/crawlstate.py` and `engine/kb/crawlfetch.py` (the hop charge), their tests, `README.md` (the step of the agent and the known limits) and `docs/specs/population.md` (where it states what is built: scheduling, the run's checks, the per-site count).

**Not changed:** the steps, the judgement, the models, the plan's keys, the log, the queue's shape, `crawlstatus.py` and `crawlreport.py`.

## Non-goals

- A limit of the memory of the converters, the sweep of old leftovers of `incoming`, the card step's look at the stop file inside a pass, and the other items of the todo list: none of them is needed for the agent.
- Installing the agent. That is the owner's act, after this plan, after approving the crawl plan again, and after a few supervised runs.
- A check of the agent under launchd. The text can be tested; whether launchd finds `wb` with the path in the text is shown only by the owner running it once and reading `crawl-agent.log` (the README's checklist says so).

## Assumptions and constraints

- The plan of the crawl is approved against a fingerprint of the engine's code and the model settings; any change here makes `crawl-run` refuse until `crawl-approve` is run again by the owner. The owner's approval of the crawl plan is his act, and this plan does not make it.
- `crawl-schedule-text` prints only: the module reads no environment variable and starts no process. The folder of `wb` is found by the command in `__main__` (`shutil.which("wb")`, in the owner's own shell, when he prints the text) or is given by an argument, and is passed to the module as text, as the other paths are.
- The check of the index folder must not refuse the owner's own setup: a folder that the owner owns, that others cannot write. Its mode may be 755 (read by others) as it is now.
- No test uses the network, a model, the owner's library, config or plan.

## Completion criteria

1. `crawl-schedule-text` prints an `EnvironmentVariables` entry `PATH` that holds the folder of `wb` (found, or given by `--path`) before `/usr/bin:/bin:/usr/sbin:/sbin`; a folder that is not a plain full path is refused; when `wb` is not found and no path is given the text says so in a comment and sets no `PATH`.
2. The plan summary names a model entry, and no longer says "the model server down N minutes".
3. A run whose index folder is not owned by the user, or can be written by group or others, is refused (exit 3) with a fixed text before the lock is taken; the dry run shows the check; the owner's own folder (owned, mode 755 or 700) passes.
4. A hop of a redirect cannot take a unit of the site's day that fetches of real candidates use: a candidate with hops to a third site leaves that site's `per_domain_per_day` for its own candidates, and a hop to a site that is stopped for the day, or whose hops have reached their own limit, is refused.
5. `wb run code-work check` passes; the tests of the modules changed pass.
6. The owner has read the result.

## Increments

### Increment A — The text of the agent sets a `PATH`

**Outcome:** the text of the agent holds the folder of `wb` in its `PATH`.
**Dependencies:** none.
**Affected areas:** `engine/kb/crawlschedule.py`, `engine/kb/__main__.py`, `engine/tests/test_crawlschedule.py`, `README.md`.
**Steps:**
1. Read `crawlschedule.text`, its checks of a path (`_folder`, `_checked`), the command in `__main__` and the tests, and `models._launcher`.
2. Tests first: `text(index, engine, python, path_dirs)` with a folder gives an `EnvironmentVariables` dict with `PATH` = that folder, then `/usr/bin:/bin:/usr/sbin:/sbin`; no folder gives a comment that says `wb` was not found and no `EnvironmentVariables`; a folder that is relative, empty, has a control character or a colon, or is `.` or `..` in a part, is refused with a reason that does not show it; the text stays valid XML (the escape of `&`, `<`, `>`); the module reads no environment variable and starts no process (the existing test of that); the command passes `--path` when given and else the folder of `wb` found by `shutil.which`.
3. Write the change; deliberate breaks; the `reviewer`'s reading; the Result. The README's step of the agent says to check `crawl-agent.log` after the agent's first firing, and that `--path` sets another folder.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlschedule`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-17-close-the-small-gaps-found-before-the-agent-is-installed#A`.

### Increment B — The plan summary names the model entry

**Outcome:** the breaker line of the summary is true of what is built.
**Dependencies:** none.
**Affected areas:** `engine/kb/crawlapprove.py`, `engine/tests/test_crawlapprove.py`.
**Steps:**
1. Read the summary's breaker line and the tests that quote it.
2. Tests first: the line says "or a model entry that has not answered for N minutes" and not "the model server down"; the digest of the summary changes only through the text (a plan with the same keys still has one digest for one text).
3. Write the change; deliberate break; the `reviewer`'s reading; the Result.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlapprove`; the break; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#B`.

### Increment C — A run is refused when its index folder is not the owner's

**Outcome:** the lock and the stop file are in a folder that only the owner can change.
**Dependencies:** none.
**Affected areas:** `engine/kb/crawlguard.py`, `engine/kb/crawlrun.py`, `engine/tests/test_crawlguard.py`, `engine/tests/test_crawlrun.py`.
**Steps:**
1. Read `crawlguard.acquire_run_lock`, `stop_requested`, `crawllog._private_dir` (which checks the folder `crawl/` the same way) and the order of the run's checks (`crawlrun._checks`, the dry run).
2. Tests first: `check_index_root(path)` passes a folder owned by the user with no write bit for group or others (mode 700 and 755), and refuses with a fixed text (no path in it) a folder that is owned by another user, one with a write bit for group or others, a path that is a link, and one that is not a folder; a run with a bad folder exits 3 before the lock is taken and writes nothing in it; the dry run says so on its line; a good folder gives the run as before.
3. Write the change (the check comes first, before the lock); deliberate breaks; the `reviewer`'s reading; the Result.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlguard engine.tests.test_crawlrun engine.tests.test_crawlchain`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#C`.

### Increment D — A hop of a redirect is not charged to another site's day

**Outcome:** a hostile redirect cannot use another site's `per_domain_per_day`.
**Dependencies:** none.
**Affected areas:** `engine/kb/crawlstate.py`, `engine/kb/crawlfetch.py`, `engine/tests/test_crawlstate.py`, `engine/tests/test_crawlfetch.py`, `docs/specs/population.md`.
**Steps:**
1. Read `crawlstate.charge_hop`, its caller in `crawlfetch._Run._policy`, `reserve`, `refusals_today` and the tests of the hops.
2. **The rule:** a hop is **checked** against the site's own day as now (refused when the site is stopped for the day or when its fetches of real candidates are at `per_domain_per_day`), but is **counted apart**, in a counter of hops for that site (`hop:<site>`, with the same limit `per_domain_per_day`), and not in the counter that `reserve` reads (`fetch:<site>`). A hostile redirect can then use up the hop count of a site, which refuses more hops to it that day, and cannot use a unit that a real candidate would have used. A refusal that the site answers to a hop still counts as the site's refusal, as now.
3. Tests first: three hops to one site leave that site's `reserve` as before (its `per_domain_per_day` units of real candidates remain) and the fourth hop is refused as at its hop limit; a hop to a site that is stopped for the day is refused; a hop to a site that is at its limit of real fetches is refused; the counters of two sites are independent; a real candidate's first request is counted as before; the day's total `fetches_per_day` is unchanged by hops (as now: hops are not a fetch of a candidate).
4. Write the change; deliberate breaks; the `reviewer`'s reading; the Result; the spec's sentence about the per-site count says what is built.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlstate engine.tests.test_crawlfetch engine.tests.test_crawlchain`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#D`.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later one changed its inputs. At the end the tests of the six R1 modules, `test_crawlfetch`, `test_crawlsteps`, `test_crawlcards`, `test_crawlmove`, `test_crawljudge`, `test_crawlschedule`, `test_crawlapprove`, `test_crawlreport`, `test_crawlstatus` and `test_crawlchain` are rerun together, because C and D change code that all of them read; `wb run code-work check` is run; a read-only check shows that no file outside "Scope" changed. The engine's whole suite is not rerun unless the owner asks. **After this plan the owner approves the crawl plan again** (`crawl-approve`), because the code fingerprint changed.

## Risks and sensitive actions

- **A network boundary and the filesystem are touched** (the hop accounting of the fetcher, the check of the index folder): the owner is asked whether to run a security review over the changes once D is done; none runs unless he asks.
- **A wrong check of the index folder could refuse a run on the owner's own setup.** The criteria say the owner's own folder (owned, 755 or 700) passes, a test covers it, and the dry run shows the check before a real run.
- **A `PATH` in the agent's text is code that launchd runs with.** The folder is the one that holds `wb`, found in the owner's shell, shown in the text the owner reads before he installs it; nothing is installed by this plan.
- The change of the code makes the approval of the crawl plan stale: the runs refuse until the owner approves again, which is his act.

## Review record

Empty until a review is asked for.

## Deferred work

The memory limit of the converters, the sweep of `incoming`, the card step's stop file inside a pass, the small leftovers of the review (a probe that raises, a restarted guard state logged by each step) and the flaky tests are left in the owner's todo list.

## Result

### Increment A — The text of the agent sets a `PATH` (committed `91e5646`)

- Changed `engine/kb/crawlschedule.py` (`SYSTEM_PATH`, `_wb_folder`, `text(..., wb_dir=None)`, the comment lines and the `EnvironmentVariables` entry), `engine/kb/__main__.py` (the argument `--path` of `crawl-schedule-text`, and the lookup of `wb` with `shutil.which` when it is not given), `engine/tests/test_crawlschedule.py` and `README.md` (step 7 and the bullet "The same `wb` under the agent"). Verification: `test_crawlschedule`, 59 tests, OK; `wb run code-work check` and `git diff --check` clean.
- **What it does.** The text sets one environment variable, `PATH`: the folder of `wb`, then `/usr/bin:/bin:/usr/sbin:/sbin`. The folder is **found by the command, in the shell of whoever prints the text** (`shutil.which("wb")`, made full with `abspath`, not resolved through a link), or **given by `--path`**; the module itself still reads no environment variable, opens no file and starts no process (its purity test passes unchanged); it takes the folder as text. A folder that is not text, is relative, has a control or invisible character, `--`, a colon or a `.`/`..` part is refused (exit 2, no text, the reason does not show it). With no `wb` found and no `--path` the text says so in a comment and sets no `PATH`. The comment names the folder and says to read `crawl-agent.log` after the agent's first firing; it has no two hyphens in a row (invalid in an XML comment: found when the first wording had `--path` in it).
- Deliberate breaks: 18 single mutations of `crawlschedule.py` and `__main__.py`; one survived (the wording "After the agent's first firing"), closed by an assertion and killed.
- Review (`reviewer`, one exchange): no blocking finding. **Applied:** one sentence in the README: **`wb` is itself a script that starts `python3`, and under the agent that is the first `python3` on the agent's `PATH` (`/usr/bin/python3` unless the folder of `wb` holds another), which may not be the Python of the owner's shell**; and that a folder name with two hyphens or a colon is refused. **Recorded:** (1) **not verified under launchd** (which environment launchd adds, and how it resolves `python3` in `ProgramArguments`): the owner reads `crawl-agent.log` after the first firing; (2) **security:** the folder is put first, so whoever can write it decides which `wb` and which programs the agent runs; the owner sees it twice (the comment and the `PATH` string) before he installs, and on this machine it is his own folder; (3) a `wb` in a folder whose name has two hyphens makes the command refuse, and `--path` cannot fix it (the same check): kept, as a fallback would hide the cause.
- Not run: the rest of the engine's tests.

### Increment B — The plan summary names the model entry (committed `874592d`)

- Changed `engine/kb/crawlapprove.py` (one sentence of the summary) and `engine/tests/test_crawlapprove.py` (two tests). The line "or the model server down N minutes" became **"or a model entry that has not answered for N minutes"**, N being the plan's own `model_down_minutes`. Verification: `test_crawlapprove`, 64 tests, OK; `wb run code-work check` and `git diff --check` clean.
- Tests first: one renders a real summary and asserts the exact new clause, the next clause intact and the old phrase absent; one sets `model_down_minutes = 45` and asserts the 45 comes from the plan. Three mutations of the line (the unit, another key, the old wording) were all killed.
- Review (`reviewer`, one exchange): no blocking finding. **The sentence is true of what is built:** `note_entry` keeps one clock for each entry and trips `model_down` over the limit; the card embedding (the entry of `card-embed`) is itself a model entry whose clock the start of a run keeps (`note_model`) with the same threshold and the same trip kind, so "a model entry" covers every trip of that kind. **Recorded:** (1) the reason string that the card-embed clock writes to the breaker still says "the model server has not answered" (not part of the summary); (2) the summary's breaker line never names the `stage_bound` trip, an omission that was there before; (3) **the digest:** `summary.txt` is stored with an approval but is not hashed, so the new sentence does not change the digest of an unchanged plan by itself; **but `crawlapprove.py` is engine code, so the code fingerprint changed and the owner's approval (`f03894c43a91`) is stale (it already was, since Increment A): he approves again with `crawl-approve` after Increment D**.
- Not run: the rest of the engine's tests.

### Increment C — A run is refused when its index folder is not the owner's (verified, not committed)

- Changed `engine/kb/crawlguard.py` (`index_root_problem`), `engine/kb/crawlrun.py` (`run`, `_dry_run`), `engine/tests/test_crawlguard.py` (the class `IndexRoot`, 8 tests) and `engine/tests/test_crawlrun.py` (5 tests in `Refusals`). Verification: `test_crawlguard`, `test_crawlrun`, `test_crawlchain` and `test_crawlstatus`, 597 tests, OK (275 for the first three after the last change); `wb run code-work check` and `git diff --check` clean. **The function is `index_root_problem(path)`, which returns the reason as text or `None`, where the plan's step 2 says `check_index_root(path)`: a naming difference, not one of behaviour.**
- **What it does.** The check refuses an index folder that is not a real folder (a link, a file or a missing path), that is not ours (`st_uid` against `getuid`, as `crawllog._check_file` does), or that group or others can write (`mode & 0o022`; 1777 too). Modes 700, 755, 750 and 711 pass; the owner's own folder (a real directory, his, mode 755) passes. The reason names no path. It reads nothing from the folder and writes nothing. In `run()` it comes **before** the log object and the lock: a refusal is **one `refused:` line on the warn stream and exit 3, with nothing written into the folder, and so no line in the crawl's log** (the folder cannot be trusted with it); a test compares a snapshot of the folder before and after, and shows that the lock was not asked for. In the dry run it is on the line of the run lock (`CHECKS` is unchanged, a test pins it): a good folder says "the index folder is yours and others cannot write it; the lock is not taken in a dry run (...)", a bad one says "would refuse" and the checks after it are "not reached", as for any refusal; the dry run still writes nothing.
- **A trailing slash.** The review found that `lstat("link/")` follows the link, so a link written with a slash at its end would not have been refused; the check now takes the name without the trailing slashes, and two tests (a link with one and with two slashes; a good folder with one still passes) show it.
- Deliberate breaks: 15 single mutations of the check, `run()` and the dry run, and 2 of the slash; one survived the first 15 (a blank path, which is refused either way because `lstat` fails: equivalent) and one the last 2 (`rstrip("/")` without the `or "/"`: the path `/` is root's and is refused as not ours: equivalent for a normal user).
- Review (`reviewer`, one exchange): no blocking finding; criterion 3 met. **Applied:** the trailing slash. **Recorded, not covered:** (1) **the parent folders**: another account that can write the parent of the index folder could rename it and plant its own after the check; low on a home folder (mode 700 or 755), and beyond this plan; (2) **ACLs**: only the mode bits are read (a macOS ACL entry that grants write to another account is not seen), as `_check_file` also does; (3) a link earlier in the path is followed, as the system does; the final component is what is refused; (4) the owner and root as actors are outside the threat. **Checked as sound:** nothing writes into the index folder before the check (the log is written lazily, `config.load` writes nothing, `run_unattended` only builds the steps); the stop file, the breaker and the guard state are covered by the same fix for the replace-the-name attack, and their own files are checked for owner, mode and type already.
- Not run: the rest of the engine's tests.
