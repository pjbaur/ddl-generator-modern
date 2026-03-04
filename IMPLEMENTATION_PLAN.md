# Plan: Implement ANALYSIS.md — DDL Generator Modernization

## Context

ANALYSIS.md identified 12 areas where the ddl-generator modernization fell short: an unmaintained dependency patched in 3 places, broken SQLAlchemy 2.x output, carried-forward bugs, version mismatches, dead tests, CI gaps, and stale documentation links. Exploration also uncovered 3 additional bugs: CI doesn't trigger on the `main` branch, a duplicated `emit_db_sequence_updates` method with a query bug, and a missing `conn.commit()` in `django_models()`.

This plan addresses all 12 items plus the additional bugs in 5 phases ordered by dependency.

---

## Phase 1 — Quick fixes (version, unused dep, CI branch)

**Items:** 2 (version), 12 (dateutils), CI branch trigger

### `ddlgenerator/__init__.py`
- Replace `__version__ = '0.1.9'` with dynamic version via `importlib.metadata`:
  ```python
  from importlib.metadata import version, PackageNotFoundError
  try:
      __version__ = version("ddl-generator")
  except PackageNotFoundError:
      __version__ = "0.0.0"
  ```

### `pyproject.toml`
- Remove `"dateutils"` from `[project.dependencies]`

### `requirements.txt`
- Remove `dateutils>=0.6,<1.0`

### `.github/workflows/ci.yml`
- Add `main` to both `push.branches` and `pull_request.branches` arrays

**Verification:** `python -c "import ddlgenerator; print(ddlgenerator.__version__)"` prints `0.2.0`. Full test suite passes.

---

## Phase 2 — Replace `data_dispenser` with inline `sources.py` (Items 1, 11)

The largest change. Eliminates the unmaintained dependency entirely, removes all 3 monkey-patches, and owns the full security boundary (especially `yaml.safe_load`).

### New file: `ddlgenerator/sources.py`

Create a `Source` class that is a drop-in replacement, covering only the interface this project actually uses:

- **Constructor dispatch** (same as data_dispenser but without the dangerous paths):
  - `str` → URL (http/https) → fetch via `url_utils.safe_fetch_text()`, detect format, deserialize
  - `str` → file path (`os.path.isfile`) → open, detect extension, deserialize
  - `str` → inline data string → try JSON then YAML via `io.StringIO`
  - File-like object (has `.read`) → detect extension from `.name`, deserialize
  - `sqlalchemy.MetaData` → reflect and iterate table rows
  - `pymongo.collection.Collection` → iterate via `.find()`
  - Iterator/generator → wrap directly
  - Other → `iter(data)` fallback

- **Safe file loaders** (all inline, ~100 lines total):
  - `.json` → `json.load(f, object_pairs_hook=OrderedDict)`
  - `.yaml`/`.yml` → `yaml.safe_load(f)` (key security fix — data_dispenser uses unsafe `yaml.load`)
  - `.csv` → `csv.DictReader(f)` yielding `OrderedDict`s
  - `.html`/`.htm` → `BeautifulSoup` table extraction
  - `.xls` → `xlrd.open_workbook()` (add `xlrd` as explicit dependency)
  - `.py`, `.pickle`, `.pkl` → **not supported** (blocked by existing security policy)

- **Attributes** preserved: `table_name`, `generator`, `db_engine`, `limit`
- **Protocol**: `__iter__`, `__next__` with limit enforcement
- **`sqlalchemy_table_sources(url)`** function — uses SA 2.x API: `MetaData()` + `meta.reflect(bind=engine)`, yields `Source` per table

### Files to modify

| File | Change |
|---|---|
| `ddlgenerator/ddlgenerator.py:55` | `from data_dispenser.sources import Source` → `from ddlgenerator.sources import Source` |
| `ddlgenerator/console.py:13` | `from data_dispenser import sqlalchemy_table_sources` → `from ddlgenerator.sources import sqlalchemy_table_sources` |
| `ddlgenerator/__init__.py` | Remove entire monkey-patch block (lines 8–20) |
| `tests/conftest.py` | Remove monkey-patch block (lines 11–21) |
| `tests/test_ddlgenerator.py` | Remove monkey-patch block (lines 24–32) |
| `pyproject.toml` | Remove `data_dispenser` dep; add `xlrd>=2.0,<3.0` |
| `requirements.txt` | Same dep changes |

**Verification:** All 221 tests pass, especially `TestFiles` (validates all file format loaders against `.sql` golden files). `pip show data-dispenser` should show it's no longer installed.

---

## Phase 3 — Bug fixes (Items 5, 10, emit duplicate)

### `ddlgenerator/reshape.py`

**Bug 1** — `unused_field_name()` line 185:
```python
# self.name → str(preferences)  (self doesn't exist in a module-level function)
raise KeyError("All desired names already taken in %s" % str(preferences))
```

**Bug 2** — `unnest_child_dict()` lines 160–161 — 4 args for 3 `%s` slots:
```python
logging.error("Could not unnest child %s; %s already present in %s (child key: %s)"
              % (name, ','.join(overlap), parent_name, key))
```

