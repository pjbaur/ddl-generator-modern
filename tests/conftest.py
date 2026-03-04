"""Shared pytest fixtures and configuration for ddlgenerator tests."""

import os
import pytest

try:
    import pymongo
except ImportError:
    pymongo = None

# Monkey-patch data_dispenser's _open to fix removed 'rU' file mode on Python 3.12+
try:
    import data_dispenser.sources as _ds_sources
    _ds_original_open = _ds_sources._open

    def _patched_open(filename):
        return open(filename, 'r')

    _ds_sources._open = _patched_open
except (ImportError, AttributeError):
    pass


@pytest.fixture
def here():
    """Return a function that resolves paths relative to the tests directory."""
    def _here(filename):
        return os.path.join(os.path.dirname(__file__), filename)
    return _here


@pytest.fixture(autouse=True)
def reset_table_index():
    """Reset Table.table_index before each test for deterministic table names."""
    from ddlgenerator.ddlgenerator import Table
    Table.table_index = 0
    yield
    Table.table_index = 0


@pytest.fixture
def table_class():
    """Provide the Table class, handling import variations."""
    try:
        from ddlgenerator.ddlgenerator import Table
        return Table
    except ImportError:
        from ddlgenerator import Table
        return Table
