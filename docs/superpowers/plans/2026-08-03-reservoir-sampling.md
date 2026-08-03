# Reservoir-K Sampling (`--sample-k`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--sample-k K` CLI flag (with optional `--seed N`) that reservoir-samples exactly K rows per source using Algorithm R, uniformly across every source type ddlgenerator supports — including fixing the pre-existing gap where `sqlalchemy://` URL sources silently ignore `--limit`/`--every-nth` today.

**Architecture:** Reservoir sampling lives inside `Source.__next__` (`ddlgenerator/sources.py`), the same layer `--every-nth` already occupies, filtering raw top-level records before `reshape.walk_and_clean`/`unnest_children` run. Because Algorithm R can't finalize which rows survive until the whole stream has been seen, `Source.__next__` lazily drains its entire underlying generator on the first call (O(K) memory buffer), then serves the finalized, order-preserved K rows one at a time.

**Tech Stack:** Python 3.12, stdlib `random.Random` for seeded/unseeded sampling, argparse, pytest, SQLAlchemy 2.x, ruff/flake8/mypy.

## Global Constraints

- Full test suite, `ruff check ddlgenerator tests`, `flake8 ddlgenerator tests --max-line-length=120 --ignore=E501,W503`, and `mypy ddlgenerator` must all stay clean at the end of every task.
- `--sample-k`, `--limit`, and `--every-nth` are mutually exclusive — combining any two raises `ValueError`, validated both in `console.py` (CLI-facing) and `Source.__init__` (direct-API callers).
- `--seed` without `--sample-k` raises `ValueError`.
- `--count-only` continues to silently ignore `--sample-k`/`--seed`, same existing precedent as `--limit`/`--every-nth`.
- Sampled rows preserve their original relative source order (not Algorithm R's internal swap order).
- `--sample-k` reservoir-samples K rows from *each* matched file/sheet independently under glob/multi-sheet/multi-table sources, not K total combined — matching existing `--limit`/`--every-nth` per-file semantics.
- Full design rationale: `docs/superpowers/specs/2026-08-03-reservoir-sampling-design.md`.

---

### Task 1: `Source.__init__` — `sample_k`/`seed` parameters and validation

**Files:**
- Modify: `ddlgenerator/sources.py:27-37` (imports), `ddlgenerator/sources.py:342-367` (`Source.__init__`)
- Test: `tests/test_sources.py`

**Interfaces:**
- Consumes: nothing new from other tasks.
- Produces: `Source(src, limit=None, fieldnames=None, table='*', every_nth=None, engine=None, sample_k=None, seed=None)`. New instance attributes later tasks rely on: `self.sample_k: int | None`, `self.seed: int | None`, `self._rng: random.Random`, `self._reservoir: list | None` (sentinel, `None` until Task 2 populates it).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_sources.py`, in a new class placed right after `TestSourceEveryNth` (which ends at line 594, just before the `# Source.count` section comment on line 597):

```python
# ---------------------------------------------------------------------------
# Source class - sample_k (reservoir sampling)
# ---------------------------------------------------------------------------
class TestSourceSampleKValidation:
    def test_sample_k_zero_raises(self):
        with pytest.raises(ValueError, match="sample_k must be a positive integer"):
            Source(iter([{"id": 1}]), sample_k=0)

    def test_sample_k_negative_raises(self):
        with pytest.raises(ValueError, match="sample_k must be a positive integer"):
            Source(iter([{"id": 1}]), sample_k=-1)

    def test_seed_without_sample_k_raises(self):
        with pytest.raises(ValueError, match="seed requires sample_k"):
            Source(iter([{"id": 1}]), seed=42)

    def test_sample_k_combined_with_limit_raises(self):
        with pytest.raises(ValueError, match="sample_k cannot be combined with limit or every_nth"):
            Source(iter([{"id": 1}]), sample_k=1, limit=1)

    def test_sample_k_combined_with_every_nth_raises(self):
        with pytest.raises(ValueError, match="sample_k cannot be combined with limit or every_nth"):
            Source(iter([{"id": 1}]), sample_k=1, every_nth=1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sources.py::TestSourceSampleKValidation -v`
Expected: FAIL — `Source.__init__() got an unexpected keyword argument 'sample_k'`

- [ ] **Step 3: Implement the parameters and validation**

In `ddlgenerator/sources.py`, add `import random` to the import block (alphabetical order, after `import os.path` and before `import urllib.parse`, matching the existing `isort`-style grouping already in the file):

```python
import csv
import itertools
import json
import logging
import os.path
import random
import urllib.parse
```

Change the `Source.__init__` signature (currently at `ddlgenerator/sources.py:342-344`) and docstring:

```python
    def __init__(self, src: Any, limit: int | None = None,
                 fieldnames: Any = None, table: str = '*',
                 every_nth: int | None = None, engine: Any = None,
                 sample_k: int | None = None, seed: int | None = None) -> None:
        """
        Initialize a data source.

        Args:
            src: Data source (path, URL, file object, iterator, etc.)
            limit: Maximum number of rows to read
            fieldnames: For CSV, override header row
            table: For Excel/SQLAlchemy, specific table/sheet name
            every_nth: Sample every Nth row instead of reading all rows
            engine: SQLAlchemy engine to query against, required when src is
                a MetaData object (SA 2.x MetaData carries no engine of its
                own -- there is no ``meta.bind`` to fall back on)
            sample_k: Reservoir-sample exactly this many rows (Algorithm R)
            seed: Random seed for sample_k reproducibility; requires sample_k
        """
```

Add validation and new instance state right after the existing `every_nth` validation block (currently `ddlgenerator/sources.py:357-360`, the `if every_nth is not None and every_nth < 1: raise ValueError(...)` / `self.every_nth = every_nth` / `self._stride_counter = 0` lines):

```python
        self.counter = 0
        self.limit = limit
        if every_nth is not None and every_nth < 1:
            raise ValueError(f"every_nth must be a positive integer, got {every_nth}")
        self.every_nth = every_nth
        self._stride_counter = 0
        if sample_k is not None and sample_k < 1:
            raise ValueError(f"sample_k must be a positive integer, got {sample_k}")
        if sample_k is not None and (limit is not None or every_nth is not None):
            raise ValueError("sample_k cannot be combined with limit or every_nth")
        if seed is not None and sample_k is None:
            raise ValueError("seed requires sample_k")
        self.sample_k = sample_k
        self.seed = seed
        self._rng = random.Random(seed)
        self._reservoir: list | None = None
        self._reservoir_pos = 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sources.py::TestSourceSampleKValidation -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Run full suite and linters**

Run: `pytest -q && ruff check ddlgenerator tests && flake8 ddlgenerator tests --max-line-length=120 --ignore=E501,W503 && mypy ddlgenerator`
Expected: all pass, no new failures

- [ ] **Step 6: Commit**

```bash
git add ddlgenerator/sources.py tests/test_sources.py
git commit -m "feat: add sample_k/seed parameters and validation to Source"
```

---

### Task 2: `Source.__next__` — Algorithm R reservoir sampling

**Files:**
- Modify: `ddlgenerator/sources.py:643-653` (`Source.__next__`)
- Test: `tests/test_sources.py`

**Interfaces:**
- Consumes: `self.sample_k`, `self._rng`, `self._reservoir`, `self._reservoir_pos` from Task 1.
- Produces: `Source.__next__` now returns reservoir-sampled rows when `self.sample_k` is set. No new public interface — later tasks call `Source(...)` the same way.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_sources.py`, inside the `TestSourceSampleKValidation` area — add a second class right after it:

```python
class TestSourceSampleK:
    def test_sample_k_returns_exactly_k_rows_when_n_greater_than_k(self):
        data = [{"id": i} for i in range(1, 101)]  # ids 1..100
        src = Source(iter(data), sample_k=10, seed=42)
        result = list(src)
        assert len(result) == 10

    def test_sample_k_is_deterministic_with_same_seed(self):
        data = [{"id": i} for i in range(1, 101)]
        result_a = list(Source(iter(data), sample_k=10, seed=42))
        result_b = list(Source(iter(data), sample_k=10, seed=42))
        assert [r["id"] for r in result_a] == [r["id"] for r in result_b]

    def test_sample_k_keeps_all_rows_when_n_less_than_k(self):
        data = [{"id": i} for i in range(1, 6)]  # 5 rows
        src = Source(iter(data), sample_k=10, seed=1)
        result = list(src)
        assert [r["id"] for r in result] == [1, 2, 3, 4, 5]

    def test_sample_k_preserves_original_relative_order(self):
        data = [{"id": i} for i in range(1, 51)]
        src = Source(iter(data), sample_k=5, seed=7)
        result = [r["id"] for r in list(src)]
        assert result == sorted(result)

    def test_sample_k_on_empty_source_yields_nothing(self):
        src = Source(iter([]), sample_k=3, seed=1)
        assert list(src) == []

    def test_sample_k_without_seed_still_returns_k_rows(self):
        data = [{"id": i} for i in range(1, 21)]
        src = Source(iter(data), sample_k=4)
        assert len(list(src)) == 4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sources.py::TestSourceSampleK -v`
Expected: FAIL — with `sample_k` set but `__next__` not implementing it, iteration currently falls through to the plain `next(self.generator)` path in the existing `__next__`, so these tests will fail on row-count assertions (e.g. `len(result) == 10` failing because all 100 rows are returned).

- [ ] **Step 3: Implement Algorithm R in `__next__`**

Replace the existing `__next__` method (currently `ddlgenerator/sources.py:643-653`):

```python
    def __next__(self) -> Any:
        if self.sample_k is not None:
            if self._reservoir is None:
                reservoir: list[tuple[int, Any]] = []
                for i, row in enumerate(self.generator):
                    if i < self.sample_k:
                        reservoir.append((i, row))
                    else:
                        j = self._rng.randint(0, i)
                        if j < self.sample_k:
                            reservoir[j] = (i, row)
                reservoir.sort(key=lambda pair: pair[0])
                self._reservoir = [row for (_i, row) in reservoir]
                self._reservoir_pos = 0
            if self._reservoir_pos >= len(self._reservoir):
                raise StopIteration
            row = self._reservoir[self._reservoir_pos]
            self._reservoir_pos += 1
            return row
        self.counter += 1
        if self.limit and (self.counter > self.limit):
            raise StopIteration
        if not self.every_nth:
            return next(self.generator)
        while True:
            row = next(self.generator)  # StopIteration propagates naturally
            self._stride_counter += 1
            if self._stride_counter % self.every_nth == 0:
                return row
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sources.py::TestSourceSampleK tests/test_sources.py::TestSourceSampleKValidation tests/test_sources.py::TestSourceEveryNth -v`
Expected: PASS (all tests in all three classes — confirms the new branch doesn't regress `--every-nth`)

- [ ] **Step 5: Run full suite and linters**

Run: `pytest -q && ruff check ddlgenerator tests && flake8 ddlgenerator tests --max-line-length=120 --ignore=E501,W503 && mypy ddlgenerator`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add ddlgenerator/sources.py tests/test_sources.py
git commit -m "feat: implement Algorithm R reservoir sampling in Source.__next__"
```

---

### Task 3: `_multiple_sources` — forward `sample_k`/`seed` per matched subsource

**Files:**
- Modify: `ddlgenerator/sources.py:633-638` (`Source._multiple_sources`)
- Test: `tests/test_sources.py`

**Interfaces:**
- Consumes: `self.sample_k`, `self.seed` from Task 1; `Source(..., sample_k=, seed=)` constructor from Task 1/2.
- Produces: glob matches / multi-sheet xlsx / multi-table HTML each sampled to K rows independently. No new public interface.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_sources.py`, inside `TestSourceSampleK` (from Task 2):

```python
    def test_sample_k_applies_per_matched_file_in_glob(self, tmp_path):
        (tmp_path / "a.json").write_text(
            '[' + ','.join(f'{{"id": {i}}}' for i in range(1, 21)) + ']'
        )
        (tmp_path / "b.json").write_text(
            '[' + ','.join(f'{{"id": {i}}}' for i in range(101, 121)) + ']'
        )
        src = Source(str(tmp_path / "*.json"), sample_k=3, seed=5)
        result = list(src)
        assert len(result) == 6  # 3 from each of the two matched files
        from_a = [r["id"] for r in result if r["id"] < 100]
        from_b = [r["id"] for r in result if r["id"] >= 100]
        assert len(from_a) == 3
        assert len(from_b) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sources.py::TestSourceSampleK::test_sample_k_applies_per_matched_file_in_glob -v`
Expected: FAIL — `_multiple_sources` does not forward `sample_k`/`seed`, so each subsource is built without sampling and the parent's own `sample_k` is never applied to the already-chained combined generator either (the parent's `_reservoir` logic in `__next__` would need `self.generator` to be the raw chained iterator, but since `self.sample_k` was never cleared, behavior is undefined/wrong — the test will fail on the row-count assertions)

- [ ] **Step 3: Implement forwarding**

Replace `_multiple_sources` (currently `ddlgenerator/sources.py:633-638`):

```python
    def _multiple_sources(self, sources: Iterable) -> None:
        """Combine multiple sources into one iterator."""
        subsources = [Source(s, limit=self.limit, every_nth=self.every_nth,
                              sample_k=self.sample_k, seed=self.seed) for s in sources]
        self.limit = None  # limit already applied to subsources
        self.every_nth = None  # stride already applied to subsources
        self.sample_k = None  # reservoir sampling already applied to subsources
        self.generator = itertools.chain.from_iterable(subsources)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sources.py::TestSourceSampleK -v`
Expected: PASS (all tests in the class, including the new glob test)

- [ ] **Step 5: Run full suite and linters**

Run: `pytest -q && ruff check ddlgenerator tests && flake8 ddlgenerator tests --max-line-length=120 --ignore=E501,W503 && mypy ddlgenerator`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add ddlgenerator/sources.py tests/test_sources.py
git commit -m "feat: forward sample_k/seed to subsources in _multiple_sources"
```

---

### Task 4: `sqlalchemy_table_sources` — thread `limit`/`every_nth`/`sample_k`/`seed` through

**Files:**
- Modify: `ddlgenerator/sources.py:727-735` (`sqlalchemy_table_sources`)
- Test: `tests/test_sources.py`

**Interfaces:**
- Consumes: `Source(meta, table=, engine=, limit=, every_nth=, sample_k=, seed=)` from Tasks 1-2.
- Produces: `sqlalchemy_table_sources(url: str, limit: int | None = None, every_nth: int | None = None, sample_k: int | None = None, seed: int | None = None) -> Iterator['Source']`. Task 7 (console.py) calls this new signature.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_sources.py`, inside `TestSqlalchemyTableSources` (which currently ends after `test_reads_rows_from_a_real_engine`, right before `test_raises_import_error_when_sqlalchemy_none`):

```python
    def test_limit_applies_to_sqlalchemy_url_source(self, tmp_path):
        """Regression guard: sqlalchemy_table_sources previously never
        received limit/every_nth at all, so --limit/--every-nth were
        silently no-ops for sqlalchemy:// URLs."""
        db_path = tmp_path / "test.db"
        engine = sqlalchemy.create_engine(f"sqlite:///{db_path}")
        with engine.connect() as connection:
            connection.execute(sqlalchemy.text("CREATE TABLE t (id INTEGER)"))
            connection.execute(sqlalchemy.text(
                "INSERT INTO t VALUES (1), (2), (3), (4), (5)"
            ))
            connection.commit()

        sources = list(sqlalchemy_table_sources(f"sqlite:///{db_path}", limit=2))

        assert len(list(sources[0])) == 2

    def test_every_nth_applies_to_sqlalchemy_url_source(self, tmp_path):
        """Same regression guard as test_limit_applies_to_sqlalchemy_url_source,
        for --every-nth."""
        db_path = tmp_path / "test.db"
        engine = sqlalchemy.create_engine(f"sqlite:///{db_path}")
        with engine.connect() as connection:
            connection.execute(sqlalchemy.text("CREATE TABLE t (id INTEGER)"))
            connection.execute(sqlalchemy.text(
                "INSERT INTO t VALUES " + ", ".join(f"({i})" for i in range(1, 11))
            ))
            connection.commit()

        sources = list(sqlalchemy_table_sources(f"sqlite:///{db_path}", every_nth=3))

        rows = list(sources[0])
        assert [tuple(row) for row in rows] == [(3,), (6,), (9,)]

    def test_sample_k_applies_to_sqlalchemy_url_source(self, tmp_path):
        db_path = tmp_path / "test.db"
        engine = sqlalchemy.create_engine(f"sqlite:///{db_path}")
        with engine.connect() as connection:
            connection.execute(sqlalchemy.text("CREATE TABLE t (id INTEGER)"))
            connection.execute(sqlalchemy.text(
                "INSERT INTO t VALUES " + ", ".join(f"({i})" for i in range(1, 21))
            ))
            connection.commit()

        sources = list(sqlalchemy_table_sources(f"sqlite:///{db_path}", sample_k=5, seed=3))

        assert len(list(sources[0])) == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sources.py::TestSqlalchemyTableSources::test_limit_applies_to_sqlalchemy_url_source tests/test_sources.py::TestSqlalchemyTableSources::test_every_nth_applies_to_sqlalchemy_url_source tests/test_sources.py::TestSqlalchemyTableSources::test_sample_k_applies_to_sqlalchemy_url_source -v`
Expected: FAIL — `sqlalchemy_table_sources() got an unexpected keyword argument 'limit'`

- [ ] **Step 3: Implement forwarding**

Replace `sqlalchemy_table_sources` (currently `ddlgenerator/sources.py:727-735`):

```python
def sqlalchemy_table_sources(url: str, limit: int | None = None,
                             every_nth: int | None = None,
                             sample_k: int | None = None,
                             seed: int | None = None) -> Iterator['Source']:
    """
    Yield Source objects for each table in a SQLAlchemy database.

    Uses SQLAlchemy 2.x API (MetaData without bind parameter).

    Args:
        url: SQLAlchemy database URL
        limit: Maximum number of rows to read per table
        every_nth: Sample every Nth row per table instead of reading all rows
        sample_k: Reservoir-sample exactly this many rows per table
        seed: Random seed for sample_k reproducibility

    Yields:
        Source objects, one per table
    """
    if sqlalchemy is None:
        raise ImportError('sqlalchemy not installed')

    engine = sqlalchemy.create_engine(url)
    meta = sqlalchemy.MetaData()
    meta.reflect(bind=engine)

    for table in meta.sorted_tables:
        yield Source(meta, table=table.name, engine=engine, limit=limit,
                     every_nth=every_nth, sample_k=sample_k, seed=seed)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sources.py::TestSqlalchemyTableSources -v`
Expected: PASS (all tests in the class, including the pre-existing mocked test and the two new ones)

- [ ] **Step 5: Run full suite and linters**

Run: `pytest -q && ruff check ddlgenerator tests && flake8 ddlgenerator tests --max-line-length=120 --ignore=E501,W503 && mypy ddlgenerator`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add ddlgenerator/sources.py tests/test_sources.py
git commit -m "feat: thread limit/every_nth/sample_k/seed through sqlalchemy_table_sources"
```

---

### Task 5: `Table.__init__` — `sample_k`/`seed` passthrough to `Source`

**Files:**
- Modify: `ddlgenerator/ddlgenerator.py:325-343` (`Table.__init__` signature and docstring), `ddlgenerator/ddlgenerator.py:377` (the `Source(...)` construction call)
- Test: `tests/test_table.py`

**Interfaces:**
- Consumes: `Source(data, limit=, every_nth=, sample_k=, seed=)` from Task 1/2.
- Produces: `Table(data, ..., sample_k: int | None = None, seed: int | None = None)`. Task 7 (console.py `generate_one`) calls this new signature.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_table.py`, as a new class placed right after `TestSqlCombined` (which ends at line 201, just before the `# _validate_data_source` section comment on line 204):

```python
# ---------------------------------------------------------------------------
# sample_k / seed passthrough
# ---------------------------------------------------------------------------
class TestSampleKWiring:
    def test_sample_k_reduces_row_count(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text(
            '[' + ','.join(f'{{"id": {i}}}' for i in range(1, 51)) + ']'
        )
        tbl = Table(str(data_file), sample_k=5, seed=42)
        assert len(tbl.data) == 5
```

Check the import block at the top of `tests/test_table.py:18-34` already imports `Table` from `ddlgenerator.ddlgenerator` — no new import needed.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_table.py::TestSampleKWiring -v`
Expected: FAIL — `Table.__init__() got an unexpected keyword argument 'sample_k'`

- [ ] **Step 3: Implement the passthrough**

In `ddlgenerator/ddlgenerator.py`, change the `Table.__init__` signature (currently ending at line 342-343 with `limit: int | None = None, every_nth: int | None = None,`):

```python
        limit: int | None = None,
        every_nth: int | None = None,
        sample_k: int | None = None,
        seed: int | None = None,
    ) -> None:
