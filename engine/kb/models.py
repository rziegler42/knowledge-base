"""Calls to a model through the workbench's Ollama bridge.

The owner lists models in the config (`models`, named entries), switches model work on (`models_on`) and says which entry does
each kind of work the engine knows (`tasks`). A call starts `wb run ask-ollama ask` as a separate program, with an argument
list and no shell, sends the prompt on standard input and reads one JSON object back. The engine prefers no model: `choose`
returns only the entry the setting names. Nothing here retries or batches. What comes back is model output: it is
untrusted data, and this module only checks that it has the bridge's shape. The server's address is in the workbench's own
endpoint file; the registry holds a server name only."""
import json
import math
import os
import re
import select
import stat
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

from . import KbError, textutil

MAX_PROMPT = 262144   # the bridge's limit on the prompt, in bytes
MAX_REPLY = 262144    # and on the reply
MAX_OUT = 2_000_000   # what is read from the bridge: its reply object, with the escaping of a reply of MAX_REPLY, fits
MAX_ERR = 4096
DEFAULT_TIMEOUT = 600  # the bridge's own default, in seconds
GRACE = 15             # seconds more than the bridge's time limit before the engine stops it
SUPERVISOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "supervisor.py")  # the watchdog that outlives the engine
WATCHDOG_WAIT = 5      # seconds the engine waits for the watchdog to say it is ready
WATCHDOG_MARGIN = 10   # seconds more than the engine's own limit before the watchdog stops the launcher itself
_PYTHON = sys.executable
CONTRACT = 2
VENDOR = "ollama"
BRIDGE = "ask-ollama"
_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
_SERVER = _NAME
_SEGMENT = r"[A-Za-z0-9][A-Za-z0-9._:-]*"
_MODEL = re.compile(_SEGMENT + "(?:/" + _SEGMENT + ")*")  # the bridge's rule for a model name: segments joined by a slash
_KEYS = ("bridge", "server", "model", "max_output", "thinking", "timeout", "kind", "dimension", "query_prefix", "document_prefix")
PREFIXES = ("query_prefix", "document_prefix")  # text that goes in front of a query, and of a stored text, when an embedding model makes its vector
MAX_PREFIX = 400
EMBED_KINDS = ("document", "query")  # what a text given to `embed` is
KINDS = ("chat", "embedding")
_REQUIRED = ("bridge", "server", "model")
MAX_MAX_OUTPUT = 200000
MAX_TIMEOUT = 3600  # the bridge refuses a longer one
MAX_MODEL = 128
MAX_SCHEMA = 65536  # the bridge reads a schema file of at most this many bytes
MAX_DIMENSION = 8192   # the largest vector the embed command of the bridge returns
EMBED_CONTRACT = 1     # the version of the embedding contract of the bridge, apart from the bridge contract
MAX_TEXT = 32768       # the bridge's limit on one text to embed, in bytes
MAX_TEXTS = 100       # and on the texts of one call
MAX_EMBED_TEXTS = 100_000  # the most texts one call of `embed` takes (it sends them in as many calls as the bridge needs)
BATCH_BYTES = 200_000  # the bytes of one batch as sent (the bridge reads at most 262144)
REPLY_BYTES = 1_500_000  # what one batch may be expected to print (the engine reads at most MAX_OUT)
NUMBER_BYTES = 26      # what one number of a vector takes as printed, at most: 24 characters (`-1.2345678901234567e-100`) and `, `
MAX_COMPONENT = 1e6    # a number of a vector larger than this in size is refused
MIN_SCALE = 1e-30      # and so is a vector whose largest number is smaller than this (its squares would vanish in a cosine)
MAX_EMBED_NUMBERS = 10_000_000  # the most numbers (texts times the dimension) one call of `embed` holds in memory
SCHEMA_DIR = ("engine", "kb", "schemas")  # where a job's schema file is kept, relative to the project root
_SCHEMA_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\.json")
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}")
_FIELD = re.compile(r"[a-z][a-z0-9_]{0,39}")
_LIMIT = 1_000_000


def _count(value, low, high):
    return type(value) is int and low <= value <= high


def _valid_model(value):
    return isinstance(value, str) and 0 < len(value) <= MAX_MODEL and ".." not in value and _MODEL.fullmatch(value) is not None


def _prefix_ok(value):
    """True for text of 1 to MAX_PREFIX characters that are printable, or a line break: no control character, no zero-width, direction or
    other format character, no lone surrogate, no private-use or unassigned character and no separator other than the plain space.
    A combining mark, a variation selector, a filler and a letter that looks like another are allowed (they are in text of many
    languages), so this does not make the text sure to be what it looks like; it is the owner's own text, sent to the owner's server."""
    return isinstance(value, str) and 0 < len(value) <= MAX_PREFIX and all(c == "\n" or c.isprintable() for c in value)


