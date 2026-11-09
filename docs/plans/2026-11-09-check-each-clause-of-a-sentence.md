# Check each clause of a grounded sentence

Status: Proposed
Created: 2026-11-09
Candidate: cards#card-clause-check
Specs: docs/specs/card.md

## Goal

A sentence of the summary or of a neutral field is marked `stated` only if each clause of it is supported by the notes it cites. A
true sentence with an unsupported extra clause is cut back to the clauses that are supported, or dropped when no clause that can
stand alone is left. The change is measured on a new blind sample, against the cards of the plan `2026-11-09-ground-the-summary-and-neutral-fields`
made of the same books, and the owner decides whether the library is carded again.

The plan is done when the check by clause is in the engine, a run on the books of the earlier measurement has been labelled and
compared with the cards made with the check of whole sentences, and the owner has decided.

## Scope

- A check of the sentences of the summary and of the five neutral fields by clause: the second model that already checks a sentence
  against up to two cited notes is asked, for each sentence, for its clauses (copied from the sentence, in order) and one verdict for
  each; the engine refuses a reply whose clauses do not rebuild the sentence.
- The rule for a sentence whose clauses are not all supported: it is cut back to the part that stands, that is, to the end of the
  last supported clause, if the clauses before the first unsupported one are supported and form a sentence of at least four words;
  otherwise it is dropped. A cut sentence keeps its mark and its notes, and the report counts it.
- A first, read-only step that finds out, on the labelled sample of the earlier plan, what kind of error the sentences marked
  `stated` and judged unsupported are, and whether the check by clause would have caught them without dropping the supported ones.
- A live run on the books of the earlier measurement, one blind sample labelled by a strong model, the owner's calibration labels,
  the comparison, and the owner's decision.
- **A revision of the card spec,** in these statements and no others: in "Non-goals", the statement of what the engine does check
  (a sentence of the summary or of a neutral field is also checked clause by clause and may be cut back); and in "Making and regenerating a card",
  the statement of what the second model says for each pair (for a sentence, one verdict for each clause). The owner's approval of this
  plan is the owner's word for this revision, which changes what the spec says about the card and is the change-direction checkpoint.
  No text of the spec is changed before the approval, and the revision is made in increment B and shown in the commit.

## Non-goals

- The topics, key ideas and caveats. They were 85 to 92 percent supported in the earlier evidence and are checked as before; if the
  comparison shows they need the check by clause too, that is a later plan.
- Letting a neutral part be kept as a marked inference, and any change to how many sentences the card model is asked for. The
  empty parts that the earlier plan found (needs 4 of 9 cards, problem 2, limits 2) are not what this plan fixes; it records whether
  cutting back makes them worse.
- A cloud model as a checker or a card writer. A cloud model labels the sample and does nothing else.
- A change to the sample method, the labels or the accuracy count, and rewriting existing cards: a new card is a new generation.
- A fix for the card model's wrong-length lists (`cards#card-format-resilience`) and search by meaning.

## Assumptions and constraints

- **The evidence for the plan** (held outside the repository; the Result of `2026-11-09-ground-the-summary-and-neutral-fields`):
  on nine books, 45 sentences of the summary and the neutral fields were kept as `stated` by the check of whole sentences, and a
  cloud labeller who saw the item and the five best passages of the book judged 21 supported, 8 inference and 16 unsupported
  (36 percent). The labeller sees only five passages, while the check saw whole notes, so some of the 16 may be supported elsewhere
  in the book; the first increment finds out how many. The labels are those of one cloud model; the owner has not yet labelled the
  15 calibration items of that sample, so the labeller's agreement with the owner is not measured for it (on an earlier sample it was
  10 of 14).
- **This plan is narrower than its roadmap candidate.** `cards#card-clause-check` speaks of "an item" and its boundary is splitting an
  item into clauses; this plan does it for the sentences of the summary and the neutral fields only, because that is where the
  measured error is (36 percent of the kept `stated` sentences judged unsupported, against 85 to 92 percent supported for key ideas and
  topics in the earlier evidence) and because the same reply shape and cut rule do not fit a one-line topic. A plan that is
  `Completed` makes its candidate complete, so the owner's approval of this plan is the owner's acknowledgement that the candidate is
  met for the sentences and that the lists are deferred (see Deferred work); if the owner wants the candidate met for every item,
  the plan gets an increment that extends the check to the lists before it is approved. The roadmap file is not edited here.
- The commonest error of the second look of the grounding run was a true statement with an unsupported extra clause. This plan tests
  whether that is what the 16 are, and does not assume it.
- The existing machinery is reused: the notes with verified quotes, the pairing of a sentence with up to two cited verified notes,
  the check job `card-check`, the marks, the journal of calls and the queue. A change to the check prompt or its reply shape changes
  the job's version, so a journal made before is stale and is made again.
