#!/usr/bin/env python
"""
test_ddlgenerator
----------------------------------

Tests for `ddlgenerator` module - file loading, MongoDB, sequence updates.
Consolidated and migrated to pytest style as part of Phase 5.
"""

import contextlib
import glob
import io
import os.path
from collections import OrderedDict, namedtuple

import pytest

try:
    import pymongo
except ImportError:
    pymongo = None

try:
    from ddlgenerator.ddlgenerator import Table, emit_db_sequence_updates
except ImportError:
    from ddlgenerator import Table, emit_db_sequence_updates


def here(filename):
    return os.path.join(os.path.dirname(__file__), filename)


# ---------------------------------------------------------------------------
# MongoDB tests
# ---------------------------------------------------------------------------
@pytest.mark.mongo
@pytest.mark.skipif(pymongo is None, reason="pymongo not installed")
class TestMongo:
    """Tests for MongoDB as a data source."""

    @pytest.fixture(autouse=True)
    def setup_mongo(self, request):
        data = [{'year': 2013,
                 'physics': ['François Englert', 'Peter W. Higgs'],
                 'chemistry': ['Martin Karplus', 'Michael Levitt', 'Arieh Warshel'],
                 'peace': ['Organisation for the Prohibition of Chemical Weapons (OPCW)',],
                 },
                {'year': 2011,
                 'physics': ['Saul Perlmutter', 'Brian P. Schmidt', 'Adam G. Riess'],
                 'chemistry': ['Dan Shechtman',],
                 'peace': ['Ellen Johnson Sirleaf', 'Leymah Gbowee', 'Tawakkol Karman'],
                 },
                ]
        self.data = data
        self.client = None
        self.db = None
        self.tbl = None

        try:
            self.client = pymongo.MongoClient(serverSelectionTimeoutMS=2000)
            self.client.server_info()  # Force connection check
            self.db = self.client.ddlgenerator_test_db
            self.tbl = self.db.prize_winners
            self.tbl.insert_many(self.data)
        except (pymongo.errors.ConnectionFailure, pymongo.errors.OperationFailure,
                pymongo.errors.ServerSelectionTimeoutError) as e:
            # Clean up any partial connection before skipping
            if self.client is not None:
                try:
                    self.client.close()
                except Exception:
                    pass
            pytest.skip(f"MongoDB not available: {e}")

        yield

        # Teardown - only runs if setup succeeded
        if self.client is not None and self.db is not None:
            try:
                self.client.drop_database(self.db)
            except Exception:
                pass
            try:
                self.client.close()
            except Exception:
                pass

    def test_data(self):
        winners = Table(self.tbl, pk_name='year')
        generated = winners.sql('postgresql', inserts=True)
        assert 'REFERENCES prize_winners (year)' in generated


# ---------------------------------------------------------------------------
# Raw Python data tests
# ---------------------------------------------------------------------------
class TestFromRawPythonData:
    """Tests for Python data structures as input."""

    prov_type = namedtuple('province', ['name', 'capital', 'pop'])
    canada = [prov_type('Quebec', 'Quebec City', '7903001'),
              prov_type('Ontario', 'Toronto', '12851821'), ]

    merovingians = [
        OrderedDict([('name', {'name_id': 1, 'name_txt': 'Clovis I'}),
                     ('reign', {'from': 486, 'to': 511}),
                     ]),
        OrderedDict([('name', {'name_id': 1, 'name_txt': 'Childebert I'}),
                     ('reign', {'from': 511, 'to': 558}),
                     ]),
    ]

    def test_pydata_named_tuples(self):
        tbl = Table(self.canada)
        generated = tbl.sql('postgresql', inserts=True).strip()
        assert 'capital VARCHAR(11) NOT NULL,' in generated
        assert "(name, capital, pop) VALUES ('Quebec', 'Quebec City', 7903001)" in generated

    def test_nested(self):
        tbl = Table(self.merovingians)
        generated = tbl.sql('postgresql', inserts=True).strip()
        assert "reign_to" in generated

    def test_django(self):
        tbl = Table(self.merovingians)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            tbl.django_models()
        generated = output.getvalue()
        assert "models.Model" in generated
        assert "name_name_id" in generated


