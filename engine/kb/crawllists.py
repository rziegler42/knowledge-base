"""The `lists` point of a crawl run (`docs/specs/population.md`, "Sites that are off limits" and "A key is a credential"; the plan `2026-11-16-run-the-steps-of-the-unattended-crawl`, Increment D).

`make_step(fetch=None, key_path=None)` gives the function that a run attaches at its `lists` point (`step` is the one with the shared web client and the owner's key file). It

1. builds the **matcher** (`weblists.Matcher`) from the owner's blacklist (read afresh every run: a bad line is a refusal that names its number and never its text), the allow file (the plan's, which a run has made
   the **approved copy**), the stored copies of the public lists and the pinned source hosts;
2. refreshes the public lists that are due (`refresh_hours`) through the shared client under **one policy**: the honest generic user agent, the plan's gap and jitter, no credential, text types only, and an
   address hook that looks at the stop file before each request and refuses an address the matcher blocks. A failed download or a list that is refused (too large, far smaller, changed too much, no valid entry) leaves the last
   good copy in use; a required list with no copy at all makes the step raise `crawlrun.StepRefused`, so that the run refuses and no step after it runs;
3. when the plan turns URLhaus recent mode on, lets `urlhaus.Source` ask for the recent URLs with the owner's key: the key is read only if the file is a plain file of the owner's with mode 600; it goes only in the
   `Auth-Key` header, over https, to its own host, in a call that follows no redirect (the client refuses anything else before a request); it is given to the log as a **secret** the moment it is read; any refusal,
   a redirect included, or a rate limit at zero stops the service for the rest of the day; and nothing that is raised inside the request reaches a log line, a report or an error with more than the name of its type;
4. logs one `list_update` line for each list (and one for each problem the matcher found with the stored copies) (`ok`, `skipped`, `failed` or `refused`, with the list's name and a reason, and never a list's text), and leaves `ctx.matcher`, `ctx.suffixes` (the Public Suffix List, which
   the policy of every later fetch is given) and `ctx.lists_report` for the steps after it.

This module makes no request of its own (the client is passed in), reads no environment variable of its own and changes no candidate row."""
import os

from . import KbError, config, crawlguard, crawlplan, crawlrun, urlhaus, webclient, weblists

LISTS_FOLDER = "lists"
KEY_FILE = "urlhaus.key"
LIST_TYPES = ("text/plain",)
OUTCOMES = {"updated": "ok", "ok": "ok", "unchanged": "skipped", "not-due": "skipped", "off": "skipped", "skipped": "skipped", "off-for-the-day": "skipped",
            "failed": "failed", "busy": "failed", "refused": "refused"}


def lists_folder(index_root):
    """Where the stored lists and the URLhaus state are kept: `<index root>/crawl/lists`, mode 700."""
    return os.path.join(os.fspath(index_root), "crawl", LISTS_FOLDER)


def _count(result):
    value = result.get("entries")
    if isinstance(value, dict):
        return len(value)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _log(log, now, name, result):
    status = result.get("status")
    detail = result.get("reason") or status
    log.write("list_update", OUTCOMES.get(status, "failed"), reason=log.safe(f"{name}: {detail}"), n=_count(result), now=now)


def _hook(index_root, matcher):
    """The policy's address hook: the stop file is looked at before each request, and an address the matcher blocks is not requested."""
    def check(address):
        if crawlguard.stop_requested(index_root):
            return "the stop file is present"
        return matcher.blocked(address) or None
    return check


def _remember_key(log, key_path):
    try:
        log.add_secrets([urlhaus.read_key(key_path)])
    except KbError:
        pass                                                      # no usable key: the source says so itself, and no request is made


def _run(ctx, fetch, key_path):
    plan, log, now = ctx.plan, ctx.log, ctx.clock()
    folder = lists_folder(ctx.index_root)
    try:
        matcher = weblists.Matcher(plan["blacklist"], plan["allow"], folder, plan["pinned_hosts"])      # the folder is made by the matcher's refresh and by the URLhaus source, in mode 700
    except KbError as e:                       # `ListError` is one: its message is safe to log and names a line, not its text
        raise crawlrun.StepRefused(f"the lists, the owner's blacklist or the allow file cannot be used: {e}") from None
    hook = _hook(ctx.index_root, matcher)
    policy = webclient.Policy(user_agent=webclient.GENERIC_USER_AGENT, gap=plan["min_gap_s"], jitter=plan["jitter"], follow_redirects=True, types=LIST_TYPES, check=hook,
                              suffixes=matcher.suffixes() or None)
    lists_plan = crawlplan.lists_plan(plan)

    def list_get(url, headers, max_bytes):
        return fetch(url, policy=policy, headers=headers, max_bytes=max_bytes)

    try:
        report = matcher.update(list_get, now, lists_plan)
    except KbError as e:
        raise crawlrun.StepRefused(f"the lists cannot be refreshed: {e}") from None
    for name, result in report["lists"].items():
        if name != "urlhaus_recent":           # URLhaus is the next call's
            _log(log, now, name, result)
    out = {"status": "off"}
    if plan["urlhaus_recent"]:
        _remember_key(log, key_path)                              # the key is a secret of the run from the moment it is read; it is not kept anywhere else
        try:
            out = urlhaus.Source(folder, key_path).update(fetch, now, lists_plan, matcher=matcher, check=hook)
        except Exception as e:                                    # what a downloader or the source raised is named by its type only
            out = {"status": "failed", "reason": f"the request failed ({type(e).__name__})"}
    if plan["urlhaus_recent"]:
        _remember_key(log, key_path)                              # the source read the file itself: if it changed since, the value it sent is a secret too
    _log(log, now, "urlhaus_recent", out)
    for problem in matcher.problems:                              # a stored copy that does not match its record, a lists folder that is not plain: said, though the run goes on
        log.write("list_update", "failed", reason=log.safe(f"stored lists: {problem}"), now=now)
    ctx.lists_report = {"lists": report["lists"], "urlhaus": out}
    if report["stop"]:
        raise crawlrun.StepRefused(report["stop_reason"])
    ctx.matcher, ctx.suffixes = matcher, matcher.suffixes()


def make_step(fetch=None, key_path=None):
    """The step for the `lists` point. `fetch` is `webclient.get` or a stand-in with its signature (tests pass one); `key_path` is the URLhaus key file (the owner's config folder by default)."""
    def step(ctx):
        _run(ctx, fetch or webclient.get, key_path or os.path.join(config.config_dir(), KEY_FILE))
    return step


step = make_step()
