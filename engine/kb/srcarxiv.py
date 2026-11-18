"""arXiv search as a source of candidates for the unattended crawl (`docs/specs/population.md`, "Discovery").

`search` turns a query into candidate papers through arXiv's legacy API (`https://export.arxiv.org/api/query`, user manual and terms of use
read on 2026-11-16: `info.arxiv.org/help/api/`, the pages and their hashes are in the plan's Result), through a
`get(url, headers=None, timeout=None) -> (status, headers, body)` function that the caller gives.

What was read and what follows from it:

- The terms ask for **no more than one request every three seconds, one connection at a time, for all the machines that you control as a
  whole**, and an attempt to get round it may be blocked. `Pacer` keeps that pause, with a clock and a sleep that a test can replace, and
  cannot be made shorter than three seconds. It is one pacer for the whole run: the runner's `capture-arxiv` asks the same API and shares the
  pause, so the runner has to wait on the same pacer before it asks, or the two together go over the rule.
- No key and no registration is needed, and no user-agent is asked for: the agent is the honest generic one of `srcopenalex`, and no contact
  address is sent.
- The answer is an Atom feed, which is untrusted text. It is read as the capture reads one (`capture_arxiv.parse_atom`): plain UTF-8 only, no
  NUL, no DOCTYPE or ENTITY declaration, then the standard library's parser; and a feed with over 20,000 tags, or one that is not an Atom feed,
  is a refusal. **The capture's checks are written again here and not imported**, because `parse_atom` reads one paper and has them inline,
  and to share them `capture_arxiv.py` would have to be changed, which this plan does not own; a test shows that the capture refuses the same
  bodies, and when that file is free the checks can move to one place.
- Only plain words go into the search: the query is cut into its letters and digits, the small words and the words that topics put before a
  subject are dropped, at most the first `MAX_TERMS` (three) of the rest are kept, each is a term `all:<word>` joined with AND, and
  nothing of the query's own punctuation, operators or field names reaches arXiv's query syntax.
- Only the id of an entry is used (the title and the abstract are not read), and it must be an arXiv abstract address that
  `capture_arxiv.parse_id` takes; the candidate is rebuilt from that id, as `srcopenalex` does for an arXiv paper."""

import math
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from urllib.parse import quote

from . import KbError, capture_arxiv, srcopenalex, textutil

API = "https://export.arxiv.org/api/query"  # as `capture_arxiv.API_BASE`
USER_AGENT = srcopenalex.USER_AGENT
TIMEOUT = 30
MAX_BODY = 1_000_000  # as `capture_arxiv.METADATA_MAX_BYTES`
MAX_TAGS = 20_000
MAX_TERMS = 3  # the words a search asks for: every word must match (`AND`), and a long phrase finds nothing (measured 2026-11-18: the whole phrase found no paper for ten phrases of ten, the first three words found ten for nine of them)
# words that a phrase of a topic carries and that no paper is searched for: the small words, and the words that put a subject in front of a kind of book (the list measured on 2026-11-18)
_STOP = frozenset("a an and are as at be by for from in into is it of on or the their to with using via toward towards textbooks textbook overview introduction advanced principles fundamentals comparative analysis".split())
MIN_GAP = 3.0
MAX_LIMIT = 50
_ATOM = "{http://www.w3.org/2005/Atom}"
_WORDS = re.compile(r"[^\W_]+")
_ENTRY_ID = re.compile(r"https?://arxiv\.org/abs/(?P<rest>[^\s]+)", re.ASCII)


class SourceRefused(srcopenalex.SourceRefused):
    """arXiv refused, answered something that is not what was expected, or could not be asked: the same refusal as every source raises
    (a caller catches `srcopenalex.SourceRefused`), named for this source."""

    def __init__(self, reason, partial=None):
        super().__init__(reason, partial)
        self.args = (f"arXiv: {self.reason}",)


def _refuse(message):
    return KbError(f"the arXiv source: {message}")


class Pacer:
    """The pause between two requests to arXiv: at least `gap` seconds (three at the least, as the terms of use ask) from the start of one
    to the start of the next. `wait()` sleeps for what is left of it and then notes the time of the request that is about to be made. A
    clock that goes back never makes it wait longer than `gap`."""

    def __init__(self, gap=MIN_GAP, clock=time.monotonic, sleep=time.sleep):
        if type(gap) not in (int, float) or not math.isfinite(gap) or not MIN_GAP <= gap <= 3600:
            raise _refuse(f"the pause is a number of seconds from {MIN_GAP:g} to 3600 (arXiv asks for no more than one request in three)")
        if not callable(clock) or not callable(sleep):
            raise _refuse("the clock and the sleep are functions")
        self.gap, self.clock, self.sleep, self.last = gap, clock, sleep, None

    def wait(self):
        now = self.clock()
        if self.last is not None:
            left = self.gap - (now - self.last)
            if left > 0:
                self.sleep(min(left, self.gap))
                now = self.clock()
        self.last = now


