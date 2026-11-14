# The shelf schema is our own list, built from OpenAlex and the Library of Congress, with finer shelves for OpenAlex topics

Status: Accepted by Robert Ziegler <25854477+rziegler42@users.noreply.github.com> on 2026-11-14

## Context

`docs/specs/shelf.md` (a draft) says a shelf is an interest area the owner defines, flat and not a classification, with a scope
statement and rules, and that a classification such as OpenAlex's is only an optional label (a "bucket"). It also says shelves can be split or
merged by a reshelving list the owner approves. The fetch engine (the crawler and its seeding) is designed there and is not built.

On 2026-11-14, in the brainstorm for the fetch engine, three things came together. The walk trial
(`docs/plans/2026-11-14-try-the-walk-on-the-owners-problems.md`) gave thin leads for the 3D-printing problem (the agent's impression, from two rounds)
and an "unclear" answer on whether the wide walk adds anything over an ordinary search; **the trial did not establish whether the cause is the
library's coverage or the method**. The owner's own judgement, which this record rests on, is that the library holds too little to judge whether novel
concepts are findable: it holds 175 books, and the design's own expected scale is hundreds of thousands. And the owner's concern that a library grown only
around the owner's stated interests limits the novelty it can offer means that growing it around those interests alone is not enough. The owner asked how the engine should decide what to fetch and how to know what the
library holds, and worked out the shelving scheme below.

## Decision

**What the owner decided in the brainstorm (their own words, where given):**

1. A shelf is a place in a **fixed schema**, kept as a **file in this project** (for example JSON). The shelving exists to focus the fetch engine on
   a topic and to know how many books the library holds on it. Because the schema is fixed, a book is not reshelved when the library grows;
   a book is matched by a model to the best-fitting shelf when it comes in.
2. The schema is **our own combination of OpenAlex and the Library of Congress Classification**, and not either one alone: "I don't want to be
   constrained by openalex alone". The owner confirmed that the Wikipedia lists may also serve as a map of fields.
3. **Finer shelves** come from OpenAlex's topics, as children under the subfields: "I'd rather have too many shelves than not enough".
4. Each shelf has a flag that says whether it is a slim **scout** shelf, holding a small number of anchor books that the walk can reach, or an
   **active** shelf that the engine should fill, and a **priority** of importance. The engine fetches for a shelf by its priority and by how few
   books it holds. The priority may be set by the owner, move with how often searches reach the shelf, or be proposed by an agent.
5. **Scouts are placed at the subfield level only.** A scout shelf may become an active one, and a drill-down to the topics under a subfield
   starts on evidence that the subfield is worth it.
6. A research agent **proposes and does not command**: it may propose that a shelf be filled, that a scout become active, or that a topic of interest be
   taken up (what that means for the schema is proposal 4 below). The owner approves.
7. The schema is built **first**, before the experiments that need it.

**What the agent proposes, for the owner to confirm or change (the owner has not decided these):**

1. **The file holds identity only.** This refines the owner's decision 4 (every shelf has a scout or active flag and a priority) and needs the
   owner's confirmation: the flag and the priority are real and every shelf has them, but their authoritative home is the library's own data, not the
   tracked file. The state of a shelf (scout or active, or neither, which this record calls dormant: a shelf with no books and no flag), its priority and its
   counts are kept there, a shelf with no entry is dormant and takes its parent's priority, and the schema file carries none of them. The reason is that the file is
   tracked and changes rarely, while state changes with use and belongs to the owner's library, which is not in this repository. Each shelf has a stable slug of our own, a name, a level (domain, field, subfield, topic or custom), its parent, its
   OpenAlex identifier and, for the shelves taken from the Library of Congress, its subclass code, and a short scope sentence. The file names the OpenAlex
   snapshot it was built from and the source of every part, with a retrieval date and a hash.
2. **The Library of Congress part is a short, reviewed list** of subclasses for fields OpenAlex does not cover (crafts and trades, recreation, the
   military, the arts and the humanities), as shelves marked custom. The owner reviews the list before it is committed. Only the names and codes of
   subclasses are kept, not the schedules.
3. **Placement.** A paper that carries OpenAlex topics takes its home shelf from the topic OpenAlex names as the work's primary topic (its highest-scoring one),
   and the other topics OpenAlex records for it (at most two more) become its secondary labels, in the order OpenAlex gives them, so no tie or missing score
   has to be resolved. A paper with no primary topic, or whose primary topic is not in the pinned snapshot, is placed like any other book. Any other book is matched in two steps: the nearest shelf
   descriptions by embedding, then a model's choice among them with a one-line reason, with the model and prompt version recorded and the choice
   sampled and audited. The matcher is first measured on OpenAlex-labelled papers with the label hidden. A book has one home shelf, for counting,
   and up to two secondary labels (for a book the matcher placed, the next-best shelves it names). Counts are of home shelves only. Counts roll up to the subfield, field and domain, and a topic shelf takes its subfield's priority unless it
   has its own.
4. **Every OpenAlex topic is in the file from the start, so a drill-down activates a shelf and adds nothing to the file.** The owner said
   "too many shelves rather than not enough". An agent's proposal to take up a topic of interest therefore means: activate the topic shelf that is
   already in the schema (a change of the library's state, approved by the owner). Only a topic that OpenAlex does not have is a **revision of the
   schema file**: a custom shelf is added, a new OpenAlex snapshot is taken in, or a finer shelf is added under a parent. A shelf is never deleted, only
   the books of the parent are placed again, and the revision is recorded.
5. **Day-one evidence for a drill-down** comes from the weave and the walk: the number of links from a scout's themes to themes of other fields,
   and how often the fixed questions of the walk trial reach it. Agent use, searches that find little, and the owner's request are added as the
   library is used. A drill-down proposes the two or three topics nearest to the lead that was followed, not all of a subfield's children.
6. **A share of the fetch budget (a guess: 20 percent) is exploration** that no demand or interest drives, so that growth does not follow only what
   is already asked.

This record does not decide the fetch engine, the matcher or the scouting pass; each is a plan of its own. Accepting it also does not edit
`docs/specs/shelf.md`: the statements there that this record changes (shelves "flat and owner-defined", the bucket as a label only) are revised
in a separate step that is the owner's change of direction.

## Alternatives considered

- **Owner-defined flat shelves only, as `shelf.md` says.** Not chosen: it grows the library around the owner's stated interests, which is the
  limit the owner wanted to escape, and it gives the engine no map of what is missing.
- **The Library of Congress Classification alone.** Not chosen. It is the best complete map of knowledge, including crafts, trades and the
  humanities, but its labels do not arrive with papers, its subclasses are too coarse where the library is densest (computer science sits inside
  mathematics, machine learning has no subclass of its own), and a book has one call number.
- **OpenAlex alone.** Not chosen: it describes research, so crafts, recreation and much of the humanities fit badly, and the owner does not want
  to depend on one source. It is the base of the schema because its labels come with papers, it is CC0 and its 252 subfields are even across modern fields.
- **The Universal Decimal Classification.** Not chosen for shelves: its free summary has about 2,600 classes, too fine for shelves, and the full
  scheme is licensed. Its colon notation for combining subjects is worth borrowing later.
- **The Dewey Decimal Classification.** Not chosen: OCLC owns it, the full scheme is a subscription and its name is a trademark.
- **Bliss (BC2) and the Colon Classification.** Not chosen: Bliss is unfinished and has no web form, and the Colon Classification has no usable machine-readable schedules.
- **Wikipedia's lists as the schema.** Not chosen as the schema, because its categories are not a tree. They remain a map for choosing scouts.
- **Scouts at every OpenAlex topic.** Not chosen now: about 4,500 topics at even two books each is about 9,000 books, many times what the library
  holds, and the time per book on the model server is not measured. A pilot at a few subfields is left to a later plan.

## Consequences

- The library gets a fixed, reviewable map. Counting and fetch focus follow from it, and an agent can propose where to grow.
- There will be about 250 subfield shelves, a few dozen custom ones and about 4,500 topic shelves, all in the file from the start and all dormant until the library's state says otherwise. Empty shelves cost nothing; the
  cost is in the books and the model work for the cards and themes.
- Placement by a model can be wrong, and a wrong placement skews counts and fetch focus but not search. It needs the audit above.
- The schema depends on a snapshot of OpenAlex. Our own slugs keep the library stable if OpenAlex renames or merges a topic.
- `docs/specs/shelf.md` will disagree with this record until it is revised. An accepted decision outranks a spec, so the disagreement is
  resolved in favour of this record, and the revision is a change of direction for the owner.
- No roadmap holds shelves or the crawler; the plan that builds the schema names `Candidate: none` for that reason, and creating a roadmap is
  the owner's.
- The Library of Congress schedules' terms of use have not been checked, and keeping only the names and codes of subclasses is the agent's way
  to stay clear of them. The owner decides before the list is committed, with the repository's visibility in mind.

## Evidence

- **Brainstorm of 2026-11-14** (the owner's decisions above), in the session that completed the plan
  `2026-11-14-try-the-walk-on-the-owners-problems`, at commit `16a3bc9`.
- **A web lookup on 2026-11-14 by the agent's search tool.** Search summaries were read; no page was fetched, so there is no content hash, and
  the figures are second-hand and to be verified by the plan that builds the schema:
  - OpenAlex: 4 domains, 26 fields, 252 subfields and 4,516 topics; topics assigned by a classifier with calibrated scores, up to three to a work;
    CC0. https://help.openalex.org/data/topics/ and https://help.openalex.org/data/subfields/
  - Library of Congress Classification: 21 main classes; "over 225" subclasses from one training slide (unverified); free PDF schedules at
    https://loc.gov/aba/publications/FreeLCC/freelcc.html; Classification Web states its content is copyrighted outside the United States
    (https://classweb.loc.gov/legal.html); the linked-data service is published as a public domain data set (https://id.loc.gov/about/); a full bulk
    download of the classification was not confirmed.
  - UDC Summary: about 2,600 classes of a scheme of over 70,000, as linked data; licence wording differs between sources
    (https://arxiv.org/pdf/2205.01395).
  - Dewey: OCLC owns it; the summaries are free under terms (https://oclc.org/research/activities/browser/terms.html).
  - Bliss BC2: 15 of about 28 volumes published, no web version (https://blissclassification.org.uk/bchist.shtml).
  - Colon Classification: faceted (PMEST), its present use is debated (https://isko.org/cyclo/colon_classification).
- **What the owner's library showed:** the walk trial of 2026-11-14 (Results of the plan above) gave the thinnest leads for the 3D-printing problem,
  by the agent's impression from rounds 1 and 2 only, and an "unclear" result for whether the wide walk adds anything over an ordinary search. It
  did not establish the cause, and it did not show whether the library holds books on layer-by-layer building.
