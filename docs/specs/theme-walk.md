# The walk: offering an agent themes it did not ask for

Status: Draft

Every decision below is the drafter's call (marked **[my call]**) unless it names the owner, in which case it points to where the owner made it. Nothing here is agreed until the owner says so. This revision follows a
review of the first draft from the standpoint of a research agent that uses the walk in a loop (the "Review from the agent's side" section).

## Scope

How a research agent uses the weave of same mechanism (`weave.md`) at query time, over several rounds: it asks with a question, gets leads (themes it did not ask for, each with the route that reaches it, the reason, and
whether an ordinary search of the same question would also have returned it), chooses some to follow further and some to drop, and asks again without being shown the same leads twice. This spec states the command,
the scale from narrow to wide, what a step counts, how leads are grouped, ranked and shown, what the agent can pass back, and how the output is kept safe. It does not cover how links are made or kept (`weave.md`), how
themes are made (`theme.md`), or how the ordinary search works (`themevectors`, the search by meaning).

## Non-goals

- Judging whether a lead is novel, useful or true. The agent decides; the walk judges nothing for it (the owner, `weave.md`, "Problem").
- Remembering anything between calls. The command keeps no state and writes nothing: the agent carries what it has seen and chosen, and passes it back.
- The other kinds of weave (same problem, fit together, alike, builds on, incompatible, disagrees). A step may use any of them later; only *same mechanism* is used now.
- A judge's label on a link ("related or better"). It is a possible later candidate and not part of this design.
- Changing how a result is marked untrusted, or the cleaning of any text of a book.
- Any call to a model other than the one that already embeds a question for the ordinary search.
- Building combinations of themes (`weave.md`, "A digest of connections"): the walk offers leads and routes only.

## Review from the agent's side

The first draft was a single call, question in and a ranked list out. For an agent that iterates it had these faults, each of which this draft answers: no way to continue from a lead (so "go further from this one"
meant asking the question again and getting the same list); no way to say what had been seen (so round two repeated round one); no stable handle on a lead; strong and weak leads in one ranking (an agent spends effort
on a few solid leads and samples a few wild ones, and the evidence says the two behave differently); a reason made of two short, often generic method sentences; no sign of convergence (a theme reached by several
routes); half a novelty signal (the ordinary-search flag, not whether the book was ever touched); silence when a start has no links or everything reached is already known; one question only (the agent splits a problem
into sub-problems and restates it in other words); and output not shaped for a program to read.

## Assumptions and constraints

- The weave of same mechanism exists, is current, and is read as `theme-links show` reads it (`weave.read`, every row checked); a weave that is missing or not the engine's is refused, and one that is out of date is
  said to be (`weave.md`, "Built").
- A link joins two themes of different books and carries its closeness, its wording closeness, its band (0, the farthest in wording, to 3, the nearest) and the matched texts. A theme has at most 12 links, at most 3
  in a band and at most one to a book in a band (`weave.md`, "The slot rule"). 52 of the 1,805 themes of the owner's library have none.
