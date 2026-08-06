.. :changelog:

History
-------

Unreleased
++++++++++

**Breaking**

* Minimum supported Python raised from 3.10 to 3.12; CI now tests
  3.12 and 3.13 only.

Development
~~~~~~~~~~~

* ``pyproject.toml`` classifiers are now the single source of truth for
  supported Python versions.  ``tests/test_version_sync.py`` fails the
  build if ``tox.ini`` or the CI workflow drifts out of sync.

0.2.2 (2026-08-03)
++++++++++++++++++

**Bug fix and documentation release**

Bug Fixes
~~~~~~~~~

* The ``--save-metadata-to`` / ``--use-metadata-from`` workflow (the
  recommended path for tables too large to analyze in one pass) crashed
  with a ``ConstructorError``.  Schema metadata was written with
  ``yaml.dump``, which emits Python object tags, but read back with
  ``yaml.safe_load``, which rejects those tags.  Metadata is now written
  as plain safe YAML: an explicit ``columns`` / ``children`` structure
  with column types stored as names and resolved through a fixed
  whitelist on load.  The read side stays on ``yaml.safe_load`` rather
  than being weakened to ``yaml.unsafe_load``.  Restored schemas are
  identical to a fresh inference, for flat and nested tables alike.
* A latent ``RuntimeError`` (dictionary changed size during iteration)
  in the child-table split prevented nested tables from being restored
  from saved metadata.
* An unknown column type in a metadata file now raises a clear
  ``ValueError`` instead of being imported, so a tampered metadata file
  cannot name its way into arbitrary code execution.

Documentation
~~~~~~~~~~~~~

* Added a comprehensive, self-contained HTML user guide at
  ``docs/user_guide.html``: quickstart, data formats, SQL dialects, type
  inference, the full CLI reference, nested/child tables, ORM
  generation, the large-tables workflow, the Python API, security,
  recipes, and troubleshooting.  All examples are verbatim output
  verified against the tool.  Linked from the README and the Sphinx
  landing page.

Other
~~~~~

* Test suite grown from 295 to 301 tests.

0.2.1 (2026-07-31)
++++++++++++++++++

**Bug fix release**

The 0.2.0 tag never published; its release workflow failed at the upload
step. This release carries the fixes merged since then.

Bug Fixes
~~~~~~~~~

* Reading a ``.xls`` file whose absolute path was 84 characters or longer
  recursed until the stack overflowed. The path was misread as raw
  spreadsheet contents, the resulting error was swallowed, and the fallback
  expanded the path into a glob that matched itself.
* ``Source`` given a directory recursed the same way, for the same reason.
* No ``.xls`` file could be read at all: ``NamedIter`` set ``__iter__`` and
  ``__next__`` as instance attributes, which Python ignores when resolving
  dunder methods, so every read raised ``TypeError``.
* Remote spreadsheets were fetched as text and re-encoded, which corrupts
  binary content. ``.xls`` and ``.xlsx`` URLs are now fetched as bytes;
  ``.xlsx`` URLs were previously not recognised as spreadsheets at all.
* A missing dependency reported itself as a circular import, because the
  internal imports were wrapped in ``try/except ImportError`` with a
  fallback branch that raised a different, misleading error.
* ``_table_score`` counted columns twice and ignored the row count it had
  computed, so a short wide HTML table could outrank a tall narrow one.
* Project URLs in the package metadata pointed at a repository that does
  not exist.

Other
~~~~~

* Test suite grown from 288 to 295 tests; coverage 82% to 84%.
* ``ruff`` and ``flake8`` both run clean, so the CI lint job passes.
* Added ``.mise.toml`` so the project virtualenv activates automatically.

0.2.0 (2026-03-03)
++++++++++++++++++

**Modernization Release**

This release modernizes the package for Python 3.10+ and SQLAlchemy 2.x,
with comprehensive security fixes and improved testing.

Breaking Changes
~~~~~~~~~~~~~~~~

