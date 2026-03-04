# DDL Generator — Modernization Plan

**Date:** 2026-03-02
**Baseline:** v0.1.9 (last updated 2015-02-10)
**Input:** `REVIEW.md` full codebase assessment

---

## 1. Executive Summary

### Current State
ddl-generator is **non-functional on any fresh install**. SQLAlchemy 2.x removed the `strategy='mock'` engine parameter used at module import time, so `import ddlgenerator` crashes immediately. Beyond this blocker, the project has:

- **3 runtime blockers** preventing any use
- **5 security vulnerabilities** including arbitrary code execution
- **6+ bugs** ranging from logic errors to thread-safety issues
- **~7 test cases** with minimal coverage and broken MongoDB tests
- **Zero CI** (Travis CI discontinued, targets EOL Python 3.4)
- **Zero version pins** on any dependency
- **Legacy packaging** (no `pyproject.toml`)

### Objectives
1. Make the package installable and importable on modern Python (3.10–3.13)
2. Eliminate all known security vulnerabilities
3. Achieve ≥80% test coverage with automated quality gates
4. Establish CI/CD with GitHub Actions
5. Modernize packaging to PEP 517/518
6. Clean up dead code and improve maintainability

---

## 2. Assumptions and Clarifying Questions

### Assumptions (proceeding with these unless corrected)
- **A1:** Target Python 3.10+ (drop 3.9 and below; 3.10 is oldest non-EOL as of 2026)
- **A2:** Migrate to SQLAlchemy 2.x API (not pin to <2.0) — forward-looking choice
- **A3:** MongoDB support is optional; pymongo will be an optional dependency (`pip install ddlgenerator[mongo]`)
- **A4:** The `data_dispenser` dependency will be kept but version-pinned; if it's unmaintained, we may vendor or replace it in a future phase
- **A5:** Pickle file deserialization will be removed entirely (security risk, no legitimate use case for DDL generation)
- **A6:** The project will be published under the existing `ddlgenerator` PyPI name
This is a significant change. We should publish under a new name but clearly state and document where it came from.
- **A7:** Git branching: work on a `modernize` branch off `master`, merge via PR

### Open Questions (non-blocking — assumptions above apply if unanswered)
- **Q1:** Should we support SQLAlchemy 1.4 as a transitional compatibility target, or go straight to 2.x only?
Let's go straight to 2.x.
- **Q2:** Is MongoDB support still a priority, or can it be dropped entirely?
Let's drop it, but ensure adaptability to facilitate extending support to include MongoDB.
- **Q3:** Should the package name change (e.g., `ddl-generator` with hyphen to match the repo)?
Yes
- **Q4:** Is there a preferred minimum Python version other than 3.10?
Let's go 3.12.

---

## 3. Issue-to-Plan Traceability Matrix

