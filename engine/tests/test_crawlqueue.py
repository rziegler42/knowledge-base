"""The candidate queue of the unattended crawl (`kb/crawlqueue.py`; `docs/specs/population.md`, "The queue and the seen list").

No test opens a socket or reads the owner's library. The address functions that `webaddr` will provide are fakes here."""

import os
import re
import sqlite3
import stat
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path

from engine.tests import ENGINE_DIR

from kb import KbError, crawlqueue

REPO = Path(ENGINE_DIR).parent
SPEC = REPO / "docs" / "specs" / "population.md"

# The spec's table as it is written there, copied here so that a change to either the spec or the module is seen (a test below
# also reads the spec's own text).
EXPECTED_CANDIDATES = [
    # (name, type, notnull, default, primary key)
    ("id", "INTEGER", 0, None, 1),
    ("identity_key", "TEXT", 1, None, 0),
    ("address", "TEXT", 1, None, 0),
    ("source", "TEXT", 1, None, 0),
    ("source_id", "TEXT", 0, None, 0),
    ("found_from", "TEXT", 0, None, 0),
    ("topic", "TEXT", 0, None, 0),
    ("weight", "INTEGER", 0, None, 0),
    ("depth", "INTEGER", 1, "0", 0),
    ("domain", "TEXT", 0, None, 0),
    ("ip", "TEXT", 0, None, 0),
    ("status", "TEXT", 1, None, 0),
    ("reason", "TEXT", 0, None, 0),
    ("score", "REAL", 0, None, 0),
    ("book_id", "TEXT", 0, None, 0),
    ("tries", "INTEGER", 1, "0", 0),
    ("run_id", "TEXT", 0, None, 0),
    ("added", "TEXT", 1, None, 0),
    ("updated", "TEXT", 1, None, 0),
    ("next_try", "TEXT", 0, None, 0),
]
EXPECTED_COUNTERS = [("day", "TEXT", 0, None, 1), ("key", "TEXT", 0, None, 2), ("n", "INTEGER", 0, None, 0)]

NOW = "2026-11-16T10:00:00Z"
LIMITS = {"queued_total": 100, "queued_per_domain": 50}


def fake_canon(address):
    """A stand-in for `webaddr.canon_address`: lower-cases the host, drops a fragment, refuses anything but http and https."""
    if not re.match(r"https?://", address, re.I):
        raise KbError("not a web address")
    scheme, rest = address.split("://", 1)
    host, _, tail = rest.partition("/")
    return f"{scheme.lower()}://{host.lower().rstrip('.')}/{tail.split('#')[0]}"


def fake_site(host):
    """A stand-in for `webaddr.site_of`: the last two labels."""
    return ".".join(host.split(".")[-2:])


def candidate(address="https://example.org/a", **kw):
    row = {"address": address, "source": "openalex"}
    row.update(kw)
    if "identity_key" not in row:
        try:
            row["identity_key"] = fake_canon(address)
        except KbError:
            pass
    return row


class QueueCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = self.tmp.name
        self.conn = crawlqueue.connect(self.folder)
        self.addCleanup(self.conn.close)

    def add(self, row=None, limits=None, now=NOW, **kw):
        return crawlqueue.enqueue(self.conn, row or candidate(**kw), canon_address=fake_canon, site_of=fake_site,
                                  limits=limits or LIMITS, now=now)

    def rows(self, where=""):
        with closing(sqlite3.connect(os.path.join(self.folder, crawlqueue.FILE))) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(f"SELECT * FROM candidates {where} ORDER BY id")]


