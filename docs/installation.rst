============
Installation
============

Requirements
============

- Python 3.10 or higher
- SQLAlchemy 2.0 or higher

From PyPI
=========

At the command line::

    $ pip install ddl-generator

With virtual environment (recommended)::

    $ python -m venv .venv
    $ source .venv/bin/activate  # On Windows: .venv\Scripts\activate
    $ pip install ddl-generator

Optional Dependencies
=====================

For MongoDB support::

    $ pip install ddl-generator[mongo]

From Source
===========

.. code-block:: bash

    $ git clone https://github.com/catherinedevlin/ddl-generator.git
    $ cd ddl-generator
    $ pip install .

For development::

    $ pip install -e ".[dev]"

Development Dependencies
========================

Install development dependencies for contributing::

    $ pip install -e ".[dev]"

This includes:

- pytest, pytest-cov - testing
- ruff, flake8 - linting
- mypy - type checking
- tox - multi-version testing