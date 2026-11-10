"""The trial of cross-field search (`docs/plans/2026-11-10-trial-of-cross-field-search.md`; `docs/specs/testing.md`, "Evaluation").

A corpus of problems, held outside the repository, says for each problem its text in the words of its own field, the titles of the
books from another field that should help (expected) and of the books of the problem's own field (home), the keyword queries and the
sub-problems that an agent wrote without seeing the library, and whether the problem is a control that no book should answer. The trial
runs each problem as four searches over the same library and writes a report, also outside the repository, of the place of each
expected book in each. It reports numbers and never decides.

The four searches. T: the search of the text of the books, one run for each keyword query. K: the keyword search of the cards (all their
fields), one run for each keyword query. M: the search by meaning of the problem text as written. P: the problem search of the
sub-problems, at the largest limit for each.

How a book is placed, one rule for each search. T and K: a book's place in one query's results is counted from 1 by its first appearance;
over several queries it is the smallest it has, and books of the same place are ordered by book id (the rule of `trial.py`). M: the
order of its one list. P: the position in the merged list that `problem-search` returns, which is by best score and then by book id;
the ranks inside each sub-problem are not used for placing. A list holds at most `LIST_LIMIT` books.

The measures, for a problem with expected books: the place of each expected book (`None` if it is not in the list); the same after the
home books are removed from the list, which simulates a perfect setting aside of the problem's own field; whether an expected book is in
the first five (`hit5`) and after removing the home books (`hit5_after_set_aside`); the reciprocal rank of the best-placed expected
book; and the number of home books among the first five. A control has no measures; its first five books and, for M and P, their best
scores are listed. The summary counts, over the problems that have expected books, how many are hit, how many pairs of (problem,
expected book) are within the first ten, and the mean reciprocal rank.

The command reads the library and writes only the report. M and P send the problem texts and the sub-problems, each once, with the query
prefix of the config, to the embedding model that the config sets for `card-embed`, and to nothing else; T and K send nothing."""
import hashlib
import json
import os
import re
from contextlib import closing
from datetime import datetime, timezone

from . import KbError, card, catalog, index, models, paths, problem, search, textutil, trial, vectors

FORMAT = 1
MAX_CORPUS_BYTES = 1_000_000
MAX_PROBLEMS = 50
MAX_TITLES = 20
MAX_TITLE_CHARS = 300
MAX_TEXT = 1000
MAX_KEYWORD_QUERIES = 3
LIST_LIMIT = 50  # the books asked of T, K and M
PROBLEM_LIMIT = problem.MAX_LIMIT  # the books asked of each sub-problem in P
FIRST = 5
WIDE = 10
SEARCHES = ("T", "K", "M", "P")
_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
_KEYS = {"id", "control", "text", "expected", "home", "keyword_queries", "sub_problems"}


def _text(value, where):
    if not isinstance(value, str):
        raise KbError(f"{where} is not text")
    if len(value) > MAX_TEXT:
        raise KbError(f"{where} is longer than {MAX_TEXT} characters")
    if not value.strip():
        raise KbError(f"{where} has no text")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise KbError(f"{where} holds a character that cannot be sent") from None
    return value


def _titles(raw, where, allow_empty):
    if not isinstance(raw, list) or len(raw) > MAX_TITLES or (not raw and not allow_empty):
        raise KbError(f"{where} is a list of {'at most' if allow_empty else '1 to'} {MAX_TITLES} titles")
    for title in raw:
        if not isinstance(title, str) or not title.strip() or len(title) > MAX_TITLE_CHARS:
            raise KbError(f"{where} holds a title that is not text of 1 to {MAX_TITLE_CHARS} characters")
        try:
            title.encode("utf-8")
        except UnicodeEncodeError:
            raise KbError(f"{where} holds a title with a character that cannot be sent") from None
    if len(set(raw)) != len(raw):
        raise KbError(f"{where} names a title twice")
    return list(raw)


