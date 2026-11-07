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
import itertools
import json
import os
import re
import sys
import time
import zlib
from html.parser import HTMLParser

MAX_STREAMS = 500_000        # the most streams it decodes in a file (about 8 microseconds each when they are tiny)
MAX_STREAM_OUT = 2_000_000   # the most it takes from one stream: what makes an image "large"
MAX_TOTAL_OUT = 2_500_000_000  # the most work it does on what it decodes, in all (about 3 ns a unit, see _work): a bound on time, not on memory
MAX_ROW = 4_000_000          # the longest row of predicted data it undoes
MAX_PREDICTED_ROWS = 2_000_000  # the most passes over rows of predicted data it undoes in a file: a row costs the same however short
MAX_SECONDS = 25                # the scan stops between streams after this long (the sandbox kills it at 60): a backstop for work the weights miss
LAYER_UNITS = 20                # what each byte read by a filter after a deflate costs, in units of _work: such a layer's output may be nothing
MAX_FILTERS = 8                 # the most filters it reads through on one stream: each layer is a decode, and only the last one's output is charged
MAX_PREDICTED_BYTES = 20_000_000  # the most bytes it undoes a predictor over in a file: that work is slow Python (0.15 s a megabyte with Paeth rows)
KINDS = {
    "malformed": "The file does not look like the kind of file it is named as.",
    "encrypted": "The PDF is encrypted, so most of what it holds cannot be checked.",
    "javascript": "The PDF contains scripts.",
    "embedded_files": "The PDF contains embedded files.",
    "launch_action": "The PDF can launch another program.",
    "xfa_forms": "The PDF contains XFA forms, which can carry scripts.",
    "external_actions": "The PDF can submit forms, import data or open other files.",
    "rich_media": "The PDF contains rich media, which can carry code.",
    "pattern_in_binary_data": "Bytes inside an image or other binary data look like the name of a script, launch or similar entry. This is usually a coincidence, and it was not read as a viewer would.",
    "large_image_streams": "The PDF contains large images, of which only the first part was checked for code; code after that part would not be found.",
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
_NOT_REGULAR = frozenset(b"\x00\t\n\x0c\r ()<>[]{}/%#")  # white space and delimiters, and the escape mark itself


def _unescape_regular(data):
    """The text of a dictionary with #xx read as the letter it spells, except where that letter is white space, a delimiter or
    `%` or `#`: those stay as written. In a name they are part of the name and not what they look like (/A#3E#3E is one name, not
    a name and the end of a dictionary), and a reader that turned them into the real thing would see a structure no viewer sees."""
    def one(m):
        value = int(m.group(1), 16)
        return m.group(0) if value in _NOT_REGULAR else bytes([value])
    return re.sub(rb"#([0-9A-Fa-f]{2})", one, data)


def _unescape_names(data):
    """In a PDF name, #xx stands for the byte xx, so /J#61vaScript is /JavaScript."""
    return re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), data)


_BLANK = b" \t\r\n\x00\x0c"  # the white space of a PDF; a writer may put some between the end of a stream's data and endstream


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
    if d.eof and d.unused_data.strip(_BLANK):
        return out, "bad"  # the data goes on after the end of the deflate data: the stream is not the length the scan took it for
    return out, "ok" if d.eof else "bad"


def _name_pattern(name):
    """A pattern for a PDF name that also matches it written with #xx escapes: /Fil#74er is /Filter."""
    return b"/" + b"".join(b"(?:" + re.escape(bytes([c])) + b"|#%02x|#%02X)" % (c, c) for c in name) + rb"(?![A-Za-z0-9#])"


