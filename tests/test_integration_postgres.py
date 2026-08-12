"""Integration tests against a real PostgreSQL server.

The server is provisioned with testcontainers, so Docker must be running.
When Docker, testcontainers, or psycopg2 is missing, the whole module
skips and plain ``pytest`` stays green -- unless
``DDLGEN_PG_INTEGRATION_REQUIRED=1`` is set (the CI escalation switch),
in which case every would-be skip becomes a failure so the CI job can
never pass by silently skipping.

The first test to touch the container pays image-pull plus startup
(seconds when the image is cached); run ``pytest -m "not postgres"`` to
avoid that during quick local loops.
"""
import io
import itertools
import os
import runpy

import pytest
import sqlalchemy as sa

try:
    try:
        from testcontainers.community.postgres import PostgresContainer
    except ImportError:  # testcontainers < 4.15 has no community namespace
        from testcontainers.postgres import PostgresContainer
except ImportError:
    PostgresContainer = None

try:
    import psycopg2  # noqa: F401  # bare postgresql:// URLs resolve to psycopg2
except ImportError:
    psycopg2 = None

from ddlgenerator.console import generate
from ddlgenerator.ddlgenerator import emit_db_sequence_updates
from ddlgenerator.sources import count_sqlalchemy_tables, sqlalchemy_table_sources

REQUIRED = os.environ.get("DDLGEN_PG_INTEGRATION_REQUIRED") == "1"

pytestmark = pytest.mark.postgres


def _unavailable(reason):
    """Skip the module -- or, under the CI escalation switch, refuse to."""
    if REQUIRED:
        raise RuntimeError(
            "DDLGEN_PG_INTEGRATION_REQUIRED=1 but PostgreSQL integration "
            f"tests cannot run: {reason}")
    pytest.skip(reason, allow_module_level=True)


if PostgresContainer is None:
    _unavailable("testcontainers not installed (pip install -e '.[integration]')")
if psycopg2 is None:
    _unavailable("psycopg2 not installed (pip install -e '.[postgres]')")


def _fail_or_skip(reason):
    """Function-scope counterpart of :func:`_unavailable`.

    Raises a plain error rather than calling ``pytest.fail`` so that under
    the escalation switch even xfail-marked tests report as errors instead
    of being absorbed as expected failures.
    """
    if REQUIRED:
        raise RuntimeError(
            f"DDLGEN_PG_INTEGRATION_REQUIRED=1 but: {reason}")
    pytest.skip(reason)


@pytest.fixture(scope="session")
def pg_container():
    try:
        from testcontainers.core.docker_client import DockerClient
        DockerClient().client.ping()
    except Exception as e:
        _fail_or_skip(f"Docker not available: {e}")
    # driver=None makes get_connection_url() return a bare postgresql://
    # URL -- the form CLI users type, which SQLAlchemy serves with psycopg2.
    container = PostgresContainer("postgres:16-alpine", driver=None)
    try:
        container.start()
    except Exception as e:
        _fail_or_skip(f"could not start PostgreSQL container: {e}")
    yield container
    container.stop()


@pytest.fixture(scope="session")
def pg_admin_engine(pg_container):
    # CREATE DATABASE cannot run inside a transaction block.
    engine = sa.create_engine(pg_container.get_connection_url(),
                              isolation_level="AUTOCOMMIT")
    yield engine
    engine.dispose()


_db_counter = itertools.count()


@pytest.fixture
def pg_db_factory(pg_admin_engine, pg_container):
    """Mint fresh databases: each call returns (bare URL, seeding engine).

    The databases are never dropped: the code under test leaks
    connections that sit idle-in-transaction (Source never closes the
    connection it reads from), which would block a DROP.  The session
    container is discarded wholesale instead.
    """
    engines = []

    def make():
        name = f"it_{next(_db_counter)}"
        with pg_admin_engine.connect() as conn:
            conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
        url = pg_container.get_connection_url().rsplit("/", 1)[0] + f"/{name}"
        engine = sa.create_engine(url)
        engines.append(engine)
        return url, engine

    yield make
    for engine in engines:
        engine.dispose()


@pytest.fixture
def pg_db(pg_db_factory):
    """A fresh database for the test: (bare postgresql:// URL, engine)."""
    return pg_db_factory()


def _seed(engine, *statements):
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(sa.text(statement))


