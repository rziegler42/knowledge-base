"""The scan tool: objective checks on a captured file, run by the engine inside the sandbox.

    python -I scan_tool.py INPUT_DIR OUTPUT_DIR

It reads `paper.pdf` or `page.html` from INPUT_DIR and writes `scan.json` to OUTPUT_DIR, using only the standard library
(it runs with `-I` and cannot import the engine). It looks for what a file might do or hide, not what it says:

  PDF   encryption, scripts (/JS, /JavaScript), embedded files, launch actions, forms that carry scripts (/XFA),
        also inside compressed streams, with names written in the #xx escape form read as what they spell
  HTML  script elements, event-handler attributes, javascript: addresses, a meta refresh, frames and embedded objects,
        and text that is hidden from a reader (the `hidden` attribute, or a style that hides it)

Findings are counts and fixed sentences. Nothing taken from the file is copied into them, so a hostile file cannot put
text of its own into a caveat. The file is untrusted: every loop here is bounded."""
import base64
import bisect
import json
import os
import re
import sys
import zlib
from html.parser import HTMLParser

MAX_STREAMS = 2000
MAX_STREAM_OUT = 2_000_000
MAX_TOTAL_OUT = 20_000_000
KINDS = {
    "malformed": "The file does not look like the kind of file it is named as.",
    "encrypted": "The PDF is encrypted, so most of what it holds cannot be checked.",
    "javascript": "The PDF contains scripts.",
    "embedded_files": "The PDF contains embedded files.",
    "launch_action": "The PDF can launch another program.",
    "xfa_forms": "The PDF contains XFA forms, which can carry scripts.",
    "external_actions": "The PDF can submit forms, import data or open other files.",
    "rich_media": "The PDF contains rich media, which can carry code.",
    "scan_incomplete": "Part of the file was not checked: it exceeded a limit of the scan, or is built in a way the scan does not read.",
    "script_elements": "The page contains script elements.",
    "event_handlers": "The page contains event-handler attributes.",
    "javascript_urls": "The page contains addresses that run code (javascript:, vbscript: or data:text/html).",
    "meta_refresh": "The page redirects by a meta refresh.",
    "embedded_content": "The page embeds frames or objects.",
    "hidden_text": "The page contains text that is hidden from a reader.",
}


def caveat(kind, count=1):
    return {"kind": kind, "count": count, "detail": KINDS[kind]}


# --- PDF
def _unescape_names(data):
    """In a PDF name, #xx stands for the byte xx, so /J#61vaScript is /JavaScript."""
    return re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), data)


def _inflate(blob, limit):
    """(output, state): "ok" when the stream ended cleanly, "limit" when more was left than the limit allowed, "bad" when
    it is not deflate data or ends early."""
    d = zlib.decompressobj()
    try:
        out = d.decompress(blob, limit)
    except zlib.error:
        return b"", "bad"
    if d.unconsumed_tail:
        return out, "limit"
    return out, "ok" if d.eof else "bad"


def _name_pattern(name):
    """A pattern for a PDF name that also matches it written with #xx escapes: /Fil#74er is /Filter."""
    return b"/" + b"".join(b"(?:" + re.escape(bytes([c])) + b"|#%02x|#%02X)" % (c, c) for c in name) + rb"(?![A-Za-z0-9#])"


_FILTER_KEY_RAW = re.compile(_name_pattern(b"Filter"))  # for the file as it is, before escapes are undone
_FILTER_KEY = re.compile(rb"/Filter(?![A-Za-z0-9])")      # for text whose escapes are already undone
_FILTER_VALUE = re.compile(rb"/Filter\s*(\[[^\]]*\]|/[A-Za-z0-9]+)")
# parameters (or a predictor) given as a reference to another object, which this scan does not follow
_INDIRECT_PARMS = re.compile(rb"/(?:DecodeParms|DP)\s*(?:\[[^\]]*?[0-9]+\s+[0-9]+\s+R|[0-9]+\s+[0-9]+\s+R)"
                             rb"|/Predictor\s+[0-9]+\s+[0-9]+\s+R")
