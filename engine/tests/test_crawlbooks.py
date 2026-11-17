"""The crawl's books: their events and readers (`kb/crawlbooks.py`, Increment C of the plan `2026-11-16-run-the-steps-of-the-unattended-crawl`).

A crawl book is a book with a `crawl_found` event; its state is what its events say, so that every step can be run again. Terminal events are `crawl_rejected`, `crawl_held`, `reshelved` and `crawl_unplaced`.
Every test runs on a temporary library with fake approvals; none reads the owner's config, library or plan. Run them with
`python3 -W error::ResourceWarning -m unittest engine.tests.test_crawlbooks`."""
import datetime
import json
import math
import os
import tempfile
import unittest
from unittest import mock

from engine.tests import ENGINE_DIR  # noqa: F401

from kb import KbError, crawlapprove, crawlbooks, crawllog, crawlplan, crawlstate, library, store

NOW = datetime.datetime(2026, 11, 16, 12, 0, 0, tzinfo=datetime.timezone.utc)
PLAN_TEXT = "[limits]\nbatch = {batch}\n[judge]\nthreshold = 0.4\n"
TOPICS = "[core weight=10]\nverification\n"
DIGEST = "a" * 32


def make_writable(path):
    for dirpath, _dirnames, filenames in os.walk(path):
        os.chmod(dirpath, 0o700)
        for f in filenames:
            p = os.path.join(dirpath, f)
            if not os.path.islink(p):
                os.chmod(p, 0o600)


