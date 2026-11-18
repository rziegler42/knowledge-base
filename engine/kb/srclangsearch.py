"""LangSearch as a web search source of candidates for the unattended crawl (`docs/specs/population.md`, "Discovery"): a search engine with an API, a free plan and a documented answer
(`https://docs.langsearch.com/api/web-search-api.md`, read on 2026-11-18; the plan `2026-11-18-add-langsearch-as-a-web-search-source` has its hash). Off unless the owner's plan chooses it, and the
owner's terms to read: the licence is for "the purposes specified in these Terms", which the terms do not list, and the ban on "scraping, mining, or harvesting data" is not defined.

`search` turns a query into the pages that the answer lists, through a `post(body) -> (status, headers, body)` function that the caller gives: the caller's function sends `body` (a dictionary, which
it makes JSON) to the one address of the search and holds everything that makes the request what it is, so **this module never sees a credential and has no address to send to**. What it does:

- Only plain words go into the search: the query is cut into its letters and digits (at most 12 words), so that an operator, a bang, a field or a quotation cannot reach the engine. The request
  holds the words and a count and nothing else: no page text, no date or domain filter, no other field.
- Only the **address** of each result is taken (`data.webPages.value[].url`). The name, the snippet and the text of a result are server text and are never read, kept or logged; the page itself is
  fetched, scanned and judged by the crawl as any candidate is. An address is taken only if it is a plain public web address (`srcopenalex._web`'s check), and an address of LangSearch itself is left out.
- The answer is data. It must be JSON that the strict reader takes (no repeated key, no `NaN`), an object whose `code` is the whole number 200 and whose `data.webPages.value` is a list of at most 50
  objects that each have a text `url`; a list may be empty. Anything else is a refusal of the source, for the day, with a fixed reason that holds none of the server's words (`SourceRefused`).
- **A refusal is never worked round and nothing is retried.** A status other than 200 (a 429 is the rate limit or the day's allowance), an answer that is not what was expected, an error of the caller's
  function that is a `KbError` (named by a fixed text and none of its own), and a refusal that the caller's function raises (kept, with its fixed reason) are each a `SourceRefused`, which turns the source
  off for the day. An error that is not a `KbError` (the stop of a run, a fault of the caller) is not hidden."""

import json
import re
from collections.abc import Mapping
from urllib.parse import urlsplit

from . import KbError, srcopenalex, textutil

SOURCE = "web-search"  # the name `crawlqueue` gives this source: the one name for any web search engine
MAX_BODY = 1_000_000
MAX_WORDS = 12
MAX_LIMIT = 30
MAX_RESULTS = 50  # the most that the service gives in one answer (`count` is 1 to 50)
_OWN = ("langsearch.com",)
_WORDS = re.compile(r"[^\W_]+")


class SourceRefused(srcopenalex.SourceRefused):
    """The engine refused, answered something that is not what was expected, or could not be asked: the same refusal as every source raises
    (a caller catches `srcopenalex.SourceRefused`), named for this source."""

    def __init__(self, reason, partial=None):
        super().__init__(reason, partial)
        self.args = (f"LangSearch: {self.reason}",)


def _refuse(message):
    return KbError(f"the LangSearch source: {message}")


def _text(query):
    if not isinstance(query, str) or len(query) > 1000 or any(ord(c) < 32 or ord(c) == 127 for c in query):
        raise _refuse("a query is a text of 1 to 300 characters with no control character")
    cleaned = textutil.clean(query, 1000)
    if not 1 <= len(cleaned) <= 300:
        raise _refuse("a query is a text of 1 to 300 characters with no control character")
    return cleaned


def _media_type(headers):
    if not isinstance(headers, Mapping):
        return None
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == "content-type":
            if not isinstance(value, str):
                raise SourceRefused("the content type is not text")
            return value.split(";")[0].strip().lower()
    return None


def _own(host):
    host = host.lower().rstrip(".")
    return any(host == name or host.endswith("." + name) for name in _OWN)


def _no_repeat(pairs):
    made = {}
    for key, value in pairs:
        if key in made:
            raise ValueError("a key is repeated")
        made[key] = value
    return made


def _no_constant(name):
    raise ValueError(name)


def _answer(reply):
    """The list of results that the answer holds, or a `SourceRefused`."""
    try:
        status, headers, body = reply
    except (TypeError, ValueError):
        raise SourceRefused("the answer is not a status, headers and a body") from None
    if type(status) is not int:
        raise SourceRefused("the status is not a number")
    if status != 200:
        raise SourceRefused(f"status {status}")
    if not isinstance(body, bytes):
        raise SourceRefused("the answer is not bytes")
    if len(body) > MAX_BODY:
        raise SourceRefused(f"the answer is over {MAX_BODY} bytes")
    kind = _media_type(headers)
    if kind is not None and kind != "application/json":
        raise SourceRefused("the answer is not JSON")
    try:
        data = json.loads(body.decode("utf-8"), object_pairs_hook=_no_repeat, parse_constant=_no_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise SourceRefused("the answer is not JSON of the expected kind") from None
    if not isinstance(data, dict):
        raise SourceRefused("the answer is not a JSON object")
    if type(data.get("code")) is not int or data["code"] != 200:
        raise SourceRefused("the answer does not say that the search succeeded")
    pages = data.get("data")
    pages = pages.get("webPages") if isinstance(pages, dict) else None
    results = pages.get("value") if isinstance(pages, dict) else None
    if not isinstance(results, list):
        raise SourceRefused("the answer has no list of results")
    if len(results) > MAX_RESULTS:
        raise SourceRefused(f"the answer has more than {MAX_RESULTS} results")
    for entry in results:
        if not isinstance(entry, dict) or not isinstance(entry.get("url"), str):
            raise SourceRefused("a result has no address")
    return results


def search(query, post, limit):
    """Candidate pages for a search of the web: the first `limit` (1 to 30) addresses that the answer lists, in its order, each once. Returns `{"candidates": [...], "rejected": []}`, each candidate a
    row for `crawlqueue.enqueue` with `source` `web-search`. A refusal of the source is a `SourceRefused`; a wrong argument is a `KbError` and costs no request."""
    text = _text(query)
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise _refuse(f"limit must be a whole number from 1 to {MAX_LIMIT}")
    if not callable(post):
        raise _refuse("post is a function of the request")
    words = _WORDS.findall(text)[:MAX_WORDS]
    if not words:
        raise _refuse("a query needs at least one letter or digit")
    try:
        reply = post({"query": " ".join(words), "count": limit})
    except srcopenalex.SourceRefused as refused:  # one that the caller's function raises, with its fixed reason, named for this source
        raise SourceRefused(refused.reason, refused.partial) from None
    except KbError:
        raise SourceRefused("the request was refused or failed") from None
    candidates, seen = [], set()
    for entry in _answer(reply):
        address = srcopenalex._web(entry["url"])
        if address is None or address in seen or _own(urlsplit(address).hostname):
            continue
        seen.add(address)
        candidates.append({"address": address, "source": SOURCE, "found_from": text, "depth": 0})
        if len(candidates) == limit:
            break
    return {"candidates": candidates, "rejected": []}