```

Change the `Source(...)` construction call (currently `ddlgenerator/ddlgenerator.py:377`):

```python
            self.data = Source(data, limit=limit, every_nth=every_nth,
                              sample_k=sample_k, seed=seed)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_table.py::TestSampleKWiring -v`
Expected: PASS

- [ ] **Step 5: Run full suite and linters**

Run: `pytest -q && ruff check ddlgenerator tests && flake8 ddlgenerator tests --max-line-length=120 --ignore=E501,W503 && mypy ddlgenerator`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add ddlgenerator/ddlgenerator.py tests/test_table.py
git commit -m "feat: thread sample_k/seed through Table.__init__"
```

---

### Task 6: `console.py` — `--sample-k`/`--seed` flags and validation

**Files:**
- Modify: `ddlgenerator/console.py:35-38` (argparse flags), `ddlgenerator/console.py:129-130` (validation in `generate()`)
- Test: `tests/test_console.py`

**Interfaces:**
- Consumes: nothing new from other tasks (pure argparse + validation, no wiring to `Table`/`Source` yet — that's Task 7).
- Produces: `parsed.sample_k: int | None`, `parsed.seed: int | None` available on the parsed namespace. Task 7 reads these.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_console.py`, as a new class placed right after `TestEveryNthValidation` (which ends at line 196, just before the blank line and `class TestCountOnly` on line 198):

```python
class TestSampleKValidation:
    def test_sample_k_zero_raises(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}]')
        with pytest.raises(ValueError, match="--sample-k must be a positive integer"):
            generate(f"--sample-k 0 postgresql {data_file}")

    def test_sample_k_negative_raises(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}]')
        with pytest.raises(ValueError, match="--sample-k must be a positive integer"):
            generate(f"--sample-k -3 postgresql {data_file}")

    def test_sample_k_combined_with_limit_raises(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}]')
        with pytest.raises(ValueError, match="--sample-k cannot be combined with --limit or --every-nth"):
            generate(f"--sample-k 1 --limit 1 postgresql {data_file}")

    def test_sample_k_combined_with_every_nth_raises(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}]')
        with pytest.raises(ValueError, match="--sample-k cannot be combined with --limit or --every-nth"):
            generate(f"--sample-k 1 --every-nth 1 postgresql {data_file}")

    def test_seed_without_sample_k_raises(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}]')
        with pytest.raises(ValueError, match="--seed requires --sample-k"):
            generate(f"--seed 42 postgresql {data_file}")
