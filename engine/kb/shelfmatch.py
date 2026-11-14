"""The pure core of the shelf matcher (Increment A of the plan `2026-11-14-measure-the-shelf-matcher`).

A work is placed on a *home shelf*, which is a topic shelf or a custom shelf of the schema (`docs/specs/shelf.md`, "Placement when more than one shelf fits"); counts roll up from it to its subfield, field and domain.
This module ranks the shelves by the cosine closeness of their vectors to the vector of a text, and scores a placement against the true shelf at each level. It makes no vector itself: the vectors come from an embedding
model, which is another step. It reads a schema file as data through the checker, uses only the standard library, and needs no network, no model, no library of books and no config.

What is ranked and what is scored (each figure has one meaning, fixed by the plan):

- the **home ranking** ranks the home shelves; *top-1* is the nearest and *top-k* the k nearest; a **home hit** is the true shelf there;
- the **rolled-up hit** is that the nearest home shelf lies in the true subfield, field or domain (a custom shelf has none, so a nearest custom shelf is never a rolled-up hit);
- the **candidate recall** is that at least one of the k nearest home shelves lies in the true subfield or field;
- the **level rankings** (information, not the bar) rank the subfield shelves alone, the field shelves alone and the domain shelves alone, each by its own vector;
- a true custom shelf has no subfield, field or domain, so the figures that need them are not defined for it (`None`) and it is counted apart;
- `nearest_custom` and `custom_in_topk` say whether a custom shelf is the nearest or among the k nearest (defined for every placement), so that a miss a custom shelf causes can be traced.

A figure is counted over the placements for which it is defined, so the figures need not share one denominator: the home figures and the two custom flags are defined for every placement (a true custom shelf included),
the rolled-up, recall and level figures only for a placement whose true shelf is a topic."""
import heapq
import math
import operator

from . import KbError, shelfschema

MAX_DIM = 8192          # the longest vector the engine takes from a model (see kb.models)
MAX_COMPONENT = 1e6     # a number of a vector larger than this in size is refused
MIN_SCALE = 1e-30       # and so is a vector whose largest number is smaller than this
COARSE = ("subfield", "field", "domain")
HOME_LEVELS = ("topic", "custom")
FIGURES = ("home_top1", "home_topk", "rolled_subfield", "rolled_field", "rolled_domain", "recall_subfield", "recall_field",
           "level_subfield_top1", "level_subfield_topk", "level_field_top1", "level_field_topk", "level_domain_top1", "nearest_custom", "custom_in_topk")
SCORE_KEYS = ("true", "true_subfield", "true_field", "true_domain", "custom_true", "k", "field_k") + FIGURES


# --- the schema

class Schema:
    """The shelves of a schema file in the order of the file: `home` (topic and custom slugs), `levels` (the slugs of each coarser level) and `ancestors` (a topic's subfield, field and domain; None for a custom shelf)."""

    def __init__(self, data):
        self.shelves = data["shelves"]
        self.by_slug = {s["slug"]: s for s in self.shelves}
        self.home = [s["slug"] for s in self.shelves if s["level"] in HOME_LEVELS]
        self.levels = {level: [s["slug"] for s in self.shelves if s["level"] == level] for level in COARSE}
        self.level_sets = {level: frozenset(slugs) for level, slugs in self.levels.items()}
        self.ancestors = {}
        for slug in self.home:
            shelf = self.by_slug[slug]
            if shelf["level"] == "custom":
                self.ancestors[slug] = None
                continue
            subfield = self.by_slug[shelf["parent"]]
            field = self.by_slug[subfield["parent"]]
            domain = self.by_slug[field["parent"]]
            self.ancestors[slug] = {"subfield": subfield["slug"], "field": field["slug"], "domain": domain["slug"]}


def schema_from_data(data):
    """The schema of an already parsed file; a file the checker finds a problem in is refused."""
    problems = shelfschema.check_schema(data)
    if problems:
        raise KbError("the schema has problems: %s" % "; ".join(problems[:5]))
    return Schema(data)


def load_schema(path):
    """The schema in the file at `path` (read as data, by the checker's loader)."""
    return schema_from_data(shelfschema.load(path))


# --- vectors and ranking

