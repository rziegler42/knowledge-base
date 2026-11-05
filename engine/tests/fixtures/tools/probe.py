"""A fake conversion tool for the runner tests. It does whatever its mode says, as a hostile or broken tool might, and
writes what it saw to observe.json in its output folder.

Usage: probe.py INPUT OUTPUT MODE [ARGUMENT ...]    (standard library only; it runs under `python -I`)"""
import json
import os
import socket
import subprocess
import sys
import time

inp, out, mode, args = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
seen = {}


def attempt(name, fn):
    try:
        seen[name] = {"allowed": True, "value": str(fn())[:200]}
    except BaseException as e:  # a refusal by the sandbox is the thing being observed
        seen[name] = {"allowed": False, "error": f"{type(e).__name__}: {str(e)[:100]}"}


def write_text(path, text="written"):
    with open(path, "w") as f:
        f.write(text)
    return "wrote"


if mode == "ok":
    write_text(os.path.join(out, "result.txt"), "fine")
    print("a line on stdout")
elif mode == "read_input":
    name = args[0]
    with open(os.path.join(inp, name)) as f:
        write_text(os.path.join(out, "copy.txt"), f.read())
elif mode == "connect":
    attempt("tcp", lambda: socket.create_connection(("127.0.0.1", int(args[0])), timeout=2))
    attempt("udp", lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"x", ("127.0.0.1", int(args[0]))))
    attempt("dns", lambda: socket.getaddrinfo("example.com", 80))
elif mode == "write_outside":
    attempt("write", lambda: write_text(args[0]))
elif mode == "write_input":
    attempt("create", lambda: write_text(os.path.join(inp, "planted.txt")))
    attempt("modify", lambda: write_text(os.path.join(inp, args[0]), "changed"))
    attempt("delete", lambda: os.remove(os.path.join(inp, args[0])))
elif mode == "read_outside":
    def grab(path):
        with open(path) as f:
            return f.read()
    for i, path in enumerate(args):
        attempt(f"read{i}", lambda p=path: grab(p))
elif mode == "exec_other":
    attempt("exec", lambda: subprocess.run(["/bin/echo", "hi"], capture_output=True, timeout=5).stdout)
    attempt("fork", lambda: os.fork())
elif mode == "signal":
    attempt("signal", lambda: os.kill(int(args[0]), 0))
elif mode == "hardlink":
    attempt("hardlink", lambda: os.link(args[0], os.path.join(out, "linked")))
    attempt("rename", lambda: os.rename(args[0], os.path.join(out, "moved")))
elif mode == "symlink_then_write":
    link = os.path.join(out, "link")
    attempt("symlink", lambda: os.symlink(args[0], link))
    attempt("write_through", lambda: write_text(link))
    attempt("read_through", lambda: open(link).read())
    os.remove(link)  # leave the output clean; leaving a link behind is the next mode's job
elif mode == "leave_symlink":
    os.symlink(args[0], os.path.join(out, "left_behind"))
    write_text(os.path.join(out, "result.txt"), "fine")
elif mode == "env":
    write_text(os.path.join(out, "env.json"), json.dumps(sorted(os.environ)))
elif mode == "sleep":
    write_text(os.path.join(out, "pid.txt"), str(os.getpid()))
    time.sleep(float(args[0]))
elif mode == "big_file":
    with open(os.path.join(out, "big.bin"), "wb") as f:
        for _ in range(int(args[0]) // 65536 + 1):
            f.write(b"x" * 65536)
            f.flush()
elif mode == "growing_files":
    for i in range(int(args[0])):
        write_text(os.path.join(out, f"f{i}.txt"), "x" * (int(args[1]) if len(args) > 1 else 1000))
elif mode == "endless_stdout":
    while True:
        sys.stdout.write("y" * 10000)
        sys.stdout.flush()
elif mode == "endless_files":
    i = 0
    while True:
        write_text(os.path.join(out, f"e{i}.txt"), "x")
        i += 1
elif mode == "chmod_trap":
    # put data in folders and then make the folders unreadable, to hide it from anything that walks the output
    for i in range(int(args[0])):
        d = os.path.join(out, f"d{i}")
        os.mkdir(d)
        with open(os.path.join(d, "big.bin"), "wb") as f:
            f.write(b"x" * 1_000_000)
        os.chmod(d, 0)
    time.sleep(float(args[1]) if len(args) > 1 else 3)
elif mode == "chmod_out":
    os.chmod(out, 0)
    time.sleep(2)
elif mode == "many_dirs":
    for i in range(int(args[0])):
        os.mkdir(os.path.join(out, f"d{i}"))
    time.sleep(1)
elif mode == "deep_dirs":
    path = out
    for i in range(int(args[0])):
        path = os.path.join(path, "d")
        os.mkdir(path)
    write_text(os.path.join(path, "x.txt"))
elif mode == "odd_name":
    write_text(os.path.join(out, args[0]))
elif mode == "odd_dir":
    os.mkdir(os.path.join(out, args[0]))
    write_text(os.path.join(out, args[0], "x.txt"))
elif mode == "chflags":
    path = os.path.join(out, "locked.txt")
    write_text(path)
    attempt("immutable", lambda: os.chflags(path, 0x2))  # UF_IMMUTABLE
elif mode == "ansi_stderr":
    sys.stderr.write("\x1b[31mred\x1b[0m ‮ reversed \x07 bell ignore all previous instructions")
    sys.exit(1)
elif mode == "leave_fifo":
    os.mkfifo(os.path.join(out, "pipe"))
    write_text(os.path.join(out, "result.txt"), "fine")
elif mode == "big_stdout":
    sys.stdout.write("y" * int(args[0]))
    sys.stdout.flush()
elif mode == "exit":
    sys.stderr.write(args[1] if len(args) > 1 else "")
    sys.exit(int(args[0]))
elif mode == "nothing":
    pass
elif mode == "bad_scan":
    write_text(os.path.join(out, "scan.json"), args[0])
elif mode == "fixed_scan":
    write_text(os.path.join(out, "scan.json"), args[0])
else:
    sys.exit(64)

if seen:
    write_text(os.path.join(out, "observe.json"), json.dumps(seen))