```

Check `tests/test_console.py`'s top imports already include `pytest` and `generate` — no new import needed (verify by checking the top of the file if unsure).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_console.py::TestSampleKValidation -v`
Expected: FAIL — `error: unrecognized arguments: --sample-k 0` (argparse rejects the unknown flag)

- [ ] **Step 3: Implement the flags and validation**

Add two new argparse arguments in `ddlgenerator/console.py`, right after the existing `--every-nth` argument (currently lines 36-37):

```python
parser.add_argument('--every-nth', type=int, default=None,
                    help='Sample every Nth row instead of reading all rows')
parser.add_argument('--sample-k', type=int, default=None,
                    help='Randomly sample exactly K rows per source (reservoir sampling)')
parser.add_argument('--seed', type=int, default=None,
                    help='Random seed for --sample-k reproducibility')
```

Add validation in `generate()`, right after the existing `every_nth` validation (currently lines 129-130):

```python
    if parsed.every_nth is not None and parsed.every_nth < 1:
        raise ValueError(f"--every-nth must be a positive integer, got {parsed.every_nth}")
    if parsed.sample_k is not None and parsed.sample_k < 1:
        raise ValueError(f"--sample-k must be a positive integer, got {parsed.sample_k}")
    if parsed.sample_k is not None and (parsed.limit is not None or parsed.every_nth is not None):
        raise ValueError("--sample-k cannot be combined with --limit or --every-nth")
    if parsed.seed is not None and parsed.sample_k is None:
        raise ValueError("--seed requires --sample-k")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_console.py::TestSampleKValidation tests/test_console.py::TestEveryNthValidation -v`