_NAME = re.compile(rb"/([A-Za-z0-9]+)")
_PREDICTOR = re.compile(rb"/Predictor\s+([0-9]+)")
_EOL = re.compile(rb"[ \t]*(?:\r\n|\n|\r)")  # what viewers accept after the word stream; the standard asks for less
_IMAGE_FILTERS = {b"DCTDecode", b"DCT", b"JPXDecode", b"CCITTFaxDecode", b"CCF", b"JBIG2Decode"}
_FLATE_NAMES = {b"FlateDecode", b"Fl"}
_A85_NAMES = {b"ASCII85Decode", b"A85"}
_HEX_NAMES = {b"ASCIIHexDecode", b"AHx"}
_DECODABLE = _FLATE_NAMES | _A85_NAMES | _HEX_NAMES
_XREF = re.compile(rb"/Type\s*/XRef(?![A-Za-z0-9])")
_IMAGE = re.compile(rb"/Subtype\s*/Image(?![A-Za-z0-9])")


def _decode_chain(blob, names, limit):
    """Undo a list of text and deflate filters, in order. (bytes, "ok") or (what it had, "bad" or "limit")."""
    data = blob
    for name in names:
        if name in _FLATE_NAMES:
            data, state = _inflate(data, limit)
            if state != "ok":
                return data, state
        elif name in _A85_NAMES:
            text = data.strip()
            text = (text[2:] if text.startswith(b"<~") else text).split(b"~>")[0]
            try:
                data = base64.a85decode(text, ignorechars=b" \t\n\r\v\f\x00")
            except (ValueError, TypeError):
                return b"", "bad"
        else:  # ASCIIHexDecode: pairs of hex digits up to >, an odd last digit standing for that digit and a zero
            text = re.sub(rb"\s", b"", data.split(b">")[0])
            try:
                data = bytes.fromhex((text + b"0" if len(text) % 2 else text).decode("ascii"))
            except (ValueError, UnicodeDecodeError):
                return b"", "bad"
    return data, "ok"


_ZLIB_MAGIC = (b"x\x9c", b"x\x01", b"x\xda", b"x^")
MAX_MARKERS = 2_000_000
MAX_DICT = 16384          # the longest stream dictionary the scan reads
MAX_STEPS = 256           # the most brackets it follows to find where one dictionary opens
DICT_BUDGET = 64_000_000  # the most bytes it will look back over, in all, to find dictionaries


def _dictionary_before(data, i, budget):
    """(start, end, text) of the dictionary that ends just before position i (the word stream), with the dictionaries nested
    in it, or None if there is none, it is longer than MAX_DICT or has more than MAX_STEPS brackets, or the scan has spent
    its budget of look-back. The budget is charged for the bytes actually looked over."""
    j = i
    while j > 0 and data[j - 1] in b" \t\r\n\x00\x0c":
        j -= 1
    if data[j - 2:j] != b">>" or budget[0] <= 0:
        return None
    low, depth, pos, steps = max(0, j - MAX_DICT), 1, j - 2, 0
    while pos > low and steps < MAX_STEPS:
        steps += 1
        opens, closes = data.rfind(b"<<", low, pos), data.rfind(b">>", low, pos)
        budget[0] -= (pos - (opens if opens >= 0 else low)) + (pos - (closes if closes >= 0 else low)) + 16
        if opens < 0 and closes < 0:
            break
        if closes > opens:
            depth, pos = depth + 1, closes
        else:
            depth, pos = depth - 1, opens
            if depth == 0:
                return opens, j, data[opens:j]
    return None


