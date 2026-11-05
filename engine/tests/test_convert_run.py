import itertools
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

from engine.tests.test_store import StoreCase, read_json

from kb import KbError, approvals, config, convert_run, incoming, stages

PROBE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "tools", "probe.py")
SANDBOX = "/usr/bin/sandbox-exec"


def approve(entries):
    """Do what the owner does by hand: put entries in the approved list of the config."""
    cfg = config.load()
    cfg["approved_tools"] = entries
    config.save(cfg)


class SandboxCase(StoreCase):
    def setUp(self):
        super().setUp()
        if not os.path.exists(SANDBOX):
            self.fail(f"{SANDBOX} was not found: these tests need macOS, whose sandbox-exec confines the tools")
        self.inp = os.path.join(self.base, "tool_in")
        self.out = os.path.join(self.base, "tool_out")
        self.outside = os.path.join(self.base, "outside")
        for d in (self.inp, self.out, self.outside):
            os.makedirs(d)
        with open(os.path.join(self.inp, "input.txt"), "w") as f:
            f.write("inside the input\n")
        self.secret = os.path.join(self.outside, "secret.txt")
        with open(self.secret, "w") as f:
            f.write("a secret outside the input\n")
        self.exe, self.prefix = approvals.python_runtime()

    def entry(self, mode, *args, name="probe", version="1", timeout=20, max_output=1_000_000, reads=None, formats=("pdf",)):
        command = [self.exe, "-I", PROBE, "{input}", "{output}", mode, *map(str, args)]
        return approvals.describe(name, version, command, reads=reads if reads is not None else [self.prefix],
                                  formats=formats, timeout=timeout, max_output=max_output, pin=[PROBE])

    def run_tool(self, mode, *args, **kw):
        fresh = kw.pop("fresh", True)
        if fresh:
            shutil.rmtree(self.out, ignore_errors=True)
            os.makedirs(self.out)
        return convert_run.run(self.entry(mode, *args, **kw), self.inp, self.out)

    def observed(self, result):
        return json.loads(result.files["observe.json"].decode())


