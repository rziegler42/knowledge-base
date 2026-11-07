"""Answers of a model that the engine refused, kept aside so that the owner can read what the model wrote.

A refused answer is not kept anywhere else: no card is made from it. A failure is easier to diagnose from the answer than from the
reason alone (for example how far past a limit a list went). The files are in the folder `refused` of the index root, which holds
what can be rebuilt, so a file there is an aid and not a record. Nothing here reads a file back, deletes one, or lists them: the
owner reads and deletes them as ordinary files, and at MAX_FILES nothing more is kept.

An answer is untrusted text, so the file is JSON with every character outside ASCII escaped: a control or escape character in it
cannot reach a terminal when the file is read with `cat`. The folder and the file are made with descriptors and without following a
link at the last step of each path: the index root is opened with no-follow (a link higher in its path is not looked for here; the
library's roots are checked for links when it is set up), `refused` is made or opened relative to it with no-follow, it must be a
directory owned by the user with no access for group or others in its mode bits (an access list, which macOS can add, is not
looked at), and the file is created relative to it, exclusively, with no-follow and mode 600. A file that cannot be written whole is
removed."""
import json
import os
import re
import secrets
from datetime import datetime, timezone

from . import KbError, ids, models, textutil

FORMAT = 1
FOLDER = "refused"
MAX_FILES = 200
MAX_ANSWER = 262144  # characters of the answer kept; the bridge limits a reply to this many bytes
TRIES = 5            # names tried before giving up, when one is already there
_VERSION = re.compile(r"v[1-9][0-9]{0,5}")
_JOB = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
_RECORD = ("model", "registry", "prompt_version", "date", "input_tokens", "output_tokens")


def _stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _count(value):
    return value is None or (type(value) is int and 0 <= value <= 10 ** 12)


def _checked(book_id, version_id, job, record, answer):
    ids.check_id(book_id)
    if not isinstance(version_id, str) or not _VERSION.fullmatch(version_id):
        raise KbError("a refused answer is kept for a version named v1, v2 and so on")
    if not isinstance(job, str) or not _JOB.fullmatch(job):
        raise KbError("a refused answer is kept for a job with a plain name")
    ok = (isinstance(record, dict) and set(record) == set(_RECORD) and models._valid_model(record["model"])
          and isinstance(record["registry"], str) and models._NAME.fullmatch(record["registry"])
          and isinstance(record["prompt_version"], str) and models._VERSION.fullmatch(record["prompt_version"])
          and isinstance(record["date"], str) and len(record["date"]) <= 40 and textutil.clean(record["date"], 40) == record["date"]
          and _count(record["input_tokens"]) and _count(record["output_tokens"]))
    if not ok:
        raise KbError("the record of the call is not in the expected form")
    if not isinstance(answer, str):
        raise KbError("the answer to keep is not text")


def keep(index_root, book_id, version_id, job, record, reason, answer):
    """Keep a refused answer in a new file of the folder `refused` of the index root and return the file's name (not its place).
    Refuses, and keeps nothing, when the index root or the folder is a link, the folder is not a directory of the user that no one
    else can enter, MAX_FILES files are already kept, or no free name is found. A file that exists is never overwritten."""
    _checked(book_id, version_id, job, record, answer)
    cut = len(answer) > MAX_ANSWER
    doc = {"format": FORMAT, "untrusted": True, "book_id": book_id, "version_id": version_id, "job": job, **{k: record[k] for k in _RECORD},
           "reason": textutil.clean(str(reason), 500), "answer_cut": cut, "answer": answer[:MAX_ANSWER]}
    data = (json.dumps(doc, indent=1) + "\n").encode("ascii")  # the default escapes everything outside ASCII
    try:
        root_fd = os.open(index_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as e:
        raise KbError(f"the index folder cannot be opened without following a link: {textutil.clean(e.strerror or 'error', 100)}") from None
    try:
        try:
            os.mkdir(FOLDER, 0o700, dir_fd=root_fd)
        except FileExistsError:
            pass
        except OSError as e:
            raise KbError(f"the folder {FOLDER} cannot be made: {textutil.clean(e.strerror or 'error', 100)}") from None
        try:
            dir_fd = os.open(FOLDER, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        except OSError:
            raise KbError(f"{FOLDER} is not a folder, or it is a link, so nothing is kept in it") from None
        try:
            st = os.fstat(dir_fd)
            if st.st_uid != os.getuid() or st.st_mode & 0o077:
                raise KbError(f"the folder {FOLDER} is not private to the user (others can enter it), so nothing is kept in it")
            if len(os.listdir(dir_fd)) >= MAX_FILES:
                raise KbError(f"{MAX_FILES} refused answers are already kept; delete some to keep more")
            for _ in range(TRIES):
                name = f"{book_id}-{version_id}-{job}-{_stamp()}-{secrets.token_hex(4)}.json"
                try:
                    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dir_fd)
                except FileExistsError:
                    continue  # a file or a link of that name is there: never written through, a new name is tried
                except OSError as e:
                    raise KbError(f"the file cannot be made: {textutil.clean(e.strerror or 'error', 100)}") from None
                try:
                    try:
                        f = os.fdopen(fd, "wb")
                    except BaseException:
                        os.close(fd)
                        raise
                    with f:
                        os.fchmod(f.fileno(), 0o600)
                        f.write(data)
                        f.flush()
                        os.fsync(f.fileno())
                except OSError as e:
                    try:
                        os.unlink(name, dir_fd=dir_fd)  # a half-written file is not left behind, and does not count toward the limit
                    except OSError:
                        pass
                    raise KbError(f"the answer could not be written: {textutil.clean(e.strerror or 'error', 100)}") from None
                return name
            raise KbError("no free name for the file was found")
        finally:
            os.close(dir_fd)
    finally:
        os.close(root_fd)