def model_config():
    return {"models_on": True, "models": {"emb": {"bridge": "ask-ollama", "server": "ned", "model": "m", "kind": "embedding", "dimension": 8, "thinking": False}}, "tasks": {"card-embed": "emb"}}


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = os.path.realpath(self._tmp.name)
        self.addCleanup(make_writable, self.base)
        self.cfgdir, self.bulk, self.index = (os.path.join(self.base, n) for n in ("cfg", "bulk", "index"))
        saved = os.environ.get("KB_CONFIG_DIR")
        os.environ["KB_CONFIG_DIR"] = self.cfgdir
        self.addCleanup(lambda: os.environ.pop("KB_CONFIG_DIR", None) if saved is None else os.environ.__setitem__("KB_CONFIG_DIR", saved))
        library.setup(self.bulk, self.index, allow_main_disk=True)
        self.store = store.Store.open()
        self.plan = crawlplan.defaults()
        self.kb = os.path.join(self.base, "kb")
        os.makedirs(self.kb)
        with open(os.path.join(self.kb, "a.py"), "w") as f:
            f.write("print(1)\n")
        self.files = os.path.join(self.base, "files")
        os.mkdir(self.files)
        self.counter = 0

    def put(self, name, text):
        path = os.path.join(self.files, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(path, 0o600)
        return path

    def approve(self, batch=None):
        """A real approval under `crawl/approved/`, of a plan that differs from every earlier one; returns its digest."""
        self.counter += 1
        batch = batch or self.counter + 1
        topics, allow = self.put("topics.txt", TOPICS), self.put("allow.txt", "")
        plan = self.put("plan.txt", PLAN_TEXT.format(batch=batch) + f"[files]\ntopics = {topics}\nallow = {allow}\nblacklist = {self.files}/b.txt\n")
        cfg = model_config()
        digest = crawlapprove.approve(self.index, cfg, plan, kb_root=self.kb)[1]
        crawlapprove.approve(self.index, cfg, plan, digest=digest, kb_root=self.kb, is_tty=lambda: True, say=lambda s: None, now=NOW)
        return digest

    def book(self, **kw):
        kw.setdefault("auto_filed", True)
        return self.store.create_book(title="A page", kind="web page", **kw)

    def found_args(self, digest=DIGEST, **kw):
        args = {"candidate": 7, "source": "openalex", "found_from": "openalex:W1", "topic": "verification", "run": "run-1", "plan_digest": digest}
        args.update(kw)
        return args

    def found(self, digest=DIGEST, **kw):
        ident = self.book()
        crawlbooks.record_found(self.store, ident, **self.found_args(digest, **kw))
        return ident

    def found_at(self, digest, stamp, **kw):
        """A crawl book whose `crawl_found` has the time `stamp`, so that the order of books does not depend on the second they were made in."""
        ident = self.book()
        with mock.patch("kb.store.now", return_value=stamp):
            crawlbooks.record_found(self.store, ident, **self.found_args(digest, **kw))
        return ident

    def events(self, ident):
        return self.store.read_events(ident)

    def names(self, ident):
        return [e["event"] for e in self.events(ident)]


class Writers(Case):
    def test_each_event_is_written_with_exactly_its_fields_and_name(self):
        a = self.book()
        b, c, d, e, f = (self.found() for _ in range(5))
        crawlbooks.record_found(self.store, a, **self.found_args())
        crawlbooks.record_held(self.store, b, ["encrypted", "javascript"])
        crawlbooks.record_rejected(self.store, c, "not about any shelf", 0.12, "judge")
        crawlbooks.record_unplaced(self.store, d, "the proposal was none")
        crawlbooks.record_step_failed(self.store, e, "convert", "the converter was killed", "run-2")
        crawlbooks.record_judged(self.store, f, 0.62, "formal-methods", True)
        got = {n: self.events(i)[-1] for n, i in (("found", a), ("held", b), ("rejected", c), ("unplaced", d), ("failed", e), ("judged", f))}
        strip = lambda ev: {k: v for k, v in ev.items() if k not in ("at",)}  # noqa: E731
        self.assertEqual(strip(got["found"]), {"event": "crawl_found", "candidate": 7, "source": "openalex", "found_from": "openalex:W1", "topic": "verification", "run": "run-1", "plan_digest": DIGEST})
        self.assertEqual(strip(got["held"]), {"event": "crawl_held", "kinds": ["encrypted", "javascript"]})
        self.assertEqual(strip(got["rejected"]), {"event": "crawl_rejected", "reason": "not about any shelf", "score": 0.12, "stage": "judge"})
        self.assertEqual(strip(got["unplaced"]), {"event": "crawl_unplaced", "reason": "the proposal was none"})
        self.assertEqual(strip(got["failed"]), {"event": "crawl_step_failed", "step": "convert", "reason": "the converter was killed", "run": "run-2"})
        self.assertEqual(strip(got["judged"]), {"event": "crawl_judged", "score": 0.62, "shelf": "formal-methods", "ok": True})
        for ev in got.values():
            self.assertRegex(ev["at"], r"^\d{4}-\d\d-\d\dT")

    def test_every_stage_every_hold_kind_and_the_edges_of_a_score_are_taken(self):
        self.assertEqual(crawlbooks.STAGES, ("capture", "scan", "convert", "index", "judge", "card", "propose", "move"))
        from kb import scan_tool
        for stage in crawlbooks.STAGES:
            ident = self.found()
            self.assertTrue(crawlbooks.record_rejected(self.store, ident, "r", 0.5, stage))
            other = self.found()
            crawlbooks.record_step_failed(self.store, other, stage, "r", "run-1")
            self.assertEqual(crawlbooks.step_failures(self.store, other, stage), 1)
        kinds = sorted(scan_tool.KINDS) + ["scan_failed", "scan_unavailable", "scan_timeout"]
        for kind in kinds:
            self.assertTrue(crawlbooks.record_held(self.store, self.found(), [kind]), kind)
        self.assertTrue(crawlbooks.record_held(self.store, self.found(), kinds))
        for score in (1, 1.0, -1, -1.0, 0, 0.0):
            self.assertTrue(crawlbooks.record_rejected(self.store, self.found(), "r", score, "judge"))
        for score in (1.0001, -1.0001, 1.5, -2):
            with self.assertRaises(KbError):
                crawlbooks.record_rejected(self.store, self.found(), "r", score, "judge")
            with self.assertRaises(KbError):
                crawlbooks.record_judged(self.store, self.found(), score, "s", True)
        for stage in (["scan"], ("scan",), {"scan"}, b"scan"):
            with self.assertRaises(KbError):
                crawlbooks.record_rejected(self.store, self.found(), "r", 0.5, stage)

    def test_every_writer_but_found_refuses_a_book_the_crawl_did_not_file_and_found_refuses_an_owners_book(self):
        owner, plain = self.book(auto_filed=False), self.book()
        for ident in (owner, plain):
            for call in (lambda i: crawlbooks.record_held(self.store, i, ["encrypted"]), lambda i: crawlbooks.record_rejected(self.store, i, "r", None, "judge"),
                         lambda i: crawlbooks.record_unplaced(self.store, i, "r"), lambda i: crawlbooks.record_step_failed(self.store, i, "scan", "r", "run-1"),
                         lambda i: crawlbooks.record_judged(self.store, i, 0.5, "s", True)):
                with self.assertRaises(KbError):
                    call(ident)
            self.assertEqual(self.events(ident), [])
        with self.assertRaises(KbError):
            crawlbooks.record_found(self.store, owner, **self.found_args())                    # a book the owner filed is not the crawl's
        self.assertEqual(self.events(owner), [])
        forged = self.book(auto_filed=False)
        self.store.append_event(forged, "crawl_found", candidate=1, source="openalex", found_from=None, topic=None, run="run-1", plan_digest=DIGEST)
        with self.assertRaises(KbError):
            crawlbooks.record_unplaced(self.store, forged, "r")
        self.assertEqual(self.names(forged), ["crawl_found"])

    def test_a_verdict_is_recorded_once_and_needs_a_score(self):
        ident = self.found()
        self.assertTrue(crawlbooks.record_judged(self.store, ident, 0.5, "x", True))
        self.assertFalse(crawlbooks.record_judged(self.store, ident, 0.1, "y", False))
        self.assertEqual([e["event"] for e in self.events(ident)].count("crawl_judged"), 1)
        self.assertEqual(self.events(ident)[1]["score"], 0.5)
        with self.assertRaises(KbError):
            crawlbooks.record_judged(self.store, self.found(), None, "x", True)

    def test_a_field_that_is_missing_wrong_or_unknown_is_refused_and_writes_nothing(self):
        fresh = self.book()
        ident = self.found()
        bad_found = [{"candidate": True}, {"candidate": 0}, {"candidate": "7"}, {"candidate": 2**63}, {"source": ""}, {"source": 5}, {"source": "x" * 41}, {"found_from": 5}, {"topic": []},
                     {"run": ""}, {"run": "a b"}, {"run": "x" * 65}, {"plan_digest": "A" * 32}, {"plan_digest": "a" * 31}, {"plan_digest": "g" * 32}, {"plan_digest": None}, {"plan_digest": 5}]
        for change in bad_found:
            with self.subTest(change=change):
                with self.assertRaises(KbError):
                    crawlbooks.record_found(self.store, fresh, **self.found_args(**change))
        with self.assertRaises(TypeError):
            crawlbooks.record_found(self.store, fresh, **self.found_args(), extra="x")
        args = self.found_args()
        del args["topic"]
        with self.assertRaises(TypeError):
            crawlbooks.record_found(self.store, fresh, **args)
        self.assertEqual(self.events(fresh), [])
        for kinds in ("encrypted", [], [""], ["encrypted", "encrypted"], ["not_a_kind"], [5], None, ["encrypted"] * 3, ["a"] * 30):
            with self.assertRaises(KbError):
                crawlbooks.record_held(self.store, ident, kinds)
        for reason, score, stage in (("", 0.1, "judge"), (5, 0.1, "judge"), ("r", True, "judge"), ("r", math.nan, "judge"), ("r", math.inf, "judge"), ("r", "0.1", "judge"), ("r", 0.1, "nowhere"),
                                     ("r", 0.1, None), ("r", 5.0, "judge"), ("r", -5.0, "judge")):
            with self.assertRaises(KbError):
                crawlbooks.record_rejected(self.store, ident, reason, score, stage)
        for step, reason, run in (("nowhere", "r", "run-1"), ("convert", "", "run-1"), ("convert", "r", ""), ("convert", "r", "a b"), (5, "r", "run-1")):
            with self.assertRaises(KbError):
                crawlbooks.record_step_failed(self.store, ident, step, reason, run)
        for score, shelf, ok in ((math.nan, "s", True), ("0.5", "s", True), (0.5, 5, True), (0.5, "s", 1), (0.5, "s", None), (True, "s", True), (0.5, "a b", True), (2.0, "s", True)):
            with self.assertRaises(KbError):
                crawlbooks.record_judged(self.store, ident, score, shelf, ok)
        self.assertEqual(self.names(ident), ["crawl_found"])

    def test_text_is_cleaned_cut_and_a_missing_score_or_shelf_is_none(self):
        ident = self.found()
        crawlbooks.record_rejected(self.store, ident, "a\x1b[31m red\r\nline‮ " + "zz " * 200, None, "scan")
        ev = self.events(ident)[-1]
        self.assertLessEqual(len(ev["reason"]), 300)
        self.assertTrue(ev["reason"].startswith("a[31m red line zz"))
        self.assertNotIn("\x1b", ev["reason"])
        self.assertNotIn("‮", ev["reason"])
        self.assertIsNone(ev["score"])
        other = self.found()
        crawlbooks.record_judged(self.store, other, 0.3, None, False)
        self.assertIsNone(self.events(other)[-1]["shelf"])
        third = self.book()
        crawlbooks.record_found(self.store, third, **self.found_args(found_from="y" * 400, topic=None))
        self.assertEqual(len(self.events(third)[0]["found_from"]), 300)
        self.assertIsNone(self.events(third)[0]["topic"])

    def test_a_book_that_is_not_there_or_a_store_opened_to_read_only_is_refused(self):
        with self.assertRaises(KbError):
            crawlbooks.record_unplaced(self.store, "nosuchbook", "x")
        ident = self.found()
        reader = store.Store(self.store.cfg, write=False)
        with self.assertRaises(KbError):
            crawlbooks.record_unplaced(reader, ident, "x")

    def test_a_book_is_found_once_and_a_terminal_event_is_written_once(self):
        ident = self.found()
        with self.assertRaises(KbError):
            crawlbooks.record_found(self.store, ident, **self.found_args())
        self.assertTrue(crawlbooks.record_held(self.store, ident, ["encrypted"]))
        self.assertFalse(crawlbooks.record_held(self.store, ident, ["encrypted"]))
        self.assertFalse(crawlbooks.record_unplaced(self.store, ident, "late"))
        self.assertFalse(crawlbooks.record_rejected(self.store, ident, "late", None, "judge"))
        self.assertEqual(self.names(ident), ["crawl_found", "crawl_held"])

    def test_a_reshelved_event_made_by_the_move_is_also_terminal(self):
        ident = self.found()
        self.store.append_event(ident, "reshelved", **{"from": "default", "to": "x", "via": "crawl"})
        self.assertFalse(crawlbooks.record_unplaced(self.store, ident, "late"))
        self.assertEqual(crawlbooks.TERMINAL, ("crawl_rejected", "crawl_held", "reshelved", "crawl_unplaced"))


class Weeding(Case):
    def test_weed_sets_the_state_and_writes_the_rejection_once(self):
        ident = self.found()
        self.assertTrue(crawlbooks.weed(self.store, ident, "below the threshold", 0.2, "judge"))
        self.assertEqual(self.store.read_book(ident)["state"], "weeded")
        self.assertEqual([e["event"] for e in self.events(ident)], ["crawl_found", "crawl_rejected"])
        self.assertFalse(crawlbooks.weed(self.store, ident, "again", 0.1, "judge"))
        self.assertEqual(len(self.events(ident)), 2)

    def test_a_weed_that_died_between_its_two_writes_leaves_the_event_and_a_reader_finishes_the_state(self):
        ident = self.found()
        with mock.patch.object(self.store, "set_state", side_effect=OSError(28, "full")):
            with self.assertRaises(OSError):
                crawlbooks.weed(self.store, ident, "below the threshold", 0.2, "judge")
        self.assertEqual(self.names(ident), ["crawl_found", "crawl_rejected"])              # the event was written first, with the reason and the stage
        self.assertEqual(self.store.read_book(ident)["state"], "active")
        self.assertEqual(crawlbooks.crawl_books(self.store, {DIGEST}), [])                  # it is terminal: not work
        self.assertEqual(crawlbooks.finish_weeds(self.store), [ident])
        self.assertEqual(self.store.read_book(ident)["state"], "weeded")
        self.assertEqual(crawlbooks.finish_weeds(self.store), [])
        self.assertEqual(self.names(ident), ["crawl_found", "crawl_rejected"])

    def test_calling_weed_again_after_that_death_finishes_it_too_and_writes_no_second_event(self):
        ident = self.found()
        crawlbooks.record_rejected(self.store, ident, "below the threshold", 0.2, "judge")      # the event is there, the state is not
        self.assertTrue(crawlbooks.weed(self.store, ident, "again", 0.1, "judge"))
        self.assertEqual(self.store.read_book(ident)["state"], "weeded")
        self.assertEqual(self.names(ident), ["crawl_found", "crawl_rejected"])
        self.assertEqual(self.events(ident)[1]["reason"], "below the threshold")

    def test_finish_weeds_touches_only_crawl_books_with_a_rejection_and_an_active_state(self):
        mine = self.found()
        crawlbooks.record_rejected(self.store, mine, "r", None, "judge")
        held = self.found()
        crawlbooks.record_held(self.store, held, ["encrypted"])
        owner = self.book(auto_filed=False)
        self.store.append_event(owner, "crawl_rejected", reason="forged", score=None, stage="judge")
        plain = self.found()
        self.assertEqual(crawlbooks.finish_weeds(self.store), [mine])
        self.assertEqual([self.store.read_book(i)["state"] for i in (mine, held, owner, plain)], ["weeded", "active", "active", "active"])

    def test_weed_does_not_overwrite_a_state_that_is_not_active(self):
        for state in ("removed", "duplicate"):
            ident = self.found()
            self.store.set_state(ident, state)
            self.assertTrue(crawlbooks.weed(self.store, ident, "r", None, "judge"))                 # the rejection is recorded
            self.assertEqual(self.store.read_book(ident)["state"], state)

    def test_weed_never_touches_a_book_that_is_not_a_crawl_book(self):
        ident = self.book()
        with self.assertRaises(KbError):
            crawlbooks.weed(self.store, ident, "x", None, "judge")
        self.assertEqual(self.store.read_book(ident)["state"], "active")
        self.assertEqual(self.events(ident), [])

    def test_a_book_that_has_a_terminal_event_is_not_weeded_afterwards(self):
        ident = self.found()
        crawlbooks.record_held(self.store, ident, ["encrypted"])
        self.assertFalse(crawlbooks.weed(self.store, ident, "late", None, "convert"))
        self.assertEqual(self.store.read_book(ident)["state"], "active")

    def test_the_failure_that_reaches_the_limit_parks_the_book_before_it_is_recorded_so_there_is_no_extra_try(self):
        plan = dict(self.plan, retries=2)
        ident = self.found()
        crawlbooks.fail_step(self.store, plan, ident, "convert", "killed", "run-1")
        with mock.patch.object(crawlbooks, "record_step_failed", side_effect=OSError(28, "full")):
            with self.assertRaises(OSError):
                crawlbooks.fail_step(self.store, plan, ident, "convert", "killed", "run-2")      # it dies after the weed, before the record of the failure
        self.assertEqual(self.store.read_book(ident)["state"], "weeded")
        self.assertIn("crawl_rejected", self.names(ident))
        self.assertEqual(crawlbooks.crawl_books(self.store, {DIGEST}), [])

    def test_step_failures_are_counted_by_step_and_at_retries_the_book_is_parked(self):
        plan = dict(self.plan, retries=3)
        ident = self.found()
        self.assertEqual(crawlbooks.step_failures(self.store, ident, "convert"), 0)
        self.assertEqual(crawlbooks.fail_step(self.store, plan, ident, "convert", "killed", "run-1"), "retry")
        self.assertEqual(crawlbooks.fail_step(self.store, plan, ident, "index", "slow", "run-1"), "retry")           # another step has its own count
        self.assertEqual(crawlbooks.fail_step(self.store, plan, ident, "convert", "killed", "run-2"), "retry")
        self.assertEqual((crawlbooks.step_failures(self.store, ident, "convert"), crawlbooks.step_failures(self.store, ident, "index")), (2, 1))
        self.assertEqual(self.store.read_book(ident)["state"], "active")
        self.assertEqual(crawlbooks.fail_step(self.store, plan, ident, "convert", "killed", "run-3"), "parked")
        self.assertEqual(self.store.read_book(ident)["state"], "weeded")
        rejected = [e for e in self.events(ident) if e["event"] == "crawl_rejected"]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["stage"], "convert")
        self.assertIn("3", rejected[0]["reason"])
        self.assertIn("killed", rejected[0]["reason"])
        self.assertIsNone(rejected[0]["score"])

    def test_a_failure_of_a_book_that_is_final_in_another_way_changes_nothing_and_says_finished(self):
        for finish in (lambda i: crawlbooks.record_held(self.store, i, ["encrypted"]), lambda i: crawlbooks.record_unplaced(self.store, i, "none")):
            ident = self.found()
            finish(ident)
            before = self.events(ident)
            self.assertEqual(crawlbooks.fail_step(self.store, self.plan, ident, "convert", "x", "run-1"), "finished")
            self.assertEqual(self.events(ident), before)

    def test_one_try_allowed_parks_at_the_first_failure_and_a_failure_of_a_parked_book_changes_nothing(self):
        ident = self.found()
        self.assertEqual(crawlbooks.fail_step(self.store, dict(self.plan, retries=1), ident, "card", "model down", "run-1"), "parked")
        before = self.events(ident)
        self.assertEqual(crawlbooks.fail_step(self.store, dict(self.plan, retries=1), ident, "card", "model down", "run-2"), "parked")
        self.assertEqual(self.events(ident), before)

    def test_a_failure_of_a_step_that_is_not_one_is_refused(self):
        ident = self.found()
        for step in ("nowhere", "", None, 5):
            with self.assertRaises(KbError):
                crawlbooks.step_failures(self.store, ident, step)
            with self.assertRaises(KbError):
                crawlbooks.fail_step(self.store, self.plan, ident, step, "x", "run-1")
        for plan in (None, {}, dict(self.plan, retries=0), dict(self.plan, retries=True)):
            with self.assertRaises(KbError):
                crawlbooks.fail_step(self.store, plan, ident, "convert", "x", "run-1")


