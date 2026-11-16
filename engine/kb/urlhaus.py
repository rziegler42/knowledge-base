"""URLhaus in recent mode (`docs/specs/population.md`, "Sites that are off limits"; the plan `2026-11-16-harden-the-fetch-for-the-unattended-crawl`, Increment E).

abuse.ch's URLhaus lists URLs that have been reported as distributing malware. In its **recent** mode this module reads the URLs added in the past days (`GET /v1/urls/recent/`, at most 1,000 a time) about once an
hour, keeps them for `urlhaus_keep_days`, and gives them to `weblists.Matcher` as a URL list: it blocks that exact canonical URL, and a whole host only when the entry's host is a bare IP address (an entry for
`github.com/some/file` must not block `github.com`). The lookup mode, which tells abuse.ch which hosts are about to be fetched, is not built.

**The key is a credential** and the owner's. It is read from a file only if that file is a regular file, not a link, mode 600 exactly, owned by the current user, and holds one printable line. It goes **only** in
the header `Auth-Key`, only over https, only to `urlhaus-api.abuse.ch`, in a call that follows no redirect (the shared client refuses anything else before a request, `webclient.Policy.credential_headers`). It is
never written into a report, a state file, an error text, an address, an environment variable or a command; this module prints and logs nothing. Whatever a server says is scrubbed of it before it is kept.
**Any refusal turns the source off for the rest of the (UTC) day and the key is not sent again that day**: a status other than 200, a redirect, a query status other than `ok`, or the rate-limit header
`X-RateLimit-Remaining` reaching zero. A network failure that is not a refusal is tried again after the hour.

`recent(get, key, now, lists_plan)` makes the one request. `Source(state_dir, key_path).update(get, now, lists_plan, matcher=None)` keeps the day's state, the once-an-hour rule and the kept URLs in
`urlhaus.json` (mode 600, no key), and feeds the matcher. `get` is `webclient.get` or a stand-in with its signature; **this module makes no request of its own**.

abuse.ch's own page on 2026-11-16 (the logged-out one) documents downloads with the key written **in the address**; this module does not do that, and the path of the recent call is the one the owner's copy of the
documentation gave (`/v1/urls/recent/`). Whether abuse.ch still answers it that way is first known when the owner makes the first real request, which any refusal then turns off."""
import datetime
import fcntl
import json
import os
import re
import stat
import time
from urllib.parse import quote, unquote

from . import KbError, __version__, textutil, webclient
from .weblists import ListError, _open_regular, check_plan, ensure_private_dir

HOST = "urlhaus-api.abuse.ch"
RECENT_URL = f"https://{HOST}/v1/urls/recent/"
REFRESH_HOURS = 1
MAX_REPLY_BYTES = 8 * 1024 * 1024
MAX_REPLY_URLS = 1000 * 5
MAX_KEPT = 200_000            # kept URLs: with MAX_URL_LENGTH this keeps the state file under MAX_STATE_BYTES
MAX_URL_LENGTH = 1024
MIN_KEY_LENGTH = 16
STALE_TEMP_SECONDS = 3600
LOCK_FILE = "urlhaus.lock"
FUTURE_ALLOWED = datetime.timedelta(days=1)    # a clock that is a day out is allowed for; further than that a time or a date is not believed
MAX_STATE_BYTES = 256 * 1024 * 1024
MAX_KEY_BYTES = 200
STATE_FILE = "urlhaus.json"
USER_AGENT = f"knowledge-base/{__version__} (research library; URLhaus recent URLs)"
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
_COUNT = re.compile(r"[0-9]{1,9}")


class UrlhausError(KbError):
    """A key, a reply or a setting that is refused. The message is safe to log and never holds the key."""


class NotOk(UrlhausError):
    """A reply whose `query_status` is not `ok` (or `no_results`): abuse.ch refused the request."""


