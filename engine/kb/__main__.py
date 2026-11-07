"""Command line: `python3 -m kb setup <bulk-root> <index-root> [--allow-main-disk]` and `python3 -m kb check`."""
import argparse
import json
import sys

from . import (KbError, __version__, approvals, capture_arxiv, capture_url, config, convert_html, convert_pdf, identity, index,
               library, models, process, read, scan, search, stages, textutil)
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
    args = parser.parse_args(argv)
    try:
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
