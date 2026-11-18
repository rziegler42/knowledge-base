"""The skeleton of a crawl run (`kb/crawlrun.py`, Increment F of the plan `2026-11-16-build-the-safeguards-of-the-unattended-crawl`).

`crawl-run` makes the spec's checks in order (the run lock, the approved plan, the stop file, the breaker, the disk floors, the ceilings, the model server), logs, exits with the right code, and does nothing else yet: the points
where the later steps attach are calls of one function that look at the stop file. Every test runs on a temporary library, with an approved fixture plan, a small copy of an engine tree, injected free-space readings, an
injected model probe and a spy on every check, so that each refusal shows that the checks after it were not made. Run them with
`python3 -W error::ResourceWarning -m unittest engine.tests.test_crawlrun`."""
import contextlib
import datetime
import json
import os
import py_compile
import importlib.util
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from engine.tests import ENGINE_DIR

from engine.tests.test_crawllists import Fetch
from kb import KbError, crawlapprove, crawlguard, crawllists, crawllog, crawlplan, crawlqueue, crawlrun, weblists

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 16, 12, 0, 0, tzinfo=UTC)
CHECKS = ("lock", "approved", "stop", "breaker", "disk", "ceilings", "model")
POINTS = ("lists", "earlier_work", "refill", "fetch", "idle")
PLAN_TEXT = "[limits]\nbatch = 4\nfetches_per_day = 3\n[judge]\nthreshold = 0.4\n"
TOPICS = "[core weight=10]\nverification\n"


DEFAULT = object()


class Reading:
    def __init__(self, free):
        self.f_bavail, self.f_frsize = free // 4096, 4096


