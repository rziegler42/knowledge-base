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

### Increment E-A — Corrections from the security review of the weave module

**Outcome:** three corrections that the security review of the weave module asked for (L1, L3 and L5 in its Result) are made, each with a test that failed before the correction, a second
look by the `reviewer` agent, and the four limits that are accepted (L2, L4, L6 and L7) are written down where the owner and an agent will read them.
**Dependencies:** E. It follows the security review of 2026-11-13, whose findings and the owner's decision are in the Result.
**Affected areas:** `engine/kb/weave.py` (`_json_numbers`, `_read_meta`, `check_rows`, `_keep_previous`, `_publish`), `engine/tests/test_weave.py`, `engine/README.md`, `docs/specs/weave.md`.
**Steps:**
1. Write the tests first and see them fail. **L1:** a weave whose median is written as a list (`[5]`) or whose edges are written as one number is refused by `read` with a refusal that
   names the command, not a `TypeError`; `check_rows` refuses a median, an edge, a closeness or a wording that is not an int or a float, a boolean included; `status`, `show` and `repair` over
   such a file refuse and write nothing. **L3:** a weave whose generation has more than nine digits (up to twelve) is read, and a build or a repair over it writes the next generation and reads it
   back; a generation of twelve digits is refused at the start of a build or a repair with a message that says what to do, before any file is made. **L5:** where a hard link cannot be made
   (`os.link` failing), a weave in place that has been swapped for a symbolic link after the check is not followed: the copy is made from a file opened with `O_NOFOLLOW` and checked with
   `fstat` to be a regular file of this user's, so a link is refused with nothing written and the file it pointed to is left alone and not copied.
2. Make the three corrections, the least that makes the tests pass.
3. Write the four accepted limits in the README paragraph of the weave and in the spec's "Built" line: a weave file has no integrity tag, so a repair keeps the numbers the weave in place holds
   and only a full build works them out again (L2); a leftover folder that cannot be removed makes a build refuse, naming it (L4); a hot journal next to the weave makes it unreadable and a build
   then goes on from the generation before (L6); and the size: about 70 MB and 2 seconds at 1,000 themes, 260 MB and 8 seconds at 2,000 and 620 MB and 22 seconds at 4,000, so that a library of
   tens of thousands of themes needs several gigabytes and an index for the candidates (L7).
4. Deliberate breaks, each restored byte for byte and each caught: a list accepted as a median or as edges; a boolean accepted as a number; the generation limit left at nine digits, or not
   checked at twelve; `O_NOFOLLOW` left off the copy; the `fstat` check left out.
5. The `reviewer` agent, for a second look at the three corrections: a correction is new surface.
**Verification:** `engine/.venv/bin/python -m unittest engine.tests.test_weave`, and the breaks of step 4. No wider run: only `weave.py` changes, and nothing else imports it but the command line,
which the tests of the weave exercise.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-13-link-themes-that-work-the-same-way#E-A`.

### Increment F — the weave over the owner's real library, and the owner's reading

**Outcome:** the weave has been built over the real library with no call to any model, the figures are recorded, repair is tested
against a rebuild, and the owner has read the links of some real themes.
**Dependencies:** D, E and E-A.
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

### Increment G — what the measurements say about repair, and when to build again (documentation only)