Expected: PASS (both classes)

- [ ] **Step 5: Run full suite and linters**

Run: `pytest -q && ruff check ddlgenerator tests && flake8 ddlgenerator tests --max-line-length=120 --ignore=E501,W503 && mypy ddlgenerator`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add ddlgenerator/console.py tests/test_console.py
git commit -m "feat: add --sample-k/--seed CLI flags with validation"
```

---

### Task 7: `console.py` — wire `--sample-k`/`--seed` into generation, fix sqlalchemy gap

**Files:**
- Modify: `ddlgenerator/console.py:65-68` (`generate_one`'s `Table(...)` call), `ddlgenerator/console.py:83-95` (`run_count_only` docstring/log), `ddlgenerator/console.py:145-162` (sqlalchemy branch in `generate()`)
- Test: `tests/test_console.py`

**Interfaces:**
- Consumes: `parsed.sample_k`, `parsed.seed` from Task 6; `Table(..., sample_k=, seed=)` from Task 5; `sqlalchemy_table_sources(url, limit=, every_nth=, sample_k=, seed=)` from Task 4.
- Produces: end-to-end `--sample-k`/`--seed` support from the CLI, for both file/URL sources and `sqlalchemy://` URLs. No further tasks depend on this.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_console.py`, as a new class placed right after `TestCountOnly` (which ends at line 219, just before the `# SQLAlchemy URL input path` section comment on line 222):

