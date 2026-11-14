"""The walk: offering an agent themes it did not ask for (`docs/specs/theme-walk.md`; the plan `2026-11-13-let-an-agent-walk-from-themes-along-the-links`).

This part is the selection, pure functions of plain data: the links of a weave (as `weave.read` gives its rows), the starting themes, the themes the agent has seen or drops, the ordinary set and a
visible set. It reads no file, calls no search and no model. A theme is a key `(book_id, version_id, theme_id)`; a REF is the same three parts joined by `/`.

What the spec's table of levels leaves open, and how it is read here (to be written into the spec's "Built" line by Increment C and left to the owner):

  * `narrow` follows a theme's links in bands 2 and 3 only, the strongest closeness first, at most 3; one step.
  * `medium` follows a theme's links in every band, the strongest closeness first (whatever the band), at most 3 at the first step and 2 at the second; two steps.
  * `wide` follows all of a theme's links (at most 12) at the first step, and at the second and third step at most 2, the farthest band first, then the strongest closeness; three steps.
  * Ties in closeness go to the key of the partner.
  * The cap on the links of a theme applies to the links that can still be followed: a link to a theme that is blocked (seen, dropped, another starting theme) or already on the route does not use one of
    the places, or a round that passes back what it has seen would find nothing new.
  * A route never visits a theme twice, never passes through a starting theme, a `--seen` theme or a `--drop` theme, and never follows a link between two themes of one book.
  * The closeness is an integer in billionths, as the weave keeps it, and the threshold of the follow-through lane is compared as an integer, at or above.
"""
from . import KbError, ids, themevectors

SCALE = 10 ** 9
THRESHOLD = 660_000_000        # the weakest link of a route at or above this puts the lead in the follow-through lane (0.66; a guess to tune on the trial)
MAX_LIMIT = 20
PER_BOOK = 2                   # at most two leads of one book in a lane
PER_START = 3                  # at most three leads reached from one starting theme in a lane
FOLLOW = "follow-through"
EXPLORE = "exploration"
LEVELS = {
    "narrow": {"steps": 1, "bands": (2, 3), "per_step": (3,)},
    "medium": {"steps": 2, "bands": (0, 1, 2, 3), "per_step": (3, 2)},
    "wide": {"steps": 3, "bands": (0, 1, 2, 3), "per_step": (12, 2, 2)},
}


def ref_of(key):
    return "/".join(key)


def key_of(ref):
    """The key of a REF, or a refusal. A REF is three identifiers joined by `/`: a book id, a version and a theme id, each of the shape the engine makes. It is never a path and never names a file."""
    if not isinstance(ref, str) or len(ref) > 200:
        raise KbError("a REF is `book_id/version_id/theme_id`")
    parts = ref.split("/")
    if len(parts) != 3:
        raise KbError("a REF is `book_id/version_id/theme_id`")
    book, version, theme_id = parts
    ids.check_id(book)
    if not themevectors._VERSION.fullmatch(version) or not themevectors._THEME_ID.fullmatch(theme_id):
        raise KbError("a REF is `book_id/version_id/theme_id`")
    return (book, version, theme_id)


def build_graph(links, visible=None):
    """`{key: {partner: (closeness, band, wording)}}` from the rows `(a, b, closeness, wording, band)` of a weave. A link is two-way. A link with a theme outside `visible` at either end, a link
    between two themes of one book and a link of a theme to itself are left out; a pair given twice keeps its first numbers."""
    graph = {}
    for a, b, closeness, wording, band in links:
        a, b = tuple(a), tuple(b)
        if a == b or a[0] == b[0]:
            continue
        if visible is not None and (a not in visible or b not in visible):
            continue
        if b in graph.get(a, {}):
            continue
        graph.setdefault(a, {})[b] = (closeness, band, wording)
        graph.setdefault(b, {})[a] = (closeness, band, wording)
    return graph


