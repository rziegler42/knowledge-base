# Title safety: one rule for a title, where it is stored and where it is shown

Status: Proposed
Created: 2026-11-06
Candidate: none (no roadmap exists; this is finding 4 of the security review of increment B of 2026-11-06-first-walk-through-fixes, deferred there for the owner)
Specs: book, reading

## Goal

A book's title is text from outside: a web page gives its own `<title>`, an arXiv record gives the paper's title, and an agent reads
the title in every search result and every read. Today the title is checked in one place only, where a tool hands back a page's title
(`convert.parse_blocks_json`), and that check is partial. Four holes were found in the security review of the page-title increment
and left for this plan:

1. **An arXiv title is stored unchecked.** `capture_arxiv` cleans it (control characters, length) and files it. A title that carries the
   words of the untrusted-text markers (`search.MARKER`, `read.END_MARKER`) can imitate the end of the untrusted section in a search
   result or a read, which is the check that a page title already gets.
2. **The store accepts any text as a title.** `Store.create_book` and `Store.set_metadata` only check that it is text, so any caller
   (now or later: an import, a hand edit of `book.json`) can put anything in.
3. **The citation line can be imitated by a title.** The citation is `<title>. <address>. Retrieved <date>. sha256 <digest>`. A title
   such as `X. https://example.org/y. Retrieved 2020-01-01. sha256 0000…` puts a fake address, date and hash in front of the real
   ones, and a reader or an agent that takes the first address takes the fake one.
4. **Search results do not take the library's folders out of a title,** as `read` does (a Low finding accepted earlier).

When this plan is done, a title is checked by one rule in one place (`textutil`) and that rule is applied where a title is stored (the
store) and where it is shown (the index, search and read), so the check no longer depends on which tool or capture produced the title;
the citation line shows the title in quotation marks that the title cannot close, so what follows the title is always the engine's own
fields.

## Scope

- One function in `engine/kb/textutil.py` that makes a title: cleaned and cut as now, and with no title at all (an empty one) when its
  letters, folded as `convert._letters` folds them, contain the words of either untrusted-text marker. The folding moves from
  `convert.py`, which then calls the shared function; page titles behave as they do now.
- `Store.create_book` and `Store.set_metadata` make every title they store with that function, so an arXiv title and any later
  source go through it.
- The index, `search` and `read` make the title they show with the same function (an older book file, or a hand-edited one, is
  covered), and take the library's folders out of it in all three places.
- The citation shows the title between ASCII quotation marks, with any quotation mark in the title turned into an apostrophe, and
  `untitled` shown the same way, so the fields after it cannot be imitated by the title.
