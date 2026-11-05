"""Identity: the keys that say two captures are the same source, and a small index to look them up before a download.

A web page is known by its canonical address and by the hash of its raw bytes. A book's root file keeps its keys
(`url`, `url_alias`, `sha256`), and this module keeps an index of them in the index root so a duplicate check does not
read every book. The index can be thrown away and rebuilt from the books."""
import os
import sqlite3
from contextlib import closing
from urllib.parse import urlsplit

from . import KbError

DEFAULT_PORT = {"http": 80, "https": 443}


def normalize_address(address):
    """The canonical form of a web address, or a refusal: http or https only, a host, no credentials, no whitespace
    or control characters; the scheme and host in lower case, the default port and the fragment dropped."""
    if not isinstance(address, str):
        raise KbError("an address must be text")
    text = address.strip()
    if not text:
        raise KbError("an address is empty")
    if any(ord(c) < 33 or ord(c) == 127 for c in text):
        raise KbError(f"the address has whitespace or control characters: {text!r}")
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError as e:
        raise KbError(f"not a usable address: {e}") from None
    scheme = parts.scheme.lower()
    if scheme not in DEFAULT_PORT:
        raise KbError(f"only http and https addresses are captured, not {scheme or 'a bare name'!r}")
    if parts.username is not None or parts.password is not None:
        raise KbError("the address carries a user name or password; remove it so no secret is stored")
    host = parts.hostname
    if not host:
        raise KbError("the address has no host")
    if port == 0:
        raise KbError("port 0 is not a usable port")
    shown = f"[{host.lower()}]" if ":" in host else host.lower()
    if port is not None and port != DEFAULT_PORT[scheme]:
        shown += f":{port}"
    return f"{scheme}://{shown}{parts.path or '/'}" + (f"?{parts.query}" if parts.query else "")


class Identity:
    """An index of identity keys in the index root: (kind, value) -> book id. The first book to claim a key keeps it."""

    def __init__(self, index_root):
        self.path = os.path.join(index_root, "identity.sqlite")
        self._run("CREATE TABLE IF NOT EXISTS identity ("
                  "kind TEXT NOT NULL, value TEXT NOT NULL, book_id TEXT NOT NULL, PRIMARY KEY (kind, value))")

    def _run(self, sql, args=(), fetch=False):
        with closing(sqlite3.connect(self.path, timeout=30)) as conn:
            with conn:
                cur = conn.execute(sql, args)
                return cur.fetchall() if fetch else None

    def lookup(self, kind, value):
        rows = self._run("SELECT book_id FROM identity WHERE kind = ? AND value = ?", (kind, value), fetch=True)
        return rows[0][0] if rows else None

    def register(self, kind, value, book_id):
        self._run("INSERT OR IGNORE INTO identity (kind, value, book_id) VALUES (?, ?, ?)", (kind, value, book_id))

    def reassign(self, kind, value, book_id):
        """Point a key at another book, for an address that turned out to belong to an earlier book."""
        self._run("INSERT OR REPLACE INTO identity (kind, value, book_id) VALUES (?, ?, ?)", (kind, value, book_id))

    def rebuild(self, store):
        """Throw the index away and rebuild it from the root files of the books that are active."""
        self._run("DELETE FROM identity")
        for book_id in store.list_books():
            root = store.read_book(book_id)
            if root.get("state") != "active":
                continue
            keys = root.get("identity_keys", {})
            urls = ([keys["url"]] if isinstance(keys.get("url"), str) else []) + list(keys.get("url_alias", []))
            for value in urls:
                self.register("url", value, book_id)
            for value in keys.get("sha256", []):
                self.register("sha256", value, book_id)
