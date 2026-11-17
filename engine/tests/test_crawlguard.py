"""The guards that stop a crawl run (`kb/crawlguard.py`, Increment D of the plan `2026-11-16-build-the-safeguards-of-the-unattended-crawl`).

The run lock (`crawl.lock`), the stop file (`crawl.stop`), the breaker file (`crawl/breaker.json`), the state file (`crawl/guard.json`), the four rules that trip the breaker, the stop of one site for a day, the disk floors, the model
probe and `crawl-clear`. Every test uses a temporary index root, injected clocks, free-space readings and model calls; nothing reads the owner's files or reaches a server.
Run them with `python3 -W error::ResourceWarning -m unittest engine.tests.test_crawlguard`."""
import datetime
import inspect
import json
import os
import re
import signal
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from unittest import mock

from engine.tests import ENGINE_DIR

from kb import KbError, crawlguard, crawllog, crawlplan, crawlqueue

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 16, 12, 0, 0, tzinfo=UTC)
KINDS = ("consecutive_failures", "failure_share", "model_down", "stage_bound")


def _stamp_of(moment):
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def plan(**changes):
    out = crawlplan.defaults()
    out.update(changes)
    return out


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = os.path.realpath(self._tmp.name)
        self.index = os.path.join(self.dir, "index")
        os.mkdir(self.index)
        self.addCleanup(self._unlock)

    def _unlock(self):
        for folder, _names, _files in os.walk(self.dir):
            os.chmod(folder, 0o700)

    def crawl(self, *parts):
        return os.path.join(self.index, "crawl", *parts)

    def read_breaker_file(self):
        with open(self.crawl("breaker.json"), encoding="utf-8") as f:
            return json.load(f)

    def put_breaker(self, text, mode=0o600):
        os.makedirs(self.crawl(), mode=0o700, exist_ok=True)
        with open(self.crawl("breaker.json"), "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(self.crawl("breaker.json"), mode)

    def log_lines(self):
        folder = self.crawl("log")
        out = []
        if os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                with open(os.path.join(folder, name), encoding="utf-8") as f:
                    out += [json.loads(line) for line in f.read().splitlines()]
        return out


class RunLock(Case):
    def path(self):
        return os.path.join(self.index, "crawl.lock")

    def test_it_takes_the_lock_and_writes_the_pid_and_start_while_it_holds_it(self):
        lock = crawlguard.acquire_run_lock(self.index, now=NOW)
        try:
            self.assertIsNotNone(lock)
            with open(self.path(), "rb") as f:
                self.assertEqual(f.read(), b"%d 2026-11-16T12:00:00Z\n" % os.getpid())
            self.assertEqual(stat.S_IMODE(os.stat(self.path()).st_mode), 0o600)
        finally:
            lock.release()

    def test_a_second_taker_is_told_it_is_held_and_the_line_is_not_overwritten(self):
        first = crawlguard.acquire_run_lock(self.index, now=NOW)
        try:
            second = crawlguard.acquire_run_lock(self.index, now=NOW + datetime.timedelta(hours=1))
            self.assertIsNone(second)
            with open(self.path(), "rb") as f:
                self.assertEqual(f.read(), b"%d 2026-11-16T12:00:00Z\n" % os.getpid())
        finally:
            first.release()

    def test_letting_go_empties_the_line_and_frees_the_lock_and_a_context_manager_does_it(self):
        lock = crawlguard.acquire_run_lock(self.index, now=NOW)
        lock.release()
        lock.release()                                      # twice is harmless
        self.assertEqual(os.path.getsize(self.path()), 0)
        with crawlguard.acquire_run_lock(self.index, now=NOW) as again:
            self.assertIsNotNone(again)
            self.assertIsNone(crawlguard.acquire_run_lock(self.index, now=NOW))
        third = crawlguard.acquire_run_lock(self.index, now=NOW)
        self.assertIsNotNone(third)
        third.release()

    def test_a_process_that_dies_leaves_no_stale_lock(self):
        script = ("import sys, datetime, time\nsys.path.insert(0, sys.argv[2])\nfrom kb import crawlguard\n"
                  "l = crawlguard.acquire_run_lock(sys.argv[1], now=datetime.datetime(2026, 11, 16, tzinfo=datetime.timezone.utc))\n"
                  "print('held' if l else 'none', flush=True)\ntime.sleep(60)\n")
        proc = subprocess.Popen([sys.executable, "-I", "-c", script, self.index, ENGINE_DIR], stdout=subprocess.PIPE)
        try:
            self.assertEqual(proc.stdout.readline().strip(), b"held")
            self.assertIsNone(crawlguard.acquire_run_lock(self.index, now=NOW))
            proc.send_signal(signal.SIGKILL)
            proc.wait(timeout=10)
        finally:
            proc.kill()
            proc.wait()
            proc.stdout.close()
        self.assertGreater(os.path.getsize(self.path()), 0)      # the dead process's line is still there
        lock = crawlguard.acquire_run_lock(self.index, now=NOW)
        self.assertIsNotNone(lock)
        with open(self.path(), "rb") as f:
            self.assertEqual(f.read(), b"%d 2026-11-16T12:00:00Z\n" % os.getpid())
        lock.release()

    def test_a_longer_line_left_by_a_dead_run_is_replaced_whole_and_the_file_is_made_at_mode_600_whatever_the_umask(self):
        with open(self.path(), "w") as f:
            f.write("99999999999 2026-01-01T00:00:00Z\nand some more that must not stay\n")
        os.chmod(self.path(), 0o600)
        lock = crawlguard.acquire_run_lock(self.index, now=NOW)
        with open(self.path(), "rb") as f:
            self.assertEqual(f.read(), b"%d 2026-11-16T12:00:00Z\n" % os.getpid())
        lock.release()
        os.remove(self.path())
        old = os.umask(0)
        try:
            crawlguard.acquire_run_lock(self.index, now=NOW).release()
        finally:
            os.umask(old)
        self.assertEqual(stat.S_IMODE(os.stat(self.path()).st_mode), 0o600)

    def test_an_error_taking_the_lock_or_writing_its_line_is_a_refusal_and_leaves_no_descriptor_open(self):
        before = len(os.listdir("/dev/fd"))
        with mock.patch.object(crawlguard.fcntl, "flock", side_effect=OSError(77, "no locks available")):
            with self.assertRaises(KbError):
                crawlguard.acquire_run_lock(self.index, now=NOW)
        with mock.patch.object(crawlguard.os, "pwrite", side_effect=OSError(28, "No space left on device")):
            with self.assertRaises(KbError):
                crawlguard.acquire_run_lock(self.index, now=NOW)
        self.assertEqual(len(os.listdir("/dev/fd")), before)
        lock = crawlguard.acquire_run_lock(self.index, now=NOW)                    # and the failed one did not keep the lock
        self.assertIsNotNone(lock)
        lock.release()

    def test_a_lock_file_that_is_a_link_a_folder_or_a_pipe_or_not_ours_to_trust_is_refused(self):
        target = os.path.join(self.dir, "target")
        open(target, "w").close()
        os.symlink(target, self.path())
        with self.assertRaises(KbError):
            crawlguard.acquire_run_lock(self.index, now=NOW)
        self.assertEqual(os.path.getsize(target), 0)
        os.remove(self.path())
        os.mkdir(self.path())
        with self.assertRaises(KbError):
            crawlguard.acquire_run_lock(self.index, now=NOW)
        os.rmdir(self.path())
        os.mkfifo(self.path())
        with self.assertRaises(KbError):                                 # and does not wait for a reader
            crawlguard.acquire_run_lock(self.index, now=NOW)
        os.remove(self.path())
        open(self.path(), "w").close()
        os.chmod(self.path(), 0o666)
        with self.assertRaises(KbError):
            crawlguard.acquire_run_lock(self.index, now=NOW)

    def test_a_missing_index_root_and_a_time_without_a_zone_are_refused(self):
        with self.assertRaises(KbError):
            crawlguard.acquire_run_lock(os.path.join(self.dir, "none"), now=NOW)
        with self.assertRaises(KbError):
            crawlguard.acquire_run_lock(self.index, now=datetime.datetime(2026, 11, 16))

    def test_no_descriptor_is_left_open_by_a_lock_that_was_held_refused_or_released(self):
        before = len(os.listdir("/dev/fd"))
        for _ in range(5):
            crawlguard.acquire_run_lock(self.index, now=NOW).release()
        first = crawlguard.acquire_run_lock(self.index, now=NOW)
        for _ in range(5):
            self.assertIsNone(crawlguard.acquire_run_lock(self.index, now=NOW))
        first.release()
        os.chmod(self.path(), 0o666)
        for _ in range(3):
            with self.assertRaises(KbError):
                crawlguard.acquire_run_lock(self.index, now=NOW)
        self.assertEqual(len(os.listdir("/dev/fd")), before)


class StopFile(Case):
    def path(self):
        return os.path.join(self.index, "crawl.stop")

    def test_no_file_means_go_on(self):
        self.assertFalse(crawlguard.stop_requested(self.index))

    def test_the_presence_of_the_name_stops_whatever_it_is_and_whatever_it_holds(self):
        open(self.path(), "w").close()
        self.assertTrue(crawlguard.stop_requested(self.index))
        with open(self.path(), "w") as f:
            f.write("go on, please\n" * 1000)
        self.assertTrue(crawlguard.stop_requested(self.index))
        os.remove(self.path())
        os.symlink(os.path.join(self.dir, "nowhere"), self.path())          # a link to nothing
        self.assertTrue(crawlguard.stop_requested(self.index))
        os.remove(self.path())
        os.mkdir(self.path())
        self.assertTrue(crawlguard.stop_requested(self.index))
        os.rmdir(self.path())
        os.mkfifo(self.path())
        self.assertTrue(crawlguard.stop_requested(self.index))
        os.remove(self.path())
        self.assertFalse(crawlguard.stop_requested(self.index))

    def test_a_name_that_cannot_be_examined_stops(self):
        with mock.patch.object(crawlguard.os, "lstat", side_effect=PermissionError(13, "denied")):
            self.assertTrue(crawlguard.stop_requested(self.index))
        with mock.patch.object(crawlguard.os, "lstat", side_effect=OSError(5, "io")):
            self.assertTrue(crawlguard.stop_requested(self.index))


class Breaker(Case):
    def test_a_breaker_is_written_in_the_interface_form_and_read_back(self):
        crawlguard._write_breaker(self.index, False, "", "", "", now=NOW)
        self.assertEqual(self.read_breaker_file(), {"tripped": False, "reason": "", "kind": "", "at": "2026-11-16T12:00:00Z", "run": ""})
        self.assertEqual(stat.S_IMODE(os.stat(self.crawl("breaker.json")).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.crawl()).st_mode), 0o700)
        self.assertFalse(crawlguard.read_breaker(self.index)["tripped"])
        crawlguard._write_breaker(self.index, True, "why", "model_down", "run-1", now=NOW)
        got = crawlguard.read_breaker(self.index)
        self.assertEqual(got, {"tripped": True, "reason": "why", "kind": "model_down", "at": "2026-11-16T12:00:00Z", "run": "run-1"})

    def test_a_file_that_is_missing_unexaminable_unreadable_in_the_form_or_tripped_reads_as_tripped(self):
        good = {"tripped": False, "reason": "", "kind": "", "at": "2026-11-16T12:00:00Z", "run": ""}
        self.assertTrue(crawlguard.read_breaker(self.index)["tripped"])                      # missing: not even the folder
        os.makedirs(self.crawl(), mode=0o700)
        self.assertTrue(crawlguard.read_breaker(self.index)["tripped"])                      # missing: the folder only
        self.put_breaker(json.dumps(good))
        self.assertFalse(crawlguard.read_breaker(self.index)["tripped"])
        with mock.patch.object(crawlguard.os, "lstat", side_effect=PermissionError(13, "denied")):
            self.assertTrue(crawlguard.read_breaker(self.index)["tripped"])
        with mock.patch.object(crawlguard.os, "open", side_effect=OSError(5, "io")):
            self.assertTrue(crawlguard.read_breaker(self.index)["tripped"])
        bad = ["", "{", "[]", "null", "true", '"x"', "{}", json.dumps(dict(good, extra=1)), json.dumps({k: v for k, v in good.items() if k != "run"}),
               json.dumps(dict(good, tripped="false")), json.dumps(dict(good, tripped=0)), json.dumps(dict(good, tripped=None)), json.dumps(dict(good, tripped=[])),
               json.dumps(dict(good, reason=5)), json.dumps(dict(good, reason="r" * 301)), json.dumps(dict(good, kind="other")), json.dumps(dict(good, kind=None)),
               json.dumps(dict(good, at=5)), json.dumps(dict(good, run=None)), json.dumps(dict(good, at="yesterday")), json.dumps(dict(good, tripped=True)),
               '{"tripped": true, "tripped": false, "reason": "", "kind": "", "at": "2026-11-16T12:00:00Z", "run": ""}', json.dumps(dict(good, run="bad run")), json.dumps(good) + " x", "\xef\xbb\xbf" + json.dumps(good), "x" * 100000]
        for text in bad:
            self.put_breaker(text)
            with self.subTest(text=text[:50]):
                self.assertTrue(crawlguard.read_breaker(self.index)["tripped"])
        self.put_breaker(json.dumps(good).encode("utf-8").decode("utf-8"))
        self.assertFalse(crawlguard.read_breaker(self.index)["tripped"])

    def test_the_size_limit_is_exact_and_bytes_that_are_not_utf_8_read_as_tripped(self):
        from kb.crawlguard import MAX_FILE
        good = json.dumps({"tripped": False, "reason": "", "kind": "", "at": "2026-11-16T12:00:00Z", "run": ""})
        self.put_breaker(good + " " * (MAX_FILE - len(good)))
        self.assertEqual(os.path.getsize(self.crawl("breaker.json")), MAX_FILE)
        self.assertFalse(crawlguard.read_breaker(self.index)["tripped"])
        self.put_breaker(good + " " * (MAX_FILE - len(good) + 1))
        self.assertTrue(crawlguard.read_breaker(self.index)["tripped"])
        self.put_breaker(good + " " * 20000)
        self.assertTrue(crawlguard.read_breaker(self.index)["tripped"])
        raw = json.dumps({"tripped": False, "reason": "REASON", "kind": "", "at": "2026-11-16T12:00:00Z", "run": ""}).encode().replace(b"REASON", b"\xff\xfe")
        with open(self.crawl("breaker.json"), "wb") as f:
            f.write(raw)
        os.chmod(self.crawl("breaker.json"), 0o600)
        self.assertTrue(crawlguard.read_breaker(self.index)["tripped"])

    def test_a_file_that_is_a_link_a_folder_a_pipe_or_loose_reads_as_tripped(self):
        good = json.dumps({"tripped": False, "reason": "", "kind": "", "at": "2026-11-16T12:00:00Z", "run": ""})
        self.put_breaker(good)
        target = os.path.join(self.dir, "elsewhere.json")
        os.rename(self.crawl("breaker.json"), target)
        os.symlink(target, self.crawl("breaker.json"))
        self.assertTrue(crawlguard.read_breaker(self.index)["tripped"])
        os.remove(self.crawl("breaker.json"))
        os.mkdir(self.crawl("breaker.json"))
        self.assertTrue(crawlguard.read_breaker(self.index)["tripped"])
        os.rmdir(self.crawl("breaker.json"))
        os.mkfifo(self.crawl("breaker.json"))
        self.assertTrue(crawlguard.read_breaker(self.index)["tripped"])
        os.remove(self.crawl("breaker.json"))
        self.put_breaker(good, mode=0o666)
        self.assertTrue(crawlguard.read_breaker(self.index)["tripped"])
        self.put_breaker(good, mode=0o620)
        self.assertTrue(crawlguard.read_breaker(self.index)["tripped"])
        self.put_breaker(good, mode=0o600)
        self.assertFalse(crawlguard.read_breaker(self.index)["tripped"])

    def test_the_file_is_written_whole_or_not_at_all(self):
        crawlguard._write_breaker(self.index, False, "", "", "", now=NOW)
        before = open(self.crawl("breaker.json"), "rb").read()
        with mock.patch.object(crawlguard.os, "replace", side_effect=OSError(28, "No space left on device")):
            with self.assertRaises(KbError):
                crawlguard._write_breaker(self.index, True, "x", "stage_bound", "r", now=NOW)
        self.assertEqual(open(self.crawl("breaker.json"), "rb").read(), before)
        self.assertEqual([n for n in os.listdir(self.crawl()) if n != "breaker.json"], [])
        real = os.fsync
        with mock.patch.object(crawlguard.os, "fsync", side_effect=OSError(5, "io")):
            with self.assertRaises(KbError):
                crawlguard._write_breaker(self.index, True, "x", "stage_bound", "r", now=NOW)
        self.assertEqual(open(self.crawl("breaker.json"), "rb").read(), before)
        self.assertEqual([n for n in os.listdir(self.crawl()) if n != "breaker.json"], [])
        del real

    def test_a_write_that_the_system_makes_in_pieces_is_still_whole(self):
        real = os.write
        with mock.patch.object(crawlguard.os, "write", lambda fd, data: real(fd, bytes(data)[:3])):
            crawlguard._write_breaker(self.index, True, "a reason of some length", "model_down", "run-1", now=NOW)
        self.assertEqual(crawlguard.read_breaker(self.index)["reason"], "a reason of some length")

    def test_a_breaker_that_is_written_over_a_link_replaces_the_link_and_does_not_write_through_it(self):
        os.makedirs(self.crawl(), mode=0o700)
        target = os.path.join(self.dir, "elsewhere.json")
        open(target, "w").write("keep")
        os.symlink(target, self.crawl("breaker.json"))
        crawlguard._write_breaker(self.index, False, "", "", "", now=NOW)
        self.assertEqual(open(target).read(), "keep")
        self.assertFalse(os.path.islink(self.crawl("breaker.json")))

    def test_the_arguments_of_a_write_are_checked(self):
        for kwargs in ({"kind": "other"}, {"kind": None}, {"run": "a b"}, {"run": "x" * 65}, {"reason": 5}):
            base = {"tripped": True, "reason": "r", "kind": "model_down", "run": "r1"}
            base.update(kwargs)
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(KbError):
                    crawlguard._write_breaker(self.index, base["tripped"], base["reason"], base["kind"], base["run"], now=NOW)
        with self.assertRaises(KbError):
            crawlguard._write_breaker(self.index, "yes", "", "", "", now=NOW)
        with self.assertRaises(KbError):
            crawlguard._write_breaker(self.index, True, "", "model_down", "", now=datetime.datetime(2026, 11, 16))

    def test_trip_records_the_kind_and_the_reason_cleaned_and_keeps_the_first_cause(self):
        for kind in KINDS:
            crawlguard._write_breaker(self.index, False, "", "", "", now=NOW)
            out = crawlguard.trip(self.index, kind, "a\x1b[31m red\r\nline\u202e " + "zz " * 130, "run-9", now=NOW)
            self.assertTrue(out["tripped"])
            got = crawlguard.read_breaker(self.index)
            self.assertEqual((got["kind"], got["run"], got["at"]), (kind, "run-9", "2026-11-16T12:00:00Z"))
            self.assertLessEqual(len(got["reason"]), 300)
            self.assertTrue(got["reason"].startswith("a[31m red line"))
            self.assertNotIn("\x1b", got["reason"])
            self.assertNotIn("\u202e", got["reason"])
        crawlguard._write_breaker(self.index, False, "", "", "", now=NOW)
        crawlguard.trip(self.index, "model_down", "first", "r1", now=NOW)
        crawlguard.trip(self.index, "stage_bound", "second", "r2", now=NOW + datetime.timedelta(hours=1))
        got = crawlguard.read_breaker(self.index)
        self.assertEqual((got["kind"], got["reason"], got["run"]), ("model_down", "first", "r1"))
        with self.assertRaises(KbError):
            crawlguard.trip(self.index, "other", "x", "r", now=NOW)

    def test_trip_writes_over_a_file_that_cannot_be_read_and_logs_the_trip_when_given_a_log(self):
        self.put_breaker("garbage")
        log = crawllog.Log(self.index, "run-9")
        crawlguard.trip(self.index, "failure_share", "half of them failed", "run-9", now=NOW, log=log)
        self.assertEqual(crawlguard.read_breaker(self.index)["kind"], "failure_share")
        lines = self.log_lines()
        self.assertEqual([(l["step"], l["outcome"], l["reason"]) for l in lines], [("breaker", "tripped", "half of them failed")])

    def test_a_reason_that_looks_like_a_credential_is_withheld_but_the_breaker_still_trips_and_is_logged(self):
        log = crawllog.Log(self.index, "run-9")
        out = crawlguard.trip(self.index, "stage_bound", "Auth-Key: SECRETVALUE", "run-9", now=NOW, log=log)
        self.assertTrue(out["tripped"])
        self.assertEqual(out["reason"], "the reason was withheld")
        self.assertNotIn("SECRETVALUE", open(self.crawl("breaker.json")).read())
        self.assertEqual([(l["step"], l["outcome"], l["reason"]) for l in self.log_lines()], [("breaker", "tripped", "the reason was withheld")])
        keyed = crawllog.Log(self.index, "run-9", secrets=["hunter22"])
        crawlguard._write_breaker(self.index, False, "", "", "", now=NOW)
        out = crawlguard.trip(self.index, "stage_bound", "failed with hunter22 in it", "run-9", now=NOW, log=keyed)
        self.assertTrue(out["tripped"])
        self.assertTrue(crawlguard.read_breaker(self.index)["tripped"])

    def test_a_breaker_whose_reason_is_not_clean_text_reads_as_tripped(self):
        for reason in ("a\x1b[31mred", "line\nbreak", "bidi\u202eflip", "  padded  "):
            self.put_breaker(json.dumps({"tripped": False, "reason": reason, "kind": "", "at": "2026-11-16T12:00:00Z", "run": ""}))
            with self.subTest(reason=reason):
                self.assertTrue(crawlguard.read_breaker(self.index)["tripped"])

    def test_trip_that_cannot_write_raises(self):
        with mock.patch.object(crawlguard.os, "replace", side_effect=OSError(28, "full")):
            with self.assertRaises(KbError):
                crawlguard.trip(self.index, "model_down", "x", "r", now=NOW)