### `ddlgenerator/ddlgenerator.py` — remove duplicate method

Delete `Table.emit_db_sequence_updates()` method (lines 490–508). It's a buggy duplicate of the module-level function (line 657) — its SQL query selects only 1 column instead of 2.

Update the call site in `inserts()` at line 519:
```python
# was: for seq_updater in self.emit_db_sequence_updates():
for seq_updater in emit_db_sequence_updates(self.source.db_engine):
```

### `tests/conftest.py` — table_index reset fixture

Add autouse fixture to reset `Table.table_index = 0` before each test, ensuring deterministic auto-generated table names.

### `tests/test_reshape.py`

Add tests for the two fixed bugs:
- Test that `unused_field_name` raises `KeyError` (not `NameError`) when all names are taken
- Test that `unnest_child_dict` logs error (not `TypeError`) when field name overlap occurs

**Verification:** Full test suite passes. The new reshape tests specifically exercise the previously-broken error paths.

---

## Phase 4 — Fix SQLAlchemy output and Django test (Items 3, 4)

### `ddlgenerator/ddlgenerator.py` — SQLAlchemy output

**`sqla_head`** (line 633): Fix `MetaData(bind=engine)` → SA 2.x style:
```python
sqla_head = """
import datetime
from sqlalchemy import create_engine, MetaData, ForeignKey
engine = create_engine(r'sqlite:///:memory:')
metadata = MetaData()
conn = engine.connect()"""
```

**`sqlalchemy_setup_template`** (line 385): Fix `.create()` → SA 2.x style. Reduce from 3 to 2 format args (remove table name for `.create()`):
```python
sqlalchemy_setup_template = textwrap.dedent("""
    from sqlalchemy import %s

    %s

    metadata.create_all(engine)""")
```

**`sqlalchemy()` method** (line 392): Fix the `MetaData()` replacement. SA 2.x `Table.__repr__()` outputs `MetaData()` not `MetaData(bind=None)`. Change:
```python
table_def = table_def.replace("MetaData()", "metadata")
```
Also update the template call at line 417–418 to pass 2 args instead of 3.

### `ddlgenerator/ddlgenerator.py` — Django fix

In `django_models()` (line 444), add `conn.commit()` after the `for i in u: c.execute(i)` loop and before `management.call_command('inspectdb')`.

### `pyproject.toml`

Add `"django>=4.2,<6.0"` to `[project.optional-dependencies] dev` for testing.

### `tests/test_ddlgenerator.py`

Restore `test_django` assertions — capture stdout with `contextlib.redirect_stdout` and assert the output contains `models.Model`.

### `tests/test_table.py`

Update `TestSQLAlchemyModel` assertions:
- Verify output contains `metadata = MetaData()` (no `bind=`)
- Verify output contains `metadata.create_all(engine)` (not `.create()`)
- Verify output does NOT contain `MetaData(bind=`

**Verification:** Run `python -c "from ddlgenerator.ddlgenerator import Table; t = Table([{'id':1,'name':'x'}]); print(t.sqlalchemy())"` and confirm the output is valid SA 2.x code. Run with Django installed and confirm `django_models()` produces model output.

---

## Phase 5 — Tooling, documentation, test consolidation (Items 6, 7, 8, 9)

### `.github/workflows/ci.yml` — CI lint (Item 7)

Update lint job to install and run both ruff and flake8:
```yaml
- run: pip install ruff flake8
- run: ruff check ddlgenerator/ tests/
- run: flake8 ddlgenerator/ tests/ --max-line-length=120 --ignore=E501,W503
```

### Documentation links (Item 8) — 6 stale references

| File | Line | Change |
|---|---|---|
| `README.rst` | ~164 | git clone URL → `pjbaur/ddl-generator` |
| `CONTRIBUTING.rst` | ~16 | issue URL → `pjbaur/ddl-generator` |
| `CONTRIBUTING.rst` | ~46 | issue URL → `pjbaur/ddl-generator` |
| `CONTRIBUTING.rst` | ~110 | CI URL → `pjbaur/ddl-generator` |
| `docs/installation.rst` | ~36 | git clone URL → `pjbaur/ddl-generator` |
| `docs/conf.py` | ~78 | `github_user` → `pjbaur` |

