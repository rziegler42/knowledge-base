"""The capture of a PDF file from the owner's disk (`docs/plans/2026-11-19-load-pdf-files-from-a-folder-into-the-library.md`, Increment A).

`capture(store, ident, path)` reads one file as bytes, checks that it begins `%PDF-`, and files it as a book of the owner's: the kind `paper`, the shelf `default`, not `auto_filed`, the file as `paper.pdf`, its content hash as
the identity key `sha256`, a `filed` event and the stage `fetched` done. **The file is never parsed**: the scan and the converter read it later, in their sandbox. It returns a dict whose `status` is `filed`, `duplicate` (the library
holds the bytes already: the book is named) or `refused` (a fixed reason; nothing is filed). Every dict carries `file_name`, the one cleaned form of the base name that is also the title and the `file_name` of the version's source:
the folder of the file and the raw name are stored and returned nowhere.

**A duplicate is told by an atomic claim of the hash in the identity index** (`Identity.register` keeps the first holder). The order for one file: look up the hash (a holder that exists and is `active` and finished is a
duplicate, with nothing written; one of the owner's that is not finished is finished with this file; anything else, an entry for a book that does not exist or is not active, is stale); make the book (so that it is live when it can
be found); claim the hash for it; read the holder again (a claim made in between by another wins, and this book is weeded with a `capture_failed` event); file the payload. An error of any kind, a stop included, after the book is
made weeds it before it leaves. `lock(index_root)` keeps two runs of the command apart (an exclusive, non-blocking `flock`). The crawl's capture does not take the lock; it meets the claim in the index.

The module makes no request."""
import contextlib
import errno
import fcntl
import hashlib
import os
import stat

from . import KbError, __version__, ids, stages, textutil
from .store import now

TOOL = f"capture-file {__version__}"
MAX_BYTES = 100_000_000                 # the largest file taken, in bytes
NAME_CHARS = 200                        # the cleaned base name is cut to this
LOCK = "capture-file.lock"
HEADER = b"%PDF-"


@contextlib.contextmanager
def lock(index_root):
    """Hold the lock of the command: one run at a time. A second holder, in this or another process, is refused. The lock is released when the holder ends or is killed."""
    path = os.path.join(os.fspath(index_root), LOCK)
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError:
        raise KbError("the lock of capture-file cannot be opened (the index folder is missing or not writable, or the lock is a link)") from None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            if e.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                raise KbError("another run of capture-file holds the lock") from None
            raise KbError("the lock of capture-file cannot be taken") from None
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def clean_name(path):
    """The cleaned base name of a path without a final `.pdf`, at most `NAME_CHARS` characters: control, bidirectional and zero-width characters removed, white space collapsed."""
    base = os.path.basename(os.fsdecode(path))
    if base.lower().endswith(".pdf"):
        base = base[:-4]
    return textutil.clean(base, NAME_CHARS) or "untitled"


def _result(status, name, book_id=None, version_id=None, reason=None):
    out = {"status": status, "file_name": name, "book_id": book_id, "version_id": version_id}
    if reason is not None:
        out["reason"] = reason
    return out