class PrivateWriter(Case):
    """Finding F5 of the security review: nothing a step can call writes the breaker as not tripped except `clear`."""

    def test_the_writer_is_private_and_only_trip_and_clear_use_it(self):
        self.assertFalse(hasattr(crawlguard, "write_breaker"))
        users = sorted(name for name, f in vars(crawlguard).items() if inspect.isfunction(f) and not name.startswith("_") and "_write_breaker" in f.__code__.co_names)
        self.assertEqual(users, ["clear", "trip"])
        source = inspect.getsource(crawlguard)
        self.assertEqual(len(re.findall(r'_atomic_write\(.*"breaker.json"', source)), 1)

    def test_clear_is_the_only_public_way_to_not_tripped_and_it_needs_yes_and_a_terminal(self):
        crawlguard.trip(self.index, "model_down", "x", "r", now=NOW)
        for kwargs in ({"yes": False, "is_tty": lambda: True}, {"yes": True, "is_tty": lambda: False}):
            with self.assertRaises(KbError):
                crawlguard.clear(self.index, now=NOW, **kwargs)
            self.assertTrue(crawlguard.read_breaker(self.index)["tripped"])
        crawlguard.clear(self.index, yes=True, is_tty=lambda: True, now=NOW)
        self.assertFalse(crawlguard.read_breaker(self.index)["tripped"])

    def test_trip_screens_its_reason_against_the_secrets_of_the_log_it_is_given(self):
        log = crawllog.Log(self.index, "run-1", secrets=["hunter22"])
        out = crawlguard.trip(self.index, "stage_bound", "it failed with hunter22 in the text", "run-1", now=NOW, log=log)
        self.assertEqual(out["reason"], "the reason was withheld")
        self.assertNotIn("hunter22", open(self.crawl("breaker.json")).read())

    def test_trip_screens_its_reason_against_the_secrets_the_caller_holds(self):
        out = crawlguard.trip(self.index, "stage_bound", "it failed with hunter22 in the text", "r", now=NOW, secrets=["hunter22"])
        self.assertEqual(out["reason"], "the reason was withheld")
        self.assertNotIn("hunter22", open(self.crawl("breaker.json")).read())
        crawlguard._write_breaker(self.index, False, "", "", "", now=NOW)
        out = crawlguard.trip(self.index, "stage_bound", "it failed with hunter22 in the text", "r", now=NOW)
        self.assertIn("hunter22", out["reason"])                                  # without the secret named, it is only text


