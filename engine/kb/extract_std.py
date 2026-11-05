"""The plain HTML extractor: the page's text as blocks, with the Python standard library only.

    python -I -S extract_std.py INPUT_DIR OUTPUT_DIR

It reads INPUT_DIR/page.html and writes OUTPUT_DIR/blocks.json. It runs inside the sandbox of the tool runner, so it is a
program of its own: it imports nothing from the engine, and nothing it reads can make it do more than write that file.

Headings, paragraphs, list items, quotes, code and table rows are blocks; text between them is kept; navigation, forms,
scripts, styles, templates, graphics and anything hidden (the `hidden` attribute, `aria-hidden`, `display:none`,
`visibility:hidden`) is left out. A page with no paragraph or heading tags is one block that keeps its line breaks.
The page is read up to MAX_HTML bytes; a longer one is cut and the output says so."""
import codecs
import json
import os
import re
import sys
from html.parser import HTMLParser

MAX_HTML = 10_000_000
MAX_BLOCK = 1_000_000  # a longer block is cut into pieces (the engine refuses one longer than 2,000,000)
MAX_BLOCKS = 150_000
MAX_DEPTH = 10_000

SKIP = {"script", "style", "noscript", "template", "svg", "math", "iframe", "object", "embed", "canvas", "nav", "footer",
        "aside", "form", "button", "select", "option", "textarea", "dialog", "head", "title"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
BLOCK = {"p", "div", "section", "article", "main", "header", "li", "ul", "ol", "dl", "dt", "dd", "blockquote", "pre", "table",
         "thead", "tbody", "tfoot", "tr", "figure", "figcaption", "address", "details", "summary", "hr", "body", "html",
         "center", "fieldset", "legend", "h1", "h2", "h3", "h4", "h5", "h6"}
KIND = {"li": ("list_item", None), "blockquote": ("quote", None), "pre": ("code", None), "tr": ("table_row", None),
        **{f"h{n}": ("heading", n) for n in range(1, 7)}}
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)
_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_.:-]+)""", re.I)
_SURROGATE = re.compile("[\ud800-\udfff]")
# The character sets a page may name: the common text encodings. Python knows others by the same call (codecs that are not
# text at all, such as zlib or base64, and encodings that read a page as something it is not), so a name outside this list is
# not looked up: the page is read as UTF-8.
# Only ones that keep ASCII as ASCII: the EBCDIC code pages (cp500 and the like) are in the same numeric families, so the
# Windows and DOS pages are listed one by one.
_CHARSET_OK = re.compile(r"(?:utf-?8|us-ascii|ascii|latin-?1|iso-?8859-\d{1,2}|(?:windows-?|cp)125[0-8]|(?:cp|ibm)-?437|"
                         r"(?:cp|ibm)-?85[0-8]|(?:cp|ibm)-?86[0-6]|(?:cp|windows-?)874|cp9(?:32|36|49|50)|koi8-[ru]|"
                         r"mac-?roman|macintosh|gb2312|gbk|gb18030|big5(?:-hkscs)?|euc-(?:jp|kr)|shift[_-]jis|sjis|"
                         r"iso-2022-(?:jp|kr)|tis-620)", re.I)
MAX_STYLE = 65_536  # a style longer than this is not read for hiding; it is treated as hiding (no page needs one)


def strip_comments(value):
    """A style with its CSS comments removed (a comment can split a property name). One pass; a comment that never ends
    runs to the end, as in CSS."""
    out, i = [], 0
    while True:
        start = value.find("/*", i)
        if start < 0:
            out.append(value[i:])
            break
        out.append(value[i:start])
        end = value.find("*/", start + 2)
        if end < 0:
            break
        i = end + 2
    return "".join(out)


def is_hidden(attrs):
    for name, value in attrs:
        value = value or ""
        if name == "hidden" or (name == "aria-hidden" and value.strip().lower() == "true"):
            return True
        if name == "style" and (len(value) > MAX_STYLE or _HIDDEN_STYLE.search(strip_comments(value))):
            return True
    return False


def decode(data):
    """The page as text: by its byte-order mark, or the common charset its meta tag declares, or UTF-8."""
    if data.startswith(codecs.BOM_UTF8):
        return data[3:].decode("utf-8", "replace")
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", "replace")
    found = _META_CHARSET.search(data[:4096])
    if found:
        declared = found.group(1).decode("ascii", "replace")
        if _CHARSET_OK.fullmatch(declared):
            try:
                return data.decode(codecs.lookup(declared).name, "replace")
            except (LookupError, UnicodeError):
                pass
    return data.decode("utf-8", "replace")


def split_long(text):
    """A block longer than MAX_BLOCK in pieces, cut at a line break or a space where one is near the end of a piece."""
    pieces = []
    while len(text) > MAX_BLOCK:
        cut = max(text.rfind("\n", 0, MAX_BLOCK), text.rfind(" ", 0, MAX_BLOCK))
        cut = cut if cut > MAX_BLOCK // 2 else MAX_BLOCK
        pieces.append(text[:cut])
        text = text[cut:]
    pieces.append(text)
    return pieces


class Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self.truncated = False
        self.pieces = []
        self.stack = []  # [tag, skipped, kind or None, level]
        self.open = {}  # how many of each tag are on the stack, so a closing tag with no opening one is ignored at once
        self.skipping = 0
        self.kinds = []  # the (kind, level) of the elements on the stack that give their text a kind
        self.stopped = False  # set when the page nests deeper than any page does: nothing after that point is read

    def flush(self):
        if not self.pieces:
            return
        text = "".join(self.pieces)
        self.pieces = []
        lines = [" ".join(line.split()) for line in text.split("\n")]
        text = _SURROGATE.sub("�", "\n".join(line for line in lines if line))  # a lone surrogate cannot be written out
        if not text:
            return
        kind, level = self.kinds[-1] if self.kinds else ("paragraph", None)
        for piece in split_long(text):
            if len(self.blocks) >= MAX_BLOCKS:
                self.truncated = True
                return
            self.blocks.append({"kind": kind, "level": level, "text": piece})

    def push(self, tag, skipped, kind):
        if len(self.stack) >= MAX_DEPTH:
            # deeper than any real page. Past this point the skip rules could no longer be kept (a closing tag would end
            # the wrong element), so the reading stops here and the output says it was cut.
            self.flush()
            self.stopped = self.truncated = True
            return
        self.stack.append((tag, skipped, kind))
        self.open[tag] = self.open.get(tag, 0) + 1
        self.skipping += 1 if skipped else 0
        if kind:
            self.kinds.append(kind)

    def pop(self):
        tag, skipped, kind = self.stack.pop()
        self.open[tag] -= 1
        self.skipping -= 1 if skipped else 0
        if kind:
            self.kinds.pop()

    def handle_starttag(self, tag, attrs):
        if self.stopped:
            return
        if tag == "body":  # a head that was never closed ends here
            while self.open.get("head") or self.open.get("title"):
                self.pop()
        if tag == "br":
            if not self.skipping:
                self.pieces.append("\n")
            return
        if tag in ("td", "th"):
            if not self.skipping and self.pieces:
                self.pieces.append(" | ")
            return
        if tag in BLOCK and not self.skipping:
            self.flush()
        if tag in VOID:
            return
        skipped = tag in SKIP or is_hidden(attrs)
        self.push(tag, skipped, KIND.get(tag))

    def handle_endtag(self, tag):
        if self.stopped or tag in VOID or not self.open.get(tag):
            return
        if tag in BLOCK and not self.skipping:
            self.flush()
        while self.stack[-1][0] != tag:  # elements left open inside it end with it
            self.pop()
        self.pop()
        if tag in BLOCK and not self.skipping:
            self.flush()

    def handle_data(self, data):
        if not self.skipping and not self.stopped:
            self.pieces.append(data)

    def close(self):
        super().close()
        self.flush()


def main(argv):
    inp, out = argv[1], argv[2]
    fd = os.open(os.path.join(inp, "page.html"), os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as f:
        data = f.read(MAX_HTML + 1)
    truncated = len(data) > MAX_HTML
    parser = Extractor()
    parser.feed(decode(data[:MAX_HTML]))
    parser.close()
    result = {"format": 1, "truncated": truncated or parser.truncated, "blocks": parser.blocks}
    with open(os.path.join(out, "blocks.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
