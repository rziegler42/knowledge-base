"""Run an approved tool on a file the library holds, confined by the macOS sandbox, and file what it makes.

The tool runs as a child of `sandbox-exec` under a profile that denies everything by default and then allows only:
running the approved program, reading system libraries, the tool's own runtime folders, its pinned scripts and its
input folder, and writing in its own output folder. It has no network, cannot start or signal other programs, and
cannot see the config, the library or anything else. It also runs with an empty environment, no standard input, a
time limit, an output limit and a file-size limit, in a process group that is killed whole when it overruns.

What it leaves in its output folder is untrusted data. It is inventoried without following links, checked to be plain
files with plain names within limits, read back, and filed as a derived payload through the incoming area, so an
interrupted run leaves nothing half filed. A tool cannot hide data from the limits by locking its own folders: a folder
that cannot be listed stops the run, and removal restores the modes first.

`sandbox-exec` is marked deprecated by Apple but ships with macOS. Memory is not limited, because macOS does not
enforce address-space limits. The profile allows reading file metadata everywhere, because the system loader needs it,
so a tool can learn whether a path exists, not what is in it."""
import itertools
import os
import re
import resource
import select
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time

from . import KbError, approvals, config, incoming, textutil

SANDBOX = "/usr/bin/sandbox-exec"
SUPERVISOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "supervisor.py")
MAX_FILES = 200
MAX_DIRS = 100
MAX_DEPTH = 8
STDERR_CAP = 65536
POLL = 0.05
_NAME = re.compile(r"[A-Za-z0-9._-]{1,100}")


class ToolError(KbError):
    """A tool that failed, overran a limit or left something unacceptable behind."""


class Result:
    def __init__(self, files, stdout, stderr, seconds):
        self.files, self.stdout, self.stderr, self.seconds = files, stdout, stderr, seconds


def _q(path):
    return '"' + approvals.safe_path(path) + '"'


def build_profile(entry, input_dir, output_dir):
    """The sandbox profile for one run. Every path in it is checked, so none can break out of its quotes."""
    readable = [_q("/usr/lib"), _q("/System/Library"), _q("/private/var/db/dyld"), _q(input_dir)]
    readable += [_q(r) for r in entry["reads"]]
    readable += ["(literal %s)" % _q(p) for p in entry["pinned"]]
    readable = [r if r.startswith("(") else "(subpath %s)" % r for r in readable]
    return "\n".join([
        "(version 1)",
        "(deny default)",
        "(deny network*)",
        "(allow process-exec (literal %s))" % _q(entry["executable"]),
        "(allow file-read-metadata)",
        '(allow file-read* (literal "/") ' + " ".join(readable) + ")",
        "(allow file-write* (subpath %s))" % _q(output_dir),
        "(deny file-write-flags)",  # no 'immutable' flag: a file a tool cannot be asked to change would also resist cleanup
        "",
    ])


def force_remove(path):
    """Remove a folder a tool wrote in, whatever modes the tool gave its folders. The modes are restored first
    (without following links), because a folder with no permissions cannot be listed or emptied."""
    def unlock(p):
        try:
            os.lchflags(p, 0)  # an 'immutable' flag stops a file being changed or removed, even by its owner
        except (OSError, AttributeError):
            pass

    stack = [path]
    while stack:
        current = stack.pop()
        try:
            unlock(current)
            if not stat.S_ISDIR(os.lstat(current).st_mode):
                continue
            os.chmod(current, 0o700)
            with os.scandir(current) as it:
                for e in it:
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
                    else:
                        unlock(e.path)
        except OSError:
            continue
    shutil.rmtree(path, ignore_errors=True)


