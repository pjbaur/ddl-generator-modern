# Reservoir-K sampling (`--sample-k`) design

Status: approved 2026-08-03. Implements the deferred "percent/random sampling"
item from the `--count-only`/`--every-nth` work (`215a7b5`, `073ce90`).

## Problem

`--limit` and `--every-nth` (already shipped) let a user cap or stride
through rows from a data source, but neither gives an unbiased random
sample. A user who wants "a representative sample of K rows" from a huge
or unknown-size source has no way to get one without picking an arbitrary
stride or writing custom code. This was explicitly deferred when
`--every-nth` shipped, with reservoir sampling (Algorithm R) chosen ahead
of time over an approximate Bernoulli-percent filter: the user wanted an
exact, well-understood algorithm (exactly K rows out), not an
approximation.

## Scope

In scope:
- New `--sample-k K` flag: reservoir-sample exactly K rows per source.
- New `--seed N` flag: optional, makes `--sample-k` reproducible.
- Fixing a pre-existing, previously out-of-scope gap: `--limit` and
  `--every-nth` are silently ignored for `sqlalchemy://` URL sources today,
  because `sqlalchemy_table_sources` never received them. `--sample-k` is
  built to work uniformly across every source type from the start,
  including `sqlalchemy://` URLs, which requires closing this gap as part
  of this work rather than inheriting it.

Out of scope (not built now):
- Percent-based (`n%` of rows) sampling — rejected in the earlier design
  pass in favor of exact-K reservoir sampling; not reopened here.
- A cheap fast-path for source types where `Source.count()` already knows
  N cheaply (xlsx, SQLAlchemy, MongoDB) — e.g. `ORDER BY RANDOM() LIMIT K`
  at the database level for SQL sources, skipping a full table read. Noted
  as a future optimization (see "Rejected/deferred approaches" below), not
  implemented now because it would only apply to 3 of ~10 source types,
  adding a second sampling algorithm to maintain for inconsistent benefit.

## Architecture

Reservoir sampling lives inside `Source`, at the same layer `--every-nth`
already occupies: filtering raw top-level records before
`reshape.walk_and_clean`/`unnest_children` ever run. This preserves the
same safety property `--every-nth` relies on — sampling after those
functions run would orphan child rows / desync FK assignment for nested
parent/child structures (confirmed unsafe when `--every-nth` was designed,
not re-litigated here).

Unlike `--every-nth`, reservoir sampling cannot decide row-by-row as it
streams. Algorithm R cannot finalize which K rows survive until the whole
stream has been seen, because any later row can still displace an earlier
one already provisionally kept. So `Source.__next__` lazily drains the
*entire* underlying generator on its first call, running Algorithm R with
an O(K) buffer (never O(N) — it holds at most K rows in memory at once,
regardless of source size), then serves the finalized K rows one at a
time on this and all subsequent calls.

This is not a memory regression relative to `--limit`/`--every-nth`:
`reshape.walk_and_clean` (`ddlgenerator.py:393`) already fully materializes
whatever `Source.__next__` yields into an in-memory list before type
inference starts, for every source type, regardless of how lazily the
underlying source could in principle stream. So the "avoid holding
everything in memory" property `--limit`/`--every-nth` provide was never
about `walk_and_clean` itself — it's about shrinking what reaches
`walk_and_clean` in the first place. `--sample-k` provides the same
property: `walk_and_clean` only ever sees the K sampled rows, never the
full N.

It *is* a time cost relative to `--limit`: `--limit` can early-exit a
lazily-streaming source (CSV/Mongo/SQLAlchemy/generators) after reading
only `limit` rows. `--sample-k` cannot — by construction, Algorithm R must
read every row of the stream once to guarantee a correct, unbiased sample.
This is an inherent property of single-pass exact-K reservoir sampling,
not an implementation shortfall. It is called out explicitly here so it
isn't mistaken for an oversight later.

## Components

### `ddlgenerator/sources.py` — `Source`

- `__init__` gains two new parameters:
  - `sample_k: int | None = None`
  - `seed: int | None = None`
- Validation in `__init__` (mirrors the existing `every_nth < 1` check):
  - `sample_k is not None and sample_k < 1` → `ValueError`
  - `sample_k is not None and (limit is not None or every_nth is not None)`
    → `ValueError` (all three are "which rows survive" strategies; combining
    them is ambiguous and rejected outright rather than guessing an
    interaction)
  - `seed is not None and sample_k is None` → `ValueError` (a seed is
    meaningless without sampling)
