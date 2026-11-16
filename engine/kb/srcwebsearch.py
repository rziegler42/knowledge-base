"""A web search engine as a source of candidates for the unattended crawl (`docs/specs/population.md`, "Discovery"): DuckDuckGo's HTML
search, best effort. Built last, and **off unless the owner's plan switches it on**.

`search` turns a query into the pages that the first page of results links to, through a `get(url, headers=None, timeout=None) ->
(status, headers, body)` function that the caller gives. What the documentation says (read on 2026-11-16: `duckduckgo.com/terms`, its
Acceptable Use Policy and the `robots.txt` of `duckduckgo.com` and `html.duckduckgo.com`; the pages and their hashes are in the plan's
Result), and what this module does about it:

- There is **no search API** that gives results (there is no key to ask for), and the markup of the page is not documented: what is read
  of it is only the title link of each result (`<a class="result__a" href=...>`), nothing else of the page.
- The terms say nothing for or against automated queries; they bind the user to the Acceptable Use Policy, which forbids interfering with
  or disrupting the service, reselling it and displaying parts of it in another service, and says the list is "not exhaustive". The
  `robots.txt` of `duckduckgo.com` says `Disallow: /html` for every agent and that of `html.duckduckgo.com` (the host asked here) says
  `Allow: /`: the two disagree. **These terms are unresolved and are the owner's to weigh** (the spec says so); this module only asks as
  rarely as the plan says (`web_search_per_day`, `gap_web_search_s`) and does nothing to get past a block.
- **A refusal is never worked round.** A status other than 200 (the page that asks for a challenge comes with 202), a page that carries
  the challenge's markup, a page that is not a page of results (the markup changed, or the page is drawn by a script), a content type that
  is not HTML, a page over a size, and a page that is not plain UTF-8 are each a `SourceRefused`, which turns the source off for the day.
  Nothing is retried, no cookie and no referrer is sent, and the agent is the honest generic one of `srcopenalex`.
- Only plain words go into the search: the query is cut into its letters and digits, so that a bang (`!g`), an operator (`site:`,
  `filetype:`, `-word`) or a quotation cannot reach the engine, which would send the search elsewhere or change it.
- A link is taken only if its target is a plain public web address of at most 2,048 characters (`srcopenalex`'s check, which turns away a
  private address written as a number and `localhost`) and is not an address of the engine itself. A link inside an advertisement (a
  container with the class `result--ad`, which the page's own `y.js` links also point to) is not taken whatever it links to, and neither is
  a link inside a `noscript` or a `template`. The engine's redirect (`duckduckgo.com/l/?uddg=<address>`, or the same with no host) is read,
  once, and any other link is taken as it stands.
  Where a name leads is for the client that fetches the page to check, as for every source."""

import re
from collections.abc import Mapping
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, urlsplit

from . import KbError, srcopenalex, textutil

API = "https://html.duckduckgo.com/html/"
USER_AGENT = srcopenalex.USER_AGENT
TIMEOUT = 30
MAX_BODY = 1_000_000
MAX_TAGS = 50_000
MAX_WORDS = 12
MAX_LIMIT = 30
SOURCE = "web-search"  # the name `crawlqueue` gives this source
_TYPES = ("text/html", "application/xhtml+xml")
_OWN = ("duckduckgo.com", "duck.com", "duck.co")
_INERT = ("noscript", "template")  # tags whose content is not the page that is shown (a script, a style, a title and a text area are text already)
_WORDS = re.compile(r"[^\W_]+")


class SourceRefused(srcopenalex.SourceRefused):
    """The engine refused, answered something that is not a page of results, or could not be asked: the same refusal as every source raises
    (a caller catches `srcopenalex.SourceRefused`), named for this source."""

    def __init__(self, reason, partial=None):
        super().__init__(reason, partial)
        self.args = (f"DuckDuckGo: {self.reason}",)


def _refuse(message):
    return KbError(f"the DuckDuckGo source: {message}")


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


