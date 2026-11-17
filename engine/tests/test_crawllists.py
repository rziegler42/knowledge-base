"""The `lists` point of a crawl run (`kb/crawllists.py`, Increment D of the plan `2026-11-16-run-the-steps-of-the-unattended-crawl`).

The step refreshes the public lists that are due, feeds the URLhaus recent URLs to the matcher when the plan turns that on and the owner's key allows it, logs each list's result, and leaves the matcher and the
public suffix list for the steps that come after. The rules of the lists themselves (their size limits, their formats, the matching of a host) are `weblists`' and `urlhaus`' and are tested there; these tests show
that the step uses them as the plan and the spec say, with a fake downloader, a fake key file and a temporary index root. No request is made and no real key is read.
Run them with `python3 -W error::ResourceWarning -m unittest engine.tests.test_crawllists`."""
import datetime
import fcntl
import json
import os
import stat
import tempfile
import types
import unittest
from unittest import mock

from engine.tests import ENGINE_DIR

from kb import KbError, crawlguard, crawllists, crawllog, crawlplan, crawlrun, urlhaus, webclient, weblists

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 16, 12, 0, 0, tzinfo=UTC)
KEY = "k3y-0123456789abcdef-SECRET"
PHISH_URL = weblists.DEFAULTS["phishing_domains_url"]
PSL_URL = weblists.DEFAULTS["public_suffix_url"]
PSL_BODY = b"// a list\ncom\norg\nco.uk\n*.ck\n"


def hosts(*names):
    return ("\n".join(names) + "\n").encode()


