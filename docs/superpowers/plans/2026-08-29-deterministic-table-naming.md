# Deterministic Table Naming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unnamed tables always get the same name in every process — no class-level counters.

**Architecture:** Replace `Table.table_index` and `Source.table_count` global counters with constant fallback names (`generated_table`, `Table`). Replace the `startswith('generated_table')` string sniff with an explicit `_name_generated` flag. The private `_used_table_names` pool stays the sole deduplication mechanism.

**Tech Stack:** Python 3.12, pytest, SQLAlchemy 2.x. Spec: `docs/superpowers/specs/2026-08-29-table-naming-design.md`.

## Global Constraints

- No global mutable state for naming (no class-level counters).
- Unnamed `Table` from bare Python data: always `generated_table`.
- Unnamed `Source` placeholder: always `Table`.
- Pool suffix style unchanged: `name`, `name_1`, `name_2` with a warning.
- `_used_table_names` stays private (leading underscore).
- Test edits are part of an intentional, user-approved behavior change (spec 2026-08-29) — notably `tests/test_sources.py` asserting `Table0` becomes `Table`.
- Never weaken an unrelated test to make code pass.

---

### Task 1: Table — constant fallback name + generated flag

**Files:**
- Modify: `ddlgenerator/ddlgenerator.py:308` (remove `table_index` attr), `ddlgenerator/ddlgenerator.py:314-325` (`_find_table_name`), `ddlgenerator/ddlgenerator.py:392-394` (override sniff)
- Modify: `tests/conftest.py:21-27` (delete `reset_table_index` fixture)
- Test: `tests/test_table.py` (class `TestSQLAlchemyInserts`, after `test_no_pool_means_no_renaming` around line 477)

**Interfaces:**
- Consumes: `Table.__init__` sets `self.table_name = table_name or ''` before calling `self._find_table_name(data)` (existing, unchanged).
- Produces: `Table._name_generated: bool` — True only when no name came from caller, Mongo collection, or file basename. Later code (`ddlgenerator.py:392`) and Task 3's grep sweep rely on it. `Table.table_index` no longer exists.

- [ ] **Step 1: Write the failing tests**

Append to `TestSQLAlchemyInserts` in `tests/test_table.py`:

```python
    def test_unnamed_table_name_is_constant_across_instances(self):
        """Table names cannot depend on how many Tables the process made."""
        first = Table([{"name": "a"}])
        second = Table([{"name": "b"}])
        assert first.table_name == "generated_table"
        assert second.table_name == "generated_table"

    def test_unnamed_tables_dedupe_through_the_pool(self):
        """The pool, not a global counter, keeps pooled names distinct."""
        used = set()
        first = Table([{"name": "a"}], _used_table_names=used)
        second = Table([{"name": "b"}], _used_table_names=used)
        assert (first.table_name, second.table_name) == \
            ("generated_table", "generated_table_1")

    def test_name_generated_flag_tracks_name_origin(self):
        assert Table([{"name": "a"}])._name_generated is True
        assert Table([{"name": "a"}],
                     table_name="explicit")._name_generated is False

    def test_file_named_generated_table_is_not_treated_as_auto_named(
            self, tmp_path):
        """A derived basename wins; the flag, not the string shape,
        decides what counts as auto-named."""
        import yaml as yaml_module
        path = tmp_path / "generated_table.yaml"
        path.write_text(yaml_module.safe_dump([{"name": "a"}]))
        tbl = Table(str(path))
        assert tbl.table_name == "generated_table"
        assert tbl._name_generated is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_table.py -k "constant_across or dedupe_through or name_generated_flag" -v`
Expected: FAIL — `constant_across` sees `generated_table0`/`generated_table1`; `dedupe_through` sees `generated_table0`/`generated_table1`; `name_generated_flag` fails with `AttributeError: _name_generated`.

- [ ] **Step 3: Implement**

In `ddlgenerator/ddlgenerator.py`, replace lines 308-325:

```python
    table_name: str
    metadata: sa.MetaData
    comments: dict[str, str]
    _name_generated: bool

    def _find_table_name(self, data: Any) -> None:
        if not self.table_name:
            if pymongo and isinstance(data, pymongo.collection.Collection):
                self.table_name = data.name
            elif hasattr(data, 'lower'):  # duck-type string test
                if os.path.isfile(data):
                    (file_path, file_extension) = os.path.splitext(data)
                    self.table_name = os.path.split(file_path)[1].lower()
        self._name_generated = not self.table_name
        self.table_name = (self.table_name or 'generated_table')
        self.table_name = reshape.clean_key_name(self.table_name)
```

(The `table_index: int = 0` class attribute, the `or f'generated_table{Table.table_index}'` fallback, and the `Table.table_index += 1` increment are all gone.)

