# Searching the cards by keyword

Status: In Progress
Created: 2026-11-07
Candidate: cards#card-catalog
Specs: card

## Goal

The cards of the library can be searched by keyword. A search of the catalog returns the cards whose text holds every word of the
query, ranked, each with the facts an agent needs to decide whether to look further: the book, its title and date, how complete the
source was, the scan findings, a citation line, and a short excerpt marked as untrusted. The catalog is a file in the index root
that is built from the book folders alone and can be thrown away and built again. When the plan is done, the three real cards can be
found by words that are in them, and the same words searched in the full text can be compared with what the cards find.

## Scope

- A catalog file `cards.sqlite` in the index root, apart from the search index, with a row for the newest card of each version of
  each active book, the whole card kept in the row as JSON, and a full-text table over the card's text fields: title, summary,
  uses, topics, adjacent topics, key ideas, the five neutral fields and caveats. A card with no model part is in it, found by its
  title.
- A rebuild from the book folders alone: it reads each card through `card.read` (hashes checked, card validated), writes a new file
  beside the old one and puts it in place, under a lock of its own, as the search index does.
- A search over it: the words of a query must all match in one card; optionally only the summary side (title, summary, uses,
  topics, adjacent topics, key ideas and caveats) or only the neutral side (the five neutral fields); optionally one named book.
- Each result gives the card: the card's text, rendered as `card-show` renders it (every field that came from a book, its source or
  a model cleaned and withheld if it holds the words of a marker) between the untrusted-text markers, and beside it the facts that
  hold no free text: the book and version, the generation of the card, whether it is for the current version, the date the book
  was added, a score, which fields matched, whether the card is partial, and a citation line. The card's text already holds the
  title, the kind, the reasons the card is partial, the structure of the conversion and the scan findings. A short excerpt of the
  first field that matched, behind the marker, shows why the card was found. A search reads the catalog file and nothing else, so
  it works with the bulk root away.
- Two commands: `card-index`, which rebuilds the catalog, and `card-search`.
- A try of both on the cards that exist, with the results written in this plan.

## Non-goals

- Search by meaning, embeddings and vectors; search by shelf; a filter by date; guest visibility.
- Keeping the catalog up to date by itself: `cards` does not refresh it, and neither does `process`. The owner runs `card-index`.
  An incremental update of one card is deferred.
- Searching the cards and the full text in one query, and judging whether the cards help (`cards#card-trial`).
- Phrase, prefix or operator syntax in a query: a query is words, as in the full-text search.
- Any change to the full-text search index, to `search`, or to a card.

## Assumptions and constraints

- A card is checked when it is read (`card.read`), so the text that reaches the catalog is already clean, within its limits and in
  the shape of a card. The catalog adds no trust: everything in it is model output or text from a book, shown as untrusted.
- The index root holds what can be rebuilt. The catalog is such a file; its loss costs a `card-index`.
- A query is cut into words and each word is put in quotes for the full-text table, and the whole is passed as a bound parameter,
  exactly as `search.py` does (`words_of`, `quote_words`), so an operator, a column name or SQL in a query is only a word. The
  columns named in a filter are constants of this module, never taken from the query.
- The catalog file is opened read-only for a search, a search that runs longer than ten seconds is stopped, and a file that holds
  anything this engine did not put there (a trigger, a view) or has another format number is refused with the command to run.
- The citation line is built when the catalog is written, from the card's own source facts, in the form `read` gives: the title
  between quotation marks that it cannot close, the arXiv id and label or the web address, the date retrieved, and the hash. A card
  keeps no PDF address, which a read adds for an arXiv paper (`address_pdf`), so for those books the catalog's line lacks that last
  part of the address and is otherwise the same. A test shows it equal to a read's line for a web page, and equal to it for an arXiv
  paper once the PDF address is taken from the read's line. Keeping the PDF address in the card is deferred; a card is never changed.
- A result's text that holds the words of an untrusted-text marker is withheld, by the rule the card renderer uses.
- The library's two roots are personal paths and appear in no tracked file. Tests use temporary libraries and fake launchers; no
  step makes a model call or sends text anywhere.

## Completion criteria

1. A catalog built from a library holds the newest card of each version of each active book and nothing else; a book that is not
   active, and a card that fails its checks, are left out and counted; building it again, or after the file is deleted, gives the
   same search results.
2. A search returns exactly the cards whose text holds every word of the query, in a fixed order, and a word in any field is found;
   the summary-side and neutral-side filters and the book filter narrow the results as described; a query with an operator, a
   quote, a column name or SQL is only words.
