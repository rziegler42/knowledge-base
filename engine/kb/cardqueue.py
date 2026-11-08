"""A queue of cards: make the cards of many books by working through the models one at a time (`docs/specs/card.md`).

`cards` goes through every model for one book before the next book starts. A queue visits each model once for all the books that are
waiting for it, so that a model is loaded as few times as the work allows, whatever the number of books.

    plan    a snapshot of the books that need a card (active, converted, no card; or all of them with `again`), written as a run in the
            index root; it sends nothing. A book that arrives later is not in the run.
    run     works through the run in passes. A pass visits the models in the order of the stages (the notes, the card, the checks, and,
            if a model is set for it, the second round and its checks); at each visit it takes every waiting book as far as the calls
            of the models it is serving go (`cardmake.make_model_part` with a journal and `allow`), and a book that comes to a call
            for another model waits for that model's turn. A card is filed as a new generation as soon as its last call is made. A call
            that fails or is refused is kept aside as `cards` keeps it, and tried again in the next pass; after one more try the book is
            reported as failed. A book whose conversion changed since the plan, or that is no longer active, is dropped and reported.
    status  where each book of a run has got to, with no text of any book.

The models are grouped by the server and model the config names for them, not by the entry: two entries that name the same server and
model are one visit, and each call keeps the options of its own entry. The state of a run is a manifest and a journal of each book's
calls (`cardstate`), in the index root, derived and disposable. Only one holder of a run's lock runs it at a time; the lock is released
when the holder ends or is killed. A run that is stopped at any point and run again repeats no call that was saved."""
import secrets
import time

from . import KbError, card, cardmake, cardstate, catalog, models, textutil

RETRIES = 1     # a stage that fails is tried once more, in the next pass
PASS_CAP = 3
REASON = 200    # characters of a reason kept in the manifest
STATE_KEYS = ("waiting", "done", "failed", "dropped")


def _sequence(cfg):
    """The model entry of each stage in the order of the calls of a card, found before anything is sent: the notes, the card, the
    checks, and, if a model is set for it, the second round and its checks."""
    notes, card_entry, check = (models.choose(cfg, t)[0] for t in ("card-notes", "card", "card-check"))
    more = models.optional(cfg, "card-more")
    return [notes, card_entry, check] + ([more, check] if more else [])


def _turns(cfg, sequence):
    """The visits of a pass: for each distinct run of stages on one server and model, the set of entries that name that server and
    model among the stages (what is served at the visit)."""
    entries = models.registry(cfg)
    group = lambda name: (entries[name]["server"], entries[name]["model"])
    turns = []
    for name in sequence:
        if not turns or turns[-1][0] != group(name):
            turns.append((group(name), set()))
    return [(g, {n for n in set(sequence) if group(n) == g}) for g, _ in turns]


def _stamp():
    return time.strftime("%Y%m%dt%H%M%Sz", time.gmtime()) + "-" + secrets.token_hex(3)


def plan(store, cfg, book_ids=None, again=False):
    """Plan a run: write the manifest and return a summary (the run's name, the number of books, what was left out, the order of the
    models by entry, and the calls that can be counted before the answers are known). Makes no call. A book that is not there, or a
    setting that is missing, is a refusal and nothing is written."""
    order = _sequence(cfg)
    if book_ids is not None:
        for book_id in book_ids:
            store.read_book(book_id)
    skipped = {"inactive": 0, "not_converted": 0, "has_card": 0}
    items, notes_calls, model_items, seen = [], 0, 0, set()
    limit = cardmake.pieces_limit(cfg)
    for book_id in (book_ids if book_ids is not None else store.list_books()):
        if book_id in seen:  # a book named twice is planned once
            continue
        seen.add(book_id)
        book = store.read_book(book_id)
        version_id = book.get("current_version")
        if book.get("state") != "active":
            skipped["inactive"] += 1
            continue
        generations = card.generations(store, book_id, version_id) if version_id else []
        if generations and not again:
            skipped["has_card"] += 1
            continue
        try:
            chosen = cardmake.plan_version(store, cfg, book_id, version_id, True)
        except KbError:
            skipped["not_converted"] += 1
            continue
        fingerprint = None
        if chosen[0] == "model":  # a card made with the models: it is for this conversion, and nothing else
            fingerprint = chosen[1][0]
            notes_calls += min(len(cardmake.pieces(chosen[1][1])), limit)
            model_items += 1
        items.append({"book_id": book_id, "version_id": version_id, "fingerprint": fingerprint,
                      "had": generations[-1] if generations else 0, "status": "waiting", "attempts": 0, "generation": None, "reason": ""})
    if len(items) > cardstate.MAX_ITEMS:
        raise KbError(f"a run holds at most {cardstate.MAX_ITEMS} books; name fewer with --book")
    index_root = store.cfg["index_root"]
    for _ in range(5):
        run_id = _stamp()
        if cardstate.read_manifest(index_root, run_id) is None:
            break
    else:
        raise KbError("no free name for the run was found")
    cardstate.write_manifest(index_root, run_id, cardstate.Manifest(run_id, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), again, items))
    return {"run": run_id, "books": len(items), "again": again, "skipped": skipped, "order": order,
            "calls_known": {"notes": notes_calls, "card": model_items},
            "calls_note": "the checks and the second round depend on the answers; about two calls for the checks for each card"}