# ---------------------------------------------------------------------------
# Sequence update tests
# ---------------------------------------------------------------------------
class TestZeroColumnSource:
    """A source yielding no columns must fail clearly, not emit invalid DDL."""

    def test_empty_list_raises(self):
        with pytest.raises(ValueError, match="no columns"):
            Table([], table_name='t0')

    def test_all_empty_rows_raise(self):
        with pytest.raises(ValueError, match="no columns"):
            Table([{}, {}], table_name='t1')

    def test_error_names_the_table(self):
        with pytest.raises(ValueError, match="t2"):
            Table([], table_name='t2')


class TestSequenceUpdates:
    """Tests for emit_db_sequence_updates - P0-3 fixes"""

    def test_emit_db_sequence_updates_postgresql_only(self):
        """Sequence updates should only be generated for PostgreSQL engines"""
        from unittest.mock import MagicMock, Mock

        # Mock a PostgreSQL engine
        mock_result = MagicMock()
        mock_result.first.return_value = (100,)

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = [
            [('SELECT last_value FROM public.my_seq;', 'public.my_seq',)],  # First query: get sequences
            mock_result  # Second query: get last_value
        ]

        mock_engine = Mock()
        mock_engine.name = 'postgresql'
        mock_engine.connect.return_value = mock_conn

        # Get the sequence updates
        updates = list(emit_db_sequence_updates(mock_engine))

        # Verify correct SQL was generated with both sequence name and nextval
        assert len(updates) == 1
        assert 'ALTER SEQUENCE public.my_seq RESTART WITH 101;' in updates[0]

    def test_emit_db_sequence_updates_non_postgresql(self):
        """Sequence updates should not be generated for non-PostgreSQL engines"""
        from unittest.mock import Mock

        # Mock a non-PostgreSQL engine (e.g., sqlite)
        mock_engine = Mock()
        mock_engine.name = 'sqlite'

        # Should yield nothing for non-PostgreSQL
        updates = list(emit_db_sequence_updates(mock_engine))
        assert len(updates) == 0

    def test_emit_db_sequence_updates_no_engine(self):
        """Sequence updates should not be generated when no engine is present"""
        updates = list(emit_db_sequence_updates(None))
        assert len(updates) == 0

    def test_emit_db_sequence_updates_runs_on_a_real_connection(self, tmp_path):
        """The tests above pass a MagicMock connection, which accepts any
        argument at all -- so they hid a real API break: SQLAlchemy 2.x
        rejects a plain string passed to ``Connection.execute``, and every
        PostgreSQL source run with ``-i`` died with ObjectNotExecutableError.

        Stand the catalog tables the query reads up in SQLite so a real
        Connection can be used without a live PostgreSQL server.
        """
        import sqlalchemy as sa

        engine = sa.create_engine(f"sqlite:///{tmp_path / 'fake_pg.db'}")
        with engine.begin() as setup:
            setup.execute(sa.text("CREATE TABLE pg_namespace (oid INTEGER, nspname TEXT)"))
            setup.execute(sa.text(
                "CREATE TABLE pg_class (relnamespace INTEGER, relname TEXT, relkind TEXT)"))
            setup.execute(sa.text("CREATE TABLE widget_id_seq (last_value INTEGER)"))
            setup.execute(sa.text("INSERT INTO pg_namespace VALUES (1, 'main')"))
            setup.execute(sa.text("INSERT INTO pg_class VALUES (1, 'widget_id_seq', 'S')"))
            setup.execute(sa.text("INSERT INTO widget_id_seq VALUES (41)"))

        class PostgresNamedEngine:
            name = 'postgresql'

            def connect(self):
                return engine.connect()

        updates = list(emit_db_sequence_updates(PostgresNamedEngine()))
        assert updates == ['ALTER SEQUENCE main.widget_id_seq RESTART WITH 42;']


