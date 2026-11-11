# Show the mark of the item a search found

Status: Proposed
Created: 2026-11-10
Candidate: cards#card-inferred-items
Specs: docs/specs/card.md

## Goal

The owner decided on 2026-11-10 (plan `2026-11-10-decide-what-to-do-with-inferred-items`, Increment D) to keep the `inferred` topics and key
ideas on the cards, keep them in the keyword index, and show the mark with the item. `card-show` does that. A search result
does not do it where it matters: the result gives the counts of `stated` and `inferred` items of the whole card (`grounding`) and an
excerpt with no mark, so a reader of the excerpt cannot tell whether the sentence that matched was stated by the book or only inferred by
the model. This plan adds to each keyword result the mark of the item the excerpt comes from. When it is done, the second half of
`cards#card-inferred-items` ("show them with a warning, and the cards and the display do that") is true for search too. Whether to close or
reword the candidate afterwards is the owner's decision and is not made here.

## Scope

- A new key of a search result, `excerpt_mark`: `stated` or `inferred` when the excerpt is the text of one item of `topics` or
  `key_ideas` of a card that carries marks; otherwise `null`. It holds one of two fixed words or nothing, never text of a card.
- For those two fields, the excerpt of a keyword result is cut from the one item that holds the first spelling of a query word (the
  rule `excerpt_of` already uses on the joined text), and not from the joined text of all the items, so that the excerpt and the
  mark are of the same item by construction. The excerpt of every other field is as it is.
- The keyword search (`card-search`) builds it; `problem-search`, which drops the rendered card from each result and keeps the other
  keys, carries it through unchanged.
- The spec line and the README paragraph on search results say it.

## Non-goals

- Any change to a card, the catalog, the vectors, the keyword index or the display of `card-show`. The decision was (c); nothing is
  dropped or hidden.
- The search by meaning gets no mark. It ranks the neutral fields only (problem, approach, provides). In the library, counted by
  `card-marks` on 2026-11-10 (Result of Increment A of the decision plan), no sentence of the neutral fields of the ten cards of the
  sentence form is `inferred` (problem 8 and 0, approach 9 and 0, provides 9 and 0), and the neutral fields of the earlier form carry no
  mark. Its results keep `excerpt_mark: null`. If a later card has an `inferred` neutral sentence, that is a plan of its own.
- Caveats get no mark here. The decision of 2026-11-10 was (c) for topics and key ideas and put caveats and limits outside it
  (they are mostly `inferred`, 83 and 80 percent, and a quote can rarely state them), so their `excerpt_mark` stays `null` until the
  owner decides what to do with them (Deferred work). `card-show` and the rendered `text` of a result still mark them.
- How caveats and limits that a quote cannot state should be written. The roadmap candidate keeps it out until the owner says.
- Any change to the roadmap.

## Assumptions and constraints

- **The result already shows marks inside the markers.** A keyword result's `text` is the whole card rendered as `card-show` renders it,
  with `[inferred]` after each such item, between the untrusted-text markers. What is missing is the mark as a fact outside the markers
  for the excerpt, and in `problem-search`, which keeps no card text. The plan's value is the structured key, not a new rendering.
- **The lists are parallel.** `card.validate` requires `grounding[field]` to have one entry for each item of `model[field]` for `topics`,
  `key_ideas` and `caveats` (this plan uses the first two), so the mark of an item is `grounding[field][i]["mark"]` for the same `i`. A card of the first format, a card
  with no model part and a card with no `grounding` record have no marks.
- **Why the excerpt must change for these fields (Codex review, round 1, R1-F2, checked in the code).** `catalog.search` cuts the
  excerpt from the joined text of a field (items joined by ` ; `), 400 characters around the first spelling of a query word that
  `excerpt_of` finds as a substring, ignoring case. A window of that size usually holds several short items, possibly of different
  marks, and the index matches whole tokens (`unicode61`, diacritics removed) while the excerpt matches a substring, so the item the
  index matched and the item the excerpt shows can differ (`topic` is a substring of `topical`). No mark of "the item" is true of such a
  window. The contract is therefore: for `topics` and `key_ideas`, the excerpt is cut from the first item (in card order) that holds a
  spelling of a query word by `excerpt_of`'s own rule, and the mark is that item's; when no item holds a spelling (the index matched by
  a diacritic or case folding that the substring rule misses) the excerpt is cut as today and the mark is `null`. The mark is of what
  the excerpt shows, which is what a reader needs, and not of the index's reason for the match.
- The key holds no free text, so it needs no marker. Everything is read from the card after `card.validate`, as `result_of` reads the
  rest. A row altered after the build is refused as it is now.
- Result keys are pinned by tests (`test_catalog`, `test_search`, `test_vectors`, `test_problem`); a new key changes those expectations
  and no other consumer in the repository is known to read result keys by position.

## Completion criteria

1. A keyword result has `excerpt_mark`. It is `inferred` or `stated` when the excerpt is the text of one topic or key idea marked so, and
   `null` for an excerpt from any other field (caveats included), for a card without marks and for a card with no model part.
