"""The approved tools: the only programs the engine will run on captured files.

A tool that parses untrusted files is approved once, by the owner, by name and exact version, and the list lives in the
owner-only config (`approved_tools`, under `~/.config/knowledge-base/`). An agent cannot change it: the config is read
only when it is a plain file owned by the user with mode 600, and nothing in the engine writes this list.

An entry says exactly what may run and what it may touch:

    name, version      the tool and the exact version that was approved
    command            the program (its real path, never a symlink) and its arguments; "{input}" and "{output}" are
                       replaced by the folders the tool is given
    executable         the same program, as the sandbox must be told
    pinned             the sha256 of the program and of every script it runs; a changed file is refused
    reads              folders the tool may read besides its input (its own runtime)
    formats            the kinds of file it may be run on
    timeout, max_output   the limits it runs within

Run `python3 -m kb describe-tool` to print the entry for the built-in scan tool and review it before pasting it into the
config. The engine never approves anything itself."""
import hashlib
import os
import re
import stat
import sys
import unicodedata

from . import KbError, config

KNOWN_FORMATS = ("pdf", "html")
_NAME = re.compile(r"[a-z][a-z0-9-]{0,40}")
_VERSION = re.compile(r"[0-9A-Za-z._-]{1,40}")
_SHA = re.compile(r"[0-9a-f]{64}")
_FIELDS = {"name", "version", "command", "executable", "pinned", "reads", "formats", "timeout", "max_output"}
MAX_COMMAND = 40