class ConnectTest(QueueCase):
    def test_the_file_is_created_in_the_folder_with_mode_600(self):
        path = os.path.join(self.folder, "candidates.sqlite")
        self.assertEqual(crawlqueue.FILE, "candidates.sqlite")
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_the_pragmas_are_those_of_the_spec(self):
        self.assertEqual(self.conn.execute("PRAGMA user_version").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(self.conn.execute("PRAGMA busy_timeout").fetchone()[0], 30000)

    def test_the_tables_have_the_columns_of_the_spec_one_by_one(self):
        for table, expected in (("candidates", EXPECTED_CANDIDATES), ("counters", EXPECTED_COUNTERS)):
            got = [(r[1], r[2], r[3], r[4], r[5]) for r in self.conn.execute(f"PRAGMA table_info({table})")]
            self.assertEqual(got, expected, table)
        names = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertEqual(names, {"candidates", "counters"})

    def test_the_identity_key_is_unique(self):
        self.assertEqual(self.add(), "queued")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO candidates (identity_key, address, source, status, added, updated) "
                              "VALUES ('https://example.org/a', 'x', 'arxiv', 'queued', 'n', 'n')")

    def test_a_second_connect_accepts_the_file_and_changes_nothing(self):
        self.add()
        with closing(crawlqueue.connect(self.folder)) as second:
            self.assertEqual(second.execute("SELECT COUNT(*) FROM candidates").fetchone()[0], 1)
            self.assertEqual(second.execute("PRAGMA busy_timeout").fetchone()[0], 30000)
            self.assertEqual(second.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_the_files_beside_it_that_wal_mode_makes_are_not_open_to_others(self):
        self.add()
        beside = [os.path.join(self.folder, crawlqueue.FILE + suffix) for suffix in ("-wal", "-shm")]
        self.assertTrue(any(os.path.exists(p) for p in beside))
        for path in beside:
            if os.path.exists(path):
                self.assertEqual(stat.S_IMODE(os.stat(path).st_mode) & 0o077, 0, path)

    def test_a_file_with_another_user_version_is_refused(self):
        self.conn.execute("PRAGMA user_version = 2")
        with self.assertRaises(KbError):
            crawlqueue.connect(self.folder)

    def test_a_file_with_a_missing_extra_or_changed_column_is_refused(self):
        for statement in ("ALTER TABLE candidates DROP COLUMN ip",
                          "ALTER TABLE candidates ADD COLUMN extra TEXT",
                          "ALTER TABLE candidates RENAME COLUMN ip TO address_ip",
                          "ALTER TABLE counters ADD COLUMN extra TEXT"):
            with self.subTest(statement):
                with tempfile.TemporaryDirectory() as folder:
                    crawlqueue.connect(folder).close()
                    with closing(sqlite3.connect(os.path.join(folder, crawlqueue.FILE))) as raw:
                        raw.execute(statement)
                    with self.assertRaises(KbError):
                        crawlqueue.connect(folder)

    def test_a_table_with_a_changed_type_not_null_default_or_extra_constraint_is_refused(self):
        first, second = ContractTest.spec_ddl(None)
        for old, new in (("weight INTEGER", "weight TEXT"), ("depth INTEGER NOT NULL DEFAULT 0", "depth INTEGER NOT NULL DEFAULT 1"),
                         ("source TEXT NOT NULL", "source TEXT"), ("added TEXT NOT NULL", "added TEXT NOT NULL CHECK (added <> '')"),
                         ("next_try TEXT)", "next_try TEXT) STRICT"), ("next_try TEXT)", "next_try TEXT) WITHOUT ROWID"),
                         ("score REAL", "score REAL GENERATED ALWAYS AS (1) VIRTUAL")):
            with self.subTest(new):
                self.assertIn(old, first)
                with tempfile.TemporaryDirectory() as folder:
                    path = os.path.join(folder, crawlqueue.FILE)
                    with closing(sqlite3.connect(path)) as raw:
                        try:
                            raw.execute(first.replace(old, new))
                        except sqlite3.Error:
                            continue  # this SQLite does not take the variant, so no file can hold it
                        raw.execute(second)
                        raw.execute("PRAGMA user_version = 1")
                    os.chmod(path, 0o600)
                    with self.assertRaises(KbError):
                        crawlqueue.connect(folder)

    def test_a_file_with_only_some_of_the_columns_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, crawlqueue.FILE)
            with closing(sqlite3.connect(path)) as raw:
                raw.execute("CREATE TABLE candidates (id INTEGER PRIMARY KEY, identity_key TEXT UNIQUE NOT NULL)")
                raw.execute("CREATE TABLE counters (day TEXT, key TEXT, n INTEGER, PRIMARY KEY(day, key))")
                raw.execute("PRAGMA user_version = 1")
            os.chmod(path, 0o600)
            with self.assertRaises(KbError):
                crawlqueue.connect(folder)

    def test_a_trigger_or_a_view_that_the_engine_did_not_put_there_is_refused(self):
        for statement in ("CREATE VIEW v AS SELECT 1",
                          "CREATE TRIGGER t AFTER INSERT ON counters BEGIN SELECT 1; END"):
            with self.subTest(statement):
                with tempfile.TemporaryDirectory() as folder:
                    crawlqueue.connect(folder).close()
                    with closing(sqlite3.connect(os.path.join(folder, crawlqueue.FILE))) as raw:
                        raw.execute(statement)
                    with self.assertRaises(KbError):
                        crawlqueue.connect(folder)

    def test_a_table_without_the_unique_identity_key_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, crawlqueue.FILE)
            with closing(sqlite3.connect(path)) as raw:
                first, second = ContractTest.spec_ddl(None)
                raw.execute(first.replace("identity_key TEXT UNIQUE NOT NULL", "identity_key TEXT NOT NULL"))
                raw.execute(second)
                raw.execute("PRAGMA user_version = 1")
            os.chmod(path, 0o600)
            with self.assertRaises(KbError):
                crawlqueue.connect(folder)

    def test_an_extra_table_or_index_is_refused(self):
        for statement in ("CREATE TABLE extra (x)", "CREATE INDEX extra_index ON candidates (source)"):
            with self.subTest(statement):
                with tempfile.TemporaryDirectory() as folder:
                    crawlqueue.connect(folder).close()
                    with closing(sqlite3.connect(os.path.join(folder, crawlqueue.FILE))) as raw:
                        raw.execute(statement)
                    with self.assertRaises(KbError):
                        crawlqueue.connect(folder)

    def test_a_pipe_that_only_the_owner_can_use_is_refused_and_not_opened(self):
        with tempfile.TemporaryDirectory() as folder:
            os.mkfifo(os.path.join(folder, crawlqueue.FILE), 0o600)
            with self.assertRaises(KbError):
                crawlqueue.connect(folder)

    def test_a_database_that_holds_something_else_is_refused_and_not_changed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, crawlqueue.FILE)
            with closing(sqlite3.connect(path)) as raw:
                raw.execute("CREATE TABLE other (x)")
            os.chmod(path, 0o600)
            with self.assertRaises(KbError):
                crawlqueue.connect(folder)
            with closing(sqlite3.connect(path)) as raw:
                self.assertEqual([r[0] for r in raw.execute("SELECT name FROM sqlite_master")], ["other"])

    def test_a_file_that_is_not_a_database_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, crawlqueue.FILE)
            with open(path, "wb") as f:
                f.write(b"not a database at all, " * 20)
            with self.assertRaises(KbError):
                crawlqueue.connect(folder)

    def test_a_link_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            target = os.path.join(folder, "elsewhere.sqlite")
            crawlqueue.connect(folder).close()
            os.rename(os.path.join(folder, crawlqueue.FILE), target)
            os.symlink(target, os.path.join(folder, crawlqueue.FILE))
            with self.assertRaises(KbError):
                crawlqueue.connect(folder)

    def test_a_path_that_is_not_a_regular_file_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            os.mkdir(os.path.join(folder, crawlqueue.FILE))
            with self.assertRaises(KbError):
                crawlqueue.connect(folder)
        with tempfile.TemporaryDirectory() as folder:
            os.mkfifo(os.path.join(folder, crawlqueue.FILE))
            with self.assertRaises(KbError):
                crawlqueue.connect(folder)

    def test_a_folder_that_is_missing_is_refused(self):
        with self.assertRaises(KbError):
            crawlqueue.connect(os.path.join(self.folder, "no", "such", "folder"))

    def test_a_file_that_others_can_read_is_refused(self):
        path = os.path.join(self.folder, crawlqueue.FILE)
        os.chmod(path, 0o644)
        with self.assertRaises(KbError):
            crawlqueue.connect(self.folder)

    def test_two_connections_can_write_at_once(self):
        errors = []

        def work(n):
            try:
                with closing(crawlqueue.connect(self.folder)) as conn:
                    for i in range(20):
                        crawlqueue.enqueue(conn, candidate(f"https://site{n}.org/{i}"), canon_address=fake_canon,
                                           site_of=fake_site, limits={"queued_total": 1000, "queued_per_domain": 100}, now=NOW)
            except BaseException as e:  # reported by the test thread
                errors.append(e)

        threads = [threading.Thread(target=work, args=(n,)) for n in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(self.rows()), 40)

    def test_two_first_openers_at_once_make_one_good_file(self):
        with tempfile.TemporaryDirectory() as folder:
            results = []

            def first():
                try:
                    crawlqueue.connect(folder).close()
                    results.append("ok")
                except BaseException as e:
                    results.append(e)

            threads = [threading.Thread(target=first) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(results, ["ok"] * 4)
            with closing(crawlqueue.connect(folder)):
                pass


class ContractTest(unittest.TestCase):
    """The table as `population.md` writes it, taken from the spec's own text, is accepted by `connect`, and `connect` makes the
    same table. A change to either is seen here."""

    def spec_ddl(self):
        text = SPEC.read_text(encoding="utf-8")
        start = text.index("candidates(\n")
        end = text.index("\n", text.index("counters(day TEXT", start))
        block = text[start:end]
        lines = [re.sub(r"\s*--.*$", "", line) for line in block.splitlines()]
        body = "\n".join(lines)
        first, second = body.split("counters(", 1)
        return "CREATE TABLE " + first.strip(), "CREATE TABLE counters(" + second.strip()

    def shape(self, conn):
        out = {}
        for table in ("candidates", "counters"):
            out[table] = [(r[1], r[2], r[3], r[4], r[5]) for r in conn.execute(f"PRAGMA table_info({table})")]
        return out

    def test_the_spec_table_is_what_the_test_and_the_module_expect(self):
        first, second = self.spec_ddl()
        with closing(sqlite3.connect(":memory:")) as conn:
            conn.execute(first)
            conn.execute(second)
            got = self.shape(conn)
        self.assertEqual(got["candidates"], EXPECTED_CANDIDATES)
        self.assertEqual(got["counters"], EXPECTED_COUNTERS)

    def test_connect_accepts_a_file_built_from_the_spec_text(self):
        first, second = self.spec_ddl()
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, crawlqueue.FILE)
            with closing(sqlite3.connect(path)) as raw:
                raw.execute(first)
                raw.execute(second)
                raw.execute("PRAGMA user_version = 1")
                raw.execute("PRAGMA journal_mode = WAL")
            os.chmod(path, 0o600)
            with closing(crawlqueue.connect(folder)) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0], 0)

    def test_connect_makes_the_table_the_spec_text_gives(self):
        first, second = self.spec_ddl()
        with closing(sqlite3.connect(":memory:")) as spec, tempfile.TemporaryDirectory() as folder:
            spec.execute(first)
            spec.execute(second)
            with closing(crawlqueue.connect(folder)) as made:
                self.assertEqual(self.shape(made), self.shape(spec))


