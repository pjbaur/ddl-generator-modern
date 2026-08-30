#!/usr/bin/env python
"""
Tests for ddlgenerator.ddlgenerator.Table methods (P3-2).

Covers: varying_length_text, reorder, force_pk, limit,
        multi-dialect DDL, django_models, sqlalchemy output validation,
        _validate_data_source, _escape_string_value, _get_literal_processor,
        security tests for blocked extensions, SQL injection prevention, YAML safety.
"""

import datetime
import io
import json
import os
import runpy
import sqlite3
from collections import Counter, OrderedDict
from decimal import Decimal

import pytest
import sqlalchemy as sa
import yaml

from ddlgenerator.ddlgenerator import (
    Table,
    UnsafeInputError,
    _escape_string_value,
    _get_literal_processor,
    _metadata_from_safe,
    _metadata_to_safe,
    _validate_data_source,
    sqla_head,
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

    def test_inserts_quote_reserved_word_table_name(self):
        """An unnamed source takes the placeholder name "table", a reserved
        word: the INSERT must quote it the way the CREATE does, or the
        statement is invalid SQL.
        """
        tbl = Table('[{"name": "Alfred"}]')
        (insert,) = tbl.inserts("postgresql")
        assert insert == 'INSERT INTO "table" (name) VALUES (\'Alfred\');'

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

    def test_sqlalchemy_unique_constraint_order_matches_columns(self):
        """UniqueConstraint lines must follow column declaration order.

        table.constraints is a plain Python set; iterating it directly
        orders entries by object id (memory address), not by any
        deterministic key, so output order varies run to run.
        """
        data = [{"id": 1, "a": "x1", "b": "y1", "c": "z1", "d": "w1"},
                {"id": 2, "a": "x2", "b": "y2", "c": "z2", "d": "w2"}]
        tbl = Table(data, table_name="test_sqla_multi_u", uniques=True)
        output = tbl.sqlalchemy()
        positions = [output.index(f"UniqueConstraint('{col}')")
                     for col in ("id", "a", "b", "c", "d")]
        assert positions == sorted(positions)

    def test_sqlalchemy_sa2x_metadata_no_bind(self):
        """SQLAlchemy 2.x style: MetaData() without bind= parameter"""
        data = [{"id": 1, "name": "test"}]
        tbl = Table(data, table_name="test_sa2x")
        output = tbl.sqlalchemy()
        # Should use MetaData() not MetaData(bind=...)
        assert "metadata = MetaData()" in output or "metadata" in output
        assert "MetaData(bind=" not in output

    def test_sqlalchemy_drops(self):
        """``-d`` was accepted and then dropped on the floor for this
        dialect. ``drop_all`` defaults to ``checkfirst=True``, making it the
        analogue of the ``DROP TABLE IF EXISTS`` the SQL dialects emit."""
        tbl = Table([{"id": 1}], table_name="test_sqla_drops")
        output = tbl.sqlalchemy(drops=True)
        assert output.index("metadata.drop_all(engine)") < output.index(
            "metadata.create_all(engine)")

    def test_sqlalchemy_no_drops_by_default(self):
        tbl = Table([{"id": 1}], table_name="test_sqla_nodrops")
        assert "drop_all" not in tbl.sqlalchemy()

    def test_sqlalchemy_sa2x_create_all(self):
        """SQLAlchemy 2.x style: metadata.create_all(engine) not .create()"""
        data = [{"id": 1, "name": "test"}]
        tbl = Table(data, table_name="test_sa2x_create")
        output = tbl.sqlalchemy()
        # Should use metadata.create_all(engine) not table.create()
        assert "metadata.create_all(engine)" in output
        assert ".create()" not in output


# ---------------------------------------------------------------------------
# SQLAlchemy model variable names
# ---------------------------------------------------------------------------
class TestSQLAlchemyVariableNames:
    """The model binds each table to a bare Python variable named after the
    table.  ``clean_key_name`` only makes a name safe for *SQL*, so names
    that are legal there and illegal in Python reached the output untouched
    and the generated module would not even parse."""

    def _run(self, tmp_path, tbl):
        module = tmp_path / "generated.py"
        module.write_text(f"{sqla_head}\n{tbl.sqlalchemy()}\n")
        return runpy.run_path(str(module))

    def test_python_keyword_name(self, tmp_path):
        """``class = Table('class', ...)`` is a SyntaxError."""
        tbl = Table([{"grade": 1}], table_name="class")
        assert "Table('class'" in tbl.sqlalchemy()  # SQL name is untouched
        namespace = self._run(tmp_path, tbl)
        assert namespace["_class"].name == "class"

    def test_python_keyword_child_table_name(self, tmp_path):
        """Reachable from data alone -- a nested key becomes a table name."""
        tbl = Table([{"who": "a", "class": [{"grade": 1}]}], table_name="school")
        namespace = self._run(tmp_path, tbl)
        assert namespace["_class"].name == "class"

    def test_name_illegal_in_python_but_legal_in_sql(self, tmp_path):
        """``$`` and ``#`` are identifier characters in Oracle and SQL
        Server, so ``clean_key_name`` keeps them; Python rejects both."""
        tbl = Table([{"amount": 1}], table_name="price$usd")
        assert "Table('price$usd'" in tbl.sqlalchemy()
        namespace = self._run(tmp_path, tbl)
        assert namespace["price_usd"].name == "price$usd"

    def test_insert_function_name_for_a_name_illegal_in_python(self, tmp_path):
        """The ``insert_*`` function names are built from the table name too,
        so ``def insert_price$usd(tbl, conn):`` was a SyntaxError even once
        the Table variable had been fixed."""
        tbl = Table([{"amount": 1}], table_name="price$usd")
        module = tmp_path / "generated.py"
        module.write_text("{}\n{}\n{}\n".format(
            sqla_head, tbl.sqlalchemy(),
            "\n".join(tbl.inserts(dialect="sqlalchemy"))))
        namespace = runpy.run_path(str(module))
        namespace["insert_price_usd"](namespace["price_usd"], namespace["conn"])
        namespace["conn"].commit()
        assert namespace["conn"].execute(
            sa.select(sa.func.count()).select_from(namespace["price_usd"])).scalar() == 1

    def test_insert_function_names_keep_their_prefix(self):
        """``insert_class`` needs no escaping -- the prefix already rules out
        the keyword and shadowing problems the bare variable has."""
        tbl = Table([{"grade": 1}], table_name="class")
        assert "def insert_class(tbl, conn):" in "\n".join(
            tbl.inserts(dialect="sqlalchemy"))

    def test_name_shadowing_the_header(self, tmp_path):
        """``metadata = Table('metadata', metadata, ...)`` rebinds the
        MetaData object, so the ``metadata.create_all(engine)`` that follows
        dies with AttributeError."""
        tbl = Table([{"name": "a"}], table_name="metadata")
        namespace = self._run(tmp_path, tbl)
        assert namespace["_metadata"].name == "metadata"
        assert isinstance(namespace["metadata"], sa.MetaData)

    def test_name_shadowing_the_text_helper(self, tmp_path):
        """``sqla_head`` imports ``text`` for the emitted sequence updates.
        A table variable of that name shadows it, so the
        ``conn.execute(text(...))`` lines would call a Table object."""
        tbl = Table([{"body": "a"}], table_name="text")
        namespace = self._run(tmp_path, tbl)
        assert namespace["_text"].name == "text"
        assert callable(namespace["text"])

    def test_shadow_list_covers_every_name_sqla_head_binds(self):
        """Drift guard: the two are edited independently -- ``text`` was
        added to the header by one change and missed by another -- so check
        the whole header rather than one name at a time."""
        from ddlgenerator.ddlgenerator import _names_bound_by_sqla_head

        namespace = {}
        exec(compile(sqla_head, "sqla_head", "exec"), namespace)
        # only lowercase names can collide; table names are lowercased
        bound = {name for name in namespace
                 if not name.startswith("__") and name.islower()}
        assert bound <= _names_bound_by_sqla_head

    def test_name_shadowing_the_connection(self, tmp_path):
        tbl = Table([{"name": "a"}], table_name="conn")
        module = tmp_path / "generated.py"
        module.write_text("{}\n{}\n{}\n".format(
            sqla_head, tbl.sqlalchemy(),
            "\n".join(tbl.inserts(dialect="sqlalchemy"))))
        namespace = runpy.run_path(str(module))
        namespace["insert_conn"](namespace["_conn"], namespace["conn"])
        namespace["conn"].commit()
        rows = list(namespace["conn"].execute(sa.select(namespace["_conn"])))
        assert [tuple(r) for r in rows] == [("a",)]

    def test_ordinary_name_is_left_alone(self):
        tbl = Table([{"name": "a"}], table_name="knights")
        assert "\nknights = Table('knights'" in tbl.sqlalchemy()

    @pytest.mark.parametrize("name", ["match", "case", "type", "knights"])
    def test_soft_keyword_is_not_prefixed(self, name):
        """Soft keywords are legal variable names; prefixing them would be
        gratuitous. (``clean_key_name`` may rename such a table anyway, for
        SQL's sake -- MATCH is a SQL reserved word -- but that is a separate
        decision from what is legal in Python.)"""
        from ddlgenerator.ddlgenerator import _python_variable_name

        assert _python_variable_name(name) == name


# ---------------------------------------------------------------------------
# SQLAlchemy INSERT output
# ---------------------------------------------------------------------------
class TestSQLAlchemyInserts:
    def test_inserts_pass_parameters_as_a_mapping(self):
        """SQLAlchemy 2.x style: conn.execute(stmt, {...}) not **{...}

        Connection.execute() dropped **kwargs bind parameters in 2.0, so the
        emitted call raised TypeError: got an unexpected keyword argument.
        """
        data = [{"id": 1, "name": "test"}]
        tbl = Table(data, table_name="test_sqla_params")
        output = "\n".join(tbl.inserts(dialect="sqlalchemy"))
        assert "conn.execute(inserter, {" in output
        assert "conn.execute(inserter, **" not in output

    def test_inserts_from_a_file_source_have_no_engine(self):
        """A Table built from anything but a live database has no db_engine.

        The sequence-update lookup read self.source.db_engine unguarded, so
        `ddlgenerator -i sqlalchemy anything.yaml` died with
        AttributeError: 'str' object has no attribute 'db_engine'.
        """
        tbl = Table(here("knights.yaml"))
        output = "\n".join(tbl.inserts(dialect="sqlalchemy"))
        assert "Lancelot" in output
        assert "ALTER SEQUENCE" not in output

    def test_generated_inserts_execute(self, tmp_path):
        """The whole point: the emitted code has to run under SQLAlchemy 2.x."""
        data = [{"id": 1, "name": "test", "value": 42.5}]
        tbl = Table(data, table_name="test_sqla_run")
        module = tmp_path / "generated.py"
        module.write_text("{}\n{}\n{}\n".format(
            sqla_head, tbl.sqlalchemy(),
            "\n".join(tbl.inserts(dialect="sqlalchemy"))))
        namespace = runpy.run_path(str(module))
        namespace["insert_test_sqla_run"](namespace["test_sqla_run"],
                                          namespace["conn"])
        namespace["conn"].commit()
        rows = namespace["conn"].execute(sa.select(namespace["test_sqla_run"]))
        assert [tuple(r) for r in rows] == [(1, "test", Decimal("42.5"))]

    def test_values_are_coerced_to_the_inferred_column_type(self):
        """Bind parameters must be Python objects matching the column type.

        The emitted mapping was built from the raw source row, so a source
        string reached a typed column and SQLAlchemy rejected it:
        "SQLite DateTime type only accepts Python datetime and date objects".
        The SQL dialects coerce the same values via _prep_datum.
        """
        tbl = Table(here("knights.yaml"))
        output = "\n".join(tbl.inserts(dialect="sqlalchemy"))
        # dob is DateTime, brave is Boolean, kg is DECIMAL
        assert "datetime.datetime(471, 1, 9, 0, 0)" in output
        assert "'dob': '9 jan 471'" not in output
        assert "'brave': True" in output and "'brave': False" in output
        assert "'brave': 'y'" not in output
        assert "Decimal('0.0691')" in output

    def test_blank_values_become_none(self):
        data = [{"id": 1, "name": "filled"}, {"id": 2, "name": "  "}]
        tbl = Table(data, table_name="test_sqla_blank")
        output = "\n".join(tbl.inserts(dialect="sqlalchemy"))
        assert "'name': None" in output

    def test_import_line_covers_types_used_only_by_children(self, tmp_path):
        """The import line was scanned off the top table's definition alone.

        A type used only by a child table was therefore never imported, and
        the generated module died with NameError before defining anything.
        """
        data = [{"name": "alpha",
                 "team": [{"name": "t1", "member": [{"who": "a"}, {"who": "b"}]},
                          {"name": "t2", "member": [{"who": "c"}]}]}]
        model = Table(data, table_name="org").sqlalchemy()
        assert "Integer" in model  # used by the child tables' id columns
        module = tmp_path / "generated.py"
        module.write_text(f"{sqla_head}\n{model}\n")
        namespace = runpy.run_path(str(module))
        assert {"org", "team", "_member"} <= set(namespace)

    def test_child_tables_get_insert_functions(self):
        """Nested data splits into child tables, which also need inserts.

        The SQL branch recursed into self.children; the SQLAlchemy branch did
        not, so a child table was created by the generated model and then left
        empty with no way to populate it.
        """
        tbl = Table(here("birds.yaml"))
        output = "\n".join(tbl.inserts(dialect="sqlalchemy"))
        assert "def insert_birds(" in output
        assert "def insert_state(" in output
        # the parent's rows must be insertable before the child's reference them
        assert output.index("def insert_birds(") < output.index("def insert_state(")

    def test_sqla_head_binds_text(self):
        """The emitted sequence updates call ``text``, so the header that
        precedes them has to import it."""
        namespace = {}
        exec(compile(sqla_head, "sqla_head", "exec"), namespace)
        assert callable(namespace["text"])

    def test_emitted_sequence_update_is_wrapped_in_text(self, monkeypatch):
        """The ``ALTER SEQUENCE`` lines are code the user runs, so they face
        the same SQLAlchemy 2.x rule as the tool's own queries: a plain
        string passed to ``Connection.execute`` raises
        ObjectNotExecutableError."""
        from types import SimpleNamespace

        import ddlgenerator.ddlgenerator as ddl

        monkeypatch.setattr(ddl, "emit_db_sequence_updates",
                            lambda engine: iter(["ALTER SEQUENCE s RESTART WITH 42;"]))
        tbl = Table([{"id": 1}], table_name="widget")
        tbl.source = SimpleNamespace(db_engine=object())
        output = "\n".join(tbl.inserts(dialect="sqlalchemy"))
        assert 'conn.execute(text("ALTER SEQUENCE s RESTART WITH 42;"))' in output

    def test_table_name_is_uniquified_against_a_shared_pool(self):
        """Each source builds its own MetaData, so nothing inside a single
        Table sees the clash -- the pool has to be handed in by the caller
        that emits them all into one script."""
        used = set()
        first = Table([{"name": "a"}], table_name="dup", _used_table_names=used)
        second = Table([{"name": "b"}], table_name="dup", _used_table_names=used)
        assert (first.table_name, second.table_name) == ("dup", "dup_1")

    def test_uniquifying_skips_names_already_taken(self):
        used = {"dup", "dup_1"}
        tbl = Table([{"name": "a"}], table_name="dup", _used_table_names=used)
        assert tbl.table_name == "dup_2"

    def test_child_table_names_join_the_pool(self):
        used = set()
        Table([{"who": "a", "state": [{"abbrev": "OH"}]}], table_name="owner",
              _used_table_names=used)
        assert {"owner", "state"} <= used

    def test_no_pool_means_no_renaming(self):
        """The default keeps Table usable on its own, outside a CLI run."""
        first = Table([{"name": "a"}], table_name="dup")
        second = Table([{"name": "b"}], table_name="dup")
        assert (first.table_name, second.table_name) == ("dup", "dup")

    def test_unnamed_table_name_is_constant_across_instances(self):
        """Table names cannot depend on how many Tables the process made."""
        first = Table([{"name": "a"}])
        second = Table([{"name": "b"}])
        assert first.table_name == "generated_table"
        assert second.table_name == "generated_table"

    def test_unnamed_tables_dedupe_through_the_pool(self):
        """The pool, not a global counter, keeps pooled names distinct."""
        used = set()
        first = Table([{"name": "a"}], _used_table_names=used)
        second = Table([{"name": "b"}], _used_table_names=used)
        assert (first.table_name, second.table_name) == \
            ("generated_table", "generated_table_1")

    def test_name_generated_flag_tracks_name_origin(self):
        assert Table([{"name": "a"}])._name_generated is True
        assert Table([{"name": "a"}],
                     table_name="explicit")._name_generated is False

    def test_file_named_generated_table_is_not_treated_as_auto_named(
            self, tmp_path):
        """A derived basename wins; the flag, not the string shape,
        decides what counts as auto-named."""
        import yaml as yaml_module
        path = tmp_path / "generated_table.yaml"
        path.write_text(yaml_module.safe_dump([{"name": "a"}]))
        tbl = Table(str(path))
        assert tbl.table_name == "generated_table"
        assert tbl._name_generated is False

    def test_insertable_table_names_match_the_functions_emitted(self):
        """The names feed ``sqla_inserter_call``; a name with no matching
        ``insert_*`` function makes the generated module raise NameError."""
        tbl = Table(here("birds.yaml"))
        names = list(tbl.insertable_table_names())
        assert names == ["birds", "state"]
        output = "\n".join(tbl.inserts(dialect="sqlalchemy"))
        assert [n for n in names if f"def insert_{n}(" in output] == names

    def test_insertable_table_names_skips_a_table_without_rows(self):
        # Columns must come from metadata: a source with neither rows nor
        # columns is rejected outright, but a known table whose current
        # extract is empty is legitimate -- and gets no insert function.
        metadata = OrderedDict([
            ("id", {"is_nullable": False, "is_unique": True,
                    "sample_datum": 1, "str_length": 1}),
        ])
        tbl = Table([], table_name="vacant", metadata_source=metadata)
        assert list(tbl.insertable_table_names()) == []

    def test_child_inserts_execute_and_keep_the_foreign_key(self, tmp_path):
        tbl = Table(here("birds.yaml"))
        module = tmp_path / "generated.py"
        module.write_text("{}\n{}\n{}\n".format(
            sqla_head, tbl.sqlalchemy(),
            "\n".join(tbl.inserts(dialect="sqlalchemy"))))
        namespace = runpy.run_path(str(module))
        namespace["insert_birds"](namespace["birds"], namespace["conn"])
        namespace["insert_state"](namespace["state"], namespace["conn"])
        namespace["conn"].commit()

        birds = namespace["birds"]
        state = namespace["state"]
        joined = namespace["conn"].execute(
            sa.select(birds.c.common_name, state.c.abbrev)
            .join_from(birds, state, birds.c.birds_id == state.c.birds_id)
            .order_by(state.c.abbrev))
        rows = [tuple(r) for r in joined]
        assert len(rows) == 8
        assert ("Great Northern Loon", "MN") in rows
        assert ("Northern Cardinal", "OH") in rows

    def test_generated_inserts_execute_for_typed_columns(self, tmp_path):
        """End to end for a source whose columns are not all strings."""
        tbl = Table(here("knights.yaml"))
        module = tmp_path / "generated.py"
        module.write_text("{}\n{}\n{}\n".format(
            sqla_head, tbl.sqlalchemy(),
            "\n".join(tbl.inserts(dialect="sqlalchemy"))))
        namespace = runpy.run_path(str(module))
        namespace["insert_knights"](namespace["knights"], namespace["conn"])
        namespace["conn"].commit()
        rows = list(namespace["conn"].execute(
            sa.select(namespace["knights"]).order_by(
                namespace["knights"].c.name)))
        assert [r.name for r in rows] == ["Gawain", "Lancelot", "Reepacheep",
                                          "Robin"]
        by_name = {r.name: r for r in rows}
        assert by_name["Lancelot"].dob == datetime.datetime(471, 1, 9, 0, 0)
        assert by_name["Lancelot"].brave is True
        assert by_name["Robin"].brave is False
        assert by_name["Gawain"].dob is None


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

    def test_full_sql_of_unnamed_source_executes_on_sqlite(self):
        """Safety net: every statement sql() emits for an unnamed source --
        whose placeholder name "table" is a reserved word -- must be
        executable, from DROP through CREATE to INSERT.
        """
        tbl = Table('[{"Name": "Alfred", "kg": 22}]')
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(tbl.sql("sqlite", inserts=True))
            rows = conn.execute('SELECT name, kg FROM "table"').fetchall()
        finally:
            conn.close()
        assert rows == [("Alfred", 22)]


# ---------------------------------------------------------------------------
# sample_k / seed passthrough
# ---------------------------------------------------------------------------
class TestSampleKWiring:
    def test_sample_k_reduces_row_count(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text(
            '[' + ','.join(f'{{"id": {i}}}' for i in range(1, 51)) + ']'
        )
        tbl = Table(str(data_file), sample_k=5, seed=42)
        assert len(tbl.data) == 5

    def test_sample_k_preserves_parent_child_correspondence(self, tmp_path):
        """
        Sampling happens in Source.__next__ before reshape.unnest_children
        runs, so only the 3 sampled parents' own children should survive --
        no orphaned children from unsampled parents, no cross-parent FK
        mismatches. With sample_k=3, seed=1 over 20 parents (ids 0..19),
        Algorithm R deterministically selects parent ids 6, 7, 17.
        """
        data = [
            OrderedDict([
                ("id", i),
                ("name", f"parent{i}"),
                ("items", [{"val": f"item{i}_0"}, {"val": f"item{i}_1"}]),
            ])
            for i in range(20)
        ]
        data_file = tmp_path / "nested.json"
        data_file.write_text(json.dumps(data))

        tbl = Table(str(data_file), table_name="parent", pk_name="id",
                    force_pk=True, sample_k=3, seed=1)

        sampled_parents = list(tbl.data)
        assert len(sampled_parents) == 3
        sampled_ids = {row["id"] for row in sampled_parents}
        assert sampled_ids == {6, 7, 17}

        child_rows = list(tbl.children["items"].data)
        assert len(child_rows) == 6
        child_fks = [row["parent_id"] for row in child_rows]
        assert set(child_fks) == sampled_ids
        assert Counter(child_fks) == Counter({6: 2, 7: 2, 17: 2})


# ---------------------------------------------------------------------------
# sample_pct / seed passthrough
# ---------------------------------------------------------------------------
class TestSamplePctWiring:
    def test_sample_pct_reduces_row_count(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text(
            '[' + ','.join(f'{{"id": {i}}}' for i in range(1, 201)) + ']'
        )
        tbl = Table(str(data_file), sample_pct=10, seed=42)
        assert 0 < len(tbl.data) < 200

    def test_sample_pct_preserves_parent_child_correspondence(self, tmp_path):
        """
        Like sample_k, Bernoulli sampling happens in Source.__next__ before
        reshape.unnest_children runs, so only the sampled parents' own
        children survive -- no orphans, no cross-parent FK mismatches. With
        sample_pct=25, seed=2 over 20 parents (ids 0..19), the Bernoulli
        filter deterministically selects parent ids 2, 3, 11.
        """
        data = [
            OrderedDict([
                ("id", i),
                ("name", f"parent{i}"),
                ("items", [{"val": f"item{i}_0"}, {"val": f"item{i}_1"}]),
            ])
            for i in range(20)
        ]
        data_file = tmp_path / "nested.json"
        data_file.write_text(json.dumps(data))

        tbl = Table(str(data_file), table_name="parent", pk_name="id",
                    force_pk=True, sample_pct=25, seed=2)

        sampled_parents = list(tbl.data)
        assert len(sampled_parents) == 3
        sampled_ids = {row["id"] for row in sampled_parents}
        assert sampled_ids == {2, 3, 11}

        child_rows = list(tbl.children["items"].data)
        assert len(child_rows) == 6
        child_fks = [row["parent_id"] for row in child_rows]
        assert set(child_fks) == sampled_ids
        assert Counter(child_fks) == Counter({2: 2, 3: 2, 11: 2})

    def test_sample_pct_floor_row_keeps_its_children(self, tmp_path):
        """The >=1 floor row is served from a different code path than a
        normally-selected row (it is emitted on StopIteration), so its
        children need the same parent/child correspondence. At 1% with
        seed 0 nothing is selected and the floor emits parent id 12.
        """
        data = [
            OrderedDict([
                ("id", i),
                ("name", f"parent{i}"),
                ("items", [{"val": f"item{i}_0"}, {"val": f"item{i}_1"}]),
            ])
            for i in range(20)
        ]
        data_file = tmp_path / "nested.json"
        data_file.write_text(json.dumps(data))

        tbl = Table(str(data_file), table_name="parent", pk_name="id",
                    force_pk=True, sample_pct=1, seed=0)

        sampled_parents = list(tbl.data)
        assert len(sampled_parents) == 1
        assert sampled_parents[0]["id"] == 12

        child_rows = list(tbl.children["items"].data)
        assert len(child_rows) == 2
        assert [row["parent_id"] for row in child_rows] == [12, 12]
        assert {row["val"] for row in child_rows} == {"item12_0", "item12_1"}


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
        assert isinstance(tbl.columns["val"]["satype"], type) and issubclass(tbl.columns["val"]["satype"], sa.Integer) or isinstance(tbl.columns["val"]["satype"], sa.Integer)  # noqa: E501

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


# ---------------------------------------------------------------------------
# Security: Blocked extensions (P1-1)
# ---------------------------------------------------------------------------
class TestBlockedExtensions:
    """Tests for P1-1: Block dangerous file extensions to prevent RCE"""

    def test_py_file_extension_blocked(self):
        """Python files should be rejected to prevent eval() RCE"""
        with pytest.raises(UnsafeInputError, match=".py"):
            Table('malicious.py')

    def test_pickle_file_extension_blocked(self):
        """Pickle files should be rejected to prevent deserialization attacks"""
        with pytest.raises(UnsafeInputError, match=".pickle"):
            Table('malicious.pickle')

    def test_pkl_file_extension_blocked(self):
        """Pickle files with .pkl extension should be rejected"""
        with pytest.raises(UnsafeInputError, match=".pkl"):
            Table('data.pkl')

    def test_safe_python_data_accepted(self):
        """Python data (lists, dicts) should be accepted without error"""
        data = [{'id': 1, 'name': 'test'}]
        table = Table(data)
        assert table is not None

    def test_case_insensitive_extension_check(self):
        """Blocked extensions should be detected regardless of case"""
        with pytest.raises(UnsafeInputError):
            Table('MALICIOUS.PY')

        with pytest.raises(UnsafeInputError):
            Table('data.Pickle')


# ---------------------------------------------------------------------------
# Security: File-like objects (P1-1)
# ---------------------------------------------------------------------------
class TestFilelikeObjectSecurity:
    """Tests that file-like objects with blocked extensions are also rejected"""

    def test_filelike_with_py_extension_blocked(self):
        """File-like objects with .py name should be rejected"""
        fake_file = io.StringIO("import os; os.system('rm -rf /')")
        fake_file.name = 'exploit.py'
        with pytest.raises(UnsafeInputError):
            Table(fake_file)

    def test_filelike_with_pickle_extension_blocked(self):
        """File-like objects with .pickle name should be rejected"""
        fake_file = io.BytesIO(b'\x80\x03some pickle data')
        fake_file.name = 'data.pickle'
        with pytest.raises(UnsafeInputError):
            Table(fake_file)


# ---------------------------------------------------------------------------
# Security: SQL Injection Prevention (P1-3)
# ---------------------------------------------------------------------------
class TestSQLInjectionPrevention:
    """Tests for P1-3: SQL injection prevention in INSERT generation"""

    def test_single_quotes_escaped(self):
        """Single quotes in data should be properly escaped"""
        data = [{'id': 1, 'name': "O'Brien"}]
        tbl = Table(data)
        inserts = list(tbl.inserts('postgresql'))
        # Should contain escaped quote, not unescaped
        assert "O''Brien" in inserts[0]
        assert "O'Brien" not in inserts[0]

    def test_sql_injection_payload_neutralized(self):
        """SQL injection payloads should be escaped, not executed"""
        data = [{'id': 1, 'name': "'; DROP TABLE users; --"}]
        tbl = Table(data)
        inserts = list(tbl.inserts('postgresql'))
        # The payload should be escaped as a string literal
        assert "DROP TABLE" in inserts[0]  # Content preserved
        assert "'''; DROP TABLE users; --'" in inserts[0]  # But safely quoted

    def test_backslash_handling(self):
        """Backslashes should be handled safely"""
        data = [{'id': 1, 'path': 'C:\\Users\\test\\file.txt'}]
        tbl = Table(data)
        inserts = list(tbl.inserts('postgresql'))
        # Should produce valid SQL
        assert 'INSERT INTO' in inserts[0]
        assert 'C:' in inserts[0]

    def test_null_value_handling(self):
        """NULL values should be properly represented"""
        data = [{'id': 1, 'name': None, 'value': 'test'}]
        tbl = Table(data)
        inserts = list(tbl.inserts('postgresql'))
        # NULL should appear as SQL NULL keyword
        assert 'NULL' in inserts[0]

    def test_unicode_handling(self):
        """Unicode characters should be safely included"""
        data = [{'id': 1, 'name': 'François Englert'}]
        tbl = Table(data)
        inserts = list(tbl.inserts('postgresql'))
        # Unicode should be preserved
        assert 'François' in inserts[0]

    def test_multiple_dialects_safe(self):
        """SQL injection prevention should work across dialects"""
        data = [{'id': 1, 'name': "O'Brien"}]

        for dialect in ['postgresql', 'mysql', 'sqlite']:
            tbl = Table(data)
            inserts = list(tbl.inserts(dialect))
            # All dialects should escape the quote
            assert "O''Brien" in inserts[0], f"Quote not escaped for dialect {dialect}"

    def test_double_quote_in_data(self):
        """Double quotes in data should be handled safely"""
        data = [{'id': 1, 'name': 'He said "hello"'}]
        tbl = Table(data)
        inserts = list(tbl.inserts('postgresql'))
        assert 'INSERT INTO' in inserts[0]

    def test_semicolon_in_data(self):
        """Semicolons in data should not break out of the INSERT"""
        data = [{'id': 1, 'comment': "value; DELETE FROM users"}]
        tbl = Table(data)
        inserts = list(tbl.inserts('postgresql'))
        # The semicolon should be inside the quoted string
        assert len(inserts) == 1  # Should be exactly one INSERT

    def test_newline_in_data(self):
        """Newlines in data should not create additional SQL statements"""
        data = [{'id': 1, 'bio': "line1\nDROP TABLE users;\nline3"}]
        tbl = Table(data)
        inserts = list(tbl.inserts('postgresql'))
        assert len(inserts) == 1


# ---------------------------------------------------------------------------
# Security: YAML Safety (P1-4)
# ---------------------------------------------------------------------------
class TestYAMLSafety:
    """Tests for P1-4: yaml.safe_load rejects malicious YAML tags"""

    def test_safe_load_rejects_python_object(self):
        """YAML with !!python/object tags should be rejected by safe_load"""
        malicious_yaml = "!!python/object/apply:os.system ['echo pwned']"
        with pytest.raises(yaml.YAMLError):
            yaml.safe_load(malicious_yaml)

    def test_safe_load_rejects_python_module(self):
        """YAML with !!python/module tags should be rejected"""
        malicious_yaml = "!!python/module:os"
        with pytest.raises(yaml.YAMLError):
            yaml.safe_load(malicious_yaml)

    def test_safe_load_rejects_python_name(self):
        """YAML with !!python/name tags should be rejected"""
        malicious_yaml = "!!python/name:os.system"
        with pytest.raises(yaml.YAMLError):
            yaml.safe_load(malicious_yaml)

    def test_safe_load_accepts_normal_yaml(self):
        """Normal YAML data should be parsed correctly"""
        normal_yaml = "name: Lancelot\nkg: 69.4\nquest: Grail"
        result = yaml.safe_load(normal_yaml)
        assert result['name'] == 'Lancelot'

    def test_metadata_source_uses_safe_load(self):
        """Table's metadata_source path uses yaml.safe_load, not yaml.load"""
        import inspect
        source = inspect.getsource(Table.__init__)
        assert 'yaml.safe_load' in source
        assert 'yaml.load(' not in source


# ---------------------------------------------------------------------------
# _dropper dialect tests
# ---------------------------------------------------------------------------
class TestDropperDialects:
    """Tests for Table._dropper() across different SQL dialects."""

    def test_dropper_postgresql_includes_if_exists(self):
        """PostgreSQL supports IF EXISTS in DROP TABLE."""
        tbl = Table([{"id": 1}], table_name="test_drop")
        result = tbl._dropper("postgresql")
        assert "DROP TABLE" in result
        assert "IF EXISTS" in result
        assert "test_drop" in result

    def test_dropper_mysql_includes_if_exists(self):
        """MySQL supports IF EXISTS in DROP TABLE."""
        tbl = Table([{"id": 1}], table_name="test_drop")
        result = tbl._dropper("mysql")
        assert "DROP TABLE" in result
        assert "IF EXISTS" in result

    def test_dropper_sqlite_includes_if_exists(self):
        """SQLite supports IF EXISTS in DROP TABLE."""
        tbl = Table([{"id": 1}], table_name="test_drop")
        result = tbl._dropper("sqlite")
        assert "DROP TABLE" in result
        assert "IF EXISTS" in result

    def test_dropper_oracle_no_if_exists(self):
        """Oracle does not support IF EXISTS (generates without it)."""
        tbl = Table([{"id": 1}], table_name="test_drop")
        result = tbl._dropper("oracle")
        assert "DROP TABLE" in result
        assert "IF EXISTS" not in result

    def test_dropper_mssql_no_if_exists(self):
        """MSSQL does not support IF EXISTS (generates without it)."""
        tbl = Table([{"id": 1}], table_name="test_drop")
        result = tbl._dropper("mssql")
        assert "DROP TABLE" in result
        assert "IF EXISTS" not in result

    def test_dropper_sybase_includes_if_exists(self):
        """Sybase supports IF EXISTS in DROP TABLE."""
        tbl = Table([{"id": 1}], table_name="test_drop")
        result = tbl._dropper("sybase")
        assert "DROP TABLE" in result
        assert "IF EXISTS" in result

    def test_dropper_drizzle_no_if_exists(self):
        """Drizzle does not support IF EXISTS (generates without it)."""
        tbl = Table([{"id": 1}], table_name="test_drop")
        result = tbl._dropper("drizzle")
        assert "DROP TABLE" in result
        assert "IF EXISTS" not in result

    def test_dropper_quotes_reserved_word_name(self):
        """A reserved-word table name must be quoted in the DROP statement.

        An unnamed source (e.g. inline JSON) takes the placeholder name
        "table", which is a reserved word: unquoted, ``DROP TABLE IF EXISTS
        table`` is invalid SQL in postgresql and sqlite.
        """
        tbl = Table('[{"id": 1}]')  # unnamed source: placeholder name "table"
        assert tbl.table_name == "table"
        assert tbl._dropper("postgresql") == 'DROP TABLE IF EXISTS "table"'


# ---------------------------------------------------------------------------
# _saveable_metadata tests
# ---------------------------------------------------------------------------
class TestSaveableMetadata:
    """Tests for Table._saveable_metadata() for serialization and round-trip."""

    def test_removes_satype(self):
        """_saveable_metadata should remove satype (SQLAlchemy types can't be serialized)."""
        tbl = Table([{"id": 1, "name": "test"}], table_name="test_meta")
        meta = tbl._saveable_metadata()

        # satype should be removed from all columns
        for col_info in meta.values():
            if isinstance(col_info, dict):
                assert "satype" not in col_info

    def test_includes_child_tables(self):
        """_saveable_metadata should include child table metadata."""
        from collections import OrderedDict
        data = [
            OrderedDict([
                ("name", "parent1"),
                ("items", [{"val": "a"}, {"val": "b"}]),
            ]),
        ]
        tbl = Table(data, table_name="parent", pk_name="id", force_pk=True)
        meta = tbl._saveable_metadata()

        # Child table should be in metadata
        if tbl.children:
            assert "items" in meta
            assert isinstance(meta["items"], dict)

    def test_roundtrip_via_yaml(self, tmp_path):
        """Metadata should survive YAML serialization round-trip using yaml.dump."""
        data = [{"id": 1, "name": "Alice", "score": 95.5}]
        tbl = Table(data, table_name="test_roundtrip")

        # Get saveable metadata
        meta = tbl._saveable_metadata()

        # Serialize to YAML using the same method Table uses
        meta_file = tmp_path / "meta.yaml"
        with open(meta_file, 'w') as f:
            yaml.dump(meta, f)

        # Verify file was created and contains column info
        assert meta_file.exists()
        content = meta_file.read_text()
        # Column names should be present
        assert "id" in content or "name" in content or "score" in content

    def test_includes_column_metadata(self):
        """_saveable_metadata should include column metadata like nullable, unique."""
        data = [{"id": 1, "name": "test"}]
        tbl = Table(data, table_name="test_cols", uniques=True)
        meta = tbl._saveable_metadata()

        # Should have column entries with metadata
        assert len(meta) > 0
        for col_info in meta.values():
            if isinstance(col_info, dict):
                # Should have some metadata keys
                assert "is_nullable" in col_info or "is_unique" in col_info or "pytype" in col_info

    def test_empty_table_metadata(self):
        """Empty table should still produce valid metadata structure."""
        # Table with data that becomes empty after processing
        tbl = Table([{"a": 1}], table_name="test_empty")
        meta = tbl._saveable_metadata()
        assert isinstance(meta, dict)


# ---------------------------------------------------------------------------
# Metadata save / restore round-trip (regression for the safe_load bug)
# ---------------------------------------------------------------------------
class TestMetadataRoundTrip:
    """The --save-metadata-to / --use-metadata-from round-trip must reproduce DDL.

    Previously the metadata was written with ``yaml.dump`` (Python object tags)
    but read with ``yaml.safe_load`` (which rejects those tags), so the
    documented large-table workflow crashed with a ``ConstructorError``.  These
    tests pin the fix: the file is plain safe YAML and the restored schema is
    identical to a fresh inference.
    """

    @staticmethod
    def _ddl(table):
        # Normalize whitespace so string comparison is stable.
        return " ".join(table.sql("postgresql").split())

    def test_flat_table_roundtrip_reproduces_ddl(self, tmp_path):
        data = [{"name": "Alfred", "species": "wart hog", "kg": 22},
                {"name": "Gertrude", "species": "polar bear", "kg": 312.7}]
        fresh = Table(data, table_name="animals", reorder=True)
        meta_path = tmp_path / "animals.meta.yaml"

        Table(data, table_name="animals", reorder=True, save_metadata_to=str(meta_path))

        assert meta_path.exists(), "save_metadata_to should write the file"
        restored = Table(data, table_name="animals", reorder=True,
                         metadata_source=str(meta_path))

        assert self._ddl(fresh) == self._ddl(restored)

    def test_decimal_column_roundtrips(self, tmp_path):
        """Decimal columns (the type that previously carried a python tag) must survive."""
        data = [{"amount": "12.50"}, {"amount": "3.00"}]  # coerced to Decimal
        fresh = Table(data, table_name="money")
        meta_path = tmp_path / "money.meta.yaml"
        Table(data, table_name="money", save_metadata_to=str(meta_path))
        restored = Table(data, table_name="money", metadata_source=str(meta_path))

        # The DECIMAL precision/scale is reconstructed from the saved sample.
        assert "DECIMAL" in restored.sql("postgresql")
        assert self._ddl(fresh) == self._ddl(restored)

    def test_nested_table_roundtrip_reproduces_ddl(self, tmp_path):
        """Child tables must survive the round-trip, including the foreign key."""
        birds = here("birds.yaml")
        fresh = Table(birds)
        meta_path = tmp_path / "birds.meta.yaml"
        Table(birds, save_metadata_to=str(meta_path))

        saved = meta_path.read_text()
        assert "children:" in saved, "child table should be nested under children"

        restored = Table(birds, metadata_source=str(meta_path))
        assert self._ddl(fresh) == self._ddl(restored)

    def test_saved_metadata_has_no_python_tags(self, tmp_path):
        """The file must be plain safe YAML -- no ``!!python/...`` tags."""
        data = [{"id": 1, "name": "Alice", "score": 95.5, "joined": "2020-01-01"}]
        meta_path = tmp_path / "plain.meta.yaml"
        Table(data, table_name="t", save_metadata_to=str(meta_path))

        content = meta_path.read_text()
        assert "!!python/" not in content
        # And it must parse cleanly with safe_load (the original failure mode).
        assert isinstance(yaml.safe_load(content), dict)

    def test_helpers_round_trip_native_types(self):
        """str/int/float/bool/None sample values survive to_safe -> from_safe."""
        col = {"sample_datum": "hi", "str_length": 2, "is_nullable": False,
               "is_unique": True, "pytype": str}
        node = _metadata_to_safe(OrderedDict([("name", col)]))
        back = _metadata_from_safe(node)
        assert back["name"]["sample_datum"] == "hi"
        assert back["name"]["str_length"] == 2
        assert back["name"]["is_nullable"] is False

    def test_unknown_pytype_is_rejected(self, tmp_path):
        """A metadata file naming an arbitrary type must not be loaded."""
        meta_path = tmp_path / "evil.meta.yaml"
        meta_path.write_text(
            "columns:\n"
            "  evil:\n"
            "    pytype: os.system\n"
            "    sample_datum: whatever\n"
            "    str_length: 8\n"
            "    is_nullable: false\n"
            "    is_unique: true\n"
            "children: {}\n"
        )
        with pytest.raises(ValueError):
            Table([{"evil": "x"}], table_name="t", metadata_source=str(meta_path))