def read_key(path):
    """The key in a key file, or `UrlhausError`: a regular file that is not a link, mode 600 exactly, owned by the current user, one printable line with no space, at most 200 characters. The message
    never holds any of the file's text."""
    if not isinstance(path, (str, os.PathLike)):
        raise UrlhausError("the key file path must be a path")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except (OSError, ValueError) as e:
        raise UrlhausError(f"the key file cannot be opened ({getattr(e, 'strerror', None) or 'bad path'})") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise UrlhausError("the key file is not a regular file")
        if info.st_uid != os.getuid():
            raise UrlhausError("the key file is not owned by the current user")
        if stat.S_IMODE(info.st_mode) != 0o600:
            raise UrlhausError("the key file must have mode 600")
        data = os.read(fd, MAX_KEY_BYTES + 4)
    except OSError as e:
        raise UrlhausError(f"the key file cannot be read ({e.strerror})") from None
    finally:
        os.close(fd)
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        raise UrlhausError("the key file is not plain ASCII text") from None
    if text.endswith("\r\n"):
        text = text[:-2]
    elif text.endswith("\n"):
        text = text[:-1]
    if not text:
        raise UrlhausError("the key file is empty")
    if len(text) < MIN_KEY_LENGTH:
        raise UrlhausError("the key file holds a line that is too short to be a key")
    if len(text) > MAX_KEY_BYTES:
        raise UrlhausError("the key file holds more than one short line")
    if not _plain_key(text):
        raise UrlhausError("the key file must hold one line of printable characters with no space")
    return text


def _plain_key(text):
    return isinstance(text, str) and MIN_KEY_LENGTH <= len(text) <= MAX_KEY_BYTES and all(33 <= ord(c) < 127 for c in text)


def _scrub(text, key):
    """Text with the key, in any letter case, replaced: what a server says may echo the header it was sent."""
    if not key:
        return text
    return re.sub(re.escape(key), "[credential]", text, flags=re.IGNORECASE)


def _day(now):
    return now.astimezone(datetime.timezone.utc).date().isoformat()


def _check_now(now):
    """The time as UTC, or `UrlhausError` if it has no time zone."""
    if not isinstance(now, datetime.datetime) or now.tzinfo is None:
        raise UrlhausError("the time must be a datetime with a time zone")
    return now.astimezone(datetime.timezone.utc)


def parse_recent(body, now, avoid=()):
    """`avoid` is lower-case texts (the key in the forms it could be written) that no entry may hold, raw, canonical or percent-decoded. `(entries, ignored)` from a `urls/recent` reply: `{canonical url: "YYYY-MM-DD" it was added}`, and the number of entries that were not usable addresses. `no_results` is an empty answer. Any other query
    status is `NotOk`; a reply that is not the documented shape is `UrlhausError`."""
    from . import webaddr
    if not isinstance(body, (bytes, bytearray)):
        raise UrlhausError("the reply is not bytes")
    try:
        data = json.loads(bytes(body).decode("utf-8"))
    except (ValueError, RecursionError, UnicodeDecodeError):
        raise UrlhausError("the reply is not JSON") from None
    if not isinstance(data, dict):
        raise UrlhausError("the reply is not the documented shape")
    status = data.get("query_status")
    if status == "no_results":
        return {}, 0
    if status != "ok":
        raise NotOk("abuse.ch answered with a query status other than ok")    # fixed text: what a server puts in the status is never copied
    urls = data.get("urls")
    if not isinstance(urls, list):
        raise UrlhausError("the reply has no list of URLs")
    if len(urls) > MAX_REPLY_URLS:
        raise UrlhausError("the reply has too many URLs")
    today = _day(now)
    entries, ignored = {}, 0
    for item in urls:
        if not isinstance(item, dict) or not isinstance(item.get("url"), str):
            ignored += 1
            continue
        try:
            url = webaddr.canon_address(item["url"])
        except webaddr.AddressError:
            ignored += 1
            continue
        if len(url) > MAX_URL_LENGTH or _holds(avoid, item["url"], url):
            ignored += 1
            continue
        added = item.get("date_added")
        date = added[:10] if isinstance(added, str) and _DAY.fullmatch(added[:10]) and _valid_date(added[:10]) else today
        entries[url] = min(date, today)
    return entries, ignored


def _holds(avoid, *texts):
    """Whether any of the texts, lower-cased and percent-decoded up to twice, holds any of the `avoid` texts."""
    if not avoid:
        return False
    seen = set()
    for text in texts:
        for _ in range(3):
            lowered = text.lower()
            seen.add(lowered)
            text = unquote(text)
        seen.add(text.lower())
    return any(bad in text for bad in avoid for text in seen)