def unit(vector):
    """The vector scaled to length one; a vector that is empty, too long, not made of finite numbers, with a number above a million, or all but zero is refused."""
    if type(vector) not in (list, tuple) or not 1 <= len(vector) <= MAX_DIM:
        raise KbError("a vector must be a list of 1 to %d numbers" % MAX_DIM)
    for x in vector:
        if type(x) not in (int, float) or abs(x) > MAX_COMPONENT or not math.isfinite(x):
            raise KbError("a vector must be made of finite numbers of at most %g in size" % MAX_COMPONENT)
    top = max(abs(x) for x in vector)
    if top < MIN_SCALE:
        raise KbError("a vector of zeros or of numbers that small has no direction")
    scaled = [x / top for x in vector]
    norm = math.sqrt(sum(x * x for x in scaled))
    return [x / norm for x in scaled]


def rank(query, slugs, vectors, k):
    """The k nearest shelves, nearest first, as (slug, cosine): `query` and `vectors` are unit vectors; a tie goes to the shelf that comes first in `slugs`, so a run is repeatable."""
    if type(k) is not int or k < 1:
        raise KbError("k must be a whole number of at least 1")
    if len(slugs) != len(vectors):
        raise KbError("there must be one vector for each slug")
    width = len(query)
    if abs(sum(map(operator.mul, query, query)) - 1.0) > 1e-6:
        raise KbError("the query must be a unit vector (see unit)")
    scores = []
    for index, vector in enumerate(vectors):
        if len(vector) != width:
            raise KbError("a vector has %d numbers and the query has %d" % (len(vector), width))
        scores.append((index, max(-1.0, min(1.0, sum(map(operator.mul, query, vector))))))
    nearest = heapq.nsmallest(k, scores, key=lambda pair: (-pair[1], pair[0]))
    return [(slugs[index], score) for index, score in nearest]


class Space:
    """The unit vectors of the home shelves and of the shelves of each coarser level, with the schema they belong to."""

    def __init__(self, schema, vectors):
        if type(vectors) is not dict:
            raise KbError("the vectors must be a dictionary from a shelf's slug to its vector")
        unknown = [slug for slug in vectors if slug not in schema.by_slug]
        if unknown:
            raise KbError("there is a vector for a shelf that is not in the schema: %s" % unknown[0])
        wanted = list(schema.home) + [slug for level in COARSE for slug in schema.levels[level]]
        missing = [slug for slug in wanted if slug not in vectors]
        if missing:
            raise KbError("%d shelves have no vector (the first is %s)" % (len(missing), missing[0]))
        made = {slug: unit(vectors[slug]) for slug in wanted}
        widths = {len(v) for v in made.values()}
        if len(widths) != 1:
            raise KbError("the vectors have different lengths")
        self.schema = schema
        self.dim = widths.pop()
        self.home = list(schema.home)
        self.home_vectors = [made[slug] for slug in self.home]
        self.levels = {level: list(schema.levels[level]) for level in COARSE}
        self.level_vectors = {level: [made[slug] for slug in self.levels[level]] for level in COARSE}


def build_space(schema, vectors):
    """The space of a schema and the vectors of its shelves (a dictionary from slug to vector): every home shelf and every subfield, field and domain shelf must have one, and no other shelf may."""
    return Space(schema, vectors)


def place(space, query, k=5):
    """The k nearest shelves of the home ranking and of each level ranking for the vector of one text."""
    q = unit(query)
    if len(q) != space.dim:
        raise KbError("the query has %d numbers and the shelves have %d" % (len(q), space.dim))
    out = {"home": rank(q, space.home, space.home_vectors, k)}
    for level in COARSE:
        out[level] = rank(q, space.levels[level], space.level_vectors[level], k)
    return out


# --- scoring

def _slugs(placement, key, needed, known):
    listed = placement.get(key) if type(placement) is dict else None
    if type(listed) is not list or len(listed) < needed or any(type(p) not in (tuple, list) or len(p) != 2 for p in listed):
        raise KbError("the placement does not hold the %d nearest shelves of its %s ranking" % (needed, key))
    slugs = [p[0] for p in listed]
    if any(type(slug) is not str or slug not in known for slug in slugs):
        raise KbError("the %s ranking of the placement names a shelf that is not a %s shelf of this schema" % (key, "home" if key == "home" else key))
    return slugs


