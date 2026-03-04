============
Contributing
============

Contributions are welcome, and they are greatly appreciated! Every
little bit helps, and credit will always be given.

You can contribute in many ways:

Types of Contributions
----------------------

Report Bugs
~~~~~~~~~~~

Report bugs at https://github.com/pjbaur/ddl-generator/issues.

If you are reporting a bug, please include:

* The data you were running ddlgenerator on
* Detailed steps to reproduce the bug
* Python version and SQLAlchemy version

Fix Bugs
~~~~~~~~

Look through the GitHub issues for bugs. Anything tagged with "bug"
is open to whoever wants to implement it.

Implement Features
~~~~~~~~~~~~~~~~~~

Look through the GitHub issues for features. Anything tagged with "feature"
is open to whoever wants to implement it.

Write Documentation
~~~~~~~~~~~~~~~~~~~

DDL Generator could always use more documentation, whether as part of the
official DDL Generator docs, in docstrings, or even on the web in blog posts,
articles, and such.

Submit Feedback
~~~~~~~~~~~~~~~

The best way to send feedback is to file an issue at https://github.com/pjbaur/ddl-generator/issues.

If you are proposing a feature:

* Explain in detail how it would work.
* Keep the scope as narrow as possible, to make it easier to implement.
* Remember that this is a volunteer-driven project, and that contributions
  are welcome :)

Get Started!
------------

Ready to contribute? Here's how to set up `ddlgenerator` for local development.

1. Fork the `ddl-generator` repo on GitHub.

2. Clone your fork locally::

    $ git clone git@github.com:your_name_here/ddl-generator.git

3. Create a virtual environment and install development dependencies::

    $ cd ddl-generator
    $ python -m venv .venv
    $ source .venv/bin/activate  # On Windows: .venv\Scripts\activate
    $ pip install -e ".[dev]"

4. Create a branch for local development::

    $ git checkout -b name-of-your-bugfix-or-feature

   Now you can make your changes locally.

5. When you're done making changes, check that your changes pass linting and tests::

    $ ruff check ddlgenerator tests
    $ pytest

   To run tests with coverage::

    $ pytest --cov=ddlgenerator --cov-report=term-missing

   To run tests across all supported Python versions::

    $ tox

6. Commit your changes and push your branch to GitHub::

    $ git add .
    $ git commit -m "Your detailed description of your changes."
    $ git push origin name-of-your-bugfix-or-feature

7. Submit a pull request through the GitHub website.

Pull Request Guidelines
-----------------------

Before you submit a pull request, check that it meets these guidelines:

1. The pull request should include tests.
2. If the pull request adds functionality, the docs should be updated. Put
   your new functionality into a function with a docstring, and add the
   feature to the list in README.rst.
3. The pull request should work for Python 3.10, 3.11, 3.12, and 3.13. Check
   https://github.com/pjbaur/ddl-generator/actions
   and make sure that the tests pass for all supported Python versions.
4. Code coverage should not decrease. Aim for at least 80% coverage.

Code Style
----------

This project uses:

* `ruff <https://docs.astral.sh/ruff/>`_ for linting and formatting
* `mypy <https://mypy.readthedocs.io/>`_ for type checking (optional)

Run linting::

    $ ruff check ddlgenerator tests

Run type checking::

    $ mypy ddlgenerator

Running Tests
-------------

Run all tests::

    $ pytest

Run a specific test file::

    $ pytest tests/test_ddlgenerator.py

Run a specific test::

    $ pytest tests/test_ddlgenerator.py::TestDDLGenerator::test_basic

Run tests with verbose output::

    $ pytest -v

Run tests excluding MongoDB tests (default)::

    $ pytest -m "not mongo"

Run MongoDB tests (requires running MongoDB)::

    $ pytest -m mongo

Project Structure
-----------------

::

    ddlgenerator/           # Main package
      ddlgenerator.py       # Core Table class - type inference, DDL generation
      console.py            # CLI entry point
      reshape.py            # Data reshaping and nested data handling
      typehelpers.py        # Type coercion and analysis
      reserved.py           # SQL reserved words
      url_utils.py          # URL validation and safe fetching
    tests/                  # Unit tests + test data
    docs/                   # Sphinx documentation