def _valid_date(text):
    try:
        datetime.date.fromisoformat(text)
    except ValueError:
        return False
    return True


def recent(get, key, now, lists_plan, check=None):
    """One request for the recent URLs. Returns a dict: `status` (`ok`, `refused` or `failed`), `reason` (fixed text or cleaned, never holding the key), `entries` and `ignored` when `ok`, and
    `off_for_the_day` when the source must not be asked again today: a refusal of any kind (a status other than 200, a redirect, a reply that is not the documented answer, a query status other than `ok`) or
    the rate-limit header at zero on any reply. A transport failure is `failed`. `get` is `webclient.get` or a stand-in; `check` is the address hook of the policy."""
    check_plan(lists_plan)
    _check_now(now)
    if not _plain_key(key):
        raise UrlhausError("the key is not a plain string")
    policy = webclient.Policy(user_agent=USER_AGENT, types=("application/json",), accept="application/json", check=check, credential_headers={"Auth-Key": key}, credential_host=HOST,
                              follow_redirects=False)
    try:
        status, headers, body = get(RECENT_URL, policy=policy, max_bytes=MAX_REPLY_BYTES)
    except webclient.Refused as e:
        return {"status": "refused", "reason": textutil.clean(_scrub(str(e), key), 200), "off_for_the_day": True}
    except webclient.FetchError as e:
        return {"status": "failed", "reason": textutil.clean(_scrub(str(e), key), 200)}
    except Exception as e:   # whatever else a downloader raises is named by its type only: its text is not ours to trust
        return {"status": "failed", "reason": f"the request failed ({type(e).__name__})"}
    if not isinstance(status, int) or isinstance(status, bool):
        return {"status": "failed", "reason": "the downloader gave no status"}
    remaining = headers.get("x-ratelimit-remaining") if isinstance(headers, dict) else None
    used_up = isinstance(remaining, str) and bool(_COUNT.fullmatch(remaining.strip())) and int(remaining.strip()) == 0
    if status != 200:
        return {"status": "refused", "reason": f"HTTP {status}", "off_for_the_day": True}
    try:
        entries, ignored = parse_recent(body, now, avoid=(key.lower(), quote(key, safe="").lower()))     # a server that echoes the header must not get the key into what is kept
    except UrlhausError as e:    # a reply that is not the documented answer is a refusal, whatever the reason
        return {"status": "refused", "reason": textutil.clean(_scrub(str(e), key), 200), "off_for_the_day": True}
    report = {"status": "ok", "entries": entries, "ignored": ignored}
    if used_up:
        report["off_for_the_day"] = True
        report["reason"] = "the rate limit is used up for the day"
    return report