- New instance state: `self._rng = random.Random(seed)` (constructed once,
  in `__init__`; `random.Random(None)` seeds from OS entropy, matching the
  "optional, default to unseeded random" decision), `self._reservoir: list
  | None = None` (sentinel: reservoir not yet computed), `self.sample_k`,
  `self.seed`.
- `__next__` gains a new branch, checked before the existing
  `limit`/`every_nth` branch (mutually exclusive, so no interaction to
  reconcile):
  - If `self.sample_k` is set and `self._reservoir is None`: drain
    `self.generator` fully. For each row at 0-indexed position `i`:
    if `i < k`, append `(i, row)` to the reservoir; else draw
    `j = self._rng.randint(0, i)` and if `j < k`, replace the reservoir
    entry at position `j` with `(i, row)` (standard Algorithm R). Once the
    generator is exhausted, sort the reservoir by original index `i` and
    store just the rows (dropping the index) into `self._reservoir`, and
    set `self._reservoir_pos = 0`. Sorting back into original index order
    is a deliberate choice: sampled rows stay in the same relative order
    they appeared in the source, rather than the arbitrary order Algorithm
    R's swaps would otherwise leave them in — this matches the UX
    `--every-nth` already provides (strided rows are yielded in source
    order).
  - Once `self._reservoir` is populated, `__next__` serves
    `self._reservoir[self._reservoir_pos]` and increments the position;
    raises `StopIteration` once the position reaches `len(self._reservoir)`.
  - `self.counter` (used by `limit`) is not incremented on this path —
    `sample_k` and `limit` are mutually exclusive, so `self.counter`'s only
    consumer never runs concurrently with this branch.

### `ddlgenerator/ddlgenerator.py` — `Table`

- `__init__` gains `sample_k: int | None = None, seed: int | None = None`,
  threaded straight through to the `Source(data, limit=limit,
  every_nth=every_nth, sample_k=sample_k, seed=seed)` call at line 377.
  No other change — the existing `isinstance(data, Source): self.data =
  data` branch is unaffected; when `data` is already a `Source` (the
  `sqlalchemy://` path, see below), these `Table`-level kwargs are simply
  unused, matching how `limit`/`every_nth` already behave in that branch.

### `ddlgenerator/sources.py` — `sqlalchemy_table_sources`

- Signature becomes `sqlalchemy_table_sources(url: str, limit: int | None =
  None, every_nth: int | None = None, sample_k: int | None = None, seed:
  int | None = None) -> Iterator['Source']`.
- Each `Source(meta, table=table.name, engine=engine)` call becomes
  `Source(meta, table=table.name, engine=engine, limit=limit,
  every_nth=every_nth, sample_k=sample_k, seed=seed)`.
- This closes the pre-existing gap: today, `sqlalchemy_table_sources` never
  received `limit`/`every_nth` at all, so `Source` objects built for
  `sqlalchemy://` URLs were always unsampled regardless of CLI flags. Any
  fix has to happen here, since these are the same `Source` instances
  `console.py` later hands directly to `Table()` (see below) — by the time
  `Table.__init__` sees them, `isinstance(data, Source)` short-circuits
  before `limit`/`every_nth`/`sample_k` kwargs on `Table()` would have any
  effect.

### `ddlgenerator/console.py`

- New argparse flags:
  ```python
  parser.add_argument('--sample-k', type=int, default=None,
                      help='Randomly sample exactly K rows per source (reservoir sampling)')
  parser.add_argument('--seed', type=int, default=None,
                      help='Random seed for --sample-k reproducibility')
  ```
- New validation in `generate()`, alongside the existing `every_nth < 1`
  check:
  ```python
  if parsed.sample_k is not None and parsed.sample_k < 1:
      raise ValueError(f"--sample-k must be a positive integer, got {parsed.sample_k}")
  if parsed.sample_k is not None and (parsed.limit is not None or parsed.every_nth is not None):
      raise ValueError("--sample-k cannot be combined with --limit or --every-nth")
  if parsed.seed is not None and parsed.sample_k is None:
      raise ValueError("--seed requires --sample-k")
  ```
  This runs before the `--count-only` branch, so bad flag combinations are
  rejected even under `--count-only` (consistent with existing `every_nth`
  validation placement).
- `generate_one()`: `Table()` call gains `sample_k=args.sample_k,
  seed=args.seed`.
