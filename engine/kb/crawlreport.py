"""`crawl-report`: the report of one day of the unattended crawl (`docs/specs/population.md`, "Status and the report"; the plan
`2026-11-16-show-the-state-and-the-report-of-the-unattended-crawl`, Increments E to G).

`build` gathers the facts of a day from the log (the day of a line is its `ts` in the plan's zone, as `crawlstatus` reads it) and from the candidate queue
(read only); `render` makes them a Markdown text; `write_report` puts that text in `<index root>/crawl/report/crawl-report-YYYY-MM-DD.md`; `make_report`
does the three for a day. **The one thing this module writes is that report file**: through a new temporary file in the same folder (mode 600, made new and
not through a link), renamed into place; in a folder of mode 700 that is the owner's and not a link; **nothing is ever written into `crawl/log/`**, and the log, the
queue, the lists and the books are only read. A day's report again replaces that day's file.

**Every text from outside** (an address, a host, a book id, a reason, a list's name, a run's id) is redacted and cleaned as `crawlstatus.clean` does, and is put
in an inline code span with its backticks, pipes and angle brackets written as `%60`, `%7C`, `%3C` and `%3E`, so that a viewer cannot be made to show a link, an
image, a heading, a table cell or HTML by what the web sent; every other word of the report is this module's own and has none of those characters."""

import datetime
import os
import re
import stat
from pathlib import Path

from . import KbError, crawlstatus as cs

FOLDER = "report"                      # `<index root>/crawl/report/`
MAX_FILED = 5000                       # the most books listed in a report (the total is said)
MAX_HOSTS = 50                         # the most hosts listed for the works rejected for their type
MAX_REASONS = 20                       # the most reasons listed for the failures
MAX_REPORT_BYTES = 8 * 1024 * 1024     # a report is a text of this size at most
EARLIEST = datetime.date(2000, 1, 1)   # a report of an earlier day is refused
UNKNOWN_HOST = "(unknown)"
_ESCAPES = (("`", "%60"), ("|", "%7C"), ("<", "%3C"), (">", "%3E"))


def _me():
    return os.getuid()


def _refuse(message):
    return KbError(f"the crawl report: {message}")


# --- text for a Markdown viewer ----------------------------------------------------------------------------------------------------------------

def code(value, limit=200):
    """`value` as an inline code span: redacted, cleaned and cut as `crawlstatus.clean` does, with a backtick, a pipe and an angle bracket written as a
    percent escape, so that it cannot close the span or make anything else. Nothing is `(none)` and a text that nothing is left of is `(empty)`: never an
    empty span."""
    text = cs.clean(value, limit)
    if value is None:
        return "`(none)`"
    if not text:
        return "`(empty)`"
    for char, escape in _ESCAPES:
        text = text.replace(char, escape)
    return f"`{text}`"


def number(value):
    """A count as a number, or `unknown` for anything that is not a whole number of 0 or more."""
    return str(value) if type(value) is int and value >= 0 else "unknown"


# --- the facts of a day -----------------------------------------------------------------------------------------------------------------------

def _distinct(lines, key):
    """The number of different values of `key` among `lines`; a line with no value counts as one of its own."""
    seen, alone = set(), 0
    for record in lines:
        value = record[key]
        if value is None:
            alone += 1
        else:
            seen.add(value)
    return len(seen) + alone


def _counts(lines):
    by = {}
    for record in lines:
        by.setdefault(record["step"], []).append(record)
    fetches, fails = by.get("fetch", []), by.get("fail", [])
    return {"fetched": sum(r["outcome"] == "ok" for r in fetches), "fetch_failed": sum(r["outcome"] == "failed" for r in fetches),
            "kept": _distinct([r for r in by.get("judge", []) if r["outcome"] == "ok"], "book"),
            "rejected": _distinct(by.get("reject", []), "candidate"), "failed": _distinct(fails, "candidate"), "fail_lines": len(fails)}


