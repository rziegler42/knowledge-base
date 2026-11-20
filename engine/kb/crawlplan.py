"""The crawl plan file and its reader (`docs/specs/population.md`, "The crawl plan"; the plan `2026-11-16-build-the-safeguards-of-the-unattended-crawl`, Increment A).

The plan is the owner's one plain-text file, kept outside the repository: `[section]` lines and `key = value` lines, a `#` starting a comment anywhere in a line, every key with the spec's default. `read_plan(path)` returns a
**flat dictionary of every key** (the defaults for the keys the file leaves out). The reader is strict: an unknown section or key, a value of the wrong kind or out of range, a key in another section than its own and a key
given twice in a section are refused, **with the number of the line and never its text** (what a plan line says is the owner's, but a message may reach a log). A file that is a link, not a plain file, over 64 KiB, not
UTF-8 or holding a NUL is refused.

The keys that discovery reads (`discover.PLAN`) are taken from discovery's own table, so the two readers cannot disagree on them; the list settings are checked by `weblists.check_plan`, which takes them. `lists_plan(plan)`
and `discovery_plan(plan)` hand those two modules exactly the keys they take. `day_of(now, timezone)` is the day of a time in the plan's `timezone` (`local` or an IANA name), which is the day of every ceiling.
This module reads one file and nothing else: no network, no config and no environment variable of its own (a `~` in a path is expanded by `os.path.expanduser`, which reads the home folder, and `local` is the machine's zone)."""
import datetime
import os
import re
import zoneinfo

from . import KbError, crawltopics, discover, scan_tool, weblists, webaddr

MAX_BYTES = 64 * 1024
HOME = "~/.config/knowledge-base/"
# the kinds of scan finding that hold a book unless the plan says otherwise: the hostile ones (the spec's list), and never the three that almost every page has
DEFAULT_HOLD = ("encrypted", "javascript", "launch_action", "embedded_files", "xfa_forms", "external_actions", "rich_media", "scan_incomplete", "malformed", "meta_refresh", "embedded_content")
NEVER_HOLD = ("script_elements", "event_handlers", "pattern_in_binary_data")
_SECTION = re.compile(r"\[([a-z_]+)\]")
_LINE = re.compile(r"([a-z_][a-z0-9_]*)[ \t]*=(.*)")
_WHOLE = re.compile(r"[0-9]{1,9}")
_NUMBER = re.compile(r"[0-9]{1,9}(?:\.[0-9]{1,15})?")
_SIGNED = re.compile(r"-?[0-9]{1,9}(?:\.[0-9]{1,15})?")
# key: (section, kind, default, lowest, highest); discovery's keys are its own
PLAN = dict(discover.PLAN)
PLAN.update({
    "fetches_per_day": ("limits", "int", 20, 1, 10_000),
    "filed_total": ("limits", "int", 200, 1, 1_000_000),
    "per_domain_per_day": ("limits", "int", 3, 1, 1000),
    "batch": ("limits", "int", 8, 1, 1000),
    "cards_per_day": ("limits", "int", 30, 1, 10_000),
    "retries": ("limits", "int", 3, 1, 20),
    "fetch_timeout_s": ("limits", "int", 60, 1, 3600),
    "timezone": ("limits", "timezone", "local", None, None),
    "min_gap_s": ("pacing", "number", 8, 0, 3600),
    "jitter": ("pacing", "number", 0.5, 0, 3600),
    "user_agent": ("pacing", "choice", "browser", ("browser", "generic"), None),
    "bulk_floor_gb": ("disk", "number", 50, 0, 1_000_000),
    "index_floor_gb": ("disk", "number", 10, 0, 1_000_000),
    "consecutive_failures": ("breaker", "int", 8, 1, 1000),
    "failure_share": ("breaker", "share_over_zero", 0.5, 0, 1),
    "window": ("breaker", "int", 20, 1, 1000),
    "model_down_minutes": ("breaker", "int", 30, 1, 10_080),
    "domain_refusals": ("breaker", "int", 3, 1, 100),
    "phishing_domains": ("lists", "list", weblists.DEFAULTS["phishing_domains"], None, None),
    "urlhaus_recent": ("lists", "list", weblists.DEFAULTS["urlhaus_recent"], None, None),
    "phishing_domains_url": ("lists", "list", weblists.DEFAULTS["phishing_domains_url"], None, None),
    "phishing_domains_format": ("lists", "list", weblists.DEFAULTS["phishing_domains_format"], None, None),
    "public_suffix_url": ("lists", "list", weblists.DEFAULTS["public_suffix_url"], None, None),
    "refresh_hours": ("lists", "list", weblists.DEFAULTS["refresh_hours"], None, None),
    "list_max_mb": ("lists", "list", weblists.DEFAULTS["list_max_mb"], None, None),
    "list_min_share": ("lists", "list", weblists.DEFAULTS["list_min_share"], None, None),
    "list_max_change": ("lists", "list", weblists.DEFAULTS["list_max_change"], None, None),
    "urlhaus_keep_days": ("lists", "list", weblists.DEFAULTS["urlhaus_keep_days"], None, None),
    "pinned_hosts": ("lists", "hosts", list(weblists.DEFAULTS["pinned_hosts"]), None, None),
    "hold_kinds": ("scan", "kinds", list(DEFAULT_HOLD), None, None),
    "threshold": ("judge", "threshold", None, -1, 1),
    "min_chars": ("judge", "int", 400, 1, 100_000),
    "model_pick": ("moves", "switch", True, None, None),
    "pdf_max_mb": ("pdf", "int", 0, 0, 200),                # the largest PDF the crawl takes, in megabytes; 0 takes none (the client holds a response whole in memory, about twice its size at peak)
    "tool_rss_mb": ("pdf", "int", 2048, 64, 100_000),       # the most resident memory a scan or a converter may use before the sandbox kills it
    "themes_window_s": ("idle", "int", 600, 0, 3600),       # the seconds a run may spend after its fetch on themes, the vectors of the themes and the weave; 0 is off
    "themes_window_full_s": ("idle", "int", 3600, 0, 3600), # the same, in a run whose day has used up its fetches (never past the end of the day); 0 is the same as `themes_window_s`
    "topics": ("files", "path", HOME + "crawl-topics.txt", None, None),
    "blacklist": ("files", "path", HOME + "crawl-blacklist.txt", None, None),
    "allow": ("files", "path", HOME + "crawl-allow.txt", None, None),
})
SECTIONS = frozenset(spec[0] for spec in PLAN.values())
_EMPTY_OK = ("hold_kinds", "threshold")


