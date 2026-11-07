"""Calls to a model through the workbench's Ollama bridge.

The owner lists models in the config (`models`, named entries) and switches model work on (`models_on`). A call starts
`wb run ask-ollama ask` as a separate program, with an argument list and no shell, sends the prompt on standard input and
reads one JSON object back. Nothing here chooses between models, retries or batches. What comes back is model output: it is
untrusted data, and this module only checks that it has the bridge's shape. The server's address is in the workbench's own
endpoint file; the registry holds a server name only."""
import json
import os
import re
import stat
import shutil
import signal
import subprocess
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
CONTRACT = 2
VENDOR = "ollama"
BRIDGE = "ask-ollama"
_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
_SERVER = _NAME
_SEGMENT = r"[A-Za-z0-9][A-Za-z0-9._:-]*"
_MODEL = re.compile(_SEGMENT + "(?:/" + _SEGMENT + ")*")  # the bridge's rule for a model name: segments joined by a slash
_KEYS = ("bridge", "server", "model", "max_output", "thinking", "timeout")
_REQUIRED = ("bridge", "server", "model")
MAX_MAX_OUTPUT = 200000
MAX_TIMEOUT = 3600  # the bridge refuses a longer one
MAX_MODEL = 128
MAX_SCHEMA = 65536  # the bridge reads a schema file of at most this many bytes
SCHEMA_DIR = ("engine", "kb", "schemas")  # where a job's schema file is kept, relative to the project root
_SCHEMA_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\.json")
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}")
_FIELD = re.compile(r"[a-z][a-z0-9_]{0,39}")
_LIMIT = 1_000_000


def _count(value, low, high):
    return type(value) is int and low <= value <= high


def _valid_model(value):
    return isinstance(value, str) and 0 < len(value) <= MAX_MODEL and ".." not in value and _MODEL.fullmatch(value) is not None


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
    if "max_output" in e and not _count(e["max_output"], 1, MAX_MAX_OUTPUT):
        raise KbError(f"models.{name}.max_output must be a whole number from 1 to {MAX_MAX_OUTPUT}")
    if "thinking" in e and e["thinking"] not in ("on", "off"):
        raise KbError(f"models.{name}.thinking must be on or off")
    if "timeout" in e and not _count(e["timeout"], 1, MAX_TIMEOUT):
        raise KbError(f"models.{name}.timeout must be a whole number of seconds from 1 to {MAX_TIMEOUT}")
    return dict(e)


def registry(cfg):
    """The checked entries of the config, by name. One wrong entry refuses the whole registry, so a call never runs on a guess
    about which entry was meant."""
    listed = cfg.get("models", {})
    if not isinstance(listed, dict):
        raise KbError("the config key models is not an object")
    out = {}
    for name, e in listed.items():
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise KbError(f"the config names a model {textutil.clean(name, 40)!r}, which is not a name")
        out[name] = _entry(name, e)
    return out


def listing(cfg):
    """What the registry holds, for the owner to read: the switch and each entry's name and options. No server name, no model
    identifier and no address is listed, and nothing is called."""
    entries = registry(cfg)
    rows = []
    for name in sorted(entries):
        e = entries[name]
        row = {"name": name, "bridge": e["bridge"]}
        for key in ("max_output", "thinking", "timeout"):
            if key in e:
                row[key] = e[key]
        rows.append(row)
    return {"on": cfg.get("models_on") is True, "models": rows}


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


def _run(argv, data, root, limit):
    """Run the bridge and return (exit code, standard output, standard error, why it was stopped or None). The process and
    whatever it started are killed when it runs past `limit` seconds or prints more than MAX_OUT bytes."""
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=root,
                                shell=False, close_fds=True, start_new_session=True)
    except OSError as e:
        raise KbError("the launcher could not be started: " + textutil.clean(e.strerror or "error", 100)) from None
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
    for t in threads:
        t.join(2)
    for stream in (proc.stdin, proc.stdout, proc.stderr):
        try:
            stream.close()
        except (OSError, ValueError):
            pass
    return proc.returncode, kept["out"], kept["err"], why


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


