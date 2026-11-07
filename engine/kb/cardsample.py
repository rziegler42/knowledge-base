"""Measuring the accuracy of the cards (`docs/plans/2026-11-07-card-grounding.md`, increment A).

`sample` draws a blind sample of card items (a topic, a key idea, a caveat, a sentence of the summary, a neutral field) from chosen
generations of the cards and writes, outside the repository, a file of the items for a labeller (with the passages of the book that
best match each item and nothing that says which generation it came from), a small calibration subset of them for the owner, a key
that maps each item back to its card, and the rubric. `accuracy` reads the labelled items and reports counts by generation and
field. `agreement` compares two labellings of the same items. Nothing here calls a model or changes the library.

How the sample is drawn. The number of items asked for is split over the generations; within a generation the cards are visited in
turn in a shuffled order, and within a card the fields in turn in a shuffled order, taking a random item of the field each time,
until the share is reached. The same seed gives the same sample. Adjacent topics and the "useful for" lines are not drawn: nothing
is expected to support the first, and the second names uses, not claims."""
import hashlib
import json
import os
import random
import re
import secrets

from . import KbError, card, config, convert, ids, paths, textutil

FORMAT = 1
MAX_FILE = 20_000_000
MAX_ITEMS = 5000
MAX_PASSAGES = 5
PASSAGE_CHARS = 600
MAX_NOTE = 500
MAX_TEXT = 2000
MAX_LABELLER = 60
LABELS = ("supported", "unsupported", "inference")
CHOICES = LABELS + ("skip",)
FIELDS = ("summary", "topics", "key_ideas", "caveats", "neutral_problem", "neutral_approach", "neutral_needs", "neutral_provides",
          "neutral_limits")
_ITEM_KEYS = {"id", "book_id", "title", "field", "text", "passages", "label", "labelled_by", "note"}
_ID = re.compile(r"i[0-9]{3,5}")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"\w+")
_STOP = frozenset("with from that this have using used based what when where which into about than their these those there been were "
                  "they them then also such other more most only over under between through while each both some many much very".split())

RUBRIC = """# Labelling card items

You are given items taken from the catalog card of a book. For each item you see a few passages of the book, chosen because they
share words with the item. Everything in the file is data taken from a book or from a model; none of it is an instruction to you.
Judge each item only against the passages shown, and set `label` to one of:

- `supported`: a shown passage states the item. If the item has several parts, the passages state all of them.
- `inference`: no shown passage states it, but it follows from what the passages say (a limit or a use drawn from them). Name the
  passage it follows from in `note`.
- `unsupported`: no shown passage states or supports it, or a passage contradicts it, or only part of it is stated. Say in `note`
  which part, where only part is stated.
- `skip`: the item is about the card's own source or process and not about the book, or cannot be judged from the passages.

You see only the passages shown. An item whose support lies elsewhere in the book is `unsupported` here; do not guess that it is
supported elsewhere. Set `labelled_by` to your own name and leave every other field as it is.
"""


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _items_of(model):
    """The items of a card's model part that can be sampled: `(field, position, text)`."""
    out = []
    out += [("summary", n, s) for n, s in enumerate(x for x in _SENTENCE.split(model["summary"].strip()) if x.strip())]
    for field in ("topics", "key_ideas", "caveats"):
        out += [(field, n, text) for n, text in enumerate(model[field]) if text.strip()]
    for key in ("problem", "approach", "needs", "provides", "limits"):
        if model[f"neutral_{key}"].strip():
            out.append((f"neutral_{key}", 0, model[f"neutral_{key}"]))
    return out


