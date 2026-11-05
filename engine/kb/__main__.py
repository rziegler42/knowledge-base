"""Command line: `python3 -m kb setup <bulk-root> <index-root> [--allow-main-disk]` and `python3 -m kb check`."""
import argparse
import json
import sys

from . import KbError, __version__, capture_url, config, identity, library
from .store import Store


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
    args = parser.parse_args(argv)
    try:
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