```python
class TestSampleKGeneration:
    def test_sample_k_reduces_insert_count(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text(
            '[' + ','.join(f'{{"id": {i}}}' for i in range(1, 51)) + ']'
        )
        out = io.StringIO()
        generate(f"--sample-k 5 --seed 1 -i postgresql {data_file}", file=out)
        output = out.getvalue()
        assert output.count("INSERT INTO") == 5

    def test_count_only_ignores_sample_k(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}, {"id": 2}, {"id": 3}]')
        out = io.StringIO()
        generate(f"--sample-k 1 postgresql {data_file} --count-only", file=out)
        assert "TOTAL: 3" in out.getvalue()

    def test_sample_k_applies_to_sqlalchemy_url(self, tmp_path):
        import sqlalchemy as sa
        db_path = tmp_path / "test.db"
        engine = sa.create_engine(f"sqlite:///{db_path}")
        with engine.connect() as connection:
            connection.execute(sa.text("CREATE TABLE t (id INTEGER)"))
            connection.execute(sa.text(
                "INSERT INTO t VALUES " + ", ".join(f"({i})" for i in range(1, 21))
            ))
            connection.commit()
        out = io.StringIO()
        generate(f"--sample-k 5 --seed 1 -i postgresql sqlite:///{db_path}", file=out)
        assert out.getvalue().count("INSERT INTO") == 5
```

