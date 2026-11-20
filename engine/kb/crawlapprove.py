"""The owner's approval of the crawl plan (`docs/specs/population.md`, "The crawl plan"; the plan `2026-11-16-build-the-safeguards-of-the-unattended-crawl`, Increment B; hardened by the plan `2026-11-16-run-the-steps-of-the-unattended-crawl`, Increment A).

`approve(...)` is `crawl-approve`. Without a digest it prints a plain summary of the plan, with the grant it makes in words, and a **digest**: the first 32 hex characters of the SHA-256 of the exact bytes of the plan file, the topics
file and the allow file, **and of the full behaviour fingerprint** below (the blacklist and the key file are not in it: the blacklist can only reduce what the runner does, and the key is a credential), so that code or
model settings that change between the owner's reading and approving are refused. The summary lists every allow host (at most `MAX_ALLOW_HOSTS`, or the file is refused for approval). With that digest, **at a terminal**, it stores the approval under
`<index root>/crawl/approved/`: `<digest>/` holding `plan.txt`, `topics.txt` and `allow.txt` (the approved copies), `fingerprint` and `summary.txt`, each mode 0400, and `current`, the digest, written last. It also creates
`crawl/breaker.json` as not tripped if there is none. The terminal check is the interlock `place-apply` uses; it keeps an agent or a scheduled job from approving, and it is not proof that a person typed.

The approval is **also bound to what will run**: the behaviour **fingerprint** is the SHA-256 of one byte string (the recipe is in the plan and the test holds a second implementation of it): a version line, then every regular
file under `engine/kb/` (a link or any other kind of entry is an error; the contents of a `__pycache__` folder are left out, and a `.pyc` anywhere else is an error) in the byte order of its repository-relative path, each as `<path length>:<path>:<file length>:<bytes>`, then
`config:` and a netstring of the canonical JSON of the model settings the crawl uses (`models_on`, the entries that eight named tasks name, and the fields of those entries that the engine reads: nothing else of the config, which
holds the owner's own settings). `load_approved(...)` is what `crawl-run` calls: it recomputes the digest of the stored copies and the stored fingerprint and the fingerprint of the code now, and returns the plan **only if
all match**, and refuses (`NotApproved`) for anything else, a link, a loose mode, a missing or extra file included. **The plan it returns names the approved copies** of the topics and the allow file (`plan["topics"]`,
`plan["allow"]`), so a step that reads them reads what was approved and not what the owner has edited since. An approval made under an earlier recipe of the digest is refused: approve again.

This module makes no request, reads no secret file and no environment variable."""
import datetime
import hashlib
import json
import os
import re
import shutil
import stat
import sys

from . import KbError, crawlplan, crawltopics, textutil, webaddr

CRAWL_TASKS = ("card-notes", "card", "card-check", "card-more", "place", "card-embed", "place-embed", "crawl-query")
ENTRY_FIELDS = ("bridge", "server", "model", "max_output", "thinking", "timeout", "kind", "dimension", "query_prefix", "document_prefix")
PREFIX = "engine/kb/"
FINGERPRINT_LINE = b"kb-fingerprint-1\n"
DIGEST_LINE = b"kb-crawl-approval-2\n"
MAX_ALLOW_HOSTS = 500
_DIGEST = re.compile(r"[0-9a-f]{32}")
_FINGERPRINT = re.compile(r"[0-9a-f]{64}")
MAX_FILE = 1_000_000
MAX_SMALL = 64 * 1024
NAMES = ("plan.txt", "topics.txt", "allow.txt", "fingerprint", "summary.txt")
CHANGED = "the engine's code or its model settings have changed since the plan was approved: approve again"
UNTRUSTED = "the approval cannot be trusted: approve again"


class NotApproved(KbError):
    """No plan is approved, or the approval does not hold. The reason is a fixed text that a log line may carry."""


def _utc_text(moment):
    return moment.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def digest_of(plan_bytes, topics_bytes, allow_bytes, fingerprint_hex):
    """The digest of the three files and of the behaviour fingerprint: the first 32 hex characters of the SHA-256 of their exact bytes, each framed by its name and length so that where one ends and the next
    begins cannot be moved. **The full fingerprint is in it**, so the digest the owner confirms is also what the code and the model settings were when the summary was read."""
    if not isinstance(fingerprint_hex, str) or not _FINGERPRINT.fullmatch(fingerprint_hex):
        raise KbError("the fingerprint is 64 lowercase hexadecimal characters")
    h = hashlib.sha256(DIGEST_LINE)
    for name, data in (("plan", plan_bytes), ("topics", topics_bytes), ("allow", allow_bytes), ("fingerprint", fingerprint_hex.encode("ascii"))):
        h.update(b"%s:%d:" % (name.encode("ascii"), len(data)))
        h.update(data)
        h.update(b"\n")
    return h.hexdigest()[:32]