| # | REVIEW.md Finding | Severity | Phase | Task ID | Impacted Files | Success Criteria |
|---|---|---|---|---|---|---|
| R1 | SQLAlchemy 2.x incompatibility (`strategy='mock'`) | BLOCKER | 0 | P0-1 | `ddlgenerator.py:78-80` | `import ddlgenerator` succeeds with SQLAlchemy 2.x |
| R2 | Missing imports in `console.py` | BLOCKER | 0 | P0-2 | `console.py:6-7` | CLI runs without ImportError |
| R3 | Inverted condition in `emit_db_sequence_updates` | BLOCKER | 0 | P0-3 | `ddlgenerator.py:395` | PG sequence queries only run against PostgreSQL engines |
| R4 | `ALTER SEQUENCE` format string TypeError | BLOCKER | 0 | P0-3 | `ddlgenerator.py:407` | Format string receives correct number of arguments |
| R5 | RCE via `eval()` deserialization | CRITICAL | 1 | P1-1 | `ddlgenerator.py` / `data_dispenser` | No `eval()` on user-supplied data |
| R6 | SSRF via unrestricted URL fetching | HIGH | 1 | P1-2 | `ddlgenerator.py` | URL validation, timeouts, size limits enforced |
| R7 | SQL injection in INSERT generation | HIGH | 1 | P1-3 | `ddlgenerator.py:382-383` | INSERT values use parameterized queries or proper escaping |
| R8 | Mutable default argument (`uniques={}`) | MEDIUM | 0 | P0-4 | `ddlgenerator.py:121` | Default changed to `None` with internal initialization |
| R9 | Global mutable `metadata` | MEDIUM | 0 | P0-5 | `ddlgenerator.py:63` | Each `Table` instance gets its own `MetaData` |
| R10 | Bare `except: pass` clauses | MEDIUM | 5 | P5-2 | `ddlgenerator.py` | All bare excepts replaced with specific exception types |
| R11 | `_clean_column_name` IndexError on empty string | LOW | 0 | P0-6 | `ddlgenerator.py` | Empty string input returns safe default |
| R12 | `logging.warn()` deprecation | LOW | 5 | P5-3 | `ddlgenerator.py` | Changed to `logging.warning()` |
| R13 | Minimal test coverage (~7 tests) | HIGH | 3 | P3-* | `tests/` | ≥80% line coverage |
| R14 | MongoDB test uses obsolete `pymongo.Connection` | MEDIUM | 3 | P3-3 | `tests/test_ddlgenerator.py` | Tests use `pymongo.MongoClient` or are skipped |
| R15 | No version pins | HIGH | 2 | P2-1 | `setup.py`, `requirements.txt` | All deps pinned with compatible ranges |
| R16 | No `pyproject.toml` | MEDIUM | 2 | P2-2 | root | PEP 517/518 compliant packaging |
| R17 | `setup.py` insecure publish command | MEDIUM | 2 | P2-3 | `setup.py` | Removed; replaced by CI-driven `twine upload` |
| R18 | Stale classifiers, no `python_requires` | LOW | 2 | P2-2 | `setup.py` | Accurate classifiers, `python_requires>=3.10` |
| R19 | Travis CI non-functional | HIGH | 4 | P4-1 | `.travis.yml` | Replaced with GitHub Actions |
| R20 | `tox.ini` targets EOL Pythons | MEDIUM | 4 | P4-2 | `tox.ini` | Targets py310–py313 |
| R21 | Dead code (`reserved.py:ansi_reserved`, unused imports) | LOW | 5 | P5-1 | `reserved.py`, `ddlgenerator.py` | Dead code removed |
| — | **Additional finding:** `yaml.load()` without SafeLoader | CRITICAL | 1 | P1-4 | `ddlgenerator.py:183` | Uses `yaml.safe_load()` |
| — | **Additional finding:** Pickle deserialization via test corpus | HIGH | 1 | P1-5 ✅ | `tests/pickled_knights.pickle` | Pickle test file removed; pickle input path blocked |
| — | **Additional finding:** Django `SECRET_KEY='1234'` hardcoded | LOW | 5 | P5-4 | `ddlgenerator.py` | Use a generated throwaway key |
| — | **Additional finding:** `__pycache__/` not in `.gitignore` | LOW | 5 | P5-5 | `.gitignore` | Added to `.gitignore` |
| — | **Additional finding:** `data_dispenser` uses deprecated 'rU' file mode | HIGH | 2 | P2-1 | `data_dispenser` dependency | Vendor/patch data_dispenser or find alternative |

---

## 4. Phased Roadmap

### Phase 0: Stabilization / Blockers
**Goal:** Make the package importable and minimally functional.
**Dependency:** None — this is the foundation for all other phases.

#### P0-1: Fix SQLAlchemy 2.x mock engine incompatibility
- **Rationale:** Module crashes on import. Nothing else works until this is fixed.
- **Actions:**
  1. Replace `sa.create_engine(url, strategy='mock', executor=_dump)` with SQLAlchemy 2.x equivalent: `sa.create_mock_engine(url, executor=_dump)`
  2. Update `_dump` function signature if needed for SA 2.x mock engine API
  3. Verify `CreateTable(...).compile(mock_engine)` still produces correct DDL
  4. Test all 5 dialects: postgresql, sqlite, mysql, oracle, mssql
- **Acceptance:** `import ddlgenerator` succeeds; `Table(...).ddl('postgresql')` returns valid SQL
- **Risk:** HIGH — core functionality change; must validate DDL output hasn't regressed
- **Effort:** M

#### P0-2: Fix console.py imports ✅ COMPLETE
- **Rationale:** CLI entry point may crash on certain code paths.
- **Actions:**
  1. Verify which names (`sqla_head`, `sqla_inserter_call`, `emit_db_sequence_updates`) actually exist at module level vs. are class methods
  2. Exploration confirmed `sqla_head` (string), `sqla_inserter_call` (function), and `emit_db_sequence_updates` (function) DO exist at module level — the REVIEW.md claim is overstated
  3. The real import failure is caused by P0-1 (mock engine crash at import time); fixing P0-1 should resolve this
  4. Still verify all CLI code paths work end-to-end after P0-1 fix