_FILTER_KEY_RAW = re.compile(_name_pattern(b"Filter"))  # for the file as it is, before escapes are undone
_FILTER_KEY = re.compile(rb"/Filter(?![A-Za-z0-9])")      # for text whose escapes are already undone
_FILTER_VALUE = re.compile(rb"/Filter\s*(\[[^\]]*\]|/[A-Za-z0-9]+)")
_FILTER_LIST = re.compile(rb"\[[ \t\r\n\x00\x0c]*(?:/[A-Za-z0-9]+[ \t\r\n\x00\x0c]*)*\]")  # a list of filters that holds names and nothing else
_NAME = re.compile(rb"/([A-Za-z0-9]+)")
_EOL = re.compile(rb"[ \t]*(?:\r\n|\n|\r)")  # what viewers accept after the word stream; the standard asks for less
_IMAGE_FILTERS = {b"DCTDecode", b"DCT", b"JPXDecode", b"CCITTFaxDecode", b"CCF", b"JBIG2Decode"}
_FLATE_NAMES = {b"FlateDecode", b"Fl"}
_A85_NAMES = {b"ASCII85Decode", b"A85"}
_HEX_NAMES = {b"ASCIIHexDecode", b"AHx"}
_DECODABLE = _FLATE_NAMES | _A85_NAMES | _HEX_NAMES
_IMAGE = re.compile(rb"/Subtype\s*/Image(?![A-Za-z0-9])")
_TYPE = re.compile(rb"/Type\s*/([A-Za-z0-9]+)")
# the keys without which a viewer cannot read objects out of a stream: an object stream needs /N and /First (and may have /Extends),
# a cross-reference stream /W (and has /Size and /Index). A dictionary that has any of them is not a picture's, whatever else it says.
# This is about the dictionary text the scan located. A crafted file can steer which text that is (a string holding a stream marker),
# which is why the exemption also refuses a stream whose bytes hold the word stream.
_CONTAINER_KEYS = re.compile(rb"/(?:N|First|Extends|W|Size|Index)(?![A-Za-z0-9])")


def _is_image(dictionary):
    """Whether a stream dictionary may be treated as a picture: none of the keys of an object stream or a cross-reference stream (a
    viewer reads objects, and so the actions in them, out of those), a /Subtype /Image, and no /Type but /XObject (the format makes
    the /Type of an image optional, and real images leave it out). The scan does not parse dictionaries, so the words may sit in a
    string or a nested dictionary, and a dictionary can say what it likes; what it cannot do is leave out the keys a viewer needs
    to use it as a container."""
    if _CONTAINER_KEYS.search(dictionary):
        return False  # the claim can be forged; these keys cannot be left out of a stream a viewer reads objects from
    return all(t == b"XObject" for t in _TYPE.findall(dictionary)) and bool(_IMAGE.search(dictionary))


class _Unreadable(Exception):
    """Parameters or predicted data that the scan cannot read with certainty. It is never guessed at: the stream is reported as
    not fully read, and what could be decoded before the predictor is still scanned."""


class _Spent(_Unreadable):
    """The data could be read, but the scan has already undone as much predicted data in this file as it does (the work is slow).
    For a picture this is not an incomplete scan: what was decoded before the predictor is read, and it is reported as a picture
    of which only the first part was checked."""


_WS = rb"[ \t\r\n\x00\x0c]"
_PARMS_KEY = re.compile(rb"/(?:DecodeParms|DP)(?![A-Za-z0-9])")
_PARM_KEYS = {"predictor": b"Predictor", "colors": b"Colors", "bpc": b"BitsPerComponent", "columns": b"Columns"}
_PARM_DEFAULTS = {"predictor": 1, "colors": 1, "bpc": 8, "columns": 1}
_WS_RUN = re.compile(_WS + rb"*")
_BRACKETS = re.compile(rb"<<|>>")


def _dict_inner(text, start):
    """(the text inside the dictionary that opens at text[start], where it ends). A dictionary of parameters holds numbers and
    names and nothing nested: a string, a hex string, an array or another dictionary in it, or one that does not close, is
    refused."""
    depth = 0
    for m in _BRACKETS.finditer(text, start):
        depth += 1 if m.group() == b"<<" else -1
        if depth == 0:
            inner = text[start + 2:m.start()]
            if b"<" in inner or b"(" in inner or b"[" in inner or b"%" in inner:
                # a string, a hex string, an array or another dictionary, or a comment: a comment can hold brackets and the end of the
                # dictionary, or sit between a number and `0 R`, and a viewer reads past it where this reader would not
                raise _Unreadable("the parameters hold more than numbers")
            return inner, m.end()
        if depth < 0:
            break
    raise _Unreadable("a dictionary of parameters that does not close")


def _parm_number(inner, key):
    """The whole number after /Key in a dictionary of parameters, None if the key is not there. A key twice, or a value that is
    not a whole number (a real, a negative, a reference, a name), is refused."""
    found = list(re.finditer(rb"/" + key + rb"(?![A-Za-z0-9])", inner))
    if not found:
        return None
    if len(found) > 1:
        raise _Unreadable("a parameter given twice")
    m = re.compile(_WS + rb"+([0-9]{1,9})(?=" + _WS + rb"|/|\Z)(?!" + _WS + rb"+[0-9]+" + _WS + rb"+R(?![A-Za-z0-9]))").match(inner, found[0].end())
    if not m:
        raise _Unreadable("a parameter that is not a whole number")
    return int(m.group(1))