def _entry(name, e):
    if not isinstance(e, dict):
        raise KbError(f"the config entry models.{name} is not an object")
    for key in e:
        if key not in _KEYS:
            raise KbError(f"the config entry models.{name} has a key it does not know: {textutil.clean(key, 40)!r}")
    for key in _REQUIRED:
        if key not in e:
            raise KbError(f"the config entry models.{name} lacks {key}")
    if e["bridge"] != BRIDGE:
        raise KbError(f"models.{name}.bridge must be {BRIDGE}")
    if not isinstance(e["server"], str) or not _SERVER.fullmatch(e["server"]):
        raise KbError(f"models.{name}.server is not a server name")
    if not _valid_model(e["model"]):
        raise KbError(f"models.{name}.model is not a model identifier")
    kind = e.get("kind", "chat")
    if not isinstance(kind, str) or kind not in KINDS:
        raise KbError(f"models.{name}.kind must be one of {', '.join(KINDS)}")
    if kind == "chat":
        for key in ("dimension",) + PREFIXES:
            if key in e:
                raise KbError(f"models.{name}.{key} belongs to an embedding entry")
    else:
        for key in PREFIXES:
            if key in e and not _prefix_ok(e[key]):
                raise KbError(f"models.{name}.{key} must be text of 1 to {MAX_PREFIX} printable characters (a line break is allowed)")
        if not _count(e.get("dimension"), 1, MAX_DIMENSION):
            raise KbError(f"models.{name}.dimension must be a whole number from 1 to {MAX_DIMENSION}")
        for key in ("max_output", "thinking"):
            if key in e:
                raise KbError(f"models.{name}.{key} belongs to a chat entry")
    if "max_output" in e and not _count(e["max_output"], 1, MAX_MAX_OUTPUT):
        raise KbError(f"models.{name}.max_output must be a whole number from 1 to {MAX_MAX_OUTPUT}")
    if "thinking" in e and e["thinking"] not in ("on", "off"):
        raise KbError(f"models.{name}.thinking must be on or off")
    if "timeout" in e and not _count(e["timeout"], 1, MAX_TIMEOUT):
        raise KbError(f"models.{name}.timeout must be a whole number of seconds from 1 to {MAX_TIMEOUT}")
    return dict(e, kind=kind)


REQUIRED_TASKS = ("card-notes", "card", "card-check")  # the kinds of model work that a card needs; the engine attaches no model to any of them
OPTIONAL_TASKS = ("card-more", "theme")  # the kinds that may be left unset: the work is then not done, and that is said. `theme` makes the
# themes of a book (`themeextract`); a card does not need it
TASKS = REQUIRED_TASKS + OPTIONAL_TASKS
EMBED_TASKS = ("card-embed",)  # the kind of work that turns text into vectors: it names an entry of the kind embedding, no card task may


def _settings(cfg, entries):
    """The `tasks` setting of the config: for each kind of work the engine knows, the name of the listed entry that does it. A kind
    of work the engine does not know, or an entry that is not listed, is refused."""
    tasks = cfg.get("tasks", {})
    if not isinstance(tasks, dict):
        raise KbError("the config key tasks is not an object")
    out = {}
    for task, name in tasks.items():
        if task not in TASKS + EMBED_TASKS:
            raise KbError(f"the config sets a model for {textutil.clean(task, 40)!r}, which is not a kind of work the engine knows "
                          f"({', '.join(TASKS + EMBED_TASKS)})")
        if not isinstance(name, str) or name not in entries:
            raise KbError(f"tasks.{task} in the config does not name a listed model")
        if entries[name]["kind"] != ("embedding" if task in EMBED_TASKS else "chat"):
            raise KbError(f"tasks.{task} in the config must name an entry of the kind {'embedding' if task in EMBED_TASKS else 'chat'}")
        out[task] = name
    return out


def registry(cfg):
    """The checked entries of the config, by name. One wrong entry or one wrong task setting refuses the whole registry, so a call
    never runs on a guess about which entry was meant."""
    listed = cfg.get("models", {})
    if not isinstance(listed, dict):
        raise KbError("the config key models is not an object")
    out = {}
    for name, e in listed.items():
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise KbError(f"the config names a model {textutil.clean(name, 40)!r}, which is not a name")
        out[name] = _entry(name, e)
    _settings(cfg, out)
    return out


def choose(cfg, task):
    """`(entry name, reason)` for a kind of work: the entry that the user's `tasks` setting names for it. The engine prefers no
    model and never guesses one, even when only one is listed."""
    entries = registry(cfg)
    if cfg.get("models_on") is not True:
        raise KbError("model work is off: set models_on to true in the config to turn it on")
    if not isinstance(task, str) or task not in TASKS + EMBED_TASKS:
        raise KbError(f"{textutil.clean(task, 40)!r} is not a kind of work the engine knows ({', '.join(TASKS + EMBED_TASKS)})")
    settings = _settings(cfg, entries)
    if task not in settings:
        raise KbError(f"no model is set for the task {task}: set tasks.{task} in the config to the name of a listed model")
    return settings[task], f"set for {task} in the config"