class Readers(Case):
    def test_crawl_books_are_those_found_under_an_approved_plan_without_a_terminal_event_in_the_order_found(self):
        digest = self.approve()
        first, second, third = (self.found_at(digest, f"2026-11-16T10:00:0{n}Z") for n in (1, 2, 3))
        done, held, rejected = self.found(digest), self.found(digest), self.found(digest)
        crawlbooks.record_unplaced(self.store, done, "none")
        crawlbooks.record_held(self.store, held, ["encrypted"])
        crawlbooks.weed(self.store, rejected, "no", 0.1, "judge")
        self.assertEqual(crawlbooks.crawl_books(self.store, {digest}), [first, second, third])

    def test_the_owners_books_and_a_book_with_no_found_event_are_never_listed_or_touched(self):
        digest = self.approve()
        owners = [self.book(auto_filed=False) for _ in range(3)]
        plain = self.book()
        self.store.append_event(owners[0], "placement_proposed", answer="x")
        mine = self.found(digest)
        self.assertEqual(crawlbooks.crawl_books(self.store, {digest}), [mine])
        self.assertEqual(crawlbooks.unapproved_books(self.store, {digest}), [])
        log = crawllog.Log(self.index, "run-1")
        self.assertEqual(crawlbooks.reconcile_unapproved(self.store, {digest}, log), [])
        for ident in owners + [plain]:
            self.assertEqual(self.store.read_book(ident)["state"], "active")
        self.assertEqual(self.events(plain), [])
        self.assertEqual(self.names(owners[0]), ["placement_proposed"])

    def test_a_found_event_forged_onto_one_of_the_owners_books_is_ignored_by_every_reader(self):
        digest = self.approve()
        owner = self.book(auto_filed=False)
        self.store.append_event(owner, "crawl_found", candidate=1, source="openalex", found_from=None, topic=None, run="run-1", plan_digest=digest)
        stranger = self.book(auto_filed=False)
        self.store.append_event(stranger, "crawl_found", candidate=1, source="openalex", found_from=None, topic=None, run="run-1", plan_digest="f" * 32)
        scan = crawlbooks.scan_crawl_books(self.store)
        self.assertEqual(scan.entries, [])
        self.assertEqual(crawlbooks.crawl_books(self.store, {digest}, scan), [])
        self.assertEqual(crawlbooks.unapproved_books(self.store, {digest}, scan), [])
        self.assertEqual(crawlbooks.filed_events(self.store, scan), {})
        self.assertEqual(crawlbooks.reconcile_unapproved(self.store, {digest}, crawllog.Log(self.index, "run-1", clock=lambda: NOW)), [])
        self.assertEqual(self.names(stranger), ["crawl_found"])
        for forged in (owner, stranger):                                              # nor can a step weed it or count a failure against it
            with self.assertRaises(KbError) as caught:
                crawlbooks.weed(self.store, forged, "x", None, "judge")
            self.assertIn("not one the crawl filed", str(caught.exception))
            with self.assertRaises(KbError):
                crawlbooks.fail_step(self.store, self.plan, forged, "convert", "x", "run-1")
            self.assertEqual(self.store.read_book(forged)["state"], "active")
            self.assertEqual(self.names(forged), ["crawl_found"])
        with self.assertRaises(KbError):
            crawlbooks.weed(self.store, self.book(auto_filed=False), "x", None, "judge")

    def test_a_missing_malformed_or_unapproved_digest_makes_an_unapproved_book_and_not_a_crawl_book(self):
        digest = self.approve()
        good = self.found(digest)
        unknown = self.found("b" * 32)
        forged_missing = self.book()
        self.store.append_event(forged_missing, "crawl_found", candidate=1, source="openalex", found_from=None, topic=None, run="run-1")
        forged_bad = self.book()
        self.store.append_event(forged_bad, "crawl_found", candidate=1, source="openalex", found_from=None, topic=None, run="run-1", plan_digest="NOT A DIGEST")
        forged_type = self.book()
        self.store.append_event(forged_type, "crawl_found", candidate=1, source="openalex", found_from=None, topic=None, run="run-1", plan_digest=["a" * 32])
        garbage = self.book()
        self.store.append_event(garbage, "crawl_found")
        self.assertEqual(crawlbooks.crawl_books(self.store, {digest}), [good])
        self.assertEqual(sorted(crawlbooks.unapproved_books(self.store, {digest})), sorted([unknown, forged_missing, forged_bad, forged_type, garbage]))

    def test_a_book_that_is_not_active_is_not_work(self):
        digest = self.approve()
        gone, removed = self.found(digest), self.found(digest)
        self.store.set_state(gone, "weeded")
        self.store.set_state(removed, "removed")
        self.assertEqual(crawlbooks.crawl_books(self.store, {digest}), [])
        self.assertEqual(crawlbooks.unapproved_books(self.store, {digest}), [])

    def test_an_event_log_that_cannot_be_read_is_skipped_and_reported_and_does_not_stop_the_scan(self):
        digest = self.approve()
        ok = self.found(digest)
        bad = self.found(digest)
        events = self.store.events_file(bad)
        os.rename(events, events + ".real")
        os.symlink(events + ".real", events)
        scan = crawlbooks.scan_crawl_books(self.store)
        self.assertEqual(scan.unreadable, [bad])
        self.assertEqual(crawlbooks.crawl_books(self.store, {digest}, scan), [ok])
        self.assertEqual(crawlbooks.filed_count(self.store, scan), 2)                       # the unreadable one is counted: a ceiling is never undercounted

    def test_the_order_is_the_time_found_and_then_the_book_id(self):
        digest = self.approve()
        ids = [self.found(digest) for _ in range(4)]
        self.assertEqual(crawlbooks.crawl_books(self.store, {digest}), sorted(ids, key=lambda i: (self.events(i)[0]["at"], i)))

    def test_the_order_follows_the_time_found_and_not_the_book_id(self):
        digest = self.approve()
        low, middle, high = sorted(self.book() for _ in range(3))             # by id: low, middle, high; by time found it is to be the opposite
        times = {low: "2026-11-16T12:00:00Z", middle: "2026-11-16T11:00:00Z", high: "2026-11-16T10:00:00Z"}
        for ident in (middle, low, high):
            with mock.patch("kb.store.now", return_value=times[ident]):
                crawlbooks.record_found(self.store, ident, **self.found_args(digest))
        self.assertEqual(crawlbooks.crawl_books(self.store, {digest}), [high, middle, low])

    def test_a_scan_that_is_handed_in_is_used_and_the_library_is_not_read_again(self):
        digest = self.approve()
        self.found(digest)
        scan = crawlbooks.scan_crawl_books(self.store)
        with mock.patch.object(crawlbooks, "scan_crawl_books", side_effect=AssertionError("the library was read again")):
            crawlbooks.crawl_books(self.store, {digest}, scan)
            crawlbooks.unapproved_books(self.store, {digest}, scan)
            crawlbooks.filed_events(self.store, scan)
            self.assertEqual(crawlbooks.filed_count(self.store, scan), 1)
            crawlbooks.finish_weeds(self.store, scan)
            crawlbooks.reconcile_unapproved(self.store, {digest}, crawllog.Log(self.index, "run-1", clock=lambda: NOW), scan)

    def test_one_scan_can_serve_every_reader(self):
        digest = self.approve()
        mine = self.found(digest)
        stranger = self.found("c" * 32)
        scan = crawlbooks.scan_crawl_books(self.store)
        self.assertEqual(crawlbooks.crawl_books(self.store, {digest}, scan), [mine])
        self.assertEqual(crawlbooks.unapproved_books(self.store, {digest}, scan), [stranger])
        self.assertEqual(sorted(crawlbooks.filed_events(self.store, scan)), sorted([mine, stranger]))

    def test_the_filed_count_counts_every_book_with_a_found_event_and_gives_the_ceiling_its_input(self):
        digest = self.approve()
        a, b = self.found(digest), self.found("d" * 32)
        crawlbooks.weed(self.store, a, "no", 0.1, "judge")
        self.book()
        self.book(auto_filed=False)
        events = crawlbooks.filed_events(self.store)
        self.assertEqual(sorted(events), sorted([a, b]))
        self.assertEqual(crawlstate.filed_total(events), 2)
        self.assertEqual(crawlbooks.filed_count(self.store), 2)


