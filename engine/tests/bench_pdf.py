"""Deterministic PDFs for measuring the scan: the same arguments always give the same bytes. Used by the tests and by the
benchmarks of the plan 2026-11-06-scan-false-alarms, so that a timing can be repeated on the same file (and checked by its sha256).

    large_images(total, count, seed=1, zeros=3_000_000)
        A PDF of about `total` bytes (the size of the file) with `count` image objects. Each is
        `<< /Type /XObject /Subtype /Image /BitsPerComponent 8 /ColorSpace /DeviceRGB /Filter /FlateDecode /Height h /Length n
        /Width w >>` and holds the zlib compression, at level 6, of seeded noise (`random.Random`) followed by `zeros` zero bytes, so
        it decodes to more than the scan's per-stream limit. The noise is sized so that the streams fill `total`. Objects follow one
        another with nothing between them.

    expanding_streams(total, zeros=2_000_000)
        A PDF of about `total` bytes of plain `/Filter /FlateDecode` streams, each the zlib compression, at level 6, of `zeros` zero
        bytes (about a thousandfold expansion), as many as fill `total`.

    nested_empty_blocks(count, nbytes=1_900_000)
        A PDF of `count` streams, each `/Filter [/FlateDecode /FlateDecode]`: the outer layer is a few kilobytes that inflate to about
        `nbytes` of a valid zlib stream made of nothing but empty dynamic blocks (11 bytes each, the end-of-block symbol and nothing
        else), and the inner layer reads them and returns no bytes. Reading them costs about 60 ns a byte, so a stream costs about 0.1 s
        at the default size while its output is nothing: the shape of a filter chain whose middle layer is not charged. Found by the
        security review of increment B of 2026-11-06-scan-false-alarms.

    tiny_streams(total, seed=1, size=100)
        A PDF of about `total` bytes of plain `/Filter /FlateDecode` streams, each the zlib compression, at level 6, of `size` seeded
        bytes (one `random.Random(seed)` for the whole file), as many as fill `total`: the most streams that fit.

    escape_text(total, unit)
        A PDF of about `total` bytes of one unfiltered stream (no image, no filter) that holds `unit` over and over, for example
        `#41` or `#2FJS `: a file of name escapes, read by the scan as the text of the file. Plan 2026-11-07-scan-deferred-items.

    escape_image(repeats, unit)
        A PDF of one unfiltered image whose data is `unit` repeated `repeats` times: the escapes sit in a binary place.

    ascii85_escapes(repeats, unit)
        A PDF of one `/Filter /ASCII85Decode` stream that decodes to `unit` repeated `repeats` times (39 MB of `#41` is 13 million).
"""
import base64
import random
import zlib

HEADER = b"%PDF-1.4\n"
TRAILER = b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"
LEVEL = 6
MIN_TOTAL = 10_000


def _object(number, dictionary, data):
    return b"%d 0 obj\n%s\nstream\n%s\nendstream\nendobj\n" % (number, dictionary, data)