def _steps(lines):
    steps = {}
    for record in lines:
        outcomes = steps.setdefault(record["step"], {})
        outcomes[record["outcome"]] = outcomes.get(record["outcome"], 0) + 1
    return steps


def _runs(found):
    runs = cs.count_runs(found)
    return {key: runs[key] for key in ("started", "ended", "ended_by_outcome", "refused", "refused_by_reason")}


def _text(value, limit):
    return None if value is None else cs.clean(value, limit)


def _grouped(reasons, size):
    """`[{"reason", "n"}]` from a mapping of reason to count, the commonest first (then by name), at most `size`."""
    return [{"reason": why, "n": n} for why, n in sorted(reasons.items(), key=lambda item: (-item[1], item[0]))[:size]]


def _log_reasons(lines):
    reasons = {}
    for record in lines:
        if record["step"] == "fail":
            why = cs.clean(record["reason"], 100) or "(no reason)"
            reasons[why] = reasons.get(why, 0) + 1
    return _grouped(reasons, MAX_REASONS)


def _pauses(lines):
    return [{"ts": r["ts"], "run": cs.clean(r["run"], 100), "reason": _text(r["reason"], 300)}
            for r in lines if r["step"] == "breaker" and r["outcome"] == "tripped"]


def _lists_failed(lines):
    return [{"ts": r["ts"], "list": cs.clean(r["host"] or "", 100) or None, "outcome": r["outcome"], "reason": _text(r["reason"], 300)}
            for r in lines if r["step"] == "list_update" and r["outcome"] != "ok"]


def _breaker_now(index_root):
    state = cs.breaker_state(index_root)
    if state["state"] == "not_tripped":
        return None
    return {key: state[key] for key in ("state", "reason", "kind", "at", "run", "detail")}


def _queue_facts(conn, low, high):
    """What the queue says of the day, each fact apart so that one that fails does not take the others."""
    bounds = (low, high)
    statuses = cs.guarded(lambda: [tuple(row) for row in conn.execute("SELECT status, COUNT(*) FROM candidates WHERE updated >= ? AND updated < ? GROUP BY status", bounds)])
    typed = cs.guarded(lambda: conn.execute("SELECT COUNT(*) FROM candidates WHERE status = 'rejected' AND reason = 'type' AND updated >= ? AND updated < ?",
                                            bounds).fetchone()[0])
    counts = None
    if isinstance(statuses, list) and not isinstance(typed, dict):
        by_status = dict(statuses)
        counts = {"kept": by_status.get("kept", 0), "rejected": by_status.get("rejected", 0) - typed, "rejected_type": typed, "failed": by_status.get("failed", 0)}
    rows = cs.guarded(lambda: conn.execute(
        "SELECT book_id, address, domain, updated FROM candidates WHERE status = 'kept' AND book_id IS NOT NULL AND updated >= ? AND updated < ? "
        "ORDER BY updated, id LIMIT ?", (low, high, MAX_FILED + 1)).fetchall())
    hosts = cs.guarded(lambda: conn.execute(
        "SELECT domain, COUNT(*) AS c FROM candidates WHERE status = 'rejected' AND reason = 'type' AND updated >= ? AND updated < ? "
        "GROUP BY domain ORDER BY c DESC LIMIT 200", bounds).fetchall())
    failed = cs.guarded(lambda: conn.execute(
        "SELECT reason, COUNT(*) AS c FROM candidates WHERE status = 'failed' AND updated >= ? AND updated < ? GROUP BY reason ORDER BY c DESC LIMIT 200",
        bounds).fetchall())
    return {"counts": counts if counts is not None else (statuses if isinstance(statuses, dict) else typed), "rows": rows, "hosts": hosts, "failed": failed}