def _tree(root):
    """`[(repository-relative path, bytes, mtime)]` for every regular file under `root` except the contents of `__pycache__` folders; anything that is not a plain file or folder, and a `.pyc` outside a `__pycache__` folder, is an error."""
    found = []

    def walk(folder, rel):
        try:
            entries = list(os.scandir(folder))
        except OSError as e:
            raise KbError(f"the engine's code cannot be read ({e.strerror})") from None
        for entry in entries:
            name = entry.name
            if entry.is_symlink():
                raise KbError("the engine's code holds a link, which is not taken")
            if entry.is_dir(follow_symlinks=False):
                if name != "__pycache__":
                    walk(entry.path, rel + name + "/")
            elif entry.is_file(follow_symlinks=False):
                if name.endswith(".pyc"):                   # Python imports a bytecode file that sits beside the code with no source, and it is in no fingerprint
                    raise KbError("the engine's code holds a bytecode file outside a __pycache__ folder, which Python would run without its source")
                found.append((rel + name, entry.path))
            else:
                raise KbError("the engine's code holds something that is neither a file nor a folder")

    walk(root, "")
    out = []
    for rel, path in found:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError as e:
            raise KbError(f"a file of the engine's code cannot be read ({e.strerror})") from None
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise KbError("the engine's code holds something that is not a plain file")
            with os.fdopen(fd, "rb", closefd=False) as f:
                data = f.read()
        except OSError as e:
            raise KbError(f"a file of the engine's code cannot be read ({e.strerror})") from None
        finally:
            os.close(fd)
        out.append((PREFIX + rel, data, info.st_mtime))
    return sorted(out, key=lambda item: item[0].encode("utf-8"))


def _model_settings(cfg):
    if not isinstance(cfg, dict):
        raise KbError("the config is not an object")
    tasks, models = cfg.get("tasks", {}), cfg.get("models", {})
    if not isinstance(tasks, dict) or not isinstance(models, dict):
        raise KbError("the config's tasks and models are not objects")
    chosen = {}
    for task in CRAWL_TASKS:
        if task in tasks:
            if not isinstance(tasks[task], str):
                raise KbError("the config names a task's entry that is not a name")
            chosen[task] = tasks[task]
    entries = {}
    for name in set(chosen.values()):
        entry = models.get(name)
        if entry is None:
            entries[name] = None
        elif isinstance(entry, dict):
            entries[name] = {key: entry[key] for key in ENTRY_FIELDS if key in entry}
        else:
            raise KbError("a model entry of the config is not an object")
    try:
        text = json.dumps({"models_on": cfg.get("models_on"), "tasks": chosen, "entries": entries}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError):
        raise KbError("the model settings of the config cannot be written down") from None
    return text.encode("ascii")


def fingerprint(cfg, kb_root=None):
    """`(the 64-hex fingerprint, the date of the newest file as YYYY-MM-DD in UTC)` of the engine's code and the crawl's model settings."""
    root = kb_root or os.path.dirname(os.path.abspath(__file__))
    files = _tree(root)
    pieces = [FINGERPRINT_LINE]
    newest = 0.0
    for path, data, mtime in files:
        raw = path.encode("utf-8")
        pieces.append(b"%d:%s:%d:" % (len(raw), raw, len(data)) + data)
        newest = max(newest, mtime)
    settings = _model_settings(cfg)
    pieces.append(b"config:%d:" % len(settings) + settings)
    date = datetime.datetime.fromtimestamp(newest, tz=datetime.timezone.utc).date().isoformat()
    return hashlib.sha256(b"".join(pieces)).hexdigest(), date


def _allow_hosts(text):
    """The hosts of the allow file, strictly: one a line, `#` starts a comment; a line that is not a host is an error that names its number and never its text."""
    hosts, bad = [], []
    for number, line in enumerate(text.split("\n"), 1):
        item = line.split("#", 1)[0].strip()
        if not item:
            continue
        try:
            hosts.append(webaddr.canon_host(item))
        except webaddr.AddressError:
            bad.append(number)
    if bad:
        raise KbError("the allow file has lines that are not hostnames: " + ", ".join(map(str, bad[:20])))
    return hosts