- A cut sentence is a true prefix of the card model's sentence, so no new text is written by a model; the display and the grounding
  record keep their shape. The sentence is cut at the end of a clause, so its last character may need a full stop, which the engine
  adds; nothing else is changed.
- Time and calls are spent on accuracy, as the owner has said; a card is never padded to reach a size. The live run, the labelling
  by a cloud model and the owner's labels each need the owner's word.

## Completion criteria

1. A record of what the 16 unsupported `stated` sentences are, by their labels' notes, and of what the check by clause does to them
   and to the supported ones on the same pairs, exists in the Result.
2. The check by clause is in the engine: a sentence is kept as it is only if every clause is supported, is cut back by the rule
   above if its first clauses are, and is dropped and counted otherwise; a reply whose clauses do not rebuild the sentence is
   refused; and the report counts the sentences cut and the clauses lost.
3. The cards of the nine books exist in the form of the earlier plan and in the new form, a blind sample with the same number of
   items from each form of the same books has been labelled, the owner has labelled a calibration subset of at least ten items
   and the agreement is computed before the cloud labels are used, and the numbers are recorded for the summary and the neutral
   fields, form against form.
4. The Result records the numbers, the limits and the owner's decision.

## Increments

### Increment A — What the unsupported sentences are, and what a check by clause does to them

