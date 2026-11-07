"""The trial of whether the cards help (`docs/specs/testing.md`, "Evaluation"; `docs/specs/card.md`, "Quality").

A corpus of questions, held outside the repository, says for each question some short queries and the books that answer it. The trial
runs each query as four searches, each over the same library: the cards (all their fields), the summary side of the cards, the neutral
side of the cards, and the full text; and it writes a report, also outside the repository, of which right books each search found and at
what place. It reads the library and the two indexes and nothing else: it calls no model, sends nothing anywhere and changes nothing.
It reports numbers and never decides.

The rules of the measures (fixed so that two implementations give the same report from the same corpus). A search of a query gives
books in order, each at a place counted from 1 by its first appearance (a book that has several cards, or several blocks, is one book).
For a question and a search, the books found are the union over its queries; a book's place is the smallest place it has in any of the
queries, and books of the same place are ordered by book id. A right book is found if any query found it. The unit is a (question, right
book) pair. A right book that has no card in the catalog is uncovered: it is left out of the measures of the three card searches and of
the comparison, and is counted only in the full-text recall over all pairs. Recall is the share of covered pairs found; the sets
cards-only, text-only, both and neither are over covered pairs, `cards` meaning the search of all fields; the hit rate is the share of
questions (with at least one covered right book) in which at least one right book was found; a question's reciprocal rank is one over
the place of its best-placed covered right book, or zero if none is found, and the mean over those questions is reported; the noise of a
question is the number of distinct books in the union that are not right. Every number is reported with its count.

The full-text search gives blocks, at most FULL_TEXT_LIMIT of them for a query; the books it finds are those of the first blocks, in the
order of their first appearance, so for a common word the books are a lower bound, and the report says when the limit was reached."""
import hashlib
import json
import os
import re
import unicodedata
from contextlib import closing
from datetime import datetime, timezone

from . import KbError, card, catalog, config, ids, index, models, search, textutil

FORMAT = 1
MAX_CORPUS_BYTES = 1_000_000
MAX_QUESTIONS = 200
MAX_QUERIES = 10
MAX_RIGHT = 50
MAX_FIELD_WORDS = 500
MAX_TEXT = 1000
FULL_TEXT_LIMIT = 50
CARD_LIMIT = 50
SEARCHES = ("cards", "summary", "neutral", "text")
_QUESTION_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
_WORD = re.compile(r"\w+")
_STOP = frozenset("with from that this have using used based what when where which into about than their these those there been were "
                  "they them then also such other more most only over under between through while each both some many much very".split())


def _inside_project(path):
    real = os.path.realpath(path)
    root = os.path.realpath(models._project_root())
    return real == root or real.startswith(root + os.sep)


def _outside(path, what):
    """Refuse a path that is, or lies under, the project's own folder (links followed): the trial's files are held outside the repository."""
    if not isinstance(path, str) or not path:
        raise KbError(f"{what} must be a path")
    if _inside_project(path):
        raise KbError(f"{what} is inside the project's own folder; the files of a trial are held outside the repository")


def _question(raw, seen):
    if not isinstance(raw, dict) or set(raw) != {"id", "text", "queries", "right"}:
        raise KbError("a question has exactly the keys id, text, queries and right")
    qid = raw["id"]
    if not isinstance(qid, str) or not _QUESTION_ID.fullmatch(qid):
        raise KbError("a question id is lower-case letters, digits, _ and -, starting with a letter or digit")
    if qid in seen:
        raise KbError(f"the question id {qid} is used twice")
    seen.add(qid)
    where = f"question {qid}"
    if not isinstance(raw["text"], str) or len(raw["text"]) > MAX_TEXT:
        raise KbError(f"the text of {where} is not text of at most {MAX_TEXT} characters")
    queries = raw["queries"]
    if not isinstance(queries, list) or not 1 <= len(queries) <= MAX_QUERIES:
        raise KbError(f"{where} has from 1 to {MAX_QUERIES} queries")
    for query in queries:
        try:
            search.words_of(query)
        except KbError as e:
            raise KbError(f"{where}: {e}") from None
    right = raw["right"]
    if not isinstance(right, list) or not 1 <= len(right) <= MAX_RIGHT or len(set(map(str, right))) != len(right):
        raise KbError(f"{where} names from 1 to {MAX_RIGHT} different right books")
    for book_id in right:
        try:
            ids.check_id(book_id)
        except KbError as e:
            raise KbError(f"{where}: {e}") from None
    return {"id": qid, "text": raw["text"], "queries": list(queries), "right": list(right)}