def _refuse(number, message):
    return KbError(f"the crawl plan file: line {number}: {message}")


def _default(key):
    spec = PLAN[key]
    value = spec[2]
    if spec[1] == "path":
        return os.path.expanduser(value)
    return list(value) if isinstance(value, list) else value


def defaults():
    """The plan with every key at its default (a new dictionary)."""
    return {key: _default(key) for key in PLAN}


def _number(kind, text):
    return float(text) if "." in text else int(text)


def _value(key, raw, number):
    section, kind, _default_value, low, high = PLAN[key]
    if kind == "switch":
        lower = raw.lower()
        if lower == "on" or (key == "web_search" and lower == "duckduckgo"):
            return True
        if lower == "off":
            return False
        raise _refuse(number, "the value is on or off" + (" (or duckduckgo)" if key == "web_search" else ""))
    if kind == "int":
        if not _WHOLE.fullmatch(raw):
            raise _refuse(number, "the value is a whole number")
        value = int(raw)
        if not low <= value <= high:
            raise _refuse(number, f"the value is out of range ({low} to {high})")
        return value
    if kind in ("share", "seconds", "number", "share_over_zero"):    # `share` and `seconds` are discovery's kinds, `number` is ours
        if not _NUMBER.fullmatch(raw):
            raise _refuse(number, "the value is a number")
        value = _number(kind, raw)
        if not low <= value <= high or (kind == "share_over_zero" and value == 0):
            raise _refuse(number, "the value is out of range")
        return value
    if kind == "choice":
        if raw not in low:
            raise _refuse(number, "the value is one of: " + ", ".join(low))
        return raw
    if kind == "timezone":
        if raw != "local" and raw not in zoneinfo.available_timezones():
            raise _refuse(number, "the value is local or the name of a time zone the system knows")
        return raw
    if kind == "threshold":
        if raw == "":
            return None
        if not _SIGNED.fullmatch(raw):
            raise _refuse(number, "the value is a number from -1 to 1, or empty")
        value = _number(kind, raw)
        if not low <= value <= high:
            raise _refuse(number, "the value is out of range (-1 to 1)")
        return value
    if kind == "kinds":
        if raw == "":
            return list(DEFAULT_HOLD)
        names = [part.strip() for part in raw.split(",")]
        for name in names:
            if name not in scan_tool.KINDS or name in NEVER_HOLD:
                raise _refuse(number, "a name in the list is not a kind of scan finding that can hold a book")
        if len(set(names)) != len(names):
            raise _refuse(number, "a kind is named twice")
        return names
    if kind == "path":
        return os.path.expanduser(raw)
    if kind == "hosts":
        names = [part.strip() for part in raw.split(",")]
        try:
            weblists.check_plan({"pinned_hosts": names})
            canonical = [webaddr.canon_host(name) for name in names]
        except (KbError, ValueError):
            raise _refuse(number, "the value is a list of sites, separated by commas") from None
        return list(dict.fromkeys(canonical))
    if kind == "list":     # the list settings are the lists module's to check
        parsed = _list_value(key, raw, number)
        try:
            weblists.check_plan({key: parsed})
        except KbError:
            raise _refuse(number, "the value is not one the lists take") from None
        return parsed
    raise AssertionError(kind)