def optional(cfg, task):
    """The entry name that the user's `tasks` setting names for a kind of work that may be left unset, or None when it is not set. A
    name that is not listed, and model work that is off, are refusals, as for `choose`; a kind of work that is needed is not optional."""
    entries = registry(cfg)
    if cfg.get("models_on") is not True:
        raise KbError("model work is off: set models_on to true in the config to turn it on")
    if task not in OPTIONAL_TASKS:
        raise KbError(f"{textutil.clean(task, 40)!r} is not a kind of work that may be left unset ({', '.join(OPTIONAL_TASKS)})")
    return _settings(cfg, entries).get(task)


def listing(cfg):
    """What the registry holds, for the owner to read: the switch, each entry's name and options, and the entry set for each kind
    of work. No server name, no model identifier and no address is listed, and nothing is called."""
    entries = registry(cfg)
    rows = []
    for name in sorted(entries):
        e = entries[name]
        row = {"name": name, "bridge": e["bridge"], "kind": e["kind"]}
        for key in ("max_output", "thinking", "timeout", "dimension"):
            if key in e:
                row[key] = e[key]
        rows.append(row)
    return {"on": cfg.get("models_on") is True, "models": rows, "tasks": dict(sorted(_settings(cfg, entries).items()))}


def _project_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _launcher(path):
    found = path or shutil.which("wb")
    if not found or not os.path.isfile(found) or not os.access(found, os.X_OK):
        raise KbError("the workbench launcher (wb) was not found; model calls need it")
    return found


def _prompt_bytes(prompt):
    if not isinstance(prompt, str):
        raise KbError("the prompt is not text")
    if not prompt.strip():
        raise KbError("the prompt is empty")
    try:
        data = prompt.encode("utf-8")
    except UnicodeEncodeError:
        raise KbError("the prompt holds text that cannot be sent") from None
    if len(data) > MAX_PROMPT:
        raise KbError(f"the prompt is too large: {len(data)} bytes, and the bridge takes {MAX_PROMPT}")
    return data


def _argv(launcher, e, schema=None):
    argv = [launcher, "run", BRIDGE, "ask", "--server", e["server"], "--model", e["model"]]
    if schema:
        argv += ["--schema", schema]
    if "max_output" in e:
        argv += ["--max-output", str(e["max_output"])]
    if "thinking" in e:
        argv += ["--thinking", e["thinking"]]
    if "timeout" in e:
        argv += ["--timeout", str(e["timeout"])]
    return argv


