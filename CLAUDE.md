# DDL Generator

Python tool that infers SQL DDL (CREATE TABLE statements) from table data. Supports multiple SQL dialects, SQLAlchemy models, and Django ORM models.

**Repository:** Fork of `catherinedevlin/ddl-generator` (upstream). Main branch: `main`.

## Project Structure

```
ddlgenerator/           # Main package
  ddlgenerator.py       # Core Table class - type inference, DDL generation
  console.py            # CLI entry point (ddlgenerator command)
  reshape.py            # Data reshaping and nested data handling
  typehelpers.py        # Type coercion and analysis
  reserved.py           # SQL reserved words
  sources.py            # Data source loading (files, URLs, Python objects)
  url_utils.py          # URL validation and safe fetching (SSRF protection)
tests/                  # Unit tests + test data (yaml, json, csv, xls, html)
docs/                   # Sphinx documentation
```

## Development

```bash
# Create the project virtualenv and install from source.
# mise auto-activates .venv on cd (see .mise.toml); without mise,
# run `source .venv/bin/activate` first.
uv venv .venv -p 3.12
uv pip install -e ".[dev,mongo]"

# Run tests
pytest

# Run with tox (multiple Python versions)
tox

# Coverage
pytest --cov=ddlgenerator --cov-report=term-missing

# Lint
ruff check ddlgenerator tests
flake8 ddlgenerator tests
```

W503 (line break before binary operator) is ignored in `.flake8`
(ruff never implements W503/W504, so nothing to set there). It
contradicts its sibling W504 (break after operator) — both can't be
satisfied at once, and PEP 8 now prefers break-before-operator, so
W503 is the one to disable.

## CLI Usage

```bash
ddlgenerator postgresql mydata.yaml          # Generate DDL
ddlgenerator -i postgresql mydata.json       # With INSERT statements
ddlgenerator sqlalchemy mydata.yaml          # SQLAlchemy models
ddlgenerator django mydata.yaml              # Django models
```

## Key Dependencies

- sqlalchemy (2.0+), pyyaml, python-dateutil, beautifulsoup4, requests, xlrd

## Architecture Notes

- `Table` class (ddlgenerator.py) is the core — it analyzes data, infers column types, detects child tables from nested structures, and generates SQL via SQLAlchemy's DDL compiler.
- Data input is handled through `sources.py` (files, URLs, Python objects, MongoDB) with SSRF protection via `url_utils.py`.
- SQL dialect support uses SQLAlchemy mock engines.
- Security: No pickle support, uses yaml.safe_load(), URL validation for SSRF prevention, SQL injection prevention in INSERT generation.