def safe_path(path, what="path"):
    """An absolute, normalised path with nothing in it that could break out of a quoted profile string."""
    if not isinstance(path, str) or not path.startswith("/"):
        raise KbError(f"the {what} must be an absolute path: {path!r}")
    if any(ord(c) < 32 or ord(c) == 127 or c in '"\\' for c in path):
        raise KbError(f"the {what} has a character that is not allowed in a path here: {path!r}")
    if os.path.normpath(path) != path:
        raise KbError(f"the {what} is not in its normal form (no '..', '.', '//' or trailing '/'): {path!r}")
    return path


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_entry(entry):
    """Check an entry from the config, or one just described, and return a clean copy. Refuses on any doubt."""
    if not isinstance(entry, dict):
        raise KbError("an approved tool must be a JSON object")
    unknown = set(entry) - _FIELDS
    if unknown:
        raise KbError(f"an approved tool has unknown fields: {sorted(unknown)}")
    missing = _FIELDS - set(entry)
    if missing:
        raise KbError(f"an approved tool is missing fields: {sorted(missing)}")
    name, version = entry["name"], entry["version"]
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise KbError(f"not a tool name: {name!r}")
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise KbError(f"not a tool version: {version!r}")
    command = entry["command"]
    if not isinstance(command, list) or not 1 <= len(command) <= MAX_COMMAND or not all(
            isinstance(a, str) and "\0" not in a for a in command):
        raise KbError("the command must be a list of text, starting with the program")
    exe = safe_path(command[0], "program")
    if os.path.realpath(exe) != exe:
        raise KbError(f"give the program's real path, not a link to it: {exe}")
    if entry["executable"] != exe:
        raise KbError("the executable must be the first word of the command")
    formats = entry["formats"]
    if not isinstance(formats, list) or not formats or not all(f in KNOWN_FORMATS for f in formats):
        raise KbError(f"formats must be a non-empty list drawn from {list(KNOWN_FORMATS)}")
    for key, low, high in (("timeout", 1, 600), ("max_output", 1, 100_000_000)):
        v = entry[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not low <= v <= high:
            raise KbError(f"{key} must be a number from {low} to {high}")
    reads = entry["reads"]
    if not isinstance(reads, list):
        raise KbError("reads must be a list of folders")
    for r in reads:
        safe_path(r, "readable folder")
    pinned = entry["pinned"]
    if not isinstance(pinned, dict) or exe not in pinned:
        raise KbError("pinned must map files to their sha256, and include the program")
    for path, digest in pinned.items():
        safe_path(path, "pinned file")
        if not isinstance(digest, str) or not _SHA.fullmatch(digest):
            raise KbError(f"not a sha256: {digest!r}")
    return {"name": name, "version": version, "command": list(command), "executable": exe, "pinned": dict(pinned),
            "reads": list(reads), "formats": list(formats), "timeout": entry["timeout"], "max_output": entry["max_output"]}


def approved_tools(cfg=None):
    """The entries of the owner's approved list. A config with no list has an empty one."""
    cfg = config.load() if cfg is None else cfg
    listed = cfg.get("approved_tools", [])
    if not isinstance(listed, list):
        raise KbError("approved_tools in the config must be a list")
    tools, seen = [], set()
    for raw in listed:
        entry = validate_entry(raw)
        key = (entry["name"], entry["version"])
        if key in seen:
            raise KbError(f"{entry['name']} {entry['version']} is on the approved list twice")
        seen.add(key)
        tools.append(entry)
    return tools


def find(name, version, cfg=None):
    for entry in approved_tools(cfg):
        if entry["name"] == name and entry["version"] == version:
            return entry
    raise KbError(f"{name} {version} is not on the approved list")


def find_for(name, fmt, cfg=None):
    """The first entry of the approved list for the tool of this name that handles this kind of file. The list is the
    owner's, and its order is the owner's choice when a tool is approved in more than one version."""
    for entry in approved_tools(cfg):
        if entry["name"] == name and fmt in entry["formats"]:
            return entry
    raise KbError(f"{name} is not on the approved list for {fmt} files")


def check_pins(entry):
    """Refuse a tool if the program or any script it runs is not exactly the file that was approved."""
    for path, digest in entry["pinned"].items():
        try:
            st = os.lstat(path)
        except OSError:
            raise KbError(f"{path} is missing; {entry['name']} {entry['version']} cannot run") from None
        if not stat.S_ISREG(st.st_mode):  # lstat: a symlink is not a regular file
            raise KbError(f"{path} is not a plain file")
        if sha256_file(path) != digest:
            raise KbError(f"{path} has changed since it was approved; approve {entry['name']} again to use it")


def _canonical(path):
    """A path in a form that compares equal however it is spelled: links resolved, and letter case and Unicode form
    folded, because the default macOS volume ignores both (the sandbox would treat /Users/x and /USERS/X as one folder)."""
    folded = unicodedata.normalize("NFC", os.path.realpath(path)).casefold()
    # the data volume is also reachable as /System/Volumes/Data/..., which names the same files as /...
    if folded == "/system/volumes/data":
        return "/"
    if folded.startswith("/system/volumes/data/"):
        return folded[len("/system/volumes/data"):]
    return folded


def check_reads(entry, cfg):
    """A tool may not be given a readable folder or a pinned file that holds, or sits inside, the config or the library,
    or that is the disk or the home folder: it would let the tool read what the sandbox exists to keep from it. The
    program and every pinned file are checked as well as the readable folders, because the sandbox lets the tool read them."""
    guarded = [_canonical(config.config_dir()), _canonical(cfg["bulk_root"]), _canonical(cfg["index_root"])]
    home = _canonical(os.path.expanduser("~"))
    covers = lambda outer, inner: inner == outer or inner.startswith(outer.rstrip("/") + "/")
    for kind, paths in (("readable folder", entry["reads"]), ("pinned file", list(entry["pinned"]))):
        for path in paths:
            real = _canonical(path)
            if real == "/" or any(covers(real, g) or covers(g, real) for g in guarded) or covers(real, home):
                raise KbError(f"{path} may not be readable by a tool ({kind}): it covers or lies inside the config, the "
                              "library, your home folder or the whole disk")


def python_runtime():
    """The interpreter to run Python tools with, and the folder it needs to read. A framework build keeps the real
    program inside Python.app, and the launcher at sys.executable starts that by a second exec, which the sandbox
    refuses; so the real program is the one to approve."""
    prefix = os.path.realpath(sys.base_prefix)
    inner = os.path.join(prefix, "Resources", "Python.app", "Contents", "MacOS", "Python")
    return (inner if os.path.isfile(inner) else os.path.realpath(sys.executable)), prefix


def describe(name, version, command, reads, formats, timeout=30, max_output=1_000_000, pin=()):
    """Build an entry for the approved list, hashing the program and every file in `pin` (scripts the program runs)."""
    if not command or not isinstance(command[0], str) or os.path.realpath(command[0]) != command[0]:
        raise KbError(f"give the program's real path, not a link to it: {command[0] if command else None}")
    pinned = {}
    for path in (command[0], *pin):
        safe_path(path, "pinned file")
        if not os.path.isfile(path) or os.path.islink(path):
            raise KbError(f"{path} is not a plain file")
        pinned[path] = sha256_file(path)
    return validate_entry({"name": name, "version": version, "command": list(command), "executable": command[0],
                           "pinned": pinned, "reads": list(reads), "formats": list(formats), "timeout": timeout,
                           "max_output": max_output})


SCAN_VERSION = "0.0.3"  # the scan tool's own label: raised, with a line in the history of ToolVersionTest, whenever scan_tool.py changes


def builtin_scan_entry():
    """The entry for the scan tool that ships with the engine, run by the interpreter that runs the engine."""
    exe, prefix = python_runtime()
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scan_tool.py")
    # -I: no user site, no environment variables, no script directory on the path. -S: no `site` module at all, so
    # nothing in the runtime folder (a .pth file, a sitecustomize) runs at start-up; the scan needs only the standard library.
    return describe("kb-scan", SCAN_VERSION, [exe, "-I", "-S", script, "{input}", "{output}"], reads=[prefix],
                    formats=list(KNOWN_FORMATS), timeout=60, max_output=1_000_000, pin=[script])