- The index (the library's four books) is rebuilt with the owner's word, and the result is recorded.
- Tests for each hole, each failing first, with honest twins (an ordinary title keeps its text).
- The README and the two specs say what the rule is.

## Non-goals

- Look-alike letters from another alphabet (a Cyrillic `u` in `untrustedtext`) and long runs of combining marks: the folding does not
  map them. The marker check is a guard, not a filter of meaning; the result stays flagged `untrusted` as a whole and the README says
  to treat the title as data. Mapping confusables is a larger design and is not part of this plan.
- Plain instructions in a title (words with no marker in them). A title is data to the reader, as the excerpt is.
- Authors, abstracts, categories and other fields that arXiv gives: they are cleaned where captured and are not shown in a search
  result or a citation. If a later feature shows them, the same question arises there.
- A change of the index schema, the conversion or the scan.
- Fetching anything, and pushing.

## Assumptions and constraints

- `textutil` is the standard library only and has no knowledge of the store; the store and `read` import it, not the other way round.
- A title made empty by the rule is stored as an empty title, which the book already allows (a web page starts with none), and which a
  later page title can still fill, since a title the book already has is never replaced and an empty one is not a title.
- The folder scrub needs the library's roots, which `read` has through the store; the index has the store while it indexes. A
  helper that both use is moved to a place both can import, with the same behaviour as now.
- The index holds the title that was current when it was built. A rule that changes what is stored takes effect in search after
  `python3 -m kb index`; this plan runs it for the four books (increment D) and says so in the README.
- Each increment is one verified, reviewed local commit. After the tests pass in increments A and C the work stops and the owner is
  asked whether to run a security review of the surface, once for each, and the answer is recorded.
- Nothing is pushed, and nothing is run on the owner's library before increment D and the owner's word.

## Completion criteria

1. One function makes a title; `convert`, `Store.create_book`, `Store.set_metadata`, the index, `search` and `read` use it and no other
   title cleaning is left in them.
2. An arXiv paper whose title carries the marker words is filed with an empty title; a title with plain words is filed as before.
3. A search result and a read never show the library's folders in a title.
4. The citation line for a title built to imitate the fields after it reads, from its first `"` to its last `". `, as the title, and
   the text after that is the engine's address, date and hash.
5. `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_textutil engine.tests.test_store engine.tests.test_capture_arxiv
   engine.tests.test_read engine.tests.test_search` and, under the engine's own Python, `engine.tests.test_convert` pass.
6. The index is rebuilt (the library holds four books) and the titles, as search and read show them, are recorded.

## Increments

### Increment A — One rule for a title, applied where titles are stored

**Outcome:** `textutil.title(text, limit)` returns the cleaned title, or an empty string when its letters, folded, contain the words
of an untrusted-text marker; `convert` uses it for a page title; `Store.create_book` and `Store.set_metadata` store every title through
it; an arXiv title with the marker words is filed with an empty title.
**Dependencies:** none.
**Affected areas:** `engine/kb/textutil.py`, `engine/kb/convert.py` (the folding and the check move out; behaviour unchanged),
`engine/kb/store.py`, `engine/kb/capture_arxiv.py` (the title is made by the rule where the record is parsed, so the version's
`source` record and the book's root file hold the same title), `engine/tests/test_textutil.py`, `engine/tests/test_store.py`,
`engine/tests/test_capture_arxiv.py`, `engine/tests/test_convert.py` (existing title tests unchanged), `engine/README.md` and `docs/specs/book.md` (the stored title is
made by one rule: cleaned, cut, and empty when it carries the words of an untrusted-text marker).
**Steps:**
1. Write the tests first and see them fail: the function on the spellings the page-title tests already use (the markers themselves,
   fullwidth, bold, circled, hyphenated, underscored and accented spellings) and on honest titles that keep their text (a title that
   contains the word `untrusted` or `text` alone, other languages, a long title cut at the limit); `create_book` and `set_metadata` with
   a marker title store an empty one, with an ordinary title store it cleaned, and still refuse a title that is not text; an arXiv
   record whose title carries the markers is filed with an empty title in the book's root file and in the version's `source` record,
   and its authors and year intact.
2. Move `_letters` and the marker words into `textutil`, write `title`, and make `convert.parse_blocks_json` call it (its existing
   tests must pass unchanged).
3. Make `capture_arxiv` build the title with it where it parses the record, and make the store apply it in `create_book` and `set_metadata` (500 characters, the limit arXiv titles are cut to now), and state the
   rule in the README and in `docs/specs/book.md` where it describes the root file and the title.
4. Run the break-it check: the check removed, each folding step removed, the store not applying it in either method.
5. Stop and ask the owner whether to run a security review of this surface (what a title can carry into a search result or a read);
   record the answer.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_textutil engine.tests.test_store
engine.tests.test_capture_arxiv` and `engine/.venv/bin/python -B -W error::ResourceWarning -m unittest engine.tests.test_convert`
pass, with the break-it check. The wider risk is the move out of `convert.py`, whose page-title tests are the ones that would show a
change of behaviour.
**Evidence:** one local commit with the trailer `Plan: 2026-11-06-title-safety#A`.

### Increment B — The same rule where a title is shown

**Outcome:** the index, `search` and `read` make the title they show with the same function; a title already in the index with a
marker in it is empty in a search result without a rebuild (search makes the title when it builds a result), and the library's
folders are taken out of a title when it is indexed and when it is read (a folder in an indexed title leaves a search result after
the index is rebuilt, which increment D does); a book file with a marker title, or one with a folder path in its title, shows neither
in a read.
**Dependencies:** A.
**Affected areas:** `engine/kb/index.py`, `engine/kb/search.py`, `engine/kb/read.py`, the helper that takes the folders out (moved
from `read.py` to a place `index.py` can import without a cycle), `engine/tests/test_search.py`, `engine/tests/test_read.py`,
`engine/README.md` and `docs/specs/reading.md` (a title in a result is made by the same rule and has no library folder in it).
**Steps:**
1. Write the tests first and see them fail: (a) a row of the index whose title carries a marker, written into the index without
   rebuilding it, is empty in a search result; (b) a book file edited by hand to hold a marker title, and one that holds the bulk root
   in its title, indexed (rebuilt) and searched, and read: the result shows an empty title (`untitled` in a citation) and `<library>`
   for the folder; (c) an ordinary title is unchanged; (d) a title that cleaning would join into a folder name is still scrubbed after
   cleaning.
2. Move the folder helper, make `index.py` build the title through `textutil.title` and the helper, make `search._results` pass
   the indexed title through `textutil.title`, and make `read.py` use
   `textutil.title` for the title in a result and in the citation (the folder scrub is kept before and after, as now); state it in
   the README and in `docs/specs/reading.md` where the result's title is described.
3. Run the break-it check: each of the three uses removed (index, search, read).
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_search engine.tests.test_read` pass, with the
break-it check. The module `engine.tests.test_textutil` is rerun only if the helper moved into `textutil`.
**Evidence:** one local commit with the trailer `Plan: 2026-11-06-title-safety#B`.

### Increment C — The citation line cannot be imitated by a title

**Outcome:** the citation reads `"<title>". <address>. Retrieved <date>. sha256 <digest>`; a quotation mark in the title becomes an
apostrophe, so the title cannot close its own quotation; a title built to look like the fields after it stays inside the quotes.
**Dependencies:** B.
**Affected areas:** `engine/kb/read.py` (`_citation`), `engine/tests/test_read.py`, `engine/README.md` (the `citation` description),
`docs/specs/reading.md` (the citation line).
**Steps:**
1. Write the tests first and see them fail: a title that imitates an address, a date and a hash, with and without a quotation mark
   in it; split on the first `"` and the last `". `, the first part is the title and the rest equals the engine's own fields exactly;
   a book with no title shows `"untitled"`; the fields that are missing still say so; an ordinary title is shown in quotes with its
   text.
2. Change `_citation` and the README and spec lines that describe the format.
3. Run the break-it check: the quote replacement removed; the quotes removed.
4. Stop and ask the owner whether to run a security review of the citation (the line an agent copies into a reference); record the
   answer.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_read` passes, with the break-it check.
`engine.tests.test_search` is not run: search does not build a citation.
**Evidence:** one local commit with the trailer `Plan: 2026-11-06-title-safety#C`.

### Increment D — Index the four books again and record what the titles show

**Outcome:** the search index is rebuilt (`python3 -m kb index` takes no book: it rebuilds the whole index from the books, which is
derived data and replaces nothing in the library) and the titles of the four books of the walk-through, as search and read show them,
are recorded; the README says that a change of the rule is seen in search after `index`.
**Dependencies:** A to C, and the owner's word to run it.
**Affected areas:** the Result section of this plan; `engine/README.md` (one sentence); the owner's index (the four books).
**Steps:**
1. Count the books in the library. The plan assumes exactly the four of the walk-through; if there are more, stop and tell the owner,
   who then says whether the whole index is rebuilt and whether the added books' titles are recorded too.
2. Record the title of each book as search and read show them now (title and citation line).
3. With the owner's word, run `python3 -m kb index` (the whole index, which is the four books) and record them again.
4. Compare: the titles are the same text as before (none carries a marker word or a folder), and the citation lines are in the new
   form. Anything that changed other than the form is recorded with its reason.
**Verification:** the recorded comparison; `python3 -m kb tools` shows every tool `ok`.
**Evidence:** one local commit with the trailer `Plan: 2026-11-06-title-safety#D`, adding the record to the Result section.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later increment changed its inputs. Increment C changes the citation that
increment B's read tests touch, so after C `engine.tests.test_read` and `engine.tests.test_search` are rerun once together;
`engine.tests.test_textutil`, `engine.tests.test_store`, `engine.tests.test_capture_arxiv` and `engine.tests.test_convert` are rerun
only if B or C changed `textutil`, the store, the capture or the conversion (B may move the folder helper into `textutil`). `python3
-m kb tools` is run in increment D. A wider run is named only with a specific risk: the whole engine suite is not planned.

## Risks and sensitive actions

- A title is untrusted text that an agent reads. The change makes the check cover every path a title takes; it does not make a title
  safe to follow as an instruction, and the marker check can be walked around with look-alike letters (non-goal, stated in the
  README).
- Applying the rule in the store changes what is written to `book.json`: a title with the marker words is dropped instead of kept.
  That is the intended effect; no existing title in the owner's library has them (checked in increment D).
- The citation format changes. Anything that parses the old format is affected; the repository has none (the tests and the README
  are the only readers), and the format is checked again in increment C.
- Increment D rebuilds the owner's whole search index (the command has no way to name a book); today that is four books. It changes
  nothing in the library itself, and it runs only with the owner's word and only after the count in its first step.
- Touching untrusted input and the text an agent reads is a place to look for a security surface: the owner is asked at increments A
  and C.

## Review record

Reviewed with the project's review engine (a second model, `gpt-5.6-terra` for rounds 1 and 2, `gpt-6.1-sol` for round 3): 3 rounds of
a bound of 3; every finding was checked against the code before it was applied. All four were applied.

1. *Major, applied (round 1):* the scope promised the README and both specs but no increment updated the Book spec. Increments A and
   B now name the README and `book.md` / `reading.md`, with a step for each.
2. *Major, applied (round 1):* `python3 -m kb index` takes no book and rebuilds the whole index. Increment D says so, counts the books
   first and stops if there are more than the four, and the risks and criteria name the whole index.
3. *Major, applied (round 2):* the arXiv title was copied into the version's `source` record before the store saw it. Increment A now
   makes the title with the rule where `capture_arxiv` parses the record, and its test checks the root file and the source record.
4. *Major, applied (round 3):* search returned the indexed title as it was. Increment B now has `search` make the title when it builds a
   result, with a test on a marker title written into the index without a rebuild, and says that folder removal at indexing needs the
   rebuild of increment D.

The fix to finding 4 was not reviewed again: the rounds are used up. The plan check (`wb run code-work check`) finds no problems. What
is left for the owner: read the plan, and say whether to approve it or to ask for another round (which needs the owner).

## Deferred work

- Look-alike letters (other alphabets) in the marker check, and long runs of combining marks.
- The same question for authors, abstracts and categories if a later feature shows them.
- The rest of the live walk-through (six more pages and two papers; the owner's list of addresses and go-ahead are needed) and the
  workbench package increment.

## Result

### Increment A — One rule for a title, applied where titles are stored (implemented, reviewed and security-reviewed; not committed)

- **Done:** `textutil.title(text, limit)` (clean, cut, and empty when the folded ASCII letters hold `untrustedtext`) with `_letters` and
  `MARKER_WORDS` moved out of `convert.py`; `Store.create_book` and `Store.set_metadata` file every title through it (500 characters,
  `store.TITLE_CHARS`; a title that is not text is still refused; `title=None` is stored as an empty title, as the web-page path already
  did); `capture_arxiv` makes the parsed title with it, so the book's title and the version's `source` record agree; `parse_blocks_json`
  calls it. The README and `docs/specs/book.md` state the rule and the cost of it (below).
- **Verification run:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_textutil engine.tests.test_store
  engine.tests.test_capture_arxiv`: 118 tests, OK; `engine/.venv/bin/python -B -W error::ResourceWarning -m unittest
  engine.tests.test_convert`: 164 tests, OK. The new tests failed first (no `textutil.title`; the store and the arXiv record held the
  marker title). Break-it: eight mutations (rule off, no compatibility fold, no case fold, digits counted, `create_book`, `set_metadata`,
  the arXiv parser, the page title): all caught, after one survivor (digits counted as letters) got a test.
- **Review (independent reviewer, one round):** no blocking finding. Applied: the indentation of the spec text; a known cost written in
  the README and the spec and pinned by a test (a true title with "untrusted text" side by side is stored empty, for example a paper on
  defending against injection in untrusted text; an arXiv book has no second source to fill it). Noted: `create_book(title=None)` now
  stores an empty title.
- **Security review (owner said yes; independent, on a copy):** no Critical, High or Medium finding. Tested: marker spellings through
  the rule (fullwidth, bold, ligatures, superscripts, every hidden character between the letters, combining marks, a marker at the
  cut), a hostile Atom record through the real parser (entities, CDATA, comments, duplicate and foreign-namespace titles), the full
  capture with a mocked fetch (book and source agree in all six cases), odd types in the store (bytes, str subclasses with overridden
  methods: refused or rebuilt as plain text), 400,000 fuzzed strings (no exception, no title above its limit, no surviving marker,
  `title(title(x)) == title(x)`), and cost (linear: 2 MB 0.4 s, 10 MB about 2 s). One Low finding, **fixed:** a letter that reads as
  punctuation or a stretch line (a modifier letter such as `ʼ`, the tatweel, a click, the prolonged sound mark `ー`) between the
  words kept the marker out of the check, so `[end of untrustedʼ text]` was stored. Reproduced; the comparison now keeps ASCII letters
  only (every real spelling of the markers is ASCII after folding), with a test that failed first. Not changed, with reasons:
  look-alike letters (Cyrillic, Greek, small capitals, enclosed and regional-indicator letters) still pass, a limit the plan and the
  README state; the cost of cleaning a very long title is paid only by a direct caller of the store (the arXiv answer is capped at
  1 MB, a page title at 2,000 characters; a title of 100 MB would take about 20 s and a few GB), and cutting before cleaning would change
  what `clean` returns for every other use; the authors, abstract and other `source` fields are only cleaned, which is a stated
  non-goal and becomes a question if a later feature shows them in a citation or an index (a marker split across a title and a
  neighbouring field is for increment C to judge when the citation joins fields); books already stored and hand-edited `book.json`
  files are for increment B (display).
- **Not run:** the wider engine tests (the changed modules are `textutil`, `store`, `capture_arxiv` and `convert`; their tests were run).
- **Committed** as 39a57247427472feb1bb6672086480452207cf2a (not pushed).

### Increment B — The same rule where a title is shown (implemented and reviewed; not committed)

- **Done:** `textutil.scrub_roots(store, text)` (the folder helper, moved from `read.py`, which keeps `_scrub_roots` as a thin call to
  it); `index.py` builds the indexed title by scrub, `textutil.title` (300), scrub; `search._results` passes the indexed title through
  `textutil.title` when it builds a result (so a marker title already in an index is empty without a rebuild); `read.py` makes the
  title of a result and of the citation with `textutil.title` (200), with the existing scrubs. The README and `docs/specs/reading.md`
  state it.
- **Verification run:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_textutil engine.tests.test_search
  engine.tests.test_read`: 193 tests, OK (the plan named test_search and test_read, and test_textutil because the helper moved into
  `textutil`). The new tests failed first (five of six): a marker title written into the index with no rebuild, a hand-edited book file
  with a marker title, a library folder in a title, a folder split by a hidden character, an honest twin (passed before and after).
  Break-it on six uses of the rule (search, the index's marker check, the index's scrub before and after cleaning, the citation title,
  the result title): all caught, after two survivors got tests (the stored row holds no marker title; the index scrubs before
  cleaning, by a spy on `scrub_roots`).
- **Review (independent reviewer, one round):** no blocking finding. Applied: the Reading spec says a search result has no folder in
  its title once the index is rebuilt. Noted, not changed: search has no store, so a folder in a title indexed before the rule stays in
  a search result until `python3 -m kb index` (increment D); the reviewer agrees a store should not be added to search, since the
  folder is the library's own path that a page or an arXiv record cannot know. No path found where a title reaches a result, a
  citation or a message without the rule; a changed title is re-indexed because the title is part of the version's signature. One
  existing read test expects the citation to start with `untitled.`, which increment C changes.
- **Not run:** the other test modules (the changed modules are `textutil`, `index`, `search` and `read`; their tests were run); a
  security review (the plan asks at A and C only).
- **Committed** as 2c373219c44f1411434095736060647c63cbc403 (not pushed).

### Increment C — The citation line cannot be imitated by a title (implemented, reviewed and security-reviewed; not committed)

- **Done:** `read._citation` shows `"<title>". <address>. Retrieved <date>. sha256 <digest>`: the title between ASCII quotation marks, each
  quotation mark in it turned into an apostrophe (one character for one, after the cut to 200), and `"untitled"` for a book with no title.
  The address also has a quotation mark written `%22` and a space `%20` (see the review below). The README and `docs/specs/reading.md`
  describe the format.
- **Statement of the criterion:** completion criterion 4 says the title runs "from its first `"` to its last `". `". The code guarantees
  the stronger and simpler form, which the tests and the README use: the title ends at the **next** quotation mark, whatever it says.
  The two forms agree unless an address holds `". `, which the address encoding now prevents. The plan text is unchanged (it is approved).
- **Verification run:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_read engine.tests.test_search`: 167 tests, OK
  (the plan named `test_read`; `test_search` was run as well). The new tests failed first: titles built to look like the fields after
  them (plain, with a closing quotation mark, with several, with typographic marks, ending in a full stop, a backslash or a quotation
  mark) must end at the next quotation mark and leave exactly the engine's fields; a missing title is `"untitled"`; an address with a
  quotation mark, a space or both cannot plant a second `Retrieved` and `sha256`. Break-it: eight mutations (the quote replacement
  removed, only the first changed, a space instead of an apostrophe, no quotation marks, no full stop after the closing mark, the address
  encoding removed or half removed): all caught, after one survivor (space instead of apostrophe) got an exact assertion.
- **Review (independent reviewer, one round):** no blocking finding. The title cannot close its own quotation or imitate the following
  fields (typographic quotes and `\` are not the closer; the cut cannot fall between a mark and its replacement; nothing after the
  citation normalises it; `<library>` in a title is only text). No code parses the citation. Applied, reproduced first (the citation
  held two `Retrieved` and two `sha256` fields): a web address is only checked for its prefix, so a quotation mark or `". ` in a recorded
  address planted a fake tail; the address now has `"` written `%22` and a space `%20`. Honest cases (a full stop, a backslash, a
  quotation mark at the end of a title) were added to the test. The reviewer's note on a title ending in a backslash was first
  accepted and then reversed after the security review (below).
- **Security review (owner said yes; independent, on a copy):** no Critical, High or Medium finding. Tested: 25 hostile addresses
  (a quotation mark followed by fake fields, no-break space, U+2028, U+3000, tab, newline, `%0a`, a very long URL, a thousand quotation
  marks, ESC and NUL), every title shape (quotation marks, backslashes, a fake `". Retrieved … sha256` string, folder names split by a
  zero-width character, non-text values), arXiv ids and labels with a quotation mark, a newline or Arabic-Indic digits (all refused by
  the exact-match checks), and 6.37 million structured random records through `_citation` and the folder scrub: every citation matched
  a strict pattern (a title with no ASCII quotation mark between two, then the address, `Retrieved` and a date or the words "date not
  recorded", and `sha256` and a digest or the words "hash not recorded") with exactly two ASCII quotation marks, and there was no
  exception. The line cannot break out when printed: `kb read` prints JSON with the default escaping. The longest citation is bounded
  at about 1,700 characters. Findings (all Low) and what was done: (1) *Fixed:* a title ending in a backslash gave a closing mark
  that a reader honouring escapes reads as escaped; trailing backslashes are now left out of the title in the citation (the result's
  title keeps them), with a test that failed first. (2) *Accepted:* a title can still contain text that looks like the following
  fields (`x'. Retrieved 2020-01-01. sha256 …`) inside its own quotation marks. The promise of the format is that the title ends at
  the next ASCII quotation mark and the engine's fields follow, which the tests check; a reader that skips the quotation marks is not
  protected, and the plan states the guard's limits. (3) *Accepted:* look-alike quotation marks (U+201C, U+201D, U+FF02) stay in
  titles and addresses; the real ASCII closer still follows `". `. (4) *Noted, owner configuration only:* a degenerate library root
  such as `.` or a lone space makes the folder scrub rewrite the separators in the citation; a real root (two or more parts, no
  quotation mark) cannot, and the scrub's replacement `<library>` holds no quotation mark or line break. Assumption: Python's
  `urlsplit` raises only `ValueError` on the inputs tried (this machine's Python). Not tested: a capture through a local server with
  redirects (the recorded address is encoded when read, so every address is covered at read time).
- **Verification after the fix:** `engine.tests.test_read engine.tests.test_search`: 167 tests, OK.
- **Not run:** the rest of the engine's tests (the changed module is `read`).
- **Left for the owner:** the word to commit C.