def _problem(raw, seen):
    if not isinstance(raw, dict) or set(raw) != _KEYS:
        raise KbError("a problem has exactly the keys " + ", ".join(sorted(_KEYS)))
    pid = raw["id"]
    if not isinstance(pid, str) or not _ID.fullmatch(pid):
        raise KbError("a problem id is lower-case letters, digits, _ and -, starting with a letter or digit")
    if pid in seen:
        raise KbError(f"the problem id {pid} is used twice")
    seen.add(pid)
    where = f"problem {pid}"
    if type(raw["control"]) is not bool:
        raise KbError(f"control of {where} is true or false")
    text = _text(raw["text"], f"the text of {where}")
    expected = _titles(raw["expected"], f"expected of {where}", allow_empty=raw["control"])
    if raw["control"] and expected:
        raise KbError(f"{where} is a control and so names no expected book")
    home = _titles(raw["home"], f"home of {where}", allow_empty=True)
    if set(expected) & set(home):
        raise KbError(f"{where} names a book as both expected and home")
    queries = raw["keyword_queries"]
    if not isinstance(queries, list) or not 1 <= len(queries) <= MAX_KEYWORD_QUERIES:
        raise KbError(f"{where} has from 1 to {MAX_KEYWORD_QUERIES} keyword queries")
    for query in queries:
        try:
            search.words_of(query)
        except KbError as e:
            raise KbError(f"{where}: {e}") from None
    subs = raw["sub_problems"]
    if not isinstance(subs, list) or not 1 <= len(subs) <= problem.MAX_SUB_PROBLEMS:
        raise KbError(f"{where} has from 1 to {problem.MAX_SUB_PROBLEMS} sub-problems")
    for n, sub in enumerate(subs, 1):
        _text(sub, f"sub-problem {n} of {where}")
    return {"id": pid, "control": raw["control"], "text": text, "expected": expected, "home": home,
            "keyword_queries": list(queries), "sub_problems": list(subs)}


def load_corpus(path):
    """`(corpus, sha256)` of the corpus file at `path`, checked. The file must be a regular file outside the project, small, one JSON
    object with no repeated key, and in the expected form."""
    paths.require_outside(path, "the corpus file")
    try:
        st = os.stat(path)
    except OSError:
        raise KbError("the corpus file cannot be read") from None
    if not os.path.isfile(path) or st.st_size > MAX_CORPUS_BYTES:
        raise KbError(f"the corpus must be a file of at most {MAX_CORPUS_BYTES} bytes")
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_CORPUS_BYTES + 1)
    except OSError:
        raise KbError("the corpus file cannot be read") from None
    try:
        doc = models._loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        doc = None
    if not isinstance(doc, dict) or set(doc) != {"format", "problems"}:
        raise KbError("the corpus is not one JSON object with the keys format and problems")
    if type(doc["format"]) is not int or doc["format"] != FORMAT:
        raise KbError(f"the corpus is not of format {FORMAT}")
    if not isinstance(doc["problems"], list) or not 1 <= len(doc["problems"]) <= MAX_PROBLEMS:
        raise KbError(f"the corpus has from 1 to {MAX_PROBLEMS} problems")
    seen = set()
    return {"problems": [_problem(p, seen) for p in doc["problems"]]}, hashlib.sha256(raw).hexdigest()


def _order_over_queries(lists):
    """The books of several lists in order of their smallest place in any list, ties by book id."""
    places = trial._places(lists)
    return sorted(places, key=lambda b: (places[b], b))


def _measures(lists, expected, home):
    """The measures of one search of a problem that has expected books (see the module docstring). `lists` are the lists of books that
    the search gave, one for each query (T and K) or the one list (M and P); a book's place is the smallest it has in any of them, and
    after setting aside it is the same with the home books taken out of each list."""
    homes = set(home)
    places = trial._places(lists)
    after = trial._places([[b for b in books if b not in homes] for books in lists])
    placed = {b: places.get(b) for b in expected}
    found = [p for p in placed.values() if p is not None]
    return {"places": placed, "places_after_set_aside": {b: after.get(b) for b in expected},
            "hit5": any(p <= FIRST for p in found),
            "hit5_after_set_aside": any(after.get(b) is not None and after[b] <= FIRST for b in expected),
            "reciprocal_rank": 1 / min(found) if found else 0.0,
            "home_in_first_five": sum(1 for b in homes if places.get(b) is not None and places[b] <= FIRST)}


_NO_MEASURES = {"places": None, "places_after_set_aside": None, "hit5": None, "hit5_after_set_aside": None, "reciprocal_rank": None,
                "home_in_first_five": None}


