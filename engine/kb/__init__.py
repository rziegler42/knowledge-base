"""The knowledge-base engine: a library of sources on disk, kept apart from the workbench."""

__version__ = "0.0.2"  # the plain extractor's label too: raised when extract_std.py changes (the scan tool has its own, in approvals)


class KbError(Exception):
    """A refusal. The message is the reason, written for the owner to read."""