class Clear(Case):
    def tripped(self):
        crawlguard._write_breaker(self.index, True, "five failures in a row", "consecutive_failures", "r1", now=NOW)

    def test_without_yes_nothing_changes_and_it_says_so(self):
        self.tripped()
        before = open(self.crawl("breaker.json"), "rb").read()
        with self.assertRaises(KbError) as caught:
            crawlguard.clear(self.index, yes=False, is_tty=lambda: True, now=NOW)
        self.assertIn("--yes", str(caught.exception))
        self.assertEqual(open(self.crawl("breaker.json"), "rb").read(), before)
        self.assertEqual(self.log_lines(), [])

    def test_with_yes_but_no_terminal_nothing_changes_and_it_says_so(self):
        self.tripped()
        before = open(self.crawl("breaker.json"), "rb").read()
        with self.assertRaises(KbError) as caught:
            crawlguard.clear(self.index, yes=True, is_tty=lambda: False, now=NOW)
        self.assertIn("terminal", str(caught.exception))
        self.assertEqual(open(self.crawl("breaker.json"), "rb").read(), before)
        self.assertEqual(self.log_lines(), [])

    def test_the_real_terminal_check_reads_stdin_and_stdout_and_a_closed_or_missing_stream_is_not_a_terminal(self):
        def terminal(stdin_tty, stdout_tty):
            with mock.patch("sys.stdin") as i, mock.patch("sys.stdout") as o:
                i.isatty.return_value, o.isatty.return_value = stdin_tty, stdout_tty
                return crawlguard.is_terminal()
        self.assertTrue(terminal(True, True))
        self.assertFalse(terminal(True, False))                     # a redirected stdout
        self.assertFalse(terminal(False, True))                     # a pipe on stdin
        self.assertFalse(terminal(False, False))
        with mock.patch("sys.stdin") as i, mock.patch("sys.stdout") as o:
            i.isatty.side_effect = ValueError("I/O operation on closed file")      # a closed stdin
            o.isatty.return_value = True
            self.assertFalse(crawlguard.is_terminal())
        with mock.patch("sys.stdin", None), mock.patch("sys.stdout") as o:
            o.isatty.return_value = True
            self.assertFalse(crawlguard.is_terminal())
        with mock.patch("sys.stdin") as i, mock.patch("sys.stdout") as o:
            i.isatty.return_value = True
            o.isatty.side_effect = OSError(9, "bad descriptor")
            self.assertFalse(crawlguard.is_terminal())

    def test_it_is_refused_for_a_real_pipe_a_closed_stdin_and_a_redirected_stdout_in_a_child_process(self):
        self.tripped()
        script = ("import sys\nsys.path.insert(0, sys.argv[2])\nfrom kb import crawlguard, KbError\n"
                  "try:\n    crawlguard.clear(sys.argv[1], yes=True)\n    print('CLEARED')\nexcept KbError as e:\n    print('refused')\n")
        before = open(self.crawl("breaker.json"), "rb").read()
        for stdin, stdout in ((subprocess.PIPE, subprocess.PIPE), (subprocess.DEVNULL, subprocess.PIPE), (None, subprocess.PIPE)):
            proc = subprocess.run([sys.executable, "-I", "-c", script, self.index, ENGINE_DIR], stdin=stdin, stdout=stdout, stderr=subprocess.PIPE, timeout=60)
            self.assertIn(b"refused", proc.stdout, proc.stderr)
        closed = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.stdin.close()\n" + script, self.index, ENGINE_DIR], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        self.assertIn(b"refused", closed.stdout, closed.stderr)
        self.assertEqual(open(self.crawl("breaker.json"), "rb").read(), before)

    def test_with_yes_at_a_terminal_it_clears_the_breaker_and_logs_the_clear(self):
        self.tripped()
        out = crawlguard.clear(self.index, yes=True, is_tty=lambda: True, now=NOW, run="run-clear")
        self.assertFalse(out["tripped"])
        self.assertEqual(self.read_breaker_file(), {"tripped": False, "reason": "", "kind": "", "at": "2026-11-16T12:00:00Z", "run": ""})
        lines = self.log_lines()
        self.assertEqual([(l["step"], l["outcome"], l["reason"], l["run"]) for l in lines], [("breaker", "ok", "cleared by the owner", "run-clear")])
        self.assertFalse(crawlguard.read_breaker(self.index)["tripped"])

    def test_a_missing_or_unreadable_breaker_file_is_cleared_to_a_good_one_and_a_link_is_replaced(self):
        crawlguard.clear(self.index, yes=True, is_tty=lambda: True, now=NOW)
        self.assertFalse(crawlguard.read_breaker(self.index)["tripped"])
        self.put_breaker("garbage")
        crawlguard.clear(self.index, yes=True, is_tty=lambda: True, now=NOW)
        self.assertFalse(crawlguard.read_breaker(self.index)["tripped"])

    def test_the_stop_file_and_the_sites_stopped_for_the_day_are_not_touched(self):
        self.tripped()
        open(os.path.join(self.index, "crawl.stop"), "w").close()
        crawlguard.clear(self.index, yes=True, is_tty=lambda: True, now=NOW)
        self.assertTrue(os.path.exists(os.path.join(self.index, "crawl.stop")))

    def test_a_log_that_cannot_be_written_leaves_the_breaker_as_it_was(self):
        self.tripped()
        before = open(self.crawl("breaker.json"), "rb").read()
        os.makedirs(self.crawl("log"), mode=0o700)
        os.chmod(self.crawl("log"), 0o500)
        with self.assertRaises(KbError):
            crawlguard.clear(self.index, yes=True, is_tty=lambda: True, now=NOW)
        self.assertEqual(open(self.crawl("breaker.json"), "rb").read(), before)

    def test_a_clear_starts_the_guard_state_afresh(self):
        self.tripped()
        crawlguard.save_state(self.index, {"model_down_since": "2026-11-16T10:00:00Z", "history": [False] * 8})
        crawlguard.clear(self.index, yes=True, is_tty=lambda: True, now=NOW)
        self.assertEqual(crawlguard.load_state(self.index), (crawlguard.fresh_state(), False))
        p = plan(consecutive_failures=8)
        state, _ = crawlguard.load_state(self.index)
        self.assertIsNone(crawlguard.record_fetch(state, False, p))

    def test_the_run_name_of_a_clear_is_made_when_none_is_given(self):
        self.tripped()
        crawlguard.clear(self.index, yes=True, is_tty=lambda: True, now=NOW)
        self.assertRegex(self.log_lines()[0]["run"], r"^20261116T120000Z-[0-9a-f]{6}$")