def _record(lists, scores, titles, expected, home, control):
    """The record of one search of one problem: the books in order, those at a place within the first five with their titles, the
    scores of M and P, and the measures (none for a control)."""
    places = trial._places(lists)
    order = sorted(places, key=lambda b: (places[b], b))
    out = {"order": order[:LIST_LIMIT], "first_five": [{"book_id": b, "title": titles.get(b, "")} for b in order if places[b] <= FIRST]}
    if scores is not None:
        out["scores"] = scores
    out.update(_NO_MEASURES if control else _measures(lists, expected, home))
    return out


def _summarize(problems):
    positive = [p for p in problems if not p["control"]]
    by = {}
    for name in SEARCHES:
        got = [p["searches"][name] for p in positive]
        pairs = [(p["expected"], s["places"]) for p, s in zip(positive, got)]
        ranks = [s["reciprocal_rank"] for s in got]
        by[name] = {"hit5": sum(1 for s in got if s["hit5"]), "hit5_after_set_aside": sum(1 for s in got if s["hit5_after_set_aside"]),
                    "of": len(positive), "pairs": sum(len(e) for e, _ in pairs),
                    "pairs_in_first_10": sum(1 for e, places in pairs for b in e if places[b] is not None and places[b] <= WIDE),
                    "mean_reciprocal_rank": round(sum(ranks) / len(ranks), 4) if ranks else None}
    return {"problems": len(problems), "positive": len(positive), "controls": len(problems) - len(positive), "by_search": by}


def _file_hashes(root):
    """The hashes of the catalog, the text index and the vectors, which the run must find unchanged at its end."""
    return tuple(trial._sha256(p) for p in (catalog.path_of(root), index.path_of(root), vectors.path_of(root)))


def _cards(store, root):
    """The cards of the catalog as `(book, made)`, after checking that the catalog is the one the cards make."""
    stale = "the catalog is not the one the cards make (a card was made, or changed, after the last card-index): run `python3 -m kb card-index`"
    rows = trial._catalog_rows(root)
    expected, _, _ = trial._card_state(store)
    if {(b, v, g) for b, v, g, _ in rows} != expected:
        raise KbError(stale)
    out = []
    for b, v, g, text in rows:
        try:
            made = models._loads(text)
            card.validate(made)
        except KbError:
            raise KbError(stale) from None
        if made["book_id"] != b or made["version_id"] != v:
            raise KbError(stale)
        out.append((b, made))
    return out


def _resolve(corpus, cards):
    """For each problem, the book ids of its expected and home titles, or a refusal for a title that matches no book or two."""
    by_title = {}
    for book_id, made in cards:
        by_title.setdefault(made["title"], set()).add(book_id)
    resolved = {}
    for p in corpus["problems"]:
        entry = {}
        for kind in ("expected", "home"):
            entry[kind] = {}
            for title in p[kind]:
                found = by_title.get(title, set())
                if len(found) != 1:
                    raise KbError(f"problem {p['id']}: the title \"{textutil.clean(title, 80)}\" matches "
                                  f"{'no book' if not found else 'more than one book'} in the catalog")
                entry[kind][title] = next(iter(found))
        resolved[p["id"]] = entry
    return resolved


def _distinct(results):
    return trial._books(results)


def _first_scores(results, order):
    first = {}
    for r in results:
        first.setdefault(r["book_id"], r["score"])
    return [first[b] for b in order[:FIRST]]


