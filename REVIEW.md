# Project Review: ddl-generator

**Date:** 2026-03-02
**Scope:** Full codebase review — code quality, bugs, security, testing, packaging, CI/CD
**Version reviewed:** 0.1.9 (last updated 2015-02-10)

## Summary

This project has been effectively unmaintained since 2015. While the core idea
is sound (infer SQL DDL from data), the codebase has multiple runtime-breaking
bugs due to SQLAlchemy 2.x incompatibility, missing imports, and undefined
attributes. Several security vulnerabilities exist around untrusted input
handling. CI is non-functional, test coverage is minimal, and dependencies are
completely unpinned.

## Blockers (code will crash at runtime)

### SQLAlchemy 2.x incompatibility
`ddlgenerator.py:78-80` — `strategy='mock'` was removed in SQLAlchemy 2.0.
Since `setup.py` does not pin `sqlalchemy<2`, a fresh install will get
SQLAlchemy 2.x and the module will fail to import. The `mock_engines` dict is
built at module level, so this crashes on `import`, not just on use.

### Missing imports in console.py
`console.py:6-7` — Imports `sqla_head`, `sqla_inserter_call`, and
`emit_db_sequence_updates` from `ddlgenerator.ddlgenerator`, but none of these
names exist as module-level symbols. `sqla_head` and `sqla_inserter_call` are
not defined anywhere. `emit_db_sequence_updates` is a method on `Table`, not a
standalone function. The CLI entry point will crash on any SQLAlchemy-dialect or
sequence-update code path.

### Broken logic in emit_db_sequence_updates
`ddlgenerator.py:395` — The condition is inverted: it checks
`if self.source.db_engine and self.source.db_engine.name != 'postgresql'` but
the body runs PostgreSQL-specific queries (`pg_namespace`, `pg_class`). Should
be `== 'postgresql'`.

`ddlgenerator.py:407` — `"ALTER SEQUENCE %s RESTART WITH %s;" % nextval` passes
a single int to a format string expecting two arguments. Will raise `TypeError`.

## Security Issues

### Remote code execution via eval
`ddlgenerator.py` uses `eval()` as a deserialization function for `.py` files
in the `eval_funcs_by_ext` dict. If a user passes an untrusted `.py` file path
or URL, arbitrary code will be executed.

### Unrestricted URL fetching (SSRF)
`ddlgenerator.py` fetches arbitrary URLs via `requests.get(data).text` with no
validation, timeout, or size limit. This enables SSRF attacks and
denial-of-service via large responses when the tool is exposed as a service.

### SQL injection
`ddlgenerator.py:382-383` — The INSERT value escaping is a naive
single-quote-doubling approach with the comment `"simple SQL injection
protection, sort of... ?"`. This does not handle all injection vectors and is
not safe for untrusted data.

## Bugs

### Mutable default arguments
`ddlgenerator.py:121` — `uniques=False` in `__init__` but the `_determine_types`
method signature has `uniques={}` (mutable default). While the `__init__`
signature is correct, `_determine_types` has the mutable default dict pattern,
which will persist state across calls.

### Duplicate class attribute
The `eval_funcs_by_ext` dict would be defined twice identically in the `Table`
class body if using the version referenced by the reviewer (confirmed the
code has been refactored in this version to use `data_dispenser` instead, but
legacy patterns remain in comments and dead code).

### Global mutable state
`ddlgenerator.py:63` — `metadata = sa.MetaData()` is a module-level global
shared across all `Table` instances. This means creating multiple `Table`
objects will accumulate tables in the same metadata, causing name collisions
and making the code not thread-safe.

### Bare except clause
`ddlgenerator.py` contains bare `except: pass` clauses that swallow all
exceptions including `KeyboardInterrupt` and `SystemExit`, making debugging
data parsing failures nearly impossible.

### _clean_column_name edge case
`ddlgenerator.py` — `_clean_column_name` will raise `IndexError` on an empty
string input after stripping underscores.

### logging.warn deprecation
`ddlgenerator.py` uses `logging.warn()` which has been deprecated in favor of
`logging.warning()`.

## Test Coverage

Test coverage is minimal — approximately 7 test cases in
`test_ddlgenerator.py`. The following are untested:

- CLI entry point (`console.py`)
- Type detection (`typehelpers.py`) — no unit tests for date, boolean, decimal coercion
- Data reshaping (`reshape.py`)
- XML, CSV, or URL-based input
- Error handling and edge cases
- `_clean_column_name`, `varying_length_text`, `reorder`, `limit`, `force_pk`
- `save_metadata_to` / `use_metadata_from` round-trip
- Django model generation (assertions are commented out in test_django)
- SQLAlchemy model generation (only basic smoke test)

The MongoDB test (`TestMongo`) uses the obsolete `pymongo.Connection()` API
(removed in pymongo 3.0+), so it will crash on any modern pymongo version.

## Packaging and Dependencies

### No version pins
`setup.py` and `requirements.txt` specify no version constraints on any
dependency. This means:
- `sqlalchemy` installs 2.x, which breaks the code (see Blockers above)
- `pymongo` installs 4.x, which removed `pymongo.Connection` (breaks tests)
- No reproducible builds are possible

### Legacy packaging
No `pyproject.toml` exists. The project uses only `setup.py`, which is the
legacy packaging approach. PEP 517/518 compliance requires `pyproject.toml`.

### setup.py publish command
`setup.py:14` — `os.system('python setup.py sdist upload')` uses the deprecated
and insecure `upload` command. Modern practice is `twine upload`.

### Stale classifiers
`setup.py:52-53` — Lists Python 3.3 only. No `python_requires` is specified.

## CI/CD

### Travis CI is non-functional
`.travis.yml` targets Python 3.4 (EOL). Travis CI free tier for open-source
was discontinued. The README badge links to defunct `travis-ci.org`.

### tox targets EOL Python versions
`tox.ini` targets `py26`, `py27`, `py33` — all long-EOL. The code uses Python 3
constructs, so py26/py27 would not work regardless.

## Dead Code

- `reserved.py` — `ansi_reserved` set is defined but never imported or used
  anywhere in the codebase.
- Multiple unused imports in `ddlgenerator.py`: `copy` (used only in
  `_saveable_metadata`), `pprint`, potentially others depending on code paths.
- Commented-out code and TODO comments throughout suggest unfinished features.

## Recommendations

If this project is to be revived for active use, the following would be needed
in roughly priority order:

1. **Pin sqlalchemy<2.0 or migrate to SQLAlchemy 2.x API** — without this, the
   package cannot be imported at all.
2. **Pin pymongo<4.0 or update to modern pymongo API** — without this, MongoDB
   functionality and tests are broken.
3. **Fix console.py imports** — `sqla_head`, `sqla_inserter_call`, and
   `emit_db_sequence_updates` need to be defined or the imports removed.
4. **Remove eval() deserialization** — replace with safe alternatives.
5. **Add version pins to all dependencies** in both `setup.py` and
   `requirements.txt`.
6. **Add pyproject.toml** for modern packaging.
7. **Replace Travis CI** with GitHub Actions or similar.
8. **Expand test coverage** significantly, especially for type inference,
   reshaping, and CLI.
9. **Fix global metadata state** — make it per-Table-instance.
10. **Add input validation** for URLs and file paths.