def _followed(graph, key, level, step, excluded):
    """The links of a theme that the level follows at this step (0 for the first): those in the level's bands to a theme not in `excluded`, in the level's order, the first few."""
    spec = LEVELS[level]
    items = [(partner, c, band) for partner, (c, band, _) in graph.get(key, {}).items() if band in spec["bands"] and partner not in excluded]
    if level == "wide" and step >= 1:
        items.sort(key=lambda t: (t[2], -t[1], t[0]))      # the farthest band first, then the strongest, then the key
    else:
        items.sort(key=lambda t: (-t[1], t[0]))            # the strongest first, then the key
    return items[:spec["per_step"][step]]


def routes(graph, starts, level, steps, blocked):
    """Every route of one to `steps` steps from the starting themes: `(themes, links)` with `themes` the keys from the start and `links` the `(closeness, band)` of each step. A route visits no theme twice
    and no theme of `blocked`."""
    depth = min(LEVELS[level]["steps"], steps)
    found = []
    for start in sorted(starts):
        frontier = [((start,), ())]
        for step in range(depth):
            following = []
            for themes, links in frontier:
                for partner, closeness, band in _followed(graph, themes[-1], level, step, blocked | set(themes)):
                    route = (themes + (partner,), links + ((closeness, band),))
                    following.append(route)
                    found.append(route)
            frontier = following
    return found


def _check(level, steps, limit):
    if level not in LEVELS:
        raise KbError(f"the level is one of {', '.join(LEVELS)}")
    if steps is None:
        steps = LEVELS[level]["steps"]
    if type(steps) is not int or not 1 <= steps <= LEVELS[level]["steps"]:
        raise KbError(f"at the level {level} the steps are a whole number from 1 to {LEVELS[level]['steps']}")
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise KbError(f"the limit is a whole number from 1 to {MAX_LIMIT}")
    return steps


def _destinations(found):
    """`{destination: [routes ending there]}`."""
    by = {}
    for route in found:
        by.setdefault(route[0][-1], []).append(route)
    return by


def _best(candidates):
    """The best route of a theme: the highest weakest link, then the fewest steps, then the smallest sequence of the REFs of its themes compared as text."""
    return min(candidates, key=lambda r: (-min(c for c, _ in r[1]), len(r[1]), tuple(ref_of(k) for k in r[0])))