3. A result gives the card: its text equals what `card-show` prints for the same card, between the markers, with a field that holds
   the words of a marker withheld; beside it are the facts listed in the scope and a citation line equal to what a read gives (up to
   the PDF address of an arXiv paper); its excerpt carries the untrusted marker and cannot add a line of its own after it; and a
   search works with the bulk root away.
4. A catalog of another format, or one with a trigger or a view, is refused with the command to run; a second writer waits for the
   first; a failure while building leaves the old catalog as it was.
5. `card-index` and `card-search` work through the command line.
6. The cards that exist were indexed and searched, and what the search found is written in this plan.
7. No name or path of the owner appears in a tracked file.

## Increments

### Increment A — The catalog file and its rebuild

**Outcome:** a catalog of the cards can be built from the book folders, and read back with the facts a result needs.
**Dependencies:** none.
**Affected areas:** a new module `engine/kb/catalog.py` and its tests `engine/tests/test_catalog.py`. The card, search and index
modules are read, not changed.
**Steps:**
1. Write the tests first, on a temporary library with cards filed by `card.file` (built from synthetic card text, no model); they
   fail because the module does not exist.
2. Define the file `cards.sqlite`: a table with a row for each card (book, version, generation, whether it is the current version,
   the date added, the citation line, and the whole card as JSON) and a full-text table over the text fields, with the row of one
   as the rowid of the other. Set a format number and refuse a file of another format or with a trigger or a view when it is opened.
3. Build the citation line from the card's source facts in the form `read._citation` gives, and test it as the criteria say: equal
   for a web page, and equal for an arXiv paper once the PDF address is taken from the read's line.
4. Write `rebuild(store)`: guard the library, take the lock `cards.lock` (no-follow, mode 600, waiting for another writer), build
   `cards.sqlite.new`, read the newest card of each version of each active book through `card.read`, leave out and count a book or
   a card that cannot be read, put the new file in place and remove the old file's journals; a failure leaves the old file as it
   was. Return the counts.
5. Run the tests and see them pass.
**Verification:** `python3 -m unittest engine.tests.test_catalog engine.tests.test_card engine.tests.test_store`. The card and store
tests are the nearest tests of the code the module reads through.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-07-card-catalog#A`.

### Increment B — Searching the catalog, and the two commands

**Outcome:** the catalog can be searched by keyword from the command line, with the results described in the scope.
**Dependencies:** A.
**Affected areas:** `engine/kb/catalog.py`, `engine/kb/__main__.py`, `engine/tests/test_catalog.py`, `engine/README.md` and `README.md`.
**Steps:**
1. Write the tests first, including hostile queries and hostile card text; they fail because the search does not exist.
2. Write `search(index_root, query, ...)` with the words of the query quoted as `search.py` does, the optional filter to the summary
   side or the neutral side (a fixed list of columns in a column filter), the optional book (its id checked), the limit (1 to 50,
   default 10), ranking by the table's measure and then a fixed order, the catalog opened read-only, and a time limit.
3. Build each result from the stored rows alone: read the stored card and check it with `card.validate` (a row that fails is a
   refusal that says to run `card-index`), render it with `card.render` between the markers, and add the facts, the score, which
   fields matched, and an excerpt of the first field that holds a word of the query, cut around it on one line with the untrusted
   marker in front and withheld if it holds the words of a marker. Test that the rendered text equals what `card-show` prints.
4. Add `card-index` (rebuild, print the counts, exit 1 if any card failed) and `card-search QUERY [--book ID] [--in all|summary|neutral]
   [--limit N]`, which prints the results as JSON.
5. Say in `engine/README.md` what the catalog is, how to build and search it, that `cards` does not refresh it, and what the
   result holds; add one sentence to `README.md`.
6. Run the tests and see them pass.
**Verification:** `python3 -m unittest engine.tests.test_catalog engine.tests.test_card engine.tests.test_setup`. The setup tests are
included because `__main__.py` changes.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-07-card-catalog#B`.

### Increment C — The catalog on the cards that exist

**Outcome:** the owner has seen the catalog find the real cards, and what it finds is written down.
**Dependencies:** B.
**Affected areas:** the index root of the owner's library (a new rebuildable file, not tracked) and this plan's Result.
**Steps:**
1. On the owner's word, run `card-index` on the library. It reads the cards from the bulk root and writes `cards.sqlite` in the
   index root. No model is called and nothing is sent anywhere.
2. Search with words that are in each of the three cards (a name from the title, a topic, a word from the neutral fields), with the
   summary-side and neutral-side filters, and with a book named; note what is found and in what order.
