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

    tiny_streams(total, seed=1, size=100)
        A PDF of about `total` bytes of plain `/Filter /FlateDecode` streams, each the zlib compression, at level 6, of `size` seeded
        bytes (one `random.Random(seed)` for the whole file), as many as fill `total`: the most streams that fit.
"""
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
