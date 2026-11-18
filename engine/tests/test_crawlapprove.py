"""The owner's approval of the crawl plan (`kb/crawlapprove.py`, Increment B of the plan `2026-11-16-build-the-safeguards-of-the-unattended-crawl`).

`crawl-approve` prints a plain summary of the plan with a digest; with the digest, at a terminal, it stores the approved copies of the plan, the topics and the allow file, a **behaviour fingerprint** of the engine's code and model
settings, and the digest as `current`. A run (`load_approved`) recomputes both and refuses if either differs. The fingerprint recipe is held here a second time, written another way, and the module must equal it.
Every test uses a temporary library and a temporary copy of a small engine tree; none reads the owner's plan, topics, config or key.
Run them with `python3 -W error::ResourceWarning -m unittest engine.tests.test_crawlapprove`."""
import copy
import datetime
import hashlib
import json
import os
import stat
import tempfile
import unittest
from unittest import mock

from engine.tests import ENGINE_DIR  # noqa: F401  (puts the engine folder on the import path)

from kb import KbError, crawlapprove, crawlplan, models

NOW = datetime.datetime(2026, 11, 16, 12, 0, tzinfo=datetime.timezone.utc)
PLAN_TEXT = "# a plan\n[limits]\nbatch = 4\nfetches_per_day = 12\n[sources]\nweb_search = off\n[judge]\nthreshold = 0.4\n"
TOPICS_TEXT = "[core weight=10]\nverification\nformal methods\n[exploratory weight=5]\nquantum error correction\n[low weight=1]\nsystemverilog\n"
ALLOW_TEXT = "# hosts a public list must not block\nexample.org\n"
NAMES_STORED = ("plan.txt", "topics.txt", "allow.txt", "fingerprint", "summary.txt")
CRAWL_TASKS = ("card-notes", "card", "card-check", "card-more", "place", "card-embed", "place-embed", "crawl-query")
FIELDS = ("bridge", "server", "model", "max_output", "thinking", "timeout", "kind", "dimension", "query_prefix", "document_prefix")


def config():
    entry = lambda kind="chat", model="m": {"bridge": "ask-ollama", "server": "ned", "model": model, "thinking": False, "kind": kind}  # noqa: E731
    return {"index_root": "/x/index", "bulk_root": "/x/bulk", "library_id": "abc", "approved_tools": ["t"], "allow_main_disk": False,
            "models_on": True,
            "models": {"gemma": entry(model="gemma"), "gpt": entry(model="gpt"), "embedder": dict(entry("embedding", "emb"), dimension=8, query_prefix="q: ", document_prefix="d: "),
                       "unused": entry(model="unused")},
            "tasks": {"card-notes": "gemma", "card": "gpt", "card-check": "gemma", "card-more": "gemma", "place": "gpt", "card-embed": "embedder", "place-embed": "embedder",
                      "crawl-query": "gemma", "theme": "unused", "theme-check": "unused"}}


