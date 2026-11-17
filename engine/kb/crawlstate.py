"""The ceilings, the counters and the changes of a candidate row (`docs/specs/population.md`, "The queue and the seen list" and "Safeguards"; the plan `2026-11-16-build-the-safeguards-of-the-unattended-crawl`, Increment E).

`crawlstate` is **the only module that changes the state of a row of `candidates.sqlite`** (discovery adds rows, `crawlqueue` reads and counts them) and the only one that writes the `counters` table. Each operation is one
transaction (`BEGIN IMMEDIATE`, so two processes take turns and SQLite's own lock is the only lock), made only with `conn.execute`, and it is all done or not done: a failure before any statement rolls back. **No function
deletes a row**, and none adds one.

The transitions it makes, by the spec's statuses (`queued`, `fetching`, `kept`, `rejected`, `failed`, `blocked`):

- `reserve`: `queued` to `fetching`, with `tries` plus one, and **one unit of `fetch` and of `fetch:<site>` of the day reserved in the same transaction**. A failed fetch keeps its count.
- `finish`: `fetching` to `kept` (a book exists), to `rejected` (final), or, for a failed try, back to `queued` at a later `next_try` (1, then 6, then 24 hours; a refusal waits 24) until `tries` reaches the plan's `retries`,
  when it is `failed` and final. (The spec words that last step as `rejected: failed 3 times`; the approved plan says `failed`, and the reason says how many times.)
- `requeue_stale`: a `fetching` row not touched for over 30 minutes goes back to `queued` as a try (its day's count stays), or, at `retries` tries, to `failed`.
- `block`: `queued` to `blocked`.
- `reject_kept`: `kept` to `rejected` (a candidate whose book was made and was then judged out).
- Counters: `fetch`, `fetch:<site>`, `card`, `refusal:<site>`, each by the plan's `timezone` day (`crawlplan.day_of`). `reserve_card` and `note_refusal` write the last two, `charge_hop` counts a redirect's hop to another site in `hop:<site>`, apart from the units of `fetch:<site>` that candidates take; `ceilings` reads.

`filed_total` is not a counter: `filed_total(events_by_book)` counts the books with a `crawl_found` event in the events it is given (this module reads no store). This module makes no request and reads no environment variable."""
import datetime
import re
from contextlib import contextmanager

from . import KbError, crawlguard, crawlplan, textutil

STALE_MINUTES = 30
WAIT_HOURS = (1, 6, 24)
REFUSAL_WAIT_HOURS = 24
REASON_MAX = 300
BOOK_MAX = 120
FINISH_STATUSES = ("kept", "rejected", "failed")
_RUN = re.compile(r"[A-Za-z0-9._:-]{1,64}")
_SITE = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?")


def _stamp(now):
    if not isinstance(now, datetime.datetime) or now.tzinfo is None:
        raise KbError("the crawl state needs a time with a time zone")
    return now.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _later(now, hours):
    """The time `hours` of elapsed time after `now`, in UTC (a wall-clock sum in a zone with a change of clock would be an hour out)."""
    return _stamp(now.astimezone(datetime.timezone.utc) + datetime.timedelta(hours=hours))


def _plan_numbers(plan, *keys):
    if not isinstance(plan, dict):
        raise KbError("the plan is not a table of settings")
    for key in keys:
        value = plan.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise KbError(f"the plan's {key} is a whole number from 1")
    if not isinstance(plan.get("timezone"), str):
        raise KbError("the plan's timezone is text")


