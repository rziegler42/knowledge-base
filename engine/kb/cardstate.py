"""The state of a card in the making: a journal of the model calls that have been made for it, kept in the index root.

A card is made by a fixed sequence of calls (`cardmake.make_model_part`): notes of each piece, the card, checks of its items, and, if
a model is set for it, a second round and the checks of that. What the card is depends only on the answers to those calls and on the
book, so a journal of the answers is the whole state: made again from the same journal, the same steps give the same card without
asking a model again for any answer already in it, and a call that is not yet in it is the next call to make. The journal is kept so that
a card can be stopped, and made again later, or by another run, without paying twice.

    <index root>/card-runs/<run>/<book>-<version>.json
      {"format": 1, "header": {...}, "entries": [{"job", "entry", "values", "record"}, ...]}

The header says what the journal was made for: the book, the version, the conversion in use, the title, the kind of source, the number
of pieces and of pieces read, the model entry of each kind of work and the server and model behind it, the prompt version of each job,
and a digest of the outline and of the text of the pieces read. `cardmake.make_model_part` compares every one of these with the card
being made and refuses the journal as stale if any differs. An entry is one successful call: the job, the model entry it went to, the checked answer, and the record of how it was
made. The values are untrusted text from a book or a model, so they are checked again when they are used. They are not signed: the verdicts,
the support lists and the records of a journal are taken as they are saved, so whoever can write the file can say what the checks
said; the file is in a folder that only the user can enter, and that is the whole of its protection.

The file is derived data that can be deleted at any time without losing a card. It is written and read as the other files of the
index root are: the index root is opened without following a link, the folders are made private to the user and checked, the file is
made with the exclusive create and mode 600 under a temporary name and put in place with one rename, a file that is a link, a pipe,
another user's, readable by others or larger than MAX_BYTES is refused, and a text that is not one JSON object with exactly the keys
below is refused."""
import json
import os
import re
import secrets
import stat

from . import KbError, ids, models, textutil

FORMAT = 1
FOLDER = "card-runs"
MAX_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 200
TRIES = 5
_RUN = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
_VERSION_ID = re.compile(r"v[1-9][0-9]{0,5}")
_JOB = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
_TASKS = ("notes", "card", "check", "more")
_HEADER = ("book_id", "version_id", "conversion", "title", "kind", "limit", "pieces", "tasks", "versions", "models", "text")
_ENTRY = ("job", "entry", "values", "record")
_RECORD = ("model", "registry", "prompt_version", "date", "input_tokens", "output_tokens")
_CONVERSION = ("generation", "tool", "version")
_DIGEST = re.compile(r"[0-9a-f]{64}")


def _names(run, book_id, version_id):
    if not isinstance(run, str) or not _RUN.fullmatch(run):
        raise KbError("a run is named with lower-case letters, digits and hyphens")
    ids.check_id(book_id)
    if not isinstance(version_id, str) or not _VERSION_ID.fullmatch(version_id):
        raise KbError("a version is named v1, v2 and so on")
    return run, f"{book_id}-{version_id}.json"


def _count(value, high=10 ** 12):
    return type(value) is int and 0 <= value <= high


def _task_name(value):
    return value is None or (isinstance(value, str) and models._NAME.fullmatch(value) is not None)


def _check_header(h):
    bad = KbError("the saved state of a card has a header that is not valid")
    if not isinstance(h, dict) or set(h) != set(_HEADER):
        raise bad
    ids.check_id(h["book_id"])
    if not isinstance(h["version_id"], str) or not _VERSION_ID.fullmatch(h["version_id"]):
        raise bad
    c = h["conversion"]
    if c is not None and not (isinstance(c, dict) and set(c) == set(_CONVERSION) and _count(c["generation"], 10 ** 6)
                              and all(isinstance(c[k], str) and 0 < len(c[k]) <= 100 for k in ("tool", "version"))):
        raise bad
    if not isinstance(h["title"], str) or len(h["title"]) > 500 or not isinstance(h["kind"], str) or not 0 < len(h["kind"]) <= 100:
        raise bad
    if type(h["limit"]) is not int or not 1 <= h["limit"] <= 1000 or not _count(h["pieces"], 10 ** 6):
        raise bad
    if not isinstance(h["tasks"], dict) or set(h["tasks"]) != set(_TASKS) or not all(_task_name(v) for v in h["tasks"].values()):
        raise bad
    if not isinstance(h["versions"], dict) or set(h["versions"]) != set(_TASKS) or not all(
            v is None or (isinstance(v, str) and models._VERSION.fullmatch(v)) for v in h["versions"].values()):
        raise bad
    _check_models(h["models"], bad)
    if not isinstance(h["text"], str) or not _DIGEST.fullmatch(h["text"]):
        raise bad


