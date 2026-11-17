"""The text of the scheduler of the unattended crawl (`docs/specs/population.md`, "Scheduling"; the plan `2026-11-16-run-the-steps-of-the-unattended-crawl`, Increment N).

`text(index_root, engine_dir, python)` is the text of a macOS launchd agent that starts one run of the unattended crawl every 900 seconds: `python3 -X pycache_prefix=<index root>/crawl-pycache -m kb crawl-run`, with the
engine folder as its working folder (where `kb` can be imported: `python3 -m kb` is run from `engine/`, as `engine/README.md` runs every command), and the agent's own output (standard output and standard error)
in one file under the index root, `crawl-agent.log`, which is not in the crawl's log (`<index root>/crawl/log/`). The agent has no other key: it does not run at load, is not kept alive, sets no environment and no
user. A firing while a run is going exits at once (the run lock), which is why the interval is the only thing that schedules it.

The text is **only printed**. This module, and the command that prints it, write no file, make no folder, load no config of their own, read no environment variable, start no process and make no request: the index
root and the engine folder are given as arguments, as text, and nothing is looked at on disk. Installing the agent, and making the bytecode folder private (mode 700, a folder of the owner's, outside the engine's
code, as `crawlrun.prefix_problem` requires), are the owner's acts; the text says so in a comment before the property list, and the README's checklist of the supervised run says so again.

A path is refused, with a plain reason that never shows the path, when it is not text, is empty or only slashes, has a control character or a line break, has a character that cannot be seen (a direction mark, a zero
width space), is not a full path, or has two hyphens in a row (which cannot stand in an XML comment); the index root must also leave the engine folder and the bytecode folder apart, since the bytecode folder must be
outside the engine's code. A value is escaped for the property list format before it is printed."""
import unicodedata

from . import KbError

LABEL = "local.knowledge-base.crawl-run"
INTERVAL = 900
PREFIX_NAME = "crawl-pycache"
OUTPUT_NAME = "crawl-agent.log"
PYTHON = "python3"

HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'


def _checked(value, what):
    """`value` if it is a safe full path, or `KbError` with a plain reason that does not show it."""
    if not isinstance(value, str):
        raise KbError(f"the {what} is not text")
    if not value.strip():
        raise KbError(f"the {what} is empty")
    kinds = {unicodedata.category(c) for c in value}
    if kinds & {"Cc", "Zl", "Zp"}:
        raise KbError(f"the {what} has a control character or a line break")
    if any(k.startswith("C") for k in kinds):
        raise KbError(f"the {what} has a character that cannot be seen, such as a direction mark")
    if not value.startswith("/"):
        raise KbError(f"the {what} is not a full path: it starts with a slash")
    if "--" in value:
        raise KbError(f"the {what} has two hyphens in a row, which the text cannot show")
    return value


def _folder(value, what):
    """A safe full path of a folder, with no slash at its end."""
    folder = _checked(value, what).rstrip("/")
    if not folder:
        raise KbError(f"the {what} is the top of the disk")
    return folder


def _program(value):
    if value == PYTHON:
        return value
    program = _checked(value, "python program")
    if program.endswith("/"):
        raise KbError("the python program is a file, not a folder")
    return program


def _xml(value):
    """`value` escaped for the text of an XML element (an ampersand first, then the angle brackets; quotes need no escape in element text)."""
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _apart(prefix, engine):
    """True if the bytecode folder is the engine folder or inside it, or holds it: the folder must be outside the engine's code."""
    return prefix == engine or prefix.startswith(engine + "/") or engine.startswith(prefix + "/")


def text(index_root, engine_dir, python=PYTHON):
    """The text of the launchd agent, for the index root and the engine folder (full paths, given as text) and the python program (`python3` or a full path). Refuses an unsafe path with `KbError`."""
    index = _folder(index_root, "index root")
    engine = _folder(engine_dir, "engine folder")
    program = _program(python)
    prefix = f"{index}/{PREFIX_NAME}"
    output = f"{index}/{OUTPUT_NAME}"
    if _apart(prefix, engine):
        raise KbError("the index root must be outside the engine folder, because the bytecode folder must be outside the engine's code")
    arguments = [program, "-X", f"pycache_prefix={prefix}", "-m", "kb", "crawl-run"]
    lines = [
        HEAD + "<!--",
        "  The agent of the unattended crawl: it starts one run of the crawl every %d seconds. This is only text: nothing here installs it." % INTERVAL,
        "  Before installing it, make this folder and make it private (mode 700), because a run refuses to start unless Python keeps its bytecode in a folder that only you can use:",
        "    " + prefix,
        "  The agent's own output goes to this file, which is outside the crawl's log:",
        "    " + output,
        "-->",
        '<plist version="1.0">',
        "<dict>",
        "  <key>Label</key>",
        f"  <string>{LABEL}</string>",
        "  <key>ProgramArguments</key>",
        "  <array>",
    ]
    lines += [f"    <string>{_xml(a)}</string>" for a in arguments]
    lines += [
        "  </array>",
        "  <key>WorkingDirectory</key>",
        f"  <string>{_xml(engine)}</string>",
        "  <key>StartInterval</key>",
        f"  <integer>{INTERVAL}</integer>",
        "  <key>StandardOutPath</key>",
        f"  <string>{_xml(output)}</string>",
        "  <key>StandardErrorPath</key>",
        f"  <string>{_xml(output)}</string>",
        "</dict>",
        "</plist>",
    ]
    return "\n".join(lines) + "\n"