class EnqueueTest(QueueCase):
    def test_a_new_address_is_queued_with_its_fields_set(self):
        result = self.add(candidate("https://Example.org/a#part", source_id="openalex:W1", found_from="a query", topic="t", weight=5,
                                    depth=1))
        self.assertEqual(result, "queued")
        (row,) = self.rows()
        self.assertEqual(row["status"], "queued")
        self.assertEqual(row["address"], "https://example.org/a")  # the canonical form
        self.assertEqual(row["identity_key"], "https://example.org/a")
        self.assertEqual(row["domain"], "example.org")
        self.assertEqual((row["source"], row["source_id"], row["found_from"], row["topic"], row["weight"], row["depth"]),
                         ("openalex", "openalex:W1", "a query", "t", 5, 1))
        self.assertEqual((row["added"], row["updated"], row["tries"]), (NOW, NOW, 0))
        for empty in ("reason", "score", "book_id", "run_id", "next_try", "ip"):
            self.assertIsNone(row[empty], empty)

    def test_depth_defaults_to_zero(self):
        self.add()
        self.assertEqual(self.rows()[0]["depth"], 0)

    def test_an_arxiv_identity_key_is_kept_as_given(self):
        row = candidate("https://arxiv.org/abs/2401.00001", source="arxiv", identity_key="arxiv:2401.00001")
        self.assertEqual(self.add(row), "queued")
        self.assertEqual(self.rows()[0]["identity_key"], "arxiv:2401.00001")
        self.assertEqual(self.rows()[0]["domain"], "arxiv.org")

    def test_the_identity_key_is_the_canonical_address_when_none_is_given(self):
        row = {"address": "https://Example.org/A#x", "source": "wikipedia"}
        self.assertEqual(self.add(row), "queued")
        self.assertEqual(self.rows()[0]["identity_key"], "https://example.org/A")

    def test_the_same_identity_key_again_is_a_duplicate_and_changes_nothing(self):
        self.add(candidate(topic="first", weight=1))
        before = self.rows()
        self.assertEqual(self.add(candidate("https://EXAMPLE.org/a#frag", topic="second", weight=9), now="2026-11-17T00:00:00Z"),
                         "duplicate")
        self.assertEqual(self.rows(), before)

    def test_the_other_sources_of_one_address_are_one_row(self):
        self.add(candidate(source="openalex"))
        self.assertEqual(self.add(candidate(source="wikipedia")), "duplicate")
        self.assertEqual(len(self.rows()), 1)

    def test_an_address_over_2048_characters_is_too_long_and_not_stored(self):
        long = "https://example.org/" + "a" * 2040
        self.assertEqual(len(long), 2060)
        self.assertEqual(self.add(candidate(long, identity_key="k")), "too_long")
        self.assertEqual(self.rows(), [])

    def test_an_address_of_exactly_2048_characters_is_taken(self):
        address = "https://example.org/" + "a" * (2048 - len("https://example.org/"))
        self.assertEqual(len(address), 2048)
        self.assertEqual(self.add(candidate(address)), "queued")

    def test_the_length_is_checked_before_the_address_is_canonicalised(self):
        calls = []

        def canon(address):
            calls.append(address)
            return fake_canon(address)

        result = crawlqueue.enqueue(self.conn, candidate("https://example.org/" + "a" * 5000, identity_key="k"), canon_address=canon,
                                    site_of=fake_site, limits=LIMITS, now=NOW)
        self.assertEqual(result, "too_long")
        self.assertEqual(calls, [])

    def test_an_identity_key_over_2048_characters_is_too_long(self):
        self.assertEqual(self.add(candidate("https://example.org/a", identity_key="k" * 2049)), "too_long")
        self.assertEqual(self.add(candidate("https://example.org/b", identity_key="k" * 2048)), "queued")

    def test_an_address_that_grows_over_2048_characters_when_canonicalised_is_too_long(self):
        def canon(address):
            return fake_canon(address) + "x" * 100

        result = crawlqueue.enqueue(self.conn, candidate("https://example.org/" + "a" * 1990, identity_key="k"), canon_address=canon,
                                    site_of=fake_site, limits=LIMITS, now=NOW)
        self.assertEqual(result, "too_long")
        self.assertEqual(self.rows(), [])

    def test_a_canonical_address_with_no_host_is_refused(self):
        result = crawlqueue.enqueue(self.conn, candidate(identity_key="k"), canon_address=lambda a: "https:///a", site_of=fake_site,
                                    limits=LIMITS, now=NOW)
        self.assertEqual(result, "refused")
        self.assertEqual(self.rows(), [])

    def test_a_text_field_may_be_1000_characters_and_not_more(self):
        self.assertEqual(self.add(candidate(topic="t" * 1000)), "queued")
        with self.assertRaises(KbError):
            self.add(candidate("https://example.org/b", topic="t" * 1001))

    def test_a_number_beyond_what_sqlite_holds_is_a_refusal_of_ours(self):
        for key, value in (("weight", 2**63), ("depth", 2**63), ("weight", 1_000_001), ("depth", 1001)):
            with self.subTest(key=key, value=value):
                with self.assertRaises(KbError):
                    self.add(candidate(**{key: value}))
        self.assertEqual(self.add(candidate(weight=1_000_000, depth=1000)), "queued")

    def test_an_ip_must_be_an_ip_address(self):
        for ip in ("not an ip", "999.1.1.1", "1.2.3", "example.org"):
            with self.subTest(ip=ip):
                with self.assertRaises(KbError):
                    self.add(candidate(ip=ip))
        self.assertEqual(self.add(candidate("https://example.org/a", ip="93.184.216.34")), "queued")
        self.assertEqual(self.add(candidate("https://example.org/b", ip="2606:2800:220:1::1")), "queued")

    def test_what_the_canonicaliser_gives_back_is_checked_too(self):
        for given in ("https://[abc/x", 5, None, "https://example.org/a‮b", "https://example.org/\x00"):
            with self.subTest(given=given):
                result = crawlqueue.enqueue(self.conn, candidate(identity_key="k"), canon_address=lambda a, g=given: g,
                                            site_of=fake_site, limits=LIMITS, now=NOW)
                self.assertEqual(result, "refused")
        self.assertEqual(self.rows(), [])

    def test_a_site_function_that_gives_nothing_usable_is_a_refusal(self):
        for site in (None, "", 5):
            with self.subTest(site=site):
                result = crawlqueue.enqueue(self.conn, candidate(identity_key="k"), canon_address=fake_canon,
                                            site_of=lambda h, s=site: s, limits=LIMITS, now=NOW)
                self.assertEqual(result, "refused")
        self.assertEqual(self.rows(), [])

    def test_a_weight_is_at_least_one(self):
        with self.assertRaises(KbError):
            self.add(candidate(weight=0))
        self.assertEqual(self.add(candidate(weight=1)), "queued")

    def test_a_time_that_is_not_a_utc_time_is_refused(self):
        for now in ("2026-11-16", "2026-11-16 10:00:00", "", None, 5, "2026-11-16T10:00:00+01:00"):
            with self.subTest(now=now):
                with self.assertRaises(KbError):
                    self.add(now=now)
        self.assertEqual(self.rows(), [])

    def test_limits_that_are_not_the_two_whole_numbers_are_refused(self):
        for limits in ({}, {"queued_total": 1}, {"queued_total": 1, "queued_per_domain": -1},
                       {"queued_total": "9", "queued_per_domain": 1}, {"queued_total": 1, "queued_per_domain": 1, "x": 1}, None):
            with self.subTest(limits=limits):
                with self.assertRaises(KbError):
                    crawlqueue.enqueue(self.conn, candidate(), canon_address=fake_canon, site_of=fake_site, limits=limits, now=NOW)
        self.assertEqual(self.rows(), [])

    def test_the_total_cap_stops_the_queue(self):
        limits = {"queued_total": 3, "queued_per_domain": 50}
        for i in range(3):
            self.assertEqual(self.add(candidate(f"https://s{i}.org/x"), limits=limits), "queued")
        self.assertEqual(self.add(candidate("https://s9.org/x"), limits=limits), "capped")
        self.assertEqual(len(self.rows()), 3)

    def test_the_per_domain_cap_counts_the_registrable_domain(self):
        limits = {"queued_total": 100, "queued_per_domain": 2}
        self.assertEqual(self.add(candidate("https://a.example.org/1"), limits=limits), "queued")
        self.assertEqual(self.add(candidate("https://b.example.org/1"), limits=limits), "queued")
        self.assertEqual(self.add(candidate("https://c.example.org/1"), limits=limits), "capped")
        self.assertEqual(self.add(candidate("https://other.net/1"), limits=limits), "queued")

    def test_only_queued_rows_count_against_the_caps(self):
        limits = {"queued_total": 1, "queued_per_domain": 1}
        self.conn.execute("INSERT INTO candidates (identity_key, address, source, domain, status, added, updated) "
                          "VALUES ('k1', 'https://example.org/old', 'arxiv', 'example.org', 'kept', 'n', 'n')")
        self.conn.execute("INSERT INTO candidates (identity_key, address, source, domain, status, added, updated) "
                          "VALUES ('k2', 'https://example.org/old2', 'arxiv', 'example.org', 'rejected', 'n', 'n')")
        self.assertEqual(self.add(candidate("https://example.org/new"), limits=limits), "queued")

    def test_a_duplicate_is_reported_before_a_cap(self):
        limits = {"queued_total": 1, "queued_per_domain": 1}
        self.add(limits=limits)
        self.assertEqual(self.add(limits=limits), "duplicate")

    def test_an_address_the_canonicaliser_refuses_is_refused_and_not_stored(self):
        self.assertEqual(self.add(candidate("ftp://example.org/a", identity_key="k")), "refused")
        self.assertEqual(self.rows(), [])

    def test_unknown_keys_are_refused(self):
        for key in ("status", "reason", "id", "added", "domain", "tries", "book_id", "next_try", "colour"):
            with self.subTest(key):
                with self.assertRaises(KbError):
                    self.add(candidate(**{key: "x"}))
        self.assertEqual(self.rows(), [])

    def test_missing_required_keys_and_bad_values_are_refused(self):
        for row in ({"address": "https://example.org/a"},
                    {"address": "https://example.org/a", "source": "gopher"},
                    {"address": "https://example.org/a", "source": "openalex", "weight": "5"},
                    {"address": "https://example.org/a", "source": "openalex", "depth": -1},
                    {"address": "https://example.org/a", "source": "openalex", "depth": True},
                    {"address": "https://example.org/a", "source": "openalex", "topic": "a\x00b"},
                    {"address": "https://example.org/a", "source": "openalex", "found_from": "a‮b"},
                    {"address": "https://example.org/a", "source": "openalex", "topic": "x" * 3000},
                    {"address": 5, "source": "openalex"},
                    "not a dict"):
            with self.subTest(row=row):
                with self.assertRaises(KbError):
                    self.add(row)
        self.assertEqual(self.rows(), [])

    def test_the_defaults_import_webaddr_when_called(self):
        # webaddr is built by another plan; until it exists the default is a refusal that says so, never a silent pass
        try:
            import kb.webaddr  # noqa: F401
        except ImportError:
            with self.assertRaises(KbError):
                crawlqueue.enqueue(self.conn, candidate(), limits=LIMITS, now=NOW)
        else:
            self.assertIn(crawlqueue.enqueue(self.conn, candidate(), limits=LIMITS, now=NOW), ("queued", "refused"))

    def test_no_function_deletes_a_row_or_changes_an_existing_one(self):
        source = Path(crawlqueue.__file__).read_text(encoding="utf-8")
        self.assertNotRegex(source, r"(?i)\bDELETE\s+FROM\b")
        self.assertNotRegex(source, r"(?i)\bUPDATE\s+\w+\s+SET\b|\bDO\s+UPDATE\b|\bON\s+CONFLICT\b")
        self.assertNotRegex(source, r"(?i)\bINSERT\s+OR\s+REPLACE\b|\bREPLACE\s+INTO\b|\bDROP\b|\bALTER\b|\bTRUNCATE\b")
        self.assertNotRegex(source, r"(?i)executescript|writable_schema|\bVACUUM\b")

    def test_every_public_function_leaves_the_rows_that_are_there_as_they_were(self):
        statuses = ("queued", "fetching", "kept", "rejected", "failed", "blocked")
        for i, status in enumerate(statuses):
            self.conn.execute("INSERT INTO candidates (identity_key, address, source, source_id, domain, status, reason, score, "
                              "book_id, tries, run_id, added, updated, next_try) VALUES (?, ?, 'openalex', ?, 'example.org', ?, 'r', "
                              "0.5, 'b', 2, 'run', 'then', 'then', 'later')",
                              (f"https://example.org/{status}", f"https://example.org/{status}", f"openalex:W{i}", status))
        before = self.rows()
        loose = {"queued_total": 100, "queued_per_domain": 100}
        tight = {"queued_total": 1, "queued_per_domain": 1}
        for status in statuses:  # the same key again, by every way in
            again = candidate(f"https://example.org/{status}", topic="new", weight=9)
            self.assertEqual(self.add(again, limits=loose), "duplicate")
            self.assertEqual(crawlqueue.insert_blocked(self.conn, again, "owner", canon_address=fake_canon, site_of=fake_site,
                                                       now=NOW), "duplicate")
            self.assertEqual(crawlqueue.insert_rejected(self.conn, again, "type", canon_address=fake_canon, site_of=fake_site,
                                                        now=NOW), "duplicate")
        self.assertEqual(self.add(candidate("https://example.org/new"), limits=tight), "capped")
        self.assertEqual(self.add(candidate("https://example.org/" + "a" * 3000, identity_key="k")), "too_long")
        self.assertEqual(self.add(candidate("ftp://example.org/x", identity_key="k")), "refused")
        crawlqueue.kept_sources(self.conn, "openalex", 5)
        crawlqueue.counts(self.conn)
        self.assertEqual(self.rows(), before)
        self.add(candidate("https://example.org/added"), limits=loose)  # and a new row changes only itself
        self.assertEqual(self.rows()[:len(before)], before)
        self.assertEqual(len(self.rows()), len(before) + 1)


