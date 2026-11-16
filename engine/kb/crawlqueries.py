"""The search queries of the unattended crawl, made from a topic (`docs/specs/population.md`, "Discovery").

The model sees one fixed text that holds the topic and a number and nothing else: the text of a fetched page is never used to make a
query. What it answers is untrusted: it is read by a strict reader that keeps a line only if it is a short plain query, and anything
it cannot read gives the plain queries made from the topic alone. The model is a function given by the caller (`chat(prompt) -> text`),
so that the work of the optional task `crawl-query` is not tied to a server here."""

import re
import unicodedata
from collections.abc import MutableMapping

from . import KbError, textutil

PROMPT_VERSION = "crawl-query-1"  # changes with the text below, so that the cache of a topic is asked again
MAX_QUERIES = 10
MAX_REPLY = 4096
_PROMPT = (
    "You help a librarian search the web for books, papers and reference articles.\n"
    "Topic: {topic}\n"
    "Write {n} short web search queries of 3 to 12 words each that would find substantial books, papers or reference articles on this "
    "topic, each from a different angle.\n"
    "Answer with one query on each line, with no numbering, no quotation marks, no comment and no other text.\n")
_MARKS = " -+/&.,:'()"
_QUOTES = "\"'\u201c\u201d\u2018\u2019\u00ab\u00bb"
_NUMBERING = re.compile(r"(?:[0-9]{1,2}[.)]|[-*\u2022\u2013])\s+")
_VERSION = re.compile(r"[a-z0-9][a-z0-9.-]{0,39}")
_FALLBACK_VARIANTS = (" survey", " introduction")


def _refuse(message):
    return KbError(f"the crawl queries: {message}")


def _topic(topic):
    if not isinstance(topic, str) or not 1 <= len(topic) <= 300 or textutil.clean(topic, len(topic)) != topic:
        raise _refuse("a topic is a clean text of 1 to 300 characters")  # as the topics file reader takes it: `AI` and `Go` are topics
    return topic


def _number(n):
    if type(n) is not int or not 1 <= n <= MAX_QUERIES:
        raise _refuse(f"the number of queries is a whole number from 1 to {MAX_QUERIES}")
    return n


def build_prompt(topic, n):
    """The one text the model is given for a topic: fixed words, the topic and the number."""
    return _PROMPT.format(topic=_topic(topic), n=_number(n))


def _plain(query):
    """Whether `query` is, exactly as it stands, a query this module would keep."""
    if not isinstance(query, str) or not 3 <= len(query) <= 120 or textutil.clean(query, len(query)) != query:
        return False
    if len(query.split()) > 12 or query.endswith(":") or re.search(r"://|\bwww\.", query, re.I):
        return False
    for word in query.split():  # a search source reads `-word`, `+word` and `field:word` as syntax: a query is free text
        if (len(word) > 1 and word[0] in "-+") or ":" in word[:-1]:
            return False
    return all(c.isalnum() or c in _MARKS for c in query)


def _key(query):
    return " ".join(query.split()).casefold()


def _read(reply, n):
    """The queries in a model's reply, at most `n`, or None when there is none: one to a line, numbering and quotation marks taken
    off, hidden characters removed. A line is dropped, not repaired, if it is not a plain query."""
    if not isinstance(reply, str) or len(reply) > MAX_REPLY:
        return None
    made, seen = [], set()
    for line in re.split(r"\r\n|\r|\n", reply):
        line = line.strip()
        if any(unicodedata.category(c) == "Cc" and c != "\t" for c in line):
            continue
        numbering = _NUMBERING.match(line)  # at the start of the line only
        line = line[numbering.end():].strip() if numbering else line
        if len(line) >= 2 and line[0] in _QUOTES and line[-1] in _QUOTES:
            line = line[1:-1].strip()
        line = textutil.clean(line, MAX_REPLY)
        if _plain(line) and _key(line) not in seen:
            seen.add(_key(line))
            made.append(line)
            if len(made) == n:
                break
    return made or None


def _cut(text, limit):
    """`text` of at most `limit` characters, cut at a word when it has a space to cut at."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    if text[limit] != " " and " " in head:
        head = head[: head.rindex(" ")]
    return head.rstrip()


def _fallback(topic, n):
    """The queries made without a model: the topic and one or two plain variants of it, each a query of at most 120 characters. The
    topic is the owner's own text and goes out as written (a `C#` stays `C#`), not through the reader that a model's line must pass; a
    source must put every query in its address as free text."""
    base = _cut(topic, 120)
    return ([base] + [_cut(base, 120 - len(v)) + v for v in _FALLBACK_VARIANTS])[:n]


def _cached(value, n):
    if not isinstance(value, list) or not 1 <= len(value) <= n or not all(_plain(q) for q in value):
        return None
    return value if len({_key(q) for q in value}) == len(value) else None


def make_queries(topic, n, chat, cache, prompt_version):
    """At most `n` search queries for a topic. `cache` is a dictionary (the caller keeps it between runs): the same topic, number and
    prompt version are served from it, read again before they are trusted, and the model is not asked again. `chat` is a function
    from the prompt to the model's reply, or None: with none, or when the model is down (a `KbError`), or when its reply holds no
    readable line, the answer is the plain queries made from the topic, which are not put in the cache. Any other error of the call
    is not hidden."""
    _topic(topic)
    _number(n)
    if not isinstance(prompt_version, str) or not _VERSION.fullmatch(prompt_version):
        raise _refuse("the prompt version is a short name of lower-case letters, digits, dots and hyphens")
    if not isinstance(cache, MutableMapping):
        raise _refuse("the cache is a dictionary that can be written")
    if chat is not None and not callable(chat):
        raise _refuse("the model is a function of the prompt, or None")
    key = f"{prompt_version}|{n}|{topic}"
    hit = _cached(cache.get(key), n)
    if hit:
        return list(hit)
    if chat is None:
        return _fallback(topic, n)
    try:
        reply = chat(build_prompt(topic, n))
    except KbError:
        return _fallback(topic, n)
    made = _read(reply, n)
    if made is None:
        return _fallback(topic, n)
    cache[key] = made
    return list(made)
