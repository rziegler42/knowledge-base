"""The refill of the candidate queue of the unattended crawl, and the command that shows what a refill would do
(`docs/specs/population.md`, "Discovery" and "The queue and the seen list").

`fill` is the one function the runner calls to refill the queue. It asks the sources the plan switches on (OpenAlex, arXiv, Wikipedia and,
only if the owner's plan switches it on, a web search engine) for candidates, by the owner's topics and by the citation links of the works already kept,
and puts what they return in the queue through `crawlqueue`: within the plan's caps, in the shares the plan gives, at the pace of each
source. It holds no state of its own beyond what it writes in the queue's `counters` table:

- `source_off:<name>`, by day: a source that refused today is not asked again that day (a day is a UTC day, as OpenAlex's budget is), except that a
  refusal that says `for_day` is False (an OpenAlex 429 that shows budget left) leaves the source alone for the rest of that refill only and writes nothing here;
- `walked:<work>`, under the day `permanent`: a kept work whose citations have been walked is not walked again;
- `web_search_queries`, by day: the queries made to a search engine today.

None of these is a row of `candidates`: discovery inserts `queued`, `blocked` and `rejected: type` rows and changes no row.

The plan is a dictionary of exactly the keys of `PLAN` (a key left out has the spec's default; one that is not in `PLAN` is refused). The
runner's own plan has many more keys: `read_plan` takes these from a plan file and leaves the rest, and the real parser is the runner's."""

import datetime
import math
import re
import time
from collections.abc import MutableMapping

from . import KbError, config, crawlqueries, crawlqueue, crawltopics, models, srcarxiv, srcopenalex, srcwebsearch, srcwikipedia, textutil

SOURCES = ("openalex", "arxiv", "wikipedia", "web_search")  # the order in which a pick asks them
PAGE = 10  # works asked for in one request
MAX_PICKS = 50  # queries made in one refill, whatever the target
PERMANENT = "permanent"
_INT, _SHARE, _SECONDS, _SWITCH = "int", "share", "seconds", "switch"
# key: (section of the plan file, kind, default, lowest, highest)
PLAN = {
    "queued_total": ("limits", _INT, 20000, 1, 10**6),
    "queued_per_domain": ("limits", _INT, 50, 1, 10**5),
    "queue_low": ("limits", _INT, 100, 0, 10**6),
    "discover_target": ("limits", _INT, 200, 1, 2000),
    "queries_per_topic": ("limits", _INT, 3, 1, 10),
    "wander_share": ("sources", _SHARE, 0.2, 0, 1),
    "wander_depth": ("sources", _INT, 2, 0, 10),
    "wander_per_work": ("sources", _INT, 5, 1, 20),
    "openalex": ("sources", _SWITCH, True, None, None),
    "arxiv": ("sources", _SWITCH, True, None, None),
    "wikipedia": ("sources", _SWITCH, True, None, None),
    "web_search": ("sources", _SWITCH, False, None, None),
    "gap_openalex_s": ("sources", _SECONDS, 1, 0, 3600),
    "gap_arxiv_s": ("sources", _SECONDS, 3, 0, 3600),
    "gap_wikipedia_s": ("sources", _SECONDS, 1, 0, 3600),
    "gap_web_search_s": ("sources", _SECONDS, 30, 0, 3600),
    "web_search_per_day": ("sources", _INT, 20, 0, 1000),
}
_NOW = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_SECTION = re.compile(r"\[([a-z_]+)\]")
_LINE = re.compile(r"([a-z_][a-z0-9_]*)[ \t]*=(.*)")
_NUMBER = re.compile(r"[0-9]{1,9}(?:\.[0-9]{1,15})?")  # bounded, so that no number is a thousand digits that `int` cannot read
_WHOLE = re.compile(r"[0-9]{1,9}")


def _refuse(message):
    return KbError(f"the refill of the queue: {message}")


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def normalize_plan(plan):
    """`plan` with the spec's default for each key it leaves out; a key that is not one of the plan's, or a value of the wrong kind or out of
    range, is a refusal."""
    if not isinstance(plan, dict):
        raise _refuse("the plan is a dictionary")
    made = {key: spec[2] for key, spec in PLAN.items()}
    for key, value in plan.items():
        spec = PLAN.get(key) if isinstance(key, str) else None
        if spec is None:
            raise _refuse(f"{textutil.literal(key)} is not a key of the plan")
        _, kind, _, low, high = spec
        if kind == _SWITCH:
            good = type(value) is bool
        elif kind == _INT:
            good = type(value) is int and low <= value <= high
        else:
            good = _number(value) and low <= value <= high
        if not good:
            raise _refuse(f"{key} is not a value that the plan takes")
        made[key] = value
    return made