class InsertBlockedAndRejectedTest(QueueCase):
    def blocked(self, row=None, reason="owner", limits=None):
        return crawlqueue.insert_blocked(self.conn, row or candidate(), reason, canon_address=fake_canon, site_of=fake_site,
                                         now=NOW)

    def rejected(self, row=None, reason="type"):
        return crawlqueue.insert_rejected(self.conn, row or candidate(), reason, canon_address=fake_canon, site_of=fake_site,
                                          now=NOW)

    def test_a_blocked_row_has_its_status_and_reason(self):
        self.assertEqual(self.blocked(reason="list:phishing"), "blocked")
        (row,) = self.rows()
        self.assertEqual((row["status"], row["reason"], row["domain"], row["added"]), ("blocked", "list:phishing", "example.org", NOW))

    def test_a_rejected_row_has_its_status_and_the_reason_type(self):
        self.assertEqual(self.rejected(), "rejected")
        (row,) = self.rows()
        self.assertEqual((row["status"], row["reason"]), ("rejected", "type"))

    def test_only_the_reasons_of_the_spec_are_taken(self):
        for reason in ("", "other", "owner ", "list:", "list:" + "x" * 100, "list:a b", None, 5):
            with self.subTest(reason=reason):
                with self.assertRaises(KbError):
                    self.blocked(reason=reason)
        for reason in ("owner", "list:phishing", "list:urlhaus", "failed 3 times", "", None):
            with self.subTest(rejected=reason):
                with self.assertRaises(KbError):
                    self.rejected(reason=reason)
        self.assertEqual(self.rows(), [])

    def test_the_duplicate_rule_is_the_same(self):
        self.add()
        before = self.rows()
        self.assertEqual(self.blocked(), "duplicate")
        self.assertEqual(self.rejected(), "duplicate")
        self.assertEqual(self.rows(), before)

    def test_a_blocked_address_is_not_queued_later(self):
        self.blocked()
        self.assertEqual(self.add(), "duplicate")
        self.assertEqual(self.rows()[0]["status"], "blocked")

    def test_a_too_long_address_is_not_stored(self):
        long = candidate("https://example.org/" + "a" * 3000, identity_key="k")
        self.assertEqual(self.blocked(long), "too_long")
        self.assertEqual(self.rejected(long), "too_long")
        self.assertEqual(self.rows(), [])

    def test_they_are_not_counted_against_the_queued_caps(self):
        limits = {"queued_total": 1, "queued_per_domain": 1}
        for i in range(5):
            self.blocked(candidate(f"https://example.org/b{i}"))
            self.rejected(candidate(f"https://example.org/r{i}"))
        self.assertEqual(self.add(candidate("https://example.org/q"), limits=limits), "queued")
        self.assertEqual(len(self.rows()), 11)

    def test_unknown_keys_are_refused(self):
        with self.assertRaises(KbError):
            self.blocked(candidate(status="queued"))
        with self.assertRaises(KbError):
            self.rejected(candidate(book_id="b"))


