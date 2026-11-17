"""The text of the scheduler of the unattended crawl (`kb/crawlschedule.py`, Increment N of the plan `2026-11-16-run-the-steps-of-the-unattended-crawl`).

`crawlschedule.text(index_root, engine_dir, python)` is the text of a macOS launchd agent that starts `python3 -X pycache_prefix=<a folder under the index root> -m kb crawl-run` every 900 seconds from the engine
folder, with the agent's own output kept outside the crawl's log, and nothing else. It is only printed: the module and the command write no file, load no config of their own, read no environment variable, start no
process and make no request, and the owner installs the text by hand. These tests parse the text as a property list, run the printed command from its working folder, and check that every command the README's
checklist names is a command of the engine. They use temporary folders and never the owner's library, config, plan or key.
Run them with `python3 -W error::ResourceWarning -m unittest engine.tests.test_crawlschedule`."""
import ast
import builtins
import contextlib
import inspect
import io
import os
import plistlib
import re
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from engine.tests import ENGINE_DIR
from engine.tests.test_store import StoreCase

from kb import KbError, __main__ as kb_main, config, crawlguard, crawlrun, crawlschedule

REPO = os.path.dirname(ENGINE_DIR)
INDEX = "/Volumes/library/index root"
ENGINE = "/Users/example/projects/knowledge-base/engine"
PREFIX = INDEX + "/crawl-pycache"
OUTPUT = INDEX + "/crawl-agent.log"
SECTION = "## Running the crawl unattended"


def parsed(text):
    return plistlib.loads(text.encode("utf-8"))


