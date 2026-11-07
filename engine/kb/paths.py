"""The rule for files that are held outside the repository: the corpus and report of a trial, and the sample of card items to be
labelled. A path is refused if it is, or lies under, the project's own folder (links followed)."""
import os

from . import KbError, models


def inside_project(path):
    """True if `path`, with its links resolved, is the project's folder or lies under it."""
    real = os.path.realpath(path)
    root = os.path.realpath(models._project_root())
    return real == root or real.startswith(root + os.sep)


def require_outside(path, what):
    """Refuse a path that is empty, is not text, or is, or lies under, the project's own folder."""
    if not isinstance(path, str) or not path:
        raise KbError(f"{what} must be a path")
    if inside_project(path):
        raise KbError(f"{what} is inside the project's own folder; the files of a trial are held outside the repository")