def _filed(lines, rows):
    """The books filed in the day, each once, in time order: from the `capture` lines that name a book, and from the queue's `kept` rows that name one."""
    books = {}
    for record in lines:
        if record["step"] == "capture" and record["outcome"] == "ok" and record["book"] is not None and record["book"] not in books:
            books[record["book"]] = {"ts": record["ts"], "book": record["book"], "address": None, "host": record["host"], "seen": {"log"}}
    for book_id, address, domain, updated in rows:
        if not isinstance(book_id, str):
            continue
        entry = books.get(book_id)
        if entry is None:
            entry = books[book_id] = {"ts": updated, "book": book_id, "address": address, "host": domain, "seen": set()}
        entry["seen"].add("queue")
        entry["address"] = entry["address"] if entry["address"] is not None else address
        entry["host"] = entry["host"] if entry["host"] is not None else domain
    ordered = sorted(books.values(), key=lambda e: str(e["ts"]))
    listed = [{"ts": cs.clean(e["ts"], 20), "book": cs.clean(e["book"], 100), "address": _text(e["address"], 200), "host": _text(e["host"], 100),
               "seen_in": "both" if len(e["seen"]) == 2 else next(iter(e["seen"]))} for e in ordered[:MAX_FILED]]
    return {"books": listed, "total": len(ordered), "truncated": len(ordered) > MAX_FILED}


def _type_hosts(hosts):
    named, total = {}, 0
    for domain, n in hosts:
        total += n
        name = cs.clean(domain, 100) if isinstance(domain, str) else ""
        name = name or UNKNOWN_HOST
        named[name] = named.get(name, 0) + n
    listed = sorted(named.items(), key=lambda item: (-item[1], item[0] == UNKNOWN_HOST, item[0]))
    return {"n": total, "hosts": [{"host": name, "n": n} for name, n in listed[:MAX_HOSTS]], "hosts_total": len(listed)}


def _queue_reasons(rows):
    reasons = {}
    for reason, n in rows:
        why = cs.clean(reason, 100) or "(no reason)"
        reasons[why] = reasons.get(why, 0) + n
    return _grouped(reasons, MAX_REASONS)


def _compare(counts, queue):
    if not isinstance(queue, dict) or "error" in queue or not isinstance(counts, dict) or "error" in counts:
        return None
    return [{"what": what, "log": counts[what], "queue": queue[what], "same": counts[what] == queue[what]} for what in ("kept", "rejected", "failed")]


def build(index_root, day, zone, now):
    """The facts of the day `day` (a `datetime.date`) in `zone` as plain data. A part that fails is `{"error": text}` in its place and the rest stand. The
    log parts are: `log` (its lines, first and last time, files, bad lines, cut), `counts`, `steps`, `runs`, `breaker` and `lists_failed` and the log's half of
    `failures_by_reason`; the queue parts (read only) are `queue`, `compare`, `filed` (with the log's capture lines), `rejected_for_type` and the queue's half of
    `failures_by_reason`."""
    start, end = cs.day_bounds(day, zone)
    if not isinstance(now, datetime.datetime) or now.tzinfo is None:
        raise _refuse("now is a time with a zone")
    found = cs.guarded(cs.lines_of_day, index_root, day, zone)
    broken = "error" in found
    lines = [] if broken else found["lines"]

    def from_lines(fn, *args):
        return found if broken else cs.guarded(fn, *args)

    data = {"day": day.isoformat(), "zone": zone, "generated": now.astimezone(datetime.timezone.utc).strftime(cs._TS_FORMAT), "zone_problem": None, "notes": []}
    data["log"] = found if broken else {"lines": len(lines), "first": found["first"], "last": found["last"], "dates": [d.isoformat() for d in found["dates"]],
                                        "bad": found["bad"], "cut": found["cut"], "unreadable": found["unreadable"], "problem": found["problem"]}
    data["counts"] = from_lines(_counts, lines)
    data["steps"] = from_lines(_steps, lines)
    data["runs"] = from_lines(_runs, found)
    data["breaker"] = {"pauses": from_lines(_pauses, lines), "now": cs.guarded(_breaker_now, index_root)}
    data["lists_failed"] = from_lines(_lists_failed, lines)
    log_reasons = from_lines(_log_reasons, lines)
    opened = cs.guarded(cs.open_queue, index_root)
    if isinstance(opened, dict):
        opened = cs.QueueOpen(None, "bad", opened["error"])
    facts = None
    if opened.status == "ok":
        try:
            facts = _queue_facts(opened.conn, start.strftime(cs._TS_FORMAT), end.strftime(cs._TS_FORMAT))
        finally:
            opened.conn.close()
    qcounts = facts["counts"] if facts else None
    data["queue"] = {"status": opened.status, "reason": opened.reason, "counts": qcounts}
    data["compare"] = _compare(data["counts"], qcounts)
    rows = facts["rows"] if facts and not isinstance(facts["rows"], dict) else []
    data["filed"] = cs.guarded(_filed, [] if broken else lines, rows)
    data["rejected_for_type"] = None if facts is None else (facts["hosts"] if isinstance(facts["hosts"], dict) else cs.guarded(_type_hosts, facts["hosts"]))
    queue_reasons = None if facts is None else (facts["failed"] if isinstance(facts["failed"], dict) else cs.guarded(_queue_reasons, facts["failed"]))
    data["failures_by_reason"] = {"log": log_reasons, "queue": queue_reasons}
    return data


