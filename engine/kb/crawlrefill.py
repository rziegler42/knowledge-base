"""The `refill` point of a crawl run (`docs/specs/population.md`, "Discovery" and "Bounds against flooding"; the plan `2026-11-16-run-the-steps-of-the-unattended-crawl`, Increment E).

`make_step(fetch=None, sources=None, call=None)` gives the function that a run attaches at its `refill` point (`step` is the one with the shared web client, the real sources and the engine's model call). It asks
**discovery** (`discover.fill`) to refill the candidate queue, which does nothing unless fewer than the plan's `queue_low` rows are queued, and otherwise adds at most `discover_target` rows within `queued_total`
and `queued_per_domain`. What the runner gives `fill`:

- `get`: the shared web client (`webclient.get`) under **one policy**: the honest generic user agent, no credential, redirects followed (each hop passes the hook), the types the sources answer in, the Public Suffix List
  the lists step left, and an address hook that looks at the stop file before each request and refuses an address the matcher blocks. Pacing between requests is discovery's own (each source has its gap), so the
  policy adds none; one request at a time to a site and to an address is the client's.
- `is_blocked`: the matcher the lists step left, as a reason (`owner` or `list:<name>`) or nothing; `canon_address` and `site_of` (with the Public Suffix List): `webaddr`'s.
- `chat`: the owner's `crawl-query` model, **only through the entry the config names for that task** and only if it names one (left unset, the queries are the topics' own); the stop file is looked at before each call;
  a model that fails gives the plain queries, never a failure of the run. The model sees the topic and nothing a page said (`crawlqueries`).
- `cache`: the model's answers, kept between runs in `<index root>/crawl/query-cache.json` (mode 600; a file that is a link, loose, too large or not in its form is not believed and is replaced).
- `log`: discovery's notes, said by **host and counts**: a candidate is named by its host, never its address, and no query or page text is in a line; the lines of each noisy kind (skipped, blocked, rejected) are
  capped, and the closing line of a refill that ends normally says how many were left out, so that a page with a hundred thousand links cannot flood the log.

A topics file that cannot be read, or no matcher (the lists step did not run), makes the step raise `crawlrun.StepRefused`; a refill that fails is logged and the run goes on, since the candidates already queued
can still be fetched. This module changes no candidate row itself (discovery inserts rows through `crawlqueue`), makes no request of its own and reads no environment variable of its own."""
import datetime
import json
import os
import stat
from collections.abc import MutableMapping
from urllib.parse import urlsplit

from . import KbError, crawlfetch, crawlguard, crawllists, crawllog, crawlplan, crawlrun, crawltopics, discover, models, webaddr, webclient

CACHE_FILE = "query-cache.json"
MAX_CACHE_BYTES = 1024 * 1024
MAX_LINES_PER_KIND = 25
CAPPED = ("skipped", "blocked", "rejected")
SET_BY_POLICY = ("user-agent", "accept")
DISCOVERY_TYPES = ("application/json", "application/atom+xml", "application/xml", "text/xml", "text/html")
ACCEPT = "application/json, application/atom+xml, application/xml;q=0.9, text/xml;q=0.9, text/html;q=0.5"


class _Stopped(Exception):
    """The stop file was seen: the refill ends at once and no source is marked off for the day (a `KbError` would be taken for a refusal by the source)."""


