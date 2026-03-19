# ddl-generator-modern: Improvement Plan

Audit performed 2026-03-18. Project is stable (219/220 tests pass, clean working tree on `main`).

---

## High Priority

### [x] 1. Bug: Unbound variable in `console.py:105`
- If `sqlalchemy_table_sources()` yields no tables, `t` is never assigned -> `NameError` at runtime.

### [x] 2. Library logging anti-pattern (`ddlgenerator.py:65`)
- `logging.basicConfig(filename='ddlgenerator.log', filemode='w')` at module level silently creates a log file in the caller's working directory and clobbers their logging config. Libraries should never configure the root logger.

### [x] 3. Resource leak in `sources.py:391`
- Files opened via `_source_is_path()` are stored in `self.file` but never closed. No `close()` method or context manager support on `Source`.

### [x] 4. Temp file leak in `ddlgenerator.py:438-458`
- `django_models()` creates a temp SQLite DB (`generated_db.db`) that's left on disk if any step fails. No `try/finally` cleanup.

---

## Medium Priority

### [x] 5. Test coverage gaps
- `sources.py` has no dedicated test file — ~15 functions/methods are untested:
  - `_ensure_rows()`, `_ordered_yaml_load()`, `_json_loader()`, `_interpret_fieldnames()`, `_table_score()`, `_html_to_odicts()`, `NamedIter`, `filename_from_url()`, `Source._source_is_generator()`, `Source._source_is_mongo()`, `Source._source_is_sqlalchemy_metadata()`, `Source._deserialize()`, `Source._source_is_url()`, `Source._source_is_excel()`, `Source._multiple_sources()`, `sqlalchemy_table_sources()`
- `console.py` CLI paths (SQLAlchemy URL input, metadata round-trip) are untested.
- `sqla_inserter_call()` (ddlgenerator.py:622) is completely untested.
- `Table._dropper()` dialect matrix (sybase, oracle, mssql, drizzle) is untested.
- `Table._saveable_metadata()` round-trip is untested.

### [x] 6. Zero type annotations
- No type hints anywhere in production code.
- `mypy` is configured but `ignore_outcome = true` in tox, so it's never enforced.
- Best candidates to start: `url_utils.py` (simple types), `typehelpers.py` (complex unions, highest value), `Table.__init__()` (15 params).

### [x] 7. Overly broad exception handling
- `sources.py:318,326` — `except Exception: pass` silently swallows all errors during source dispatch.
- `typehelpers.py:97` — `except Exception: pass` hides date-parsing failures.
- `url_utils.py:157` — `except Exception: return False` broader than necessary.
- `sources.py:374` — `except Exception as e` in `_deserialize()` catches too broadly (won't propagate `KeyboardInterrupt`-type signals).

### [x] 8. Dead code / stale logic
- `ddlgenerator.py:316` — `if True` clause is dead noise in column loop.
- `ddlgenerator.py:460` — `_datetime_format = {}` is always empty, making branch at line 478 unreachable.
- `sources.py:28,34` — unused imports (`BytesIO`, `re`).
- `ddlgenerator.py:622-636` — `sqla_inserter_call()` and `insert_test_rows()` are confusingly structured (real function defined only as template body).

---

## Low-Medium Priority

### [x] 9. Packaging cleanup
- `setup.py` shim is unnecessary — modern pip (21.3+) handles `pyproject.toml` editable installs.
- `requirements.txt` / `requirements-dev.txt` duplicate `pyproject.toml` and are out of sync (e.g., tox version bounds differ).
- CI (`ci.yml:5`) triggers on dead `modernize` branch.

### [x] 10. Documentation gaps
- `docs/usage.rst` is an empty stub (just `import ddlgenerator`).
- `HISTORY.rst:63` still references removed `data_dispenser` dependency.
- `README.rst:33` example output is stale/inaccurate (column name casing mismatch).
- Many public functions lack docstrings: `_dump()`, `KeyAlreadyExists`, `Table._find_table_name()`, `Table._dropper()`, `Table._fill_metadata_from_sample()`, `Table._determine_types()`, `Table.__str__()`, `is_scalar()`, `_places_b4_and_after_decimal()`, `all_values_for()`, etc.
- `console.py:74` — typo "Genereate DDL" (should be "Generate").

### [x] 11. Style / code smell
- `reshape.py:100` — `max` parameter name shadows the builtin.
- `ddlgenerator.py:603` — `!= False` instead of `is not False`.
- `ddlgenerator.py:245` — `hasattr(data, 'lower')` as string check (Python 2 idiom, should be `isinstance(data, str)`).
- `ddlgenerator.py:394-405` — `sqlalchemy()` method uses fragile string `.replace()` heuristics on SQLAlchemy `__repr__` output.
- `console.py:12` — joke comment left in production code.

### [x] 12. Dependency improvements
- `xlrd` only supports `.xls` — consider adding `openpyxl` for `.xlsx` support.
- `beautifulsoup4` and `requests` are hard dependencies but only needed for HTML/URL features — could be made optional extras.
- `pyyaml>=6.0,<7.0` upper bound may cause future pip resolution failures.

### [x] 13. CI / tooling
- `tox.ini` `[testenv:typecheck]` has `ignore_outcome = true` — mypy results are always green.
- CI lint job installs `ruff flake8` directly instead of using project-pinned versions.
- `Makefile` `make docs` uses `open` (macOS-specific), breaks on Linux.
- `Source.table_count` (sources.py:254) is a class-level mutable counter never reset between test runs (non-deterministic table names).
