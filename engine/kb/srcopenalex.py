"""OpenAlex as a source of candidates for the unattended crawl (`docs/specs/population.md`, "Discovery").

Two things come out of it: `search` turns a query into candidates, and `wander` takes the works a kept work cites and the works that cite
it. Both ask the API of OpenAlex (`https://api.openalex.org`, documentation read on 2026-11-16: `help.openalex.org`, the pages and their
hashes are in the plan's Result) through a `get(url, headers=None, timeout=None) -> (status, headers, body)` function that the caller
gives: the shared web client once it exists, a fake in a test.

What was read and what follows from it:

- Basic queries need no key and no contact address; a free key gives ten times the daily budget and is needed only for paging past the
  first page, which nothing here does. So no key and no address is sent, and the agent is honest and generic. Without a key the day's
  budget is $0.10: a search costs $0.001, a filter-only list $0.0001, so about 100 searches a day. Over it the API answers 429, and it also answers
  429 for a pace or a load limit (read on 2026-11-18 from `help.openalex.org/api/errors/`). The client keeps no body for a status other than 200,
  so a 429 is told by the header `X-RateLimit-Remaining`: a plain number above zero is a refusal for this refill only (`for_day` is False), and
  zero, no header or anything else is a refusal for the day.
- The answers are data. The size is capped, the JSON is read strictly (no repeated key, no NaN, nothing deeper than the parser takes), and
  every address in it is checked before it is used. An answer that is not what was expected is a refusal of the source for the day
  (`SourceRefused`), with the reason and not a word of what the server sent.

How a work becomes a candidate (the spec's rules):

1. A work that is not open access is skipped.
2. A work with an arXiv location (the landing page or the PDF address of one of its open locations) is the arXiv paper: identity key
   `arxiv:<id without version>`, address `https://arxiv.org/abs/<id>`.
3. Otherwise the first open location with a landing page that looks like a web page (not a PDF, and not the same address as its PDF) is the
   candidate, at that address. This is a judgement from the address alone; the page itself is fetched, and judged, by the runner.
4. Otherwise, a work whose only full text is a PDF is a `rejected` row with the reason `type`, so that the report counts what was missed.
5. A work with no usable address, or whose id is not an OpenAlex work id, is skipped.

Wandering ranks the works found by how much they are cited (most first), then by the number of the OpenAlex id (lowest first), and takes
`per_work` of them in all from one kept work: half, the odd place included, from the works it cites, the rest from the works that cite
it, and a place that one side cannot fill goes to the other.

What this module does not do, and the client that fetches an address must: it cannot limit how much of an answer is read (the size is
checked after the whole body has come, so the client must stop the read at a limit), and it cannot say where a host name leads (it
turns away `localhost` and a host written as a number that is private, loopback, link-local, reserved or multicast, or that is written
in a form of a number that the standard library does not read, but a name may point at such an address, so the client checks the
address it connects to)."""

import ipaddress
import json
import re
import unicodedata
from collections.abc import Mapping
from urllib.parse import quote, urlsplit

from . import KbError, capture_arxiv, textutil

USER_AGENT = "knowledge-base-discovery/0.1"  # honest and generic: no contact address, and no pretence of being a browser
TIMEOUT = 30
MAX_BODY = 2_000_000
BASE = "https://api.openalex.org"
SELECT = "id,type,cited_by_count,open_access,best_oa_location,locations"
MAX_REFERENCES = 300  # the references of one kept work that are looked at
BATCH = 100  # the OR limit of one filter and the largest page
INCOMING_MARGIN = 10  # works asked for beyond `per_work` when asking who cites a work, so that works already seen do not use up the places
_WORK_ID = re.compile(r"https://openalex\.org/(W[0-9]{1,12})")
_SOURCE_ID = re.compile(r"openalex:(W[0-9]{1,12})")
_CONTROL = ("Cc",)
_PLAIN_NUMBER = re.compile(r"[0-9]{1,15}(?:\.[0-9]{1,15})?")  # ASCII digits and at most one point: no sign, no exponent, no `NaN`
# A host written as numbers in a form that a browser or a resolver may read as an address (`2130706433`, `127.1`, `0x7f.1`): no real host
# name is all numbers, since the last label of a name is never one.
_NUMBER_HOST = re.compile(r"(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*", re.IGNORECASE)