class RunnerTest(SandboxCase):
    def test_a_tool_runs_reads_its_input_and_its_output_is_collected(self):
        result = self.run_tool("ok")
        self.assertEqual(result.files, {"result.txt": b"fine"})
        self.assertEqual(result.stdout, b"a line on stdout\n")
        result = self.run_tool("read_input", "input.txt")
        self.assertEqual(result.files["copy.txt"], b"inside the input\n")

    def test_the_network_is_denied_and_nothing_reaches_a_listener(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(5)
        server.settimeout(0.2)
        port, accepted = server.getsockname()[1], []

        def accept_loop():
            end = time.monotonic() + 8
            while time.monotonic() < end:
                try:
                    accepted.append(server.accept())
                except OSError:
                    continue

        thread = threading.Thread(target=accept_loop, daemon=True)
        thread.start()
        self.addCleanup(server.close)
        seen = self.observed(self.run_tool("connect", port))
        self.assertFalse(seen["tcp"]["allowed"], seen)
        self.assertFalse(seen["udp"]["allowed"], seen)
        self.assertFalse(seen["dns"]["allowed"], seen)
        time.sleep(0.5)
        self.assertEqual(accepted, [], "the tool reached the listener")

    def test_a_write_outside_the_output_folder_is_denied(self):
        target = os.path.join(self.outside, "planted.txt")
        seen = self.observed(self.run_tool("write_outside", target))
        self.assertFalse(seen["write"]["allowed"], seen)
        self.assertFalse(os.path.exists(target))

    def test_the_input_cannot_be_changed_created_in_or_deleted_from(self):
        seen = self.observed(self.run_tool("write_input", "input.txt"))
        for what in ("create", "modify", "delete"):
            self.assertFalse(seen[what]["allowed"], (what, seen))
        self.assertEqual(os.listdir(self.inp), ["input.txt"])
        with open(os.path.join(self.inp, "input.txt")) as f:
            self.assertEqual(f.read(), "inside the input\n")

    def test_a_file_outside_the_input_cannot_be_read(self):
        config_file = os.path.join(self.cfg, "config.json")
        marker = os.path.join(self.bulk, ".kb-library")
        seen = self.observed(self.run_tool("read_outside", self.secret, config_file, marker, "/etc/hosts"))
        for key in ("read0", "read1", "read2", "read3"):
            self.assertFalse(seen[key]["allowed"], (key, seen[key]))
        self.assertNotIn("secret", json.dumps(seen))

    def test_other_programs_cannot_be_started_and_the_tool_cannot_fork(self):
        seen = self.observed(self.run_tool("exec_other"))
        self.assertFalse(seen["exec"]["allowed"], seen)
        self.assertFalse(seen["fork"]["allowed"], seen)

    def test_the_tool_cannot_signal_this_process(self):
        seen = self.observed(self.run_tool("signal", os.getpid()))
        self.assertFalse(seen["signal"]["allowed"], seen)

    def test_a_file_outside_cannot_be_linked_or_moved_in(self):
        seen = self.observed(self.run_tool("hardlink", self.secret))
        self.assertFalse(seen["hardlink"]["allowed"], seen)
        self.assertFalse(seen["rename"]["allowed"], seen)
        self.assertTrue(os.path.exists(self.secret))

    def test_a_symlink_to_a_file_outside_cannot_be_written_or_read_through(self):
        target = os.path.join(self.outside, "viasymlink.txt")
        seen = self.observed(self.run_tool("symlink_then_write", target))
        self.assertFalse(seen["write_through"]["allowed"], seen)
        self.assertFalse(os.path.exists(target))
        seen = self.observed(self.run_tool("symlink_then_write", self.secret))
        self.assertFalse(seen["read_through"]["allowed"], seen)

    def test_the_tool_gets_a_minimal_environment(self):
        with mock.patch.dict(os.environ, {"SECRET_TOKEN": "hunter2", "HOME": "/Users/someone"}):
            keys = json.loads(self.run_tool("env").files["env.json"].decode())
        self.assertNotIn("SECRET_TOKEN", keys)
        self.assertNotIn("HOME", keys)
        self.assertTrue(set(keys) <= {"PATH", "LC_ALL", "TMPDIR", "__CF_USER_TEXT_ENCODING"}, keys)

    def test_a_tool_that_runs_past_the_time_limit_is_killed(self):
        started = time.monotonic()
        with self.assertRaises(convert_run.ToolError) as cm:
            self.run_tool("sleep", 30, timeout=1)
        self.assertLess(time.monotonic() - started, 8)
        self.assertIn("timed out", str(cm.exception))
        with open(os.path.join(self.out, "pid.txt")) as f:
            pid = int(f.read())
        for _ in range(40):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            self.fail("the tool is still running")

    def test_a_tool_that_writes_more_than_the_output_limit_is_stopped(self):
        with self.assertRaises(convert_run.ToolError) as cm:
            self.run_tool("big_file", 5_000_000, max_output=1_000_000)
        self.assertIn("output", str(cm.exception))
        self.assertLessEqual(sum(os.path.getsize(os.path.join(self.out, n)) for n in os.listdir(self.out)), 1_100_000)

    def test_many_small_files_together_over_the_limit_are_stopped(self):
        with self.assertRaises(convert_run.ToolError):
            self.run_tool("growing_files", 400, max_output=100_000)

    def test_too_much_on_standard_output_is_stopped(self):
        with self.assertRaises(convert_run.ToolError) as cm:
            self.run_tool("big_stdout", 3_000_000, max_output=100_000)
        self.assertIn("output", str(cm.exception))

    def test_a_tool_that_streams_output_without_end_is_stopped_at_once_not_at_the_time_limit(self):
        started = time.monotonic()
        with self.assertRaises(convert_run.ToolError) as cm:
            self.run_tool("endless_stdout", max_output=100_000, timeout=30)
        self.assertLess(time.monotonic() - started, 8)
        self.assertIn("standard output", str(cm.exception))

    def test_a_tool_that_creates_files_without_end_is_stopped_at_once_not_at_the_time_limit(self):
        started = time.monotonic()
        with self.assertRaises(convert_run.ToolError):
            self.run_tool("endless_files", max_output=1_000_000, timeout=30)
        self.assertLess(time.monotonic() - started, 8)
        self.assertLess(len(os.listdir(self.out)), 5000)

    def test_more_files_than_the_file_limit_are_refused_even_when_they_are_tiny(self):
        with self.assertRaises(convert_run.ToolError) as cm:
            self.run_tool("growing_files", 300, 1, max_output=1_000_000)
        self.assertIn("files", str(cm.exception))

    def test_a_pipe_left_in_the_output_is_refused_and_does_not_hang_the_collection(self):
        started = time.monotonic()
        with self.assertRaises(convert_run.ToolError) as cm:
            self.run_tool("leave_fifo")
        self.assertLess(time.monotonic() - started, 8)
        self.assertIn("not a plain file", str(cm.exception))

    def test_the_process_is_started_closed_to_input_in_its_own_session_with_the_output_as_working_folder(self):
        seen = {}
        real = convert_run.subprocess.Popen

        def spy(*args, **kwargs):
            if not seen:  # the first process started is the tool; the second is its watchdog
                seen.update(kwargs)
            return real(*args, **kwargs)

        with mock.patch.object(convert_run.subprocess, "Popen", spy):
            self.run_tool("ok")
        self.assertEqual(seen["stdin"], convert_run.subprocess.DEVNULL)
        self.assertEqual(seen["cwd"], self.out)
        self.assertTrue(seen["start_new_session"])
        self.assertEqual(seen["env"], {"PATH": "/usr/bin:/bin", "LC_ALL": "C.UTF-8", "TMPDIR": self.out})

    def test_a_tool_that_locks_its_own_folders_cannot_hide_data_from_the_limits_or_from_cleanup(self):
        started = time.monotonic()
        with self.assertRaises(convert_run.ToolError) as cm:
            self.run_tool("chmod_trap", 40, 5, max_output=2_000_000, timeout=10)
        self.assertLess(time.monotonic() - started, 8)
        self.assertIn("cannot be listed", str(cm.exception))
        convert_run.force_remove(self.out)  # whatever the tool did to the modes, the folder can be removed
        self.assertFalse(os.path.exists(self.out))

    def test_a_tool_that_locks_its_whole_output_folder_is_refused_not_taken_for_an_empty_output(self):
        with self.assertRaises(convert_run.ToolError) as cm:
            self.run_tool("chmod_out")
        self.assertIn("cannot be listed", str(cm.exception))
        convert_run.force_remove(self.out)
        self.assertFalse(os.path.exists(self.out))

    def test_too_many_folders_or_folders_nested_too_deep_are_refused(self):
        with self.assertRaises(convert_run.ToolError) as cm:
            self.run_tool("many_dirs", 400)
        self.assertIn("folders", str(cm.exception))
        with self.assertRaises(convert_run.ToolError) as cm:
            self.run_tool("deep_dirs", 30)
        self.assertIn("deep", str(cm.exception))

    def test_file_names_with_control_or_direction_characters_are_refused(self):
        for name in ("a\nb.txt", "a‮b.txt", "tab\there.txt", "sp ace.txt", "café.txt", "x" * 120):
            with self.assertRaises(convert_run.ToolError, msg=repr(name)) as cm:
                self.run_tool("odd_name", name)
            self.assertIn("name", str(cm.exception))
        self.assertEqual(self.run_tool("odd_name", "fine-name_1.v2.txt").files, {"fine-name_1.v2.txt": b"written"})

    def test_what_a_failing_tool_wrote_to_standard_error_is_cleaned_and_called_untrusted(self):
        with self.assertRaises(convert_run.ToolError) as cm:
            self.run_tool("ansi_stderr")
        message = str(cm.exception)
        for bad in ("\x1b", "‮", "\x07"):
            self.assertNotIn(bad, message)
        self.assertIn("untrusted", message)
        self.assertIn("red", message)

    def test_a_missing_sandbox_is_a_tool_failure_not_a_crash(self):
        with mock.patch.object(convert_run, "SANDBOX", "/nonexistent/sandbox-exec"):
            with self.assertRaises(convert_run.ToolError) as cm:
                self.run_tool("ok")
        self.assertIn("could not be started", str(cm.exception))

    def test_a_name_chosen_by_the_tool_cannot_put_control_or_direction_characters_into_a_message(self):
        for name, folder in (("a\nb\x1b[31m‮", False), ("d\nx‮", True)):
            with self.assertRaises(convert_run.ToolError, msg=repr(name)) as cm:
                self.run_tool("odd_name", name) if not folder else self.run_tool("odd_dir", name)
            message = str(cm.exception)
            for bad in ("\n", "\x1b", "‮"):
                self.assertNotIn(bad, message)

    def test_a_tool_cannot_set_the_flags_that_make_a_file_impossible_to_remove(self):
        seen = self.observed(self.run_tool("chflags"))
        self.assertFalse(seen["immutable"]["allowed"], seen)

    def test_cleanup_removes_a_folder_even_when_a_file_in_it_cannot_be_changed_or_deleted(self):
        folder = os.path.join(self.base, "stuck")
        os.makedirs(os.path.join(folder, "sub"))
        path = os.path.join(folder, "sub", "locked.txt")
        with open(path, "w") as f:
            f.write("x")
        os.chflags(path, stat.UF_IMMUTABLE)
        self.addCleanup(lambda: os.path.exists(path) and os.chflags(path, 0))
        os.chmod(os.path.join(folder, "sub"), 0)
        convert_run.force_remove(folder)
        self.assertFalse(os.path.exists(folder))

    def test_a_tool_does_not_outlive_an_engine_that_was_killed(self):
        entry = json.dumps(self.entry("sleep", 60, timeout=90))
        out = os.path.join(self.base, "orphan_out")
        os.makedirs(out)
        child = self.run_child_async(f"""
import json
from kb import convert_run
convert_run.run(json.loads({entry!r}), {self.inp!r}, {out!r})
""")
        pid_file = os.path.join(out, "pid.txt")
        for _ in range(100):
            if os.path.exists(pid_file) and os.path.getsize(pid_file):
                break
            time.sleep(0.1)
        else:
            child.kill()
            self.fail("the tool never started")
        with open(pid_file) as f:
            tool_pid = int(f.read())
        os.kill(tool_pid, 0)  # it is running
        child.kill()  # the engine dies without cleaning up
        child.wait()
        for _ in range(80):
            try:
                os.kill(tool_pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)
        os.killpg(tool_pid, 9)
        self.fail("the tool is still running after the engine was killed")

    def test_a_run_without_a_working_watchdog_does_not_start_the_tool(self):
        with mock.patch.object(convert_run, "SUPERVISOR", os.path.join(self.base, "no-such-watchdog.py")):
            with self.assertRaises(convert_run.ToolError) as cm:
                self.run_tool("sleep", 30, timeout=60)
        self.assertIn("watchdog", str(cm.exception))
        pid_file = os.path.join(self.out, "pid.txt")
        if os.path.exists(pid_file):  # the tool may have started in the moment before the watchdog was found missing
            with open(pid_file) as f:
                pid = int(f.read() or 0)
            for _ in range(40):
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.1)
            else:
                os.killpg(pid, 9)
                self.fail("the tool is still running without a watchdog")

    def test_a_watchdog_that_cannot_be_started_at_all_does_not_leave_the_tool_running(self):
        with mock.patch.object(convert_run.sys, "executable", "/nonexistent/python"):
            with self.assertRaises(convert_run.ToolError) as cm:
                self.run_tool("sleep", 30, timeout=60)
        self.assertIn("watchdog", str(cm.exception))
        pid_file = os.path.join(self.out, "pid.txt")
        if os.path.exists(pid_file):
            with open(pid_file) as f:
                pid = int(f.read() or 0)
            for _ in range(40):
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.1)
            else:
                os.killpg(pid, 9)
                self.fail("the tool is still running without a watchdog")

    def test_millions_of_empty_files_in_one_folder_are_stopped_without_listing_them_all(self):
        started = time.monotonic()
        with self.assertRaises(convert_run.ToolError):
            self.run_tool("growing_files", 5000, 0, max_output=1_000_000)
        self.assertLess(time.monotonic() - started, 15)

    def test_the_watchdog_that_guards_a_run_is_gone_when_the_run_ends(self):
        procs = []
        real = convert_run.subprocess.Popen

        def spy(*args, **kwargs):
            p = real(*args, **kwargs)
            procs.append(p)
            return p

        with mock.patch.object(convert_run.subprocess, "Popen", spy):
            self.run_tool("ok")
        self.assertEqual(len(procs), 2)  # the tool, and its watchdog
        self.assertTrue(all(p.poll() is not None for p in procs), "something is still running")
        self.assertEqual(procs[1].returncode, 0, "the watchdog was not told the run was done")

    def test_a_failing_tool_reports_its_status_and_what_it_said(self):
        with self.assertRaises(convert_run.ToolError) as cm:
            self.run_tool("exit", 3, "it broke because of reasons")
        self.assertIn("status 3", str(cm.exception))
        self.assertIn("it broke because of reasons", str(cm.exception))

    def test_a_symlink_left_in_the_output_is_refused_and_its_target_is_not_read(self):
        with self.assertRaises(convert_run.ToolError) as cm:
            self.run_tool("leave_symlink", self.secret)
        self.assertIn("left a symlink in its output: 'left_behind'", str(cm.exception))
        self.assertNotIn("secret", str(cm.exception))

    def test_the_tool_cannot_see_files_it_was_not_given_even_with_the_same_name_in_the_output(self):
        with open(os.path.join(self.out, "stale.txt"), "w") as f:
            f.write("left from earlier")
        with self.assertRaises(convert_run.ToolError) as cm:
            self.run_tool("ok", fresh=False)
        self.assertIn("not empty", str(cm.exception))