Replace the override at lines 392-394:

```python
        if (self._name_generated
                and hasattr(self.data, 'table_name')):
            self.table_name = self.data.table_name
```

Behavior note: an explicit `table_name` that merely *starts with* `generated_table` no longer gets clobbered by the source's name — the flag, not string shape, decides.

Delete the now-broken fixture in `tests/conftest.py` (lines 21-27):

```python
@pytest.fixture(autouse=True)
def reset_table_index():
    """Reset Table.table_index before each test for deterministic table names."""
    from ddlgenerator.ddlgenerator import Table
    Table.table_index = 0
    yield
    Table.table_index = 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_table.py -v`
Expected: PASS (whole file — proves no other test depended on the counter).

- [ ] **Step 5: Commit**

```bash
git add ddlgenerator/ddlgenerator.py tests/test_table.py tests/conftest.py
git commit -m "fix: name unnamed tables deterministically via flag, not counter"
```

---

### Task 2: Source — constant placeholder

**Files:**
- Modify: `ddlgenerator/sources.py:361` (remove `table_count`), `ddlgenerator/sources.py:426` (placeholder), `ddlgenerator/sources.py:432` (increment)
- Modify: `tests/conftest.py:41-47` (delete `reset_source_table_count` fixture)
- Test: `tests/test_sources.py` (`test_source_is_generator_without_name`, line ~338)

**Interfaces:**
- Consumes: `Source.__init__` dispatch overwrites `self.table_name` for file/URL/mongo/sqla/generator-with-name sources (existing, unchanged).
- Produces: `Source.table_name` placeholder is the constant `Table` when nothing derives a name; `Source.table_count` no longer exists. Flows into `Table` via the Task 1 override only when the Table itself is unnamed.

- [ ] **Step 1: Update the existing test and add a determinism test**

In `tests/test_sources.py`, change `test_source_is_generator_without_name` (line ~338) — intentional behavior change per spec:

```python
    def test_source_is_generator_without_name(self):
        """Generator without name attribute should get default table name."""
        def gen():
            yield {"a": 1}
        src = Source(gen())
        assert src.table_name == "Table"
```

Add next to it:

```python
    def test_default_table_name_is_constant_across_sources(self):
        """The placeholder cannot depend on process history."""
        def gen():
            yield {"a": 1}
        first = Source(gen())
        second = Source(gen())
        assert first.table_name == "Table"
        assert second.table_name == "Table"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sources.py -k "generator_without_name or constant_across_sources" -v`
Expected: FAIL — `generator_without_name` sees `Table0`; `constant_across_sources` sees `Table0`/`Table1`.

- [ ] **Step 3: Implement**

In `ddlgenerator/sources.py`:

Delete line 361 (`    table_count = 0`).

Line 426 becomes:

```python
        self.table_name = 'Table'
```

Delete line 432 (`        Source.table_count += 1`).

Delete the now-broken fixture in `tests/conftest.py` (lines 41-47):

```python
@pytest.fixture(autouse=True)
def reset_source_table_count():
    """Reset Source.table_count before each test for deterministic table names."""
    from ddlgenerator.sources import Source
    Source.table_count = 0
    yield
    Source.table_count = 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sources.py tests/test_table.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ddlgenerator/sources.py tests/test_sources.py tests/conftest.py
git commit -m "fix: constant Source table-name placeholder, drop table_count"
```

---

### Task 3: Sweep, docs, full gate

**Files:**
- Modify: `DEV-NOTES.md` (close "Still open" counter item)

**Interfaces:**
- Consumes: Tasks 1-2 complete — `Table.table_index` and `Source.table_count` gone.
- Produces: clean repo state, PR ready.

- [ ] **Step 1: Grep sweep for dangling references**

Run: `grep -rn "table_index\|table_count\|Table[0-9]\|generated_table[0-9]" ddlgenerator/ tests/ docs/*.rst README.rst`
Expected: no matches (raw `Table0`-style names, counters, or numbered fallbacks). If hits appear, fix them in this task before committing.

- [ ] **Step 2: Update DEV-NOTES.md**

In the "Still open" list, delete the `Table names come from a global counter...` bullet. Bump the snapshot date line to today.

- [ ] **Step 3: Full verification**

Run: `pytest -m "not postgres" --tb=short`
Expected: all pass (baseline was 520 passed, 1 skipped; count may shift +4 from new tests).

Run: `ruff check ddlgenerator tests && mypy ddlgenerator/`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add DEV-NOTES.md
git commit -m "docs: close table-name counter backlog item"
```

- [ ] **Step 5: Push and open PR**

```bash
git push -u origin fix/deterministic-table-naming
```

Open PR targeting `main`; note the intentional test change (`Table0` to `Table`) in the description per the code-standards rule.
