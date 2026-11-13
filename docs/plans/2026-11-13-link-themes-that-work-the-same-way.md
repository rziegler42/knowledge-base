# Link themes that work the same way, across fields

Status: Proposed
Created: 2026-11-13
Candidate: theme-weave#theme-links
Specs: docs/specs/weave.md

## Goal

A weave of "same mechanism" links exists over the themes of the library, and an agent can look at the links of a theme. The weave is
precomputed and stored, each link carries its method closeness, its wording distance, the matched texts and the evidence to check it,
and the links are kept by the slot rule and the floor of strength that the weave spec records (`docs/specs/weave.md`, "Keeping the
graph sparse without losing novelty"). New books are added to it in batches by repair, and it can be rebuilt on its own. When the
plan is done the owner has seen the links of some real themes and has said what they make of them.

## Scope

- A new module `engine/kb/weave.py` and the commands `python3 -m kb theme-links build`, `show` and `status` (and `repair`, as the
  increments below say). It reads the file of the theme vectors (`theme-vectors.sqlite`) and nothing else of the library, except that
  `status` reads when each book was added.
- The selection of links: the four bands of wording distance, the floor of strength, and the slot rule (3 slots in each band, at most
  one link to one book in a band, strongest first, links two-way).
- The file of the weave in the index root, written the way the file of the theme vectors is (a folder of its own, a lock, a rename),
  with the previous generation kept.
- numpy, as the accepted decision `docs/decisions/2026-11-13-the-engine-may-use-numpy.md` allows: pinned by hash, imported only where
  the weave is built or repaired.
- The README, the engine README and the weave spec, where they describe what is built.

## Non-goals

- The other kinds of weave: *same problem*, *fit together* and *alike* are the candidates `theme-links-same-problem`,
  `theme-links-fit-together` and `theme-links-alike`; *builds on*, *incompatible* and *disagrees* wait (the roadmap's deferred work).
- The walk, the narrow-to-wide setting, and the check of whether an ordinary search would have returned a theme (`theme-walk`).
- Any call to a model. The links need none, and no text of a book is sent anywhere by this plan.
- A change to the file of the theme vectors, to the themes or to the cards.
- Slots for a directional weave, an approximate nearest-neighbour index for a far larger library, and any package but numpy.

## Assumptions and constraints

- The file of the theme vectors exists and is the one for the embedding model the config names (`python3 -m kb theme-vectors`). The
  weave is derived from it: it is built from that file alone and says which model, dimension and build of it it was made from.
- A theme with no usable summary vector or method vector is not in the weave and is counted. On the owner's library of 2026-11-13,
  1,805 of 1,913 themes had both.
- The numbers of the design are the owner's decisions and are in the spec: 4 bands, 3 slots in each band, one link to one book in a
  band, the floor at the median closeness of all pairs of themes of different books, and the batching rule (new themes reaching about
  5 percent of the themes already linked, or 30 days from the oldest unlinked book, or the owner's word). The batching numbers are
  guesses that this plan may tune on the real library.
- Measurements that the design rests on are in the spec's "Evidence": on 1,805 themes a build took about 1 second, 9,264 links
  resulted, no theme had more than 12, 14 percent of the links fell at or under the floor, and a repair for 17 added books took about
  0.7 second and gave 72 percent of the links of a full rebuild.
- Tests that import numpy run in the pinned environment (`engine/.venv/bin/python`). Installing into that environment fetches
  a package from the internet, and the owner says when.
- Nothing tracked points to anything untracked: the real-library report is kept outside the repository and cited by its sha256.

## Completion criteria

1. A build makes a file of the weave in which every link joins themes of different books, no theme has more than 12 links, more than
   3 in one band, or two to the same book in one band, and every link is closer than the median closeness of all pairs of themes of
   different books. The same vectors file gives the same links, in the tests and on the real library.
2. The weave file says what it was made from (the model, the dimension and the build of the vectors file), its generation, the band
   edges, the median it used, the slot count, and every theme it processed with its generation and text hashes, those left with no
   link included, so that a theme the floor left with no link is not mistaken for one awaiting repair; a weave made from a vectors
   file that has since changed is said to be out of date and is not shown as current.
3. `theme-links show` prints the links of one theme by band, each with the other theme as a theme-search result shows it, the method
   closeness, the wording distance, and the matched method texts of both, with every text of a book cleaned and withheld whole if it
   holds the words of an untrusted-text marker, as the rest of the engine shows it.
4. `theme-links status` says how many themes are linked, how many are not yet linked, how many have changed or gone, and whether a
   repair is due and why, or that a full `theme-links build` is needed; `theme-links repair` adds the unlinked themes by the rule the
   spec records, keeps every rule of criterion 1, refuses when none of the three triggers holds unless the owner says to go on,
   makes a new generation and keeps one previous. A book whose themes changed, or a book taken out, is treated as removed and added
   again: the links of its old themes are dropped, the themes that lost a link are refilled, and its new themes are added as unlinked
   themes. A repair refuses, saying that a full build is needed, and does not go on even when told to, if more than 5 percent of the
   themes in the weave have changed or gone, or the vectors file is for another model, dimension or prefix.
5. numpy is imported only by the build and the repair, and every other command runs without it; it is pinned by hash in
   `engine/requirements.lock`, and the READMEs say which commands need it.
6. The weave has been built over the owner's real library, nothing was sent to any model, the figures are recorded in the Result, and
   the owner has seen the links of some real themes and said what they make of them.

## Increments

### Increment A — numpy in the pinned environment

**Outcome:** numpy is in `engine/requirements.lock` with a hash, installs into `engine/.venv` the way the other pinned packages do, and
the READMEs say which commands will need it.
**Dependencies:** none. The decision `2026-11-13-the-engine-may-use-numpy` is accepted.
**Affected areas:** `engine/requirements.lock`, `README.md` and `engine/README.md` (the requirements lines and the install lines).
**Steps:**
1. With the owner's word to fetch a package, find the wheel for Python 3.15 on macOS arm64 that the lock should name, and take its
   hash from the index (not from a file the engine made); record the version, the wheel name and the hash in the lock in the form of
   the other entries.
2. With the owner's word, rebuild or update `engine/.venv` with `pip install --require-hashes --no-deps -r engine/requirements.lock` and
   show what changed (`pip list` before and after: only numpy is added, no other package changes its version).
3. Say in both READMEs that the build and the repair of the weave need numpy, from the pinned environment, and that every other command
   does not; the lines that now say "no code imports it yet" change when the code that imports it is written, in Increment C.
**Verification:** `engine/.venv/bin/python -c 'import numpy; print(numpy.__version__)'` prints the pinned version, `pip list` shows only
numpy added, and the tests of the extractor that already run in this environment still pass
(`engine/.venv/bin/python -m unittest engine.tests.test_convert`), because installing a package into a pinned environment could change
a shared package; numpy has none. No wider run.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-13-link-themes-that-work-the-same-way#A`.

### Increment B — the selection of links, as pure functions

**Outcome:** a module with the functions that, given the summary vectors and the method vectors of themes and the book of each,
return the links by the slot rule and the floor, with no file and no store.
**Dependencies:** A.
**Affected areas:** `engine/kb/weave.py` (new: the selection only), `engine/tests/test_weave.py` (new).
**Steps:**
1. Write the tests first and see them fail, on small vectors made by hand so that the answer is known: the band edges (the quarters of
   the summary closeness over the pairs of themes of different books), the median method closeness of those pairs, a link between two
   themes of one book never made, the floor (a pair at or under the median never linked), the slot rule (no theme above 3 links in a
   band or 12 in all, no two links to one book in a band, strongest first), the links two-way and counted once, the tie broken by the
   keys of the themes so that the same input gives the same links, a theme with no usable vector left out and counted, and the same
   links whatever the order in which the themes are given; and values that sit within 0.0005 of the median or of an edge, on both
   sides and exactly on it, which an estimate that is only close would put on the wrong side.
2. Write the functions with numpy, working in blocks of themes so that memory does not grow with the square of the number of themes.
   The closeness of a pair is worked out in double precision and kept as an integer, in billionths, rounded, so that the same pair gives
   the same value whatever the block it was worked out in. The median of the method closeness of all pairs of themes of different
   books, and the three edges of the bands (the quarters of the summary closeness over those pairs), are exact: the value at the rank,
   by linear interpolation between the two nearest values as `numpy.median` and `numpy.quantile` give it. They are found in memory
   that does not depend on how the values are spread, by a radix selection over the blocks: a pass counts the values in 65,536 bins
   of the top 16 bits of the integer, finds the bin that holds the rank, and a second pass counts the next 16 bits within that bin,
   so the rank is pinned to one integer value in at most two passes, equal values being only counts; the two order statistics that
   the interpolation needs are found the same way. A pair is above the floor only if its closeness is greater than the median, so a
   pair exactly at it is not linked. The tests compare the result with `numpy.median` and `numpy.quantile` over the whole matrix on
   vectors small enough to hold it, with odd and even counts and with repeated values, and with every pair equal and every pair within
   1e-6 of one value (identical and tightly clustered vectors), where they also check that the largest array held during the
   selection does not grow with the number of themes.
3. Deliberate breaks, each restored byte for byte and each caught: no floor; the floor at the wrong side or a pair exactly at the
   median linked; one slot too many or too few; the band by a wrong edge; two links to one book in a band allowed; links not
   strongest first; pairs of one book allowed; the edges taken over pairs of one book too; ties left to the order of the input; the
   median or an edge taken from a coarse histogram (off by 0.001); the median taken without the interpolation between the two middle
   values for an even count; the exact values of a bin collected whole (the memory grows with the number of themes when all the
   values are alike); the second pass of the selection left out.
4. A test that the same links result from blocks of different sizes.
5. The `reviewer` agent.
**Verification:** `engine/.venv/bin/python -m unittest engine.tests.test_weave`, and the breaks of step 3. No wider run: the module
is new and nothing else imports it.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-13-link-themes-that-work-the-same-way#B`.

### Increment C — the file of the weave and `theme-links build`

**Outcome:** `python3 -m kb theme-links build` reads the file of the theme vectors read-only, makes the links, and writes the file of
the weave in the index root, with a lock and a rename, keeping the previous generation.
**Dependencies:** B.
**Affected areas:** `engine/kb/weave.py` (the file, its schema, its reading and checks, the build), `engine/kb/__main__.py` (the
command), `engine/tests/test_weave.py`, `engine/README.md` and `README.md` (the lines of Increment A now say which code imports numpy),
`docs/specs/weave.md` (what is built).
**Steps:**
1. Write the tests first and see them fail: a build over a small vectors file (made as the tests of `themevectors` make one) gives the
   links of Increment B and the meta named in criterion 2; a second build of the same file gives the same links and a new generation
   with the previous kept as it was; a vectors file for another model, dimension or prefix, damaged, or not made by this engine, is
   refused as `themevectors` refuses it; the weave is written in a folder of its own and renamed under a lock, a killed build leaves
   no half file, and the file is mode 600; a link and a lock file that is a symbolic link are not followed; the vectors file is not
   changed (its bytes before and after); no model is called (the embedding call is made to fail if reached); a command run without
   numpy installed (the import made to fail) refuses the build with a message that says what to install, and every other command
   still runs.
2. Write the file: `meta` (format, kind, generation, the model, dimension and build of the vectors file, the band edges, the median,
   the slot count, the time), `themes` (the key of every theme the build processed, whether it ended with links or with none, its theme generation, the hash of its
   method text and of its summary text, and its number of links) and `links` (the two keys, the method closeness, the wording distance, the band). Check every row when the file is
   read, as `themevectors` does, so that a file that is not the engine's is refused.
3. Write the command and its output (the counts: themes in the vectors file, themes processed, of them those with links and those left
   with none, themes left out because they have no usable vector and why, links, links dropped by the floor, themes with no link in
   the farthest band, the generation). A test shows that a theme left with no link by the floor is in the weave, with zero links.
4. Deliberate breaks, each caught: the lock not taken; the rename before the write is whole; the previous generation not kept or
   kept over; the vectors file written to; a link followed; the meta not written; a row not checked on reading; numpy imported by a
   module that does not need it (a test that imports every other module with numpy made unavailable).
5. Update the README lines that said no code imports numpy, and the spec's account of what is built.
6. The `reviewer` agent.
**Verification:** `engine/.venv/bin/python -m unittest engine.tests.test_weave`, and, because the command line and the README change,
`engine/.venv/bin/python -m unittest engine.tests.test_themevectors` (the module whose file this one reads), and the breaks of step 4.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-13-link-themes-that-work-the-same-way#C`.

### Increment D — `theme-links show`

**Outcome:** an agent can look at the links of one theme, by band, with what it needs to judge each, and the text of an untrusted
book is shown as every other text is.
**Dependencies:** C.
**Affected areas:** `engine/kb/weave.py` (the reading of a theme's links), `engine/kb/__main__.py`, `engine/tests/test_weave.py`,
`engine/README.md`, `docs/specs/weave.md`.
**Steps:**
1. Write the tests first and see them fail: the links of a theme by band, each with the other theme as `themevectors.result_of` shows
   it (its citation, marks, flags, anchor and text between the untrusted-text markers), the method closeness, the wording distance and
   the matched method texts of both; a theme that is not in the weave said so, and a weave out of date said so with the command to run;
   hostile text (a title, a heading, a summary or a part that holds the words of a marker) is cleaned and withheld whole as the
   search shows it, in every string of the reply; the weave file is read-only and not changed.
2. Write the reading and the command; reuse `result_of` and the cleaning that the search uses, and add no other path by which text of
   a book reaches the output.
3. Deliberate breaks: a text not cleaned; the marker words left in a title; the links of another theme returned; the out-of-date weave
   shown as current; a band mislabelled; a link counted for one end only.
4. The `reviewer` agent. This command prints text of untrusted books from a derived file of the index root, so the owner is asked once
   whether to run a security review of it (it runs only when the owner asks).
**Verification:** `engine/.venv/bin/python -m unittest engine.tests.test_weave`, and the breaks of step 3. No wider run: the search
and the read are not touched.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-13-link-themes-that-work-the-same-way#D`.

### Increment E — `theme-links status` and `repair`

**Outcome:** the owner can ask whether a repair is due or a full build is needed, and a repair adds the unlinked themes by the rule of
the spec, treating a book whose themes changed as removed and added again, unless too many have changed.
**Dependencies:** C.
**Affected areas:** `engine/kb/weave.py` (the status and the repair), `engine/kb/__main__.py`, `engine/tests/test_weave.py`,
`engine/README.md`, `docs/specs/weave.md`.
**Steps:**
1. Write the tests first and see them fail: `status` counts the themes of the vectors file that the weave has not processed (not in its
   record of themes: these are the unlinked, awaiting repair), apart from those it processed that ended with no link, which it counts
   separately and which never make a repair due (a test: right after a build or a repair, with a theme left with no link by the floor,
   `status` says nothing is due); those whose theme generation or text hash changed, and those no longer in the vectors file; when more than 5 percent of the themes in
   the weave have changed or gone, or the vectors file is for another model, dimension or prefix, it says a full build is needed and
   not that a repair is due; otherwise it says a repair is due when the unlinked themes (new ones, and those of a book whose themes
   changed) reach 5 percent of the linked, or the oldest unlinked book was added 30 days ago or more (the `added` date of the book,
   read from the store without writing), and says which; `repair` refuses when none holds unless told to go on, and refuses in every
   case when a full build is needed; it drops the links of changed and gone themes, offers the candidate links of the new themes
   strongest first, lets a link take a free slot or replace the weakest of a full slot if it is stronger, refills the themes that
   lost a link, keeps the band edges and the median of the weave it repairs, never breaks a rule of criterion 1, is deterministic,
   makes a new generation and keeps one previous.
2. Write the status and the repair; the batching numbers are constants with the spec's values, named in one place.
3. Deliberate breaks: a theme left with no link counted as awaiting repair; the links of a changed or gone theme kept; a repair that goes on when more than 5 percent of the themes changed
   or gone (the share wrong by one theme, either way), or when the vectors model, dimension or prefix differs (also with the flag to
   go on); the trigger wrong by a day or by a share; a repair that breaks the slot rule or the floor; a displaced link not refilled;
   a previous generation lost; the store opened to write.
4. The `reviewer` agent.
**Verification:** `engine/.venv/bin/python -m unittest engine.tests.test_weave`, and the breaks of step 3. No wider run.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-13-link-themes-that-work-the-same-way#E`.

### Increment F — the weave over the owner's real library, and the owner's reading

**Outcome:** the weave has been built over the real library with no call to any model, the figures are recorded, repair is tested
against a rebuild, and the owner has read the links of some real themes.
**Dependencies:** D and E.
**Affected areas:** the owner's local index root (a new file, `weave-same-mechanism.sqlite`), a report outside the repository, and this
plan's Result.
**Steps:**
1. Say to the owner what will be written (one new file in the index root, and the previous generation kept on a second build) and that
   nothing is sent anywhere; wait for the owner's word.
2. Build the weave. Record the counts and compare them with the measurement in the spec: the number of links, the most links on a
   theme, the links dropped by the floor, the themes with no link in the farthest band, and the time.
3. In a throwaway copy of the vectors file, leave out about 10 percent of the books, build, then repair for them, and compare with a full
   build: the share of links in common and the mean method closeness (the spec records 72 percent and 0.618 against 0.624 for one such
   test); then repair in several batches, one after another, until all the books are back, and compare with a full build again, to
   see whether quality drifts, which the spec records as not tested. In the same copy, change the themes of a few books (as if
   they were made again, by giving each theme another text hash) and repair, which treats them as removed and added again, and
   compare with a full build the same way; and show that a change of more than 5 percent of the themes is refused.
4. Show the owner the links of three themes the owner names or the agent picks and says so, band by band, and record what the owner
   makes of them: whether the farthest band is too sparse, whether the weak links are useful, whether the floor is in the right place.
5. Keep the report outside the repository, mode 600, cited in the Result by its sha256.
**Verification:** the counts and the comparisons of steps 2 and 3, the file unchanged by any later read (its sha256), and no call to
any model. No wider run.
**Evidence:** the one local commit (the Result of this plan, and the spec's "Evidence" with the figures), with the trailer
`Plan: 2026-11-13-link-themes-that-work-the-same-way#F`.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later increment changed its inputs. Increment C changes the README lines that
Increment A wrote, and the tests of A are the install, so the install check is rerun after C. Increment F's real-library figures
rest on C, D and E and are taken after all three. The tests of `themevectors` are run in C because the weave reads its file; they are
not run again unless a later increment changes `themevectors.py`. Nothing wider is run: the search, the read, the cards and the
conversion are not touched, and the tests of the extractor run in A because the pinned environment changes.

## Risks and sensitive actions

- **A package is fetched from the internet and installed (Increment A).** It changes `engine/.venv`, which is not tracked. The hash in
  the lock is taken from the package index and checked at install (`--require-hashes`). The owner says when.
- **The weave file is derived from a file in the index root that anyone with write access could change.** It is read read-only and every
  row is checked as `themevectors` checks its own; a file that is not the engine's is refused.
- **`show` prints text of untrusted books.** It reuses the cleaning and the markers of the search and adds no other path; Increment D
  asks the owner once whether to run a security review (it runs only when the owner asks).
- **Memory.** A build holds blocks of vectors and not a matrix of all pairs; at the owner's library it is a few hundred megabytes at
  most, and the tests check the blocks give the same links. A far larger library may need an index and is a later decision.
- **A repair differs from a rebuild.** By the measurement 72 percent of the links of a repair are those of a rebuild, with the same
  quality; the drift over many repairs is untested and is measured in Increment F.
- **The floor may leave the farthest band sparse.** 22 percent of themes had no link in it in the measurement. The plan reports it and
  the owner reads it; changing the floor is a new decision.
- **A write to the owner's index root** happens only in Increment F, with the owner's word. No call to any model, no push.

## Review record

- **Reviewer:** the Codex review engine (`wb run review-engine review-plan`; models `gpt-5.6-terra` in rounds 1 and 2 and `gpt-6.1-sol` in
  rounds 3 and 4), asked for by the owner on 2026-11-13. Only the plan file was sent, with what the reviewer read of the project from it.
- **Rounds:** 4 of a bound of 4 (the owner extended it from 3 by 1; the ceiling is 5). It did not converge: round 4 still raised a
  finding. The owner chose to stop and approve rather than extend again.
- **Applied (4):**
  - R1-F1 (major): repair after a changed theme conflicted with the spec's rule that a change of theme generation needs a full rebuild.
    Applied; the owner then chose that a book whose themes changed is treated as removed and added again, with a full build needed
    when more than 5 percent of the themes changed or the vectors model, dimension or prefix differs. The plan and the spec say so.
  - R2-F1 (major): a histogram estimate of the median could put a link on the wrong side of the floor. The median and the band edges are
    exact order statistics, a pair exactly at the median is not linked, and the tests use values within 0.0005 of them.
  - R3-F1 (major): the exact selection could use memory that grows with the number of themes when scores are concentrated. The
    closeness is an integer in billionths and a radix selection over the blocks pins the rank in at most two passes with memory fixed
    by the bins; tests with every pair equal and every pair within 1e-6 check the values and the memory.
  - R4-F1 (major): a theme left with no link by the floor would have counted as awaiting repair forever. The weave records every theme
    it processed, with its number of links, and `status` counts those with none separately.
- **Rejected:** none.
- **Not reviewed after the last change:** the text of R4-F1 (status and the record of processed themes) was not seen by a reviewer.
  The `reviewer` agent looks at every increment, and Increments C and E carry tests and deliberate breaks for it.
- **Left for the owner:** whether to ask for a security review of Increment D (`show` prints text of untrusted books from a derived
  file); it is asked once there and runs only when the owner asks.

## Deferred work

- The other kinds of weave, in the candidates of the roadmap that name them.
- The walk, and the check of whether an ordinary search would have returned a theme.
- Slots for a directional weave, and an index for a far larger library.
- Whether the batching numbers (5 percent, 30 days) suit real use: tuned after the library has grown.
- Whether the 5 percent limit of changed themes, above which repair refuses and a full build is needed, is the right one: it is a
  guess, tuned on use. A check of how far the stored band edges and median have moved from what the current themes would give is a
  possible better test, left until a library has changed enough to need it.

## Result

Empty until work starts.
