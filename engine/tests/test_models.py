import json
import os
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

from engine.tests import ENGINE_DIR  # noqa: F401  (puts the engine folder on the path)

from kb import KbError, models

GOOD = {"contract": 2, "ok": True, "vendor": "ollama", "model": "m1:latest", "reply": "hello",
        "usage": {"input_tokens": 7, "output_tokens": 3, "total_tokens": None, "cached_input_tokens": None,
                  "reasoning_output_tokens": None}}

FAKE = """#!{python}
import json, os, subprocess, sys, time
here = os.path.dirname(os.path.abspath(__file__))
plan = json.load(open(os.path.join(here, "plan.json")))
json.dump(sys.argv[1:], open(os.path.join(here, "args.json"), "w"))
if not plan.get("noread"):
    open(os.path.join(here, "stdin.bin"), "wb").write(sys.stdin.buffer.read())
open(os.path.join(here, "cwd.txt"), "w").write(os.getcwd())
if plan.get("child"):
    child = subprocess.Popen(["sleep", "30"])
    open(os.path.join(here, "child.pid"), "w").write(str(child.pid))
if plan.get("sleep"):
    time.sleep(plan["sleep"])
if plan.get("flood"):
    sys.stdout.write("x" * plan["flood"])
    sys.stdout.flush()
    time.sleep(plan.get("sleep_after", 0))
else:
    sys.stdout.write(plan.get("stdout", ""))
sys.stderr.write(plan.get("stderr", ""))
sys.exit(plan.get("exit", 0))
"""


def entry(**over):
    e = {"bridge": "ask-ollama", "server": "srv", "model": "m1:latest"}
    e.update(over)
    return e


def config(models_on=True, **entries):
    return {"models_on": models_on, "models": entries or {"local": entry()}}


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = os.path.realpath(self._tmp.name)
        self.root = os.path.join(self.dir, "project")
        os.mkdir(self.root)
        self.launcher = os.path.join(self.dir, "wb")
        with open(self.launcher, "w") as f:
            f.write(FAKE.format(python=sys.executable))
        os.chmod(self.launcher, 0o700)
        self.plan(stdout=json.dumps(GOOD))

    def plan(self, **p):
        with open(os.path.join(self.dir, "plan.json"), "w") as f:
            json.dump(p, f)

    def seen(self, name):
        path = os.path.join(self.dir, name)
        if not os.path.exists(path):
            return None
        mode = "rb" if name.endswith(".bin") else "r"
        with open(path, mode) as f:
            text = f.read()
        return json.loads(text) if name.endswith(".json") else text

    def call(self, prompt="a question", cfg=None, name="local"):
        return models.call(cfg or config(), name, prompt, launcher=self.launcher, root=self.root)

    def refused(self, *args, **kw):
        with self.assertRaises(KbError) as cm:
            self.call(*args, **kw)
        return str(cm.exception)


class CallTest(Base):
    def test_a_good_call_sends_the_argument_list_and_the_prompt_on_standard_input(self):
        got = self.call("the prompt text")
        self.assertEqual(self.seen("args.json"), ["run", "ask-ollama", "ask", "--server", "srv", "--model", "m1:latest"])
        self.assertEqual(self.seen("stdin.bin"), b"the prompt text")
        self.assertEqual(self.seen("cwd.txt"), self.root)
        self.assertEqual(got["reply"], "hello")
        self.assertEqual(got["model"], "m1:latest")
        self.assertEqual(got["usage"], {"input_tokens": 7, "output_tokens": 3})

    def test_the_prompt_is_never_an_argument(self):
        self.call("secret-words-in-the-prompt")
        self.assertNotIn("secret-words-in-the-prompt", " ".join(self.seen("args.json")))

    def test_the_optional_fields_become_options(self):
        cfg = config(local=entry(max_output=500, thinking="off", timeout=90))
        self.call(cfg=cfg)
        args = self.seen("args.json")
        self.assertEqual(args[args.index("--max-output") + 1], "500")
        self.assertEqual(args[args.index("--thinking") + 1], "off")
        self.assertEqual(args[args.index("--timeout") + 1], "90")

    def test_a_prompt_with_non_ascii_text_goes_in_as_utf8(self):
        self.call("café ☃")
        self.assertEqual(self.seen("stdin.bin"), "café ☃".encode("utf-8"))

    def test_the_usage_may_lack_counts(self):
        self.plan(stdout=json.dumps(dict(GOOD, usage={"input_tokens": None, "output_tokens": None})))
        self.assertEqual(self.call()["usage"], {"input_tokens": None, "output_tokens": None})


