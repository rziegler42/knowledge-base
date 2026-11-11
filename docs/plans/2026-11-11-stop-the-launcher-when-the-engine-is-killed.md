# Stop the launcher when the engine is killed

Status: Proposed
Created: 2026-11-11
Candidate: none (a correction that follows from Low finding 1 of the security review recorded in the Result of 2026-11-10-pose-a-problem-to-the-search-by-meaning.md)
Specs: models

## Goal

A model call made by the engine leaves nothing running when the engine is killed. Today `models._run` starts the launcher (`wb`, and the bridge it starts) in a session of its own and kills that process group only when the call overruns or prints too much. When something else kills the engine first, `_run` never reaches its kill. The case that was found: the `kb` helper stops `problem-search` at 60 seconds and kills the engine's process group with SIGKILL, so the launcher and the bridge go on until the embedding entry's own timeout (600 seconds by default, plus a grace period). An agent that calls `problem-search` again and again can leave several such calls running on the owner's machine and server. Nothing leaves the owner's server; the harm is to availability.

When the plan is done, a launcher started by `models._run` is killed with everything it started when the engine dies in any way (a signal that cannot be caught included) once the watchdog is ready, and a normal call behaves as before. The guarantee starts when the watchdog says `ready`. Between the start of the launcher and that word (the watchdog is started at once after the launcher, so this is a few milliseconds) no process but the engine knows the launcher's group, and an engine killed in that window leaves the launcher as it does today, to the entry's own timeout. This is the same window that the converter's watchdog has, and it is stated here and not closed; closing it would need a wrapper that starts the launcher itself, which is a larger change than the finding that led to this plan.

## Scope

- `models._run` starts the existing watchdog `engine/kb/supervisor.py` beside the launcher, as `convert_run` does for a converter: the watchdog holds the read end of a pipe to the engine and kills the launcher's process group if the pipe closes without the word "done", or after a time slightly longer than the call's own limit.
- A call whose watchdog did not start and say `ready` is stopped, as in `convert_run`: the launcher must not run unguarded.
- A test that starts a call with a fake launcher that starts a child and waits, kills the engine process with SIGKILL, and shows that the launcher and its child are gone; seen failing before the change.
- One line in the engine README, and in the models spec if it states how a call is stopped, saying that a launcher cannot outlive the engine.

## Non-goals

- Changing the `kb` helper, its 60-second limit, or `helper.json`. The helper's kill of the engine's group is correct; the leak is in what the engine started.
- Changing the config, the `timeout` of any entry, or what is sent to a model. I never write the owner's config.
- Changing `supervisor.py` unless a step below shows it cannot be reused as it is. If it must change, stop and ask, because the converter also relies on it.
- Any other finding of that security review.
- A change to how `wb` or the bridge behave inside the launcher's group.

## Assumptions and constraints

- The launcher is started with `start_new_session=True` (`engine/kb/models.py`, `_run`), so its process group id is its pid and `os.killpg(pid, SIGKILL)` reaches `wb`, the bridge and what they started, unless one of them leaves the group itself. A process that makes its own session is out of reach of this plan and of the converter's watchdog alike; that limit is recorded, not solved.
- The watchdog is started in its own session, so the helper's kill of the engine's group does not reach it. When the engine dies the operating system closes the engine's end of the pipe, and the watchdog sees the end of the pipe. This is the property the converter already relies on; the test of this plan checks it for a SIGKILL of the engine, which is the case that matters.
- The watchdog kills a group by pid, and a pid can be reused after the launcher is reaped. This plan does not prevent that: `models._run` reaps the launcher (`proc.wait()`) during a normal call, as `convert_run` does before it tells its watchdog "done", and the one call that would let `_run` observe the end without reaping (`os.waitid` with `WNOWAIT`) is not available on macOS. So between the reaping of the launcher and the watchdog's "done" there is a window, of the length of a few instructions, in which an engine that dies would leave the watchdog armed on a pid that no longer belongs to the launcher. The plan shortens the window and does not close it: "done" is sent at once after the reaping, with nothing between them but the closing of the streams. What limits the harm is that a process group id stays reserved while any member of the group lives, that pids are handed out in turn and so a reuse within that window needs the whole range to wrap in a few microseconds, and that the watchdog can only signal a group the same user owns. This is recorded as a remaining risk, not as a property.
- No model is called by any step: the tests use a fake launcher in a temporary folder, as the existing tests of `models` do.

