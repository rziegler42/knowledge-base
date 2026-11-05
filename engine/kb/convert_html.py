"""The HTML converters: two extractors that run as approved tools in the sandbox, and the entries that describe them.

    kb-html-std    the plain extractor (`extract_std.py`): the Python standard library with a tag skip list
    trafilatura    an article extractor (`extract_traf.py`), run with the packages pinned in `engine/requirements.lock`

Both read `page.html` from the input folder and write `blocks.json`; what they write is checked by `convert`.
Run `python3 -m kb describe-tool kb-html-std` (or `trafilatura`) to print the entry to review and paste into
`approved_tools` in the config. The engine never approves anything itself."""
import glob
import os
import re
import sys

from . import KbError, __version__, approvals

STD_NAME = "kb-html-std"
TRAF_NAME = "trafilatura"
TRAF_LIBRARY = "2.3.1"  # the version `extract_traf.py` insists on (EXPECTED there) and `requirements.lock` pins
TRAF_VERSION = f"{TRAF_LIBRARY}-kb1"  # the number after kb is the revision of our wrapper and its settings: raise it when they change
HERE = os.path.dirname(os.path.abspath(__file__))
VENV = os.path.join(os.path.dirname(HERE), ".venv")


def std_entry():
    """The approved-list entry for the plain extractor, run by the interpreter that runs the engine."""
    exe, prefix = approvals.python_runtime()
    script = os.path.join(HERE, "extract_std.py")
    # -I and -S as for the scan: no environment, no user site, and no `site` module, so nothing in the runtime folder runs at
    # start-up. The extractor needs only the standard library.
    return approvals.describe(STD_NAME, __version__, [exe, "-I", "-S", script, "{input}", "{output}"], reads=[prefix],
                              formats=["html"], timeout=60, max_output=30_000_000, pin=[script])


def venv_site(venv=VENV):
    """The folder of the pinned packages in the environment built from `requirements.lock`, as a real path. Refuses an
    environment that is missing, was built by another Python than the one that runs the engine, or has an odd layout."""
    cfg = os.path.join(venv, "pyvenv.cfg")
    try:
        with open(cfg) as f:
            text = f.read(10_000)
    except OSError:
        raise KbError(f"there is no Python environment at {venv}: build it with `python3 -m venv engine/.venv` and "
                      "`engine/.venv/bin/python -m pip install --require-hashes --no-deps -r engine/requirements.lock`") from None
    found = re.search(r"^version\s*=\s*(\d+)\.(\d+)", text, re.M)
    if not found or (int(found.group(1)), int(found.group(2))) != tuple(sys.version_info[:2]):
        raise KbError(f"the environment at {venv} was not built by this Python ({sys.version_info[0]}.{sys.version_info[1]}); rebuild it")
    sites = sorted(p for p in glob.glob(os.path.join(glob.escape(venv), "lib", "python*", "site-packages")) if os.path.isdir(p))
    if len(sites) != 1 or os.path.basename(os.path.dirname(sites[0])) != f"python{sys.version_info[0]}.{sys.version_info[1]}":
        raise KbError(f"the environment at {venv} does not have exactly one site-packages folder for this Python")
    return os.path.realpath(sites[0])


def trafilatura_entry(venv=VENV):
    """The approved-list entry for the article extractor: the engine's interpreter, the wrapper, and the pinned packages."""
    exe, prefix = approvals.python_runtime()
    script = os.path.join(HERE, "extract_traf.py")
    site = venv_site(venv)
    # The packages are a runtime folder, readable but not pinned file by file: they are fixed by the hashes in
    # requirements.lock when the environment is built, not checked again each time a page is converted.
    return approvals.describe(TRAF_NAME, TRAF_VERSION, [exe, "-I", "-S", script, site, "{input}", "{output}"],
                              reads=sorted({prefix, site}), formats=["html"], timeout=120, max_output=30_000_000, pin=[script])