class Approved(Case):
    def test_every_stored_approval_that_reads_strictly_is_listed(self):
        a, b = self.approve(), self.approve()
        self.assertNotEqual(a, b)
        self.assertEqual(crawlbooks.approved_digests(self.index), {a, b})

    def test_nothing_approved_or_no_folder_gives_an_empty_set(self):
        self.assertEqual(crawlbooks.approved_digests(self.index), set())
        os.makedirs(os.path.join(self.index, "crawl"))
        self.assertEqual(crawlbooks.approved_digests(self.index), set())

    def test_a_folder_that_a_link_a_loose_mode_an_extra_or_missing_file_or_a_changed_byte_spoils_is_left_out(self):
        good, linked, loose, extra, missing, changed, forged = (self.approve() for _ in range(7))
        approved = os.path.join(self.index, "crawl", "approved")
        os.chmod(approved, 0o700)

        def open_folder(digest):
            os.chmod(os.path.join(approved, digest), 0o700)
            return os.path.join(approved, digest)

        # a link in place of the folder
        os.chmod(os.path.join(approved, linked), 0o700)
        os.rename(os.path.join(approved, linked), os.path.join(self.base, "moved"))
        os.symlink(os.path.join(self.base, "moved"), os.path.join(approved, linked))
        # a loose mode
        os.chmod(os.path.join(open_folder(loose), "plan.txt"), 0o440)
        # an extra file, a missing file
        with open(os.path.join(open_folder(extra), "extra.txt"), "w") as f:
            f.write("x")
        os.remove(os.path.join(open_folder(missing), "summary.txt"))
        # a changed byte in an approved copy
        path = os.path.join(open_folder(changed), "allow.txt")
        os.chmod(path, 0o600)
        with open(path, "a") as f:
            f.write("evil.example\n")
        os.chmod(path, 0o400)
        # a stored fingerprint rewritten (the digest covers it)
        path = os.path.join(open_folder(forged), "fingerprint")
        os.chmod(path, 0o600)
        with open(path, "w") as f:
            f.write("0" * 64 + "\n")
        os.chmod(path, 0o400)
        self.assertEqual(crawlbooks.approved_digests(self.index), {good})

    def test_an_approval_made_for_earlier_code_still_counts_because_the_book_was_found_by_it(self):
        digest = self.approve()
        with open(os.path.join(self.kb, "a.py"), "a") as f:
            f.write("# the code changed since")
        self.assertEqual(crawlbooks.approved_digests(self.index), {digest})

    def test_a_loose_or_linked_approved_folder_or_crawl_folder_lists_nothing(self):
        digest = self.approve()
        approved = os.path.join(self.index, "crawl", "approved")
        os.chmod(approved, 0o777)
        self.assertEqual(crawlbooks.approved_digests(self.index), set())
        os.chmod(approved, 0o700)
        self.assertEqual(crawlbooks.approved_digests(self.index), {digest})
        os.rename(os.path.join(self.index, "crawl"), os.path.join(self.base, "crawl-moved"))
        os.symlink(os.path.join(self.base, "crawl-moved"), os.path.join(self.index, "crawl"))
        self.assertEqual(crawlbooks.approved_digests(self.index), set())

    def test_a_name_in_the_approved_folder_that_is_not_a_digest_is_ignored(self):
        digest = self.approve()
        approved = os.path.join(self.index, "crawl", "approved")
        os.chmod(approved, 0o700)
        os.mkdir(os.path.join(approved, "not-a-digest"))
        os.mkdir(os.path.join(approved, ".new-abc"))
        self.assertEqual(crawlbooks.approved_digests(self.index), {digest})


