#!/usr/bin/env python3
"""The action-review shadow hook: records what the engine would say about a command that raised a prompt, and says nothing.

The owner copies this file and ``shadow_store.py`` out of the project to a directory of their own and registers the hook for
the ``PermissionRequest`` event, matcher ``Bash``, with a time limit of 30 seconds and no ``onFailure`` setting:

    /usr/bin/env -i /absolute/path/to/python3 -I -B /path/to/shadow_hook.py --wb /absolute/path/to/wb

``env -i`` and ``-I`` are what keep the interpreter's own start-up from reading the environment (a hostile ``PYTHONPATH`` or user
site, and the variables that load code into a process): a script cannot defend itself against code that runs before it. This file
notes a missing ``-I`` and does nothing; it takes the home directory from the account database and not from ``HOME``, and has no
default launcher (``docs/specs/action-review.md``, "The shadow hook"). For each prompt it runs ``wb run action-review review --log-row
--collect '<command>'`` from the directory the command will run in, reads the lines the engine prints on standard error, and
writes a row to ``~/.config/project-workbench/action-review/`` through ``shadow_store``. It writes nothing to standard output
and exits 0 in every case: the prompt stays the owner's, whatever the engine said and whatever went wrong here. A failure of the
hook is noted on standard error, with fixed text that never quotes the command.

What it does not do: parse the command (the engine's own parse and exit path give the reason), find ``wb`` through ``PATH`` or
inside the command's own directory, pass its environment on, or trust a line of standard error that is not the last line of its
kind. The ``wb`` launcher is given a clean environment. Standard library only, apart from the store beside it.
"""

import sys

if __name__ == "__main__" and not sys.flags.isolated:
    # Above every other import, so that nothing the hook imports is taken from a path the environment named. This makes a missing
    # `-I` visible and stops the hook's work; it cannot stop code the interpreter ran before this file (the entry's `env -i` does).
    try:
        sys.stderr.write("the hook was not started with python3 -I; nothing was reviewed or recorded\n")
    except Exception:  # a closed standard error is `None`: whatever it is, the hook still exits 0
        pass
    sys.exit(0)

import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import pwd  # noqa: E402
import re  # noqa: E402
import signal  # noqa: E402
import subprocess  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import shadow_store as store  # noqa: E402  the store beside this file, whose directory is the first on the path

# The engine's own limit is 25 seconds and the hook's, in the owner's settings, is 30: this wait is between them, so the engine
# reports first and the hook records a timeout before the harness stops it.
WAIT_SECONDS = 27
SECOND_WAIT = 2  # after the group is killed, for the output of a program that left it; the two add up to under 30
MAX_INPUT = 1 << 20
MAX_COMMAND = 4096
MAX_REASON = 300  # the store's limit for a stored reason
MAX_STREAM = 2 << 20
USAGE = "usage: shadow_hook.py --wb <absolute path of the wb launcher>   (the launcher is required: there is no default)"
REASONS = ("reviewed", "no_rule", "unreviewable", "refused", "failed", "timeout")
# A timeout is exit 1 when `describe` ran out of time (a refusal) and exit 2 when the bridge did (a failure).
EXIT_OF = {"reviewed": (0,), "no_rule": (1,), "unreviewable": (1,), "refused": (1,), "failed": (2,), "timeout": (1, 2)}
ENGINE_FIELDS = ("rule", "facts_sha256", "rubric_sha256", "bridge", "model", "effort", "format")
ENVIRONMENT = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}
# A command the engine declined because of one of these checks holds a secret or touches a credential-named path, and the redactor
# below is a list of patterns that cannot tell what the engine's own scan can: nothing of such a command is collected (its verdict
# row stays, with the redacted reason). Plan `2026-11-04-shadow-hook-security-review-fixes`, increment A.
NO_COLLECT_CHECKS = ("no_secret_lines", "paths_not_credentials")


def note(err, text):
    try:
        err.write(text + "\n")
    except Exception:  # a note must never change the exit status
        pass


# -- redaction ---------------------------------------------------------------------------------------------------------
# What the hook stores is redacted by a fixed list of patterns (`docs/specs/action-review.md`, "The shadow hook"). It is best
# effort: a secret in a shape the list does not name is kept as it was. There is no rule by entropy, because it would hide the git
# hashes that the owner needs to judge a command. Every pattern is bounded or anchored so that its work is linear in the text, and
# a test pins the time on the largest text the hook can hold.

MAX_DEPTH = 64
_NAMES = r"secret|token|passw(?:or)?d|passphrase|credential|[_-]key|(?:api|access|private|auth)key"
_VALUE = r"""(?!\[redacted:)(?:"[^"\n]+"|'[^'\n]+'|["'][^\r\n]{4,}|[^\s"';]{4,})"""
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z0-9 ]{0,40}PRIVATE KEY(?: BLOCK)?-----.*?"
                          r"(?:-----END [A-Z0-9 ]{0,40}PRIVATE KEY(?: BLOCK)?-----|\Z)", re.S)