def _read(path, what):
    return crawltopics.read_text(path, what)


def _inputs(plan_path):
    """The plan, and the three files as the text read once: `(plan dict, plan text, topics, topics text, allow hosts, allow text)`. A topics file that changes while it is read is refused."""
    plan_text = _read(plan_path, "the crawl plan file")
    plan = crawlplan.parse_plan(plan_text)
    topics_text = _read(plan["topics"], "the topics file")
    topics = crawltopics.parse_topics(topics_text)
    try:
        os.lstat(plan["allow"])
    except FileNotFoundError:
        allow_text = ""
    except OSError as e:
        raise KbError(f"the allow file cannot be read ({e.strerror})") from None
    else:
        allow_text = _read(plan["allow"], "the allow file")
    hosts = _allow_hosts(allow_text)
    if len(hosts) > MAX_ALLOW_HOSTS:
        raise KbError(f"the allow file holds {len(hosts)} hosts, more than the {MAX_ALLOW_HOSTS} that the summary can list in full: shorten it")
    return plan, plan_text, topics, topics_text, hosts, allow_text


def _clean(text, limit=200):
    return textutil.clean(str(text), limit)


def _switch(value):
    return "on" if value else "off"


def render_summary(plan, topics, allow_hosts, fingerprint_hex, date):
    """The plain summary the owner reads before approving, without the digest line."""
    sections = {}
    for _topic, weight, section in topics:
        sections.setdefault(section, [weight, 0])[1] += 1
    kinds = ", ".join(plan["hold_kinds"])
    lines = [
        "WHAT YOU ARE ABOUT TO APPROVE",
        "",
        "Approving this plan lets the runner, without anyone at the keyboard, run again and again, on the schedule you set, for as long as the plan, the topics, the allow file, the engine's code and the model settings",
        "named below stay as they are now. It finds candidate books itself, in the sources named below and from them, fetches them slowly, files them as books, judges them, makes cards with the models on your server,",
        "and " + ("moves each kept book onto a shelf by the model's pick, with no further question to you." if plan["model_pick"] else "leaves each kept book on the default shelf (moves by the model's pick are off)."),
        "It takes only books it fetched itself. It is bounded by the ceilings below, and stopped by the stop file, the circuit breaker, the disk floors and a held lock. This is a larger grant than one list of moves:",
        "it covers a long period of unattended action. The terminal check you pass is an interlock; it is not proof that a person typed. If any of this is wrong, do not approve.",
        "",
        f"Ceilings: fetches per day {plan['fetches_per_day']}; books filed in all {plan['filed_total']}; fetches per site per day {plan['per_domain_per_day']}; candidates per run {plan['batch']}; cards per day "
        f"{plan['cards_per_day']}; queued rows {plan['queued_total']} ({plan['queued_per_domain']} per site); tries {plan['retries']}; one fetch may take {plan['fetch_timeout_s']} seconds; the day is the day in {plan['timezone']}.",
        f"Pacing: at least {plan['min_gap_s']} seconds between requests to one site and one address, and up to {plan['jitter']} more at random; the page user agent is {plan['user_agent']}.",
        f"Disk: a run stops when free space falls under the floors: the bulk drive {plan['bulk_floor_gb']} GB, the index drive {plan['index_floor_gb']} GB.",
        f"Circuit breaker: after {plan['consecutive_failures']} failures in a row, or {plan['failure_share']} of the last {plan['window']} fetches, or a model entry that has not answered for {plan['model_down_minutes']} minutes; "
        f"a site that refuses {plan['domain_refusals']} times in a day is stopped for the day.",
        f"Topics: {sum(count for _w, count in sections.values())} topics: " + ", ".join(f"{count} in {_clean(name, 40)} at weight {weight}" for name, (weight, count) in sections.items()) + ".",
        f"Sources: OpenAlex: {_switch(plan['openalex'])}{' (with your key)' if plan['openalex'] and plan['openalex_key'] else ''}; arXiv: {_switch(plan['arxiv'])}; Wikipedia: {_switch(plan['wikipedia'])}; web search: {_switch(plan['web_search'])}{' (LangSearch)' if plan['web_search'] and plan['web_search_engine'] == 'langsearch' else ''}; "
        f"{plan['wander_share']} of a batch from citation links, to depth {plan['wander_depth']}, {plan['wander_per_work']} per work.",
    ]
    if plan["openalex"] and plan["openalex_key"]:
        lines.append("  OpenAlex requests carry your key from the file openalex.key in your config folder, in the address of each request: its terms are for you to have read.")
    if plan["web_search"] and plan["web_search_engine"] == "langsearch":
        lines.append("  Web search uses LangSearch (api.langsearch.com) with your key from the file langsearch.key in your config folder; your query words go to it, and its terms are for you to have read.")
    elif plan["web_search"]:
        lines.append("  Web search uses DuckDuckGo's HTML results, best effort: its terms are unresolved and are for you to have read.")
    lines += [
        f"Public lists: phishing_domains: {_switch(plan['phishing_domains'])}; urlhaus_recent: {_switch(plan['urlhaus_recent'])}; refreshed at most every {plan['refresh_hours']} hours; "
        f"pinned sites never blocked by a public list: {', '.join(plan['pinned_hosts'])}.",
    ]
    if plan["urlhaus_recent"]:
        lines.append("  URLhaus (abuse.ch) is used with your key, for non-profit use under fair-use limits: its terms are for you to have read.")
    lines += [
        f"Scan findings that hold a book (it is filed, and not converted, indexed, carded or moved): {kinds}. A list named in the plan replaces the default list; it does not add to it.",
        f"Judgement: threshold: {plan['threshold'] if plan['threshold'] is not None else 'not set; a run refuses to fetch until one is set'}; at least {plan['min_chars']} characters of text.",
        f"moves by the model's pick: {_switch(plan['model_pick'])}.",
        ("PDF files: none are taken (pdf_max_mb is 0)." if plan["pdf_max_mb"] == 0 else
         f"PDF files: taken up to {plan['pdf_max_mb']} MB each, scanned before any conversion (a file with a finding in the hold list above is held), and converted in a tool that is killed above {plan['tool_rss_mb']} MB of memory."),
        ("Idle window: none (themes_window_s is 0): no themes are made between runs." if plan["themes_window_s"] == 0 else
         f"Idle window: after each run's fetch, up to {plan['themes_window_s']} seconds (never longer than the run's own time budget) make themes for books that have none, the vectors of the cards that have none, the vectors of the themes, and a repair of the weave when it is due; the stop file ends it"
         + (f"; once the day's fetches are used up the window is up to {plan['themes_window_full_s']} seconds (never past the end of the day, never longer than the run's own time budget)." if plan["themes_window_full_s"]
            else "; once the day's fetches are used up the window is the same length.")),
        f"  allow file: {len(allow_hosts)} host{'' if len(allow_hosts) == 1 else 's'}"
        + (" (a public list cannot block these; only your blacklist can), every one listed:" if allow_hosts else "") + ("" if allow_hosts else "."),
        *[f"    {_clean(h, 253)}" for h in allow_hosts],
        f"Code and model settings: fingerprint {fingerprint_hex[:12]}; the engine's code last changed on {date}. The digest on the last line covers the whole fingerprint, so code or model settings that change between your reading this and your approving are refused. Any later change to the engine's code, its schemas, or the "
        "model settings of the card, placement, embedding and crawl-query tasks stops every run until you approve again. A change to your blacklist does not need a new approval; a change to the allow file does.",
    ]
    return "\n".join(lines)