`tests/test_console.py` already imports `io` and `generate` at the top (used by the existing `TestCountOnly` class) — no new imports needed there. `sqlalchemy` is a hard dependency of this project (`pyproject.toml:28`, `sqlalchemy>=2.0,<3.0`, not behind an optional extra like `pymongo`/`xlrd`/`openpyxl`), so the inline `import sqlalchemy as sa` shown above needs no `skipif` guard — every existing sqlalchemy-related test in `tests/test_console.py` (e.g. `test_generate_one_sqlalchemy`, `test_sqlalchemy_url_generates_ddl`) already runs unconditionally for the same reason.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_console.py::TestSampleKGeneration -v`
Expected: FAIL — `test_sample_k_reduces_insert_count` and `test_sample_k_applies_to_sqlalchemy_url` fail because `Table()` never receives `sample_k`/`seed` (all 50/20 rows come through instead of 5); `test_count_only_ignores_sample_k` passes already (no code change needed for that one, included here as a regression guard for Task 6's flags not breaking `--count-only`)

- [ ] **Step 3: Implement the wiring**

In `ddlgenerator/console.py`, change `generate_one`'s `Table(...)` call (currently lines 65-68):

```python
    table = Table(tbl, table_name=table_name, varying_length_text=args.text, uniques=args.uniques,
                  pk_name=args.key, force_pk=args.force_key, reorder=args.reorder, data_size_cushion=args.cushion,
                  save_metadata_to=args.save_metadata_to, metadata_source=args.use_metadata_from,
                  loglevel=args.log, limit=args.limit, every_nth=args.every_nth,
                  sample_k=args.sample_k, seed=args.seed)
