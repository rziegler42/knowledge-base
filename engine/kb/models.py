"""Calls to a model through the workbench's Ollama bridge.

The owner lists models in the config (`models`, named entries) and switches model work on (`models_on`). A call starts
`wb run ask-ollama ask` as a separate program, with an argument list and no shell, sends the prompt on standard input and
reads one JSON object back. Nothing here chooses between models, retries or batches. What comes back is model output: it is
untrusted data, and this module only checks that it has the bridge's shape. The server's address is in the workbench's own
endpoint file; the registry holds a server name only."""
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time

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


def _argv(launcher, e):
    argv = [launcher, "run", BRIDGE, "ask", "--server", e["server"], "--model", e["model"]]
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


def _document(out):
    try:
        return json.loads(out.decode("utf-8"), object_pairs_hook=_no_repeats, parse_constant=_no_constants)
    except (ValueError, RecursionError):
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


def call(cfg, name, prompt, launcher=None, root=None):
    """Send `prompt` to the model listed as `name` and return {"model", "reply", "usage"} as the bridge reported them. The
    reply is the model's text, untrusted and not yet checked for the shape a job expects."""
    entries = registry(cfg)
    if cfg.get("models_on") is not True:
        raise KbError("model work is off: set models_on to true in the config to turn it on")
    if not isinstance(name, str) or name not in entries:
        raise KbError(f"the model {textutil.clean(name, 40)!r} is not listed in the config")
    data = _prompt_bytes(prompt)
    argv = _argv(_launcher(launcher), entries[name])
    limit = entries[name].get("timeout", DEFAULT_TIMEOUT) + GRACE
    code, out, err, why = _run(argv, data, root or _project_root(), limit)
    if why == "output":
        raise KbError(f"the bridge printed too much (over {MAX_OUT} bytes); the call was stopped")
    if why == "time":
        raise KbError(f"the call ran past its time limit of {limit} seconds and was stopped")
    return _check(code, out, err)
