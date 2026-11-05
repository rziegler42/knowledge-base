"""The incoming area: where a payload is built, checked and only then renamed into place.

It sits inside the bulk root, so a rename into a book folder stays on one volume and is atomic. A folder that a
crash leaves behind here is never read as a book or a payload."""
import hashlib
import os
import posixpath
import stat
import tempfile

from . import KbError

AREA = "incoming"
MANIFEST = "payload.json"


def area(bulk_root):
    return os.path.join(bulk_root, AREA)


def make_dir(bulk_root):
    root = area(bulk_root)
    os.makedirs(root, exist_ok=True)
    return tempfile.mkdtemp(prefix="i-", dir=root)  # mode 0700


def clean_rel(rel):
    """A file name inside a payload: relative, no dot or dot-dot parts, no backslash or NUL. Returns it."""
    if not isinstance(rel, str) or not rel or "\0" in rel or "\\" in rel or rel.startswith("/"):
        raise KbError(f"not a file name inside a payload: {rel!r}")
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts) or posixpath.normpath(rel) != rel:
        raise KbError(f"not a file name inside a payload: {rel!r}")
    if rel == MANIFEST:
        raise KbError(f"{MANIFEST} is reserved for the payload's own hash list")
    return rel


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_file(dirpath, rel, data):
    """Write one file into an incoming folder, never overwriting, and flush it to disk."""
    target = os.path.join(dirpath, *rel.split("/"))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def hash_tree(dirpath):
    """{relative path: (sha256, size)} of every file under a folder, excluding the folder's own hash list.
    A symlink or anything but a plain file or folder is refused."""
    found = {}
    for cur, dirnames, filenames in os.walk(dirpath):
        for name in dirnames + filenames:
            p = os.path.join(cur, name)
            mode = os.lstat(p).st_mode
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise KbError(f"{os.path.relpath(p, dirpath)} is not a plain file or folder")
        for name in filenames:
            p = os.path.join(cur, name)
            rel = os.path.relpath(p, dirpath).replace(os.sep, "/")
            if rel == MANIFEST:
                continue
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            found[rel] = (h.hexdigest(), os.path.getsize(p))
    return found


def verify_incoming(dirpath, manifest):
    """Re-read the files from disk and compare them with the hash list. Refuse on any difference."""
    expected = {rel: (e["sha256"], e["size"]) for rel, e in manifest["files"].items()}
    actual = hash_tree(dirpath)
    problems = []
    for rel in sorted(set(expected) | set(actual)):
        if rel not in actual:
            problems.append(f"{rel} is missing")
        elif rel not in expected:
            problems.append(f"{rel} is not in the hash list")
        elif actual[rel] != expected[rel]:
            problems.append(f"{rel} does not match its recorded hash")
    if problems:
        raise KbError("the payload does not match its hash list: " + "; ".join(problems))


def seal_files(dirpath):
    for cur, _dirnames, filenames in os.walk(dirpath):
        for name in filenames:
            os.chmod(os.path.join(cur, name), 0o444)


def promote(src, dst):
    """Rename a built folder into its place. Both are on the same volume, so the rename is atomic: the folder
    is there whole or not at all."""
    if os.path.lexists(dst):
        raise KbError("already filed: the place for this payload is taken")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.stat(src).st_dev != os.stat(os.path.dirname(dst)).st_dev:
        raise KbError("the incoming area and the book folder are on different volumes")
    fsync_dir(src)
    os.rename(src, dst)
    fsync_dir(os.path.dirname(dst))


def make_read_only(path):
    """Mark a filed payload read-only: files 444 (already done before the rename) and folders 555."""
    for cur, _dirnames, filenames in os.walk(path, topdown=False):
        for name in filenames:
            os.chmod(os.path.join(cur, name), 0o444)
        os.chmod(cur, 0o555)