class Rules(Case):
    def test_consecutive_failures_trip_at_the_number_and_not_before_and_a_success_resets(self):
        p = plan(consecutive_failures=3, window=1000, failure_share=0.99)
        state = crawlguard.fresh_state()
        self.assertIsNone(crawlguard.record_fetch(state, False, p))
        self.assertIsNone(crawlguard.record_fetch(state, False, p))
        trip = crawlguard.record_fetch(state, False, p)
        self.assertEqual(trip[0], "consecutive_failures")
        self.assertIn("3", trip[1])
        state = crawlguard.fresh_state()
        for ok in (False, False, True, False, False):
            self.assertIsNone(crawlguard.record_fetch(state, ok, p))
        self.assertEqual(crawlguard.record_fetch(state, False, p)[0], "consecutive_failures")

    def test_a_fetch_is_a_success_or_a_failure_and_nothing_else(self):
        for bad in (1, 0, None, "ok", [True]):
            with self.assertRaises(KbError):
                crawlguard.record_fetch(crawlguard.fresh_state(), bad, plan())

    def test_the_share_looks_at_exactly_the_last_window_of_fetches(self):
        p = plan(consecutive_failures=1000, window=4, failure_share=0.75)
        state = {"model_down_since": None, "history": [True, True]}
        self.assertIsNone(crawlguard.record_fetch(state, False, p))
        self.assertIsNone(crawlguard.record_fetch(state, False, p))
        trip = crawlguard.record_fetch(state, False, p)             # the last four are T, F, F, F
        self.assertEqual(trip[0], "failure_share")
        self.assertIn("3 of the last 4", trip[1])

    def test_one_failure_in_a_row_needed_trips_at_the_first_failure(self):
        p = plan(consecutive_failures=1, window=1000, failure_share=0.99)
        self.assertEqual(crawlguard.record_fetch(crawlguard.fresh_state(), False, p)[0], "consecutive_failures")
        self.assertIsNone(crawlguard.record_fetch(crawlguard.fresh_state(), True, p))

    def test_the_share_trips_only_over_a_full_window_and_at_or_over_the_share(self):
        p = plan(consecutive_failures=1000, window=4, failure_share=0.5)
        state = crawlguard.fresh_state()
        for ok in (False, False, False):                      # three of three failed, but the window of four is not full
            self.assertIsNone(crawlguard.record_fetch(state, ok, p))
        trip = crawlguard.record_fetch(state, True, p)        # now 3 of 4
        self.assertEqual(trip[0], "failure_share")
        state = crawlguard.fresh_state()
        for ok in (False, True, False):
            self.assertIsNone(crawlguard.record_fetch(state, ok, p))
        self.assertEqual(crawlguard.record_fetch(state, True, p)[0], "failure_share")        # exactly 2 of 4 is the share
        state = crawlguard.fresh_state()
        for ok in (False, True, True):
            self.assertIsNone(crawlguard.record_fetch(state, ok, p))
        self.assertIsNone(crawlguard.record_fetch(state, True, p))                           # 1 of 4 is under it
        self.assertIsNone(crawlguard.record_fetch(state, True, p))                           # the old failure has left the window

    def test_the_window_slides_over_the_last_fetches_only(self):
        p = plan(consecutive_failures=1000, window=4, failure_share=0.75)
        state = crawlguard.fresh_state()
        for ok in (False, False, False, True):
            crawlguard.record_fetch(state, ok, p)
        self.assertEqual(state["history"], [False, False, False, True])
        self.assertIsNone(crawlguard.record_fetch(state, True, p))
        self.assertEqual(state["history"][-4:], [False, False, True, True])

    def test_the_history_is_kept_as_long_as_the_rules_need_and_no_longer(self):
        p = plan(consecutive_failures=3, window=5, failure_share=0.9)
        state = crawlguard.fresh_state()
        for _ in range(30):
            crawlguard.record_fetch(state, True, p)
        self.assertEqual(len(state["history"]), 5)
        p = plan(consecutive_failures=9, window=5, failure_share=0.9)
        state = crawlguard.fresh_state()
        for _ in range(30):
            crawlguard.record_fetch(state, True, p)
        self.assertEqual(len(state["history"]), 9)

    def test_the_model_down_rule_waits_for_longer_than_the_minutes_and_a_success_forgets(self):
        p = plan(model_down_minutes=30)
        state = crawlguard.fresh_state()
        self.assertIsNone(crawlguard.note_model(state, False, NOW, p))
        self.assertEqual(state["model_down_since"], "2026-11-16T12:00:00Z")
        self.assertIsNone(crawlguard.note_model(state, False, NOW + datetime.timedelta(minutes=29, seconds=59), p))
        self.assertIsNone(crawlguard.note_model(state, False, NOW + datetime.timedelta(minutes=30), p))        # exactly the limit is not over it
        trip = crawlguard.note_model(state, False, NOW + datetime.timedelta(minutes=30, seconds=1), p)
        self.assertEqual(trip[0], "model_down")
        self.assertEqual(state["model_down_since"], "2026-11-16T12:00:00Z")                                    # the first sight is kept
        self.assertIsNone(crawlguard.note_model(state, True, NOW + datetime.timedelta(hours=2), p))
        self.assertIsNone(state["model_down_since"])
        self.assertIsNone(crawlguard.note_model(state, False, NOW + datetime.timedelta(hours=3), p))
        self.assertEqual(state["model_down_since"], "2026-11-16T15:00:00Z")

    def test_a_sighting_in_the_future_or_not_a_real_time_restarts_the_clock_and_a_probe_is_a_truth_value_only(self):
        p = plan(model_down_minutes=1)
        for since in ("2026-11-16T12:00:00Z", "9999-01-01T00:00:00Z", "2026-13-45T00:00:00Z"):
            state = {"model_down_since": since, "history": []}
            self.assertIsNone(crawlguard.note_model(state, False, NOW - datetime.timedelta(hours=5), p) if since.startswith("2026-11") else crawlguard.note_model(state, False, NOW, p))
            self.assertEqual(state["model_down_since"], _stamp_of(NOW - datetime.timedelta(hours=5)) if since.startswith("2026-11") else "2026-11-16T12:00:00Z")
        for bad in (1, 0, None, "no", []):
            with self.assertRaises(KbError):
                crawlguard.note_model(crawlguard.fresh_state(), bad, NOW, p)
        os.makedirs(self.crawl(), mode=0o700)
        for since in ("2026-13-45T00:00:00Z", "2026-02-30T00:00:00Z"):
            with open(self.crawl("guard.json"), "w") as f:
                f.write(json.dumps({"model_down_since": since, "history": []}))
            os.chmod(self.crawl("guard.json"), 0o600)
            self.assertEqual(crawlguard.load_state(self.index), (crawlguard.fresh_state(), True))

    def test_a_clock_that_went_back_does_not_trip_and_a_time_without_a_zone_is_refused(self):
        p = plan(model_down_minutes=1)
        state = {"model_down_since": "2026-11-16T12:00:00Z", "history": []}
        self.assertIsNone(crawlguard.note_model(state, False, NOW - datetime.timedelta(hours=5), p))
        with self.assertRaises(KbError):
            crawlguard.note_model(state, False, datetime.datetime(2026, 11, 16), p)

    def test_a_stage_that_hits_a_bound_is_a_trip_with_the_stage_in_its_words(self):
        kind, reason = crawlguard.bound_trip("convert", "the text was over its limit")
        self.assertEqual(kind, "stage_bound")
        self.assertIn("convert", reason)
        self.assertIn("over its limit", reason)
        with self.assertRaises(KbError):
            crawlguard.bound_trip("", "x")
        with self.assertRaises(KbError):
            crawlguard.bound_trip("convert", 5)

    def test_every_trip_the_rules_make_can_be_written_as_the_breaker(self):
        p = plan(consecutive_failures=1)
        state = crawlguard.fresh_state()
        kind, reason = crawlguard.record_fetch(state, False, p)
        crawlguard.trip(self.index, kind, reason, "r1", now=NOW)
        self.assertEqual(crawlguard.read_breaker(self.index)["kind"], "consecutive_failures")