class Source:
    """The state of URLhaus recent mode: the kept URLs, the time of the last request and the day the source was turned off. **The rules `no key after a refusal` and `once an hour` fail closed**: a state
    that exists and cannot be read (a damaged, link, pipe, folder, huge, foreign or loose-mode file) means no request for the rest of that day; a folder that cannot hold the state means no request; the time
    of a request is written **before** it is made, so a stop during it is remembered; a refusal whose state cannot be written still stops the day in this process. One writer at a time is enforced by an
    advisory lock on a file in the state folder (a second one gets `busy`)."""

    def __init__(self, state_dir, key_path):
        self._dir, self._key_path = state_dir, key_path
        self.problems = []
        self._mem_off, self._mem_last = None, None      # what this process knows if the state cannot be written
        self._load()

    # --- state ---

    def _state_path(self):
        return os.path.join(self._dir, STATE_FILE)

    def _load(self):
        """Read the state. A state that exists and cannot be trusted (not a plain file, over the size limit, not JSON, a time or a version that is not a time or a version, a file that is not ours or has group or
        other mode bits) sets `_unreadable`; the entries that could be read are kept, and a file that could not be read at all is moved aside by the first step."""
        self._entries, self._last, self._off_day, self._unreadable, self._aside = {}, None, None, False, False
        path = self._state_path()
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            return self._damaged(f"the URLhaus state cannot be examined ({getattr(e, 'strerror', None) or type(e).__name__})")
        if not stat.S_ISREG(info.st_mode):
            return self._damaged("the URLhaus state is not a plain file", aside=True)
        try:
            raw = _open_regular(path, MAX_STATE_BYTES, "the URLhaus state")
        except ListError as e:
            return self._damaged(str(e), aside=True)
        if raw is None:
            return
        try:
            data = json.loads(raw.decode("utf-8"))
            entries = data["entries"]
            if not isinstance(data, dict) or not isinstance(entries, dict):
                raise ValueError
        except (ValueError, KeyError, TypeError, RecursionError, UnicodeDecodeError):
            return self._damaged("the URLhaus state cannot be read", aside=True)
        from . import webaddr
        kept = {}
        for url, date in entries.items():
            if isinstance(url, str) and isinstance(date, str) and _DAY.fullmatch(date) and _valid_date(date) and len(url) <= MAX_URL_LENGTH:
                try:
                    if webaddr.canon_address(url) == url:
                        kept[url] = date
                except webaddr.AddressError:
                    continue
        self._entries = kept
        version = data.get("version", 1)
        last, off = data.get("last"), data.get("off_day")
        if type(version) is not int or version != 1:
            self._damaged("the URLhaus state is of a version this code does not read")
        if last is not None:
            try:
                if not isinstance(last, str):
                    raise ValueError
                self._last = datetime.datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
            except ValueError:
                self._damaged("the URLhaus state holds a time that is not a time")
        if off is not None:
            if isinstance(off, str) and _DAY.fullmatch(off) and _valid_date(off):
                self._off_day = off
            else:
                self._damaged("the URLhaus state holds a day that is not a day")
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            self._damaged("the URLhaus state is not a file of ours with a private mode")

    def _damaged(self, why, aside=False):
        self._unreadable = True
        self._aside = self._aside or aside
        self.problems.append(f"{why}, so no request is made today")

    def _move_aside(self):
        """Keep a state that could not be read as `urlhaus.json.bad` (one copy, the last), so that writing a new state does not destroy it."""
        try:
            os.replace(self._state_path(), self._state_path() + ".bad")
        except OSError:
            pass

    def _save(self):
        ensure_private_dir(self._dir)
        last = self._last or self._mem_last
        state = {"version": 1, "entries": self._entries, "last": last.strftime("%Y-%m-%dT%H:%M:%SZ") if last else None, "off_day": self._off_day}
        tmp = os.path.join(self._dir, f".{STATE_FILE}.{os.urandom(6).hex()}.new")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            try:
                view = memoryview(json.dumps(state, sort_keys=True).encode("utf-8"))
                while view:
                    view = view[os.write(fd, view):]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp, self._state_path())
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        self._sweep_temps()

    def _sweep_temps(self):
        """Remove this file's temporary files that are old enough to belong to a writer that is gone."""
        pattern = re.compile(rf"\.{re.escape(STATE_FILE)}\.[0-9a-f]{{12}}\.new")
        try:
            names = os.listdir(self._dir)
        except OSError:
            return
        for name in names:
            if pattern.fullmatch(name):
                path = os.path.join(self._dir, name)
                try:
                    if time.time() - os.lstat(path).st_mtime > STALE_TEMP_SECONDS:
                        os.unlink(path)
                except OSError:
                    pass

    def _drop_old(self, now, keep_days):
        today = now.astimezone(datetime.timezone.utc).date()
        self._entries = {url: date for url, date in self._entries.items() if _fresh(today, date, keep_days)}

    def load_into(self, matcher, now=None, lists_plan=None):
        """Give the kept URLs to a `Matcher`; returns how many. With `now` and `lists_plan` the plan's switch and `urlhaus_keep_days` apply: a source that is off gives nothing, and an entry that is as old as
        the keep days or older, or dated more than a day ahead, is not given (the saved state is not changed)."""
        entries = self._entries
        if now is not None and lists_plan is not None:
            cfg = check_plan(lists_plan)
            today = _check_now(now).date()
            if not cfg["urlhaus_recent"]:
                return 0
            entries = {url: date for url, date in entries.items() if _fresh(today, date, cfg["urlhaus_keep_days"])}
        return matcher.set_urls("urlhaus_recent", list(entries))

    # --- one step ---

    def _lock(self):
        """The advisory lock of the state folder, or None if another writer holds it."""
        fd = os.open(os.path.join(self._dir, LOCK_FILE), os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError(0, "the lock file is not a plain file")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return None
        except OSError:
            os.close(fd)
            raise
        return fd

    def update(self, get, now, lists_plan, matcher=None, check=None):
        """Ask for the recent URLs if the plan turns the source on, it is not off for the day and an hour has passed; keep them; give the matcher what is kept (and not too old) after every outcome except `off`,
        which feeds nothing (also when another writer is `busy` or the folder cannot be used). Returns a dict whose `status` is `off`, `off-for-the-day`, `not-due`, `ok`, `refused`, `failed` or `busy`. The key
        is read only when a request is to be made. **A request that was made, whatever came of it, is not made again within the hour**, and its day is written down as off before it is made and cleared only by a
        clean answer, so that a stop in the middle of it, or a state that cannot be written afterwards, still means no second key that day."""
        cfg = check_plan(lists_plan)
        now = _check_now(now)
        if not cfg["urlhaus_recent"]:
            return {"status": "off"}
        out = self._guarded(get, now, lists_plan, cfg, check)
        if matcher is not None:
            self.load_into(matcher, now, lists_plan)
        return out

    def _guarded(self, get, now, lists_plan, cfg, check):
        try:
            ensure_private_dir(self._dir)
            lock = self._lock()
        except (ListError, OSError, ValueError, TypeError) as e:
            return {"status": "failed", "reason": f"the state folder cannot be used, so no request is made ({getattr(e, 'strerror', None) or type(e).__name__})"}
        if lock is None:
            return {"status": "busy"}
        try:
            self._load()
            return self._step(get, now, lists_plan, cfg, check)
        finally:
            os.close(lock)

    def _step(self, get, now, lists_plan, cfg, check):
        today = _day(now)
        if self._unreadable:                 # fail closed: a state that cannot be trusted is a day without the key
            self._off_day = today
            self._unreadable = False
            if self._aside:
                self._move_aside()
            self._try_save()
            return {"status": "off-for-the-day"}
        self._drop_old(now, cfg["urlhaus_keep_days"])
        if self._off_day == today or self._mem_off == today:
            return {"status": "off-for-the-day"}
        last = self._last or self._mem_last
        if last is not None and -FUTURE_ALLOWED <= now - last < datetime.timedelta(hours=REFRESH_HOURS):
            return {"status": "not-due"}
        try:
            key = read_key(self._key_path)
        except UrlhausError as e:
            return {"status": "failed", "reason": f"the key file is not usable: {e}"}
        before = (self._last, self._off_day)
        self._last, self._off_day = now, today      # written down before the request, the day as off: only a clean answer clears it
        try:
            self._save()
        except (OSError, ListError) as e:
            self._last, self._off_day = before
            return {"status": "failed", "reason": f"the state cannot be written, so no request is made ({getattr(e, 'strerror', None) or type(e).__name__})"}
        self._mem_last = now
        report = recent(get, key, now, lists_plan, check=check)
        if report["status"] == "ok":
            self._entries.update(report["entries"])
            self._drop_old(now, cfg["urlhaus_keep_days"])
            if len(self._entries) > MAX_KEPT:
                newest = sorted(self._entries.items(), key=lambda item: item[1], reverse=True)[:MAX_KEPT]
                self._entries = dict(newest)
        if report.get("off_for_the_day"):
            self._mem_off = today
        else:
            self._off_day = None
        if not self._try_save():
            self._mem_off = today            # the day's state could not be written: this process asks no more today, and the state on disk still says off
        out = {"status": report["status"]}
        if "reason" in report:
            out["reason"] = report["reason"]
        if report["status"] == "ok":
            out["entries"] = len(self._entries)
            out["ignored"] = report["ignored"]
        return out

    def _try_save(self):
        try:
            self._save()
        except (OSError, ListError) as e:
            self.problems.append(f"the URLhaus state could not be written ({getattr(e, 'strerror', None) or type(e).__name__})")
            return False
        return True


def _fresh(today, date, keep_days):
    """Whether an entry added on `date` (YYYY-MM-DD) is kept: younger than the keep days, and not dated more than a day ahead."""
    age = (today - datetime.date.fromisoformat(date)).days
    return -FUTURE_ALLOWED.days <= age < keep_days