2. A search by meaning and a problem search return results with the key present, and it is `null` for the meaning search.
3. The mark is that of the item the excerpt shows, not of the first item of the field and not of the card: a test with a card whose
   first topic is `stated` and whose matching topic is `inferred` (and the reverse) tells the two apart.
4. The tests of the catalog, the search, the vectors, the problem search and the card pass, and `wb run code-work check` finds no
   problems. The spec and the README say what the key is.

## Increments

### Increment A — The mark of the excerpt's item in a search result

**Outcome:** `catalog.result_of` gives every result `excerpt_mark`, and the keyword search sets it from the item the excerpt is from.
**Dependencies:** none (the decision is recorded; `card-marks` and the grounding record exist).
**Affected areas:** `engine/kb/catalog.py` (`search`, `result_of`, and the `pick` that cuts the excerpt), `engine/kb/search.py`
(`excerpt_of`) only if it must be shared; `engine/kb/vectors.py` and `engine/kb/problem.py` only to confirm the key is present and carried (no behaviour change
expected); `engine/tests/test_catalog.py`, `test_search.py`, `test_vectors.py`, `test_problem.py`; `docs/specs/card.md` (the
"Searching the catalog" lines, edited in place to say what is built); `engine/README.md` (the paragraph on search results).
**Steps:**
1. Read `excerpt_of`, `catalog._matched` and the index tokenizing; confirm the facts under "Why the excerpt must change" (a window
   crossing items, and a substring that is not a token) with a throwaway card, and record them in the Result.
2. Write the tests first and see them fail: the cases of criterion 1 (a stated and an inferred item, in a topic and a key idea; a
   caveat; a field with no marks; a card of the first format; a card with no model part), criterion 3 (the matching item is not the
   first, both ways round), a word in two items of different marks (the first in card order is shown), an excerpt that used to cross
   two items of different marks and now holds one, a word that is a substring of a longer word in an earlier item (the item shown and
   marked is the earlier one, as the excerpt says), a match by diacritics or case that the substring rule misses (excerpt as today,
   mark `null`), a long item (the excerpt is still at most 400 characters), the meaning search, and a problem search result that
   carries the key without the card text.
3. Add `excerpt_mark` to `result_of` (read from the checked card, `null` unless the excerpt's field is `topics` or `key_ideas`, an item
   holds a spelling, and the card has `grounding`), and change `pick` in `search` to cut those two fields' excerpt from that item.
4. Say it in the spec lines and the README paragraph on search results, in place, as what is built.
5. Make deliberate breaks, each from green, and see each caught: the mark of the first item of the field, the mark of the card (the
   majority or the counts), the marks swapped, the excerpt cut from the joined text again, a mark given for a caveat, the mark taken for
   a field that has none, the key missing from the meaning search, and the
   key missing from the problem search.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_catalog engine.tests.test_search
engine.tests.test_vectors engine.tests.test_problem engine.tests.test_card`; `wb run code-work check`; one read-only
`python3 -m kb card-search` on the library for a word known to be in an `inferred` topic, to see the mark on a real result. No model is
called by the keyword search; the meaning search sends the query to the model of the config, so it is not run on the library here (the
tests use the fake model).
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-10-show-the-mark-of-the-item-a-search-found#A`.

## Verification for the plan as a whole

The one increment's recorded verification stands. At the end, rerun the five test modules above once and `wb run code-work check`. A wider
run is not named. What could break outside what is tested: a script or an agent that reads a search result by an exact set of keys (none
is known in this repository); the test modules named are the ones that pin result keys.

## Risks and sensitive actions

- **A wrong mark is worse than none.** If the item named is not the one the excerpt shows, a reader trusts a mark that belongs to another
  sentence. The excerpt and the mark are taken from the same item by construction, and the tests of criterion 3 and the breaks aim at
  this. **The excerpt of topics and key ideas changes** (one item, not a window over several): tests that pin the old excerpt are
  changed with it, and the Result names each. The owner may prefer to leave the excerpt alone and have the mark `null` when the window
  holds more than one item; that would make the mark rare (items are short and the window is 400 characters), and is why it is not the
  plan.
- **A new field of output.** It holds one of two fixed words or `null`, read from a validated card; no text of a book reaches it. I would
  not ask for a security review of this, since no input path changes; the owner may ask for one.
- Nothing is sent out, nothing is written outside the repository, and no card, catalog or vector file is changed.

## Review record

Codex through the review engine (model `gpt-5.6-terra`), 2 rounds of 3. Round 1: verdict `changes_needed`, two major findings, both
applied. Round 2: no meaningful findings, converged.

- **R1-F1, applied (major).** The decision of 2026-11-10 chose (c) for topics and key ideas only and left caveats and limits outside it,
  so a mark for caveats widened it. The key is limited to `topics` and `key_ideas`; caveats keep `null`, and marks for caveats are in
  Deferred work for the owner.