class InventoryTest(unittest.TestCase):
    def test_a_folder_that_never_ends_is_not_read_to_its_end(self):
        class Entry:
            def __init__(self, i):
                self.name = f"f{i}"

            def stat(self, follow_symlinks=True):
                return os.stat_result((stat.S_IFREG | 0o644, 0, 0, 1, 0, 0, 1, 0, 0, 0))

        class Endless:
            def __enter__(self):
                return iter(Entry(i) for i in itertools.count())

            def __exit__(self, *a):
                return False

        with mock.patch("os.scandir", lambda path: Endless()):
            with self.assertRaises(convert_run.ToolError):
                convert_run._inventory("/nowhere", 10_000_000)


class SupervisorTest(unittest.TestCase):
    """The watchdog on its own: it must kill the tool's group when the pipe closes without 'done' or the time is up, and
    must leave it alone when it is told 'done'."""

    def start(self, seconds):
        sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], start_new_session=True)
        self.addCleanup(lambda: (sleeper.poll() is None) and (os.killpg(sleeper.pid, 9), sleeper.wait()))
        dog = subprocess.Popen([sys.executable, "-I", "-S", convert_run.SUPERVISOR, str(sleeper.pid), str(seconds)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self.addCleanup(lambda: (dog.poll() is None) and (dog.kill(), dog.wait()))
        self.assertEqual(dog.stdout.readline(), b"ready\n")
        return sleeper, dog

    def gone(self, proc, seconds=4.0):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if proc.poll() is not None:
                return True
            time.sleep(0.05)
        return False

    def test_told_done_it_leaves_the_tool_alone_and_exits(self):
        sleeper, dog = self.start(60)
        dog.stdin.write(b"done\n")
        dog.stdin.close()
        self.assertEqual(dog.wait(timeout=5), 0)
        self.assertIsNone(sleeper.poll(), "the tool was killed although the engine said done")

    def test_a_pipe_that_closes_without_done_means_the_engine_is_gone_and_the_tool_is_killed(self):
        sleeper, dog = self.start(60)
        dog.stdin.close()
        self.assertTrue(self.gone(sleeper), "the tool is still running")
        self.assertEqual(dog.wait(timeout=5), 3)

    def test_a_tool_still_running_when_the_time_is_up_is_killed_with_the_pipe_still_open(self):
        sleeper, dog = self.start(1)
        self.assertTrue(self.gone(sleeper), "the tool is still running")
        self.assertEqual(dog.wait(timeout=5), 4)


class ProfileTest(SandboxCase):
    def test_the_profile_denies_by_default_allows_writes_only_to_the_output_and_never_the_network(self):
        text = convert_run.build_profile(self.entry("ok"), self.inp, self.out)
        self.assertIn("(deny default)", text)
        self.assertIn("(deny network*)", text)
        self.assertNotIn("(allow default)", text)
        self.assertNotIn("(allow network", text)
        writes = [ln for ln in text.splitlines() if "file-write" in ln and ln.startswith("(allow")]
        self.assertEqual(len(writes), 1)
        self.assertIn(self.out, writes[0])
        self.assertNotIn(self.cfg, text)
        self.assertNotIn(self.bulk, text)
        self.assertNotIn('(subpath "%s")' % os.path.expanduser("~"), text)  # the home folder is not readable

    def test_a_path_that_could_break_out_of_the_profile_text_is_refused(self):
        for bad in ('/tmp/a"b', "/tmp/a\nb", "/tmp/a\\b", "/tmp/a\0b", "relative/path", "/tmp/../etc"):
            with self.assertRaises(KbError, msg=repr(bad)):
                convert_run.build_profile(self.entry("ok"), bad, self.out)


class ApprovalTest(SandboxCase):
    def test_a_tool_not_on_the_list_is_refused(self):
        approve([])
        with self.assertRaises(KbError) as cm:
            approvals.find("probe", "1")
        self.assertIn("not on the approved list", str(cm.exception))

    def test_a_missing_list_is_an_empty_list(self):
        self.assertEqual(approvals.approved_tools(), [])

    def test_the_exact_version_is_needed(self):
        approve([self.entry("ok", version="1")])
        self.assertEqual(approvals.find("probe", "1")["version"], "1")
        with self.assertRaises(KbError):
            approvals.find("probe", "2")
        with self.assertRaises(KbError):
            approvals.find("other", "1")

    def test_a_tool_whose_file_changed_since_it_was_approved_is_refused(self):
        script = os.path.join(self.base, "tool.py")
        shutil.copy(PROBE, script)
        entry = approvals.describe("probe", "1", [self.exe, "-I", script, "{input}", "{output}", "ok"],
                                   reads=[self.prefix], formats=["pdf"], pin=[script])
        convert_run.run(entry, self.inp, self.out)
        with open(script, "a") as f:
            f.write("\n# changed after approval\n")
        shutil.rmtree(self.out)
        os.makedirs(self.out)
        with self.assertRaises(KbError) as cm:
            convert_run.run(entry, self.inp, self.out)
        self.assertIn("changed since it was approved", str(cm.exception))

    def test_a_missing_file_is_refused_not_ignored(self):
        script = os.path.join(self.base, "gone.py")
        shutil.copy(PROBE, script)
        entry = approvals.describe("probe", "1", [self.exe, "-I", script, "{input}", "{output}", "ok"],
                                   reads=[self.prefix], formats=["pdf"], pin=[script])
        os.remove(script)
        with self.assertRaises(KbError):
            approvals.check_pins(entry)

    def test_the_program_must_be_given_by_its_real_path(self):
        link = os.path.join(self.base, "py-link")
        os.symlink(self.exe, link)
        with self.assertRaises(KbError) as cm:
            approvals.describe("probe", "1", [link, "-I", PROBE, "{input}", "{output}", "ok"], reads=[self.prefix],
                               formats=["pdf"])
        self.assertIn("real path", str(cm.exception))
        entry = self.entry("ok")
        entry["command"][0] = link
        entry["executable"] = link
        entry["pinned"][link] = entry["pinned"][self.exe]
        with self.assertRaises(KbError):
            approvals.validate_entry(entry)

    def test_an_entry_that_is_malformed_is_refused(self):
        good = self.entry("ok")
        for field, bad in (("name", "Bad Name"), ("name", ""), ("version", ""), ("command", []), ("command", "python"),
                           ("command", ["relative/python"]), ("formats", []), ("formats", ["exe"]), ("timeout", 0),
                           ("timeout", 100000), ("max_output", -1), ("reads", "/usr"), ("reads", ["relative"]),
                           ("pinned", {}), ("pinned", {"relative": "ab" * 32}), ("pinned", {self.exe: "nothex"})):
            entry = json.loads(json.dumps(good))
            entry[field] = bad
            with self.assertRaises(KbError, msg=f"{field}={bad!r}"):
                approvals.validate_entry(entry)
        extra = json.loads(json.dumps(good))
        extra["surprise"] = 1
        with self.assertRaises(KbError):
            approvals.validate_entry(extra)

    def test_readable_paths_may_not_include_the_config_the_library_or_the_whole_disk(self):
        for bad in ("/", self.cfg, os.path.dirname(self.cfg), self.bulk, os.path.join(self.bulk, "books"), self.index,
                    os.path.expanduser("~"), self.base):
            entry = self.entry("ok", reads=[self.prefix, bad])
            with self.assertRaises(KbError, msg=bad) as cm:
                convert_run.run(entry, self.inp, self.out)
            self.assertIn("may not be readable", str(cm.exception))

    def test_a_different_spelling_of_a_protected_folder_is_the_same_folder_on_a_volume_that_ignores_case(self):
        for bad in (self.cfg.upper(), self.bulk.upper(), os.path.join(self.bulk, "BOOKS"), self.index.upper(),
                    os.path.dirname(self.cfg).swapcase()):
            entry = self.entry("ok", reads=[self.prefix, bad])
            with self.assertRaises(KbError, msg=bad) as cm:
                convert_run.run(entry, self.inp, self.out)
            self.assertIn("may not be readable", str(cm.exception))

    def test_the_firmlink_spelling_of_a_protected_folder_or_of_the_whole_disk_is_refused_too(self):
        home = os.path.expanduser("~")
        for bad in ("/System/Volumes/Data", "/System/Volumes/Data" + home, "/system/volumes/data" + home.upper(),
                    "/System/Volumes/Data" + self.cfg, "/System/Volumes/Data" + self.bulk):
            entry = self.entry("ok", reads=[self.prefix, bad])
            with self.assertRaises(KbError, msg=bad) as cm:
                convert_run.run(entry, self.inp, self.out)
            self.assertIn("may not be readable", str(cm.exception))

    def test_a_pinned_file_or_the_program_cannot_be_something_that_must_stay_unreadable(self):
        entry = approvals.describe("probe", "1", [self.exe, "-I", PROBE, "{input}", "{output}", "ok"],
                                   reads=[self.prefix], formats=["pdf"], pin=[PROBE, os.path.join(self.cfg, "config.json")])
        with self.assertRaises(KbError) as cm:
            convert_run.run(entry, self.inp, self.out)
        self.assertIn("may not be readable", str(cm.exception))

    def test_the_list_is_read_from_the_config_only_if_it_is_owner_only(self):
        approve([self.entry("ok")])
        os.chmod(os.path.join(self.cfg, "config.json"), 0o660)
        with self.assertRaises(KbError):
            approvals.approved_tools()

    def test_the_same_tool_and_version_listed_twice_is_refused(self):
        approve([self.entry("ok"), self.entry("nothing")])
        with self.assertRaises(KbError) as cm:
            approvals.approved_tools()
        self.assertIn("twice", str(cm.exception))

    def test_a_list_that_is_not_a_list_is_refused(self):
        cfg = config.load()
        cfg["approved_tools"] = {"probe": "1"}
        config.save(cfg)
        with self.assertRaises(KbError):
            approvals.approved_tools()


class PayloadTest(SandboxCase):
    def setUp(self):
        super().setUp()
        self.book, self.version = self.new_version()
        self.store.file_payload(self.book, self.version, "original", {"paper.pdf": b"%PDF-1.4 sample"}, primary="paper.pdf")

    def test_a_tools_output_is_filed_as_a_derived_payload_marked_untrusted(self):
        entry = self.entry("ok", name="probe", version="1")
        manifest = convert_run.run_to_payload(self.store, self.book, self.version, entry, "derived/probe/1")
        self.assertEqual(manifest["tool"], "probe 1")
        self.assertTrue(manifest["untrusted"])
        path = self.store.payload_dir(self.book, self.version, "derived/probe/1")
        with open(os.path.join(path, "result.txt"), "rb") as f:
            self.assertEqual(f.read(), b"fine")
        self.store.verify_payload(self.book, self.version, "derived/probe/1")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode) & 0o222, 0)
        self.assertEqual(os.listdir(os.path.join(self.bulk, "incoming")), [])  # the tool's scratch folder is gone

    def test_the_tool_reads_the_filed_original_and_cannot_change_it(self):
        entry = self.entry("write_input", "paper.pdf")
        manifest = convert_run.run_to_payload(self.store, self.book, self.version, entry, "derived/probe/1")
        self.assertEqual(set(manifest["files"]), {"observe.json"})
        path = self.store.payload_dir(self.book, self.version, "derived/probe/1")
        seen = read_json(os.path.join(path, "observe.json"))
        for what in ("create", "modify", "delete"):
            self.assertFalse(seen[what]["allowed"], seen)
        self.store.verify_payload(self.book, self.version, "original")

    def test_a_failing_tool_leaves_no_payload_and_no_scratch_folder(self):
        entry = self.entry("exit", 2, "boom")
        with self.assertRaises(convert_run.ToolError):
            convert_run.run_to_payload(self.store, self.book, self.version, entry, "derived/probe/1")
        self.assertIsNone(self.store.payload_dir(self.book, self.version, "derived/probe/1"))
        self.assertEqual(os.listdir(os.path.join(self.bulk, "incoming")), [])

    def test_a_tool_with_no_output_is_a_failure(self):
        with self.assertRaises(convert_run.ToolError) as cm:
            convert_run.run_to_payload(self.store, self.book, self.version, self.entry("nothing"), "derived/probe/1")
        self.assertIn("no output", str(cm.exception))

    def test_a_missing_input_payload_is_refused(self):
        with self.assertRaises(KbError):
            convert_run.run_to_payload(self.store, self.book, self.version, self.entry("ok"), "derived/probe/1",
                                       input_payload="derived/nothing/1")

    def test_the_scratch_folder_of_a_tool_that_locked_its_folders_is_still_removed(self):
        with self.assertRaises(convert_run.ToolError):
            convert_run.run_to_payload(self.store, self.book, self.version, self.entry("chmod_trap", 5, 3, timeout=10),
                                       "derived/probe/1")
        self.assertEqual(os.listdir(os.path.join(self.bulk, "incoming")), [])

    def test_a_run_that_is_killed_before_its_output_is_filed_leaves_no_payload(self):
        entry = json.dumps(self.entry("ok"))
        done = self.run_child(f"""
import json
from unittest import mock
from kb import convert_run, incoming, store
s = store.Store.open()
with mock.patch.object(incoming, "promote", lambda *a, **k: os._exit(7)):
    convert_run.run_to_payload(s, {self.book!r}, {self.version!r}, json.loads({entry!r}), "derived/probe/1")
""")
        self.assertEqual(done.returncode, 7, done.stderr)
        self.assertIsNone(self.store.payload_dir(self.book, self.version, "derived/probe/1"))
        self.assertEqual(self.store.read_version(self.book, self.version)["payloads"].keys(), {"original"})
        self.store.verify_payload(self.book, self.version, "original")


if __name__ == "__main__":
    unittest.main()
