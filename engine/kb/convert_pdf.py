"""The PDF converter: poppler's `pdftotext`, run as an approved tool in the sandbox, and the entry that describes it.

    pdftotext -q -enc UTF-8 -eol unix {input}/paper.pdf {output}/text.txt

It writes the text of the PDF with a form feed at the end of each page, which `convert.parse_paged_text` cuts into pages and
paragraphs. The program is a Homebrew build whose libraries live in other packages; the entry names the folder of each of those
packages, found by reading the program's load commands, so the sandbox lets it read those and nothing else. Run `python3 -m kb describe-tool pdftotext` to print the entry to review and paste into
`approved_tools` in the config. The engine never approves anything itself."""
import os
import re
import shutil
import subprocess

from . import KbError, approvals

NAME = "pdftotext"
REVISION = "kb1"  # raised when the options of the command below change
OTOOL = "/usr/bin/otool"
SYSTEM = ("/usr/lib/", "/System/")
_VERSION = re.compile(r"version\s+(\d+(?:\.\d+)*)")


def _otool(flag, path):
    try:
        done = subprocess.run([OTOOL, flag, path], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        raise KbError(f"cannot read the libraries of {path}: {getattr(e, 'strerror', None) or e}") from None
    if done.returncode != 0:
        raise KbError(f"cannot read the libraries of {path}: otool said {done.stderr.strip()[:200]}")
    return done.stdout


def libraries(exe):
    """Every non-system library the program loads, directly or through another, by the name it is asked for (which may be a
    link, such as /opt/homebrew/opt/freetype/lib/...; `readable_folders` follows it to the package it leads to)."""
    names, seen, todo = [], set(), [exe]
    while todo:
        current = todo.pop()
        if current in seen:
            continue
        seen.add(current)
        rpaths = re.findall(r"cmd LC_RPATH\n\s+cmdsize \d+\n\s+path (\S+)", _otool("-l", current))
        for line in _otool("-L", current).splitlines()[1:]:
            name = line.strip().split(" (")[0]
            if name.startswith(SYSTEM):
                continue
            if name.startswith("@rpath/"):
                options = [os.path.join(r.replace("@loader_path", os.path.dirname(current))
                                        .replace("@executable_path", os.path.dirname(exe)), name[7:]) for r in rpaths]
            elif name.startswith("@loader_path/"):
                options = [os.path.join(os.path.dirname(current), name[13:])]
            elif name.startswith("@executable_path/"):
                options = [os.path.join(os.path.dirname(exe), name[17:])]
            else:
                options = [name]
            found = [o for o in options if os.path.exists(o)]
            if not found:
                raise KbError(f"{current} needs {name}, which is not here, so it cannot be set up for the sandbox")
            names.append(os.path.normpath(found[0]))
            todo.append(os.path.realpath(found[0]))
    return names


_CELLAR = re.compile(r"(/(?:opt/homebrew|usr/local)/Cellar/[A-Za-z0-9@._+-]+/[A-Za-z0-9@._+-]+)/.+")


def _root_of(path):
    """The folder a file's package lives in: <prefix>/Cellar/<package>/<version>. Only Homebrew packages are described: a file
    anywhere else would have its whole folder (a `lib`, a `bin`, a home folder) put on the list of folders to read."""
    found = _CELLAR.fullmatch(path)
    if not found:
        raise KbError(f"{path} is not in a Homebrew package folder (<prefix>/Cellar/<package>/<version>); only a Homebrew "
                      "poppler can be described")
    return found.group(1)


def readable_folders(exe):
    """The folders the program must be able to read: its own package and the package of each library it loads."""
    return sorted({_root_of(exe)} | {_root_of(os.path.realpath(name)) for name in libraries(exe)})


def pdftotext_entry(exe=None):
    """The approved-list entry for the pdftotext found on the path (or at `exe`), with the exact version it reports."""
    found = exe or shutil.which("pdftotext")
    if not found:
        raise KbError("pdftotext was not found: install poppler (brew install poppler)")
    exe = os.path.realpath(found)
    _root_of(exe)  # refuses a program that is not a Homebrew one, before anything is run
    try:
        said = subprocess.run([exe, "-v"], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        raise KbError(f"pdftotext cannot be run: {getattr(e, 'strerror', None) or e}") from None
    version = _VERSION.search(said.stderr + said.stdout)
    if not version:
        raise KbError("pdftotext did not say which version it is")
    command = [exe, "-q", "-enc", "UTF-8", "-eol", "unix", "{input}/paper.pdf", "{output}/text.txt"]
    return approvals.describe(NAME, f"{version.group(1)}-{REVISION}", command, reads=readable_folders(exe),
                              formats=["pdf"], timeout=120, max_output=50_000_000)