class Reconcile(Case):
    def test_an_unapproved_book_gets_one_unplaced_event_and_one_log_line_and_a_second_call_writes_nothing(self):
        digest = self.approve()
        stranger = self.found("e" * 32)
        mine = self.found(digest)
        log = crawllog.Log(self.index, "run-1", clock=lambda: NOW)
        self.assertEqual(crawlbooks.reconcile_unapproved(self.store, {digest}, log), [stranger])
        self.assertEqual(self.names(stranger), ["crawl_found", "crawl_unplaced"])
        self.assertIn("approved", self.events(stranger)[1]["reason"])
        self.assertEqual(self.names(mine), ["crawl_found"])
        self.assertEqual(self.store.read_book(stranger)["state"], "active")
        self.assertEqual(self.store.read_book(stranger)["shelf"], "default")
        lines = [json.loads(l) for l in open(os.path.join(self.index, "crawl", "log", "crawl-2026-11-16.jsonl"))]
        self.assertEqual([(l["step"], l["outcome"], l["book"]) for l in lines], [("move", "refused", stranger)])
        self.assertEqual(crawlbooks.reconcile_unapproved(self.store, {digest}, log), [])
        self.assertEqual(self.names(stranger), ["crawl_found", "crawl_unplaced"])
        self.assertEqual(len(open(os.path.join(self.index, "crawl", "log", "crawl-2026-11-16.jsonl")).read().splitlines()), 1)

    def test_it_calls_no_model_no_move_no_proposal_and_no_capture(self):
        for name in ("models", "capture_url", "capture_arxiv", "placement", "placereview", "placeapply", "webclient", "subprocess", "socket", "urllib"):
            self.assertNotIn(name, vars(crawlbooks), name)
        with open(os.path.join(ENGINE_DIR, "kb", "crawlbooks.py"), encoding="utf-8") as f:
            source = f.read()
        for word in ("set_shelf", "embed(", "capture(", "propose(", "DELETE", "os.environ"):
            self.assertNotIn(word, source, word)
        stranger = self.found("e" * 32)
        before = self.store.read_book(stranger)
        with mock.patch.object(self.store, "set_shelf", side_effect=AssertionError("no move")):
            crawlbooks.reconcile_unapproved(self.store, set(), crawllog.Log(self.index, "run-1", clock=lambda: NOW))
        self.assertEqual(self.store.read_book(stranger), before)

    def test_a_log_that_cannot_take_the_line_ends_it_with_an_error_after_the_event_is_written_once(self):
        stranger = self.found("e" * 32)
        os.makedirs(os.path.join(self.index, "crawl", "log"), mode=0o700)
        os.chmod(os.path.join(self.index, "crawl", "log"), 0o500)
        with self.assertRaises(KbError):
            crawlbooks.reconcile_unapproved(self.store, set(), crawllog.Log(self.index, "run-1", clock=lambda: NOW))
        self.assertEqual(self.names(stranger), ["crawl_found", "crawl_unplaced"])