## Completion criteria

1. A test shows that after the engine process is killed with SIGKILL during a call, once the watchdog is ready (the driver reports that before the test kills it), the fake launcher and a child it started are no longer running within a stated short time. It failed before the change and passes after.
2. A normal call, a call that overruns its limit, a call that prints too much and a call whose launcher is not found behave as before: the existing tests of `models` pass unchanged.
3. When the watchdog cannot be started, and when it starts but does not say `ready`, the call fails with a message that names the watchdog, and the launcher is not left running. A test shows each of the two.
4. No watchdog or launcher is left running after any test of the increment.
5. The engine README says that a launcher started for a model call is killed if the engine dies.

## Increments

### Increment A — A launcher cannot outlive the engine

**Outcome:** `models._run` starts a watchdog for the launcher's process group and tells it "done" when the call ends; a SIGKILL of the engine in the middle of a call ends the launcher and what it started.
**Dependencies:** none.
**Affected areas:** `engine/kb/models.py` (`_run`, and a small helper that starts and ends the watchdog); `engine/tests/test_models.py` (new tests, in `ProcessTest`); `engine/README.md` (one sentence). `engine/kb/supervisor.py` is read and reused, not changed. The models spec (`docs/specs/models.md`) is edited only if it states how a call is stopped.
**Steps:**
1. Read `convert_run.py` (the use of the watchdog) and `supervisor.py` again, and the existing test `ProcessTest.test_a_call_that_runs_too_long_is_killed_with_what_it_started`, and reuse their shape.
2. Write the first test: a fake launcher that starts a child process and then sleeps; a small driver program started as its own process, in a session of its own, that calls `models.call` with that fake launcher; the test kills the driver with SIGKILL while the call is running, waits up to a stated few seconds, and checks that neither the fake launcher nor its child is alive (checked by pid, by `os.kill(pid, 0)`, with the pids written by the fake to a file in the temporary folder). See it fail, for the right reason: the launcher is still alive.
3. Write two more tests, each seen failing. (a) A watchdog that starts but does not say `ready` (the supervisor path points to a program that prints nothing, set for the test only): the call fails with a message that names the watchdog, and the launcher and its child are gone. (b) A watchdog that cannot be started at all (starting it raises `OSError`, for example a supervisor interpreter path that does not exist, set for the test only), which happens after the launcher already exists: the call fails with a message that names the watchdog, and the launcher and its child are gone.
4. In `_run`, start `supervisor.py` immediately after the launcher starts, before the threads that feed and read it, as `convert_run` does (`sys.executable -I -S`, the launcher's pid, the call's limit plus a few seconds), wait up to five seconds for `ready`, and stop the call if it does not come. In `finally`, after the launcher has been waited for and its group killed if it was still alive, tell the watchdog "done" first of all the cleanup that follows (before the threads are joined and the streams are closed), then wait for the watchdog, and kill it if it does not end in five seconds.
5. Run the new tests and see them pass. Break the change on purpose in two ways and see a test fail each time: remove the "done" write (the watchdog then ends by its pipe closing and a test finds that it ended with the wrong code), and start the watchdog with the engine's own pid instead of the launcher's. Restore each byte for byte.
6. Add the sentence to the engine README; check the models spec for a statement about how a call is stopped and change it only if one exists.
7. Check by hand, with the fake launcher and no model, that the `kb` helper's own 60-second stop leaves nothing behind: run the helper's `run_program` against a driver that makes a call to a fake launcher that never ends, with the call's own limit set well above the helper's (120 seconds against a helper `timeout` argument of a few seconds, so that the helper's stop comes first and not the call's), wait for the watchdog's `ready` to show before the helper's time is up, confirm that the helper reports that it timed out, and only then list the processes: the launcher and its child must be gone. This sends nothing to any server.

