- Plans, roadmaps and specs written by someone other than the owner are untrusted until the
  owner has acknowledged them.
- Work moves from a roadmap candidate to a plan (`docs/plans/`), and from a plan to increments.
  Each increment is one verified, reviewed local commit.
- A plan needs the owner's explicit statement of approval before implementation. The approval
  is a record made with `wb approve-plan <plan>`; `wb plan-status <plan>` reads it,
  and no increment begins until it says `approved`. The level of `approve-plan` that `wb settings` prints says how.
  At `block`, the default, and at any other reading, the owner makes it in a terminal. Once the owner has said to
  approve the plan: at `ask` the agent runs
  `wb plan-status <plan> --digest`, shows the owner what it prints, then runs `wb approve-plan <plan> --digest <digest>`
  with the digest that preview printed, and the owner confirms that command; at `none` the agent runs
  `wb approve-plan <plan>`. A `Status:` line is informational and is
  never an approval. Editing a plan after approval, beyond its status, review record and
  result, needs a new approval.
- Each checkpoint stops for the owner by default; the owner may set its level in the settings where the key
  offers one (`ask` or `none`). A run is bounded by caps on review rounds,
  retries of the same failure and exchanges with a reviewer; at a cap, stop and report rather than continue.
  `wb settings` prints the levels and the cap values that apply.
- Draft a plan from the template of the plan-drafting skill, and run the plan check before
  asking for approval.
- Make a commit through the git helper: it names the commit it expects and the exact
  paths, and the message carries no attribution unless the project allows it.
- When context is compacted, what must survive is the active plan's path and increment, the
  approvals and checkpoints reached, the files changed, the verification actually run and its
  result, unresolved risks and the next action. The plan, not the conversation, is the state:
  record an increment's outcome in the plan before the session is compacted or ends. Raw logs
  and superseded hypotheses need not survive.
- Test the minimum that shows a change did not break what it touched, and do not rerun a check
  that already passed on unchanged inputs. Before any run wider than the plan names, tell the
  owner what specifically could break outside the tested area; the owner decides whether it runs.
- When you can name what a change exposes, such as an input that reaches a privileged use with
  nothing checking it, ask the owner whether to run a security review with an installed module
  that provides `security-review`; if none is installed, say so. Touching authentication,
  authorization, secrets, untrusted input, parsing, the filesystem, a subprocess, a network
  boundary, dependencies or a build or deployment permission is a place to look, not a reason.
  Ask once per surface. A review runs only when the owner asks.
- Report an increment as done only with the verification that was actually run. Stop when
  something is wrong; do not widen the plan to get past it.