def _id(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise KbError("a candidate is named by its number")
    return value


def _reason(value):
    return textutil.clean(value, REASON_MAX) or None


def _wait(tries):
    return WAIT_HOURS[min(max(tries, 1), len(WAIT_HOURS)) - 1]


@contextmanager
def _transaction(conn):
    """One transaction that is taken with the write lock at once and rolled back on any failure."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def _bump(conn, day, key):
    conn.execute("INSERT INTO counters(day, key, n) VALUES (?, ?, 1) ON CONFLICT(day, key) DO UPDATE SET n = n + 1", (day, key))


def _count(conn, day, key):
    row = conn.execute("SELECT n FROM counters WHERE day = ? AND key = ?", (day, key)).fetchone()
    return row[0] if row else 0


def _row(conn, ident):
    cur = conn.execute("SELECT * FROM candidates WHERE id = ?", (ident,))
    names = [d[0] for d in cur.description]
    found = cur.fetchone()
    return dict(zip(names, found)) if found else None


def reserve(conn, plan, now, run, filed):
    """Take the next queued candidate for `run`: `(row, "")`, or `(None, why)` with `why` one of `fetches_per_day`, `filed_total`, `batch`, `nothing_queued`.

    The order is the higher weight first (a wandered candidate counts as 0), then the oldest, then the lower depth. A row waits for its `next_try`; a row of a site at `per_domain_per_day` for the day, or one that
    `crawlguard.site_stopped` says is stopped for the day, is skipped (it stays queued), and other sites' rows are still taken; a row with no site cannot be paced and is not taken. `filed` is the number of books filed so far
    (`filed_total`): **required**, so that a caller cannot leave that ceiling unchecked by forgetting it."""
    _plan_numbers(plan, "fetches_per_day", "per_domain_per_day", "batch", "filed_total", "domain_refusals")
    stamp = _stamp(now)
    if not isinstance(run, str) or not _RUN.fullmatch(run):
        raise KbError("a run name is 1 to 64 letters, digits or . _ : -")
    if isinstance(filed, bool) or not isinstance(filed, int) or filed < 0:
        raise KbError("the number of books filed is a whole number from 0")
    day = crawlplan.day_of(now, plan["timezone"])
    with _transaction(conn):
        if _count(conn, day, "fetch") >= plan["fetches_per_day"]:
            return None, "fetches_per_day"
        if filed >= plan["filed_total"]:
            return None, "filed_total"
        if conn.execute("SELECT COUNT(*) FROM candidates WHERE run_id = ?", (run,)).fetchone()[0] >= plan["batch"]:
            return None, "batch"
        used = {key[6:]: n for key, n in conn.execute("SELECT key, n FROM counters WHERE day = ? AND substr(key, 1, 6) = 'fetch:'", (day,)).fetchall()}
        refusals = crawlguard.refusals_today(conn, plan, now)
        chosen = None
        cur = conn.execute("SELECT id, domain FROM candidates WHERE status = 'queued' AND domain IS NOT NULL AND (next_try IS NULL OR next_try <= ?) "
                           "ORDER BY COALESCE(weight, 0) DESC, added ASC, depth ASC, id ASC", (stamp,))
        for ident, domain in cur:
            if not _SITE.fullmatch(domain) or used.get(domain, 0) >= plan["per_domain_per_day"] or crawlguard.site_stopped(refusals, domain, plan):
                continue
            chosen = (ident, domain)
            break
        cur.close()
        if chosen is None:
            return None, "nothing_queued"
        ident, domain = chosen
        moved = conn.execute("UPDATE candidates SET status = 'fetching', tries = tries + 1, run_id = ?, updated = ? WHERE id = ? AND status = 'queued'", (run, stamp, ident))
        if moved.rowcount != 1:
            raise KbError("the candidate was taken by another run")
        _bump(conn, day, "fetch")
        _bump(conn, day, f"fetch:{domain}")
        return _row(conn, ident), ""


def finish(conn, plan, ident, status, reason, book_id, now, refusal=False, run=None, count=True):
    """Close the try of a `fetching` row: `kept` (with the `book_id`), `rejected` (final; a `book_id` may name the book it duplicates), or `failed` (this try failed: back to `queued` at a later `next_try`, or `failed` and
    final when `tries` has reached `retries`). With `refusal`, a failed try is a refusal of the site (403, 429, an abuse signal): it waits a day and, unless `count` is false, counts for the row's own site's refusals (a caller that charges the refusal to a different site, the one that a redirect led to and that answered it, passes `count=False`: the row's site is then not charged for what another site did). With `run`, only the run that took the row can finish it (a late finish of a try that was
    given up and taken again by another run is refused)."""
    _plan_numbers(plan, "retries")
    ident = _id(ident)
    if not isinstance(status, str) or status not in FINISH_STATUSES:
        raise KbError("a try ends as " + ", ".join(FINISH_STATUSES))
    if not isinstance(count, bool):
        raise KbError("whether a refusal counts for the row's site is true or false")
    if not isinstance(refusal, bool) or (refusal and status != "failed"):
        raise KbError("a refusal is a failed try")
    book = None
    if book_id is not None:
        book = textutil.clean(book_id, BOOK_MAX) if isinstance(book_id, str) else ""
        if not book:
            raise KbError("a book is named by text")
    if status == "kept" and book is None:
        raise KbError("a kept candidate has its book")
    stamp = _stamp(now)
    day = crawlplan.day_of(now, plan["timezone"])
    text = _reason(reason)
    with _transaction(conn):
        row = _row(conn, ident)
        if row is None or row["status"] != "fetching" or (run is not None and row["run_id"] != run):
            raise KbError("only a candidate that is being fetched, by this run, can be finished")
        new, next_try = status, None
        if status == "failed":
            tries = row["tries"]
            if tries < plan["retries"]:
                new, next_try = "queued", _later(now, REFUSAL_WAIT_HOURS if refusal else _wait(tries))
            else:
                text = textutil.clean(f"failed {tries} times" + (f": {text}" if text else ""), REASON_MAX)
        conn.execute("UPDATE candidates SET status = ?, reason = ?, book_id = ?, next_try = ?, updated = ? WHERE id = ? AND status = 'fetching'", (new, text, book, next_try, stamp, ident))
        if refusal and count and isinstance(row["domain"], str) and _SITE.fullmatch(row["domain"]):
            _bump(conn, day, f"refusal:{row['domain']}")


def requeue_stale(conn, plan, now):
    """Return the rows that have been `fetching` for over 30 minutes to `queued` as a try (the count of their day stays), or, at `retries` tries, make them `failed`. Returns `{"requeued": n, "failed": m}`."""
    _plan_numbers(plan, "retries")
    stamp = _stamp(now)
    limit = _stamp(now.astimezone(datetime.timezone.utc) - datetime.timedelta(minutes=STALE_MINUTES))
    out = {"requeued": 0, "failed": 0}
    with _transaction(conn):
        for ident, tries in conn.execute("SELECT id, tries FROM candidates WHERE status = 'fetching' AND updated < ? ORDER BY id", (limit,)).fetchall():
            if tries >= plan["retries"]:
                conn.execute("UPDATE candidates SET status = 'failed', reason = ?, next_try = NULL, updated = ? WHERE id = ? AND status = 'fetching'",
                             (f"stalled; gave up after {tries} tries", stamp, ident))
                out["failed"] += 1
            else:
                conn.execute("UPDATE candidates SET status = 'queued', reason = 'stalled for over 30 minutes', next_try = ?, updated = ? WHERE id = ? AND status = 'fetching'",
                             (_later(now, _wait(tries)), stamp, ident))
                out["requeued"] += 1
    return out


def reject_kept(conn, plan, ident, reason, now):
    """`kept` to `rejected`, with the reason: a candidate whose book was made and was then judged out. It is the only way a `kept` row changes, and it changes nothing else."""
    _plan_numbers(plan, "retries")
    ident = _id(ident)
    stamp = _stamp(now)
    text = _reason(reason)
    with _transaction(conn):
        moved = conn.execute("UPDATE candidates SET status = 'rejected', reason = ?, updated = ? WHERE id = ? AND status = 'kept'", (text, stamp, ident))
        if moved.rowcount != 1:
            raise KbError("only a kept candidate can be rejected after its book was made")


def block(conn, ident, reason, now):
    """`queued` to `blocked`, with the reason; only a queued row can be blocked."""
    ident = _id(ident)
    stamp = _stamp(now)
    text = _reason(reason)
    with _transaction(conn):
        moved = conn.execute("UPDATE candidates SET status = 'blocked', reason = ?, updated = ? WHERE id = ? AND status = 'queued'", (text, stamp, ident))
        if moved.rowcount != 1:
            raise KbError("only a queued candidate can be blocked")


def reserve_card(conn, plan, now):
    """Take one unit of the day's `cards_per_day`: true if there was one, false at the ceiling."""
    _plan_numbers(plan, "cards_per_day")
    day = crawlplan.day_of(now, plan["timezone"])
    with _transaction(conn):
        if _count(conn, day, "card") >= plan["cards_per_day"]:
            return False
        _bump(conn, day, "card")
        return True


def note_refusal(conn, plan, now, site):
    """Count one refusal (403, 429, an abuse signal) by `site` in the plan's day."""
    _plan_numbers(plan, "domain_refusals")
    if not isinstance(site, str) or len(site) > 253 or not _SITE.fullmatch(site):
        raise KbError("a site is its lower-case registrable name")
    day = crawlplan.day_of(now, plan["timezone"])
    with _transaction(conn):
        _bump(conn, day, f"refusal:{site}")


def charge_hop(conn, plan, now, site):
    """Count one request that a redirect led to, **apart from the units that candidates take** (the first request of a candidate is reserved by `reserve`, in `fetch:<site>`; this is for the hops after it, to a site other
    than the first, and is counted in `hop:<site>`, which `reserve` does not read: a hostile redirect cannot use up the units that the site's own candidates would have used). A hop is refused when the site is stopped for
    the day, when its candidates' units are at `per_domain_per_day`, or when its hops have reached `per_domain_per_day` too. Returns `""` when the
    unit was taken, or the reason it was not: `the site is stopped for the day` (it has reached `domain_refusals` refusals) or `the site is at its limit for the day` (`per_domain_per_day`). Nothing is taken then."""
    _plan_numbers(plan, "per_domain_per_day", "domain_refusals")
    if not isinstance(site, str) or len(site) > 253 or not _SITE.fullmatch(site):
        raise KbError("a site is its lower-case registrable name")
    day = crawlplan.day_of(now, plan["timezone"])
    with _transaction(conn):
        if crawlguard.site_stopped(crawlguard.refusals_today(conn, plan, now), site, plan):
            return "the site is stopped for the day"
        if _count(conn, day, f"fetch:{site}") >= plan["per_domain_per_day"] or _count(conn, day, f"hop:{site}") >= plan["per_domain_per_day"]:
            return "the site is at its limit for the day"
        _bump(conn, day, f"hop:{site}")
        return ""


def ceilings(conn, plan, now, filed=None):
    """What the day has used of each ceiling, without changing anything: `{"day", "fetch": (used, limit), "card": (used, limit), "filed": (filed or None, limit)}`."""
    _plan_numbers(plan, "fetches_per_day", "cards_per_day", "filed_total")
    day = crawlplan.day_of(now, plan["timezone"])
    return {"day": day, "fetch": (_count(conn, day, "fetch"), plan["fetches_per_day"]), "card": (_count(conn, day, "card"), plan["cards_per_day"]), "filed": (filed, plan["filed_total"])}


def filed_total(events_by_book):
    """The number of books with a `crawl_found` event in `{book id: [event, ...]}` (each event a dictionary with its `event` name), as `filed_total` counts them. It reads no store."""
    if not isinstance(events_by_book, dict):
        raise KbError("the books' events are a table of book to events")
    total = 0
    for book, events in events_by_book.items():
        if not isinstance(book, str) or not isinstance(events, (list, tuple)):
            raise KbError("the books' events are a table of book to events")
        found = False
        for event in events:
            if not isinstance(event, dict) or not isinstance(event.get("event"), str):
                raise KbError("an event of a book is a dictionary with its name")
            found = found or event["event"] == "crawl_found"
        total += found
    return total