3. Run the full-text `search` for the same words, and note what only one of the two finds. This is a look, not the trial: it
   judges nothing.
4. Record the run in this plan's Result.
**Verification:** `python3 -m unittest engine.tests.test_catalog engine.tests.test_card engine.tests.test_cardmake` once more, and
the run of steps 1 to 3, read as written.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-07-card-catalog#C`.

## Verification for the plan as a whole

Each increment's recorded verification still stands unless a later increment changed its inputs. After C, rerun
`python3 -m unittest engine.tests.test_catalog engine.tests.test_card engine.tests.test_cardmake engine.tests.test_search
engine.tests.test_setup` once: the search tests are included to show that the full-text search is as it was, and the setup tests
because `__main__.py` changed. The wider engine suite is not named: no stage, no conversion and no full-text index changes. A wider
run is the owner's to ask for.

## Risks and sensitive actions

- **Model text and book text in a database.** Everything in the catalog came through `card.read`, so it is checked and clean, and
  it is shown only as an excerpt behind the untrusted marker, or withheld. A query is words and is bound as a parameter. Nothing
  in the catalog is run.
- **A new file in the owner's index root.** It is rebuildable and the owner can delete it. Step 1 of increment C asks first.
- **A catalog that is out of date.** `cards` does not refresh it, so a card made after the last `card-index` is not found. The
  README says so; the search result does not say how old the catalog is.
- **A card with no model part.** It is found only by its title, and its result says that it is partial.
- **The size of a result.** A result carries the whole card, a few thousand characters, so a search with the largest limit of 50
  prints a few hundred thousand characters at most. The limit defaults to 10.
- **A damaged catalog.** A row that fails `card.validate` stops the search with the command to run, and does not show it.

## Review record

Reviewer: Codex through the review engine (model gpt-5.6-terra). Round 1 of 3: changes needed, two findings, both applied.

- R1-F1, applied: a citation equal to a read's line cannot be built for an arXiv paper, because a read adds the PDF address
  (`address_pdf`) and a card keeps no such key (checked in `read.py` and `card.py`). The contract now says the catalog's line lacks
  that last part of the address for those books and is otherwise the same, with a test for a web page and a test for an arXiv paper
  once the PDF address is taken from the read's line. Keeping the address in the card is deferred; a card is never changed.
- R1-F2, applied: the roadmap says a result gives the card, and the plan returned only facts and an excerpt. The catalog now stores
  the whole card, each result carries the card's text as `card-show` renders it, between the markers and with the same withholding,
  and a row that fails `card.validate` stops the search with the command to run. A test shows the text equal to `card-show`'s.

## Deferred work

- Refreshing the catalog when a card is filed, and an incremental update of one card.
- Search by meaning and the embedding model; search by shelf; a filter by date; guest visibility.
- Searching the cards and the full text together, and the trial of whether the cards help (`cards#card-trial`).
- Telling the reader how old the catalog is, and listing the catalog's cards.

## Result

### Increment A — The catalog file and its rebuild (2026-11-07)

