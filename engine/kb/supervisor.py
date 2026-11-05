"""The watchdog for one tool run: a tiny program, outside the sandbox, that makes sure a tool cannot outlive the engine.

    python -I -S supervisor.py TOOL_PID SECONDS

The engine starts it beside the tool and keeps a pipe to its standard input. It kills the tool's process group when

  - the pipe closes without the engine having said "done" (the engine died, however it died), or
  - SECONDS have passed (the engine's own time limit failed to stop the tool).

When the engine says "done" it exits and does nothing. It reads nothing from the tool and trusts nothing but that pipe."""
import os
import select
import signal
import sys
import time


EXIT_DONE, EXIT_ENGINE_GONE, EXIT_TIME_UP = 0, 3, 4  # how it ended: told done, the pipe closed without it, the time passed


def kill_group(pid):
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def main(argv):
    pid, seconds = int(argv[1]), float(argv[2])
    started = time.monotonic()
    sys.stdout.write("ready\n")  # the engine waits for this word before it trusts the tool to run
    sys.stdout.flush()
    sys.stdout.close()
    while True:
        remaining = seconds - (time.monotonic() - started)
        if remaining <= 0:
            kill_group(pid)
            return EXIT_TIME_UP
        ready, _, _ = select.select([0], [], [], min(remaining, 1.0))
        if ready:
            data = os.read(0, 64)
            if data == b"":  # the pipe closed with no word from the engine: it is gone
                kill_group(pid)
                return EXIT_ENGINE_GONE
            if b"done" in data:
                return EXIT_DONE


if __name__ == "__main__":
    sys.exit(main(sys.argv))