class State(Case):
    def test_it_is_written_atomically_at_mode_600_and_read_back(self):
        state = {"model_down_since": "2026-11-16T12:00:00Z", "history": [True, False, True]}
        crawlguard.save_state(self.index, state)
        self.assertEqual(stat.S_IMODE(os.stat(self.crawl("guard.json")).st_mode), 0o600)
        self.assertEqual(crawlguard.load_state(self.index), (state, False))
        with mock.patch.object(crawlguard.os, "replace", side_effect=OSError(28, "full")):
            with self.assertRaises(KbError):
                crawlguard.save_state(self.index, {"model_down_since": None, "history": []})
        self.assertEqual(crawlguard.load_state(self.index), (state, False))
        self.assertEqual([n for n in os.listdir(self.crawl()) if n != "guard.json"], [])

    def test_a_file_that_is_not_there_is_a_fresh_state_and_one_that_cannot_be_read_restarts_the_clock_and_says_so(self):
        self.assertEqual(crawlguard.load_state(self.index), (crawlguard.fresh_state(), False))
        os.makedirs(self.crawl(), mode=0o700)
        self.assertEqual(crawlguard.load_state(self.index), (crawlguard.fresh_state(), False))
        good = {"model_down_since": "2026-11-16T12:00:00Z", "history": [True]}
        bad = ["", "{", "[]", "null", json.dumps({"model_down_since": None}), json.dumps({"history": []}), json.dumps(dict(good, extra=1)), json.dumps(dict(good, history=[1])),
               json.dumps(dict(good, history="x")), json.dumps(dict(good, model_down_since="now")), json.dumps(dict(good, model_down_since=5)), json.dumps(dict(good, history=[True] * 5000)),
               "x" * 100000]
        for text in bad:
            with open(self.crawl("guard.json"), "w") as f:
                f.write(text)
            os.chmod(self.crawl("guard.json"), 0o600)
            with self.subTest(text=text[:40]):
                self.assertEqual(crawlguard.load_state(self.index), (crawlguard.fresh_state(), True))
        with open(self.crawl("guard.json"), "w") as f:
            f.write(json.dumps(good))
        os.chmod(self.crawl("guard.json"), 0o666)
        self.assertEqual(crawlguard.load_state(self.index), (crawlguard.fresh_state(), True))
        os.chmod(self.crawl("guard.json"), 0o600)
        self.assertEqual(crawlguard.load_state(self.index), (good, False))

    def test_the_history_limit_is_exact(self):
        for count, restarted in ((1000, False), (1001, True)):
            os.makedirs(self.crawl(), mode=0o700, exist_ok=True)
            with open(self.crawl("guard.json"), "w") as f:
                f.write(json.dumps({"model_down_since": None, "history": [True] * count}))
            os.chmod(self.crawl("guard.json"), 0o600)
            self.assertEqual(crawlguard.load_state(self.index)[1], restarted, count)
        with self.assertRaises(KbError):
            crawlguard.save_state(self.index, {"model_down_since": None, "history": [True] * 1001})
        crawlguard.save_state(self.index, {"model_down_since": None, "history": [True] * 1000})

    def test_a_link_a_folder_or_a_pipe_is_not_read_and_not_written_through(self):
        os.makedirs(self.crawl(), mode=0o700)
        target = os.path.join(self.dir, "t.json")
        open(target, "w").write(json.dumps({"model_down_since": None, "history": [True]}))
        os.chmod(target, 0o600)
        os.symlink(target, self.crawl("guard.json"))
        self.assertEqual(crawlguard.load_state(self.index), (crawlguard.fresh_state(), True))
        crawlguard.save_state(self.index, {"model_down_since": None, "history": [False]})
        self.assertEqual(json.load(open(target))["history"], [True])
        self.assertFalse(os.path.islink(self.crawl("guard.json")))
        os.remove(self.crawl("guard.json"))
        os.mkdir(self.crawl("guard.json"))
        self.assertEqual(crawlguard.load_state(self.index), (crawlguard.fresh_state(), True))
        os.rmdir(self.crawl("guard.json"))
        os.mkfifo(self.crawl("guard.json"))
        self.assertEqual(crawlguard.load_state(self.index), (crawlguard.fresh_state(), True))

    def test_a_state_that_is_not_the_shape_is_not_saved(self):
        for bad in ({"model_down_since": None}, {"model_down_since": "x", "history": []}, {"model_down_since": None, "history": [1]}, [], None, {"model_down_since": None, "history": [], "x": 1}):
            with self.assertRaises(KbError):
                crawlguard.save_state(self.index, bad)

    def test_a_fresh_state_is_a_new_one_each_time(self):
        a, b = crawlguard.fresh_state(), crawlguard.fresh_state()
        a["history"].append(True)
        self.assertEqual(b, {"model_down_since": None, "history": []})