Added `engine/kb/catalog.py`. The catalog is `cards.sqlite` in the index root, apart from the full-text index, which it neither reads
nor changes. A table `cards` has a row for the newest card of each version of each active book (book, version, generation, whether
the version is the book's current one, the date added, the citation line, and the whole card as JSON), and a full-text table
`cards_fts` has one column for each text field (title, summary, uses, topics, adjacent topics, key ideas, the five neutral fields,
caveats), its rowid the id of the row in `cards`; a card with no model part has only its title. `rebuild(store)` guards the library,
takes the lock `cards.lock` (no-follow, mode 600, waiting for another writer), builds `cards.sqlite.new`, reads each card through
`card.read` (hashes checked, card validated), leaves out and counts a book that is not active (`inactive`) and a book or a card that
cannot be read (`failed`), checks the library again, makes the file private (mode 600), removes the old file's journals and renames the
new file into place; any failure leaves the old catalog as it was and no half-built file. `connect` refuses a file of another format
number, with missing or different tables or columns, whose full-text table is not an FTS5 table, or that holds a trigger or a view, each
with the command to run. `citation_of` builds the citation line from the card's own source facts in the form a read gives.

Verification run: `python3 -m unittest engine.tests.test_catalog engine.tests.test_card engine.tests.test_store` gave 125 tests, OK
(35 new in `test_catalog`, which also pass with a resource warning treated as an error). Tests were written first and failed because
the module did not exist. Twenty-one deliberate breaks were each caught (a book with no card counted as failed; an inactive book
included or not counted; an older card read; every version current; a failing card stopping the build; two columns swapped; an
empty citation; the old journal staying; the library not checked again; the lock following a link; another format, other columns or a
plain table for the full-text table accepted; a trigger or view accepted; a half-built file staying; accents mattering; a card with no
model part losing its title; the build not atomic; the date added not checked; the file not private). A test caught a real bug while
I wrote it: after a database error the half-built `.new` file stayed behind; cleanup now runs in a `finally`. Not run: any other test
file, and the catalog on the owner's library (increment C).

Review: the `reviewer` agent, one exchange, no blocking findings. Applied: the plan said the citation line is "otherwise the same" as a
read's apart from the arXiv PDF address, and that is too strong; it also differs when a card dropped a non-web address (a read says
`non-web address`, the card has none, and when a web address was asked for the card shows that one), and when an address is between
300 and 500 characters (the card keeps 300). The docstring says so and three tests pin these cases; the plan's own text is not
changed. The date added, which comes from the book file and not from the checked card, is now stored only if it has the shape of a
date, since increment B shows it outside the markers; the check of a foreign file also looks at the columns and at the full-text
table; the file is private; and tests were added for the join of the two tables, a book that cannot be read, a library that is not
there at the start, and the other states that keep a book out. Noted for B: `connect` wraps database errors only while opening, so the
search must wrap errors of its own queries in a refusal that says to run `card-index`; and an operating-system error that is not a
refusal propagates, as in the full-text index, and is reported by the command. Not changed: `versions` and `cards` in the counts are
always equal for now.

### Increment B — Searching the catalog, and the two commands (2026-11-07)

Added `catalog.search` and the commands `card-index` (rebuild, print the counts, exit 1 if any card failed) and `card-search QUERY
[--book ID] [--in all|summary|neutral] [--limit N]` (the query is one quoted argument, as in `search`). The words of a query are cut
and quoted by the rules of `search.py` and bound as a parameter; the side is a column filter built from constants; the book id is
checked and bound; the limit is 1 to 50 (10 by default); the catalog is opened read-only and a search is stopped after ten seconds;
results are ranked by the table's measure and then by book and version. Each result carries the card rendered as `card-show` renders
it, between the untrusted-text markers (a field with the words of a marker is withheld), an excerpt of the first matching field behind
the marker, the fields that matched on the side searched, the score, and facts: book, version, generation, whether it is the current
version, the date added, whether the card is partial, and a citation line. A search reads the catalog file and nothing else. Every row
is checked against its stored card before it is shown: the card must pass `card.validate`, belong to the row's book and version, and
the row's citation, date, generation and version flag must be what the card gives; a row that is not, a card nested too deeply to read,
and a database error are refusals that say to run `card-index`. The excerpt is cut from the stored card and not from the full-text
columns. `engine/README.md` has a section "Searching the cards" and `README.md` says the cards can be searched.

Verification run: `python3 -m unittest engine.tests.test_catalog engine.tests.test_card engine.tests.test_setup` gave 160 tests, OK
(74 in `test_catalog`, which also pass with a resource warning treated as an error). Tests were written first and failed because the
search and the commands did not exist. Deliberate breaks of the search, the row checks and the commands were caught except where a
break's code no longer exists. How that check went, honestly: my first run of the breaks was on a baseline with one failing test of
mine (a wrong expected order), so I discarded it, fixed the test, and ran again; the second run had three survivors, which were gaps in
my tests (ties in the score, the stored-card check, the read-only open) and now have tests; after the review's fixes one break
survived again (the book and version check was covered only through the citation check, so I added a test with two books whose
citations are the same) and one was a check that cannot fail (the score is computed by the query, not stored), which I removed. Also,
my scripted edit of the documents was refused by the command gate, and I made the edits with the edit tools. Not run: any other test
file, and the catalog on the owner's library (increment C).

Review: the `reviewer` agent, one exchange, no blocking findings. Applied: the facts printed outside the markers (citation, date,
generation, version flag) came from the row unchecked and are now checked against the card on every search; an address in the
citation is escaped as a read escapes it (a quotation mark, a space), since a card is only checked for a web prefix; the fields that
matched and the excerpt now follow the side that was searched and come from the stored card; a tampered row or a deeply nested card
gives a refusal and not a traceback; and the README no longer calls the citation a fact without free text (it holds the title and the
address, cleaned, outside the markers). Recorded, not changed: `card.validate` accepts a quotation mark or a space in an address,
which `mechanical` never produces; tightening it would change `card.py`, outside this plan, so the catalog escapes it instead.
