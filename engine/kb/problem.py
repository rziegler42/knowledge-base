"""Pose a problem to the search by meaning: one to five sub-problems, each searched by meaning, and one merged list of books.

An agent that has put a problem in general terms and split it into sub-problems gives them here. Each is searched with `vectors.search`
(so each is sent, with the query prefix of the config, to the embedding model that the config sets for `card-embed`, and to nothing
else), and the reply holds, for each sub-problem, its ranked books (book id, version, rank, score) and one list in which each book is held
once: its best result, without the text of the whole card (the card is read with `card-show`, the book with `read`), and `found_by`,
the sub-problems that returned it with the rank and the score each gave. The books are ordered by their best score, then by book id.

Nothing is set aside by field here: no card says which field a book belongs to, so the agent does that from the title in the citation and
the matched text. The reply is data from outside, marked like every result of the library: each entry's excerpt carries the untrusted-text
marker and the entry says `untrusted`.

The reply is measured as it will be printed, and one of more than `MAX_REPLY` characters is refused before anything is printed, because the
helper that an agent calls cuts what it reads at 65,536 characters and a cut reply is not valid JSON.
"""

import json
import os

from . import KbError, vectors

MAX_SUB_PROBLEMS = 5
MAX_SUB_CHARS = 1000
DEFAULT_LIMIT = 5
MAX_LIMIT = 10
MAX_REPLY = 61000  # characters of the printed reply; the helper reads at most 65,536
_SAME = ("model", "query_prefix", "cards_searched", "stale", "without_vector")  # what every search of one reply must agree on


def _sub_problems(subs):
    if type(subs) is not list:
        raise KbError("the sub-problems must be a list of texts")
    if not 1 <= len(subs) <= MAX_SUB_PROBLEMS:
        raise KbError(f"give from 1 to {MAX_SUB_PROBLEMS} sub-problems")
    for sub in subs:
        if not isinstance(sub, str):
            raise KbError("a sub-problem must be text")
        if len(sub) > MAX_SUB_CHARS:
            raise KbError(f"a sub-problem is at most {MAX_SUB_CHARS} characters")
        if not sub.strip():
            raise KbError("a sub-problem has no text to look for")
        try:
            sub.encode("utf-8")
        except UnicodeEncodeError:
            raise KbError("a sub-problem holds a character that cannot be sent") from None
    return subs


def _limit(limit):
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise KbError(f"the limit must be a whole number from 1 to {MAX_LIMIT}")
    return limit


def _launcher(path):
    if path is None:
        return None
    if not isinstance(path, str) or not os.path.isabs(path) or not os.path.isfile(path) or not os.access(path, os.X_OK):
        raise KbError("the launcher must be the absolute path of an executable file")
    return path


def search(index_root, cfg, sub_problems, limit=DEFAULT_LIMIT, launcher=None, root=None):
    """Search by meaning for each sub-problem (one to five texts of at most 1000 characters) and merge. Returns
    `{"meaning", "model", "query_prefix", "cards_searched", "stale", "without_vector", "sub_problems", "books"}`: `sub_problems` lists, in
    the order given, `{"sub_problem": n, "books": [{"book_id", "version_id", "rank", "score"}]}` and `books` lists each book once, as the
    result of a search by meaning without its `text`, with `found_by` (`{"sub_problem", "rank", "score"}` for each sub-problem that
    returned it); its `score` is the best of those. `limit` (1 to 10) is the number of books asked of each sub-problem. Everything that can be
    refused is refused before the first sub-problem is sent: the count, the length and the text of the sub-problems, the limit, the
    launcher, and (by `vectors.search`, at the first) a missing, stale-format or foreign file of vectors. One search that fails fails
    all, and nothing partial is returned. Only the sub-problems go to the model."""
    subs = _sub_problems(sub_problems)
    limit = _limit(limit)
    launcher = _launcher(launcher)
    first = None
    listed, merged = [], {}
    for n, sub in enumerate(subs, 1):
        got = vectors.search(index_root, cfg, sub, limit=limit, launcher=launcher, root=root)
        if first is None:
            first = got
        elif any(got[key] != first[key] for key in _SAME):
            raise KbError("the cards or the vectors changed while the sub-problems were searched; search again")
        books = []
        for rank, result in enumerate(got["results"], 1):
            key = (result["book_id"], result["version_id"])
            books.append({"book_id": key[0], "version_id": key[1], "rank": rank, "score": result["score"]})
            entry = merged.get(key)
            find = {"sub_problem": n, "rank": rank, "score": result["score"]}
            if entry is None:
                merged[key] = {**{k: v for k, v in result.items() if k != "text"}, "found_by": [find]}
            else:
                entry["found_by"].append(find)
                if result["score"] > entry["score"]:  # the best result, and so its excerpt and the field that matched, is the larger score
                    entry.update({k: v for k, v in result.items() if k != "text"})
        listed.append({"sub_problem": n, "books": books})
    ordered = sorted(merged.values(), key=lambda e: (-e["score"], e["book_id"], e["version_id"]))
    return {"meaning": True, "model": first["model"], "query_prefix": first["query_prefix"], "cards_searched": first["cards_searched"],
            "stale": first["stale"], "without_vector": first["without_vector"], "sub_problems": listed, "books": ordered}


def render(reply):
    """The reply as the command prints it, or `KbError` if it is longer than `MAX_REPLY` characters (nothing is printed then)."""
    text = json.dumps(reply, indent=1)
    if len(text) > MAX_REPLY:
        raise KbError(f"the reply would be {len(text)} characters, more than the {MAX_REPLY} that can be passed on; "
                      f"use a lower --limit or fewer sub-problems")
    return text