class Sites(Case):
    def conn(self):
        folder = os.path.join(self.dir, "queue")
        os.makedirs(folder, exist_ok=True)
        return crawlqueue.connect(folder)

    def put(self, conn, day, key, n):
        conn.execute("INSERT OR REPLACE INTO counters(day, key, n) VALUES (?, ?, ?)", (day, key, n))
        conn.commit()

    def test_a_site_that_reached_the_number_of_refusals_is_stopped_and_no_other_site(self):
        p = plan(domain_refusals=3, timezone="UTC")
        with closing(self.conn()) as conn:
            self.put(conn, "2026-11-16", "refusal:bad.example", 3)
            self.put(conn, "2026-11-16", "refusal:near.example", 2)
            self.put(conn, "2026-11-16", "fetch:other.example", 50)
            self.put(conn, "2026-11-16", "fetch", 80)
            refusals = crawlguard.refusals_today(conn, p, NOW)
        self.assertEqual(refusals, {"bad.example": 3, "near.example": 2})
        self.assertTrue(crawlguard.site_stopped(refusals, "bad.example", p))
        self.assertFalse(crawlguard.site_stopped(refusals, "near.example", p))
        self.assertFalse(crawlguard.site_stopped(refusals, "other.example", p))
        self.assertTrue(crawlguard.site_stopped({"x.example": 4}, "x.example", p))
        self.assertFalse(crawlguard.site_stopped({}, "x.example", p))

    def test_what_is_not_a_table_of_sites_or_a_site_is_not_a_stop(self):
        p = plan(domain_refusals=1)
        for refusals in (None, [], "bad.example", 5):
            self.assertTrue(crawlguard.site_stopped(refusals, "bad.example", p))        # what is not a table is not let through
        for site in (None, 5, ["bad.example"], b"bad.example"):
            self.assertTrue(crawlguard.site_stopped({"bad.example": 9}, site, p))

    def test_it_reads_and_changes_nothing_and_does_not_touch_the_breaker(self):
        p = plan(domain_refusals=1, timezone="UTC")
        with closing(self.conn()) as conn:
            self.put(conn, "2026-11-16", "refusal:bad.example", 9)
            before = conn.execute("SELECT day, key, n FROM counters ORDER BY day, key").fetchall()
            statements = []
            conn.set_trace_callback(statements.append)
            crawlguard.site_stopped(crawlguard.refusals_today(conn, p, NOW), "bad.example", p)
            conn.set_trace_callback(None)
            self.assertEqual(conn.execute("SELECT day, key, n FROM counters ORDER BY day, key").fetchall(), before)
        self.assertTrue(all(s.lstrip().upper().startswith("SELECT") for s in statements), statements)
        self.assertFalse(os.path.exists(self.crawl("breaker.json")))

    def test_the_stop_is_gone_the_next_day_at_the_edge_in_a_zone_with_a_change_of_clock(self):
        p = plan(domain_refusals=2, timezone="America/New_York")
        with closing(self.conn()) as conn:
            self.put(conn, "2026-11-01", "refusal:bad.example", 2)       # the day the clocks go back: 25 hours long
            for now, stopped in ((datetime.datetime(2026, 11, 1, 4, 0, tzinfo=UTC), True),        # 00:00 EDT
                                 (datetime.datetime(2026, 11, 1, 5, 30, tzinfo=UTC), True),       # 01:30 EDT
                                 (datetime.datetime(2026, 11, 1, 6, 30, tzinfo=UTC), True),       # 01:30 EST, the same hour again
                                 (datetime.datetime(2026, 11, 2, 4, 59, 59, tzinfo=UTC), True),   # 23:59:59 EST
                                 (datetime.datetime(2026, 11, 2, 5, 0, 0, tzinfo=UTC), False),    # 00:00 EST of the next day
                                 (datetime.datetime(2026, 10, 31, 23, 0, tzinfo=UTC), False)):    # the evening before
                with self.subTest(now=now.isoformat()):
                    self.assertEqual(crawlguard.site_stopped(crawlguard.refusals_today(conn, p, now), "bad.example", p), stopped)

    def test_the_day_is_the_plans_day_and_a_time_without_a_zone_is_refused(self):
        p = plan(domain_refusals=1, timezone="Asia/Tokyo")
        with closing(self.conn()) as conn:
            self.put(conn, "2026-11-17", "refusal:bad.example", 1)       # 12:00 UTC on the 16th is 21:00 on the 16th in Tokyo; 15:30 UTC is the 17th there
            self.assertEqual(crawlguard.refusals_today(conn, p, NOW), {})
            self.assertEqual(crawlguard.refusals_today(conn, p, datetime.datetime(2026, 11, 16, 15, 30, tzinfo=UTC)), {"bad.example": 1})
            with self.assertRaises(KbError):
                crawlguard.refusals_today(conn, p, datetime.datetime(2026, 11, 16, 12, 0))

    def test_a_counter_that_is_not_a_number_or_a_key_that_is_not_a_site_is_not_a_stop(self):
        p = plan(domain_refusals=1, timezone="UTC")
        with closing(self.conn()) as conn:
            self.put(conn, "2026-11-16", "refusal:", 5)
            self.put(conn, "2026-11-16", "refusals:x.example", 5)
            self.put(conn, "2026-11-16", "refusal:ok.example", 1)
            self.assertEqual(crawlguard.refusals_today(conn, p, NOW), {"ok.example": 1})