def select(links, starts, level="wide", steps=None, seen=(), drop=(), ordinary=None, limit=12, visible=None):
    """The leads for the starting themes. `links` are the rows of a weave; `starts` the keys to walk from; `seen` and `drop` keys; `ordinary` `{key: rank}` of the ordinary set (rank from 1);
    `visible` the set of keys the caller may see, or `None` for all. Every number is over the visible themes and over nothing else. Returns a dict:
    `follow_through` and `exploration` (the leads of each lane, in order), `held_back` (leads not shown, by reason: `book`, `start`, `limit`; and the themes the walk would have offered but for `seen` and
    for `drop`), `reached_by_level` (the themes reachable at each level, before the caps on leads; the caps on the links of a theme apply), `starts`, `starts_without_links`, `lane_shares` (the places each
    lane is given by the limit before a short lane gives its places away), `lane_counts` (the leads each lane shows), `notes` (why little or nothing was found) and `level`, `steps`, `limit`."""
    steps = _check(level, steps, limit)
    seen, drop, starts = set(map(tuple, seen)), set(map(tuple, drop)), [tuple(s) for s in starts]
    visible_set = None if visible is None else set(map(tuple, visible))
    if visible_set is not None:
        seen, drop, starts = seen & visible_set, drop & visible_set, [s for s in starts if s in visible_set]
    starts = sorted(set(starts))
    ordinary = {tuple(k): r for k, r in (ordinary or {}).items() if visible_set is None or tuple(k) in visible_set}
    ordinary_books = {k[0] for k in ordinary}
    graph = build_graph(links, visible_set)
    blocked = seen | drop | set(starts)
    reached_by_level = {name: len(_destinations(routes(graph, starts, name, LEVELS[name]["steps"], blocked))) for name in LEVELS}
    found = routes(graph, starts, level, steps, blocked)
    by = _destinations(found)
    lanes = {FOLLOW: [], EXPLORE: []}
    for destination, candidates in by.items():
        themes, links_used = _best(candidates)
        weakest = min(c for c, _ in links_used)
        weakest_band = next(band for c, band in links_used if c == weakest)
        lead = {"key": destination, "ref": ref_of(destination), "route": [{"theme": themes[0], "closeness": None, "band": None}] +
                [{"theme": t, "closeness": c, "band": b} for t, (c, b) in zip(themes[1:], links_used)],
                "steps": len(links_used), "weakest": weakest, "weakest_band": weakest_band, "last_band": links_used[-1][1], "start": themes[0],
                "ordinary_rank": ordinary.get(destination), "book_in_ordinary": destination[0] in ordinary_books, "reached_by": len(candidates)}
        lanes[FOLLOW if weakest >= THRESHOLD else EXPLORE].append(lead)
    held = {"book": 0, "start": 0, "limit": 0}
    kept = {}
    for lane, leads in lanes.items():
        in_set = lambda lead: 0 if lead["ordinary_rank"] is None else 1
        if lane == FOLLOW:
            leads.sort(key=lambda lead: (in_set(lead), -lead["weakest"], lead["ref"]))
        else:
            leads.sort(key=lambda lead: (in_set(lead), lead["last_band"], -lead["weakest"], lead["ref"]))
        books, roots, taken = {}, {}, []
        for lead in leads:
            if books.get(lead["key"][0], 0) >= PER_BOOK:
                held["book"] += 1
            elif roots.get(lead["start"], 0) >= PER_START:
                held["start"] += 1
            else:
                books[lead["key"][0]] = books.get(lead["key"][0], 0) + 1
                roots[lead["start"]] = roots.get(lead["start"], 0) + 1
                taken.append(lead)
        kept[lane] = taken
    follow_share = -(-2 * limit // 3)                      # two thirds, rounded up
    places = {FOLLOW: min(len(kept[FOLLOW]), follow_share), EXPLORE: min(len(kept[EXPLORE]), limit - follow_share)}
    spare = limit - places[FOLLOW] - places[EXPLORE]
    for lane in (FOLLOW, EXPLORE):                         # a lane that is short gives its places to the other
        more = min(spare, len(kept[lane]) - places[lane])
        places[lane] += more
        spare -= more
    out = {lane: kept[lane][:places[lane]] for lane in kept}
    held["limit"] = sum(len(kept[lane]) - len(out[lane]) for lane in kept)
    unblocked = _destinations(routes(graph, starts, level, steps, set(starts)))       # what would be reached if nothing were seen or dropped
    held["seen"] = sum(1 for d in unblocked if d in seen)
    held["drop"] = sum(1 for d in unblocked if d in drop and d not in seen)
    followable = [s for s in starts if graph.get(s)]
    notes = []
    if not starts:
        notes.append("no_starting_theme")
    elif not followable:
        notes.append("no_starting_theme_has_a_link")
    if starts and not by:
        notes.append("everything_reached_is_seen_or_dropped" if unblocked else "nothing_reached")
    elif by and all(d in ordinary for d in by):
        notes.append("everything_reached_is_in_the_ordinary_set")
    return {"level": level, "steps": steps, "limit": limit, "follow_through": out[FOLLOW], "exploration": out[EXPLORE], "held_back": held, "reached_by_level": reached_by_level,
            "starts": [ref_of(s) for s in starts], "starts_without_links": [ref_of(s) for s in starts if not graph.get(s)],
            "lane_shares": {FOLLOW: follow_share, EXPLORE: limit - follow_share}, "lane_counts": {FOLLOW: len(out[FOLLOW]), EXPLORE: len(out[EXPLORE])}, "notes": notes}