# Not \b: a hyphen is a character of the token, and \b before every "eyJ-" would start a scan to the end of the text each time.
_JWT = re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}")
_TOKEN = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b|\bgh[pousr]_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"
                    r"|\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}|\bxox[abprs]-[A-Za-z0-9-]{10,}|\bAIza[0-9A-Za-z_-]{35}")
_AUTHORIZATION = re.compile(r"""(\bAuthorization(?:\\?["'])?[ \t]{0,8}[:=][ \t]{0,8}(?:\\?["'])?)(?:(?:Basic|Bearer|Digest|Token)[ \t]+)?"""
                            r"""(?!\[redacted:)[^\s"',;]{8,}""", re.I)
_BEARER = re.compile(r"\b(Bearer[ \t]+)(?=[A-Za-z0-9._~+/=-]*[0-9._~+/=-])[A-Za-z0-9._~+/=-]{16,}", re.I)
_CREDENTIALS = re.compile(r"(\b[A-Za-z][A-Za-z0-9+.-]{0,20}://)[^\s/:@]{1,200}:[^\s/]{1,200}@")
# The name is found by its keyword, so that the work is a few steps per keyword and not per character; what comes before the
# keyword in the name is left where it is.
_ASSIGNMENT = re.compile(r"((?:%s)[A-Za-z0-9_.-]{0,32}(?:\\?[\"'])?[ \t]{0,8}[:=][ \t]{0,8}\\?)(%s)" % (_NAMES, _VALUE), re.I)
_FLAG = re.compile(r"((?<![-A-Za-z0-9])-{1,2}[a-z-]{0,32}(?:%s)[a-z-]{0,32}[ \t]+)(?!-)(%s)" % (_NAMES, _VALUE), re.I)


def _marker(kind):
    return "[redacted:%s]" % kind


def _quoted(match):
    """The assignment with its value replaced; a quote that opened the value stays, and so does one that closed it."""
    value = match.group(2)
    if value[0] in "\"'":
        return match.group(1) + value[0] + _marker("assignment") + (value[-1] if value[-1] == value[0] else "")
    return match.group(1) + _marker("assignment")


def redact_text(text):
    """`text` with every secret the patterns find replaced by ``[redacted:<kind>]``; anything else, line breaks included, is kept."""
    text = _PRIVATE_KEY.sub(_marker("private-key"), text)
    text = _JWT.sub(_marker("jwt"), text)
    text = _TOKEN.sub(_marker("token"), text)
    text = _AUTHORIZATION.sub(lambda match: match.group(1) + _marker("bearer"), text)
    text = _BEARER.sub(lambda match: match.group(1) + _marker("bearer"), text)
    text = _CREDENTIALS.sub(lambda match: match.group(1) + _marker("url-credentials") + "@", text)
    text = _FLAG.sub(_quoted, text)
    return _ASSIGNMENT.sub(_quoted, text)


def redact(value, depth=0):
    """A copy of a text, list or object of JSON values with every string redacted; keys, numbers, booleans and nulls are kept. A
    value of any other type, a key that is not a string, or a nesting deeper than MAX_DEPTH is refused with ValueError, so that a
    row is never written from something this function did not see whole."""
    if depth > MAX_DEPTH:
        raise ValueError("nested too deeply")
    if isinstance(value, str):
        return redact_text(value)
    if value is None or isinstance(value, (int, float)):  # a bool is an int
        return value
    if isinstance(value, list):
        return [redact(item, depth + 1) for item in value]
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("a key that is not a string")
            out[key] = redact(item, depth + 1)
        return out
    raise ValueError("a value of a type that is not JSON")


# -- the input --------------------------------------------------------------------------------------------------------

def read_event(stdin):
    """``(kind, command, cwd)``: kind is ``ok``, ``malformed_input`` or ``not_bash``."""
    try:
        data = stdin.read(MAX_INPUT + 1)
        if not isinstance(data, bytes) or len(data) > MAX_INPUT:
            return "malformed_input", None, None
        event = json.loads(data.decode("utf-8"))
    except (OSError, ValueError, RecursionError):
        return "malformed_input", None, None
    if not isinstance(event, dict) or event.get("hook_event_name") != "PermissionRequest":
        return "malformed_input", None, None
    if event.get("tool_name") != "Bash":
        return "not_bash", None, None
    tool_input, cwd = event.get("tool_input"), event.get("cwd")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command or not isinstance(cwd, str) or "\0" in cwd \
            or not os.path.isabs(cwd) or not os.path.isdir(cwd):
        return "malformed_input", None, None
    return "ok", command, cwd


