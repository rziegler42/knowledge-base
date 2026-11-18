"""The whole chain of the unattended crawl (`kb/crawlrun.py`, Increment M of the plan `2026-11-16-run-the-steps-of-the-unattended-crawl`).

Each step has its own tests. These tests run the steps **together**, as `crawlrun.run` assembles them (`crawlrun.default_steps`), on one temporary library with every outside thing faked: the pages come from the fake
server of `test_webclient` through the real shared client and the real capture, the lists from the fake downloader of `test_crawllists`, the scan, the converter and the index are fakes that file what the real ones
file, the embedding and chat models are the fake hooks of `test_placement`, and the clock and the free space are injected. The scan, the convert, the index, the judgement, the proposal and the move are the real
steps; **the card step is a small fake step** (`Chain.card_step`) that files a card the way `test_placement` does, because the real card queue runs its own launcher and models, which cannot be put in the same library
with the placement hooks (a test shows that the registry uses `crawlcards.step` for the cards, and calls it with the books that were judged in). No request leaves the machine (the tests dial a loopback server) and no model call is made; nothing reads the owner's config,
plan, key, library or shelves, or sleeps. Run them with
`python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlchain`."""
import contextlib
import copy
import datetime
import json
import os
import re
import types
import unittest
from unittest import mock
from urllib.parse import urlsplit

from engine.tests import ENGINE_DIR  # noqa: F401  (puts the engine folder on the import path)
from engine.tests.test_card import MODEL
from engine.tests.test_crawllists import PHISH_URL, PSL_URL, Fetch, hosts
from engine.tests.test_crawlsteps import FakeIndex, FakeScan
from engine.tests.test_discover import Source
from engine.tests.test_placement import LONG, PlaceCase
from engine.tests.test_webclient import Net, reply

from kb import card, crawlapprove, crawlplan, crawlreport, crawlstatus, crawlbooks, crawlcards, crawlguard, crawllists, crawllog, crawlmove, crawlqueue, crawlrefill, crawlrun, crawlstate, crawlsteps, crawlfetch, crawlidle, stages, store, weblists
from kb import capture_url

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 16, 12, 0, 0, tzinfo=UTC)
PLAN_TEXT = """[limits]
batch = 4
fetches_per_day = 20
filed_total = 50
per_domain_per_day = 50
cards_per_day = 10
retries = 3
timezone = UTC
[pacing]
min_gap_s = 0
jitter = 0
[breaker]
consecutive_failures = 3
model_down_minutes = 30
[judge]
threshold = 0.9
min_chars = 400
"""
TOPICS = "[core weight=10]\nverification\n"
PSL = b"com\norg\nco.uk\ntest\nexample\n"
CHAIN_STEPS = ("capture", "fetch", "scan", "hold", "convert", "index", "judge", "card", "propose", "move")
PROSE = ("The controller keeps the plant stable when the load changes, and the text explains how the gain is chosen. "
         "A worked example follows, with the limits of the method and the cases where it fails. "
         "The last part compares the method with two older ones and says when each is the better choice. ")


class Boom(BaseException):
    """A death of the process, injected where a test says (the way `test_crawlfetch` does)."""


def roomy(path):
    return types.SimpleNamespace(f_bavail=10**9, f_frsize=4096)


def short(path):
    return types.SimpleNamespace(f_bavail=1, f_frsize=4096)


def page(title, body=PROSE * 2):
    paragraphs = "".join(f"<p>{sentence.strip()}.</p>" for sentence in body.split(".") if sentence.strip())
    return f"<html><head><title>{title}</title></head><body>{paragraphs}</body></html>".encode()


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f.read().splitlines()]