def _counts(manifest):
    counts = {k: 0 for k in STATE_KEYS}
    for item in manifest.items:
        counts[item["status"]] += 1
    return counts


def _items(manifest):
    return [{k: i[k] for k in ("book_id", "version_id", "status", "generation", "reason", "attempts")} for i in manifest.items]


class ManifestFault(KbError):
    """The manifest of the run cannot be kept. The run stops: its state cannot be trusted to say where it has got to."""


def _save(index_root, manifest):
    try:
        cardstate.write_manifest(index_root, manifest.run, manifest)
    except KbError as e:
        raise ManifestFault(str(e)) from None


def _finish(index_root, manifest, item, status, reason="", generation=None, keep_journal=False):
    item["status"], item["reason"], item["generation"] = status, textutil.clean(reason, REASON), generation
    if not keep_journal:
        cardstate.remove(index_root, manifest.run, item["book_id"], item["version_id"])
    _save(index_root, manifest)


def _fail(index_root, manifest, item, reason):
    """A call failed: another try in the next pass, or the book is failed if it has been tried again already."""
    item["attempts"] += 1
    item["reason"] = textutil.clean(reason, REASON)
    if item["attempts"] > RETRIES:
        _finish(index_root, manifest, item, "failed", reason, keep_journal=True)
    else:
        _save(index_root, manifest)


def _serve(store, cfg, manifest, item, allow, launcher, root):
    """Take one book as far as the models in `allow` go. Returns "paused" (it waits for another model), "blocked" (a call failed:
    leave it for the next pass) or "finished" (its card is filed, or it is dropped or failed)."""
    index_root = store.cfg["index_root"]
    book_id, version_id = item["book_id"], item["version_id"]
    try:
        book = store.read_book(book_id)
    except KbError as e:
        _finish(index_root, manifest, item, "dropped", f"the book cannot be read: {e}")
        return "finished"
    if book.get("state") != "active":
        _finish(index_root, manifest, item, "dropped", "the book is no longer active")
        return "finished"
    if book.get("current_version") != version_id:
        _finish(index_root, manifest, item, "dropped", "the book has a newer version than the plan saw; plan again for it")
        return "finished"
    generations = card.generations(store, book_id, version_id)
    if (generations[-1] if generations else 0) > item["had"]:
        _finish(index_root, manifest, item, "done", "a card was filed after the plan", generation=generations[-1])
        return "finished"
    try:
        chosen = cardmake.plan_version(store, cfg, book_id, version_id, True)
    except KbError as e:
        _finish(index_root, manifest, item, "dropped", f"the version cannot be carded: {e}")
        return "finished"
    if chosen[0] == "metadata":
        if item["fingerprint"] is not None:  # the plan saw a conversion that is for the models, and now there is none, or too little text
            _finish(index_root, manifest, item, "dropped", "the conversion in use changed after the plan, or its text is now below the cutoff")
            return "finished"
        try:
            number = card.file(store, chosen[1])
        except (KbError, OSError) as e:
            _fail(index_root, manifest, item, f"the card could not be filed: {e}")
            return "blocked" if item["status"] == "waiting" else "finished"
        _finish(index_root, manifest, item, "done", generation=number)
        return "finished"
    _, loaded, mechanical = chosen
    if loaded[0] != item["fingerprint"]:
        _finish(index_root, manifest, item, "dropped", "the conversion in use changed after the plan")
        return "finished"
    save = lambda j: cardstate.write(index_root, manifest.run, book_id, version_id, j)
    try:
        journal = cardstate.read(index_root, manifest.run, book_id, version_id)
    except KbError as e:  # a journal that cannot be read: this book is dropped and the run goes on; it is left as it is, for the owner
        _finish(index_root, manifest, item, "dropped", f"the saved state of the card is not usable: {e}", keep_journal=True)
        return "finished"
    try:
        if journal is None:
            journal = cardmake.new_journal(cfg, loaded[1], mechanical["title"], book_id, version_id, fingerprint=loaded[0],
                                           kind=mechanical["kind"], save=save)
        else:
            journal.set_save(save)
        part = cardmake.make_model_part(cfg, loaded[1], mechanical["title"], launcher=launcher, root=root, kind=mechanical["kind"],
                                        journal=journal, allow=allow,
                                        identity={"book_id": book_id, "version_id": version_id, "conversion": loaded[0]})
    except cardmake.Pause:
        return "paused"
    except (cardstate.Stale, cardmake.JournalFault) as e:
        _finish(index_root, manifest, item, "dropped", f"the saved state of the card is not usable: {e}")
        return "finished"
    except models.AnswerRefused as refusal:
        kept = cardmake.keep_aside(store, refusal, book_id, version_id)
        _fail(index_root, manifest, item, str(kept) + (f" ({kept.note})" if kept.note else ""))
        return "blocked" if item["status"] == "waiting" else "finished"
    except KbError as e:
        _fail(index_root, manifest, item, str(e))
        return "blocked" if item["status"] == "waiting" else "finished"
    except Exception as e:  # whatever one book's data does to the program, the other books go on; only the kind of error is shown
        _fail(index_root, manifest, item, f"an unexpected error ({type(e).__name__})")
        return "blocked" if item["status"] == "waiting" else "finished"
    try:
        report = cardmake.file_model_card(store, book_id, version_id, part)
    except (KbError, OSError) as e:  # the card was made and cannot be filed: a failure of this book, not of the run
        _fail(index_root, manifest, item, f"the card could not be filed: {e}")
        return "blocked" if item["status"] == "waiting" else "finished"
    _finish(index_root, manifest, item, "done", generation=report["generation"])
    return "finished"