def config(index, bulk):
    return {"index_root": index, "bulk_root": bulk, "models_on": True,
            "models": {"emb": {"bridge": "ask-ollama", "server": "ned", "model": "m", "kind": "embedding", "dimension": 8, "thinking": False}},
            "tasks": {"card-embed": "emb"}}


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = os.path.realpath(self._tmp.name)
        self.addCleanup(self._unlock)
        self.index = os.path.join(self.dir, "index")
        self.bulk = os.path.join(self.dir, "bulk")
        os.mkdir(self.index)
        os.mkdir(self.bulk)
        self.cfg = config(self.index, self.bulk)
        self.kb = os.path.join(self.dir, "kb")
        os.makedirs(self.kb)
        self.prefix = os.path.join(self.dir, "pyc")
        os.mkdir(self.prefix, 0o700)
        with open(os.path.join(self.kb, "a.py"), "w") as f:
            f.write("print(1)\n")
        self.files = os.path.join(self.dir, "files")
        os.mkdir(self.files)
        self.free = 10**13
        self.probe_calls = 0
        self.probe_ok = True
        self.out, self.err = [], []
        self.set_plan(PLAN_TEXT)
        self.approve()

    def _unlock(self):
        for folder, _names, _files in os.walk(self.dir):
            os.chmod(folder, 0o700)

    def put(self, name, text):
        path = os.path.join(self.files, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(path, 0o600)
        return path

    def set_plan(self, text):
        self.topics = self.put("topics.txt", TOPICS)
        self.allow = self.put("allow.txt", "")
        self.plan_path = self.put("plan.txt", text + f"[files]\ntopics = {self.topics}\nallow = {self.allow}\nblacklist = {os.path.join(self.files, 'black.txt')}\n")

    def approve(self):
        digest = crawlapprove.approve(self.index, self.cfg, self.plan_path, kb_root=self.kb)[1]
        crawlapprove.approve(self.index, self.cfg, self.plan_path, digest=digest, kb_root=self.kb, is_tty=lambda: True, say=lambda s: None, now=NOW)

    def probe(self, cfg):
        self.probe_calls += 1
        return self.probe_ok

    def do_run(self, now=NOW, dry_run=False, steps=None, statvfs=None, probe=None, prefix=DEFAULT, secrets=()):
        return crawlrun.run(self.cfg, dry_run=dry_run, now=now, say=self.out.append, warn=self.err.append, kb_root=self.kb,
                            statvfs=statvfs or (lambda path: Reading(self.free)), probe=probe or self.probe, steps=steps,
                            pycache_prefix=self.prefix if prefix is DEFAULT else prefix, secrets=secrets)

    def crawl(self, *parts):
        return os.path.join(self.index, "crawl", *parts)

    def log_lines(self):
        folder = self.crawl("log")
        out = []
        if os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                with open(os.path.join(folder, name), encoding="utf-8") as f:
                    out += [json.loads(line) for line in f.read().splitlines()]
        return out

    def steps_of(self):
        return [(l["step"], l["outcome"]) for l in self.log_lines()]

    def spies(self):
        """A spy on each check, so that a test can say which were made."""
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        spies = {
            "lock": stack.enter_context(mock.patch.object(crawlrun.crawlguard, "acquire_run_lock", wraps=crawlguard.acquire_run_lock)),
            "approved": stack.enter_context(mock.patch.object(crawlrun.crawlapprove, "load_approved", wraps=crawlapprove.load_approved)),
            "stop": stack.enter_context(mock.patch.object(crawlrun.crawlguard, "stop_requested", wraps=crawlguard.stop_requested)),
            "breaker": stack.enter_context(mock.patch.object(crawlrun.crawlguard, "read_breaker", wraps=crawlguard.read_breaker)),
            "disk": stack.enter_context(mock.patch.object(crawlrun.crawlguard, "check_disk", wraps=crawlguard.check_disk)),
            "ceilings": stack.enter_context(mock.patch.object(crawlrun.crawlqueue, "connect", wraps=crawlqueue.connect)),
        }
        return spies

    def assert_checks_made(self, spies, upto):
        """The checks up to and including `upto` were made, and none after it."""
        reached = CHECKS.index(upto)
        for name in CHECKS[:reached + 1]:
            if name == "model":
                self.assertGreaterEqual(self.probe_calls, 1, name)
            else:
                self.assertGreaterEqual(spies[name].call_count, 1, name)
        for name in CHECKS[reached + 1:]:
            if name == "model":
                self.assertEqual(self.probe_calls, 0, name)
            else:
                self.assertEqual(spies[name].call_count, 0, name)

    def refusals(self):
        return [l for l in self.log_lines() if l["step"] == "refuse"]

    def candidate_rows(self):
        path = os.path.join(self.index, "candidates.sqlite")
        if not os.path.exists(path):
            return None
        with sqlite3.connect(path) as conn:
            return conn.execute("SELECT * FROM candidates").fetchall(), conn.execute("SELECT * FROM counters").fetchall()

    def lock_is_free(self):
        lock = crawlguard.acquire_run_lock(self.index, now=NOW)
        if lock is None:
            return False
        lock.release()
        return True


class Bytecode(Case):
    """Finding F1 of the security review: bytecode planted in the tree's own `__pycache__` is not in the fingerprint, so a run reads its bytecode from a private folder outside the tree or does not run."""

    def test_a_run_without_a_bytecode_prefix_is_refused_before_the_approval_is_read(self):
        spies = self.spies()
        self.assertEqual(self.do_run(prefix=None), 3)
        lines = self.refusals()
        self.assertEqual(len(lines), 1)
        self.assertIn("pycache_prefix", lines[0]["reason"])
        self.assertEqual([l["step"] for l in self.log_lines()], ["refuse"])
        self.assertGreaterEqual(spies["lock"].call_count, 1)
        for name in ("approved", "stop", "breaker", "disk", "ceilings"):
            self.assertEqual(spies[name].call_count, 0, name)
        self.assertEqual(self.probe_calls, 0)
        self.assertEqual(len(self.err), 1)
        self.assertTrue(self.lock_is_free())

    def test_a_prefix_that_is_not_a_private_folder_of_ours_outside_the_code_is_refused(self):
        link = os.path.join(self.dir, "link")
        os.symlink(self.prefix, link)
        loose = os.path.join(self.dir, "loose")
        os.mkdir(loose, 0o700)
        os.chmod(loose, 0o770)
        readable = os.path.join(self.dir, "readable")
        os.mkdir(readable, 0o700)
        os.chmod(readable, 0o750)
        afile = os.path.join(self.dir, "afile")
        open(afile, "w").close()
        private_file = os.path.join(self.dir, "private-file")
        open(private_file, "w").close()
        os.chmod(private_file, 0o700)                                            # private, but not a folder
        os.chmod(self.kb, 0o700)                                                 # the code folder itself is private, so only its place refuses it
        inside = os.path.join(self.kb, "cache")
        os.mkdir(inside, 0o700)
        alias = os.path.join(self.dir, "alias")
        os.symlink(self.dir, alias)
        through_a_link = os.path.join(alias, "kb", "cache")                       # inside the code folder, by a path that only a resolved name shows
        relative = os.path.relpath(self.prefix)                                  # a real private folder, named relative to the working folder
        self.assertFalse(os.path.isabs(relative))
        bad = ["", " ", relative, afile, private_file, link, loose, readable, os.path.join(self.dir, "nowhere"), inside, through_a_link, self.kb, self.dir, os.path.dirname(self.dir), 5, b"x"]
        for prefix in bad:
            with self.subTest(prefix=str(prefix)[-20:]):
                before = len(self.refusals())
                self.assertEqual(self.do_run(prefix=prefix), 3)
                self.assertEqual(len(self.refusals()), before + 1)
                self.assertNotIn(self.dir, self.refusals()[-1]["reason"])
        self.assertEqual(self.do_run(), 0)                                    # and the good one runs

    def test_the_engines_own_code_folder_is_the_default_place_a_prefix_may_not_be_in(self):
        self.assertIsNone(crawlrun.prefix_problem(self.prefix, self.kb))
        inside = os.path.join(self.kb, "cache")
        os.mkdir(inside, 0o700)
        with mock.patch.object(crawlrun.crawlapprove, "__file__", os.path.join(self.kb, "crawlapprove.py")):
            self.assertIsNone(crawlrun.prefix_problem(self.prefix))
            self.assertIn("outside the engine's code", crawlrun.prefix_problem(inside))

    def test_without_the_argument_the_interpreter_setting_is_read_each_time(self):
        with mock.patch.object(sys, "pycache_prefix", None):
            self.assertEqual(crawlrun.run(self.cfg, now=NOW, say=self.out.append, warn=self.err.append, kb_root=self.kb, statvfs=lambda p: Reading(self.free), probe=self.probe), 3)
        with mock.patch.object(sys, "pycache_prefix", self.prefix):
            self.assertEqual(crawlrun.run(self.cfg, now=NOW, say=self.out.append, warn=self.err.append, kb_root=self.kb, statvfs=lambda p: Reading(self.free), probe=self.probe), 0)

    def test_the_command_refuses_when_the_interpreter_was_started_without_a_prefix(self):
        from kb import __main__ as cli
        with mock.patch.object(cli.config, "load", return_value=self.cfg), mock.patch.object(sys, "pycache_prefix", None), mock.patch("sys.stderr") as err:
            self.assertEqual(cli.main(["crawl-run"]), 3)
        self.assertIn("pycache_prefix", "".join(c.args[0] for c in err.write.call_args_list))

    def test_a_dry_run_names_the_bytecode_folder_and_says_what_a_real_run_would_do(self):
        self.do_run(dry_run=True)
        text = "\n".join(self.out)
        self.assertIn("bytecode", text)
        self.assertNotIn("would refuse", text)
        self.out.clear()
        self.assertEqual(self.do_run(dry_run=True, prefix=None), 0)
        text = "\n".join(self.out)
        self.assertIn("would refuse", text.split("the bytecode")[1] if "the bytecode" in text else text)
        self.assertIn("would exit 3 (refused)", text)
        self.assertIn("not reached", text)
        self.assertEqual(text.count("would refuse"), 1)                       # said once, not again under the approved plan
        self.assertFalse(os.path.exists(self.crawl("log")))

    def test_a_planted_bytecode_file_over_unchanged_source_runs_without_the_prefix_and_not_with_it(self):
        tree = os.path.join(self.dir, "tree")
        os.makedirs(os.path.join(tree, "kb"))
        open(os.path.join(tree, "kb", "__init__.py"), "w").close()
        source = os.path.join(tree, "kb", "probe.py")
        with open(source, "w") as f:
            f.write("VALUE = 'the source'\n")
        evil = os.path.join(self.dir, "evil.py")
        with open(evil, "w") as f:
            f.write("VALUE = 'planted bytecode'\n")
        py_compile.compile(evil, cfile=importlib.util.cache_from_source(source), invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH, doraise=True)
        code = "import sys; sys.path.insert(0, sys.argv[1]); import kb.probe as m; print(m.VALUE)"
        without = subprocess.run([sys.executable, "-I", "-c", code, tree], capture_output=True, text=True, timeout=60)
        self.assertEqual(without.stdout.strip(), "planted bytecode", without.stderr)               # the danger the check closes
        cache = os.path.join(self.dir, "private-cache")
        os.mkdir(cache, 0o700)
        with_prefix = subprocess.run([sys.executable, "-I", "-X", f"pycache_prefix={cache}", "-c", code, tree], capture_output=True, text=True, timeout=60)
        self.assertEqual(with_prefix.stdout.strip(), "the source", with_prefix.stderr)
        self.assertTrue(os.listdir(cache))                                                         # the bytecode went to the private folder


class Passing(Case):
    def test_a_run_that_passes_every_check_logs_its_start_the_points_and_its_end_and_exits_0(self):
        spies = self.spies()
        self.assertEqual(self.do_run(), 0)
        self.assert_checks_made(spies, "model")
        steps = self.steps_of()
        self.assertEqual(steps[0], ("run_start", "ok"))
        self.assertEqual(steps[-1], ("run_end", "ok"))
        self.assertEqual([s for s in steps if s[0] == "stop"], [("stop", "skipped")] * len(POINTS))
        self.assertEqual(len(steps), 2 + len(POINTS))
        self.assertEqual(self.refusals(), [])
        self.assertEqual(self.out, [])
        self.assertEqual(self.err, [])
        self.assertTrue(self.lock_is_free())

    def test_the_points_are_named_and_in_the_order_of_the_specs_steps(self):
        self.assertEqual(crawlrun.POINTS, POINTS)
        self.assertEqual(crawlrun.CHECKS, CHECKS)
        self.do_run()
        reasons = [l["reason"] for l in self.log_lines() if l["step"] == "stop"]
        for point, reason in zip(POINTS, reasons):
            self.assertIn(point, reason)

    def test_every_line_of_a_run_has_its_run_name_and_each_run_has_its_own(self):
        self.do_run()
        self.do_run(now=NOW + datetime.timedelta(minutes=15))
        names = [l["run"] for l in self.log_lines()]
        self.assertEqual(len(set(names)), 2)
        for line in self.log_lines():
            self.assertRegex(line["run"], r"^2026111[0-9]T[0-9]{6}Z-[0-9a-f]{6}$")

    def test_the_run_start_says_which_approved_plan_it_runs_and_the_size_of_the_batch(self):
        self.do_run()
        start = self.log_lines()[0]
        self.assertEqual(start["n"], 4)
        digest = crawlapprove.load_approved(self.index, self.cfg, kb_root=self.kb)["digest"]
        self.assertIn(digest[:12], start["reason"])

    def test_a_run_changes_no_candidate_row_and_no_counter_and_leaves_the_breaker_and_the_approval_as_they_were(self):
        before_breaker = open(self.crawl("breaker.json"), "rb").read()
        before_approved = sorted(os.listdir(self.crawl("approved")))
        self.do_run()
        self.assertEqual(self.candidate_rows(), ([], []))
        self.assertEqual(open(self.crawl("breaker.json"), "rb").read(), before_breaker)
        self.assertEqual(sorted(os.listdir(self.crawl("approved"))), before_approved)

    def test_a_run_saves_the_guard_state_with_the_model_server_seen_up(self):
        crawlguard.save_state(self.index, {"model_down_since": "2026-11-16T11:00:00Z", "history": [True, False], "entries_down": {}})
        self.do_run()
        self.assertEqual(crawlguard.load_state(self.index), ({"model_down_since": None, "history": [True, False], "entries_down": {}}, False))


class Refusals(Case):
    def check_refusal(self, upto, code, reason, spies=None, lock_free=True):
        spies = spies or self.spies()
        self.assertEqual(self.do_run(), code)
        self.assert_checks_made(spies, upto)
        lines = self.refusals()
        self.assertEqual(len(lines), 1)
        self.assertIn(reason, lines[0]["reason"])
        self.assertEqual(lines[0]["outcome"], "refused")
        self.assertEqual([l["step"] for l in self.log_lines()], ["refuse"])           # no start, no end, nothing else
        if lock_free:
            self.assertTrue(self.lock_is_free())
        return lines[0]

    def tree(self):
        return sorted((os.path.join(d, n), os.lstat(os.path.join(d, n)).st_mtime_ns) for d, ds, fs in os.walk(self.index) for n in ds + fs)

    def test_an_index_folder_that_others_can_write_is_refused_before_the_lock_and_nothing_is_written_in_it(self):
        self.set_plan(PLAN_TEXT)
        self.approve()
        spies = self.spies()
        os.chmod(self.index, 0o777)
        self.addCleanup(os.chmod, self.index, 0o700)
        before = self.tree()
        self.assertEqual(self.do_run(), 3)
        self.assertEqual(len(self.err), 1)
        self.assertTrue(self.err[0].startswith("refused: the index folder"), self.err)
        self.assertNotIn(self.index, self.err[0])
        spies["lock"].assert_not_called()
        self.assertEqual(self.tree(), before)
        self.assertFalse(os.path.exists(os.path.join(self.index, "crawl.lock")))

    def test_an_index_folder_that_another_user_owns_is_refused_the_same_way(self):
        self.set_plan(PLAN_TEXT)
        self.approve()
        with mock.patch.object(crawlrun.crawlguard.os, "getuid", return_value=os.getuid() + 1):
            self.assertEqual(self.do_run(), 3)
        self.assertIn("not ours", self.err[0])

    def test_an_index_folder_with_mode_755_is_the_owners_own_and_a_run_goes_on(self):
        self.set_plan(PLAN_TEXT)
        self.approve()
        os.chmod(self.index, 0o755)
        self.addCleanup(os.chmod, self.index, 0o700)
        self.assertEqual(self.do_run(), 0)
        self.assertEqual(self.err, [])

    def test_the_dry_run_says_what_it_would_refuse_for_the_index_folder_on_the_line_of_the_lock(self):
        self.set_plan(PLAN_TEXT)
        self.approve()
        os.chmod(self.index, 0o777)
        self.addCleanup(os.chmod, self.index, 0o700)
        self.assertEqual(self.do_run(dry_run=True), 0)                 # (a dry run only says what a real run would do)
        text = "\n".join(self.out)
        self.assertIn("the run lock: would refuse: the index folder", text)
        self.assertIn("a real run would exit 3 (refused)", text)
        self.assertIn("the approved plan: not reached", text)

    def test_the_dry_run_for_a_good_index_folder_says_it_is_the_owners(self):
        self.set_plan(PLAN_TEXT)
        self.approve()
        self.do_run(dry_run=True)
        line = next(x for x in self.out if x.startswith("the run lock:"))
        self.assertIn("the index folder is yours", line)
        self.assertIn("not taken in a dry run", line)

    def test_a_held_lock_exits_0_prints_nothing_and_logs_one_refuse_line_that_says_a_run_is_in_progress(self):
        spies = self.spies()
        held = crawlguard.acquire_run_lock(self.index, now=NOW)
        try:
            self.assertEqual(self.do_run(), 0)
        finally:
            held.release()
        self.assert_checks_made(spies, "lock")
        self.assertEqual((self.out, self.err), ([], []))
        lines = self.log_lines()
        self.assertEqual([(l["step"], l["outcome"], l["reason"]) for l in lines], [("refuse", "held", "a run is in progress")])
        self.assertEqual(self.candidate_rows(), None)

    def test_a_lock_file_that_cannot_be_used_is_a_refusal_with_exit_3(self):
        os.symlink(os.path.join(self.dir, "elsewhere"), os.path.join(self.index, "crawl.lock"))
        self.check_refusal("lock", 3, "run lock", lock_free=False)
        self.assertEqual(len(self.err), 1)

    def test_a_change_of_the_engines_code_since_the_approval_is_a_refusal_with_exit_3(self):
        spies = self.spies()
        with open(os.path.join(self.kb, "a.py"), "a") as f:
            f.write("# changed\n")
        self.check_refusal("approved", 3, "approve again", spies)
        self.assertEqual(self.err, ["refused: " + self.refusals()[0]["reason"]])

    def test_a_library_that_was_never_approved_is_refused_with_exit_3(self):
        os.remove(self.crawl("approved", "current"))
        spies = self.spies()
        self.check_refusal("approved", 3, "no plan is approved", spies)

    def test_a_changed_model_setting_is_a_refusal(self):
        spies = self.spies()
        self.cfg["models"]["emb"]["model"] = "another"
        self.check_refusal("approved", 3, "approve again", spies)

    def test_a_plan_with_no_threshold_is_refused_before_any_check_after_it_and_before_any_fetch(self):
        self.set_plan("[limits]\nbatch = 4\n")
        self.approve()
        spies = self.spies()
        line = self.check_refusal("approved", 3, "threshold", spies)
        self.assertEqual(line["step"], "refuse")
        self.assertIsNone(self.candidate_rows())

    def test_the_stop_file_is_a_refusal_with_exit_3_and_the_breaker_is_not_read(self):
        open(os.path.join(self.index, "crawl.stop"), "w").close()
        spies = self.spies()
        self.check_refusal("stop", 3, "stop file", spies)

    def test_a_tripped_breaker_a_missing_breaker_file_and_an_unreadable_one_are_refusals_with_exit_4(self):
        crawlguard._write_breaker(self.index, True, "five in a row", "consecutive_failures", "r0", now=NOW)
        spies = self.spies()
        self.assertEqual(self.do_run(), 4)
        self.assert_checks_made(spies, "breaker")
        self.assertIn("five in a row", self.refusals()[0]["reason"])
        os.remove(self.crawl("breaker.json"))
        self.assertEqual(self.do_run(), 4)
        with open(self.crawl("breaker.json"), "w") as f:
            f.write("garbage")
        os.chmod(self.crawl("breaker.json"), 0o600)
        self.assertEqual(self.do_run(), 4)
        self.assertEqual(len(self.refusals()), 3)
        self.assertEqual(self.probe_calls, 0)

    def test_a_disk_under_its_floor_or_a_reading_that_fails_is_a_refusal_with_exit_3(self):
        self.free = 1
        spies = self.spies()
        self.check_refusal("disk", 3, "drive", spies)

    def test_each_drive_is_read_by_its_own_path_and_named_when_it_is_the_one_that_is_low(self):
        def by_path(path):
            return Reading(1 if path == self.bulk else 10**13)
        self.assertEqual(self.do_run(statvfs=by_path), 3)
        self.assertIn("bulk", self.refusals()[0]["reason"])
        self.assertNotIn("index", self.refusals()[0]["reason"])

        def by_index(path):
            return Reading(1 if path == self.index else 10**13)
        self.assertEqual(self.do_run(statvfs=by_index), 3)
        self.assertIn("index", self.refusals()[1]["reason"])
        self.assertNotIn("bulk", self.refusals()[1]["reason"])

    def test_a_failed_free_space_reading_is_a_refusal(self):
        def broken(path):
            raise OSError(5, "io")
        spies = self.spies()
        self.assertEqual(self.do_run(statvfs=broken), 3)
        self.assert_checks_made(spies, "disk")
        self.assertIn("cannot be read", self.refusals()[0]["reason"])

    def test_without_a_warn_function_the_refusal_goes_to_the_error_stream_and_not_the_output(self):
        open(os.path.join(self.index, "crawl.stop"), "w").close()
        with mock.patch("sys.stderr") as err, mock.patch("sys.stdout") as out:
            crawlrun.run(self.cfg, now=NOW, kb_root=self.kb, statvfs=lambda p: Reading(self.free), probe=self.probe, pycache_prefix=self.prefix)
        written = "".join(c.args[0] for c in err.write.call_args_list)
        self.assertIn("refused: the stop file is present", written)
        self.assertEqual(out.write.call_args_list, [])

    def test_the_refusal_is_printed_on_the_error_stream_once_with_its_reason(self):
        open(os.path.join(self.index, "crawl.stop"), "w").close()
        self.do_run()
        self.assertEqual(self.out, [])
        self.assertEqual(len(self.err), 1)
        self.assertTrue(self.err[0].startswith("refused: "))

    def test_no_refusal_makes_a_request_or_changes_a_row(self):
        for setup in (lambda: open(os.path.join(self.index, "crawl.stop"), "w").close(), lambda: setattr(self, "free", 1),
                      lambda: crawlguard._write_breaker(self.index, True, "x", "model_down", "r", now=NOW)):
            setup()
            self.do_run()
        self.assertEqual(self.probe_calls, 0)
        self.assertIsNone(self.candidate_rows())


class Closing(Case):
    """The queue connection a run opens is closed whatever happens to the run."""

    class Recording:
        def __init__(self, conn):
            self.conn, self.closed = conn, 0

        def close(self):
            self.closed += 1
            self.conn.close()

        def __getattr__(self, name):
            return getattr(self.conn, name)

    def made(self):
        made = []
        real = crawlqueue.connect

        def connect(folder):
            conn = self.Recording(real(folder))
            made.append(conn)
            return conn

        return made, mock.patch.object(crawlrun.crawlqueue, "connect", connect)

    def test_it_is_closed_after_a_run_after_a_refusal_after_the_connection_and_after_a_step_that_fails(self):
        made, patch = self.made()
        with patch:
            self.do_run()
            self.probe_ok = False
            self.do_run()
            self.probe_ok = True
            with self.assertRaises(KbError):
                self.do_run(steps={"lists": lambda ctx: (_ for _ in ()).throw(KbError("a step failed"))})
        self.assertEqual(len(made), 3)
        self.assertEqual([c.closed for c in made], [1, 1, 1])


class Unlogged(Case):
    """Every way a check can fail is a refusal that is logged once, with a fixed reason that holds no path."""

    def assert_one_refusal(self, reason, code=3):
        lines = self.refusals()
        self.assertEqual(len(lines), 1)
        self.assertIn(reason, lines[0]["reason"])
        self.assertNotIn(self.dir, lines[0]["reason"])
        self.assertTrue(self.lock_is_free())
        return code

    def test_the_ceilings_are_read_before_the_model_server_is_asked(self):
        spies = self.spies()
        with mock.patch.object(crawlrun.crawlstate, "ceilings", side_effect=KbError("broken")):
            self.assertEqual(self.do_run(), 3)
        self.assertEqual(self.probe_calls, 0)
        self.assert_one_refusal("ceilings cannot be read")
        self.assertFalse(os.path.exists(self.crawl("guard.json")))
        self.assertGreaterEqual(spies["ceilings"].call_count, 1)

    def test_a_database_error_while_reading_the_ceilings_is_a_refusal_and_not_a_traceback(self):
        with mock.patch.object(crawlrun.crawlstate, "ceilings", side_effect=sqlite3.OperationalError("disk I/O error")):
            self.assertEqual(self.do_run(), 3)
        self.assertEqual(self.probe_calls, 0)
        self.assert_one_refusal("ceilings cannot be read")

    def test_a_queue_that_is_not_this_engines_is_a_refusal_and_asks_nothing(self):
        os.symlink(os.path.join(self.dir, "elsewhere"), os.path.join(self.index, "candidates.sqlite"))
        self.assertEqual(self.do_run(), 3)
        self.assertEqual(self.probe_calls, 0)
        self.assert_one_refusal("candidate queue")

    def test_a_queue_that_sqlite_cannot_lock_is_a_refusal_and_not_a_traceback(self):
        with mock.patch.object(crawlrun.crawlqueue, "connect", side_effect=sqlite3.OperationalError("database is locked")):
            self.assertEqual(self.do_run(), 3)
        self.assert_one_refusal("candidate queue")

    def test_an_approval_that_cannot_be_read_is_a_refusal(self):
        with mock.patch.object(crawlrun.crawlapprove, "load_approved", side_effect=KbError("odd")):
            self.assertEqual(self.do_run(), 3)
        self.assert_one_refusal("approve again")

    def test_a_guard_state_or_breaker_that_cannot_be_written_is_a_refusal(self):
        with mock.patch.object(crawlrun.crawlguard, "save_state", side_effect=KbError("full")):
            self.assertEqual(self.do_run(), 3)
        self.assert_one_refusal("cannot be written")

    def test_a_trip_that_cannot_be_written_is_a_refusal_and_the_clock_was_saved_first(self):
        self.probe_ok = False
        self.do_run(now=NOW)
        with mock.patch.object(crawlrun.crawlguard, "trip", side_effect=KbError("full")):
            self.assertEqual(self.do_run(now=NOW + datetime.timedelta(minutes=31)), 3)
        self.assertEqual(len(self.refusals()), 2)
        self.assertEqual(crawlguard.load_state(self.index)[0]["model_down_since"], "2026-11-16T12:00:00Z")

    def test_the_refusal_for_a_server_that_does_not_answer_does_not_blame_the_server_alone(self):
        self.probe_ok = False
        self.do_run()
        self.assertIn("model settings", self.refusals()[0]["reason"])


class StepsAndBreaker(Case):
    def test_a_step_that_trips_the_breaker_and_goes_on_does_not_carry_the_run_past_it(self):
        reached = []

        def trip_and_go_on(ctx):
            crawlguard.trip(ctx.index_root, "stage_bound", "a stage hit a bound", ctx.run, now=NOW, log=ctx.log)

        self.assertEqual(self.do_run(steps={"lists": trip_and_go_on, "earlier_work": lambda ctx: reached.append(1)}), 4)
        self.assertEqual(reached, [])
        self.assertEqual(self.steps_of()[-1], ("run_end", "tripped"))
        self.assertTrue(self.lock_is_free())
        self.assertEqual(self.do_run(), 4)                                                    # the next run is refused by the breaker

    def test_a_step_that_ends_the_run_for_a_bound_without_writing_it_down_has_the_runner_write_it(self):
        def give_up(ctx):
            raise crawlrun.BreakerTripped()

        self.assertEqual(self.do_run(steps={"refill": give_up}), 4)
        got = crawlguard.read_breaker(self.index)
        self.assertEqual((got["tripped"], got["kind"]), (True, "stage_bound"))
        self.assertIn("refill", got["reason"])
        self.assertEqual(self.do_run(), 4)

    def test_a_step_that_fails_closes_the_log_with_a_failed_end_before_the_error_goes_on(self):
        def broken(ctx):
            raise KbError("a step failed")

        with self.assertRaises(KbError):
            self.do_run(steps={"fetch": broken})
        self.assertEqual(self.steps_of()[-1], ("run_end", "failed"))
        self.assertTrue(self.lock_is_free())


class Ceilings(Case):
    def fill(self, n):
        with closing_queue(self.index) as conn:
            conn.execute("INSERT INTO counters(day, key, n) VALUES ('2026-11-16', 'fetch', ?)", (n,))

    def test_an_exhausted_ceiling_is_not_a_refusal_it_limits_new_fetches_and_the_run_goes_on(self):
        self.fill(3)
        self.assertEqual(self.do_run(now=NOW), 0)
        steps = self.steps_of()
        self.assertEqual(steps[0], ("run_start", "ok"))
        self.assertIn(("fetch", "skipped"), steps)
        self.assertEqual(steps[-1], ("run_end", "ok"))
        skipped = [l for l in self.log_lines() if (l["step"], l["outcome"]) == ("fetch", "skipped")]
        self.assertIn("fetches_per_day", skipped[0]["reason"])
        self.assertEqual(self.refusals(), [])
        self.assertEqual(self.probe_calls, 1)

    def test_a_ceiling_with_room_logs_no_skip_and_the_next_day_is_clear(self):
        self.fill(2)
        self.do_run()
        self.assertNotIn(("fetch", "skipped"), self.steps_of())
        self.do_run(now=NOW + datetime.timedelta(days=1))
        self.assertEqual(len([s for s in self.steps_of() if s == ("fetch", "skipped")]), 0)


class Model(Case):
    def test_a_server_that_does_not_answer_is_a_refusal_and_starts_the_down_clock(self):
        self.probe_ok = False
        self.assertEqual(self.do_run(), 3)
        self.assertIn("model server", self.refusals()[0]["reason"])
        state, restarted = crawlguard.load_state(self.index)
        self.assertEqual((state["model_down_since"], restarted), ("2026-11-16T12:00:00Z", False))
        self.assertFalse(crawlguard.read_breaker(self.index)["tripped"])
        self.assertEqual([l["step"] for l in self.log_lines()], ["refuse"])

    def test_down_for_longer_than_the_minutes_trips_the_breaker_and_the_next_run_is_refused_by_it(self):
        self.probe_ok = False
        self.assertEqual(self.do_run(now=NOW), 3)
        self.assertEqual(self.do_run(now=NOW + datetime.timedelta(minutes=30)), 3)
        self.assertEqual(self.do_run(now=NOW + datetime.timedelta(minutes=30, seconds=1)), 4)
        got = crawlguard.read_breaker(self.index)
        self.assertEqual((got["tripped"], got["kind"]), (True, "model_down"))
        self.assertIn("breaker", [l["step"] for l in self.log_lines()])
        self.assertEqual([l["outcome"] for l in self.log_lines() if l["step"] == "breaker"], ["tripped"])
        calls = self.probe_calls
        self.assertEqual(self.do_run(now=NOW + datetime.timedelta(minutes=45)), 4)
        self.assertEqual(self.probe_calls, calls)                                       # the breaker is looked at first: no probe

    def test_a_server_that_answers_again_forgets_the_time_it_was_down(self):
        self.probe_ok = False
        self.do_run(now=NOW)
        self.probe_ok = True
        self.assertEqual(self.do_run(now=NOW + datetime.timedelta(minutes=10)), 0)
        self.assertEqual(crawlguard.load_state(self.index)[0]["model_down_since"], None)
        self.probe_ok = False
        self.assertEqual(self.do_run(now=NOW + datetime.timedelta(minutes=50)), 3)         # a new first sighting, not 50 minutes of it
        self.assertFalse(crawlguard.read_breaker(self.index)["tripped"])

    def test_a_guard_state_that_cannot_be_read_restarts_the_clock_and_the_log_says_so(self):
        with open(self.crawl("guard.json"), "w") as f:
            f.write("garbage")
        os.chmod(self.crawl("guard.json"), 0o600)
        self.do_run()
        notes = [l for l in self.log_lines() if "restart" in (l["reason"] or "")]
        self.assertEqual(len(notes), 1)
        self.assertEqual(crawlguard.load_state(self.index)[1], False)


class Points(Case):
    def test_each_step_that_attaches_is_called_once_at_its_point_in_order_and_gets_what_it_needs(self):
        seen = []

        def step(name):
            def call(ctx):
                seen.append((name, ctx.run, ctx.index_root, ctx.plan["batch"], ctx.log is not None))
            return call

        self.do_run(steps={name: step(name) for name in POINTS})
        self.assertEqual([s[0] for s in seen], list(POINTS))
        self.assertEqual({s[1] for s in seen}, {self.log_lines()[0]["run"]})
        self.assertEqual({s[2:] for s in seen}, {(self.index, 4, True)})

    def test_a_stop_file_made_between_two_points_ends_the_run_at_the_next_and_later_points_are_not_reached(self):
        called = []

        def make_the_stop_file(ctx):
            called.append("lists")
            open(os.path.join(self.index, "crawl.stop"), "w").close()

        self.assertEqual(self.do_run(steps={"lists": make_the_stop_file, "earlier_work": lambda ctx: called.append("earlier_work"), "fetch": lambda ctx: called.append("fetch")}), 0)
        self.assertEqual(called, ["lists"])
        steps = self.steps_of()
        self.assertEqual(steps, [("run_start", "ok"), ("stop", "skipped"), ("stop", "refused"), ("run_end", "ok")])
        stopped = [l for l in self.log_lines() if l["outcome"] == "refused"][0]
        self.assertIn("earlier_work", stopped["reason"])
        self.assertTrue(self.lock_is_free())

    def test_the_stop_file_is_looked_at_at_every_point_by_one_function(self):
        with mock.patch.object(crawlrun.crawlguard, "stop_requested", wraps=crawlguard.stop_requested) as spy:
            self.do_run()
        self.assertEqual(spy.call_count, 1 + len(POINTS))                      # once for the check, once at each point

    def test_a_step_that_raises_ends_the_run_with_the_lock_let_go_and_the_error_reaches_the_caller(self):
        def broken(ctx):
            raise KbError("a step failed")
        with self.assertRaises(KbError):
            self.do_run(steps={"refill": broken})
        self.assertTrue(self.lock_is_free())
        self.assertEqual(self.steps_of()[0], ("run_start", "ok"))

    def test_a_step_that_is_not_one_of_the_points_is_refused_before_anything_is_done(self):
        with self.assertRaises(KbError):
            self.do_run(steps={"nowhere": lambda ctx: None})
        self.assertEqual(self.log_lines(), [])
        self.assertTrue(self.lock_is_free())

    def test_a_step_that_trips_the_breaker_ends_the_run_with_exit_4(self):
        def trip(ctx):
            crawlguard.trip(ctx.index_root, "stage_bound", "a stage hit a bound", ctx.run, now=NOW, log=ctx.log)
            raise crawlrun.BreakerTripped()
        self.assertEqual(self.do_run(steps={"earlier_work": trip}), 4)
        self.assertEqual(self.steps_of()[-1], ("run_end", "tripped"))
        self.assertTrue(self.lock_is_free())


class Refusing(Case):
    """A step that cannot let the run go on says so with `StepRefused`: the run refuses (exit 3), with one `refuse` line, and the error text of nothing."""

    def test_a_step_that_refuses_ends_the_run_with_exit_3_one_refuse_line_and_the_lock_let_go(self):
        reached = []

        def refuse(ctx):
            raise crawlrun.StepRefused("the required list has no usable copy")

        self.assertEqual(self.do_run(steps={"lists": refuse, "earlier_work": lambda ctx: reached.append(1)}), 3)
        self.assertEqual(reached, [])
        lines = self.log_lines()
        self.assertEqual([(l["step"], l["outcome"]) for l in lines if l["step"] == "refuse"], [("refuse", "refused")])
        self.assertIn("no usable copy", [l for l in lines if l["step"] == "refuse"][0]["reason"])
        self.assertEqual(lines[-1]["step"], "run_end")
        self.assertEqual(lines[-1]["outcome"], "refused")
        self.assertEqual(self.err, ["refused: the required list has no usable copy"])
        self.assertTrue(self.lock_is_free())
        self.assertFalse(crawlguard.read_breaker(self.index)["tripped"])

    def test_the_reason_a_step_gives_is_cleaned_and_a_credential_shape_in_it_is_withheld(self):
        def refuse(ctx):
            raise crawlrun.StepRefused("a bad line\x1b[31m Authorization: Bearer abcdefgh12345")

        self.assertEqual(self.do_run(steps={"lists": refuse}), 3)
        self.assertEqual([l["reason"] for l in self.log_lines() if l["step"] == "refuse"], [crawllog.WITHHELD])
        self.assertEqual(self.err, ["refused: " + crawllog.WITHHELD])

    def test_the_context_has_a_place_for_the_matcher_and_the_suffix_list_for_the_steps_after(self):
        seen = []
        self.do_run(steps={"lists": lambda ctx: seen.append((ctx.matcher, ctx.suffixes))})
        self.assertEqual(seen, [(None, None)])

        def set_them(ctx):
            ctx.matcher, ctx.suffixes = "a matcher", frozenset({"com"})

        later = []
        self.do_run(steps={"lists": set_them, "fetch": lambda ctx: later.append((ctx.matcher, ctx.suffixes))})
        self.assertEqual(later, [("a matcher", frozenset({"com"}))])


    def test_the_context_carries_the_digest_of_the_approved_plan_for_the_steps_that_write_it_into_a_book(self):
        seen = []
        self.do_run(steps={"lists": lambda ctx: seen.append(ctx.plan_digest)})
        self.assertEqual(seen, [crawlapprove.load_approved(self.index, self.cfg, kb_root=self.kb)["digest"]])


class ListsPoint(Case):
    """The real `lists` step in a real run, with a fake downloader."""

    def setUp(self):
        super().setUp()
        floors = mock.patch.dict(weblists.MIN_ENTRIES, {"phishing_domains": 1, "public_suffix": 1})
        floors.start()
        self.addCleanup(floors.stop)
        self.fetch = Fetch()
        self.fetch.replies[weblists.DEFAULTS["phishing_domains_url"]] = (200, {}, b"bad.example\nbad2.example\n")
        self.fetch.replies[weblists.DEFAULTS["public_suffix_url"]] = (200, {}, b"com\norg\n")
        self.step = crawllists.make_step(fetch=self.fetch, key_path=os.path.join(self.dir, "urlhaus.key"))

    def test_a_run_with_the_lists_step_refreshes_the_lists_and_hands_the_matcher_to_the_steps_after(self):
        seen = []
        self.assertEqual(self.do_run(steps={"lists": self.step, "fetch": lambda ctx: seen.append((ctx.matcher.blocked("bad.example") is not None, "org" in ctx.suffixes))}), 0)
        self.assertEqual(seen, [(True, True)])
        updates = [l for l in self.log_lines() if l["step"] == "list_update"]
        self.assertEqual(len(updates), 3)

    def test_a_required_list_with_no_copy_and_no_download_refuses_the_run_with_exit_3_before_any_later_step(self):
        self.fetch.replies[weblists.DEFAULTS["phishing_domains_url"]] = (500, {}, b"")
        reached = []
        self.assertEqual(self.do_run(steps={"lists": self.step, "earlier_work": lambda ctx: reached.append(1)}), 3)
        self.assertEqual(reached, [])
        self.assertIn("phishing_domains", [l for l in self.log_lines() if l["step"] == "refuse"][0]["reason"])
        self.assertTrue(self.lock_is_free())

    def test_a_stop_file_made_before_the_step_ends_the_run_at_the_point_and_nothing_is_downloaded(self):
        open(os.path.join(self.index, "crawl.stop"), "w").close()
        self.assertEqual(self.do_run(steps={"lists": self.step}), 3)                          # the check of the stop file comes first
        self.assertEqual(self.fetch.calls, [])

    def test_a_stop_file_made_by_an_earlier_point_is_seen_before_the_lists_step_downloads(self):
        def make_the_stop_file(ctx):
            open(os.path.join(self.index, "crawl.stop"), "w").close()

        calls_before = len(self.fetch.calls)
        self.assertEqual(self.do_run(steps={"lists": make_the_stop_file, "earlier_work": self.step}), 0)
        self.assertEqual(len(self.fetch.calls), calls_before)                              # the next point's look at the stop file ended the run first


class Remembered(Case):
    """Finding F5: a run that tripped the breaker ends with exit 4 whatever a step does to the file afterwards."""

    def test_a_step_that_trips_through_the_context_and_then_rewrites_the_file_as_not_tripped_still_ends_the_run_with_exit_4(self):
        reached = []

        def trip_and_hide(ctx):
            ctx.trip("stage_bound", "a stage hit a bound")
            crawlguard._write_breaker(ctx.index_root, False, "", "", "", now=NOW)         # the file is made good again by something inside the process

        code = self.do_run(steps={"lists": trip_and_hide, "earlier_work": lambda ctx: reached.append(1)})
        self.assertEqual(code, 4)
        self.assertEqual(reached, [])
        self.assertEqual(self.steps_of()[-1], ("run_end", "tripped"))
        self.assertTrue(self.lock_is_free())

    def test_the_context_trip_writes_the_breaker_logs_it_and_remembers_it_for_the_run(self):
        seen = {}

        def trip(ctx):
            seen["before"] = ctx.tripped
            seen["record"] = ctx.trip("stage_bound", "a stage hit a bound")
            seen["after"] = ctx.tripped
            seen["secrets"] = ctx.secrets

        self.do_run(steps={"refill": trip})
        self.assertEqual((seen["before"], seen["after"]), (False, True))
        self.assertEqual(seen["secrets"], ())
        self.assertEqual((seen["record"]["tripped"], seen["record"]["kind"]), (True, "stage_bound"))
        self.assertTrue(crawlguard.read_breaker(self.index)["tripped"])
        self.assertEqual(crawlguard.read_breaker(self.index)["kind"], "stage_bound")
        self.assertEqual([(l["step"], l["outcome"]) for l in self.log_lines() if l["step"] == "breaker"], [("breaker", "tripped")])

    def test_a_step_that_trips_and_then_fails_ends_the_run_with_exit_4_and_logs_its_end_without_the_error_text(self):
        def trip_then_fail(ctx):
            ctx.trip("stage_bound", "a stage hit a bound")
            raise KbError("a failure that quotes s3cr3t-value")

        self.assertEqual(self.do_run(steps={"lists": trip_then_fail}, secrets=["s3cr3t-value"]), 4)
        self.assertEqual(self.steps_of()[-1], ("run_end", "tripped"))
        self.assertNotIn("s3cr3t-value", "".join(open(os.path.join(self.crawl("log"), n)).read() for n in os.listdir(self.crawl("log"))))
        self.assertTrue(self.lock_is_free())
        self.assertEqual(self.do_run(), 4)

    def test_a_trip_that_wrote_the_file_and_then_failed_is_still_remembered_by_the_run(self):
        def trip_that_fails_after_writing(ctx):
            real = crawlguard.trip

            def trip(*args, **kwargs):
                real(*args, **kwargs)
                raise KbError("the log could not be written")

            with mock.patch.object(crawlrun.crawlguard, "trip", trip):
                ctx.trip("stage_bound", "a stage hit a bound")

        self.assertEqual(self.do_run(steps={"lists": trip_that_fails_after_writing}), 4)
        self.assertTrue(crawlguard.read_breaker(self.index)["tripped"])

    def test_a_step_that_trips_clears_the_file_and_gives_up_still_ends_with_exit_4_even_if_the_second_trip_cannot_be_written(self):
        def hide_and_give_up(ctx):
            ctx.trip("stage_bound", "a stage hit a bound")
            crawlguard._write_breaker(ctx.index_root, False, "", "", "", now=NOW)
            raise crawlrun.BreakerTripped()

        real = crawlguard.trip
        calls = []

        def trip(*args, **kwargs):
            calls.append(1)
            if len(calls) > 1:
                raise KbError("full")
            return real(*args, **kwargs)

        with mock.patch.object(crawlrun.crawlguard, "trip", trip):
            self.assertEqual(self.do_run(steps={"lists": hide_and_give_up}), 4)
        self.assertEqual(len(calls), 2)

    def test_a_run_that_did_not_trip_is_not_marked_tripped(self):
        seen = []
        self.assertEqual(self.do_run(steps={"fetch": lambda ctx: seen.append(ctx.tripped)}), 0)
        self.assertEqual(seen, [False])

    def test_the_secrets_a_run_is_given_reach_its_log_and_its_trips(self):
        def step(ctx):
            ctx.log.write("fetch", "failed", reason=ctx.log.safe("failed after sending s3cr3t-value"))
            ctx.trip("stage_bound", "bad with s3cr3t-value in it")

        seen = []
        self.assertEqual(self.do_run(steps={"lists": lambda ctx: (seen.append(ctx.secrets), step(ctx))}, secrets=["s3cr3t-value"]), 4)
        self.assertEqual(seen, [("s3cr3t-value",)])
        everything = "".join(open(os.path.join(self.crawl("log"), n)).read() for n in os.listdir(self.crawl("log"))) + open(self.crawl("breaker.json")).read()
        self.assertNotIn("s3cr3t-value", everything)
        self.assertIn("withheld", everything)


class LogFailure(Case):
    def test_a_log_that_cannot_be_written_ends_the_run_and_lets_go_of_the_lock(self):
        os.makedirs(self.crawl("log"), mode=0o700)
        os.chmod(self.crawl("log"), 0o500)
        with self.assertRaises(KbError):
            self.do_run()
        self.assertTrue(self.lock_is_free())

    def test_a_log_that_fails_part_way_ends_the_run(self):
        real = crawllog.Log.write
        calls = []

        def failing(log, step, outcome, **kw):
            calls.append(step)
            if step == "run_end":
                raise KbError("the crawl log cannot be written")
            return real(log, step, outcome, **kw)

        with mock.patch.object(crawllog.Log, "write", failing):
            with self.assertRaises(KbError):
                self.do_run()
        self.assertIn("run_end", calls)
        self.assertTrue(self.lock_is_free())

    def test_a_held_lock_whose_refusal_cannot_be_logged_still_does_not_run_anything(self):
        os.makedirs(self.crawl("log"), mode=0o700)
        os.chmod(self.crawl("log"), 0o500)
        held = crawlguard.acquire_run_lock(self.index, now=NOW)
        try:
            with self.assertRaises(KbError):
                self.do_run()
        finally:
            held.release()
        self.assertEqual(self.probe_calls, 0)


class DryRun(Case):
    def snapshot(self):
        files = {}
        for folder, _names, names in os.walk(self.index):
            for name in names:
                path = os.path.join(folder, name)
                with open(path, "rb") as f:
                    files[os.path.relpath(path, self.index)] = f.read()
        return files

    def test_it_takes_no_lock_writes_no_log_line_row_counter_or_state_and_makes_no_request(self):
        before = self.snapshot()
        spies = self.spies()
        held = crawlguard.acquire_run_lock(self.index, now=NOW)       # even a held lock does not stop a dry run from describing
        try:
            before = self.snapshot()
            self.assertEqual(self.do_run(dry_run=True), 0)
            after = self.snapshot()
        finally:
            held.release()
        self.assertEqual(after, before)
        self.assertEqual(self.probe_calls, 0)
        self.assertEqual(spies["lock"].call_count, 1)                  # only the test's own take
        self.assertFalse(os.path.exists(self.crawl("log")))
        self.assertIsNone(self.candidate_rows())
        self.assertEqual(self.err, [])

    def test_it_prints_each_check_in_order_what_it_would_do_next_and_the_exit_code_in_words(self):
        self.assertEqual(self.do_run(dry_run=True), 0)
        text = "\n".join(self.out)
        positions = [text.index(word) for word in ("run lock", "approved plan", "stop file", "breaker", "disk", "ceilings", "model server")]
        self.assertEqual(positions, sorted(positions))
        for point in POINTS:
            self.assertIn(point.replace("_", " "), text)
        self.assertIn("would exit 0 (done)", text)
        self.assertNotIn("would exit 3", text)

    def test_a_check_that_fails_is_shown_with_the_checks_after_it_marked_as_not_reached_and_the_code_in_words(self):
        open(os.path.join(self.index, "crawl.stop"), "w").close()
        before = self.snapshot()
        self.assertEqual(self.do_run(dry_run=True), 0)
        text = "\n".join(self.out)
        self.assertIn("would exit 3 (refused)", text)
        self.assertIn("would refuse: the stop file is present", text)
        self.assertIn("stop file", text)
        self.assertEqual(text.count("not reached"), 4)                  # breaker, disk, ceilings, model server
        self.assertEqual(self.snapshot(), before)
        crawlguard._write_breaker(self.index, True, "x", "model_down", "r", now=NOW)
        os.remove(os.path.join(self.index, "crawl.stop"))
        self.out.clear()
        self.do_run(dry_run=True)
        self.assertIn("would exit 4 (the circuit breaker is tripped)", "\n".join(self.out))

    def test_it_reads_the_ceilings_of_an_existing_queue_without_changing_it_and_does_not_make_one(self):
        self.do_run(dry_run=True)
        self.assertIsNone(self.candidate_rows())
        with closing_queue(self.index) as conn:
            conn.execute("INSERT INTO counters(day, key, n) VALUES ('2026-11-16', 'fetch', 3)")
        before = self.candidate_rows()
        self.out.clear()
        self.do_run(dry_run=True)
        self.assertEqual(self.candidate_rows(), before)
        self.assertIn("3 of 3", "\n".join(self.out))
        self.assertIn("exhausted", "\n".join(self.out))

    def test_a_dry_run_of_a_queue_that_exists_leaves_the_folder_as_it_was_file_for_file(self):
        with closing_queue(self.index) as conn:
            conn.execute("INSERT INTO counters(day, key, n) VALUES ('2026-11-16', 'fetch', 1)")
        before = sorted(os.listdir(self.index))
        self.do_run(dry_run=True)
        self.do_run(dry_run=True)
        self.assertEqual(sorted(os.listdir(self.index)), before)

    def test_a_dry_run_sees_what_a_live_writer_has_committed_and_not_yet_moved_into_the_file(self):
        conn = crawlqueue.connect(self.index)                      # kept open: its committed rows are in the write-ahead file
        try:
            conn.execute("INSERT INTO counters(day, key, n) VALUES ('2026-11-16', 'fetch', 3)")
            self.assertTrue(os.path.exists(os.path.join(self.index, "candidates.sqlite-wal")))
            self.do_run(dry_run=True)
        finally:
            conn.close()
        self.assertIn("3 of 3", "\n".join(self.out))

    def test_the_closing_line_says_which_checks_a_dry_run_cannot_make(self):
        self.do_run(dry_run=True)
        self.assertIn("if the checks a dry run cannot make (the lock, the model server, the state files) also pass", self.out[-1])
        self.out.clear()
        open(os.path.join(self.index, "crawl.stop"), "w").close()
        self.do_run(dry_run=True)
        self.assertNotIn("cannot make", self.out[-1])

    def test_it_does_not_call_the_model_server_and_says_it_would(self):
        self.probe_ok = False
        self.do_run(dry_run=True)
        self.assertEqual(self.probe_calls, 0)
        self.assertIn("would", "\n".join(self.out).split("model server")[1])

    def test_it_says_the_plan_has_no_threshold_and_that_a_run_would_refuse(self):
        self.set_plan("[limits]\nbatch = 4\n")
        self.approve()
        self.do_run(dry_run=True)
        text = "\n".join(self.out)
        self.assertIn("threshold", text)
        self.assertIn("would exit 3 (refused)", text)


PARTS = ("stale", "lists", "reconcile", "scan", "convert", "judge", "cards", "move", "refill", "fetch", "idle")
ONE_CHAIN = ["scan", "convert", "judge", "cards", "move"]


class Assembly(Case):
    """The order of one run when the steps are assembled (`crawlrun.default_steps`): each part is replaced here by a function that notes that it was called; the steps themselves are tested in their own files and
    together in `test_crawlchain`."""

    def parts(self, order, **over):
        out = {name: (lambda ctx, name=name: order.append(name)) for name in PARTS}
        out.update(over)
        return out

    def run_assembled(self, order, **over):
        return self.do_run(steps=crawlrun.default_steps(self.parts(order, **over)))

    def test_the_registry_names_the_points_and_every_part_is_a_step(self):
        steps = crawlrun.default_steps(self.parts([]))
        self.assertEqual(set(steps), set(POINTS))
        self.assertTrue(all(callable(step) for step in steps.values()))
        real = crawlrun.default_steps()                                   # with no parts the real steps are made, and none is called
        self.assertEqual(set(real), set(POINTS))
        self.assertTrue(all(callable(step) for step in real.values()))

    def test_one_run_takes_the_stale_rows_the_lists_the_earlier_work_the_refill_and_the_fetch_and_then_the_new_books_through_the_chain_again(self):
        order = []
        self.assertEqual(self.run_assembled(order), 0)
        self.assertEqual(order, ["stale", "lists", "reconcile"] + ONE_CHAIN + ["refill", "fetch"] + ONE_CHAIN + ["idle"])

    def test_the_scan_comes_before_the_convert_in_every_pass_of_the_chain(self):
        order = []
        self.run_assembled(order)
        for start in (order.index("scan"), len(order) - 1 - len(ONE_CHAIN)):        # the last step of a run is the idle window
            self.assertEqual(order[start:start + len(ONE_CHAIN)], ONE_CHAIN)

    def test_the_stop_file_made_between_two_steps_of_the_chain_prevents_the_next_step_and_the_run_ends_at_the_next_point(self):
        order = []

        def cards(ctx):
            order.append("cards")
            open(os.path.join(self.index, "crawl.stop"), "w").close()

        self.assertEqual(self.run_assembled(order, cards=cards), 0)
        self.assertEqual(order, ["stale", "lists", "reconcile", "scan", "convert", "judge", "cards"])
        lines = self.log_lines()
        self.assertEqual([l["outcome"] for l in lines if l["step"] == "stop"][-1], "refused")
        self.assertEqual([(l["outcome"], l["reason"]) for l in lines if l["step"] == "run_end"], [("ok", "stopped by the stop file at refill")])

    def test_a_stop_file_made_by_the_fetch_prevents_the_idle_window(self):
        order = []

        def fetch(ctx):
            order.append("fetch")
            open(os.path.join(self.index, "crawl.stop"), "w").close()

        self.assertEqual(self.run_assembled(order, fetch=fetch), 0)
        self.assertEqual(order[-1], "fetch")
        self.assertNotIn("idle", order)
        self.assertEqual([(l["outcome"], l["reason"]) for l in self.log_lines() if l["step"] == "run_end"], [("ok", "stopped by the stop file at idle")])

    def test_a_time_budget_that_the_fetch_spends_prevents_the_idle_window(self):
        order = []

        def fetch(ctx):
            order.append("fetch")
            ctx.deadline = ctx.clock()

        self.assertEqual(self.run_assembled(order, fetch=fetch), 0)
        self.assertNotIn("idle", order)
        self.assertEqual([(l["outcome"], l["reason"]) for l in self.log_lines() if l["step"] == "run_end"], [("ok", "stopped by the time budget at idle")])

    def test_a_run_that_reaches_its_end_in_the_normal_way_calls_the_idle_window_last(self):
        order = []
        self.assertEqual(self.run_assembled(order), 0)
        self.assertEqual(order[-1], "idle")
        self.assertEqual(order.count("idle"), 1)

    def test_a_time_budget_that_is_spent_between_two_steps_of_the_chain_prevents_the_next_step_and_ends_the_run_with_a_line_that_says_so(self):
        order = []

        def convert(ctx):
            order.append("convert")
            ctx.deadline = ctx.clock()

        self.assertEqual(self.run_assembled(order, convert=convert), 0)
        self.assertEqual(order, ["stale", "lists", "reconcile", "scan", "convert"])
        spent = [l for l in self.log_lines() if l["step"] == "stop" and l["outcome"] == "refused"]
        self.assertEqual([l["reason"] for l in spent], ["the time budget of the run is spent at refill"])
        self.assertEqual([l["reason"] for l in self.log_lines() if l["step"] == "run_end"], ["stopped by the time budget at refill"])

    def test_a_run_whose_budget_is_spent_before_it_begins_does_nothing_and_ends_at_the_first_point(self):
        order = []
        with mock.patch.object(crawlrun, "RUN_SECONDS", 0):
            self.assertEqual(self.run_assembled(order), 0)
        self.assertEqual(order, [])
        self.assertIn("the time budget of the run is spent at lists", [l["reason"] for l in self.log_lines() if l["step"] == "stop"])

    def test_the_budget_is_an_hour_and_each_run_has_its_own(self):
        self.assertEqual(crawlrun.RUN_SECONDS, 3600)
        seen = []
        self.do_run(steps={"lists": lambda ctx: seen.append(ctx.deadline - ctx.clock())})
        self.assertEqual(seen, [datetime.timedelta(seconds=3600)])

    def test_a_step_that_trips_the_breaker_ends_the_run_with_exit_4_and_no_later_step_runs(self):
        order = []

        def convert(ctx):
            order.append("convert")
            ctx.trip("stage_bound", "a bound")
            raise crawlrun.BreakerTripped()

        self.assertEqual(self.run_assembled(order, convert=convert), 4)
        self.assertEqual(order, ["stale", "lists", "reconcile", "scan", "convert"])
        self.assertEqual(self.do_run(), 4)                                 # the next run is refused until `crawl-clear --yes`

    def test_a_step_that_refuses_the_run_ends_it_with_exit_3_and_no_later_step_runs(self):
        order = []

        def judge(ctx):
            order.append("judge")
            raise crawlrun.StepRefused("the shelf vectors are not there")

        self.assertEqual(self.run_assembled(order, judge=judge), 3)
        self.assertEqual(order, ["stale", "lists", "reconcile", "scan", "convert", "judge"])

    def test_the_stalled_rows_are_queued_again_before_the_lists_and_the_line_says_how_many(self):
        conn = crawlqueue.connect(self.index)
        conn.execute("INSERT INTO candidates(identity_key, address, source, domain, status, tries, run_id, added, updated) VALUES ('k1', 'http://a.test/1', 'openalex', 'a.test', 'fetching', 1, 'old', ?, ?)",
                     ("2026-11-16T08:00:00Z", "2026-11-16T08:00:00Z"))
        conn.commit()
        conn.close()
        order = []
        parts = self.parts(order)
        del parts["stale"]                                                 # the real sweep
        parts["lists"] = lambda ctx: order.append(("lists", [r[0] for r in ctx.conn.execute("SELECT status FROM candidates")]))
        self.do_run(steps=crawlrun.default_steps(parts))
        self.assertEqual(order[0], ("lists", ["queued"]))
        line = [l for l in self.log_lines() if l["step"] == "fail"]
        self.assertEqual([(l["outcome"], l["n"]) for l in line], [("ok", 1)])

    def test_a_stalled_row_that_has_used_its_tries_is_given_up_and_counted_in_the_line(self):
        conn = crawlqueue.connect(self.index)
        conn.execute("INSERT INTO candidates(identity_key, address, source, domain, status, tries, run_id, added, updated) VALUES ('k1', 'http://a.test/1', 'openalex', 'a.test', 'fetching', 3, 'old', ?, ?)",
                     ("2026-11-16T08:00:00Z", "2026-11-16T08:00:00Z"))
        conn.commit()
        conn.close()
        parts = self.parts([])
        del parts["stale"]
        self.do_run(steps=crawlrun.default_steps(parts))
        line = [l for l in self.log_lines() if l["step"] == "fail"]
        self.assertEqual([(l["reason"], l["n"]) for l in line], [("0 stalled rows queued again, 1 given up", 1)])

    def test_the_books_of_a_plan_that_is_not_approved_are_named_with_the_library_and_the_approved_digests_of_the_run(self):
        parts = self.parts([])
        del parts["reconcile"]
        mine = crawlapprove.load_approved(self.index, self.cfg, kb_root=self.kb)["digest"]
        with mock.patch("kb.store.Store.open", return_value="the library"), mock.patch("kb.crawlbooks.approved_digests", return_value={"d" * 32, mine}), \
                mock.patch("kb.crawlbooks.reconcile_unapproved") as reconcile:
            self.do_run(steps=crawlrun.default_steps(parts))
        args = reconcile.call_args.args
        self.assertEqual((reconcile.call_count, args[0], args[1]), (1, "the library", {"d" * 32, mine}))

    def test_approvals_that_cannot_be_read_or_lack_the_runs_own_digest_refuse_the_run_and_no_book_is_named(self):
        parts = self.parts([])
        del parts["reconcile"]
        for approved in (set(), {"e" * 32}):
            with self.subTest(sorted(approved)), mock.patch("kb.store.Store.open", return_value="the library"), mock.patch("kb.crawlbooks.approved_digests", return_value=approved), \
                    mock.patch("kb.crawlbooks.reconcile_unapproved") as reconcile:
                self.assertEqual(self.do_run(steps=crawlrun.default_steps(parts)), 3)
            self.assertEqual(reconcile.call_count, 0)

    def test_a_part_that_is_not_a_step_of_the_assembly_is_refused(self):
        with self.assertRaises(KbError):
            crawlrun.default_steps({"lists": lambda ctx: None, "scann": lambda ctx: None})

    def test_a_run_with_no_stalled_row_writes_no_line_for_the_sweep(self):
        parts = self.parts([])
        del parts["stale"]
        self.do_run(steps=crawlrun.default_steps(parts))
        self.assertEqual([l for l in self.log_lines() if l["step"] == "fail"], [])


class ModelEntries(Case):
    """The start of a run follows the model entries that an earlier run found down (`crawl/guard.json`, `entries_down`)."""

    def setUp(self):
        super().setUp()
        chat = {"bridge": "ask-ollama", "server": "ned", "model": "m", "kind": "chat", "thinking": "off"}
        emb = {"bridge": "ask-ollama", "server": "ned", "model": "m", "kind": "embedding", "dimension": 8}          # (as the registry of the models accepts it)
        self.cfg = dict(self.cfg, models=dict(emb=emb, notes=chat, cardm=dict(chat)), tasks={"card-embed": "emb", "card-notes": "notes", "card-check": "notes", "card": "cardm"})
        self.approve()                                                           # the approval is of the code and of these model settings
        self.entry_calls, self.answers = [], {}

    def entry_probe(self, cfg, task):
        self.entry_calls.append(task)
        return self.answers.get(task, True)

    def down(self, **since):
        state = crawlguard.fresh_state()
        state["entries_down"] = since
        crawlguard.save_state(self.index, state)

    def run_with(self, now=NOW, **kw):
        return crawlrun.run(self.cfg, now=now, say=self.out.append, warn=self.err.append, kb_root=self.kb, statvfs=lambda p: Reading(self.free), probe=self.probe,
                            entry_probe=self.entry_probe, pycache_prefix=self.prefix, **kw)

    def clocks(self):
        return crawlguard.load_state(self.index)[0]["entries_down"]

    def lines_of(self, step):
        return [(l["outcome"], l["reason"]) for l in self.log_lines() if l["step"] == step]

    def test_with_no_entry_down_the_start_makes_the_one_probe_it_made_before_and_asks_no_entry(self):
        self.assertEqual(self.run_with(), 0)
        self.assertEqual((self.probe_calls, self.entry_calls, self.clocks()), (1, [], {}))

    def test_an_entry_that_answers_again_has_its_clock_cleared_and_the_run_goes_on(self):
        self.down(notes="2026-11-16T11:00:00Z")
        self.assertEqual(self.run_with(), 0)
        self.assertEqual((self.entry_calls, self.clocks()), (["card-notes"], {}))
        self.assertIn(("ok", "the model entry notes answers again"), self.lines_of("breaker"))

    def test_an_entry_that_still_does_not_answer_keeps_the_first_time_and_the_run_goes_on_within_the_limit(self):
        self.down(notes="2026-11-16T11:50:00Z")
        self.answers["card-notes"] = False
        self.assertEqual(self.run_with(), 0)
        self.assertEqual(self.clocks(), {"notes": "2026-11-16T11:50:00Z"})
        self.assertIn(("failed", "the model entry notes has not answered since 2026-11-16T11:50:00Z"), self.lines_of("breaker"))

    def test_an_entry_down_for_longer_than_the_limit_trips_the_breaker_and_the_next_run_is_refused_until_it_is_cleared(self):
        self.down(notes="2026-11-16T10:00:00Z")
        self.answers["card-notes"] = False
        self.assertEqual(self.run_with(), 4)
        breaker = crawlguard.read_breaker(self.index)
        self.assertEqual((breaker["tripped"], breaker["kind"]), (True, "model_down"))
        self.assertIn("the model entry notes has not answered for over", breaker["reason"])
        self.entry_calls.clear()
        self.assertEqual(self.run_with(), 4)
        self.assertEqual(self.entry_calls, [])                                   # refused at the breaker, before any probe
        crawlguard.clear(self.index, yes=True, is_tty=lambda: True, now=NOW)
        self.answers["card-notes"] = True
        self.assertEqual(self.run_with(now=NOW + datetime.timedelta(minutes=15)), 0)

    def test_an_entry_the_config_no_longer_names_is_dropped_with_a_line_and_is_not_probed(self):
        self.down(gone="2026-11-16T10:00:00Z", notes="2026-11-16T11:55:00Z")
        self.answers["card-notes"] = False
        self.assertEqual(self.run_with(), 0)
        self.assertEqual((self.entry_calls, self.clocks()), (["card-notes"], {"notes": "2026-11-16T11:55:00Z"}))
        self.assertIn(("skipped", "the model entry gone is not named in the config any more: its clock is dropped"), self.lines_of("breaker"))

    def test_the_card_embedding_entry_is_asked_by_its_own_task_when_it_is_the_one_found_down(self):
        self.down(emb="2026-11-16T11:55:00Z")
        self.run_with()
        self.assertEqual((self.entry_calls, self.clocks()), (["card-embed"], {}))

    def test_when_two_entries_are_over_the_limit_the_first_by_name_is_the_trip_that_is_written_and_the_rest_are_not_asked(self):
        self.down(cardm="2026-11-16T10:00:00Z", notes="2026-11-16T10:00:00Z")
        self.answers.update({"card": False, "card-notes": False})
        self.assertEqual(self.run_with(), 4)
        self.assertIn("the model entry cardm has not answered", crawlguard.read_breaker(self.index)["reason"])
        self.assertEqual(self.entry_calls, ["card"])                                  # a trip is known: asking the others would only wait for their timeouts
        self.assertEqual(self.clocks(), {"cardm": "2026-11-16T10:00:00Z", "notes": "2026-11-16T10:00:00Z"})

    def test_the_stop_file_is_looked_at_between_the_probes_and_the_ones_not_asked_keep_their_clocks(self):
        self.down(cardm="2026-11-16T11:50:00Z", notes="2026-11-16T11:51:00Z")
        stop = os.path.join(self.index, "crawl.stop")

        def stopping(cfg, task):
            self.entry_calls.append(task)
            open(stop, "w").close()
            return False

        ran = []
        self.assertEqual(crawlrun.run(self.cfg, now=NOW, say=self.out.append, warn=self.err.append, kb_root=self.kb, statvfs=lambda p: Reading(self.free), probe=self.probe,
                                      entry_probe=stopping, pycache_prefix=self.prefix, steps={"lists": lambda ctx: ran.append("lists")}), 0)
        self.assertEqual((self.entry_calls, ran), (["card"], []))                     # one asked; the run ends at its first point: the stop file is there
        self.assertEqual(self.clocks(), {"cardm": "2026-11-16T11:50:00Z", "notes": "2026-11-16T11:51:00Z"})

    def test_an_entry_that_two_tasks_name_is_probed_once_by_the_first_of_them(self):
        self.down(notes="2026-11-16T11:55:00Z")
        self.run_with()
        self.assertEqual(self.entry_calls, ["card-notes"])

    def test_the_entries_are_asked_in_the_order_of_their_names_and_each_is_noted_in_its_own_clock(self):
        self.down(notes="2026-11-16T11:55:00Z", cardm="2026-11-16T11:56:00Z")
        self.answers["card-notes"] = False
        self.run_with()
        self.assertEqual((self.entry_calls, self.clocks()), (["card", "card-notes"], {"notes": "2026-11-16T11:55:00Z"}))

    def test_when_the_card_embedding_does_not_answer_the_run_is_refused_as_before_and_no_entry_is_asked(self):
        self.down(notes="2026-11-16T11:55:00Z")
        self.probe_ok = False
        self.assertEqual(self.run_with(), 3)
        self.assertEqual((self.entry_calls, self.clocks()), ([], {"notes": "2026-11-16T11:55:00Z"}))

    def test_an_entry_that_has_been_down_longer_than_the_limit_trips_even_when_the_card_embedding_answers_and_the_other_clock_is_untouched(self):
        crawlguard.save_state(self.index, dict(crawlguard.fresh_state(), model_down_since="2026-11-16T11:59:00Z", entries_down={"notes": "2026-11-16T10:00:00Z"}))
        self.answers["card-notes"] = False
        self.assertEqual(self.run_with(), 4)
        self.assertIsNone(crawlguard.load_state(self.index)[0]["model_down_since"])          # the card embedding answered: its own clock is clear

    def test_a_file_in_the_old_shape_starts_the_clocks_afresh_with_one_line_that_says_so(self):
        os.makedirs(os.path.join(self.index, "crawl"), exist_ok=True)
        path = os.path.join(self.index, "crawl", "guard.json")
        with open(path, "w") as f:
            f.write(json.dumps({"model_down_since": "2026-11-16T10:00:00Z", "history": []}))
        os.chmod(path, 0o600)
        self.assertEqual(self.run_with(), 0)
        self.assertIn(("skipped", "the guard state could not be read: the model clocks restart"), self.lines_of("breaker"))
        self.assertEqual((self.entry_calls, self.clocks()), ([], {}))

    def test_what_the_entry_probe_returns_is_all_that_is_kept_and_a_line_holds_only_the_name_and_the_time(self):
        self.down(notes="2026-11-16T11:50:00Z")
        self.answers["card-notes"] = False
        self.run_with()
        text = json.dumps(self.log_lines())
        self.assertNotIn("CANARY", text)

    def test_the_default_entry_probe_is_the_guards_and_a_run_without_one_uses_it(self):
        self.down(notes="2026-11-16T11:50:00Z")
        with mock.patch.object(crawlguard, "probe_entry", return_value=True) as probe:
            crawlrun.run(self.cfg, now=NOW, say=self.out.append, warn=self.err.append, kb_root=self.kb, statvfs=lambda p: Reading(self.free), probe=self.probe, pycache_prefix=self.prefix)
        self.assertEqual([c.args[1] for c in probe.call_args_list], ["card-notes"])

    def test_the_dry_run_says_that_it_would_ask_the_entries_found_down_and_asks_none(self):
        self.down(notes="2026-11-16T11:50:00Z")
        self.assertEqual(crawlrun.run(self.cfg, dry_run=True, now=NOW, say=self.out.append, warn=self.err.append, kb_root=self.kb, statvfs=lambda p: Reading(self.free),
                                      probe=self.probe, entry_probe=self.entry_probe, pycache_prefix=self.prefix), 0)
        self.assertIn("each model entry that an earlier run found down", "\n".join(self.out))
        self.assertEqual((self.entry_calls, self.probe_calls, self.clocks()), ([], 0, {"notes": "2026-11-16T11:50:00Z"}))


class AssemblyOfTheCommand(Case):
    def test_the_command_runs_the_assembled_steps_and_a_dry_run_runs_none(self):
        sentinel = {"lists": lambda ctx: None}
        with mock.patch.object(crawlrun, "default_steps", return_value=sentinel), mock.patch.object(crawlrun, "run", return_value=0) as run:
            self.assertEqual(crawlrun.run_unattended(self.cfg, dry_run=False), 0)
            self.assertEqual(run.call_args.kwargs["steps"], sentinel)
            run.reset_mock()
            self.assertEqual(crawlrun.run_unattended(self.cfg, dry_run=True), 0)
            self.assertEqual((run.call_args.kwargs["steps"], run.call_args.kwargs["dry_run"]), (None, True))

    def test_the_dry_run_names_the_steps_a_real_run_takes_and_still_writes_nothing(self):
        before = DryRun.snapshot(self)
        self.assertEqual(self.do_run(dry_run=True), 0)
        text = "\n".join(self.out)
        for words in ("requeue the stalled rows", "refresh the lists", "reconcile", "scan and hold", "convert and index", "judge", "cards", "proposal and move", "refill", "fetch"):
            self.assertIn(words, text)
        self.assertNotIn("not built yet", text)
        self.assertEqual(DryRun.snapshot(self), before)


class Command(Case):
    def test_crawl_run_takes_no_argument_but_dry_run(self):
        from kb import __main__ as cli
        with mock.patch.object(cli.config, "load", return_value=self.cfg), mock.patch.object(crawlrun, "run", return_value=0) as run:
            self.assertEqual(cli.main(["crawl-run"]), 0)
            self.assertFalse(run.call_args.kwargs["dry_run"])
            self.assertEqual(cli.main(["crawl-run", "--dry-run"]), 0)
            self.assertTrue(run.call_args.kwargs["dry_run"])
        for bad in (["--plan", "x"], ["--digest", "x"], ["--run"], ["x"], ["--dry-run", "--yes"]):
            with self.subTest(bad=bad):
                with self.assertRaises(SystemExit):
                    with mock.patch("sys.stderr"):
                        cli.main(["crawl-run"] + bad)

    def test_the_exit_code_of_the_run_is_the_exit_code_of_the_command(self):
        from kb import __main__ as cli
        for code in (0, 3, 4):
            with mock.patch.object(cli.config, "load", return_value=self.cfg), mock.patch.object(crawlrun, "run", return_value=code):
                self.assertEqual(cli.main(["crawl-run"]), code)

    def test_a_refused_log_is_the_commands_error_exit(self):
        from kb import __main__ as cli
        with mock.patch.object(cli.config, "load", return_value=self.cfg), mock.patch.object(crawlrun, "run", side_effect=KbError("the crawl log cannot be written")), \
                mock.patch("sys.stderr"):
            self.assertEqual(cli.main(["crawl-run"]), 2)


class Contract(Case):
    """The files a run leaves, read in the forms of the plan's 'Interfaces' section, as the other plans read them."""

    def test_the_lock_the_breaker_the_guard_state_the_log_and_the_queue_are_in_their_agreed_forms(self):
        self.do_run()
        self.assertEqual(os.path.getsize(os.path.join(self.index, "crawl.lock")), 0)                    # no line while no run holds it
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.index, "crawl.lock")).st_mode), 0o600)
        breaker = json.load(open(self.crawl("breaker.json")))
        self.assertEqual(sorted(breaker), ["at", "kind", "reason", "run", "tripped"])
        self.assertIs(breaker["tripped"], False)
        state = json.load(open(self.crawl("guard.json")))
        self.assertEqual(sorted(state), ["entries_down", "history", "model_down_since"])
        lines = self.log_lines()
        for line in lines:
            self.assertEqual(list(line), ["ts", "run", "step", "outcome", "candidate", "book", "host", "reason", "n", "seconds"])
            self.assertIn(line["step"], crawllog.STEPS)
            self.assertIn(line["outcome"], crawllog.OUTCOMES)
        self.assertEqual(os.listdir(self.crawl("log")), ["crawl-2026-11-16.jsonl"])
        with sqlite3.connect(os.path.join(self.index, "candidates.sqlite")) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(sorted(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")), ["candidates", "counters"])
        self.assertEqual(len(os.listdir(self.crawl("approved"))), 2)                                  # `current` and the digest folder, as the approval left them

    def test_the_lock_holds_the_pid_and_start_while_a_step_runs(self):
        seen = []

        def look(ctx):
            with open(os.path.join(self.index, "crawl.lock"), "rb") as f:
                seen.append(f.read())

        self.do_run(steps={"lists": look})
        self.assertEqual(seen, [b"%d 2026-11-16T12:00:00Z\n" % os.getpid()])

    def test_a_reader_of_the_queue_finds_the_rows_a_run_left_as_it_found_them(self):
        with closing_queue(self.index) as conn:
            conn.execute("INSERT INTO candidates(identity_key, address, source, domain, status, added, updated) VALUES ('k', 'https://a.example/', 'openalex', 'a.example', 'queued', '2026-11-16T10:00:00Z', '2026-11-16T10:00:00Z')")
        before = self.candidate_rows()
        self.do_run()
        self.assertEqual(self.candidate_rows(), before)
        self.assertEqual(crawlqueue.counts(sqlite3.connect(os.path.join(self.index, "candidates.sqlite")))["queued"], 1)


class Wiring(Case):
    def test_the_module_changes_no_row_itself_makes_no_request_and_reads_no_environment(self):
        with open(os.path.join(ENGINE_DIR, "kb", "crawlrun.py"), encoding="utf-8") as f:
            source = f.read()
        for word in ("socket", "urllib", "subprocess", "os.environ", "getenv", "webclient", "UPDATE", "DELETE", "INSERT", "DROP"):
            self.assertNotIn(word, source, word)


@contextlib.contextmanager
def closing_queue(index):
    conn = crawlqueue.connect(index)
    try:
        yield conn
    finally:
        conn.close()


if __name__ == "__main__":
    unittest.main()