class SourceRefused(KbError):
    """OpenAlex refused, answered something that is not what was expected, or could not be asked. The source is off for the rest of the
    day (the caller records it), unless `for_day` is False: then it is off for the rest of this refill only (a 429 that shows budget left).
    `reason` is a short cleaned text and never the server's words; `partial` holds what was found before the refusal, in the form `search`
    and `wander` return, for the caller to keep."""

    def __init__(self, reason, partial=None, for_day=True):
        self.reason = textutil.clean(reason, 200)
        self.partial = partial if partial is not None else {"candidates": [], "rejected": []}
        self.for_day = for_day
        super().__init__(f"OpenAlex: {self.reason}")


def _refuse(message):
    return KbError(f"the OpenAlex source: {message}")


def _int(name, value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise _refuse(f"{name} must be a whole number from {low} to {high}")
    return value


def _get(get):
    if not callable(get):
        raise _refuse("get is a function of the address")
    return get


def _query(text):
    if not isinstance(text, str) or len(text) > 1000 or any(unicodedata.category(c) in _CONTROL for c in text):
        raise _refuse("a query is a text of 1 to 300 characters with no control character")
    cleaned = textutil.clean(text, 1000)
    if not 1 <= len(cleaned) <= 300:
        raise _refuse("a query is a text of 1 to 300 characters with no control character")
    return cleaned


def _url(path, params):
    """The address of a request. Each value is percent-encoded, so a query cannot add a parameter; only the marks that the documented
    forms use (`:`, `,` and `|` in a filter, `,` in a list of fields) are left as they are."""
    return BASE + path + "?" + "&".join(f"{key}={quote(value, safe=safe)}" for key, value, safe in params)


def _plain_number(headers, name):
    """The plain number (at most 20 characters) that the header `name` holds, as written, or None: the header is absent, is given more than once
    (the client joins two values with a comma), or holds anything else. The header is read in any case; nothing else of it is ever used."""
    if not isinstance(headers, Mapping):
        return None
    found = [value for key, value in headers.items() if isinstance(key, str) and key.lower() == name and isinstance(value, str)]
    if len(found) != 1:
        return None
    value = found[0].strip()
    return value if len(value) <= 20 and _PLAIN_NUMBER.fullmatch(value) else None


def _fetch(get, url):
    """The JSON object that the answer to `url` holds, or a `SourceRefused`."""
    try:
        status, headers, body = get(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=TIMEOUT)
    except SourceRefused:
        raise
    except KbError:
        raise SourceRefused("the request was refused or failed") from None
    if type(status) is not int:
        raise SourceRefused("the status is not a number")
    if status == 429:
        # The client keeps no body for a status other than 200, so the headers decide, and only as plain numbers: budget left (`X-RateLimit-Remaining`
        # above zero) means a pace or a load answer, which ends this refill only; zero, absent or anything odd ends the day, as every refusal does.
        remaining, retry = _plain_number(headers, "x-ratelimit-remaining"), _plain_number(headers, "retry-after")
        raise SourceRefused(f"status 429 (remaining {remaining or 'none'}, retry-after {retry or 'none'})",
                            for_day=not (remaining is not None and float(remaining) > 0))
    if status != 200:
        raise SourceRefused(f"status {status}")
    if not isinstance(body, bytes):
        raise SourceRefused("the answer is not bytes")
    if len(body) > MAX_BODY:
        raise SourceRefused(f"the answer is over {MAX_BODY} bytes")

    def no_repeat(pairs):
        made = {}
        for key, value in pairs:
            if key in made:
                raise ValueError("a key is repeated")
            made[key] = value
        return made

    def no_constant(name):
        raise ValueError(name)

    try:
        data = json.loads(body.decode("utf-8"), object_pairs_hook=no_repeat, parse_constant=no_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise SourceRefused("the answer is not JSON of the expected kind") from None
    if not isinstance(data, dict):
        raise SourceRefused("the answer is not a JSON object")
    return data


def _results(data, most):
    results = data.get("results")
    if not isinstance(results, list) or not all(isinstance(item, dict) for item in results):
        raise SourceRefused("the answer has no list of works")
    if len(results) > most:
        raise SourceRefused("the answer has more works than were asked for")
    return results


def _web(url):
    """`url` if it is a plain http or https address of at most 2,048 characters with a host, no user name and nothing hidden, else None."""
    if not isinstance(url, str) or not url or len(url) > 2048 or textutil.clean(url, len(url)) != url or any(c.isspace() for c in url):
        return None
    try:
        parts = urlsplit(url)
        parts.port  # a port that is not a number is an error here
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname or "@" in parts.netloc:
        return None
    host = parts.hostname.rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        return None
    try:
        number = ipaddress.ip_address(host)
        if not number.is_global or number.is_multicast:  # a private, loopback, link-local, reserved or multicast address as a number
            return None
    except ValueError:
        if _NUMBER_HOST.fullmatch(host):  # numbers in a form that is not a plain address (`127.1`, `2130706433`): not read here, so not taken
            return None
        # a name: whether it leads to such an address is for the client that fetches it to check, as it connects
    return url


def _pdf_like(url):
    return urlsplit(url).path.lower().endswith(".pdf")


def _arxiv_id(url):
    """The id (with no version) of the arXiv paper that `url` is the abstract page or the PDF of, or None. Only `arxiv.org` itself, no
    user name, port, query or fragment, and an id that `capture_arxiv.parse_id` takes."""
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or parts.netloc.lower() not in ("arxiv.org", "www.arxiv.org") or parts.query or parts.fragment:
        return None
    for prefix in ("/abs/", "/pdf/"):
        if parts.path.startswith(prefix):
            rest = parts.path[len(prefix):]
            if prefix == "/pdf/" and rest.endswith(".pdf"):
                rest = rest[:-4]
            try:
                return capture_arxiv.parse_id(rest)[0]
            except KbError:
                return None
    return None


def _source_id(work):
    found = _WORK_ID.fullmatch(work.get("id")) if isinstance(work.get("id"), str) else None
    return f"openalex:{found.group(1)}" if found else None


def _resolve(work):
    """`("candidate" | "rejected", fields)` for a work, or None if it is skipped; see the rules in the module's text."""
    source_id = _source_id(work)
    oa = work.get("open_access")
    if source_id is None or not isinstance(oa, dict) or oa.get("is_oa") is not True:
        return None
    where = [work.get("best_oa_location")]
    if isinstance(work.get("locations"), list):
        where += work["locations"]
    where = [w for w in where if isinstance(w, dict) and w.get("is_oa") is True]
    base = {"source": "openalex", "source_id": source_id}
    for place in where:
        for url in (place.get("landing_page_url"), place.get("pdf_url")):
            ident = _arxiv_id(url)
            if ident:
                return "candidate", dict(base, address=f"https://arxiv.org/abs/{ident}", identity_key=f"arxiv:{ident}")
    refused = None
    for place in where:
        landing, pdf = _web(place.get("landing_page_url")), _web(place.get("pdf_url"))
        if landing and not _pdf_like(landing) and landing != pdf:
            return "candidate", dict(base, address=landing)
        if refused is None and (landing or pdf):
            refused = dict(base, address=pdf or landing)
    return ("rejected", refused) if refused else None


def _count(work):
    count = work.get("cited_by_count")
    return count if type(count) is int and count >= 0 else 0


def _key(fields):
    return fields.get("identity_key") or fields["address"]


def _resolved(works, excluded, allowed=None):
    """`(kind, fields, work)` for each work of `works` that resolves, leaving out a work whose source id or key is in `excluded`, a
    repeat of one already in the list, and, when `allowed` (source ids) is given, a work that is not one of those asked for."""
    made, local = [], set()
    for work in works:
        resolved = _resolve(work)
        if resolved is None:
            continue
        kind, fields = resolved
        if allowed is not None and fields["source_id"] not in allowed:
            continue
        if {fields["source_id"], _key(fields)} & (excluded | local):
            continue
        local |= {fields["source_id"], _key(fields)}
        made.append((kind, fields, work))
    return made


def _keep(chosen, found, taken, found_from, depth):
    for kind, fields, _ in chosen:
        found["candidates" if kind == "candidate" else "rejected"].append(dict(fields, found_from=found_from, depth=depth))
        taken |= {fields["source_id"], _key(fields)}


def search(query, get, limit):
    """Candidates for a search of OpenAlex works, open access only, at most `limit` works (1 to 100) in one request. Returns
    `{"candidates": [...], "rejected": [...]}`: the first are rows for `crawlqueue.enqueue`, the second for `insert_rejected` with the
    reason `type`. A refusal of the source is a `SourceRefused`."""
    text = _query(query)
    _int("limit", limit, 1, BATCH)
    get = _get(get)
    url = _url("/works", [("search", text, ""), ("filter", "open_access.is_oa:true", ":,|"), ("per_page", str(limit), ""),
                          ("select", SELECT, ",")])
    found = {"candidates": [], "rejected": []}
    _keep(_resolved(_results(_fetch(get, url), limit), set()), found, set(), text, 0)
    return found


def _references(get, number):
    data = _fetch(get, _url(f"/works/{number}", [("select", "id,referenced_works", ",")]))
    if data.get("id") != f"https://openalex.org/{number}":
        raise SourceRefused("the answer is about another work")
    refs = data.get("referenced_works", [])
    if not isinstance(refs, list):
        raise SourceRefused("the references are not a list")
    ids = []
    for ref in refs[: 10 * MAX_REFERENCES]:
        found = _WORK_ID.fullmatch(ref) if isinstance(ref, str) else None
        if found and found.group(1) not in ids:
            ids.append(found.group(1))
    return ids


def _ranked(items):
    """`items` in the ranking of the module's text, none of them the same work (or paper) as an earlier one."""
    chosen, keys = [], set()
    for item in sorted(items, key=lambda i: (-_count(i[2]), int(i[1]["source_id"][len("openalex:W"):]))):
        if {item[1]["source_id"], _key(item[1])} & keys:
            continue
        keys |= _names(item)
        chosen.append(item)
    return chosen


def _names(item):
    return {item[1]["source_id"], _key(item[1])}


def wander(kept, get, per_work, max_depth, seen=()):
    """The works that kept works cite and the works that cite them. `kept` is `[(source_id, depth), ...]` (what
    `crawlqueue.kept_sources` gives); a work at `max_depth` or deeper is not walked from, a source id that is not an OpenAlex work id is
    skipped, and a work is never taken that is one of the kept works or in `seen` (source ids) or already found.

    From each kept work at most `per_work` works are taken in all (the spec's `wander_per_work`, "works taken from one kept work"): the
    most cited first, one level deeper, with `found_from` the kept work, up to half of them (the odd place included) from the works it
    cites and the rest from the works that cite it, and a place that one side cannot fill passes to the other. A work whose only full
    text is a PDF takes a place and is returned as `rejected`. Two to five requests are made for a kept work (the work itself, none to
    three batches of its references, one for each 100 of the first 300 in the order OpenAlex lists them, and last who cites it, most
    cited first), and the strongest are chosen among the works looked at. A refusal is a `SourceRefused` whose `partial` holds what was found before it."""
    if not isinstance(kept, (list, tuple)) or not all(isinstance(k, (list, tuple)) and len(k) == 2 and type(k[1]) is int and k[1] >= 0
                                                       for k in kept):
        raise _refuse("kept is a list of (source_id, depth)")
    _int("per_work", per_work, 1, 20)
    _int("max_depth", max_depth, 0, 10)
    if not isinstance(seen, (set, frozenset, list, tuple)) or not all(isinstance(s, str) for s in seen):
        raise _refuse("seen is a set of source ids")
    get = _get(get)
    known = set(seen) | {k[0] for k in kept if isinstance(k[0], str) and _SOURCE_ID.fullmatch(k[0])}
    found, taken, done = {"candidates": [], "rejected": []}, set(), set()
    try:
        for source_id, depth in kept:
            matched = _SOURCE_ID.fullmatch(source_id) if isinstance(source_id, str) else None
            if not matched or depth >= max_depth or matched.group(1) in done:
                continue
            number = matched.group(1)
            done.add(number)
            origin = f"openalex:{number}"
            refs = [r for r in _references(get, number)[:MAX_REFERENCES] if f"openalex:{r}" not in known]
            cited = []
            for start in range(0, len(refs), BATCH):
                asked_for = refs[start:start + BATCH]
                url = _url("/works", [("filter", "openalex:" + "|".join(asked_for) + ",open_access.is_oa:true", ":,|"),
                                      ("per_page", str(BATCH), ""), ("select", SELECT, ",")])
                cited += _resolved(_results(_fetch(get, url), BATCH), known | taken, {f"openalex:{r}" for r in asked_for})
            cited = _ranked(cited)
            first = cited[: (per_work + 1) // 2]
            _keep(first, found, taken, origin, depth + 1)  # kept at once, so that a refusal on the next request still carries them
            asked = min(BATCH, per_work + INCOMING_MARGIN)
            url = _url("/works", [("filter", f"cites:{number},open_access.is_oa:true", ":,|"), ("sort", "cited_by_count:desc", ":"),
                                  ("per_page", str(asked), ""), ("select", SELECT, ",")])
            second = _ranked(_resolved(_results(_fetch(get, url), asked), known | taken))[: per_work - len(first)]
            _keep(second, found, taken, origin, depth + 1)
            more = [i for i in cited[len(first):] if not _names(i) & taken][: per_work - len(first) - len(second)]
            _keep(more, found, taken, origin, depth + 1)
    except SourceRefused as refused:
        refused.partial = found
        raise
    return found
