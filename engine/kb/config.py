"""The owner-only config. It lives outside both roots, in `~/.config/knowledge-base/` unless the
environment variable KB_CONFIG_DIR names another folder (the tests use that)."""
import json
import os
import secrets
import stat

from . import KbError

ENV = "KB_CONFIG_DIR"
FILE = "config.json"


def config_dir():
    return os.environ.get(ENV) or os.path.expanduser("~/.config/knowledge-base")


def config_path():
    return os.path.join(config_dir(), FILE)


def exists():
    return os.path.lexists(config_path())


def write_json_atomic(path, obj, mode):
    """Write a temporary file in the same folder, flush it to disk, then rename it into place."""
    tmp = f"{path}.tmp.{secrets.token_hex(6)}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=1, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.lexists(tmp):
            os.remove(tmp)
        raise
    dfd = os.open(os.path.dirname(path), os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def load():
    path = config_path()
    try:
        # O_NOFOLLOW refuses a symlink, and the checks below run on the opened file, so the file cannot be
        # swapped between the check and the read.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        raise KbError(f"no library is set up: there is no config at {path}") from None
    except OSError as e:
        raise KbError(f"the config at {path} cannot be opened: {e.strerror} (a symlink is refused)") from None
    with os.fdopen(fd) as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode):
            raise KbError(f"the config at {path} is not a plain file")
        if st.st_uid != os.getuid():
            raise KbError(f"the config at {path} is not owned by the user running this program")
        if st.st_mode & 0o077:
            raise KbError(f"the config at {path} is not owner-only (mode {stat.S_IMODE(st.st_mode):o}); it must be 600")
        if os.stat(os.path.dirname(path)).st_mode & 0o022:
            raise KbError(f"the config directory {os.path.dirname(path)} is writable by others; it must not be")
        try:
            cfg = json.load(f)
        except (OSError, ValueError) as e:
            raise KbError(f"the config at {path} cannot be read: {e}") from None
    if not isinstance(cfg, dict):
        raise KbError(f"the config at {path} is not a JSON object")
    return cfg


def save(cfg):
    d = config_dir()
    created = not os.path.isdir(d)
    os.makedirs(d, mode=0o700, exist_ok=True)
    if created:
        os.chmod(d, 0o700)
    write_json_atomic(config_path(), cfg, 0o600)
