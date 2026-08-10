# Percent-based sampling (`--sample-pct`) design

Status: approved 2026-08-09. Reopens and implements the percent-based
sampling item that
[2026-08-03-reservoir-sampling-design.md](2026-08-03-reservoir-sampling-design.md)
placed out of scope.

## Problem

`ddlgenerator` already ships four ways to cut down what a large source
feeds into type inference — `--limit`, `--every-nth`, `--sample-k`/`--seed`,
plus `--count-only` to survey a source first. None of them expresses
"a fixed *proportion* of whatever is in there."

`--sample-k` answers "give me exactly K rows." That is the right question
when the sample size is what matters, but not when the sample should scale
with the source: K=1000 is most of a small file and a rounding error in a
large one, and picking K per source means knowing each source's size first.

There is also a structural gap `--sample-k` cannot close. Algorithm R
cannot finalize which rows survive until it has seen the whole stream —
any later row can displace one already provisionally kept — so
`Source.__next__` must drain the *entire* underlying generator before it
can yield its first row. Bernoulli sampling decides each row on the spot,
so it streams: it buffers nothing and yields as it goes.

## Reversing the earlier decision

The 2026-08-03 pass rejected percent sampling in favor of exact-K
reservoir sampling, on the grounds that an exact, well-understood
algorithm beat an approximate one. That reasoning was sound and
`--sample-k` shipped on it; it is not being undone here.

What changed is the framing. The two are not competing answers to one
question — they answer different questions, and the exactness argument
only settles the first:

- **"How many rows do I want?"** → `--sample-k`. Exact count, needs no
  upfront N, costs a full drain before first output.
- **"What share of this source do I want?"** → `--sample-pct`. Approximate
  count, needs no upfront N, streams.

Making percent sampling *exact* would require knowing N before sampling —
a counting pass (cheap only for xlsx/SQLAlchemy/MongoDB, a full second
read for CSV/JSON/YAML/HTML/`.xls`, and impossible for generators and
file-like objects that cannot be reopened). Paying that to convert an
approximate count into an exact one gives up the streaming property that
is the whole reason to choose percent sampling. So the approximation is
accepted deliberately here, and the docs state it plainly rather than
burying it: **use `--sample-k` when the row count matters.**

## Scope

In scope:
- New `--sample-pct P` flag (`0 < P <= 100`, fractional values allowed),
  Bernoulli-sampling each row with probability `P/100`.
- A ≥1-row floor so a non-empty source never infers DDL from zero rows.
- `--seed` extended to cover `--sample-pct` as well as `--sample-k`.

Out of scope:
- Combining `--sample-pct` with `--limit` as a safety cap ("10%, but never
  more than 1000 rows"). Both are row-by-row streaming decisions so they
  would layer cleanly, but full exclusivity matches `--sample-k`'s existing
  rule and keeps one validation shape. Revisit on demand.
- Database-side pushdown (`TABLESAMPLE`, `WHERE random() < p`) for
  `sqlalchemy://` sources. Same reasoning that deferred `ORDER BY RANDOM()`
  for `--sample-k`: it applies to 3 of ~10 source types and adds a second
  sampling algorithm to maintain.
- Any change to `--sample-k`, `--every-nth`, `--limit`, or `--count-only`
  behavior.

## Architecture

`--sample-pct` sits in `Source.__next__` (`ddlgenerator/sources.py`), in
the same band as `--every-nth`: filtering raw top-level records **before**
`reshape.walk_and_clean` / `unnest_children` run. This is load-bearing and
was settled when `--every-nth` was designed — sampling after those
functions run orphans child rows and desyncs FK assignment for nested
parent/child structures. `tests/test_table.py::TestSamplePctWiring::
test_sample_pct_preserves_parent_child_correspondence` pins it.

Unlike `--sample-k`, the percent branch never buffers rows and never
drains ahead: it pulls from the underlying generator until one row passes
the filter, returns it, and resumes there on the next call.

### The ≥1-row floor

A low percentage over a small source can select nothing at all, leaving
DDL generation with an empty table. The floor: while nothing has been
yielded, maintain an Algorithm R reservoir of **size 1** over the rows
seen so far. If the generator is exhausted and the yield count is still
zero, serve that row and stop.

Properties this buys:

- **O(1) memory**, and still fully streaming — one row held, never N.
- **Unbiased** — the floor row is uniform over the whole source, unlike
  the obvious alternative of remembering row 1, which for any sorted
  source is systematically unrepresentative.
- **Free in the common case** — once anything has been yielded normally
  the floor is unreachable, so the extra draw and branch stop.
- **Empty stays empty** — an empty source has no reservoir row and still
  yields nothing.

The floor reservoir draws from a **separate** RNG stream, derived as
`random.Random(f"{seed}:pct-fallback")`, so Bernoulli keep/drop decisions
stay a clean function of `(seed, row index)` and are not perturbed by
floor bookkeeping. A string-derived seed also cannot collide with the
`seed + idx` offsets `_multiple_sources` gives subsources.

### Multi-source behavior

`_multiple_sources` already builds an independent `Source` per matched
file/sheet with `seed + idx`, so `--sample-pct` inherits both the
per-subsource independence and, as a consequence, a **per-subsource
floor**: five matched files yield at least five rows, not one. The seed
offset matters for the same reason it did for Algorithm R — Bernoulli
decisions are index-driven, not content-driven, so an unmodified shared
seed would select identical relative positions from every same-length
file.

### Interaction summary

| With | Behavior |
|---|---|
| `--limit`, `--every-nth`, `--sample-k` | `ValueError` — mutually exclusive |
| `--seed` | Optional; makes the sample reproducible. `--seed` alone still errors. |
| `--count-only` | Ignored, as with every other sampling flag |
| glob / multi-sheet | Applied per subsource, floor included |
| `sqlalchemy://` URLs | Supported, via `sqlalchemy_table_sources` |

## Components

- `ddlgenerator/sources.py` — `Source.__init__` validation and state,
  `Source.__next__` percent branch, `_multiple_sources` passthrough,
  `sqlalchemy_table_sources` parameter.
- `ddlgenerator/ddlgenerator.py` — `Table.__init__` parameter, forwarded
  to `Source`.
- `ddlgenerator/console.py` — `--sample-pct` argument, CLI-layer
  validation, passthrough to `Table` and `sqlalchemy_table_sources`,
  relaxed `--seed` requirement.
- Docs — `docs/usage.rst`, `README.rst`, `docs/user_guide.html`.

## Known consequence

A one- or two-row sample distorts type inference: a lone `id` value of `1`
infers as `BOOLEAN`, and `VARCHAR(n)` widths reflect only the sampled
strings. This is pre-existing behavior shared with `--limit 1` and
`--sample-k 1`, not introduced here, but the ≥1 floor makes it easier to
reach — so the user guide calls it out where the floor is described, and
points at `-c/--cushion`.