class Rows(Case):
    """`crawlstate.reject_kept` and the required `filed` of `reserve` (this increment's changes to the state module)."""

    def conn(self):
        from kb import crawlqueue
        conn = crawlqueue.connect(self.index)
        self.addCleanup(conn.close)
        return conn

    def row(self, conn, status, domain="a.example"):
        conn.execute("INSERT INTO candidates(identity_key, address, source, domain, status, added, updated) VALUES (?,?,?,?,?,?,?)",
                     (f"k-{status}-{domain}", f"https://{domain}/", "openalex", domain, status, "2026-11-16T10:00:00Z", "2026-11-16T10:00:00Z"))
        return conn.execute("SELECT id FROM candidates WHERE identity_key = ?", (f"k-{status}-{domain}",)).fetchone()[0]

    def test_a_kept_candidate_can_become_rejected_with_a_reason_and_only_that(self):
        conn = self.conn()
        ident = self.row(conn, "kept")
        crawlstate.reject_kept(conn, self.plan, ident, "below the threshold", NOW)
        got = conn.execute("SELECT status, reason, updated FROM candidates WHERE id = ?", (ident,)).fetchone()
        self.assertEqual(got, ("rejected", "below the threshold", "2026-11-16T12:00:00Z"))
        for status in ("queued", "fetching", "rejected", "failed", "blocked"):
            other = self.row(conn, status, domain=f"{status}.example")
            with self.assertRaises(KbError):
                crawlstate.reject_kept(conn, self.plan, other, "x", NOW)
            self.assertEqual(conn.execute("SELECT status FROM candidates WHERE id = ?", (other,)).fetchone()[0], status)
        for bad in (99999, None, True, "1"):
            with self.assertRaises(KbError):
                crawlstate.reject_kept(conn, self.plan, bad, "x", NOW)
        with self.assertRaises(KbError):
            crawlstate.reject_kept(conn, self.plan, ident, "x", datetime.datetime(2026, 11, 16, 12))
        fresh = self.row(conn, "kept", domain="fresh.example")
        for bad in (None, {}, dict(self.plan, retries=0)):
            with self.assertRaises(KbError):
                crawlstate.reject_kept(conn, bad, fresh, "x", NOW)
        self.assertEqual(conn.execute("SELECT status FROM candidates WHERE id = ?", (fresh,)).fetchone()[0], "kept")

    def test_the_reason_is_cleaned_and_the_state_module_still_has_no_delete(self):
        conn = self.conn()
        ident = self.row(conn, "kept")
        crawlstate.reject_kept(conn, self.plan, ident, "a\x1b[0m" + "q " * 400, NOW)
        reason = conn.execute("SELECT reason FROM candidates WHERE id = ?", (ident,)).fetchone()[0]
        self.assertLessEqual(len(reason), 300)
        self.assertNotIn("\x1b", reason)
        with open(os.path.join(ENGINE_DIR, "kb", "crawlstate.py"), encoding="utf-8") as f:
            self.assertNotIn("DELETE", f.read())

    def test_reserve_needs_to_be_told_how_many_books_are_filed(self):
        conn = self.conn()
        self.row(conn, "queued")
        with self.assertRaises(TypeError):
            crawlstate.reserve(conn, self.plan, NOW, "run-1")
        for bad in (None, -1, True, "5", 1.5):
            with self.assertRaises(KbError):
                crawlstate.reserve(conn, self.plan, NOW, "run-1", bad)
        row, why = crawlstate.reserve(conn, self.plan, NOW, "run-1", 0)
        self.assertEqual(why, "")
        self.assertEqual(row["status"], "fetching")


if __name__ == "__main__":
    unittest.main()