def _parm_dict(inner):
    return {name: (lambda v: _PARM_DEFAULTS[name] if v is None else v)(_parm_number(inner, key)) for name, key in _PARM_KEYS.items()}


def _parms(dictionary, names):
    """The decode parameters of each filter in `names`: None, or a dictionary of the predictor, colours, bits and columns (the
    defaults where a key is not given). Read from the one /DecodeParms (or /DP) of the dictionary text, given directly: as a
    dictionary for one filter, or as an array with one entry (null or a dictionary) for each. A reference, a second key, a
    value that is not plain, or more entries than filters is refused with _Unreadable."""
    keys = list(_PARMS_KEY.finditer(dictionary))
    if not keys:
        return [None] * len(names)
    if len(keys) > 1:
        raise _Unreadable("two keys for the parameters")
    i = _WS_RUN.match(dictionary, keys[0].end()).end()
    if re.compile(rb"null(?![A-Za-z0-9])").match(dictionary, i):
        return [None] * len(names)
    if dictionary.startswith(b"<<", i):
        if len(names) != 1:
            raise _Unreadable("one dictionary of parameters for several filters")
        return [_parm_dict(_dict_inner(dictionary, i)[0])]
    if dictionary.startswith(b"[", i):
        close = dictionary.find(b"]", i)
        if close < 0:
            raise _Unreadable("an array of parameters that does not close")
        body, pos, items = dictionary[i + 1:close], 0, []
        while True:
            pos = _WS_RUN.match(body, pos).end()
            if pos >= len(body):
                break
            if re.compile(rb"null(?![A-Za-z0-9])").match(body, pos):
                items.append(None)
                pos += 4
            elif body.startswith(b"<<", pos):
                inner, pos = _dict_inner(body, pos)
                items.append(_parm_dict(inner))
            else:
                raise _Unreadable("an entry of the parameters that is not null or a dictionary")
        if len(items) > len(names):
            raise _Unreadable("more parameters than filters")
        return items + [None] * (len(names) - len(items))
    raise _Unreadable("parameters that are not a dictionary or an array")