def reference_fingerprint(kb_root, cfg):
    """The recipe of the plan, written another way: a walk, a sort of the paths as bytes, one hash over a list of pieces."""
    skipped = {"__pycache__"}
    found = []
    for folder, names, files in os.walk(kb_root):
        names[:] = sorted(n for n in names if n not in skipped)
        for name in files:
            if name.endswith(".pyc"):
                raise ValueError("a bytecode file outside __pycache__")
            if True:
                full = os.path.join(folder, name)
                found.append(("engine/kb/" + os.path.relpath(full, kb_root).replace(os.sep, "/")).encode("utf-8") + b"\0" + full.encode("utf-8"))
    pieces = [b"kb-fingerprint-1\n"]
    for item in sorted(found, key=lambda x: x.split(b"\0", 1)[0]):
        path, real = item.split(b"\0", 1)
        with open(real.decode("utf-8"), "rb") as f:
            data = f.read()
        pieces.append(b"%d:%s:%d:" % (len(path), path, len(data)) + data)
    tasks = {t: cfg["tasks"][t] for t in CRAWL_TASKS if t in cfg.get("tasks", {})}
    entries = {name: {k: cfg["models"][name][k] for k in FIELDS if k in cfg["models"][name]} for name in set(tasks.values())}
    text = json.dumps({"models_on": cfg.get("models_on"), "tasks": tasks, "entries": entries}, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    pieces.append(b"config:%d:" % len(text) + text)
    return hashlib.sha256(b"".join(pieces)).hexdigest()


def make_writable(path):
    for folder, names, files in os.walk(path):
        os.chmod(folder, 0o700)
        for name in files:
            full = os.path.join(folder, name)
            if not os.path.islink(full):
                os.chmod(full, 0o600)


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = os.path.realpath(self._tmp.name)
        self.addCleanup(make_writable, self.dir)
        self.index = os.path.join(self.dir, "index")
        os.mkdir(self.index)
        self.cfg = config()
        self.kb = os.path.join(self.dir, "kb")
        for rel, data in {"a.py": b"print(1)\n", "b.py": b"x = 2\n", "schemas/card.json": b"{}", "data/shelf-schema.json": b"[]", "sub/deep/c.py": b"c = 3\n",
                          "__pycache__/a.cpython-315.pyc": b"junk"}.items():
            full = os.path.join(self.kb, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as f:
                f.write(data)
        self.files = os.path.join(self.dir, "files")
        os.mkdir(self.files)
        self.plan = self.put("plan.txt", PLAN_TEXT)
        self.topics = self.put("topics.txt", TOPICS_TEXT)
        self.allow = self.put("allow.txt", ALLOW_TEXT)
        self.black = self.put("black.txt", "evil.example\n")
        self.say = []
        self.tty = lambda: True

    def put(self, name, text):
        path = os.path.join(self.files, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(path, 0o600)
        return path

    def set_plan(self, text=PLAN_TEXT):
        body = text + f"[files]\ntopics = {self.topics}\nblacklist = {self.black}\nallow = {self.allow}\n"
        self.put("plan.txt", body)

    def approve(self, digest=None, **kw):
        self.set_plan_if_needed()
        kw.setdefault("is_tty", self.tty)
        kw.setdefault("say", self.say.append)
        kw.setdefault("now", NOW)
        return crawlapprove.approve(self.index, self.cfg, self.plan, digest=digest, kb_root=self.kb, **kw)

    def set_plan_if_needed(self):
        with open(self.plan, encoding="utf-8") as f:
            if "[files]" not in f.read():
                self.set_plan()

    def digest(self):
        return self.approve()[1]

    def approved(self):
        self.set_plan_if_needed()
        crawlapprove.approve(self.index, self.cfg, self.plan, digest=self.digest(), kb_root=self.kb, is_tty=self.tty, say=self.say.append, now=NOW)

    def load(self):
        return crawlapprove.load_approved(self.index, self.cfg, kb_root=self.kb)

    def crawl(self, *parts):
        return os.path.join(self.index, "crawl", *parts)


class Fingerprint(Case):
    def test_it_equals_the_second_implementation_of_the_recipe(self):
        self.assertEqual(crawlapprove.fingerprint(self.cfg, self.kb)[0], reference_fingerprint(self.kb, self.cfg))
        self.assertRegex(crawlapprove.fingerprint(self.cfg, self.kb)[0], r"^[0-9a-f]{64}$")

    def test_it_is_the_same_on_the_real_engine_tree_in_both_implementations_and_between_runs(self):
        real = os.path.join(ENGINE_DIR, "kb")
        first = crawlapprove.fingerprint(self.cfg, real)[0]
        self.assertEqual(first, crawlapprove.fingerprint(self.cfg, real)[0])
        self.assertEqual(first, reference_fingerprint(real, self.cfg))

    def test_one_byte_of_any_file_a_file_added_or_removed_or_renamed_changes_it(self):
        base = crawlapprove.fingerprint(self.cfg, self.kb)[0]
        for rel in ("a.py", "schemas/card.json", "data/shelf-schema.json", "sub/deep/c.py"):
            full = os.path.join(self.kb, rel)
            with open(full, "rb") as f:
                before = f.read()
            with open(full, "wb") as f:
                f.write(before + b" ")
            self.assertNotEqual(crawlapprove.fingerprint(self.cfg, self.kb)[0], base, rel)
            with open(full, "wb") as f:
                f.write(before)
            self.assertEqual(crawlapprove.fingerprint(self.cfg, self.kb)[0], base, rel)
        extra = os.path.join(self.kb, "new.py")
        open(extra, "w").close()
        self.assertNotEqual(crawlapprove.fingerprint(self.cfg, self.kb)[0], base)
        os.remove(extra)
        os.rename(os.path.join(self.kb, "b.py"), os.path.join(self.kb, "c.py"))
        self.assertNotEqual(crawlapprove.fingerprint(self.cfg, self.kb)[0], base)

    def test_a_bytecode_file_outside_a_pycache_folder_is_an_error_because_python_would_run_it_without_its_source(self):
        for rel in ("stray.pyc", os.path.join("sub", "new.pyc"), os.path.join("sub", "deep", "x.pyc")):
            path = os.path.join(self.kb, rel)
            with open(path, "wb") as f:
                f.write(b"another")
            with self.subTest(rel=rel):
                with self.assertRaises(KbError) as caught:
                    crawlapprove.fingerprint(self.cfg, self.kb)
                self.assertIn("bytecode", str(caught.exception))
            os.remove(path)
        crawlapprove.fingerprint(self.cfg, self.kb)

    def test_a_run_refuses_when_a_bytecode_file_was_planted_beside_the_code_after_the_approval(self):
        self.approved()
        with open(os.path.join(self.kb, "planted.pyc"), "wb") as f:
            f.write(b"x")
        with self.assertRaises(crawlapprove.NotApproved) as caught:
            self.load()
        self.assertIn("approve again", str(caught.exception))

    def test_the_contents_of_a_pycache_folder_and_the_order_of_the_filesystem_do_not_matter(self):
        base = crawlapprove.fingerprint(self.cfg, self.kb)[0]
        with open(os.path.join(self.kb, "__pycache__", "a.cpython-315.pyc"), "wb") as f:
            f.write(b"another")
        os.makedirs(os.path.join(self.kb, "sub", "__pycache__"))
        with open(os.path.join(self.kb, "sub", "__pycache__", "z.py"), "wb") as f:
            f.write(b"not code that runs")
        self.assertEqual(crawlapprove.fingerprint(self.cfg, self.kb)[0], base)
        real_scandir = os.scandir
        with mock.patch.object(crawlapprove.os, "scandir", lambda p: iter(sorted(real_scandir(p), key=lambda e: e.name, reverse=True))):
            self.assertEqual(crawlapprove.fingerprint(self.cfg, self.kb)[0], base)

    def test_the_framing_cannot_be_confused_by_file_boundaries_or_names(self):
        base = crawlapprove.fingerprint(self.cfg, self.kb)[0]
        with open(os.path.join(self.kb, "a.py"), "wb") as f:
            f.write(b"print(1)")                         # the line end moves into the next file's start
        with open(os.path.join(self.kb, "b.py"), "wb") as f:
            f.write(b"\nx = 2\n")
        self.assertNotEqual(crawlapprove.fingerprint(self.cfg, self.kb)[0], base)

    def test_a_link_a_pipe_or_an_unreadable_file_in_the_tree_is_an_error(self):
        os.symlink(os.path.join(self.kb, "a.py"), os.path.join(self.kb, "link.py"))
        with self.assertRaises(KbError):
            crawlapprove.fingerprint(self.cfg, self.kb)
        os.remove(os.path.join(self.kb, "link.py"))
        os.mkfifo(os.path.join(self.kb, "pipe.py"))
        with self.assertRaises(KbError):
            crawlapprove.fingerprint(self.cfg, self.kb)
        os.remove(os.path.join(self.kb, "pipe.py"))
        os.symlink(self.kb, os.path.join(self.kb, "sub", "loop"))
        with self.assertRaises(KbError):
            crawlapprove.fingerprint(self.cfg, self.kb)
        os.remove(os.path.join(self.kb, "sub", "loop"))
        os.chmod(os.path.join(self.kb, "a.py"), 0)
        try:
            with self.assertRaises(KbError):
                crawlapprove.fingerprint(self.cfg, self.kb)
        finally:
            os.chmod(os.path.join(self.kb, "a.py"), 0o600)
        with self.assertRaises(KbError):
            crawlapprove.fingerprint(self.cfg, os.path.join(self.dir, "nowhere"))

    def test_the_model_settings_that_are_named_change_it_and_nothing_else_of_the_config_does(self):
        base = crawlapprove.fingerprint(self.cfg, self.kb)[0]
        for mutate in (lambda c: c["models"]["gemma"].__setitem__("model", "gemma2"), lambda c: c["models"]["gpt"].__setitem__("server", "other"),
                       lambda c: c["models"]["embedder"].__setitem__("query_prefix", "Q: "), lambda c: c["models"]["embedder"].__setitem__("dimension", 9),
                       lambda c: c["models"]["gemma"].__setitem__("thinking", True), lambda c: c["models"]["gemma"].__setitem__("max_output", 100),
                       lambda c: c["models"]["gemma"].__setitem__("timeout", 5), lambda c: c.__setitem__("models_on", False),
                       lambda c: c["tasks"].__setitem__("card", "gemma"), lambda c: c["tasks"].__setitem__("crawl-query", "gpt"), lambda c: c["tasks"].__setitem__("place-embed", "gemma"),
                       lambda c: c["tasks"].pop("place")):
            changed = copy.deepcopy(self.cfg)
            mutate(changed)
            self.assertNotEqual(crawlapprove.fingerprint(changed, self.kb)[0], base)
        for mutate in (lambda c: c.__setitem__("index_root", "/elsewhere"), lambda c: c.__setitem__("bulk_root", "/elsewhere"), lambda c: c.__setitem__("library_id", "other"),
                       lambda c: c["approved_tools"].append("t2"), lambda c: c["models"]["unused"].__setitem__("model", "other"), lambda c: c["tasks"].__setitem__("theme", "gpt"),
                       lambda c: c["tasks"].__setitem__("theme-check", "gpt"), lambda c: c["models"]["gemma"].__setitem__("api_key", "a secret that is not part of it"),
                       lambda c: c.__setitem__("something_new", {"secret": "x"})):
            changed = copy.deepcopy(self.cfg)
            mutate(changed)
            self.assertEqual(crawlapprove.fingerprint(changed, self.kb)[0], base)

    def test_a_config_that_is_not_the_shape_is_an_error_and_a_task_naming_no_entry_is_still_recorded(self):
        for bad in (lambda c: c.__setitem__("tasks", []), lambda c: c.__setitem__("models", "x"), lambda c: c["models"].__setitem__("gemma", "not an object")):
            changed = copy.deepcopy(self.cfg)
            bad(changed)
            with self.assertRaises(KbError):
                crawlapprove.fingerprint(changed, self.kb)
        changed = copy.deepcopy(self.cfg)
        changed["tasks"]["card"] = "no-such-entry"
        self.assertNotEqual(crawlapprove.fingerprint(changed, self.kb)[0], crawlapprove.fingerprint(self.cfg, self.kb)[0])

    def test_the_entry_fields_are_those_the_engine_reads(self):
        self.assertEqual(crawlapprove.ENTRY_FIELDS, models._KEYS)
        self.assertEqual(crawlapprove.CRAWL_TASKS, CRAWL_TASKS)

    def test_the_date_is_that_of_the_newest_file_in_utc(self):
        stamp = datetime.datetime(2026, 11, 14, 23, 30, tzinfo=datetime.timezone.utc).timestamp()
        for folder, _names, files in os.walk(self.kb):
            for name in files:
                os.utime(os.path.join(folder, name), (stamp - 86400, stamp - 86400))
        os.utime(os.path.join(self.kb, "b.py"), (stamp, stamp))
        self.assertEqual(crawlapprove.fingerprint(self.cfg, self.kb)[1], "2026-11-14")


class Digest(Case):
    def test_the_digest_is_32_hex_and_changes_with_one_byte_of_the_plan_the_topics_or_the_allow_file(self):
        self.set_plan()
        base = self.approve()[1]
        self.assertRegex(base, r"^[0-9a-f]{32}$")
        for path in (self.plan, self.topics, self.allow):
            with open(path, "a", encoding="utf-8") as f:
                f.write(" ")
            self.assertNotEqual(self.approve()[1], base, path)
            with open(path, "rb") as f:
                data = f.read()
            with open(path, "wb") as f:
                f.write(data[:-1])
            self.assertEqual(self.approve()[1], base, path)

    def test_the_blacklist_and_anything_else_are_not_in_it(self):
        self.set_plan()
        base = self.approve()[1]
        with open(self.black, "a", encoding="utf-8") as f:
            f.write("another.example\n")
        self.assertEqual(self.approve()[1], base)
        os.remove(self.black)
        self.assertEqual(self.approve()[1], base)

    def test_the_framing_cannot_be_confused_by_where_one_file_ends_and_the_next_begins(self):
        fp = "0" * 64
        a = crawlapprove.digest_of(b"ab", b"c", b"d", fp)
        b = crawlapprove.digest_of(b"a", b"bc", b"d", fp)
        c = crawlapprove.digest_of(b"ab", b"cd", b"", fp)
        self.assertEqual(len({a, b, c, crawlapprove.digest_of(b"abc", b"d", b"", fp)}), 4)
        self.assertEqual(a, crawlapprove.digest_of(b"ab", b"c", b"d", fp))
        self.assertNotEqual(a, crawlapprove.digest_of(b"ab", b"c", b"d", "1" + "0" * 63))
        for bad in ("", "0" * 63, "G" * 64, "A" * 64, None, 5):
            with self.assertRaises(KbError):
                crawlapprove.digest_of(b"ab", b"c", b"d", bad)

    def test_the_digest_equals_a_second_implementation_of_the_recipe(self):
        fp = "ab" * 32
        framed = b"kb-crawl-approval-2\n" + b"plan:2:ab\n" + b"topics:1:c\n" + b"allow:0:\n" + b"fingerprint:64:" + fp.encode() + b"\n"
        self.assertEqual(crawlapprove.digest_of(b"ab", b"c", b"", fp), hashlib.sha256(framed).hexdigest()[:32])

    def test_the_digest_covers_the_full_fingerprint_of_the_code_and_the_named_model_settings(self):
        self.set_plan()
        base = self.approve()[1]
        for rel in ("a.py", "schemas/card.json", "sub/deep/c.py"):
            full = os.path.join(self.kb, rel)
            before = open(full, "rb").read()
            with open(full, "ab") as f:
                f.write(b"# changed")
            self.assertNotEqual(self.approve()[1], base, rel)
            with open(full, "wb") as f:
                f.write(before)
            self.assertEqual(self.approve()[1], base, rel)
        self.cfg["models"]["gpt"]["model"] = "another"
        self.assertNotEqual(self.approve()[1], base)
        self.cfg["models"]["gpt"]["model"] = "gpt"
        self.assertEqual(self.approve()[1], base)
        self.cfg["models"]["unused"]["model"] = "another"                      # a setting the fingerprint does not name
        self.assertEqual(self.approve()[1], base)


class Preview(Case):
    def preview(self):
        self.set_plan()
        text, digest = self.approve()
        return text, digest

    def test_it_ends_with_the_digest_line_and_names_the_numbers_the_owner_is_agreeing_to(self):
        text, digest = self.preview()
        self.assertTrue(text.rstrip("\n").endswith("digest: " + digest))
        for fragment in ("12", "4", "0.4", "ceilings", "fetches per day", "disk", "bulk", "index"):
            self.assertIn(fragment, text)

    def test_it_says_the_grant_in_words(self):
        text, _ = self.preview()
        self.assertIn("without anyone at the keyboard", text)
        self.assertIn("moves each kept book onto a shelf by the model's pick", text)
        self.assertIn("no further question", text)
        self.assertIn("not proof that a person typed", text)
        self.assertIn("approve again", text)
        self.assertIn("If any of this is wrong, do not approve", text)

    def test_it_names_the_topics_by_section_and_weight(self):
        text, _ = self.preview()
        self.assertIn("4 topics", text)
        self.assertIn("2 in core at weight 10", text)
        self.assertIn("1 in exploratory at weight 5", text)
        self.assertIn("1 in low at weight 1", text)

    def test_it_names_every_source_that_is_on_and_each_with_terms_that_are_unresolved_and_says_they_are_the_owners(self):
        text, _ = self.preview()
        self.assertIn("OpenAlex: on", text)
        self.assertIn("web search: off", text)
        self.assertNotIn("DuckDuckGo", text)
        self.assertNotIn("abuse.ch", text)
        self.set_plan("[sources]\nweb_search = on\n[lists]\nurlhaus_recent = on\n")
        text, _ = self.approve()
        self.assertIn("web search: on", text)
        self.assertIn("DuckDuckGo", text)
        self.assertIn("abuse.ch", text)
        self.assertIn("for you to have read", text)

    def test_it_says_when_the_openalex_key_is_used_and_where_it_comes_from_and_says_nothing_when_it_is_not(self):
        text, _ = self.preview()
        self.assertNotIn("openalex.key", text)
        self.assertNotIn("your key", text.split("Sources:")[1].split("Public lists")[0])
        self.set_plan("[sources]\nopenalex_key = on\n")
        text, _ = self.approve()
        self.assertIn("OpenAlex: on (with your key)", text)
        self.assertIn("openalex.key", text)
        self.assertIn("in the address of each request", text)
        self.assertIn("for you to have read", text.split("openalex.key")[1].split("\n")[0])
        self.set_plan("[sources]\nopenalex = off\nopenalex_key = on\n")
        text, _ = self.approve()
        self.assertNotIn("openalex.key", text)  # a key for a source that is off is not used, and is not said to be

    def test_it_says_when_langsearch_is_the_web_search_and_where_its_key_comes_from_and_names_the_engine_of_the_search_only_when_it_is_on(self):
        self.set_plan("[sources]\nweb_search = on\nweb_search_engine = langsearch\n")
        text, _ = self.approve()
        self.assertIn("web search: on (LangSearch)", text)
        self.assertIn("langsearch.key", text)
        self.assertIn("your query words go to it", text)
        self.assertIn("for you to have read", text.split("langsearch.key")[1].split("\n")[0])
        self.assertNotIn("DuckDuckGo", text)
        self.set_plan("[sources]\nweb_search = on\n")
        text, _ = self.approve()
        self.assertIn("DuckDuckGo", text)
        self.assertNotIn("langsearch.key", text)
        self.assertNotIn("(LangSearch)", text)
        self.set_plan("[sources]\nweb_search = off\nweb_search_engine = langsearch\n")
        text, _ = self.approve()
        self.assertIn("web search: off", text)
        self.assertNotIn("langsearch.key", text)   # a choice of engine for a search that is off is not used, and is not said to be
        self.assertNotIn("DuckDuckGo", text)

    def test_it_names_the_lists_the_scan_kinds_that_hold_and_that_a_named_list_replaces_the_default(self):
        text, _ = self.preview()
        self.assertIn("phishing_domains: on", text)
        self.assertIn("urlhaus_recent: off", text)
        self.assertIn("encrypted", text)
        self.assertIn("replaces the default", text)
        self.assertIn("allow file: 1 host", text)
        self.assertIn("example.org", text)

    def test_it_says_whether_moves_by_the_models_pick_are_on(self):
        text, _ = self.preview()
        self.assertIn("moves by the model's pick: on", text)
        self.set_plan("[moves]\nmodel_pick = off\n")
        off = self.approve()[0]
        self.assertIn("moves by the model's pick: off", off)
        self.assertIn("leaves each kept book on the default shelf", off)
        self.assertNotIn("moves each kept book onto a shelf", off)

    def test_it_gives_the_first_12_characters_of_the_fingerprint_and_the_date_of_the_code(self):
        text, _ = self.preview()
        fingerprint, date = crawlapprove.fingerprint(self.cfg, self.kb)
        self.assertIn(fingerprint[:12], text)
        self.assertNotIn(fingerprint[:20], text)
        self.assertIn(date, text)

    def test_it_says_there_is_no_threshold_yet_and_what_that_means(self):
        self.set_plan("")
        text, _ = self.approve()
        self.assertIn("threshold: 0.4", self.preview()[0])
        with open(self.plan, "w", encoding="utf-8") as f:
            f.write(f"[files]\ntopics = {self.topics}\nallow = {self.allow}\n")
        text, _ = self.approve()
        self.assertIn("threshold: not set", text)
        self.assertIn("refuses to fetch", text)

    def test_text_from_the_files_is_cleaned_before_it_is_shown(self):
        self.put("allow.txt", "example.org\n")
        self.put("topics.txt", "[core weight=10]\nplain\n")
        text, _ = self.preview()
        self.assertNotIn("\x1b", text)
        self.assertNotIn("‮", text)


class FileProblems(Case):
    def test_a_plan_that_is_not_valid_is_refused_before_anything_is_stored(self):
        self.put("plan.txt", f"[limits]\nbatch = not a number\n[files]\ntopics = {self.topics}\nallow = {self.allow}\n")
        with self.assertRaises(KbError):
            self.approve()
        self.assertFalse(os.path.exists(self.crawl("approved")))

    def test_the_topics_file_must_exist_and_hold_a_topic_and_the_allow_file_may_be_missing_but_not_bad(self):
        self.set_plan()
        os.remove(self.topics)
        with self.assertRaises(KbError):
            self.approve()
        self.put("topics.txt", "# nothing\n")
        with self.assertRaises(KbError):
            self.approve()
        self.put("topics.txt", TOPICS_TEXT)
        os.remove(self.allow)
        text, digest = self.approve()
        self.assertIn("allow file: 0 hosts", text)
        self.put("allow.txt", "not a host\nsecond bad line\n")
        with self.assertRaises(KbError) as caught:
            self.approve()
        self.assertIn("1", str(caught.exception))
        self.assertNotIn("second bad line", str(caught.exception))
        self.put("allow.txt", "bad host\n" * 30)
        with self.assertRaises(KbError) as caught:
            self.approve()
        self.assertNotIn("21", str(caught.exception))
        for bad in ("https://example.org/\n", "a b\n", "*.example.org\n", "example.org:80\n"):
            self.put("allow.txt", bad)
            with self.assertRaises(KbError):
                self.approve()

    def test_a_file_that_is_a_link_is_refused(self):
        self.set_plan()
        os.remove(self.allow)
        os.symlink(self.topics, self.allow)
        with self.assertRaises(KbError):
            self.approve()
        os.remove(self.allow)
        self.put("allow.txt", ALLOW_TEXT)

    def test_the_summary_describes_the_bytes_that_are_digested_and_a_bad_allow_path_is_a_refusal(self):
        self.set_plan()
        with mock.patch.object(crawlapprove.crawltopics, "read_topics", side_effect=AssertionError("topics must be parsed from the text read once")):
            self.approve()
        os.remove(self.allow)
        os.makedirs(self.allow + "d")
        self.put("plan.txt", PLAN_TEXT + f"[files]\ntopics = {self.topics}\nallow = {self.allow}/x\n")
        with open(self.allow, "w") as f:                     # a file where a folder is needed: ENOTDIR on the allow path
            f.write("x")
        with self.assertRaises(KbError):
            self.approve()


class Storing(Case):
    def test_without_a_digest_nothing_is_written(self):
        self.set_plan()
        text, digest = self.approve()
        self.assertFalse(os.path.exists(self.crawl()))
        self.assertEqual(os.listdir(self.index), [])

    def test_with_the_digest_at_a_terminal_the_approval_is_stored_in_the_agreed_form(self):
        self.set_plan()
        digest = self.approve()[1]
        out = self.approve(digest)
        self.assertEqual(out["digest"], digest)
        approved = self.crawl("approved")
        folder = os.path.join(approved, digest)
        self.assertEqual(sorted(os.listdir(folder)), ["allow.txt", "fingerprint", "plan.txt", "summary.txt", "topics.txt"])
        for name in os.listdir(folder):
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(folder, name)).st_mode), 0o400, name)
        self.assertEqual(stat.S_IMODE(os.stat(folder).st_mode), 0o500)
        self.assertEqual(stat.S_IMODE(os.stat(approved).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(self.crawl()).st_mode), 0o700)
        with open(os.path.join(approved, "current"), "rb") as f:
            self.assertEqual(f.read(), digest.encode() + b"\n")
        with open(os.path.join(folder, "fingerprint"), "rb") as f:
            self.assertEqual(f.read(), crawlapprove.fingerprint(self.cfg, self.kb)[0].encode() + b"\n")
        for name, source in (("plan.txt", self.plan), ("topics.txt", self.topics), ("allow.txt", self.allow)):
            with open(os.path.join(folder, name), "rb") as a, open(source, "rb") as b:
                self.assertEqual(a.read(), b.read())
        with open(os.path.join(folder, "summary.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read().rstrip("\n").splitlines()[-1], "digest: " + digest)
        self.assertEqual([n for n in os.listdir(approved) if n.startswith(".")], [])

    def test_without_a_terminal_with_another_digest_a_bad_digest_or_a_changed_file_nothing_is_stored(self):
        self.set_plan()
        digest = self.approve()[1]
        for kwargs, digest_given in (({"is_tty": lambda: False}, digest), ({}, "0" * 32), ({}, digest.upper()), ({}, digest[:31]), ({}, digest + "0"), ({}, ""), ({}, None.__class__.__name__),
                                     ({}, 5)):
            with self.subTest(kwargs=bool(kwargs), digest=str(digest_given)[:8]):
                with self.assertRaises(KbError):
                    self.approve(digest_given, **kwargs)
                self.assertFalse(os.path.exists(self.crawl("approved")))
        with open(self.plan, "a", encoding="utf-8") as f:
            f.write("# changed after the preview\n")
        with self.assertRaises(KbError):
            self.approve(digest)
        self.assertFalse(os.path.exists(self.crawl("approved")))

    def test_the_terminal_check_reads_both_the_input_and_the_output(self):
        self.set_plan()
        digest = self.approve()[1]
        with mock.patch("sys.stdin.isatty", return_value=True), mock.patch("sys.stdout.isatty", return_value=False):
            with self.assertRaises(KbError):
                crawlapprove.approve(self.index, self.cfg, self.plan, digest=digest, kb_root=self.kb, now=NOW)
        with mock.patch("sys.stdin.isatty", return_value=False), mock.patch("sys.stdout.isatty", return_value=True):
            with self.assertRaises(KbError):
                crawlapprove.approve(self.index, self.cfg, self.plan, digest=digest, kb_root=self.kb, now=NOW)
        with mock.patch("sys.stdin.isatty", return_value=True), mock.patch("sys.stdout.isatty", return_value=True):
            crawlapprove.approve(self.index, self.cfg, self.plan, digest=digest, kb_root=self.kb, now=NOW)

    def test_the_breaker_file_is_created_as_not_tripped_when_there_is_none_and_left_alone_when_there_is(self):
        self.set_plan()
        digest = self.approve()[1]
        self.approve(digest)
        with open(self.crawl("breaker.json"), encoding="utf-8") as f:
            made = json.load(f)
        self.assertEqual(made, {"tripped": False, "reason": "", "kind": "", "at": "2026-11-16T12:00:00Z", "run": ""})
        self.assertEqual(stat.S_IMODE(os.stat(self.crawl("breaker.json")).st_mode), 0o600)
        tripped = {"tripped": True, "reason": "x", "kind": "model_down", "at": "2026-11-16T11:00:00Z", "run": "r1"}
        with open(self.crawl("breaker.json"), "w", encoding="utf-8") as f:
            json.dump(tripped, f)
        self.approve(digest)
        with open(self.crawl("breaker.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), tripped)

    def test_a_file_in_the_place_of_the_breaker_file_that_is_a_link_is_not_followed(self):
        self.set_plan()
        digest = self.approve()[1]
        os.makedirs(self.crawl(), mode=0o700)
        target = os.path.join(self.dir, "elsewhere.json")
        os.symlink(target, self.crawl("breaker.json"))
        self.approve(digest)
        self.assertFalse(os.path.exists(target))

    def test_code_that_changed_between_the_summary_and_the_digest_is_refused_and_the_message_says_so(self):
        self.set_plan()
        digest = self.approve()[1]
        with open(os.path.join(self.kb, "a.py"), "ab") as f:
            f.write(b"# changed after the summary was read")
        with self.assertRaises(KbError) as caught:
            self.approve(digest)
        self.assertIn("the engine's code or model settings", str(caught.exception))
        self.assertFalse(os.path.exists(self.crawl("approved")))
        self.cfg["models"]["gpt"]["model"] = "another"
        fresh = self.approve()[1]
        self.cfg["models"]["gpt"]["model"] = "gpt"
        with self.assertRaises(KbError):
            self.approve(fresh)

    def test_approving_after_the_code_changed_makes_a_new_approval_and_the_old_one_stops_being_current(self):
        self.set_plan()
        first = self.approve()[1]
        self.approve(first)
        with open(os.path.join(self.kb, "a.py"), "ab") as f:
            f.write(b"# changed")
        with self.assertRaises(crawlapprove.NotApproved):
            self.load()                                                       # the old approval no longer holds for the changed code
        second = self.approve()[1]
        self.assertNotEqual(first, second)
        self.approve(second)
        self.assertEqual(self.load()["digest"], second)
        self.assertEqual(sorted(n for n in os.listdir(self.crawl("approved")) if n != "current"), sorted([first, second]))

    def test_a_new_plan_leaves_the_old_approved_copy_and_moves_current(self):
        self.set_plan()
        first = self.approve()[1]
        self.approve(first)
        self.set_plan("[limits]\nbatch = 5\n")
        second = self.approve()[1]
        self.assertNotEqual(first, second)
        self.approve(second)
        self.assertEqual(sorted(n for n in os.listdir(self.crawl("approved")) if n != "current"), sorted([first, second]))
        self.assertEqual(self.load()["digest"], second)

    def test_a_link_a_folder_or_a_loose_mode_where_the_approved_folder_goes_is_refused(self):
        self.set_plan()
        digest = self.approve()[1]
        os.makedirs(self.crawl(), mode=0o700)
        os.symlink(self.dir, self.crawl("approved"))
        with self.assertRaises(KbError):
            self.approve(digest)
        os.remove(self.crawl("approved"))
        os.mkdir(self.crawl("approved"), 0o777)
        os.chmod(self.crawl("approved"), 0o777)
        with self.assertRaises(KbError):
            self.approve(digest)
        os.chmod(self.crawl("approved"), 0o700)
        os.symlink(self.dir, self.crawl("approved", digest))
        with self.assertRaises(KbError):
            self.approve(digest)

    def test_a_failure_while_storing_leaves_no_half_approval_and_the_old_one_stands(self):
        self.set_plan()
        first = self.approve()[1]
        self.approve(first)
        self.set_plan("[limits]\nbatch = 5\n")
        second = self.approve()[1]
        real = os.replace

        def broken(src, dst):
            if os.path.basename(dst) == "current":
                raise OSError(28, "No space left on device")
            return real(src, dst)

        with mock.patch.object(crawlapprove.os, "replace", broken):
            with self.assertRaises(KbError):
                self.approve(second)
        self.assertEqual(self.load()["digest"], first)
        self.assertEqual([n for n in os.listdir(self.crawl("approved")) if n.startswith(".")], [])

    def test_a_failure_while_writing_the_files_leaves_no_half_made_folder(self):
        self.set_plan()
        digest = self.approve()[1]
        real = crawlapprove._write_ro
        calls = []

        def broken(path, data):
            calls.append(path)
            if len(calls) == 3:
                raise OSError(28, "No space left on device")
            return real(path, data)

        with mock.patch.object(crawlapprove, "_write_ro", broken):
            with self.assertRaises(KbError):
                self.approve(digest)
        self.assertEqual(os.listdir(self.crawl("approved")), [])

    def test_a_failure_making_the_breaker_file_says_the_approval_is_stored(self):
        self.set_plan()
        digest = self.approve()[1]
        with mock.patch.object(crawlapprove, "_ensure_breaker", side_effect=OSError(1, "Operation not permitted")):
            with self.assertRaises(KbError) as caught:
                self.approve(digest)
        self.assertIn("is stored", str(caught.exception))
        self.assertIn("tripped", str(caught.exception))

    def test_what_is_said_is_a_plain_line_with_the_digest_and_the_start_of_the_fingerprint_and_no_file_text(self):
        self.set_plan()
        digest = self.approve()[1]
        self.approve(digest)
        said = " ".join(self.say)
        self.assertIn(digest, said)
        self.assertIn(crawlapprove.fingerprint(self.cfg, self.kb)[0][:12], said)
        self.assertNotIn("verification", said)


class Loading(Case):
    def test_an_approved_plan_loads_with_its_parsed_plan_and_the_paths_of_the_approved_copies(self):
        self.approved()
        loaded = self.load()
        self.assertEqual(loaded["plan"]["batch"], 4)
        self.assertEqual(loaded["plan"]["threshold"], 0.4)
        self.assertEqual(loaded["digest"], self.digest())
        self.assertEqual(loaded["fingerprint"], crawlapprove.fingerprint(self.cfg, self.kb)[0])
        for key, name in (("plan_path", "plan.txt"), ("topics_path", "topics.txt"), ("allow_path", "allow.txt")):
            self.assertEqual(loaded[key], self.crawl("approved", loaded["digest"], name))
            self.assertTrue(os.path.exists(loaded[key]))

    def test_the_run_uses_the_approved_copies_and_not_the_files_the_owner_has_since_changed(self):
        self.approved()
        with open(self.topics, "a", encoding="utf-8") as f:
            f.write("a topic added after the approval\n")
        with open(self.plan, "a", encoding="utf-8") as f:
            f.write("[limits]\nbatch = 7\n")
        self.assertEqual(self.load()["plan"]["batch"], 4)

    def test_nothing_approved_a_missing_current_and_a_current_that_is_not_a_digest_refuse(self):
        with self.assertRaises(crawlapprove.NotApproved):
            self.load()
        self.approved()
        current = self.crawl("approved", "current")
        for text in (b"", b"\n", b"short\n", b"0" * 32, b"0" * 32 + b"\n\n", b"G" * 32 + b"\n", ("0" * 32 + "\n").encode().upper(), b"../" + b"0" * 29 + b"\n", ("0" * 32 + "\n").encode()):
            os.chmod(current, 0o600)
            with open(current, "wb") as f:
                f.write(text)
            os.chmod(current, 0o400)
            with self.subTest(text[:12]):
                with self.assertRaises(crawlapprove.NotApproved):
                    self.load()

    def test_a_changed_stored_copy_a_changed_fingerprint_file_a_missing_or_extra_file_and_a_loose_mode_refuse(self):
        self.approved()
        digest = self.digest()
        folder = self.crawl("approved", digest)
        for name in ("plan.txt", "topics.txt", "allow.txt"):
            path = os.path.join(folder, name)
            os.chmod(folder, 0o700)
            os.chmod(path, 0o600)
            with open(path, "rb") as f:
                data = f.read()
            with open(path, "wb") as f:
                f.write(data + b" ")
            os.chmod(path, 0o400)
            os.chmod(folder, 0o500)
            with self.subTest(name):
                with self.assertRaises(crawlapprove.NotApproved):
                    self.load()
            os.chmod(folder, 0o700)
            os.chmod(path, 0o600)
            with open(path, "wb") as f:
                f.write(data)
            os.chmod(path, 0o400)
            os.chmod(folder, 0o500)
        self.load()
        path = os.path.join(folder, "fingerprint")
        os.chmod(folder, 0o700)
        os.chmod(path, 0o600)
        with open(path, "wb") as f:
            f.write(b"0" * 64 + b"\n")
        os.chmod(path, 0o400)
        with self.assertRaises(crawlapprove.NotApproved):
            self.load()
        self.approve(digest)            # approving the same plan again repairs it
        self.load()
        os.chmod(folder, 0o700)
        os.chmod(os.path.join(folder, "plan.txt"), 0o644)
        with self.assertRaises(crawlapprove.NotApproved):
            self.load()
        os.chmod(os.path.join(folder, "plan.txt"), 0o400)
        os.remove(os.path.join(folder, "summary.txt"))
        with self.assertRaises(crawlapprove.NotApproved):
            self.load()
        self.approve(digest)
        os.chmod(folder, 0o700)
        with open(os.path.join(folder, "extra.txt"), "w") as f:
            f.write("x")
        with self.assertRaises(crawlapprove.NotApproved):
            self.load()

    def test_a_link_in_the_place_of_a_file_a_folder_or_current_refuses(self):
        self.approved()
        digest = self.digest()
        folder = self.crawl("approved", digest)
        os.chmod(folder, 0o700)
        os.chmod(os.path.join(folder, "plan.txt"), 0o600)
        os.rename(os.path.join(folder, "plan.txt"), os.path.join(self.dir, "moved-plan.txt"))
        os.chmod(os.path.join(self.dir, "moved-plan.txt"), 0o400)
        os.symlink(os.path.join(self.dir, "moved-plan.txt"), os.path.join(folder, "plan.txt"))
        with self.assertRaises(crawlapprove.NotApproved):
            self.load()
        os.remove(os.path.join(folder, "plan.txt"))
        os.rename(os.path.join(self.dir, "moved-plan.txt"), os.path.join(folder, "plan.txt"))
        os.chmod(os.path.join(folder, "plan.txt"), 0o400)
        os.chmod(folder, 0o500)
        self.load()
        current = self.crawl("approved", "current")
        os.rename(current, os.path.join(self.dir, "moved-current"))
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.dir, "moved-current")).st_mode), 0o400)
        os.symlink(os.path.join(self.dir, "moved-current"), current)
        with self.assertRaises(crawlapprove.NotApproved):
            self.load()
        os.remove(current)
        os.rename(os.path.join(self.dir, "moved-current"), current)
        self.load()
        os.chmod(folder, 0o700)
        os.rename(folder, os.path.join(self.dir, "moved-folder"))
        os.symlink(os.path.join(self.dir, "moved-folder"), folder)
        with self.assertRaises(crawlapprove.NotApproved):
            self.load()

    def test_a_change_of_one_byte_of_the_code_or_the_named_model_settings_refuses_and_any_other_change_does_not(self):
        self.approved()
        self.load()
        for rel in ("a.py", "schemas/card.json", "data/shelf-schema.json", "sub/deep/c.py"):
            full = os.path.join(self.kb, rel)
            with open(full, "rb") as f:
                before = f.read()
            with open(full, "wb") as f:
                f.write(before + b"#")
            with self.subTest(rel):
                with self.assertRaises(crawlapprove.NotApproved) as caught:
                    self.load()
                self.assertIn("approve again", str(caught.exception))
            with open(full, "wb") as f:
                f.write(before)
            self.load()
        changed = copy.deepcopy(self.cfg)
        changed["models"]["gpt"]["model"] = "other"
        with self.assertRaises(crawlapprove.NotApproved):
            crawlapprove.load_approved(self.index, changed, kb_root=self.kb)
        other = copy.deepcopy(self.cfg)
        other["index_root"] = "/elsewhere"
        other["models"]["unused"]["model"] = "another"
        other["tasks"]["theme"] = "gpt"
        crawlapprove.load_approved(self.index, other, kb_root=self.kb)

    def test_a_change_of_the_blacklist_needs_no_approval_and_a_change_of_the_allow_file_does(self):
        self.approved()
        approved = self.load()["digest"]
        with open(self.black, "a", encoding="utf-8") as f:
            f.write("another.example\n")
        self.load()
        self.assertEqual(self.approve()[1], approved)            # the blacklist is not in the digest: no new approval is asked for
        with open(self.allow, "a", encoding="utf-8") as f:
            f.write("another.example\n")
        self.assertEqual(self.load()["digest"], approved)        # a run reads the approved copy, so the changed file is not seen by it
        self.assertNotEqual(self.approve()[1], approved)         # but the owner is asked to approve again before it can be

    def test_a_current_without_its_line_end_or_with_loose_modes_on_any_file_refuses(self):
        self.approved()
        digest = self.digest()
        current = self.crawl("approved", "current")
        os.chmod(current, 0o600)
        with open(current, "wb") as f:
            f.write(digest.encode())
        os.chmod(current, 0o400)
        with self.assertRaises(crawlapprove.NotApproved):
            self.load()
        os.chmod(current, 0o600)
        with open(current, "wb") as f:
            f.write(digest.encode() + b"\n")
        os.chmod(current, 0o400)
        self.load()
        folder = self.crawl("approved", digest)
        os.chmod(folder, 0o700)
        for name in NAMES_STORED:
            for mode in (0o600, 0o440):
                os.chmod(os.path.join(folder, name), mode)
                with self.subTest(name=name, mode=mode):
                    with self.assertRaises(crawlapprove.NotApproved):
                        self.load()
                os.chmod(os.path.join(folder, name), 0o400)
        os.chmod(folder, 0o500)
        self.load()

    def test_a_code_tree_that_cannot_be_read_now_refuses_and_does_not_fall_back_to_the_stored_fingerprint(self):
        self.approved()
        os.symlink(os.path.join(self.kb, "a.py"), os.path.join(self.kb, "link.py"))
        with self.assertRaises(crawlapprove.NotApproved) as caught:
            self.load()
        self.assertIn("approve again", str(caught.exception))

    def test_a_plan_that_the_reader_would_refuse_is_not_loaded(self):
        self.approved()
        digest = self.digest()
        folder = self.crawl("approved", digest)
        path = os.path.join(folder, "plan.txt")
        bad = b"[limits]\nbatch = oops\n"
        os.chmod(folder, 0o700)
        os.chmod(path, 0o600)
        with open(path, "wb") as f:
            f.write(bad)
        os.chmod(path, 0o400)
        os.chmod(folder, 0o500)
        with self.assertRaises(crawlapprove.NotApproved):
            self.load()

    def test_not_approved_is_a_plain_refusal_with_a_fixed_reason_a_log_line_can_carry(self):
        try:
            self.load()
        except crawlapprove.NotApproved as e:
            self.assertIsInstance(e, KbError)
            self.assertLess(len(str(e)), 200)
            self.assertNotIn(self.dir, str(e))