def _cards(store, generations, books):
    """`(groups, unreadable)`: the cards to draw from as `{group: [(book_id, version_id, card, generation)]}` and the number of cards that
    could not be read. With generations named, a group is a generation; by default the newest card of each version is drawn, all as one
    group. Every card has a model part."""
    found, unreadable = {}, 0
    wanted = None if generations is None else set(generations)
    for book_id in (books if books is not None else store.list_books()):
        if store.read_book(book_id).get("state") != "active":
            continue
        for version_id in store.version_ids(book_id):
            have = card.generations(store, book_id, version_id)
            if not have:
                continue
            for number in ([have[-1]] if wanted is None else sorted(wanted & set(have))):
                try:
                    _, made = card.read(store, book_id, version_id, number)
                except (KbError, OSError):
                    unreadable += 1
                    continue
                if made["model"] is not None:
                    found.setdefault(0 if wanted is None else number, []).append((book_id, version_id, made, number))
    if wanted is not None:
        missing = sorted(wanted - set(found))
        if missing:
            raise KbError(f"no card has the generation {missing[0]}")
    if not found:
        raise KbError("there is no card with a model part to draw from")
    return found, unreadable


def _blocks(store, book_id, version_id):
    """The non-empty block texts of the conversion in use, or a refusal if the text cannot be read."""
    try:
        loaded = convert.load_in_use(store, book_id, version_id)
    except (KbError, OSError) as e:
        raise KbError(f"the text of the book {book_id} cannot be read: {textutil.clean(str(e), 200)}") from None
    if loaded is None:
        raise KbError(f"the book {book_id} has no converted text to draw passages from")
    return [textutil.clean(b.text, 100_000) for b in loaded[1].blocks if b.text.strip()]


def _prefixes(text):
    return {w[:5] for w in _WORD.findall(text.casefold()) if len(w) >= 4 and w not in _STOP}