```

Update `run_count_only`'s docstring and log message (currently lines 83-95) to keep the documented ignore-list accurate:

```python
def run_count_only(args: argparse.Namespace, file: IO[str] | None = None) -> None:
    """
    Report row counts per source and exit without generating DDL/INSERTs.

    Always reports the true total record count, ignoring --limit/--every-nth/
    --sample-k/--seed (this mode exists to help pick a sampling value for a
    subsequent run). xlsx, SQLAlchemy, and MongoDB sources use a cheap count;
    CSV/JSON/YAML/HTML/xls and generator sources must be fully read to count
    them.
    """
    logging.info(
        "--count-only: xlsx, SQLAlchemy, and MongoDB sources use a cheap count; "
        "CSV/JSON/YAML/HTML/xls and generator sources must be fully read to count them."
    )
```

Change the sqlalchemy branch in `generate()` (currently line 149, `for tbl in sqlalchemy_table_sources(datafile):`):

```python
            for tbl in sqlalchemy_table_sources(datafile, limit=parsed.limit,
                                                every_nth=parsed.every_nth,
                                                sample_k=parsed.sample_k,
                                                seed=parsed.seed):
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_console.py -v`
Expected: PASS (full file, including `TestSampleKGeneration` and every pre-existing class — confirms no regression to `--count-only`, `--every-nth`, or the sqlalchemy URL path)

- [ ] **Step 5: Run full suite and linters**

Run: `pytest -q && ruff check ddlgenerator tests && flake8 ddlgenerator tests --max-line-length=120 --ignore=E501,W503 && mypy ddlgenerator`
Expected: all pass, 0 failures, 0 new lint/type errors

- [ ] **Step 6: Manual CLI smoke test**

Run:
```bash
source .venv/bin/activate
python - <<'EOF'
import json
data = [{"id": i, "name": f"row{i}"} for i in range(1, 101)]
open("/tmp/sample_k_smoke.json", "w").write(json.dumps(data))
EOF
ddlgenerator postgresql /tmp/sample_k_smoke.json --sample-k 5 --seed 1 -i
rm -f /tmp/sample_k_smoke.json
```
Expected: `CREATE TABLE` output followed by exactly 5 `INSERT INTO` statements, `id` values a subset of 1-100 in ascending order.

- [ ] **Step 7: Commit**

```bash
git add ddlgenerator/console.py tests/test_console.py
git commit -m "feat: wire --sample-k/--seed into generation, fix sqlalchemy limit/every-nth gap"
```

---

### Task 8: Documentation — `docs/usage.rst` and `README.rst`

**Files:**
- Modify: `docs/usage.rst:110-113` (right after the existing `--every-nth` entry, before the `-c`/`--cushion` entry)
- Modify: `README.rst:102-103` (right after the existing `--every-nth EVERY_NTH` entry, before the `-c CUSHION` entry)

**Interfaces:**
- Consumes: nothing (documentation only).
- Produces: nothing consumed by other tasks; this is the last task.

- [ ] **Step 1: Add the entries to `docs/usage.rst`**

Insert after the existing `--every-nth` block (currently `docs/usage.rst:110-113`, ending with `then capping the surviving rows.` right before the `` ``-c``, ``--cushion`` `` entry):

```rst
``--every-nth``
    Sample every Nth row instead of reading all rows (e.g. ``--every-nth 3``
    keeps rows 3, 6, 9, ...). Combines with ``--limit`` by striding first,
    then capping the surviving rows.