def score(schema, placement, true_slug, k=5, field_k=3):
    """The figures of one placement against its true home shelf (see the module's text); `placement` is what `place` returns for at least max(k, field_k) shelves."""
    if type(true_slug) is not str or true_slug not in schema.ancestors:
        raise KbError("the true shelf must be a home shelf (a topic or a custom shelf) of the schema")
    for value in (k, field_k):
        if type(value) is not int or value < 1:
            raise KbError("k must be a whole number of at least 1")
    home = _slugs(placement, "home", min(k, len(schema.home)), schema.ancestors)
    levels = {"subfield": _slugs(placement, "subfield", min(k, len(schema.levels["subfield"])), schema.level_sets["subfield"]),
              "field": _slugs(placement, "field", min(field_k, len(schema.levels["field"])), schema.level_sets["field"]),
              "domain": _slugs(placement, "domain", 1, schema.level_sets["domain"])}
    true = schema.ancestors[true_slug]
    nearest = schema.ancestors[home[0]]
    out = {key: None for key in SCORE_KEYS}
    out.update(true=true_slug, custom_true=true is None, k=k, field_k=field_k, home_top1=home[0] == true_slug, home_topk=true_slug in home[:k],
               nearest_custom=nearest is None, custom_in_topk=any(schema.ancestors[slug] is None for slug in home[:k]))
    if true is None:
        return out
    out.update(true_subfield=true["subfield"], true_field=true["field"], true_domain=true["domain"])
    for level in COARSE:
        out["rolled_" + level] = nearest is not None and nearest[level] == true[level]
    nearer = [schema.ancestors[slug] for slug in home[:k]]
    for level in ("subfield", "field"):
        out["recall_" + level] = any(a is not None and a[level] == true[level] for a in nearer)
    out["level_subfield_top1"] = levels["subfield"][0] == true["subfield"]
    out["level_subfield_topk"] = true["subfield"] in levels["subfield"][:k]
    out["level_field_top1"] = levels["field"][0] == true["field"]
    out["level_field_topk"] = true["field"] in levels["field"][:field_k]
    out["level_domain_top1"] = levels["domain"][0] == true["domain"]
    return out


def _figures(scored):
    out = {}
    for name in FIGURES:
        defined = [s[name] for s in scored if s[name] is not None]
        hits = sum(1 for value in defined if value)
        out[name] = {"hits": hits, "of": len(defined), "share": hits / len(defined) if defined else None}
    return out


def _floor(scored, key):
    """The most common true value of `key` and its share among the placements for which it is defined; a tie goes to the slug that sorts first."""
    values = [s[key] for s in scored if s[key] is not None]
    if not values:
        return {"shelf": None, "share": None}
    counts = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    best = min(counts, key=lambda value: (-counts[value], value))
    return {"shelf": best, "share": counts[best] / len(values)}


def summarise(scored):
    """The counts and shares of every figure over a list of scored placements, the same by the field of the true shelf, and the floor (what always answering the most common shelf, subfield, field or domain would score)."""
    if type(scored) is not list or not scored or any(type(s) is not dict or any(key not in s for key in SCORE_KEYS) for s in scored):
        raise KbError("there must be a non-empty list of scored placements")
    ks = {(s["k"], s["field_k"]) for s in scored}
    if len(ks) != 1:
        raise KbError("the placements were scored with different k (%s)" % ", ".join(sorted("%s and %s" % pair for pair in ks)))
    (k, field_k), = ks
    by_field = {}
    for s in scored:
        if s["true_field"] is not None:
            by_field.setdefault(s["true_field"], []).append(s)
    return {"n": len(scored), "k": k, "field_k": field_k, "n_custom_true": sum(1 for s in scored if s["custom_true"]), "figures": _figures(scored),
            "per_field": {field: {"n": len(rows), "figures": _figures(rows)} for field, rows in sorted(by_field.items())},
            "floor": {"home_top1": _floor(scored, "true"), "rolled_subfield": _floor(scored, "true_subfield"), "rolled_field": _floor(scored, "true_field"),
                      "rolled_domain": _floor(scored, "true_domain")}}
