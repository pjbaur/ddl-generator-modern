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
# Install from source
pip install -e ".[dev]"

# Run tests
pytest

# Run with tox (multiple Python versions)
tox

# Coverage
pytest --cov=ddlgenerator --cov-report=term-missing

# Lint
ruff check ddlgenerator tests
flake8 ddlgenerator tests --max-line-length=120 --ignore=E501,W503
```

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