- The owner's reading of the first weave (2026-11-13): keep the farthest band sparse; keep weak links available for exploration; treat the median floor as a provisional filter (`weave.md`, "The floor of strength").
- The agent sets a weighting on a short named scale and a distance in steps; the default leans wide; noise is expected and accepted if each item is cheap to skim (the owner, `weave.md`, "Problem").
- Whether an ordinary search would also have returned a theme is worked out when the agent asks, from its question, and is shown with each theme; it is not stored in a link (the owner, `weave.md`, "Using the weave at
  query time").
- **Visibility.** The weave spec requires that a link with a private theme at either end is invisible to a guest, and so are the counts and hints derived from it, and that links are computed and returned over the
  visible subset of the token (`weave.md`, "Privacy and safety"; `shelf.md`). The engine has no guests, tokens or shelves yet, so today the visible subset is every theme of the library and the walk is run by the
  owner's own agent. The walk is written for the day it is not: **the selection takes the visible set of themes as an input** (today, all of them), so that the starting themes, the ordinary set, the routes, the
  leads, the header's counts, `reached_by` and the book flag are all computed over it and over nothing else.
- The ordinary search is the search by meaning of themes with its per-book limit (`themevectors.search`, default two themes of a book). Every text of a book is cleaned and marked untrusted as the search does it.

## What the evidence says about the weave (measured; `weave.md`, "Evidence")

On the first weave over the real library, judged by two local models and rated blind by the owner on 20 pairs: the share of links called related or better rose with closeness; it was highest in the band nearest in
wording; a theme's first three links by closeness were called related or better about twice as often as the rest; within the three farther bands the rise sat in the highest closeness tercile, from about 0.66
(exploratory, chosen after the other tables were seen); the gap between closeness and wording closeness was not a clean signal; the method sentence of a theme is often short and generic. Few links were judged
*same mechanism* (18 and 4 of 269). These figures are from 30 themes, one prompt and one order, and say nothing about novelty. They are why the walk separates solid leads from wild ones, and why it shows more than
two method sentences as the reason.

## Behavior

### The command and what the agent can pass back (**[my call]**)

`python3 -m kb theme-walk --question "<text>" [--question "<text>" ...] [--from REF ...] [--seen REF ...] [--drop REF ...] [--level narrow|medium|wide] [--steps N] [--limit M]`

- **`--question`** (once or more): the agent's words, so that it can state the problem, a restatement of it in abstract terms, and each sub-problem. The starting themes are the top 5 themes of each question's ordinary
  search that have at least one link, and the **ordinary set** is the first 30 results of all the questions together. A question that finds nothing is said to have found nothing.
- **`--from REF`**: continue from these themes (leads the agent chose) in place of the search's starting themes. The questions are still needed, for the ordinary set. A REF names a theme and not a route: the
  command does not know how the agent came to it, so the themes of that route that the agent should not be shown again are the ones it passes in `--seen` (every theme of a lead's route was shown to it in the
  lead's `route`, so it has them). The command itself only guarantees that **a route never visits a theme twice** and never returns to a `--from` theme.
- **`--seen REF`**: themes the agent has been shown or does not want shown again (the leads, and the themes of their routes). They are never offered, and are not walked through unless they are also given with
  `--from`.
- **`--drop REF`**: themes whose neighbourhood is a dead end: they are neither offered nor walked through, so that a hub or a bad lead does not bring its links back.
- A **REF** is `book_id/version_id/theme_id`, the weave's own key, and is what every lead carries. A REF is validated as an identifier and nothing else (never a path); a REF not in the weave is reported as unknown and
  ignored, with how many.
- **[my call]** The command is stateless and deterministic: the same arguments, weave and vectors give the same leads in the same order. The agent iterates by passing back `--seen` (every lead it has read) and
  `--from` (the ones it follows).
- **Defaults [my call]:** `--level wide` (the owner's "leans wide"), steps as the level says, `--limit 12`. `--limit` is a whole number from 1 to 20 (the cap on a call's output, below) and a value outside that is refused, as the search refuses a limit out of range. The header
  says which were used.

### The scale (**[my call]**; the names, the counts and the bands are guesses to tune on use)

| level | steps | which links of a theme are followed |
|---|---|---|
| narrow | 1 | the theme's links in the two nearest bands (2 and 3), strongest first, at most 3 per theme |
| medium | 2 | all four bands, strongest first within a band, at most 3 per theme at the first step and 2 at the second |
| wide (default) | 3 | all of the theme's links, at most 12; at the second and third step at most 2 per theme, taken from the farthest bands first |

- **[my call]** A step is one link of the weave of same mechanism. A route is the starting theme and the links used. A level bounds the distance and how many links of a theme are followed; `--steps` may lower the
  distance and never raise it above the level's. For an agent that wants to iterate one hop at a time, `--steps 1 --level wide` follows every link of the chosen themes once.
- **[my call]** `narrow` behaves like an ordinary search in what it offers (the roadmap's "a narrow setting behaves like an ordinary search"): the flags below say how much of it an ordinary search already returned.

### Two lanes (**[my call]**)

An agent spends effort as a portfolio: a few leads it can follow with some confidence, and a few it samples for the chance of something it would not have thought of. The leads are therefore in two lanes, never
blended into one ranking:

- **Follow-through lane:** leads whose route's weakest link has closeness at or above a threshold (**0.66**, from the exploratory cut of the evidence; provisional and tuned on use), ordered by the closeness of the
  weakest link, highest first.
- **Exploration lane:** the other leads, ordered by the band of the last link, the farthest first, then by the closeness of the weakest link, highest first. A weak link is offered here at its rank and is never dropped
  (the owner, 2026-11-13).
- Each lane has its share of `--limit` (**[my call]** two thirds and one third, rounded up for the first); a lane with fewer leads gives its places to the other, and the header says how many each held.
- Within a lane, leads **not in the ordinary set** come before those that are, then the order above, then the REF, so that the order is repeatable. At most two leads from one book and at most three reached from one
  starting theme in a lane, so that one book or one hub does not fill it; the count of leads held back is said.
- **[my call]** One lead per theme: its best route, which is the route with the highest weakest link, then the fewest steps, then the smallest sequence of the REFs of the themes of the route compared as text
  (so that the choice does not depend on the order in which routes are found). A starting theme, a `--seen` theme and a `--drop` theme is never a lead.

### One lead (cheap to skim, and enough to decide) **[my call]**

- `ref`; the theme's title and type and its book's title (cleaned); its neutral **problem**, **method**, **needs** and **provides** (what it gives), in the domain-neutral words of the theme (its fields `neutral.problem`, `neutral.method`,
  `neutral.needs` and `neutral.provides`; the `limits` stay with the theme and are read when the agent opens it), each cleaned and carrying its mark, `stated` or `inferred` (one of two fixed words taken from the file, never from text), and its one-line summary; the theme's `citation`, as a search result carries it;
  the `lane`.
- `route`: the chain from the starting theme, each step with the theme's ref and title, the closeness to two decimals, and the band's name (so the agent sees how far in wording each step went).
- `why`: the matched method texts of the **last** link, both sides, cleaned; and `explain`, the exact `theme-links show` arguments for the last link, so that the agent can open the whole route's matched texts when
  it chooses to (one step at a time, not in every item).
- `novelty`: `ordinary_set` (the rank at which an ordinary search returned it, or "not in the first 30"), and `book_in_ordinary_results` (whether any theme of its book is among the ordinary set), so that the agent can
  tell a new theme of a known book from a theme of a book the search never touched.
- `reached_by`: the number of different routes (to the depth of the level) that reach it; a theme reached by several is a convergence the agent may weigh. It is shown and is not used in the order.
- `weak_link`: the weakest link's closeness and band, as a number the agent can read, since the walk decides nothing.

### The header, and what it says when little is found (**[my call]**)

The questions; the level, steps and limit used; the embedding model and whether a query prefix is used, and when the vectors were built (as the search reports them); the starting themes and the ones skipped for having no link; how many themes were reached in all, by level, so that the agent knows what widening would add; how many
are in the ordinary set; the leads in each lane and how many were held back and why (the book limit, the starting-theme limit, `--limit`, `--seen`, `--drop`); the weave's generation and whether it is out of date;
and that the leads are leads and not findings. When a start has no links, or everything reached is in the ordinary set or `--seen`, it says so and says what would widen it (a higher level, other questions,
`--drop` removed), and never returns an empty answer without a reason.

### Format and size **[my call]**

One JSON object (as the other commands print), the text fields between the untrusted-text markers the search uses and the fields of the lead as named above, bounded: at most 20 leads (`--limit` cannot ask for more), each
lead at most about 1,500 bytes, the whole at most about 40 KB, and a REF list of at most 200 in `--seen` and `--drop`.

### Safety **[my call]**

Everything the command computes or counts (the ordinary set, the starting themes, the routes, the leads, `reached_by`, `book_in_ordinary_results`, and every number of the header) is over the visible set of the caller
and never over the whole library, so that no count or flag depends on a theme the caller cannot see (`weave.md`, "Privacy and safety"); today the visible set is the whole library. Every text of a book or a card in the output is cleaned and withheld whole if it holds the words of an untrusted-text marker, as `theme-links show` does. The questions are the agent's and are shown as given,
cleaned. The command reads the weave and the file of theme vectors read only and writes nothing; it takes no option that names a file, and a REF is an identifier and never a path. It embeds the questions with the
embedding model of the config, as the search does, and calls no other model.

## Built (what exists, and the readings the owner is asked to confirm)

`python3 -m kb theme-walk` is built (`engine/kb/walk.py`, `engine/README.md`; the plan `2026-11-13-let-an-agent-walk-from-themes-along-the-links`, Increments A to C). It reads only, keeps no state, needs no numpy and sends only each
question to the embedding model, as `theme-search` does. It is a Draft still: the owner has not run it on the library (Increment E), and the trial that tunes the numbers is the separate candidate `extrapolation-trial`. Where this
spec was open or silent, the code reads it as follows. **These readings decide which leads exist, and are the owner's to confirm or change.**

- **The level table.** `narrow` follows a theme's links in bands 2 and 3, the strongest closeness first, at most 3, one step. `medium` follows links in every band, the strongest closeness first *whatever the band* (the table's
  "strongest first within a band" could be read band by band), at most 3 at the first step and 2 at the second. `wide` follows all of a theme's links (at most 12) at the first step and, at the second and third, two links, the
  farthest band first and then the strongest. A tie in closeness goes to the key of the partner.
- **The cap on a theme's links** applies to the links that can still be followed: a link to a seen, dropped, starting or on-route theme does not use one of the places, so a round that passes back what it has seen finds new leads.
- **A route** never visits a theme twice, never passes through a starting, `--seen` or `--drop` theme, and never joins two themes of one book. The threshold of the follow-through lane is the integer 660,000,000 billionths, at or
  above. When two links of a route are equally weak, the weakest band is that of the first. `reached_by` counts the routes found within the level after the caps on a theme's links.
- **The ordinary set** is the first 30 *themes of the merge* of all the questions by best rank (not 30 from each question), the rank being a theme's place among the visible results of the question where it comes first. The
  starting themes are the first 5 results of each question that have a link, the ones passed over being counted in the header.
- **Numbers the spec did not state:** a call asks at most **5 questions** (`MAX_QUESTIONS`), continues from at most **20** themes (`--from`), and takes at most 200 REFs in each of `--seen` and `--drop`; the search is asked for a
  full page of 50; a lead's texts are cut to 140 characters a part and 100 a title; the printed output is kept under 60,000 bytes by leaving out the last leads of the longer lane (`held_back.size` says how many).
- **Format and size: the built numbers replace the ones above.** A lead is about 2 KB (the tests assert under 2,600 bytes, with texts as long as a theme may be) and not about 1,500, because it carries the four neutral parts, the
  summary and the matched methods; the whole output is kept under 60,000 bytes *as it is printed* (indented) by leaving out the last leads of the longer lane. A text outside ASCII is escaped at six bytes a character, so a library in another script
  has fewer leads on a page, and the header says how many were left out; measured, a lead with the longest texts a theme may have is about 2.5 KB, and twenty of them come to about 55 KB, not 40.
- **Names that differ from the spec's words.** `novelty` has `ordinary_rank` (the rank, or null when the theme is not among the first 30) and `book_in_ordinary_results`; the header's `defaults_used` lists only what the agent did not
  give; when `--from` gives no theme of the weave the note is `from_refs_unknown` and not `no_starting_theme`, with its own hint.
- **The output.** One JSON object: `warning` (first; null unless the weave is out of date), `header`, `follow_through` and `exploration`. A lead carries its `ref`, its `lane`, titles, `citation`, a marked `text` (title, summary and the
  four neutral parts, each part with its `stated` or `inferred` mark taken from the file), the `route`, `why` (the methods of the theme before it and of itself, marked), `explain`, `novelty`, `reached_by` and `weak_link`.
  `lane_shares` (the places a lane is given) and `lane_counts` (what it shows) are different numbers, and `held_back` says how many leads were left out for a book, a starting theme, the limit, and how many themes were left out
  for being `--seen` or `--drop`.
- **A known limit (criterion 9).** The search keeps its own two themes of a book and its page of 50 over the whole library before the walk drops the themes outside the visible set, so with a visible set smaller than the library a
  hidden theme could still take a book's place in the page. The visible set is the whole library today, so nothing is affected; the search itself will need the visible set when guests exist. A REF that names a theme outside the
  visible set is counted as unknown, in the same words as one not in the weave.
- **Not built:** the skill that tells an agent how to use the walk (Increment D), the read-only run on the owner's library (Increment E), and the agent trial (`extrapolation-trial`).

## Acceptance criteria

1. For a question, the command returns starting themes and leads, each lead with a route of at most the level's number of steps in which every link is a link of the weave and every theme is of a different book
   from its predecessor; no lead is a starting, `--seen` or `--drop` theme.
2. At `narrow` no route has more than one step and no link of a band below 2; at `medium` no more than two steps; at `wide` no more than three; `--steps` never exceeds the level's.
3. The same arguments, weave, vectors and **embedding configuration** (the model and the query prefix the config names for the search) give the same leads in the same order, provided the embedding model returns the
   same vector for the same text; the command writes nothing and keeps no state. As the search does, it refuses a file of theme vectors made for another model, dimension or document prefix than the config's, and
   a reply for a question from another model than the one that made the vectors, before any lead is made; so a change of the configuration is a refusal and never a different answer under the same header.
4. **Iteration:** passing a call's leads and the themes of their routes back as `--seen` gives a second call with none of them; `--from` a lead gives leads reached from it, none of them a `--from` or `--seen`
   theme, and no route visits a theme twice; `--drop` a lead removes it and what is reached only through it.
5. Every lead carries the ordinary-search flag and the book flag, computed from the questions; within a lane, leads not in the ordinary set come before those that are.
6. The leads are in two lanes by the threshold, each with its share of the limit, never blended; a lane that is short gives its places to the other and the header says so.
7. A start with no links, or a call in which everything reached is known, says so and says what would widen it.
8. A text of a book or a card holding the words of an untrusted-text marker is withheld whole; a deliberately hostile theme text, title, question or REF does not change the structure of the output, and a REF
   that is not an identifier is refused.
9. **Visibility:** with a visible set that leaves out some themes (a test fixture; the engine has no guests yet), no starting theme, route, lead, count, `reached_by`, flag or ordinary-set rank depends on a theme
   outside it, and a link with a hidden theme at either end is never followed; a deliberate break that computes any of them over all themes is caught.
10. A weave that is missing or not the engine's is refused with the command to run; one that is out of date is said to be; the command needs no numpy.
11. **An agent trial (the roadmap's `extrapolation-trial`, run with this session's agent standing in for the research agent and the owner reading):** for two or three problems the owner chooses, an agent runs the
    walk for several rounds, passing back `--seen` and `--from`, and the owner reads what it did. The written result **reports, for each level and each step distance used, the share of offered leads that an ordinary
    search of the agent's own question would already have returned** (the roadmap's finish line for `extrapolation-trial`), and may add how many leads were new to the agent (not in the ordinary set of any of its
    questions, not seen before) and how many the owner, reading them, would have followed; the walk judges neither.

## Open questions (for the owner)

- The names, the counts and the bands of the three levels in the table, and whether three steps at the wide level is too far to skim.
- The threshold of the follow-through lane (0.66, from an exploratory cut) and the shares of the two lanes (two thirds and one third).
- Whether the best route is the one with the highest weakest link, or the shortest.
- Whether the ordinary set should be 30 results and the starting themes 5, per question.
- Whether `reached_by` should one day weigh in the order (it is only shown now).
- Whether the judged label of a link (a possible later candidate) should wait until the owner has read the walk's output.

## Governing decisions and references

- Decisions: `docs/decisions/2026-11-13-the-engine-may-use-numpy.md` (the walk itself needs no numpy).
- Specs: `weave.md` (the links, the slot rule, the floor, the evidence), `theme.md` (themes), `library.md` (where files live), `models.md` (the embedding model of the search).
- Roadmap: `docs/roadmaps/theme-weave.md`, the candidates `theme-walk` and `extrapolation-trial`.