class TestSqlAlchemyTableSources:
    """sqlalchemy_table_sources reflecting and reading a live database."""

    def test_yields_one_source_per_table_in_fk_order(self, pg_db):
        url, engine = pg_db
        _seed(engine,
              "CREATE TABLE parent (id integer PRIMARY KEY)",
              "CREATE TABLE child (id integer PRIMARY KEY,"
              " parent_id integer REFERENCES parent(id))",
              "INSERT INTO parent VALUES (1)",
              "INSERT INTO child VALUES (1, 1)")

        sources = list(sqlalchemy_table_sources(url))

        assert [s.table_name for s in sources] == ["parent", "child"]

    def test_source_rows_round_trip(self, pg_db):
        url, engine = pg_db
        _seed(engine,
              "CREATE TABLE knights (id integer, name text)",
              "INSERT INTO knights VALUES (1, 'Lancelot'), (2, 'Galahad'),"
              " (3, 'Robin')")

        sources = list(sqlalchemy_table_sources(url))

        rows = list(sources[0])
        assert [tuple(row.values()) for row in rows] == [
            (1, "Lancelot"), (2, "Galahad"), (3, "Robin")]

    def test_limit_applies_per_table(self, pg_db):
        url, engine = pg_db
        _seed(engine,
              "CREATE TABLE t (id integer)",
              "INSERT INTO t SELECT generate_series(1, 20)")

        sources = list(sqlalchemy_table_sources(url, limit=5))

        assert len(list(sources[0])) == 5


class TestCountSqlAlchemyTables:
    """count_sqlalchemy_tables issuing SELECT count(*) against live tables."""

    def test_counts_all_tables_without_reading_rows(self, pg_db):
        url, engine = pg_db
        _seed(engine,
              "CREATE TABLE t1 (id integer)",
              "CREATE TABLE t2 (id integer)",
              "INSERT INTO t1 SELECT generate_series(1, 7)",
              "INSERT INTO t2 SELECT generate_series(1, 3)")

        assert sorted(count_sqlalchemy_tables(url)) == [("t1", 7), ("t2", 3)]

    def test_counts_single_named_table(self, pg_db):
        url, engine = pg_db
        _seed(engine,
              "CREATE TABLE t1 (id integer)",
              "CREATE TABLE t2 (id integer)",
              "INSERT INTO t1 SELECT generate_series(1, 7)")

        assert count_sqlalchemy_tables(url, table="t1") == [("t1", 7)]


class TestSequenceUpdates:
    """emit_db_sequence_updates against real pg_catalog tables.

    Until now this function was only ever tested against SQLite tables
    dressed up as pg_namespace/pg_class (test_ddlgenerator.py), because it
    only runs for a live PostgreSQL engine.
    """

    def test_used_sequence_restarts_past_max(self, pg_db):
        url, engine = pg_db
        _seed(engine,
              "CREATE TABLE widgets (id serial PRIMARY KEY, name text)",
              "INSERT INTO widgets (name) VALUES ('a'), ('b'), ('c')")

        updates = list(emit_db_sequence_updates(sa.create_engine(url)))

        assert updates == ["ALTER SEQUENCE public.widgets_id_seq RESTART WITH 4;"]

    def test_fresh_sequence_is_not_skipped_past_one(self, pg_db):
        """A never-used sequence reports last_value=1 with is_called=false,
        so its next nextval() is 1 -- but the code emits last_value + 1
        unconditionally, skipping id 1 on the rebuilt database."""
        url, engine = pg_db
        _seed(engine, "CREATE TABLE widgets (id serial PRIMARY KEY, name text)")

        updates = list(emit_db_sequence_updates(sa.create_engine(url)))

        assert updates == ["ALTER SEQUENCE public.widgets_id_seq RESTART WITH 1;"]

    def test_enumerates_sequences_in_all_visible_schemas(self, pg_db):
        """Characterization, not endorsement: the pg_class query is not
        filtered by schema or by the tables being generated, so every
        visible sequence is emitted -- other schemas' and orphans'
        included."""
        url, engine = pg_db
        _seed(engine,
              "CREATE SCHEMA other",
              "CREATE TABLE widgets (id serial PRIMARY KEY)",
              "CREATE TABLE other.gadgets (id serial PRIMARY KEY)",
              "CREATE SEQUENCE orphan_seq",
              "INSERT INTO widgets DEFAULT VALUES",
              "INSERT INTO other.gadgets DEFAULT VALUES")

        updates = list(emit_db_sequence_updates(sa.create_engine(url)))

        touched = {u.split()[2] for u in updates}
        assert touched == {"public.widgets_id_seq", "other.gadgets_id_seq",
                           "public.orphan_seq"}