def _list_value(key, raw, number):
    default = PLAN[key][2]
    if isinstance(default, bool):
        lower = raw.lower()
        if lower in ("on", "off"):
            return lower == "on"
        raise _refuse(number, "the value is on or off")
    if isinstance(default, (int, float)):
        if not _NUMBER.fullmatch(raw):
            raise _refuse(number, "the value is a number")
        return _number("number", raw)
    return raw


def read_plan(path):
    """The plan file at `path` as a flat dictionary of every key (the spec's default for each key the file leaves out), or a `KbError` that names a line and never quotes it."""
    return parse_plan(crawltopics.read_text(path, "the crawl plan file"))


def parse_plan(text):
    """The same from the text of a plan that has been read already (so that the bytes that are approved are the bytes that are parsed)."""
    if not isinstance(text, str):
        raise KbError("the crawl plan file: the plan is text")
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise KbError(f"the crawl plan file: it is over {MAX_BYTES // 1024} KiB")
    plan = defaults()
    section, seen, word = None, set(), None   # `word` is what the plan wrote for web_search, in lower case
    for number, raw_line in enumerate(text.removeprefix("﻿").replace("\r\n", "\n").replace("\r", "\n").split("\n"), 1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        found = _SECTION.fullmatch(line)
        if found:
            section = found.group(1)
            if section not in SECTIONS:
                raise _refuse(number, "this is not a section of the plan")
            continue
        found = _LINE.fullmatch(line)
        if not found or section is None:
            raise _refuse(number, "a line is [section] or key = value, under a section")
        key, raw = found.group(1), found.group(2).strip()
        spec = PLAN.get(key)
        if spec is None:
            raise _refuse(number, "this is not a key of the plan")
        if spec[0] != section:
            raise _refuse(number, f"this key belongs to the section [{spec[0]}]")
        if (section, key) in seen:
            raise _refuse(number, "the key is given twice in the section")
        seen.add((section, key))
        if raw == "" and key not in _EMPTY_OK:
            raise _refuse(number, "the value is empty")
        plan[key] = _value(key, raw, number)
        if key == "web_search":
            word = raw.lower()
        if word == "duckduckgo" and plan["web_search_engine"] == "langsearch" and key in ("web_search", "web_search_engine"):
            raise _refuse(number, "web_search = duckduckgo names the engine and web_search_engine says langsearch: write web_search = on")
    return plan


def lists_plan(plan):
    """The settings of the public lists as `weblists.Matcher.update` takes them: exactly its keys."""
    return {key: (list(plan[key]) if isinstance(plan[key], list) else plan[key]) for key in weblists.DEFAULTS}


def discovery_plan(plan):
    """The settings discovery reads, as `discover.normalize_plan` takes them: exactly the keys of `discover.PLAN`."""
    return {key: plan[key] for key in discover.PLAN}


def day_end(now, timezone):
    """The end of the day that `day_of(now, timezone)` names: the start of the next day in the plan's zone, as an aware time **in UTC** (`local` is the machine's zone, with its changes of the clock; a day of 23 or 25
    hours has its own end). UTC is returned so that it is compared and subtracted as a real instant: two times that share one zone object are compared by their wall clocks, which is wrong across a change of the
    clock. A time with no zone and a zone that is not known are refused as `day_of` refuses them."""
    day = datetime.date.fromisoformat(day_of(now, timezone)) + datetime.timedelta(days=1)
    start = datetime.datetime.combine(day, datetime.time.min)
    if timezone == "local":
        end = start.astimezone()                    # a time with no zone is taken as the machine's own time, changes of the clock included
    else:
        end = start.replace(tzinfo=zoneinfo.ZoneInfo(timezone))
    return end.astimezone(datetime.timezone.utc)


def day_of(now, timezone):
    """The day, as `YYYY-MM-DD`, of an aware time in the plan's zone (`local` is the machine's zone)."""
    if not isinstance(now, datetime.datetime) or now.tzinfo is None:
        raise KbError("a time needs a time zone")
    try:
        zone = None if timezone == "local" else zoneinfo.ZoneInfo(timezone)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError, TypeError):
        raise KbError("the plan's time zone is not one the system knows") from None
    return now.astimezone(zone).date().isoformat()
