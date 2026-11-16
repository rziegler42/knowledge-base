"""The owner's topics for the unattended crawl: the file is read strictly, and each topic gets its share of the day's queries
(`docs/specs/population.md`, "The crawl plan"). The topics are the owner's interests: a topic is a line of text, never a command.

The file, `key = value` having no part in it:

    # a comment: a line whose first character, after white space, is a hash
    [core weight=10]        a section: a name and a whole-number weight, one or more of them
    Control theory          a topic: one to a line, under the section above it

A hash inside a topic line stays in the topic (`C#`, `F#`)."""

import bisect
import os
import re
import stat
from contextlib import closing

from . import KbError, textutil

MAX_BYTES = 256 * 1024
MAX_TOPICS = 5000
MAX_TOPIC = 300
_SECTION = re.compile(r"\[([A-Za-z][A-Za-z0-9_-]{0,39}) weight=([1-9][0-9]{0,6})\]")
_GOLDEN = 0x9E3779B97F4A7C15  # 2**64 over the golden ratio: a step that spreads points evenly however many are taken
_WORD = (1 << 64) - 1


def _refuse(message):
    return KbError(f"the topics file: {message}")


def read_topics(path):
    """`[(topic, weight, section), ...]` in the order of the file. It is read without following a link or waiting on a pipe, as a
    plain file of at most 256 KB of UTF-8, and anything that does not fit the form above is a refusal that names the line and does
    not repeat its text. A topic has control, invisible and direction characters removed and its white space made single; one that
    is empty then, over 300 characters, or the same as an earlier one (in any case) is refused; so is a topic before any section, a
    file with no topic, and one with over 5,000."""
    if not isinstance(path, (str, os.PathLike)) or not os.fspath(path):
        raise _refuse("the path is not a path")
    shown = textutil.literal(os.fspath(path))
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError as e:
        raise _refuse(f"it cannot be opened ({e.strerror}); a link is not followed: {shown}") from None
    except ValueError:  # a NUL character in the path
        raise _refuse(f"the path cannot be opened: {shown}") from None
    try:
        info = os.fstat(fd)  # of the file that was opened, before anything is read from it
        if not stat.S_ISREG(info.st_mode):
            raise _refuse(f"it is not a plain file: {shown}")
        if info.st_size > MAX_BYTES:
            raise _refuse(f"it is over {MAX_BYTES // 1024} KB: {shown}")
        f = os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise
    with closing(f):
        data = f.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise _refuse(f"it is over {MAX_BYTES // 1024} KB: {shown}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise _refuse(f"it is not UTF-8 text: {shown}") from None
    if "\x00" in text:
        raise _refuse(f"it holds a NUL character: {shown}")
    topics, seen, section, weight = [], set(), None, None
    for number, raw in enumerate(text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n").split("\n"), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            found = _SECTION.fullmatch(line)
            if not found:
                raise _refuse(f"line {number}: a section line is [name weight=N], a name of up to 40 letters, digits, - or _, "
                              "and a whole number from 1 to 9999999")
            section, weight = found.group(1), int(found.group(2))
            continue
        if section is None:
            raise _refuse(f"line {number}: a topic comes before any section")
        topic = textutil.clean(line, len(line))
        if not topic:
            raise _refuse(f"line {number}: the topic has nothing left once hidden characters are removed")
        if len(topic) > MAX_TOPIC:
            raise _refuse(f"line {number}: a topic is at most {MAX_TOPIC} characters")
        if topic.casefold() in seen:
            raise _refuse(f"line {number}: the topic is a repeat of an earlier one")
        if len(topics) >= MAX_TOPICS:
            raise _refuse(f"line {number}: there are over {MAX_TOPICS} topics")
        seen.add(topic.casefold())
        topics.append((topic, weight, section))
    if not topics:
        raise _refuse(f"it holds no topic: {shown}")
    return topics


def _checked(topics):
    if not isinstance(topics, (list, tuple)):
        raise _refuse("the topics are a list of (topic, weight, section)")
    for item in topics:
        if (not isinstance(item, (tuple, list)) or len(item) != 3 or not isinstance(item[0], str) or type(item[1]) is not int
                or item[1] < 1):
            raise _refuse("a topic is (topic, weight, section) with a whole-number weight of at least 1")
    return topics


def shares(topics):
    """`[(topic, share), ...]`: each topic's weight over the sum of the weights, in the order given (the shares add up to 1)."""
    topics = _checked(topics)
    total = sum(item[1] for item in topics)
    return [(item[0], item[1] / total) for item in topics]


def quota(topics, n, day_index):
    """How many of `n` queries each topic gets on day `day_index`, in the order of `topics`, adding up to `n`. The days read one
    endless sequence of picks in proportion to the weights, `n` of them to a day, so that the same day always gives the same answer,
    the days differ, and every topic is reached over the days: a topic with a small weight is reached on a few days of many and not on
    none. The sequence is a step of the golden ratio round the line of cumulative weights (integers only, so it is the same on every
    machine). Pick number `day_index * n + k + 1` is the same pick whatever `n` is, so the days are slices of one sequence: if `n`
    changes from one day to the next the slices still follow each other and no pick is taken twice. A topic of share `s` is picked
    about `s * n` times a day, so a small one is reached after many days and not on a fixed one (the weight-1 topic of a list like
    the owner's, a share of 1 in 956, about once in 48 days at 20 a day); the order of the topics in the list is part of the sequence, and a changed list
    changes it."""
    topics = _checked(topics)
    for name, value in (("n", n), ("day_index", day_index)):
        if type(value) is not int or not 0 <= value <= 10**9:
            raise _refuse(f"{name} must be a whole number from 0 to 10^9")
    ends, total = [], 0
    for item in topics:
        total += item[1]
        ends.append(total)
    made = [0] * len(topics)
    if not topics:
        return made
    for k in range(n):
        point = (((day_index * n + k + 1) * _GOLDEN) & _WORD) * total >> 64
        made[bisect.bisect_right(ends, point)] += 1
    return made
