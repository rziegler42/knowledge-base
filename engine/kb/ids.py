"""Book ids: a ULID, which is unique and sorts by time, and is generated once when a book is filed.

A ULID is 128 bits written as 26 characters of Crockford base32: 48 bits of milliseconds since the epoch, then
80 random bits. The id is namespaced by the library id by the root file, and `qualified` gives the form that names
both when an id has to cross libraries."""
import os
import re
import time

from . import KbError

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ID = re.compile(r"[0-7][0-9A-HJKMNP-TV-Z]{25}")


def new_book_id(now_ms=None, rand=None):
    ts = int(time.time() * 1000) if now_ms is None else now_ms
    if not 0 <= ts < 1 << 48:
        raise KbError("the time for a book id is out of range")
    r = int.from_bytes(os.urandom(10), "big") if rand is None else rand
    n = (ts << 80) | (r & ((1 << 80) - 1))
    chars = []
    for _ in range(26):
        chars.append(ALPHABET[n & 31])
        n >>= 5
    return "".join(reversed(chars))


def check_id(book_id):
    """Return the id if it has the shape of a book id; otherwise refuse. Every path is built from a checked id."""
    if not isinstance(book_id, str) or not _ID.fullmatch(book_id):
        raise KbError(f"not a book id: {book_id!r}")
    return book_id


def shard(book_id):
    """Books are sharded by the end of the id, because the start of a ULID is a timestamp and would put every
    new book in the same folder."""
    return check_id(book_id)[-2:]


def qualified(library_id, book_id):
    return f"{library_id}/{check_id(book_id)}"
