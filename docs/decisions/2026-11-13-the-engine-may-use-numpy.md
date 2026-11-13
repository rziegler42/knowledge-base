# The engine may use numpy, first to build the weaves

Status: Accepted by Robert Ziegler <25854477+rziegler42@users.noreply.github.com> on 2026-11-13

## Context

The README and the engine README say that the engine's own code uses only the Python standard library. The only packages beyond it
are the article extractor's, which are pinned by hash in `engine/requirements.lock` and installed into `engine/.venv`.

The weaves (`docs/specs/weave.md`) are sets of links between themes. Building one compares every theme with every other: on the
owner's library of 2026-11-13, 1,805 themes with a summary vector and a method vector of 2,560 numbers each, about 3.3 million pairs
and about 8.4 billion multiplications for each of the two comparisons a same-mechanism weave needs. The library will keep growing, a
build grows with the square of the number of themes, and there will be several weaves.

On 2026-11-13, in the brainstorm for the roadmap candidate `theme-weave#theme-links`, the owner said: the project can also use numpy
if it is needed or helps the engine.

## Decision

The engine may use numpy where it is needed or where it helps. The first use is the build of the weaves.

The agent proposes three details for the owner to confirm or change; the owner has not decided them:

1. **Only numpy.** This record does not allow other third-party packages. Each other one needs its own decision.
2. **Where it is imported.** numpy is imported where it is used, so that the commands that do not need it (search, read, the cards,
   the themes, the vectors) still run on the standard library alone.
3. **How it is installed.** numpy is pinned by hash in `engine/requirements.lock` and installed into `engine/.venv` the way the
   article extractor's packages are, and the README says which commands need it.

## Alternatives considered

The owner did not weigh these; they are the agent's.

- **Stay on the standard library and build the weaves in plain Python.** Rejected. A comparison loop in plain Python runs at a few
  million multiplications a second, so the 8.4 billion of one comparison would take roughly half an hour, and a weave needs two. This
  is an estimate from that rate, not a measurement, and it grows with the square of the library.
- **A heavier package for the comparisons** (a scientific library, a vector index or a vector database). Not chosen. They are more to
  install, pin and approve, and the library does not need them at its present size. A far larger library may need an approximate
  nearest-neighbour index, and that would be a decision of its own.
- **A compiled helper written for the project.** Not chosen. It would add a build step and code to maintain to do what numpy does.

## Consequences

- A same-mechanism weave over the owner's library builds in about a second, and adding a batch of books by repair takes under a
  second, so rebuilds and repairs cost little at the present size.
- The sentence "the engine itself uses only the standard library" in the README and the engine README stops being true and has to
  change with the first code that imports numpy.
- There is one more package to pin and to keep current. The version tested, numpy 2.5.4, has a wheel for Python 3.15 on Apple
  silicon, which is the platform the engine is written for; a platform with no such wheel would build it from source.
- Not yet checked: whether the build of a weave runs inside any sandbox the engine uses for other tools, and what that sandbox would
  need to allow.
- A change of mind about numpy, or a wish to add another package, is a new record.

## Evidence

Run on 2026-11-13, with Python 3.15.0 and pip 26.2.2 on macOS, with the repository at `ff99750`:

- `pip install numpy` into a throwaway virtual environment outside the repository installed numpy 2.5.4 from the wheel
  `numpy-2.5.4-cp315-cp315-macosx_14_0_arm64`. The hash of the wheel was not recorded; the plan that adds the dependency pins it.
- On the owner's local library, which is not in this repository, read only and with no call to any model: building a same-mechanism
  weave over 1,805 themes in 173 books took about 1.0 second with numpy, and repairing it for 17 added books took about 0.7 second.
  The figures for plain Python above are an estimate and were not measured.
- The weave spec (`docs/specs/weave.md`, "Evidence") holds the other measurements made in the same brainstorm.