def _kill(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def _start_watchdog(pid, seconds):
    """Start the watchdog of `supervisor.py` for the process group of `pid`, and wait for it to say it is ready. It kills that
    group if the pipe to it closes without the word "done" (the engine died, however), or after `seconds`. Raises `KbError`
    when it cannot be started or does not say ready; the caller then stops the launcher."""
    try:
        dog = subprocess.Popen([_PYTHON, "-I", "-S", SUPERVISOR, str(pid), str(seconds)], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    except (OSError, ValueError, subprocess.SubprocessError):
        raise KbError("the call was stopped: its watchdog could not be started") from None
    try:
        ready, _, _ = select.select([dog.stdout], [], [], WATCHDOG_WAIT)
        line = dog.stdout.readline() if ready else b""
    except (OSError, ValueError):
        line = b""
    finally:
        dog.stdout.close()
    if line != b"ready\n":
        dog.kill()
        dog.wait()
        dog.stdin.close()
        raise KbError("the call was stopped: its watchdog did not start")
    return dog


def _end_watchdog(dog, done=True):
    """Tell the watchdog the launcher is gone and make sure it has ended. With `done` false (the launcher could not be
    stopped), the pipe is closed with no word, so the watchdog kills the launcher's group itself."""
    try:
        if done:
            dog.stdin.write(b"done\n")
        dog.stdin.close()
    except (OSError, ValueError):  # ValueError: already closed, when the cleanup runs a second time
        pass
    try:
        dog.wait(timeout=5)
    except subprocess.TimeoutExpired:
        dog.kill()
        dog.wait()


def _run(argv, data, root, limit):
    """Run the bridge and return (exit code, standard output, standard error, why it was stopped or None). The process and
    whatever it started are killed when it runs past `limit` seconds or prints more than MAX_OUT bytes, and when the engine
    dies once the watchdog is ready (a few milliseconds after the start)."""
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=root,
                                shell=False, close_fds=True, start_new_session=True)
    except OSError as e:
        raise KbError("the launcher could not be started: " + textutil.clean(e.strerror or "error", 100)) from None
    try:
        dog = _start_watchdog(proc.pid, limit + WATCHDOG_MARGIN)
    except BaseException:
        _kill(proc)
        proc.wait()
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            stream.close()
        raise
    try:
        kept = {"out": b"", "err": b""}
        over = threading.Event()

        def feed():
            try:
                proc.stdin.write(data)
            except (OSError, ValueError):
                pass
            finally:
                try:
                    proc.stdin.close()
                except (OSError, ValueError):
                    pass

        def pump(stream, key, cap, stops):
            try:
                got = stream.read(cap + 1)
                kept[key] = got[:cap]
                if len(got) > cap:
                    if stops:
                        over.set()
                    else:
                        while stream.read(65536):
                            pass
            except (OSError, ValueError):
                pass

        threads = [threading.Thread(target=feed), threading.Thread(target=pump, args=(proc.stdout, "out", MAX_OUT, True)),
                   threading.Thread(target=pump, args=(proc.stderr, "err", MAX_ERR, False))]
        for t in threads:
            t.daemon = True
            t.start()
        deadline = time.monotonic() + limit
        why = None
        while True:
            if over.is_set():
                why = "output"
                break
            if not threads[1].is_alive() and not threads[2].is_alive():
                try:
                    proc.wait(timeout=max(0.05, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    why = "time"
                break
            if time.monotonic() >= deadline:
                why = "time"
                break
            threads[1].join(0.02)
        if why:
            _kill(proc)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _kill(proc)
        _end_watchdog(dog, done=proc.returncode is not None)  # first of the cleanup: the sooner, the shorter the window
        for t in threads:
            t.join(2)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            try:
                stream.close()
            except (OSError, ValueError):
                pass
        return proc.returncode, kept["out"], kept["err"], why
    except BaseException:  # nothing it started may outlive a call that fails for a reason of the engine's own
        _kill(proc)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        _end_watchdog(dog, done=proc.returncode is not None)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            try:
                stream.close()
            except (OSError, ValueError):
                pass
        raise


def _no_repeats(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("a repeated key")
        out[key] = value
    return out


def _no_constants(name):
    raise ValueError("not a JSON number")


def _loads(text):
    try:
        return json.loads(text, object_pairs_hook=_no_repeats, parse_constant=_no_constants)
    except (ValueError, RecursionError):
        return None


def _document(out):
    try:
        return _loads(out.decode("utf-8"))
    except UnicodeDecodeError:
        return None


def _shown(value, limit):
    """Text from a program that may be altered, as it is shown in a refusal: cleaned and cut, and not shown at all if it holds the
    words of an untrusted-text marker (the same rule that blanks a title), a fixed text standing in its place."""
    if not textutil.clean(value, limit):
        return ""
    return textutil.title(value, limit) or "[text withheld]"


def _why_failed(doc):
    """The reason a bridge gave for a failure, cleaned and cut. It is text from a program that may be altered, so a reason that holds
    the words of an untrusted-text marker is not shown (the same rule that blanks a title) and a fixed text stands in its place."""
    parts = [_shown(doc.get(key), 150) for key in ("error", "detail") if isinstance(doc.get(key), str)]
    return ": ".join(p for p in parts if p) or "no reason given"


def _usage(value):
    if not isinstance(value, dict):
        raise KbError("the bridge's reply has no usage object")
    out = {}
    for key in ("input_tokens", "output_tokens"):
        if key not in value:
            raise KbError(f"the bridge's usage lacks {key}")
        n = value[key]
        if n is not None and not _count(n, 0, 10 ** 12):
            raise KbError(f"the bridge's usage.{key} is not a count")
        out[key] = n
    return out


def _check(code, out, err):
    doc = _document(out)
    if doc is None:
        if code:
            raise KbError(f"the bridge failed (exit {code}): {_shown(err.decode('utf-8', 'replace'), 200) or 'no message'}")
        raise KbError("the bridge printed text that is not valid JSON")
    if not isinstance(doc, dict):
        raise KbError("the bridge's reply is not a JSON object")
    if type(doc.get("contract")) is not int or doc["contract"] != CONTRACT:
        raise KbError(f"the bridge's reply is not contract version {CONTRACT}")
    if type(doc.get("ok")) is not bool or doc.get("vendor") != VENDOR:
        raise KbError("the bridge's reply does not have the shape of contract version 2")
    if not doc["ok"]:
        raise KbError("the bridge could not answer: " + _why_failed(doc))
    if code:
        raise KbError(f"the bridge reported success but exited with {code}")
    model = doc.get("model")
    if not _valid_model(model):
        raise KbError("the bridge's reply names no valid model")
    reply = doc.get("reply")
    if not isinstance(reply, str) or not reply.strip():
        raise KbError("the bridge's reply holds no text")
    if len(reply.encode("utf-8", "replace")) > MAX_REPLY:
        raise KbError("the bridge's reply is larger than it may be")
    return {"model": model, "reply": reply, "usage": _usage(doc.get("usage"))}


def _schema_path(root, name):
    """The path of a job's schema file relative to the project root, once the file has been checked: a plain name in the
    engine's schema folder, no link anywhere below the root, a regular file of at most MAX_SCHEMA bytes holding one JSON object.
    The bridge checks the same again when it reads the file."""
    if not isinstance(name, str) or not _SCHEMA_NAME.fullmatch(name):
        raise KbError("a schema is named by a plain file name of lower-case letters, digits, _ and - ending in .json")
    parts = SCHEMA_DIR + (name,)
    current = root
    for i, part in enumerate(parts):
        current = os.path.join(current, part)
        try:
            st = os.lstat(current)
        except OSError:
            raise KbError(f"the schema file {name} does not exist in the engine's schema folder") from None
        if stat.S_ISLNK(st.st_mode):
            raise KbError(f"the schema path has a link in it: {part}")
        last = i == len(parts) - 1
        if last and not stat.S_ISREG(st.st_mode) or not last and not stat.S_ISDIR(st.st_mode):
            raise KbError(f"the schema path is not a {'file' if last else 'folder'}: {part}")
        if last and st.st_size > MAX_SCHEMA:
            raise KbError(f"the schema file {name} is larger than {MAX_SCHEMA} bytes")
    try:
        fd = os.open(current, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as f:
            data = f.read(MAX_SCHEMA + 1)
    except OSError:
        raise KbError(f"the schema file {name} cannot be read") from None
    if len(data) > MAX_SCHEMA:
        raise KbError(f"the schema file {name} is larger than {MAX_SCHEMA} bytes")
    try:
        doc = _loads(data.decode("utf-8"))
    except UnicodeDecodeError:
        doc = None
    if not isinstance(doc, dict):
        raise KbError(f"the schema file {name} does not hold one JSON object")
    return "/".join(parts)


def call(cfg, name, prompt, launcher=None, root=None, schema=None):
    """Send `prompt` to the model listed as `name` and return {"model", "reply", "usage"} as the bridge reported them. The
    reply is the model's text, untrusted and not yet checked for the shape a job expects. `schema` is the file name of a
    schema in the engine's schema folder, which the bridge hands to the server so that it shapes its reply."""
    entries = registry(cfg)
    if cfg.get("models_on") is not True:
        raise KbError("model work is off: set models_on to true in the config to turn it on")
    if not isinstance(name, str) or name not in entries:
        raise KbError(f"the model {textutil.clean(name, 40)!r} is not listed in the config")
    if entries[name]["kind"] != "chat":
        raise KbError(f"the model {textutil.clean(name, 40)!r} is an embedding entry; a prompt is sent to a chat entry")
    data = _prompt_bytes(prompt)
    root = root or _project_root()
    relative = _schema_path(root, schema) if schema is not None else None
    argv = _argv(_launcher(launcher), entries[name], relative)
    limit = entries[name].get("timeout", DEFAULT_TIMEOUT) + GRACE
    code, out, err, why = _run(argv, data, root, limit)
    if why == "output":
        raise KbError(f"the bridge printed too much (over {MAX_OUT} bytes); the call was stopped")
    if why == "time":
        raise KbError(f"the call ran past its time limit of {limit} seconds and was stopped")
    return _check(code, out, err)


def _batches(texts, dimension):
    """The texts in order as groups for the bridge: at most MAX_TEXTS in a group, at most BATCH_BYTES as sent, and at most as many as
    their vectors, of `dimension` numbers each, can be read back from one reply (REPLY_BYTES). No group is empty."""
    most = max(1, min(MAX_TEXTS, REPLY_BYTES // (dimension * NUMBER_BYTES)))
    groups, group, size = [], [], 0
    for text in texts:
        need = len(json.dumps(text)) + 2
        if group and (len(group) >= most or size + need > BATCH_BYTES):
            groups.append(group)
            group, size = [], 0
        group.append(text)
        size += need
    if group:
        groups.append(group)
    return groups


def _vector(vector, dimension):
    if not isinstance(vector, list):
        raise KbError("the bridge's reply holds a vector that is not a list of numbers")
    if len(vector) != dimension:
        raise KbError(f"the bridge's reply holds a vector that does not have the dimension of the entry ({dimension})")
    out = []
    for x in vector:
        if type(x) is bool or not isinstance(x, (int, float)) or (isinstance(x, float) and not math.isfinite(x)):
            raise KbError("the bridge's reply holds a vector with something that is not a finite number")
        if abs(x) > MAX_COMPONENT:
            raise KbError("the bridge's reply holds a vector with a number that is out of range")
        out.append(float(x))
    if not any(out):
        raise KbError("the bridge's reply holds a vector of zeros, which has no direction")
    if max(abs(x) for x in out) < MIN_SCALE:
        raise KbError("the bridge's reply holds a vector whose numbers are all too small to compare (out of range)")
    return out


def _check_embed(code, out, err, count, dimension):
    doc = _document(out)
    if doc is None:
        if code:
            raise KbError(f"the bridge failed (exit {code}): {_shown(err.decode('utf-8', 'replace'), 200) or 'no message'}")
        raise KbError("the bridge printed text that is not valid JSON")
    if not isinstance(doc, dict):
        raise KbError("the bridge's reply is not a JSON object")
    if type(doc.get("contract")) is not int or doc["contract"] != EMBED_CONTRACT:
        raise KbError(f"the bridge's reply is not embedding contract version {EMBED_CONTRACT}")
    if type(doc.get("ok")) is not bool or doc.get("vendor") != VENDOR:
        raise KbError(f"the bridge's reply does not have the shape of embedding contract version {EMBED_CONTRACT}")
    if not doc["ok"]:
        raise KbError("the bridge could not answer: " + _why_failed(doc))
    if code:
        raise KbError(f"the bridge reported success but exited with {code}")
    model = doc.get("model")
    if not _valid_model(model):
        raise KbError("the bridge's reply names no valid model")
    if type(doc.get("dimension")) is not int or doc["dimension"] != dimension:
        raise KbError(f"the bridge's reply does not give the dimension of the entry ({dimension})")
    vectors = doc.get("vectors")
    if not isinstance(vectors, list) or len(vectors) != count:
        raise KbError(f"the bridge's reply does not hold {count} vectors for the {count} texts")
    return model, [_vector(v, dimension) for v in vectors]


def embed(cfg, name, texts, launcher=None, root=None, kind="document"):
    """Turn `texts` into vectors with the embedding entry listed as `name` and return {"model", "dimension", "vectors"}: the model as
    the bridge reported it, the dimension of the entry, and one vector of floats for each text, in order. The texts go to the bridge
    in as many calls as it needs (`_batches`). Every reply is checked: the same model each time, the number of vectors, the dimension
    of the entry for each, finite numbers of a sensible size, no vector of zeros. One reply that is wrong refuses the whole call and
    gives no vectors. The vectors are model output and untrusted data; this only checks their shape. `kind` says what the texts are,
    `"document"` (a stored text, the default) or `"query"`: the entry's `document_prefix` or `query_prefix`, if it has one, is put in
    front of each text before its size is checked and it is sent, so that the vector is made from the text with its prefix; an entry
    with no prefix for the kind sends the text as it is."""
    if not isinstance(kind, str) or kind not in EMBED_KINDS:
        raise KbError(f"the kind of text to embed is {' or '.join(EMBED_KINDS)}")
    entries = registry(cfg)
    if cfg.get("models_on") is not True:
        raise KbError("model work is off: set models_on to true in the config to turn it on")
    if not isinstance(name, str) or name not in entries:
        raise KbError(f"the model {textutil.clean(name, 40)!r} is not listed in the config")
    entry = entries[name]
    if entry["kind"] != "embedding":
        raise KbError(f"the model {textutil.clean(name, 40)!r} is a chat entry; texts are embedded with an embedding entry")
    if not isinstance(texts, list) or not texts or len(texts) > MAX_EMBED_TEXTS:
        raise KbError(f"the texts to embed are a list of 1 to {MAX_EMBED_TEXTS} texts")
    prefix = entry.get(f"{kind}_prefix", "")
    sent = []
    for n, text in enumerate(texts, start=1):
        if not isinstance(text, str) or not text.strip():
            raise KbError(f"text {n} to embed is not text with a character that is not white space")
        whole = prefix + text
        try:
            size = len(whole.encode("utf-8"))
        except UnicodeEncodeError:
            raise KbError(f"text {n} to embed holds a character that cannot be sent") from None
        if size > MAX_TEXT:
            raise KbError(f"text {n} to embed is larger than the bridge takes ({MAX_TEXT} bytes{', with its prefix' if prefix else ''})")
        sent.append(whole)
    texts = sent
    if len(texts) * entry["dimension"] > MAX_EMBED_NUMBERS:
        raise KbError(f"the vectors of {len(texts)} texts of {entry['dimension']} numbers would not fit in memory; embed fewer texts at a time")
    root = root or _project_root()
    argv = [_launcher(launcher), "run", BRIDGE, "embed", "--server", entry["server"], "--model", entry["model"]]
    if "timeout" in entry:
        argv += ["--timeout", str(entry["timeout"])]
    limit = entry.get("timeout", DEFAULT_TIMEOUT) + GRACE
    vectors, model = [], None
    for group in _batches(texts, entry["dimension"]):
        data = json.dumps({"texts": group}).encode("ascii")
        code, out, err, why = _run(argv, data, root, limit)
        if why == "output":
            raise KbError(f"the bridge printed too much (over {MAX_OUT} bytes); the call was stopped")
        if why == "time":
            raise KbError(f"the call ran past its time limit of {limit} seconds and was stopped")
        got_model, got = _check_embed(code, out, err, len(group), entry["dimension"])
        if model is not None and got_model != model:
            raise KbError("the model that the bridge reported changed between the batches of one call")
        model = got_model
        vectors += got
    return {"model": model, "dimension": entry["dimension"], "vectors": vectors}


_TYPE_KEYS = {"string": {"type", "max", "optional"}, "strings": {"type", "min_items", "max_items", "max", "optional"},
              "integer": {"type", "low", "high", "optional"}, "boolean": {"type", "optional"},
              "items": {"type", "min_items", "max_items", "max", "support_max", "optional"}}
_NEEDED = {"string": ("max",), "strings": ("max_items", "max"), "integer": ("low", "high"), "boolean": (),
           "items": ("max_items", "max", "support_max")}


def _spec(field, spec):
    if not isinstance(field, str) or not _FIELD.fullmatch(field):
        raise KbError(f"the shape has a key that is not a plain name: {textutil.clean(field, 40)!r}")
    if not isinstance(spec, dict) or spec.get("type") not in _TYPE_KEYS:
        raise KbError(f"the shape of {field} is not one of {', '.join(sorted(_TYPE_KEYS))}")
    kind = spec["type"]
    extra = set(spec) - _TYPE_KEYS[kind]
    if extra:
        raise KbError(f"the shape of {field} has a key it does not know: {sorted(extra)[0]}")
    for key in _NEEDED[kind]:
        if key not in spec:
            raise KbError(f"the shape of {field} lacks {key}")
    if "optional" in spec and type(spec["optional"]) is not bool:
        raise KbError(f"the shape of {field}: optional is true or false")
    if "max" in spec and not _count(spec["max"], 1, MAX_REPLY):
        raise KbError(f"the shape of {field}: max is a whole number from 1 to {MAX_REPLY}")
    if "support_max" in spec and not _count(spec["support_max"], 1, MAX_REPLY):
        raise KbError(f"the shape of {field}: support_max is a whole number from 1 to {MAX_REPLY}")
    if "max_items" in spec and not _count(spec["max_items"], 0, _LIMIT):
        raise KbError(f"the shape of {field}: max_items is a whole number from 0 to {_LIMIT}")
    if "min_items" in spec and not _count(spec["min_items"], 0, spec["max_items"]):
        raise KbError(f"the shape of {field}: min_items is a whole number from 0 to max_items")
    if kind == "integer" and not (_count(spec["low"], -_LIMIT, _LIMIT) and _count(spec["high"], -_LIMIT, _LIMIT)
                                  and spec["low"] <= spec["high"]):
        raise KbError(f"the shape of {field}: low and high are whole numbers with low not above high")
    return dict(spec)


def _stored_shape(shape):
    """The shape of the values a reply gives: the same as the shape of the reply, except that a list of `items` is two lists of strings,
    the texts under its name and the supports under its name with `_support`. A saved answer is checked against this shape."""
    stored = {}
    for field, spec in shape.items():
        if spec["type"] != "items":
            stored[field] = dict(spec)
            continue
        if f"{field}_support" in shape:
            raise KbError(f"the shape has {field}_support, which the items of {field} already give")
        extra = {k: spec[k] for k in ("min_items", "optional") if k in spec}
        stored[field] = {"type": "strings", "max_items": spec["max_items"], "max": spec["max"], **extra}
        stored[f"{field}_support"] = {"type": "strings", "max_items": spec["max_items"], "max": spec["support_max"], **extra}
    return stored


class Job:
    """What a kind of model work expects: a name, the version of its prompt, the shape of the JSON object it asks for, and
    optionally the file name of a schema in the engine's schema folder, and optionally a `check`: a function that is given the checked
    values and raises a KbError to refuse an answer whose parts do not fit together (lists that must be the same length, say). A
    refusal by the check is a refused answer like any other: it carries the answer, so that it can be kept aside. It is checked when
    it is made."""

    def __init__(self, name, prompt_version, shape, schema=None, check=None):
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise KbError("a job's name is lower-case letters, digits, _ and -, starting with a letter or digit")
        if not isinstance(prompt_version, str) or not _VERSION.fullmatch(prompt_version):
            raise KbError("a prompt version is up to 40 letters, digits, . _ and -, starting with a letter or digit")
        if not isinstance(shape, dict) or not shape:
            raise KbError("a job's shape is an object with at least one key")
        if schema is not None and (not isinstance(schema, str) or not _SCHEMA_NAME.fullmatch(schema)):
            raise KbError("a schema is named by a plain file name ending in .json")
        if check is not None and not callable(check):
            raise KbError("a job's check is a function")
        self.name = name
        self.prompt_version = prompt_version
        self.shape = {field: _spec(field, spec) for field, spec in shape.items()}
        self.stored_shape = _stored_shape(self.shape)
        self.schema = schema
        self.check = check


def status(cfg, launcher=None):
    """The listing of the registry, with whether the launcher is found. It makes no call."""
    out = listing(cfg)
    try:
        _launcher(launcher)
        out["launcher_found"] = True
    except KbError:
        out["launcher_found"] = False
    return out


def _text(field, value, spec):
    if not isinstance(value, str):
        raise KbError(f"the answer's {field} is not text")
    if len(value) > spec["max"]:
        raise KbError(f"the answer's {field} is longer than the {spec['max']} characters allowed")
    kept = textutil.clean(value, spec["max"])
    if not kept:
        raise KbError(f"the answer's {field} holds no text")
    return kept


def _value(field, value, spec):
    kind = spec["type"]
    if kind == "string":
        return _text(field, value, spec)
    if kind == "strings":
        if not isinstance(value, list):
            raise KbError(f"the answer's {field} is not a list")
        if len(value) > spec["max_items"]:
            raise KbError(f"the answer's {field} has more than the {spec['max_items']} items allowed")
        if len(value) < spec.get("min_items", 0):
            raise KbError(f"the answer's {field} has fewer than the {spec['min_items']} items required")
        return [_text(field, item, spec) for item in value]
    if kind == "integer":
        if type(value) is not int or not spec["low"] <= value <= spec["high"]:
            raise KbError(f"the answer's {field} is not a whole number from {spec['low']} to {spec['high']}")
        return value
    if type(value) is not bool:
        raise KbError(f"the answer's {field} is not true or false")
    return value


def _items(field, value, spec):
    """The texts and the supports of a list of items, each an object with exactly a `text` and a `support`, in the same order: the two
    lists are as long as each other because each item holds both. A refusal names the field and the kind of fault."""
    if not isinstance(value, list):
        raise KbError(f"the answer's {field} is not a list")
    if len(value) > spec["max_items"]:
        raise KbError(f"the answer's {field} has more than the {spec['max_items']} items allowed")
    if len(value) < spec.get("min_items", 0):
        raise KbError(f"the answer's {field} has fewer than the {spec['min_items']} items required")
    texts, supports = [], []
    for item in value:
        if not isinstance(item, dict):
            raise KbError(f"the answer's {field} has an item that is not an object with a text and a support")
        for key in item:
            if key not in ("text", "support"):
                raise KbError(f"the answer's {field} has an item with a key that was not asked for: {textutil.literal(key, 40)}")
        for key in ("text", "support"):
            if key not in item:
                raise KbError(f"the answer's {field} has an item with no {key}")
        texts.append(_text(field, item["text"], {"max": spec["max"]}))
        supports.append(_text(f"{field} support", item["support"], {"max": spec["support_max"]}))
    return texts, supports


def _check_answer(text, shape):
    """The values of the JSON object in `text`, if it has exactly the shape `shape` asks for. Text is cleaned, a value is refused
    and not cut when it is too long (checked before cleaning), and a refusal names the key and the kind of fault and quotes no
    value. The values stay untrusted data."""
    doc = _loads(text)
    if not isinstance(doc, dict):
        raise KbError("the answer is not one JSON object")
    for key in doc:
        if key not in shape:
            raise KbError(f"the answer has a key that was not asked for: {textutil.literal(key, 40)}")   # as written, not cleaned: a key must not read as a known one
    values = {}
    for field, spec in shape.items():
        if field not in doc:
            if spec.get("optional"):
                continue
            raise KbError(f"the answer lacks {field}")
        if spec["type"] == "items":   # the values are the two lists that the rest of the program reads: the texts, and their supports
            values[field], values[f"{field}_support"] = _items(field, doc[field], spec)
        else:
            values[field] = _value(field, doc[field], spec)
    return values


class AnswerRefused(KbError):
    """A model answered and the answer was refused for its shape. The refusal carries the answer (`reply`, untrusted text), the
    record of the call (`record`) and the name of the job (`job`), so that a caller can keep the answer aside for the owner to read.
    A call that failed, or a reply that was not of the bridge's form, has no answer and raises a plain `KbError`."""

    def __init__(self, message, reply, record, job):
        super().__init__(message)
        self.reply, self.record, self.job = reply, record, job


def run_job(cfg, name, prompt, job, launcher=None, root=None):
    """Make one call for `job` and return {"untrusted": True, "values": ..., "record": ...}: the checked values, and the record of
    how they were made (the model the server reported, the registry name, the prompt version, the date and the token counts)."""
    got = call(cfg, name, prompt, launcher=launcher, root=root, schema=job.schema)
    record = {"model": got["model"], "registry": name, "prompt_version": job.prompt_version,
              "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "input_tokens": got["usage"]["input_tokens"], "output_tokens": got["usage"]["output_tokens"]}
    try:
        values = _check_answer(got["reply"], job.shape)
        if job.check is not None:
            job.check(values)
    except KbError as e:
        raise AnswerRefused(str(e), got["reply"], record, job.name) from None
    return {"untrusted": True, "values": values, "record": record}


# the job of the `model-try` command: one short answer, with the schema file that goes with it
TRY_JOB = Job("model-try", "v1", {"answer": {"type": "string", "max": 2000}}, schema="model-try.json")