(Leave the fork attribution at README.rst:19 — that's intentional.)

### `Makefile` (Item 9)

Update broken targets:
- `test:` → `pytest --tb=short`
- `coverage:` → `pytest --cov=ddlgenerator --cov-report=term-missing --cov-report=html`
- `release:` → `python -m build && twine upload dist/*`
- `sdist:` → `python -m build --sdist`
- `lint:` → `ruff check ddlgenerator/ tests/ && flake8 ...`

### Test consolidation (Item 6)

Migrate `test_ddlgenerator.py` from unittest.TestCase to pytest style and remove duplicates:

1. **Move** URL/SSRF tests (`TestURLValidation`, `TestSSRFAdditional`) → new `tests/test_url_utils.py`
2. **Move** security tests (`TestSecurityInputValidation`, `TestFilelikeObjectSecurity`) → `tests/test_table.py` security section
3. **Move** SQL injection tests (`TestSQLInjectionPrevention`, `TestSQLInjectionAdditional`) → `tests/test_table.py`
4. **Move** `TestYAMLSafety` → `tests/test_table.py`
5. **Remove duplicates**: `TestCleanKeyName` (covered by `test_reshape.py`), `test_sqlalchemy`/`test_cushion` (covered by `test_table.py`)
6. **Keep** in `test_ddlgenerator.py` (slimmed): `TestMongo`, `TestFiles`, `TestSequenceUpdates`, `test_django`
7. **Convert** remaining unittest classes to pytest style (remove `self.assert*` → plain `assert`)

**Verification:** `pytest --tb=short` — all tests pass, count is the same (minus any exact duplicates removed). `ruff check` passes. Coverage stays ≥80%.

---

## Phase Dependencies and Parallelization

### Dependency graph

```
Phase 1 (quick fixes)
   ↓
Phase 2 (data_dispenser)  ←→  Phase 3 (bug fixes) — PARALLEL OK
   ↓                              ↓
Phase 4 (SQLAlchemy + Django) — depends on Phases 2 & 3
   ↓
Phase 5 (tooling, docs, tests) — depends on Phase 4
```

### Parallelization guidance

**Within Phase 1** — All 4 file changes are independent. Execute all edits in parallel.

**Phases 2 and 3 — Run in parallel with caveats:**
- Phase 2 and Phase 3 both touch `ddlgenerator/ddlgenerator.py` and `tests/conftest.py`. When running as parallel agents, assign them to separate worktrees to avoid merge conflicts. Merge Phase 2 first (larger change), then rebase Phase 3 on top.
- Phase 2 files: `ddlgenerator/sources.py` (new), `ddlgenerator/ddlgenerator.py` (import change at line 55), `ddlgenerator/console.py`, `ddlgenerator/__init__.py`, `tests/conftest.py` (monkey-patch removal), `tests/test_ddlgenerator.py` (monkey-patch removal), `pyproject.toml`, `requirements.txt`
- Phase 3 files: `ddlgenerator/reshape.py`, `ddlgenerator/ddlgenerator.py` (lines 490–519: emit method removal), `tests/conftest.py` (table_index fixture addition), `tests/test_reshape.py`
- **Conflict zones**: `ddlgenerator/ddlgenerator.py` (Phase 2 changes line 55, Phase 3 changes lines 490–519 — non-overlapping, clean merge expected) and `tests/conftest.py` (Phase 2 removes lines 11–21, Phase 3 adds fixture — non-overlapping, clean merge expected)

**Within Phase 4** — The SQLAlchemy output fix and Django fix touch different sections of `ddlgenerator.py` and different test files. They can be done by the same agent sequentially but should not be split across agents (they share the same file).

**Within Phase 5** — All 4 sub-items are fully independent:
- CI lint fix (`.github/workflows/ci.yml`) — independent
- Documentation links (6 files) — independent
- Makefile update — independent
- Test consolidation (test files) — independent

These 4 can be assigned to up to 4 parallel agents. The test consolidation is the largest and should get its own agent. The other 3 are small enough to combine into one agent.

### Recommended agent assignment (if using a team)

| Agent | Work | Worktree? |
|---|---|---|
| Agent A | Phase 1 (all), then Phase 2 | No (sequential on main) |
| Agent B | Phase 3 (after Phase 1 merges) | Yes (worktree, merge after Phase 2) |
| Agent C | Phase 4 (after Phases 2+3 merge) | No |
| Agent D | Phase 5: CI lint + docs + Makefile | Yes (worktree, merge after Phase 4) |
| Agent E | Phase 5: test consolidation | Yes (worktree, merge after Phase 4) |

### If working sequentially (single agent)

Execute in order: Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5. Run full test suite after each phase as a gate.

---

## Critical Files

- `ddlgenerator/ddlgenerator.py` — touched in Phases 2, 3, 4
- `ddlgenerator/sources.py` — **new file** in Phase 2
- `ddlgenerator/__init__.py` — Phases 1, 2
- `ddlgenerator/reshape.py` — Phase 3
- `ddlgenerator/console.py` — Phase 2
- `tests/conftest.py` — Phases 2, 3
- `tests/test_ddlgenerator.py` — Phases 2, 4, 5
- `tests/test_table.py` — Phases 4, 5
- `tests/test_reshape.py` — Phase 3
- `tests/test_url_utils.py` — **new file** in Phase 5
- `pyproject.toml` — Phases 1, 2, 4
- `requirements.txt` — Phases 1, 2
- `.github/workflows/ci.yml` — Phases 1, 5
- `Makefile` — Phase 5
- `README.rst`, `CONTRIBUTING.rst`, `docs/installation.rst`, `docs/conf.py` — Phase 5