def account_home():
    """The home directory of the account the hook runs as, from the account database, or None. The ``HOME`` variable is not read:
    it is part of the environment the harness passes on, and this directory decides where the rows go and what home the engine
    is given."""
    try:
        home = pwd.getpwuid(os.getuid()).pw_dir
    except (KeyError, OSError, OverflowError):
        return None
    return home if isinstance(home, str) and os.path.isabs(home) and "\0" not in home else None


def parse_arguments(argv):
    """The path of the ``wb`` launcher, or None for a call this hook does not take: ``--wb`` and its value, and nothing else."""
    if len(argv) == 2 and argv[0] == "--wb":
        return argv[1]
    return None


def usable_launcher(wb, cwd):
    """True when `wb` is an absolute path to an executable file named ``wb`` that is not inside the command's own directory,
    which a repository could change. The name is `wb` because the engine looks for that name in the trusted entries of its
    ``PATH``, which the hook builds from the launcher's own directory (so that directory must not hold the path separator)."""
    if not isinstance(wb, str) or "\0" in wb or not os.path.isabs(wb) or not os.path.isfile(wb) \
            or not os.access(wb, os.X_OK) or os.path.basename(wb) != "wb" or os.pathsep in os.path.dirname(wb):
        return False
    real, base = os.path.realpath(wb), os.path.realpath(cwd)
    return not (real == base or real.startswith(base + os.sep))


# -- the engine ---------------------------------------------------------------------------------------------------------

def run_engine(wb, command, cwd, home_dir):
    """``(exit code, standard output, standard error, timed out)`` of the engine, run in its own process group."""
    # The engine finds `wb` by name in the trusted entries of the PATH it inherits, so the launcher's own directory comes first.
    environment = dict(ENVIRONMENT, HOME=home_dir, PATH=os.pathsep.join([os.path.dirname(wb), ENVIRONMENT["PATH"]]))
    proc = subprocess.Popen([wb, "run", "action-review", "review", "--log-row", "--collect", command], cwd=cwd,
                            env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            start_new_session=True, close_fds=True)
    try:
        out, err = proc.communicate(timeout=WAIT_SECONDS)
        timed_out = False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            out, err = proc.communicate(timeout=SECOND_WAIT)
        except subprocess.TimeoutExpired:  # a program that left the group still holds the pipes: do not wait for it
            out, err = b"", b""
        timed_out = True
    return proc.returncode, out, err, timed_out


def last_line(lines, prefix):
    for line in reversed(lines):
        if line.startswith(prefix):
            return line[len(prefix):]
    return None


def parse_json(text):
    try:
        return json.loads(text)
    except (ValueError, RecursionError):
        return None


def read_verdict(out):
    """The engine's verdict object as ``(verdict, failed_checks, reason)``, or None unless it is exactly the object the
    engine promises: one line, three fields, an approve with no failed check and a decline with at least one."""
    try:
        text = out.decode("ascii")
    except UnicodeDecodeError:
        return None
    if not text.endswith("\n") or text.count("\n") != 1:
        return None
    body = parse_json(text)
    if not isinstance(body, dict) or set(body) != {"verdict", "failed_checks", "reason"}:
        return None
    verdict, failed, reason = body["verdict"], body["failed_checks"], body["reason"]
    if verdict not in ("approve", "decline") or not isinstance(failed, list) or len(failed) > 32 \
            or not all(isinstance(item, str) for item in failed) or (verdict == "approve") != (not failed) \
            or not isinstance(reason, str) or not 1 <= len(reason) <= 300 \
            or not all(" " <= char <= "~" for char in reason):
        return None
    return verdict, failed, reason


def classify(code, out, err, timed_out):
    """``(outcome, verdict, log_row, facts)`` from what the engine did. The outcome is the engine's own reason, taken from the
    last line of its standard error, and is believed only when it agrees with the exit code and, for a review, with a whole
    verdict object."""
    if timed_out:
        return "timeout", None, None, None
    if len(out) > MAX_STREAM or len(err) > MAX_STREAM:
        return "failed", None, None, None
    lines = err.decode("ascii", "replace").split("\n")
    present = [line for line in lines if line]
    body = parse_json(present[-1][len("outcome: "):]) if present and present[-1].startswith("outcome: ") else None
    reason = body.get("reason") if isinstance(body, dict) and set(body) == {"reason"} else None
    if reason not in REASONS:
        return ("refused" if code == 1 else "failed"), None, None, None
    if code not in EXIT_OF[reason]:
        return "failed", None, None, None
    if reason != "reviewed":
        return reason, None, None, None
    verdict = read_verdict(out)
    if verdict is None:
        return "failed", None, None, None
    row, facts = last_line(lines, "log-row: "), last_line(lines, "facts: ")
    row = parse_json(row) if row is not None else None
    facts = parse_json(facts) if facts is not None else None
    return "reviewed", verdict, row if isinstance(row, dict) else None, facts if isinstance(facts, dict) else None