def _inventory(root, limit):
    """Everything under a tool's output folder, as (relative path, kind, size), without following links. Refuses at once
    a link, a pipe or other odd file, a folder that cannot be listed, and more than the limits allow of files, folders,
    depth or bytes, so a hostile tool can neither hide data from the limits nor make the walk itself long."""
    entries, files, dirs, total = [], 0, 0, 0
    stack = [("", 0)]
    while stack:
        rel_dir, depth = stack.pop()
        try:
            with os.scandir(os.path.join(root, rel_dir) if rel_dir else root) as it:
                # at most as many entries as the limits allow, so a folder of millions of empty files is not listed whole;
                # a folder with more than this is over a limit whatever its entries are
                children = list(itertools.islice(it, MAX_FILES + MAX_DIRS + 2))
        except OSError:
            raise ToolError("the tool left a folder that cannot be listed: "
                            + (textutil.literal(rel_dir) if rel_dir else "(its output folder)")) from None
        for child in children:
            rel = f"{rel_dir}/{child.name}" if rel_dir else child.name
            shown = textutil.literal(rel)  # names are chosen by the tool: never put one in a message raw
            mode = child.stat(follow_symlinks=False).st_mode
            if stat.S_ISLNK(mode):
                raise ToolError(f"the tool left a symlink in its output: {shown}")
            if stat.S_ISDIR(mode):
                dirs += 1
                if depth + 1 > MAX_DEPTH:
                    raise ToolError(f"the tool nested its folders too deep (more than {MAX_DEPTH} levels): {shown}")
                if dirs > MAX_DIRS:
                    raise ToolError(f"the tool made more than {MAX_DIRS} folders")
                entries.append((rel, "dir", 0))
                stack.append((rel, depth + 1))
            elif stat.S_ISREG(mode):
                files += 1
                total += child.stat(follow_symlinks=False).st_size
                if files > MAX_FILES or total > limit:
                    raise ToolError(f"the tool wrote more than the output limit ({limit} bytes, {MAX_FILES} files)")
                entries.append((rel, "file", child.stat(follow_symlinks=False).st_size))
            else:
                raise ToolError(f"the tool left something that is not a plain file: {shown}")
    return entries


def _drain(stream, cap, box, key):
    """Read a pipe to its end into box[key], keeping at most `cap` bytes and noting at once if there was more."""
    buf = bytearray()
    box[key + "_over"] = False
    while True:
        chunk = stream.read1(65536)  # what has arrived, so an endless stream is noticed as it grows
        if not chunk:
            break
        if len(buf) < cap + 1:
            buf += chunk[: cap + 1 - len(buf)]
        if len(buf) > cap:
            box[key + "_over"] = True  # set at once: the caller stops the tool without waiting for the stream to end
    box[key] = bytes(buf[:cap])