def _image(number, noise, zeros):
    raw = noise + bytes(zeros)
    data = zlib.compress(raw, LEVEL)
    width = 1000
    height = -(-len(raw) // (3 * width))
    dictionary = (b"<< /Type /XObject /Subtype /Image /BitsPerComponent 8 /ColorSpace /DeviceRGB /Filter /FlateDecode "
                  b"/Height %d /Length %d /Width %d >>" % (height, len(data), width))
    return _object(number, dictionary, data)


def large_images(total, count, seed=1, zeros=3_000_000):
    if not (isinstance(total, int) and isinstance(count, int) and isinstance(seed, int) and isinstance(zeros, int)):
        raise ValueError("the arguments must be whole numbers")
    if count < 1 or zeros < 1 or total < MIN_TOTAL or total < count * 200:
        raise ValueError("the size must be at least 10,000 bytes and 200 bytes for each image, and there must be one image or more")
    fixed = len(HEADER) + len(TRAILER)
    per_image = (total - fixed) // count
    overhead = len(_image(1, b"", zeros))  # what an image takes besides its noise: the compressed zeros and the dictionary
    if per_image < overhead:
        raise ValueError(f"{count} images need at least {fixed + count * overhead} bytes")
    parts = [HEADER]
    for i in range(1, count + 1):
        noise = random.Random(seed * 1_000_003 + i).randbytes(per_image - overhead)
        obj = _image(i, noise, zeros)
        obj = _image(i, noise[:max(0, len(noise) - (len(obj) - per_image))], zeros)  # noise grows a little under zlib: cut the excess once
        parts.append(obj)
    parts.append(TRAILER)
    return b"".join(parts)


def expanding_streams(total, zeros=2_000_000):
    if not (isinstance(total, int) and isinstance(zeros, int)) or total < MIN_TOTAL or zeros < 1:
        raise ValueError("the size must be at least 10,000 bytes")
    data = zlib.compress(bytes(zeros), LEVEL)
    parts = [HEADER]
    used = len(HEADER) + len(TRAILER)
    number = 1
    while True:
        obj = _object(number, b"<< /Filter /FlateDecode /Length %d >>" % len(data), data)
        if used + len(obj) > total:
            break
        parts.append(obj)
        used += len(obj)
        number += 1
    parts.append(TRAILER)
    return b"".join(parts)


def tiny_streams(total, seed=1, size=100):
    if not (isinstance(total, int) and isinstance(seed, int) and isinstance(size, int)) or total < MIN_TOTAL or size < 1:
        raise ValueError("the size must be at least 10,000 bytes and each stream at least one byte")
    rnd = random.Random(seed)
    parts = [HEADER]
    used = len(HEADER) + len(TRAILER)
    number = 1
    while True:
        data = zlib.compress(rnd.randbytes(size), LEVEL)
        obj = _object(number, b"<< /Filter /FlateDecode /Length %d >>" % len(data), data)
        if used + len(obj) > total:
            break
        parts.append(obj)
        used += len(obj)
        number += 1
    parts.append(TRAILER)
    return b"".join(parts)


def _check_unit(unit):
    if not isinstance(unit, bytes) or not unit:
        raise ValueError("the unit must be some bytes")


def escape_text(total, unit):
    _check_unit(unit)
    if not isinstance(total, int) or total < MIN_TOTAL:
        raise ValueError("the size must be at least 10,000 bytes")
    room = total - len(HEADER) - len(TRAILER) - len(_object(1, b"<< /Length 00000000 >>", b""))
    data = unit * (room // len(unit))
    return HEADER + _object(1, b"<< /Length %08d >>" % len(data), data) + TRAILER


def escape_image(repeats, unit):
    _check_unit(unit)
    if not isinstance(repeats, int) or repeats < 1:
        raise ValueError("at least one repeat")
    data = unit * repeats
    dictionary = b"<< /Type /XObject /Subtype /Image /BitsPerComponent 8 /ColorSpace /DeviceGray /Height 1 /Length %d /Width %d >>" % (
        len(data), len(data))
    return HEADER + _object(1, dictionary, data) + TRAILER


def ascii85_escapes(repeats, unit):
    _check_unit(unit)
    if not isinstance(repeats, int) or repeats < 1:
        raise ValueError("at least one repeat")
    data = base64.a85encode(unit * repeats) + b"~>"
    return HEADER + _object(1, b"<< /Filter /ASCII85Decode /Length %d >>" % len(data), data) + TRAILER


class _Bits:
    """Bits written least significant first, as deflate wants them."""

    def __init__(self):
        self.value = 0
        self.length = 0

    def put(self, value, nbits):
        self.value |= value << self.length
        self.length += nbits

    def huffman(self, code, nbits):  # a Huffman code is written most significant bit first
        for i in range(nbits - 1, -1, -1):
            self.put((code >> i) & 1, 1)

    def to_bytes(self):
        return self.value.to_bytes((self.length + 7) // 8, "little")


def _empty_dynamic_block(bits, final):
    """A dynamic Huffman block with no data: its tables, then the end-of-block symbol."""
    bits.put(1 if final else 0, 1)
    bits.put(2, 2)  # a dynamic block
    bits.put(0, 5)  # 257 literal/length codes
    bits.put(0, 5)  # 1 distance code
    bits.put(14, 4)  # 18 code length codes
    for symbol in (16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1):
        bits.put(1 if symbol in (18, 1) else 0, 3)
    bits.huffman(1, 1)
    bits.put(127, 7)  # 138 zero lengths
    bits.huffman(1, 1)
    bits.put(107, 7)  # 118 zero lengths
    bits.huffman(0, 1)  # the end-of-block symbol has length 1
    bits.huffman(0, 1)  # the one distance code has length 1
    bits.huffman(0, 1)  # the end-of-block symbol itself


def nested_empty_blocks(count, nbytes=1_900_000):
    if not (isinstance(count, int) and isinstance(nbytes, int)) or count < 1 or nbytes < 1000:
        raise ValueError("at least one stream, and at least 1,000 bytes in the middle layer")
    four = _Bits()
    for _ in range(4):
        _empty_dynamic_block(four, False)
    last = _Bits()
    _empty_dynamic_block(last, True)
    # a zlib header, the blocks, a final empty block, and the Adler-32 of nothing (1)
    middle = b"\x78\x9c" + four.to_bytes() * (nbytes // 45) + last.to_bytes() + b"\x00\x00\x00\x01"
    outer = zlib.compress(middle, LEVEL)
    parts = [HEADER]
    for number in range(1, count + 1):
        parts.append(_object(number, b"<< /Filter [/FlateDecode /FlateDecode] /Length %d >>" % len(outer), outer))
    parts.append(TRAILER)
    return b"".join(parts)