_MASK = (255).__and__


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def _undo_predictor(data, parms, rows=None, volume=None):
    """The data of a stream with its predictor undone: PNG (predictors 10 to 15, whatever the number, each row says its filter)
    and TIFF (2, at 8 bits). Rows and the bytes in them are taken as they come; a last row that is cut short is undone as far as
    it goes. Anything else (another predictor, bits or colours that make no sense, a row type that is no PNG filter, a row longer
    than MAX_ROW) is refused with _Unreadable. `rows` is a one-item list, the rows left to undo in the file, and `volume` one, the
    bytes left to undo in it."""
    predictor = parms["predictor"]
    if predictor == 1:
        return data
    colors, bpc, columns = parms["colors"], parms["bpc"], parms["columns"]
    if predictor != 2 and not 10 <= predictor <= 15:
        raise _Unreadable("a predictor this scan does not undo")
    if not 1 <= colors <= 32 or bpc not in (1, 2, 4, 8, 16) or columns < 1:
        raise _Unreadable("parameters that make no sense")
    rowbytes = (colors * bpc * columns + 7) // 8
    if rowbytes > MAX_ROW:
        raise _Unreadable("a row too long to undo")
    if volume is not None:
        volume[0] -= len(data)  # the work is in the bytes, and the limit on all that is decoded is far above what this can do in time
        if volume[0] < 0:
            raise _Spent("more predicted data than the scan undoes")
    bpp = colors if predictor == 2 else max(1, (colors * bpc + 7) // 8)
    count = -(-len(data) // (rowbytes + (predictor != 2)))
    if rows is not None:
        rows[0] -= count * bpp  # a row costs a pass over it for each byte of a pixel, whatever its length
        if rows[0] < 0:
            raise _Spent("more rows of predicted data than the scan undoes")
    out = bytearray()
    if predictor == 2:
        if bpc != 8:
            raise _Unreadable("the TIFF predictor at other than 8 bits")
        for start in range(0, len(data), rowbytes):
            row = bytearray(data[start:start + rowbytes])
            for k in range(colors):
                row[k::colors] = bytes(map(_MASK, itertools.accumulate(row[k::colors])))
            out += row
        return bytes(out)
    prev, step = bytes(min(rowbytes, len(data))), rowbytes + 1  # (not a whole row of zeros for a stream that holds a few bytes)
    for start in range(0, len(data), step):
        kind, row = data[start], bytearray(data[start + 1:start + step])
        if kind == 0:
            pass
        elif kind == 1:
            for k in range(bpp):
                row[k::bpp] = bytes(map(_MASK, itertools.accumulate(row[k::bpp])))
        elif kind == 2:
            row = bytearray([(x + y) & 255 for x, y in zip(row, prev)])
        elif kind == 3:
            for i in range(len(row)):
                row[i] = (row[i] + ((row[i - bpp] if i >= bpp else 0) + prev[i]) // 2) & 255
        elif kind == 4:
            for i in range(len(row)):
                if i >= bpp:
                    row[i] = (row[i] + _paeth(row[i - bpp], prev[i], prev[i - bpp])) & 255
                else:
                    row[i] = (row[i] + prev[i]) & 255
        else:
            raise _Unreadable("a row whose filter is not a PNG filter")
        out += row
        prev = bytes(row) + prev[len(row):]
    return bytes(out)


def _decode_chain(blob, names, limit, parms=None, rows=None, raws=None, volume=None, layers=None):
    """Undo a list of text and deflate filters, in order, and the predictor of a deflate step that has one. (bytes, "ok") or (what
    it had, "bad", "limit", "spent" or "unreadable": the predictor could not be undone, and the bytes are those before it; "spent":
    the scan has undone all the predicted data it does in a file). `raws`, if
    given, gets the bytes from before each predictor that was undone. `layers`, if given, is a one-item list that gets the cost of
    every layer after a deflate: only the last output is charged by the caller, and a layer that reads two million bytes of empty
    deflate blocks gives none, at 60 nanoseconds a byte."""
    data = blob
    deflated = False  # whether a deflate has come before: only that can turn a small blob into a large input (a text filter's output
    for i, name in enumerate(names):  # is bounded by the blob), so only a layer after one is charged
        if deflated and layers is not None:
            layers[0] += LAYER_UNITS * len(data)
        if name in _FLATE_NAMES:
            deflated = True
        if name in _FLATE_NAMES:
            data, state = _inflate(data, limit)
            if state == "bad":
                return data, state
            if parms and parms[i] and parms[i]["predictor"] > 1:
                try:
                    undone = _undo_predictor(data, parms[i], rows, volume)
                except _Spent:
                    return data, ("limit" if state == "limit" else "spent")
                except _Unreadable:
                    return data, "unreadable"
                if raws is not None:
                    raws.append(data)  # the bytes before the predictor, for the patterns too: see scan_pdf
                data = undone
            if state != "ok":
                return data, state
        elif name in _A85_NAMES:
            text = data.strip()
            if b"~>" not in text:
                # the letters of endstream are ASCII85 digits, so the scan may have cut the stream short where a viewer, reading by
                # /Length, read on; text with its end mark is the whole of what a viewer decodes, text without it may not be
                return b"", "bad"
            text, _, rest = (text[2:] if text.startswith(b"<~") else text).partition(b"~>")
            if rest.strip(_BLANK):
                return b"", "bad"  # more after the end mark
            try:
                data = base64.a85decode(text, ignorechars=b" \t\n\r\v\f\x00")
            except (ValueError, TypeError):
                return b"", "bad"
        else:  # ASCIIHexDecode: pairs of hex digits up to >, an odd last digit standing for that digit and a zero
            if b">" not in data:
                return b"", "bad"  # no end mark: the scan may have cut the stream where a viewer, reading by /Length, read on
            text, _, rest = data.partition(b">")
            if rest.strip(_BLANK):
                return b"", "bad"  # more after the end mark
            text = re.sub(rb"\s", b"", text)
            try:
                data = bytes.fromhex((text + b"0" if len(text) % 2 else text).decode("ascii"))
            except (ValueError, UnicodeDecodeError):
                return b"", "bad"
    return data, "ok"


_ZLIB_MAGIC = (b"x\x9c", b"x\x01", b"x\xda", b"x^")


def _deflate_header(data):
    """Whether data begins like zlib data of any window size: a method of 8 and a check value that makes the two bytes a multiple
    of 31. More than the four common headers, and a few more things that are not: it errs on the side of calling it deflate."""
    return len(data) >= 2 and data[0] & 0x0F == 8 and (data[0] << 8 | data[1]) % 31 == 0
MAX_DICT = 16384          # the longest stream dictionary the scan reads
MAX_DEPTH = 100           # the deepest nesting of brackets in one object it reads
MAX_OBJECTS = 1_000_000   # the most objects it reads in a file: each costs about the same
MAX_UNFINISHED = 20       # the most objects it tries and cannot finish: after a broken one it reads on from the next header, so
# a file of broken objects could have it read the same long stretch over and over; an honest file has none, and one with this many is
# reported either way
MAX_READ_STEPS = 12_000_000  # the most steps it takes in all (a bracket, a string escape, a comment), so that a file of nothing but
# string escapes or comments costs as much as its size and no more

_HEADER_TEXT = rb"(?<![0-9])[0-9]{1,10}" + _WS + rb"+[0-9]{1,5}" + _WS + rb"*obj(?![A-Za-z0-9])"
_TOP = re.compile(rb"(?P<obj>" + _HEADER_TEXT + rb")|(?P<trailer>(?<![A-Za-z0-9])trailer(?![A-Za-z0-9]))")
_HEADER_AT = re.compile(_HEADER_TEXT)
# what an object value has no business holding: the word obj or endobj. Every object header holds obj, however it is written (a comment
# between its numbers, digits without end, glued to a word), and a viewer does not need an endobj, so the word and not the whole header.
_STRUCTURE = re.compile(rb"(?<![A-Za-z/])(?:end)?obj(?![A-Za-z0-9])")
_STREAM_KW = re.compile(rb"(?<![A-Za-z0-9])stream[ \t]*(?:\r\n|\n|\r)")
_LINE_END = re.compile(rb"[\r\n]")
_SPECIAL = re.compile(rb"[()<>\[\]%]")
_STRING_SPECIAL = re.compile(rb"[()\\]")
_TOKEN = re.compile(rb"/?[^\x00\t\n\x0c\r ()<>\[\]{}/%]*")  # a name, a number or a keyword


class _Unfinished(Exception):
    """An object the reader cannot read to its end."""


class _OverBudget(Exception):
    """The reader has taken all the steps it is allowed in a file."""


def _step(state):
    state["steps"] -= 1
    if state["steps"] < 0:
        raise _OverBudget


def _skip_blank(data, i, state):
    """The position after white space and comments from i."""
    n = len(data)
    while True:
        i = _WS_RUN.match(data, i).end()
        if i < n and data[i] == 0x25:
            if i >= state.get("no_line_end", n + 1):
                return n  # already searched from before here and found none
            m = _LINE_END.search(data, i)
            if m is None:
                state["no_line_end"] = i  # a comment with no line end ends the file: say so once, not once per object
                return n
            _step(state)
            i = m.end()
        else:
            return i


def _string_end(data, i, state):
    """The position after the literal string that opens at data[i]: parentheses nest, and a backslash takes the byte after it (an
    escaped parenthesis, a backslash, a line end; the digits of an octal escape are ordinary). None if it never closes."""
    depth, pos = 1, i + 1
    while True:
        m = _STRING_SPECIAL.search(data, pos)
        if m is None:
            return None
        _step(state)
        c, p = data[m.start()], m.start()
        if c == 0x5c:
            pos = p + 2
        elif c == 0x28:
            depth, pos = depth + 1, p + 1
        else:
            depth, pos = depth - 1, p + 1
            if depth == 0:
                return pos


def _container_end(data, i, state):
    """The position after the dictionary or array that opens at data[i], reading strings, hex strings and comments as such, so a
    bracket inside one is not a bracket. _Unfinished if it does not close, closes with the wrong bracket or nests deeper than
    MAX_DEPTH."""
    stack, pos = [], i
    while True:
        m = _SPECIAL.search(data, pos)
        if m is None:
            raise _Unfinished
        _step(state)
        p = m.start()
        c = data[p]
        if c == 0x28:
            pos = _string_end(data, p, state)
            if pos is None:
                raise _Unfinished
        elif c == 0x25:
            e = _LINE_END.search(data, p)
            if e is None:
                raise _Unfinished
            pos = e.end()
        elif c == 0x3c:
            if data.startswith(b"<<", p):
                stack.append(0)
                pos = p + 2
                if len(stack) > MAX_DEPTH:
                    raise _Unfinished
            else:
                e = data.find(b">", p + 1)
                if e < 0:
                    raise _Unfinished
                pos = e + 1
        elif c == 0x3e:
            if data.startswith(b">>", p):
                if not stack or stack.pop() != 0:
                    raise _Unfinished
                pos = p + 2
                if not stack:
                    return pos
            else:
                pos = p + 1  # a single > closes nothing
        elif c == 0x5b:
            stack.append(1)
            pos = p + 1
            if len(stack) > MAX_DEPTH:
                raise _Unfinished
        elif c == 0x5d:
            if not stack or stack.pop() != 1:
                raise _Unfinished
            pos = p + 1
            if not stack:
                return pos
        else:
            pos = p + 1  # a closing parenthesis with no string open


def _read_value(data, i, state):
    """(the position after the object value that starts at i, the span of its dictionary or None). Any value is read, not only a
    dictionary: a string or an array can hold text that looks like an object, and must be read to its end. _Unfinished if it
    cannot be."""
    i = _skip_blank(data, i, state)
    if i >= len(data):
        raise _Unfinished
    c = data[i]
    if c == 0x3c:
        if data.startswith(b"<<", i):
            end = _container_end(data, i, state)
            return end, (i, end)
        end = data.find(b">", i + 1)
        if end < 0:
            raise _Unfinished
        return end + 1, None
    if c == 0x5b:
        return _container_end(data, i, state), None
    if c == 0x28:
        end = _string_end(data, i, state)
        if end is None:
            raise _Unfinished
        return end, None
    end = _TOKEN.match(data, i).end()
    if end == i or _HEADER_AT.match(data, i):  # nothing a value can start with, or the next object's header: this one has no value
        raise _Unfinished
    return end, None


def _streams(data, state):
    """Each stream of a PDF as (its dictionary as (start, end, text) or None, its bytes), found by reading the file forward: from
    each `N G obj` header the object's value is read (strings, comments and all), and a dictionary followed by the word stream is
    a stream whose data runs to the first endstream. What the reader cannot account for sets state["incomplete"]: a stream
    keyword outside any object it read, an object that cannot be finished, a value that holds another object's header or end
    (which is what swallowing a real object in a string looks like), a stream with no end. A real compressed stream swallowed into
    the data of another stream is found by the check that every /Filter key lies in a dictionary that was read."""
    n, pos = len(data), 0
    try:
        while True:
            m = _TOP.search(data, pos)
            if _STREAM_KW.search(data, pos, m.start() if m else n):
                state["incomplete"] = True  # the word stream where no object the reader read is
            if m is None:
                return
            state["objects"] += 1
            if state["objects"] > MAX_OBJECTS:
                state["incomplete"] = True
                return
            try:
                end, span = _read_value(data, m.end(), state)
            except _Unfinished:
                state["incomplete"] = True
                state["unfinished"] += 1
                if state["unfinished"] >= MAX_UNFINISHED:
                    return
                pos = m.end()
                continue
            if _STRUCTURE.search(data, m.end(), end):
                state["incomplete"] = True
            pos = end
            if m.lastgroup != "obj" or span is None:
                continue
            after = _skip_blank(data, end, state)
            if not data.startswith(b"stream", after):
                continue
            eol = _EOL.match(data, after + 6)
            if eol is None:
                state["incomplete"] = True
                continue
            start = eol.end()
            stop = data.find(b"endstream", start)
            if stop < 0:
                state["incomplete"] = True
                return  # no end to this one: the rest is scanned as plain bytes, and said so
            located = (span[0], span[1], data[span[0]:span[1]]) if span[1] - span[0] <= MAX_DICT else None
            pos = stop + 9
            yield located, data[start:stop], start
    except _OverBudget:
        state["incomplete"] = True


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


def _work(piece, picture=False):
    """What reading a decoded piece costs, in units of about three nanoseconds: a unit for each byte, and more for the bytes that make
    the reading slow. Ordinary content costs its length; a piece of nothing but escapes (#41) takes thirty times as long to unescape,
    and one that is all matches takes ten times as long to collect, which a hostile file can use to make the limit on the bytes alone
    allow minutes. The costs were measured on the worst pieces tried (a hash 260 to 400 ns, since an escape may spell a slash; a
    slash 100 ns), and none took more than 3.8 ns a unit, so the limit is under ten seconds. The pixels of a picture are read twice,
    to place each match (_tally_binary), so a slash in one costs twice as much."""
    return len(piece) + 135 * piece.count(b"#") + (70 if picture else 35) * piece.count(b"/")


# The shape of a use: twelve bytes before a match that are printable or white space (the dictionary around a real name), and a byte after
# it that can begin its value (white space, a string or a hex string: a digit cannot follow a name that is a match, it would continue it). Pixels and compressed bytes seldom have it; a real action dictionary always does. (The twelve bytes are
# a fixed-width look-behind, so the pad of newlines in _tally_binary stands for the start of the data.)
_PAD = b"\n" * 12  # stands in front of the data: the start of it is printable, as the shape asks
_END = b"\xff"  # and after it: the end of the data is not a byte that begins a value (a name that ends the data has none)
_PRINTABLE = rb"\t\n\x0c\r\x20-\x7e"
_BEFORE = re.compile(rb"[" + _PRINTABLE + rb"]{12}")
_VALUE_START = frozenset(b"\t\n\x0c\r (<")


def _tally_binary(counts, binary, haystack):
    """Add to `counts` the matches in a piece of binary data that have the shape of a use, and to `binary[0]` the others. Nothing is
    dropped: the two numbers together are what _tally would have counted. The shape is checked on each match, after the plain
    pattern has found it: a look-behind at the start of a regex makes the engine try every position, about a hundred times as slow.
    (No two matches overlap: a name has no slash in it, and the end of a pattern looks ahead only. Every pattern begins with a slash
    and the pad has none, so a match starts at 12 or later and `start - 12` is never negative, which a match position would clamp.)"""
    padded = _PAD + haystack + _END
    before = _BEFORE.match
    for kind, pattern in _PATTERNS.items():
        shaped = other = 0
        for m in re.finditer(pattern, padded):
            if padded[m.end()] in _VALUE_START and before(padded, m.start() - 12):
                shaped += 1
            else:
                other += 1
        counts[kind] += shaped
        binary[0] += other


def _tally(counts, haystack):
    """Add to `counts` the matches of each pattern in one piece of text."""
    for kind, pattern in _PATTERNS.items():
        counts[kind] += sum(1 for _ in re.finditer(pattern, haystack))  # counted as they come: three million matches are not a list


def scan_pdf(data):
    caveats, incomplete, large_images = [], False, 0
    if b"%PDF-" not in data[:1024]:
        caveats.append(caveat("malformed"))
    counts = dict.fromkeys(_PATTERNS, 0)  # what each pattern matched, in every piece: a decoded piece is counted and dropped
    binary, spans = [0], []  # matches in binary places without the shape of a use; the raw data of the streams that are binary places
    total, decoded, covered, rows_left, bytes_left = 0, 0, [], [MAX_PREDICTED_ROWS], [MAX_PREDICTED_BYTES]
    reader = {"incomplete": False, "steps": MAX_READ_STEPS, "objects": 0, "unfinished": 0}  # what the forward reader keeps
    started = time.monotonic()
    for found in _streams(data, reader):
        if time.monotonic() - started > MAX_SECONDS:
            incomplete = True  # out of time: the rest of the streams are not read, and it says so
            break
        located, blob, start = found
        if located is None:
            incomplete = True  # a stream whose dictionary could not be read, so what filter it uses is unknown
            continue
        covered.append(located[:2])  # the filters named inside this dictionary are accounted for below
        dictionary = _unescape_regular(located[2])
        picture_shaped = _is_image(dictionary)  # its raw and decoded bytes are pixels, a binary place
        if len(_FILTER_KEY.findall(dictionary)) > 1:
            # the text is read without knowing strings or nested dictionaries, so which /Filter is the stream's own is not known: the
            # first one read could be a decoy that says an image codec, which the scan does not look into. Not guessed at, not skipped.
            incomplete = True
            continue
        value = _FILTER_VALUE.search(dictionary)
        if value and value.group(1).startswith(b"[") and not _FILTER_LIST.fullmatch(value.group(1)):
            # the list ends at the first bracket the text shows, and a comment, a string, an array or an escape can put one before
            # the real end: unless it holds nothing but names, the chain read here may be shorter than the viewer's
            incomplete = True
            continue
        names = _NAME.findall(value.group(1)) if value else []
        if len(names) > MAX_FILTERS:
            incomplete = True  # a chain this long is no honest file's, and each layer is a decode that is not charged
            continue
        if _FILTER_KEY.search(dictionary) and not names:
            incomplete = True  # a filter written in a way this scan does not read
        elif not names or all(n in _IMAGE_FILTERS for n in names):
            if names or picture_shaped:
                spans.append((start, start + len(blob)))  # an image codec's data, or the pixels of an unfiltered image
            continue  # not compressed, or an image: covered by the scan of the file as it is, below
        elif all(n in _DECODABLE for n in names):
            try:
                parms = _parms(dictionary, names)
            except _Unreadable:
                incomplete = True  # parameters given as a reference or in a way this scan does not read: not guessed at, not skipped
                continue
            decoded += 1
            if decoded > MAX_STREAMS or total >= MAX_TOTAL_OUT:
                incomplete = True
                break
            cap = min(MAX_STREAM_OUT, MAX_TOTAL_OUT - total)
            raws, layers = [], [0]
            out, state = _decode_chain(blob, names, cap, parms, rows_left, raws, bytes_left, layers)
            total += _work(out, picture_shaped) + sum(_work(raw, picture_shaped) for raw in raws) + layers[0]
            only_deflate_last = (names[-1] in _FLATE_NAMES and sum(n in _FLATE_NAMES for n in names) == 1
                                 and len(_FILTER_KEY.findall(dictionary)) == 1)  # one filter key: a second might be the real list
            picture = (only_deflate_last and not _deflate_header(out) and _is_image(dictionary)
                       and b"stream" not in blob)  # a stream marker in its bytes: structure was swallowed
            if picture and ((state == "limit" and cap == MAX_STREAM_OUT) or state == "spent"):
                # a picture too big to read to the end, or whose predictor the scan has no more work for: its first part was read, and
                # it is reported as that. Only when the deflate step that ran out is the last of the filters: the chain stops there,
                # and anything after it was not undone
                large_images += 1
            elif state != "ok" or out[:2] in _ZLIB_MAGIC:  # damaged, cut short, or compressed again inside
                incomplete = True
            if picture_shaped or state in ("ok", "limit", "spent"):
                spans.append((start, start + len(blob)))  # compressed bytes that were decoded, or a picture's: not text to a viewer
            # what the stream decoded to is read where it sits: pixels are a binary place, any other content (an object stream, a font, a
            # page) is a text place. A dictionary is read as text, so a decoy /DecodeParms in a string would make the scan undo a
            # predictor that the viewer never applies, and garble what it reads: the bytes from before the predictor are read as well
            for piece in ([out] if out else []) + [raw for raw in raws if raw]:
                if picture_shaped:
                    _tally_binary(counts, binary, _unescape_names(piece))
                else:
                    _tally(counts, _unescape_names(piece))
        else:
            incomplete = True  # a filter this scan does not decode (LZW, run-length, crypt, or one it has not heard of)
    text, pieces, last = data, [], 0
    for a, b in spans:  # the file as it is, which covers every stream that is not compressed: the places that are not binary...
        pieces.append(data[last:a])
        last = b
    if spans:
        text = b"\n".join(pieces + [data[last:]])  # (a newline between the pieces, so nothing is joined into a name)
    _tally(counts, _unescape_names(text))
    del text, pieces
    if spans:  # ...and the binary ones, where only a match with the shape of a use keeps its own name
        _tally_binary(counts, binary, _unescape_names((_END + _PAD).join(data[a:b] for a, b in spans)))
    incomplete = incomplete or reader["incomplete"]  # what the reader could not account for
    if not incomplete and _filter_outside(data, covered):
        incomplete = True  # a filter is declared somewhere that is not the dictionary of a stream the scan read
    for kind, count in counts.items():
        if count:
            caveats.append(caveat(kind, count))
    if binary[0]:
        caveats.append(caveat("pattern_in_binary_data", binary[0]))
    if large_images:
        caveats.append(caveat("large_image_streams", large_images))
    if incomplete:
        caveats.append(caveat("scan_incomplete"))
    return caveats


# --- HTML
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_HIDING = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?:px|pt|em|rem|%)?\s*(?:;|$|!)"
                     r"|opacity\s*:\s*0(?:\.0*)?\s*(?:;|$|!)|(?:^|;)\s*(?:width|height)\s*:\s*0(?:px)?\s*(?:;|$)"
                     r"|text-indent\s*:\s*-\d{3,}", re.I)
_MAX_DEPTH = 5000


def _strip_comments(value):
    """A style with its CSS comments removed (a comment can split a property name), in one pass: a pattern that looks for the
    end of each comment costs the square of the length when none ends. A comment that never ends runs to the end, as in CSS."""
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
        raw_style = a.get("style", "")
        style = _strip_comments(raw_style[:65_536])  # a comment can split the property name
        # a style no page needs (over 64 KB) is not read for hiding, it is counted as hiding; so padding cannot push the
        # rule that hides the text out of the part that is read
        if self.hidden_from is None and ("hidden" in a or len(raw_style) > 65_536 or _HIDING.search(style)):
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