def _fetch(get, url):
    """The text of the page that the answer to `url` is, or a `SourceRefused`."""
    try:
        status, headers, body = get(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"}, timeout=TIMEOUT)
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
    kind = _media_type(headers)
    if kind is not None and kind not in _TYPES:
        raise SourceRefused("the answer is not HTML")
    if b"\x00" in body:
        raise SourceRefused("the answer is not plain UTF-8 text")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise SourceRefused("the answer is not valid UTF-8") from None
    if body.count(b"<") > MAX_TAGS:
        raise SourceRefused("the answer has too many tags")
    return text


class _Page(HTMLParser):
    """What is read of a page: the `href` of each title link of a result, and whether the page says there is no result or asks for a
    challenge. A script or a style is text to this parser, and a comment is not a tag, so a link in either is not seen."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs, self.results, self.empty, self.challenge = [], False, False, False
        self.divs, self.ad_at, self.inert = 0, None, 0  # how many `div` are open, the depth of the one that holds an advertisement, and how many inert tags

    def handle_starttag(self, tag, attrs):
        values = {name: value for name, value in attrs if isinstance(value, str)}
        classes = values.get("class", "").split()
        if tag in _INERT:
            self.inert += 1
        if tag == "div":
            self.divs += 1
            if self.ad_at is None and any(c.startswith("result--ad") for c in classes):
                self.ad_at = self.divs
        if tag == "a" and "result__a" in classes and not self.inert:
            self.results = True
            if values.get("href") and self.ad_at is None:  # a link inside an advertisement is a result of the page and not a candidate
                self.hrefs.append(values["href"])
        if "no-results" in classes:
            self.empty = True
        if values.get("id") == "challenge-form" or any(c.startswith("anomaly-modal") for c in classes):
            self.challenge = True

    def handle_endtag(self, tag):
        if tag in _INERT and self.inert:
            self.inert -= 1
        if tag == "div" and self.divs:
            if self.divs == self.ad_at:
                self.ad_at = None
            self.divs -= 1


def _own(host):
    host = host.lower().rstrip(".")
    return any(host == name or host.endswith("." + name) for name in _OWN)


def _target(href):
    """The address that a result's link leads to: the target of the engine's redirect, or the link itself; None if it is not a plain public
    web address, or is an address of the engine."""
    try:
        parts = urlsplit(href)
    except ValueError:
        return None
    if (parts.hostname and _own(parts.hostname)) or (not parts.scheme and not parts.netloc):  # the engine's own link, with its host or without one
        if parts.path != "/l/":
            return None
        values = parse_qs(parts.query).get("uddg")
        href = values[0] if values else None
    address = srcopenalex._web(href)
    if address is None or _own(urlsplit(address).hostname):
        return None
    return address


def search(query, get, limit):
    """Candidate pages for a search of the web, the first `limit` (1 to 30) that the first page of results links to, in the order of the
    page. Returns `{"candidates": [...], "rejected": []}`, each candidate a row for `crawlqueue.enqueue` with `source` `web-search`. A
    refusal of the source is a `SourceRefused`; a wrong argument is a `KbError` and costs no request."""
    text = _text(query)
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise _refuse(f"limit must be a whole number from 1 to {MAX_LIMIT}")
    if not callable(get):
        raise _refuse("get is a function of the address")
    words = _WORDS.findall(text)[:MAX_WORDS]
    if not words:
        raise _refuse("a query needs at least one letter or digit")
    page = _Page()
    html = _fetch(get, f"{API}?q={quote(' '.join(words), safe='')}")
    try:
        page.feed(html)
        page.close()
    except (AssertionError, ValueError, RecursionError):
        raise SourceRefused("the page cannot be read") from None
    if page.challenge:
        raise SourceRefused("the page asks for a challenge")
    if not page.results and not page.empty:
        raise SourceRefused("the page is not a page of results")
    candidates, seen = [], set()
    for href in page.hrefs:
        address = _target(href)
        if address is not None and address not in seen:
            seen.add(address)
            candidates.append({"address": address, "source": SOURCE, "found_from": text, "depth": 0})
            if len(candidates) == limit:
                break
    return {"candidates": candidates, "rejected": []}