class Hardening(Case):
    """Findings F2, F3 and F9 of the security review of plan R1."""

    def test_the_plan_a_step_gets_names_the_approved_copies_of_the_topics_and_the_allow_file_and_not_the_live_ones(self):
        self.approved()
        with open(self.topics, "a", encoding="utf-8") as f:
            f.write("a topic added after the approval\n")
        with open(self.allow, "a", encoding="utf-8") as f:
            f.write("evil.example\n")
        loaded = self.load()
        self.assertEqual(loaded["plan"]["topics"], loaded["topics_path"])
        self.assertEqual(loaded["plan"]["allow"], loaded["allow_path"])
        self.assertEqual(open(loaded["plan"]["allow"], encoding="utf-8").read(), ALLOW_TEXT)
        self.assertNotIn("evil.example", open(loaded["plan"]["allow"], encoding="utf-8").read())
        self.assertNotIn("a topic added", open(loaded["plan"]["topics"], encoding="utf-8").read())
        self.assertEqual(loaded["plan"]["blacklist"], self.black)             # the blacklist is the owner's and is read afresh

    def test_an_approval_made_under_the_first_recipe_of_the_digest_is_refused_and_says_to_approve_again(self):
        self.approved()
        new = self.load()["digest"]
        folder = self.crawl("approved", new)
        planb, topicsb, allowb = (open(os.path.join(folder, n), "rb").read() for n in ("plan.txt", "topics.txt", "allow.txt"))
        h = hashlib.sha256(b"kb-crawl-approval-1\n")
        for name, data in (("plan", planb), ("topics", topicsb), ("allow", allowb)):
            h.update(b"%s:%d:" % (name.encode("ascii"), len(data)))
            h.update(data)
            h.update(b"\n")
        old = h.hexdigest()[:32]
        self.assertNotEqual(old, new)
        os.chmod(self.crawl("approved"), 0o700)
        os.rename(folder, self.crawl("approved", old))
        os.chmod(self.crawl("approved", "current"), 0o600)
        with open(self.crawl("approved", "current"), "w") as f:
            f.write(old + "\n")
        os.chmod(self.crawl("approved", "current"), 0o400)
        with self.assertRaises(crawlapprove.NotApproved) as caught:
            self.load()
        self.assertIn("approve again", str(caught.exception))

    def test_a_stored_fingerprint_that_was_changed_to_match_changed_code_is_refused_because_the_digest_covers_it(self):
        self.approved()
        digest = self.load()["digest"]
        with open(os.path.join(self.kb, "a.py"), "ab") as f:
            f.write(b"# changed")
        forged = crawlapprove.fingerprint(self.cfg, self.kb)[0]
        folder = self.crawl("approved", digest)
        os.chmod(folder, 0o700)
        path = os.path.join(folder, "fingerprint")
        os.chmod(path, 0o600)
        with open(path, "wb") as f:
            f.write(forged.encode() + b"\n")
        os.chmod(path, 0o400)
        os.chmod(folder, 0o500)
        with self.assertRaises(crawlapprove.NotApproved):
            self.load()

    def test_the_breaker_line_says_a_model_entry_and_its_minutes_and_not_the_model_server(self):
        self.set_plan()
        text, _ = self.approve()
        line = next(x for x in text.splitlines() if x.startswith("Circuit breaker:"))
        self.assertIn("or a model entry that has not answered for 30 minutes;", line)
        self.assertNotIn("model server down", text)
        self.assertIn("a site that refuses 3 times in a day is stopped for the day.", line)

    def test_the_summary_says_that_no_pdf_is_taken_by_default_and_what_limits_apply_when_the_plan_sets_them(self):
        self.set_plan()
        text, _ = self.approve()
        self.assertIn("PDF files: none are taken (pdf_max_mb is 0)", text)
        self.set_plan(PLAN_TEXT + "[pdf]\npdf_max_mb = 20\ntool_rss_mb = 1536\n")
        text, _ = self.approve()
        self.assertIn("PDF files: taken up to 20 MB each, scanned before any conversion (a file with a finding in the hold list above is held), and converted in a tool that is killed above 1536 MB of memory", text)
        self.assertNotIn("none are taken", text)

    def test_a_change_of_the_pdf_keys_changes_the_digest(self):
        self.set_plan()
        _, first = self.approve()
        self.set_plan(PLAN_TEXT + "[pdf]\npdf_max_mb = 20\n")
        _, second = self.approve()
        self.set_plan(PLAN_TEXT + "[pdf]\npdf_max_mb = 20\ntool_rss_mb = 4096\n")
        _, third = self.approve()
        self.assertEqual(len({first, second, third}), 3)

    def test_the_minutes_of_the_breaker_line_are_the_plans_own(self):
        self.set_plan(PLAN_TEXT + "[breaker]\nmodel_down_minutes = 45\n")
        text, _ = self.approve()
        self.assertIn("a model entry that has not answered for 45 minutes", text)

    def test_the_summary_lists_every_allow_host_one_a_line_and_says_how_many(self):
        hosts = [f"host{i}.example" for i in range(60)]
        self.put("allow.txt", "\n".join(hosts) + "\n")
        self.set_plan()
        text, _ = self.approve()
        for host in hosts:
            self.assertIn("    " + host + "\n", text + "\n", host)
        self.assertIn("60 hosts", text)
        self.assertIn("every one listed", text)
        self.assertNotIn("and more", text)

    def test_an_allow_file_with_more_hosts_than_a_summary_lists_in_full_is_refused_for_approval(self):
        limit = crawlapprove.MAX_ALLOW_HOSTS
        self.assertEqual(limit, 500)
        self.put("allow.txt", "\n".join(f"h{i}.example" for i in range(limit)) + "\n")
        self.set_plan()
        self.assertIn(f"{limit} hosts", self.approve()[0])
        self.put("allow.txt", "\n".join(f"h{i}.example" for i in range(limit + 1)) + "\n")
        with self.assertRaises(KbError) as caught:
            self.approve()
        self.assertIn(str(limit + 1), str(caught.exception))
        self.assertFalse(os.path.exists(self.crawl("approved")))