class RefusalBeforeSendTest(Base):
    def assertNotRun(self):
        self.assertIsNone(self.seen("args.json"))

    def test_a_prompt_over_the_limit(self):
        self.assertIn("too large", self.refused("a" * (models.MAX_PROMPT + 1)))
        self.assertNotRun()

    def test_a_prompt_at_the_limit_is_sent(self):
        self.call("a" * models.MAX_PROMPT)
        self.assertEqual(len(self.seen("stdin.bin")), models.MAX_PROMPT)

    def test_the_limit_counts_bytes_not_characters(self):
        self.assertIn("too large", self.refused("é" * (models.MAX_PROMPT // 2 + 1)))
        self.assertNotRun()

    def test_an_empty_prompt(self):
        for p in ("", "   \n"):
            self.assertIn("empty", self.refused(p))
        self.assertNotRun()

    def test_a_prompt_that_is_not_text(self):
        for p in (None, b"bytes", 5):
            with self.assertRaises(KbError):
                self.call(p)
        self.assertNotRun()

    def test_an_unlisted_model(self):
        self.assertIn("not listed", self.refused(name="other"))
        self.assertNotRun()

    def test_the_switch_off_missing_or_not_a_boolean(self):
        for cfg in (config(models_on=False), {"models": {"local": entry()}}, config(models_on="yes"), config(models_on=1)):
            self.assertIn("off", self.refused(cfg=cfg))
        self.assertNotRun()

    def test_a_launcher_that_is_not_found(self):
        with self.assertRaises(KbError) as cm:
            models.call(config(), "local", "q", launcher=os.path.join(self.dir, "nope"), root=self.root)
        self.assertIn("not found", str(cm.exception))

    def test_no_launcher_on_the_path(self):
        with mock.patch.object(models.shutil, "which", return_value=None):
            with self.assertRaises(KbError) as cm:
                models.call(config(), "local", "q", root=self.root)
        self.assertIn("not found", str(cm.exception))

    def test_a_launcher_that_is_not_a_file_or_not_executable(self):
        plain = os.path.join(self.dir, "plain")
        with open(plain, "w") as f:
            f.write("x")
        os.chmod(plain, 0o600)
        for target in (plain, self.dir):
            with self.assertRaises(KbError):
                models.call(config(), "local", "q", launcher=target, root=self.root)


class RegistryTest(Base):
    def assertBad(self, cfg, text=None):
        if os.path.exists(os.path.join(self.dir, "args.json")):
            os.remove(os.path.join(self.dir, "args.json"))  # a record left by an earlier case in the same test
        message = self.refused(cfg=cfg)
        self.assertIsNone(self.seen("args.json"), message)
        if text:
            self.assertIn(text, message)

    def test_hostile_values_are_refused_before_anything_runs(self):
        hostile = ["-x", "--model", "a b", "a\nb", "a\x00b", "", "a;b", "$(x)", "`x`", "../x", "a..b", "x" * 200, "аbc", "a‮b",
                   " lead", "trail ", "srv\n", "/a", "a/", "a//b", "a/-b", 5, None, ["a"], {"a": 1}, True]
        for field in ("server", "model"):
            for value in hostile:
                with self.subTest(field=field, value=value):
                    self.assertBad(config(local=entry(**{field: value})))

    def test_a_server_name_has_no_slash_but_a_model_may_be_namespaced(self):
        self.assertBad(config(local=entry(server="a/b")))
        self.call(cfg=config(local=entry(model="org/name:tag")))
        args = self.seen("args.json")
        self.assertEqual(args[args.index("--model") + 1], "org/name:tag")

    def test_a_model_name_is_as_long_as_the_bridge_allows(self):
        self.call(cfg=config(local=entry(model="a" * 128)))
        self.assertBad(config(local=entry(model="a" * 129)))

    def test_a_hostile_model_name_in_the_registry(self):
        for name in ("-x", "a b", "A", "", "x" * 40, "a\n"):
            with self.subTest(name=name):
                cfg = {"models_on": True, "models": {name: entry()}}
                with self.assertRaises(KbError):
                    models.call(cfg, name, "q", launcher=self.launcher, root=self.root)
        self.assertIsNone(self.seen("args.json"))

    def test_the_bridge_must_be_the_ollama_bridge(self):
        for value in ("ask-codex", "", None, "ask-ollama ", "ask-ollama\n"):
            with self.subTest(value=value):
                self.assertBad(config(local=entry(bridge=value)))

    def test_missing_fields(self):
        for field in ("bridge", "server", "model"):
            e = entry()
            del e[field]
            with self.subTest(field=field):
                self.assertBad(config(local=e), field)

    def test_an_unknown_key_in_an_entry(self):
        self.assertBad(config(local=entry(root="/x")), "root")

    def test_the_optional_fields_are_checked(self):
        for key, bad in (("max_output", [0, -1, 1.5, "5", True, 10 ** 9]), ("thinking", ["", "yes", "on ", 1, True]),
                         ("timeout", [0, -3, 3601, 10000, 1.5, "9", True])):
            for value in bad:
                with self.subTest(key=key, value=value):
                    self.assertBad(config(local=entry(**{key: value})))

    def test_the_registry_must_be_an_object_of_objects(self):
        for models_value in (None, [], "x", {"local": "x"}, {"local": None}, {"local": []}):
            with self.subTest(models_value=models_value):
                self.assertBad({"models_on": True, "models": models_value})

    def test_a_bad_entry_refuses_a_call_to_a_good_one(self):
        # one wrong entry means the config is wrong, so nothing runs on a guess about which entry was meant
        cfg = config(local=entry(), other=entry(server="-x"))
        self.assertBad(cfg)

    def test_a_listing_names_the_entries_without_a_call(self):
        listed = models.listing(config(local=entry(), other=entry(model="m2")))
        self.assertEqual([row["name"] for row in listed["models"]], ["local", "other"])
        self.assertTrue(listed["on"])
        self.assertIsNone(self.seen("args.json"))


class ProcessTest(Base):
    def test_a_call_that_runs_too_long_is_killed_with_what_it_started(self):
        self.plan(child=True, sleep=30)
        with mock.patch.object(models, "GRACE", 0):
            began = time.monotonic()
            message = self.refused(cfg=config(local=entry(timeout=1)))
            took = time.monotonic() - began
        self.assertIn("time", message)
        self.assertLess(took, 10)
        pid = int(self.seen("child.pid"))
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            self.fail("the child of the launcher is still running")

    def test_output_over_the_limit_ends_the_call_at_once(self):
        self.plan(flood=5_000_000, sleep_after=30)
        began = time.monotonic()
        with mock.patch.object(models, "GRACE", 0):  # a failure of the cap shows as the time limit, not as a long wait
            message = self.refused(cfg=config(local=entry(timeout=3)))
        self.assertLess(time.monotonic() - began, 10)
        self.assertIn("too much", message)

    def test_a_launcher_that_never_reads_a_large_prompt_is_still_stopped(self):
        self.plan(sleep=30, noread=True)
        with mock.patch.object(models, "GRACE", 0):
            message = self.refused("a" * models.MAX_PROMPT, cfg=config(local=entry(timeout=1)))
        self.assertIn("time", message)


class ReplyTest(Base):
    def reply(self, **over):
        doc = dict(GOOD)
        doc.update(over)
        self.plan(stdout=json.dumps(doc))
        return self.refused()

    def test_text_that_is_not_json(self):
        for out in ("", "not json", "{", "\xff", "[1]", "null", '"x"', "5"):
            self.plan(stdout=out)
            with self.subTest(out=out):
                self.refused()

    def test_the_contract_must_be_the_integer_two(self):
        for value in (1, 3, "2", 2.0, 2.5, True, None, [2]):
            with self.subTest(value=value):
                self.reply(contract=value)

    def test_a_missing_contract(self):
        doc = dict(GOOD)
        del doc["contract"]
        self.plan(stdout=json.dumps(doc))
        self.refused()

    def test_ok_must_be_a_boolean(self):
        for value in ("true", 1, None, "yes"):
            with self.subTest(value=value):
                self.reply(ok=value)

    def test_the_vendor_must_be_ollama(self):
        for value in ("codex", None, 5, "Ollama"):
            with self.subTest(value=value):
                self.reply(vendor=value)

    def test_a_reply_must_be_a_non_empty_string_within_the_limit(self):
        for value in (None, 5, ["x"], "", {"a": 1}, "x" * (models.MAX_REPLY + 1)):
            with self.subTest(value=type(value).__name__):
                self.reply(reply=value)

    def test_a_missing_reply(self):
        doc = dict(GOOD)
        del doc["reply"]
        self.plan(stdout=json.dumps(doc))
        self.refused()

    def test_the_model_must_be_a_short_string(self):
        for value in (None, 5, "x" * 500, "a" * 129, "../x", "a b"):
            with self.subTest(value=str(value)[:10]):
                self.reply(model=value)

    def test_a_namespaced_model_name_in_a_reply_is_accepted(self):
        self.plan(stdout=json.dumps(dict(GOOD, model="org/name:tag")))
        self.assertEqual(self.call()["model"], "org/name:tag")

    def test_the_usage_must_hold_counts_or_nothing(self):
        for value in (None, 5, "x", [], {"input_tokens": "7", "output_tokens": 1}, {"input_tokens": -1, "output_tokens": 1},
                      {"input_tokens": 1.5, "output_tokens": 1}, {"input_tokens": True, "output_tokens": 1}, {"input_tokens": 1}):
            with self.subTest(value=value):
                self.reply(usage=value)

    def test_a_failure_reply_gives_its_reason(self):
        self.plan(stdout=json.dumps({"contract": 2, "ok": False, "vendor": "ollama", "error": "unreachable",
                                     "detail": "the server did not answer"}), exit=1)
        message = self.refused()
        self.assertIn("unreachable", message)

    def test_a_failure_reason_is_cleaned_and_cut(self):
        text = "bad \x1b[31mred\x1b[0m ‮" + "z" * 1000
        self.plan(stdout=json.dumps({"contract": 2, "ok": False, "vendor": "ollama", "error": text, "detail": text}), exit=1)
        message = self.refused()
        self.assertNotIn("\x1b", message)
        self.assertNotIn("‮", message)
        self.assertLess(len(message), 600)

    def test_ok_false_with_exit_zero_is_still_a_failure(self):
        self.plan(stdout=json.dumps({"contract": 2, "ok": False, "vendor": "ollama", "error": "x"}), exit=0)
        self.refused()

    def test_a_good_reply_with_a_failing_exit_is_refused(self):
        self.plan(stdout=json.dumps(GOOD), exit=1)
        self.refused()

    def test_a_failing_exit_with_no_json_reports_the_exit_and_a_cleaned_stderr(self):
        self.plan(stdout="", stderr="refused: \x1b[1mnope\x1b[0m\n", exit=2)
        message = self.refused()
        self.assertIn("2", message)
        self.assertIn("nope", message)
        self.assertNotIn("\x1b", message)

    def test_a_reply_with_a_repeated_key_is_refused(self):
        self.plan(stdout='{"contract": 2, "contract": 2, "ok": true, "vendor": "ollama", "model": "m", "reply": "r", '
                         '"usage": {"input_tokens": 1, "output_tokens": 1}}')
        self.refused()

    def test_the_reply_is_returned_unchanged_so_a_later_step_can_check_it(self):
        text = "line1\n\tline2 \x1b[0m"
        self.plan(stdout=json.dumps(dict(GOOD, reply=text)))
        self.assertEqual(self.call()["reply"], text)


if __name__ == "__main__":
    unittest.main()