class TheText(unittest.TestCase):
    def test_it_is_a_property_list_with_these_keys_and_no_others(self):
        text = crawlschedule.text(INDEX, ENGINE)
        agent = parsed(text)
        self.assertEqual(sorted(agent), ["Label", "ProgramArguments", "StandardErrorPath", "StandardOutPath", "StartInterval", "WorkingDirectory"])
        self.assertTrue(text.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">'))
        self.assertTrue(text.endswith("</plist>\n"))
        self.assertIn('<plist version="1.0">\n<dict>', text)

    def test_the_program_is_python3_with_the_bytecode_folder_then_the_module_and_the_command(self):
        agent = parsed(crawlschedule.text(INDEX, ENGINE))
        self.assertEqual(agent["ProgramArguments"], ["python3", "-X", "pycache_prefix=" + PREFIX, "-m", "kb", "crawl-run"])

    def test_it_runs_every_900_seconds_and_nothing_makes_it_run_at_load_or_keeps_it_alive(self):
        text = crawlschedule.text(INDEX, ENGINE)
        agent = parsed(text)
        self.assertEqual(agent["StartInterval"], 900)
        self.assertIs(type(agent["StartInterval"]), int)
        for key in ("RunAtLoad", "KeepAlive", "EnvironmentVariables", "StartCalendarInterval", "WatchPaths", "ThrottleInterval", "Program", "UserName"):
            self.assertNotIn(key, agent)
            self.assertNotIn("<key>" + key + "</key>", text)

    def test_the_working_folder_is_the_engine_folder_it_was_given(self):
        self.assertEqual(parsed(crawlschedule.text(INDEX, ENGINE))["WorkingDirectory"], ENGINE)

    def test_the_agents_own_output_goes_to_one_file_under_the_index_root_and_outside_the_crawls_log(self):
        agent = parsed(crawlschedule.text(INDEX, ENGINE))
        self.assertEqual((agent["StandardOutPath"], agent["StandardErrorPath"]), (OUTPUT, OUTPUT))
        crawl = os.path.join(INDEX, "crawl")
        self.assertFalse(OUTPUT.startswith(crawl + os.sep))
        self.assertNotEqual(os.path.dirname(OUTPUT), crawl)

    def test_the_label_is_a_fixed_name_of_this_agent(self):
        self.assertEqual(parsed(crawlschedule.text(INDEX, ENGINE))["Label"], "local.knowledge-base.crawl-run")

    def test_the_text_names_the_folder_and_tells_the_owner_to_make_it_private_before_installing(self):
        text = crawlschedule.text(INDEX, ENGINE)
        comment = text[text.index("<!--"):text.index("-->")]
        self.assertIn(PREFIX, comment)
        self.assertIn("mode 700", comment)
        self.assertIn("before", comment.lower())
        self.assertIn(OUTPUT, comment)
        self.assertEqual(text.count("<!--"), 1)

    def test_the_text_says_unattended_and_nothing_else_about_when_or_for_how_long_it_runs(self):
        text = crawlschedule.text(INDEX, ENGINE).lower()
        self.assertIn("unattended", text)
        for word in ("night", "away", "vacation", "holiday", "weekend", "overnight", "sleep", "asleep", "hours a day", "all day"):
            self.assertNotIn(word, text)

    def test_the_text_is_the_same_for_the_same_arguments(self):
        self.assertEqual(crawlschedule.text(INDEX, ENGINE), crawlschedule.text(INDEX, ENGINE))

    def test_a_python_is_python3_or_a_full_path(self):
        self.assertEqual(parsed(crawlschedule.text(INDEX, ENGINE, "/usr/bin/python3"))["ProgramArguments"][0], "/usr/bin/python3")
        self.assertEqual(parsed(crawlschedule.text(INDEX, ENGINE, "python3"))["ProgramArguments"][0], "python3")
        for bad in ("python", "python3.15", "bin/python3", "", None, 3, "/usr/bin/python3\n", "/usr/bin/python3/", "/usr/bin/", "/usr/bin//"):
            with self.subTest(bad), self.assertRaises(KbError):
                crawlschedule.text(INDEX, ENGINE, bad)

    def test_the_constants_are_what_the_plan_says(self):
        self.assertEqual((crawlschedule.INTERVAL, crawlschedule.LABEL, crawlschedule.PREFIX_NAME, crawlschedule.OUTPUT_NAME), (900, "local.knowledge-base.crawl-run", "crawl-pycache", "crawl-agent.log"))


class Escaping(unittest.TestCase):
    ODD = "/Volumes/a & b <c> \"d\" 'e'/index"

    def test_a_path_with_markup_characters_is_escaped_and_comes_back_whole(self):
        text = crawlschedule.text(self.ODD, ENGINE)
        agent = parsed(text)
        self.assertEqual(agent["ProgramArguments"][2], "pycache_prefix=" + self.ODD + "/crawl-pycache")
        self.assertEqual(agent["StandardOutPath"], self.ODD + "/crawl-agent.log")
        body = text[text.index("<plist"):]
        self.assertNotIn("a & b", body)
        self.assertIn("a &amp; b &lt;c&gt;", body)

    def test_the_engine_folder_is_escaped_too(self):
        odd = "/Users/a&b/<engine>"
        self.assertEqual(parsed(crawlschedule.text(INDEX, odd))["WorkingDirectory"], odd)

    def test_a_path_with_a_space_and_with_non_ascii_letters_is_kept(self):
        index = "/Volumes/Bücher und mehr/ index"
        agent = parsed(crawlschedule.text(index, ENGINE))
        self.assertEqual(agent["StandardOutPath"], index + "/crawl-agent.log")

    def test_a_path_that_ends_in_a_slash_does_not_double_it(self):
        agent = parsed(crawlschedule.text(INDEX + "/", ENGINE + "/"))
        self.assertEqual(agent["ProgramArguments"][2], "pycache_prefix=" + PREFIX)
        self.assertEqual(agent["WorkingDirectory"], ENGINE)
        self.assertEqual(agent["StandardOutPath"], OUTPUT)


class Refusals(unittest.TestCase):
    BAD = ("", "relative/path", "./index", "index", "~/index", "/a\nb", "/a\rb", "/a\tb", "/a\x00b", "/a\x1bb", "/a\x7fb", "/a\u202eb", "/a\u200bb", "/a\u2028b", "/a\u2029b", "/a--b", " ", "/", None, 5, b"/abs", ["/abs"])

    def test_an_unsafe_index_root_is_refused_and_nothing_is_printed(self):
        for bad in self.BAD:
            with self.subTest(repr(bad)), self.assertRaises(KbError) as caught:
                crawlschedule.text(bad, ENGINE)
            self.assertIn("index root", str(caught.exception))

    def test_an_unsafe_engine_folder_is_refused(self):
        for bad in self.BAD:
            with self.subTest(repr(bad)), self.assertRaises(KbError) as caught:
                crawlschedule.text(INDEX, bad)
            self.assertIn("engine folder", str(caught.exception))

    def test_a_refusal_says_why_and_never_shows_the_path(self):
        for bad in ("/secret-marker\nx", "relative-marker/x", "/secret-marker\x00x", "/secret-marker\u202ex", "/secret-marker--x"):
            for args in ((bad, ENGINE), (INDEX, bad)):
                with self.subTest(args), self.assertRaises(KbError) as caught:
                    crawlschedule.text(*args)
                self.assertNotIn("marker", str(caught.exception))
                self.assertNotIn("\n", str(caught.exception))
                self.assertTrue(str(caught.exception).strip())

    @staticmethod
    def reason(bad):
        try:
            crawlschedule.text(bad, ENGINE)
        except KbError as e:
            return str(e)
        raise AssertionError("not refused")

    def test_each_kind_of_fault_gets_its_own_plain_reason(self):
        reasons = set()
        for bad in ("relative/x", "/a\nb", "/a\u202eb", "/a--b", "", "///", 5):
            with self.assertRaises(KbError) as caught:
                crawlschedule.text(bad, ENGINE)
            reasons.add(str(caught.exception))
        self.assertEqual(len(reasons), 7)
        self.assertEqual(self.reason(" "), self.reason(""))                                      # a blank is as empty as nothing
        self.assertEqual(self.reason("/a\u2029b"), self.reason("/a\nb"))                       # a paragraph separator is a line break
        self.assertIn("empty", self.reason(" "))
        self.assertIn("control", self.reason("/a\u2029b"))

    def test_an_index_root_inside_the_engine_folder_or_holding_it_is_refused(self):
        for index, engine in ((ENGINE + "/index", ENGINE), (ENGINE, ENGINE), (ENGINE + "/", ENGINE), (INDEX, PREFIX), (INDEX, PREFIX + "/engine"), (INDEX, PREFIX + "/")):
            with self.subTest((index, engine)), self.assertRaises(KbError) as caught:
                crawlschedule.text(index, engine)
            self.assertIn("outside", str(caught.exception))

    def test_an_index_root_that_holds_the_engine_folder_is_fine_because_the_bytecode_folder_is_a_sibling_of_it(self):
        agent = parsed(crawlschedule.text("/Users/example", ENGINE))
        self.assertEqual(agent["ProgramArguments"][2], "pycache_prefix=/Users/example/crawl-pycache")
        self.assertEqual(agent["WorkingDirectory"], ENGINE)

    def test_a_folder_with_a_name_that_starts_like_the_engine_folder_is_not_inside_it(self):
        agent = parsed(crawlschedule.text(ENGINE + "-index", ENGINE))
        self.assertEqual(agent["ProgramArguments"][2], "pycache_prefix=" + ENGINE + "-index/crawl-pycache")


class ItDoesNothingButPrint(unittest.TestCase):
    def test_the_module_opens_no_file_starts_no_process_makes_no_connection_and_reads_no_environment_variable(self):
        tree = ast.parse(inspect.getsource(crawlschedule))
        imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module and n.level == 0}
        self.assertFalse(imported & {"socket", "subprocess", "urllib", "http", "ssl", "shutil", "tempfile", "pathlib", "glob", "io", "builtins", "ctypes", "requests"})
        used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for name in ("open", "environ", "getenv", "system", "popen", "Popen", "run", "call", "check_output", "listdir", "scandir", "stat", "lstat", "exists", "isdir", "isfile", "realpath", "abspath", "expanduser", "makedirs", "mkdir", "write", "write_text", "remove", "chmod"):
            self.assertNotIn(name, used)

    def test_running_it_with_every_door_shut_still_gives_the_text(self):
        def shut(*a, **k):
            raise AssertionError("the module reached outside itself")

        with mock.patch.object(builtins, "open", shut), mock.patch.object(socket, "socket", shut), mock.patch.object(socket, "create_connection", shut), \
                mock.patch.object(subprocess, "Popen", shut), mock.patch.object(os, "system", shut), mock.patch.object(os, "stat", shut), mock.patch.object(os, "lstat", shut), \
                mock.patch.object(os, "listdir", shut), mock.patch.object(os, "mkdir", shut), mock.patch.dict(os.environ, clear=True), mock.patch.object(os, "getenv", shut):
            text = crawlschedule.text(INDEX, ENGINE)
        self.assertEqual(parsed(text)["StartInterval"], 900)

    def test_it_writes_no_file_and_does_not_make_the_folders_it_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = os.path.realpath(tmp)
            index = os.path.join(tmp, "index")
            before = sorted(os.listdir(tmp))
            crawlschedule.text(index, ENGINE)
            self.assertEqual(sorted(os.listdir(tmp)), before)
            self.assertFalse(os.path.exists(index))
            self.assertFalse(os.path.exists(index + "/crawl-pycache"))
            self.assertFalse(os.path.exists(index + "/crawl-agent.log"))


