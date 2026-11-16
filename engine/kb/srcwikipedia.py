"""Wikipedia search as a source of candidates for the unattended crawl (`docs/specs/population.md`, "Discovery").

`search` turns a query into candidate articles of the English Wikipedia through the Action API (`https://en.wikipedia.org/w/api.php`,
`list=search`), through a `get(url, headers=None, timeout=None) -> (status, headers, body)` function that the caller gives. The documentation
(`mediawiki.org/wiki/API:Search` and `API:Etiquette`, the Wikimedia User-Agent policy and the robot policy, read on 2026-11-16; the pages and
their hashes are in the plan's Result) says:

- There is **no hard speed limit on reads**, but requests should be made one at a time, and a 429 asks for the delay in `Retry-After` to be
  respected: the pause between requests is the caller's (`discover.fill`, with the plan's `gap_wikipedia_s`), and a 429 is a refusal here, which
  turns the source off for the day.
- Wikimedia asks every script for **an informative User-Agent with contact information**, and says that an empty or generic one may get a 403
  and a block "without notice". There is no contact address to give (none of the owner's details leaves the machine), so the agent is the honest
  and generic one of `srcopenalex` (a name and a version, no pretence of a browser), the question is open, and **a 403 or 429 is a refusal that
  turns Wikipedia off for the day** and is not worked round. The owner may give an address in the plan later.
- Only plain words go into the search: the query is cut into its letters and digits, and the words AND, OR and NOT, which the search reads as
  operators, are written in lower case, so nothing of the query's own punctuation, quotation marks, operators (`intitle:`, `-word`) or wildcards
  reaches the search engine's syntax.
- Only the title of a page in the main namespace, with its page id, is used. The address is made from the title, with each mark that would
  change the address written out, and a title with a `.` or `..` part between slashes is left out (a real title cannot have one, and the
  address would be another path on the host); the snippet and everything else the answer holds is never read.

The answer is read as `srcopenalex` reads one: strict JSON, at most 2,000,000 bytes, a refusal that holds a fixed reason and none of the
server's words."""

import re
from urllib.parse import quote

from . import KbError, srcopenalex, textutil

API = "https://en.wikipedia.org/w/api.php"
PAGE = "https://en.wikipedia.org/wiki/"
MAX_WORDS = 12
MAX_LIMIT = 50
MAX_TITLE = 255
_WORDS = re.compile(r"[^\W_]+")
_OPERATORS = ("AND", "OR", "NOT")
_PATH_SAFE = "!$&'()*+,-./:;=@_~"  # what a page address keeps as it is


class SourceRefused(srcopenalex.SourceRefused):
    """Wikipedia refused, answered something that is not what was expected, or could not be asked: the same refusal as every source raises
    (a caller catches `srcopenalex.SourceRefused`), named for this source."""

    def __init__(self, reason, partial=None):
        super().__init__(reason, partial)
        self.args = (f"Wikipedia: {self.reason}",)


def _refuse(message):
    return KbError(f"the Wikipedia source: {message}")


def _text(query):
    if not isinstance(query, str) or len(query) > 1000 or any(ord(c) < 32 or ord(c) == 127 for c in query):
        raise _refuse("a query is a text of 1 to 300 characters with no control character")
    cleaned = textutil.clean(query, 1000)
    if not 1 <= len(cleaned) <= 300:
        raise _refuse("a query is a text of 1 to 300 characters with no control character")
    return cleaned


def _fetch(get, url):
    try:
        return srcopenalex._fetch(get, url)  # the strict reading of an answer is the one `srcopenalex` makes; only the name is ours
    except srcopenalex.SourceRefused as refused:
        raise SourceRefused(refused.reason, refused.partial) from None


def search(query, get, limit):
    """Candidate articles for a search of the English Wikipedia, at most `limit` pages (1 to 50) in one request. Returns
    `{"candidates": [...], "rejected": []}` (the second list is empty: a page is not rejected for its type here), each candidate a row for
    `crawlqueue.enqueue` with `source` `wikipedia` and the address of the page. A disambiguation page or a list is kept: judging it is the
    runner's. A refusal of the source is a `SourceRefused`; a wrong argument is a `KbError` and costs no request."""
    text = _text(query)
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise _refuse(f"limit must be a whole number from 1 to {MAX_LIMIT}")
    if not callable(get):
        raise _refuse("get is a function of the address")
    words = [w.lower() if w in _OPERATORS else w for w in _WORDS.findall(text)[:MAX_WORDS]]
    if not words:
        raise _refuse("a query needs at least one letter or digit")
    url = API + "?" + "&".join(f"{key}={quote(value, safe='')}" for key, value in [
        ("action", "query"), ("list", "search"), ("srsearch", " ".join(words)), ("srnamespace", "0"), ("srlimit", str(limit)),
        ("srprop", ""), ("srinfo", ""), ("format", "json"), ("formatversion", "2")])
    data = _fetch(get, url)
    if "error" in data or "errors" in data:
        raise SourceRefused("the API reports an error")  # its own words are not repeated
    found = data.get("query")
    pages = found.get("search") if isinstance(found, dict) else None
    if not isinstance(pages, list) or not all(isinstance(p, dict) for p in pages):
        raise SourceRefused("the answer has no list of pages")
    if len(pages) > limit:
        raise SourceRefused("the answer has more pages than were asked for")
    candidates, seen = [], set()
    for item in pages:
        title, number, ns = item.get("title"), item.get("pageid"), item.get("ns")
        if type(ns) is not int or ns != 0 or type(number) is not int or number < 1:
            continue
        if not isinstance(title, str) or not 1 <= len(title) <= MAX_TITLE or textutil.clean(title, 1000) != title:
            continue
        if any(part in (".", "..") for part in title.split("/")):  # `/wiki/../w/api.php` would be another path on the host
            continue
        address = PAGE + quote(title.replace(" ", "_"), safe=_PATH_SAFE)
        if number in seen or address in seen:
            continue
        seen |= {number, address}
        candidates.append({"address": address, "source": "wikipedia", "found_from": text, "depth": 0})
    return {"candidates": candidates, "rejected": []}