class Disk(Case):
    class Reading:
        def __init__(self, free, frsize=4096):
            self.f_bavail, self.f_frsize, self.f_bfree = free // frsize, frsize, free * 10 // frsize

    def check(self, bulk, index, **changes):
        p = plan(bulk_floor_gb=50, index_floor_gb=10)
        p.update(changes)
        free = {"/bulk": bulk, "/index": index}

        def statvfs(path):
            value = free[path]
            if isinstance(value, Exception):
                raise value
            return value if not isinstance(value, int) else self.Reading(value)

        return crawlguard.check_disk("/bulk", "/index", p, statvfs=statvfs)

    def test_both_drives_over_their_floors_are_fine(self):
        self.assertIsNone(self.check(51 * 10**9, 11 * 10**9))
        self.assertIsNone(self.check(10**13, 10**13))

    def test_a_drive_at_or_under_its_floor_refuses_and_names_which(self):
        with self.assertRaises(KbError) as caught:
            self.check(50 * 10**9, 11 * 10**9)
        self.assertIn("bulk", str(caught.exception))
        with self.assertRaises(KbError) as caught:
            self.check(51 * 10**9, 10 * 10**9)
        self.assertIn("index", str(caught.exception))
        with self.assertRaises(KbError) as caught:
            self.check(1, 1)
        self.assertIn("bulk", str(caught.exception))
        self.assertIn("index", str(caught.exception))
        for free in (50 * 10**9 - 1, 0):
            with self.assertRaises(KbError):
                self.check(free, 11 * 10**9)

    def test_free_space_exactly_at_the_floor_refuses_and_one_block_more_does_not(self):
        with self.assertRaises(KbError):
            self.check(self.Reading(50 * 10**9, frsize=1000), 11 * 10**9)
        self.assertIsNone(self.check(self.Reading(50 * 10**9 + 1000, frsize=1000), 11 * 10**9))
        with self.assertRaises(KbError):
            self.check(51 * 10**9, self.Reading(10 * 10**9, frsize=1000))

    def test_a_floor_of_zero_refuses_only_a_full_drive(self):
        self.assertIsNone(self.check(4096, 4096, bulk_floor_gb=0, index_floor_gb=0))
        with self.assertRaises(KbError):
            self.check(0, 4096, bulk_floor_gb=0, index_floor_gb=0)

    def test_a_count_that_is_a_truth_value_is_not_a_reading_even_when_the_floors_are_zero(self):
        class Odd:
            def __init__(self, avail, size):
                self.f_bavail, self.f_frsize = avail, size
        for avail, size in ((True, 4096), (4096, True), (True, True), (-5, 4096), (5, -4096)):
            with self.subTest(avail=avail, size=size):
                with self.assertRaises(KbError):
                    crawlguard.check_disk("/b", "/i", plan(bulk_floor_gb=0, index_floor_gb=0), statvfs=lambda p, a=avail, s=size: Odd(a, s))

    def test_the_space_a_normal_user_can_use_is_what_counts(self):
        class Odd:
            f_bavail, f_frsize, f_bfree = 1, 4096, 10**12
        with self.assertRaises(KbError):
            crawlguard.check_disk("/bulk", "/index", plan(), statvfs=lambda p: Odd())

    def test_a_reading_that_fails_or_is_not_a_number_refuses(self):
        for bad in (OSError(5, "io"), PermissionError(13, "denied"), FileNotFoundError(2, "none")):
            with self.subTest(bad=type(bad).__name__):
                with self.assertRaises(KbError):
                    self.check(bad, 11 * 10**9)
                with self.assertRaises(KbError):
                    self.check(51 * 10**9, bad)

        class Broken:
            def __init__(self, avail, size):
                self.f_bavail, self.f_frsize = avail, size
        for avail, size in ((None, 4096), (1.5, 4096), (-1, 4096), (10**9, 0), (10**9, -4096), (10**9, None), ("5", 4096), (True, 4096), (10**9, True)):
            with self.subTest(avail=avail, size=size):
                with self.assertRaises(KbError):
                    crawlguard.check_disk("/bulk", "/index", plan(), statvfs=lambda p, a=avail, s=size: Broken(a, s))
        with self.assertRaises(KbError):
            crawlguard.check_disk("/bulk", "/index", plan(), statvfs=lambda p: object())

    def test_it_reads_the_real_drive_by_default_and_a_missing_path_refuses(self):
        self.assertIsNone(crawlguard.check_disk(self.dir, self.dir, plan(bulk_floor_gb=0, index_floor_gb=0)))
        with self.assertRaises(KbError):
            crawlguard.check_disk(os.path.join(self.dir, "nowhere"), self.dir, plan(bulk_floor_gb=0, index_floor_gb=0))

    def test_each_drive_is_read_once_per_check_and_with_its_own_path(self):
        seen = []

        def statvfs(path):
            seen.append(path)
            return self.Reading(10**13)

        crawlguard.check_disk("/b", "/i", plan(), statvfs=statvfs)
        self.assertEqual(seen, ["/b", "/i"])