def _check_dir(path, create_mode=None):
    """A folder of ours that is not a link and that others cannot write; made with `create_mode` if it is not there and a mode is given."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        if create_mode is None:
            raise
        os.mkdir(path, create_mode)
        os.chmod(path, create_mode)
        return
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise KbError("a folder of the approval is a link or not a folder")
    if info.st_uid != os.getuid():
        raise KbError("a folder of the approval is not ours")
    if stat.S_IMODE(info.st_mode) & 0o022:
        raise KbError("a folder of the approval can be written by others")


def _write_ro(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fchmod(fd, 0o400)
        os.fsync(fd)
    finally:
        os.close(fd)


def _remove_tree(path):
    if not os.path.lexists(path):
        return
    for folder, _names, files in os.walk(path):
        os.chmod(folder, 0o700)
        for name in files:
            full = os.path.join(folder, name)
            if not os.path.islink(full):
                os.chmod(full, 0o600)
    shutil.rmtree(path, ignore_errors=True)


def _ensure_breaker(crawl_dir, now):
    """`crawl/breaker.json` as not tripped, if there is no file there (a link or anything else that is there is left alone: it reads as tripped)."""
    path = os.path.join(crawl_dir, "breaker.json")
    if os.path.lexists(path):
        return
    text = json.dumps({"tripped": False, "reason": "", "kind": "", "at": _utc_text(now), "run": ""}, sort_keys=True)
    tmp = os.path.join(crawl_dir, f".breaker-{os.urandom(6).hex()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, text.encode("ascii"))
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.link(tmp, path)     # a name that is taken in the meantime stays as it is
    except FileExistsError:
        pass
    finally:
        os.unlink(tmp)


def _store(index_root, digest, files):
    crawl = os.path.join(index_root, "crawl")
    approved = os.path.join(crawl, "approved")
    target = os.path.join(approved, digest)
    work = None
    try:
        _check_dir(crawl, 0o700)
        _check_dir(approved, 0o700)
        work = os.path.join(approved, f".new-{os.urandom(6).hex()}")
        os.mkdir(work, 0o700)
        for name, data in files.items():
            _write_ro(os.path.join(work, name), data)
        os.chmod(work, 0o500)
        old = None
        if os.path.lexists(target):
            info = os.lstat(target)
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                raise KbError("the folder of an earlier approval of this plan is not a plain folder of ours")
            old = os.path.join(approved, f".old-{os.urandom(6).hex()}")
            os.rename(target, old)
        os.rename(work, target)
        work = None
        if old is not None:
            _remove_tree(old)
        tmp = os.path.join(approved, f".current-{os.urandom(6).hex()}")
        _write_ro(tmp, digest.encode("ascii") + b"\n")
        try:
            os.replace(tmp, os.path.join(approved, "current"))
        except OSError:
            if os.path.lexists(tmp):
                os.chmod(tmp, 0o600)
                os.unlink(tmp)
            raise
    except OSError as e:
        raise KbError(f"the approval could not be stored ({e.strerror})") from None
    finally:
        if work is not None:
            _remove_tree(work)


def approve(index_root, cfg, plan_path, digest=None, is_tty=None, say=print, kb_root=None, now=None):
    """Without `digest`: `(the summary ending with "digest: <digest>", the digest)`, nothing written. With it, at a terminal, and only if the files still have that digest: store the approval and return
    `{"digest", "fingerprint" (the first 12 characters), "folder"}`."""
    plan, plan_text, topics, topics_text, allow_hosts, allow_text = _inputs(plan_path)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    plan_bytes, topics_bytes, allow_bytes = plan_text.encode("utf-8"), topics_text.encode("utf-8"), allow_text.encode("utf-8")
    fingerprint_hex, date = fingerprint(cfg, kb_root)
    current = digest_of(plan_bytes, topics_bytes, allow_bytes, fingerprint_hex)
    text = render_summary(plan, topics, allow_hosts, fingerprint_hex, date) + "\ndigest: " + current
    if digest is None:
        return text, current
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise KbError("the digest is the 32 lowercase hexadecimal characters on the last line of what `crawl-approve` prints")
    if is_tty is None:
        is_tty = lambda: sys.stdin.isatty() and sys.stdout.isatty()  # noqa: E731
    if not is_tty():
        raise KbError("crawl-approve with a digest takes the owner's approval from a terminal; run it in your own terminal (`crawl-approve` with no digest prints the summary and needs none)")
    if digest != current:
        raise KbError("the plan, topics or allow file, or the engine's code or model settings, are not the ones with that digest (they changed since you read the summary, or the digest is another's): run `crawl-approve` again, read the summary and give its digest")
    files = {"plan.txt": plan_bytes, "topics.txt": topics_bytes, "allow.txt": allow_bytes, "fingerprint": fingerprint_hex.encode("ascii") + b"\n", "summary.txt": text.encode("utf-8") + b"\n"}
    _store(index_root, current, files)
    try:
        _ensure_breaker(os.path.join(index_root, "crawl"), now)
    except OSError as e:
        raise KbError(f"the approval is stored, but the breaker file could not be made ({e.strerror}); a run reads a missing breaker file as tripped") from None
    folder = os.path.join(index_root, "crawl", "approved", current)
    say(f"approved: digest {current}; fingerprint of the code and model settings {fingerprint_hex[:12]}; stored in {folder}")
    return {"digest": current, "fingerprint": fingerprint_hex[:12], "folder": folder}


def _strict_read(path, limit):
    """The bytes of a plain file of ours with mode 0400, not a link, of at most `limit` bytes; otherwise `NotApproved`."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise NotApproved(UNTRUSTED) from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o400 or info.st_size > limit:
            raise NotApproved(UNTRUSTED)
        data = os.read(fd, limit + 1)
        if len(data) > limit:
            raise NotApproved(UNTRUSTED)
        return data
    except OSError:
        raise NotApproved(UNTRUSTED) from None
    finally:
        os.close(fd)