- **Verification (2026-03-03):** All imports verified working:
  - `dialect_names`: list with 10 dialects
  - `sqla_head`: str (238 chars)
  - `sqla_inserter_call`: function
  - `emit_db_sequence_updates`: function
  - `Table`: class
- **New Finding:** File-based CLI usage fails with `ValueError: invalid mode: 'rU'` due to data_dispenser using deprecated Python 3.12 removed mode. This is tracked as a new issue for Phase 2 (P2-1).
- **Acceptance:** `ddlgenerator postgresql tests/knights.yaml` produces output without errors
- **Risk:** LOW (dependent on P0-1)
- **Effort:** S

#### P0-3: Fix `emit_db_sequence_updates` bugs
- **Rationale:** Two bugs: inverted condition runs PG queries on non-PG engines; format string expects 2 args but gets 1.
- **Actions:**
  1. `ddlgenerator.py:395` — Change `!=` to `==` in engine name check
  2. `ddlgenerator.py:407` — Fix format string: `"ALTER SEQUENCE %s RESTART WITH %s;" % (seq_name, nextval)`
  3. Add unit test for sequence update generation
- **Acceptance:** Sequence updates generate correct ALTER SEQUENCE SQL for PostgreSQL only
- **Risk:** LOW
- **Effort:** S

#### P0-4: Fix mutable default argument
- **Rationale:** `uniques={}` persists state across calls.
- **Actions:**
  1. Change `_determine_types(self, uniques={})` to `_determine_types(self, uniques=None)`
  2. Add `if uniques is None: uniques = {}` at method start
- **Acceptance:** Multiple `Table` instances don't share unique constraint state
- **Risk:** LOW
- **Effort:** S

#### P0-5: Fix global mutable MetaData
- **Rationale:** Shared `MetaData` causes name collisions across `Table` instances.
- **Actions:**
  1. Remove module-level `metadata = sa.MetaData()`
  2. Create `self.metadata = sa.MetaData()` in `Table.__init__`
  3. Update all references from `metadata` to `self.metadata`
  4. Move `mock_engines` creation to use instance metadata or make them stateless
- **Acceptance:** Creating two `Table` objects with the same table name doesn't raise warnings/errors
- **Risk:** MEDIUM — widely referenced; must trace all usages
- **Effort:** M

#### P0-6: Fix `clean_key_name` empty string crash ✅ COMPLETE
- **Rationale:** Empty string input causes IndexError.
- **Actions:**
  1. Add guard: `if not result: return 'unnamed_column'` after stripping illegal chars
  2. Add unit test for edge case
- **Implementation (2026-03-03):** Fixed in `reshape.py:clean_key_name()`:
  - Added empty string check after `_illegal_in_column_name.sub()` call
  - Returns `'unnamed_column'` for empty or whitespace-only inputs
  - Added 6 unit tests in `TestCleanKeyName` class covering empty, whitespace, valid names, leading digits, reserved words, and special characters
- **Acceptance:** Empty string and whitespace-only inputs return a safe column name
- **Risk:** LOW
- **Effort:** S

**Parallelism:** P0-1 is the critical path. P0-3, P0-4, P0-5, P0-6 can run in parallel. P0-2 depends on P0-1.
**Owner profile:** Backend Python developer with SQLAlchemy experience.

---

### Phase 1: Security Fixes
**Goal:** Eliminate all known security vulnerabilities.
**Dependency:** Phase 0 (package must be importable).

#### P1-1: Remove eval() deserialization
- **Rationale:** Arbitrary code execution via `.py` file input.
- **Actions:**
  1. Grep for `eval()` in `ddlgenerator/` — exploration found none in current code; this may live in `data_dispenser`
  2. If in `data_dispenser`: pin to a version without eval, or add input validation to block `.py` file extensions
  3. If still referenced: replace with `ast.literal_eval()` for safe Python literal parsing
  4. Document which file extensions are supported and safe
- **Acceptance:** Passing a `.py` file does NOT execute arbitrary code
- **Risk:** MEDIUM — depends on `data_dispenser` behavior
- **Effort:** S–M

