"""The book store: books on disk, with immutable payloads and small mutable manifests.

Layout under the bulk root (nothing stored holds an absolute path):

    books/<last two characters of the id>/<book id>/
        book.json                          the root file (mutable metadata)
        v/<version>/version.json           the version file (mutable metadata)
        v/<version>/stages.json            the stage state (mutable metadata)
        v/<version>/original/              a payload: the source as captured (immutable once filed)
        v/<version>/derived/<tool>/<n>/    a payload: output of a tool, one folder per generation
    incoming/                              where payloads and new folders are built before they are renamed in

A payload folder holds its files and a `payload.json` with the sha256 and size of each. A payload is built in the
incoming area, re-read from disk and checked against that list, and only then renamed into place and marked
read-only, so it is never half filed. Manifests are rewritten with a temporary file and a rename."""
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone

from . import KbError, config, ids, incoming, library, stages

BOOKS = "books"
FORMAT = 1
_VERSION = re.compile(r"v[1-9][0-9]{0,5}")
_PAYLOAD = re.compile(r"original|derived/[a-z0-9][a-z0-9._-]{0,63}/[0-9]{1,6}")
_SHELF = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path, what):
    try:
        with open(path) as f:
            obj = json.load(f)
    except FileNotFoundError:
        raise KbError(f"no such {what}") from None
    except (OSError, ValueError) as e:
        raise KbError(f"the {what} cannot be read: {e}") from None
    if not isinstance(obj, dict):
        raise KbError(f"the {what} is not a JSON object")
    return obj