def _collect(output_dir, limit):
    """The files a tool left, as {relative name: bytes}, after checking every name and every file."""
    files = {}
    for rel, kind, _size in _inventory(output_dir, limit):
        if kind != "file":
            continue
        shown = textutil.literal(rel)  # a name the tool chose: never put one in a message raw
        try:
            incoming.clean_rel(rel)
        except KbError:
            raise ToolError(f"the tool left a file with an unusable name: {shown}") from None
        if len(rel) > 200 or not all(_NAME.fullmatch(part) for part in rel.split("/")):
            raise ToolError("the tool left a file with a name that is not plain letters, digits, dot, dash and "
                            f"underscore, or is too long: {shown}")
        path = os.path.join(output_dir, *rel.split("/"))
        try:  # opened without following a link and without waiting, then checked on the open file
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError as e:
            raise ToolError(f"the tool's output file {shown} cannot be read: {e.strerror}") from None
        with os.fdopen(fd, "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                raise ToolError(f"the tool left something that is not a plain file: {shown}")
            files[rel] = f.read(limit + 1)
    return files


def _clean(text, limit):
    return textutil.clean(text, limit, tail=True)


def run(entry, input_dir, output_dir, cfg=None):
    """Run an approved tool on `input_dir`, writing into the empty folder `output_dir`. Returns the files it made.

    Refuses a tool whose files changed since it was approved, or whose readable folders reach the config or the
    library. Raises ToolError for a failure, an overrun or an unacceptable output."""
    entry = approvals.validate_entry(entry)
    cfg = config.load() if cfg is None else cfg
    approvals.check_pins(entry)
    approvals.check_reads(entry, cfg)
    input_dir, output_dir = os.path.realpath(input_dir), os.path.realpath(output_dir)
    if not os.path.isdir(input_dir):
        raise KbError(f"the tool's input is not a folder: {input_dir}")
    if not os.path.isdir(output_dir) or os.listdir(output_dir):
        raise ToolError(f"the tool's output folder is missing or not empty: {output_dir}")
    profile = build_profile(entry, input_dir, output_dir)
    command = [SANDBOX, "-p", profile] + [a.replace("{input}", input_dir).replace("{output}", output_dir)
                                          for a in entry["command"]]
    timeout, limit = float(entry["timeout"]), int(entry["max_output"])
    env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C.UTF-8", "TMPDIR": output_dir}
    label = f"{entry['name']} {entry['version']}"

    def limits():
        resource.setrlimit(resource.RLIMIT_FSIZE, (limit + 1, limit + 1))
        resource.setrlimit(resource.RLIMIT_CPU, (int(timeout) + 5, int(timeout) + 5))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    started = time.monotonic()
    try:
        proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=output_dir, env=env, start_new_session=True, preexec_fn=limits)
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        raise ToolError(f"{label} could not be started: {getattr(e, 'strerror', None) or e}") from None
    box = {}
    readers = [threading.Thread(target=_drain, args=(proc.stdout, limit, box, "stdout"), daemon=True),
               threading.Thread(target=_drain, args=(proc.stderr, STDERR_CAP, box, "stderr"), daemon=True)]
    for t in readers:
        t.start()
    dog = None
    try:
        # A watchdog outside the sandbox kills the tool's process group if this program dies, however it dies, or if the
        # tool is still running ten seconds after its limit. It is told "done" when the run ends normally. A run whose
        # watchdog did not start and say so is stopped: the tool must not run unguarded.
        try:
            dog = subprocess.Popen([sys.executable, "-I", "-S", SUPERVISOR, str(proc.pid), str(timeout + 10)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   start_new_session=True, close_fds=True)
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            raise ToolError(f"{label} was stopped: its watchdog could not be started: {e}") from None
        ready, _, _ = select.select([dog.stdout], [], [], 5)
        line = dog.stdout.readline() if ready else b""
        dog.stdout.close()
        if line != b"ready\n":
            raise ToolError(f"{label} was stopped: its watchdog did not start")
        last_walk = 0.0
        while proc.poll() is None:
            now = time.monotonic()
            if now - started > timeout:
                raise ToolError(f"{label} timed out after {entry['timeout']} seconds")
            if box.get("stdout_over"):
                raise ToolError(f"{label} wrote more than the output limit ({limit} bytes) on its standard output")
            if now - last_walk > 0.1:
                last_walk = now
                try:
                    _inventory(output_dir, limit)
                except ToolError as e:
                    raise ToolError(f"{label}: {e}") from None
            time.sleep(POLL)
    finally:
        if proc.poll() is None:  # still ours: nothing it started may outlive it. (A reaped group id could be reused.)
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        proc.wait()
        for t in readers:
            t.join(5)
        proc.stdout.close()
        proc.stderr.close()
        if dog is not None:
            try:  # the tool is gone: tell the watchdog it can stop, and make sure it has
                dog.stdin.write(b"done\n")
                dog.stdin.close()
            except OSError:
                pass
            try:
                dog.wait(timeout=5)
            except subprocess.TimeoutExpired:
                dog.kill()
                dog.wait()
    seconds = time.monotonic() - started
    stdout, stderr = box.get("stdout", b""), box.get("stderr", b"").decode("utf-8", "replace")
    if box.get("stdout_over"):
        raise ToolError(f"{label} wrote more than the output limit ({limit} bytes) on its standard output")
    if proc.returncode != 0:
        tail = _clean(stderr, 300)
        raise ToolError(f"{label} exited with status {proc.returncode}"
                        + (f"; its error output, which is untrusted, said: {tail}" if tail else ""))
    try:
        return Result(_collect(output_dir, limit), stdout, stderr, seconds)
    except ToolError as e:
        raise ToolError(f"{label}: {e}") from None


def run_to_payload(store, book_id, version_id, entry, payload_name, input_payload="original"):
    """Run an approved tool on a payload of a version and file its output as a derived payload, marked untrusted.

    The tool writes into a scratch folder in the incoming area; that folder is removed whatever happens, and the
    files it held are filed through `Store.file_payload`, so a stop at any point leaves no half-filed payload."""
    store._guard()
    input_dir = store.payload_dir(book_id, version_id, input_payload)
    if input_dir is None:
        raise KbError(f"there is no {input_payload} payload to run the tool on")
    scratch = incoming.make_dir(store.bulk)
    try:
        result = run(entry, input_dir, scratch)
    finally:
        force_remove(scratch)
    if not result.files:
        raise ToolError(f"{entry['name']} {entry['version']} produced no output")
    return store.file_payload(book_id, version_id, payload_name, result.files,
                              tool=f"{entry['name']} {entry['version']}", untrusted=True)