class Fetch:
    """A fake `webclient.get`: it records each call, runs the policy's address hook as the real client does, and answers from a table (`replies`: a url to `(status, headers, body)`, an exception, or a function of the call number)."""

    def __init__(self):
        self.calls, self.replies = [], {}

    def __call__(self, url, *, policy, headers=None, max_bytes=None, timeout=None, total_timeout=None):
        verdict = policy.check(url) if policy.check is not None else None
        self.calls.append(types.SimpleNamespace(url=url, policy=policy, headers=dict(headers or {}), max_bytes=max_bytes, verdict=verdict))
        if verdict:
            raise webclient.Refused("refused: " + str(getattr(verdict, "reason", verdict)))
        reply = self.replies.get(url)
        if callable(reply):
            reply = reply(len(self.calls))
        if isinstance(reply, Exception):
            raise reply
        if reply is None:
            raise webclient.FetchError("no reply was made up for this address")
        status, reply_headers, body = reply
        return webclient.Result(status, reply_headers, body, url)

    def urls(self):
        return [c.url for c in self.calls]


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = os.path.realpath(self._tmp.name)
        self.addCleanup(self._unlock)
        self.index = os.path.join(self.dir, "index")
        os.makedirs(os.path.join(self.index, "crawl"), mode=0o700)
        self.files = os.path.join(self.dir, "files")
        os.mkdir(self.files)
        self.black = self.put("black.txt", "evil.example\n")
        self.allow = self.put("allow.txt", "")
        self.key_path = os.path.join(self.dir, "urlhaus.key")
        floors = mock.patch.dict(weblists.MIN_ENTRIES, {"phishing_domains": 1, "public_suffix": 1})
        floors.start()
        self.addCleanup(floors.stop)
        self.plan = crawlplan.defaults()
        self.plan.update(blacklist=self.black, allow=self.allow, min_gap_s=0, jitter=0)
        self.fetch = Fetch()
        self.fetch.replies[PHISH_URL] = (200, {}, hosts("bad1.example", "bad2.example", "bad3.example", "bad4.example"))
        self.fetch.replies[PSL_URL] = (200, {}, PSL_BODY)
        self.now = NOW
        self.log = crawllog.Log(self.index, "run-1", clock=lambda: self.now)

    def _unlock(self):
        for folder, _names, _files in os.walk(self.dir):
            os.chmod(folder, 0o700)

    def put(self, name, text):
        path = os.path.join(self.files, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(path, 0o600)
        return path

    def ctx(self, plan=None):
        return types.SimpleNamespace(index_root=self.index, plan=plan or self.plan, log=self.log, clock=lambda: self.now, secrets=(), run="run-1", matcher=None, suffixes=None, lists_report=None)

    def step(self, ctx=None, fetch=None):
        ctx = ctx or self.ctx()
        crawllists.make_step(fetch=fetch or self.fetch, key_path=self.key_path)(ctx)
        return ctx

    def lines(self):
        folder = os.path.join(self.index, "crawl", "log")
        out = []
        if os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                with open(os.path.join(folder, name), encoding="utf-8") as f:
                    out += [json.loads(line) for line in f.read().splitlines()]
        return out

    def key(self, mode=0o600, text=KEY):
        with open(self.key_path, "w") as f:
            f.write(text + "\n")
        os.chmod(self.key_path, mode)

    def urlhaus_on(self):
        self.plan["urlhaus_recent"] = True

    def tree_text(self):
        text = ""
        for folder, _names, files in os.walk(self.dir):
            for name in files:
                try:
                    with open(os.path.join(folder, name), "rb") as f:
                        text += f.read().decode("utf-8", "replace")
                except OSError:
                    pass
        return text


class Refresh(Case):
    def test_the_first_run_downloads_the_required_list_and_the_public_suffix_list_and_gives_the_matcher_to_the_steps_after(self):
        ctx = self.step()
        self.assertEqual(sorted(self.fetch.urls()), sorted([PHISH_URL, PSL_URL]))
        self.assertIsNotNone(ctx.matcher.blocked("bad1.example"))
        self.assertIsNone(ctx.matcher.blocked("good.example"))
        self.assertIn("co.uk", ctx.suffixes)
        self.assertEqual(ctx.lists_report["lists"]["phishing_domains"]["status"], "updated")
        self.assertEqual(ctx.lists_report["lists"]["public_suffix"]["status"], "updated")

    def test_nothing_is_requested_when_the_lists_are_fresh_and_the_log_says_so(self):
        self.step()
        self.fetch.calls.clear()
        self.now = NOW + datetime.timedelta(hours=self.plan["refresh_hours"] - 1)
        ctx = self.step()
        self.assertEqual(self.fetch.calls, [])
        self.assertIsNotNone(ctx.matcher.blocked("bad1.example"))                       # the stored copy is in use
        lines = [l for l in self.lines() if l["step"] == "list_update"]
        self.assertEqual({(l["outcome"]) for l in lines[-3:]}, {"skipped"})
        self.now = NOW + datetime.timedelta(hours=self.plan["refresh_hours"] + 1)       # and it is asked again when it is due
        self.step()
        self.assertEqual(sorted(self.fetch.urls()), sorted([PHISH_URL, PSL_URL]))

    def test_each_list_has_a_list_update_line_with_its_name_its_outcome_and_no_list_text(self):
        self.step()
        lines = [l for l in self.lines() if l["step"] == "list_update"]
        by = {l["reason"].split(":")[0]: l for l in lines}
        self.assertEqual(set(by), {"phishing_domains", "public_suffix", "urlhaus_recent"})
        self.assertEqual((by["phishing_domains"]["outcome"], by["public_suffix"]["outcome"], by["urlhaus_recent"]["outcome"]), ("ok", "ok", "skipped"))
        self.assertNotIn("bad1.example", json.dumps(lines))
        for line in lines:
            self.assertEqual(line["run"], "run-1")

    def test_the_number_of_entries_is_logged_and_the_first_matcher_has_no_problem_with_its_folder(self):
        ctx = self.step()
        line = [l for l in self.lines() if l["step"] == "list_update" and l["reason"].startswith("phishing_domains")][0]
        self.assertEqual(line["n"], 4)
        self.assertEqual(ctx.matcher.problems, [])

    def test_a_list_that_comes_back_not_modified_is_skipped_and_the_validators_and_the_size_limit_are_sent(self):
        self.fetch.replies[PHISH_URL] = (200, {"etag": '"v1"'}, hosts("bad1.example", "bad2.example"))
        self.step()
        self.now += datetime.timedelta(hours=13)
        self.fetch.calls.clear()
        self.fetch.replies[PHISH_URL] = (304, {}, b"")
        ctx = self.step()
        call = [c for c in self.fetch.calls if c.url == PHISH_URL][0]
        self.assertEqual(call.headers.get("If-None-Match"), '"v1"')
        self.assertEqual(call.max_bytes, int(self.plan["list_max_mb"] * 1024 * 1024))
        self.assertEqual(ctx.lists_report["lists"]["phishing_domains"]["status"], "unchanged")
        line = [l for l in self.lines() if l["step"] == "list_update" and l["reason"].startswith("phishing_domains")][-1]
        self.assertEqual(line["outcome"], "skipped")

    def test_a_reason_that_looks_like_a_credential_is_withheld_in_the_log_and_does_not_stop_the_step(self):
        self.step()
        self.now += datetime.timedelta(hours=13)
        self.fetch.replies[PHISH_URL] = webclient.FetchError("Authorization: Bearer abcdefgh12345 was not accepted")
        ctx = self.step()
        self.assertEqual(ctx.lists_report["lists"]["phishing_domains"]["status"], "failed")
        line = [l for l in self.lines() if l["step"] == "list_update" and l["outcome"] == "failed"][0]
        self.assertEqual(line["reason"], crawllog.WITHHELD)
        self.assertNotIn("abcdefgh12345", json.dumps(self.lines()))

    def test_a_stored_copy_that_does_not_match_its_record_is_logged_and_the_list_is_asked_for_again(self):
        self.step()
        folder = os.path.join(self.index, "crawl", "lists")
        stored = [n for n in os.listdir(folder) if n.startswith("phishing_domains.") and n.endswith(".txt")]
        self.assertEqual(len(stored), 1)
        os.chmod(os.path.join(folder, stored[0]), 0o600)
        with open(os.path.join(folder, stored[0]), "a") as f:
            f.write("extra.example\n")
        self.now += datetime.timedelta(minutes=5)                 # not due, but the copy is damaged: it is not believed
        self.fetch.calls.clear()
        ctx = self.step()
        problems = [l for l in self.lines() if l["step"] == "list_update" and l["reason"].startswith("stored lists:")]
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["outcome"], "failed")
        self.assertTrue(ctx.matcher.problems)
        self.assertNotIn("extra.example", json.dumps(self.lines()))

    def test_a_clean_library_logs_no_problem_line(self):
        self.step()
        self.step()
        self.assertEqual([l for l in self.lines() if l["reason"].startswith("stored lists:")], [])

    def test_a_list_address_that_is_loopback_or_resolves_to_a_private_address_is_refused_by_the_real_client_and_the_step_refuses(self):
        for address in ("https://127.0.0.1/list.txt", "https://localhost/list.txt", "https://[::1]/list.txt", "https://169.254.169.254/latest/list.txt"):
            with self.subTest(address=address):
                plan = dict(self.plan, phishing_domains_url=address)
                with self.assertRaises(crawlrun.StepRefused) as caught:
                    self.step(self.ctx(plan), fetch=webclient.get)                # the real client: nothing is sent, because the address is not fetched
                self.assertIn("phishing_domains", str(caught.exception))
        failed = [l for l in self.lines() if l["step"] == "list_update" and l["outcome"] == "failed" and l["reason"].startswith("phishing_domains")]
        self.assertEqual(len(failed), 4)                                      # each was refused by the client and logged, so the step reached the real client each time

    def test_a_plan_the_lists_module_will_not_take_is_a_refusal_of_the_step(self):
        self.plan["list_max_change"] = 5
        with self.assertRaises(crawlrun.StepRefused):
            self.step()
        self.assertEqual(self.fetch.calls, [])

    def test_the_log_line_of_a_status_it_does_not_know_is_failed_and_a_count_is_a_whole_number_or_nothing(self):
        crawllists._log(self.log, NOW, "x", {"status": "weird"})
        crawllists._log(self.log, NOW, "y", {"status": "ok", "entries": {"a": 1, "b": 2}})
        lines = self.lines()
        self.assertEqual((lines[0]["outcome"], lines[0]["n"]), ("failed", None))
        self.assertEqual((lines[1]["outcome"], lines[1]["n"]), ("ok", 2))
        for value, expected in ((True, None), (-1, None), (3, 3), (0, 0), ("5", None), (1.5, None), (None, None)):
            self.assertEqual(crawllists._count({"entries": value}), expected, value)

    def test_a_failed_download_keeps_the_last_good_copy_and_is_logged_as_failed(self):
        self.step()
        self.now = NOW + datetime.timedelta(hours=13)
        self.fetch.replies[PHISH_URL] = webclient.FetchError("the connection was reset")
        self.fetch.replies[PSL_URL] = (503, {}, b"")
        ctx = self.step()
        self.assertIsNotNone(ctx.matcher.blocked("bad1.example"))
        self.assertEqual(ctx.lists_report["lists"]["phishing_domains"]["status"], "failed")
        failed = [l for l in self.lines() if l["step"] == "list_update" and l["outcome"] == "failed"]
        self.assertEqual(len(failed), 2)
        self.assertIn("reset", failed[0]["reason"] + failed[1]["reason"])

    def test_a_required_list_with_no_copy_ends_the_step_with_a_refusal_naming_the_list(self):
        self.fetch.replies[PHISH_URL] = (500, {}, b"")
        with self.assertRaises(crawlrun.StepRefused) as caught:
            self.step()
        self.assertIn("phishing_domains", str(caught.exception))
        self.assertTrue(any(l["outcome"] == "failed" for l in self.lines() if l["step"] == "list_update"))

    def test_a_list_that_is_refused_for_its_size_its_shrinking_or_its_change_leaves_the_copy_in_use(self):
        self.fetch.replies[PHISH_URL] = (200, {}, hosts(*[f"bad{i}.example" for i in range(10)]))
        self.step()
        cases = {"smaller than the share": hosts("bad0.example", "bad1.example", "bad2.example", "bad3.example"),
                 "changed too much": hosts(*[f"bad{i}.example" for i in range(5)] + [f"new{i}.example" for i in range(5)]),
                 "no valid entry": b"not a host!\n\x00\xff\n"}
        for name, body in cases.items():
            with self.subTest(name):
                self.now += datetime.timedelta(hours=13)
                self.fetch.replies[PHISH_URL] = (200, {}, body)
                ctx = self.step()
                self.assertEqual(ctx.lists_report["lists"]["phishing_domains"]["status"], "refused", name)
                self.assertIsNotNone(ctx.matcher.blocked("bad9.example"), name)
                self.assertIsNone(ctx.matcher.blocked("new0.example"), name)
        self.plan["list_max_mb"] = 1
        self.now += datetime.timedelta(hours=13)
        self.fetch.replies[PHISH_URL] = (200, {}, hosts(*[f"bad{i}.example" for i in range(10)]) + b"x" * (1024 * 1024 + 1))
        ctx = self.step()
        self.assertEqual(ctx.lists_report["lists"]["phishing_domains"]["status"], "refused")
        self.assertIsNotNone(ctx.matcher.blocked("bad9.example"))
        self.assertTrue(any(l["outcome"] == "refused" for l in self.lines() if l["step"] == "list_update"))

    def test_a_list_that_is_switched_off_is_not_requested(self):
        self.plan["phishing_domains"] = False
        self.step()
        self.assertEqual(self.fetch.urls(), [PSL_URL])

    def test_a_download_that_raises_something_odd_is_a_failed_list_and_not_a_crash_of_the_step(self):
        self.step()
        self.now += datetime.timedelta(hours=13)
        self.fetch.replies[PHISH_URL] = RuntimeError("something odd")
        ctx = self.step()
        self.assertEqual(ctx.lists_report["lists"]["phishing_domains"]["status"], "failed")
        self.assertIsNotNone(ctx.matcher.blocked("bad1.example"))