**Outcome:** the owner and the plan know, from the labelled sample of the earlier plan, how many of the 16 unsupported `stated`
sentences have an unsupported clause that a check by clause could catch, and whether the check by clause keeps the supported ones.
**Dependencies:** none.
**Affected areas:** files outside the repository (a script, its log), and the plan's Result. No tracked file other than the plan
changes.
**Steps:**
1. Read, from the labelled file of the sample and its key, the 45 sentences of the summary and the neutral fields that the new form
   kept as `stated`, with their labels and the labeller's notes. Put each of the 16 unsupported ones in one kind by its note:
   an extra clause that no shown passage states; the sentence loosely related to the note that was cited; the sentence stated
   elsewhere in the book (the note's quote, read against the whole book, supports it); or a label that is too strict. Count them.
2. Find out whether the notes of those 45 sentences can be had again (the journals of the nine books, if they are still kept, or the
   notes' points and quotes). If they cannot, say so and use the quote kept in each sentence's grounding record, and record that
   the probe then shows one note of the two.
3. Tell the owner what will be called (the check model of the owner's config, with the new prompt, on the 45 sentences, 3 to 5 calls
   of ten, nothing leaving the owner's network) and wait for the word. Then run the check by clause on the 45 pairs as a read-only
   probe, with the prompt and reply shape that increment B would use, and count: of the 16 unsupported, how many have at least
   one clause judged `partly` or `no`; of the 21 supported, how many have every clause judged `supports`.
4. Record the counts. If fewer than a third of the 16 have an unsupported clause by step 1 or fewer than half are caught by step 3,
   or if more than a quarter of the supported ones would be cut or dropped, **stop and report before increment B**: the check by clause
   does not address what was found, and the owner decides what the plan becomes.
**Verification:** the probe read as written, with its counts. No test runs, since no code of the repository changes.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-09-check-each-clause-of-a-sentence#A`, which holds the plan's Result.

### Increment B — The check by clause in the engine

**Outcome:** the engine checks the sentences of the summary and of the neutral fields by clause and cuts or drops them by the rule
above; the card spec and the engine README say so.
**Dependencies:** A, and its count not having stopped the plan.
**Affected areas:** `engine/kb/cardmake.py` (the check job and its version, the prompt, the rule that turns verdicts into kept,
cut and dropped sentences, the report), the spec statements named in the scope, `engine/README.md`, and the tests of those.
**Steps:**
1. Write the tests first and see them fail: the reply shape for a sentence (its clauses and one verdict each, of the same count); a
   reply whose clauses do not rebuild the sentence refused; a sentence kept whole when every clause supports; a sentence cut at the
   last supported clause when the clauses before the first unsupported one are supported and make at least four words; a sentence
   dropped when its first clause is unsupported, when the cut would leave fewer than four words, or when no clause is supported; the
   full stop added to a cut sentence; the notes shown, the mark and the quote kept as before; the report counting the sentences cut
   and the clauses lost; and the list items checked exactly as before.
2. Change the check job (`card-check`, next version), the prompt (it names the clause and asks for the clauses copied from the sentence
   in order, and for one verdict each) and the rule that builds the kept sentence from the verdicts. Leave the list items, the pairing,
   the grounding record and the display as they are.
3. Revise the spec in the two statements named in the scope and the engine README in the paragraphs on the check and on the report.
4. Run the verification, then a review by the `reviewer` agent, and record the Result.
**Verification:** `python3 -m unittest engine.tests.test_cardmake engine.tests.test_card engine.tests.test_cardstate
engine.tests.test_cardqueue engine.tests.test_models engine.tests.test_catalog engine.tests.test_cardsample`, and `wb run code-work check`.
Deliberate one-line breaks of the new rule, each caught by a test. Nothing wider is named, since no other module reads the check.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-09-check-each-clause-of-a-sentence#B`.

### Increment C — A live run, the labelled sample and the comparison

**Outcome:** the owner has numbers on whether checking by clause makes the sentences of the summary and the neutral fields more
accurate, at what loss of content, and has decided.
**Dependencies:** B, and the owner's word on the books, on sending the sample to a cloud model, and on the calibration labels.
**Affected areas:** the owner's library (new card generations for the books named), files outside the repository, and the plan's
Result. No tracked file other than the plan changes.
**Steps:**
1. Tell the owner what will be done: the nine books of the earlier measurement are carded again with `cards-queue` and `--again` as
   the next generation (about 32 notes calls, 10 card calls and the checks, as the last run), the catalog is rebuilt at the end of
   the run so that search shows the new cards for those books, and the labelling sends items and passages to a cloud model. Wait for the
   word.
2. Make the cards, and record the sentences asked for, kept, cut and dropped, the clauses lost, the cards that are partial, the
   parts that ended empty and every failure. If a part ends empty on more cards than in the earlier run by two or more, **stop and
   report** before the labelling.
3. Draw one blind sample from both forms of the same books: `card-sample` over the generation of the earlier plan and the new one, with
   the same number of items from each (about 90 each), so that the book and the kind of item are matched by construction. Have a
   strong model label it without the generation or the form, and compute the owner's agreement on a calibration subset of at least
   ten items before the cloud labels are used. If the owner does not label, or the agreement is below three in four, the
   comparison is reported as the model's labels alone and the Result says no decision is supported.
4. Compare, form against form, the supported, inference and unsupported shares of the summary and the neutral fields (all six
   together and each apart), the share of the sentences kept as `stated` that are judged unsupported (36 percent in the earlier
   measurement), and the words and sentences lost. The difference between two runs of the same form on the same book was about 12
   points in the earlier measurement, and a difference smaller than that is not a finding.
5. Write the result in the plan, naming no personal question, path or machine, with the limits and a provenance line, and a
   recommendation: use the new form if the share of kept `stated` sentences judged unsupported falls from 36 percent to 21 percent
   or less, the supported share of the six fields does not fall, no part ends empty on more cards than in the earlier run by two or
   more, and the owner agrees with the labels. Record the owner's decision, including whether the library is carded again with
   `cards-queue`.
**Verification:** the runs of steps 2 to 4 read as written, and the tests of increment B once more.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-09-check-each-clause-of-a-sentence#C`, which holds the plan's Result.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later increment changed its inputs. After C, rerun
`python3 -m unittest engine.tests.test_cardmake engine.tests.test_card engine.tests.test_cardstate engine.tests.test_cardqueue
engine.tests.test_models engine.tests.test_catalog engine.tests.test_cardsample engine.tests.test_setup` and `wb run code-work check`;
nothing wider is named, since no other module reads the check.

## Risks and sensitive actions

- **The check by clause may not address what was found.** The 16 may be loosely related notes or support elsewhere in the book,
  which a clause check does not catch. Increment A measures this on the existing labels before anything is built, and stops the
  plan if it is so.
- **Cutting back can leave an empty part.** The card model writes one sentence for almost every neutral part, so a dropped sentence
  empties the part; the cut rule keeps a supported first clause, and the comparison counts the parts that end empty. A cut sentence
  can also read as less complete; the words lost are reported.
- **A larger reply for the check model,** which has to copy the clauses and give a verdict for each; a reply of the wrong shape is
  refused, and the check is retried as it is now. The report counts the failures.
- **A new check version changes the journal.** The job version is in the journal's header, so a journal made before is stale and its
  book is planned again.
- **Book text and notes go to the owner's local models,** as for every card. The labelling sends items and passages to a cloud model
  and needs the owner's word. The probe of increment A sends nothing out.
- **The catalog is rebuilt at the end of the live run,** so search shows the newest card for the books named; the earlier
  generations are kept, and nothing is deleted.

## Review record

- Reviewer: a second model (gpt-5.6-terra) through the project's review engine, on 2026-11-09, round 1 of 3. Verdict: changes needed,
  one finding, major.
- Applied (R1-F1): the plan covers the sentences of the summary and the neutral fields, and the roadmap candidate speaks of every
  item. The plan now says so in its assumptions, with the reason, and that the owner's approval is the acknowledgement that the
  candidate is met for the sentences; the lists stay deferred.
- Rejected: none.
- Left for the owner: whether to meet the whole candidate, which adds an increment for the lists before the approval, or to approve
  the plan as it stands.

## Deferred work

- The check by clause for topics, key ideas and caveats, if the comparison shows they need it.
- Letting a neutral part be kept as a marked inference, or marked "not stated", for the parts that end empty.
- Saving the reasons for each drop in the queue's report, so that a run can be read without reading the cards.
- Putting back the earlier generation of the nine books in search, which needs its own plan.

## Result

Empty until work starts.