def _read(path, max_bytes):
    """The bytes of a regular file of at most `max_bytes`, or a fixed reason. The file is opened without following a link and without blocking (a pipe returns at once and is not a regular file), and at most one
    byte more than the limit is read, so that a file that grows while it is read cannot fill the memory."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_NOCTTY", 0))
    except (OSError, ValueError):                 # (a path with a NUL byte is a ValueError)
        return None, "the file cannot be opened (it is missing, unreadable, or a link)"
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return None, "it is not a regular file"
        if info.st_size > max_bytes:
            return None, "the file is larger than the limit"
        chunks, total = [], 0
        while total <= max_bytes:
            chunk = os.read(fd, min(1 << 20, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total > max_bytes:
            return None, "the file is larger than the limit"
        return b"".join(chunks), None
    except OSError:
        return None, "the file cannot be read"
    finally:
        os.close(fd)


def _state(store, book_id):
    """`stale` (no book, one that cannot be read, or one that is not active: the index entry is not a holder), `unfinished` (an active book of the owner's whose fetch is not done), or `finished`."""
    if not book_id:
        return "stale"
    try:
        root = store.read_book(book_id)
    except KbError:
        return "stale"
    if root.get("state") != "active":
        return "stale"
    version = root.get("current_version")
    done = bool(version) and stages.read(store, book_id, version)["stages"]["fetched"]["status"] in ("done", "skipped")
    keys = root.get("identity_keys") or {}
    if done or root.get("auto_filed") is True or root.get("kind") != "paper" or "url" in keys or "arxiv" in keys:
        return "finished"                     # a book of the crawl's, or one that another capture made (a page, an arXiv paper), is never written into
    return "unfinished"


def _weed(store, book_id, reason):
    """Set a book this command made aside: the event first, as the crawl's `drop` does."""
    try:
        store.append_event(book_id, "capture_failed", reason=reason)
    except (KbError, OSError):
        pass                                  # the state is set even when the event cannot be written: a book that is not active is not a holder
    try:
        store.set_state(book_id, "weeded")
    except (KbError, OSError):
        pass


def _holds(store, book_id, version, digest, size):
    """True if the filed `paper.pdf` of the version is a regular file of `size` bytes with the hash `digest`. It is opened without following a link and without blocking, and read to `size` bytes at most."""
    try:
        fd = os.open(os.path.join(store.payload_path(book_id, version, "original"), "paper.pdf"), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_NOCTTY", 0))
    except OSError:
        return False
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size != size:
            return False
        h, total = hashlib.sha256(), 0
        while total <= size:
            chunk = os.read(fd, min(1 << 20, size + 1 - total))
            if not chunk:
                break
            h.update(chunk)
            total += len(chunk)
        return total == size and h.hexdigest() == digest
    except OSError:
        return False
    finally:
        os.close(fd)


def _note_filed(store, book_id, digest, name, retrieved):
    """The `filed` event of the hash, once."""
    if not any(e.get("event") == "filed" and e.get("sha256") == digest for e in store.read_events(book_id)):
        store.append_event(book_id, "filed", file_name=name, sha256=digest, retrieved=retrieved)


def _file(store, book_id, data, digest, name):
    """File the payload of a book that holds the hash and has none done: adopt a payload that an earlier try filed (it must be these very bytes, and is looked at before anything is written: `reconcile` marks the stage done when it
    adopts), or file this one; then the event and the stage. For an adopted payload the event is written before `reconcile` marks the stage, so that a stop between the two cannot leave a finished book with no event."""
    root = store.read_book(book_id)
    source = {"file_name": name, "sha256": digest, "bytes": len(data), "retrieved": now()}
    version = root.get("current_version")
    fresh = not version
    if fresh:
        version = store.add_version(book_id, source=source)
    earlier = store.payload_dir(book_id, version, "original") is not None
    if earlier:
        if not _holds(store, book_id, version, digest, len(data)):
            return None
        if not fresh:
            store.set_version_source(book_id, version, source)
        _note_filed(store, book_id, digest, name, source["retrieved"])
    elif not fresh:
        store.set_version_source(book_id, version, source)
    outcome = stages.reconcile(store, book_id, version, "fetched", "original")
    if outcome == "invalid":
        return None
    if outcome == "run":
        store.file_payload(book_id, version, "original", {"paper.pdf": data}, primary="paper.pdf", tool=TOOL)
    elif outcome == "blocked":
        raise KbError("an earlier filing of this book cannot be finished")
    _note_filed(store, book_id, digest, name, source["retrieved"])
    stages.mark(store, book_id, version, "fetched", "done", tool=TOOL)
    return version


def capture(store, ident, path, max_bytes=MAX_BYTES, step_hook=None):
    """File one PDF file as a book of the owner's (see the module). `step_hook` is called with `made` and `claimed` (tests pause the capture there)."""
    if type(max_bytes) is not int or max_bytes < 1:
        raise KbError("the size limit must be a whole number from 1")
    hook = step_hook or (lambda step: None)
    path = os.fsdecode(path)                  # a text or bytes path, or a path object
    name = clean_name(path)
    data, why = _read(path, max_bytes)
    if why:
        return _result("refused", name, reason=why)
    if not data.startswith(HEADER):
        return _result("refused", name, reason="it does not begin like a PDF")
    digest = hashlib.sha256(data).hexdigest()

    holder = ident.lookup("sha256", digest)
    try:
        state = _state(store, holder)
    except KbError:
        return _result("refused", name, holder, reason="the library cannot say whether it holds this file (the stages of a book cannot be read)")
    if state == "finished":
        return _result("duplicate", name, holder, store.read_book(holder).get("current_version"))
    if state == "unfinished":
        version = _file(store, holder, data, digest, name)
        if version is None:
            return _result("refused", name, holder, reason="an earlier filing of the book does not validate")
        return _result("filed", name, holder, version)

    book_id = ids.new_book_id()
    store.create_book(title=name, kind="paper", identity_keys={"sha256": [digest]}, book_id=book_id)
    try:
        hook("made")
        if holder is None:
            ident.register("sha256", digest, book_id)
        else:
            ident.reassign("sha256", digest, book_id)                      # the entry named a book that is not a holder
        winner = ident.lookup("sha256", digest)
        if winner != book_id:
            if _state(store, winner) != "stale":
                _weed(store, book_id, "another capture claimed the hash first")
                return _result("duplicate", name, winner, store.read_book(winner).get("current_version"))
            ident.reassign("sha256", digest, book_id)
        hook("claimed")
        version = _file(store, book_id, data, digest, name)
        if version is None:
            _weed(store, book_id, "the filing does not validate")
            return _result("refused", name, reason="the filing does not validate")
        return _result("filed", name, book_id, version)
    except BaseException:
        _weed(store, book_id, "the capture did not finish")
        raise