# ---------------------------------------------------------------------------
# File-based tests
# ---------------------------------------------------------------------------
class TestFiles:
    """Tests for loading data from various file formats."""

    def test_use_open_file(self):
        with open(here('knights.yaml')) as infile:
            knights = Table(infile)
            generated = knights.sql('postgresql', inserts=True)
            assert 'Lancelot' in generated

    def test_files(self):
        """Test all file formats against their expected SQL output."""
        blocked_extensions = {'.py', '.pyw', '.pickle', '.pkl'}
        for sql_fname in glob.glob(here('*.sql')):
            with open(sql_fname) as infile:
                expected = infile.read().strip()
            (fname, ext) = os.path.splitext(sql_fname)
            for source_fname in glob.glob(here(f'{fname}.*')):
                (fname, ext) = os.path.splitext(source_fname)
                if ext != '.sql' and ext not in blocked_extensions:
                    tbl = Table(source_fname, uniques=True)
                    generated = tbl.sql('postgresql', inserts=True, drops=True).strip()
                    assert generated == expected


# ---------------------------------------------------------------------------
# sqla_inserter_call tests
# ---------------------------------------------------------------------------
class TestSqlaInserterCall:
    """Tests for sqla_inserter_call function."""

    def test_generates_function_definition(self):
        """Should generate insert_test_rows function."""
        from ddlgenerator.ddlgenerator import sqla_inserter_call

        result = sqla_inserter_call(["users"])
        assert "def insert_test_rows" in result
        assert "meta" in result
        assert "conn" in result

    def test_includes_all_table_names(self):
        """Should include all table names in the generated function."""
        from ddlgenerator.ddlgenerator import sqla_inserter_call

        table_names = ["users", "orders", "products"]
        result = sqla_inserter_call(table_names)

        for name in table_names:
            assert f"insert_{name}" in result
            assert f"meta.tables['{name}']" in result

    def test_empty_list_generates_empty_function_body(self):
        """Empty table list should generate function with no table insert calls."""
        from ddlgenerator.ddlgenerator import sqla_inserter_call

        result = sqla_inserter_call([])
        assert "def insert_test_rows" in result
        # Should have function definition but no insert_ calls for specific tables
        # (The function name contains "insert_" but there should be no insert_tablename calls)
        assert "meta.tables" not in result

    def test_single_table_format(self):
        """Single table should generate correct insert call."""
        from ddlgenerator.ddlgenerator import sqla_inserter_call

        result = sqla_inserter_call(["my_table"])
        assert "insert_my_table(meta.tables['my_table'], conn)" in result

    def test_name_illegal_in_python_is_escaped_in_the_call_only(self):
        """``$`` is an identifier character in Oracle and SQL Server, so it
        survives into the table name; the function name it builds has to drop
        it, while the lookup key keeps the real SQL name."""
        from ddlgenerator.ddlgenerator import sqla_inserter_call

        result = sqla_inserter_call(["price$usd"])
        assert "insert_price_usd(meta.tables['price$usd'], conn)" in result

    def test_docstring_included(self):
        """Generated function should include docstring."""
        from ddlgenerator.ddlgenerator import sqla_inserter_call

        result = sqla_inserter_call(["users"])
        assert '"""' in result
        assert "test data" in result.lower() or "populate" in result.lower()

    def test_generated_function_defines_without_error(self):
        """The emitted code is plain Python, so it must not use names the
        generated module never imports.

        A blanket annotation pass put `meta: Any, conn: Any` in this template;
        `Any` is not in scope where the code lands, so loading the generated
        module raised NameError before any insert could run.
        """
        from ddlgenerator.ddlgenerator import sqla_head, sqla_inserter_call

        module = (f"{sqla_head}\n"
                  "def insert_users(tbl, conn): pass\n"
                  f"{sqla_inserter_call(['users'])}")
        namespace: dict = {}
        exec(compile(module, "<generated>", "exec"), namespace)
        assert callable(namespace["insert_test_rows"])

    def test_commits_after_inserting(self):
        """SQLAlchemy 2.0 dropped autocommit, so the rows need an explicit commit."""
        from ddlgenerator.ddlgenerator import sqla_inserter_call

        result = sqla_inserter_call(["users"])
        lines = [line for line in result.splitlines() if line.strip()]
        assert lines[-1].strip() == "conn.commit()"
        assert lines[-2].strip() == "insert_users(meta.tables['users'], conn)"