- **R1-F2, applied (major).** Checked in `excerpt_of` and `catalog.search`: the excerpt is a 400-character window over the joined items,
  so it can span items of different marks, and it matches a substring where the index matches tokens. For `topics` and `key_ideas` the
  excerpt is now cut from one item (the first holding a spelling of a query word) and the mark is that item's, `null` when no item holds
  one; the tests and breaks name the boundary and substring cases. The change of the excerpt is stated in Risks.

## Deferred work

- A mark for the neutral sentences in a meaning search, if a card ever has an `inferred` one (see Non-goals).
- Marks for caveats (mostly `inferred`): the owner's decision on caveats and limits, which the decision of 2026-11-10 left open. The same
  code would serve once the field is named.
- The marks of every matching item, not only the excerpt's, if a reader needs them; the key can grow to a list without breaking this one.
- Closing or rewording `cards#card-inferred-items`: the owner's decision after this plan is done.

## Result

### Increment A — The mark of the excerpt's item in a search result

- **Step 1, the facts, confirmed.** Before the change, the test of a card with topics `alpha one`, `beta quokka`, `gamma three` showed the
  excerpt `alpha one ; beta quokka ; gamma three` (the whole joined text, three items), so a window does cross items. The substring case
  (`topical sweets` before `the topic of bees`, query `topic`) is a test that passes after the change with the earlier item shown and
  marked, as the contract says. A fact found while reading: a topic is at most 60 characters and a key idea at most 300 (`MODEL_SHAPE`
  in `engine/kb/card.py`), both under the 400 of an excerpt, so the item-based excerpt is always the whole item and is never cut.
- **Done.** `engine/kb/catalog.py`: `result_of` takes `(field, excerpt, mark)` from `pick` and gives every result `excerpt_mark`;
  `_item_excerpt` cuts the excerpt of `topics` and `ideas` from the first item (in card order) that `search.spells` accepts, and gives
  the mark of that item from `grounding`; when no item spells a word, or the card has no marks, the excerpt is cut from the joined text as
  before and the mark is `null` (with no marks the excerpt is still the one item). `engine/kb/search.py`: `spells` and `_spelling`, the
  rule `excerpt_of` already used, now shared. `engine/kb/vectors.py`: its `pick` gives `None` as the third value. Caveats and every other
  field give `null`. The spec line (`docs/specs/card.md`, Searching the catalog) and the README paragraph on a result say it.
- **Deviation, decided by the owner.** `engine/kb/problem.py` `MAX_REPLY` is raised from 60,000 to 61,000 characters (README and spec text
  changed with it, and the value pinned in `test_problem`). The new key adds about 24 characters to an entry, and an existing test
  (`test_five_sub_problems_at_the_largest_limit_over_many_cards_fit_in_the_bound`) requires 50 of the largest entries to fit: 50 entries of
  1,216 characters are 60,800, and before the key the margin was under 1 percent. The plan did not name this change. I stopped and
  put three options to the owner (raise the bound, change the test's factor from 50 to 25, or leave the key out of `problem-search`);
  the owner chose to raise it. The helper reads at most 65,536.
- **Verification as run.** `python3 -W error::ResourceWarning -m unittest engine.tests.test_catalog engine.tests.test_search
  engine.tests.test_vectors engine.tests.test_problem engine.tests.test_card`: 459 tests, OK (13 new in `ExcerptMarkTest`, one in
  `test_vectors`; `MERGED_KEYS` of `test_problem` gains the key); `wb run code-work check`: no problems. The new tests were seen failing
  first (missing key, and the joined window). 11 deliberate breaks, each from green and the files restored byte for byte, were each
  caught: the mark of the first item, of the field, the marks swapped, the excerpt cut from the joined text again, a mark for a caveat,
  a mark for a field with none, a mark invented for a card with no marks, the first item taken when none spells a word, a mark given to a
  result by meaning, the key dropped from a problem-search entry, and a case-sensitive spelling rule. Two were first missed (a defensive
  check of the mark's value, which cannot be reached through a validated card and was removed instead of tested; and the case rule, for
  which `test_the_case_of_the_query_does_not_matter` was added). A read-only `card-search` on the library (words `sampling`, `clustering`,
  `regression`, `search`) gave `inferred` and `stated` marks on topic and key-idea excerpts, and the `inferred` case (`hierarchical
  sampling`) is `[inferred]` in the card's own text. No model was called; the search by meaning was not run on the library.
- **Review.** Independent `reviewer`, one exchange, no blocking finding and no security risk named. It could not run anything and did
  not read the new tests or the document edits. Its three notes: the Result must be written (done here); `test_search.py` is among the
  modules named and is unchanged, which is fine because its tests pass; and the fall back to the joined text with `null` when the index
  matched an item the substring rule does not see is as the plan specifies. It noted that the `MAX_REPLY` change is not in the plan,
  which the Deviation above records.
- **Not done.** No security review (the owner was told none was recommended); the search by meaning on the library; marks for caveats
  (Deferred work).
