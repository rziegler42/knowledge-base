"""The article extractor: trafilatura, as blocks.

    python -I -S extract_traf.py SITE_PACKAGES INPUT_DIR OUTPUT_DIR

It reads INPUT_DIR/page.html and writes OUTPUT_DIR/blocks.json, in the form `extract_std.py` writes. SITE_PACKAGES is the
folder of the pinned packages (`engine/requirements.lock`); the program is run with -I -S, so it puts that folder on its
import path itself. It runs inside the sandbox of the tool runner and imports nothing from the engine.

Settings (the first values, taken from the ten-page test): comments off, tables on, links and images off, no
de-duplication. It refuses to run with any trafilatura but the version it was written and tested against."""
import json
import os
import sys

EXPECTED = "2.3.1"
MAX_HTML = 10_000_000
MAX_BLOCKS = 150_000
# trafilatura's time and memory grow with the number of tags, not the number of bytes: on a page of paragraphs of one letter
# it took about 4.6 s and 275 MB for 125,000 and 31 s and 1.6 GB for a million. The page is cut after this many tags (a real
# page has a few thousand; a very large table, tens of thousands), and the output says so. Memory is not limited by the sandbox.
MAX_TAGS = 200_000
BLOCK_TAGS = {"p", "head", "item", "quote", "code", "row", "list", "table"}


def cut_at_tags(data, limit):
    """`data` up to just before its (limit+1)-th tag, and whether anything was cut."""
    position = -1
    for _ in range(limit):
        position = data.find(b"<", position + 1)
        if position < 0:
            return data, False
    following = data.find(b"<", position + 1)
    return (data[:following], True) if following >= 0 else (data, False)


def _allow_uname():
    """The sandbox does not let a program read the system's name and release, and `dateutil` (which trafilatura loads) imports
    `ctypes`, which asks for it. Where it is refused, a fixed answer is given instead, rather than allowing it for every tool."""
    real = os.uname

    def uname():
        try:
            return real()
        except OSError:
            return os.uname_result(("Darwin", "localhost", "25.0.0", "", "arm64"))
    os.uname = uname


def inline_text(el, etree):
    """The text of an element without its block-level descendants; line breaks inside it stay as line breaks."""
    parts = [el.text or ""]
    for child in el:
        if child.tag == "lb":
            parts.append("\n")
        elif child.tag not in BLOCK_TAGS:
            parts.append(etree.tostring(child, method="text", encoding="unicode", with_tail=False))
        parts.append(child.tail or "")
    return "".join(parts)


def blocks_of(xml, etree):
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)
    root = etree.fromstring(xml.encode("utf-8"), parser)
    main = root.find("main")
    blocks, truncated = [], False
    if main is None:
        return blocks, truncated
    if (main.text or "").strip():
        blocks.append({"kind": "paragraph", "level": None, "text": main.text})
    for el in main.iter():
        if el is main or el.tag not in ("head", "p", "item", "quote", "code", "row"):
            continue
        if next(el.iterancestors("row"), None) is not None:
            continue  # inside a table row, which is one block
        if el.tag == "row":
            text = " | ".join(inline_text(cell, etree) for cell in el.iter("cell"))
            kind, level = "table_row", None
        else:
            text = inline_text(el, etree)
            kind, level = {"head": ("heading", None), "item": ("list_item", None), "quote": ("quote", None),
                           "code": ("code", None)}.get(el.tag, ("paragraph", None))
            if el.tag == "p" and next(el.iterancestors("quote"), None) is not None:
                kind = "quote"
            if kind == "heading":
                rend = el.get("rend") or ""
                level = int(rend[1]) if len(rend) == 2 and rend[0] == "h" and rend[1] in "123456" else 2
        if text.strip():
            if len(blocks) >= MAX_BLOCKS:
                return blocks, True
            blocks.append({"kind": kind, "level": level, "text": text})
    return blocks, truncated


def main(argv):
    site, inp, out = argv[1], argv[2], argv[3]
    _allow_uname()
    sys.path.insert(0, site)
    import trafilatura
    from lxml import etree
    if trafilatura.__version__ != EXPECTED:
        print(f"trafilatura {trafilatura.__version__} is installed; this wrapper was written for {EXPECTED}", file=sys.stderr)
        return 3
    fd = os.open(os.path.join(inp, "page.html"), os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as f:
        data = f.read(MAX_HTML + 1)
    too_long = len(data) > MAX_HTML
    data, too_many_tags = cut_at_tags(data[:MAX_HTML], MAX_TAGS)
    cut = too_long or too_many_tags
    xml = trafilatura.extract(data, output_format="xml", include_comments=False, include_tables=True,
                              include_links=False, include_images=False, deduplicate=False)
    blocks, truncated = blocks_of(xml, etree) if xml else ([], False)
    with open(os.path.join(out, "blocks.json"), "w", encoding="utf-8") as f:
        json.dump({"format": 1, "truncated": cut or truncated, "blocks": blocks}, f, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