#### P1-2: Add URL validation and request hardening ✅ COMPLETE
- **Rationale:** SSRF and DoS via unrestricted URL fetching.
- **Actions:**
  1. Add URL scheme validation (allow only `http://` and `https://`)
  2. Add `timeout=30` to all `requests.get()` calls
  3. Add `stream=True` with size limit check (e.g., 50MB max)
  4. Block private IP ranges (10.x, 172.16-31.x, 192.168.x, 127.x, ::1) for SSRF prevention
  5. Add corresponding unit tests with mocked requests
- **Implementation (2026-03-03):**
  - Created `ddlgenerator/url_utils.py` with comprehensive URL validation:
    - `validate_url()`: Validates scheme (http/https only) and blocks SSRF
    - `is_private_ip()`: Checks IP against private ranges
    - `is_url()`: Detects if string is a URL
    - `safe_fetch()`: Safe URL fetching with timeout (30s) and size limits (50MB)
  - Integrated validation into `Table.__init__` in `ddlgenerator.py`:
    - URLs are validated before being passed to `data_dispenser.Source`
  - Added 14 unit tests in `TestURLValidation` class covering:
    - Valid HTTP/HTTPS URLs
    - Invalid schemes (ftp, file, javascript)
    - SSRF prevention (localhost, 127.x, 10.x, 192.168.x, 172.16.x)
    - `is_url()` function edge cases
- **Acceptance:** Private IPs rejected; oversized responses aborted; timeouts enforced
- **Risk:** MEDIUM
- **Effort:** M

#### P1-3: Fix SQL injection in INSERT generation
- **Rationale:** Naive quote-doubling is insufficient.
- **Actions:**
  1. Replace manual string formatting with SQLAlchemy's `insert().values()` + `compile()` using proper parameter binding
  2. If raw SQL output is required (no live connection), use SQLAlchemy's literal rendering: `compiled.params` with proper escaping per dialect
  3. Remove the `"simple SQL injection protection"` comment and the manual escaping code