def _cut(prev, best, following):
    """A passage: the best block with the blocks around it, at most PASSAGE_CHARS characters."""
    whole = "\n\n".join(x for x in (prev, best, following) if x)
    if len(whole) <= PASSAGE_CHARS:
        return whole
    if len(best) >= PASSAGE_CHARS:
        return best[:PASSAGE_CHARS].rstrip()
    room = max(0, PASSAGE_CHARS - len(best) - 4)
    before = min(len(prev), room // 2)
    after = min(len(following), room - before)
    return "\n\n".join(x for x in (prev[len(prev) - before:] if before else "", best, following[:after] if after else "") if x)


def passages(blocks, text):
    """Up to MAX_PASSAGES passages of the book for an item: the blocks that share the most words with it, best first (earlier first
    on a tie), each with the block before and after it, no two within two blocks of each other."""
    words = _prefixes(text)
    if not words:
        return []
    scored = sorted(((-len(words & _prefixes(b)), n) for n, b in enumerate(blocks)))
    chosen = []
    for negative, n in scored:
        if negative == 0 or len(chosen) == MAX_PASSAGES:
            break
        if all(abs(n - m) >= 3 for m in chosen):
            chosen.append(n)
    out = []
    for n in chosen:
        best = blocks[n]
        if len(best) > PASSAGE_CHARS:  # a long block is cut around the first of the words that matched
            first = min((m.start() for m in _WORD.finditer(best.casefold()) if m.group()[:5] in words and len(m.group()) >= 4), default=0)
            best = best[max(0, first - 200):]
        out.append(_cut(blocks[n - 1] if n else "", best, blocks[n + 1] if n + 1 < len(blocks) else ""))
    return out


def _draw(rng, cards, quota):
    """`quota` items from `cards`: `[(book_id, version_id, card, generation, field, position, text)]`."""
    order = sorted(cards, key=lambda c: (c[0], c[1]))
    rng.shuffle(order)
    pools = []
    for book_id, version_id, made, number in order:
        by_field = {}
        for field, position, text in _items_of(made["model"]):
            by_field.setdefault(field, []).append((position, text))
        names = sorted(by_field)
        rng.shuffle(names)
        for name in names:
            rng.shuffle(by_field[name])
        pools.append({"card": (book_id, version_id, made, number), "names": names, "by_field": by_field, "next": 0})
    if quota > sum(len(v) for p in pools for v in p["by_field"].values()):
        raise KbError("the cards do not hold as many items as the sample asks for")
    picked = []
    while len(picked) < quota:
        for pool in pools:
            if len(picked) == quota:
                break
            for _ in range(len(pool["names"])):
                name = pool["names"][pool["next"] % len(pool["names"])]
                pool["next"] += 1
                if pool["by_field"][name]:
                    position, text = pool["by_field"][name].pop()
                    book_id, version_id, made, number = pool["card"]
                    picked.append((book_id, version_id, made, number, name, position, text))
                    break
    return picked


def _spread(rng, items, count):
    """`count` of `items` taken from different fields in turn."""
    by_field = {}
    for item in items:
        by_field.setdefault(item["field"], []).append(item)
    names = sorted(by_field)
    rng.shuffle(names)
    for name in names:
        rng.shuffle(by_field[name])
    chosen = []
    while len(chosen) < count:
        for name in names:
            if by_field[name] and len(chosen) < count:
                chosen.append(by_field[name].pop())
    keep = {i["id"] for i in chosen}
    return [i for i in items if i["id"] in keep]


def _prepare(outdir):
    """Check the folder and make it if it is not there; returns True if it was made here."""
    paths.require_outside(outdir, "the folder for the sample")
    parent = os.path.realpath(os.path.dirname(os.path.abspath(outdir)))
    folder = os.path.join(parent, os.path.basename(os.path.abspath(outdir)))
    if paths.inside_project(parent):
        raise KbError("the folder for the sample is inside the project's own folder; the files of a trial are held outside the repository")
    if os.path.lexists(folder):
        if os.path.islink(folder) or not os.path.isdir(folder) or os.listdir(folder):
            raise KbError("the folder for the sample exists and is not an empty folder")
        os.chmod(folder, 0o700)
        return folder, False
    if not os.path.isdir(parent):
        raise KbError("the folder that is to hold the sample is not there")
    os.mkdir(folder, 0o700)
    os.chmod(folder, 0o700)
    return folder, True


def _write_text(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())


def sample(store, outdir, items=80, calibration=15, seed=None, generations=None, books=None):
    """Draw the sample and write its files in `outdir`; returns a summary of numbers. Refuses a folder inside the project or one that
    holds files, a sample larger than the cards hold, a calibration larger than the sample, a generation no card has, and a book
    whose converted text cannot be read. Changes nothing in the library."""
    if type(items) is not int or not 1 <= items <= MAX_ITEMS or type(calibration) is not int or not 0 <= calibration <= items:
        raise KbError(f"the sample is from 1 to {MAX_ITEMS} items and its calibration subset from 0 to as many as the sample")
    if seed is None:
        seed = secrets.randbelow(10 ** 9)
    if type(seed) is not int or not 0 <= seed < 10 ** 12:
        raise KbError("the seed is a whole number")
    wanted = None if generations is None else sorted(set(generations))
    if wanted is not None and (not wanted or not all(type(g) is int and g > 0 for g in wanted)):
        raise KbError("a generation is a whole number from 1")
    folder_check = os.path.realpath(os.path.dirname(os.path.abspath(outdir)))
    paths.require_outside(outdir, "the folder for the sample")
    if paths.inside_project(folder_check):
        raise KbError("the folder for the sample is inside the project's own folder; the files of a trial are held outside the repository")
    pool, unreadable = _cards(store, wanted, books)
    for cards in pool.values():  # a book whose text cannot be read stops the sample before anything is written
        for book_id, version_id, _, _ in cards:
            _blocks(store, book_id, version_id)
    numbers = sorted(pool)
    picked = []
    for n, group in enumerate(numbers):
        quota = items // len(numbers) + (1 if n < items % len(numbers) else 0)
        picked += _draw(random.Random(f"{seed}:{group}"), pool[group], quota)
    random.Random(f"{seed}:order").shuffle(picked)
    cache = {}
    listed, key = [], {}
    for n, (book_id, version_id, made, number, field, position, text) in enumerate(picked, start=1):
        item_id = f"i{n:03d}"
        if (book_id, version_id) not in cache:
            cache[(book_id, version_id)] = _blocks(store, book_id, version_id)
        listed.append({"id": item_id, "book_id": book_id, "title": made["title"], "field": field, "text": text,
                       "passages": passages(cache[(book_id, version_id)], text), "label": None, "labelled_by": None, "note": ""})
        key[item_id] = {"book_id": book_id, "version_id": version_id, "generation": number, "field": field, "position": position,
                        "sha256": _sha(text)}
    subset = _spread(random.Random(f"{seed}:calibration"), listed, calibration)
    head = {"format": FORMAT, "untrusted": True, "rubric": RUBRIC}
    folder, made_here = _prepare(outdir)
    written = []
    try:
        for name, obj in (("items.json", {**head, "items": listed}), ("calibration.json", {**head, "items": subset}),
                          ("key.json", {"format": FORMAT, "seed": seed, "generations": sorted({e["generation"] for e in key.values()}),
                                        "items": key})):
            written.append(name)
            config.write_json_atomic(os.path.join(folder, name), obj, 0o600)
        written.append("rubric.md")
        _write_text(os.path.join(folder, "rubric.md"), RUBRIC)
    except BaseException:
        for name in written:  # only what this call wrote; a file of someone else that appeared in the folder is left alone
            try:
                os.remove(os.path.join(folder, name))
            except OSError:
                pass
        if made_here:
            try:
                os.rmdir(folder)
            except OSError:
                pass
        raise
    count = lambda values: {str(k): values.count(k) for k in sorted(set(values))}
    return {"items": len(listed), "calibration": len(subset), "seed": seed, "cards": len({(e[0], e[1], e[3]) for e in picked}),
            "unreadable_cards": unreadable, "generations": count([e[3] for e in picked]), "fields": count([e[4] for e in picked])}


def _read_json(path, what):
    """The JSON object in a regular file of at most MAX_FILE bytes, with no repeated key; a refusal for anything else (a pipe, a file
    that is too large, text that is not JSON, nesting that is too deep, a number that is too long)."""
    try:
        if not os.path.isfile(path):
            raise KbError(f"{what} is not a file")
        with open(path, "rb") as f:
            raw = f.read(MAX_FILE + 1)
        if len(raw) > MAX_FILE:
            raise KbError(f"{what} is larger than a sample file may be")
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_no_repeats)
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        raise KbError(f"{what} cannot be read") from None