class Wiring(Case):
    def test_the_module_makes_no_request_and_reads_no_secret_file(self):
        with open(os.path.join(ENGINE_DIR, "kb", "crawlapprove.py"), encoding="utf-8") as f:
            source = f.read()
        for word in ("socket", "urllib.request", "http.client", "subprocess", "webclient", "urlhaus.key", "os.environ", "getenv"):
            self.assertNotIn(word, source, word)

    def test_the_command_is_registered_with_a_plan_option_and_a_digest_option_and_no_other(self):
        from kb import __main__ as cli
        with mock.patch.object(crawlapprove, "approve", return_value=("a summary\ndigest: " + "a" * 32, "a" * 32)) as approve, \
                mock.patch.object(cli.config, "load", return_value=self.cfg), mock.patch.object(cli.config, "config_dir", return_value=self.dir), \
                mock.patch("builtins.print") as shown:
            self.assertEqual(cli.main(["crawl-approve", "--plan", self.plan]), 0)
            self.assertEqual(approve.call_args.args[2], self.plan)
            self.assertIsNone(approve.call_args.kwargs.get("digest"))
            self.assertIn("digest: " + "a" * 32, " ".join(str(c.args[0]) for c in shown.call_args_list))
        with mock.patch.object(crawlapprove, "approve", return_value={"digest": "a" * 32, "fingerprint": "b" * 12}) as approve, \
                mock.patch.object(cli.config, "load", return_value=self.cfg), mock.patch.object(cli.config, "config_dir", return_value=self.dir), mock.patch("builtins.print"):
            self.assertEqual(cli.main(["crawl-approve", "--digest", "a" * 32]), 0)
            self.assertEqual(approve.call_args.args[2], os.path.join(self.dir, "crawl-plan.txt"))
            self.assertEqual(approve.call_args.kwargs["digest"], "a" * 32)
        with self.assertRaises(SystemExit):
            with mock.patch("sys.stderr"):
                cli.main(["crawl-approve", "--plan", self.plan, "--run"])


if __name__ == "__main__":
    unittest.main()