# -- the rows ---------------------------------------------------------------------------------------------------------

def sha256(text):
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def write(err, name, row, home, fallback=None):
    """Append `row`; on a refusal try `fallback`; a store that cannot take it is noted and nothing else changes."""
    for candidate in (row, fallback):
        if candidate is None:
            continue
        try:
            store.append(name, candidate, home)
            return True
        except store.StoreError as exc:
            problem = str(exc)
    note(err, "the hook could not record a row in %s: %s" % (name, problem[:200]))
    return False


def redacted_text(err, command, verdict, facts):
    """``(reason, command, facts)`` as they may be stored: the reason, the command and the facts with their secrets replaced. The
    command and the facts are None when nothing is to be collected. If a redaction fails, or the redacted text no longer fits the
    store's limits, everything comes back None: a row never holds text that this function did not redact, and the note is fixed
    text that quotes nothing."""
    reason = verdict[2] if verdict else None
    try:
        if reason is not None:
            reason = redact_text(reason)
            if len(reason) > MAX_REASON:
                raise ValueError("the redacted reason is too long")
        if facts is None:
            return reason, None, None
        shown = redact_text(command)
        if len(shown) > MAX_COMMAND:
            raise ValueError("the redacted command is too long")
        return reason, shown, redact(facts)
    except Exception:  # whatever went wrong, no raw text goes to a file
        note(err, "the hook could not redact the text of a row; the reason and the collected row are left out")
        return None, None, None


def record(err, home, outcome, command, verdict=None, log_row=None, facts=None):
    """Write the verdict row for one prompted command and, for a reviewed command with its facts, the collected row. The reason,
    the command and the facts are stored redacted ("redaction"); the command's hash is of the command as it was."""
    reviewed = outcome == "reviewed"
    digest = sha256(command) if command is not None else None
    rule = log_row.get("rule") if log_row else None
    declined_for_a_secret = bool(verdict) and any(check in NO_COLLECT_CHECKS for check in verdict[1])
    collecting = reviewed and facts is not None and isinstance(rule, str) and not declined_for_a_secret
    reason, shown, facts = redacted_text(err, command, verdict, facts if collecting else None)
    row = {"ts": store.now(), "command_sha256": digest, "outcome": outcome,
           "verdict": verdict[0] if verdict else None, "failed_checks": list(verdict[1]) if verdict else [],
           "reason": reason, "reviewed": reviewed, "no_review_reason": None if reviewed else outcome}
    plain = dict(row)
    if reviewed and log_row:
        row.update({field: log_row[field] for field in ENGINE_FIELDS if field in log_row})
    write(err, "verdicts.jsonl", row, home, plain if row != plain else None)
    if collecting and shown is not None:
        write(err, "collected.jsonl", {
            "id": store.new_id(), "ts": row["ts"], "rule": rule, "command_sha256": digest, "command": shown,
            "facts": facts, "verdict": verdict[0], "failed_checks": list(verdict[1]), "reason": reason}, home)


def run(argv, stdin, err, home):
    home_dir = home if home is not None else account_home()
    if home_dir is None:
        note(err, "the hook could not find the account's home directory; nothing was reviewed or recorded")
        return
    wb = parse_arguments(argv)
    if wb is None:
        note(err, USAGE)
        return
    kind, command, cwd = read_event(stdin)
    if kind != "ok":
        record(err, home_dir, kind, None)
        return
    if len(command) > MAX_COMMAND:
        record(err, home_dir, "unreviewable", command)
        return
    if not usable_launcher(wb, cwd):
        note(err, "the hook was not given a wb it may run; nothing was reviewed")
        record(err, home_dir, "failed", command)
        return
    try:
        code, out, errb, timed_out = run_engine(wb, command, cwd, home_dir)
    except (OSError, ValueError):
        note(err, "the engine could not be started")
        record(err, home_dir, "failed", command)
        return
    outcome, verdict, log_row, facts = classify(code, out, errb, timed_out)
    record(err, home_dir, outcome, command, verdict, log_row, facts)


def main(argv, stdin, err, home=None):
    """Record one prompted command and return 0. Nothing is written to standard output, and an error of any kind, an
    interrupt included, is noted and does not change the return value: the hook answers nothing."""
    try:
        run(argv, stdin, err, home)
    except BaseException as exc:
        note(err, "the hook stopped on %s; the prompt is unchanged" % type(exc).__name__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], sys.stdin.buffer, sys.stderr))
