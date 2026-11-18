"""The crawl plan file and its reader (`kb/crawlplan.py`, Increment A of the plan `2026-11-16-build-the-safeguards-of-the-unattended-crawl`).

The plan is the owner's one plain-text file (`docs/specs/population.md`, "The crawl plan"): `[section]` lines and `key = value` lines, a `#` starting a comment, every key with a default. The reader is strict: an unknown
section or key, a value of the wrong kind or out of range, a key in the wrong section and a key given twice are refused with the line number, and never the text of the line. It agrees with discovery's own reader on every key
that discovery reads. No test reads the owner's plan or config.
Run them with `python3 -W error::ResourceWarning -m unittest engine.tests.test_crawlplan`."""
import datetime
import os
import re
import tempfile
import time
import unittest
from unittest import mock

from engine.tests import ENGINE_DIR  # noqa: F401  (puts the engine folder on the import path)

from kb import KbError, crawlplan, discover, scan_tool, weblists

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "crawl", "plan-discovery-only.txt")
SPEC = os.path.join(os.path.dirname(os.path.dirname(HERE)), "docs", "specs", "population.md")
CANARY = "CANARY-text-from-a-plan-line-7c1d"


def spec_example():
    """The example plan in the spec, as the spec writes it."""
    with open(SPEC, encoding="utf-8") as f:
        text = f.read()
    start = text.index("### The crawl plan")
    block = re.search(r"```\n(\[limits\].*?)\n```", text[start:], re.S)
    return block.group(1) + "\n"


