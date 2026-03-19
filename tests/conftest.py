"""Shared pytest fixtures and configuration for ddlgenerator tests."""

import os
import pytest

try:
    import pymongo
except ImportError:
    pymongo = None


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


@pytest.fixture(autouse=True)
def reset_source_table_count():
    """Reset Source.table_count before each test for deterministic table names."""
    from ddlgenerator.sources import Source
    Source.table_count = 0
    yield
    Source.table_count = 0
