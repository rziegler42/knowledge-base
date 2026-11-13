"""Command line: `python3 -m kb setup <bulk-root> <index-root> [--allow-main-disk]` and `python3 -m kb check`."""
import argparse
import json
import sys

from . import (KbError, __version__, approvals, capture_arxiv, capture_url, card, cardmake, catalog, config, convert_html,
               convert_pdf, identity, index, library, models, process, read, scan, search, stages, textutil, trial)
from . import cardmarks, cardqueue
from . import themerun, themereflag, themevectors, weave
from . import cardsample
from . import problem
from . import problemtrial
from . import vectors
from .store import Store


# the tools the engine can describe for the owner to approve, in the order `all` prints them
DESCRIBABLE = {"kb-scan": approvals.builtin_scan_entry, "kb-html-std": convert_html.std_entry,
               "trafilatura": convert_html.trafilatura_entry, "pdftotext": convert_pdf.pdftotext_entry}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="kb", description="The knowledge-base engine.")
    parser.add_argument("--version", action="version", version=f"kb {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("setup", help="create an empty library with a bulk root and an index root")
    s.add_argument("bulk_root")
    s.add_argument("index_root")
    s.add_argument("--allow-main-disk", action="store_true",
                   help="allow the bulk root to be on the main disk (the owner's choice, made once)")
    sub.add_parser("check", help="check that writing to the library is safe")
    c = sub.add_parser("capture-url", help="fetch one web page and store it in the library")
    c.add_argument("address")
    c.add_argument("--allow-private", action="store_true",
                   help="allow addresses on this machine or a private network (and redirects to them)")
    c.add_argument("--max-bytes", type=int, default=capture_url.MAX_BYTES, help="refuse a page larger than this")
    c.add_argument("--timeout", type=float, default=capture_url.TIMEOUT, help="seconds for each network read")
    c.add_argument("--total-timeout", type=float, default=capture_url.TOTAL_TIMEOUT, help="seconds for the whole fetch")
    ax = sub.add_parser("capture-arxiv", help="fetch an arXiv paper (its PDF and metadata) and store it in the library")
    ax.add_argument("arxiv_id", help="for example 2101.00001, 2101.00001v2 or cs/0112017; with no version, the latest")
    ax.add_argument("--allow-private", action="store_true",
                    help="allow addresses on this machine or a private network (and redirects to them)")
    ax.add_argument("--api-base", default=capture_arxiv.API_BASE, help="the arXiv API address (for a mirror or a test)")
    ax.add_argument("--pdf-base", default=capture_arxiv.PDF_BASE, help="the address PDFs are fetched under")
    ax.add_argument("--max-bytes", type=int, default=capture_arxiv.PDF_MAX_BYTES, help="refuse a PDF larger than this")
    ax.add_argument("--timeout", type=float, default=capture_url.TIMEOUT, help="seconds for each network read")
    ax.add_argument("--total-timeout", type=float, default=capture_url.TOTAL_TIMEOUT, help="seconds for each fetch")
    d = sub.add_parser("describe-tool", help="print the approved-list entry for a tool, to review and paste into "
                                             "approved_tools in the config (it changes nothing)")
    d.add_argument("tool", nargs="?", default="kb-scan", choices=[*DESCRIBABLE, "all"],
                   help="which tool (default kb-scan); all prints the four as one list")
    sub.add_parser("tools", help="list the approved tools and say whether each still matches what was approved")
    pr = sub.add_parser("process", help="take every version through the stages it has not finished: scan, convert, index")
    pr.add_argument("--book", action="append", dest="books", metavar="BOOK_ID", help="only this book (may be repeated)")
    rc = sub.add_parser("reconvert", help="put the conversion (and the index) of books back to pending, so that `process` makes them "
                                          "again with the tools approved now; nothing is deleted")
    rc.add_argument("--book", action="append", dest="books", metavar="BOOK_ID",
                    help="only this book (may be repeated); with none, every active book, and every version of it")
    rc.add_argument("--scan", action="store_true", help="the scan as well, for when the scan tool was changed")
    sub.add_parser("index", help="build the search index again from the books")
    rd = sub.add_parser("read", help="the text at a locator that a search returned, in a bounded piece")
    rd.add_argument("book_id")
    rd.add_argument("locator", help="the locator, as JSON")
    rd.add_argument("--version", help="the version the result came from (default: the book's current version)")
    rd.add_argument("--chars", type=int, default=read.DEFAULT_CHARS, help=f"at most this many characters ({read.MIN_CHARS} to {read.MAX_CHARS})")
    se = sub.add_parser("search", help="keyword search; every word of the query must match")
    se.add_argument("query")
    se.add_argument("--limit", type=int, default=search.DEFAULT_LIMIT, help=f"at most this many results (1 to {search.MAX_LIMIT})")
    sub.add_parser("models", help="list the models in the config and whether model work is on; it makes no call and prints no server")
    mt = sub.add_parser("model-try", help="send the prompt on standard input to one listed model and print its answer, marked as "
                                          "untrusted, with the record of how it was made")
    mt.add_argument("name", help="the name of the model in the config")
    cs = sub.add_parser("cards", help="make the card of each named book with the models the tasks setting of the config names; "
                                      "book text goes to those models; no model, server or address is an argument")
    cs.add_argument("--book", action="append", dest="books", metavar="BOOK_ID", required=True,
                    help="a book to make a card for (repeat for more; there is no way to cover the whole library)")
    cs.add_argument("--again", action="store_true", help="make another card for a book that has one, as a new generation")
    cs.add_argument("--form", choices=cardmake.FORMS, default=cardmake.DEFAULT_FORM,
                    help=f"the form of the card call: earlier (plain summary and neutral parts) or sentences (default {cardmake.DEFAULT_FORM})")
    cq = sub.add_parser("cards-queue", help="make the cards of many books by working through the models one at a time: plan a run (a "
                                            "snapshot of the books that need a card; nothing is sent), run it, and see where it has got "
                                            "to; book text goes to the models the tasks setting names; no model, server or address is an "
                                            "argument")
    cqs = cq.add_subparsers(dest="action", required=True)
    cqp = cqs.add_parser("plan", help="plan a run for the active, converted books that have no card; sends nothing")
    cqp.add_argument("--book", action="append", dest="books", metavar="BOOK_ID", help="limit the plan to this book (repeat for more)")
    cqp.add_argument("--again", action="store_true", help="include books that have a card, to make another as a new generation")
    cqp.add_argument("--form", choices=cardmake.FORMS, default=cardmake.DEFAULT_FORM,
                     help=f"the form of the card call for the whole run: earlier or sentences (default {cardmake.DEFAULT_FORM})")
    cqr = cqs.add_parser("run", help="run a planned run until nothing is waiting or the passes are made; it can be stopped and run again")
    cqr.add_argument("run", help="the name of the run that `plan` printed")
    cqr.add_argument("--passes", type=int, default=cardqueue.PASS_CAP, help=f"at most this many passes (1 to 10, default {cardqueue.PASS_CAP})")
    cqt = cqs.add_parser("status", help="where each book of a run has got to; no book text")
    cqt.add_argument("run", help="the name of the run")
    tr = sub.add_parser("themes-run", help="make the themes of many books: plan a run (a snapshot of the books to make themes for, and why the "
                                           "others are left out; nothing is sent), run it, and see where it has got to; book text goes to the "
                                           "models the tasks setting names for theme and theme-check; no model, server or address is an argument")
    trs = tr.add_subparsers(dest="action", required=True)
    trp = trs.add_parser("plan", help="plan a run for the active books that have a card and a conversion and no themes made with this prompt and "
                                      "model; sends nothing")
    trp.add_argument("--book", action="append", dest="books", metavar="BOOK_ID", help="limit the plan to this book (repeat for more)")
    trp.add_argument("--again", action="store_true", help="include books whose themes were made with this prompt and model, to make another generation")
    trr = trs.add_parser("run", help="run a planned run: each book is made, checked and filed as a new generation; a book that fails does not end the "
                                     "run; it can be stopped and run again")
    trr.add_argument("run", help="the name of the run that `plan` printed")
    trt = trs.add_parser("status", help="where each book of a run has got to; no book text")
    trt.add_argument("run", help="the name of the run")
    rf = sub.add_parser("themes-reflag", help="give the themes already made the flags of the rule now in force, without a call to a model: plan "
                                              "(read only: the books whose flags would change) or run (a new generation for each of them)")
    rfs = rf.add_subparsers(dest="action", required=True)
    rfs.add_parser("plan", help="the books whose themes would get other flags, the books left out and why, and the themes flagged before and after; "
                                "writes nothing")
    rfs.add_parser("run", help="file the themes of each of those books as the next generation, with the new flags and all else as it was; it can "
                               "be run again and then files nothing")
    sw = sub.add_parser("card-show", help="the card of a book, with its text between the untrusted-text markers")
    sw.add_argument("book_id")
    sw.add_argument("--version", help="the version (default: the book's current version)")
    sw.add_argument("--generation", type=int, help="the card to show (default: the newest)")
    sub.add_parser("card-index", help="build the catalog of cards again from the book folders (cards are not added to it as they are made)")
    cv = sub.add_parser("card-vectors", help="make the vectors of the cards (three neutral fields of each) with the embedding model that the config "
                                             "sets for card-embed; a vector whose text has not changed is kept; the text of those fields goes to that model")
    cv.add_argument("--again", action="store_true", help="make every vector again")
    tv = sub.add_parser("theme-vectors", help="make the vectors of the themes (the summary, the whole description and each of the five parts of "
                                              "every theme, up to seven texts) with the embedding model that the config sets for card-embed; a vector "
                                              "whose text has not changed is kept; those texts go to that model")
    tv.add_argument("--again", action="store_true", help="make every vector again")
    tl = sub.add_parser("theme-links", help="the links between the themes: a weave is a set of links of one kind (the weave of same mechanism is the first); "
                                            "needs numpy, so run it with engine/.venv/bin/python")
    tls = tl.add_subparsers(dest="links_command", required=True)
    tls.add_parser("build", help="build the weave of same mechanism from the file of theme vectors (read only; nothing is sent to any model) and put it in the "
                                 "index root in place of the old one, keeping the generation before; needs `theme-vectors` run first")
    ts = sub.add_parser("theme-search", help="search the themes by meaning: the query is any text (a sentence or two about a problem), turned into "
                                             "a vector by the embedding model that the config sets for card-embed (the query goes to that model), "
                                             "and the themes are ranked by the closeness of their closest text; needs `theme-vectors` run first")
    ts.add_argument("query")
    ts.add_argument("--limit", type=int, default=catalog.DEFAULT_LIMIT, help=f"at most this many themes (1 to {catalog.MAX_LIMIT})")
    ts.add_argument("--per-book", type=int, default=themevectors.DEFAULT_PER_BOOK, dest="per_book",
                    help=f"at most this many themes of one book in the results (0 to {catalog.MAX_LIMIT}; 0 is no limit; default {themevectors.DEFAULT_PER_BOOK})")
    cx = sub.add_parser("card-search", help="keyword search of the cards; every word of the query must match in one card")
    cx.add_argument("query")
    cx.add_argument("--book", metavar="BOOK_ID", help="only the cards of this book")
    cx.add_argument("--meaning", action="store_true", help="search by meaning: the query is any text (a sentence or two about a problem), turned "
                    "into a vector by the embedding model that the config sets for card-embed (the query goes to that model), and the cards are "
                    "ranked by the closeness of their vectors; needs `card-vectors` run first; takes no --in and no --book")
    cx.add_argument("--in", dest="within", choices=list(catalog.SIDES), default=None,
                    help="where to look: all, summary (the card in the words of its source) or neutral (the five neutral fields)")
    cx.add_argument("--limit", type=int, default=catalog.DEFAULT_LIMIT, help=f"at most this many results (1 to {catalog.MAX_LIMIT})")
    ps = sub.add_parser("problem-search", help="search by meaning for each of one to five sub-problems (a problem put in general terms and "
                        "split by the caller) and print each one's ranked books and one list of the books found; each sub-problem goes to "
                        "the embedding model that the config sets for card-embed, with its query prefix, and to nothing else; needs "
                        "`card-vectors` run first; give the sub-problems after `--`")
    ps.add_argument("sub_problems", nargs="+", metavar="SUB_PROBLEM", help=f"a sub-problem, at most {problem.MAX_SUB_CHARS} characters")
    ps.add_argument("--limit", type=int, default=problem.DEFAULT_LIMIT, help=f"at most this many books from each sub-problem (1 to {problem.MAX_LIMIT})")
    ps.add_argument("--launcher", metavar="PATH", help="the absolute path of the workbench launcher (wb), for a caller whose PATH does not hold it")
    tp = sub.add_parser("trial-problems", help="run a corpus of problems through four searches (the text, the cards by keyword, the cards by "
                        "meaning, and the problem search) and write a report of the place of each expected book; both files are held outside "
                        "the repository; the problem texts and the sub-problems of the corpus go to the embedding model's server and to "
                        "nothing else; the report holds numbers and decides nothing; --check reads the corpus and the library and sends nothing")
    tp.add_argument("corpus", help="the corpus file (JSON): problems, expected and home titles, keyword queries and sub-problems")
    tp.add_argument("report", help="the report file to write")
    tp.add_argument("--replace", action="store_true", help="replace a report that exists")
    tp.add_argument("--check", action="store_true", help="read the corpus and the library, resolve the titles and print what would be run; "
                    "send nothing and write nothing")
    tr = sub.add_parser("trial", help="run a corpus of questions against the library and write a report of what the search of the cards and "
                                       "the search of the text find; both files are held outside the repository; no model is called "
                                       "and nothing in the library changes")
    tr.add_argument("corpus", help="the corpus file (JSON): questions, queries and the books that answer them")
    tr.add_argument("report", help="the report file to write")
    tr.add_argument("--replace", action="store_true", help="replace a report that exists")
    cs = sub.add_parser("card-sample", help="draw a blind sample of card items, with passages of the book, to be labelled; the files are held "
                                            "outside the repository; no model is called and nothing in the library changes")
    cs.add_argument("outdir", help="the folder to write the sample in (new or empty)")
    cs.add_argument("--items", type=int, default=None, help="the number of items (default 80; not to be given with --marks)")
    cs.add_argument("--marks", nargs="+", metavar="MARK=N", help="draw N items of each mark, inferred and stated, from the newest card of "
                    "each version, mixed; the items file does not say which is which, the key does. The count of each mark is split "
                    "equally over the fields given with --field (topics, key_ideas or caveats), and the size of the sample is the sum "
                    "of the counts (for example --marks inferred=60 stated=60 --field topics --field key_ideas)")
    cs.add_argument("--calibration", type=int, default=15, help="the number of items in the calibration subset (default 15)")
    cs.add_argument("--added", type=int, default=0, help="the number of items to draw from those that a second round added to the cards "
                    "(default 0); they are counted in the sample and marked in the key")
    cs.add_argument("--seed", type=int, default=None, help="the seed (default: a random one, recorded in the key)")
    cs.add_argument("--book", action="append", help="a book to draw from; repeat for several (default: every book that has a card)")
    cs.add_argument("--generation", type=int, action="append", help="a card generation to draw from; repeat for several "
                                                                    "(default: the newest card of each version)")
    cs.add_argument("--field", action="append", choices=list(cardsample.FIELDS), help="a field to draw from; repeat for several "
                                                                                  "(default: every field)")
    cm = sub.add_parser("card-marks", help="count the items of the cards marked stated and inferred, by field and by form of the card; "
                                           "prints numbers only, calls no model and changes nothing")
    cm.add_argument("--book", action="append", help="a book to count; repeat for several (default: every active book that has a card)")
    cm.add_argument("--generation", type=int, action="append", help="a card generation to count; repeat for several "
                                                                    "(default: the newest card of each version)")
    ca = sub.add_parser("card-accuracy", help="count the labels of a sample by generation and field")
    ca.add_argument("items", help="the labelled items file")
    ca.add_argument("key", help="the key file of the sample")
    ca.add_argument("--by-mark", action="store_true", help="also report the labels for each mark, overall and for each field "
                    "(needs the key of a sample drawn with --marks)")
    cg = sub.add_parser("card-agreement", help="compare two labellings of the same items")
    cg.add_argument("first")
    cg.add_argument("second")
    args = parser.parse_args(argv)
    try:
        if args.command == "card-sample":
            print(json.dumps(cardsample.sample(Store.open(write=False), args.outdir, items=args.items, calibration=args.calibration,
                                               seed=args.seed, generations=args.generation, books=args.book, added=args.added, fields=args.field,
                                               marks=cardsample.parse_marks(args.marks) if args.marks is not None else None),
                             indent=1))
            return 0
        if args.command == "card-marks":
            print(json.dumps(cardmarks.counts(Store.open(write=False), generations=args.generation, books=args.book), indent=1))
            return 0
        if args.command == "card-accuracy":
            print(json.dumps(cardsample.accuracy(args.items, args.key, by_mark=args.by_mark), indent=1))
            return 0
        if args.command == "card-agreement":
            print(json.dumps(cardsample.agreement(args.first, args.second), indent=1))
            return 0
        if args.command == "trial":
            print(json.dumps(trial.run(Store.open(write=False), args.corpus, args.report, replace=args.replace), indent=1))
            return 0
        if args.command == "cards-queue":
            cfg = config.load()
            store = Store.open() if args.action != "status" else Store.open(write=False)
            if args.action == "plan":
                out = cardqueue.plan(store, cfg, book_ids=args.books, again=args.again, form=args.form)
            elif args.action == "run":
                out = cardqueue.run(store, cfg, args.run, passes=args.passes)
            else:
                out = cardqueue.status(store, args.run)
            print(json.dumps(out, indent=1))
            if args.action == "run" and out["counts"]["failed"]:
                print(f"{out['counts']['failed']} book could not be carded", file=sys.stderr)
                return 1
            return 0
        if args.command == "themes-run":
            store = Store.open() if args.action != "status" else Store.open(write=False)
            if args.action == "plan":
                out = themerun.plan(store, config.load(), book_ids=args.books, again=args.again)
            elif args.action == "run":
                out = themerun.run(store, config.load(), args.run)
            else:
                out = themerun.status(store, args.run)
            print(json.dumps(out, indent=1))
            if args.action == "run":
                if out["stopped"]:
                    print(out["stopped"], file=sys.stderr)
                    return 1
                if out["counts"]["failed"]:
                    print(f"{out['counts']['failed']} book could not be given themes", file=sys.stderr)
                    return 1
            return 0
        if args.command == "themes-reflag":
            if args.action == "plan":
                out = themereflag.plan(Store.open(write=False))
            else:
                out = themereflag.run(Store.open())
            print(json.dumps(out, indent=1))
            if args.action == "run" and out["failed"]:
                print(f"{len(out['failed'])} books could not be given the new flags", file=sys.stderr)
                return 1
            return 0
        if args.command == "card-index":
            counts = catalog.rebuild(Store.open())
            print(json.dumps(counts))
            if counts["failed"]:
                print(f"{counts['failed']} book or card could not be read and is not in the catalog", file=sys.stderr)
                return 1
            return 0
        if args.command == "card-vectors":
            counts = vectors.build(Store.open(), config.load(), again=args.again)
            print(json.dumps(counts))
            if counts["left_out"]:
                print(f"{counts['left_out']} book or card could not be read and has no vectors", file=sys.stderr)
                return 1
            return 0
        if args.command == "theme-vectors":
            counts = themevectors.build(Store.open(), config.load(), again=args.again)
            print(json.dumps(counts))
            if counts["unreadable"]:
                print(f"{counts['unreadable']} book could not be read and has no vectors", file=sys.stderr)
                return 1
            return 0
        if args.command == "theme-links":
            cfg = config.load()
            print(json.dumps(weave.build(cfg["index_root"], cfg)))
            return 0
        if args.command == "theme-search":
            cfg = config.load()
            print(json.dumps(themevectors.search(cfg["index_root"], cfg, args.query, limit=args.limit, per_book=args.per_book), indent=1))
            return 0
        if args.command == "card-search":
            if args.meaning:
                if args.within is not None or args.book is not None:
                    raise KbError("a search by meaning takes no --in and no --book")
                cfg = config.load()
                found = vectors.search(cfg["index_root"], cfg, args.query, limit=args.limit)
            else:
                found = catalog.search(config.load()["index_root"], args.query, limit=args.limit, book_id=args.book,
                                       within=args.within or "all")
            print(json.dumps(found, indent=1))
            return 0
        if args.command == "trial-problems":
            print(json.dumps(problemtrial.run(Store.open(write=False), config.load(), args.corpus, args.report, replace=args.replace,
                                              check=args.check), indent=1))
            return 0
        if args.command == "problem-search":
            cfg = config.load()
            print(problem.render(problem.search(cfg["index_root"], cfg, args.sub_problems, limit=args.limit, launcher=args.launcher)))
            return 0
        if args.command == "cards":
            cfg = config.load()
            for task in models.REQUIRED_TASKS:  # model work on and a model set for each task that is needed, before any book is touched
                models.choose(cfg, task)
            cardmake.pieces_limit(cfg)  # and the number of pieces to read, if the config sets one
            reports = cardmake.run(Store.open(), cfg, args.books, again=args.again, form=args.form)
            for report in reports:
                print(json.dumps(report))
            failed = [r for r in reports if r["status"] == "failed"]
            if failed:
                print(f"{len(failed)} book could not be carded", file=sys.stderr)
            return 1 if failed else 0
        if args.command == "card-show":
            store = Store.open(write=False)
            version_id = args.version or store.read_book(args.book_id).get("current_version")
            if not version_id:
                raise KbError("the book has no version")
            number, shown = card.read(store, args.book_id, version_id, generation=args.generation)
            print(json.dumps({"untrusted": True, "book_id": shown["book_id"], "version_id": shown["version_id"], "generation": number,
                              "shelf": shown["shelf"], "partial": shown["partial"], "scan_status": shown["scan"]["status"],
                              "made": shown["made"], "text": f"{search.MARKER}\n{card.render(shown)}\n{read.END_MARKER}"}, indent=1))
            return 0
        if args.command == "models":
            print(json.dumps(models.status(config.load()), indent=1))
            return 0
        if args.command == "model-try":
            raw = sys.stdin.buffer.read(models.MAX_PROMPT + 1)
            if len(raw) > models.MAX_PROMPT:
                raise KbError(f"the prompt is too large: the bridge takes {models.MAX_PROMPT} bytes")
            try:
                prompt = raw.decode("utf-8")
            except UnicodeDecodeError:
                raise KbError("the prompt is not UTF-8 text") from None
            out = models.run_job(config.load(), args.name, prompt, models.TRY_JOB)
            # the answer is the model's text: it is shown between the markers, and withheld if it holds the words of one
            shown = textutil.title(out["values"]["answer"], 2000) or "[the answer was withheld: it holds the words of an untrusted-text marker]"
            out["values"]["answer"] = f"{search.MARKER}\n{shown}\n{read.END_MARKER}"
            print(json.dumps(out, indent=1))
            return 0
        if args.command == "describe-tool":
            entries = [make() for make in DESCRIBABLE.values()] if args.tool == "all" else DESCRIBABLE[args.tool]()
            print(json.dumps(entries, indent=1))
            return 0
        if args.command == "process":
            print(json.dumps(process.process(Store.open(), book_ids=args.books), indent=1))
            return 0
        if args.command == "reconvert":
            store = Store.open()
            cfg = config.load()
            try:  # the entry the conversion would use is the first of that name that handles web pages
                std_used = approvals.find_for("kb-html-std", "html", cfg)["version"]
            except KbError:
                std_used = None
            if std_used != __version__:
                print(f"warning: kb-html-std {__version__} is not the entry `process` would use (the first one on the list is "
                      f"{std_used or 'missing'}), so it cannot make this with it; run `python3 -m kb describe-tool all`, replace the "
                      f"list in the config with its entries, and check `python3 -m kb tools` first", file=sys.stderr)
            if args.scan:
                try:
                    approvals.find(scan.TOOL_NAME, scan.TOOL_VERSION, cfg)
                except KbError:
                    print(f"warning: {scan.TOOL_NAME} {scan.TOOL_VERSION} is not on the approved list, so `process` cannot make the scan again; "
                          f"run `python3 -m kb describe-tool all`, put its entries in the config, and check `python3 -m kb tools` first",
                          file=sys.stderr)
            report = stages.redo_books(store, args.books, scan=args.scan, reason="made again at the owner's command")
            print(json.dumps(report, indent=1))
            failed = [r for r in report if "error" in r]
            if failed:
                print(f"{len(failed)} version could not be read and was left as it was", file=sys.stderr)
            return 1 if failed else 0
        if args.command == "index":
            counts = index.rebuild(Store.open())
            print(json.dumps(counts))
            if counts["failed"]:
                print(f"{counts['failed']} book or version could not be read and is not in the index", file=sys.stderr)
                return 1
            return 0
        if args.command == "read":
            out = read.read(Store.open(write=False), args.book_id, args.locator, version_id=args.version, chars=args.chars)
            print(json.dumps(out, indent=1))
            if out["status"] not in ("found", "found_by_text"):
                print(f"{out['status']}: the passage was not read", file=sys.stderr)
                return 1
            return 0
        if args.command == "search":
            print(json.dumps(search.search(config.load()["index_root"], args.query, limit=args.limit), indent=1))
            return 0
        if args.command == "tools":
            cfg = config.load()
            rows, healthy = [], True
            for entry in approvals.approved_tools(cfg):
                try:
                    approvals.check_pins(entry)
                    approvals.check_reads(entry, cfg)
                    status = "ok"
                except KbError as e:
                    status, healthy = str(e), False
                rows.append({"name": entry["name"], "version": entry["version"], "formats": entry["formats"],
                             "status": status})
            print(json.dumps(rows, indent=1))
            return 0 if healthy else 1
        if args.command == "capture-arxiv":
            store = Store.open()
            out = capture_arxiv.capture(store, identity.Identity(store.cfg["index_root"]), args.arxiv_id,
                                        allow_private=args.allow_private, api_base=args.api_base,
                                        pdf_base=args.pdf_base, max_bytes=args.max_bytes, timeout=args.timeout,
                                        total_timeout=args.total_timeout)
            print(json.dumps(out))
            if out["status"] == "failed":
                print(f"failed: {out['reason']}", file=sys.stderr)
                return 1
            return 0
        if args.command == "capture-url":
            store = Store.open()
            out = capture_url.capture(store, identity.Identity(store.cfg["index_root"]), args.address,
                                      allow_private=args.allow_private, max_bytes=args.max_bytes,
                                      timeout=args.timeout, total_timeout=args.total_timeout)
            print(json.dumps(out))
            if out["status"] == "failed":
                print(f"failed: {out['reason']}", file=sys.stderr)
                return 1
            return 0
        if args.command == "setup":
            first_time = not config.exists()
            out = {"library_id": library.setup(args.bulk_root, args.index_root, allow_main_disk=args.allow_main_disk)}
            if first_time:
                print(library.NOTICE, file=sys.stderr)
        else:
            out = {"library_id": library.check_writable()["library_id"]}
    except KbError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"failed: {e.strerror or e}: {e.filename or ''}".rstrip(": "), file=sys.stderr)
        return 1
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