class Chain(PlaceCase, Net):
    """One temporary library with its index, the shelf vectors of the fixture schema, a fake page server, an approved plan and the fakes of every step; `go()` makes one run of the assembled steps."""

    plan_text = PLAN_TEXT

    def setUp(self):
        super().setUp()                                                   # the library, the schema, the shelf vectors and the hooks of `PlaceCase`
        Net.setUp(self)                                                   # the fake resolver and the fake page server
        self.addCleanup(os.umask, os.umask(0o077))
        self.ticks = 0
        for patcher in (mock.patch("kb.store.now", self.tick), mock.patch.object(crawlrun.crawlguard, "probe_model", self.probe),
                        mock.patch.object(__import__("kb.shelfvectors", fromlist=["x"]), "DEFAULT_SCHEMA", self.schema_path),
                        mock.patch.dict(weblists.MIN_ENTRIES, {"phishing_domains": 1, "public_suffix": 1})):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.cfg_crawl = dict(self.cfg_models, index_root=self.index, bulk_root=self.bulk)
        self.kb_tree = os.path.join(self.base, "kbtree")
        self.prefix = os.path.join(self.base, "pyc")
        self.files = os.path.join(self.base, "files")
        for folder in (self.kb_tree, self.files):
            os.makedirs(folder)
        os.mkdir(self.prefix, 0o700)
        with open(os.path.join(self.kb_tree, "a.py"), "w") as f:
            f.write("print(1)\n")
        self.now = NOW
        self.up, self.probes = True, 0
        self.order = []                                                   # (step, book) in the order the fakes were called
        self.scan_kinds, self.scan_status, self.weak, self.found_rows = {}, {}, set(), 0
        self.lists = Fetch()
        self.sources = {"openalex": Source("openalex"), "arxiv": Source("arxiv"), "wikipedia": Source("wikipedia"), "web_search": Source("web")}
        self.lists.replies[PHISH_URL] = (200, {}, hosts("bad1.example", "bad2.example"))
        self.lists.replies[PSL_URL] = (200, {}, PSL)
        self.hooks = {}                                                   # a name -> a function called at that point of a fake (a stop file made, a death injected)
        self.reserved = []
        self.set_plan(self.plan_text)

    # -- the plan and the run
    def tick(self):
        self.ticks += 1
        return (NOW + datetime.timedelta(seconds=self.ticks)).isoformat(timespec="seconds")

    def probe(self, cfg=None, task=None):
        self.probes += 1
        return self.up

    def put(self, name, text):
        path = os.path.join(self.files, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(path, 0o600)
        return path

    def set_plan(self, text):
        topics, allow = self.put("topics.txt", TOPICS), self.put("allow.txt", "")
        self.plan_path = self.put("plan.txt", text + f"[files]\ntopics = {topics}\nallow = {allow}\nblacklist = {os.path.join(self.files, 'black.txt')}\n")
        digest = crawlapprove.approve(self.index, self.cfg_crawl, self.plan_path, kb_root=self.kb_tree)[1]
        crawlapprove.approve(self.index, self.cfg_crawl, self.plan_path, digest=digest, kb_root=self.kb_tree, is_tty=lambda: True, say=lambda s: None, now=NOW)
        self.digest = crawlapprove.load_approved(self.index, self.cfg_crawl, kb_root=self.kb_tree)["digest"]
        self.plan = crawlapprove.load_approved(self.index, self.cfg_crawl, kb_root=self.kb_tree)["plan"]

    def steps(self, without=(), **over):
        """The assembled steps with the fakes: the lists, the refill, the fetch, the scan, the convert, the judge and the move are the real steps. `without` leaves a part to the registry's own."""
        parts = {
            "lists": crawllists.make_step(fetch=self.lists, key_path=os.path.join(self.files, "no.key")).__call__,
            "refill": crawlrefill.make_step(fetch=self.lists, sources=self.sources),
            "fetch": crawlfetch.make_step(capture=self.capture, statvfs=roomy),
            "scan": crawlsteps.make_scan_step(scan=self.scan, statvfs=roomy),
            "convert": crawlsteps.make_convert_step(convert=self.convert, index=self.index_fake, statvfs=roomy),
            "judge": crawlsteps.make_judge_step(embed=self.embed_hooked, statvfs=roomy, probe=self.probe),
            "cards": self.card_step,
            "move": crawlmove.make_step(statvfs=roomy, probe=self.probe, embed=self.embed_hooked, call=self.call_hooked, schema_path=self.schema_path),
            "idle": crawlidle.make_step(statvfs=roomy),
        }
        real_lists = parts["lists"]

        def lists(ctx):
            self.ctx = ctx                                                        # the context of the run, for a test that spends the time budget from inside it
            return real_lists(ctx)

        parts["lists"] = lists
        parts.update(over)
        for name in without:
            del parts[name]
        return crawlrun.default_steps(parts)

    def go(self, now=None, steps=None, dry_run=False, probe=None, statvfs=None, prefix=None):
        if now is not None:
            self.now = now
        self.out, self.err = [], []
        return crawlrun.run(self.cfg_crawl, dry_run=dry_run, now=self.now, say=self.out.append, warn=self.err.append, kb_root=self.kb_tree, statvfs=statvfs or roomy, probe=probe or self.probe,
                            steps=None if dry_run else (steps if steps is not None else self.steps()), pycache_prefix=prefix or self.prefix)

    def later(self, **delta):
        self.now = self.now + datetime.timedelta(**delta)
        return self.now

    # -- the hooks and the fakes
    def hook(self, name, *args):
        if name in self.hooks:
            self.hooks[name](*args)

    def once(self, name, action):
        """`action` the first time the fake named `name` is reached, and no more."""
        def run_once(*args):
            self.hooks.pop(name, None)
            action(*args)
        self.hooks[name] = run_once

    def die_at(self, name):
        def die(*args):
            raise Boom(name)
        self.once(name, die)

    def spend(self, *args):
        self.ctx.deadline = self.ctx.clock()

    def stop_file(self, *args):
        with open(os.path.join(self.index, "crawl.stop"), "w"):
            pass

    def remove_stop_file(self):
        os.unlink(os.path.join(self.index, "crawl.stop"))

    def capture(self, library, ident, address, **kw):
        result = capture_url.capture(library, ident, address, **kw)
        self.order.append(("capture", result["book_id"]))
        self.hook("capture", result)
        return result

    def scan(self, library, book, version):
        self.order.append(("scan", book))
        path = urlsplit(library.read_book(book)["identity_keys"]["url"]).path                    # (the title is not known before the convert)
        out = FakeScan(self.scan_kinds.get(path, []), status=self.scan_status.get(path, "done"))(library, book, version)
        self.hook("scan", book)
        return out

    def convert(self, library, book, version):
        """What the real converter files: the text of the captured page, as the blocks of a conversion record."""
        self.order.append(("convert", book))
        original = library.payload_path(book, version, "original")
        name = [n for n in os.listdir(original) if n.endswith((".html", ".pdf"))][0]            # (a PDF of the fixtures holds the same page after its binary head)
        with open(os.path.join(original, name), encoding="utf-8", errors="replace") as f:
            html = f.read()
        blocks = [{"kind": "paragraph", "level": None, "text": text} for text in re.findall(r"<p>(.*?)</p>", html, re.S)]
        title = re.search(r"<title>(.*?)</title>", html, re.S).group(1)
        raw = json.dumps({"format": 1, "truncated": False, "blocks": blocks, "title": title}).encode()
        library.file_payload(book, version, "derived/kb-chain/1", {"blocks.json": raw}, tool="kb-chain 1", untrusted=True)
        record = {"tool": "kb-chain", "version": "1", "generation": 1, "payload": "derived/kb-chain/1", "parse": "blocks-json", "quality": "full", "blocks": len(blocks),
                  "chars": sum(len(b["text"]) for b in blocks), "pages": None, "truncated": False}
        check = {"rule": "r", "compared": False, "partial": False, "reasons": [], "ratio": 1.0, "chars": {}, "notes": {}}
        library.set_version_conversions(book, version, [record], {k: record[k] for k in ("tool", "version", "generation")}, check)
        library.set_metadata(book, title=title, metadata_source=version)          # the real converter takes the page's title for the book (`convert._take_title`)
        stages.mark(library, book, version, "converted", "done", tool="kb-chain 1")
        self.hook("convert", book)
        return {"status": "done"}

    def index_fake(self, library, book, version):
        self.order.append(("index", book))
        out = FakeIndex()(library, book, version)
        self.hook("index", book)
        return out

    def far_vector(self):
        """A vector that is far from every shelf, so that its best match is under the plan's threshold."""
        return [-x for x in self.vector_of("additive")]

    def embed_hooked(self, cfg, name, texts, launcher=None, root=None, kind="document"):
        self.order.append(("embed", tuple(texts)))
        self.hook("embed", texts)
        out = self.embed(cfg, name, texts, launcher=launcher, root=root, kind=kind)
        if kind == "document":
            out["vectors"] = [self.far_vector() if any(t.startswith(w) for w in self.weak) else v for t, v in zip(texts, out["vectors"])]
        return out

    def call_hooked(self, cfg, name, prompt, launcher=None, root=None, schema=None):
        self.order.append(("chat", prompt))
        self.hook("chat", prompt)
        return self.call(cfg, name, prompt, launcher=launcher, root=root, schema=schema)

    def card_step(self, ctx):
        """THE FAKE CARD STEP: the judged-in crawl books with no card get one, within `cards_per_day`, looking at the stop file before each; it files the card the way `test_placement` does."""
        library = store.Store.open()
        scan = crawlbooks.scan_crawl_books(library)
        for book in crawlbooks.crawl_books(library, crawlbooks.approved_digests(ctx.index_root), scan):
            entry = next(e for e in scan.entries if e["id"] == book)
            version = library.read_book(book)["current_version"]
            if not any(x.get("event") == "crawl_judged" and x.get("ok") is True for x in entry["events"] if isinstance(x, dict)) or card.generations(library, book, version):
                continue
            if crawlguard.stop_requested(ctx.index_root) or crawlrun.spent(ctx):
                return
            if not crawlstate.reserve_card(ctx.conn, ctx.plan, ctx.clock()):
                ctx.log.write("card", "skipped", reason="cards_per_day reached", now=ctx.clock())
                return
            self.order.append(("card", book))
            card.file(library, card.make(library, book, version, model=dict(copy.deepcopy(MODEL), summary=LONG, topics=["topic one", "topic two"]), records=[]))
            self.hook("card", book)
            ctx.log.write("card", "ok", book=book, now=ctx.clock())

    # -- the fixture
    def host_dns(self, host):
        self.dns.setdefault(host, ["93.184.216.34"])

    def add(self, path, host="a.test", source="openalex", title=None, target="additive", text=None, route=True, resolves=True, topic="verification", weight=1):
        """A queued candidate whose page the fake server serves: the page's title is the book's title, and `target` is the shelf its text is close to."""
        self.found_rows += 1
        if resolves:
            self.host_dns(host)
        title = title or f"Chain book {self.found_rows}"
        if route:
            self.srv.routes[path] = reply(200, body=page(title, text or PROSE * 2))
        self.targets[title] = target
        address = f"http://{host}{path}"
        stamp = f"2026-11-16T10:{self.found_rows // 60:02d}:{self.found_rows % 60:02d}Z"
        site = host.split(".", 1)[1] if host.count(".") > 1 else host
        conn = crawlqueue.connect(self.index)
        try:
            conn.execute("INSERT INTO candidates(identity_key, address, source, found_from, topic, domain, weight, status, added, updated) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (address, address, source, "openalex:W1", topic, site, weight, "queued", stamp, stamp))
            conn.commit()
            return conn.execute("SELECT id FROM candidates WHERE identity_key = ?", (address,)).fetchone()[0], title
        finally:
            conn.close()

    # -- what a test reads

    def trace(self, run=None):
        """`[(step, book)]` of the lines of the chain, in the order the log has them (all runs, or one)."""
        return [(l["step"], l["book"]) for l in self.lines() if l["step"] in CHAIN_STEPS and l["book"] and l["outcome"] in ("ok", "held", "rejected") and (run is None or l["run"] == run)]

    def conn(self):
        conn = crawlqueue.connect(self.index)
        self.addCleanup(conn.close)
        return conn

    def used(self):
        return crawlstate.ceilings(self.conn(), self.plan, self.now)

    def assert_within_ceilings(self):
        used = self.used()
        for key in ("fetch", "card"):
            self.assertLessEqual(used[key][0], used[key][1], key)
        self.assertLessEqual(crawlbooks.filed_count(self.store), self.plan["filed_total"])
        per_run = {}
        for line in self.lines():
            if line["step"] == "fetch" and line["outcome"] == "ok":
                per_run[line["run"]] = per_run.get(line["run"], 0) + 1
        self.assertTrue(all(n <= self.plan["batch"] for n in per_run.values()), per_run)

    def assert_nothing_half_made(self):
        rows = {r["book_id"]: r for r in self.rows() if r["book_id"]}
        for book in self.crawl_books_all():
            root, names = self.store.read_book(book), self.names(book)
            if root["state"] == "active":
                self.assertIn("crawl_found", names, f"an active crawl book with no crawl_found: {names}")
            else:
                self.assertTrue({"crawl_rejected", "crawl_held", "capture_failed"} & set(names), f"a weeded book with no reason: {names}")
                if "crawl_rejected" in names:                                       # a held book keeps its row `kept` (a book exists: spec, the queue's statuses); a rejected one does not
                    self.assertNotEqual(rows.get(book, {}).get("status"), "kept", "a rejected book with a kept row")
        for row in self.rows():
            if row["status"] == "kept":
                names = self.names(row["book_id"])
                self.assertTrue(self.store.read_book(row["book_id"])["state"] == "active" or "crawl_held" in names, f"a kept row of a weeded book that is not held: {names}")
    def lines(self):
        folder = os.path.join(self.index, "crawl", "log")
        out = []
        if os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                out += jsonl(os.path.join(folder, name))
        return out

    def last_run(self):
        return [l for l in self.lines() if l["run"] == self.lines()[-1]["run"]]

    def rows(self):
        conn = crawlqueue.connect(self.index)
        try:
            cur = conn.execute("SELECT * FROM candidates ORDER BY id")
            return [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
        finally:
            conn.close()

    def row(self, ident):
        return next(r for r in self.rows() if r["id"] == ident)

    def counters(self):
        conn = crawlqueue.connect(self.index)
        try:
            return dict(((day, key), n) for day, key, n in conn.execute("SELECT day, key, n FROM counters"))
        finally:
            conn.close()

    def book_of(self, ident):
        return self.row(ident)["book_id"]

    def events(self, book, name=None):
        found = [e for e in self.store.read_events(book) if isinstance(e, dict)]
        return [e for e in found if name is None or e.get("event") == name]

    def names(self, book):
        return [e["event"] for e in self.events(book)]

    def shelf(self, book):
        return self.store.read_book(book)["shelf"]

    def crawl_books_all(self):
        return [b for b in self.store.list_books() if self.store.read_book(b).get("auto_filed") is True]

    def requests(self):
        return [path for path, _headers in self.srv.hits]


class TheTopicsInTurn(Chain):
    """The fetches of a run go to the topics in turn, and the turns are kept from one run to the next."""

    def test_the_runs_of_the_chain_spread_their_fetches_over_the_topics_and_keep_the_turns_from_one_run_to_the_next(self):
        rows = {}
        for topic in ("alpha", "beta", "gamma", "delta"):
            rows[topic] = [self.add(f"/{topic}{n}", host=f"{topic}{n}.test", topic=topic, weight=10)[0] for n in range(6)]

        def tried():
            return {t: sum(1 for i in ids if self.row(i)["tries"] > 0) for t, ids in rows.items()}

        self.assertEqual(self.go(), 0)
        first = tried()
        self.assertGreater(sum(first.values()), 0)
        self.assertLessEqual(max(first.values()) - min(first.values()), 1)                     # the first run did not finish one topic before the next
        self.assertGreater(min(first.values()), 0)                                             # and every topic had its turn
        self.assertEqual(self.go(), 0)
        second = tried()
        self.assertGreater(sum(second.values()), sum(first.values()))
        self.assertLessEqual(max(second.values()) - min(second.values()), 1)                   # the turns went on where the first run left them


class WholeChain(Chain):
    def test_a_fixture_candidate_is_taken_by_one_run_through_fetch_scan_convert_index_judge_card_proposal_and_move(self):
        ident, title = self.add("/p1", target="gene-editing")
        self.assertEqual(self.go(), 0)
        book = self.book_of(ident)
        root = self.store.read_book(book)
        self.assertEqual((root["auto_filed"], root["state"], root["title"]), (True, "active", title))
        (found,) = self.events(book, "crawl_found")
        self.assertEqual((found["candidate"], found["plan_digest"], found["run"]), (ident, self.digest, self.last_run()[0]["run"]))
        (judged,) = self.events(book, "crawl_judged")
        self.assertTrue(judged["ok"])
        self.assertTrue(card.generations(self.store, book, root["current_version"]))
        (proposal,) = self.events(book, "placement_proposed")
        (moved,) = self.events(book, "reshelved")
        self.assertEqual((moved["from"], moved["to"], moved["action"], moved["basis"], moved["via"]), ("default", proposal["answer"]["chosen"], "move", "model-pick", "crawl"))
        self.assertEqual((moved["run"], moved["plan_digest"]), (found["run"], self.digest))
        self.assertNotIn("confirmation", moved)
        self.assertEqual(self.shelf(book), moved["to"])
        self.assertNotEqual(self.shelf(book), "default")
        self.assertEqual((self.row(ident)["status"], self.row(ident)["book_id"]), ("kept", book))
        self.assertEqual(self.requests().count("/p1"), 1)

    def test_every_step_has_its_log_line_in_the_order_of_the_run_and_the_run_ends_with_its_line(self):
        ident, _title = self.add("/p1", target="gene-editing")
        self.assertEqual(self.go(), 0)
        book = self.book_of(ident)
        lines = self.lines()
        self.assertEqual([l["step"] for l in lines if l["book"] == book and l["step"] in CHAIN_STEPS], ["capture", "fetch", "scan", "convert", "index", "judge", "card", "propose", "move"])
        self.assertEqual([l["outcome"] for l in lines if l["book"] == book and l["step"] in CHAIN_STEPS], ["ok"] * 9)
        points = [l["reason"] for l in lines if l["step"] == "stop"]
        self.assertEqual(points, ["no stop file at lists", "no stop file at earlier_work", "no stop file at refill", "no stop file at fetch", "no stop file at idle"])
        self.assertEqual([(l["outcome"], l["reason"]) for l in lines if l["step"] == "idle"], [("skipped", "settings")])   # this library has no model set for themes: the window ends quietly
        self.assertEqual((lines[0]["step"], lines[-1]["step"], lines[-1]["outcome"], lines[-1]["reason"]), ("run_start", "run_end", "ok", "done"))
        self.assertEqual({l["run"] for l in lines}, {lines[0]["run"]})

    def test_the_page_is_fetched_by_the_real_client_once_and_the_book_holds_what_the_page_said(self):
        ident, title = self.add("/p1")
        self.go()
        book = self.book_of(ident)
        self.assertEqual(self.requests(), ["/p1"])
        self.assertEqual(self.store.read_book(book)["identity_keys"]["url"], "http://a.test/p1")
        self.assertEqual(self.store.read_book(book)["title"], title)


def readable(pgid):
    return 0


def pdf_of(title, body=PROSE * 2):
    """A stand-in for a PDF: it begins as one, has binary bytes in its head (as a real one does), and holds the text of a page that the fake converter reads."""
    return b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n\x00\x01 binary\n" + page(title, body) + b"\n%%EOF\n"


class PdfChain(Chain):
    """With `pdf_max_mb` above 0 a PDF is a book that goes through the whole chain, scanned before it is converted; the scan, the converter and the index are the chain's fakes (the real tools are not run here)."""

    plan_text = PLAN_TEXT + "[pdf]\npdf_max_mb = 5\n"

    def steps(self, without=(), **over):
        over.setdefault("fetch", crawlfetch.make_step(capture=self.capture, statvfs=roomy, rss_reader=readable))
        over.setdefault("refill", crawlrefill.make_step(fetch=self.lists, sources=self.sources, rss_reader=readable))
        return super().steps(without, **over)

    def add_pdf(self, path="/paper.pdf", **kw):
        ident, title = self.add(path, route=False, **kw)
        self.srv.routes[path] = reply(200, body=pdf_of(title), ctype="application/pdf")
        return ident, title

    def test_a_pdf_candidate_goes_through_fetch_scan_convert_index_judge_card_and_move_and_the_log_and_the_queue_compare_the_same(self):
        ident, title = self.add_pdf(target="gene-editing")
        self.assertEqual(self.go(), 0)
        book = self.book_of(ident)
        root = self.store.read_book(book)
        version = root["current_version"]
        self.assertEqual((root["auto_filed"], root["kind"], root["state"], root["title"]), (True, "paper", "active", title))
        self.assertEqual(self.store.read_version(book, version)["primary"], "paper.pdf")
        (judged,) = self.events(book, "crawl_judged")
        self.assertTrue(judged["ok"])
        self.assertTrue(card.generations(self.store, book, version))
        self.assertEqual(len(self.events(book, "reshelved")), 1)
        self.assertEqual((self.row(ident)["status"], self.row(ident)["book_id"]), ("kept", book))
        self.assertEqual([step for step, b in self.order if b == book][:3], ["capture", "scan", "convert"])
        data = crawlreport.build(self.index, datetime.date(2026, 11, 16), "UTC", self.now, store=store.Store.open(write=False))
        self.assertTrue(all(c["same"] for c in data["compare"]), data["compare"])

    def test_a_pdf_that_the_scan_flags_is_held_and_never_converted_or_indexed(self):
        ident, _ = self.add_pdf()
        self.scan_kinds["/paper.pdf"] = ["javascript"]
        self.assertEqual(self.go(), 0)
        book = self.book_of(ident)
        self.assertIn("crawl_held", self.names(book))
        self.assertEqual([step for step, b in self.order if b == book], ["capture", "scan"])
        self.assertEqual(self.events(book, "crawl_judged"), [])

    def test_a_pdf_and_a_page_in_one_run_each_take_their_own_way(self):
        pdf, _ = self.add_pdf("/paper.pdf", target="gene-editing")
        page_ident, _ = self.add("/p2", target="additive")
        self.assertEqual(self.go(), 0)
        files = [self.store.read_version(self.book_of(i), self.store.read_book(self.book_of(i))["current_version"])["primary"] for i in (pdf, page_ident)]
        self.assertEqual(sorted(files), ["page.html", "paper.pdf"])
        self.assertEqual(sorted(self.row(i)["status"] for i in (pdf, page_ident)), ["kept", "kept"])


class PdfOffChain(Chain):
    """The default plan (no `[pdf]` section): a candidate that is a PDF is rejected without a request, as before."""

    def test_a_pdf_candidate_is_rejected_for_its_type_with_no_request_and_no_book(self):
        ident, _ = self.add("/paper.pdf", route=False)
        self.srv.routes["/paper.pdf"] = reply(200, body=pdf_of("x"), ctype="application/pdf")
        self.assertEqual(self.go(), 0)
        self.assertEqual((self.row(ident)["status"], self.row(ident)["reason"]), ("rejected", "pdf not safe to convert"))
        self.assertNotIn("/paper.pdf", self.requests())
        self.assertEqual(self.crawl_books_all(), [])


class TheOrder(Chain):
    def test_two_candidates_are_fetched_in_one_run_and_each_goes_through_the_chain_in_that_run_a_step_at_a_time(self):
        a, _ = self.add("/pa", target="gene-editing")
        b, _ = self.add("/pb", target="gene-editing")
        self.assertEqual(self.go(), 0)
        books = [self.book_of(a), self.book_of(b)]
        self.assertEqual(self.trace()[:4], [("capture", books[0]), ("fetch", books[0]), ("capture", books[1]), ("fetch", books[1])])
        steps = [s for s, _b in self.trace()[4:]]
        self.assertEqual(steps, ["scan"] * 2 + ["convert", "index"] * 2 + ["judge"] * 2 + ["card"] * 2 + ["propose", "move", "propose", "move"])
        for step in ("scan", "judge", "card"):
            self.assertEqual([b for s, b in self.trace() if s == step], books, step)                                   # oldest first
        self.assertTrue(all(self.shelf(book) != "default" for book in books))
        self.assertEqual(sorted(self.requests()), ["/pa", "/pb"])

    def test_a_book_the_earlier_run_left_unfinished_is_taken_through_the_steps_it_has_not_had_before_the_refill_and_the_new_candidate(self):
        a, _ = self.add("/pa")
        self.once("convert", self.stop_file)                                            # the first run stops after the convert of the first book
        self.assertEqual(self.go(), 0)
        book_a = self.book_of(a)
        self.assertEqual([s for s, b in self.trace() if b == book_a], ["capture", "fetch", "scan", "convert"])                   # the stop is seen before the index write
        self.assertEqual(self.shelf(book_a), "default")
        self.remove_stop_file()
        b, _ = self.add("/pb")
        self.later(minutes=20)
        self.assertEqual(self.go(), 0)
        book_b = self.book_of(b)
        run = self.lines()[-1]["run"]
        second = self.trace(run)
        self.assertEqual(second[:5], [("index", book_a), ("judge", book_a), ("card", book_a), ("propose", book_a), ("move", book_a)])       # the earlier work comes first
        self.assertEqual([s for s, b in second if b == book_b], ["capture", "fetch", "scan", "convert", "index", "judge", "card", "propose", "move"])
        order = [l["step"] for l in self.lines() if l["run"] == run and l["step"] in ("move", "discover", "capture")]
        self.assertLess(order.index("move"), order.index("discover"))
        self.assertLess(order.index("discover"), order.index("capture"))
        self.assertEqual(self.requests(), ["/pa", "/pb"])

    def test_the_scan_is_made_before_the_convert_of_a_book_and_a_scan_step_is_never_after_a_convert_of_the_same_pass(self):
        a, _ = self.add("/pa")
        b, _ = self.add("/pb")
        self.go()
        kinds = [k for k, _b in self.order if k in ("scan", "convert")]
        self.assertEqual(kinds, ["scan", "scan", "convert", "convert"])


class Killed(Chain):
    """A run that is killed by an injected failure, and the next run on the same library (criterion 4)."""

    def kill_and_resume(self, point, action="move", arrange=None, finished_by_the_next_run=True):
        a, _ = self.add("/pa", target="gene-editing")
        b, _ = self.add("/pb", target="gene-editing")
        (arrange or (lambda: self.die_at(point)))()
        with self.assertRaises(Boom):
            self.go()
        crawlguard.acquire_run_lock(self.index, now=NOW).release()                      # the lock was let go: a run can take it
        self.assert_within_ceilings()
        self.later(minutes=31)                                                          # a row that was being fetched is stalled after thirty minutes
        self.assertEqual(self.go(), 0)
        self.assert_within_ceilings()
        if not finished_by_the_next_run:
            self.assert_the_book_of_the_dead_fetch_waits_for_its_retry(a)
            self.later(days=1)
            self.assertEqual(self.go(), 0)
            self.assert_within_ceilings()
        self.assert_nothing_half_made()
        books = [self.book_of(a), self.book_of(b)]
        for book in books:
            self.assertEqual(len(self.events(book, "crawl_found")), 1, self.names(book))
            self.assertEqual(len(self.events(book, "crawl_judged")), 1, self.names(book))
            self.assertEqual(len(self.events(book, "reshelved")), 1, self.names(book))
            self.assertNotEqual(self.shelf(book), "default")
            self.assertEqual(len(card.generations(self.store, book, self.store.read_book(book)["current_version"])), 1)
        self.assertEqual(sorted(self.requests()), ["/pa", "/pb"])                       # nothing was fetched twice
        self.assertEqual(self.events(books[0], "reshelved")[0]["action"], action)
        self.assertEqual([r["status"] for r in self.rows()], ["kept", "kept"])
        return books

    def assert_the_book_of_the_dead_fetch_waits_for_its_retry(self, ident):
        """What the plan's Result of G says: the book the dead run filed is an active orphan, counted by the ceiling, and its row is queued again with a wait, so the next run does not fetch it twice."""
        row = self.row(ident)
        self.assertEqual((row["status"], row["reason"], row["book_id"]), ("queued", "stalled for over 30 minutes", None))
        (orphan,) = [b for b in self.crawl_books_all() if "crawl_found" not in self.names(b)]
        self.assertEqual(self.store.read_book(orphan)["state"], "active")
        self.assertEqual(crawlbooks.filed_count(self.store), 2)
        self.assertEqual(self.requests().count("/pa"), 1)
        run = [l for l in self.lines() if l["run"] == self.lines()[-1]["run"]]
        sweep = [i for i, l in enumerate(run) if l["step"] == "fail"]
        self.assertEqual([(run[i]["outcome"], run[i]["reason"]) for i in sweep], [("ok", "1 stalled rows queued again, 0 given up")])
        self.assertLess(sweep[0], min(i for i, l in enumerate(run) if l["step"] == "list_update"))            # the stalled rows are queued again before the lists are refreshed

    def test_killed_in_the_fetch_after_the_capture_and_before_the_row_is_finished(self):
        self.kill_and_resume("capture", finished_by_the_next_run=False)

    def test_killed_in_the_scan(self):
        self.kill_and_resume("scan")

    def test_killed_in_the_convert(self):
        self.kill_and_resume("convert")

    def test_killed_in_the_index(self):
        self.kill_and_resume("index")

    def test_killed_in_the_judge_at_its_model_call(self):
        self.kill_and_resume("embed")

    def test_killed_in_the_card_after_the_card_is_filed(self):
        self.kill_and_resume("card")

    def test_killed_in_the_proposal_at_its_model_call(self):
        self.kill_and_resume("chat")

    def test_killed_in_the_move_after_the_shelf_is_set_and_before_the_line(self):
        real = store.Store.set_shelf
        dead = []

        def set_shelf(this, *a, **k):
            out = real(this, *a, **k)
            if not dead:
                dead.append(1)
                raise Boom("set_shelf")
            return out

        patch = mock.patch.object(store.Store, "set_shelf", set_shelf)
        self.addCleanup(patch.stop)
        self.kill_and_resume("move", action="record", arrange=patch.start)


def no_step(ctx):
    return None


class TheStopFile(Chain):
    """The stop file made in the middle of a batch (criterion 3): it prevents the next request, the next model call and the next move; the run ends with exit 0, and the next run (the file removed) goes on from there."""

    def stage(self, **late):
        """Two books taken up to the step before the one a test is about: the steps named in `late` do nothing in the first run."""
        self.a, _ = self.add("/pa", target="gene-editing")
        self.b, _ = self.add("/pb", target="gene-editing")
        self.assertEqual(self.go(steps=self.steps(**{name: no_step for name in late})), 0)
        self.later(minutes=20)
        self.books = [self.book_of(self.a), self.book_of(self.b)]

    def embedded_titles(self):
        return [t for kind, texts in self.order if kind == "embed" for t in texts]

    def test_a_stop_file_made_after_the_first_request_prevents_the_second_and_the_next_run_goes_on_with_nothing_fetched_twice(self):
        a, _ = self.add("/pa")
        b, _ = self.add("/pb")
        c, _ = self.add("/pc")
        self.once("capture", self.stop_file)
        self.assertEqual(self.go(), 0)
        self.assertEqual(self.requests(), ["/pa"])
        self.assertEqual([r["status"] for r in self.rows()], ["kept", "queued", "queued"])
        self.assertEqual([r["tries"] for r in self.rows()], [1, 0, 0])
        ended = [l for l in self.lines() if l["step"] == "fetch" and l["outcome"] == "skipped"]
        self.assertEqual([l["reason"] for l in ended], [crawlfetch.STOPPED])
        self.assertEqual([t for t in self.trace() if t[0] != "capture"], [("fetch", self.book_of(a))])                  # the chain did not begin after the stop
        self.assertEqual(self.lines()[-1]["step"], "run_end")
        self.remove_stop_file()
        self.later(minutes=20)
        self.assertEqual(self.go(), 0)
        self.assertEqual(sorted(self.requests()), ["/pa", "/pb", "/pc"])
        self.assertEqual([r["status"] for r in self.rows()], ["kept"] * 3)
        for book in (self.book_of(a), self.book_of(b), self.book_of(c)):
            self.assertEqual((len(self.events(book, "crawl_found")), len(self.events(book, "reshelved"))), (1, 1))
        self.assert_nothing_half_made()

    def test_a_stop_file_made_at_the_first_model_call_of_the_judge_prevents_the_next_model_call_and_the_next_run_judges_the_other_book(self):
        self.stage(judge=1, cards=1, move=1)
        self.once("embed", self.stop_file)
        self.assertEqual(self.go(), 0)
        embedded = self.embedded_titles()
        self.assertEqual(len(embedded), 1)                                              # one call, for the first book; none for the second
        self.assertTrue(embedded[0].startswith(self.store.read_book(self.books[0])["title"]))
        self.assertEqual([len(self.events(b, "crawl_judged")) for b in self.books], [1, 0])
        self.assertEqual(self.lines()[-1]["step"], "run_end")
        self.assertIn("the stop file is present at refill", [l["reason"] for l in self.lines() if l["step"] == "stop" and l["outcome"] == "refused"])
        self.assertEqual(self.lines()[-1]["reason"], "stopped by the stop file at refill")
        self.remove_stop_file()
        self.assertEqual(self.go(), 0)
        self.assertEqual([len(self.events(b, "crawl_judged")) for b in self.books], [1, 1])
        self.assertEqual(len([t for t in self.embedded_titles() if t.startswith(self.store.read_book(self.books[0])["title"] + "\n\n")]), 1)         # the first book is not judged again
        self.assertEqual([len(self.events(b, "reshelved")) for b in self.books], [1, 1])

    def test_a_stop_file_made_at_the_first_chat_call_of_the_proposal_prevents_the_next_model_call_and_the_move_of_that_book(self):
        self.stage(move=1)
        titles = [self.store.read_book(b)["title"] for b in self.books]
        self.once("chat", self.stop_file)
        before = len(self.embedded_titles())
        self.assertEqual(self.go(), 0)
        self.assertEqual(len([o for o in self.order if o[0] == "chat"]), 1)
        self.assertFalse([t for t in self.embedded_titles()[before:] if t.startswith(titles[1])])      # nothing about the second book was sent to a model
        self.assertEqual([len(self.events(b, "placement_proposed")) for b in self.books], [1, 0])
        self.assertEqual([self.shelf(b) for b in self.books], ["default", "default"])                  # the proposal that was asked for is kept, and not used after the stop
        self.assertEqual([len(self.events(b, "reshelved")) for b in self.books], [0, 0])
        self.remove_stop_file()
        self.assertEqual(self.go(), 0)
        self.assertEqual(len([o for o in self.order if o[0] == "chat"]), 2)                            # the first book's proposal was not asked for again
        self.assertEqual([len(self.events(b, "placement_proposed")) for b in self.books], [1, 1])
        self.assertEqual([len(self.events(b, "reshelved")) for b in self.books], [1, 1])

    def test_a_stop_file_made_when_the_first_book_is_moved_prevents_the_move_and_the_proposal_of_the_next_and_the_next_run_goes_on(self):
        self.stage(move=1)
        real = store.Store.set_shelf
        patch = mock.patch.object(store.Store, "set_shelf", lambda this, *a, **k: (real(this, *a, **k), self.stop_file())[0])
        with patch:
            self.assertEqual(self.go(), 0)
        first, second = self.books
        self.assertEqual((len(self.events(first, "reshelved")), self.shelf(first) != "default"), (1, True))             # the move that was going is finished and written down
        self.assertEqual((self.shelf(second), self.events(second, "placement_proposed"), self.events(second, "reshelved")), ("default", [], []))
        self.assertEqual(len([o for o in self.order if o[0] == "chat"]), 1)
        self.remove_stop_file()
        self.assertEqual(self.go(), 0)
        self.assertEqual([len(self.events(b, "reshelved")) for b in self.books], [1, 1])
        self.assertEqual([len(self.events(b, "placement_proposed")) for b in self.books], [1, 1])
        self.assertEqual(len([o for o in self.order if o[0] == "chat"]), 2)


class TheBreaker(Chain):
    def assert_tripped_then_refused_then_clear_goes_again(self, kind, up=True):
        breaker = crawlguard.read_breaker(self.index)
        self.assertEqual((breaker["tripped"], breaker["kind"]), (True, kind))
        with open(os.path.join(self.index, "crawl", "breaker.json"), encoding="utf-8") as f:
            self.assertTrue(json.load(f)["tripped"])
        before = len(self.lines())
        self.later(minutes=1)
        self.assertEqual(self.go(), 4)                                                  # refused while it is tripped, and nothing else is done
        new = self.lines()[before:]
        self.assertEqual([(l["step"], l["outcome"]) for l in new], [("refuse", "refused")])
        self.assertIn("circuit breaker is tripped", new[0]["reason"])
        crawlguard.clear(self.index, yes=True, is_tty=lambda: True, now=self.now)
        self.assertFalse(crawlguard.read_breaker(self.index)["tripped"])

    def test_failures_of_fetches_in_a_row_trip_it_the_next_run_is_refused_and_a_run_goes_again_only_after_the_clear(self):
        dead = [self.add(f"/dead{n}", host=f"dead{n}.test", route=False, resolves=False) for n in range(3)]
        good, _ = self.add("/good")
        self.assertEqual(self.go(), 4)
        self.assertEqual(self.lines()[-1]["outcome"], "tripped")
        self.assertEqual(self.requests(), [])                                           # the dead addresses never answered, and the good one was not tried in that run
        self.assertEqual([(r["status"], r["reason"], r["tries"]) for r in self.rows()][:3], [("queued", "the fetch failed", 1)] * 3)
        self.assertEqual(self.row(good)["tries"], 0)
        self.assert_tripped_then_refused_then_clear_goes_again("consecutive_failures")
        self.assertEqual(self.requests(), [])                                           # the refused run made no request either
        for n, (_ident, title) in enumerate(dead):                                      # the sites are back
            self.host_dns(f"dead{n}.test")
            self.srv.routes[f"/dead{n}"] = reply(200, body=page(title))
        self.later(hours=30)
        self.assertEqual(self.go(), 0)
        self.assertEqual([r["status"] for r in self.rows()], ["kept"] * 4)              # it goes again, and every page is taken
        self.assertEqual(sorted(self.requests()), ["/dead0", "/dead1", "/dead2", "/good"])

    def test_a_model_down_for_longer_than_the_limit_trips_it_and_a_run_goes_again_after_the_clear(self):
        ident, _ = self.add("/p1")
        self.up = False
        self.assertEqual(self.go(), 3)                                                  # the first run that finds it down is refused and starts the clock
        self.assertEqual(self.requests(), [])
        self.assertFalse(crawlguard.read_breaker(self.index)["tripped"])
        self.assertEqual(self.go(now=self.later(minutes=30)), 3)                       # down for exactly `model_down_minutes`: not yet longer than it
        self.assertFalse(crawlguard.read_breaker(self.index)["tripped"])
        self.assertEqual(self.go(now=self.later(minutes=1)), 4)                         # down for 31 minutes: longer than it
        self.assertEqual(self.requests(), [])
        self.assert_tripped_then_refused_then_clear_goes_again("model_down")
        self.up = True
        self.assertEqual(self.go(), 0)
        self.assertEqual(self.row(ident)["status"], "kept")

    def test_a_stage_that_hits_a_bound_trips_it_with_the_books_parked_and_a_run_goes_again_after_the_clear(self):
        self.set_plan(PLAN_TEXT.replace("retries = 3", "retries = 1"))                  # one failed try parks a book, so three of them in one run are a bound
        ids = [self.add(f"/p{n}")[0] for n in range(4)]
        died = []

        def broken(book):
            died.append(book)
            raise RuntimeError("the converter died")

        self.hooks["convert"] = broken
        self.assertEqual(self.go(), 4)
        self.assertEqual(len(died), 3)
        self.assertEqual(crawlguard.read_breaker(self.index)["kind"], "stage_bound")
        parked = [self.book_of(i) for i in ids[:3]]
        for book in parked:
            self.assertEqual(self.store.read_book(book)["state"], "weeded")
            self.assertEqual(self.events(book, "crawl_rejected")[0]["stage"], "convert")
        self.assertEqual([r["status"] for r in self.rows()][:3], ["rejected"] * 3)
        self.hooks.clear()
        self.assert_tripped_then_refused_then_clear_goes_again("stage_bound")
        self.assertEqual(self.go(), 0)
        self.assertEqual([self.store.read_book(b)["state"] for b in parked], ["weeded"] * 3)         # the parked books stay parked
        self.assertEqual(self.events(self.book_of(ids[3]), "reshelved")[0]["via"], "crawl")


class AtACeiling(Chain):
    def test_a_book_judged_in_when_the_cards_of_the_day_are_used_is_carded_and_moved_by_the_run_of_the_next_day(self):
        self.set_plan(PLAN_TEXT.replace("cards_per_day = 10", "cards_per_day = 1"))
        a, _ = self.add("/pa", target="gene-editing")
        b, _ = self.add("/pb", target="gene-editing")
        self.assertEqual(self.go(), 0)
        first, second = self.book_of(a), self.book_of(b)
        self.assertEqual((len(self.events(first, "reshelved")), len(self.events(second, "crawl_judged"))), (1, 1))      # the second book is filed, judged in and waiting for its card
        self.assertEqual((self.events(second, "placement_proposed"), self.events(second, "reshelved"), self.shelf(second)), ([], [], "default"))
        self.assertEqual([l["reason"] for l in self.lines() if l["step"] == "card" and l["outcome"] == "skipped"], ["cards_per_day reached"])
        self.assertEqual(self.used()["card"], (1, 1))
        self.later(minutes=30)
        self.assertEqual(self.go(), 0)                                                  # the same day: the ceiling holds
        self.assertEqual(self.used()["card"], (1, 1))
        self.assertEqual(self.events(second, "reshelved"), [])
        self.later(days=1)
        self.assertEqual(self.go(), 0)
        self.assertEqual((len(self.events(second, "reshelved")), self.shelf(second) != "default"), (1, True))
        self.assertEqual(self.used()["card"], (1, 1))
        self.assertEqual(len(self.events(first, "reshelved")), 1)
        self.assertEqual(sorted(self.requests()), ["/pa", "/pb"])

    def test_a_candidate_left_in_the_queue_when_the_fetches_of_the_day_are_used_is_fetched_and_finished_by_the_run_of_the_next_day(self):
        self.set_plan(PLAN_TEXT.replace("fetches_per_day = 20", "fetches_per_day = 1"))
        a, _ = self.add("/pa")
        b, _ = self.add("/pb")
        self.assertEqual(self.go(), 0)
        self.assertEqual((self.row(a)["status"], self.row(b)["status"]), ("kept", "queued"))
        self.assertEqual(self.requests(), ["/pa"])
        reasons = [l["reason"] for l in self.lines() if l["step"] == "fetch" and l["outcome"] == "skipped"]
        self.assertEqual(reasons, ["fetches_per_day reached: no new candidates today"])
        self.later(minutes=30)
        self.assertEqual(self.go(), 0)                                                  # the same day: the start of the run says the ceiling is reached, and nothing is fetched
        reasons = [l["reason"] for l in self.lines() if l["step"] == "fetch" and l["outcome"] == "skipped"]
        self.assertEqual(reasons[1:], ["fetches_per_day reached (1 of 1): no new candidates", "fetches_per_day reached: no new candidates today"])
        self.assertEqual((self.row(b)["status"], self.requests()), ("queued", ["/pa"]))
        self.assertEqual(len(self.events(self.book_of(a), "reshelved")), 1)             # the later steps still ran for the book that was fetched
        self.later(days=1)
        self.assertEqual(self.go(), 0)
        self.assertEqual((self.row(b)["status"], len(self.events(self.book_of(b), "reshelved"))), ("kept", 1))
        self.assertEqual(self.requests(), ["/pa", "/pb"])
        self.assertEqual(self.used()["fetch"], (1, 1))


class TheFiledCount(Chain):
    def spy_on_reserve(self):
        """Every call of `crawlstate.reserve`: the `filed` it was given, and what the books say at that moment."""
        seen, real = [], crawlstate.reserve

        def reserve(conn, plan, now, run, filed):
            seen.append((filed, crawlbooks.filed_count(self.store), crawlstate.filed_total(crawlbooks.filed_events(self.store))))
            return real(conn, plan, now, run, filed)

        patch = mock.patch.object(crawlstate, "reserve", reserve)
        patch.start()
        self.addCleanup(patch.stop)
        return seen

    def orphan_and_unreadable(self):
        """A book the crawl filed whose `crawl_found` was never written (its page is filed), and one of the crawl's whose event log cannot be read: the ceiling counts both."""
        orphan = self.store.create_book(title="An orphan", kind="webpage", auto_filed=True)
        version = self.store.add_version(orphan, source={"address_asked": "http://orphan.test/o"})
        self.store.file_payload(orphan, version, "original", {"page.html": page("An orphan")}, primary="page.html")
        stages.mark(self.store, orphan, version, "fetched", "done")
        bad = self.store.create_book(title="Unreadable", kind="webpage", auto_filed=True)
        self.store.append_event(bad, "filed")
        events = self.store.events_file(bad)
        os.rename(events, events + ".real")
        os.symlink(events + ".real", events)
        return orphan, bad

    def test_every_reserve_of_a_run_is_given_the_number_of_books_with_a_crawl_found_at_that_moment(self):
        for n in range(3):
            self.add(f"/p{n}")
        seen = self.spy_on_reserve()
        self.assertEqual(self.go(), 0)
        self.assertEqual([filed for filed, _counted, _events in seen], [0, 1, 2, 3])
        self.assertTrue(all(filed == counted == events for filed, counted, events in seen), seen)
        self.assertEqual(len([b for b in self.crawl_books_all() if "crawl_found" in self.names(b)]), 3)

    def test_orphans_and_unreadable_books_are_in_the_count_and_a_small_filed_total_stops_the_fetches_at_it(self):
        self.set_plan(PLAN_TEXT.replace("filed_total = 50", "filed_total = 4"))
        orphan, bad = self.orphan_and_unreadable()
        ids = [self.add(f"/p{n}")[0] for n in range(3)]
        seen = self.spy_on_reserve()
        self.assertEqual(self.go(), 0)
        self.assertEqual([filed for filed, _counted, _events in seen], [2, 3, 4])      # the orphan and the unreadable book are counted from the start
        self.assertTrue(all(filed == counted for filed, counted, _events in seen), seen)
        self.assertEqual([r["status"] for r in self.rows()], ["kept", "kept", "queued"])
        self.assertEqual(self.requests(), ["/p0", "/p1"])                               # the ceiling stopped the fetches at 4 filed
        ended = [l["reason"] for l in self.lines() if l["step"] == "fetch" and l["outcome"] == "skipped" and "filed_total" in (l["reason"] or "")]
        self.assertEqual(len(ended), 1)
        self.assertEqual(crawlbooks.filed_count(self.store), 4)
        self.assertEqual(self.names(orphan), [])                                        # no step took the orphan up


class TheRunName(Chain):
    def test_each_run_has_its_own_name_and_every_line_and_event_of_a_run_carries_it(self):
        ident, _ = self.add("/p1")
        names = []
        for n in range(3):
            self.assertEqual(self.go(now=NOW + datetime.timedelta(hours=n * 2)) if n else self.go(), 0)       # the first two runs share their start's second, as two firings of a clock can
            names.append(self.lines()[-1]["run"])
        self.assertEqual(self.go(now=NOW), 0)
        names.append(self.lines()[-1]["run"])
        self.assertEqual(len(set(names)), 4)
        self.assertTrue(all(re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]{6}", name) for name in names), names)
        by_run = {}
        for line in self.lines():
            by_run.setdefault(line["run"], []).append(line["step"])
        self.assertEqual(sorted(by_run), sorted(names))
        for steps in by_run.values():
            self.assertEqual((steps[0], steps[-1]), ("run_start", "run_end"))
        book = self.book_of(ident)
        self.assertEqual({self.events(book, "crawl_found")[0]["run"], self.events(book, "reshelved")[0]["run"]}, {names[0]})
        self.assertEqual(self.row(ident)["run_id"], names[0])


class TheDryRun(Chain):
    def snapshot(self):
        out = {}
        for folder, dirs, files in os.walk(self.base):
            for name in dirs + files:
                path = os.path.join(folder, name)
                info = os.lstat(path)
                out[path] = (info.st_mode, info.st_size, info.st_mtime_ns)
        return out

    def test_it_prints_the_steps_it_would_take_and_writes_nothing_asks_no_model_and_makes_no_request(self):
        self.add("/p1")
        self.add("/p2")
        self.assertEqual(self.go(), 0)                                                  # a library with books, a log, a queue and counters worth protecting
        self.add("/p3")
        before, hits, lookups, probes, order = self.snapshot(), len(self.srv.hits), len(self.lookups), self.probes, len(self.order)
        self.assertEqual(self.go(dry_run=True), 0)
        text = "\n".join(self.out)
        for words in ("requeue the stalled rows", "refresh the lists", "reconcile", "scan and hold", "convert and index", "judge", "cards", "proposal and move", "refill", "fetch up to 4 new candidates"):
            self.assertIn(words, text)
        self.assertEqual(self.snapshot(), before)                                       # no file made, changed or removed in the library, the index, the log or the queue
        self.assertEqual((len(self.srv.hits), len(self.lookups), self.probes, len(self.order)), (hits, lookups, probes, order))
        self.assertEqual(self.requests(), ["/p1", "/p2"])
        self.assertEqual(self.rows()[-1]["status"], "queued")



class Mixed(Chain):
    """A library with a good book, one the scan holds, one the judge rejects and one the proposal leaves unplaced."""

    def setUp(self):
        super().setUp()
        self.good, _ = self.add("/good", title="Good book", target="gene-editing")
        self.held, _ = self.add("/held", title="Held book")
        self.weak_id, weak_title = self.add("/weak", title="Weak book")
        self.none, none_title = self.add("/none", title="None book", target="gene-editing")
        self.weak.add(weak_title)                                                       # its best match is far under the threshold
        self.scan_kinds["/held"] = ["javascript"]                                       # the scan reports a hold kind
        self.answers[none_title] = "none: no shelf fits"                                # the model says no shelf fits

    def books(self):
        return {name: self.book_of(ident) for name, ident in (("good", self.good), ("held", self.held), ("weak", self.weak_id), ("none", self.none))}


class EmptyCardInTheChain(Mixed):
    """The library of `Mixed` with a page whose card has no summary: the real rule of `crawlcards` judges it out after the (fake) card step, and the report compares the same on every row."""

    def card_step(self, ctx):
        super().card_step(ctx)
        library = store.Store.open()
        book = self.book_of(self.none)
        if book is not None and card.generations(library, book, library.read_book(book)["current_version"]) and not self.events(book, "crawl_rejected"):
            version = library.read_book(book)["current_version"]
            card.file(library, card.make(library, book, version, model=None, records=[]))          # the newest card of this one has no model part, so no summary
        crawlcards.judge_out_empty_cards(ctx, library, roomy, crawlbooks.approved_digests(ctx.index_root))

    def test_the_page_with_an_empty_card_is_judged_out_and_the_log_and_the_queue_still_compare_the_same(self):
        self.assertEqual(self.go(), 0)
        books = self.books()
        empty = books["none"]
        self.assertEqual((self.store.read_book(empty)["state"], [e["stage"] for e in self.events(empty, "crawl_rejected")]), ("weeded", ["card"]))
        self.assertEqual(self.row(self.none)["status"], "rejected")
        self.assertEqual(self.store.read_book(books["good"])["state"], "active")                      # a book with a summary is moved on its way, as before
        data = crawlreport.build(self.index, datetime.date(2026, 11, 16), "UTC", self.now, store=store.Store.open(write=False))
        self.assertEqual([(c["what"], c["log"], c["queue"], c["same"]) for c in data["compare"]], [("kept", 2, 2, True), ("rejected", 2, 2, True), ("failed", 0, 0, True)])
        self.assertEqual(sorted(b["book"] for b in data["books"]["rejected"]), sorted([books["weak"], empty]))
        self.assertEqual(self.events(empty, "reshelved"), [])


class TheOtherMachinesReaders(Mixed):
    """The files a whole run leaves, read the way `crawlstatus` and `crawlreport` read them (the forms of the plan's R1 'Interfaces')."""

    def read_status(self):
        return crawlstatus.status(self.index, self.bulk, read_plan=crawlplan.read_plan, store=store.Store.open(write=False), now=self.now, statvfs=roomy)

    def test_the_status_shows_a_run_that_is_going_and_then_the_state_the_run_left(self):
        seen = []
        self.once("scan", lambda book: seen.append(crawlstatus.state(self.index)))
        self.assertEqual(self.go(), 0)
        self.assertEqual((seen[0]["state"], seen[0]["running"], seen[0]["lock"]["holder"]["pid"]), ("running", True, os.getpid()))
        status = self.read_status()
        self.assertEqual((status["state"]["state"], status["state"]["breaker"]["paused"], status["state"]["lock"]["held"]), ("idle", False, False))
        last = status["last_run"]
        self.assertEqual((last["found"], last["run"], last["status"], last["end_outcome"], last["end_reason"]), (True, self.lines()[-1]["run"], "ended", "ok", "done"))
        self.assertEqual({k: status["runs_today"][k] for k in ("started", "ended", "ended_by_outcome", "refused")}, {"started": 1, "ended": 1, "ended_by_outcome": {"ok": 1}, "refused": 0})

    def test_the_status_shows_the_counters_against_their_ceilings_and_the_books_against_the_filed_ceiling(self):
        self.assertEqual(self.go(), 0)
        status = self.read_status()
        self.assertEqual((status["plan"]["status"], status["plan"]["digest"]), ("approved", self.digest[:12]))
        counters = status["queue"]["counters"]
        self.assertEqual((counters["fetch"]["n"], counters["fetch"]["limit"], counters["fetch"]["at_or_over"]), (4, 20, False))
        self.assertEqual((counters["card"]["n"], counters["card"]["limit"]), (2, 10))                         # the good book and the unplaced one were carded; the held and the rejected were not
        self.assertEqual([(d["domain"], d["fetch"], d["limit"]) for d in counters["domains"]], [("a.test", 4, 50)])
        self.assertEqual(status["queue"]["counts"]["today"], {"queued": 0, "fetching": 0, "kept": 3, "rejected": 1, "failed": 0, "blocked": 0})
        self.assertEqual((status["books"]["filed"]["n"], status["books"]["filed"]["limit"], status["books"]["unreviewed"]), (4, 50, 4))
        self.assertEqual([(h["book"], h["reason"]) for h in status["holds"]["holds"]], [(self.books()["held"], "javascript")])
        self.assertEqual([r["address"] for r in status["queue"]["reasons"]["rejected"]["recent"]], ["http://a.test/weak"])

    def test_the_report_names_the_book_filed_judged_carded_and_moved_and_the_held_the_rejected_and_the_unplaced_book(self):
        self.assertEqual(self.go(), 0)
        books = self.books()
        data = crawlreport.build(self.index, datetime.date(2026, 11, 16), "UTC", self.now, store=store.Store.open(write=False))
        self.assertEqual({k: data["counts"][k] for k in ("fetched", "fetch_failed", "kept")}, {"fetched": 4, "fetch_failed": 0, "kept": 2})           # kept: the two judged in (a judge line that says ok)
        self.assertEqual((data["counts"]["rejected"], data["counts"]["standing"]), (1, 3))                                  # the judged-out book is a rejection, and the three others stand
        self.assertEqual([(c["what"], c["log"], c["queue"]) for c in data["compare"]], [("kept", 3, 3), ("rejected", 1, 1), ("failed", 0, 0)])
        self.assertTrue(all(c["same"] for c in data["compare"]), data["compare"])                                          # a healthy run, with a held, a judged-out and an unplaced book, says the same on every row
        self.assertEqual(sorted(b["book"] for b in data["filed"]["books"]), sorted(books.values()))
        self.assertEqual({b["book"]: b["seen_in"] for b in data["filed"]["books"]}, {books["good"]: "both", books["held"]: "both", books["none"]: "both", books["weak"]: "log"})      # the queue's row of a judged-out book is no longer `kept`
        moved = data["books"]["moved"]
        self.assertEqual([(m["book"], m["from"], m["to"]) for m in moved], [(books["good"], "default", self.shelf(books["good"]))])
        self.assertEqual([(b["book"], b["proposal"]) for b in data["books"]["left_default"]], [(books["none"], "none")])
        self.assertEqual([(b["book"], b["kinds"]) for b in data["books"]["held"]], [(books["held"], ["javascript"])])
        self.assertEqual([b["book"] for b in data["books"]["rejected"]], [books["weak"]])
        self.assertLess(data["books"]["rejected"][0]["score"], 0.9)
        self.assertEqual(data["books"]["totals"], {"checked": 4, "held": 1, "left_default": 1, "log_too_large": 0, "moved": 1, "not_filed_by_the_crawl": 0, "rejected": 1, "unreadable": 0})
        self.assertEqual(data["unreviewed"]["unreviewed"], 4)
        self.assertEqual({k: data["steps"][k] for k in ("capture", "scan", "hold", "convert", "index", "judge", "card", "propose", "move")},
                         {"capture": {"ok": 4}, "scan": {"ok": 3}, "hold": {"held": 1}, "convert": {"ok": 3}, "index": {"ok": 3}, "judge": {"ok": 2, "rejected": 1}, "card": {"ok": 2}, "propose": {"ok": 2, "skipped": 1}, "move": {"ok": 1, "refused": 1}})
        text = crawlreport.render(data)
        for book in books.values():
            self.assertIn(book, text)
        for words in ("Moved by the crawl to a shelf: 1", "Left on the shelf default: 1", "Held by the scan: 1", "Judged out and kept as weeded: 1"):
            self.assertIn(words, text)
        written = crawlreport.make_report(self.index, read_plan=crawlplan.read_plan, now=self.now, day=None, store=store.Store.open(write=False))
        self.assertEqual((written["filed"], written["counts"]["fetched"]), (4, 4))

    def test_the_files_a_whole_run_leaves_are_in_the_forms_the_readers_expect(self):
        self.assertEqual(self.go(), 0)
        self.assertEqual(os.path.getsize(os.path.join(self.index, "crawl.lock")), 0)
        breaker = read_json(os.path.join(self.index, "crawl", "breaker.json"))
        self.assertEqual((sorted(breaker), breaker["tripped"]), (["at", "kind", "reason", "run", "tripped"], False))
        state = read_json(os.path.join(self.index, "crawl", "guard.json"))
        self.assertTrue({"history", "model_down_since"} <= set(state))                 # (the file may hold more keys: the entries found down)
        for line in self.lines():
            self.assertEqual(list(line), list(crawllog.FIELDS))
            self.assertIn(line["step"], crawllog.STEPS)
            self.assertIn(line["outcome"], crawllog.OUTCOMES)
        self.assertEqual(os.listdir(os.path.join(self.index, "crawl", "log")), ["crawl-2026-11-16.jsonl"])
        conn = self.conn()
        self.assertEqual(sorted(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")), ["candidates", "counters"])
        self.assertEqual(sorted(k for _day, k, _n in conn.execute("SELECT day, key, n FROM counters") if not k.startswith("fetch:")), ["card", "fetch"])
        for book in self.books().values():
            found = self.events(book, "crawl_found")[0]
            self.assertEqual({k: found[k] for k in ("source", "found_from", "topic", "plan_digest")}, {"source": "openalex", "found_from": "openalex:W1", "topic": "verification", "plan_digest": self.digest})
        self.assertEqual({e["event"] for b in self.books().values() for e in self.events(b)} - {"filed", "crawl_found", "crawl_judged", "crawl_rejected", "crawl_held", "placement_proposed", "reshelved", "crawl_unplaced"}, set())


class TheScanComesFirst(Chain):
    def test_a_book_is_converted_only_after_its_scan_is_done_and_a_held_book_never_reaches_a_later_step(self):
        self.set_plan(PLAN_TEXT.replace("batch = 4", "batch = 8"))
        ok, _ = self.add("/ok", title="Plain book")
        script, _ = self.add("/script", title="Script book")
        held, held_title = self.add("/held", title="Held book")
        failed, failed_title = self.add("/failed", title="Failed scan book")
        skipped, skipped_title = self.add("/skipped", title="No scanner book")
        self.scan_kinds.update({"/script": ["script_elements", "event_handlers", "pattern_in_binary_data"], "/held": ["encrypted"]})
        self.scan_status.update({"/failed": "failed", "/skipped": "skipped"})
        self.assertEqual(self.go(), 0)
        books = {name: self.book_of(i) for name, i in (("ok", ok), ("script", script), ("held", held), ("failed", failed), ("skipped", skipped))}
        scans = [b for kind, b in self.order if kind == "scan"]
        self.assertEqual(sorted(scans), sorted(books.values()))
        for name in ("ok", "script"):                                                   # the kinds that do not hold go all the way
            book = books[name]
            self.assertLess(self.order.index(("scan", book)), self.order.index(("convert", book)))
            self.assertEqual(len(self.events(book, "reshelved")), 1)
        for name in ("held", "failed", "skipped"):                                       # a hold, a failed scan and a missing scanner each stop the book before the converter
            book = books[name]
            self.assertNotIn(("convert", book), self.order)
            self.assertNotIn(("index", book), self.order)
            self.assertEqual(len(self.events(book, "crawl_held")), 1)
            self.assertEqual((self.events(book, "crawl_judged"), self.events(book, "placement_proposed"), self.events(book, "reshelved")), ([], [], []))
            self.assertEqual((self.shelf(book), self.store.read_book(book)["state"]), ("default", "weeded"))
            self.assertFalse(card.generations(self.store, book, self.store.read_book(book)["current_version"]))
        embedded = [t for kind, texts in self.order if kind == "embed" for t in texts]
        for title in ("Held book", "Failed scan book", "No scanner book"):
            self.assertFalse([t for t in embedded if t.startswith(title)], title)
        self.assertEqual([self.events(books[n], "crawl_held")[0]["kinds"] for n in ("held", "failed", "skipped")], [["encrypted"], ["scan_failed"], ["scan_unavailable"]])
        calls = [(kind, b) for kind, b in self.order if kind in ("scan", "convert")]                         # every convert follows the scan of the same book
        for index, (kind, book) in enumerate(calls):
            if kind == "convert":
                self.assertIn(("scan", book), calls[:index])


class TheOwnersBooks(Chain):
    def snapshot(self, books):
        return {b: (self.store.read_book(b), self.store.read_events(b)) for b in books}

    def test_the_172_unanswered_proposals_and_every_other_book_are_untouched_by_a_whole_run(self):
        owners = []
        for n in range(172):                                                            # the owner's books on default, each with a proposal nobody has answered
            owner = self.store.create_book(title=f"Owner {n}", kind="preprint")
            self.store.append_event(owner, "placement_proposed", answer={"kind": "shelf"}, order=["a"], generation=1)
            owners.append(owner)
        plain = [self.store.create_book(title=f"Plain owner {n}", kind="preprint") for n in range(3)]
        shelved = self.store.create_book(title="On a shelf", kind="preprint", shelf="cloning")
        carded_owner, _ = self.book_with("An owner book with a card")                  # on default, with a card, which the owner's own `place-propose` would take
        forged, _ = self.book_with("An owner book with a forged event")
        self.store.append_event(forged, "crawl_found", candidate=1, source="openalex", found_from=None, topic=None, run="run-0", plan_digest=self.digest)
        self.store.append_event(forged, "crawl_judged", score=0.9, shelf="cloning", ok=True)
        good, _ = self.add("/good", title="Good book", target="gene-editing")
        others = owners + plain + [shelved, carded_owner, forged]
        before = self.snapshot(others)
        self.assertEqual(self.go(steps=self.steps(scan=no_step, convert=no_step, judge=no_step, cards=no_step, move=no_step)), 0)       # the crawl's book is filed and no more: the next run's earlier work takes it up
        self.later(minutes=20)
        stranger = self.store.create_book(title="A crawl book of an unapproved plan", kind="preprint", auto_filed=True)
        crawlbooks.record_found(self.store, stranger, candidate=2, source="openalex", found_from=None, topic=None, run="run-0", plan_digest="b" * 32)
        before_stranger = self.snapshot([stranger])[stranger]
        self.assertEqual(self.go(), 0)
        self.assertEqual(self.snapshot(others), before)                                 # no event, no proposal, no shelf, no state of any other book changed
        self.assertEqual([self.shelf(b) for b in owners + plain], ["default"] * 175)
        after = self.snapshot([stranger])[stranger]
        self.assertEqual(after[0], before_stranger[0])
        self.assertEqual(after[1][:len(before_stranger[1])], before_stranger[1])
        self.assertEqual([e["event"] for e in after[1][len(before_stranger[1]):]], ["crawl_unplaced"])                       # named once, and nothing else done for it
        run = [l for l in self.lines() if l["run"] == self.lines()[-1]["run"]]
        named = [i for i, l in enumerate(run) if l["step"] == "move" and l["book"] == stranger]
        self.assertEqual(len(named), 1)
        self.assertLess(named[0], min(i for i, l in enumerate(run) if l["step"] == "scan"))                                    # it is named at the start of the earlier work, before its chain
        self.assertEqual(len(self.events(self.book_of(good), "reshelved")), 1)         # the crawl's own book was moved
        self.assertEqual(len(self.prompts), 1)                                          # one proposal was asked for, and for that book only
        self.assertFalse([p for p in self.prompts if "Owner" in p["prompt"] or "owner book" in p["prompt"]])
        self.assertFalse([t for kind, texts in self.order if kind == "embed" for t in texts if "wner" in t[:20] or "On a shelf" in t[:20]])
        self.assertEqual(self.go(now=self.later(hours=2)), 0)
        self.assertEqual(self.snapshot(others), before)                                 # a second run changes none of them either
        self.assertEqual([e["event"] for e in self.snapshot([stranger])[stranger][1][len(before_stranger[1]):]], ["crawl_unplaced"])


class TheRegistry(Chain):
    def test_the_registry_uses_the_card_step_of_crawlcards_and_calls_it_with_the_books_that_have_been_judged_in(self):
        self.assertIn("make_step", crawlcards.step.__qualname__)                        # the registry's `cards` is the step `crawlcards.make_step` made
        good, _ = self.add("/good", target="gene-editing")
        other, _ = self.add("/other", target="gene-editing")
        seen = []

        def spy(ctx):
            library = store.Store.open()
            scan = crawlbooks.scan_crawl_books(library)
            judged = [e["id"] for e in scan.entries if any(x.get("event") == "crawl_judged" and x.get("ok") is True for x in e["events"])]
            seen.append((ctx.run, ctx.plan_digest, judged, [b for b in crawlbooks.crawl_books(library, crawlbooks.approved_digests(ctx.index_root), scan)]))

        with mock.patch.object(crawlcards, "step", spy):
            steps = self.steps(without=("cards",))
            self.assertEqual(self.go(steps=steps), 0)
        run = self.lines()[-1]["run"]
        books = [self.book_of(good), self.book_of(other)]
        self.assertEqual(seen, [(run, self.digest, [], []), (run, self.digest, books, books)])      # at the earlier work nothing is judged yet; after the fetch both books have been, and are waiting

    def test_each_point_of_the_real_registry_is_the_step_of_its_module_and_the_chain_comes_twice_in_the_spec_order(self):
        called = []
        patches = [mock.patch.object(crawllists, "step", lambda ctx: called.append("lists")), mock.patch.object(crawlrefill, "step", lambda ctx: called.append("refill")),
                   mock.patch.object(crawlfetch, "step", lambda ctx: called.append("fetch")), mock.patch.object(crawlsteps, "step", lambda ctx: called.append("scan")),
                   mock.patch.object(crawlsteps, "convert_step", lambda ctx: called.append("convert")), mock.patch.object(crawlsteps, "judge_step", lambda ctx: called.append("judge")),
                   mock.patch.object(crawlcards, "step", lambda ctx: called.append("cards")), mock.patch.object(crawlmove, "step", lambda ctx: called.append("move"))]
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            self.assertEqual(self.go(steps=crawlrun.default_steps()), 0)
        chain = ["scan", "convert", "judge", "cards", "move"]
        self.assertEqual(called, ["lists"] + chain + ["refill", "fetch"] + chain)


class Refusals(Chain):
    def test_a_run_that_is_started_while_the_stop_file_is_there_is_refused_and_nothing_is_done(self):
        self.add("/p1")
        self.stop_file()
        self.assertEqual(self.go(), 3)
        self.assertEqual((self.requests(), self.probes, self.rows()[0]["status"]), ([], 0, "queued"))
        self.assertEqual([(l["step"], l["outcome"], l["reason"]) for l in self.lines()], [("refuse", "refused", "the stop file is present")])
        self.remove_stop_file()
        self.assertEqual(self.go(), 0)
        self.assertEqual(self.requests(), ["/p1"])

    def test_a_required_list_that_cannot_be_had_ends_the_run_at_the_first_point_with_exit_3_and_nothing_is_fetched(self):
        self.add("/p1")
        del self.lists.replies[PHISH_URL]
        self.assertEqual(self.go(), 3)
        self.assertEqual(self.requests(), [])
        self.assertEqual((self.lines()[-1]["step"], self.lines()[-1]["outcome"]), ("run_end", "refused"))
        self.assertEqual([l["outcome"] for l in self.lines() if l["step"] == "refuse"], ["refused"])
        self.assertEqual(self.rows()[0]["status"], "queued")
        self.lists.replies[PHISH_URL] = (200, {}, hosts("bad1.example", "bad2.example"))
        self.assertEqual(self.go(), 0)                                                  # the next run tries again: nothing was tripped
        self.assertEqual(self.requests(), ["/p1"])

    def test_a_run_holds_the_lock_while_it_goes_and_lets_it_go_at_its_end_so_that_the_next_run_can_take_it(self):
        self.add("/p1")
        held = []
        self.once("scan", lambda book: held.append(crawlguard.acquire_run_lock(self.index, now=NOW)))
        self.assertEqual(self.go(), 0)
        self.assertEqual(held, [None])                                                  # a second run cannot take it while the first goes
        self.assertEqual(self.go(now=self.later(hours=1)), 0)
        self.assertEqual([l["outcome"] for l in self.lines() if l["step"] == "run_end"], ["ok", "ok"])


class TheTimeBudget(Chain):
    """The run's own time budget (an hour) is looked at between two steps of the chain, at each point and before each book of a step: it is spent here from inside a step, since the injected clock does not move."""

    def test_a_budget_spent_during_a_step_prevents_the_books_after_it_and_the_next_step_and_ends_the_run_at_the_next_point_and_the_next_run_goes_on(self):
        a, _ = self.add("/pa")
        b, _ = self.add("/pb")
        self.assertEqual(self.go(steps=self.steps(judge=no_step, cards=no_step, move=no_step)), 0)          # both books are scanned, converted and indexed
        books = [self.book_of(a), self.book_of(b)]
        self.later(minutes=20)
        self.once("embed", self.spend)
        self.assertEqual(self.go(), 0)
        self.assertEqual([len(self.events(x, "crawl_judged")) for x in books], [1, 0])                  # the book that was going is judged; the one after it is not begun
        self.assertEqual([len(card.generations(self.store, x, self.store.read_book(x)["current_version"])) for x in books], [0, 0])      # the next step of the chain is not begun
        run = [l for l in self.lines() if l["run"] == self.lines()[-1]["run"]]
        self.assertIn("the time budget of the run is spent at refill", [l["reason"] for l in run if l["step"] == "stop" and l["outcome"] == "refused"])
        self.assertEqual(run[-1]["reason"], "stopped by the time budget at refill")
        self.assertEqual([l for l in run if l["step"] == "discover"], [])                              # the refill and the fetch are not reached
        self.assertEqual(self.go(now=self.later(minutes=20)), 0)
        self.assertEqual([len(self.events(x, "reshelved")) for x in books], [1, 1])
        self.assertEqual([len(self.events(x, "crawl_judged")) for x in books], [1, 1])

    def test_a_budget_spent_during_the_first_fetch_ends_the_batch_and_the_next_run_takes_the_rest(self):
        self.add("/p0")
        self.add("/p1")
        self.add("/p2")
        self.once("capture", self.spend)
        self.assertEqual(self.go(), 0)
        self.assertEqual(self.requests(), ["/p0"])
        self.assertEqual([r["status"] for r in self.rows()], ["kept", "queued", "queued"])
        self.assertEqual([l["reason"] for l in self.lines() if l["step"] == "fetch" and l["outcome"] == "skipped"], ["the time budget of the run is spent"])
        self.assertEqual(self.go(now=self.later(minutes=20)), 0)
        self.assertEqual(sorted(self.requests()), ["/p0", "/p1", "/p2"])
        self.assertEqual([r["status"] for r in self.rows()], ["kept"] * 3)
        self.assertEqual([len(self.events(b, "reshelved")) for b in self.crawl_books_all()], [1, 1, 1])

    def test_a_budget_spent_during_the_scan_of_the_first_book_leaves_the_second_unscanned_for_the_next_run(self):
        self.add("/pa")
        self.add("/pb")
        self.once("scan", self.spend)
        self.assertEqual(self.go(), 0)
        self.assertEqual([o[0] for o in self.order if o[0] in ("scan", "convert")], ["scan"])
        self.assertEqual(self.go(now=self.later(minutes=20)), 0)
        self.assertEqual([o[0] for o in self.order if o[0] == "scan"], ["scan", "scan"])
        self.assertEqual([len(self.events(b, "reshelved")) for b in self.crawl_books_all()], [1, 1])


class AnErrorIsNotADeath(Chain):
    def test_a_step_that_fails_with_an_error_closes_the_run_with_a_failed_end_lets_go_of_the_lock_and_the_next_run_goes_on(self):
        a, _ = self.add("/pa")

        def fail(book):
            raise RuntimeError("the scan tool broke")

        self.once("scan", fail)
        with self.assertRaises(RuntimeError):
            self.go()
        self.assertEqual((self.lines()[-1]["step"], self.lines()[-1]["outcome"], self.lines()[-1]["reason"]), ("run_end", "failed", "a step failed"))
        crawlguard.acquire_run_lock(self.index, now=NOW).release()
        self.assertEqual(self.go(now=self.later(minutes=31)), 0)
        self.assertEqual(self.requests(), ["/pa"])
        self.assertEqual(len(self.events(self.book_of(a), "reshelved")), 1)


class ScanGuards(Chain):
    def test_a_scan_that_failed_and_died_before_the_hold_is_held_by_the_next_run_and_the_book_is_never_converted(self):
        self.scan_status["/pa"] = "failed"
        a, _ = self.add("/pa")
        self.die_at("scan")
        with self.assertRaises(Boom):
            self.go()
        self.assertEqual(self.events(self.crawl_books_all()[0], "crawl_held"), [])                                          # the death came before the hold
        self.assertEqual(self.go(now=self.later(minutes=31)), 0)
        (book,) = self.crawl_books_all()
        self.assertEqual([e["kinds"] for e in self.events(book, "crawl_held")], [["scan_failed"]])
        self.assertNotIn(("convert", book), self.order)
        self.assertEqual(len([o for o in self.order if o[0] == "scan"]), 1)            # a scan that failed is not made again

    def test_a_book_whose_scan_was_refused_by_a_disk_floor_is_not_converted_by_the_step_after_it(self):
        self.add("/pa")
        parts = {"scan": crawlsteps.make_scan_step(scan=self.scan, statvfs=short)}
        self.assertEqual(self.go(steps=self.steps(**parts)), 0)
        self.assertEqual([o for o in self.order if o[0] in ("scan", "convert", "index")], [])
        (book,) = self.crawl_books_all()
        self.assertEqual(stages.read(self.store, book, self.store.read_book(book)["current_version"])["stages"]["scanned"]["status"], "pending")
        self.assertEqual(self.go(now=self.later(minutes=20)), 0)                       # the next run, with room, takes it all the way
        self.assertEqual(len(self.events(book, "reshelved")), 1)


class NoTripBetweenSuccesses(Chain):
    def test_failures_that_a_success_separates_do_not_trip_the_breaker(self):
        self.set_plan(PLAN_TEXT.replace("batch = 4", "batch = 6"))
        self.add("/dead0", host="dead0.test", route=False, resolves=False)
        self.add("/dead1", host="dead1.test", route=False, resolves=False)
        self.add("/ok1")
        self.add("/dead2", host="dead2.test", route=False, resolves=False)
        self.add("/dead3", host="dead3.test", route=False, resolves=False)
        self.add("/ok2")
        self.assertEqual(self.go(), 0)
        self.assertFalse(crawlguard.read_breaker(self.index)["tripped"])
        self.assertEqual(sorted(self.requests()), ["/ok1", "/ok2"])
        self.assertEqual([r["status"] for r in self.rows()], ["queued", "queued", "kept", "queued", "queued", "kept"])


class TheBatch(Chain):
    def test_a_run_takes_no_more_candidates_than_the_batch_and_the_next_runs_take_the_rest(self):
        self.set_plan(PLAN_TEXT.replace("batch = 4", "batch = 2"))
        for n in range(5):
            self.add(f"/p{n}")
        for run in range(3):
            self.assertEqual(self.go(now=self.later(minutes=20)), 0)
            self.assert_within_ceilings()
            self.assertEqual(len(self.requests()), min(2 * (run + 1), 5))
        self.assertEqual([r["status"] for r in self.rows()], ["kept"] * 5)


class BetweenTheSteps(Chain):
    """A step that does not look at the stop file or the budget itself is not begun after either was made: the registry looks between two steps of the chain."""

    def recorder(self, called):
        return lambda ctx: called.append(ctx.run)

    def test_a_stop_file_made_by_one_step_prevents_the_next_step_of_the_chain_whichever_it_is(self):
        self.add("/pa")
        called = []
        self.once("embed", self.stop_file)
        self.assertEqual(self.go(steps=self.steps(cards=self.recorder(called), move=self.recorder(called))), 0)
        self.assertEqual(len(called), 2)                                                # the two of the earlier work, which came before the stop file; none after the judge that made it
        self.remove_stop_file()
        self.assertEqual(self.go(steps=self.steps(cards=self.recorder(called), move=self.recorder(called)), now=self.later(minutes=20)), 0)
        self.assertEqual(len(called), 2 + 4)                                            # the next run goes through both chains again, with the two recorders in each

    def test_a_budget_spent_by_one_step_prevents_the_next_step_of_the_chain_whichever_it_is(self):
        self.add("/pa")
        called = []
        self.once("embed", self.spend)
        self.assertEqual(self.go(steps=self.steps(cards=self.recorder(called), move=self.recorder(called))), 0)
        self.assertEqual(len(called), 2)


class ApprovalsThatCannotBeRead(Chain):
    def test_a_set_of_approved_plans_that_cannot_be_read_ends_the_run_and_no_book_is_named_unplaced(self):
        a, _ = self.add("/pa")
        self.assertEqual(self.go(steps=self.steps(scan=no_step, convert=no_step, judge=no_step, cards=no_step, move=no_step)), 0)
        book = self.book_of(a)
        with mock.patch.object(crawlbooks, "approved_digests", return_value=set()):
            self.assertEqual(self.go(now=self.later(minutes=20)), 3)
        self.assertEqual(self.events(book, "crawl_unplaced"), [])
        self.assertEqual(self.lines()[-1]["outcome"], "refused")
        self.assertEqual(self.go(now=self.later(minutes=20)), 0)                        # the next run, which can read them, takes the book all the way
        self.assertEqual(len(self.events(book, "reshelved")), 1)


if __name__ == "__main__":
    unittest.main()