def run(store, cfg, run_id, passes=PASS_CAP, launcher=None, root=None):
    """Run a planned run until nothing is waiting or `passes` passes have been made, and return the report: the counts, each book
    with its status, generation and reason, the passes made, and the result of rebuilding the catalog (None if no card was made now).
    A run that is run again goes on from where it was."""
    index_root = store.cfg["index_root"]
    if type(passes) is not int or not 1 <= passes <= 10:
        raise KbError("the number of passes is a whole number from 1 to 10")
    if cardstate.read_manifest(index_root, run_id) is None:
        raise KbError("there is no run with that name; make one with `cards-queue plan`")
    sequence = _sequence(cfg)
    turns = _turns(cfg, sequence)
    made_now, made_passes = 0, 0
    with cardstate.lock(index_root, run_id):
        manifest = cardstate.read_manifest(index_root, run_id)
        while made_passes < passes and any(i["status"] == "waiting" for i in manifest.items):
            made_passes += 1
            blocked = set()
            for _, allow in turns:
                for position, item in enumerate(manifest.items):
                    if item["status"] != "waiting" or position in blocked:
                        continue
                    try:
                        outcome = _serve(store, cfg, manifest, item, allow, launcher, root)
                    except ManifestFault:
                        raise
                    except Exception as e:  # whatever one book's data does to the program, the other books go on; only the kind is shown
                        _fail(index_root, manifest, item, f"an unexpected error ({type(e).__name__})")
                        outcome = "blocked" if item["status"] == "waiting" else "finished"
                    if outcome == "blocked":
                        blocked.add(position)
                    elif item["status"] == "done":
                        made_now += 1
            manifest.passes += 1
            _save(index_root, manifest)
    catalog_result, note = None, ""
    if made_now:
        try:
            catalog_result = catalog.rebuild(store)
        except KbError as e:
            catalog_result = {"failed": textutil.clean(str(e), 300), "command": catalog.COMMAND}
    elif any(i["status"] == "done" for i in manifest.items):
        note = ("no card was made by this call, so the catalog was not rebuilt; if cards of this run were made before, run "
                f"`{catalog.COMMAND}`")
    return {"run": run_id, "passes": made_passes, "counts": _counts(manifest), "items": _items(manifest), "catalog": catalog_result,
            "catalog_note": note}


_STAGE = {"card-notes": "notes", "card": "card", "card-check": "check", "card-more": "round"}


def status(store, run_id):
    """Where each book of a run has got to: the counts, and for the books that wait, how far their calls have got. No book text."""
    index_root = store.cfg["index_root"]
    manifest = cardstate.read_manifest(index_root, run_id)
    if manifest is None:
        raise KbError("there is no run with that name")
    waiting = {}
    for item in manifest.items:
        if item["status"] != "waiting":
            continue
        try:
            journal = cardstate.read(index_root, run_id, item["book_id"], item["version_id"])
        except KbError:  # one journal that cannot be read does not hide the others
            waiting["unreadable"] = waiting.get("unreadable", 0) + 1
            continue
        if journal is None or not journal.entries:
            where = "not started"
        else:
            last = journal.entries[-1]["job"]
            where = _STAGE.get(last, last)
            if last == "card-check" and any(e["job"] == "card-more" for e in journal.entries):
                where = "round check"
        waiting[where] = waiting.get(where, 0) + 1
    return {"run": run_id, "passes": manifest.passes, "counts": _counts(manifest), "waiting": waiting, "items": _items(manifest)}