# --- the text -------------------------------------------------------------------------------------------------------------------------------------

def _broken(part):
    return isinstance(part, dict) and "error" in part


def _unreadable(part):
    return f"- This part could not be read: {code(part['error'], 300)}"


def render(data):
    """The Markdown of a day's facts. Every text from outside is in a code span (see `code`); the words around it are fixed here and have no character that a
    viewer would read as markup beyond a heading mark, a bullet and a colon."""
    out = [f"# Crawl report for {data['day']}", "", f"- Zone: {code(data['zone'])}. Generated {code(data['generated'])}."]
    if data.get("zone_problem"):
        out.append(f"- Problem with the zone: {code(data['zone_problem'], 300)}")
    for note in data.get("notes") or ():
        out.append(f"- Note: {code(note, 300)}")
    counts = data["counts"]
    out += ["", "## The day in numbers", ""]
    if _broken(counts):
        out.append(_unreadable(counts))
    else:
        out += [f"- Fetched: {number(counts['fetched'])} (fetch lines that say ok)", f"- Fetches that failed: {number(counts['fetch_failed'])}",
                f"- Kept: {number(counts['kept'])} (judge lines that say ok)", f"- Rejected: {number(counts['rejected'])} (candidates with a reject line)",
                f"- Failed: {number(counts['failed'])} candidates, {number(counts['fail_lines'])} fail lines"]
    runs = data["runs"]
    out += ["", "## Runs", ""]
    if _broken(runs):
        out.append(_unreadable(runs))
    else:
        ends = ", ".join(f"{name}: {number(n)}" for name, n in sorted(runs["ended_by_outcome"].items()))
        out += [f"- Started: {number(runs['started'])}", f"- Ended: {number(runs['ended'])}" + (f" ({ends})" if ends else ""),
                f"- Refused firings, which are not runs: {number(runs['refused'])}"]
        out += [f"- Refused: {code(why, 100)} x {number(n)}" for why, n in runs["refused_by_reason"].items()]
    queue = data["queue"]
    out += ["", "## The log and the queue compared", ""]
    if data["compare"] is None:
        out.append(f"- The queue was not read: {code(queue['status'])}" + (f", {code(queue['reason'], 300)}" if queue["reason"] else ""))
        if _broken(queue["counts"]):
            out.append(_unreadable(queue["counts"]))
    else:
        out += [f"- {c['what']}: log {number(c['log'])}, queue {number(c['queue'])}: {'the same' if c['same'] else 'DIFFERENT'}" for c in data["compare"]]
        out.append(f"- Rejected for their type, which are not in the comparison: {number(queue['counts']['rejected_type'])}")
    filed = data["filed"]
    out += ["", "## Books filed", ""]
    if _broken(filed):
        out.append(_unreadable(filed))
    else:
        out.append(f"- {number(filed['total'])} books" + (f", of which the first {number(len(filed['books']))} are listed" if filed["truncated"] else ""))
        if _broken(data["log"]):
            out.append("- The log could not be read, so only the books of the queue are listed.")
        if data["queue"]["status"] != "ok":
            out.append("- The queue was not read, so only the books of the log are listed.")
        out += [f"- {code(b['ts'])} {code(b['book'])} address {code(b['address'])} host {code(b['host'])} (seen in {b['seen_in']})" for b in filed["books"]]
    typed = data["rejected_for_type"]
    out += ["", "## Works rejected for their type", ""]
    if typed is None:
        out.append("- Not known: the queue was not read.")
    elif _broken(typed):
        out.append(_unreadable(typed))
    else:
        out.append(f"- {number(typed['n'])} works, by {number(typed['hosts_total'])} hosts")
        out += [f"- {code(h['host'], 100)}: {number(h['n'])}" for h in typed["hosts"]]
    breaker = data["breaker"]
    out += ["", "## Pauses of the circuit breaker", ""]
    if _broken(breaker["pauses"]):
        out.append(_unreadable(breaker["pauses"]))
    elif not breaker["pauses"]:
        out.append("- None in the log of this day.")
    else:
        out += [f"- {code(p['ts'])} run {code(p['run'], 100)}: {code(p['reason'], 300)}" for p in breaker["pauses"]]
    now = breaker["now"]
    if _broken(now):
        out.append(_unreadable(now))
    elif now is not None:
        extra = "".join(f", {label} {code(now[key], 300)}" for label, key in (("since", "at"), ("reason", "reason"), ("kind", "kind")) if now.get(key))
        out.append(f"- The breaker file now: {code(now['state'])}{extra}")
    lists = data["lists_failed"]
    out += ["", "## Lists that could not be refreshed", ""]
    if _broken(lists):
        out.append(_unreadable(lists))
    elif not lists:
        out.append("- None in the log of this day.")
    else:
        out += [f"- {code(item['ts'])} {code(item['list'], 100)} {item['outcome']}: {code(item['reason'], 300)}" for item in lists]
    failures = data["failures_by_reason"]
    out += ["", "## Failures by reason", ""]
    for label, part in (("From the log (fail lines):", failures["log"]), ("From the queue (failed rows of the day):", failures["queue"])):
        out.append(label)
        if part is None:
            out.append("- Not known: the queue was not read.")
        elif _broken(part):
            out.append(_unreadable(part))
        elif not part:
            out.append("- None.")
        else:
            out += [f"- {code(item['reason'], 300)}: {number(item['n'])}" for item in part]
    log = data["log"]
    out += ["", "## The log", ""]
    if _broken(log):
        out.append(_unreadable(log))
    else:
        if log["lines"] == 0:
            out.append("- No log line of this day was found.")
        else:
            out.append(f"- Lines of the day: {number(log['lines'])}, first {code(log['first'])}, last {code(log['last'])}")
        if log["dates"]:
            out.append("- Files read: " + ", ".join(code(d) for d in log["dates"]))
        bad = sum(log["bad"].values())
        if bad:
            out.append(f"- Bad lines skipped: {number(bad)} (" + ", ".join(f"{kind}: {number(n)}" for kind, n in sorted(log["bad"].items())) + ")")
        if log["cut"]:
            out.append("- The log was cut at its size limit, so this report is not complete.")
        if log["unreadable"]:
            out.append(f"- Files that could not be read: {number(log['unreadable'])}")
        if log["problem"]:
            out.append(f"- Problem with the log folder: {code(log['problem'], 300)}")
    return "\n".join(out) + "\n"


