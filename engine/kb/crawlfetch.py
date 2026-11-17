"""The policy of a fetch of the unattended crawl (`docs/specs/population.md`, "Pacing, the type gate and the shared client"; the plan `2026-11-16-run-the-steps-of-the-unattended-crawl`, Increment F).

`build(plan, matcher, suffixes, index_root, ...)` makes the **one** `webclient.Policy` under which every candidate is fetched, and the limits that go with it (`FetchPolicy`). `classify(error)` says what a failed
fetch was, in a fixed text that holds nothing the server said. The capture of a page (`capture_url.capture`, with `policy=`, `types=` and `auto_filed=True`) is made by a later step with the value `build` gives.

Which of the spec's rules the policy has already, and which this module gives it:

- Already in the shared client (`webclient`, built and tested in the plan before this one), and only used here: the public-address check at connect (a private, loopback, link-local or metadata address is refused
  at the first hop and at every redirect hop, and the address that was checked is the one dialled), ports 80 and 443 only, no credential in an address, no encoded response, a bound on size and time, a response with
  no `Content-Type` or one that disagrees with a sniff of its first bytes refused, one request at a time to a registrable domain and to an address, and an irregular gap.
- Given here: the plan's user agent (`browser`: a common browser's string, or `generic`: the client's honest one), the plan's `min_gap_s` and `jitter`, the plan's `fetch_timeout_s` as the whole time of one
  hop, the page types only (`text/html`, `application/xhtml+xml`), at most 5 redirects, the stored Public Suffix List (a run says loudly when it has none), and the **address hook** of the `lists` step
  (`crawllists.address_hook`) at every hop: the stop file first, then the matcher (the owner's blacklist, the public lists, the URL lists, the pinned hosts and the allow file, under the separate rules of
  `weblists`). No change to `webclient.py` was needed: the stop file between the hops of one fetch is the hook.
- Said in `classify`: a block by the policy (`blocked`), the stop file (`stopped`), a refusal by a site (HTTP 401, 403, 429 or 451: `refused`, which a caller counts for the circuit breaker and does not count
  as a failure), a candidate to reject for what it is (a PDF: `pdf not safe to convert`, a page over the size limit, a body that is not a web page: `rejected`, never tried again) and a failure (`failed`).
  An abuse signal in a body, and the `Retry-After` and rate-limit headers, are not read here: only the status says (a recorded narrowing of the plan's "an abuse signal"). The tests of the text are of the start
  of the client's fixed messages, never of a part a server can fill (a content type, an encoding), so that a server cannot choose its own class.

This module makes no request of its own, reads no file and no environment variable."""
import math
from collections import namedtuple

from . import KbError, capture_url, crawllists, webclient

# a common browser's string; the plan's `user_agent = browser` sends it. It names no project, tool or contact (the owner chose a browser's, as `shelf.md` agreed).
BROWSER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15"
PAGE_MAX_BYTES = capture_url.MAX_BYTES               # the plan has no key for the size of a page; this is the capture's own limit
SITE_REFUSALS = (401, 403, 429, 451)
PDF_REASON = "pdf not safe to convert"

Outcome = namedtuple("Outcome", "kind reason retry")


class FetchPolicy:
    """What a fetch is made under: `policy` (a `webclient.Policy`), `max_bytes`, `timeout` (one network operation) and `total_timeout` (one hop). Plain attributes."""

    def __init__(self, policy, max_bytes, timeout, total_timeout):
        self.policy, self.max_bytes, self.timeout, self.total_timeout = policy, max_bytes, timeout, total_timeout


def _refuse(message):
    return KbError(f"the policy of a fetch: {message}")


def _number(plan, key):
    value = plan.get(key)
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise _refuse(f"{key} is a number of seconds, not below zero")
    return value


def build(plan, matcher, suffixes, index_root, *, pacer=None, log=None, warn=None, now=None):
    """The `FetchPolicy` for the approved `plan` (a dictionary of the crawl plan's keys), the `matcher` and the Public Suffix List (a set of rules; none is said loudly: `warn(text)` is called and `log` gets a
    `list_update` line `failed`, and the policy then finds a registrable domain by the last two labels). `pacer` replaces the shared one (tests)."""
    if matcher is None:
        raise _refuse("it needs the matcher of the lists step")
    agent = {"browser": BROWSER_AGENT, "generic": webclient.GENERIC_USER_AGENT}.get(plan.get("user_agent")) if isinstance(plan.get("user_agent"), str) else None
    if agent is None:
        raise _refuse("user_agent is browser or generic")
    gap, jitter = _number(plan, "min_gap_s"), _number(plan, "jitter")
    total = plan.get("fetch_timeout_s")
    if type(total) is not int or total < 1:
        raise _refuse("fetch_timeout_s is a whole number of seconds, at least 1")
    if not suffixes:
        text = "the Public Suffix List is not in use: the registrable domain of a site is taken as its last two labels, so the pacing and the per-domain limits are less exact"
        if warn is not None:
            warn(text)
        if log is not None:
            log.write("list_update", "failed", reason=log.safe(text), now=now)
        suffixes = None
    policy = webclient.Policy(user_agent=agent, gap=gap, jitter=jitter, max_redirects=capture_url.MAX_REDIRECTS, follow_redirects=True, types=capture_url.PAGE_TYPES,
                              check=crawllists.address_hook(index_root, matcher), allow_private=False, suffixes=suffixes, pacer=pacer)
    return FetchPolicy(policy, PAGE_MAX_BYTES, min(capture_url.TIMEOUT, total), total)


def _blocked(text):
    if "the stop file" in text:
        return Outcome("stopped", "the stop file is present", True)
    if "owner" in text:
        return Outcome("blocked", "blocked by the owner's blacklist", False)
    if "list:" in text:
        return Outcome("blocked", "blocked by a public list", False)
    if "unusable" in text:
        return Outcome("blocked", "the address is not usable", False)
    return Outcome("blocked", "the address is not allowed", False)


def classify(error):
    """What a failed fetch was: `Outcome(kind, reason, retry)`. `kind` is `blocked`, `stopped`, `refused`, `rejected` or `failed`; `reason` is a fixed text; `retry` says whether the same candidate may be tried
    again (a failure and a stop, yes; the others, no). An error that is not a fetch error is raised again."""
    if not isinstance(error, capture_url.FetchError):
        raise error
    text = str(error)
    if isinstance(error, webclient.Refused):
        # every test below is of the start of one of the client's own fixed messages, or the whole of it: a text a server can put into a message (a content type, an encoding) is never searched
        if text.startswith("refused: "):
            return _blocked(text)
        if text == "not an expected type: its content type is application/pdf":
            return Outcome("rejected", PDF_REASON, False)
        if text.startswith("not an expected type: ") or text == "the response has no Content-Type" or text.startswith("the response says it is "):
            return Outcome("rejected", "not a web page", False)
        if text.startswith("too many redirects") or text == "a redirect with no usable Location was refused":
            return Outcome("failed", "a redirect was refused", True)
        if text == "the address check failed, so the request was not made":
            return Outcome("failed", "the address check failed", True)
        return Outcome("blocked", "the address is not allowed", False)
    if text.startswith("HTTP "):
        digits = text[5:]
        if digits.isdigit() and len(digits) == 3:
            status = int(digits)
            if status in SITE_REFUSALS:
                return Outcome("refused", f"the site refused (HTTP {status})", False)
            return Outcome("failed", f"HTTP {status}", True)
    if text.startswith("the response is larger than "):
        return Outcome("rejected", "over the size limit", False)
    return Outcome("failed", "timed out" if text.startswith("timed out") else "the fetch failed", True)