def _streams(data, budget):
    """Each stream of a PDF as (the text of its dictionary or None, its bytes), found in one forward pass, so the cost is
    linear in the size of the file however the markers are arranged. Yields None once if it gave up on a limit."""
    pos, seen = 0, 0
    while True:
        i = data.find(b"stream", pos)
        if i < 0:
            return
        pos = i + 6
        seen += 1
        if seen > MAX_MARKERS:
            yield None
            return
        if data[i - 3:i] == b"end":
            continue
        eol = _EOL.match(data, pos)
        if not eol:
            continue
        start = eol.end()
        end = data.find(b"endstream", start)
        if end < 0:
            return  # no end to this one or to any later one: the rest is scanned as plain bytes
        yield _dictionary_before(data, i, budget), data[start:end]
        pos = end + 9


_PATTERNS = {
    "encrypted": rb"/Encrypt(?![A-Za-z0-9])",
    "javascript": rb"/(?:JavaScript|JS)(?![A-Za-z0-9])",
    "embedded_files": rb"/EmbeddedFiles?(?![A-Za-z0-9])",
    "launch_action": rb"/Launch(?![A-Za-z0-9])",
    "xfa_forms": rb"/XFA(?![A-Za-z0-9])",
    "external_actions": rb"/(?:SubmitForm|GoToR|GoToE|ImportData)(?![A-Za-z0-9])",
    "rich_media": rb"/RichMedia(?![A-Za-z0-9])",
}


def _filter_outside(data, covered):
    """Whether a /Filter key (in any spelling) sits outside every dictionary the scan read. Compared by position, not by
    count, so a decoy cannot make the numbers come out even: a real stream whose dictionary lies inside something else's
    data, or inside a string, is found here."""
    merged = []
    for start, end in sorted(covered):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    starts = [s for s, _ in merged]
    for m in _FILTER_KEY_RAW.finditer(data):
        i = bisect.bisect_right(starts, m.start()) - 1
        if i < 0 or m.start() >= merged[i][1]:
            return True
    return False


def scan_pdf(data):
    caveats, incomplete = [], False
    if b"%PDF-" not in data[:1024]:
        caveats.append(caveat("malformed"))
    plain = _unescape_names(data)
    haystacks = [plain]  # the file as it is, which covers every stream that is not compressed
    total, decoded, budget, covered = 0, 0, [DICT_BUDGET], []
    for found in _streams(data, budget):
        if found is None:
            incomplete = True
            break
        located, blob = found
        if located is None:
            incomplete = True  # a stream whose dictionary could not be read, so what filter it uses is unknown
            continue
        covered.append(located[:2])  # the filters named inside this dictionary are accounted for below
        dictionary = _unescape_names(located[2])
        value = _FILTER_VALUE.search(dictionary)
        names = _NAME.findall(value.group(1)) if value else []
        if _FILTER_KEY.search(dictionary) and not names:
            incomplete = True  # a filter written in a way this scan does not read
        elif not names or all(n in _IMAGE_FILTERS for n in names):
            continue  # not compressed, or an image: covered by the plain scan above
        elif all(n in _DECODABLE for n in names):
            if _INDIRECT_PARMS.search(dictionary) or any(int(p) > 1 for p in _PREDICTOR.findall(dictionary)):
                # a prediction step changes the bytes before they can be read as text, and parameters given as a
                # reference are not followed. Cross-reference streams and images use prediction all the time and hold
                # nothing a viewer runs, so those are skipped; anywhere else it means the stream was not read
                if not (_XREF.search(dictionary) or _IMAGE.search(dictionary)):
                    incomplete = True
                continue
            decoded += 1
            if decoded > MAX_STREAMS or total >= MAX_TOTAL_OUT:
                incomplete = True
                break
            out, state = _decode_chain(blob, names, min(MAX_STREAM_OUT, MAX_TOTAL_OUT - total))
            total += len(out)
            if state != "ok" or out[:2] in _ZLIB_MAGIC:  # damaged, cut short, or compressed again inside
                incomplete = True
            if out:
                haystacks.append(_unescape_names(out))
        else:
            incomplete = True  # a filter this scan does not decode (LZW, run-length, crypt, or one it has not heard of)
    if not incomplete and _filter_outside(data, covered):
        incomplete = True  # a filter is declared somewhere that is not the dictionary of a stream the scan read
    for kind, pattern in _PATTERNS.items():
        count = sum(len(re.findall(pattern, h)) for h in haystacks)
        if count:
            caveats.append(caveat(kind, count))
    if incomplete:
        caveats.append(caveat("scan_incomplete"))
    return caveats