def load_corpus(path):
    """`(corpus, sha256)` of the corpus file at `path`, checked. The file must be a regular file outside the project, small, one JSON
    object with no repeated key, and in the expected form."""
    _outside(path, "the corpus file")
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
    if not isinstance(doc, dict) or not {"format", "questions"} <= set(doc) <= {"format", "questions", "field_words"}:
        raise KbError("the corpus is not one JSON object with the keys format, questions and, if wanted, field_words")
    if type(doc["format"]) is not int or doc["format"] != FORMAT:
        raise KbError(f"the corpus is not of format {FORMAT}")
    if not isinstance(doc["questions"], list) or not 1 <= len(doc["questions"]) <= MAX_QUESTIONS:
        raise KbError(f"the corpus has from 1 to {MAX_QUESTIONS} questions")
    seen = set()
    questions = [_question(q, seen) for q in doc["questions"]]
    words = doc.get("field_words", [])
    if not isinstance(words, list) or len(words) > MAX_FIELD_WORDS or not all(
            isinstance(w, str) and len(w) <= 60 and _WORD.fullmatch(w) for w in words):
        raise KbError(f"field_words is a list of at most {MAX_FIELD_WORDS} single words")
    return {"questions": questions, "field_words": sorted({unicodedata.normalize("NFKC", w).casefold() for w in words})}, hashlib.sha256(raw).hexdigest()


def _report_path(path, replace):
    _outside(path, "the report file")
    parent = os.path.realpath(os.path.dirname(os.path.abspath(path)))
    if not os.path.isdir(parent):
        raise KbError("the folder for the report is not there")
    if _inside_project(parent):
        raise KbError("the report file is inside the project's own folder; the files of a trial are held outside the repository")
    final = os.path.join(parent, os.path.basename(path))
    if os.path.lexists(final) and not replace:
        raise KbError("the report file exists; ask to replace it, or name another file")
    return final