def _check_models(m, bad):
    """The server and the model that each registry entry named: a list of two names, or None where no entry is set."""
    if not isinstance(m, dict) or set(m) != set(_TASKS):
        raise bad
    for pair in m.values():
        if pair is not None and not (isinstance(pair, list) and len(pair) == 2 and all(isinstance(x, str) and 0 < len(x) <= 200 for x in pair)):
            raise bad


def _check_entry(e):
    bad = KbError("the saved state of a card has an entry that is not valid")
    if not isinstance(e, dict) or set(e) != set(_ENTRY):
        raise bad
    if not isinstance(e["job"], str) or not _JOB.fullmatch(e["job"]) or not isinstance(e["entry"], str) or not models._NAME.fullmatch(e["entry"]):
        raise bad
    if not isinstance(e["values"], dict):
        raise bad
    r = e["record"]
    ok = (isinstance(r, dict) and set(r) == set(_RECORD) and models._valid_model(r["model"])
          and isinstance(r["registry"], str) and models._NAME.fullmatch(r["registry"])
          and isinstance(r["prompt_version"], str) and models._VERSION.fullmatch(r["prompt_version"])
          and isinstance(r["date"], str) and len(r["date"]) <= 40 and textutil.clean(r["date"], 40) == r["date"]
          and all(r[k] is None or _count(r[k]) for k in ("input_tokens", "output_tokens")))
    if not ok:
        raise bad


class Journal:
    """The calls made for one card. `save`, if given, is called with the journal each time a call is added, so that the call is kept
    before the next one is made."""

    def __init__(self, header, entries=None, save=None):
        self.header = header
        self.entries = list(entries or [])
        self._save = save

    def add(self, job, entry, values, record):
        self.entries.append({"job": job, "entry": entry, "values": values, "record": record})
        if self._save is not None:
            self._save(self)

    def check_header(self, expected):
        """Refuse the journal as stale unless each key of `expected` has the same value in its header."""
        for key, value in expected.items():
            if key not in self.header or self.header[key] != value:
                raise KbError(f"the saved state of the card is stale: its {key} is not what the card is being made with")


def _open_folder(index_root, run, create):
    """The descriptors of the index root and of the run's folder, made private to the user; refuses a link and a folder that others can
    enter. Returns (root_fd, run_fd); the caller closes both."""
    try:
        root_fd = os.open(index_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as e:
        raise KbError(f"the index folder cannot be opened without following a link: {textutil.clean(e.strerror or 'error', 100)}") from None
    fds = [root_fd]
    try:
        for name in (FOLDER, run):
            parent = fds[-1]
            if create:
                try:
                    os.mkdir(name, 0o700, dir_fd=parent)
                except FileExistsError:
                    pass
                except OSError as e:
                    raise KbError(f"the folder {name} cannot be made: {textutil.clean(e.strerror or 'error', 100)}") from None
            try:
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            except FileNotFoundError:
                if create:
                    raise KbError(f"{name} is not a folder") from None
                for each in fds:
                    os.close(each)
                return None
            except OSError:
                raise KbError(f"{name} is not a folder, or it is a link, so the saved state is not used") from None
            fds.append(fd)
            st = os.fstat(fd)
            if st.st_uid != os.getuid() or st.st_mode & 0o077:
                raise KbError(f"the folder {name} is not private to the user (others can enter it), so the saved state is not used")
        os.close(fds[1])
        return fds[0], fds[2]
    except BaseException:
        for each in fds:
            try:
                os.close(each)
            except OSError:
                pass
        raise


def write(index_root, run, book_id, version_id, journal):
    """Put the journal in its file, whole, replacing an earlier one. Nothing else is left in the folder, and an earlier file is
    untouched if the write fails."""
    run, name = _names(run, book_id, version_id)
    if journal.header["book_id"] != book_id or journal.header["version_id"] != version_id:
        raise KbError("the journal is not the journal of this book and version")
    _check_header(journal.header)
    if len(journal.entries) > MAX_ENTRIES:
        raise KbError("the saved state of a card holds too many calls")
    for e in journal.entries:
        _check_entry(e)
    try:
        data = (json.dumps({"format": FORMAT, "header": journal.header, "entries": journal.entries}) + "\n").encode("ascii")
    except (TypeError, ValueError):
        raise KbError("the saved state of a card is not plain data") from None
    if len(data) > MAX_BYTES:
        raise KbError("the saved state of a card is larger than the limit")
    root_fd, run_fd = _open_folder(index_root, run, create=True)
    temp = None
    try:
        for _ in range(TRIES):
            temp = f".{name}.{secrets.token_hex(4)}.tmp"
            try:
                fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=run_fd)
                break
            except FileExistsError:
                temp = None
        else:
            raise KbError("no free name for the saved state was found")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.rename(temp, name, src_dir_fd=run_fd, dst_dir_fd=run_fd)
            temp = None
        except OSError as e:
            raise KbError(f"the saved state of a card could not be written: {textutil.clean(e.strerror or 'error', 100)}") from None
    finally:
        if temp is not None:
            try:
                os.unlink(temp, dir_fd=run_fd)
            except OSError:
                pass
        os.close(run_fd)
        os.close(root_fd)


