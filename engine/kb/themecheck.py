"""Checking the descriptions of themes: the words of the book's field, and support in the excerpt (`docs/specs/theme.md`; the plan
`2026-11-11-make-the-theme-the-unit-of-the-weave`, Increment D).

A theme carries a description in words of no field, in five parts. Two checks are made of it, and neither drops a theme for what it finds.

The words of the field. A book's vocabulary is the words of its title, of the topics and adjacent topics of its card, and the words
that occur at least FREQUENT_MIN times in its text while at most RARE_PERCENT percent of the books of the library hold them, less the
words that at least half of the books hold. A word is a run of letters of four or more in its plain lower-case form (no stemming). A
description that holds a word of the vocabulary as a whole word is flagged with the words found, and kept: the flag is for the owner to
read, and a false flag is a word that is not the field's.

Support. A second model (the kind of work `theme-check`) is shown the excerpt and the parts of the description that have text, and says
for each whether the excerpt supports it. A part it says is supported is marked `stated`; every other stays `inferred`. A theme whose
check gives no valid answer (the answer is refused, asked once more with the reason, and refused again) is dropped with the reason
`unchecked`, so that no theme is filed with a part that no one has looked at.

The excerpt and the parts go to the model as data in sections of their own, between delimiters that hold a random token no input holds.
Nothing here files anything."""
import copy
from collections import Counter

from . import KbError, cardmake, convert, models, textutil, theme, themeextract

FREQUENT_MIN = 5       # occurrences in the book's own text for a word to count as one of its words
RARE_PERCENT = 15      # the most percent of the books of the library that may hold such a word
COMMON_SHARE = 2       # a word held by at least one book in this many (half) is common, and is never in a vocabulary
AVOID_LIMIT = 80       # the most words of a book's vocabulary that the extraction is told to avoid
AVOID_WORD_MAX = 40    # the longest word it is told to avoid: a run of letters of any length in a book cannot make the prompt too large
VERDICTS = cardmake.VERDICTS
THEME_CHECK_SHAPE = {"verdicts": {"type": "strings", "min_items": 1, "max_items": len(theme.PARTS), "max": 16}}


words = textutil.words   # runs of four or more letters, folded to plain lower case, not stemmed


def frequencies(texts):
    """`(document frequencies, number of texts)`: for each word, the number of the texts that hold it (a text counts once)."""
    df, size = Counter(), 0
    for text in texts:
        df.update(set(words(text)))
        size += 1
    return df, size


def library_frequencies(store):
    """`frequencies` over the converted text of the current version of each active book that has a conversion in use. A book whose
    conversion cannot be read is left out."""
    df, size = Counter(), 0
    for book_id in store.list_books():
        try:
            book = store.read_book(book_id)
            version = book.get("current_version")
            if book.get("state") != "active" or not version:
                continue
            loaded = convert.load_in_use(store, book_id, version)
        except KbError:
            continue
        if loaded is not None:
            df.update(set(words(loaded[1].text)))   # one text at a time: the texts of the library are not held together
            size += 1
    return df, size


def _common(df, size):
    """The words held by at least half of the `size` books: never in a vocabulary and never to be avoided."""
    return {w for w, n in df.items() if n * COMMON_SHARE >= size}


def _own_words(text, df, size):
    """`[(word, uses)]` for the words of a book that occur at least FREQUENT_MIN times in its text and that at most RARE_PERCENT percent of the
    `size` books hold (`df` counts the book itself), the one used most first, and alphabetical among equals."""
    own = Counter(words(text))
    return sorted(((w, n) for w, n in own.items() if n >= FREQUENT_MIN and df.get(w, 0) * 100 <= RARE_PERCENT * size),
                  key=lambda pair: (-pair[1], pair[0]))