class RunningThePrintedCommand(unittest.TestCase):
    """The printed program and arguments, run from the printed working folder with `--help`: `kb` is found there and not from the repository's top folder."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = os.path.realpath(self._tmp.name)
        self.index = os.path.join(self.tmp, "index")
        os.mkdir(self.index)
        self.agent = parsed(crawlschedule.text(self.index, ENGINE_DIR, sys.executable))
        self.env = {"PATH": "/usr/bin:/bin", "HOME": self.tmp, "KB_CONFIG_DIR": os.path.join(self.tmp, "cfg")}

    def run_from(self, folder):
        return subprocess.run(self.agent["ProgramArguments"] + ["--help"], cwd=folder, env=self.env, capture_output=True, text=True, timeout=60)

    def test_the_printed_working_folder_is_where_kb_can_be_imported(self):
        self.assertEqual(self.agent["WorkingDirectory"], ENGINE_DIR)
        self.assertTrue(os.path.isdir(os.path.join(self.agent["WorkingDirectory"], "kb")))
        self.assertFalse(os.path.isdir(os.path.join(REPO, "kb")))

    def test_from_the_working_folder_the_command_is_found_and_answers_help(self):
        done = self.run_from(self.agent["WorkingDirectory"])
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        self.assertIn("crawl-run", done.stdout)
        self.assertIn("--dry-run", done.stdout)

    def test_from_the_repositorys_top_folder_it_is_not_found(self):
        done = self.run_from(REPO)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("No module named kb", done.stderr)

    def test_the_bytecode_folder_it_names_is_the_one_the_runner_accepts_once_it_is_private(self):
        prefix = self.agent["ProgramArguments"][2].split("=", 1)[1]
        self.assertEqual(prefix, os.path.join(self.index, "crawl-pycache"))
        kb_root = os.path.join(ENGINE_DIR, "kb")
        self.assertIsNotNone(crawlrun.prefix_problem(prefix, kb_root))                # it does not exist yet: the owner makes it
        os.mkdir(prefix, 0o700)
        self.assertIsNone(crawlrun.prefix_problem(prefix, kb_root))
        os.chmod(prefix, 0o755)
        self.assertIsNotNone(crawlrun.prefix_problem(prefix, kb_root))

    def test_a_run_with_the_printed_prefix_is_a_run_the_bytecode_rule_accepts(self):
        prefix = self.agent["ProgramArguments"][2].split("=", 1)[1]
        os.mkdir(prefix, 0o700)
        code = "import sys; print(sys.pycache_prefix)"
        done = subprocess.run([self.agent["ProgramArguments"][0], "-X", self.agent["ProgramArguments"][2], "-c", code], cwd=ENGINE_DIR, env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(done.stdout.strip(), prefix)


class TheCommand(StoreCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(os.umask, os.umask(0o077))

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = kb_main.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def tree(self):
        return {os.path.join(d, n): (os.stat(os.path.join(d, n)).st_mtime_ns, os.stat(os.path.join(d, n)).st_size) for d, ds, fs in os.walk(self.base) for n in ds + fs}

    def test_it_prints_the_text_for_the_configs_index_root_and_the_engine_folder_and_changes_nothing(self):
        before = self.tree()
        code, out, err = self.run_main("crawl-schedule-text")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, crawlschedule.text(config.load()["index_root"], ENGINE_DIR))
        agent = parsed(out)
        self.assertEqual(agent["WorkingDirectory"], ENGINE_DIR)
        self.assertEqual(agent["ProgramArguments"][2], "pycache_prefix=" + os.path.join(self.index, "crawl-pycache"))
        self.assertEqual(self.tree(), before)
        self.assertFalse(os.path.exists(os.path.join(self.index, "crawl-pycache")))

    def test_a_python_may_be_named_by_its_full_path(self):
        code, out, err = self.run_main("crawl-schedule-text", "--python", "/usr/bin/python3")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(parsed(out)["ProgramArguments"][0], "/usr/bin/python3")

    def test_a_python_that_is_not_a_full_path_is_a_refusal_with_exit_2_and_no_text(self):
        before = self.tree()
        code, out, err = self.run_main("crawl-schedule-text", "--python", "relative/python3")
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("refused: "))
        self.assertNotIn("relative/python3", err)
        self.assertEqual(self.tree(), before)

    def test_it_takes_no_other_argument(self):
        for argv in (("crawl-schedule-text", "extra"), ("crawl-schedule-text", "--install"), ("crawl-schedule-text", "--out", "x")):
            with self.subTest(argv), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                kb_main.main(list(argv))
            self.assertEqual(raised.exception.code, 2)

    def test_a_library_that_is_not_set_up_is_a_refusal_with_no_text(self):
        os.environ["KB_CONFIG_DIR"] = os.path.join(self.base, "no-such-config")
        code, out, err = self.run_main("crawl-schedule-text")
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith(("refused: ", "failed: ")))

    def test_the_help_lists_the_command_and_says_it_only_prints(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), self.assertRaises(SystemExit):
            kb_main.main(["--help"])
        self.assertIn("crawl-schedule-text", buffer.getvalue())
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), self.assertRaises(SystemExit):
            kb_main.main(["crawl-schedule-text", "--help"])
        self.assertIn("installs nothing", " ".join(buffer.getvalue().split()))


class TheReadme(unittest.TestCase):
    NAMED = ("crawl-approve", "crawl-run", "crawl-status", "crawl-report", "crawl-clear", "crawl-schedule-text")

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(REPO, "README.md"), encoding="utf-8") as f:
            text = f.read()
        cls.whole = text
        start = text.index(SECTION)
        end = text.find("\n## ", start + 1)
        cls.section = text[start:end if end != -1 else None]

    def test_there_is_one_section_with_this_heading(self):
        self.assertEqual(self.whole.count(SECTION), 1)
        self.assertEqual(len(re.findall(r"^## .*crawl", self.whole, re.M | re.I)), 1)

    def test_every_command_the_section_names_is_a_command_of_the_engine(self):
        named = set(re.findall(r"python3 -m kb ([a-z][a-z-]*)", self.section))
        self.assertTrue(set(self.NAMED) <= named, set(self.NAMED) - named)
        for command in sorted(named):
            with self.subTest(command), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as raised:
                kb_main.main([command, "--help"])
            self.assertEqual(raised.exception.code, 0)

    def test_a_name_that_is_not_a_command_would_be_found_out(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            kb_main.main(["crawl-no-such-command", "--help"])
        self.assertNotEqual(raised.exception.code, 0)

    def test_it_names_the_steps_of_the_supervised_run_in_order(self):
        order = [self.section.index(x) for x in ("crawl-approve", "crawl-run --dry-run", "small ceiling", "crawl-status", "crawl-report", "crawl-clear", "crawl.stop", "crawl-schedule-text", "launchctl bootout")]
        self.assertEqual(order, sorted(order))
        for phrase in ("terminal", "small ceiling", "stop file", "launchctl"):
            self.assertIn(phrase, self.section)

    def test_it_names_the_stop_file_the_agent_and_the_folders_as_the_code_has_them(self):
        self.assertIn("crawl.stop", self.section)
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "crawl.stop"), "w").close()
            self.assertTrue(crawlguard.stop_requested(tmp))                           # the name the README gives is the one the runner looks for
        self.assertIn(crawlschedule.LABEL, self.section)
        self.assertIn(crawlschedule.PREFIX_NAME, self.section)
        self.assertIn(crawlschedule.OUTPUT_NAME, self.section)
        self.assertIn("mode 700", self.section)
        self.assertIn(str(crawlschedule.INTERVAL), self.section)

    def test_it_says_unattended_and_nothing_else_about_when_or_for_how_long_it_runs(self):
        low = self.section.lower()
        self.assertIn("unattended", low)
        for word in ("night", "away", "vacation", "holiday", "weekend", "overnight", "sleep", "asleep"):
            self.assertNotIn(word, low)

    def test_it_installs_nothing_itself_and_says_the_owner_does(self):
        self.assertIn("installs nothing", " ".join(self.section.split()))
        self.assertNotIn("sudo", self.section)
        self.assertNotIn("pip install", self.section)


if __name__ == "__main__":
    unittest.main()