def _loads(data):
    def pairs(items):
        keys = [k for k, _ in items]
        if len(keys) != len(set(keys)):
            raise ValueError("a key is repeated")
        return dict(items)

    return json.loads(data, object_pairs_hook=pairs, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))


def read(index_root, run, book_id, version_id):
    """The journal in its file, or None if there is no file. Refuses a file that is not as the module describes."""
    run, name = _names(run, book_id, version_id)
    opened = _open_folder(index_root, run, create=False)
    if opened is None:
        return None
    root_fd, run_fd = opened
    try:
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=run_fd)
        except FileNotFoundError:
            return None
        except OSError:
            raise KbError("the saved state of the card is a link, or cannot be opened") from None
        with os.fdopen(fd, "rb") as f:
            st = os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
                raise KbError("the saved state of the card is not a file of the user that no one else can read or write")
            if st.st_size > MAX_BYTES:
                raise KbError("the saved state of the card is larger than the limit")
            data = f.read(MAX_BYTES + 1)
    finally:
        os.close(run_fd)
        os.close(root_fd)
    if len(data) > MAX_BYTES:
        raise KbError("the saved state of the card is larger than the limit")
    try:
        doc = _loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise KbError("the saved state of the card is not valid JSON") from None
    if not isinstance(doc, dict) or set(doc) != {"format", "header", "entries"} or type(doc["format"]) is not int or doc["format"] != FORMAT:
        raise KbError("the saved state of the card is not of this format")
    _check_header(doc["header"])
    if doc["header"]["book_id"] != book_id or doc["header"]["version_id"] != version_id:
        raise KbError("the saved state is for another book or version than its file name says")
    if not isinstance(doc["entries"], list) or len(doc["entries"]) > MAX_ENTRIES:
        raise KbError("the saved state of the card has too many calls")
    for e in doc["entries"]:
        _check_entry(e)
    return Journal(doc["header"], doc["entries"])


def remove(index_root, run, book_id, version_id):
    """Delete the file of a journal, if there is one."""
    run, name = _names(run, book_id, version_id)
    opened = _open_folder(index_root, run, create=False)
    if opened is None:
        return
    root_fd, run_fd = opened
    try:
        try:
            # the file, and what a crash between making a temporary file and putting it in place left beside it
            for each in [name] + [n for n in os.listdir(run_fd) if n.startswith(f".{name}.") and n.endswith(".tmp")]:
                try:
                    os.unlink(each, dir_fd=run_fd)
                except FileNotFoundError:
                    pass
        except OSError as e:
            raise KbError(f"the saved state of the card could not be removed: {textutil.clean(e.strerror or 'error', 100)}") from None
    finally:
        os.close(run_fd)
        os.close(root_fd)