def _load(path, what):
    """The labelled-items file at `path`, checked. Returns the list of items."""
    doc = _read_json(path, what)
    if not isinstance(doc, dict) or doc.get("format") != FORMAT or type(doc.get("format")) is not int \
            or set(doc) != {"format", "untrusted", "rubric", "items"} or not isinstance(doc["items"], list) or len(doc["items"]) > MAX_ITEMS:
        raise KbError(f"{what} is not a file of items of this format")
    seen = set()
    for item in doc["items"]:
        _check_item(item, what)
        if item["id"] in seen:
            raise KbError(f"{what} holds the id {item['id']} twice")
        seen.add(item["id"])
    return doc["items"]


def _no_repeats(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError("a key is repeated")
        out[k] = v
    return out


def _check_item(item, what):
    bad = lambda why: KbError(f"{what} holds an item that is not valid: {why}")
    if not isinstance(item, dict) or set(item) != _ITEM_KEYS:
        raise bad("it does not have the keys of an item")
    if not isinstance(item["id"], str) or not _ID.fullmatch(item["id"]):
        raise bad("its id")
    ids.check_id(item["book_id"])
    if item["field"] not in FIELDS:
        raise bad("its field")
    if not isinstance(item["title"], str) or len(item["title"]) > 500:
        raise bad("its title")
    if not isinstance(item["text"], str) or not item["text"] or len(item["text"]) > MAX_TEXT:
        raise bad("its text")
    if not isinstance(item["passages"], list) or len(item["passages"]) > MAX_PASSAGES or not all(
            isinstance(p, str) and len(p) <= PASSAGE_CHARS + 100 for p in item["passages"]):
        raise bad("its passages")
    if item["label"] is not None and item["label"] not in CHOICES:
        raise bad(f"its label is not one of {', '.join(CHOICES)}")
    labeller = item["labelled_by"]
    if labeller is not None and (not isinstance(labeller, str) or not labeller.strip() or len(labeller) > MAX_LABELLER):
        raise bad("its labeller")
    if item["label"] is not None and labeller is None:
        raise bad("a label with no labeller")
    if not isinstance(item["note"], str) or len(item["note"]) > MAX_NOTE:
        raise bad("its note")
    if item["label"] == "inference" and not item["note"].strip():
        raise bad("an inference needs a note naming the passage it follows from")


def _load_key(path):
    doc = _read_json(path, "the key file")
    if not isinstance(doc, dict) or doc.get("format") != FORMAT or not isinstance(doc.get("items"), dict):
        raise KbError("the key file is not a key of this format")
    for entry in doc["items"].values():
        if not isinstance(entry, dict) or set(entry) != {"book_id", "version_id", "generation", "field", "position", "sha256"} \
                or type(entry["generation"]) is not int or not 1 <= entry["generation"] <= 10 ** 6:
            raise KbError("the key file holds an entry that is not valid")
    return doc["items"]


def accuracy(items_path, key_path):
    """Counts of supported, unsupported and inference items (and skipped ones) by generation and field, from the labelled items and the
    key they were drawn with. Every item must be labelled and must be the item the key names. Holds no item text."""
    items = _load(items_path, "the items file")
    key = _load_key(key_path)
    if {i["id"] for i in items} != set(key):
        raise KbError("the items are not the ones the key was made for (the ids differ)")
    for item in items:
        entry = key[item["id"]]
        if _sha(item["text"]) != entry["sha256"] or item["field"] != entry["field"] or item["book_id"] != entry["book_id"]:
            raise KbError(f"the item {item['id']} is not the item the key names (its text, field or book differs)")
        if item["label"] is None:
            raise KbError(f"the item {item['id']} is not labelled")
    blank = lambda: {"items": 0, "skipped": 0, **{label: 0 for label in LABELS}}
    generations = {}
    for item in items:
        group = generations.setdefault(str(key[item["id"]]["generation"]), {**blank(), "fields": {}})
        for target in (group, group["fields"].setdefault(item["field"], blank())):
            target["items"] += 1
            target["skipped" if item["label"] == "skip" else item["label"]] += 1
    for group in generations.values():
        judged = group["items"] - group["skipped"]
        group["shares"] = {label: round(group[label] / judged, 4) for label in LABELS} if judged else None
    labeller = {}
    for item in items:
        labeller[item["labelled_by"]] = labeller.get(item["labelled_by"], 0) + 1
    return {"items": len(items), "notes": sum(1 for i in items if i["note"].strip()), "labelled_by": labeller,
            "generations": dict(sorted(generations.items()))}


def agreement(first_path, second_path):
    """How far two labellings of the same items agree. The files may be the whole sample and a subset of it; the comparison is over
    the ids of the smaller. Holds no item text."""
    first = {i["id"]: i for i in _load(first_path, "the first file")}
    second = {i["id"]: i for i in _load(second_path, "the second file")}
    small, large = (first, second) if len(first) <= len(second) else (second, first)
    if not set(small) <= set(large):
        raise KbError("the smaller file holds an item that the other does not")
    for item_id, item in small.items():
        other = large[item_id]
        if any(item[k] != other[k] for k in ("text", "field", "book_id")):
            raise KbError(f"the item {item_id} differs between the files")
    compared = agree = skipped = unlabelled = 0
    pairs, differ = {}, []
    for item_id in sorted(small):
        a, b = first.get(item_id), second.get(item_id)
        if a["label"] is None or b["label"] is None:
            unlabelled += 1
        elif "skip" in (a["label"], b["label"]):
            skipped += 1
        else:
            compared += 1
            pairs[(a["label"], b["label"])] = pairs.get((a["label"], b["label"]), 0) + 1
            if a["label"] == b["label"]:
                agree += 1
            else:
                differ.append(item_id)
    return {"compared": compared, "agree": agree, "share": round(agree / compared, 4) if compared else None, "skipped": skipped,
            "unlabelled": unlabelled, "differ": differ,
            "pairs": [{"first": f, "second": s, "count": n} for (f, s), n in sorted(pairs.items())]}