- `run_count_only()`: no code change needed (it never reads
  `sample_k`/`seed`, same as it already ignores `limit`/`every_nth`); its
  docstring and the `logging.info` message are updated to mention
  `--sample-k`/`--seed` alongside `--limit`/`--every-nth` as ignored flags,
  so the existing documented precedent stays accurate.
- The `sqlalchemy://` branch's call becomes
  `sqlalchemy_table_sources(datafile, limit=parsed.limit,
  every_nth=parsed.every_nth, sample_k=parsed.sample_k, seed=parsed.seed)`.

## Data flow

```
CLI args
  -> argparse-level validation (fail fast: bad type / bad combo)
  -> console.generate()
  -> Table(sample_k=, seed=)                          [file/URL/generator path]
     or sqlalchemy_table_sources(url, sample_k=, seed=) -> Table(data=<Source>)  [sqlalchemy:// path]
  -> Source(sample_k=, seed=)
  -> first Source.__next__() call: drain self.generator fully via Algorithm R
     (O(K) buffer), sort by original index, cache as self._reservoir
  -> subsequent Source.__next__() calls: serve from self._reservoir
  -> reshape.walk_and_clean / unnest_children: process only the K sampled rows
  -> type inference / DDL / INSERT generation: unchanged, operates on the
     already-sampled data exactly as it does today for --limit/--every-nth
```

## Error handling

| Condition | Behavior |
|---|---|
| `--sample-k 0` or negative | `ValueError`, both in `console.py` (CLI-facing message) and `Source.__init__` (direct-API callers) |
| `--sample-k` combined with `--limit` or `--every-nth` | `ValueError`, both layers — rejected outright, not silently resolved |
| `--seed` without `--sample-k` | `ValueError`, both layers |
| `--count-only` combined with `--sample-k`/`--seed` | `--sample-k`/`--seed` silently ignored — same existing precedent as `--limit`/`--every-nth` under `--count-only` |
| K greater than the source's total row count | No error. Algorithm R degrades gracefully: the reservoir ends up holding all N < K rows. This is correct reservoir-sampling behavior, not a bug, and is covered by a test rather than special-cased in code. |
| Empty source with `--sample-k` set | No error, yields nothing (empty reservoir), consistent with `--every-nth`'s existing behavior on an empty source |

## Testing

`tests/test_sources.py::TestSourceSampleK` (mirrors the structure of the
existing `TestSourceEveryNth`):
- exact-K sample when N > K
- keeps all N rows when N < K (no padding, no crash)
- same seed → identical output across repeated runs (determinism)
- `sample_k=0` / negative raises `ValueError`
- `seed` given without `sample_k` raises `ValueError`
- `sample_k` combined with `limit` raises `ValueError`
- `sample_k` combined with `every_nth` raises `ValueError`
- output preserves original relative source order
- empty source yields nothing

`tests/test_console.py`:
- `TestSampleKValidation` (mirrors `TestEveryNthValidation`): CLI-level
  errors for `--sample-k 0`/negative, `--sample-k` + `--limit`, `--sample-k`
  + `--every-nth`, `--seed` without `--sample-k`
- `--count-only` ignores `--sample-k`/`--seed` (extends `TestCountOnly`)
- New real-engine regression test (mirrors the pattern added for the
  `meta.bind` fix): `--limit`/`--every-nth`/`--sample-k` all actually take
  effect against a `sqlite:///` URL, guarding against silently
  reintroducing the gap this design closes

Full suite, `ruff check`, `flake8 --max-line-length=120
--ignore=E501,W503`, and `mypy` must all stay clean, matching the bar set
by the `--count-only`/`--every-nth` work and both bug fixes that preceded
this design.

## Rejected/deferred approaches

- **Sampling outside `Source`** (in `Table.__init__` or `console.py`,
  draining and sampling before constructing `Source`/`Table`): rejected.
  Breaks the "filter at `Source.__next__`, before `reshape`" precedent that
  keeps parent/child row correspondence intact for nested data, and would
  require duplicating per-source-type access logic outside `Source`.
- **Exploiting `Source.count()`'s cheap-count fast paths** (xlsx,
  SQLAlchemy, MongoDB) to compute target indices via `random.sample(range(N),
  k)` and fetch only those rows — for SQLAlchemy specifically, this could
  become `ORDER BY RANDOM() LIMIT K` at the database, avoiding a full table
  read entirely. Real potential win for those three source types, but
  deferred: it would only apply to 3 of ~10 source types, leaving Algorithm
  R as a second code path to maintain for everything else, for
  inconsistent benefit. Left as a documented future optimization, not
  built now.