class QueryCache(MutableMapping):
    """The model's answers (`{key: [query, ...]}`) in a file of mode 600 that is read strictly and written whole or not at all. A file that cannot be believed is ignored and replaced by the next `save`."""

    def __init__(self, path):
        self._path, self._data, self._dirty = path, {}, False
        self._load()

    def _load(self):
        try:
            info = os.lstat(self._path)
        except FileNotFoundError:
            return
        except OSError:
            self._dirty = True
            return
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > MAX_CACHE_BYTES:
            self._dirty = True                      # not believed, and replaced on the next save
            return
        try:
            fd = os.open(self._path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                raw = os.read(fd, MAX_CACHE_BYTES + 1)
            finally:
                os.close(fd)
            data = json.loads(raw.decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError, RecursionError):
            self._dirty = True
            return
        if not isinstance(data, dict):
            self._dirty = True
            return
        self._data = {k: v for k, v in data.items() if isinstance(v, list) and all(isinstance(q, str) for q in v)}

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value
        self._dirty = True

    def __delitem__(self, key):
        del self._data[key]
        self._dirty = True

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def save(self):
        """Write the cache if it changed or the file on disk was not believed: a new file at mode 600, synced, renamed over the name (a link there is replaced, not followed)."""
        if not self._dirty:
            return
        data = json.dumps(self._data, sort_keys=True).encode("utf-8")
        if len(data) > MAX_CACHE_BYTES:                       # too large to keep: the oldest are not known, so none is kept
            data = b"{}"
        folder = os.path.dirname(self._path)
        tmp = os.path.join(folder, f".{CACHE_FILE}-{os.urandom(6).hex()}")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            try:
                view = memoryview(data)
                while view:
                    view = view[os.write(fd, view):]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp, self._path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


class _Notes:
    """Discovery's notes as log lines: a candidate by its host, the source and the reason as text, the lines of the noisy kinds capped."""

    def __init__(self, log, now):
        self.log, self.now, self.counts, self.left_out = log, now, {}, 0

    def __call__(self, step, outcome, **fields):
        outcome = outcome if outcome in crawllog.OUTCOMES else "failed"
        kind = (step, outcome)
        self.counts[kind] = self.counts.get(kind, 0) + 1
        if outcome in CAPPED and self.counts[kind] > MAX_LINES_PER_KIND:
            self.left_out += 1
            return
        address = fields.get("candidate")
        host = None
        if isinstance(address, str):
            try:
                host = urlsplit(address).hostname
            except ValueError:
                host = None
        parts = [str(p) for p in (fields.get("source"), fields.get("reason")) if p]
        n = fields.get("n")
        self.log.write(step, outcome, host=self.log.safe(host, "host") if host else None, reason=self.log.safe(": ".join(parts) or None),
                       n=n if isinstance(n, int) and not isinstance(n, bool) and n >= 0 else None, now=self.now)


def _stamp(now):
    return now.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(ctx, fetch, sources, call, rss_reader=None):
    plan, log, now = ctx.plan, ctx.log, ctx.clock()
    if ctx.matcher is None:
        raise crawlrun.StepRefused("the refill needs the matcher of the lists step, which did not run")
    try:
        topics = crawltopics.read_topics(plan["topics"])
    except KbError as e:
        raise crawlrun.StepRefused(f"the topics file cannot be used: {e}") from None
    suffixes = ctx.suffixes or None
    policy = webclient.Policy(user_agent=webclient.GENERIC_USER_AGENT, gap=0, jitter=0, follow_redirects=True, types=DISCOVERY_TYPES, check=crawllists.address_hook(ctx.index_root, ctx.matcher),
                              suffixes=suffixes, accept=ACCEPT)

    def get(url, headers=None, timeout=None):
        """The sources' `get`. The sources send their own `User-Agent` and `Accept`, which the client refuses from a caller (the policy sets both); every other header goes on. A request the client
        refuses or cannot make is a `KbError` with a fixed text, which a source takes as its own refusal and discovery as the source being off for the day."""
        if crawlguard.stop_requested(ctx.index_root):
            raise _Stopped()
        kept = {name: value for name, value in (headers or {}).items() if not (isinstance(name, str) and name.lower() in SET_BY_POLICY)}
        try:
            return fetch(url, policy=policy, headers=kept or None, **({} if timeout is None else {"timeout": timeout}))
        except webclient.FetchError:
            raise KbError("the request was refused or failed") from None

    def is_blocked(address):
        """A reason discovery can record (`owner`, `list:<name>`), or nothing. An address the matcher cannot read (`unusable`) is not a block: the queue drops it by its own checks (too long, not an address),
        and a reason it cannot record would end the whole refill, which a source could use to keep the queue empty."""
        block = ctx.matcher.blocked(address)
        reason = block.reason if block else None
        return reason if reason == "owner" or (isinstance(reason, str) and reason.startswith("list:")) else None

    entry = ctx.cfg.get("tasks", {}).get("crawl-query") if isinstance(ctx.cfg, dict) and isinstance(ctx.cfg.get("tasks"), dict) else None

    def chat(prompt):
        if crawlguard.stop_requested(ctx.index_root):
            raise _Stopped()
        reply = call(ctx.cfg, entry, prompt)
        text = reply.get("reply") if isinstance(reply, dict) else None
        if not isinstance(text, str):
            raise KbError("the model's reply is not text")
        return text

    cache = QueryCache(os.path.join(ctx.index_root, "crawl", CACHE_FILE))
    notes = _Notes(log, now)
    try:
        result = discover.fill(ctx.conn, crawlplan.discovery_plan(plan), topics, now=_stamp(now), get=get, chat=chat if isinstance(entry, str) and entry else None, sources=sources, log=notes,
                               cache=cache, is_blocked=is_blocked, canon_address=webaddr.canon_address, site_of=lambda host: webaddr.site_of(host, suffixes),
                               pdfs=crawlfetch.pdf_limit(ctx, rss_reader) is not None)
    except _Stopped:
        result = {"status": "stopped", "added": 0}
        log.write("discover", "skipped", reason="the stop file is present", now=now)
    except KbError:
        result = {"status": "failed", "added": 0}
        log.write("discover", "failed", reason="the refill of the queue failed", now=now)
    finally:
        try:
            cache.save()
        except OSError:
            pass                                                 # the cache saves model calls and nothing else
    ctx.refill_report = result
    if result.get("status") not in ("failed", "stopped"):
        said = f"added {result['added']}, skipped {result['skipped']}, rejected {result['rejected']}, blocked {result['blocked']}"
        said += "; the total cap was reached" if result.get("capped") else ""
        said += f"; {notes.left_out} lines left out" if notes.left_out else ""
        log.write("discover", "ok", reason=said, n=result["added"], now=now)


def make_step(fetch=None, sources=None, call=None, rss_reader=None):
    """The step for the `refill` point. `fetch` is `webclient.get` or a stand-in with its signature, `sources` replaces the source modules (tests), `call` is `models.call` or a stand-in, `rss_reader` reads the
    memory of a process group (`crawlfetch.pdf_limit`: with PDFs on and the memory readable, a work whose only text is a PDF is queued, and otherwise rejected for its type)."""
    def step(ctx):
        _run(ctx, fetch or webclient.get, sources, call or models.call, rss_reader)
    return step


step = make_step()