class TestCliAgainstLivePostgres:
    """The console's SQLAlchemy-URL branch, end to end."""

    def test_generate_postgresql_dialect_end_to_end(self, pg_db):
        url, engine = pg_db
        _seed(engine,
              "CREATE TABLE knights (id serial PRIMARY KEY, name text)",
              "INSERT INTO knights (name) VALUES ('Lancelot'), ('Galahad')")
        out = io.StringIO()

        generate(f"-i postgresql {url}", file=out)

        output = out.getvalue()
        assert "CREATE TABLE knights" in output
        assert "'Lancelot'" in output
        assert "'Galahad'" in output
        assert ("ALTER SEQUENCE public.knights_id_seq RESTART WITH 3;"
                in output)

    def test_reflected_column_types_are_preserved(self, pg_db):
        """Rows from a live database keep their declared types: the
        reflected schema rides on Source.sqla_columns, so a bigint stays a
        bigint no matter what its values look like (issue #28; before the
        fix, bigint 1 came back BOOLEAN and a timestamp VARCHAR(19))."""
        url, engine = pg_db
        _seed(engine,
              "CREATE TABLE measures (big bigint, price numeric(12, 4),"
              " label text, seen timestamp)",
              "INSERT INTO measures VALUES"
              " (1, 1.50, 'ab', '2026-01-02 03:04:05')")
        out = io.StringIO()

        generate(f"postgresql {url}", file=out)

        output = out.getvalue()
        assert "big BIGINT" in output
        assert "price NUMERIC(12, 4)" in output
        assert "label TEXT" in output
        assert "seen TIMESTAMP" in output

    def test_count_only_reports_live_counts(self, pg_db):
        url, engine = pg_db
        _seed(engine,
              "CREATE TABLE t1 (id integer)",
              "CREATE TABLE t2 (id integer)",
              "INSERT INTO t1 SELECT generate_series(1, 7)",
              "INSERT INTO t2 SELECT generate_series(1, 3)")
        out = io.StringIO()

        generate(f"--count-only postgresql {url}", file=out)

        output = out.getvalue()
        assert "t1: 7" in output
        assert "t2: 3" in output
        assert "TOTAL: 10" in output

    def test_sample_k_applies_to_live_source(self, pg_db):
        url, engine = pg_db
        _seed(engine,
              "CREATE TABLE t (id integer)",
              "INSERT INTO t SELECT generate_series(1, 50)")
        out = io.StringIO()

        generate(f"--sample-k 5 --seed 1 -i postgresql {url}", file=out)

        assert out.getvalue().count("INSERT INTO t ") == 5

    def test_generated_sqlalchemy_module_round_trips_without_sequences(
            self, pg_db, pg_db_factory, tmp_path):
        """The module generated from a live database rebuilds and
        repopulates a fresh one, as long as the source has no sequences
        (see the xfail below for why serial columns break this)."""
        url, engine = pg_db
        _seed(engine,
              "CREATE TABLE knights (id integer, name text)",
              "INSERT INTO knights VALUES (1, 'Lancelot'), (2, 'Galahad')")
        out = io.StringIO()

        generate(f"-i sqlalchemy {url}", file=out)

        target_url, _ = pg_db_factory()
        module = tmp_path / "generated.py"
        module.write_text(out.getvalue().replace("sqlite:///:memory:",
                                                 target_url))
        namespace = runpy.run_path(str(module))
        try:
            namespace["insert_test_rows"](namespace["metadata"],
                                          namespace["conn"])
            count = namespace["conn"].execute(
                sa.select(sa.func.count()).select_from(namespace["knights"])
            ).scalar()
        finally:
            namespace["conn"].close()
            namespace["engine"].dispose()
        assert count == 2

    def test_generated_sqlalchemy_module_round_trips_serial_source(
            self, pg_db, pg_db_factory, tmp_path):
        """A module generated from a source with a serial column should
        rebuild a fresh database too -- the ALTER SEQUENCE updates ride
        inside ``insert_test_rows``, so they run against whatever the
        module's engine points at (a PostgreSQL target here; the default
        sqlite:///:memory: header could never execute them at all)."""
        url, engine = pg_db
        _seed(engine,
              "CREATE TABLE knights (id serial PRIMARY KEY, name text)",
              "INSERT INTO knights (name) VALUES ('Lancelot'), ('Galahad')")
        out = io.StringIO()

        generate(f"-i sqlalchemy {url}", file=out)

        output = out.getvalue()
        assert 'conn.execute(text("ALTER SEQUENCE' in output

        target_url, _ = pg_db_factory()
        module = tmp_path / "generated.py"
        module.write_text(output.replace("sqlite:///:memory:", target_url))
        namespace = runpy.run_path(str(module))
        conn = namespace["conn"]
        try:
            namespace["insert_test_rows"](namespace["metadata"], conn)
            count = conn.execute(
                sa.select(sa.func.count()).select_from(namespace["knights"])
            ).scalar()
            assert count == 2
            # the sequence update took effect: the next id continues past
            # the copied rows instead of colliding with them
            assert conn.execute(
                sa.text("SELECT nextval('knights_id_seq')")).scalar() == 3
        finally:
            # close even on the expected failure -- pytest keeps the
            # traceback (and with it this frame) alive until interpreter
            # exit, long after the container is gone
            conn.close()
            namespace["engine"].dispose()