def read_plan(path):
    """The values of a crawl plan file for the keys of `PLAN`, as `normalize_plan` takes them (a key that the file does not give is not in
    the answer). The file is the spec's form (`[section]` lines and `key = value` lines, a hash starting a comment anywhere in a line); keys
    that this refill does not use are left alone, a key of the plan in another section than its own is refused, and a refusal names the line
    and never quotes it."""
    text = crawltopics.read_text(path, "the crawl plan file")
    made, section, seen = {}, None, set()  # `seen` holds (section, key): a key may be in two sections, not twice in one
    for number, raw in enumerate(text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n").split("\n"), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        found = _SECTION.fullmatch(line)
        if found:
            section = found.group(1)
            continue
        found = _LINE.fullmatch(line)
        if not found or section is None:
            raise _refuse(f"line {number}: a line is [section] or key = value, under a section")
        key, value = found.group(1), found.group(2).strip()
        if (section, key) in seen:
            raise _refuse(f"line {number}: the key is given twice in the section")
        seen.add((section, key))
        spec = PLAN.get(key)
        if spec is None:
            continue
        if spec[0] != section:
            raise _refuse(f"line {number}: this key belongs to the section [{spec[0]}]")
        made[key] = _value(spec, key, value, number)
    return made


def _value(spec, key, value, number):
    _, kind, _, _, _ = spec
    if kind == _SWITCH:
        lower = value.lower()
        if lower == "on" or (key == "web_search" and lower == "duckduckgo"):
            return True
        if lower == "off":
            return False
        raise _refuse(f"line {number}: the value is on or off" + (" (or duckduckgo)" if key == "web_search" else ""))
    if kind == _INT:
        if not _WHOLE.fullmatch(value):
            raise _refuse(f"line {number}: the value is a whole number")
        return int(value)
    if not _NUMBER.fullmatch(value):
        raise _refuse(f"line {number}: the value is a number")
    return float(value) if "." in value else int(value)


def date_of(now):
    """The date of a UTC time written `2026-11-16T10:00:00Z`; any other form is a refusal."""
    if not isinstance(now, str) or not _NOW.fullmatch(now):
        raise _refuse("the time is a UTC time like 2026-11-16T10:00:00Z")
    try:
        return datetime.date.fromisoformat(now[:10])
    except ValueError:
        raise _refuse("the time is not a date") from None


class _Gap:
    """The least time between two requests to one source: `wait()` sleeps for what is left of it."""

    def __init__(self, seconds, clock, sleep):
        self.seconds, self.clock, self.sleep, self.last = seconds, clock, sleep, None

    def wait(self):
        now = self.clock()
        if self.last is not None:
            left = self.seconds - (now - self.last)
            if left > 0:
                self.sleep(min(left, self.seconds))
                now = self.clock()
        self.last = now


def _paced(get, gap):
    def paced(url, headers=None, timeout=None):
        gap.wait()
        return get(url, headers=headers, timeout=timeout)

    return paced


def _counter(conn, day, key):
    row = conn.execute("SELECT n FROM counters WHERE day = ? AND key = ?", (day, key)).fetchone()
    return row[0] if row else 0


def _bump(conn, day, key):
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("INSERT OR IGNORE INTO counters (day, key, n) VALUES (?, ?, 0)", (day, key))
        conn.execute("UPDATE counters SET n = n + 1 WHERE day = ? AND key = ?", (day, key))
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def _in_turn(quotas):
    """The topics' picks one topic at a time in turn, so that a refill that stops early has reached many topics and not the first few."""
    left, order = list(quotas), []
    while any(left):
        for index, count in enumerate(left):
            if count:
                order.append(index)
                left[index] -= 1
    return order


def _parts(plan, queued=0):
    budget = min(plan["discover_target"], max(0, plan["queued_total"] - queued))
    wander = int(budget * plan["wander_share"])
    return budget - wander, wander


def _picks(plan, topics, topic_part, day):
    if not topic_part or not topics:
        return []
    count = min(MAX_PICKS, max(1, math.ceil(topic_part / PAGE)))
    return _in_turn(crawltopics.quota(topics, count, (day - datetime.date(1970, 1, 1)).days))


def fill(conn, plan, topics, *, now, get, chat=None, sources=None, log=None, cache=None, is_blocked=None, canon_address=None, site_of=None,
         arxiv_pacer=None, clock=time.monotonic, sleep=time.sleep, pdfs=False):
    """Refill the queue. Returns early with nothing added when the queue holds `queue_low` rows or more that are queued (a `queue_low` of
    nothing means the queue is never refilled); otherwise adds up to `discover_target` rows, never more, and never past the total cap of
    the queue (which ends the refill; a registrable domain at its own cap only leaves that row): `1 - wander_share` of them from queries made from the topics (the
    topics' picks for the day, one query a pick, asked of each source that is on in the order OpenAlex, arXiv, Wikipedia), and `wander_share`
    from the citation links of kept works (at most `wander_part // wander_per_work` kept works, never one twice). A source that refuses
    (`srcopenalex.SourceRefused`) is off for the rest of the day, or for the rest of this refill when the refusal says so (`for_day` is False), and the others go on.

    `conn` is a `crawlqueue` connection; `plan` the dictionary of `PLAN`; `topics` what `crawltopics.read_topics` gives; `now` a UTC time
    (`2026-11-16T10:00:00Z`; its date is the day); `get(url, headers=None, timeout=None) -> (status, headers, body)` the shared web client.
    `chat(prompt)` is the model of `crawlqueries` (none: the queries are the topic's own) and `cache` the dictionary it keeps its answers in
    (the caller keeps it between runs, in the index root, mode 600). `sources` replaces the source modules (a dictionary of name to an
    object with `search`, and with `wander` for openalex); `log(step, outcome, **fields)` is called for each request and each row, with the
    steps `discover`, `enqueue` and `block`, and no query is ever in a line. `is_blocked(address)` is the owner's blacklist and the public
    lists: it gives a reason (`owner` or `list:<name>`) for an address that is off limits, which is then recorded as `blocked` and not
    queued. `canon_address` and `site_of` are `webaddr`'s, by default. `arxiv_pacer` is the pause of arXiv, which the runner shares with its
    `capture-arxiv`; without one a pacer of the plan's gap (never under three seconds) is made for this refill. `clock` and `sleep` keep
    the gaps between requests to each source. Returns a dictionary of the counts."""
    plan = normalize_plan(plan)
    day = date_of(now)
    key_day = day.isoformat()
    checks = {"get": get, "clock": clock, "sleep": sleep}
    for name, function in list(checks.items()) + [("chat", chat), ("log", log), ("is_blocked", is_blocked)]:
        if function is not None and not callable(function):
            raise _refuse(f"{name} is a function")
        if function is None and name in checks:
            raise _refuse(f"{name} is a function")
    if cache is None:
        cache = {}
    if not isinstance(cache, MutableMapping):
        raise _refuse("the cache is a dictionary that can be written")
    if arxiv_pacer is not None and not callable(getattr(arxiv_pacer, "wait", None)):
        raise _refuse("the pacer of arXiv has a wait")
    registry = {"openalex": srcopenalex, "arxiv": srcarxiv, "wikipedia": srcwikipedia, "web_search": srcwebsearch}
    if sources is not None:
        if not isinstance(sources, dict) or not set(sources) <= set(SOURCES):
            raise _refuse("sources is a dictionary of source names to the objects that ask them")
        registry.update(sources)
    for name, source in registry.items():
        if not callable(getattr(source, "search", None)) or (name == "openalex" and not callable(getattr(source, "wander", None))):
            raise _refuse(f"the source {name} has a search" + (" and a wander" if name == "openalex" else ""))

    def note(step, outcome, **fields):
        if log is not None:
            log(step, outcome, **fields)

    result = {"added": 0, "skipped": 0, "rejected": 0, "blocked": 0, "capped": False, "requests": {}, "refused": {}, "walked": 0}
    queued = crawlqueue.counts(conn)["queued"]
    if queued >= plan["queue_low"]:
        note("discover", "skipped", reason="the queue holds enough")
        return result
    topic_part, wander_part = _parts(plan, queued)
    limits = {"queued_total": plan["queued_total"], "queued_per_domain": plan["queued_per_domain"]}
    pass_through = {"canon_address": canon_address, "site_of": site_of, "now": now}
    off = {name for name in SOURCES if _counter(conn, key_day, f"source_off:{name}")}
    for name in SOURCES:
        if plan[name] and name in off:
            note("discover", "skipped", source=name, reason="the source is off for the day")
    gaps = {name: _Gap(plan[f"gap_{name}_s"], clock, sleep) for name in ("openalex", "wikipedia", "web_search")}
    paced = {name: _paced(get, gap) for name, gap in gaps.items()}
    state = {"topic": 0, "pacer": arxiv_pacer}

    def put(kind, row):
        address = row["address"]
        reason = is_blocked(address) if is_blocked is not None else None
        if reason is not None:
            code = crawlqueue.insert_blocked(conn, row, reason, **pass_through)
            if code == "blocked":
                result["blocked"] += 1
                note("block", "blocked", candidate=address, reason=reason)
            else:
                result["skipped"] += 1
                note("block", "skipped", candidate=address, reason=code)
            return True
        if kind == "rejected":
            code = crawlqueue.insert_rejected(conn, row, "type", **pass_through)
            if code == "rejected":
                result["rejected"] += 1
                note("enqueue", "rejected", candidate=address, reason="type")
            else:
                result["skipped"] += 1
                note("enqueue", "skipped", candidate=address, reason=code)
            return True
        code = crawlqueue.enqueue(conn, row, limits=limits, **pass_through)
        if code == "queued":
            result["added"] += 1
            state["topic"] += 1 if row.get("topic") is not None else 0
            note("enqueue", "ok", candidate=address)
        elif code == "capped" and crawlqueue.counts(conn)["queued"] >= plan["queued_total"]:
            result["capped"] = True  # the queue is full: nothing more is asked of anyone, and this row is not taken
            result["skipped"] += 1
            note("enqueue", "skipped", candidate=address, reason="capped")
            return False
        elif code == "capped":
            result["skipped"] += 1  # the registrable domain is at its cap: this row is left, and other sources and domains go on
            note("enqueue", "skipped", candidate=address, reason="domain cap")
        else:
            result["skipped"] += 1
            note("enqueue", "skipped", candidate=address, reason=code)
        return True

    def store(found, topic=None, weight=None, stop=lambda: False):
        """Put the rows of `found` in the queue until the queue is full or `stop()` (which is about rows that are queued: a row that is
        rejected for its type takes no room, and is recorded whatever the target); the `found_from` of each row that was left is the answer."""
        left = set()
        groups = (("candidate", found["candidates"] + found["rejected"]),) if pdfs else (("candidate", found["candidates"]), ("rejected", found["rejected"]))        # with PDFs on, a work whose only text is a PDF is a candidate
        for kind, rows in groups:
            for row in rows:
                if result["capped"] or (kind == "candidate" and stop()) or not put(
                        kind, dict(row, topic=topic, weight=weight) if topic is not None else dict(row)):
                    left.add(row.get("found_from"))
        return left

    def refused(name, error):
        result["refused"][name] = error.reason
        off.add(name)
        if error.for_day is not False:  # a refusal for this refill only (a 429 with budget left) is not written for the day: the next refill asks again
            _bump(conn, key_day, f"source_off:{name}")
        note("discover", "refused", source=name, reason=error.reason)

    def ask(name, query):
        source = registry[name]
        if name == "web_search":
            if _counter(conn, key_day, "web_search_queries") >= plan["web_search_per_day"]:
                note("discover", "skipped", source=name, reason="the daily number of queries is reached")
                return None
            _bump(conn, key_day, "web_search_queries")
        result["requests"][name] = result["requests"].get(name, 0) + 1
        try:
            if name == "arxiv":
                if state["pacer"] is None:
                    state["pacer"] = srcarxiv.Pacer(max(srcarxiv.MIN_GAP, plan["gap_arxiv_s"]), clock=clock, sleep=sleep)
                found = source.search(query, get, PAGE, state["pacer"])
            else:
                found = source.search(query, paced[name], PAGE)
        except srcopenalex.SourceRefused as error:
            refused(name, error)
            return None
        note("discover", "ok", source=name, n=len(found["candidates"]) + len(found["rejected"]))
        return found

    asking = [name for name in SOURCES if plan[name] and name in registry]
    if topic_part and topics and asking:
        queries, uses = {}, {}
        for index in _picks(plan, topics, topic_part, day):
            if result["capped"] or state["topic"] >= topic_part:
                break
            topic, weight, _ = topics[index]
            if index not in queries:
                queries[index] = crawlqueries.make_queries(topic, plan["queries_per_topic"], chat, cache, crawlqueries.PROMPT_VERSION)
            query = queries[index][uses.get(index, 0) % len(queries[index])]
            uses[index] = uses.get(index, 0) + 1
            for name in asking:
                if name in off:
                    continue
                if result["capped"] or state["topic"] >= topic_part:
                    break
                found = ask(name, query)
                if found is not None:
                    store(found, topic, weight, stop=lambda: state["topic"] >= topic_part)

    if wander_part and plan["openalex"] and "openalex" not in off and not result["capped"]:
        kept = crawlqueue.kept_sources(conn, "openalex", plan["wander_depth"])
        fresh, listed = [], set()
        for work in kept:  # a work is listed once, and only if its citations have not been walked
            if work[0] not in listed and not _counter(conn, PERMANENT, "walked:" + work[0][len("openalex:"):]):
                fresh.append(work)
                listed.add(work[0])
        chosen = fresh[: max(1, wander_part // plan["wander_per_work"])]
        if chosen:
            result["requests"]["openalex"] = result["requests"].get("openalex", 0) + 1
            before = result["added"]
            full = lambda: result["added"] - before >= wander_part  # noqa: E731  the walk takes its share and no more: the rest is left
            try:
                found = registry["openalex"].wander(chosen, paced["openalex"], plan["wander_per_work"], plan["wander_depth"],
                                                    seen={k[0] for k in kept})
            except srcopenalex.SourceRefused as error:
                refused("openalex", error)  # first, so that a refusal is recorded whatever happens to the rows found before it
                store(error.partial, stop=full)
            else:
                note("discover", "ok", source="openalex", n=len(found["candidates"]) + len(found["rejected"]))
                left = store(found, stop=full)
                for source_id, _ in chosen:
                    if source_id not in left:  # a work that has rows left over (its share or the queue was full) is walked again
                        _bump(conn, PERMANENT, "walked:" + source_id[len("openalex:"):])
                        result["walked"] += 1
    result["off"] = sorted(off)
    return result


def _model_state(load_config):
    """Whether the config sets a chat model for `crawl-query`: no call is made and no entry, server or model is named."""
    none = {"configured": False, "would_call": False, "calls": 0}
    try:
        cfg = load_config()
    except KbError:
        return dict(none, why="there is no config that sets crawl-query")
    if cfg.get("models_on") is not True:
        return dict(none, why="model work is off in the config")
    try:
        name = models.optional(cfg, "crawl-query")
    except KbError as error:
        return dict(none, why="the config does not say: " + textutil.clean(str(error), 160))
    if name is None:
        return dict(none, why="tasks.crawl-query is not set in the config")
    return {"configured": True, "would_call": True, "calls": 0, "why": "tasks.crawl-query names a chat entry"}


def check(plan_path, topics_path, *, now=None, load_config=config.load):
    """What a refill would send, from a plan file and a topics file, and nothing sent and nothing written: no request is made, no model is
    called, the queue is not opened (so how many rows are queued, and which kept works there are to walk, are not known) and no cache is
    kept. The queries are shown when no model would make them."""
    plan = normalize_plan(read_plan(plan_path))
    topics = crawltopics.read_topics(topics_path)
    moment = now or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    day = date_of(moment)
    topic_part, wander_part = _parts(plan)
    order = _picks(plan, topics, topic_part, day)
    model = _model_state(load_config)
    if model["would_call"]:
        model["calls"] = len({i for i in order})
        queries = None
    else:
        made, uses, queries = {}, {}, []
        for index in order:
            if index not in made:
                made[index] = crawlqueries.make_queries(topics[index][0], plan["queries_per_topic"], None, {}, crawlqueries.PROMPT_VERSION)
            queries.append(made[index][uses.get(index, 0) % len(made[index])])
            uses[index] = uses.get(index, 0) + 1
    shown = {}
    for name in SOURCES:
        asked = len(order) if plan[name] else 0
        if name == "web_search":
            asked = min(asked, plan["web_search_per_day"])  # a day's queries to a search engine are at most the plan's number
        shown[name] = {"on": plan[name], "requests": asked, "gap_s": plan[f"gap_{name}_s"],
                       "queries": queries[:asked] if queries is not None and asked else ([] if queries is not None else None)}
    works = max(1, wander_part // plan["wander_per_work"]) if wander_part and plan["openalex"] else 0
    return {"check": True, "day": day.isoformat(), "plan": plan, "topics": len(topics), "picks": len(order), "model": model, "sources": shown,
            "wander": {"on": bool(works), "rows": wander_part, "kept_works_at_most": works, "requests_per_kept_work": 3,
                       "per_work": plan["wander_per_work"], "depth": plan["wander_depth"],
                       "note": "the queue is not read here, so the kept works to walk from are not known"},
            "sends": "nothing", "writes": "nothing"}
