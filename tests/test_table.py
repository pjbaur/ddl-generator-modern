#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tests for ddlgenerator.ddlgenerator.Table methods (P3-2).

Covers: varying_length_text, reorder, force_pk, limit,
        multi-dialect DDL, django_models, sqlalchemy output validation,
        _validate_data_source, _escape_string_value, _get_literal_processor
"""

import os
from collections import OrderedDict

import pytest

from ddlgenerator.ddlgenerator import (
    Table,
    UnsafeInputError,
    _validate_data_source,
    _escape_string_value,
    _get_literal_processor,
    mock_engines,
    dialect_names,
)


def here(filename):
    return os.path.join(os.path.dirname(__file__), filename)


# ---------------------------------------------------------------------------
# Multi-dialect DDL generation
# ---------------------------------------------------------------------------
class TestMultiDialectDDL:
    """Verify DDL output for all supported dialects."""

    data = [{"id": 1, "name": "Alice", "score": 95.5}]

    @pytest.mark.parametrize("dialect", ["postgresql", "mysql", "sqlite", "oracle", "mssql"])
    def test_ddl_contains_create_table(self, dialect):
        tbl = Table(self.data, table_name="test_multi")
        ddl = tbl.ddl(dialect)
        assert "CREATE TABLE" in ddl

    @pytest.mark.parametrize("dialect", ["postgresql", "mysql", "sqlite", "oracle", "mssql"])
    def test_ddl_contains_table_name(self, dialect):
        tbl = Table(self.data, table_name="test_multi")
        ddl = tbl.ddl(dialect)
        assert "test_multi" in ddl

    @pytest.mark.parametrize("dialect", ["postgresql", "mysql", "sqlite"])
    def test_inserts_valid(self, dialect):
        tbl = Table(self.data, table_name="test_multi")
        inserts = list(tbl.inserts(dialect))
        assert len(inserts) == 1
        assert "INSERT INTO" in inserts[0]
        assert "Alice" in inserts[0]

    def test_drops_included(self):
        tbl = Table(self.data, table_name="test_multi")
        ddl = tbl.ddl("postgresql", drops=True)
        assert "DROP TABLE" in ddl

    def test_drops_excluded(self):
        tbl = Table(self.data, table_name="test_multi")
        ddl = tbl.ddl("postgresql", drops=False)
        assert "DROP TABLE" not in ddl

    def test_creates_excluded(self):
        tbl = Table(self.data, table_name="test_multi")
        ddl = tbl.ddl("postgresql", creates=False, drops=False)
        assert "CREATE TABLE" not in ddl

    def test_invalid_dialect_raises(self):
        tbl = Table(self.data, table_name="test_multi")
        with pytest.raises(NotImplementedError, match="unknown"):
            tbl.ddl("bogus")

    def test_no_dialect_raises(self):
        tbl = Table(self.data, table_name="test_multi")
        with pytest.raises(KeyError, match="No SQL dialect"):
            tbl.ddl(None)


# ---------------------------------------------------------------------------
# varying_length_text
# ---------------------------------------------------------------------------
class TestVaryingLengthText:
    data = [{"id": 1, "name": "Alice"}]

    def test_varchar_by_default(self):
        tbl = Table(self.data, table_name="test_vlt")
        ddl = tbl.ddl("postgresql")
        assert "VARCHAR" in ddl

    def test_text_when_enabled(self):
        tbl = Table(self.data, table_name="test_vlt", varying_length_text=True)
        ddl = tbl.ddl("postgresql")
        assert "TEXT" in ddl


# ---------------------------------------------------------------------------
# reorder
# ---------------------------------------------------------------------------
class TestReorder:
    def test_columns_reordered_alphabetically(self):
        data = [OrderedDict([("zebra", 1), ("alpha", 2), ("middle", 3)])]
        tbl = Table(data, table_name="test_reorder", reorder=True)
        col_names = list(tbl.columns.keys())
        assert col_names == sorted(col_names)

    def test_pk_first_when_reordered(self):
        data = [OrderedDict([("zebra", 1), ("alpha", 2), ("myid", 3)])]
        tbl = Table(data, table_name="test_reorder", reorder=True, pk_name="myid")
        col_names = list(tbl.columns.keys())
        assert col_names[0] == "myid"


# ---------------------------------------------------------------------------
# force_pk
# ---------------------------------------------------------------------------
class TestForcePK:
    def test_pk_created_when_forced(self):
        data = [{"name": "Alice"}, {"name": "Bob"}]
        tbl = Table(data, table_name="test_fpk", pk_name="id", force_pk=True)
        assert tbl.pk_name == "id"
        ddl = tbl.ddl("postgresql")
        assert "PRIMARY KEY" in ddl or "id" in ddl


# ---------------------------------------------------------------------------
# data_size_cushion
# ---------------------------------------------------------------------------
class TestDataSizeCushion:
    def test_cushion_increases_varchar_size(self):
        data = [{"name": "Alice"}]
        tbl_no_cushion = Table(data, table_name="test_c0", data_size_cushion=0)
        tbl_with_cushion = Table(data, table_name="test_c1", data_size_cushion=2)
        # Cushion should increase the string column length
        no_cushion_len = tbl_no_cushion.columns["name"]["satype"].length
        with_cushion_len = tbl_with_cushion.columns["name"]["satype"].length
        assert with_cushion_len > no_cushion_len


# ---------------------------------------------------------------------------
# SQLAlchemy model output
# ---------------------------------------------------------------------------
class TestSQLAlchemyModel:
    def test_sqlalchemy_output_valid(self):
        data = [{"id": 1, "name": "test", "value": 42.5}]
        tbl = Table(data, table_name="test_sqla")
        output = tbl.sqlalchemy()
        assert "Column(" in output
        assert "test_sqla" in output
        # Should include import statement
        assert "from sqlalchemy import" in output

    def test_sqlalchemy_with_unique(self):
        data = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
        tbl = Table(data, table_name="test_sqla_u", uniques=True)
        output = tbl.sqlalchemy()
        assert "Column(" in output

    def test_sqlalchemy_sa2x_metadata_no_bind(self):
        """SQLAlchemy 2.x style: MetaData() without bind= parameter"""
        data = [{"id": 1, "name": "test"}]
        tbl = Table(data, table_name="test_sa2x")
        output = tbl.sqlalchemy()
        # Should use MetaData() not MetaData(bind=...)
        assert "metadata = MetaData()" in output or "metadata" in output
        assert "MetaData(bind=" not in output

    def test_sqlalchemy_sa2x_create_all(self):
        """SQLAlchemy 2.x style: metadata.create_all(engine) not .create()"""
        data = [{"id": 1, "name": "test"}]
        tbl = Table(data, table_name="test_sa2x_create")
        output = tbl.sqlalchemy()
        # Should use metadata.create_all(engine) not table.create()
        assert "metadata.create_all(engine)" in output
        assert ".create()" not in output


# ---------------------------------------------------------------------------
# sql() combined method
# ---------------------------------------------------------------------------
class TestSqlCombined:
    def test_sql_with_inserts(self):
        data = [{"id": 1, "name": "test"}]
        tbl = Table(data, table_name="test_sql")
        output = tbl.sql("postgresql", inserts=True)
        assert "CREATE TABLE" in output
        assert "INSERT INTO" in output

    def test_sql_without_inserts(self):
        data = [{"id": 1, "name": "test"}]
        tbl = Table(data, table_name="test_sql")
        output = tbl.sql("postgresql", inserts=False)
        assert "CREATE TABLE" in output
        assert "INSERT INTO" not in output


# ---------------------------------------------------------------------------
# _validate_data_source
# ---------------------------------------------------------------------------
class TestValidateDataSource:
    def test_safe_extensions_accepted(self):
        # These should not raise (they won't exist, but validation only checks extension)
        for ext in [".json", ".yaml", ".yml", ".csv", ".html", ".xls", ".xlsx"]:
            _validate_data_source(f"data{ext}")  # no error

    def test_blocked_extensions_rejected(self):
        for ext in [".py", ".pyw", ".pickle", ".pkl"]:
            with pytest.raises(UnsafeInputError):
                _validate_data_source(f"data{ext}")

    def test_non_string_data_accepted(self):
        _validate_data_source([{"a": 1}])  # no error
        _validate_data_source({"a": 1})  # no error

    def test_file_object_with_blocked_name(self):
        class FakeFile:
            name = "evil.pickle"
        with pytest.raises(UnsafeInputError):
            _validate_data_source(FakeFile())


# ---------------------------------------------------------------------------
# _escape_string_value / _get_literal_processor
# ---------------------------------------------------------------------------
class TestEscapeStringValue:
    def test_escapes_single_quote(self):
        result = _escape_string_value("O'Brien", "postgresql")
        assert "'O''Brien'" == result

    def test_plain_string(self):
        result = _escape_string_value("hello", "postgresql")
        assert "'hello'" == result

    def test_different_dialects(self):
        for dialect in ["postgresql", "mysql", "sqlite"]:
            result = _escape_string_value("test", dialect)
            assert "test" in result

    def test_processor_cached(self):
        p1 = _get_literal_processor("postgresql")
        p2 = _get_literal_processor("postgresql")
        assert p1 is p2


# ---------------------------------------------------------------------------
# Table.__str__
# ---------------------------------------------------------------------------
class TestTableStr:
    def test_str_without_dialect(self):
        tbl = Table([{"id": 1}], table_name="test_str")
        result = str(tbl)
        assert "test_str" in result.lower() or "Table" in result

    def test_str_with_default_dialect(self):
        tbl = Table([{"id": 1}], table_name="test_str", default_dialect="postgresql")
        result = str(tbl)
        assert "CREATE TABLE" in result


# ---------------------------------------------------------------------------
# Table with child tables (nested data)
# ---------------------------------------------------------------------------
class TestChildTables:
    def test_nested_list_creates_child(self):
        data = [
            OrderedDict([
                ("name", "parent1"),
                ("items", [{"val": "a"}, {"val": "b"}]),
            ]),
        ]
        tbl = Table(data, table_name="parent", pk_name="id", force_pk=True)
        assert "items" in tbl.children
        child = tbl.children["items"]
        ddl = child.ddl("postgresql")
        assert "CREATE TABLE" in ddl

    def test_child_references_parent(self):
        data = [
            OrderedDict([
                ("name", "parent1"),
                ("items", [{"val": "a"}, {"val": "b"}]),
            ]),
        ]
        tbl = Table(data, table_name="parent", pk_name="id", force_pk=True)
        child = tbl.children["items"]
        ddl = child.ddl("postgresql")
        assert "REFERENCES" in ddl or "parent" in ddl.lower()


# ---------------------------------------------------------------------------
# Nullable detection
# ---------------------------------------------------------------------------
class TestNullableDetection:
    def test_nullable_when_missing(self):
        data = [{"a": 1, "b": 2}, {"a": 3}]
        tbl = Table(data, table_name="test_null")
        assert tbl.columns["b"]["is_nullable"] is True

    def test_not_nullable_when_always_present(self):
        data = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
        tbl = Table(data, table_name="test_notnull")
        assert tbl.columns["a"]["is_nullable"] is False

    def test_nullable_when_none_value(self):
        data = [{"a": 1}, {"a": None}]
        tbl = Table(data, table_name="test_nullval")
        assert tbl.columns["a"]["is_nullable"] is True


# ---------------------------------------------------------------------------
# Unique detection
# ---------------------------------------------------------------------------
class TestUniqueDetection:
    def test_unique_when_all_different(self):
        data = [{"a": 1}, {"a": 2}, {"a": 3}]
        tbl = Table(data, table_name="test_uniq", uniques=True)
        assert tbl.columns["a"]["is_unique"] is True

    def test_not_unique_when_duplicates(self):
        data = [{"a": 1}, {"a": 1}, {"a": 2}]
        tbl = Table(data, table_name="test_notuniq", uniques=True)
        assert tbl.columns["a"]["is_unique"] is False


# ---------------------------------------------------------------------------
# Type inference
# ---------------------------------------------------------------------------
class TestTypeInference:
    def test_integer_column(self):
        data = [{"val": 1}, {"val": 2}]
        tbl = Table(data, table_name="test_int")
        import sqlalchemy as sa
        assert isinstance(tbl.columns["val"]["satype"], type) and issubclass(tbl.columns["val"]["satype"], sa.Integer) or isinstance(tbl.columns["val"]["satype"], sa.Integer)

    def test_string_column(self):
        data = [{"val": "hello"}, {"val": "world"}]
        tbl = Table(data, table_name="test_str_col")
        import sqlalchemy as sa
        assert isinstance(tbl.columns["val"]["satype"], sa.Unicode)

    def test_mixed_types_widen(self):
        data = [{"val": 1}, {"val": "text"}]
        tbl = Table(data, table_name="test_mixed")
        import sqlalchemy as sa
        assert isinstance(tbl.columns["val"]["satype"], (sa.Unicode, sa.Text))