**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_models engine.tests.test_convert_run` (the converter shares the watchdog) and `wb run code-work check`. No live run, and nothing is sent to `ned`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-11-stop-the-launcher-when-the-engine-is-killed#A`.

## Verification for the plan as a whole

With one increment, the plan's verification is that of Increment A. Nothing else is rerun. The widest run named is the test modules `test_models` and `test_convert_run`; the rest of the engine's tests do not call `models._run` except through the fake launchers that `test_models` already covers, and are not rerun unless the owner wants them.

What could break outside the tested area: `models._run` is the one place every model call goes through (`card-make`, the checks, `vectors.search`, `problem-search`). A watchdog that wrongly kills a live call, or a start that fails on a machine where `sys.executable -I -S` behaves differently, would fail those calls. The tests use fake launchers, so they show the engine's side only. I would ask the owner whether to run one real `problem-search` against `ned` after the commit (two short sub-problems, plain HTTP, the text sent is the sub-problems only), and would say exactly what is sent before it runs.

## Risks and sensitive actions

- A new subprocess is started on every model call, and the engine now trusts a pipe to keep a process group from running. The watchdog reads nothing but the pipe, takes its pid and seconds from the engine only, and runs with `-I -S`, as for the converter. I will ask the owner once whether to run a security review of this surface, as the policy says, and will not recommend one unless I can name an input that reaches a privileged use; I can name none now, since the pid and the limit come from the engine and not from a caller.
- Killing by pid: if the pid were reused the watchdog could kill another group of the same user. The plan narrows the window between the reaping of the launcher and "done" and does not close it (see the assumptions); the remaining risk is that an engine which dies inside that window, together with a reuse of the pid in the same few instructions, makes the watchdog signal an unrelated group. The converter's watchdog has the same window today. A test of the ordering (that "done" is sent before the threads are joined) is not written, because a timing test of a few instructions would not be deterministic; the first deliberate break in step 5 checks only that "done" is sent.
- No secret is read or written, no file of the owner's configuration is touched, and nothing is sent to a server by any test.

## Review record

Reviewer: Codex through the review engine (plan-0038b5650df7cf0d), 3 rounds of 3. The last round still found something, so the review did not converge; the owner chose to approve after round 3. Records are in `.workbench/workbench/review-engine/plan-0038b5650df7cf0d/`.

- Round 1 (1 major, applied): the watchdog starts after the launcher, so an engine killed in that gap leaves the launcher. The guarantee now starts at the watchdog's `ready`; the gap is stated and deferred.
- Round 2 (1 major, 1 minor, both applied): a separate test for a watchdog that cannot be started at all; the hand check sets the call limit above the helper's so the helper's stop comes first.
- Round 3 (1 major, applied): the claim that "done" before letting go of the launcher prevents pid reuse was false, because the launcher is reaped first. The claim is withdrawn and the remaining race is recorded as a risk.
- Rejected: none.
- Left for the owner: the pid-reuse window and the startup window, both recorded and not closed.

## Deferred work

- The window between the start of the launcher and the watchdog's `ready` (see the Goal): an engine killed inside it still leaves the launcher to the entry's own timeout. Closing it needs a wrapper that owns the launcher from its first instruction. Not planned; the README sentence says that the guarantee starts when the watchdog is ready.
- A process that a launcher starts and then puts in a session of its own is not reached by any watchdog of this project. Closing that would need a different mechanism (a control group or a job object) and is not planned.
- The owner's mitigation, a `timeout` on the `embed-qwen` entry of the config shorter than the helper's 60 seconds, remains the owner's to set; after this plan it is no longer needed to stop a leak, only to make a slow call fail sooner.

## Result

Empty until work starts.