def _read_folder(approved, digest):
    """One stored approval, read as strictly as a run reads it, without comparing it with the code now: `(folder, the plan's bytes, the stored fingerprint)`, or `NotApproved` for a link, a loose mode, an extra or
    missing file, a changed byte (the digest covers the three copies and the stored fingerprint) or a malformed name."""
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise NotApproved(UNTRUSTED)
    folder = os.path.join(approved, digest)
    try:
        _check_dir(folder)
        names = sorted(os.listdir(folder))
    except (KbError, OSError):
        raise NotApproved(UNTRUSTED) from None
    if names != sorted(NAMES):
        raise NotApproved(UNTRUSTED)
    plan_b = _strict_read(os.path.join(folder, "plan.txt"), MAX_SMALL)
    topics_b = _strict_read(os.path.join(folder, "topics.txt"), MAX_FILE)
    allow_b = _strict_read(os.path.join(folder, "allow.txt"), MAX_FILE)
    stored = _strict_read(os.path.join(folder, "fingerprint"), 65)
    _strict_read(os.path.join(folder, "summary.txt"), MAX_FILE)
    if len(stored) != 65 or stored[-1:] != b"\n" or not _FINGERPRINT.fullmatch(stored[:-1].decode("ascii", "replace")):
        raise NotApproved(UNTRUSTED)
    if digest_of(plan_b, topics_b, allow_b, stored[:-1].decode("ascii")) != digest:
        raise NotApproved(UNTRUSTED)
    return folder, plan_b, stored[:-1].decode("ascii")