**Outcome:** the README and the spec say, with the measured figures, that a repair is a quick way, that a full build takes about 5 seconds at 1,800 themes and is better when many themes changed,
that the limit above which a full build is needed stays at 5 percent of the themes of the weave (the same number as the share that makes a repair due), and that the owner may build again after
about five repairs in a row. The first version of this increment raised the limit to 10 percent; its measurement (step 1, done on 2026-11-13) did not support that, and the owner chose to keep 5
percent and write the findings down ("yes, rewrite G as documentation only"). No code, test or constant changes.
**Dependencies:** F (its measurements are the reason).
**Affected areas:** `engine/README.md` (the paragraph of the weave), `docs/specs/weave.md` (the batching rule, its evidence and the floor's owner reading already there).
**Steps:**
1. The measurement, already made on throwaway copies of the file of vectors (nothing written to the real library, nothing sent to any model; the report is outside the repository, mode 600, sha256
   `b6d2496ed8b62b930bf52b507e1fd0c0af2d4b60dbe828932b8d94907f4f1eb7`): the themes of books at 5, 7 and 9 percent of the themes were made again (another generation, a vector moved towards another
   theme's; a text hash cannot change without the text, which the file checks) and repaired with the limit set to 10 percent for that run only. The links in common with a full build over the same file
   were 69, 63 and 59 percent (the old links without a repair, 62, 53 and 49 percent), against 81 percent for a repair of 10 percent new themes. So a repair of changed themes recovers only 7 to 10
   points over leaving the links as they were, and the limit stays at 5 percent.
2. Write in the paragraph of the weave in `engine/README.md` and in the spec's batching rule, as measured and not as a promise: the figures of step 1 and of Increment F (a repair of new themes at 10
   percent: 81 percent of the links in common with a rebuild, mean closeness 0.645 against 0.648; five repairs in a row: 69 percent and 0.640; one repair of 30 percent: 72 percent and 0.6425); that more
   than 5 percent of the themes changed or gone means a full build, which takes about 5 seconds; that the owner may build again after about five repairs in a row; and that the numbers stay guesses to
   tune. Put the figures in the spec's "Evidence" with their provenance (what was run, the tool versions, the commit, the conclusion).
3. The `reviewer` agent, for a second look at the wording against the figures.
**Verification:** `wb run code-work check`, and a read of each figure in the text against the two reports (`weave-real-run-d86ef289da13.json` and `weave-g-measure-b6d2496ed8b6.json`, outside the
repository). No test run: no code changes. The real library is not touched.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-13-link-themes-that-work-the-same-way#G`.

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

### Increment A (numpy in the pinned environment; committed)

- **Done.** `engine/requirements.lock` pins `numpy==2.5.4` with the sha256 `0b4724a19de67bea8cfc4970798efa78bcbbe2ac2613cfac16721a42d44de2a5`
  of the wheel `numpy-2.5.4-cp315-cp315-macosx_14_0_arm64.whl` (5,454,250 bytes), between `lxml_html_clean` and `python-dateutil`; its header
  and a provenance line say what numpy is for and how the hash was taken. `README.md` (the install bullet of the quick start) and
  `engine/README.md` (the requirements sentence) say the same lock pins numpy, that only the build and the repair of the weaves will need
  it, and that no code imports it yet; Increment C changes that last clause.
- **The hash.** `pip download --no-deps --only-binary=:all: numpy==2.5.4` (with the owner's word) served the wheel from pip's cache of an
  earlier install from PyPI, not from a new download, so its hash was compared with the sha256 that `https://pypi.org/pypi/numpy/2.5.4/json`
  publishes for that file: equal, and the sizes equal. The lock says so (the reviewer noted that "the same way" overstated this and the
  line was corrected).
- **The install** (with the owner's word): `engine/.venv/bin/python -m pip install --require-hashes --no-deps -r engine/requirements.lock`
  installed numpy 2.5.4; the other 21 packages were already satisfied and unchanged (`pip list --format=freeze` before and after: the same
  21, plus numpy). `engine/.venv/bin/python -c 'import numpy; print(numpy.__version__)'` printed `2.5.4`.
- **Verification as run.** `engine/.venv/bin/python -W error::ResourceWarning -m unittest engine.tests.test_convert`: 169 tests OK (the one
  `ResourceWarning` about `kb/extract_traf.py` that it prints is the same as before this change); `wb run code-work check`: no problems.
- **Review.** The `reviewer` agent (read only): no blocking finding. Not blocking: the provenance wording (applied, above); the long line 9 of
  the engine README (left); the READMEs name the build and repair as future uses, as the plan says. It could not check the runs, the hash,
  the network comparison or the unchanged packages, which are the ones above. It noted that the sandboxed extractor is given the
  `engine/.venv` folder, where numpy now is; the extractor does not import it, and no exposure was named.
- **Not run.** The tests of the other engine modules (nothing but the lock and two README sentences changed, and no code imports numpy); a
  security review (not asked). No push.

### Increment B (the selection of links, as pure functions; committed)

- **Done.** `engine/kb/weave.py` (new, the selection only, no file and no store) and `engine/tests/test_weave.py` (new). `select(keys, books,
  summaries, methods, slots=3, top=300, block=256, use_floor=True)` returns the links, the three band edges, the median, the number of pairs and the
  themes left out; `exact_ranks` and `exact_quantiles` find the median and the edges exactly (the closeness is an integer in billionths, a radix
  selection in two passes with memory fixed by the bins: 16 top bits and 15 low bits, because the shifted range is below 2^31, where the plan said
  "the next 16 bits"; interpolation as `numpy.quantile` does it). numpy is imported inside the functions, so `import kb.weave` works without it.
- **Tests, first.** Written before the module and seen to fail (no module `kb.weave`). 32 tests: the exact selection against sorted lists (spread
  values, extremes, all alike, within 1e-6, repeated ranks, out of range, and the memory with 100 times the values, all alike), against
  `numpy.quantile` and `numpy.median` (odd and even counts, repeated values); hand-worked cases (one book, the floor and a pair exactly at the median,
  values 0.0004 either side of the median and of an edge, a pair exactly on an edge, three slots, one theme of a book in a band, strongest first, ties by
  keys, slots and `top` changed, themes left out, bad input, huge and tiny vectors, no numpy); and a plain-Python reference written from the rule, on
  random themes with and without the floor, with two sizes of `top`, with blocks of 1 to 1000, and with the themes in any order.
  `engine/.venv/bin/python -W error::ResourceWarning -m unittest engine.tests.test_weave`: **32 tests OK**; with plain `python3` the 32 are skipped with
  a reason.
- **Deliberate breaks.** 27, each caught, the file restored byte for byte (sha256 prefix `fd00df042a4c`): no floor; the floor at the wrong side; a pair
  exactly at the median linked; one slot too many and too few; a pair on an edge put in the band below; wrong edges; two links to one book in a band;
  not strongest first; pairs of one book; the edges and median over pairs of one book; ties by input order; the median and the edges from a coarse
  estimate; no interpolation; the selection's values collected whole (the memory test); its second pass left out; ties in what a theme puts forward to
  the last key; the closeness floored and not rounded; vectors not made unit and not scaled by their largest entry; the cut `top` not applied;
  unhashable books not refused; the pair count including pairs of one book; a left-out theme not named; a rank or a value out of range not refused.
- **A timing run on random vectors** (not the library; 1,800 themes of 2,560 numbers, 10 per book): 10.0 seconds and a peak of 381 MB traced, 10,778
  links. The spec's 1 second was measured with another procedure (float32 products, no exact selection, 100 candidates for each theme and band, vectors already in memory); this one makes three passes of double-precision products and prepares its inputs, and the comparison on the real library is for Increment F.
- **Review.** The `reviewer` agent (read only): no blocking finding. Applied: the unused `itertools` import removed; vectors with entries near 1e200
  or 1e-200 are scaled by their largest entry before the length is taken, so they are not wrongly left out; unhashable books are refused with a
  message; a test of pairs 0.0004 either side of an edge, which the plan asked for and I had only for the median. Recorded, not changed:
  (1) **`top` is a bound that neither the plan nor the spec states.** Each theme puts forward only its 300 closest partners in each band, so memory
  grows with the number of themes and not with its square; a theme whose candidates in a band are all taken gets no further link there even if
  other partners are free (the spec says the themes "take their next candidate"). The module says so in its docstring. The plain-Python reference
  uses the same cut, so the tests cannot show how often it bites; on the real library it can be seen by building with `top` at the number of themes
  and comparing, which Increment F can do. **The owner's decision (2026-11-13), on the agent's recommendation: accept `top` as a recorded
  bound**, to be measured in Increment F by building once with `top` 300 and once with `top` at the number of themes and comparing the links and the themes with
  none in a band, and to be written into the spec at Increment C; the rule without the cut (rounds of further candidates for themes with free slots) is a change
  of the plan, to be brought to the owner only if that comparison shows the cut changes real results. (2) A pair exactly on an edge is put in the band above it; the
  tests pin it and the spec should say so, in Increment C. (3) The closeness of a pair is worked out from the row of one end for the links and from
  the upper triangle for the median and the edges; a BLAS that sums in another order could differ by 1e-16, and a pair within that distance of a
  half billionth could then carry another value; with the same block size the result is the same every time, and the docstring says so.
- **Not run.** Any run on the real library (Increment F); the tests of the other engine modules (nothing else imports `weave`); a security review
  (not asked: the module is pure functions of numbers, with no file, subprocess or network). No push.

### Increment C (the file of the weave and `theme-links build`; committed)

- **Done.** `engine/kb/weave.py` now holds the file of the weave and its build below the selection of Increment B: `build(index_root, cfg)` reads the file of the
  theme vectors read-only (`themevectors.connect`, `check_entry`, `read_themes`, `check_vector_rows`, `iter_vectors`, as the search does), counts a vector only if its
  text is the text the theme still has, calls `select`, and writes `weave-same-mechanism.sqlite` in the index root: in a folder of its own under a lock, mode 600, read
  back before it is put in place, renamed into place; the generation before is kept as it was in `weave-same-mechanism.previous.sqlite` (a second name for the same
  file, or a copy where a link cannot be made). The file holds `meta`, `themes` (every theme processed, those left with no link included, with its number of links)
  and `links`. `read(path)` and `check_rows` check every row. `engine/kb/__main__.py` has `theme-links build`, which takes no option that names a model, a server or an
  address. The READMEs say that only `theme-links build` needs numpy (the repair will too), the engine README has a paragraph for the weave, and `docs/specs/weave.md`
  records the bound on the candidates (agreed), the edge side (proposed) and what is built (proposed).
- **Tests, first.** Written before the code and seen to fail (no `weave.build`, no `theme-links` command). `test_weave` has 60 tests: the build against `select` on a
  small file made as the tests of `themevectors` make theirs (six themes of three books with vectors at chosen angles), the meta, the counts, a second and a third
  generation with the one before kept byte for byte, mode 600, a leftover folder of a killed build, the vectors file unchanged and no model called, a failed rename and
  a failed second rename, another writer holding the lock, a lock file and a weave file and a name for the generation before that are links, a weave that is damaged
  (replaced, and the generation going on from the one before), a vectors file that is missing, damaged, not the engine's or for another model, dimension or prefix (nothing
  written), a stale vector, no numpy, a theme left with no link by the floor (in the weave with none), 28 ways in which a row of the weave file could be wrong (all refused),
  slots and two links to one book in a band, more than nine digits of pairs, the command line (counts, a second generation, no vectors file, no options, no numpy and
  every module of `kb` imported with numpy made unavailable). `engine/.venv/bin/python -W error::ResourceWarning -m unittest engine.tests.test_weave
  engine.tests.test_themevectors`: **171 tests OK**; with plain `python3` the 60 of `test_weave` are skipped with a reason.
- **Deliberate breaks.** 30, each caught, `weave.py` restored byte for byte (sha256 prefix `21182de24dce`): the lock not held; the file written in place and not in a folder
  of its own; the generation before not kept; a link followed (the lock file, the weave file, the weave in place when it is kept); the vectors file written to; the
  meta not written; rows not checked on reading; numpy imported at the top; a theme with no link left out; a leftover not removed; the file not private (and the copy);
  the generation not counted up or not gone on from the one before; a file in the way not said to be replaced; a stale vector accepted; the model of the vectors file
  not checked; the counts wrong; a link not above the floor, in the wrong band, with a wrong number on a theme, over the slots, or two to one book in a band not
  refused; a trigger not refused; the file in place not checked to be a regular file of this user's; pairs limited to nine digits.
- **Review.** The `reviewer` agent (read only): no blocking finding. Applied: the file in place is checked with `lstat` to be a regular file of this user's before it is kept
  as the generation before, and linked with `follow_symlinks=False`; the generation goes on from the generation before when the file in place is not a weave (it started
  again at 1 under a `previous` that could hold a higher number); the number of pairs may have up to 15 digits (a library of about 45,000 themes would have refused its own
  file); `build` also prints `links_at_or_under_the_floor`, the number of links the slot rule makes without the floor that are no closer than the median, which is
  what the plan's "links dropped by the floor" means (`links_without_floor` stays, and the second selection that gives them roughly doubles the time of a build); the README
  says that the model work of the config must be on, only to find the embedding entry; and tests for the copy fallback, a name for the generation before that is a link,
  a failure at the second rename, and the `lstat` check. Recorded, not changed: `read` checks the slot rule against the slots the file records, not the constant 3 (a
  build is given the number of slots, and the docstring says so); the one `previous` name shares the inode of the file in place until the new file is renamed over it, which
  is safe because a build never writes the old file, **and Increment E must write a new file and rename it, never change the file in place, or it would change the generation
  before** (the engine README says so too); a crash between the two renames leaves both names with the generation in place and loses only the generation before that.
- **Not run.** Any run on the real library (Increment F); the other engine modules' tests (nothing else changed besides the command line, which `test_themevectors`
  exercises); a security review (not asked: the new code reads two files of the index root, every row of which is checked, and writes one in a private folder). No push.

### Increment D (`theme-links show`; committed)

- **Done.** `engine/kb/weave.py` has `show(index_root, cfg, book_id, theme_id, version_id=None)` and `engine/kb/__main__.py` has `theme-links show BOOK_ID THEME_ID
  [--version V]`. It reads the file of the theme vectors and the weave read-only (the vectors file checked as the search checks it; the weave by `read`), sends nothing to
  any model and imports no numpy. It prints, first a `warning` (empty when the weave is current), then the weave (kind, generation, times, `current`, a note, and a text
  that says what the numbers are), the theme as `themevectors.result_of` shows it, the number of links, and the four bands (wording-farthest, second, third, wording-nearest),
  each with its links strongest first: the kind, the method `closeness`, the `wording_closeness` (how close the summaries are), the matched texts (the method text of each
  theme) and the other theme as `result_of` shows it, so that every text of a book is cleaned and withheld whole if it holds the words of a marker, and the excerpt and
  the text are between the markers; no other path carries text of a book to the output. Refusals: ids that are not ids; no such theme (naming `theme-search`); a theme in
  more than one version of its book (name it); a theme no longer in the vectors file; a theme not yet linked (build again); a theme the build left out because it has no
  usable summary or method vector (a build cannot help; the vectors are made by `theme-vectors`); a missing, damaged or foreign weave or vectors file. A weave made from an
  older build of the vectors is shown with the warning, and a linked theme gone from the vectors file is shown as `missing`. The READMEs and the spec say so.
- **Tests, first.** Written before the code and seen to fail (no `weave.show`). 77 tests in `test_weave` in all, of which 17 are new here: the links of a theme by band against
  `result_of` of the other themes; a link from both of its ends; the weave said to be current and the warning empty; out of date with the command; not yet linked and no such
  theme; a theme with no link; a theme missing from the vectors file; two versions of a book (named or not), and a book whose version changed since the weave; the left-out
  theme; the two files unchanged, no model called, numpy not needed; refusals for a missing weave, a damaged one and a vectors file for another model, dimension or prefix; bad
  ids; hostile text (a summary and a part that hold the words of a marker, a flag, a heading in the anchor, strings in every place of the reply, the markers counted); and the
  command line (it prints, `--version`, bad ids, a missing weave, no option names a model). `engine/.venv/bin/python -W error::ResourceWarning -m unittest
  engine.tests.test_weave engine.tests.test_themevectors`: **188 tests OK**; with plain `python3` the 77 of `test_weave` are skipped with a reason.
- **Deliberate breaks.** 17, each caught, `weave.py` restored byte for byte (sha256 prefix `7675e5f3a29b`): a text of a book not cleaned; the words of a marker left in a summary;
  the links of another theme returned; a link shown from one end only; an out-of-date weave shown as current, or its warning left out; a band mislabelled; closeness and
  wording swapped; a theme not yet linked, or one the build left out, not refused as it should be; a stale vector counted as usable; the model of the vectors file not checked;
  a theme missing from the vectors file not shown as missing; numpy needed to show; the number of links wrong; more than one version not refused; the words of the refusal for
  no such theme.
- **Review.** The `reviewer` agent (read only): no blocking finding. Applied: the left-out theme was told to build again, which cannot help (it is now told that the vectors are
  made by `theme-vectors`, and whether a theme has usable vectors is checked in the file, not guessed from the build time); "no such theme" names `theme-search`; versions are
  counted in the vectors file only, so a rebuild that moved a book from v1 to v2 is not called two versions; the field `wording` is named `wording_closeness` (a higher number
  is nearer wording), and the weave's text says so; a `warning` is the first thing printed when the weave is out of date; the help text of `theme-links` says that `build`
  needs numpy; the README says that the numbers of a weave are not worked out again from the vectors when it is shown, so a file written by someone else could hold others that
  look right (no text injection results: every text still goes through `result_of`). Recorded, not changed: `current` compares the time of the build and the model of the vectors
  only, so two builds of the vectors in one second look the same, and a build that changed nothing makes the weave look out of date, which errs on the safe side.
- **Not run.** Any run on the real library (Increment F); the other engine modules' tests (nothing else changed besides the command line, which `test_themevectors` exercises).
  A security review was not run. **The owner's decision (2026-11-13), on the agent's recommendation: no security review of this command now; the agent asks again before
  Increment F** (the first write into the real index root), for one review of the whole weave module (the reading, the build, the repair and `show`), which runs only when the
  owner asks. The reasons: the text of a book goes through `themevectors.result_of`, whose cleaning an earlier security review fixed; the other strings are validated ids, times,
  bounded numbers and fixed words; the surface is the same as the search's; and the earlier review's finding in the search (the anchor headings) is the precedent for asking
  once more over the whole module. No push.

### Security review of the weave module (asked for by the owner on 2026-11-13, before Increment F)

- **Run.** The `security-reviewer` agent, over `engine/kb/weave.py`, the `theme-links` commands and their tests, on a copy of the code in its own scratch folder, with forged weave and vectors
  files, links and races at the names of the index root, hostile vectors and a library fixture; it did not touch the owner's library or config. Findings are advice.
- **Result.** No Critical, High or Medium finding, and no path by which text of a weave file or of a book reaches the output unvalidated (every id is checked by a pattern, every book text goes
  through `themevectors.result_of`; the SQL is bound; a forged file is refused for a trigger, a view, an extra table, bad UTF-8, a float, a bool, NaN, inf, a huge number, a deep nest, a
  reversed key, a hot journal; the lock, the folder, the modes 0600 and 0700, the order of the renames and `expect_generation` against a second writer all held).
- **Seven Low findings** (each needs write access to the index folder or the weave file, or is a size limit):
  - **L1:** a forged median written as a list (`[5]`) is accepted by `read` and later raises an uncaught `TypeError` in `check_rows` or in a repair (nothing is written). Correction: `_json_numbers`
    returns a scalar for one number and `check_rows` refuses any type but int and float.
  - **L2:** a forged but well-formed weave (a median of -1e9, 999 slots) is accepted by `repair`, which keeps the weave's own numbers and writes a new generation that passes every check. The
    weave has no integrity tag, so no read can tell. An accepted trust boundary: the same position can already replace the vectors file; only `build` derives the numbers again.
  - **L3:** a forged generation of 999999999 blocks `build` and `repair` (the file they would write is refused by their own check) until the file is removed. Correction: allow more digits.
  - **L4:** a leftover folder that cannot be removed (read-only inside, or another owner's) makes every build refuse, with a clear message: denial of service only.
  - **L5:** the copy fallback of `_keep_previous` (used only where a hard link cannot be made) follows a symbolic link swapped in after the `lstat` check: it would copy a file the owner can already
    read into the previous name, mode 0600, where the next read refuses it. Correction: open the weave with `O_NOFOLLOW`, check `fstat`, and copy from the descriptor.
  - **L6:** a hot journal planted next to the weave makes every read refuse it, and a build then goes on from the generation before (the number can go back). Accepted.
  - **L7:** memory and time are bounded by the cut on the candidates and not by the square of the number of themes: 70 MB and 1.8 s at 1,000 random themes, 260 MB and 8 s at 2,000, 617 MB and
    22 s at 4,000; tens of thousands of themes would need several gigabytes. A size limit for a far larger library, which the plan already puts out of scope.
- **Not checked by the agent** (limits of the evidence): `os.link(follow_symlinks=False)` against a symlink swapped in a real race on macOS, a weave of hundreds of thousands of rows, the
  `Store.read_book` path with a hostile `book.json`, and an index root owned by another user.
- **The agent's evaluation and the owner's decision.** The agent recommends correcting L1, L3 and L5 (small, each with a test that fails first, and an independent second look, since a fix is
  new attack surface) and recording L2, L4, L6 and L7 as accepted limits in the README. A correction is a change of the code beyond the six increments, which the approved plan does not name, so
  it needs the owner's word and a new increment (E-A) with a new approval of the plan. **The owner's decision (2026-11-13): go with the agent's recommendation** (correct L1, L3 and L5 in
  Increment E-A; write L2, L4, L6 and L7 down as accepted limits); the plan was approved again with E-A in it (region `fcc14d7a…2a1b`).

### Increment E-A (corrections from the security review of the weave module; committed)

- **Done.** In `engine/kb/weave.py`: **L1** a median is one finite number and the edges are three in order (or `null` for both), in `_json_numbers` and now also in `check_rows`, which refuses a
  list, a boolean, text, NaN, infinity and an integer of any size (the range is tested before `isfinite`, which raises for an integer of 400 digits); `status`, `show` and `repair` over such a
  file refuse with the command to run and write nothing. **L3** the generation may have twelve digits (`_GENERATION_LAST`); a build or a repair over a weave at the limit refuses at its
  start, before any link is worked out and before any file is made, naming the two files to remove (the weave and the generation before, which holds the number too), and `_publish` checks
  again under the lock. **L5** where a hard link cannot be made, the copy that keeps the generation before is made from a descriptor opened with `O_NOFOLLOW` and `O_NONBLOCK`, checked with
  `fstat` to be a regular file of this user's, into a file created with `O_EXCL` and mode 0600; a link, a folder or a pipe swapped in is refused with a `KbError` and nothing is created, and
  where the hard link was made of a link, what is at `held` is checked and removed. The four accepted limits (L2, L4, L6, L7), the limit of twelve digits and the form of the median are in the
  README and the spec.
- **Tests, first.** Written before the corrections and seen to fail (a list median gave a `TypeError` or was accepted, a generation of ten digits was refused, the copy followed a swapped link).
  `test_weave` has 128 tests (126 before this increment's second look; 119 before E-A's first tests). `engine/.venv/bin/python -W error::ResourceWarning -m unittest engine.tests.test_weave`:
  **128 tests OK**; with plain `python3` they are skipped with a reason.
- **Second look.** The `reviewer` agent (read only) found **one blocking finding in the correction itself**, which was applied: `math.isfinite` raises `OverflowError` for an integer of about 400
  digits, which `json.loads` reads, so a forged median could still end in a traceback (confirmed by running it; the range is now tested first, with tests for 400-digit values in the median,
  the edges and `check_rows`). Applied also: the message at the limit named only the weave in place, but when the generation before holds the number removing that alone does not help (it names
  both, with a test of the generation before alone); the hard link made of a link is checked after it is made; `O_NONBLOCK` so that a pipe swapped in does not hold the lock while it waits for a
  writer (the test first passed by accident, because the alarm's `TimeoutError` is an `OSError` that the code turns into a refusal after ten seconds; it now fails when the copy waits); a
  descriptor that `fdopen` could not take is closed. The README and the spec say the limit of twelve digits and the form of the median.
- **Deliberate breaks.** 15, each caught (file restored byte for byte): a list accepted as a median; a boolean accepted; the median or the edges not checked in `check_rows`; the generation limited
  to nine digits; the last generation not refused at the start of a build or of a repair, or one too late; a link followed when the weave is copied; the descriptor not checked; the copy made with
  the name and not the descriptor; the range tested after `isfinite`; the message not naming the generation before; a link made of a link kept; a pipe waited for.
- **Not run.** Any run on the real library (Increment F); a security review of the corrections (the second look above was read only, and the first review's findings were these three, tested).
  Recorded, not changed: the hard link path is not tested against a symbolic link swapped in a real race on macOS (the code checks what it can: `lstat` before, `lstat` of `held` after). No push.

### Increment E (`theme-links status` and `repair`; committed)

- **Done.** `engine/kb/weave.py` has `status(index_root, cfg, store, now=None)`, `repair(index_root, cfg, store, now=None, force=False)` and, below them, the repair as a pure
  function `repair_links(...)`; `engine/kb/__main__.py` has `theme-links status` and `theme-links repair [--now]`, which open the store with `Store.open(write=False)` and take
  no option that names a model, a server or an address. `status` (no numpy, no model) says what waits: the themes of the vectors file that the weave has not processed and that
  have a summary vector and a method vector that count (`new`), those it processed whose generation or text hash is not what it recorded (`changed`: a book whose themes were
  made again is removed and added again), those no longer in the file (`gone`), and, apart, those that ended with no link (`themes_with_no_link`) and those with no usable vector
  (`left_out`), which never wait. A repair is due when the waiting themes are 5 percent or more of the themes in the weave, or the oldest waiting book was added 30 days ago or
  more (`REPAIR_SHARE` and `REPAIR_DAYS`, named in one place); a full build is needed, and the status says why, when more than 5 percent of the themes changed or are gone, when
  the vectors are of another model, dimension or prefix than the weave was made from, or when the weave has no edges. `repair` (needs numpy) drops the links of changed and gone
  themes, offers the candidates of the new and changed themes strongest first (a link takes a free slot or replaces the weakest link of a full slot if it is stronger, with a rule
  for a second link to one book in a band), then lets each theme that lost a link take its next candidates into free slots only; the band edges, the median, the slots and the cut are the
  weave's own; the result is written as a new file under the lock and renamed (the shared `_publish`, which `build` now uses too), the generation before is kept as it was, the file in
  place is never written over, and a weave that changed while the repair was worked out is refused. It is refused, with nothing written, when a full build is needed (also with
  `--now`), when nothing waits and nothing is gone, and when no trigger holds (unless `--now`).
- **Tests, first.** Written before the code and seen to fail (no `repair_links`, `status`, `repair`). `test_weave` now has 119 tests, 42 of them new in this increment (it had 77): `repair_links` against
  `reference_repair`, a plain-Python statement of the rule written separately in the tests, on 24 random scenarios (8 seeds, 1, 2 and 3 slots, themes gone, changed and new), with a smaller cut,
  blocks of 1 to 1000 and the themes in another order; two hand-worked cases (a new theme takes the slot of a weaker link; a changed theme with no partner now loses its old link); `status`
  right after a build, with one new theme of twenty (exactly 5 percent, due) and of twenty-one (below, not due), with 1 and 2 changed themes of twenty (5 percent is not more than 5 percent,
  10 percent is a full build), a theme whose text changed, a theme gone, a model that differs, the 30 days (29 days and 23 hours is not due, 30 days is), a book that cannot be read, dates that
  are not dates (ten forms, three of them with the form of a date), a theme with no link and a theme with no usable vector (neither waits), no numpy, the files unchanged, no model called;
  `repair` of a new book, of a changed theme, of a gone theme, of all three in a library of forty, the same result twice, the edges, the median, the slots and the pairs, the previous
  generation byte for byte and its inode, never written in place, a failed rename and a writer that got in first, no numpy, a refusal for nothing waiting, for a full build (also with
  `--now`), for a repair not due; and the two commands (the store opened read-only, the counts, `--now`, no option names a model). `engine/.venv/bin/python -W error::ResourceWarning -m
  unittest engine.tests.test_weave engine.tests.test_themevectors`: **230 tests OK**; with plain `python3` the 119 of `test_weave` are skipped with a reason.
- **Deliberate breaks.** 27, each caught in a final run after the last change of the code (three were missed at first and the tests were strengthened until they were caught: a changed theme's old links kept needed a case where the
  changed theme has no partner now, the median not kept needed a larger shift and a break on the written value, and the age of a book needed dates that are not dates), the files restored
  byte for byte: a theme with no link counted as waiting; the links of a changed or gone theme kept; a full build needed at more than 5 percent and a half, or at exactly 5 percent; the
  vectors model not compared; a full build not refused with `--now`; the age trigger a day early or late; the share trigger above 5 percent or at half of it; a full slot, or the floor,
  not respected by the repair; a theme that lost a link not refilled; the new file written over the file in place; a weave that changed during the repair not noticed; a changed theme not
  added again; the median or the edges not kept (three ways); the pairs not worked out again; changed themes not counted as waiting; a theme with no usable vector counted as waiting; a
  gone theme alone not repaired with `--now`; the age not read as a date, and an impossible date raising; a theme that lost its vectors not counted; the store opened to write.
- **Review.** The `reviewer` agent (read only): no blocking finding. Applied: a date that has the form of a date and is not one (month 13, year 0) made `status` and `repair` end in a traceback,
  and now gives no age (a test with three such dates); a theme that is unchanged but has lost its summary or method vector is dropped with its links and counted
  (`themes_lost_vectors`; the code that dropped it twice is now once); the help text says that `repair` needs numpy too; the spec says that "already linked" means the themes in the weave,
  no-link themes included, and records the repair's details (the replacement rules, the tie to the greater key, the second link to one book) as proposed, since they are the agent's choices.
  Recorded for the owner, not changed: **the 30 days count from the date a book was added, as the plan says, so a book that is old and whose themes were made again is due at once**
  (the date the themes changed is not recorded where the status can read it); the plan and the spec said "of the linked" and the code takes the share of all the themes in the weave, no-link
  themes included, as the README and "Built" say; a theme that lost its vectors alone does not make a repair due; `reference_repair` checks the numeric side of the code and shares its design
  (the two phases, "touched", the tie and same-book choices), so it would not catch a wrong reading of the rule.
- **Not run.** Any run on the real library (Increment F); the other engine modules' tests (nothing else changed besides the command line); a security review (not asked: the owner decided to
  ask once more over the whole weave module before Increment F). No push.

### Increment F (the weave over the owner's real library, and the owner's reading; run and read, recorded here; the figures in the spec's evidence follow with Increment G)

- **What was written to the real library (with the owner's word, "run it", 2026-11-13).** One build with `engine/.venv/bin/python -m kb theme-links build` from the config of the owner: the index root gained
  `weave-same-mechanism.sqlite` (1,794,048 bytes, mode 600, sha256 `ebbba8f45128d0e7f75e3d63bfc0c981d0d640e763b8668f30ccab0058e68fe3`) and an empty `weave.lock` (mode 600), and nothing else; the file of
  theme vectors was read only and its sha256 is the same before and after (`59fe64746b3c854aaad1b3324120a0827fa5baf691c8b247108970580d1f9229`); nothing was sent to any model; the build took 5.3 seconds.
- **The figures of the build** (the measurement of the spec in brackets): 1,913 themes in the vectors file, 1,805 processed and 108 left out (all 108 have no method or summary text), **7,966 links**, 9,263
  links by the slot rule without the floor [9,264], of which 1,297 [1,298] are at or under the median (14 percent), the edges 0.316, 0.378 and 0.447, the median 0.490, at most 12 links on a theme (599
  themes have 12), **52 themes with no link** [4 or fewer without the floor], 680 themes (38 percent) with no link in the wording-farthest band [391 without the floor], links per band 1,420, 1,964, 2,311 and
  2,271 from the farthest, the closeness of the links from 0.490 to 0.911 with a median of 0.649. The file is the one a build over a copy with 300 candidates gives (the links are equal).
- **Experiments on throwaway copies** of the file of vectors (private folder of the scratchpad, removed after; the report holds numbers only, mode 600, outside the repository:
  `weave-real-run-d86ef289da13.json`, sha256 `d86ef289da134ebf1f80d565d1cd013788985e8a2a3110cadfb89633a91fdb0e`; peak memory of the whole run 966 MB):
  - **The cut on the candidates (300 against 5,000, no cut at this size):** the same 7,966 links, 100 percent in common. The cut changes nothing on this library.
  - **Repair against a rebuild, with 18 books (200 themes, 189 of them usable) left out:** the build on the rest 7,074 links in 1,616 themes; status said a repair is due (189 themes waiting, 5 percent or more);
    the repair took 4.3 seconds, dropped 1,003 links and added 1,953, and gave 8,024 links, **81 percent of which are in the full rebuild** (82 percent of the rebuild is in the repair); mean closeness 0.6452 against
    0.6484, 52 themes with no link as in the rebuild, at most 12 links on a theme.
  - **Drift, repair in batches one after another** (from 125 books and 1,355 themes, five repairs of 6 to 15 books, 3.0 to 4.0 seconds each, one of them not due and made with `--now`): 8,179 links at the end,
    mean closeness 0.6399, 44 themes with no link, **69 percent of the links in the rebuild** (71 percent of the rebuild in them). One big repair of all the rest at once (525 themes waiting): 8,090 links, mean
    closeness 0.6425, 72 percent in common. So quality drifts a little with repairs (0.6484 for the rebuild, 0.6452 for one repair of 10 percent, 0.6425 for one of 30 percent, 0.6399 after five in a row), and a full
    build puts it back; both were made with the rules checked on reading.
  - **Books made again** (the generation of 71 themes in 5 books raised by one, 62 of them in the weave: 3.4 percent): the status says they wait, a repair is not due, and with `--now` it took 3.6 seconds and
    gave exactly the 7,966 links of before (the vectors had not changed, so the same links come back). With 164 themes (8 percent) made again, **a full build is needed and the repair is refused even with
    `--now`**, as the plan says.
- **What the experiments show about the design, for the owner.** (1) For themes that changed, the 5 percent that makes a repair due and the 5 percent above which a full build is needed are the same number:
  a repair is due by the share only at exactly 5 percent, so books made again are repaired only through the 30 days from the date the book was added, or by `--now`, and above 5 percent the answer is a full
  build, which is cheap (5 seconds at this size) and makes the weave as a rebuild does. (2) The farthest band is sparse after the floor: 38 percent of the themes have no link in it. (3) A weave repaired many
  times drifts a little from a rebuild, in the direction of weaker links, which a full build corrects.
- **The owner's reading (step 4), 2026-11-13,** after the links of three themes and of seven random ones were shown with the method text of both sides (the printout is outside the repository,
  mode 600, sha256 `034369d167c42a030da59a2dc792d92e167f969cb98680d4dee14df7833354d9`): "Keep the farthest band sparse. Keep weak links available for exploration. Treat the median as a
  provisional filter." So nothing changes in the slot rule or the floor; the spec's floor rule records the reading. The agent's own reading, given to the owner and not the owner's: closeness is
  a weak proxy for the same mechanism (ten themes read; the strong links are mostly in the middle and nearest bands; many method sentences are short and generic).
- **Not yet done.** The Result of the whole plan; the two decisions about a limit for a full build and about building again (Increment G, drafted, waits for approval). No push.