class Matching(Case):
    def test_the_owners_blacklist_blocks_a_host_and_every_host_below_it_and_not_a_similar_name(self):
        ctx = self.step()
        for host in ("evil.example", "www.evil.example", "a.b.evil.example"):
            self.assertIsNotNone(ctx.matcher.blocked(host), host)
        for host in ("notevil.example", "evil.example.org", "evil-example.net"):
            self.assertIsNone(ctx.matcher.blocked(host), host)

    def test_a_public_host_entry_blocks_that_exact_host_only(self):
        self.fetch.replies[PHISH_URL] = (200, {}, hosts("bad.example", "x.big.example"))
        ctx = self.step()
        self.assertIsNotNone(ctx.matcher.blocked("bad.example"))
        self.assertIsNone(ctx.matcher.blocked("www.bad.example"))
        self.assertIsNotNone(ctx.matcher.blocked("x.big.example"))
        self.assertIsNone(ctx.matcher.blocked("big.example"))
        self.assertIsNone(ctx.matcher.blocked("y.big.example"))

    def test_a_pinned_source_host_is_never_blocked_by_a_public_list_but_the_owners_blacklist_still_can(self):
        self.fetch.replies[PHISH_URL] = (200, {}, hosts("openalex.org", "api.openalex.org", "bad.example"))
        ctx = self.step()
        self.assertIsNone(ctx.matcher.blocked("openalex.org"))
        self.assertIsNone(ctx.matcher.blocked("api.openalex.org"))
        self.put("black.txt", "evil.example\nopenalex.org\n")
        ctx = self.step()
        self.assertIsNotNone(ctx.matcher.blocked("openalex.org"))

    def test_the_allow_file_lets_through_a_host_a_public_list_blocks_and_never_one_the_owner_blocks(self):
        self.fetch.replies[PHISH_URL] = (200, {}, hosts("listed.example", "evil.example"))
        self.put("allow.txt", "listed.example\nevil.example\n")
        ctx = self.step()
        self.assertIsNone(ctx.matcher.blocked("listed.example"))
        self.assertIsNotNone(ctx.matcher.blocked("evil.example"))
        self.assertIsNotNone(ctx.matcher.blocked("www.evil.example"))

    def test_the_allow_file_read_is_the_one_the_plan_names_which_a_run_makes_the_approved_copy(self):
        approved = self.put("approved-allow.txt", "listed.example\n")
        self.fetch.replies[PHISH_URL] = (200, {}, hosts("listed.example"))
        self.put("allow.txt", "")                                       # the live file says nothing
        plan = dict(self.plan, allow=approved)
        ctx = self.step(self.ctx(plan))
        self.assertIsNone(ctx.matcher.blocked("listed.example"))
        ctx = self.step(self.ctx(dict(self.plan, allow=self.allow)))
        self.assertIsNotNone(ctx.matcher.blocked("listed.example"))

    def test_the_blacklist_is_read_afresh_each_run_and_a_bad_line_is_a_refusal_that_names_its_number_and_not_its_text(self):
        ctx = self.step()
        self.assertIsNone(ctx.matcher.blocked("later.example"))
        self.put("black.txt", "evil.example\nlater.example\n")
        self.assertIsNotNone(self.step().matcher.blocked("later.example"))
        self.put("black.txt", "evil.example\nthis is not a host SECRETWORD\n")
        with self.assertRaises(crawlrun.StepRefused) as caught:
            self.step()
        self.assertIn("2", str(caught.exception))
        self.assertNotIn("SECRETWORD", str(caught.exception))

    def test_the_public_suffix_list_is_given_to_the_steps_and_to_the_policy_of_the_next_download(self):
        ctx = self.step()
        self.assertTrue({"com", "org", "co.uk"} <= set(ctx.suffixes))
        self.fetch.calls.clear()
        self.now += datetime.timedelta(hours=13)
        self.step()
        self.assertTrue(self.fetch.calls)
        for call in self.fetch.calls:
            self.assertIn("co.uk", call.policy.suffixes)                  # the policy of the second run holds the list the first one stored