# --- the file ------------------------------------------------------------------------------------------------------------------------------------

def _check_day(day, today):
    if type(day) is not datetime.date or type(today) is not datetime.date:
        raise _refuse("a day is a date")
    if day < EARLIEST or day > today:
        raise _refuse(f"a day is from {EARLIEST.isoformat()} to today")


def _check_text(text):
    if not isinstance(text, str):
        raise _refuse("a report is text")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError:
        raise _refuse("a report is text that can be written out") from None
    if size > MAX_REPORT_BYTES:
        raise _refuse("a report is over its size limit")
    if any(not (c.isprintable() or c == "\n") for c in text):
        raise _refuse("a report has only printable characters and line feeds")


def _ensure_dir(path, private):
    """A folder that is a plain folder of the owner's: made with mode 700 if it is missing; an existing one that is a link, not the owner's, or that the group
    or others can write is a refusal, and, if `private`, so is one they can read."""
    try:
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            os.mkdir(path, 0o700)
            info = os.lstat(path)
    except OSError as e:
        raise _refuse(f"a folder cannot be made ready ({e.strerror})") from None
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != _me():
        raise _refuse("a folder is a link, not a folder or not the owner's")
    if stat.S_IMODE(info.st_mode) & (0o077 if private else 0o022):
        raise _refuse("a folder of the report is open to others (the report folder must be mode 700, the crawl folder not writable by them)")


