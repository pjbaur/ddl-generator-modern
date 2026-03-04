# DDL Generator

Python tool that infers SQL DDL (CREATE TABLE statements) from table data. Supports multiple SQL dialects, SQLAlchemy models, and Django ORM models.

**Repository:** Fork of `catherinedevlin/ddl-generator` (upstream). Main branch: `master`.

## Project Structure

```
ddlgenerator/           # Main package
  ddlgenerator.py       # Core Table class - type inference, DDL generation
  console.py            # CLI entry point (ddlgenerator command)
  reshape.py            # Data reshaping and nested data handling
  typehelpers.py        # Type coercion and analysis
  reserved.py           # SQL reserved words
tests/                  # Unit tests + test data (yaml, json, csv, xls, html)
docs/                   # Sphinx documentation
```

## Development

```bash
# Install from source
pip3 install -e .

# Run tests
python setup.py test
# or
python -m unittest tests.test_ddlgenerator
# or
nosetests

# Run with tox (multiple Python versions)
tox

# Coverage
coverage run --source ddlgenerator setup.py test
coverage report -m

# Lint
flake8 ddlgenerator
```

## CLI Usage

```bash
ddlgenerator postgresql mydata.yaml          # Generate DDL
ddlgenerator -i postgresql mydata.json       # With INSERT statements
ddlgenerator sqlalchemy mydata.yaml          # SQLAlchemy models
ddlgenerator django mydata.yaml              # Django models
```

## Key Dependencies

- sqlalchemy, pyyaml, python-dateutil, beautifulsoup4, requests, data_dispenser

## Architecture Notes

- `Table` class (ddlgenerator.py) is the core — it analyzes data, infers column types, detects child tables from nested structures, and generates SQL via SQLAlchemy's DDL compiler.
- Data input is abstracted through the `data_dispenser` package (files, URLs, Python objects, MongoDB).
- SQL dialect support uses SQLAlchemy mock engines.
