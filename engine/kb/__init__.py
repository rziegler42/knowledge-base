"""The knowledge-base engine: a library of sources on disk, kept apart from the workbench."""

__version__ = "0.0.2"  # raised when a tool script changes: the tool labels carry it


class KbError(Exception):
    """A refusal. The message is the reason, written for the owner to read."""