def _discard(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def write_report(index_root, day, text, *, today):
    """Write `text` as the report of `day`: `<index root>/crawl/report/crawl-report-YYYY-MM-DD.md`, mode 600, in a folder of mode 700, through a new temporary
    file in that folder that is renamed into place (a link in the file's place is replaced and never written through). Refused before anything is made: a
    day that is not a date, before 2000 or after `today`, and a text that is not printable text of a bounded size. Returns the path."""
    _check_day(day, today)
    _check_text(text)
    crawl = Path(index_root) / "crawl"
    folder = crawl / FOLDER
    _ensure_dir(crawl, False)
    _ensure_dir(folder, True)
    final = folder / f"crawl-report-{day.isoformat()}.md"
    temp = folder / f".crawl-report-{day.isoformat()}.md.{os.urandom(6).hex()}.new"
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0), 0o600)
    except OSError as e:
        raise _refuse(f"the report cannot be made ({e.strerror})") from None
    try:
        try:
            view = memoryview(text.encode("utf-8"))
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temp, final)
    except OSError as e:
        _discard(temp)
        raise _refuse(f"the report cannot be written ({e.strerror})") from None
    return final


# --- the whole report -------------------------------------------------------------------------------------------------------------------------

def make_report(index_root, *, read_plan, now, day=None):
    """Make and write the report of `day` (today in the plan's zone if none is given). `read_plan` is the reader of the approved plan, as for `status`; its zone
    is the report's, and with no plan that can be read the report is of the machine's zone and says so. Returns `{"path", "day", "zone", "counts", "filed",
    "notes"}`."""
    if not isinstance(now, datetime.datetime) or now.tzinfo is None:
        raise _refuse("now is a time with a zone")
    plan = cs.guarded(cs.approved_plan, index_root, read_plan)
    if "error" in plan:
        plan = {"status": "unreadable", "digest": None, "values": None, "reason": plan["error"]}
    zone, zone_problem = cs.zone_of(plan)
    today = cs.today_in_zone(now, zone)
    day = today if day is None else day
    _check_day(day, today)
    data = build(index_root, day, zone, now)
    data["zone_problem"] = zone_problem
    if plan["status"] != "approved":
        data["notes"].append(("no approved plan" if plan["status"] == "none" else "the approved plan cannot be read") + ": the time zone is the machine's")
    path = write_report(index_root, day, render(data), today=today)
    filed = data["filed"]
    return {"path": str(path), "day": data["day"], "zone": zone, "counts": data["counts"], "filed": None if _broken(filed) else filed["total"],
            "notes": data["notes"]}