class ReadTest(QueueCase):
    def put(self, key, status, source="openalex", source_id=None, depth=0):
        self.conn.execute("INSERT INTO candidates (identity_key, address, source, source_id, depth, status, added, updated) "
                          "VALUES (?, ?, ?, ?, ?, ?, 'n', 'n')", (key, "https://example.org/" + key, source, source_id, depth, status))

    def test_kept_sources_gives_the_source_id_and_depth_of_kept_rows_that_have_an_id(self):
        self.put("a", "kept", source_id="openalex:W1", depth=0)
        self.put("b", "kept", source_id="openalex:W2", depth=1)
        self.put("c", "kept", source_id=None)
        self.put("d", "queued", source_id="openalex:W4")
        self.put("e", "rejected", source_id="openalex:W5")
        self.put("f", "kept", source="arxiv", source_id="arxiv:1")
        self.assertEqual(crawlqueue.kept_sources(self.conn, "openalex", 2), [("openalex:W1", 0), ("openalex:W2", 1)])
        self.assertEqual(crawlqueue.kept_sources(self.conn, "arxiv", 2), [("arxiv:1", 0)])

    def test_kept_sources_leaves_out_rows_that_are_already_at_the_depth_limit(self):
        self.put("a", "kept", source_id="openalex:W1", depth=1)
        self.put("b", "kept", source_id="openalex:W2", depth=2)
        self.assertEqual(crawlqueue.kept_sources(self.conn, "openalex", 2), [("openalex:W1", 1)])
        self.assertEqual(crawlqueue.kept_sources(self.conn, "openalex", 0), [])

    def test_kept_sources_is_in_the_order_the_rows_were_added(self):
        self.put("b", "kept", source_id="openalex:W2")
        self.put("a", "kept", source_id="openalex:W1")
        self.assertEqual([s for s, _ in crawlqueue.kept_sources(self.conn, "openalex", 2)], ["openalex:W2", "openalex:W1"])

    def test_counts_gives_every_status_even_when_it_is_zero(self):
        self.assertEqual(crawlqueue.counts(self.conn), {s: 0 for s in ("queued", "fetching", "kept", "rejected", "failed", "blocked")})
        self.put("a", "queued")
        self.put("b", "queued")
        self.put("c", "kept")
        self.put("d", "blocked")
        self.assertEqual(crawlqueue.counts(self.conn),
                         {"queued": 2, "fetching": 0, "kept": 1, "rejected": 0, "failed": 0, "blocked": 1})

    def test_reading_changes_nothing(self):
        self.put("a", "kept", source_id="openalex:W1")
        before = self.rows()
        crawlqueue.kept_sources(self.conn, "openalex", 2)
        crawlqueue.counts(self.conn)
        self.assertEqual(self.rows(), before)


if __name__ == "__main__":
    unittest.main()