class Probe(Case):
    CFG = {"models_on": True, "tasks": {"card-embed": "emb"}, "models": {"emb": {"kind": "embedding"}}}

    def test_a_reply_is_a_live_server_and_one_short_text_is_sent_to_the_embedding_entry(self):
        calls = []

        def embed(cfg, name, texts, **kw):
            calls.append((name, texts, kw))
            return {"model": "m", "dimension": 8, "vectors": [[0.1] * 8]}

        self.assertTrue(crawlguard.probe_model(self.CFG, embed=embed))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "emb")
        self.assertEqual(len(calls[0][1]), 1)
        self.assertLess(len(calls[0][1][0]), 40)
        self.assertTrue(calls[0][1][0].strip())

    def test_any_refusal_or_error_of_the_call_is_a_server_that_does_not_answer(self):
        for error in (KbError("down"), OSError(111, "refused"), TimeoutError("slow"), ConnectionError("reset")):
            with self.subTest(error=type(error).__name__):
                def embed(cfg, name, texts, error=error, **kw):
                    raise error
                self.assertFalse(crawlguard.probe_model(self.CFG, embed=embed))

    def test_a_reply_with_no_vectors_is_not_an_answer(self):
        for reply in (None, {}, {"vectors": []}, {"vectors": None}, "ok", {"vectors": [[]]}):
            with self.subTest(reply=str(reply)):
                self.assertFalse(crawlguard.probe_model(self.CFG, embed=lambda cfg, name, texts, **kw: reply))

    def test_a_config_without_an_embedding_task_does_not_call_and_is_not_an_answer(self):
        def embed(*a, **k):
            raise AssertionError("must not be called")
        for cfg in ({"tasks": {}}, {}, {"tasks": {"card-embed": 5}}, {"tasks": []}, None):
            self.assertFalse(crawlguard.probe_model(cfg, embed=embed))

    def test_a_bug_in_the_call_is_not_hidden_as_a_server_that_is_down(self):
        def embed(cfg, name, texts, **kw):
            raise AssertionError("a bug")
        with self.assertRaises(AssertionError):
            crawlguard.probe_model(self.CFG, embed=embed)


class Wiring(Case):
    def test_the_module_reads_no_environment_makes_no_request_and_starts_no_program(self):
        with open(os.path.join(ENGINE_DIR, "kb", "crawlguard.py"), encoding="utf-8") as f:
            source = f.read()
        for word in ("socket", "urllib", "http.client", "subprocess", "os.environ", "getenv", "webclient", "UPDATE", "DELETE", "INSERT"):
            self.assertNotIn(word, source, word)

    def test_the_clear_command_has_a_yes_option_and_no_other_and_prints_what_it_did(self):
        from kb import __main__ as cli
        cfg = {"index_root": self.index}
        with mock.patch.object(cli.config, "load", return_value=cfg), mock.patch.object(crawlguard, "clear", return_value={"tripped": False}) as clear, mock.patch("builtins.print") as shown:
            self.assertEqual(cli.main(["crawl-clear", "--yes"]), 0)
            self.assertTrue(clear.call_args.kwargs["yes"])
            self.assertEqual(clear.call_args.args[0], self.index)
            self.assertTrue(shown.called)
        with mock.patch.object(cli.config, "load", return_value=cfg), mock.patch.object(crawlguard, "clear", return_value={"tripped": False}) as clear, mock.patch("builtins.print"):
            self.assertEqual(cli.main(["crawl-clear"]), 0)
            self.assertFalse(clear.call_args.kwargs["yes"])
        with self.assertRaises(SystemExit):
            with mock.patch("sys.stderr"):
                cli.main(["crawl-clear", "--yes", "--force"])

    def test_the_clear_command_without_a_terminal_changes_nothing_and_exits_with_an_error(self):
        from kb import __main__ as cli
        crawlguard._write_breaker(self.index, True, "x", "model_down", "r", now=NOW)
        before = open(self.crawl("breaker.json"), "rb").read()
        with mock.patch.object(cli.config, "load", return_value={"index_root": self.index}), mock.patch("sys.stdin") as i, mock.patch("sys.stdout") as o, mock.patch("sys.stderr"):
            i.isatty.return_value, o.isatty.return_value = False, True
            self.assertNotEqual(cli.main(["crawl-clear", "--yes"]), 0)
        self.assertEqual(open(self.crawl("breaker.json"), "rb").read(), before)


if __name__ == "__main__":
    unittest.main()