class Policy(Case):
    def test_a_download_is_made_under_a_policy_with_the_honest_agent_the_plans_pacing_and_no_credential(self):
        self.plan.update(min_gap_s=7, jitter=2)
        self.step()
        for call in self.fetch.calls:
            policy = call.policy
            self.assertEqual(policy.user_agent, webclient.GENERIC_USER_AGENT)
            self.assertEqual((policy.gap, policy.jitter), (7, 2))
            self.assertTrue(policy.follow_redirects)
            self.assertFalse(policy.credential_headers)
            self.assertFalse(policy.allow_private)
            self.assertIn("text/plain", policy.types)

    def test_the_stop_file_refuses_each_request_through_the_policys_hook_and_the_list_stays_as_it_was(self):
        self.step()
        self.now += datetime.timedelta(hours=13)
        self.fetch.calls.clear()
        open(os.path.join(self.index, "crawl.stop"), "w").close()
        ctx = self.step()
        self.assertEqual(ctx.lists_report["lists"]["phishing_domains"]["status"], "failed")
        self.assertIn("stop file", ctx.lists_report["lists"]["phishing_domains"]["reason"])
        self.assertIsNotNone(ctx.matcher.blocked("bad1.example"))
        self.assertTrue(self.fetch.calls and all(c.verdict for c in self.fetch.calls))          # every request was refused by the hook, and none was answered
        self.assertEqual(ctx.lists_report["lists"]["public_suffix"]["status"], "failed")

    def test_an_address_on_the_owners_blacklist_is_not_requested_even_as_a_list_address(self):
        self.put("black.txt", "raw.githubusercontent.com\n")
        with self.assertRaises(crawlrun.StepRefused):                # the required list could not be had
            self.step()
        asked = [c for c in self.fetch.calls if c.url == PHISH_URL]
        self.assertEqual(len(asked), 1)
        self.assertTrue(asked[0].verdict)                              # the hook refused it, for the owner's blacklist
        self.assertEqual(asked[0].verdict.reason, "owner")
        self.assertTrue(any(c.url == PSL_URL and not c.verdict for c in self.fetch.calls))      # and not an address that is not listed