``--sample-k``
    Reservoir-sample exactly K rows per source (Algorithm R) instead of
    reading all rows. Gives an unbiased random sample without needing to
    know the source's total row count upfront. Cannot be combined with
    ``--limit`` or ``--every-nth``. Applies K independently per matched
    file when a source expands to multiple files (glob patterns) or
    multiple sheets/tables (xlsx, HTML).

``--seed``
    Random seed for ``--sample-k`` reproducibility. Optional; omit for an
    unseeded (non-reproducible) sample. Requires ``--sample-k``.
```

- [ ] **Step 2: Add the entries to `README.rst`**

Insert after the existing `--every-nth EVERY_NTH` line (currently `README.rst:101-103`, ending right before the `` -c CUSHION, --cushion CUSHION `` entry):

```rst
      --limit LIMIT         Max number of rows to read from each source file
      --every-nth EVERY_NTH
                            Sample every Nth row instead of reading all rows
      --sample-k SAMPLE_K   Randomly sample exactly K rows per source
                            (reservoir sampling)
      --seed SEED           Random seed for --sample-k reproducibility
```

- [ ] **Step 3: Verify against actual `--help` output**

Run: `source .venv/bin/activate && ddlgenerator --help`
Expected: `--sample-k SAMPLE_K` and `--seed SEED` lines appear with help text matching what was just added to `README.rst` word-for-word (same verification approach used for the `--count-only`/`--every-nth` docs in commit `073ce90`)

- [ ] **Step 4: Commit**

```bash
git add docs/usage.rst README.rst
git commit -m "docs: document --sample-k and --seed flags"
```