class Files(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = os.path.realpath(self._tmp.name)

    def write(self, text, name="plan.txt", mode=0o600):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.chmod(path, mode)
        return path

    def read(self, text):
        return crawlplan.read_plan(self.write(text))

    def refused(self, text, *words):
        with self.assertRaises(KbError) as caught:
            self.read(text)
        message = str(caught.exception)
        for word in words:
            self.assertIn(word, message)
        self.assertNotIn(CANARY, message)
        return message


class Defaults(Files):
    def test_an_empty_file_is_a_plan_with_every_default_of_the_spec(self):
        plan = self.read("")
        home = os.path.expanduser("~/.config/knowledge-base/")
        expected = {
            "fetches_per_day": 20, "filed_total": 200, "per_domain_per_day": 3, "batch": 8, "cards_per_day": 30, "queue_low": 100, "discover_target": 200, "queries_per_topic": 3,
            "queued_total": 20000, "queued_per_domain": 50, "retries": 3, "fetch_timeout_s": 60, "timezone": "local",
            "min_gap_s": 8, "jitter": 0.5, "user_agent": "browser",
            "bulk_floor_gb": 50, "index_floor_gb": 10,
            "consecutive_failures": 8, "failure_share": 0.5, "window": 20, "model_down_minutes": 30, "domain_refusals": 3,
            "openalex": True, "openalex_key": False, "arxiv": True, "wikipedia": True, "web_search": False, "wander_share": 0.2, "wander_depth": 2, "wander_per_work": 5,
            "gap_openalex_s": 1, "gap_arxiv_s": 3, "gap_wikipedia_s": 1, "gap_web_search_s": 30, "web_search_per_day": 20,
            "phishing_domains": True, "urlhaus_recent": False, "phishing_domains_format": "domains", "refresh_hours": 12, "list_max_mb": 50, "list_min_share": 0.5, "list_max_change": 0.3,
            "urlhaus_keep_days": 30, "pinned_hosts": ["openalex.org", "arxiv.org", "wikipedia.org"],
            "threshold": None, "min_chars": 400, "model_pick": True, "pdf_max_mb": 0, "tool_rss_mb": 2048,
            "topics": home + "crawl-topics.txt", "blacklist": home + "crawl-blacklist.txt", "allow": home + "crawl-allow.txt",
        }
        for key, value in expected.items():
            self.assertEqual(plan[key], value, key)
        self.assertEqual(plan["phishing_domains_url"], "https://raw.githubusercontent.com/Phishing-Database/Phishing.Database/master/phishing-domains-ACTIVE.txt")
        self.assertEqual(plan["public_suffix_url"], "https://publicsuffix.org/list/public_suffix_list.dat")
        self.assertEqual(set(plan), set(expected) | {"phishing_domains_url", "public_suffix_url", "hold_kinds"})

    def test_the_shipped_default_has_the_sources_with_unresolved_terms_off_and_no_threshold(self):
        plan = self.read("")
        self.assertFalse(plan["web_search"])
        self.assertFalse(plan["openalex_key"])
        self.assertFalse(plan["urlhaus_recent"])
        self.assertIsNone(plan["threshold"])

    def test_the_default_scan_kinds_that_hold_are_the_hostile_ones_and_never_the_three_that_every_page_has(self):
        plan = self.read("")
        self.assertEqual(set(plan["hold_kinds"]), {"encrypted", "javascript", "launch_action", "embedded_files", "xfa_forms", "external_actions", "rich_media", "scan_incomplete", "malformed", "meta_refresh",
                                                    "embedded_content"})
        self.assertTrue(set(plan["hold_kinds"]) <= set(scan_tool.KINDS))
        for never in ("script_elements", "event_handlers", "pattern_in_binary_data"):
            self.assertNotIn(never, plan["hold_kinds"])

    def test_the_example_in_the_spec_is_a_valid_plan_and_equals_the_defaults(self):
        self.assertEqual(self.read(spec_example()), self.read(""))

    def test_two_reads_give_separate_dictionaries(self):
        first = self.read("")
        first["pinned_hosts"].append("evil.example")
        first["hold_kinds"].append("evil")
        first["batch"] = 999
        second = self.read("")
        self.assertEqual(second["pinned_hosts"], ["openalex.org", "arxiv.org", "wikipedia.org"])
        self.assertNotIn("evil", second["hold_kinds"])
        self.assertEqual(second["batch"], 8)


class Values(Files):
    def test_values_are_read_in_their_kinds(self):
        plan = self.read("""
[limits]
fetches_per_day = 5        # a comment
batch=2
timezone = Europe/London
[pacing]
min_gap_s = 2.5
jitter = 1
user_agent = generic
[disk]
bulk_floor_gb = 100.5
[breaker]
failure_share = 1
[sources]
web_search = duckduckgo
openalex = off
[lists]
phishing_domains = off
urlhaus_recent = on
refresh_hours = 6
pinned_hosts = Arxiv.org., openalex.org,  wikipedia.org
[scan]
hold_kinds = encrypted, javascript
[judge]
threshold = 0.42
min_chars = 500
[moves]
model_pick = off
[files]
topics = ~/somewhere/topics.txt
""")
        self.assertEqual((plan["fetches_per_day"], plan["batch"], plan["timezone"]), (5, 2, "Europe/London"))
        self.assertEqual((plan["min_gap_s"], plan["jitter"], plan["user_agent"], plan["bulk_floor_gb"], plan["failure_share"]), (2.5, 1, "generic", 100.5, 1))
        self.assertEqual((plan["web_search"], plan["openalex"], plan["phishing_domains"], plan["urlhaus_recent"], plan["refresh_hours"]), (True, False, False, True, 6))
        self.assertEqual(plan["pinned_hosts"], ["arxiv.org", "openalex.org", "wikipedia.org"])
        self.assertEqual(plan["hold_kinds"], ["encrypted", "javascript"])
        self.assertEqual((plan["threshold"], plan["min_chars"], plan["model_pick"]), (0.42, 500, False))
        self.assertEqual(plan["topics"], os.path.expanduser("~/somewhere/topics.txt"))
        self.assertEqual(plan["blacklist"], os.path.expanduser("~/.config/knowledge-base/crawl-blacklist.txt"))

    def test_a_path_is_expanded_for_the_home_folder_and_not_otherwise_changed(self):
        plan = self.read("[files]\ntopics = /abs/../odd//path/topics.txt\nblacklist = relative/black.txt\nallow = ~other/allow.txt\n")
        self.assertEqual(plan["topics"], "/abs/../odd//path/topics.txt")
        self.assertEqual(plan["blacklist"], "relative/black.txt")
        self.assertEqual(plan["allow"], os.path.expanduser("~other/allow.txt"))

    def test_pdfs_are_off_by_default_and_the_two_keys_are_whole_numbers_in_range(self):
        plan = self.read("")
        self.assertEqual((plan["pdf_max_mb"], plan["tool_rss_mb"]), (0, 2048))
        self.assertEqual(self.read("[pdf]\npdf_max_mb = 20\ntool_rss_mb = 1024\n")["pdf_max_mb"], 20)
        self.assertEqual(self.read("[pdf]\npdf_max_mb = 0\n")["pdf_max_mb"], 0)
        self.assertEqual(self.read("[pdf]\ntool_rss_mb = 64\n")["tool_rss_mb"], 64)
        self.assertEqual(self.read("[pdf]\npdf_max_mb = 200\n")["pdf_max_mb"], 200)                  # the ends of both ranges are in
        self.assertEqual(self.read("[pdf]\ntool_rss_mb = 100000\n")["tool_rss_mb"], 100000)
        for key, bad in (("pdf_max_mb", "-1"), ("pdf_max_mb", "201"), ("pdf_max_mb", "1000"), ("pdf_max_mb", "2.5"), ("pdf_max_mb", "abc"), ("pdf_max_mb", ""), ("tool_rss_mb", "63"), ("tool_rss_mb", "0"),
                         ("tool_rss_mb", "100001"), ("tool_rss_mb", "1.5"), ("tool_rss_mb", "x")):
            with self.subTest(f"{key}={bad}"):
                self.refused(f"[pdf]\n{key} = {bad}\n", "line 2")

    def test_the_two_pdf_keys_belong_to_their_own_section_and_nowhere_else(self):
        for text in ("[limits]\npdf_max_mb = 5\n", "[files]\ntool_rss_mb = 128\n"):
            with self.subTest(text):
                self.refused(text, "line 2")

    def test_the_threshold_is_empty_by_default_and_read_as_a_number_in_range(self):
        self.assertIsNone(self.read("[judge]\nthreshold =\n")["threshold"])
        self.assertIsNone(self.read("[judge]\nthreshold =   # nothing yet\n")["threshold"])
        for good, value in (("0", 0), ("0.5", 0.5), ("-0.25", -0.25), ("1", 1), ("-1", -1)):
            self.assertEqual(self.read(f"[judge]\nthreshold = {good}\n")["threshold"], value)
        for bad in ("abc", "nan", "inf", "1.01", "-1.01", "1e3", "0x1", "0.5.5", "--1", "+0.5 0"):
            with self.subTest(bad):
                self.refused(f"[judge]\nthreshold = {bad}\n", "line 2")

    def test_an_empty_hold_list_means_the_default_and_a_list_may_be_all_the_kinds_the_scan_knows_but_never_the_three_that_do_not_hold(self):
        default = self.read("")["hold_kinds"]
        self.assertEqual(self.read("[scan]\nhold_kinds =\n")["hold_kinds"], default)
        every = [k for k in scan_tool.KINDS if k not in ("script_elements", "event_handlers", "pattern_in_binary_data")]
        self.assertEqual(self.read("[scan]\nhold_kinds = " + ", ".join(every) + "\n")["hold_kinds"], every)
        for bad in ("script_elements", "event_handlers", "pattern_in_binary_data", "encrypted, nonsense", "encrypted,,javascript", ",", "encrypted encrypted", "Encrypted", "encrypted, encrypted"):
            with self.subTest(bad):
                self.refused(f"[scan]\nhold_kinds = {bad}\n", "line 2")

    def test_the_switches_take_on_and_off_in_any_case_and_web_search_also_duckduckgo(self):
        for text, value in (("on", True), ("ON", True), ("Off", False), ("off", False)):
            self.assertEqual(self.read(f"[sources]\narxiv = {text}\n")["arxiv"], value)
        self.assertTrue(self.read("[sources]\nweb_search = DuckDuckGo\n")["web_search"])
        for bad in ("yes", "true", "1", "maybe", "", "on off"):
            with self.subTest(bad):
                self.refused(f"[sources]\narxiv = {bad}\n", "line 2")
        self.refused("[sources]\nopenalex = duckduckgo\n", "line 2")

    def test_the_openalex_key_is_a_switch_that_is_off_unless_the_plan_says_on(self):
        self.assertFalse(self.read("")["openalex_key"])
        for text, value in (("on", True), ("ON", True), ("Off", False), ("off", False)):
            self.assertEqual(self.read(f"[sources]\nopenalex_key = {text}\n")["openalex_key"], value)
        for bad in ("yes", "true", "1", "", "duckduckgo", "openalex.key", "on off"):
            with self.subTest(bad):
                self.refused(f"[sources]\nopenalex_key = {bad}\n", "line 2")
        self.refused("[limits]\nopenalex_key = on\n", "line 2")  # a key of the plan in another section than its own is refused

    def test_whole_numbers_and_numbers_are_checked_for_kind_and_range(self):
        cases = [("limits", "fetches_per_day", ["abc", "1.5", "-1", "0", "1e3", "10000000000", "10001", "", "0x10", "1_0"]), ("limits", "retries", ["0", "21", "x"]),
                 ("limits", "fetch_timeout_s", ["0", "3601"]), ("pacing", "min_gap_s", ["-1", "3601", "x"]), ("pacing", "jitter", ["-0.1", "3601"]), ("disk", "bulk_floor_gb", ["-1", "x", "1e9"]),
                 ("breaker", "failure_share", ["0", "1.01", "-0.5", "x"]), ("breaker", "window", ["0", "1001"]), ("breaker", "model_down_minutes", ["0", "10081"]),
                 ("breaker", "domain_refusals", ["0", "101"]), ("limits", "queued_total", ["0", "1000001"]), ("sources", "wander_share", ["1.5", "-0.1"]), ("judge", "min_chars", ["0", "x", "100001"]),
                 ("lists", "refresh_hours", ["0", "0.5", "8761", "x"]), ("lists", "list_max_mb", ["0", "251"]), ("lists", "urlhaus_keep_days", ["0", "3651"])]
        for section, key, bad_values in cases:
            for bad in bad_values:
                with self.subTest(key=key, bad=bad):
                    self.refused(f"[{section}]\n{key} = {bad}\n", "line 2")

    def test_the_timezone_is_local_or_a_name_the_system_knows(self):
        self.assertEqual(self.read("[limits]\ntimezone = local\n")["timezone"], "local")
        self.assertEqual(self.read("[limits]\ntimezone = America/New_York\n")["timezone"], "America/New_York")
        self.assertEqual(self.read("[limits]\ntimezone = UTC\n")["timezone"], "UTC")
        for bad in ("Mars/Base", "../x", "/etc/localtime", "America/", "LOCAL", "utc ", "a" * 80):
            with self.subTest(bad):
                self.refused(f"[limits]\ntimezone = {bad}\n", "line 2")

    def test_the_user_agent_is_browser_or_generic(self):
        for bad in ("Mozilla/5.0", "honest", ""):
            with self.subTest(bad):
                self.refused(f"[pacing]\nuser_agent = {bad}\n", "line 2")

    def test_the_list_settings_are_those_the_lists_module_takes_and_nothing_wider(self):
        for text in ("phishing_domains_url = http://x.example/list", "phishing_domains_url = ftp://x.example/list", "public_suffix_url =", "pinned_hosts = com", "pinned_hosts = bad host",
                     "pinned_hosts =", "phishing_domains_format = xml", "list_min_share = 1.5", "list_max_change = -0.1", "phishing_domains = maybe"):
            with self.subTest(text):
                self.refused(f"[lists]\n{text}\n", "line 2")

    def test_a_site_named_twice_in_the_pinned_list_is_kept_once_in_its_first_place(self):
        self.assertEqual(self.read("[lists]\npinned_hosts = openalex.org, ARXIV.org, arxiv.org., openalex.org\n")["pinned_hosts"], ["openalex.org", "arxiv.org"])

    def test_the_list_switches_take_only_on_and_off(self):
        for key in ("phishing_domains", "urlhaus_recent"):
            for bad in ("yes", "true", "1", "duckduckgo"):
                with self.subTest(key=key, bad=bad):
                    self.refused(f"[lists]\n{key} = {bad}\n", "line 2")

    def test_the_settings_handed_on_are_copies(self):
        plan = self.read("")
        lists = crawlplan.lists_plan(plan)
        lists["pinned_hosts"].append("evil.example")
        self.assertEqual(plan["pinned_hosts"], ["openalex.org", "arxiv.org", "wikipedia.org"])
        self.assertEqual(crawlplan.discovery_plan(plan), {key: plan[key] for key in discover.PLAN})

    def test_the_lists_settings_and_the_discovery_settings_can_be_handed_on_as_those_modules_take_them(self):
        plan = self.read(spec_example())
        lists = crawlplan.lists_plan(plan)
        self.assertEqual(set(lists), set(weblists.DEFAULTS))
        self.assertEqual(weblists.check_plan(lists)["refresh_hours"], 12)
        disc = crawlplan.discovery_plan(plan)
        self.assertEqual(set(disc), set(discover.PLAN))
        self.assertEqual(discover.normalize_plan(disc), discover.normalize_plan({}))


class Agreement(Files):
    def test_discoverys_own_reader_and_this_one_agree_on_every_key_both_read(self):
        for path in (FIXTURE, self.write(spec_example(), "spec.txt"),
                     self.write("[limits]\nqueue_low = 7\ndiscover_target = 9\nqueries_per_topic = 5\nqueued_total = 99\nqueued_per_domain = 4\n[sources]\nopenalex = off\nweb_search = duckduckgo\nwander_share = 0.5\n"
                                "gap_arxiv_s = 4\nweb_search_per_day = 3\n", "mixed.txt")):
            theirs = discover.read_plan(path)
            ours = crawlplan.read_plan(path)
            self.assertTrue(theirs)
            for key, value in theirs.items():
                self.assertEqual(ours[key], value, (path, key))
                self.assertIs(type(ours[key]), type(value), (path, key))

    def test_the_owners_discovery_file_is_a_valid_plan_with_the_defaults_for_the_runners_keys(self):
        plan = crawlplan.read_plan(FIXTURE)
        self.assertEqual(plan["batch"], 8)
        self.assertFalse(plan["web_search"])
        self.assertEqual(plan["queue_low"], 100)

    def test_a_value_that_discovery_refuses_this_reader_refuses_too(self):
        for text in ("[limits]\nqueue_low = -1\n", "[limits]\ndiscover_target = 2001\n", "[sources]\nwander_share = 2\n", "[sources]\ngap_arxiv_s = 3601\n", "[sources]\nopenalex = maybe\n",
                     "[limits]\nqueued_total = x\n", "[sources]\nweb_search_per_day = 1001\n"):
            path = self.write(text, "bad.txt")
            with self.assertRaises(KbError):
                discover.normalize_plan(discover.read_plan(path))      # discovery reads the grammar, and checks the range when it normalises
            with self.assertRaises(KbError):
                crawlplan.read_plan(path)


class Shape(Files):
    def test_a_section_that_is_not_one_of_the_plans_is_refused_alone_or_with_keys(self):
        self.refused("[bogus]\n", "line 1")
        self.refused("[bogus]\nbatch = 1\n", "line 1")
        self.refused("[limits]\nbatch = 1\n[files_extra]\n", "line 3")

    def test_an_unknown_section_or_key_is_refused_and_the_message_does_not_quote_it(self):
        for text in (f"[{CANARY.lower().replace('-', '_')}]\n", "[limits]\nunknown_key = 1\n", f"[limits]\n{CANARY.lower().replace('-', '_')} = 1\n", "[Limits]\nbatch = 1\n", "[]\n", "[limits\nbatch = 1\n"):
            with self.subTest(text[:30]):
                message = self.refused(text, "line")
                self.assertNotIn("unknown_key", message)

    def test_a_key_in_the_wrong_section_is_refused_and_says_which_section_it_belongs_to(self):
        message = self.refused("[sources]\nbatch = 5\n", "line 2", "[limits]")
        self.assertNotIn("batch", message)
        self.refused("[limits]\nopenalex = on\n", "line 2", "[sources]")
        self.refused("[files]\nthreshold = 1\n", "line 2", "[judge]")

    def test_a_key_given_twice_in_a_section_is_refused(self):
        self.refused("[limits]\nbatch = 2\nbatch = 3\n", "line 3")
        self.refused("[limits]\nbatch = 2\n[limits]\nbatch = 3\n", "line 4")

    def test_a_section_may_be_written_twice_if_no_key_is_repeated(self):
        plan = self.read("[limits]\nbatch = 2\n[sources]\narxiv = off\n[limits]\nretries = 5\n")
        self.assertEqual((plan["batch"], plan["retries"], plan["arxiv"]), (2, 5, False))

    def test_a_line_that_is_neither_a_section_nor_a_key_or_comes_before_any_section_is_refused(self):
        for text in ("just some text\n", "batch = 5\n", "[limits]\n= 5\n", "[limits]\nbatch 5\n", "[limits]\nbatch == 5\n", "[limits] # trailing\n x\n", f"[limits]\n{CANARY}\n", "[limits]\n  = \n"):
            with self.subTest(text[:30]):
                self.refused(text, "line")

    def test_comments_blank_lines_a_byte_order_mark_and_other_line_ends_are_taken(self):
        plan = self.read("﻿# first\r\n\r\n[limits]  # the section\r\nbatch = 2 # two\r\n\r\n  retries = 4\r\n")
        self.assertEqual((plan["batch"], plan["retries"]), (2, 4))
        self.assertEqual(self.read("[limits]\rbatch = 3\r")["batch"], 3)

    def test_a_refusal_names_the_line_and_never_quotes_it(self):
        message = self.refused(f"# a comment\n\n[limits]\nbatch = {CANARY}\n", "line 4")
        self.assertNotIn("batch", message)
        message = self.refused(f"[limits]\n{CANARY} = 1\n", "line 2")
        self.assertNotIn(CANARY, message)
        message = self.refused(f"[files]\ntopics = {CANARY}\nblacklist =\n", "line 3")
        self.assertNotIn(CANARY, message)

    def test_a_value_may_not_be_empty_except_for_the_threshold_and_the_hold_list(self):
        for key, section in (("batch", "limits"), ("topics", "files"), ("timezone", "limits"), ("phishing_domains_format", "lists"), ("min_chars", "judge")):
            with self.subTest(key):
                self.refused(f"[{section}]\n{key} =\n", "line 2")

    def test_a_value_may_hold_a_hash_inside_a_path_only_as_a_comment_start(self):
        self.assertEqual(self.read("[files]\ntopics = /a/b # c\n")["topics"], "/a/b")


class FileProblems(Files):
    def test_a_missing_file_a_folder_a_link_a_pipe_and_a_path_that_is_not_a_path_are_refused(self):
        with self.assertRaises(KbError):
            crawlplan.read_plan(os.path.join(self.dir, "missing.txt"))
        os.mkdir(os.path.join(self.dir, "folder"))
        with self.assertRaises(KbError):
            crawlplan.read_plan(os.path.join(self.dir, "folder"))
        real = self.write("[limits]\nbatch = 2\n", "real.txt")
        os.symlink(real, os.path.join(self.dir, "link.txt"))
        with self.assertRaises(KbError):
            crawlplan.read_plan(os.path.join(self.dir, "link.txt"))
        os.mkfifo(os.path.join(self.dir, "pipe.txt"))
        with self.assertRaises(KbError):
            crawlplan.read_plan(os.path.join(self.dir, "pipe.txt"))
        for bad in (None, 5, "", b"x", "a\x00b"):
            with self.subTest(repr(bad)):
                with self.assertRaises(KbError):
                    crawlplan.read_plan(bad)

    def test_a_file_over_64_kib_or_not_utf8_or_with_a_nul_is_refused(self):
        with self.assertRaises(KbError):
            crawlplan.read_plan(self.write("# " + "x" * 70000 + "\n", "big.txt"))
        edge = "# " + "x" * (65536 - 3) + "\n"
        self.assertEqual(len(edge.encode()), 65536)
        crawlplan.read_plan(self.write(edge, "edge.txt"))
        with self.assertRaises(KbError):
            crawlplan.read_plan(self.write(edge + "#", "over.txt"))
        path = os.path.join(self.dir, "latin.txt")
        with open(path, "wb") as f:
            f.write(b"[limits]\nbatch = 2 # caf\xe9\n")
        with self.assertRaises(KbError):
            crawlplan.read_plan(path)
        with self.assertRaises(KbError):
            crawlplan.read_plan(self.write("[limits]\nbatch = 2\x00\n", "nul.txt"))

    def test_the_reader_makes_no_network_request_and_reads_nothing_but_the_one_file(self):
        with open(os.path.join(ENGINE_DIR, "kb", "crawlplan.py"), encoding="utf-8") as f:
            source = f.read()
        for word in ("socket", "urllib.request", "http.client", "subprocess", "webclient", "os.environ", "config.load"):
            self.assertNotIn(word, source, word)


class Days(unittest.TestCase):
    def test_the_day_of_a_time_is_a_day_in_the_plans_zone(self):
        t = datetime.datetime(2026, 11, 16, 3, 30, tzinfo=datetime.timezone.utc)
        self.assertEqual(crawlplan.day_of(t, "UTC"), "2026-11-16")
        self.assertEqual(crawlplan.day_of(t, "America/New_York"), "2026-11-15")      # 22:30 the evening before
        self.assertEqual(crawlplan.day_of(t, "Asia/Tokyo"), "2026-11-16")
        self.assertEqual(crawlplan.day_of(t.replace(hour=15), "Asia/Tokyo"), "2026-11-17")

    def test_a_day_at_a_change_of_clock_has_no_repeat_and_no_gap(self):
        zone = "America/New_York"
        before = datetime.datetime(2026, 3, 8, 6, 59, tzinfo=datetime.timezone.utc)      # 01:59 EST, a minute before the clocks go forward
        after = datetime.datetime(2026, 3, 8, 7, 1, tzinfo=datetime.timezone.utc)        # 03:01 EDT
        self.assertEqual((crawlplan.day_of(before, zone), crawlplan.day_of(after, zone)), ("2026-03-08", "2026-03-08"))
        late = datetime.datetime(2026, 3, 9, 3, 59, tzinfo=datetime.timezone.utc)        # 23:59 EDT the same evening
        later = datetime.datetime(2026, 3, 9, 4, 1, tzinfo=datetime.timezone.utc)        # 00:01 EDT the next day
        self.assertEqual((crawlplan.day_of(late, zone), crawlplan.day_of(later, zone)), ("2026-03-08", "2026-03-09"))
        fall_a = datetime.datetime(2026, 11, 1, 5, 30, tzinfo=datetime.timezone.utc)     # 01:30 EDT, the first of two 01:30
        fall_b = datetime.datetime(2026, 11, 1, 6, 30, tzinfo=datetime.timezone.utc)     # 01:30 EST, the second
        self.assertEqual((crawlplan.day_of(fall_a, zone), crawlplan.day_of(fall_b, zone)), ("2026-11-01", "2026-11-01"))

    def test_local_is_the_zone_of_the_machine(self):
        t = datetime.datetime(2026, 11, 16, 3, 30, tzinfo=datetime.timezone.utc)
        saved = os.environ.get("TZ")
        self.addCleanup(lambda: (os.environ.pop("TZ", None) if saved is None else os.environ.__setitem__("TZ", saved), time.tzset()))
        os.environ["TZ"] = "America/Los_Angeles"
        time.tzset()
        self.assertEqual(crawlplan.day_of(t, "local"), "2026-11-15")
        os.environ["TZ"] = "Asia/Tokyo"
        time.tzset()
        self.assertEqual(crawlplan.day_of(t, "local"), "2026-11-16")

    def test_a_time_without_a_zone_or_a_zone_that_is_not_known_is_refused(self):
        with self.assertRaises(KbError):
            crawlplan.day_of(datetime.datetime(2026, 11, 16), "UTC")
        with self.assertRaises(KbError):
            crawlplan.day_of("2026-11-16", "UTC")
        with self.assertRaises(KbError):
            crawlplan.day_of(datetime.datetime(2026, 11, 16, tzinfo=datetime.timezone.utc), "Mars/Base")


if __name__ == "__main__":
    unittest.main()