# --- HTML
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_HIDING = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?:px|pt|em|rem|%)?\s*(?:;|$|!)"
                     r"|opacity\s*:\s*0(?:\.0*)?\s*(?:;|$|!)|(?:^|;)\s*(?:width|height)\s*:\s*0(?:px)?\s*(?:;|$)"
                     r"|text-indent\s*:\s*-\d{3,}", re.I)
_MAX_DEPTH = 5000


class _Scanner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.counts = {k: 0 for k in ("script_elements", "event_handlers", "javascript_urls", "meta_refresh",
                                      "embedded_content", "hidden_text")}
        self.stack, self.open, self.hidden_from, self.in_script = [], {}, None, 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "script":
            self.counts["script_elements"] += 1
        if tag in ("iframe", "frame", "object", "embed", "applet"):
            self.counts["embedded_content"] += 1
        if tag == "meta" and a.get("http-equiv", "").strip().lower() == "refresh":
            self.counts["meta_refresh"] += 1
        for k, v in a.items():
            if re.fullmatch(r"on[a-z]+", k):
                self.counts["event_handlers"] += 1
            if k in ("href", "src", "action", "formaction", "data", "xlink:href") and re.sub(
                    r"[\s\x00-\x1f]", "", v).lower().startswith(("javascript:", "vbscript:", "data:text/html")):
                self.counts["javascript_urls"] += 1
        if tag in _VOID:
            return
        if len(self.stack) < _MAX_DEPTH:
            self.stack.append(tag)
            self.open[tag] = self.open.get(tag, 0) + 1
        style = re.sub(r"/\*.*?\*/", "", a.get("style", "")[:4096], flags=re.S)  # a comment can split the property name
        if self.hidden_from is None and ("hidden" in a or _HIDING.search(style)):
            self.hidden_from = len(self.stack)
        if tag in ("script", "style"):
            self.in_script += 1

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("script", "style") and self.in_script:
            self.in_script -= 1
        if self.open.get(tag):  # an end tag with nothing open to close costs nothing
            while self.stack:
                popped = self.stack.pop()
                self.open[popped] -= 1
                if popped == tag:
                    break
            if self.hidden_from is not None and len(self.stack) < self.hidden_from:
                self.hidden_from = None

    def handle_data(self, data):
        if self.hidden_from is not None and not self.in_script:
            self.counts["hidden_text"] += len("".join(data.split()))


MAX_HTML = 10_000_000  # the parser reads about two megabytes a second, and the scan has a time limit


def scan_html(data):
    parser = _Scanner()
    parser.feed(data[:MAX_HTML].decode("utf-8", "replace"))
    parser.close()
    caveats = [caveat(kind, n) for kind, n in parser.counts.items() if n]
    if len(data) > MAX_HTML:
        caveats.append(caveat("scan_incomplete"))  # the rest of a very large page was not read
    return caveats


def main(argv):
    inp, out = argv[1], argv[2]
    names = sorted(os.listdir(inp))
    if "paper.pdf" in names:
        kind, scanner, name = "pdf", scan_pdf, "paper.pdf"
    elif "page.html" in names:
        kind, scanner, name = "html", scan_html, "page.html"
    else:
        sys.stderr.write("no paper.pdf or page.html in the input\n")
        return 2
    with open(os.path.join(inp, name), "rb") as f:
        data = f.read()
    result = {"format": 1, "kind": kind, "bytes": len(data), "caveats": scanner(data)}
    with open(os.path.join(out, "scan.json"), "w") as f:
        json.dump(result, f, sort_keys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