def stored_digests(index_root):
    """The digests of every stored approval that reads strictly (see `_read_folder`), whether or not it is the current one and whether or not the code has changed since: a book found under it was found by an
    approved run. An empty set if there is none."""
    approved = os.path.join(os.fspath(index_root), "crawl", "approved")
    try:
        _check_dir(os.path.join(os.fspath(index_root), "crawl"))
        _check_dir(approved)
        names = os.listdir(approved)
    except (KbError, OSError):
        return set()
    found = set()
    for name in names:
        try:
            _read_folder(approved, name)               # a name that is not a digest is refused by it
        except NotApproved:
            continue
        found.add(name)
    return found


def load_approved(index_root, cfg, kb_root=None):
    """The approved plan, or `NotApproved`. Returns `{"plan", "digest", "fingerprint", "plan_path", "topics_path", "allow_path", "folder"}`; the paths are those of the approved copies."""
    crawl = os.path.join(index_root, "crawl")
    approved = os.path.join(crawl, "approved")
    for path in (crawl, approved):
        try:
            _check_dir(path)
        except FileNotFoundError:
            raise NotApproved("no plan is approved") from None
        except (KbError, OSError):
            raise NotApproved(UNTRUSTED) from None
    try:
        os.lstat(os.path.join(approved, "current"))
    except FileNotFoundError:
        raise NotApproved("no plan is approved") from None
    except OSError:
        raise NotApproved(UNTRUSTED) from None
    line = _strict_read(os.path.join(approved, "current"), 64)
    if len(line) != 33 or line[-1:] != b"\n" or not _DIGEST.fullmatch(line[:-1].decode("ascii", "replace")):
        raise NotApproved(UNTRUSTED)
    digest = line[:-1].decode("ascii")
    folder, plan_b, stored_fingerprint = _read_folder(approved, digest)
    try:
        now_fingerprint = fingerprint(cfg, kb_root)[0]
    except KbError:
        raise NotApproved(CHANGED) from None
    if now_fingerprint != stored_fingerprint:
        raise NotApproved(CHANGED)
    try:
        plan = crawlplan.parse_plan(plan_b.decode("utf-8"))
    except (KbError, UnicodeDecodeError):
        raise NotApproved(UNTRUSTED) from None
    topics_path, allow_path = os.path.join(folder, "topics.txt"), os.path.join(folder, "allow.txt")
    plan["topics"], plan["allow"] = topics_path, allow_path          # a step reads what was approved, never the owner's live files
    return {"plan": plan, "digest": digest, "fingerprint": now_fingerprint, "plan_path": os.path.join(folder, "plan.txt"), "topics_path": topics_path, "allow_path": allow_path,
            "folder": folder}