class UrlHaus(Case):
    URL = urlhaus.RECENT_URL

    def reply(self, urls=("http://203.0.113.9/payload.sh",)):
        body = json.dumps({"query_status": "ok", "urls": [{"url": u, "date_added": "2026-11-16 11:00:00 UTC", "url_status": "online"} for u in urls]}).encode()
        return (200, {"x-ratelimit-remaining": "99"}, body)

    def test_it_is_off_by_default_and_makes_no_request_and_reads_no_key(self):
        self.key()
        with mock.patch.object(urlhaus, "read_key", side_effect=AssertionError("the key must not be read")):
            self.step()
        self.assertNotIn(self.URL, self.fetch.urls())

    def test_with_no_key_file_no_request_is_made_and_the_list_is_logged_as_failed_without_a_path(self):
        self.urlhaus_on()
        self.step()
        self.assertNotIn(self.URL, self.fetch.urls())
        line = [l for l in self.lines() if l["step"] == "list_update" and l["reason"].startswith("urlhaus_recent")][0]
        self.assertEqual(line["outcome"], "failed")
        self.assertNotIn(self.dir, line["reason"])

    def test_a_key_file_that_is_loose_or_a_link_or_empty_is_not_used_and_no_request_is_made(self):
        self.urlhaus_on()
        self.key(mode=0o644)
        self.step()
        self.assertNotIn(self.URL, self.fetch.urls())
        os.remove(self.key_path)
        self.key(text="short")
        self.step()
        self.assertNotIn(self.URL, self.fetch.urls())

    def test_the_key_goes_only_in_the_auth_key_header_over_https_to_its_host_in_a_call_that_follows_no_redirect(self):
        self.urlhaus_on()
        self.key()
        self.fetch.replies[self.URL] = self.reply()
        ctx = self.step()
        call = [c for c in self.fetch.calls if c.url == self.URL][0]
        self.assertEqual(call.policy.credential_headers, {"Auth-Key": KEY})
        self.assertEqual(call.policy.credential_host, urlhaus.HOST)
        self.assertFalse(call.policy.follow_redirects)
        self.assertTrue(call.url.startswith("https://"))
        for other in self.fetch.calls:
            if other.url != self.URL:
                self.assertFalse(other.policy.credential_headers)
                self.assertNotIn(KEY, json.dumps(other.headers))
        self.assertEqual(ctx.lists_report["urlhaus"]["status"], "ok")
        self.assertIsNotNone(ctx.matcher.blocked("http://203.0.113.9/payload.sh"))

    def test_a_url_entry_blocks_that_exact_address_and_a_host_only_when_it_is_a_bare_ip(self):
        self.urlhaus_on()
        self.key()
        self.fetch.replies[self.URL] = self.reply(["http://203.0.113.9/payload.sh", "https://github.com/some/file", "http://scam.example/a"])
        ctx = self.step()
        self.assertIsNotNone(ctx.matcher.blocked("http://203.0.113.9/other"))              # a bare IP: the whole host
        self.assertIsNotNone(ctx.matcher.blocked("https://github.com/some/file"))
        self.assertIsNone(ctx.matcher.blocked("https://github.com/another/file"))        # a named host: that URL only
        self.assertIsNone(ctx.matcher.blocked("github.com"))
        self.assertIsNone(ctx.matcher.blocked("http://scam.example/b"))

    def test_the_urlhaus_line_is_ok_with_the_number_of_urls_and_the_default_key_file_is_the_one_in_the_config_folder(self):
        self.urlhaus_on()
        self.fetch.replies[self.URL] = self.reply(["http://203.0.113.9/a", "http://203.0.113.10/b"])
        with open(os.path.join(self.dir, "urlhaus.key"), "w") as f:                       # the spec's name for the owner's key file
            f.write(KEY + "\n")
        os.chmod(os.path.join(self.dir, "urlhaus.key"), 0o600)
        ctx = self.ctx()
        with mock.patch.object(crawllists.config, "config_dir", return_value=self.dir), mock.patch.object(crawllists.webclient, "get", self.fetch):
            crawllists.make_step()(ctx)
        self.assertIn(self.URL, self.fetch.urls())
        line = [l for l in self.lines() if l["reason"].startswith("urlhaus_recent")][0]
        self.assertEqual((line["outcome"], line["n"]), ("ok", 2))

    def test_a_service_that_another_process_is_asking_is_logged_as_failed_and_no_request_is_made(self):
        self.urlhaus_on()
        self.key()
        folder = os.path.join(self.index, "crawl", "lists")
        os.makedirs(folder, mode=0o700)
        fd = os.open(os.path.join(folder, urlhaus.LOCK_FILE), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            ctx = self.step()
        finally:
            os.close(fd)
        self.assertEqual(ctx.lists_report["urlhaus"]["status"], "busy")
        self.assertNotIn(self.URL, self.fetch.urls())
        line = [l for l in self.lines() if l["reason"].startswith("urlhaus_recent")][0]
        self.assertEqual(line["outcome"], "failed")

    def test_the_stop_file_refuses_the_urlhaus_request_through_the_same_hook(self):
        self.urlhaus_on()
        self.key()
        open(os.path.join(self.index, "crawl.stop"), "w").close()
        self.fetch.replies[self.URL] = self.reply()
        ctx = self.step(self.ctx(dict(self.plan, phishing_domains=False)))
        calls = [c for c in self.fetch.calls if c.url == self.URL]
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].verdict)
        self.assertNotEqual(ctx.lists_report["urlhaus"]["status"], "ok")

    def test_a_source_that_raises_is_a_failed_service_named_by_its_type_and_never_by_its_text(self):
        self.urlhaus_on()
        self.key()
        with mock.patch.object(crawllists.urlhaus, "Source", side_effect=RuntimeError(f"broke, with {KEY} in it")):
            ctx = self.step()
        self.assertEqual(ctx.lists_report["urlhaus"]["status"], "failed")
        self.assertIn("RuntimeError", ctx.lists_report["urlhaus"]["reason"])
        self.assertNotIn(KEY, json.dumps(ctx.lists_report, default=str))
        self.assertNotIn(KEY, json.dumps(self.lines()))

    def test_a_key_that_changed_while_the_request_was_made_is_a_secret_of_the_log_too(self):
        self.urlhaus_on()
        self.key()
        first, second = "first-key-0123456789abcdef", "second-key-0123456789abcdef"
        reads = []

        def read_key(path):
            reads.append(path)
            return first if len(reads) == 1 else second              # the file changed after the step read it, before the source did

        self.fetch.replies[self.URL] = webclient.FetchError(f"it failed, and echoed {second}")
        with mock.patch.object(urlhaus, "read_key", read_key):
            ctx = self.step()
        self.assertGreaterEqual(len(reads), 2)
        for secret in (first, second):
            self.assertEqual(ctx.log.safe(f"text with {secret} in it"), crawllog.WITHHELD, secret)
        self.assertNotIn(second, json.dumps(self.lines()))

    def test_the_key_is_given_to_the_log_as_a_secret_and_a_text_with_it_is_withheld(self):
        self.urlhaus_on()
        self.key()
        self.fetch.replies[self.URL] = self.reply()
        ctx = self.step()
        self.assertEqual(ctx.log.safe(f"it failed with {KEY} in it"), crawllog.WITHHELD)
        with self.assertRaises(KbError):
            ctx.log.write("fail", "failed", reason=f"it failed with {KEY} in it")

    def test_a_redirect_shows_the_second_host_no_key_and_the_key_is_not_sent_again_that_day(self):
        self.urlhaus_on()
        self.key()
        self.fetch.replies[self.URL] = webclient.Refused("the server redirected, and this request follows no redirect")
        ctx = self.step()
        self.assertEqual(ctx.lists_report["urlhaus"]["status"], "refused")
        self.assertEqual([c.url for c in self.fetch.calls].count(self.URL), 1)
        self.assertNotIn("https://other.example", self.fetch.urls())
        before = len(self.fetch.calls)
        self.now += datetime.timedelta(hours=3)                                                     # the same day
        self.fetch.replies[self.URL] = self.reply()
        ctx = self.step()
        self.assertEqual([c.url for c in self.fetch.calls[before:]].count(self.URL), 0)
        self.assertEqual(ctx.lists_report["urlhaus"]["status"], "off-for-the-day")
        outcomes = [l["outcome"] for l in self.lines() if l["step"] == "list_update" and l["reason"].startswith("urlhaus_recent")]
        self.assertEqual(outcomes, ["refused", "skipped"])

    def test_a_status_other_than_200_and_a_rate_limit_at_zero_stop_the_service_for_the_day(self):
        self.urlhaus_on()
        self.key()
        self.fetch.replies[self.URL] = (200, {"x-ratelimit-remaining": "0"}, self.reply()[2])
        self.step()
        before = len(self.fetch.calls)
        self.now += datetime.timedelta(hours=2)
        self.step()
        self.assertNotIn(self.URL, [c.url for c in self.fetch.calls[before:]])
        self.now += datetime.timedelta(days=1)                                                       # and it is asked again the next day
        self.fetch.replies[self.URL] = (429, {}, b"")
        self.step()
        self.assertIn(self.URL, [c.url for c in self.fetch.calls[before:]])
        before = len(self.fetch.calls)
        self.now += datetime.timedelta(hours=2)
        self.step()
        self.assertNotIn(self.URL, [c.url for c in self.fetch.calls[before:]])

    def test_a_forced_exception_inside_the_request_leaves_the_key_nowhere(self):
        self.urlhaus_on()
        self.key()
        self.fetch.replies[self.URL] = RuntimeError(f"boom, and the key is {KEY}")
        env_before = dict(os.environ)
        ctx = self.step()
        self.assertEqual(ctx.lists_report["urlhaus"]["status"], "failed")
        self.assertNotIn(KEY, self.tree_text().replace(open(self.key_path).read().strip(), ""))     # nowhere in the library, the log or the state, but the key file itself
        self.assertNotIn(KEY, json.dumps(ctx.lists_report, default=str))
        self.assertNotIn(KEY, repr(sorted(os.environ.items())))
        self.assertEqual(dict(os.environ), env_before)
        for line in self.lines():
            self.assertNotIn(KEY, json.dumps(line))
        self.assertNotIn(KEY, " ".join(c.url for c in self.fetch.calls))

    def test_the_key_is_in_no_address_and_a_server_that_echoes_it_does_not_get_it_kept(self):
        self.urlhaus_on()
        self.key()
        body = json.dumps({"query_status": "ok", "urls": [{"url": f"http://scam.example/{KEY}", "date_added": "2026-11-16 11:00:00 UTC"}]}).encode()
        self.fetch.replies[self.URL] = (200, {"x-ratelimit-remaining": "9"}, body)
        self.step()
        self.assertNotIn(KEY, self.tree_text().replace(open(self.key_path).read().strip(), ""))
        for call in self.fetch.calls:
            self.assertNotIn(KEY, call.url)

    def test_the_hourly_rule_and_the_kept_urls_work_through_the_step(self):
        self.urlhaus_on()
        self.key()
        self.fetch.replies[self.URL] = self.reply()
        self.step()
        before = len(self.fetch.calls)
        self.now += datetime.timedelta(minutes=30)
        ctx = self.step()
        self.assertNotIn(self.URL, [c.url for c in self.fetch.calls[before:]])
        self.assertIsNotNone(ctx.matcher.blocked("http://203.0.113.9/payload.sh"))              # the kept URLs are still in use
        self.now += datetime.timedelta(hours=2)
        self.step()
        self.assertIn(self.URL, [c.url for c in self.fetch.calls[before:]])