def _why_failed(doc):
    parts = [textutil.clean(doc.get(k), 150) for k in ("error", "detail") if isinstance(doc.get(k), str)]
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
            raise KbError(f"the bridge failed (exit {code}): {textutil.clean(err.decode('utf-8', 'replace'), 200) or 'no message'}")
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


_TYPE_KEYS = {"string": {"type", "max", "optional"}, "strings": {"type", "max_items", "max", "optional"},
              "integer": {"type", "low", "high", "optional"}, "boolean": {"type", "optional"}}
_NEEDED = {"string": ("max",), "strings": ("max_items", "max"), "integer": ("low", "high"), "boolean": ()}


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
    if "max_items" in spec and not _count(spec["max_items"], 0, _LIMIT):
        raise KbError(f"the shape of {field}: max_items is a whole number from 0 to {_LIMIT}")
    if kind == "integer" and not (_count(spec["low"], -_LIMIT, _LIMIT) and _count(spec["high"], -_LIMIT, _LIMIT)
                                  and spec["low"] <= spec["high"]):
        raise KbError(f"the shape of {field}: low and high are whole numbers with low not above high")
    return dict(spec)


class Job:
    """What a kind of model work expects: a name, the version of its prompt, the shape of the JSON object it asks for, and
    optionally the file name of a schema in the engine's schema folder. It is checked when it is made."""

    def __init__(self, name, prompt_version, shape, schema=None):
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise KbError("a job's name is lower-case letters, digits, _ and -, starting with a letter or digit")
        if not isinstance(prompt_version, str) or not _VERSION.fullmatch(prompt_version):
            raise KbError("a prompt version is up to 40 letters, digits, . _ and -, starting with a letter or digit")
        if not isinstance(shape, dict) or not shape:
            raise KbError("a job's shape is an object with at least one key")
        if schema is not None and (not isinstance(schema, str) or not _SCHEMA_NAME.fullmatch(schema)):
            raise KbError("a schema is named by a plain file name ending in .json")
        self.name = name
        self.prompt_version = prompt_version
        self.shape = {field: _spec(field, spec) for field, spec in shape.items()}
        self.schema = schema


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
        return [_text(field, item, spec) for item in value]
    if kind == "integer":
        if type(value) is not int or not spec["low"] <= value <= spec["high"]:
            raise KbError(f"the answer's {field} is not a whole number from {spec['low']} to {spec['high']}")
        return value
    if type(value) is not bool:
        raise KbError(f"the answer's {field} is not true or false")
    return value


def _check_answer(text, shape):
    """The values of the JSON object in `text`, if it has exactly the shape `shape` asks for. Text is cleaned, a value is refused
    and not cut when it is too long (checked before cleaning), and a refusal names the key and the kind of fault and quotes no
    value. The values stay untrusted data."""
    doc = _loads(text)
    if not isinstance(doc, dict):
        raise KbError("the answer is not one JSON object")
    for key in doc:
        if key not in shape:
            raise KbError(f"the answer has a key that was not asked for: {textutil.clean(key, 40)!r}")
    values = {}
    for field, spec in shape.items():
        if field not in doc:
            if spec.get("optional"):
                continue
            raise KbError(f"the answer lacks {field}")
        values[field] = _value(field, doc[field], spec)
    return values


def run_job(cfg, name, prompt, job, launcher=None, root=None):
    """Make one call for `job` and return {"untrusted": True, "values": ..., "record": ...}: the checked values, and the record of
    how they were made (the model the server reported, the registry name, the prompt version, the date and the token counts)."""
    got = call(cfg, name, prompt, launcher=launcher, root=root, schema=job.schema)
    values = _check_answer(got["reply"], job.shape)
    record = {"model": got["model"], "registry": name, "prompt_version": job.prompt_version,
              "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "input_tokens": got["usage"]["input_tokens"], "output_tokens": got["usage"]["output_tokens"]}
    return {"untrusted": True, "values": values, "record": record}