def _write_report(out_path, report, replace):
    """Write the report. Without `replace` the name is claimed first with an exclusive create, so a file that appears after the
    check is never overwritten; a failed write leaves no claim behind. With `replace` a link at the name is replaced, not followed."""
    claimed = False
    if not replace:
        try:
            os.close(os.open(out_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
        except FileExistsError:
            raise KbError("the report file exists; ask to replace it, or name another file") from None
        except OSError:
            raise KbError("the report file cannot be created") from None
        claimed = True
    try:
        config.write_json_atomic(out_path, report, 0o600)
    except BaseException:
        if claimed:
            try:
                os.unlink(out_path)
            except OSError:
                pass
        raise


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _card_state(store):
    """`(expected, unreadable, inactive)`: the (book, version, generation) of the newest card of each version of each active book that
    can be read, which is what the catalog should hold; the books whose newest card cannot be read; the books that are not active."""
    expected, unreadable, inactive = set(), set(), set()
    for book_id in store.list_books():
        try:
            if store.read_book(book_id).get("state") != "active":
                inactive.add(book_id)
                continue
            versions = store.version_ids(book_id)
        except KbError:
            continue
        for version_id in versions:
            found = card.generations(store, book_id, version_id)
            if not found:
                continue
            try:
                card.read(store, book_id, version_id, found[-1])
            except (KbError, OSError):
                unreadable.add(book_id)
                continue
            expected.add((book_id, version_id, found[-1]))
    return expected, unreadable, inactive


def _catalog_rows(index_root):
    with closing(catalog.connect(catalog.path_of(index_root), readonly=True)) as conn:
        return [(b, v, g, c) for b, v, g, c in conn.execute("SELECT book_id, version_id, generation, card FROM cards ORDER BY book_id, version_id")]


def _books(results):
    """The distinct books of results, in order of first appearance."""
    out = []
    for r in results:
        if r["book_id"] not in out:
            out.append(r["book_id"])
    return out


def _all_words(text):
    return set(_WORD.findall(unicodedata.normalize("NFKC", text).casefold()))


def _words(text):
    return {w for w in _all_words(text) if len(w) >= 4 and w not in _STOP}


def _count(text):
    return len(_WORD.findall(text))


def _card_measures(made, field_words):
    model = made["model"]
    if model is None:
        zero = {k: 0 for k in ("total", "summary", "useful_for", "topics", "adjacent_topics", "key_ideas", "neutral", "caveats")}
        return {"book_id": made["book_id"], "version_id": made["version_id"], "title": made["title"], "has_model_part": False,
                "words": zero, "leaked": []}
    joined = lambda key: _count(" ".join(model[key]))
    neutral = " ".join(model[f"neutral_{k}"] for k in ("problem", "approach", "needs", "provides", "limits"))
    words = {"summary": _count(model["summary"]), "useful_for": joined("useful_for"), "topics": joined("topics"),
             "adjacent_topics": joined("adjacent_topics"), "key_ideas": joined("key_ideas"), "neutral": _count(neutral),
             "caveats": joined("caveats")}
    words["total"] = sum(words.values())
    source = _words(made["title"] + " " + " ".join(model["topics"]))
    leaked = sorted((source & _words(neutral)) | (set(field_words) & _all_words(neutral)))
    return {"book_id": made["book_id"], "version_id": made["version_id"], "title": made["title"], "has_model_part": True,
            "words": words, "leaked": leaked}


def _places(lists):
    """The best place of each book over lists of books: a book's smallest place in any of them."""
    places = {}
    for books in lists:
        for place, book_id in enumerate(books, start=1):
            places[book_id] = min(place, places.get(book_id, place))
    return places


def _question_result(q, per_query, covered):
    """The record of one question. For each query and each search, the right books found with their places and the noise; for the
    question and each search, the union of the queries: the books in order, the right books found with their best places, the noise,
    whether a covered right book was found (`hit`) and the reciprocal rank of the best-placed covered right book. The cards are scored
    on the covered right books, the text on all of them."""
    record = {"id": q["id"], "text": q["text"], "right": q["right"], "covered": [b for b in q["right"] if b in covered],
              "queries": per_query, "searches": {}}

    def scored(name):
        return q["right"] if name == "text" else record["covered"]

    for entry in per_query:
        entry["found"], entry["noise"] = {}, {}
        for name in SEARCHES:
            places = _places([entry["books"][name]])
            entry["found"][name] = {b: places.get(b) for b in scored(name)}
            entry["noise"][name] = len([b for b in places if b not in q["right"]])
    for name in SEARCHES:
        places = _places([entry["books"][name] for entry in per_query])
        covered_places = [places[b] for b in record["covered"] if b in places]
        record["searches"][name] = {
            "found": {b: places.get(b) for b in scored(name)}, "order": sorted(places, key=lambda b: (places[b], b)),
            "noise": len([b for b in places if b not in q["right"]]),
            "hit": bool(covered_places) if record["covered"] else None,
            "reciprocal_rank": (1 / min(covered_places) if covered_places else 0.0) if record["covered"] else None}
    return record


def _summarize(results):
    pairs = sum(len(r["right"]) for r in results)
    covered_pairs = sum(len(r["covered"]) for r in results)
    scored = [r for r in results if r["covered"]]  # the questions with at least one covered right book
    out = {"questions": len(results), "pairs": pairs, "covered_pairs": covered_pairs, "uncovered_pairs": pairs - covered_pairs}

    def found(r, name):
        return [b for b in r["covered"] if r["searches"][name]["found"].get(b) is not None]

    out["recall"] = {name: {"found": sum(len(found(r, name)) for r in results), "of": covered_pairs} for name in SEARCHES}
    out["recall"]["text_all_pairs"] = {"found": sum(1 for r in results for b in r["right"] if r["searches"]["text"]["found"][b] is not None),
                                       "of": pairs}
    sets = {"cards_only": 0, "text_only": 0, "both": 0, "neither": 0}
    for r in results:
        for b in r["covered"]:
            by_cards, by_text = r["searches"]["cards"]["found"][b] is not None, r["searches"]["text"]["found"][b] is not None
            sets["both" if by_cards and by_text else "cards_only" if by_cards else "text_only" if by_text else "neither"] += 1
    out["sets"] = {**sets, "of": covered_pairs}
    out["hit_rate"] = {name: {"questions_hit": sum(1 for r in scored if r["searches"][name]["hit"]), "of": len(scored)} for name in SEARCHES}
    reciprocal = {}
    for name in SEARCHES:
        ranks = [r["searches"][name]["reciprocal_rank"] for r in scored]
        reciprocal[name] = {"value": round(sum(ranks) / len(ranks), 4) if ranks else None, "of": len(scored)}
    out["mean_reciprocal_rank"] = reciprocal
    out["noise"] = {name: {"mean": round(sum(r["searches"][name]["noise"] for r in results) / len(results), 4), "of": len(results)}
                    for name in SEARCHES}
    return out


def run(store, corpus_path, report_path, replace=False):
    """Run the corpus against the library, write the report, and return the summary (the numbers and the corpus hash, never the
    questions). Refuses a corpus or a report inside the project, a corpus that is not in the expected form, a book that is not in the
    library, an existing report (unless `replace`), a catalog that is not the one the cards make, and a missing index. Changes nothing
    in the library and calls no model."""
    corpus, corpus_hash = load_corpus(corpus_path)
    out_path = _report_path(report_path, replace)
    root = store.cfg["index_root"]
    for q in corpus["questions"]:
        for book_id in q["right"]:
            try:
                store.read_book(book_id)
            except KbError:
                raise KbError(f"question {q['id']} names a book that is not in the library: {book_id}") from None
    if not os.path.isfile(catalog.path_of(root)):
        raise KbError("there is no catalog of the cards: run `python3 -m kb card-index`")
    if not os.path.isfile(index.path_of(root)):
        raise KbError("there is no search index of the text: run `python3 -m kb index`")
    catalog_hash, text_hash = _sha256(catalog.path_of(root)), _sha256(index.path_of(root))
    rows = _catalog_rows(root)
    expected, unreadable, inactive = _card_state(store)
    stale = "the catalog is not the one the cards make (a card was made, or changed, after the last card-index): run `python3 -m kb card-index`"
    if {(b, v, g) for b, v, g, _ in rows} != expected:
        raise KbError(stale)
    cards = []
    for b, v, g, text in rows:
        try:
            made = models._loads(text)
            card.validate(made)
        except KbError:
            raise KbError(stale) from None
        if made["book_id"] != b or made["version_id"] != v:
            raise KbError(stale)
        cards.append((b, v, g, made))
    covered = {b for b, _, _, _ in cards}
    with closing(index.connect(index.path_of(root), readonly=True)) as conn:
        in_text = {row[0] for row in conn.execute("SELECT DISTINCT book_id FROM versions")}

    results = []
    for q in corpus["questions"]:
        per_query = []
        for query in q["queries"]:
            entry = {"query": query, "books": {}, "text_limit_reached": False}
            for name, within in (("cards", "all"), ("summary", "summary"), ("neutral", "neutral")):
                entry["books"][name] = _books(catalog.search(root, query, limit=CARD_LIMIT, within=within))
            blocks = search.search(root, query, limit=FULL_TEXT_LIMIT)
            entry["books"]["text"] = _books(blocks)
            entry["text_limit_reached"] = len(blocks) >= FULL_TEXT_LIMIT
            per_query.append(entry)
        results.append(_question_result(q, per_query, covered))

    if _sha256(catalog.path_of(root)) != catalog_hash or _sha256(index.path_of(root)) != text_hash:
        raise KbError("the catalog or the text index changed during the run; run the trial again")
    uncovered, text_uncovered = {}, {}
    for q in corpus["questions"]:
        for b in q["right"]:
            if b not in covered:
                uncovered.setdefault(b, []).append(q["id"])
            if b not in in_text:
                text_uncovered.setdefault(b, []).append(q["id"])

    def reason(book_id):
        return "book is not active" if book_id in inactive else "card cannot be read" if book_id in unreadable else "no card"
    summary = _summarize(results)
    each = [_card_measures(made, corpus["field_words"]) for _, _, _, made in cards]
    modelled = [c for c in each if c["has_model_part"]]
    totals = [c["words"]["total"] for c in modelled]
    manifest = {"library_id": store.library_id,
                "cards": [{"book_id": b, "version_id": v, "generation": g,
                           "sha256": store.verify_payload(b, v, f"derived/card/{g}")["files"][card.FILENAME]["sha256"]} for b, v, g, _ in cards],
                "catalog_sha256": catalog_hash, "catalog_cards": len(cards),
                "text_index_sha256": text_hash}
    report = {"format": FORMAT, "corpus_sha256": corpus_hash, "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "full_text_limit": FULL_TEXT_LIMIT, "card_limit": CARD_LIMIT, "manifest": manifest,
              "uncovered": [{"book_id": b, "reason": reason(b), "questions": qs} for b, qs in sorted(uncovered.items())],
              "text_uncovered": [{"book_id": b, "questions": qs} for b, qs in sorted(text_uncovered.items())],
              "questions": results, "summary": summary,
              "cards": {"each": each, "with_model_part": len(modelled),
                        "leaking": {"cards": sum(1 for c in modelled if c["leaked"]), "of": len(modelled)},
                        "words": {"mean": round(sum(totals) / len(totals), 1) if totals else None, "min": min(totals, default=None),
                                  "max": max(totals, default=None), "of": len(totals)}}}
    _write_report(out_path, report, replace)
    return {**summary, "corpus_sha256": corpus_hash, "uncovered": [u["book_id"] for u in report["uncovered"]],
            "cards": {k: report["cards"][k] for k in ("with_model_part", "leaking", "words")}}