def _text(query):
    if not isinstance(query, str) or len(query) > 1000 or any(ord(c) < 32 or ord(c) == 127 for c in query):
        raise _refuse("a query is a text of 1 to 300 characters with no control character")
    cleaned = textutil.clean(query, 1000)
    if not 1 <= len(cleaned) <= 300:
        raise _refuse("a query is a text of 1 to 300 characters with no control character")
    return cleaned


def _headers_type(headers):
    """The media type that the answer says it has (lower case, with no parameters), None if it says nothing, and a refusal if the
    header is there and is not text."""
    if not isinstance(headers, Mapping):
        return None
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == "content-type":
            if not isinstance(value, str):
                raise SourceRefused("the content type is not text")
            return value.split(";")[0].strip().lower()
    return None


def _fetch(get, url):
    try:
        status, headers, body = get(url, headers={"User-Agent": USER_AGENT, "Accept": "application/atom+xml"}, timeout=TIMEOUT)
    except srcopenalex.SourceRefused as refused:  # one that the client raises, named for this source
        raise SourceRefused(refused.reason, refused.partial) from None
    except KbError:
        raise SourceRefused("the request was refused or failed") from None
    if type(status) is not int:
        raise SourceRefused("the status is not a number")
    if status != 200:
        raise SourceRefused(f"status {status}")
    if not isinstance(body, bytes):
        raise SourceRefused("the answer is not bytes")
    if len(body) > MAX_BODY:
        raise SourceRefused(f"the answer is over {MAX_BODY} bytes")
    kind = _headers_type(headers)
    if kind is not None and kind not in capture_arxiv.METADATA_TYPES:
        raise SourceRefused("the answer is not XML")
    # as `capture_arxiv.parse_atom` reads an answer: plain UTF-8 only (a UTF-16 answer has NUL bytes between its letters, which would
    # hide a declaration from the check), and no declaration of a type or an entity
    if b"\x00" in body:
        raise SourceRefused("the answer is not plain UTF-8 text")
    try:
        body.decode("utf-8")
    except UnicodeDecodeError:
        raise SourceRefused("the answer is not valid UTF-8") from None
    if re.search(rb"<!\s*(DOCTYPE|ENTITY)", body, re.I):
        raise SourceRefused("the answer carries a declaration, which is refused")
    if body.count(b"<") > MAX_TAGS:
        raise SourceRefused("the answer has too many tags")
    try:
        root = ET.fromstring(body)
    except (ET.ParseError, RecursionError, ValueError):
        raise SourceRefused("the answer is not XML that can be read") from None
    if root.tag != f"{_ATOM}feed":
        raise SourceRefused("the answer is not an Atom feed")
    return root


def search(query, get, limit, pacer):
    """Candidate papers for a search of arXiv, at most `limit` entries (1 to 50) in one request, after the pause that `pacer` keeps.
    Returns `{"candidates": [...], "rejected": []}` (the second list is empty: arXiv has no PDF-only paper), each candidate a row for
    `crawlqueue.enqueue` with `source` `arxiv` and the identity key `arxiv:<id without version>`. A refusal of the source is a
    `SourceRefused`; a wrong argument is a `KbError` and costs no request and no wait."""
    text = _text(query)
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise _refuse(f"limit must be a whole number from 1 to {MAX_LIMIT}")
    if not callable(get) or not callable(getattr(pacer, "wait", None)):
        raise _refuse("get is a function of the address and the pacer has a wait")
    words = _WORDS.findall(text)
    if not words:
        raise _refuse("a query needs at least one letter or digit")
    kept = [w for w in words if w.lower() not in _STOP][:MAX_TERMS] or words[:1]  # a phrase of nothing but small words keeps its first word
    terms = " AND ".join(f"all:{w}" for w in kept)
    url = API + "?" + "&".join(f"{key}={quote(value, safe=safe)}" for key, value, safe in [
        ("search_query", terms, ":"), ("start", "0", ""), ("max_results", str(limit), ""), ("sortBy", "relevance", ""),
        ("sortOrder", "descending", "")])
    pacer.wait()
    root = _fetch(get, url)
    entries = root.findall(f"{_ATOM}entry")
    if len(entries) > limit:
        raise SourceRefused("the answer has more entries than were asked for")
    ids = []
    for entry in entries:
        identity = entry.find(f"{_ATOM}id")
        said = (identity.text or "").strip() if identity is not None else ""
        if "/api/errors" in said:
            raise SourceRefused("arXiv reports an error")  # its own words are not repeated
        found = _ENTRY_ID.fullmatch(said)
        if found:
            try:
                ids.append(capture_arxiv.parse_id(found.group("rest"))[0])
            except KbError:
                pass
    candidates = []
    for paper in dict.fromkeys(ids):
        candidates.append({"address": f"https://arxiv.org/abs/{paper}", "identity_key": f"arxiv:{paper}", "source": "arxiv",
                           "found_from": text, "depth": 0})
    return {"candidates": candidates, "rejected": []}