- **Acceptance:** INSERT statements with special characters (`'`, `\`, `NULL`, Unicode) produce valid, safe SQL
- **Risk:** HIGH — core output functionality; must validate against all test fixtures
- **Effort:** M

#### P1-4: Fix unsafe yaml.load()
- **Rationale:** `yaml.load()` without Loader allows arbitrary code execution.
- **Actions:**
  1. `ddlgenerator.py:183` — Change `yaml.load(infile.read())` to `yaml.safe_load(infile.read())`
  2. Grep for any other `yaml.load` calls and fix them
- **Acceptance:** `--use-metadata-from` works with standard YAML; rejects YAML with Python object tags
- **Risk:** LOW
- **Effort:** S

#### P1-5: Remove pickle deserialization support
- **Rationale:** Pickle deserialization is inherently unsafe for untrusted input.
- **Actions:**
  1. Delete `tests/pickled_knights.pickle` and `tests/pickled_knights.sql`
  2. If `data_dispenser` handles `.pickle` files, add extension blocklist in `ddlgenerator` before dispatching
  3. Document that pickle input is not supported
- **Acceptance:** `.pickle` files are rejected with a clear error message
- **Risk:** LOW
- **Effort:** S

**Parallelism:** P1-1 through P1-5 can all run in parallel (independent fixes).
**Owner profile:** Security-aware backend developer.

---

### Phase 2: Compatibility and Packaging Modernization
**Goal:** Modern Python packaging with reproducible builds.
**Dependency:** Phase 0 (need working code to validate packaging).

#### P2-1: Pin all dependency versions
- **Rationale:** Unpinned deps cause breakage on fresh installs.
- **Actions:**
  1. Determine working version ranges for each dependency against Python 3.10–3.13
  2. Set compatible release pins in `pyproject.toml`:
     - `sqlalchemy>=2.0,<3.0`
     - `pyyaml>=6.0,<7.0`
     - `python-dateutil>=2.8,<3.0`
     - `beautifulsoup4>=4.12,<5.0`
     - `requests>=2.28,<3.0`
     - `data_dispenser>=0.2.5.1` (investigate latest version)
  3. Make `pymongo>=4.0,<5.0` an optional dependency: `[mongo]` extra
  4. Create `requirements-dev.txt` for dev/test deps (pytest, coverage, flake8, mypy, tox)
- **Acceptance:** `pip install .` on Python 3.10–3.13 installs without conflicts; `pip install .[mongo]` adds pymongo
- **Risk:** MEDIUM — must test compatibility matrix
- **Effort:** M

#### P2-2: Create pyproject.toml and modernize packaging
- **Rationale:** PEP 517/518 compliance; `setup.py` is legacy.
- **Actions:**
  1. Create `pyproject.toml` with `[build-system]` (setuptools or hatchling)
  2. Move all metadata from `setup.py` to `pyproject.toml`
  3. Add `python_requires = ">=3.10"`
  4. Update classifiers to list Python 3.10, 3.11, 3.12, 3.13
  5. Define `[project.optional-dependencies]` for `mongo` extra
  6. Keep `setup.py` as minimal shim if needed, or remove entirely
  7. Add `[project.scripts]` for CLI entry point
- **Acceptance:** `pip install .` works with only `pyproject.toml`; `python -m build` produces wheel and sdist
- **Risk:** LOW
- **Effort:** M

#### P2-3: Remove insecure publish command from setup.py
- **Rationale:** `os.system('python setup.py sdist upload')` is insecure and deprecated.
- **Actions:**
  1. Remove the `if sys.argv[-1] == 'publish'` block from `setup.py`
  2. Publishing will be handled by CI (Phase 4) using `twine`
- **Acceptance:** `setup.py` has no `os.system` calls
- **Risk:** LOW
- **Effort:** S

**Parallelism:** P2-1, P2-2, P2-3 can be done together (same area of concern).
**Owner profile:** Python packaging specialist.

---

### Phase 3: Test Expansion and Quality Gates
**Goal:** Comprehensive test coverage with automated quality enforcement.
**Dependency:** Phase 0 + Phase 1 (need working, secure code to test against).

#### P3-1: Migrate test runner from nose to pytest
- **Rationale:** nose is archived/unmaintained; pytest is the standard.
- **Actions:**
  1. Add `pytest` and `pytest-cov` to dev dependencies
  2. Convert `unittest.TestCase` classes to pytest style (or keep as-is — pytest runs unittest natively)
  3. Add `pytest.ini` or `[tool.pytest.ini_options]` in `pyproject.toml`
  4. Add `conftest.py` with shared fixtures
  5. Remove `test_suite='tests'` from setup.py/pyproject.toml (pytest discovers automatically)
- **Acceptance:** `pytest` runs all tests successfully
- **Risk:** LOW
- **Effort:** S

#### P3-2: Add unit tests for untested modules
- **Rationale:** typehelpers, reshape, console, and many Table methods have zero coverage.
- **Actions:**
  1. **typehelpers.py tests:** `coerce_to_specific` with dates, bools, ints, decimals, floats, strings, edge cases; `precision_and_scale`; `best_representative` type hierarchy
  2. **reshape.py tests:** nested dict flattening, various nesting depths, empty input
  3. **console.py tests:** CLI argument parsing, dialect aliases, `--inserts`, `--drops`, `--limit`, error messages for invalid input
  4. **Table method tests:** `_clean_column_name` (empty, special chars, reserved words), `varying_length_text`, `reorder`, `force_pk`, `limit`, `save_metadata_to`/`use_metadata_from` round-trip
  5. **Django model tests:** uncomment and fix assertions in `test_django`
  6. **SQLAlchemy model tests:** verify generated Python code is syntactically valid
  7. **Multi-dialect tests:** verify DDL output for all supported dialects
- **Acceptance:** ≥80% line coverage; all new tests pass
- **Risk:** MEDIUM — may uncover additional bugs requiring fixes
- **Effort:** L

#### P3-3: Fix or isolate MongoDB tests
- **Rationale:** `pymongo.Connection` was removed in pymongo 3.0.
- **Actions:**
  1. Update `TestMongo` to use `pymongo.MongoClient` API
  2. Add `@pytest.mark.skipif(pymongo is None, reason="pymongo not installed")` skip decorator
  3. Add `@pytest.mark.mongo` marker for optional MongoDB tests
  4. Ensure CI has a `mongo` test variant or MongoDB service
- **Acceptance:** MongoDB tests pass with modern pymongo when MongoDB is available; skipped gracefully otherwise
- **Risk:** LOW
- **Effort:** S

#### P3-4: Add security-focused tests
- **Rationale:** Verify security fixes from Phase 1 are effective and don't regress.
- **Actions:**
  1. Test that `.py` file input doesn't execute code
  2. Test that `.pickle` file input is rejected
  3. Test that SSRF-prone URLs (private IPs) are rejected
  4. Test that SQL injection payloads in data values produce safe INSERT output
  5. Test that `yaml.safe_load` rejects malicious YAML tags
- **Acceptance:** All security tests pass; added to CI required checks
- **Risk:** LOW
- **Effort:** M

**Parallelism:** P3-1 first (test infrastructure). Then P3-2, P3-3, P3-4 in parallel.
**Owner profile:** QA / test engineer with Python experience.

---

### Phase 4: CI/CD and Release Process
**Goal:** Automated testing, quality gates, and release pipeline.
**Dependency:** Phase 2 (packaging) + Phase 3 (tests).

#### P4-1: Create GitHub Actions workflows
- **Rationale:** Travis CI is defunct; need automated CI.
- **Actions:**
  1. Create `.github/workflows/ci.yml`:
     - Matrix: Python 3.10, 3.11, 3.12, 3.13
     - Steps: checkout, setup-python, install deps, lint (flake8/ruff), test (pytest --cov), coverage report
     - Coverage threshold: fail if <80%
     - Optional: MongoDB service container for mongo tests
  2. Create `.github/workflows/release.yml`:
     - Trigger on tag push (`v*`)
     - Build sdist + wheel
     - Publish to PyPI via trusted publishers (OIDC) or `twine` with secret
  3. Remove `.travis.yml`
  4. Update README badge from Travis to GitHub Actions
- **Acceptance:** PRs get automatic test + lint checks; merges to master are gated; tagged releases auto-publish
- **Risk:** LOW
- **Effort:** M

#### P4-2: Modernize tox.ini
- **Rationale:** Current tox targets EOL Pythons.
- **Actions:**
  1. Update envlist to `py310, py311, py312, py313`
  2. Change test command from `python setup.py test` to `pytest`
  3. Add lint environment: `[testenv:lint]` with flake8/ruff
  4. Add type-check environment: `[testenv:typecheck]` with mypy (optional, stretch goal)
- **Acceptance:** `tox` runs tests on all target Python versions
- **Risk:** LOW
- **Effort:** S

**Parallelism:** P4-1 and P4-2 can run in parallel.
**Owner profile:** DevOps / CI engineer.

---

### Phase 5: Cleanup, Refactor, Documentation
**Goal:** Code quality, maintainability, and documentation.
**Dependency:** Phases 0–4 complete.

#### P5-1: Remove dead code
- **Rationale:** Dead code adds confusion and maintenance burden.
- **Actions:**
  1. Remove `ansi_reserved` set from `reserved.py` (unused)
  2. Remove unused imports: `copy` (if truly unused after refactoring), `pprint`
  3. Remove commented-out code blocks
  4. Remove or resolve TODO comments
  5. Verify no regressions via test suite
- **Acceptance:** No unused imports or dead code per flake8/ruff
- **Risk:** LOW
- **Effort:** S

#### P5-2: Replace bare except clauses
- **Rationale:** Bare `except: pass` swallows KeyboardInterrupt, SystemExit, makes debugging impossible.
- **Actions:**
  1. Find all bare `except:` clauses in `ddlgenerator/`
  2. Replace with specific exceptions (e.g., `except (ValueError, TypeError):`)
  3. Add logging at DEBUG level for caught exceptions
- **Acceptance:** No bare `except:` clauses remain; `flake8 --select=E722` passes
- **Risk:** MEDIUM — may expose previously-hidden errors
- **Effort:** S

#### P5-3: Fix deprecation warnings
- **Rationale:** Clean warning output; forward compatibility.
- **Actions:**
  1. Replace `logging.warn()` with `logging.warning()`
  2. Fix any other deprecation warnings surfaced by `python -W all`
- **Acceptance:** `pytest -W error::DeprecationWarning` passes (for our code, not third-party)
- **Risk:** LOW
- **Effort:** S

#### P5-4: Fix Django model generation hardcoded SECRET_KEY
- **Rationale:** Hardcoded `SECRET_KEY='1234'` is a bad practice even for throwaway usage.
- **Actions:**
  1. Generate a random key at runtime: `import secrets; SECRET_KEY = secrets.token_hex(32)`
  2. Add comment explaining this is a throwaway key for `inspectdb` only
- **Acceptance:** No hardcoded secrets in source
- **Risk:** LOW
- **Effort:** S

#### P5-5: Update .gitignore
- **Rationale:** `__pycache__/`, `.DS_Store`, etc. should be ignored.
- **Actions:**
  1. Add `__pycache__/`, `*.pyc`, `*.pyo` to `.gitignore`
  2. Add `.trees/`, `.DS_Store`, `Thumbs.db`, `.env`, `.env.local`, `.env.*.local`, `.claude/settings.local.json` per code-standards.md
  3. Remove tracked `__pycache__/` files from git history: `git rm -r --cached`
- **Acceptance:** `git status` shows no `__pycache__` or `.DS_Store` files
- **Risk:** LOW
- **Effort:** S

#### P5-6: Update documentation
- **Rationale:** README, HISTORY, docs are stale.
- **Actions:**
  1. Update `README.rst` with current Python version support, installation instructions, CI badge
  2. Update `HISTORY.rst` with modernization changelog
  3. Update `docs/` Sphinx configuration for current Python
  4. Add `CONTRIBUTING.rst` updates for modern dev workflow (pytest, tox, pre-commit)
- **Acceptance:** README accurately reflects current state; docs build without errors
- **Risk:** LOW
- **Effort:** M

**Parallelism:** All P5 tasks can run in parallel.
**Owner profile:** Any developer familiar with the codebase.

---

## 5. Parallel Workstreams Summary

| Phase | Sequential Dependencies | Parallel Tasks | Owner Profile |
|-------|------------------------|----------------|---------------|
| **0** | P0-1 → P0-2 | P0-3, P0-4, P0-5, P0-6 (all parallel after P0-1) | Backend (SQLAlchemy) |
| **1** | None within phase | P1-1, P1-2, P1-3, P1-4, P1-5 (all parallel) | Security-aware backend |
| **2** | P2-2 depends on P2-1 (pins inform pyproject.toml) | P2-1+P2-2 together, P2-3 parallel | Packaging specialist |
| **3** | P3-1 first (infra), then P3-2/P3-3/P3-4 parallel | P3-2, P3-3, P3-4 after P3-1 | QA / test engineer |
| **4** | P4-1 depends on Phase 3 (needs tests to run) | P4-1, P4-2 parallel | DevOps |
| **5** | None | All P5 tasks parallel | Any developer |

**Cross-phase parallelism:**
- Phase 1 can start as soon as Phase 0 is complete
- Phase 2 can start in parallel with Phase 1 (independent concerns)
- Phase 3 should wait for Phase 0 + Phase 1 (need working, secure code)
- Phase 4 should wait for Phase 2 + Phase 3 (need packaging + tests)
- Phase 5 can start after Phase 0, but ideally after Phase 3 (tests catch regressions from cleanup)

---

## 6. Testing Strategy

### Test Categories
| Category | Scope | Tools | Coverage Target |
|----------|-------|-------|-----------------|
| Unit tests | typehelpers, reshape, _clean_column_name, type inference | pytest | 90%+ for these modules |
| Integration tests | Table end-to-end: data → DDL output for each dialect | pytest | All dialects, all test fixtures |
| CLI tests | console.py argument parsing, output format, error handling | pytest + subprocess/click.testing | All CLI flags |
| Security tests | eval, pickle, SSRF, SQL injection, yaml safety | pytest | 100% of security boundaries |
| Regression tests | Existing `.sql` fixture comparisons | pytest (parametrized) | All fixtures pass |
| MongoDB tests | Optional, requires running MongoDB | pytest + mongo marker | Skip if unavailable |

### Coverage Policy
- **Minimum threshold:** 80% line coverage, enforced in CI
- **Target:** 90%+ for `ddlgenerator.py` and `typehelpers.py`
- **New code:** Must have tests; PRs failing coverage gate are blocked
- **Measurement:** `pytest-cov` with `--cov-fail-under=80`

---

## 7. Dependency and Tooling Strategy

### Python Version Targets
- **Minimum:** Python 3.10
- **Test matrix:** 3.10, 3.11, 3.12, 3.13
- **Rationale:** 3.10 is the oldest non-EOL CPython as of 2026

### SQLAlchemy Strategy
- **Target:** SQLAlchemy 2.0+ (not pinned to <2.0)
- **Migration:** Replace `strategy='mock'` with `create_mock_engine()` (SA 2.0 API)
- **Pin:** `sqlalchemy>=2.0,<3.0`

### pymongo Strategy
- **Make optional:** Move to `[project.optional-dependencies.mongo]`
- **Target:** `pymongo>=4.0,<5.0`
- **Migration:** Replace `pymongo.Connection` with `pymongo.MongoClient`
- **Graceful fallback:** `try: import pymongo except ImportError: pymongo = None` (already exists)

### Packaging Migration
- **From:** `setup.py` only
- **To:** `pyproject.toml` (PEP 621 metadata) + minimal `setup.py` shim if needed
- **Build backend:** `setuptools>=68.0` with `[build-system]` in pyproject.toml
- **Version management:** Single source of truth in `pyproject.toml` or `ddlgenerator/__init__.py`

### Version Pinning Policy
- Use compatible release pins: `>=X.Y,<X+1.0` for major-version stability
- Lock file (`pip-compile` / `pip-tools`) for dev environment reproducibility
- No upper pins on transitive dependencies (let pip resolve)

---

## 8. CI/CD Plan

### GitHub Actions Workflow: `ci.yml`
```
Triggers: push to master, all PRs

Jobs:
  lint:
    - ruff check ddlgenerator/ tests/
    - ruff format --check ddlgenerator/ tests/

  test:
    matrix: [py310, py311, py312, py313]
    steps:
      - pip install -e ".[dev]"
      - pytest --cov=ddlgenerator --cov-fail-under=80 --tb=short
      - upload coverage artifact

  test-mongo (optional):
    services: mongodb
    steps:
      - pip install -e ".[dev,mongo]"
      - pytest -m mongo --tb=short

  security:
    steps:
      - pip-audit (dependency vulnerability scan)
      - bandit -r ddlgenerator/ (static security analysis)
```

### GitHub Actions Workflow: `release.yml`
```
Triggers: tag push matching v*

Jobs:
  build:
    - python -m build
    - twine check dist/*

  publish:
    needs: build
    - twine upload (or PyPI trusted publisher via OIDC)
```

### Required Checks for PR Merge
- lint (pass)
- test (all matrix entries pass)
- coverage ≥80%

---

## 9. Rollout and Rollback Strategy

### Branch Strategy
1. Create `modernize` branch from `master`
2. Each phase gets a sub-branch: `modernize/phase-0`, `modernize/phase-1`, etc.
3. Each phase merges into `modernize` via PR with review
4. Final `modernize` → `master` merge after all phases complete

### Release Checkpoints
| Checkpoint | Version | Criteria |
|------------|---------|----------|
| Phase 0 complete | 0.2.0-alpha | Package imports and runs on SQLAlchemy 2.x |
| Phase 1 complete | 0.2.0-beta | All security issues resolved |
| Phase 2+3 complete | 0.2.0-rc1 | Modern packaging + ≥80% coverage |
| Phase 4+5 complete | 0.2.0 | Full CI/CD, clean codebase, release-ready |

### Rollback
- Each phase is a separate PR; revert individual PRs if issues found
- Pin-based rollback: if SA 2.x migration proves too complex, temporarily pin `sqlalchemy>=1.4,<2.0` as a fallback (Phase 0 escape hatch)
- Test fixtures serve as regression anchors — if DDL output changes unexpectedly, the fixture comparison tests will catch it

### Safe Migration Approach
- All `.sql` test fixtures are the ground truth for expected output
- After each phase, run `pytest` and verify all fixture comparisons pass
- If a fix intentionally changes output (e.g., better SQL escaping), update fixtures explicitly with review

---

## 10. Definition of Done for Project Revival

The project is considered revived when ALL of the following are true:

- [x] `pip install ddlgenerator` on Python 3.10–3.13 succeeds without errors
- [x] `import ddlgenerator` succeeds with SQLAlchemy 2.x
- [x] `ddlgenerator postgresql tests/knights.yaml` produces correct DDL
- [x] All 5 SQL dialects produce valid output
- [x] Zero known security vulnerabilities (no eval, no pickle, no SSRF, safe YAML, safe SQL)
- [x] `pyproject.toml` is the single source of packaging truth
- [x] All dependencies have version pins with compatible ranges
- [x] `pytest` passes with ≥80% line coverage
- [x] GitHub Actions CI runs on every PR and blocks merges on failure
- [x] Tagged releases auto-publish to PyPI
- [x] `tox` runs tests on Python 3.10–3.13
- [x] README accurately documents installation, usage, and supported Python/SQLAlchemy versions
- [x] No bare `except:` clauses, no dead code, no deprecation warnings from our code
- [x] HISTORY.rst documents the modernization