class Store:
    def __init__(self, cfg, write=True):
        self.cfg = cfg
        self.bulk = cfg["bulk_root"]
        self.library_id = cfg["library_id"]
        self.write = write

    @classmethod
    def open(cls, write=True):
        """Open the library named by the config. Opening to write runs the write guard first."""
        return cls(library.check_writable() if write else config.load(), write)

    def _guard(self):
        if not self.write:
            raise KbError("the store was opened read-only")
        library.check_writable()

    # --- paths
    def book_dir(self, book_id):
        return os.path.join(self.bulk, BOOKS, ids.shard(book_id), book_id)

    def book_file(self, book_id):
        return os.path.join(self.book_dir(book_id), "book.json")

    def version_dir(self, book_id, version_id):
        if not isinstance(version_id, str) or not _VERSION.fullmatch(version_id):
            raise KbError(f"not a version id: {version_id!r}")
        return os.path.join(self.book_dir(book_id), "v", version_id)

    def version_file(self, book_id, version_id):
        return os.path.join(self.version_dir(book_id, version_id), "version.json")

    def stages_file(self, book_id, version_id):
        return os.path.join(self.version_dir(book_id, version_id), "stages.json")

    def payload_path(self, book_id, version_id, name):
        if not isinstance(name, str) or not _PAYLOAD.fullmatch(name):
            raise KbError(f"not a payload name: {name!r}")
        return os.path.join(self.version_dir(book_id, version_id), *name.split("/"))

    # --- reading
    def list_books(self):
        root = os.path.join(self.bulk, BOOKS)
        found = []
        if os.path.isdir(root):
            for shard in os.listdir(root):
                shard_dir = os.path.join(root, shard)
                if len(shard) == 2 and os.path.isdir(shard_dir) and not os.path.islink(shard_dir):
                    for name in os.listdir(shard_dir):
                        book_dir = os.path.join(shard_dir, name)
                        try:
                            if (ids.shard(name) == shard and not os.path.islink(book_dir)
                                    and os.path.isfile(os.path.join(book_dir, "book.json"))):
                                found.append(name)
                        except KbError:
                            continue
        return sorted(found)

    def read_book(self, book_id):
        root = _read_json(self.book_file(book_id), "book")
        if root.get("book_id") != book_id:
            raise KbError("the root file does not belong to this book id")
        return root

    def version_ids(self, book_id):
        folder = os.path.join(self.book_dir(book_id), "v")
        if not os.path.isdir(folder):
            return []
        return sorted((n for n in os.listdir(folder) if _VERSION.fullmatch(n) and not os.path.islink(os.path.join(folder, n))), key=lambda n: int(n[1:]))

    def read_version(self, book_id, version_id):
        version = _read_json(self.version_file(book_id, version_id), "version")
        if version.get("book_id") != book_id or version.get("version_id") != version_id:
            raise KbError("the version file does not belong to this book and version")
        return version

    def payload_dir(self, book_id, version_id, name):
        """The path of a filed payload, or None. Nothing in the incoming area is ever returned."""
        path = self.payload_path(book_id, version_id, name)
        return path if os.path.isdir(path) and not os.path.islink(path) else None

    def verify_payload(self, book_id, version_id, name):
        """Re-hash every file of a filed payload against its hash list. Returns the list, or refuses."""
        path = self.payload_dir(book_id, version_id, name)
        if path is None:
            raise KbError(f"no such payload: {name}")
        manifest = _read_json(os.path.join(path, incoming.MANIFEST), "payload hash list")
        files = manifest.get("files")
        if not isinstance(files, dict) or not all(isinstance(e, dict) and "sha256" in e and "size" in e
                                                 for e in files.values()):
            raise KbError("the payload hash list is malformed")
        incoming.verify_incoming(path, manifest)
        return manifest

    # --- writing
    def _rewrite(self, path, mutate):
        obj = _read_json(path, os.path.basename(path))
        mutate(obj)
        config.write_json_atomic(path, obj, 0o644)

    def _file_folder(self, build, dest):
        """Build a folder in the incoming area, then rename it to dest. A failure removes what was built."""
        tmp = incoming.make_dir(self.bulk)
        try:
            build(tmp)
            incoming.promote(tmp, dest)
        except BaseException:
            if os.path.lexists(tmp):
                shutil.rmtree(tmp, ignore_errors=True)
            raise

    def create_book(self, title, kind, authors=None, year=None, language=None, identity_keys=None,
                    shelf="default", auto_filed=False, book_id=None):
        """File an empty book (its root file only) and return its id.

        A caller that must record the id elsewhere first (an index entry) can choose it with `ids.new_book_id()` and
        pass it as `book_id`; an id that already has a folder is refused."""
        if not isinstance(kind, str) or not kind:
            raise KbError("a book needs a kind")
        if title is not None and not isinstance(title, str):
            raise KbError("the title must be text")
        if authors is not None and not (isinstance(authors, list) and all(isinstance(a, str) for a in authors)):
            raise KbError("the authors must be a list of names")
        if year is not None and not isinstance(year, int):
            raise KbError("the year must be a whole number")
        if identity_keys is not None and not (isinstance(identity_keys, dict) and all(
                isinstance(k, str) and (isinstance(v, str) or (isinstance(v, list) and all(isinstance(x, str) for x in v)))
                for k, v in identity_keys.items())):
            raise KbError("the identity keys must be text, or lists of text")
        if not isinstance(shelf, str) or not _SHELF.fullmatch(shelf):
            raise KbError(f"not a shelf name: {shelf!r}")
        self._guard()
        if book_id is not None:
            ids.check_id(book_id)
            if os.path.lexists(self.book_dir(book_id)):
                raise KbError(f"the book id {book_id} is already used")
        chosen = book_id
        for _ in range(5):
            book_id = chosen or ids.new_book_id()
            dest = self.book_dir(book_id)
            if os.path.lexists(dest):
                continue  # an id is never reused
            root = {
                "format": FORMAT, "book_id": book_id, "library_id": self.library_id, "title": title or "",
                "authors": authors or [], "year": year, "kind": kind, "language": language,
                "identity_keys": identity_keys or {}, "shelf": shelf, "added": now(),
                "auto_filed": bool(auto_filed), "state": "active", "current_version": None, "same_work": [],
            }
            self._file_folder(lambda tmp: config.write_json_atomic(os.path.join(tmp, "book.json"), root, 0o644), dest)
            return book_id
        raise KbError("could not find a free book id")

    def add_version(self, book_id, label=None, source=None):
        """File a new version of a book, make it the current one, and return its id (v1, v2, ...)."""
        self.read_book(book_id)
        self._guard()
        if source is not None and not isinstance(source, dict):
            raise KbError("the source must be a mapping")
        existing = self.version_ids(book_id)
        version_id = f"v{(int(existing[-1][1:]) + 1) if existing else 1}"
        dest = self.version_dir(book_id, version_id)
        version = {"format": FORMAT, "book_id": book_id, "version_id": version_id, "label": label,
                   "source": source or {}, "created": now(), "primary": None, "payloads": {}, "caveats": []}

        def build(tmp):
            config.write_json_atomic(os.path.join(tmp, "version.json"), version, 0o644)
            config.write_json_atomic(os.path.join(tmp, "stages.json"), stages.initial_state(), 0o644)

        self._file_folder(build, dest)
        self._rewrite(self.book_file(book_id), lambda root: root.__setitem__("current_version", version_id))
        return version_id

    def set_shelf(self, book_id, shelf):
        """A reshelve is a small edit of the root file. No bytes move."""
        if not isinstance(shelf, str) or not _SHELF.fullmatch(shelf):
            raise KbError(f"not a shelf name: {shelf!r}")
        self.read_book(book_id)
        self._guard()
        self._rewrite(self.book_file(book_id), lambda root: root.__setitem__("shelf", shelf))

    def set_state(self, book_id, state):
        """Set a book's state. A book that turned out to duplicate another is marked `duplicate`."""
        if state not in ("active", "weeded", "removed", "duplicate"):
            raise KbError(f"not a book state: {state!r}")
        self.read_book(book_id)
        self._guard()
        self._rewrite(self.book_file(book_id), lambda root: root.__setitem__("state", state))

    def merge_identity_keys(self, book_id, set_keys=None, add_keys=None):
        """Change a book's identity keys. `set_keys` replaces single values (the address); `add_keys` appends to lists
        (other addresses, raw hashes) without repeating one."""
        set_keys, add_keys = set_keys or {}, add_keys or {}
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in set_keys.items()):
            raise KbError("set_keys must be text pairs")
        if not all(isinstance(k, str) and isinstance(v, list) and all(isinstance(x, str) for x in v)
                   for k, v in add_keys.items()):
            raise KbError("add_keys must map names to lists of text")
        self.read_book(book_id)
        self._guard()

        def mutate(root):
            keys = root.setdefault("identity_keys", {})
            keys.update(set_keys)
            for k, values in add_keys.items():
                current = keys.get(k, [])
                if not isinstance(current, list):
                    raise KbError(f"the identity key {k!r} is a single value and cannot take a list")
                keys[k] = current + [x for i, x in enumerate(values) if x not in current and x not in values[:i]]
        self._rewrite(self.book_file(book_id), mutate)

    def set_current_version(self, book_id, version_id):
        """Make an existing version the current one (the newest label, not necessarily the last one filed)."""
        if version_id not in self.version_ids(book_id):
            raise KbError(f"the book has no version {version_id!r}")
        self._guard()
        self._rewrite(self.book_file(book_id), lambda root: root.__setitem__("current_version", version_id))

    def set_metadata(self, book_id, /, **fields):
        """Change the descriptive fields of the root file: title, authors, year, language, and `metadata_source` (the
        version they were taken from). Nothing else."""
        checks = {"title": lambda v: isinstance(v, str), "language": lambda v: v is None or isinstance(v, str),
                  "year": lambda v: v is None or (isinstance(v, int) and not isinstance(v, bool)),
                  "authors": lambda v: isinstance(v, list) and all(isinstance(a, str) for a in v),
                  "metadata_source": lambda v: v is None or isinstance(v, str)}
        for name, value in fields.items():
            if name not in checks or not checks[name](value):
                raise KbError(f"cannot set {name!r} to that value")
        self.read_book(book_id)
        self._guard()
        self._rewrite(self.book_file(book_id), lambda root: root.update(fields))

    def set_version_caveats(self, book_id, version_id, caveats):
        """Record what the scan found: a list of {kind, count, detail, tool}. They never stop a book being filed."""
        ok = (isinstance(caveats, list) and len(caveats) <= 100 and all(
            isinstance(c, dict) and set(c) == {"kind", "count", "detail", "tool"} and isinstance(c["kind"], str)
            and isinstance(c["count"], int) and not isinstance(c["count"], bool) and isinstance(c["detail"], str)
            and isinstance(c["tool"], str) for c in caveats))
        if not ok:
            raise KbError("caveats must be a list of {kind, count, detail, tool}")
        self.read_version(book_id, version_id)
        self._guard()
        self._rewrite(self.version_file(book_id, version_id), lambda version: version.__setitem__("caveats", caveats))

    def set_version_label(self, book_id, version_id, label):
        """Record the label the source gave a version (for example an arXiv version), once it is known."""
        if not isinstance(label, str) or not label:
            raise KbError("a label must be text")
        self.read_version(book_id, version_id)
        self._guard()
        self._rewrite(self.version_file(book_id, version_id), lambda version: version.__setitem__("label", label))

    def set_version_source(self, book_id, version_id, source):
        """Replace the record of where a version came from (used when a failed fetch is retried)."""
        if not isinstance(source, dict):
            raise KbError("the source must be a mapping")
        self.read_version(book_id, version_id)
        self._guard()
        self._rewrite(self.version_file(book_id, version_id), lambda version: version.__setitem__("source", source))

    def events_file(self, book_id):
        return os.path.join(self.book_dir(book_id), "events.jsonl")

    def append_event(self, book_id, event, **data):
        """Add one line to the book's append-only event log (filed, sighting, ...)."""
        if not isinstance(event, str) or not re.fullmatch(r"[a-z][a-z_]{0,31}", event):
            raise KbError(f"not an event name: {event!r}")
        if {"event", "at"} & set(data):
            raise KbError("an event's data cannot use the names event or at")
        self.read_book(book_id)
        self._guard()
        line = (json.dumps({"event": event, "at": now(), **data}, sort_keys=True) + "\n").encode()
        fd = os.open(self.events_file(book_id), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o644)
        try:
            os.write(fd, line)  # one write, so lines from two writers do not mix
            os.fsync(fd)
        finally:
            os.close(fd)

    def read_events(self, book_id):
        self.read_book(book_id)
        try:
            with open(self.events_file(book_id)) as f:
                lines = [ln for ln in f.read().splitlines() if ln.strip()]
        except FileNotFoundError:
            return []
        try:
            return [json.loads(ln) for ln in lines]
        except ValueError as e:
            raise KbError(f"the event log cannot be read: {e}") from None

    def file_payload(self, book_id, version_id, name, files, primary=None, tool=None, untrusted=False):
        """File a payload: `files` maps a relative name to its bytes. Returns the hash list.

        The payload is built in the incoming area, checked against its hash list, renamed into place and made
        read-only. A payload already filed is never overwritten."""
        dest = self.payload_path(book_id, version_id, name)
        if not isinstance(files, dict) or not files:
            raise KbError("a payload needs at least one file")
        seen = {}
        for rel, data in files.items():
            incoming.clean_rel(rel)
            if not isinstance(data, (bytes, bytearray)):
                raise KbError(f"the content of {rel!r} must be bytes")
            if rel.casefold() in seen:
                raise KbError(f"two files differ only in letter case: {rel!r}")
            seen[rel.casefold()] = rel
        for rel in files:
            if any(other.startswith(rel + "/") for other in files):
                raise KbError(f"{rel!r} is both a file and a folder")
        if primary is not None and (name != "original" or primary not in files):
            raise KbError("the primary file must be one of the files of the original")
        self.read_version(book_id, version_id)
        self._guard()
        if os.path.lexists(dest):
            raise KbError(f"already filed: {name} of {version_id}")
        manifest = {"format": FORMAT, "name": name, "tool": tool, "primary": primary, "untrusted": bool(untrusted),
                    "created": now(),
                    "files": {rel: {"sha256": hashlib.sha256(bytes(data)).hexdigest(), "size": len(data)}
                              for rel, data in sorted(files.items())}}

        def build(tmp):
            for rel, data in files.items():
                incoming.write_file(tmp, rel, bytes(data))
            incoming.write_file(tmp, incoming.MANIFEST, (json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode())
            incoming.verify_incoming(tmp, manifest)
            incoming.seal_files(tmp)

        self._file_folder(build, dest)
        incoming.make_read_only(dest)
        self._note_payload(book_id, version_id, name, manifest)
        return manifest

    def _note_payload(self, book_id, version_id, name, manifest):
        """Record a filed payload in the version file, from the payload's own hash list. If a stop comes before
        this, the payload is still filed, and `adopt_payload` repairs the version file on resume."""
        primary = manifest.get("primary")

        def mutate(version):
            version["payloads"][name] = {"files": len(manifest["files"]),
                                         "bytes": sum(e["size"] for e in manifest["files"].values()),
                                         "tool": manifest.get("tool")}
            if primary is not None:
                version["primary"] = primary
        self._rewrite(self.version_file(book_id, version_id), mutate)

    def adopt_payload(self, book_id, version_id, name):
        """Take a payload that was filed before a stop: check it against its hash list, mark it read-only if the stop
        came before that, and bring the version file up to date from the hash list. Never writes to the payload's
        files. Safe to repeat. Refuses a payload that fails its check."""
        self._guard()
        manifest = self.verify_payload(book_id, version_id, name)
        incoming.make_read_only(self.payload_path(book_id, version_id, name))
        self._note_payload(book_id, version_id, name, manifest)
        return manifest