def run(store, cfg, corpus_path, report_path, replace=False, check=False, launcher=None):
    """Run the corpus against the library, write the report, and return the summary (the numbers, the hashes and the counts, never the
    problems). With `check`, read the corpus and the library, resolve the titles and return the plan, send nothing and write nothing.
    Refused, before anything is sent: a corpus or a report inside the project, a corpus that is not in the expected form, a title that
    matches no book or two, an existing report (unless `replace`), a catalog that is not the one the cards make, a missing text index,
    catalog or vectors, vectors made by another model, dimension or document prefix than the config sets, and vectors that are not
    current (a stored vector whose card text changed, or a card with no vector). The text index is checked only for its presence, as
    `trial` checks it. Refused after: a call that
    fails (no report is written) and a library that changed during the run. Changes nothing in the library."""
    corpus, corpus_hash = load_corpus(corpus_path)
    out_path = trial._report_path(report_path, replace)
    root = store.cfg["index_root"]
    if not os.path.isfile(catalog.path_of(root)):
        raise KbError("there is no catalog of the cards: run `python3 -m kb card-index`")
    if not os.path.isfile(index.path_of(root)):
        raise KbError("there is no search index of the text: run `python3 -m kb index`")
    if not os.path.isfile(vectors.path_of(root)):
        raise KbError(f"there is no file of vectors: run `{vectors.COMMAND}`")
    before = _file_hashes(root)
    cards = _cards(store, root)
    resolved = _resolve(corpus, cards)
    titles = {book: made["title"] for book, made in cards}
    name, _ = models.choose(cfg, "card-embed")
    entry = models.registry(cfg)[name]
    with closing(vectors.connect(vectors.path_of(root), readonly=True)) as vconn:
        meta = vectors.check_entry(vconn, entry)
    covered = vectors.coverage(root, cfg)  # what M and P would search, found without sending anything
    if covered["stale"] or covered["without_vector"]:
        raise KbError(f"the vectors are not current ({covered['stale']} stale, {covered['without_vector']} without a vector): "
                      f"run `{vectors.COMMAND}`")
    problems = corpus["problems"]
    to_send = len(problems) + sum(len(p["sub_problems"]) for p in problems)
    controls = sum(1 for p in problems if p["control"])
    if check:
        return {"check": True, "corpus_sha256": corpus_hash, "problems": len(problems), "positive": len(problems) - controls,
                "controls": controls, "keyword_queries": sum(len(p["keyword_queries"]) for p in problems),
                "sub_problems": sum(len(p["sub_problems"]) for p in problems), "sentences_to_send": to_send, "resolved": resolved,
                "model": meta["model"], "query_prefix": "query_prefix" in entry, **covered}
    with closing(index.connect(index.path_of(root), readonly=True)) as conn:
        in_text = {row[0] for row in conn.execute("SELECT DISTINCT book_id FROM versions")}

    records = []
    for p in problems:
        ids = resolved[p["id"]]
        expected, home = list(ids["expected"].values()), list(ids["home"].values())
        searches = {}
        for label, run_query in (("T", lambda q: search.search(root, q, limit=LIST_LIMIT)),
                                 ("K", lambda q: catalog.search(root, q, limit=LIST_LIMIT, within="all"))):
            lists = [_distinct(run_query(q)) for q in p["keyword_queries"]]
            searches[label] = _record(lists, None, titles, expected, home, p["control"])
        results = vectors.search(root, cfg, p["text"], limit=LIST_LIMIT, launcher=launcher)["results"]
        order = _distinct(results)
        searches["M"] = _record([order], _first_scores(results, order), titles, expected, home, p["control"])
        merged = problem.search(root, cfg, p["sub_problems"], limit=PROBLEM_LIMIT, launcher=launcher)["books"]
        order = _distinct(merged)
        searches["P"] = _record([order], _first_scores(merged, order), titles, expected, home, p["control"])
        records.append({"id": p["id"], "control": p["control"], "text": p["text"], "expected": expected, "home": home,
                        "titles": {b: titles[b] for b in expected + home}, "keyword_queries": p["keyword_queries"],
                        "sub_problems": p["sub_problems"], "expected_without_text": [b for b in expected if b not in in_text],
                        "searches": searches})
    after = _file_hashes(root)
    if after != before:
        raise KbError("the catalog, the text index or the vectors changed during the run; run the trial again")
    summary = _summarize(records)
    report = {"format": FORMAT, "corpus_sha256": corpus_hash, "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "limits": {"list": LIST_LIMIT, "problem_search_per_sub_problem": PROBLEM_LIMIT, "first": FIRST},
              "manifest": {"library_id": store.library_id, "catalog_sha256": after[0], "text_index_sha256": after[1],
                           "vectors_sha256": after[2], "model": meta["model"], "query_prefix": "query_prefix" in entry,
                           "cards": len(cards), **covered},
              "problems": records, "summary": summary}
    trial._write_report(out_path, report, replace)
    return {**summary, "corpus_sha256": corpus_hash, "report_sha256": trial._sha256(out_path), "sentences_sent": to_send,
            "model": meta["model"], "query_prefix": "query_prefix" in entry}