* **Python 3.10+ required** - Dropped support for Python 2.x and older Python 3.x versions
* **SQLAlchemy 2.x required** - Migrated from deprecated ``strategy='mock'`` to ``create_mock_engine()``
* **Pickle support removed** - Removed due to inherent security risks of pickle deserialization
* **Package renamed** - Published as ``ddl-generator`` to distinguish from the original ``ddlgenerator`` package

Security Fixes
~~~~~~~~~~~~~~

* Removed ``eval()`` deserialization vulnerability
* Fixed SSRF vulnerability with URL validation, timeouts, and private IP blocking
* Fixed SQL injection in INSERT generation with proper parameter binding
* Changed ``yaml.load()`` to ``yaml.safe_load()`` to prevent code execution
* Removed hardcoded Django ``SECRET_KEY`` - now uses randomly generated key

Bug Fixes
~~~~~~~~~

* Fixed SQLAlchemy 2.x incompatibility with mock engine (module crashed on import)
* Fixed inverted condition in ``emit_db_sequence_updates`` - PG sequences now only run on PostgreSQL
* Fixed ``ALTER SEQUENCE`` format string TypeError
* Fixed mutable default argument ``uniques={}`` causing state leakage across calls
* Fixed global mutable ``metadata`` causing name collisions across Table instances
* Fixed ``clean_key_name`` IndexError on empty string input
* Fixed ``logging.warn()`` deprecation - changed to ``logging.warning()``
* Replaced all bare ``except: pass`` clauses with specific exception types

Improvements
~~~~~~~~~~~~

* Migrated to ``pyproject.toml`` (PEP 517/518) for modern packaging
* Added version pins for all dependencies with compatible release ranges
* Migrated test runner from nose to pytest
* Added GitHub Actions CI/CD replacing discontinued Travis CI
* Updated ``tox.ini`` for Python 3.10-3.13
* Added comprehensive test coverage (targeting 80%+)
* Removed dead code (unused ``ansi_reserved`` set, unused imports)
* Updated ``.gitignore`` with standard Python entries

Dependencies
~~~~~~~~~~~~

* ``sqlalchemy>=2.0,<3.0``
* ``pyyaml>=6.0,<7.0``
* ``python-dateutil>=2.8,<3.0``
* ``beautifulsoup4>=4.12,<5.0``
* ``requests>=2.28,<3.0``
* ``pymongo>=4.0,<5.0`` (optional, via ``pip install ddl-generator[mongo]``)

Acknowledgments
~~~~~~~~~~~~~~~

This modernization effort was based on a comprehensive codebase review
and addresses all known security vulnerabilities, runtime blockers,
and compatibility issues with modern Python and SQLAlchemy versions.

0.1.0 (2014-03-22)
++++++++++++++++++

* First release on PyPI.

0.1.2 (2014-07-15)
++++++++++++++++++

* ``data_dispenser`` moved to separate module

0.1.3 (2014-07-16)
++++++++++++++++++

* Bugfix for long integers found after short strings

0.1.4 (2014-07-25)
++++++++++++++++++

* Fixed bug: external ``data_dispenser`` unused by 0.1.3!

0.1.5 (2014-07-25)
++++++++++++++++++

* ``sqlalchemy`` pseudo-dialect added

0.1.6 (2014-07-25)
++++++++++++++++++

* Generate sqlalchemy inserts

0.1.7 (2014-09-14)
++++++++++++++++++

* Read via HTTP
* Support HTML format
* Generate Django models

0.1.7.1 (2014-09-14)
++++++++++++++++++++

* Require data-dispenser 0.2.3

0.1.7.3 (2014-10-19)
++++++++++++++++++++

* Require all formerly recommended dependencies, for simplicity
* Several bugfixes for complex number-like fields

0.1.8 (2015-02-01)
++++++++++++++++++

* UNIQUE contstraints handled properly in sqlalchemy output

0.1.8.2 (2015-02-05)
++++++++++++++++++++

* Cleaner SQLAlchemy generation for fixtures

0.1.9 (2015-02-10)
++++++++++++++++++

* README fixes from Anatoly Technonik, Mikhail Podgurskiy
* Parse args passed to ``generate(args, namespace)`` for non-command-line use