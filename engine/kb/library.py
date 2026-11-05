"""Setting up a library and guarding writes to it.

A library has two roots: a bulk root for books (it holds a marker file with the library id) and an
index root for the search index. The owner-only config, outside both roots, records them with the
library id, the device of the bulk root and whether the bulk root may be on the main disk."""
import json
import os
import secrets

from . import KbError
from . import config

FORMAT = 1
MARKER = ".kb-library"
NOTICE = ("Notice: rights and legality are your responsibility as the owner of this library. "
          "This tool does not judge what you add to it or how you use it.")


def _check_path(path, what):
    """An absolute path with no symlink in it. Components that do not exist yet are fine."""
    if not isinstance(path, str) or not path or "\0" in path:
        raise KbError(f"the {what} must be a path")
    if not os.path.isabs(path):
        raise KbError(f"the {what} must be an absolute path, not {path!r}")
    norm = os.path.normpath(path)
    cur = os.sep
    for part in [p for p in norm.split(os.sep) if p]:
        cur = os.path.join(cur, part)
        try:
            if os.path.islink(cur):
                raise KbError(f"the {what} has a symlink in its path: {cur}")
        except OSError:
            break
        if not os.path.lexists(cur):
            break
    return norm


def _device_of_existing(path):
    """The device a path lives on: its own if it exists, else the nearest existing parent's."""
    cur = path
    while not os.path.lexists(cur):
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return os.stat(cur).st_dev


def _main_device(main_device):
    return main_device if main_device is not None else os.stat(os.path.expanduser("~")).st_dev


def _read_marker(bulk):
    path = os.path.join(bulk, MARKER)
    try:
        with open(path) as f:
            marker = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {}
    return marker if isinstance(marker, dict) else {}


def setup(bulk_root, index_root, allow_main_disk=False, main_device=None):
    """Create a working empty library and return its id. Repeating it with the same roots is a no-op.

    `main_device` is the device number of the main disk; it is a parameter so that the tests do not
    depend on how the machine's disks are laid out."""
    bulk = _check_path(bulk_root, "bulk root")
    index = _check_path(index_root, "index root")
    if bulk.casefold() == index.casefold():
        # also folds case, because the default macOS filesystem treats /x/Bulk and /x/bulk as one folder
        raise KbError("the bulk root and the index root are the same folder")

    if config.exists():
        cfg = config.load()
        if cfg.get("bulk_root") == bulk and cfg.get("index_root") == index:
            marker = _read_marker(bulk)
            if not marker or marker.get("library_id") != cfg.get("library_id"):
                raise KbError("the library is already set up, but its marker file is missing or does not match")
            return cfg["library_id"]
        raise KbError(f"a library is already set up (config at {config.config_path()}) with other roots; "
                      "setup does not move a library")

    if _read_marker(bulk) is not None:
        raise KbError(f"the bulk root already holds another library's marker: {os.path.join(bulk, MARKER)}")

    if not allow_main_disk and _device_of_existing(bulk) == _main_device(main_device):
        raise KbError("the bulk root is on the main disk; setup allows that only when the owner passes "
                      "--allow-main-disk")

    library_id = secrets.token_hex(16)
    written = []
    try:
        os.makedirs(bulk, exist_ok=True)
        os.makedirs(index, exist_ok=True)
        marker_path = os.path.join(bulk, MARKER)
        config.write_json_atomic(marker_path, {"format": FORMAT, "library_id": library_id}, 0o644)
        written.append(marker_path)
        format_path = os.path.join(index, "format.json")
        config.write_json_atomic(format_path, {"format": FORMAT}, 0o644)
        written.append(format_path)
        config.save({
            "format": FORMAT,
            "library_id": library_id,
            "bulk_root": bulk,
            "index_root": index,
            "bulk_device": os.stat(bulk).st_dev,
            "allow_main_disk": bool(allow_main_disk),
        })
    except BaseException:
        # the config is written last; if anything fails, take back the files this call wrote, so the next
        # setup does not meet its own marker and refuse it as another library's
        for p in written:
            if os.path.lexists(p):
                os.remove(p)
        raise
    return library_id


def check_writable(device_of=None, main_device=None):
    """Return the config if writing to the library is safe, else raise KbError with the reason.

    Run before any write: the bulk root must be reachable with its marker, on the device it was on at
    setup, and off the main disk unless the owner allowed that. This stops a write to an unmounted
    volume from quietly creating a folder of the same name on the main disk."""
    cfg = config.load()
    bulk, index = cfg.get("bulk_root"), cfg.get("index_root")
    if bulk and index:
        _check_path(bulk, "bulk root")  # a root swapped for a symlink since setup is refused
        _check_path(index, "index root")
    if not bulk or not index or not os.path.isdir(bulk):
        raise KbError(f"the bulk root is not reachable: {bulk}")
    if not os.path.isdir(index):
        raise KbError(f"the index root is not reachable: {index}")
    marker = _read_marker(bulk)
    if not marker or marker.get("library_id") != cfg.get("library_id"):
        raise KbError(f"the marker file in the bulk root is missing or does not match this library: "
                      f"{os.path.join(bulk, MARKER)}")
    dev = (device_of or (lambda p: os.stat(p).st_dev))(bulk)
    if dev != cfg.get("bulk_device"):
        raise KbError("the bulk root is on a different device than at setup (a volume may be unmounted or replaced)")
    if not cfg.get("allow_main_disk") and dev == _main_device(main_device):
        raise KbError("the bulk root is on the main disk, which this library was not set up to allow")
    return cfg