def field_vocabulary(text, df, size, title, topics):
    """The vocabulary of a book's field: the set of words of its title, of its topics, and of its own text that occur at least
    FREQUENT_MIN times in it and are held by at most RARE_PERCENT percent of the `size` books (`df` counts the book itself), less the
    common words, which at least half of the books hold."""
    named = set(words(title)) | {w for topic in topics for w in words(topic)}
    return (named | {w for w, _ in _own_words(text, df, size)}) - _common(df, size)


def avoid_words(text, df, size, title, topics, limit=AVOID_LIMIT):
    """The words of a book's vocabulary as a list for a model to avoid, strongest first: the words of the title, then those of the topics,
    then the book's own words (`_own_words`: the one used most first); each once, none of them common or of more than AVOID_WORD_MAX
    letters, at most `limit`. With `limit` unbounded, they are the words of `field_vocabulary` of that length or less."""
    common = _common(df, size)
    out, seen = [], set()
    for word in [w for part in [title, *topics] for w in words(part)] + [w for w, _ in _own_words(text, df, size)]:
        if word not in common and word not in seen and len(word) <= AVOID_WORD_MAX:
            seen.add(word)
            out.append(word)
    return out[:limit]


def field_flag(neutral, vocabulary):
    """The flag for a description that holds words of the vocabulary, or None: `{"kind": "field_words", "detail": the words found}`."""
    held = {w for name in theme.PARTS for w in words(neutral[name]["text"])}
    found = sorted(held & set(vocabulary))
    if not found:
        return None
    detail = ", ".join(found)
    if len(detail) > theme.MAX_DETAIL:
        detail = detail[:theme.MAX_DETAIL].rsplit(", ", 1)[0]
    return {"kind": "field_words", "detail": detail}


def check_job(count):
    """The job that asks a model whether the excerpt supports the `count` parts shown: one verdict for each."""

    def check(values):
        if len(values["verdicts"]) != count:
            raise KbError("the answer's verdicts and the parts asked about are not lists of the same length")
        for verdict in values["verdicts"]:
            if verdict.strip().casefold() not in VERDICTS:
                raise KbError(f"a verdict is one of {', '.join(VERDICTS)}: {textutil.literal(verdict, 20)}")

    return models.Job("theme-check", "v1", THEME_CHECK_SHAPE, schema="theme-check.json", check=check)


def check_prompt(excerpt, parts):
    """The prompt that asks whether the excerpt supports each part. `parts` are `(name, text)`; they are numbered in order, and the
    answer is one verdict for each."""
    body = "\n".join(f"{n}. {name}: {text}" for n, (name, text) in enumerate(parts, start=1))
    rules = ("You are checking a description against the text it was made from. Below are two sections of data: an EXCERPT from a book, "
             "and numbered PARTS of a description of it, each a short statement in general words that a model wrote.\n"
             f"{themeextract._DATA}\nFor each part decide whether the EXCERPT supports it. Judge only by the excerpt, not by what you know "
             f"of the subject.\nReply with one JSON object with the single key \"verdicts\": a list of exactly {len(parts)} words, one "
             "for each part in order: \"supports\" if the excerpt states the part or clearly leads to it, \"partly\" if the excerpt "
             "supports only part of it, or \"no\" if the excerpt does not bear on it.")
    return cardmake._prompt(rules, [("EXCERPT", excerpt), ("PARTS", body)])