class Wiring(Case):
    def test_the_step_makes_no_request_of_its_own_changes_no_row_and_reads_no_environment_variable_of_its_own(self):
        with open(os.path.join(ENGINE_DIR, "kb", "crawllists.py"), encoding="utf-8") as f:
            source = f.read()
        for word in ("socket", "urllib", "subprocess", "UPDATE", "DELETE", "INSERT", "os.environ", "getenv"):
            self.assertNotIn(word, source, word)

    def test_a_step_that_refuses_leaves_no_matcher_on_the_context_but_keeps_the_report_for_the_log(self):
        self.fetch.replies[PHISH_URL] = (500, {}, b"")
        ctx = self.ctx()
        with self.assertRaises(crawlrun.StepRefused):
            crawllists.make_step(fetch=self.fetch, key_path=self.key_path)(ctx)
        self.assertIsNone(ctx.matcher)
        self.assertIsNone(ctx.suffixes)
        self.assertEqual(ctx.lists_report["lists"]["phishing_domains"]["status"], "failed")

    def test_the_step_leaves_only_the_lists_folder_in_the_crawl_folder_and_in_mode_700(self):
        self.step()
        folder = os.path.join(self.index, "crawl", "lists")
        self.assertEqual(stat.S_IMODE(os.stat(folder).st_mode), 0o700)
        for name in os.listdir(folder):
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(folder, name)).st_mode) & 0o077, 0, name)
        self.assertEqual(sorted(n for n in os.listdir(os.path.join(self.index, "crawl")) if not n.startswith(".")), ["lists", "log"])

    def test_the_default_step_uses_the_shared_client_and_the_owners_key_file_in_the_config_folder(self):
        built = crawllists.make_step()
        self.assertTrue(callable(built))
        with mock.patch.object(crawllists.config, "config_dir", return_value=self.dir):
            with mock.patch.object(crawllists.webclient, "get", self.fetch):
                ctx = self.ctx()
                built(ctx)
        self.assertIsNotNone(ctx.matcher)
        self.assertTrue(self.fetch.calls)


if __name__ == "__main__":
    unittest.main()