def check_themes(cfg, ref, conversion, themes, vocabulary, launcher=None, root=None, on_refused=None):
    """Check themes of the conversion `ref` names. Returns `{"themes", "dropped", "records", "calls"}`: the themes with their parts marked
    and their flags added (the others in the order given), the themes that were dropped as `unchecked` with the reason, the record of
    each call and the number of calls. One call is made for each theme that has a part with text. The model is the one the config sets for
    `theme-check`, and the anchor of every theme is checked against the text, both before anything is sent. A refusal that is asked again
    and given to `on_refused` is kept aside by the caller; a call that fails is raised."""
    name, _ = models.choose(cfg, "theme-check")
    excerpts = []
    for t in themes:
        try:
            excerpts.append(theme.excerpt_text(ref, conversion, t["anchor"]))
        except KbError as e:
            raise KbError(f"the anchor of the theme {t['id']!r} does not hold in the text: {e}") from None
    kept, dropped, records = [], [], []
    for original, excerpt in zip(themes, excerpts):
        t = copy.deepcopy(original)
        asked = [(part, t["neutral"][part]["text"]) for part in theme.PARTS if t["neutral"][part]["text"]]
        flags = []
        if not asked:
            flags.append({"kind": "no_description", "detail": "the model gave no part of a description"})
        else:
            try:
                out = themeextract._ask(cfg, name, check_prompt(excerpt, asked), launcher, root, on_refused, job=check_job(len(asked)))
            except models.AnswerRefused as refusal:
                if on_refused is not None:
                    try:
                        on_refused(refusal)
                    except Exception:   # keeping the answer is for the owner to read: it must not stop the check or hide the refusal
                        pass
                dropped.append({"title": t["title"], "reason": textutil.clean("unchecked: " + str(refusal), 300)})
                continue
            records.append({**out["record"], "task": "theme-check"})
            for (part, _), verdict in zip(asked, out["values"]["verdicts"]):
                t["neutral"][part]["mark"] = "stated" if verdict.strip().casefold() == "supports" else "inferred"
        flag = field_flag(t["neutral"], vocabulary)
        if flag:
            flags.append(flag)
        t["flags"] = list(t["flags"]) + flags
        try:
            theme.check_theme(t, t["book_id"], t["version_id"])
        except KbError as e:
            dropped.append({"title": t["title"], "reason": textutil.clean(str(e), 300)})
            continue
        kept.append(t)
    return {"themes": kept, "dropped": dropped, "records": records, "calls": len(records)}


def make_and_check_for_version(store, cfg, book_id, version_id=None, launcher=None, root=None, frequencies=None, journal=None):
    """The themes of one version (the current one, if none is named), made and checked but not filed: the result of `check_themes` and
    of the extraction put together, and under `generation` the generation for `theme.file`. Both models are found before anything is
    sent. `frequencies` is `(document frequencies, number of books)` of the library, counted from the store when it is not given. A
    refused answer is kept aside and raised as `ThemeRefused`. A `journal` (`themeextract.PieceJournal`) keeps the answers of the extraction, so
    that a book made again asks only for the pieces it has no answer for; the check is asked again for every theme."""
    models.choose(cfg, "theme")
    models.choose(cfg, "theme-check")
    version_id, current, ref, conversion = themeextract.prepare(store, book_id, version_id)
    df, size = frequencies if frequencies is not None else library_frequencies(store)
    model = current.get("model") or {}
    topics = list(model.get("topics", [])) + list(model.get("adjacent_topics", []))
    vocabulary = field_vocabulary(conversion.text, df, size, current["title"], topics)
    avoid = avoid_words(conversion.text, df, size, current["title"], topics)
    keep = lambda refusal: themeextract._keep(store, refusal, book_id, version_id)
    try:
        made = themeextract.extract(cfg, book_id, version_id, ref, conversion, current["title"], launcher=launcher, root=root, on_refused=keep,
                                    avoid=avoid, journal=journal)
        checked = check_themes(cfg, ref, conversion, made["themes"], vocabulary, launcher=launcher, root=root, on_refused=keep)
    except models.AnswerRefused as refusal:
        kept, note = themeextract._keep(store, refusal, book_id, version_id)
        raise themeextract.ThemeRefused(str(refusal), kept, note) from None
    return {"book_id": book_id, "version_id": version_id, "generation": theme.make(book_id, version_id, checked["themes"]),
            "dropped": made["dropped"] + checked["dropped"], "records": made["records"] + checked["records"], "pieces": made["pieces"],
            "calls": made["calls"] + checked["calls"], "vocabulary_words": len(vocabulary)}
